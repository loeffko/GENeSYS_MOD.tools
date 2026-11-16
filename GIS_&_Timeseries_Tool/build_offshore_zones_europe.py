"""Build the offshore wind zones for the Europe hub, for calibrate_offshore_sites.

Writes geodata/offshore/offshore_zones_europe.geojson (EPSG:4326), one dissolved
(multi)polygon per hub region, with columns: region, source, area_km2, geometry.

Sources (EMODnet Human Activities WFS, https://ows.emodnet-humanactivities.eu/wfs, no
auth; raw downloads cached in geodata/_cache/emodnet/):

- emodnet:mspzoningpoly, the member states' maritime spatial plans. Use 'Wind Farms'
  (and 'Ocean Energy Facilities', which holds Belgium's Princess Elisabeth zone and
  Lithuania's wind area), function Priority / Reserved / Potential / Allowed or untagged;
  Latvia's 'Forbidden' and 'Restricted' polygons are dropped. Covers BE DK EE FI DE IT
  LV LT NL PL ES SE. For these countries, wind farm polygons are added only where built,
  under construction or approved (their 'Planned' polygons include developer
  applications, e.g. 86 GW in Sweden).
- emodnet:windfarmspoly, wind farm polygons by status. For the countries without a
  spatial plan in the MSP layer (GB, FR, IE, PT) every status except Dismantled counts:
  the UK's are Crown Estate (Scotland) lease sites, France's the tendered zones.

Each region's polygons are dissolved (zones must not overlap) and clipped to that
region's own EEZ (geodata/offshore/eez_europe.geojson). Not covered: Norway, Italy
beyond its two MSP areas, Greece, the Black Sea, Turkey and the Western Balkans (no
polygons in EMODnet); those regions are calibrated on their EEZ alone.
"""
import json
import os
import urllib.parse
import urllib.request

import geopandas as gpd
import pandas as pd
from shapely.validation import make_valid

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "geodata", "_cache", "emodnet")
EEZ = os.path.join(HERE, "geodata", "offshore", "eez_europe.geojson")
OUT = os.path.join(HERE, "geodata", "offshore", "offshore_zones_europe.geojson")
WFS = "https://ows.emodnet-humanactivities.eu/wfs"

NAME_TO_ISO2 = {
    "Belgium": "BE", "Denmark": "DK", "Estonia": "EE", "Finland": "FI", "France": "FR",
    "Germany": "DE", "Ireland": "IE", "Italy": "IT", "Latvia": "LV", "Lithuania": "LT",
    "Netherlands": "NL", "Poland": "PL", "Portugal": "PT", "Spain": "ES", "Sweden": "SE",
    "United Kingdom": "GB",
}
MSP_USES = ("Wind Farms", "Ocean Energy Facilities")
MSP_DROP_FUNCTIONS = {"Forbidden", "Restricted"}
BUILT = {"Production", "Construction", "Approved"}


def fetch(layer, out, cql=None):
    """GetFeature as GeoJSON, cached."""
    path = os.path.join(CACHE, out)
    if os.path.exists(path):
        return gpd.read_file(path)
    os.makedirs(CACHE, exist_ok=True)
    q = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
         "typeNames": layer, "outputFormat": "application/json"}
    if cql:
        q["CQL_FILTER"] = cql
    url = WFS + "?" + urllib.parse.urlencode(q)
    print(f"download {layer} ...")
    with urllib.request.urlopen(url, timeout=600) as r:
        data = json.load(r)
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(path + ".part", path)
    return gpd.read_file(path)


def main():
    uses = "','".join(MSP_USES)
    msp = fetch("emodnet:mspzoningpoly", "msp_wind_zones.geojson", f"seausename IN ('{uses}')")
    wf = fetch("emodnet:windfarmspoly", "windfarmspoly.geojson")

    msp = msp[~msp["seausefct"].isin(MSP_DROP_FUNCTIONS)].copy()
    msp["region"] = msp["ms"].map(NAME_TO_ISO2)
    msp["source"] = "EMODnet MSP " + msp["seausename"] + " / " + msp["seausefct"].fillna("untagged")
    msp_regions = set(msp["region"].dropna())

    wf["region"] = wf["country"].map(NAME_TO_ISO2)
    keep = wf["status"].isin(BUILT) | (~wf["region"].isin(msp_regions)
                                      & (wf["status"] != "Dismantled"))
    wf = wf[keep].copy()
    wf["source"] = "EMODnet wind farms / " + wf["status"]

    z = pd.concat([msp[["region", "source", "geometry"]], wf[["region", "source", "geometry"]]],
                  ignore_index=True)
    z = gpd.GeoDataFrame(z, geometry="geometry", crs=msp.crs).to_crs("EPSG:4326")
    unknown = sorted(set(msp["ms"][msp["region"].isna()]) | set(wf["country"][wf["region"].isna()]))
    if unknown:
        print(f"Note: no region code for {unknown}, skipped")
    z = z[z["region"].notna()].copy()
    z["geometry"] = z.geometry.apply(make_valid)

    eez = gpd.read_file(EEZ).to_crs("EPSG:4326")
    rows = []
    for reg, g in z.groupby("region"):
        geom = g.geometry.union_all()
        own = eez[eez["region"] == reg].geometry.union_all()
        geom = geom.intersection(own)
        if geom.is_empty:
            print(f"{reg}: no zone area inside its EEZ, skipped")
            continue
        rows.append({"region": reg, "source": "; ".join(sorted(set(g["source"]))),
                     "geometry": geom})
    out = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    out["area_km2"] = (out.to_crs("EPSG:3035").area / 1e6).round(0)
    out = out[["region", "source", "area_km2", "geometry"]]
    if os.path.exists(OUT):
        os.remove(OUT)
    out.to_file(OUT, driver="GeoJSON")
    print(f"wrote {OUT}: {len(out)} regions, {os.path.getsize(OUT) / 1e6:.1f} MB")
    print(out[["region", "area_km2"]].to_string(index=False))


if __name__ == "__main__":
    main()
