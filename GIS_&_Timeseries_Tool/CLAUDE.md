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
- `geodata/` — input layers, one subfolder per kind (paths in code are `geodata/<sub>/<file>`):
  - `config/` — small tables (`rooftop_shares.csv`, `iso_codes_all.csv`). **Tracked.**
  - `regions/` — region polygons (`europe_regions`, `fel_APAC_regions`, `fel_india_*`, `iso_regions*`, natural-earth admin-1). **Tracked** (except the unused `tl_2022_us_state.*`).
  - `example/` — the small Germany example set (polygon, EEZ, bathymetry). **Tracked.**
  - `landcover/` — WorldCover / CORINE / NALCMS / LCNext rasters. Local only.
  - `exclusions/` — WDPA, PAD-US, CPCAD, US ordinance layers. Local only.
  - `offshore/` — EEZ polygons, bathymetry grids, offshore no-build masks. Local only.
  - `_cache/` — raw downloads the `build_*.py` scripts reuse (WorldCover tiles, WDPA packs, GHSL). Local only.
  The root `.gitignore` ignores `geodata/*` and re-includes `config/`, `regions/`, `example/`. A new layer goes in the matching subfolder; a new build script writes there and caches raw downloads under `_cache/<name>/`.
- `sources/data_sources.csv` — provenance for every externally sourced input (provider, version, URL, licence, local path, build script). Add a row when you bring in a new dataset; `TO CONFIRM` marks fields not yet known.
- `cutouts/` — atlite ERA5 cutouts (`.nc`) + `era5_cache/` (raw CDS download cache). Large, git-ignored.
  Cutouts and the local-only `geodata/` layers are kept on the project SharePoint, not in
  git (repo size); `sources/data_sources.csv` lists each layer's local path.
- `solarpanel/` — PV module configs (`CSi.yaml`, `CdTe.yaml`, `KANENA.yaml`).
- `windturbines/` — turbine power-curve configs (referenced by `onshore_turbine`/`offshore_turbine`).
- `output/` — generated results, git-ignored (see "Outputs and the transfer zip").

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
- `make_land_excluder(raster, exclude_codes, raster_crs=, raster_nodata=, protected_files=, protected_layer=, protected_query=, protected_buffer=, buffered_codes=, code_buffer=)` — utility PV / onshore wind land availability. `buffered_codes` + `code_buffer` (metres) exclude those classes plus a setback around them.
- **PV and wind use separate land excluders.** `excluder` is utility PV: the land rules plus a `PV_BUILTUP_BUFFER = 500` m setback around the built-up classes, and in Europe also forest (CORINE 23-25, WorldCover 10; the other notebooks already exclude forest for both). `wind_excluder` is the plain land rules (US: plus federal land / county bans). Potentials calls pass `return_wind_coords=True` and the usable wind profiles use `coords_wind_usable`. In tile specs: `pv_exclude_codes`, `pv_buffered_codes`, `pv_code_buffer`. Utility PV density is `PV_CAP_PER_SQKM = 79.2` MW/km² (Risch et al. 2022, Energies 15, 5536, Eq. 3). Checked against Germany: CORINE alone leaves ~88 % of land eligible (only built-up, water, wetland and IUCN Ia-II out); forest + 500 m bring it to ~44 %, i.e. ~372 GW PV at 3 % use, inside Risch's 348-456 GWp. Wind (247 GW, 27 MW/km²) sits inside Risch's 90-403 GW.
- `make_rooftop_excluder(raster, developed_codes, ...)` — rooftop proxy (keeps only built-up classes via `invert=True`).
- `calculate_potentials_per_region(...)` — **memory-safe**: processes one region at a time so atlite only rasterizes the land-cover raster over a single region's bbox (the whole-extent rasterization is what exhausts RAM at 30 m). Writes per-region + combined CSVs, returns `(combined_df, stitched_land, stitched_rooftop, coords_onshore_usable, coords_rooftop_usable, coords_offshore_usable)`. Stitched availability maps with area-weighted headline %.
- `calculate_capacity_potentials(...)` — single-pass version (all regions at once; can exhaust RAM on big extents).
- `calculate_offshore_potentials(...)` — offshore wind per region + depth class, reuses EEZ+depth `coords_offshore`.
- `usable_onshore_coords` / `usable_offshore_coords` — filter cutout cells to developable sites, feed into the CF functions for "usable sites only" timeseries.
- `plot_offshore_map`, `equal_area_crs`.

`pv_capacity_factors(..., tech_label=, optimal_tilt=)`: `tech_label` renames output
files without changing the opt/avg/inf split; `optimal_tilt=True` uses a cheap
per-cell latitude rule for tilt (`_optimal_orientation`, not a per-angle yield
search). The PV physics lives in `_pv_capacity_factor(ds, panel, slope, azimuth)`
(radians, scalar or per-cell), shared by the utility and rooftop paths.

**Rooftop PV = segments, not inf/avg/opt.** GENeSYS-MOD has `P_PV_Rooftop_Residential`
and `P_PV_Rooftop_Commercial`, so rooftop is split by segment:
- `pv_rooftop_capacity_factors(cutout, coords_rooftop_usable, panel, segments=)` writes
  one series per segment (`..._pv_rooftop_{segment}.csv`), each a weighted mix of
  orientations, averaged over a region's rooftop cells weighted by rooftop area (cell
  area × built-up share). Orientations are equator-relative so one spec works in both
  hemispheres: `tilt` = degrees or `"optimal"`, `azimuth` = `"equator"`/`"pole"`/
  `"east"`/`"west"` or degrees clockwise from north (atlite's solar azimuth convention:
  90 = east, 180 = south). Default `ROOFTOP_SEGMENTS`: residential 50% equator-facing +
  25% east + 25% west at 20°; commercial (flat roofs, racks) optimal tilt facing the equator.
- `rooftop_shares` on `calculate_capacity_potentials` / `calculate_potentials_per_region` /
  `run_batch_by_tile` adds `Rooftop Capacity {segment} [GW]` columns. Either one
  `{segment: share}` for all regions or `{region: {segment: share}}`; each sums to 1, and a
  region with no entry is an error. Notebooks build it with `load_rooftop_shares(...)` from
  the per-country table `geodata/config/rooftop_shares.csv` (WorldCover can't tell residential
  from commercial, so it's a country share, not per cell). The region-to-country mapping
  is a notebook argument: region codes are ISO2 (EU/APAC/DE/SG, the default),
  `country="US"` for a sub-national file, or `country_col="country_iso3"` (India). ISO2
  or ISO3 both match.
- `build_rooftop_shares.py` makes that CSV from GHSL `GHS_BUILT_S` / `GHS_BUILT_S_NRES`
  R2023A E2020 at 1 km (~186 MB, JRC FTP, no auth, cached in `geodata/_cache/ghsl/`). Each
  country is measured over the project's own region polygons (listed in `SOURCES`; add a
  region file there for a new country). commercial = non-residential footprint share ×
  1.5 usable-roof factor, calibrated so the EU-27 total matches JRC's 2025 building-stock
  split of 22% non-residential rooftop capacity (GHSL footprint alone gives 16%). The raw
  share is kept in `commercial_footprint`. GHSL under-detects non-residential buildings in
  dense mixed fabric: India comes out at ~3% and Bangladesh at ~2%, and every country
  below 5% is flagged in `note`. Put better national figures in `OVERRIDES` and re-run.
- `run_batch_by_tile` emits rooftop families `pv_rooftop_{segment}` alongside the others.
- In 2018 India results, commercial ≈ utility PV and residential is 3–7% lower; the hourly
  shape barely changes (east/west at a 20° pitch only widens the shoulders slightly).

## Outputs and the transfer zip

```
output/
  {timeframe}/                {timeframe}_{filename}_{series}.csv   timeseries
    tiles/                    per-tile timeseries of a tiled run
  potentials/[tiles|scenarios/<s>]/   {filename}_potentials_{combined|<region>|offshore...}.csv
  coords/[tiles|scenarios/<s>]/       {filename}_coords_{onshore|rooftop|wind|offshore}_usable.csv
  zip_transfer/               {timeframe}_{filename}_genesys_inputs.zip
```

- **One naming scheme**: `{timeframe}_{filename}_{series}`, e.g. `2018_india_heating`,
  `2018_india_usable_pv_avg`. Usable-site runs pass `filename + "_usable"`, so their
  series read `usable_<tech>_<cat>`. `_CF_FAMILIES` / `_HEAT_FAMILIES` in
  `functions.py` list the series names.
- **Year-agnostic results** (potentials, coords) live next to the timeframe folders.
  `output_subdir(output_dir, kind)` gives the folder; `calculate_potentials_per_region`
  takes `potentials_dir=` / `coords_dir=` (defaults: those folders), which the US
  scenario loop sets to `.../scenarios/<s>/`. A later run with another weather year
  overwrites them (the inf/avg/opt category split comes from the latest run's CFs).
- **`potentials_combined`** is the per-region table on usable areas: onshore PV / wind
  (incl. inf/avg/opt split), rooftop (incl. residential / commercial), and offshore
  per depth class on usable offshore sites (depth AND offshore exclusions). Notebooks
  set `offshore_cap_per_sqkm` / `offshore_percent_available` in the capacity-density
  cell and pass them to the potentials loop.
- **`create_transfer_zip(filename, timeframe, rooftop_segments=...)`** (last cell of each
  notebook) bundles heat series + COPs (`heat/`), usable-site profiles (`profiles/`)
  and `potentials_combined` (`potentials/`) with a `manifest.json` (units, meaning,
  regions, tool commit, missing files) into `output/zip_transfer/`. For a tiled run it
  takes the combined files, never `tiles/`. Missing files are warned, not fatal.
- **Heat-pump "COP" files hold the inverse Carnot COP**, `(T_supply - T)/T_supply` at
  55 degC supply (values ~0.04-0.2), not a COP; the manifest says so.
- `migrate_output_layout.py [--dry-run] [output_root]` moves an old-layout `output/`
  (flat year folders, `{tf}_{series}_{name}` heat files) to this layout. Idempotent.

## Adding a new region

1. Make a region geojson (a `region` column for the region-geojson workflow) or use country ISO codes for the country workflow.
2. Get the regional data layers: a land-cover raster (note its class codes + CRS), a protected-areas file, and — for offshore — an EEZ polygon + a bathymetry grid covering the region.
3. Copy a notebook, swap the paths + class-code lists + capacity densities. No `functions.py` change should be needed.
4. Run `estimate_cutout_size` first to sanity-check the cutout extent before downloading.

### Batch/tiling for continent-scale areas

A single cutout over a continent-scale extent (all of Europe at country level + Turkey
and neighbours, say) — plus rasterizing the land-cover layer over the whole extent —
exhausts a laptop's RAM. `run_batch_by_tile(tiles, geo_file, timeframe, filename, ...)`
splits the area into disjoint **country-group tiles**, builds one small ERA5 cutout per
tile, runs the full pipeline (capacity factors + GIS potentials) on that tile, frees
the cutout, then **combines everything into single outputs** (one CSV per
tech/category, one combined potentials table, per-tile maps for
`combine_and_plot_tile_maps`). Peak RAM is bounded by the largest single tile, not the
whole extent. `GENeSYS-MOD_RES_Tool_EU.ipynb` is the thin driver (the only thing you
edit is the `TILES` dict). Region-agnostic, so no country logic enters `functions.py`.
`GENeSYS-MOD_RES_Tool_APAC.ipynb` is a second example (18 countries, 88–179°E ×
-55–46°N — a bigger extent than the Europe hub — split into 8 tiles; `TILE_LAYERS`
there is simpler than Europe's since every tile uses the same ESA WorldCover source,
just one raster file per tile via `build_worldcover_apac.py <tile>`, plus one hub-wide
WDPA GeoPackage shared across all tiles). For a single country inside a continent-scale
hub file (e.g. just Singapore out of the APAC geojson), skip the batch tiler entirely
and pass explicit `cutout_north_west`/`cutout_south_east` corners around that one
country's own bbox instead — `GENeSYS-MOD_RES_Tool_SG.ipynb` does this; see the next
bullet for why `regions=` alone does not work here.

Mechanics worth knowing:

- **Region-geojson workflow only.** `run_batch_by_tile` asserts the geo_file has a
  literal `region` column and **no `iso_a2`** (that combination selects the
  region-geojson workflow; a file carrying both silently falls into the country/ISO
  path). `build_europe_regions.py` derives such a file from a source that has both by
  dropping `iso_a2`/`iso_a3`/`admin` — that drop is the load-bearing fix.
- **Per-tile bbox via explicit corners.** For a region-geojson, `get_cutout` **ignores**
  `regions=` and would span the whole file, so the orchestrator computes each tile's
  bbox from its member polygons (`total_bounds` + `bbox_buffer`) and passes explicit
  `cutout_north_west`/`cutout_south_east` corners, which win. Corner mapping:
  `nw=(maxy, minx)`, `se=(miny, maxx)`.
- **Disjoint tiles.** Every region must appear in exactly one tile; a duplicate is a
  hard error (prevents double-counting). Missing codes / regions covered by no tile are
  warned, non-fatal.
- **Shared ERA5 chunk cache.** Each tile's cutout `.nc` is tile-scoped
  (`filename=f"{filename}_{tile}"`) so there are no collisions and re-runs reuse it;
  overlapping tile buffers reuse the same `cutouts/era5_cache/` downloads.
- **Filename discipline.** Per-tile calls use `filename=f"{filename}_{tile}"` and write
  to the `tiles/` subfolders (`output/{timeframe}/tiles/`, `output/potentials/tiles/`,
  `output/coords/tiles/`); the combined files use the **base** `filename`
  (`output/{timeframe}/{timeframe}_{filename}_{family}.csv`,
  `output/potentials/{filename}_potentials_combined.csv`). Resume and cleanup match
  exact family names, never a prefix glob (tile `central` vs `central_asia`).
- **Usable-site profiles.** With potentials on, each tile also gets PV / onshore wind
  (usable land set) / offshore (usable sites) / rooftop profiles as `usable_*`
  families — the ones the transfer zip ships. `full_area_cf=False` skips the
  all-cells PV/wind series.
- **"Prove fast, scale later."** Start with a short `timeframe` (one day) and coarse
  `dx`/`dy` to smoke-test the tiling; the same code runs a full year by switching
  `timeframe="2018"` (cutouts + chunk cache reused). Set `run_potentials=False` to get
  timeseries only until a Europe land-cover raster + WDPA exist. `estimate_only=True`
  prints each tile's grid size and the peak-tile RAM before any download.

### Offshore data sources (EEZ + bathymetry)

Both are scriptable from data already in `geodata/` or a no-auth web service — no manual portal download needed. India (`eez_india.geojson` + `bathymetry_india.nc`) and the Europe/APAC hubs (`build_eez_*.py`, `build_bathymetry_*.py`) were built this way:

- **EEZ**: extract the country's polygons from the bundled global Marine Regions EEZ v12 (`geodata/offshore/eez_v12.gpkg`), filtering on `ISO_SOV1` (the sovereign ISO3, e.g. `'IND'`). Keep only `GEONAME`→`name` + `geometry` in EPSG:4326 to match `eez_us.geojson`. The reader only uses `geometry`; the `name` column is convention. `ISO_SOV1` catches all of a country's zones (mainland + far offshore banks/islands).
  ```python
  g = gpd.read_file("geodata/offshore/eez_v12.gpkg", where="ISO_SOV1='IND'")
  g[["GEONAME","geometry"]].rename(columns={"GEONAME":"name"}).to_file("geodata/offshore/eez_<region>.geojson", driver="GeoJSON")
  ```
  **Multi-sovereign hub + overseas-territory bbox clip**: for a hub of several sovereigns (`build_eez_europe.py`, `build_eez_apac.py`), `ISO_SOV1 IN (...)` also pulls in each sovereign's far-flung overseas EEZ (French Polynesia for France, Cook Islands/Niue/Tokelau for New Zealand, Heard/McDonald/Norfolk/Cocos/Christmas Island for Australia) — these share the sovereign's ISO3 but sit nowhere near the hub, pulling the raw query's bbox out to the full ±180°. Clip to a hub bbox (intersect + `geometry.intersection(box(*hub_bbox))`) to drop them.
  **Simplify a hub-wide EEZ before writing it.** An archipelagic country's EEZ can be one multipolygon with hundreds of thousands of vertices (Indonesia's is ~368k) — large enough that GDAL's GeoJSON reader refuses it outright (`"GeoJSON object too complex/large"`) on a plain `gpd.read_file`, which breaks not just the build script but every runtime read in `functions.py` (`get_coords`/`_get_coords_custom`, `plot_offshore_map`). Call `.simplify(tol, preserve_topology=True)` (e.g. `tol=0.001`° ≈ 100 m) after the bbox clip — far finer than the ~30 km cutout / depth-classification scale this feeds, so no real precision is lost, and it keeps the file readable everywhere with no `OGR_GEOJSON_MAX_OBJ_SIZE` env-var workaround needed.
- **Bathymetry**: pull a subset from the **GMRT GridServer** (Global Multi-Resolution Topography, no auth) over the EEZ bounding box, padded a little. Use `format=coards` to get a 2-D `altitude(lat, lon)` grid (the default `format=netcdf` returns the GMT native 1-D `z` + header layout, which the reader can't index); `resolution=low` auto-caps to a sensible cell count (a 16°×16° box → ~910×926 cells, 2.5 MB). Sign convention matches the reader: negative below sea level, so `depth = -z`.
  ```python
  url = ("https://www.gmrt.org/services/GridServer?"
         f"minlongitude={W}&maxlongitude={E}&minlatitude={S}&maxlatitude={N}"
         "&format=coards&resolution=low&layer=topo")
  # then rename lat/lon -> latitude/longitude and the var -> z to match bathymetry_us.nc,
  # save float32 zlib-compressed. The reader auto-detects z/elevation/Band1 + lat/latitude either way.
  ```
  Alternatives that also work unchanged: GEBCO (`elevation`/`lat`/`lon`, 15 arc-sec — needs a manual portal download) and SRTM15+ (`z`/`latitude`/`longitude`).

### Land cover + protected areas (onshore)

For a non-US, non-European region with no national land-cover raster, both onshore layers are scriptable from free, no-manual-portal sources. The India region (`worldcover_india_300m.tif` + `wdpa_india.geojson`, spanning 9 nodes across 4 countries) and the APAC hub (`worldcover_apac_<tile>_*.tif` per tile + one hub-wide `wdpa_apac.gpkg`, 18 countries) were built this way. **Base new non-US notebooks on `..._DE.ipynb`, not `..._US.ipynb`** — the US notebook carries federal-land + county wind/solar ordinance layers (PAD-US `Own_Type`, NREL reVX) that only exist for the US; on other regions those `FEDERAL_LAYER`/`WINDBAN_LAYER` specs are set to `None` and the filter-scenario cells collapse to a single land-only run. (`..._IN.ipynb` is a ready-made region-geojson starting point too.)

- **Land cover — ESA WorldCover 10 m** (2021 v200) from the public AWS S3 bucket `esa-worldcover` (no auth). The world is split into 3°×3° tiles named by SW corner (e.g. `N09W075`); only land tiles are published, so ocean tiles 404 and are skipped. For a national run the 10 m tiles are far finer than the cutout (and risk the RAM blow-up), so downsample each with **class-preserving mode resampling** (`Resampling.mode`) and merge to one GeoTIFF. `build_worldcover_india.py` / `build_worldcover_apac.py` do the whole fetch/downsample/merge — copy one and change the bbox + `DECIMATE` + output name. **Scale the decimation to the region size:** a single ~15°×18° country at `DECIMATE=10` → ~100 m; the India region (~30°×30°, ~40 land tiles) at `DECIMATE=30` → ~300 m keeps the merged raster ~100 MB instead of ~1 GB. 300 m is fine for national/multi-region potentials (the ERA5 cutout is ~0.275° ≈ 30 km anyway). **Download robustness:** the S3 fetch can reset mid-stream on a big multi-tile run — download to a `.part` file renamed on success (so a truncated file is never mistaken for a cached tile) and retry with backoff; `build_worldcover_india.py` and `build_worldcover_apac.py` have this. The builders cache completed tiles in a `_worldcover*_tmp/` dir, so a re-run resumes. WorldCover classes: 10 tree, 20 shrubland, 30 grassland, 40 cropland, 50 built-up, 60 bare/sparse, 70 snow/ice, 80 water, 90 herbaceous wetland, 95 mangrove, 100 moss/lichen (0 = ocean/nodata fill in the merged raster). A sensible strict land-exclude list: `[0, 10, 40, 50, 70, 80, 90, 95]` (keep shrub/grass/bare; drop cropland from the list to allow agrivoltaics). Rooftop excluder keeps only built-up `[50]`. WorldCover already carries EPSG:4326, so no `raster_crs=` — but see the projected-CRS gotcha below.
- **Protected areas — WDPA** (World Database on Protected Areas) from Protected Planet, cloudfront direct download, no token. Historically a per-country shapefile pack at:
  ```
  https://d1gam3xoknrgr2.cloudfront.net/current/WDPA_WDOECM_<Mon><YYYY>_Public_<ISO3>_shp.zip
  ```
  with the outer zip nesting three inner shapefile zips (`_shp_0/1/2`, polygons split by size) — read all three and concat. `build_wdpa_india.py`/`build_wdpa_europe.py` use this. **This pack naming is no longer reliable** (checked live Oct 2026 against the APAC hub's 18 countries: only 3 had that exact key). What Protected Planet still always publishes is ONE global pack per release, `WDPA_WDOECM_<Mon><YYYY>_Public_Global_<hash>.zip` (~2 GB; the hash suffix changes every release, so discover the current key live via an unauthenticated listing of the bucket root, `https://d1gam3xoknrgr2.cloudfront.net/?max-keys=1000`, paginated by `marker` — regex for `Public_[Gg]lobal_[0-9a-f]{32,}\.zip`). That pack (and apparently some surviving per-country packs too) is now a **File Geodatabase** (`<name>.gdb/` inside the zip), not shapefiles — a `.shp`-nesting reader silently finds nothing against it. Read it with `geopandas.read_file("/vsizip/<local_zip_path>/<gdb_name>.gdb", layer=..., bbox=..., where=...)` (geopandas/pyogrio reads FileGDB natively); find the polygon layer name (`..._poly_Public_...`) via `fiona.listlayers`. **Download locally first, then read from the local path** — a remote `/vsizip/vsicurl/` read of the same bbox+where query against the ~1 GB polygon table was still running (or stuck on the FileGDB driver's own `organizePolygons() ... may be really slow` warning) after 10+ minutes; the identical filtered read against a local copy of the same file finished in well under a minute. `build_wdpa_apac.py` does the whole discover/download/read; its `fetch_global_pack` also resumes an interrupted download with an HTTP `Range` request rather than restarting the ~2 GB from byte 0 (worth having on a slow/limited connection — losing partial progress on every interruption is expensive at this size).

  Attributes used for filtering either way: `IUCN_CAT` (`Ia`/`Ib`/`II` ≈ the US GAP 1/2 strict-protection tier), `REALM` (`Terrestrial`/`Coastal`/`Marine` — replaced the old `MARINE` column in recent releases; `build_wdpa_india.py` maps the old 0/1/2 `MARINE` flag to REALM when a pack predates the switch). Filter terrestrial+coastal strict areas for the land excluder's `protected_query`, and marine+coastal strict areas for the offshore `OFFSHORE_EXCLUDE_QUERY`. **Multi-country regions** (e.g. the India node set spans India, Sri Lanka, Bhutan, Nepal; the APAC hub spans all 18 of its countries): either fetch each country's per-country pack and concat (`build_wdpa_india.py`, when those packs still exist for your countries), or filter the one global pack to your hub's bbox (`build_wdpa_apac.py`, more robust against the naming change, costs one ~2 GB one-time download). Not every country has a per-country cloudfront pack at every release (Nepal's `NPL` 404'd across recent months; most APAC countries lack one entirely now); a 404 is skipped rather than failing the whole build.

**Region file needs a literal `region` column.** `get_coords`/`get_region_shapes` detect the region-geojson workflow by the presence of a column named exactly `region` (and absence of `iso_a2`). A file keyed on some other name (the India geometry uses `region_code`/`region_id`) must get a `region` column added first — e.g. `g['region'] = g['region_code']`. A `region_col=` arg exists on `get_region_shapes`/`calculate_potentials_per_region` but does **not** thread through `get_coords`/`_get_coords_custom` (they hardcode `"region"`), so adding the column is the reliable fix.

## atlite / data gotchas (learned the hard way)

- **int8/uint8 land-cover raster + nodata=255:** atlite's `add_raster` default `nodata=255` overflows signed/8-bit dtypes → `TypeError: Cannot convert fill_value 255 to dtype int8`. `_safe_nodata` handles it (raster's own nodata, else dtype min). The "Value -128 changed to -128" GDAL warnings are harmless (silenced unless `verbose=True`).
- **Raster with no embedded CRS:** pass `raster_crs="EPSG:xxxx"` to the excluder builders.
- **Excluder must use a PROJECTED (metre) analysis CRS.** atlite's availability calc (`compute_shape_availability` / `cutout.availabilitymatrix`) works in the excluder's own CRS. A geographic (degrees) CRS such as EPSG:4326 degenerates: the raster window collapses to ~1 cell and land availability comes back **zero everywhere** — an empty land/rooftop map while offshore (a separate code path) still looks fine. Land-cover rasters already in metres (US NLCD is EPSG:5070) mask the problem; ESA WorldCover is EPSG:4326 and hits it. Fix: pass a projected CRS to `make_land_excluder` / `make_rooftop_excluder`, e.g. `crs=equal_area_crs(shapes)` (auto LAEA centred on the region). Applies to the land, rooftop and wind excluders alike.
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
