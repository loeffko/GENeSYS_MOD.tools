"""Build a merged, strict-tier WDPA protected-areas layer for the Europe-hub RES run.

Downloads the per-country WDPA packs from Protected Planet (cloudfront, no token for
country packs), reads the polygon shapefiles nested in each outer zip, normalises the
schema, filters to the strict-protection IUCN tiers, and writes one merged GeoPackage:

    geodata/wdpa_europe.gpkg

The hub is 51 countries. An unfiltered 51-country WDPA GeoJSON would be multiple GB
(Europe is densely protected), so two things keep it small:
  1. Only IUCN categories Ia/Ib/II are kept (the strict-protection tier the excluder
     queries anyway - the same Ia/Ib/II set used in the US GAP 1/2 mapping). Category-V
     "protected landscapes" etc. are not blanket wind/PV exclusions and are dropped.
  2. The output is a GeoPackage (binary, spatially indexed) instead of GeoJSON (text).
This still keeps REALM so the notebook can split terrestrial+coastal (land excluder) from
marine+coastal (offshore excluder) with a query.

Not every country has a cloudfront pack at every release; a 404 is skipped (that country
just contributes no protected areas) rather than failing the whole build.

Schema written (matches wdpa_india.geojson): NAME_ENG, DESIG_ENG, IUCN_CAT, REALM,
STATUS. REALM is Terrestrial/Coastal/Marine; recent releases carry it directly, older
ones only a MARINE flag (0=terrestrial, 1=coastal, 2=marine) which we map.
"""
import os
import io
import zipfile
import requests
import geopandas as gpd
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
GEODATA = os.path.join(HERE, "geodata")
TMPDIR = os.path.join(GEODATA, "_wdpa_europe_tmp")
os.makedirs(TMPDIR, exist_ok=True)
OUT = os.path.join(GEODATA, "wdpa_europe.gpkg")
LAYER = "wdpa"

RELEASE = "Sep2026"                       # month-stamp of the current WDPA release
BASE = "https://d1gam3xoknrgr2.cloudfront.net/current"
KEEP = ["NAME_ENG", "DESIG_ENG", "IUCN_CAT", "REALM", "STATUS"]
MARINE_TO_REALM = {0: "Terrestrial", 1: "Coastal", 2: "Marine"}
STRICT_IUCN = {"Ia", "Ib", "II"}         # strict-protection tier kept at build time

# The 51 hub countries as WDPA ISO3 (kept in sync with the notebook TILES / KEEP list;
# the ISO3 spelling is WDPA's, e.g. Kosovo has no ISO3 pack so it is not listed).
COUNTRIES = [
    "ESP", "PRT", "AND",
    "FRA", "BEL", "NLD", "LUX", "MCO",
    "GBR", "IRL",
    "DEU", "AUT", "CHE", "CZE", "POL", "SVK", "HUN", "LIE",
    "SWE", "NOR", "FIN", "DNK",
    "ITA", "SVN", "HRV", "SMR",
    "GRC", "BGR", "ROU", "SRB", "MKD", "ALB", "MNE", "BIH",
    "EST", "LVA", "LTU",
    "UKR", "MDA", "BLR",
    "TUR", "GEO", "ARM", "AZE", "ISR",
    "KAZ", "UZB", "TKM", "TJK", "KGZ",
]


def fetch_pack(iso):
    dst = os.path.join(TMPDIR, f"WDPA_{iso}.zip")
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        print(f"  {iso}: cached ({os.path.getsize(dst)/1e6:.1f} MB)")
        return dst
    url = f"{BASE}/WDPA_WDOECM_{RELEASE}_Public_{iso}_shp.zip"
    print(f"  {iso}: downloading {url}")
    r = requests.get(url, stream=True, timeout=600)
    if r.status_code == 404:
        print(f"  {iso}: 404 - no country pack, skipping")
        return None
    r.raise_for_status()
    with open(dst, "wb") as f:
        for c in r.iter_content(1 << 20):
            f.write(c)
    print(f"  {iso}: {os.path.getsize(dst)/1e6:.1f} MB")
    return dst


def read_polys_from_pack(zippath):
    """WDPA outer zip nests three inner shapefile zips (_shp_0/1/2, polygons split
    by size). Read every polygon shapefile and concat."""
    frames = []
    with zipfile.ZipFile(zippath) as outer:
        inner_zips = [n for n in outer.namelist() if n.lower().endswith(".zip")]
        # Some small packs are a single flat shapefile, not nested zips.
        if not inner_zips:
            shps = [n for n in outer.namelist()
                    if n.lower().endswith(".shp") and "point" not in n.lower()]
            for shp in shps:
                frames.append(gpd.read_file(f"zip://{zippath}!{shp}"))
            return frames
        for iz in inner_zips:
            data = outer.read(iz)
            with zipfile.ZipFile(io.BytesIO(data)) as inner:
                shps = [n for n in inner.namelist()
                        if n.lower().endswith(".shp") and "point" not in n.lower()]
                for shp in shps:
                    tmp = os.path.join(TMPDIR, os.path.basename(iz)[:-4])
                    inner.extractall(tmp)
                    frames.append(gpd.read_file(os.path.join(tmp, os.path.basename(shp))))
    return frames


def normalise(gdf):
    cols = {c.upper(): c for c in gdf.columns}
    name = cols.get("NAME_ENG") or cols.get("NAME")
    desig = cols.get("DESIG_ENG") or cols.get("DESIG")
    iucn = cols.get("IUCN_CAT")
    status = cols.get("STATUS")
    out = gpd.GeoDataFrame(geometry=gdf.geometry, crs=gdf.crs)
    out["NAME_ENG"] = gdf[name] if name else None
    out["DESIG_ENG"] = gdf[desig] if desig else None
    out["IUCN_CAT"] = gdf[iucn] if iucn else None
    out["STATUS"] = gdf[status] if status else None
    if "REALM" in cols:
        out["REALM"] = gdf[cols["REALM"]]
    elif "MARINE" in cols:
        m = pd.to_numeric(gdf[cols["MARINE"]], errors="coerce").fillna(0).astype(int)
        out["REALM"] = m.map(MARINE_TO_REALM).fillna("Terrestrial")
    else:
        out["REALM"] = "Terrestrial"
    return out[["NAME_ENG", "DESIG_ENG", "IUCN_CAT", "REALM", "STATUS", "geometry"]]


def main():
    all_frames = []
    skipped = []
    for iso in COUNTRIES:
        pack = fetch_pack(iso)
        if pack is None:
            skipped.append(iso)
            continue
        for f in read_polys_from_pack(pack):
            if len(f):
                n = normalise(f)
                # Filter to the strict IUCN tier at build time (keeps the file small).
                n = n[n["IUCN_CAT"].isin(STRICT_IUCN)]
                if len(n):
                    all_frames.append(n)
    if not all_frames:
        raise SystemExit("no strict-tier WDPA polygons read")
    merged = gpd.GeoDataFrame(pd.concat(all_frames, ignore_index=True), crs="EPSG:4326")
    merged = merged.to_crs("EPSG:4326")
    if os.path.exists(OUT):
        os.remove(OUT)
    merged.to_file(OUT, driver="GPKG", layer=LAYER)
    print(f"wrote {OUT} (layer '{LAYER}'): {len(merged)} polygons, "
          f"{os.path.getsize(OUT)/1e6:.1f} MB")
    if skipped:
        print(f"skipped (404, no pack): {skipped}")
    print("REALM counts:", merged["REALM"].value_counts().to_dict())
    print("IUCN_CAT counts:", merged["IUCN_CAT"].value_counts().to_dict())


if __name__ == "__main__":
    main()
