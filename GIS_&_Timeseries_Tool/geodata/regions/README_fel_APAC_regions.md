# APAC region polygons

Two files, same 18 features (AU BD BN ID JP KH KP KR LA MM MY NZ PG PH SG TH TL VN),
same properties (`region` = ISO2, `region_name`, `country_iso3`), EPSG:4326.

| File | Geometry | Use |
|---|---|---|
| `fel_APAC_regions.geojson` | land only | this tool (APAC and SG notebooks, `build_*_apac.py`) |
| `fel_APAC_regions_buffered.geojson` | land + 0.5 deg sea buffer, split at median lines | fel-powerplantmatching (plant-to-zone assignment); scope reference for `build_apac_regions.py` |

## Why two files

The buffered file is the original `fel_APAC_regions.geojson` (synced from GitHub on
2026-10-27, commit 38929de, byte-identical to
`fel-powerplantmatching/data/geodata/fel_APAC_regions.geojson`). It follows the FEL
region-geojson contract of the power-plant pipeline: each zone is the country's land
buffered by 0.5 deg (about 55 km), with every other country's land removed and shared sea
split at the median line, so plants on reclaimed land, industrial islands and near-shore
offshore sites are assigned to their country. Measured: the outer boundary of every
coastal zone lies at 0.49-0.50 deg (median) from land, all Natural Earth land of each
country lies inside its zone, and New Zealand's parts across the antimeridian are dropped.
The buffer is deliberate for plant matching. Keep it there.

In this tool the same polygons decide which cutout cells are onshore and which are
offshore (`_get_coords_custom`): a cell is onshore when its centre lies inside a region
polygon, and offshore only when its centre lies in the EEZ and outside EVERY region
polygon. With the buffered file, the first ~55 km of sea around every coast was treated
as land: it never reached the offshore potential, it inflated `Area [km2]` and it added
sea cells to the onshore cell set used for temperature, heating/cooling and full-area
PV/wind series. Sea cells get zero land availability (WorldCover ocean fill 0 is in the
exclude list), so the land potentials themselves were not inflated.

## How the land file is built

`python build_apac_regions.py --geodata <main checkout>/geodata` (see its docstring):
Natural Earth 10m admin-1 (`natural_earth_world_admin1.geojson`) dissolved by `iso_a2`;
only land parts that touch the same country's buffered zone are kept (drops the Chatham
and Kermadec Islands of NZ and the Senkaku islets, as the buffered file does); Singapore
taken from the Marine Regions EEZ v12 coastline instead (the land inside the buffered SG
zone that no EEZ polygon covers, 705 km2 with Jurong Island, Tuas, Tekong, Ubin, Sentosa;
Natural Earth's Singapore is 511 km2 and misses them); `shapely.coverage_simplify` with a
tolerance of 0.001 deg (about 110 m) so shared borders stay identical; coordinates
snapped to 1e-6 deg. 82,307 vertices, 2.2 MB.

Not included (no `iso_a2` in the admin-1 source, `-1`): Christmas Island, Cocos (Keeling)
Islands and the Coral Sea Islands, which the buffered AU zone contains. Leaving them out
keeps the `australia` tile cutout at 173 x 175 cells instead of 175 x 237.

## Measured effect in the tool (0.275 deg tile grids, APAC notebook parameters)

Grid-only check (unprepared cutouts, no ERA5 data) with the tool's `get_coords`,
`usable_offshore_coords` (strict marine WDPA) and `calculate_offshore_potentials`
(5 MW/km2; 10 / 10 / 5 % for shallow / transitional / deep), all 18 countries:

| | buffered | land only |
|---|---|---|
| onshore cells | 23,491 | 15,963 |
| `Area [km2]` of onshore cells | 20.15 M | 13.61 M (Natural Earth land 13.59 M) |
| offshore cells 0-1000 m deep | 7,311 | 12,858 |
| usable offshore cells | 7,151 | 12,524 |
| offshore wind potential | 1,971 GW | 3,754 GW |
| land in cells that are not onshore cells of that country | 0.8 % | 3.8 % |

Trade-off to know: cell-centre assignment drops a coastal cell from the onshore set when
its centre lies at sea, so its land share no longer counts for onshore potentials. This is
small for compact countries but large for archipelagos and small countries (land outside
own onshore cells: PH 16.5 %, JP 9.2 %, ID 8.0 %, BN 40 %, TL 25.5 %, SG 26 %). Full tool
recomputation for three small countries (PV capacity, buffered -> land only): SG 0.057 ->
0.021 GW, BN 0.138 -> 0.078 GW, TL 7.69 -> 6.11 GW. A fix belongs in `functions.py`
(e.g. count a cell as onshore when the region polygon intersects it, and as offshore only
for its sea part), not in the polygons.

Figure: `fel-viewer/data/build/gis_figures/apac/region_polygons_before_after.png`.
