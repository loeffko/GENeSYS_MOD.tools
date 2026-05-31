# GIS & Timeseries Tool — working notes

Generates renewable capacity-factor timeseries (PV, onshore/offshore wind, heat-pump
COP / heating / cooling) and GIS-based renewable **potentials** (utility PV, onshore
wind, rooftop PV, offshore wind) for GENeSYS-MOD, from ERA5 weather + land-cover /
protected-area / bathymetry layers. Built on [atlite](https://atlite.readthedocs.io).

All logic lives in `functions.py`; the notebooks are thin drivers that set
region-specific paths/parameters and call those functions.

## Layout

- `functions.py` — all functions (~1500 lines). Edit here, not in the notebooks.
- `GENeSYS-MOD_RES_Tool_example.ipynb` — small, self-contained Germany example for git (tiny cutout, no large exclusion layers). The shareable reference.
- `GENeSYS-MOD_RES_Tool_US.ipynb`, `..._CA.ipynb`, `..._DE.ipynb` — full regional setups. Large; depend on big local `geodata/` layers, NOT pushed to git.
- `geodata/` — input layers (region polygons, land cover, protected areas, EEZ, bathymetry). Big rasters/GDBs live here; keep it to files the notebooks reference.
- `cutouts/` — atlite ERA5 cutouts (`.nc`) + `era5_cache/` (raw CDS download cache). Large, git-ignored.
- `solarpanel/` — PV module configs (`CSi.yaml`, `CdTe.yaml`, `KANENA.yaml`).
- `windturbines/` — turbine power-curve configs (referenced by `onshore_turbine`/`offshore_turbine`).
- `output/` — generated CSVs + figures.

## Core design principle: region-agnostic functions

`functions.py` contains **no country-specific logic**. Regional specifics (region
polygons, land-cover raster + its class codes, protected-area files, capacity
densities, depth thresholds) are all passed in as arguments from the notebook. The
same code runs any region. When adding a feature, keep it parameterised — do not
hardcode a CRS, class code, file path, or region name in `functions.py`.

Two coordinate workflows, auto-selected by `get_coords` from the geo_file columns:
- **region-geojson**: geo_file has a `region` column → `get_region_shapes`, `_get_coords_custom`. Offshore via an EEZ file + bathymetry.
- **country/ISO** (original): geo_file has `iso_a2`/`iso_3166_2` (natural-earth admin1) → `gis_get_country_geometry`. `admin=0` country level, `admin=1` states.

## Typical pipeline (per notebook)

1. Set turbines/panel, `geo_file`, `offshore_file`, `bathymetry_file`, `timeframe`, `filename`, `regions`, `dx_step`/`dy_step`.
2. `estimate_cutout_size(...)` — print grid size BEFORE downloading.
3. `get_cutout(...)` — download/prepare the ERA5 cutout (cached; see resilience below).
4. `get_coords(...)` → `coords_onshore`, `coords_offshore`.
5. Capacity factors: `pv_capacity_factors`, `wind_onshore_capacity_factors`, `wind_offshore_capacity_factors`, `temperature_timeseries`.
6. GIS potentials: build excluders (`make_land_excluder`, `make_rooftop_excluder`), then `calculate_potentials_per_region` (memory-safe, all regions) **or** the per-region `calculate_and_plot_available_*` + `calculate_capacity_potentials` cells.
7. Usable-site CF timeseries + offshore potential + maps.

## Cutout download resilience (already built in)

`get_cutout` monkeypatches `atlite.datasets.era5.retrieve_data` (`_retrieve_data_cached`)
to cache each CDS chunk in `cutouts/era5_cache/` keyed by request hash. An
interrupted/failed run **reuses** cached chunks instead of re-downloading. It also
deletes a corrupt/all-NaN cutout and rebuilds (`_cutout_has_data`).

**Environment gotcha (Windows):** large cutout `.nc` writes can freeze at "99%
Completed" because Windows Defender real-time scan locks the multi-GB file during the
HDF5 close. This is NOT a code bug. Fix once, per machine:
`Add-MpPreference -ExclusionPath "...\GIS_&_Timeseries_Tool\cutouts"` (admin
PowerShell). Smaller cutouts also avoid it. See the auto-memory note
`project_res_tool_cutout_write_freeze` for detail.

## GIS potentials — key functions

- `get_region_shapes(geo_file, regions)` — onshore region polygons (region workflow).
- `make_land_excluder(raster, exclude_codes, raster_crs=, raster_nodata=, protected_files=, protected_layer=, protected_query=, protected_buffer=)` — utility PV / onshore wind land availability.
- `make_rooftop_excluder(raster, developed_codes, ...)` — rooftop proxy (keeps only built-up classes via `invert=True`).
- `calculate_potentials_per_region(...)` — **memory-safe**: processes one region at a time so atlite only rasterizes the land-cover raster over a single region's bbox (the whole-extent rasterization is what exhausts RAM at 30 m). Writes per-region + combined CSVs, returns `(combined_df, stitched_land, stitched_rooftop, coords_onshore_usable, coords_rooftop_usable, coords_offshore_usable)`. Stitched availability maps with area-weighted headline %.
- `calculate_capacity_potentials(...)` — single-pass version (all regions at once; can exhaust RAM on big extents).
- `calculate_offshore_potentials(...)` — offshore wind per region + depth class, reuses EEZ+depth `coords_offshore`.
- `usable_onshore_coords` / `usable_offshore_coords` — filter cutout cells to developable sites, feed into the CF functions for "usable sites only" timeseries.
- `plot_offshore_map`, `equal_area_crs`.

`pv_capacity_factors(..., tech_label=, optimal_tilt=)`: `tech_label` renames output
files (e.g. `pv_rooftop`) without changing the opt/avg/inf split; `optimal_tilt=True`
uses a cheap per-cell latitude rule for tilt (not a per-angle yield search).

## Adding a new region

1. Make a region geojson (a `region` column for the region-geojson workflow) or use country ISO codes for the country workflow.
2. Get the regional data layers: a land-cover raster (note its class codes + CRS), a protected-areas file, and — for offshore — an EEZ polygon + a bathymetry grid covering the region.
3. Copy a notebook, swap the paths + class-code lists + capacity densities. No `functions.py` change should be needed.
4. Run `estimate_cutout_size` first to sanity-check the cutout extent before downloading.

## atlite / data gotchas (learned the hard way)

- **int8/uint8 land-cover raster + nodata=255:** atlite's `add_raster` default `nodata=255` overflows signed/8-bit dtypes → `TypeError: Cannot convert fill_value 255 to dtype int8`. `_safe_nodata` handles it (raster's own nodata, else dtype min). The "Value -128 changed to -128" GDAL warnings are harmless (silenced unless `verbose=True`).
- **Raster with no embedded CRS:** pass `raster_crs="EPSG:xxxx"` to the excluder builders.
- **availabilitymatrix shape dim** is named after the shapes index (`region`), NOT `dim_0`. Plot/aggregation code reads `matrix.dims[0]`.
- **`calculate_capacity_potentials`** collapses the matrix to one value per `(y,x)` before merging, else the matrix's `region` column collides with `coords_onshore`'s.
- **Point-in-polygon exclusion** (`_drop_points_in_geometries`): use an inner `sjoin(predicate='intersects')` + boolean drop mask. A left-join + `groupby(level=0).all()` collapses duplicate-index multi-match rows and drops everything.
- **Bathymetry**: reader auto-detects var (`z`/`elevation`) + coords (`latitude`/`lat`) so different products (US srtm15, GEBCO) both work. Depth = metres below sea level (positive offshore).
- **Enclosed/ice-bound seas**: depth alone keeps inland bays (e.g. Hudson Bay) as "offshore". Add an explicit no-build mask geojson and pass it to the offshore exclusion if those aren't real offshore-wind zones.
- **Big runs are slow** (large protected-area files, 30 m rasters): test one region first, e.g. `get_region_shapes(geo_file, ['<one region>'])`.
- **`usable_*_coords` threshold** is applied to the RAW availability share; `round_to` is display-only. Rooftop share is tiny everywhere → use a higher threshold for rooftop than land.

## Conventions

- Edit `functions.py`; keep notebooks as parameter-only drivers.
- New region = new geojson + data layers + a copy of a notebook with paths/codes swapped. No `functions.py` changes should be needed.
- Equal-area math uses `equal_area_crs` (auto LAEA centred on the data) — never hardcode a national CRS for area/distance.
- After editing `functions.py`, sanity-check: `python -c "import ast; ast.parse(open('functions.py',encoding='utf-8').read())"` then `import functions`.
- The full regional notebooks + their big `geodata/` layers are not git-pushable. Share `GENeSYS-MOD_RES_Tool_example.ipynb` (small Germany cutout) as the reference; it downloads its own tiny ERA5 cutout and needs no large local layers.
