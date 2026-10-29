"""Extract a Europe-hub EEZ polygon layer for the RES tool offshore workflow.

Pulls the coastal hub countries out of the bundled global Marine Regions EEZ v12
(`geodata/offshore/eez_v12.gpkg`) by their sovereign ISO3 (`ISO_SOV1`) and writes one merged
polygon file in EPSG:4326:

    geodata/offshore/eez_europe.geojson

`run_batch_by_tile` uses this as the single global `offshore_file`; `_get_coords_custom`
clips it to each tile's cutout bbox, so one Europe-wide file is cheap per tile (no need
for 11 per-tile EEZ files). Landlocked tiles simply find no sea in their bbox.

Caspian exclusion: Azerbaijan (AZE), Kazakhstan (KAZ) and Turkmenistan (TKM) border ONLY
the Caspian Sea, an enclosed non-oceanic basin that is not real offshore-wind territory
(the same class of problem as Hudson Bay in CLAUDE.md). They are dropped from the ISO
list, so `central_asia` becomes genuinely landlocked for offshore and `turkey_levant`
keeps only Turkey/Georgia's Black Sea and Israel's Mediterranean zones. Turkey and
Georgia keep their (real) Black Sea EEZ because they also have oceanic coasts.

Schema written (matches eez_us.geojson / eez_india.geojson): name, geometry. Zone
geometries are clipped to a Europe-hub bbox so overseas territories of hub sovereigns
(French Polynesia, the Falklands, the Caribbean, etc.) are dropped and the file stays small.
"""
import os
import geopandas as gpd
from shapely.geometry import box

HERE = os.path.dirname(os.path.abspath(__file__))
GEODATA = os.path.join(HERE, "geodata")
SRC = os.path.join(GEODATA, "offshore", "eez_v12.gpkg")
OUT = os.path.join(GEODATA, "offshore", "eez_europe.geojson")

# Europe-hub bbox (lon/lat). Several hub sovereigns (FR, GB, NL, ES, PT, NO) hold far-flung
# overseas EEZ - French Polynesia, the Falklands, the Caribbean, Reunion, Antarctic claims,
# etc. - which are the same ISO_SOV1 but nowhere near the hub. Dropping every EEZ polygon
# that does not intersect this box turns a global 125 MB file into a small one and keeps
# per-tile reads cheap. West -32 catches the Azores/Canaries, east 90 covers the Caspian
# rim, south 25 catches Israel/Cyprus, north 84 the Barents/Svalbard fringe.
HUB_BBOX = (-32.0, 25.0, 90.0, 84.0)

# Coastal hub sovereigns (ISO3), Caspian-only sovereigns (AZE/KAZ/TKM) deliberately
# omitted so their tiles are landlocked for offshore wind (see module docstring).
COASTAL = [
    "ESP", "PRT", "FRA", "BEL", "NLD", "GBR", "IRL", "DEU", "POL", "SWE", "NOR",
    "FIN", "DNK", "ITA", "SVN", "HRV", "GRC", "BGR", "ROU", "ALB", "MNE", "BIH",
    "EST", "LVA", "LTU", "UKR", "TUR", "GEO", "ISR",
]


def main():
    iso_list = ", ".join(f"'{c}'" for c in COASTAL)
    where = f"ISO_SOV1 IN ({iso_list})"
    g = gpd.read_file(SRC, where=where).to_crs("EPSG:4326")
    if g.empty:
        raise SystemExit("no EEZ polygons matched - check ISO_SOV1 codes")
    name = "GEONAME" if "GEONAME" in g.columns else g.columns[0]
    out = g[[name, "geometry"]].rename(columns={name: "name"})
    # Clip zone geometries to the hub bbox: drops the overseas territories that share a hub
    # sovereign but lie outside Europe, and trims the vertices of any zone that merely grazes
    # the box edge - both the polygon count and the on-disk size come down a lot.
    hub = box(*HUB_BBOX)
    before = len(out)
    out = out[out.intersects(hub)].copy()
    out["geometry"] = out.geometry.intersection(hub)
    out = out[~out.geometry.is_empty & out.geometry.notna()].copy()
    print(f"clipped to hub bbox: kept {len(out)}/{before} EEZ polygons")
    if os.path.exists(OUT):
        os.remove(OUT)
    out.to_file(OUT, driver="GeoJSON")
    print(f"wrote {OUT}: {len(out)} EEZ polygons, {os.path.getsize(OUT)/1e6:.1f} MB")
    print(f"sovereigns covered: {sorted(set(g.loc[out.index, 'ISO_SOV1']))}")
    print(f"bounds: {tuple(round(b, 2) for b in out.total_bounds)}")


if __name__ == "__main__":
    main()
