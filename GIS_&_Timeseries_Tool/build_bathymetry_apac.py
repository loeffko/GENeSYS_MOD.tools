"""Build per-tile GMRT bathymetry grids for the APAC hub offshore workflow.

`run_batch_by_tile` groups the 18 APAC regions into disjoint country-group tiles and
runs one ERA5 cutout per tile. Offshore wind needs a depth grid over each tile's sea,
so this writes ONE bathymetry file per COASTAL tile:

    geodata/bathymetry_apac_{tile}.nc

Each is a GMRT GridServer pull (public, no auth) over the tile's bbox padded by
BBOX_PAD, saved as z(latitude, longitude) float32 to match bathymetry_us.nc so the
notebook's `_get_coords_custom` reader auto-detects it (depth = -z).

Every APAC tile is coastal (LA/Laos is the only landlocked country in the hub and sits
in the mainland_sea tile alongside four coastal neighbours), so this always pulls one
grid per tile; the coastal-check against eez_apac.geojson is kept anyway for
consistency with build_bathymetry_europe.py and as a safety net if TILES changes.

The TILES grouping below is kept in sync with the notebook's TILES dict (cell-5). It
lives here as data, not in functions.py, so the region-agnostic rule (CLAUDE.md) holds:
only the build script knows the country groups.
"""
import os
import time
import geopandas as gpd
import requests
import xarray as xr
from shapely.geometry import box

HERE = os.path.dirname(os.path.abspath(__file__))
GEODATA = os.path.join(HERE, "geodata")

REGIONS = os.path.join(GEODATA, "fel_APAC_regions.geojson")
EEZ = os.path.join(GEODATA, "eez_apac.geojson")
OUT_TMPL = os.path.join(GEODATA, "bathymetry_apac_{tile}.nc")

BBOX_PAD = 1.0     # degrees padded onto each tile's region bbox for the depth grid
RETRIES = 4

# Country-group tiles (region codes), kept in sync with the notebook TILES dict.
# New Zealand and Papua New Guinea get their own tiles despite being small - they sit
# ~5000 km apart with open ocean between, so merging them would waste cutout cells on
# empty sea. Australia is its own tile (continent-scale on its own, ~41k cells at
# 0.275 deg - already the largest single tile, comparable to the Europe hub's biggest).
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


def download(url, dst):
    """GMRT pull to a .part file renamed on success, with backoff on transient errors."""
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, timeout=300)
            r.raise_for_status()
            part = dst + ".part"
            with open(part, "wb") as f:
                f.write(r.content)
            os.replace(part, dst)
            return
        except (requests.exceptions.RequestException, OSError) as e:
            wait = 2 ** attempt
            print(f"    retry {attempt + 1}/{RETRIES} after {type(e).__name__} "
                  f"(sleep {wait}s)")
            time.sleep(wait)
    raise SystemExit(f"failed to download {url}")


def save_grid(part, out):
    """Normalise the coards GMRT output to z(latitude, longitude) float32 zlib."""
    ds = xr.open_dataset(part)
    var = next((v for v in ("altitude", "z", "elevation", "Band1") if v in ds), None)
    if var is None:
        var = list(ds.data_vars)[0]
    latname = "lat" if ("lat" in ds.coords or "lat" in ds.dims) else "latitude"
    lonname = "lon" if ("lon" in ds.coords or "lon" in ds.dims) else "longitude"
    grid = ds.rename({var: "z", latname: "latitude", lonname: "longitude"})[["z"]]
    grid["z"] = grid["z"].astype("float32")
    enc = {"z": {"zlib": True, "complevel": 4}}
    ds.close()
    grid.to_netcdf(out, encoding=enc)
    z = grid["z"]
    dims = dict(z.sizes)
    zmin, zmax = float(z.min()), float(z.max())
    grid.close()
    return dims, zmin, zmax


def main():
    regions = gpd.read_file(REGIONS).to_crs("EPSG:4326")
    eez = gpd.read_file(EEZ).to_crs("EPSG:4326")
    eez_union = eez.union_all() if hasattr(eez, "union_all") else eez.unary_union

    coastal, landlocked = [], []
    for tile, codes in TILES.items():
        sel = regions[regions["region"].isin(codes)]
        if sel.empty:
            print(f"{tile}: no regions matched {codes}, skip")
            continue
        minx, miny, maxx, maxy = sel.total_bounds
        W, S, E, N = minx - BBOX_PAD, miny - BBOX_PAD, maxx + BBOX_PAD, maxy + BBOX_PAD
        if not box(minx, miny, maxx, maxy).intersects(eez_union):
            landlocked.append(tile)
            print(f"{tile}: bbox has no EEZ -> landlocked, no bathymetry")
            continue

        out = OUT_TMPL.format(tile=tile)
        if os.path.exists(out):
            print(f"{tile}: cached ({os.path.getsize(out)/1e6:.1f} MB), skip")
            coastal.append(tile)
            continue
        url = ("https://www.gmrt.org/services/GridServer?"
               f"minlongitude={W}&maxlongitude={E}&minlatitude={S}&maxlatitude={N}"
               "&format=coards&resolution=low&layer=topo")
        print(f"{tile}: coastal, GMRT bbox W{W:.2f} S{S:.2f} E{E:.2f} N{N:.2f}")
        part = out + ".part"
        download(url, part)
        dims, zmin, zmax = save_grid(part, out)
        os.remove(part)
        coastal.append(tile)
        print(f"  wrote {out}  grid {dims}  z range [{zmin:.0f}, {zmax:.0f}] m")

    print(f"\ncoastal   ({len(coastal)}): {coastal}")
    print(f"landlocked({len(landlocked)}): {landlocked}")


if __name__ == "__main__":
    main()
