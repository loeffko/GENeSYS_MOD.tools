"""Build per-country residential / commercial rooftop shares for the rooftop PV split.

    geodata/config/rooftop_shares.csv

GENeSYS-MOD splits rooftop PV into P_PV_Rooftop_Residential and P_PV_Rooftop_Commercial,
but the tool's rooftop potential is one number per region (built-up land cover x
capacity density). This file gives the share used to split it, per country, from ONE
consistent global source so every region is treated the same way:

  GHSL GHS_BUILT_S R2023A (JRC), epoch 2020, 1 km, Mollweide (ESRI:54009):
    - GHS_BUILT_S       total built-up surface (building footprint, m2 per cell)
    - GHS_BUILT_S_NRES  non-residential built-up surface (m2 per cell)
  commercial_footprint = NRES / total  (non-residential = commercial + industrial + public)

Built-up surface is building footprint, i.e. a roof-area proxy. Flat non-residential
roofs carry more PV per m2 of footprint than pitched homes (NREL 2016: only ~26 % of
small-building roof area is suitable), so the share actually used re-weights the
footprint share by COMMERCIAL_USABLE_FACTOR:
  commercial  = f*k / (f*k + (1 - f)),   f = commercial_footprint, k = 1.5
  residential = 1 - commercial
k = 1.5 is calibrated so the EU-27 aggregate matches JRC's 2025 EU building-stock study
(Nature Energy, EDBSM R2025): 22 % of EU rooftop capacity on non-residential roofs
(519 of 2341 GWp), against a 16 % GHSL footprint share. Cross-check: NREL's 2016 US
study puts ~35 % of capacity on medium/large buildings (which also hold multi-family
housing) vs 16 % here.

Caveat: GHSL's non-residential layer is known to under-detect commercial buildings
where they are mixed into dense residential fabric (much of South / South-East Asia):
India comes out at ~3 %, Bangladesh ~2 %. These are flagged in the `note` column;
put a better national estimate in OVERRIDES when one is available.

Countries are measured over the project's own region polygons (the same areas the
notebooks model), dissolved to one polygon per country:
  europe_regions.geojson (region = ISO2), fel_APAC_regions.geojson (region = ISO2),
  fel_india_regions_simplified.geojson (country_iso3), iso_regions.geojson (US),
  iso_regions_canada_south55.geojson (CA).
To add a country, add its region file to SOURCES and re-run. The 1 km rasters (~186 MB
zipped) are downloaded once into geodata/_cache/ghsl/ and read straight from the zips.
"""
import os
import requests
import numpy as np
import pandas as pd
import geopandas as gpd
import pycountry
import rasterio
import rasterio.mask

HERE = os.path.dirname(os.path.abspath(__file__))
GEODATA = os.path.join(HERE, "geodata")
TMPDIR = os.path.join(GEODATA, "_cache", "ghsl")
OUT = os.path.join(GEODATA, "config", "rooftop_shares.csv")

BASE = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_BUILT_S_GLOBE_R2023A"
EPOCH = 2020
PRODUCTS = {"total": f"GHS_BUILT_S_E{EPOCH}_GLOBE_R2023A_54009_1000",
            "nres": f"GHS_BUILT_S_NRES_E{EPOCH}_GLOBE_R2023A_54009_1000"}
SOURCE = f"GHSL GHS_BUILT_S(_NRES) R2023A E{EPOCH} 1km, NRES footprint x1.5 usable-roof factor"

# (region file, how to get the country code: a column name, or a fixed ISO2)
SOURCES = [
    ("europe_regions.geojson", "region"),
    ("fel_APAC_regions.geojson", "region"),
    ("fel_india_regions_simplified.geojson", "country_iso3"),
    ("iso_regions.geojson", "US"),
    ("iso_regions_canada_south55.geojson", "CA"),
]
EXTRA_CODES = {"XK": ("XKX", "Kosovo")}   # not in ISO 3166 / pycountry

COMMERCIAL_USABLE_FACTOR = 1.5   # usable PV per m2 footprint, non-res vs res (see above)
LOW_DETECTION = 0.05             # flag commercial shares below this as likely under-detected
# Manual {iso2: (commercial share, note)} that replace the GHSL value, e.g. from a
# national rooftop study.
OVERRIDES = {}


def fetch(name):
    dst = os.path.join(TMPDIR, f"{name}.zip")
    if not os.path.exists(dst):
        os.makedirs(TMPDIR, exist_ok=True)
        url = f"{BASE}/{name}/V1-0/{name}_V1_0.zip"
        print(f"downloading {url}")
        with requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(dst + ".part", "wb") as f:
                for c in r.iter_content(1 << 22):
                    f.write(c)
        os.replace(dst + ".part", dst)
    return f"/vsizip/{dst}/{name}_V1_0.tif"


def codes(code):
    """(iso2, iso3, name) from an ISO2 or ISO3 code."""
    if code in EXTRA_CODES:
        return (code, *EXTRA_CODES[code])
    c = pycountry.countries.get(alpha_2=code) if len(code) == 2 else pycountry.countries.get(alpha_3=code)
    if c is None:
        raise ValueError(f"unknown country code {code}")
    return c.alpha_2, c.alpha_3, getattr(c, "common_name", c.name)


def country_polygons():
    parts = []
    for fname, key in SOURCES:
        g = gpd.read_file(os.path.join(GEODATA, "regions", fname))
        g["code"] = g[key] if key in g.columns else key
        parts.append(g[["code", "geometry"]])
    g = pd.concat(parts, ignore_index=True)
    g["iso2"] = [codes(c)[0] for c in g["code"]]
    g = gpd.GeoDataFrame(g, crs="EPSG:4326").dissolve("iso2")
    return g.to_crs("ESRI:54009")


def masked_sum(src, geom):
    # filled=False -> masked array; cells outside the polygon and nodata are masked out
    data, _ = rasterio.mask.mask(src, [geom], crop=True, filled=False)
    return float(data.astype("float64").sum())


def main():
    paths = {k: fetch(v) for k, v in PRODUCTS.items()}
    countries = country_polygons()
    rows = []
    with rasterio.open(paths["total"]) as tot, rasterio.open(paths["nres"]) as nres:
        for iso2, geom in countries.geometry.items():
            t, n = masked_sum(tot, geom), masked_sum(nres, geom)
            _, iso3, name = codes(iso2)
            f = n / t if t > 0 else np.nan
            k = COMMERCIAL_USABLE_FACTOR
            com = f * k / (f * k + 1 - f)
            source, note = SOURCE, ""
            if iso2 in OVERRIDES:
                com, note = OVERRIDES[iso2]
                source = "manual override"
            elif com < LOW_DETECTION:
                note = "GHSL NRES likely under-detects non-residential here"
            rows.append({"iso2": iso2, "iso3": iso3, "country": name,
                         "residential": round(1 - com, 3), "commercial": round(com, 3),
                         "commercial_footprint": round(f, 3),
                         "built_up_km2": round(t / 1e6, 1), "nonres_km2": round(n / 1e6, 1),
                         "source": source, "note": note})
            print(f"{iso2} {name:<28} built-up {t/1e6:9.1f} km2  footprint {f:.3f}  commercial {com:.3f}")
    df = pd.DataFrame(rows).sort_values("iso2")
    df.to_csv(OUT, index=False)
    print(f"wrote {OUT}: {len(df)} countries")


if __name__ == "__main__":
    main()
