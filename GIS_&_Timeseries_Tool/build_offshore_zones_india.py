"""Build the designated offshore wind zones for India, for the RES tool's zone mode.

Writes geodata/offshore/offshore_zones_india.geojson (EPSG:4326), one polygon per zone
or site, with columns: name, state, kind, share, area_km2, source.

Source: MNRE, "Strategy for Establishment of Offshore Wind Energy Projects", Revision 02,
26 Sept 2023 (https://cdnbbsr.s3waas.gov.in/s3716e1b8c6cd17b771da77391355749f3/uploads/
2023/09/202309271030958532.pdf).

- Tamil Nadu, kind "site": the 14 lease blocks off Kanyakumari, from the boundary
  coordinates in Annexure I (site 1, VGF model) and Annexure II (sites 2-14, Model B,
  3,409 km2 / 15.3 GW at 4.5 MW/km2). They cover NIWE zones B, D, E and G. share = 1.
- Gujarat, kind "site": zone B3 (365 km2, Model A / VGF), from Annexure I.
- Gujarat, kind "zone": NIWE zones A, B, D, E, F in the Gulf of Khambhat. No coordinates
  are published, so they are digitized from the document's Fig. 2 (colour segmentation,
  georeferenced on six town markers, RMS error 2.1 km, i.e. far below a ~30 km ERA5
  cell). Zone B excludes B3. `share` scales the outlines so the five zones hold NIWE's
  ~36 GW Gujarat estimate at 4.5 MW/km2 (the outlines are coarse and include shipping
  lanes and oil & gas areas).

Not included: Tamil Nadu zones A and C (no published coordinates; about 1,300 km2) and
F, G, H north of Rameswaram (not cleared by the Ministry of Defence, per Fig. 1), and any
Sri Lankan zones.
"""
import os
import geopandas as gpd
from shapely.geometry import Polygon

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "geodata", "offshore", "offshore_zones_india.geojson")
SOURCE = "MNRE Strategy for Establishment of Offshore Wind Energy Projects, Rev. 02 (2023-09-26)"
DENSITY = 4.5          # MW/km2, MNRE's lowest density assumption
GUJARAT_GW = 36.0      # NIWE estimate for the Gujarat zones


def dms(s):
    d, m, sec = (float(v) for v in s.split())
    return d + m / 60 + sec / 3600


def poly(points):
    """points: [(lat 'd m s', lon 'd m s'), ...] -> Polygon(lon, lat)."""
    return Polygon([(dms(lon), dms(lat)) for lat, lon in points])


# Boundary points (latitude N, longitude E) as printed in the annexures.
TN_SITES = {
    1: [("07 58 55.18210279", "077 37 12.02065596"), ("08 03 43.86189371", "077 38 44.11998271"),
        ("08 03 47.08469163", "077 40 52.99759552"), ("07 52 13.83103455", "077 44 37.29375890"),
        ("07 49 28.65104409", "077 39 55.45169623")],
    2: [("08 03 47.72371698", "077 41 35.96290002"), ("08 03 57.00346702", "077 47 33.44613731"),
        ("07 55 30.88471532", "077 50 33.38988611"), ("07 52 36.82018998", "077 45 22.52165955")],
    3: [("08 04 02.28905987", "077 48 31.78896036"), ("08 09 24.80536546", "077 52 46.05191377"),
        ("07 59 16.22684932", "077 57 15.96460351"), ("07 56 03.13526471", "077 51 25.35945949")],
    4: [("08 09 49.11076938", "077 53 23.24046568"), ("08 12 24.25027828", "077 58 05.34119981"),
        ("08 02 31.37124854", "078 03 04.96530421"), ("07 59 44.48055006", "077 58 06.18390086")],
    5: [("08 00 54.28839758", "077 27 28.85848997"), ("08 00 51.98256744", "077 28 05.21346003"),
        ("07 58 52.04896032", "077 29 59.87801480"), ("07 58 40.63219616", "077 32 35.74430290"),
        ("07 48 24.59450207", "077 32 37.03942199"), ("07 51 44.61656638", "077 25 23.96926039")],
    6: [("07 58 34.68200788", "077 33 14.61680538"), ("07 58 17.20337524", "077 35 41.67334128"),
        ("07 58 21.81288230", "077 36 24.53319668"), ("07 58 31.30960553", "077 36 39.64314789"),
        ("07 44 41.47105107", "077 40 24.82125405"), ("07 48 02.20013345", "077 33 21.42063696")],
    7: [("08 12 37.91193679", "077 58 43.82592826"), ("08 15 13.82133421", "078 03 29.58241167"),
        ("08 05 44.39836787", "078 08 50.79919045"), ("08 02 53.41435470", "078 03 48.41315508")],
    8: [("07 58 30.33143998", "077 16 09.04137618"), ("07 59 48.90680417", "077 20 17.27000005"),
        ("08 01 18.75414078", "077 23 13.62068673"), ("08 00 59.11329808", "077 26 44.47382096"),
        ("07 52 01.20573916", "077 24 41.79192222"), ("07 56 14.08341944", "077 15 41.55617817")],
    9: [("08 15 32.11071367", "078 04 09.70559677"), ("08 18 19.61987184", "078 08 46.46421194"),
        ("08 08 47.45387218", "078 14 24.36867201"), ("08 06 03.12614358", "078 09 34.83845947")],
    10: [("08 18 23.15699062", "078 09 35.96920951"), ("08 18 14.42777667", "078 15 19.56389762"),
         ("08 16 58.29950502", "078 15 58.43976767"), ("08 16 35.99457199", "078 19 50.27896696"),
         ("08 07 24.39370128", "078 17 36.59823722"), ("08 06 17.24001953", "078 16 50.73123357")],
    11: [("08 08 11.29589253", "078 14 41.63988006"), ("08 05 35.73940718", "078 16 19.33342989"),
         ("08 04 57.98614800", "078 16 19.91835497"), ("08 02 04.14643594", "078 16 16.18655536"),
         ("08 00 54.11863666", "078 14 55.90246981"), ("07 59 37.46750361", "078 14 24.96798289"),
         ("07 58 11.41121293", "078 14 07.99840949"), ("07 55 58.77516874", "078 12 09.19398588"),
         ("07 54 03.97912806", "078 09 55.16064656"), ("07 52 54.98392620", "078 09 34.27230090"),
         ("08 02 19.25746235", "078 04 06.08348106")],
    12: [("08 01 53.69961989", "078 03 23.51782678"), ("07 52 09.77104527", "078 09 08.42430667"),
         ("07 51 43.20657021", "078 08 55.42343941"), ("07 48 32.77760265", "078 07 53.47208800"),
         ("07 47 53.58829271", "078 06 53.14223854"), ("07 47 19.73490903", "078 05 19.93768282"),
         ("07 43 51.63507155", "078 04 17.89437024"), ("07 42 27.68109495", "078 03 58.87786307"),
         ("07 42 20.21797023", "078 02 26.82989813"), ("07 59 04.36545731", "077 58 31.70175866")],
    13: [("07 48 45.60025502", "077 40 05.49019943"), ("07 54 48.57062926", "077 50 51.74206470"),
         ("07 38 50.89710540", "077 54 06.93520381"), ("07 38 42.17315576", "077 53 56.34085329"),
         ("07 38 30.09624334", "077 53 44.04326774"), ("07 38 30.06784593", "077 53 38.24126067"),
         ("07 44 12.95618121", "077 41 19.38420765")],
    14: [("07 55 11.79361368", "077 51 38.92752112"), ("07 58 31.56061750", "077 57 38.18124271"),
         ("07 41 26.83772139", "078 01 29.03317188"), ("07 40 25.46633473", "078 00 25.86779902"),
         ("07 39 03.21925376", "077 59 02.82007333"), ("07 38 59.70350976", "077 58 59.47243427"),
         ("07 38 56.08406121", "077 58 55.69638254"), ("07 37 30.77144500", "077 57 18.49450152"),
         ("07 37 00.78265983", "077 56 47.66308208"), ("07 37 49.90206152", "077 55 05.94017387")],
}
# Published seabed areas (km2), Annexure II; site 1 has none printed.
TN_AREA = {2: 203, 3: 209, 4: 208, 5: 207, 6: 204, 7: 208, 8: 204, 9: 204, 10: 203,
           11: 329, 12: 380, 13: 425, 14: 425}

GJ_B3 = [("20 35 23.4724", "71 39 36.0604"), ("20 35 40.3142", "71 42 48.9256"),
         ("20 37 8.6836", "71 46 32.2712"), ("20 38 33.8318", "71 48 27.8889"),
         ("20 44 35.4573", "71 48 27.0911"), ("20 50 2.6047", "71 48 26.4892"),
         ("20 50 2.4566", "71 51 34.0013"), ("20 51 38.8328", "71 50 51.3695"),
         ("20 53 11.1231", "71 49 52.7061"), ("20 51 17.5642", "71 46 54.6909"),
         ("20 49 9.3229", "71 43 30.8629"), ("20 46 42.3267", "71 39 35.7641"),
         ("20 43 16.9636", "71 39 35.0917"), ("20 38 36.9260", "71 39 36.6028")]

# Digitized from Fig. 2 (lon, lat), simplified to ~400 m.
GJ_ZONES = {
    "A": [(71.589, 20.214), (71.48, 20.234), (71.154, 20.337), (71.045, 20.378), (71.069, 20.407),
          (71.46, 20.645), (71.575, 20.709), (71.589, 20.706)],
    "B": [(72.133, 21.107), (71.932, 20.953), (71.935, 20.937), (71.922, 20.924), (71.908, 20.931),
          (71.81, 20.851), (71.796, 20.851), (71.684, 20.777), (71.681, 20.359), (71.698, 20.337),
          (71.728, 20.337), (71.806, 20.308), (71.83, 20.317), (71.82, 20.812), (71.834, 20.825),
          (72.136, 20.831), (72.15, 20.818), (72.153, 20.568), (71.956, 20.372), (71.963, 20.356),
          (72.228, 20.494), (72.258, 20.571), (72.35, 20.738), (72.377, 20.812), (72.167, 21.091),
          (72.153, 21.107)],
    "D": [(72.391, 20.259), (72.207, 20.452), (72.404, 20.793), (72.574, 20.979), (72.652, 20.985),
          (72.748, 20.626), (72.425, 20.279), (72.404, 20.259)],
    "E": [(72.167, 20.449), (71.854, 20.292), (71.704, 20.327), (71.684, 20.324), (71.684, 20.176),
          (72.313, 19.989), (72.36, 20.118), (72.353, 20.134), (72.374, 20.153), (72.391, 20.214)],
    "F": [(72.493, 21.577), (72.466, 21.567), (72.35, 21.462), (72.333, 21.414), (72.296, 21.363),
          (72.296, 21.347), (72.173, 21.132), (72.18, 21.107), (72.404, 20.818), (72.537, 20.931),
          (72.554, 21.004), (72.544, 21.567)],
}


def main():
    rows = [{"name": f"TN site {k}", "state": "Tamil Nadu", "kind": "site", "share": 1.0,
             "geometry": poly(v)} for k, v in TN_SITES.items()]
    b3 = poly(GJ_B3)
    rows.append({"name": "GJ B3", "state": "Gujarat", "kind": "site", "share": 1.0, "geometry": b3})
    taken = b3
    for z, pts in GJ_ZONES.items():
        g = Polygon(pts).difference(taken)          # keep zones disjoint (B3, digitizing overlaps)
        taken = taken.union(g)
        rows.append({"name": f"GJ zone {z}", "state": "Gujarat", "kind": "zone", "share": None,
                     "geometry": g})
    out = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    out["area_km2"] = (out.to_crs(out.estimate_utm_crs()).area / 1e6).round(1)
    out["source"] = [SOURCE + (", Fig. 2 (digitized)" if k == "zone" else ", Annexure I/II")
                     for k in out["kind"]]

    zones = out["kind"] == "zone"
    share = GUJARAT_GW * 1000 / (DENSITY * out.loc[zones, "area_km2"].sum())
    out.loc[zones, "share"] = round(share, 3)

    for k, a in TN_AREA.items():
        got = out.loc[out["name"] == f"TN site {k}", "area_km2"].iloc[0]
        assert abs(got - a) / a < 0.05, f"TN site {k}: {got} km2 vs published {a} km2"
    overlap = out.geometry.unary_union.area - out.geometry.area.sum()
    assert abs(overlap) < 1e-9, "zones overlap"

    if os.path.exists(OUT):
        os.remove(OUT)
    out[["name", "state", "kind", "share", "area_km2", "source", "geometry"]].to_file(OUT, driver="GeoJSON")
    cap = out["area_km2"] * out["share"] * DENSITY / 1000
    print(out.assign(gw=cap.round(2))[["name", "kind", "share", "area_km2", "gw"]].to_string(index=False))
    print(f"wrote {OUT}: {len(out)} polygons; at {DENSITY} MW/km2: "
          + ", ".join(f"{s} {g:.1f} GW" for s, g in cap.groupby(out["state"]).sum().items()))


if __name__ == "__main__":
    main()
