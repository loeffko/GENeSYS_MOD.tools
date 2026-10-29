"""Extract an APAC-hub EEZ polygon layer for the RES tool offshore workflow.

Pulls the 18 APAC hub countries out of the bundled global Marine Regions EEZ v12
(`geodata/offshore/eez_v12.gpkg`) by their sovereign ISO3 (`ISO_SOV1`) and writes one merged
polygon file in EPSG:4326:

    geodata/offshore/eez_apac.geojson

`run_batch_by_tile` uses this as the single global `offshore_file`; `_get_coords_custom`
clips it to each tile's cutout bbox, so one APAC-wide file is cheap per tile.

Hub-bbox clip: several hub sovereigns hold EEZ zones far outside the APAC hub extent -
New Zealand's associated-state zones (Cook Islands, Niue, Tokelau) and Australia's
remote territories (Heard/McDonald, Norfolk, Cocos, Christmas Island) all carry
ISO_SOV1=NZL/AUS but sit thousands of km away, pulling the raw query's bbox out to the
full +-180 deg (the same overseas-territory problem as the Europe builder). Clipping to
the hub bbox drops those and keeps the file small; the real NZ/AUS mainland EEZ (and
Macquarie Island, which is close enough to matter for the New Zealand tile) survive.

Schema written (matches eez_us.geojson / eez_india.geojson): name, geometry.

Simplification: Indonesia's EEZ is one archipelagic multipolygon with ~368k vertices -
large enough that GDAL's GeoJSON reader refuses it outright ("GeoJSON object too
complex/large") on plain `gpd.read_file`, which would break `functions.py`'s runtime
reads (get_coords/_get_coords_custom, plot_offshore_map), not just this build script.
A ~0.001 deg (~100 m) simplify tolerance is far finer than the ~30 km ERA5 cutout /
depth-classification scale this feeds, so it costs no real precision and keeps the
file readable everywhere with no env var workaround needed.
"""
import os
import geopandas as gpd
from shapely.geometry import box

HERE = os.path.dirname(os.path.abspath(__file__))
GEODATA = os.path.join(HERE, "geodata")
SRC = os.path.join(GEODATA, "offshore", "eez_v12.gpkg")
OUT = os.path.join(GEODATA, "offshore", "eez_apac.geojson")
SIMPLIFY_TOL = 0.001   # degrees (~100 m), applied after the bbox clip

# APAC hub bbox (lon/lat), padded a bit beyond fel_APAC_regions.geojson's own bounds
# (88.0, -55.3, 179.3, 46.0) so coastal EEZ fringe is not clipped at the hub edge.
HUB_BBOX = (85.0, -58.0, 180.0, 48.0)

# All 18 hub sovereigns (ISO3) - every country in fel_APAC_regions.geojson has a coast.
COASTAL = [
    "AUS", "BGD", "BRN", "IDN", "JPN", "KHM", "KOR", "LAO", "MMR", "MYS",
    "NZL", "PHL", "PNG", "PRK", "SGP", "THA", "TLS", "VNM",
]


def main():
    iso_list = ", ".join(f"'{c}'" for c in COASTAL)
    where = f"ISO_SOV1 IN ({iso_list})"
    g = gpd.read_file(SRC, where=where).to_crs("EPSG:4326")
    if g.empty:
        raise SystemExit("no EEZ polygons matched - check ISO_SOV1 codes")
    name = "GEONAME" if "GEONAME" in g.columns else g.columns[0]
    out = g[[name, "geometry"]].rename(columns={name: "name"})
    hub = box(*HUB_BBOX)
    before = len(out)
    out = out[out.intersects(hub)].copy()
    out["geometry"] = out.geometry.intersection(hub)
    out = out[~out.geometry.is_empty & out.geometry.notna()].copy()
    print(f"clipped to hub bbox: kept {len(out)}/{before} EEZ polygons")
    out["geometry"] = out.geometry.simplify(SIMPLIFY_TOL, preserve_topology=True)
    out = out[~out.geometry.is_empty & out.geometry.notna()].copy()
    if os.path.exists(OUT):
        os.remove(OUT)
    out.to_file(OUT, driver="GeoJSON")
    print(f"wrote {OUT}: {len(out)} EEZ polygons, {os.path.getsize(OUT)/1e6:.1f} MB")
    print(f"sovereigns covered: {sorted(set(g.loc[out.index, 'ISO_SOV1']))}")
    print(f"bounds: {tuple(round(b, 2) for b in out.total_bounds)}")


if __name__ == "__main__":
    main()
