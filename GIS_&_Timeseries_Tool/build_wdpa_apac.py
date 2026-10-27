"""Build a merged, strict-tier WDPA protected-areas layer for the APAC hub RES run.

    geodata/wdpa_apac.gpkg

Protected Planet's cloudfront bucket changed since the India/Europe builders
were written, in two ways (both checked live against the Oct2026 release):
  1. Per-country packs are no longer reliably published under the old
     `WDPA_WDOECM_<Mon><Year>_Public_<ISO3>_shp.zip` name - only 3 of the 18 APAC hub
     countries have that exact key.
  2. What packs DO exist (e.g. the per-country ones that are published, and the one
     global pack that always is) are now a File Geodatabase (`<name>.gdb/` inside the
     zip), not shapefiles. A `.shp`-nesting reader (the India/Europe pattern)
     silently finds nothing against a `.gdb` pack.

This script downloads the one global pack Protected Planet always publishes (~2 GB,
`WDPA_WDOECM_<Mon><Year>_Public_Global_<hash>.zip`; the hash suffix changes every
release, so the current key is discovered live via an unauthenticated listing of the
public bucket root) and reads its polygon `.gdb` layer with geopandas/pyogrio, which
reads File Geodatabases natively - no shapefile conversion needed.

Reading used a remote `/vsizip/vsicurl/` virtual path first (letting GDAL range-request
just the needed data without a local download), but that read took quite a while
on this ~1 GB polygon table even bbox+where-filtered (likely the FileGDB driver's
`organizePolygons()` step on bulky multipolygons, per its own "may be really slow"
warning - probably the same large-multipolygon shape as Indonesia's archipelagic EEZ).
A full local download, then reading from disk, is the SAME filtered read with the I/O
done locally instead of over many small HTTP range requests, so it is both faster
and more predictable here. Still filtered to:
  1. the APAC hub bbox (fel_APAC_regions.geojson bounds, padded), and
  2. the strict-protection IUCN tier (Ia/Ib/II) - the same tier the land/offshore
     excluder queries use.
Output is a GeoPackage (binary, spatially indexed), matching build_wdpa_europe.py.

Schema written (matches wdpa_india.geojson / wdpa_europe.gpkg): NAME_ENG, DESIG_ENG,
IUCN_CAT, REALM, STATUS.
"""
import os
import re
import time
import zipfile
import requests
import geopandas as gpd
from shapely.geometry import box

HERE = os.path.dirname(os.path.abspath(__file__))
GEODATA = os.path.join(HERE, "geodata")
TMPDIR = os.path.join(GEODATA, "_wdpa_apac_tmp")
os.makedirs(TMPDIR, exist_ok=True)
OUT = os.path.join(GEODATA, "wdpa_apac.gpkg")
LAYER = "wdpa"
REGIONS = os.path.join(GEODATA, "fel_APAC_regions.geojson")

BUCKET = "https://d1gam3xoknrgr2.cloudfront.net/"
STRICT_IUCN = ("Ia", "Ib", "II")          # strict-protection tier kept at build time
HUB_BBOX_PAD = 1.0                        # degrees padded onto the hub geojson bounds
GLOBAL_PACK_RE = re.compile(r"^current/WDPA_WDOECM_\w+_Public_[Gg]lobal_[0-9a-f]{32,}\.zip$")


def find_global_pack():
    """Paginate the public bucket listing to find the current global pack (its hash
    suffix changes every release, so this discovers it live)."""
    marker = ""
    for _ in range(20):
        url = f"{BUCKET}?max-keys=1000"
        if marker:
            url += f"&marker={marker}"
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        keys = re.findall(r"<Key>(.*?)</Key>", r.text)
        for k in keys:
            if GLOBAL_PACK_RE.match(k):
                return k
        if len(keys) < 1000:
            break
        marker = keys[-1]
    raise SystemExit("could not find a current global WDPA pack in the bucket listing")


def fetch_global_pack(key, retries=6):
    """Download to a .part file then rename on success. Resumable at two levels:
    a complete file already on disk (>1 GB) skips the download entirely, and an
    interrupted .part is continued with an HTTP Range request rather than restarted
    from byte 0 - this pack is ~2 GB on a slow/limited connection, so losing partial
    progress on every interruption (a plain stream download does exactly that) is
    expensive enough to be worth avoiding."""
    dst = os.path.join(TMPDIR, "WDPA_Global.zip")
    if os.path.exists(dst) and os.path.getsize(dst) > 1_000_000_000:
        print(f"  global pack: cached ({os.path.getsize(dst)/1e9:.2f} GB)")
        return dst
    url = BUCKET + key
    part = dst + ".part"
    for attempt in range(1, retries + 1):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=1800) as r:
                if have and r.status_code == 200:
                    # server ignored the Range request (no partial-content support) -
                    # restart cleanly rather than append a second copy onto .part.
                    print("  global pack: server does not support resume, restarting")
                    have = 0
                    mode = "wb"
                elif have and r.status_code == 416:
                    # "range not satisfiable" - .part is already the full file.
                    break
                else:
                    r.raise_for_status()
                    mode = "ab" if have else "wb"
                print(f"  global pack: downloading {url} from byte {have} "
                      f"({'resume' if have else 'start'}, attempt {attempt}/{retries})")
                with open(part, mode) as f:
                    for c in r.iter_content(1 << 22):
                        f.write(c)
            break
        except (requests.exceptions.RequestException, OSError) as e:
            if attempt == retries:
                raise
            wait = min(2 ** attempt, 60)
            print(f"    retry {attempt}/{retries} after {type(e).__name__}; wait {wait}s")
            time.sleep(wait)
    os.replace(part, dst)
    print(f"  global pack: {os.path.getsize(dst)/1e9:.2f} GB")
    return dst


def find_gdb_entry(zippath):
    """The pack zip's top level has the .gdb/ directory plus PDF resource folders
    (Resources_in_English/ etc.) - find the .gdb entry's name so GDAL can be pointed
    at it directly (listing the bare zip fails: multiple top-level entries)."""
    with zipfile.ZipFile(zippath) as z:
        top_level = {n.split("/")[0] for n in z.namelist()}
        gdbs = sorted(n for n in top_level if n.lower().endswith(".gdb"))
    if not gdbs:
        raise SystemExit(f"no .gdb entry found in {zippath}")
    return gdbs[0]


def gdb_poly_layer_name(zippath, gdb_entry):
    """The polygon layer inside the pack's .gdb - named
    WDPA_WDOECM_<release>_poly_Public_<hash-or-iso>, discovered via fiona.listlayers
    (cheap: just reads the gdb catalog, not the data)."""
    import fiona
    vpath = f"/vsizip/{zippath}/{gdb_entry}"
    layers = fiona.listlayers(vpath)
    poly = [n for n in layers if "_poly_" in n.lower() or n.lower().endswith("poly")]
    if not poly:
        raise SystemExit(f"no polygon layer found in {vpath}: layers were {layers}")
    return vpath, poly[0]


def normalise(gdf):
    cols = {c.upper(): c for c in gdf.columns}
    name = cols.get("NAME_ENG") or cols.get("NAME")
    desig = cols.get("DESIG_ENG") or cols.get("DESIG")
    iucn = cols.get("IUCN_CAT")
    status = cols.get("STATUS")
    realm = cols.get("REALM")
    out = gpd.GeoDataFrame(geometry=gdf.geometry, crs=gdf.crs)
    out["NAME_ENG"] = gdf[name] if name else None
    out["DESIG_ENG"] = gdf[desig] if desig else None
    out["IUCN_CAT"] = gdf[iucn] if iucn else None
    out["STATUS"] = gdf[status] if status else None
    out["REALM"] = gdf[realm] if realm else "Terrestrial"
    return out[["NAME_ENG", "DESIG_ENG", "IUCN_CAT", "REALM", "STATUS", "geometry"]]


def main():
    regions = gpd.read_file(REGIONS).to_crs("EPSG:4326")
    minx, miny, maxx, maxy = regions.total_bounds
    hub_bbox = (minx - HUB_BBOX_PAD, miny - HUB_BBOX_PAD, maxx + HUB_BBOX_PAD, maxy + HUB_BBOX_PAD)
    print(f"APAC hub bbox: {tuple(round(b, 2) for b in hub_bbox)}")

    key = find_global_pack()
    print(f"found current global pack: {key}")
    pack = fetch_global_pack(key)

    gdb_entry = find_gdb_entry(pack)
    vpath, layer = gdb_poly_layer_name(pack, gdb_entry)
    print(f"gdb: {gdb_entry}  polygon layer: {layer}")

    where = "IUCN_CAT IN ('" + "','".join(STRICT_IUCN) + "')"
    print(f"reading (bbox + where={where}) from local pack ...")
    g = gpd.read_file(vpath, layer=layer, bbox=hub_bbox, where=where)
    print(f"read {len(g)} strict-tier polygons in the hub bbox")
    if g.empty:
        raise SystemExit("no strict-tier WDPA polygons read in the APAC hub bbox")

    merged = normalise(g).to_crs("EPSG:4326")
    merged = merged[merged.intersects(box(*hub_bbox))].copy()

    if os.path.exists(OUT):
        os.remove(OUT)
    merged.to_file(OUT, driver="GPKG", layer=LAYER)
    print(f"wrote {OUT} (layer '{LAYER}'): {len(merged)} polygons, "
          f"{os.path.getsize(OUT)/1e6:.1f} MB")
    print("REALM counts:", merged["REALM"].value_counts().to_dict())
    print("IUCN_CAT counts:", merged["IUCN_CAT"].value_counts().to_dict())


if __name__ == "__main__":
    main()
