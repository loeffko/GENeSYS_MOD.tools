"""One-off: move an old output/ folder to the current layout.

    output/{timeframe}/            timeseries {timeframe}_{name}_{series}.csv
    output/{timeframe}/tiles/      per-tile timeseries of run_batch_by_tile
    output/coords/[tiles|scenarios/<s>]/       usable-site coords (year-agnostic)
    output/potentials/[tiles|scenarios/<s>]/   potentials (year-agnostic)

What it does, per timeframe folder:
  - renames {tf}_{series}_{name}.csv -> {tf}_{name}_{series}.csv for the heat
    series (temperature, heating, cooling, heatpump_cop, heatpump_ground_cop)
  - moves *_coords_* to output/coords/ and *_potentials_* / *_wind_filter_scenarios.*
    to output/potentials/ (scenario runs keep their scenarios/<s>/ subfolder)
  - moves per-tile files of batch runs (names {base}_{tile}_..., tiles below) into
    the tiles/ subfolders
Coords and potentials are year-agnostic, so the same file can come from several
timeframe folders: identical copies collapse to one, otherwise the newest wins.
Idempotent; run with --dry-run first to see the plan.

    python migrate_output_layout.py [--dry-run] [output_root]
"""
import os
import re
import sys
import filecmp
import shutil

# Batch tiles as named in the EU / APAC notebooks' TILES dicts (+ retired names).
TILES = {
    "europe": ["iberia", "france_bnl", "british_isles", "central", "nordics", "italy_alps",
               "balkans", "baltics", "east", "turkey_levant", "turkey_nb", "central_asia"],
    "apac": ["mainland_sea", "maritime_sea", "philippines", "east_asia", "south_asia",
             "australia", "new_zealand", "png"],
}
HEAT = ["heatpump_ground_cop", "heatpump_cop", "temperature", "heating", "cooling"]
YEAR_AGNOSTIC = ("coords", "potentials", "zip_transfer")


def tile_of(name):
    """True if a run name ('europe_central', 'europe_central_usable', ...) is per-tile."""
    for base, tiles in TILES.items():
        for t in sorted(tiles, key=len, reverse=True):
            if name == f"{base}_{t}" or name.startswith(f"{base}_{t}_"):
                return True
    return False


def plan_moves(root):
    moves = []
    for tf in sorted(os.listdir(root)):
        tf_dir = os.path.join(root, tf)
        if tf in YEAR_AGNOSTIC or not os.path.isdir(tf_dir):
            continue
        for dirpath, _, files in os.walk(tf_dir):
            rel = os.path.relpath(dirpath, tf_dir).replace("\\", "/")
            if rel.split("/")[0] == "tiles":
                continue
            # scenario runs: {tf}/scenarios/<s>/ (and the old {tf}/scenarios/coords/)
            scen = rel[len("scenarios/"):] if rel.startswith("scenarios/") else ""
            for f in files:
                src = os.path.join(dirpath, f)
                name = f
                m = re.match(rf"^{re.escape(tf)}_({'|'.join(HEAT)})_(.+)\.csv$", f)
                if m and m.group(2) != "raw":
                    name = f"{tf}_{m.group(2)}_{m.group(1)}.csv"
                if "_coords_" in f or scen == "coords":
                    sub = "tiles" if tile_of(f.split("_coords_")[0]) else (
                        "scenarios" if scen == "coords" else f"scenarios/{scen}" if scen else "")
                    dst = os.path.join(root, "coords", sub, name)
                elif "_potentials_" in f or "_wind_filter_scenarios." in f:
                    run = re.split(r"_potentials_|_wind_filter_scenarios\.", f)[0]
                    sub = "tiles" if tile_of(run) else (f"scenarios/{scen}" if scen else "")
                    dst = os.path.join(root, "potentials", sub, name)
                else:
                    m2 = re.match(rf"^{re.escape(tf)}_(.+)\.csv$", name)
                    in_tile = m2 is not None and tile_of(m2.group(1))
                    dst = os.path.join(tf_dir, "tiles" if in_tile else rel, name)
                dst = os.path.normpath(dst)
                if os.path.normpath(src) != dst:
                    moves.append((src, dst))
    return moves


def main():
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv
    root = args[0] if args else "output"
    moves = plan_moves(root)
    stats = {"moved": 0, "duplicate dropped": 0, "older dropped": 0, "replaced older": 0}
    for src, dst in moves:
        if dry:
            print(f"{os.path.relpath(src, root)}  ->  {os.path.relpath(dst, root)}")
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            if filecmp.cmp(src, dst, shallow=False):
                os.remove(src); stats["duplicate dropped"] += 1
            elif os.path.getmtime(src) > os.path.getmtime(dst):
                shutil.move(src, dst + ".tmp"); os.replace(dst + ".tmp", dst)
                stats["replaced older"] += 1
            else:
                os.remove(src); stats["older dropped"] += 1
        else:
            shutil.move(src, dst); stats["moved"] += 1
    if not dry:
        # remove folders emptied by the move (e.g. old scenarios/ trees)
        for dirpath, dirs, files in sorted(os.walk(root), key=lambda w: -len(w[0])):
            if dirpath != root and not os.listdir(dirpath):
                os.rmdir(dirpath)
    print(f"{len(moves)} planned" + ("" if dry else f": {stats}"))


if __name__ == "__main__":
    main()
