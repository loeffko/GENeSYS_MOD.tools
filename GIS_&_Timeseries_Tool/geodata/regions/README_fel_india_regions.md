# FEL "India region" geometry — v1

Region split follows the **five CEA / Grid-India regional grids** (the closest Indian
analogue to the US ISO zones), plus one non-synchronous island feature and the three
non-focus neighbour countries.

## Files

| File | Features | Size | Use |
|---|---|---|---|
| `fel_india_regions.geojson` | 9 | ~10 MB | main modelling geometry, full resolution — raster clipping, RES potential, land-area masks |
| `fel_india_regions_simplified.geojson` | 9 | ~270 KB | web maps, quick spatial joins, plots |
| `fel_india_states.geojson` | 36 | ~5.5 MB | current states/UTs tagged with `region_code` — for aggregating CEA state-level data up to regions |
| `fel_india_state_region_lookup.csv` | 36 rows | 2 KB | plain state → region table, no geometry |

All files: **EPSG:4326 / CRS84**, lon-lat degrees, RFC 7946 GeoJSON.

## Region features

| `region_code` | `region_name` | RLDC | States/UTs | Area (km²) |
|---|---|---|---|---|
| `NR` | Northern Region | NRLDC, New Delhi | 10 | 893,596 |
| `WR` | Western Region | WRLDC, Mumbai | 6 | 940,816 |
| `SR` | Southern Region | SRLDC, Bengaluru | 6 | 634,670 |
| `ER` | Eastern Region | ERLDC, Kolkata | 5 | 422,231 |
| `NER` | North Eastern Region | NERLDC, Shillong | 7 | 253,387 |
| `ISL` | Isolated Island Systems | — | 2 | 7,646 |
| `BTN` | Bhutan | — | — | 39,872 |
| `NPL` | Nepal | — | — | 144,979 |
| `LKA` | Sri Lanka | — | — | 66,291 |

### Region membership

- **NR** — Rajasthan, Uttar Pradesh, Punjab, Haryana, Delhi, Himachal Pradesh, Uttarakhand, Jammu and Kashmir, Ladakh, Chandigarh
- **WR** — Maharashtra, Gujarat, Madhya Pradesh, Chhattisgarh, Goa, Dadra and Nagar Haveli and Daman and Diu
- **SR** — Tamil Nadu, Karnataka, Andhra Pradesh, Telangana, Kerala, Puducherry
- **ER** — West Bengal, Bihar, Jharkhand, Odisha, Sikkim
- **NER** — Assam, Arunachal Pradesh, Meghalaya, Manipur, Mizoram, Nagaland, Tripura
- **ISL** — Andaman and Nicobar Islands, Lakshadweep

## Properties schema

```
region_id                        "IND-NR" | "BTN" | ...   stable join key
region_code                      NR|WR|SR|ER|NER|ISL|BTN|NPL|LKA
region_name                      human readable
country_iso3, country_name
focus_country                    true only for the Indian regions
level                            "grid_region" | "country"
rldc                             Regional Load Despatch Centre (null for non-India)
synchronous_with_national_grid   false for ISL, BTN, NPL, LKA
n_states, states                 member list (null for countries)
area_km2                         geodesic area, WGS84 ellipsoid
centroid_lon, centroid_lat       representative point (guaranteed inside polygon)
bbox                             [minx, miny, maxx, maxy]
note                             only on neighbour countries
```

## Caveats

1. **Territorial extent.** Indian polygons cover **administered** territory only
   (source: GADM). Aksai Chin and Pakistan-administered Kashmir are excluded, so
   India totals 3,152,346 km² rather than the 3,287,263 km² of the official Indian
   claim. For energy modelling this is the right choice — CEA generation, demand and
   capacity data cover administered territory only. If you need the claim extent,
   rebuild NR from an Indian-government boundary source.
2. **No overlaps.** Bhutan and Nepal polygons have the India union subtracted, so
   disputed strips (e.g. Kalapani) are not double counted in area or RES potential.
3. **State layer vintage.** State polygons are current (post-2019, includes Telangana
   and Ladakh); region polygons come from an older high-resolution source whose
   internal splits predate those changes. Both splits are internal to one region
   (Telangana/AP → SR, Ladakh/J&K → NR), so region outlines are unaffected. State
   polygons are clipped to the same India extent; `sum(state area) ≈ region area`
   to within ~1% on the mainland, ~25% for `ISL` (the coarse island source drops
   many small islands — negligible, `ISL` has no synchronous grid).
4. **Regions are not price zones.** All five have been synchronously interconnected
   since 2013 ("One Nation One Grid"). They are transmission-corridor and
   data-reporting units, not market zones. The balancing unit in India is the state
   (SLDC / discom). Add inter-regional transfer capacity from CEA / Grid-India if
   the model needs constraints.

## Downstream use

- **RES potential** — clip Global Wind Atlas / Global Solar Atlas rasters with
  `fel_india_regions.geojson`; use `area_km2` for land-availability denominators.
- **Timeseries** — feed `bbox` to ERA5 / MERRA-2 retrieval, then mask by polygon.
  `centroid_lon`/`centroid_lat` work as single-point proxies for the small nodes
  (BTN, NPL, LKA, ISL).
- **Capacity & demand** — CEA monthly Executive Summary and LGBR publish by these
  exact five regions; the state layer plus lookup CSV lets you roll state-level
  series up to regions.

## Sources

- `github.com/geohacker/india` — high-resolution state polygons (GADM derived)
- `github.com/udit-001/india-maps-data` — current 36 states/UTs
- `github.com/datasets/geo-countries` — Bhutan, Nepal, Sri Lanka (Natural Earth 10m derived)
- Region membership per CEA / Grid-India RLDC definitions
