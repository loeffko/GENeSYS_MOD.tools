"""Build the APAC-hub offshore wind zones, for calibrate_offshore_sites.

Writes geodata/offshore/offshore_zones_apac.geojson (EPSG:4326), one polygon per zone,
with columns: region, name, status, area_km2, source, geometry.

Australia (region AU): the six declared offshore renewable energy infrastructure areas
(Gippsland, Hunter, Southern Ocean, Bass Strait off Northern Tasmania, Illawarra,
Bunbury) under the Offshore Electricity Infrastructure Act 2021, layer
"Declared Offshore Renewable Energy Infrastructure Regions" (Geoscience Australia /
DCCEEW), served without auth on the Tasmanian Department of State Growth ArcGIS server
(the Geoscience Australia service itself refuses anonymous access). Cached in
geodata/_cache/au_oei/. The legal boundaries are the declaration instruments on
legislation.gov.au.

No other hub country publishes downloadable official zones (checked Nov 2026): Japan's
promotion zones exist only as vertex tables in each tender guideline PDF, Korea has not
designated zones yet (Offshore Wind Special Act, in force Mar 2026), and Vietnam's and
the Philippines' zone layers are World Bank roadmap studies, not designations. Those
countries are calibrated on their EEZ and their targets alone.
"""
import json
import os
import urllib.parse
import urllib.request

import geopandas as gpd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "geodata", "_cache", "au_oei")
OUT = os.path.join(HERE, "geodata", "offshore", "offshore_zones_apac.geojson")
AU_URL = ("https://data.stategrowth.tas.gov.au/ags/rest/services/"
          "REAP_Case_Management_System/MapServer/5/query")
AU_SOURCE = "Geoscience Australia / DCCEEW declared OEI areas (via Tas. State Growth ArcGIS)"


def fetch_au():
    path = os.path.join(CACHE, "au_declared_oei_areas.geojson")
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        q = urllib.parse.urlencode({"where": "1=1", "outFields": "*", "outSR": 4326,
                                    "f": "geojson"})
        with urllib.request.urlopen(f"{AU_URL}?{q}", timeout=300) as r:
            data = json.load(r)
        with open(path + ".part", "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(path + ".part", path)
    return gpd.read_file(path)


def main():
    au = fetch_au().to_crs("EPSG:4326")
    print("AU layer columns:", list(au.columns))
    name = next(c for c in au.columns if c.lower() in ("name", "area_name", "title", "region_name"))
    status = next((c for c in au.columns if c.lower() == "status"), None)
    au = au.dissolve(by=name, as_index=False, aggfunc="first")
    out = gpd.GeoDataFrame({
        "region": "AU",
        "name": au[name].values,
        "status": au[status].values if status else "Declared",
        "source": AU_SOURCE,
    }, geometry=au.geometry.values, crs="EPSG:4326")
    laea = "+proj=laea +lat_0=-30 +lon_0=135 +datum=WGS84 +units=m"
    out["area_km2"] = (out.to_crs(laea).area / 1e6).round(1)
    out = out[["region", "name", "status", "area_km2", "source", "geometry"]]
    if os.path.exists(OUT):
        os.remove(OUT)
    out.to_file(OUT, driver="GeoJSON")
    print(f"wrote {OUT}: {len(out)} zones, {out['area_km2'].sum():.0f} km2")
    print(out[["region", "name", "status", "area_km2"]].to_string(index=False))


if __name__ == "__main__":
    main()
