#!/usr/bin/env python3
"""Cartouche Wine bench: cold prefix boot, small-exe start, runner size and DWARF.

Measures without touching any existing prefix and without writing into the
runner: every run uses a throwaway WINEPREFIX in a temporary work directory.
CSV goes to stdout or --csv.

    python3 bench/wine_bench.py --runner <runner-dir> [--runs N] [--csv FILE]
        [--work DIR] [--prefix-only|--exe-only|--size-only] [--keep]

Example (what produced bench/example-26.3.0-2-gpuid.csv):

    python3 bench/wine_bench.py \
        --runner "$HOME/Library/Application Support/Cartouche/runners/cartouche-wine-26.3.0-2-gpuid" \
        --runs 3 --csv bench/example-26.3.0-2-gpuid.csv
"""

import argparse
import csv
import os
import pathlib
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

BOOT_TIMEOUT = 300
EXE_TIMEOUT = 60
OBJDUMP_TIMEOUT = 30


def fail(msg):
    sys.exit(f"wine_bench: {msg}")


def run_ms(argv, env, timeout):
    start = time.monotonic()
    try:
        subprocess.run(argv, env=env, timeout=timeout,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None
    return (time.monotonic() - start) * 1000


def wine_env(prefix):
    env = dict(os.environ)
    env["WINEPREFIX"] = str(prefix)
    env["WINEDEBUG"] = "-all"
    # Keep Wine away from any real prefix or Steam path.
    for key in ("STEAM_COMPAT_DATA_PATH", "STEAM_COMPAT_CLIENT_INSTALL_PATH",
                "STEAM_COMPAT_APP_ID", "WINEPREFIX_"):
        env.pop(key, None)
    return env


def kill_wineserver(wineserver, env):
    subprocess.run([wineserver, "-k"], env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def measure_boot(wine, wineserver, work, runs):
    times = []
    for i in range(runs):
        prefix = work / f"pfx-boot-{i}"
        prefix.mkdir(parents=True, exist_ok=True)
        env = wine_env(prefix)
        ms = run_ms([wine, "wineboot", "--init"], env, BOOT_TIMEOUT)
        kill_wineserver(wineserver, env)
        if ms is None:
            fail(f"wineboot timed out on run {i + 1} (>{BOOT_TIMEOUT}s)")
        times.append(ms)
        shutil.rmtree(prefix, ignore_errors=True)
    return times


def measure_exe(wine, wineserver, work, runs):
    # One warm prefix per run set, then a cold `wineboot --end-session`
    # so each exe start pays its own wineserver bring-up.
    times = []
    for i in range(runs):
        prefix = work / f"pfx-exe-{i}"
        env = wine_env(prefix)
        if run_ms([wine, "wineboot", "--init"], env, BOOT_TIMEOUT) is None:
            fail(f"wineboot timed out preparing exe run {i + 1}")
        kill_wineserver(wineserver, env)
        ms = run_ms([wine, "cmd", "/c", "echo", "cartouche-bench"], env, EXE_TIMEOUT)
        kill_wineserver(wineserver, env)
        if ms is None:
            fail(f"test exe timed out on run {i + 1} (>{EXE_TIMEOUT}s)")
        times.append(ms)
        shutil.rmtree(prefix, ignore_errors=True)
    return times


def dwarf_bytes(path):
    try:
        out = subprocess.run(
            ["xcrun", "llvm-objdump", "-h", str(path)],
            timeout=OBJDUMP_TIMEOUT, capture_output=True, text=True,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0
    total = 0
    for line in out.splitlines():
        fields = line.split()
        if fields and fields[-1] == "DEBUG" and fields[1].startswith(".debug"):
            total += int(fields[2], 16)
    return total


def measure_size(runner):
    total = pe_total = dwarf = files = 0
    for path in runner.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        size = path.stat().st_size
        total += size
        files += 1
        if path.suffix.lower() in (".dll", ".exe"):
            pe_total += size
            dwarf += dwarf_bytes(path)
    return total, pe_total, dwarf, files


def row(runner_id, metric, values, unit):
    return {
        "runner": runner_id, "metric": metric, "runs": len(values),
        "unit": unit,
        "min": f"{min(values):.1f}", "median": f"{statistics.median(values):.1f}",
        "max": f"{max(values):.1f}",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runner", required=True, type=pathlib.Path,
                    help="installed runner directory (read-only)")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--csv", type=pathlib.Path)
    ap.add_argument("--work", type=pathlib.Path,
                    help="work directory for throwaway prefixes (default: mktemp)")
    ap.add_argument("--keep", action="store_true", help="keep the work directory")
    ap.add_argument("--prefix-only", action="store_true")
    ap.add_argument("--exe-only", action="store_true")
    ap.add_argument("--size-only", action="store_true")
    args = ap.parse_args()

    runner = args.runner.resolve()
    wine = runner / "bin" / "wine"
    wineserver = runner / "bin" / "wineserver"
    if not wine.is_file():
        fail(f"no bin/wine under {runner}")
    only = {n for n in ("prefix", "exe", "size")
            if getattr(args, f"{n}_only")}
    do = set(only) if only else {"prefix", "exe", "size"}

    work = args.work or pathlib.Path(tempfile.mkdtemp(prefix="cartouche-bench-"))
    work.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        if "prefix" in do:
            rows.append(row(runner.name, "prefix_boot_ms",
                            measure_boot(str(wine), str(wineserver), work, args.runs), "ms"))
        if "exe" in do:
            rows.append(row(runner.name, "exe_start_ms",
                            measure_exe(str(wine), str(wineserver), work, args.runs), "ms"))
        if "size" in do:
            total, pe_total, dwarf, files = measure_size(runner)
            rows += [
                row(runner.name, "runner_bytes", [total], "B"),
                row(runner.name, "runner_pe_bytes", [pe_total], "B"),
                row(runner.name, "runner_dwarf_bytes", [dwarf], "B"),
                row(runner.name, "runner_dwarf_pct", [dwarf / total * 100 if total else 0], "%"),
                row(runner.name, "runner_files", [files], "count"),
            ]
    finally:
        if not args.keep and not args.work:
            shutil.rmtree(work, ignore_errors=True)

    out = args.csv.open("w", newline="") if args.csv else sys.stdout
    with out:
        writer = csv.DictWriter(out, fieldnames=["runner", "metric", "runs", "unit", "min", "median", "max"])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
