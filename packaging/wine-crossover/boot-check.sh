#!/bin/sh
# Initializes a fresh prefix (the first wineboot can take many minutes under
# Rosetta) and checks that it works: wineboot finishes with the bundled Wine
# Mono, the registry files are written, and console programs run. With a GUI
# session it then times how long winecfg's window takes to show and saves a
# screenshot; without one (a headless runner) that part is skipped.
#
#   ./boot-check.sh <runner root> <out folder> [window limit seconds, default 180]
#       [init limit seconds, default $BOOT_INIT_LIMIT or 1200]
#
# BOOT_GUI=1 or 0 forces the window check on or off; by default it runs when
# launchctl reports an Aqua session. Writes <out>/boot.txt and keeps the logs
# (and winecfg.png) next to it. Exits 1 on any failed check.
set -eu

here="$(cd "$(dirname "$0")" && pwd -P)"
[ $# -ge 2 ] || { echo "usage: boot-check.sh <runner root> <out folder> [limit] [init limit]" >&2; exit 2; }
root=$1 out=$2 limit=${3:-180} init_limit=${4:-${BOOT_INIT_LIMIT:-1200}}
cmd_limit=${BOOT_CMD_LIMIT:-300}
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
fail() {
    result=$1 log=$2
    shift 2
    echo "boot-check: $*" >&2
    [ -z "$log" ] || tail_log "$log"
    echo "result=$result" > "$out/boot.txt"
    exit 1
}

# Runs a command with its output in a log and a time limit; 124 past the limit.
# macOS has no timeout(1).
limited() {
    secs=$1 log=$2
    shift 2
    rm -f "$work/overran"
    "$@" > "$log" 2>&1 &
    pid=$!
    (
        n=0
        while kill -0 "$pid" 2>/dev/null; do
            if [ "$n" -ge "$secs" ]; then touch "$work/overran"; kill "$pid"; exit 0; fi
            sleep 1
            n=$(( n + 1 ))
        done
    ) > /dev/null 2>&1 &
    dog=$!
    rc=0
    wait "$pid" || rc=$?
    wait "$dog" 2>/dev/null || true
    if [ -f "$work/overran" ]; then return 124; fi
    return "$rc"
}

case "${BOOT_GUI:-auto}" in
    1) gui=1 ;;
    0) gui= ;;
    *) if [ "$(launchctl managername 2>/dev/null)" = Aqua ]; then gui=1; else gui=; fi ;;
esac
# Compiled first, so the compile time is not counted
[ -z "$gui" ] || swiftc -O "$here/wait-window.swift" -o "$work/wait-window"

# Programs started before the prefix install finishes fail to open windows, so
# run wineboot first under its own limit; the remaining system services don't
# keep wineserver alive, so -w returns once the install is done. The addons
# (Wine Mono, Wine Gecko) are left out here and installed by a second, separate
# wineboot, so a failure says which part broke.
start=$(date +%s)
init() {
    WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=err+all "$root/bin/wine" wineboot -i \
        && "$root/bin/wineserver" -w
}
rc=0
limited "$init_limit" "$out/wineboot.log" init || rc=$?
init_seconds=$(( $(date +%s) - start ))
[ "$rc" -ne 124 ] || fail "init-timeout init_limit=$init_limit" "$out/wineboot.log" \
    "prefix initialization did not finish within $init_limit s"
if [ "$rc" -ne 0 ]; then
    # The first errors and the PE folders say more than the log's end
    {
        echo "== first error lines"; grep -n "err:\|could not load\|c0000" "$out/wineboot.log" | head -n 60
        echo "== log head"; head -n 40 "$out/wineboot.log"
        for arch in i386-windows x86_64-windows; do
            echo "== lib/wine/$arch: $(ls "$root/lib/wine/$arch" 2>/dev/null | wc -l) files"
            ls -l "$root/lib/wine/$arch/kernel32.dll" "$root/lib/wine/$arch/ntdll.dll" 2>&1
        done
    } >&2 || true
    # Which part hangs: the published 26.3.0-1 on this same runner image, then this
    # build with its bundled addon folders moved away, each in its own fresh prefix
    [ "${BOOT_DIAG:-0}" = 1 ] && {
    ref_url=https://github.com/BRYANN2K/cartouche-wine/releases/download/wine-crossover-26.3.0-1/wine-crossover-26.3.0-1-x86_64.tar.xz
    ref_sha=60400817826a053599193aa290d4e24e97213a743195f4187400bf9c74906887
    mkdir -p "$work/ref"
    if curl -fsSL -o "$work/ref.tar.xz" "$ref_url" \
        && [ "$(shasum -a 256 "$work/ref.tar.xz" | cut -d" " -f1)" = "$ref_sha" ] \
        && tar -xJf "$work/ref.tar.xz" -C "$work/ref"; then
        ref_root="$work/ref/wine-crossover-26.3.0-1"
    else
        ref_root=
        echo "boot-check: could not fetch the 26.3.0-1 reference" >&2
    fi
    for variant in reference-26.3.0-1 no-addon-folders; do
        export WINEPREFIX="$work/prefix-$variant"
        case "$variant" in
            reference-26.3.0-1) [ -n "$ref_root" ] || continue; vroot=$ref_root ;;
            no-addon-folders) vroot=$root; mv "$root/share/wine/mono" "$work/mono.off" 2>/dev/null || true
                mv "$root/share/wine/gecko" "$work/gecko.off" 2>/dev/null || true ;;
        esac
        probe() { WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=err+all "$vroot/bin/wine" wineboot -i \
            && "$vroot/bin/wineserver" -w; }
        t=$(date +%s)
        prc=0
        limited 600 "$out/wineboot-$variant.log" probe || prc=$?
        echo "boot-check: first boot with $variant: rc=$prc in $(( $(date +%s) - t )) s" >&2
        [ "$variant" != reference-26.3.0-1 ] || ref_rc=$prc
        grep "err:\|could not load" "$out/wineboot-$variant.log" | head -n 5 >&2 || true
        "$vroot/bin/wineserver" -k 2>/dev/null || true
    done
    }
    # The published 26.3.0-1 hanging the same way means this runner image cannot boot a
    # prefix at all (seen on macos-15-intel from 2026-10-22): report it, do not block on it
    if [ "${ref_rc:-}" = "$rc" ]; then
        echo "boot-check: the published 26.3.0-1 fails the same way (rc=$rc) on this runner image;" \
            "the boot is not checked here and must be checked on a Mac" >&2
        echo "::warning::boot not checked: this runner image cannot boot a prefix (26.3.0-1 fails too)"
        echo "result=env-cannot-boot rc=$rc" > "$out/boot.txt"
        exit 0
    fi
    fail "init-failed rc=$rc" "$out/wineboot.log" "prefix initialization exited $rc"
fi
echo "boot-check: prefix initialized in $init_seconds s"

# Second pass: wineboot -u with mscoree and mshtml on installs the bundled addons
addons() {
    WINEDEBUG=err+all,trace+mscoree,trace+appwizcpl,+loaddll "$root/bin/wine" wineboot -u \
        && "$root/bin/wineserver" -w
}
start=$(date +%s)
rc=0
limited "$init_limit" "$out/addons.log" addons || rc=$?
addons_seconds=$(( $(date +%s) - start ))
if [ "$rc" -ne 0 ]; then
    {
        echo "== addons: first error lines"; grep -n "err:\|could not load\|c0000" "$out/addons.log" | head -n 60
        echo "== addons: programs and core dlls loaded"
        grep -n "Loaded.*\(kernel32\|ntdll\|mscoree\|appwiz\|msiexec\|rundll\|wineboot\)\|\.exe" "$out/addons.log" | head -n 80
        echo "== addons: mscoree/appwiz traces"; grep "mscoree\|appwizcpl" "$out/addons.log" | head -n 40
        echo "== share/wine"; ls "$root/share/wine/mono" "$root/share/wine/gecko" 2>&1
    } >&2 || true
    [ "$rc" -ne 124 ] || fail "addons-timeout" "$out/addons.log" "installing the addons did not finish within $init_limit s"
    fail "addons-failed rc=$rc" "$out/addons.log" "installing the addons exited $rc"
fi
echo "boot-check: addons installed in $addons_seconds s"

# appwiz.cpl traces "Got URL" only on its way to the download dialog
if grep -q "mono runtime not found\|Got URL" "$out/addons.log" \
    || ! grep -q "mono runtime is at" "$out/addons.log"; then
    grep "mscoree\|appwizcpl" "$out/addons.log" | tail -n 30 >&2 || true
    fail addon-download "" "wineboot did not use the bundled Wine Mono"
fi

for f in system.reg user.reg userdef.reg; do
    [ -s "$WINEPREFIX/$f" ] || fail "no-registry file=$f" "$out/wineboot.log" "wineboot did not write $f"
done

# Console programs need no window server
rc=0
limited "$cmd_limit" "$out/cmd.log" "$root/bin/wine" cmd /c ver || rc=$?
grep -q "Windows" "$out/cmd.log" || fail "cmd-failed rc=$rc" "$out/cmd.log" "wine cmd /c ver exited $rc"
rc=0
limited "$cmd_limit" "$out/reg.log" "$root/bin/wine" reg query \
    'HKLM\Software\Microsoft\Windows NT\CurrentVersion' /v CurrentBuildNumber || rc=$?
grep -q CurrentBuildNumber "$out/reg.log" || fail "reg-failed rc=$rc" "$out/reg.log" "wine reg query exited $rc"
echo "boot-check: cmd and reg ran"

summary="init_seconds=$init_seconds wine=$("$root/bin/wine" --version)"
if [ -z "$gui" ]; then
    echo "result=pass mode=headless $summary" | tee "$out/boot.txt"
    exit 0
fi

WINEDEBUG=err+all "$root/bin/wine" winecfg > "$out/winecfg.log" 2>&1 &
# The loader shows up under its own name, or the program's
seconds=$("$work/wait-window" wine "$limit") || {
    "$work/wait-window" --list > "$out/windows.txt" 2>&1 || true
    fail "timeout limit=$limit" "$out/winecfg.log" "no winecfg window within $limit s (windows on screen: windows.txt)"
}
sleep 2
screencapture -x "$out/winecfg.png" || echo "boot-check: screencapture failed" >&2
echo "result=pass mode=gui seconds=$seconds limit=$limit $summary" | tee "$out/boot.txt"
