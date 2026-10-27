"""Build an India(+neighbours) land-cover raster for the RES tool from ESA WorldCover 10m.

Downloads the ESA WorldCover 2021 v200 tiles that intersect the India region
bounding box (public AWS S3, no auth), downsamples each to ~300 m by
class-preserving mode resampling, and merges them into a single EPSG:4326 GeoTIFF:

    geodata/worldcover_india_300m.tif

The India geometry (fel_india_regions.geojson) spans ~68-97 E x 6-36 N, i.e. up to
~11 x 11 = ~120 candidate 3-deg tiles. At 10 m that is several GB of downloads and a
~1 GB merged raster; a national/multi-region study does not need 10 m, so we decimate
by 30 (10 m -> ~300 m). Ocean tiles simply 404 and are skipped.

WorldCover class codes are preserved (10 tree, 20 shrub, 30 grassland, 40 cropland,
50 built-up, 60 bare, 70 snow/ice, 80 water, 90 wetland, 95 mangrove, 100 moss;
0 = ocean/nodata fill in the merged raster) and its embedded CRS is kept, so the
notebook needs no raster_crs. See CLAUDE.md for the projected-CRS gotcha at analysis
time (pass crs=equal_area_crs(shapes) to the excluders).
"""
import os
import math
import time
import requests
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.io import MemoryFile

HERE = os.path.dirname(os.path.abspath(__file__))
GEODATA = os.path.join(HERE, "geodata")
OUT = os.path.join(GEODATA, "worldcover_india_300m.tif")
TMPDIR = os.path.join(GEODATA, "_worldcover_india_tmp")
os.makedirs(TMPDIR, exist_ok=True)

# India region bbox (from fel_india_regions.geojson total_bounds, small pad). Covers
# the 6 Indian grid regions + Bhutan/Nepal/Sri Lanka.
W, S, E, N = 67.7, 5.4, 97.9, 36.0
BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
DECIMATE = 30          # 10 m -> ~300 m
CHUNK = 1 << 20


def floor3(x):
    return int(math.floor(x / 3.0) * 3)


def tile_name(lat, lon):
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def tiles_for_bbox():
    lats = range(floor3(S), floor3(N) + 3, 3)
    lons = range(floor3(W), floor3(E) + 3, 3)
    return [tile_name(la, lo) for la in lats for lo in lons]


def download(url, dst, retries=5):
    """Download to a .part file then rename on success, so an interrupted transfer
    never leaves a truncated file that a later run mistakes for a complete tile.
    Retries with backoff on connection resets (S3 occasionally drops mid-stream)."""
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


def downsampled_dataset(path):
    """Open a tile and return an in-memory dataset decimated by DECIMATE using
    mode resampling (majority class per coarse cell)."""
    with rasterio.open(path) as src:
        h, w = src.height // DECIMATE, src.width // DECIMATE
        data = src.read(
            1, out_shape=(h, w), resampling=Resampling.mode
        )
        transform = src.transform * src.transform.scale(
            src.width / w, src.height / h
        )
        profile = src.profile.copy()
        profile.update(height=h, width=w, transform=transform, driver="GTiff")
    mem = MemoryFile()
    with mem.open(**profile) as ds:
        ds.write(data, 1)
    return mem.open()


def main():
    tiles = tiles_for_bbox()
    print(f"{len(tiles)} candidate tiles over India bbox")
    small = []
    for t in tiles:
        url = f"{BASE}/ESA_WorldCover_10m_2021_v200_{t}_Map.tif"
        raw = os.path.join(TMPDIR, f"{t}.tif")
        if not os.path.exists(raw):
            ok = download(url, raw)
            print(f"  {t}: {'downloaded' if ok else 'no land tile (404), skip'}")
            if not ok:
                continue
        else:
            print(f"  {t}: cached")
        small.append(downsampled_dataset(raw))

    if not small:
        raise SystemExit("no land tiles found - check bbox")

    print(f"merging {len(small)} downsampled tiles ...")
    mosaic, out_transform = merge(small)
    prof = small[0].profile.copy()
    prof.update(
        height=mosaic.shape[1],
        width=mosaic.shape[2],
        transform=out_transform,
        compress="deflate",
        tiled=True,
    )
    with rasterio.open(OUT, "w", **prof) as dst:
        dst.write(mosaic)
    for s in small:
        s.close()

    with rasterio.open(OUT) as ds:
        vals, counts = np.unique(ds.read(1), return_counts=True)
    print(f"wrote {OUT}")
    print(f"  size   : {ds.width} x {ds.height}, CRS {ds.crs}")
    print(f"  classes: {dict(zip(vals.tolist(), counts.tolist()))}")


if __name__ == "__main__":
    main()
