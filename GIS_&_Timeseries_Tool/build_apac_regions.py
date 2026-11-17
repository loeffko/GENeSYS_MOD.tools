"""Derive the APAC land polygons geodata/regions/fel_APAC_regions.geojson for the RES tool.

The original fel_APAC_regions.geojson (now kept as fel_APAC_regions_buffered.geojson) was
made for fel-powerplantmatching, whose region contract wants land PLUS a 0.5 deg sea
buffer split at the median line with every neighbour, so coastal, reclaimed-land and
near-shore offshore plants fall inside their country's zone. In this tool the same
polygons decide which cutout cells are "onshore" (`_get_coords_custom`: cell centre inside
a region polygon) and which are offshore (EEZ cells outside EVERY region polygon), so the
buffer turned the first ~55 km of sea into onshore cells and removed them from the
offshore potential. This script writes land-only polygons instead:

  1. Natural Earth admin-1 (geodata/regions/natural_earth_world_admin1.geojson, the only
     world outline in the repo; 10m scale) dissolved by `iso_a2` into one geometry per
     country.
  2. Island scope from the buffered file: a land part is kept only if it touches the
     same country's buffered zone. This reproduces the scope of the original file, which
     dropped New Zealand's parts across the antimeridian (Chatham Islands, Kermadec
     Islands) and the Senkaku islets that the buffered file leaves to the median split.
     Every other island is kept.
  3. Singapore override (OVERRIDE_FROM_EEZ): Natural Earth's Singapore is a 40-vertex
     outline of 511 km2 that misses Jurong Island, Tuas, Senoko, Pulau Tekong and Ubin.
     Its land is taken instead as the buffered SG zone minus the Marine Regions EEZ v12
     polygons (geodata/offshore/eez_v12.gpkg, the same source as eez_apac.geojson), i.e.
     the land the EEZ leaves out: about 706 km2 with Jurong Island, Tekong, Ubin, Sentosa
     and the southern islands. Override land is cut out of every other country. Parts
     below MIN_OVERRIDE_PART_DEG2 (slivers along the EEZ seams) are dropped.
  4. Coverage simplification (shapely.coverage_simplify, SIMPLIFY_TOL) so shared land
     borders stay identical between neighbours (no gaps, no overlaps), then coordinates
     snapped to a 1e-6 deg grid and re-validated.
  5. Properties copied from the buffered file: region (ISO2), region_name, country_iso3.
     No iso_a2 column, so get_coords selects the region-geojson workflow.

Run under the genesys conda env (from the repo root or anywhere):
    conda run -n genesys --no-capture-output python build_apac_regions.py [--geodata DIR]
--geodata points at the folder that holds the local-only offshore/eez_v12.gpkg (default:
this repo's geodata/; a git worktree has only the tracked files, so pass the main
checkout's geodata there). Region files are always read from and written to this repo.

Known limits: Natural Earth 10m misses recent reclamation and tiny islets elsewhere; with
cell-centre assignment (_get_coords_custom) a coastal cell whose centre lies at sea is not
onshore any more, so its land share drops out of the onshore potentials (see
geodata/regions/README_fel_APAC_regions.md for the measured effect).
"""
import argparse
import os

import geopandas as gpd
import shapely
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
REGIONS = os.path.join(HERE, "geodata", "regions")
SRC = os.path.join(REGIONS, "natural_earth_world_admin1.geojson")
SCOPE = os.path.join(REGIONS, "fel_APAC_regions_buffered.geojson")
OUT = os.path.join(REGIONS, "fel_APAC_regions.geojson")
EEZ_REL = os.path.join("offshore", "eez_v12.gpkg")

OVERRIDE_FROM_EEZ = ["SG"]       # land = buffered zone minus EEZ v12 polygons
MIN_OVERRIDE_PART_DEG2 = 1e-7    # ~0.001 km2; drops slivers along EEZ seams

SIMPLIFY_TOL = 0.001   # degrees (~110 m), shapely.coverage_simplify (Visvalingam-Whyatt
                       # effective-area tolerance as a length); far finer than the
                       # 0.1-0.275 deg cutout cells and the 100-300 m WorldCover rasters
GRID = 1e-6            # coordinate snapping grid (degrees) before writing
MIN_PART_KM2 = 0.0     # keep every island (no area filter)


def parts(g):
    return list(getattr(g, "geoms", [g]))


def override_from_eez(zone, eez_file):
    """Land inside `zone` that no EEZ v12 polygon covers."""
    eez = gpd.read_file(eez_file, bbox=tuple(zone.bounds)).to_crs("EPSG:4326")
    land = zone.difference(unary_union(eez.geometry.values))
    keep = [p for p in parts(land) if p.geom_type == "Polygon" and p.area >= MIN_OVERRIDE_PART_DEG2]
    return unary_union(keep)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geodata", default=os.path.join(HERE, "geodata"),
                    help="folder holding the local-only offshore/eez_v12.gpkg")
    a = ap.parse_args()
    eez_file = os.path.join(a.geodata, EEZ_REL)

    scope = gpd.read_file(SCOPE).to_crs("EPSG:4326")
    codes = list(scope["region"])
    ne = gpd.read_file(SRC).to_crs("EPSG:4326")
    ne = ne[ne["iso_a2"].isin(codes)]
    missing = sorted(set(codes) - set(ne["iso_a2"]))
    if missing:
        raise SystemExit(f"codes not in {SRC}: {missing}")

    land, dropped = {}, {}
    for _, row in scope.iterrows():
        c = row["region"]
        g = shapely.make_valid(unary_union(ne.loc[ne["iso_a2"] == c, "geometry"].values))
        keep = [p for p in parts(g) if p.geom_type == "Polygon" and p.intersects(row.geometry)]
        drop = [p for p in parts(g) if p.geom_type == "Polygon" and not p.intersects(row.geometry)]
        if drop:
            dropped[c] = [tuple(round(v, 2) for v in p.representative_point().coords[0]) for p in drop]
        land[c] = unary_union(keep)

    # high-resolution overrides win: cut them out of every other country
    zones = dict(zip(scope["region"], scope.geometry))
    for c in OVERRIDE_FROM_EEZ:
        if c not in land:
            continue
        before = land[c]
        land[c] = override_from_eez(zones[c], eez_file)
        for k in land:
            if k != c and land[k].intersects(land[c]):
                land[k] = shapely.make_valid(land[k].difference(land[c]))
                land[k] = unary_union([p for p in parts(land[k]) if p.geom_type == "Polygon"])
        print(f"override {c}: {len(parts(before))} NE part(s) -> {len(parts(land[c]))} EEZ-derived part(s)")

    # simplify all countries as one coverage so shared borders move together
    simp = shapely.coverage_simplify([land[c] for c in codes], SIMPLIFY_TOL)
    geoms = []
    for c, g in zip(codes, simp):
        g = shapely.set_precision(g, GRID)
        g = shapely.make_valid(g)
        g = unary_union([p for p in parts(g) if p.geom_type == "Polygon" and not p.is_empty])
        geoms.append(g)

    out = gpd.GeoDataFrame(scope[["region", "region_name", "country_iso3"]].copy(),
                           geometry=geoms, crs="EPSG:4326")
    if os.path.exists(OUT):
        os.remove(OUT)
    out.to_file(OUT, driver="GeoJSON")

    n_vert = int(shapely.get_num_coordinates(out.geometry.values).sum())
    print(f"Wrote {OUT}: {len(out)} regions, {os.path.getsize(OUT) / 1e6:.2f} MB, {n_vert} vertices")
    print(f"columns : {list(out.columns)}  (iso_a2 present: {'iso_a2' in out.columns})")
    print(f"bounds  : {tuple(round(b, 2) for b in out.total_bounds)}")
    print(f"invalid : {int((~out.is_valid).sum())}")
    print(f"dropped land parts outside the buffered scope: {dropped}")
    print(f"regions : {list(out['region'])}")


if __name__ == "__main__":
    main()
