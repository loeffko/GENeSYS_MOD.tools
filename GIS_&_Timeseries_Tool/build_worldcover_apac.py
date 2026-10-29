"""Build per-tile ESA WorldCover land-cover rasters for the APAC hub RES run.

APAC spans ~88-179 E x -55-46 N (bigger than the Europe hub) across 18 countries, so
one hub-wide land-cover raster would mean fetching/merging ~1000+ candidate 10 m
WorldCover tiles. Instead this mirrors the Europe batch's `tile_layers` pattern: ONE
raster per TILE (the same country-group tiles as build_bathymetry_apac.py /
build_wdpa_apac.py / the notebook's TILES dict), downloaded, downsampled and merged
on demand:

    geodata/landcover/worldcover_apac_{tile}_300m.tif

Run for a single tile (e.g. the Singapore proof of concept, which lives in the
"maritime_sea" tile) with:

    python build_worldcover_apac.py maritime_sea

or with no argument to build every tile. Already-built tiles (output file exists) are
skipped; pass --force to rebuild.

Downloads ESA WorldCover 2021 v200 tiles intersecting the tile's bbox (public AWS S3,
no auth; the world is split into 3x3 deg tiles named by SW corner, e.g. N09W075; only
land tiles are published so ocean tiles 404 and are skipped), downsamples each with
class-preserving mode resampling, and merges to one EPSG:4326 GeoTIFF per tile.

DECIMATE scales with tile size so the merged raster stays a reasonable size: small
tiles (south_asia, philippines, png) keep ~100 m, the big ones (australia, east_asia,
maritime_sea) go to ~300 m - still far finer than the ~30 km ERA5 cutout grid.
Download is resumable: completed tiles cache in a per-tile `_worldcover_apac_tmp/`
dir, downloads go to a `.part` file renamed on success (S3 can reset mid-stream on a
big multi-tile run), with retry/backoff - matching build_worldcover_india.py.

WorldCover classes are preserved (10 tree, 20 shrub, 30 grassland, 40 cropland, 50
built-up, 60 bare, 70 snow/ice, 80 water, 90 wetland, 95 mangrove, 100 moss; 0 =
ocean/nodata fill in the merged raster) and its embedded CRS kept, so the notebook
needs no raster_crs - but DOES need a projected analysis CRS at excluder time (pass
crs=equal_area_crs(shapes), see CLAUDE.md's projected-CRS gotcha).
"""
import os
import sys
import math
import time
import requests
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.io import MemoryFile

HERE = os.path.dirname(os.path.abspath(__file__))
GEODATA = os.path.join(HERE, "geodata")
REGIONS = os.path.join(GEODATA, "regions", "fel_APAC_regions.geojson")
OUT_TMPL = os.path.join(GEODATA, "landcover", "worldcover_apac_{tile}_{res}.tif")

BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
CHUNK = 1 << 20
BBOX_PAD = 1.0

# Country-group tiles, kept in sync with build_bathymetry_apac.py / the notebook.
TILES = {
    "mainland_sea": ["TH", "LA", "KH", "VN", "MM"],
    "maritime_sea": ["MY", "SG", "BN", "ID", "TL"],
    "philippines":  ["PH"],
    "east_asia":    ["JP", "KR", "KP"],
    "south_asia":   ["BD"],
    "australia":    ["AU"],
    "new_zealand":  ["NZ"],
    "png":          ["PG"],
}

# 10 m -> target decimation factor per tile (bigger tile = coarser, to bound raster
# size). ~100 m for the small tiles, ~300 m for the continent-scale ones.
DECIMATE = {
    "mainland_sea": 15,
    "maritime_sea": 30,
    "philippines":  10,
    "east_asia":    20,
    "south_asia":   10,
    "australia":    30,
    "new_zealand":  15,
    "png":          10,
}


def floor3(x):
    return int(math.floor(x / 3.0) * 3)


def tile_name(lat, lon):
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def tiles_for_bbox(W, S, E, N):
    lats = range(floor3(S), floor3(N) + 3, 3)
    lons = range(floor3(W), floor3(E) + 3, 3)
    return [tile_name(la, lo) for la in lats for lo in lons]


def download(url, dst, retries=5):
    """Download to a .part file then rename on success; retries with backoff on
    connection resets (S3 occasionally drops mid-stream on a big multi-tile run)."""
    part = dst + ".part"
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, stream=True, timeout=300)
            if r.status_code == 404:
                return False
            r.raise_for_status()
            with open(part, "wb") as f:
                for c in r.iter_content(CHUNK):
                    f.write(c)
            os.replace(part, dst)
            return True
        except (requests.exceptions.RequestException, OSError) as e:
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass
            if attempt == retries:
                raise
            wait = 2 ** attempt
            print(f"    retry {attempt}/{retries} after {type(e).__name__}; wait {wait}s")
            time.sleep(wait)
    return False


def downsampled_dataset(path, decimate):
    """Open a tile and return an in-memory dataset decimated by `decimate` using
    mode resampling (majority class per coarse cell)."""
    with rasterio.open(path) as src:
        h, w = max(src.height // decimate, 1), max(src.width // decimate, 1)
        data = src.read(1, out_shape=(h, w), resampling=Resampling.mode)
        transform = src.transform * src.transform.scale(src.width / w, src.height / h)
        profile = src.profile.copy()
        profile.update(height=h, width=w, transform=transform, driver="GTiff")
    mem = MemoryFile()
    with mem.open(**profile) as ds:
        ds.write(data, 1)
    return mem.open()


def build_tile(tile, force=False):
    codes = TILES[tile]
    decimate = DECIMATE[tile]
    res_m = round(decimate * 10)
    out = OUT_TMPL.format(tile=tile, res=f"{res_m}m")
    if os.path.exists(out) and not force:
        print(f"[{tile}] already built: {out} (pass --force to rebuild)")
        return

    regions = gpd.read_file(REGIONS)
    sel = regions[regions["region"].isin(codes)]
    if sel.empty:
        print(f"[{tile}] no regions matched {codes}, skip")
        return
    minx, miny, maxx, maxy = sel.total_bounds
    W, S, E, N = minx - BBOX_PAD, miny - BBOX_PAD, maxx + BBOX_PAD, maxy + BBOX_PAD

    tmpdir = os.path.join(GEODATA, "_cache", f"worldcover_apac_{tile}")
    os.makedirs(tmpdir, exist_ok=True)

    tiles = tiles_for_bbox(W, S, E, N)
    print(f"[{tile}] {len(tiles)} candidate WorldCover tiles over bbox "
          f"({W:.1f},{S:.1f},{E:.1f},{N:.1f}), decimate={decimate} (~{res_m} m)")

    small = []
    n_land = 0
    for t in tiles:
        url = f"{BASE}/ESA_WorldCover_10m_2021_v200_{t}_Map.tif"
        raw = os.path.join(tmpdir, f"{t}.tif")
        if not os.path.exists(raw):
            ok = download(url, raw)
            if not ok:
                continue
            print(f"  {t}: downloaded")
        else:
            print(f"  {t}: cached")
        n_land += 1
        small.append(downsampled_dataset(raw, decimate))

    if not small:
        print(f"[{tile}] no land tiles found (fully oceanic bbox?), skip")
        return

    print(f"[{tile}] merging {n_land} downsampled tiles ...")
    mosaic, out_transform = merge(small)
    prof = small[0].profile.copy()
    prof.update(height=mosaic.shape[1], width=mosaic.shape[2],
                transform=out_transform, compress="deflate", tiled=True)
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(mosaic)
    for s in small:
        s.close()

    with rasterio.open(out) as ds:
        vals, counts = np.unique(ds.read(1), return_counts=True)
        size_mb = os.path.getsize(out) / 1e6
        print(f"[{tile}] wrote {out}")
        print(f"  size   : {ds.width} x {ds.height}, CRS {ds.crs}, {size_mb:.1f} MB")
        print(f"  classes: {dict(zip(vals.tolist(), counts.tolist()))}")


def main():
    args = sys.argv[1:]
    force = "--force" in args
    args = [a for a in args if a != "--force"]
    targets = args if args else list(TILES.keys())
    for t in targets:
        if t not in TILES:
            raise SystemExit(f"unknown tile '{t}', choices: {list(TILES.keys())}")
    for t in targets:
        build_tile(t, force=force)


if __name__ == "__main__":
    main()
