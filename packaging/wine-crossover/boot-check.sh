#!/bin/sh
# Initializes a fresh prefix (the first wineboot can take many minutes under
# Rosetta), then starts winecfg in it and times how long its window takes to
# show. Saves a screenshot and the timings.
#
#   ./boot-check.sh <runner root> <out folder> [limit seconds, default 60]
#       [init limit seconds, default $BOOT_INIT_LIMIT or 1200]
#
# Writes <out>/winecfg.png and <out>/boot.txt, and keeps the wineboot and
# winecfg logs next to them. Exits 1 past a limit. Needs a logged-in GUI
# session (GitHub's macOS runners have one).
set -eu

here="$(cd "$(dirname "$0")" && pwd -P)"
[ $# -ge 2 ] || { echo "usage: boot-check.sh <runner root> <out folder> [limit] [init limit]" >&2; exit 2; }
root=$1 out=$2 limit=${3:-60} init_limit=${4:-${BOOT_INIT_LIMIT:-1200}}
mkdir -p "$out"

work=$(mktemp -d)
export HOME="$work/home" WINEPREFIX="$work/prefix" WINEDEBUG=-all
mkdir -p "$HOME"
cleanup() {
    "$root/bin/wineserver" -k 2>/dev/null || true
    rm -rf "$work"
}
trap cleanup EXIT

tail_log() { tail -n 30 "$1" >&2 || true; }

# Compiled first, so the compile time is not counted
swiftc -O "$here/wait-window.swift" -o "$work/wait-window"

# Programs started before the prefix install finishes fail to open windows, so
# run wineboot first under its own limit; the remaining system services don't
# keep wineserver alive, so -w returns once the install is done. mscoree stays
# on, so the bundled Wine Mono is installed (its traces are checked below).
start=$(date +%s)
(
    set +e
    WINEDEBUG=err+all,trace+mscoree,trace+appwizcpl "$root/bin/wine" wineboot -i \
        && "$root/bin/wineserver" -w
    r=$?
    touch "$work/init-done"
    exit "$r"
) > "$out/wineboot.log" 2>&1 &
init=$!
end=$(( start + init_limit ))
while [ ! -f "$work/init-done" ] && [ "$(date +%s)" -lt "$end" ]; do sleep 2; done
if [ ! -f "$work/init-done" ]; then
    "$root/bin/wineserver" -k 2>/dev/null || true
    kill "$init" 2>/dev/null || true
    wait "$init" 2>/dev/null || true
    echo "boot-check: prefix initialization did not finish within $init_limit s" >&2
    tail_log "$out/wineboot.log"
    echo "result=init-timeout init_limit=$init_limit" > "$out/boot.txt"
    exit 1
fi
rc=0
wait "$init" || rc=$?
init_seconds=$(( $(date +%s) - start ))
if [ "$rc" -ne 0 ]; then
    echo "boot-check: prefix initialization exited $rc" >&2
    tail_log "$out/wineboot.log"
    echo "result=init-failed rc=$rc" > "$out/boot.txt"
    exit 1
fi
echo "boot-check: prefix initialized in $init_seconds s"

# appwiz.cpl traces "Got URL" only on its way to the download dialog
if grep -q "mono runtime not found\|Got URL" "$out/wineboot.log" \
    || ! grep -q "mono runtime is at" "$out/wineboot.log"; then
    echo "boot-check: wineboot did not use the bundled Wine Mono" >&2
    grep "mscoree\|appwizcpl" "$out/wineboot.log" | tail -n 30 >&2 || true
    echo "result=addon-download" > "$out/boot.txt"
    exit 1
fi

WINEDEBUG=err+all "$root/bin/wine" winecfg > "$out/winecfg.log" 2>&1 &
# The loader shows up under its own name, or the program's
seconds=$("$work/wait-window" wine "$limit") || {
    echo "boot-check: no winecfg window within $limit s" >&2
    tail_log "$out/winecfg.log"
    echo "result=timeout limit=$limit" > "$out/boot.txt"
    exit 1
}
sleep 2
screencapture -x "$out/winecfg.png" || echo "boot-check: screencapture failed" >&2
echo "result=pass seconds=$seconds limit=$limit init_seconds=$init_seconds wine=$("$root/bin/wine" --version)" | tee "$out/boot.txt"
