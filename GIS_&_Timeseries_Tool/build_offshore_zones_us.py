"""Build the US offshore wind zones (active BOEM leases), for calibrate_offshore_sites.

Writes geodata/offshore/offshore_zones_us.geojson (EPSG:4326), one polygon per lease,
with columns: region, lease, project, company, state, area_km2, geometry. `region` is
the model region (geodata/regions/iso_regions.geojson) the lease delivers to.

Source: BOEM "Wind Lease Boundaries" feature service (no auth), cached in
geodata/_cache/boem/:
https://services7.arcgis.com/G5Ma95RzqJRPKsWL/ArcGIS/rest/services/Wind_Lease_Boundaries__BOEM_/FeatureServer/8

Kept: Commercial and Research generation leases. Dropped: easements and the sea2shore
cable lease (OCS-A 0506), and the leases surrendered in 2026 buyback deals, which the
BOEM layer (last edited 2025-03) still shows (SURRENDERED below; TotalEnergies' and
Golden State Wind's are named in the sources, the rest matched by lessee name).
Wind Energy Areas and call areas are not used: BOEM rescinded all of them on
30 Jul 2025 (https://www.boem.gov/newsroom/notes-stakeholders/boem-rescinds-designated-wind-energy-areas-outer-continental-shelf).

Region: by the lease's state label, except where a lease delivers elsewhere (OVERRIDE):
Sunrise Wind and South Fork (RI/MA lease area) deliver to Long Island (NYISO), Kitty
Hawk (North Carolina) lands in Virginia (PJM), and the NY Bight leases labelled "NY/NJ"
go to the state they lie nearest.
"""
import json
import os
import urllib.parse
import urllib.request

import geopandas as gpd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "geodata", "_cache", "boem")
OUT = os.path.join(HERE, "geodata", "offshore", "offshore_zones_us.geojson")
URL = ("https://services7.arcgis.com/G5Ma95RzqJRPKsWL/ArcGIS/rest/services/"
       "Wind_Lease_Boundaries__BOEM_/FeatureServer/8/query")

SURRENDERED = {
    "OCS-A 0538": "TotalEnergies (Attentive Energy), Mar 2026",
    "OCS-A 0545": "TotalEnergies Carolina Long Bay, Mar 2026",
    "OCS-A 0537": "Bluepoint Wind, 2026",
    "OCS-P 0564": "Golden State Wind, 2026",
    "OCS-A 0542": "Invenergy, Jun 2026",
    "OCS-A 0562": "Invenergy, Jun 2026",
    "OCS-A 0567": "Invenergy, Jun 2026",
    "OCS-P 0565": "Invenergy, Jun 2026",
    "OCS-A 0546": "Duke Energy, Jun 2026",
    "OCS-A 0539": "RWE (Community Offshore Wind), Aug 2026",
    "OCS-P 0561": "RWE, Aug 2026",
    "OCS-G 37334 Provisional": "RWE (Lake Charles), Aug 2026",
}
CABLE = {"OCS-A 0506"}

STATE_REGION = {
    "Maine": "ISONE", "Massachusetts": "ISONE", "Massachussets": "ISONE",
    "Rhode Island / Massachusetts": "ISONE", "New York": "NYISO", "New Jersey": "PJM",
    "Delaware": "PJM", "Delaware/Maryland": "PJM", "Maryland": "PJM", "Virginia": "PJM",
    "North Carolina": "SERC", "CA": "CAISO", "Louisanna/Texas": "MISO",
}
OVERRIDE = {
    "OCS-A 0487": "NYISO",   # Sunrise Wind -> Long Island
    "OCS-A 0517": "NYISO",   # South Fork -> Long Island
    "OCS-A 0508": "PJM",     # Kitty Hawk South, lands in Virginia
    "OCS-A 0559": "PJM",     # Kitty Hawk North, lands in Virginia
    "OCS-A 0544": "NYISO",   # NY Bight, nearest New York
    "OCS-A 0541": "PJM",     # NY Bight, nearest New Jersey
}


def fetch():
    path = os.path.join(CACHE, "boem_wind_lease_outlines.geojson")
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        q = urllib.parse.urlencode({"where": "1=1", "outFields": "*", "outSR": 4326,
                                    "f": "geojson"})
        with urllib.request.urlopen(f"{URL}?{q}", timeout=300) as r:
            data = json.load(r)
        with open(path + ".part", "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(path + ".part", path)
    return gpd.read_file(path)


def main():
    g = fetch()
    g = g[g["LEASE_TYPE"].isin(["Commercial", "Research"])
          & ~g["LEASE_NUMBER"].isin(SURRENDERED) & ~g["LEASE_NUMBER"].isin(CABLE)].copy()
    g["region"] = g["LEASE_NUMBER"].map(OVERRIDE).fillna(g["STATE"].map(STATE_REGION))
    missing = g[g["region"].isna()]
    if len(missing):
        raise SystemExit(f"no region for {missing[['LEASE_NUMBER', 'STATE']].values.tolist()}")
    g = g.dissolve(by="LEASE_NUMBER", as_index=False, aggfunc="first")
    out = g.rename(columns={"LEASE_NUMBER": "lease", "PROJECT_NAME_1": "project",
                            "COMPANY": "company", "STATE": "state"})
    out["area_km2"] = (out.to_crs("EPSG:5070").area / 1e6).round(1)
    out = out[["region", "lease", "project", "company", "state", "area_km2", "geometry"]]
    if os.path.exists(OUT):
        os.remove(OUT)
    out.to_file(OUT, driver="GeoJSON")
    print(f"wrote {OUT}: {len(out)} leases, {out['area_km2'].sum():.0f} km2")
    print(out.groupby("region")["area_km2"].agg(["count", "sum"]).round(0).to_string())


if __name__ == "__main__":
    main()
