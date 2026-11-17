"""Check the PV capacity-factor cap (PV_CF_MAX, cap_pv_series, cap_pv_series_file).

Runs without a cutout, in a temporary folder, and prints one line per check:
  - cap_pv_series on a synthetic frame (above 1, exactly 1, NaN, negative; None = off)
  - pivot_and_categorize: PV (pv, horizontal) capped, onshore wind not
  - cap_pv_series_file on a synthetic file gives byte for byte what the writer writes
  - create_transfer_zip packs PV capped, wind as is, manifest unit and pv_cf_max
  - optional: real series CSVs given as arguments. Each is copied to the temporary
    folder (the given file is never changed) and capped there; only fields above 1
    may differ, they become '1.0', the result equals reading the file and writing it
    again through cap_pv_series + to_csv, and a file without a value above 1 stays
    byte-identical.

    python check_pv_cap.py [series.csv ...]

Exit code 1 if a check fails.
"""
import os
import sys
import shutil
import tempfile
import zipfile
import json

import numpy as np
import pandas as pd

import functions as fn

FAILED = []


def check(name, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + name + (f": {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def synthetic_frame():
    idx = pd.date_range("2018-06-21 10:00", periods=4, freq="h", name="time")
    return pd.DataFrame({"AA": [1.2, 1.0, np.nan, -0.01],
                         "BB": [0.5, 1.0000001, 0.123456789, 0.0],
                         "CC": [np.nan, np.nan, 2.0, 0.9999]}, index=idx)


def check_helper():
    df = synthetic_frame()
    out = fn.cap_pv_series(df)
    exp = pd.DataFrame({"AA": [1.0, 1.0, np.nan, -0.01],
                        "BB": [0.5, 1.0, 0.123456789, 0.0],
                        "CC": [np.nan, np.nan, 1.0, 0.9999]}, index=df.index)
    check("cap_pv_series caps above 1, keeps 1, NaN, negative and the rest",
          out.equals(exp), f"max {np.nanmax(out.values)}")
    keep = df.le(1.0)
    check("cap_pv_series leaves values at or below 1 bit-identical",
          (out[keep] == df[keep]).sum().sum() == keep.sum().sum())
    check("cap_pv_series(pv_cf_max=None) returns the frame unchanged",
          fn.cap_pv_series(df, None).equals(df))
    check("PV_CF_MAX is 1.0", fn.PV_CF_MAX == 1.0)
    fams = {"pv_inf": True, "usable_pv_opt": True, "usable_pv_rooftop_commercial": True,
            "pv_horizontal": True, "wind_onshore_inf": False,
            "usable_wind_offshore_deep": False, "heating": False, "temperature": False}
    check("_is_pv_family tells PV from wind and heat families",
          all(fn._is_pv_family(f) == v for f, v in fams.items()))


def check_pivot(tmp):
    # long frame: two cells per region, 3 hours; cell values above 1 in region AA
    t = pd.date_range("2018-06-21 10:00", periods=3, freq="h")
    rows = []
    for h, ts in enumerate(t):
        for c, base in (("1, 1", 1.05), ("1, 2", 1.01), ("2, 1", 0.4), ("2, 2", 0.6)):
            rows.append({"time": ts, "coords": c, "capacity_factor": base - 0.1 * h,
                         "region": "AA" if c.startswith("1") else "BB"})
    long = pd.DataFrame(rows)
    inf, avg, opt = fn.pivot_and_categorize(long, "pv", timeframe="2018", filename="chk",
                                            output_dir=tmp)
    on_disk = pd.read_csv(os.path.join(tmp, "2018_chk_pv_opt.csv"), index_col=0)
    check("pivot_and_categorize pv: written series capped",
          float(on_disk.max().max()) == 1.0 and float(opt.max().max()) == 1.0,
          f"max written {on_disk.max().max()}")
    inf_u, _, opt_u = fn.pivot_and_categorize(long, "pv", timeframe="2018", filename="chk_off",
                                              output_dir=tmp, pv_cf_max=None)
    check("pivot_and_categorize pv, pv_cf_max=None: uncapped",
          float(opt_u.max().max()) > 1.0, f"max {opt_u.max().max()}")
    w_inf, w_avg, w_opt = fn.pivot_and_categorize(long, "wind_onshore", timeframe="2018",
                                                  filename="chk", output_dir=tmp)
    check("pivot_and_categorize wind_onshore: not capped",
          float(w_opt.max().max()) > 1.0, f"max {w_opt.max().max()}")
    hor = fn.pivot_and_categorize(long, "horizontal", timeframe="2018", filename="chk",
                                  output_dir=tmp)
    check("pivot_and_categorize horizontal: capped", float(hor.max().max()) <= 1.0,
          f"max {hor.max().max()}")


def check_file_inplace(tmp):
    df = synthetic_frame()
    raw = os.path.join(tmp, "2018_syn_usable_pv_opt.csv")
    df.to_csv(raw)                                   # as written before the cap
    ref = os.path.join(tmp, "ref.csv")
    fn.cap_pv_series(df).to_csv(ref)                 # as the writer writes now
    n = fn.cap_pv_series_file(raw)
    same = open(raw, "rb").read() == open(ref, "rb").read()
    check("cap_pv_series_file on a synthetic file equals the capped writer output",
          same and n == 3, f"{n} values capped")
    n2 = fn.cap_pv_series_file(raw)
    check("cap_pv_series_file is idempotent", n2 == 0 and open(raw, "rb").read() == open(ref, "rb").read())
    # wind, heat and per-cell raw files are refused and left as they are
    for other in ("2018_syn_heating.csv", "2018_syn_usable_wind_onshore_opt.csv",
                  "2018_syn_pv_opt_raw.csv"):
        p = os.path.join(tmp, other)
        df.to_csv(p)
        before = open(p, "rb").read()
        try:
            fn.cap_pv_series_file(p)
            refused = False
        except ValueError:
            refused = True
        check(f"cap_pv_series_file refuses {other} and leaves it unchanged",
              refused and open(p, "rb").read() == before)


def check_zip(tmp):
    root = os.path.join(tmp, "output")
    os.makedirs(os.path.join(root, "2018"))
    df = synthetic_frame()
    df.to_csv(os.path.join(root, "2018", "2018_syn_usable_pv_opt.csv"))
    df.to_csv(os.path.join(root, "2018", "2018_syn_usable_pv_inf.csv"))
    df.clip(upper=1.0).to_csv(os.path.join(root, "2018", "2018_syn_usable_pv_avg.csv"))
    df.to_csv(os.path.join(root, "2018", "2018_syn_usable_wind_onshore_opt.csv"))
    src_before = open(os.path.join(root, "2018", "2018_syn_usable_pv_opt.csv"), "rb").read()
    zp = fn.create_transfer_zip("syn", "2018", output_root=root)
    with zipfile.ZipFile(zp) as z:
        man = json.loads(z.read("manifest.json"))
        pv_opt = z.read("profiles/2018_syn_usable_pv_opt.csv")
        pv_avg = z.read("profiles/2018_syn_usable_pv_avg.csv")
        wind = z.read("profiles/2018_syn_usable_wind_onshore_opt.csv")
    ref = os.path.join(tmp, "zipref.csv")
    fn.cap_pv_series(df).to_csv(ref)
    units = {f["unit"] for f in man["files"] if f["series"].startswith("pv_")}
    check("zip: PV profile packed capped", pv_opt == open(ref, "rb").read())
    check("zip: PV profile without a value above 1 packed byte-identical",
          pv_avg == open(os.path.join(root, "2018", "2018_syn_usable_pv_avg.csv"), "rb").read())
    check("zip: wind profile packed as is (not capped)",
          wind == open(os.path.join(root, "2018", "2018_syn_usable_wind_onshore_opt.csv"), "rb").read())
    check("zip: source file on disk unchanged",
          src_before == open(os.path.join(root, "2018", "2018_syn_usable_pv_opt.csv"), "rb").read())
    check("zip: one PV unit text, the constant", units == {fn._PV_CF_UNIT}, str(units))
    check("zip: manifest pv_cf_max", man.get("pv_cf_max") == 1.0, str(man.get("pv_cf_max")))


def check_real(tmp, path):
    name = os.path.basename(path)
    work = os.path.join(tmp, "real_" + name)
    shutil.copyfile(path, work)
    orig = open(path, "rb").read()
    df = pd.read_csv(path, index_col=0, float_precision="round_trip")
    above = int((df.to_numpy(dtype=float) > 1.0).sum())
    # the writer's format reproduces the file (index, header, float text, line ends)
    rt = os.path.join(tmp, "rt_" + name)
    df.to_csv(rt)
    check(f"{name}: read + to_csv reproduces the file byte for byte",
          open(rt, "rb").read() == orig)
    n = fn.cap_pv_series_file(work)
    new = open(work, "rb").read()
    ref = os.path.join(tmp, "ref_" + name)
    fn.cap_pv_series(df).to_csv(ref)
    check(f"{name}: capped file equals cap_pv_series + to_csv of the file",
          new == open(ref, "rb").read(), f"{n} values capped, {above} above 1 before")
    nl = b"\r\n" if b"\r\n" in orig else b"\n"
    a, b = orig.split(nl), new.split(nl)
    diffs, bad = 0, 0
    for la, lb in zip(a, b):
        if la == lb:
            continue
        for ca, cb in zip(la.split(b","), lb.split(b",")):
            if ca != cb:
                diffs += 1
                if not (float(ca) > 1.0 and cb == b"1.0"):
                    bad += 1
    check(f"{name}: only values above 1 differ, each now '1.0'",
          len(a) == len(b) and diffs == above and bad == 0,
          f"{diffs} fields differ, {len(a) - 1} lines, line ending {nl!r}")
    if above == 0:
        check(f"{name}: no value above 1, byte-identical", new == orig)
    cap_after = pd.read_csv(work, index_col=0)
    check(f"{name}: max after cap", float(np.nanmax(cap_after.to_numpy(dtype=float))) <= 1.0,
          f"max before {np.nanmax(df.to_numpy(dtype=float))}, "
          f"after {np.nanmax(cap_after.to_numpy(dtype=float))}")


def main():
    tmp = tempfile.mkdtemp(prefix="pv_cap_check_")
    try:
        check_helper()
        check_pivot(tmp)
        check_file_inplace(tmp)
        check_zip(tmp)
        for p in sys.argv[1:]:
            check_real(tmp, p)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(FAILED)} check(s) failed" if FAILED else "\nall checks passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
