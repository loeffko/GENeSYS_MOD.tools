"""Derive geodata/europe_regions.geojson from the supplied country file.

The user's geodata/res_countries_europe_mainland.geojson carries both a `region`
and an `iso_a2` column, so get_coords/_determine_cutout_bounds would select the
country/ISO workflow rather than the region-geojson workflow the batch process
needs. This script produces a clean region-geojson: it drops `iso_a2` (and the
other ISO/admin columns), keeps only the study-scope countries (KEEP), dissolves to
one geometry per region, clips detached offshore islands (CLIP - e.g. Norway's
Svalbard, which otherwise inflates the nordics cutout to 80.8 N), and writes
`region, region_name, geometry` in EPSG:4326.

Run under the genesys conda env:
    conda run -n genesys --no-capture-output python build_europe_regions.py
"""
import os
import geopandas as gpd
from shapely.geometry import MultiPolygon

SRC = "geodata/res_countries_europe_mainland.geojson"
OUT = "geodata/europe_regions.geojson"

# Study-scope keep-list: the codes kept in europe_regions.geojson. This is the full
# official Europe hub definition, including Israel and the Central-Asian countries
# (IL, KZ, UZ, TM, TJ, KG). The microstates LI, MC and SM are kept in the geojson
# (valid geometries) even though the notebook leaves them out of any tile - they are
# too small to catch a cell at the run resolution, so they get no timeseries there.
# All 51 source rows are in scope, so nothing is currently trimmed; the .isin filter
# is kept anyway so a narrower KEEP still works. Kept in sync with the notebook's
# TILES dict (which groups these into cutouts and drops the microstates).
KEEP = [
    "ES", "PT", "AD",
    "FR", "BE", "NL", "LU", "MC",
    "GB", "IE",
    "DE", "AT", "CH", "CZ", "PL", "SK", "HU", "LI",
    "SE", "NO", "FI", "DK",
    "IT", "SI", "HR", "SM",
    "GR", "BG", "RO", "RS", "MK", "AL", "ME", "BA", "XK",
    "EE", "LV", "LT",
    "UA", "MD", "BY",
    "TR", "GE", "AM", "AZ", "IL",
    "KZ", "UZ", "TM", "TJ", "KG",
]

# Drop detached offshore island territories that are geographically separate from the
# rest of the hub and play a negligible energy role, but inflate a tile's cutout. Each
# entry keeps only the polygon parts that fall INSIDE the given bbox
# (min_lon, min_lat, max_lon, max_lat). Norway: keep the mainland (lat <= 74, lon >= 0),
# dropping Svalbard (lat ~74-81 N, which alone pushed the nordics cutout up to 80.8 N)
# and Jan Mayen (the lon ~ -9 island). Add other regions here if the same issue arises.
CLIP = {
    "NO": (0.0, 50.0, 40.0, 74.0),
}


def clip_offshore_islands(g):
    """Keep only the polygon parts of each CLIP region that lie within its bbox."""
    for code, (minx, miny, maxx, maxy) in CLIP.items():
        sel = g["region"] == code
        if not sel.any():
            continue
        geom = g.loc[sel, "geometry"].iloc[0]
        parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
        kept = [p for p in parts
                if minx <= p.bounds[0] and p.bounds[2] <= maxx
                and miny <= p.bounds[1] and p.bounds[3] <= maxy]
        dropped = len(parts) - len(kept)
        new_geom = MultiPolygon(kept) if len(kept) != 1 else kept[0]
        g.loc[sel, "geometry"] = gpd.GeoSeries([new_geom], index=g.index[sel], crs=g.crs)
        print(f"clip {code}: kept {len(kept)}/{len(parts)} parts (dropped {dropped}),"
              f" new bounds {tuple(round(b, 2) for b in new_geom.bounds)}")
    return g


def main():
    keep = sorted(set(KEEP))
    g = gpd.read_file(SRC).to_crs("EPSG:4326")
    present = set(g["region"])
    missing = sorted(set(keep) - present)
    if missing:
        print(f"Warning: {len(missing)} KEEP code(s) not in {SRC}: {missing}")

    g = g[g["region"].isin(keep)].copy()
    # Drop iso_a2/iso_a3/admin so the region-geojson workflow fires (functions.py
    # selects it only when 'region' is present AND 'iso_a2' is absent).
    g = g.rename(columns={"name": "region_name"})[["region", "region_name", "geometry"]]
    g = g.dissolve(by="region", as_index=False)   # one geometry per region
    g = clip_offshore_islands(g)                   # drop Svalbard etc. (see CLIP)
    g["geometry"] = g.geometry.buffer(0)          # fix any self-touch from dissolve

    if os.path.exists(OUT):
        os.remove(OUT)
    g.to_file(OUT, driver="GeoJSON")

    print(f"Wrote {OUT}: {len(g)} regions, {os.path.getsize(OUT) / 1e6:.2f} MB")
    print(f"columns    : {list(g.columns)}  (iso_a2 present: {'iso_a2' in g.columns})")
    print(f"bounds     : {tuple(round(b, 2) for b in g.total_bounds)}")
    print(f"invalid    : {(~g.is_valid).sum()}")
    print(f"regions    : {sorted(g['region'])}")


if __name__ == "__main__":
    main()
