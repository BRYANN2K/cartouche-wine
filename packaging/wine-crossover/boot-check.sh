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
#
# A failed first boot dumps the Wine processes still running, a stack sample of
# each and the prefix's system32. With BOOT_DIAG=1 it then boots the published
# 26.3.0-1 (or BOOT_REF_ROOT) and this build with the display driver off, each
# in a fresh prefix. When 26.3.0-1 fails the same way the runner image is at
# fault: if the build boots without the display driver, the other checks run in
# that prefix (mode=no-display-driver), otherwise the result is env-cannot-boot.
# Either way it warns and exits 0, and the build must be booted on a Mac.
set -eu

here="$(cd "$(dirname "$0")" && pwd -P)"
[ $# -ge 2 ] || { echo "usage: boot-check.sh <runner root> <out folder> [limit] [init limit]" >&2; exit 2; }
root=$1 out=$2 limit=${3:-180} init_limit=${4:-${BOOT_INIT_LIMIT:-1200}}
cmd_limit=${BOOT_CMD_LIMIT:-300}
# Wine itself waits 300 s for wineboot (run_wineboot), so a diagnostic boot
# gets more than that
diag_limit=${BOOT_DIAG_LIMIT:-600}
mkdir -p "$out"

work=$(mktemp -d)
export HOME="$work/home" WINEPREFIX="$work/prefix" WINEDEBUG=-all WINEDLLOVERRIDES=
drv_off=
mkdir -p "$HOME"
cleanup() {
    for p in "$work"/prefix*; do
        [ -d "$p" ] || continue
        WINEPREFIX=$p "$root/bin/wineserver" -k 2>/dev/null || true
    done
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

# After a failed boot: the Wine processes still running (with a stack sample
# of each, where macOS lets us take one) and what wineboot put in system32,
# into <file>.txt; the short version goes to stderr
dump_prefix() {
    {
        echo "== processes"
        ps axww -o pid,ppid,etime,stat,command | grep -i "wine\|\.exe" | grep -v "grep\|boot-check" || true
        for d in system32 syswow64; do
            sys="$WINEPREFIX/drive_c/windows/$d"
            echo "== $d: $(ls "$sys" 2>/dev/null | wc -l | tr -d ' ') files"
            ls -l "$sys/kernel32.dll" "$sys/ntdll.dll" "$sys/wineboot.exe" 2>&1
        done
    } > "$1.txt" 2>&1 || true
    cat "$1.txt" >&2
    ls -la "$WINEPREFIX/drive_c/windows/system32" > "$1-system32.txt" 2>&1 || true
    command -v sample > /dev/null 2>&1 || return 0
    n=0
    for pid in $(ps axww -o pid=,command= | grep -i "\.exe" | grep -v grep | awk '{ print $1 }'); do
        n=$(( n + 1 )); [ "$n" -le 8 ] || break
        s="$1-sample-$pid.txt"
        sudo -n sample "$pid" 2 -mayDie -file "$s" > /dev/null 2>&1 \
            || sample "$pid" 2 -mayDie -file "$s" > /dev/null 2>&1 || continue
        echo "== stack of $pid: $(ps -o command= -p "$pid" 2>/dev/null)" >&2
        sed -n '/^Call graph:/,/^$/p' "$s" | head -n 45 >&2 || true
    done
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
# With Mono and Gecko on, wineboot --init would wait on their install here.
# +loaddll shows which DLL each thread loaded last if it hangs.
init() {
    WINEDLLOVERRIDES="mscoree,mshtml=$drv_off" WINEDEBUG=err+all,+loaddll "$1/bin/wine" wineboot -i \
        && "$1/bin/wineserver" -w
}
rc=0
limited "$init_limit" "$out/wineboot.log" init "$root" || rc=$?
init_seconds=$(( $(date +%s) - start ))
# limited() sets rc too, so the diagnostic boots below would overwrite it
first_rc=$rc mode=
if [ "$rc" -ne 0 ]; then
    # The first errors, the PE folders and the processes still running say more
    # than the log's end
    {
        echo "== first error lines"; grep -n "err:\|could not load\|c0000" "$out/wineboot.log" | head -n 60
        echo "== log head"; grep -v ":trace:loaddll:" "$out/wineboot.log" | head -n 40
        echo "== last DLL each process loaded"
        grep ":trace:loaddll:" "$out/wineboot.log" | awk -F: '{ last[$1] = $0 } END { for (p in last) print last[p] }'
        for arch in i386-windows x86_64-windows; do
            echo "== lib/wine/$arch: $(ls "$root/lib/wine/$arch" 2>/dev/null | wc -l) files"
            ls -l "$root/lib/wine/$arch/kernel32.dll" "$root/lib/wine/$arch/ntdll.dll" 2>&1
        done
    } >&2 || true
    dump_prefix "$out/hung"
    [ "$rc" -ne 124 ] || fail "init-timeout init_limit=$init_limit" "$out/wineboot.log" \
        "prefix initialization did not finish within $init_limit s"
    # Which part hangs: the published 26.3.0-1 on this same runner image, then this
    # build with the macOS display driver off, each in its own fresh prefix
    [ "${BOOT_DIAG:-0}" = 1 ] && {
    if [ -n "${BOOT_REF_ROOT:-}" ]; then
        ref_root=$BOOT_REF_ROOT
    else
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
    fi
    for variant in reference-26.3.0-1 no-display-driver; do
        export WINEPREFIX="$work/prefix-$variant"
        drv_off=
        case "$variant" in
            reference-26.3.0-1) [ -n "$ref_root" ] || continue; vroot=$ref_root ;;
            # winemac.drv disabled: windows go to Wine's null driver
            no-display-driver) vroot=$root drv_off=",winemac.drv=" ;;
        esac
        t=$(date +%s)
        prc=0
        limited "$diag_limit" "$out/wineboot-$variant.log" init "$vroot" || prc=$?
        echo "boot-check: first boot with $variant: rc=$prc in $(( $(date +%s) - t )) s" >&2
        grep "err:\|could not load" "$out/wineboot-$variant.log" | head -n 5 >&2 || true
        case "$variant" in
            reference-26.3.0-1) ref_rc=$prc
                [ "$prc" -eq 0 ] || dump_prefix "$out/hung-$variant"
                "$vroot/bin/wineserver" -k 2>/dev/null || true ;;
            no-display-driver) nodrv_rc=$prc nodrv_seconds=$(( $(date +%s) - t ))
                [ "$prc" -eq 0 ] || { dump_prefix "$out/hung-$variant"; "$vroot/bin/wineserver" -k 2>/dev/null || true; } ;;
        esac
    done
    }
    # The published 26.3.0-1 hanging the same way means this runner image cannot boot a
    # prefix at all (seen on macos-15-intel from 2026-10-22): report it, do not block on it
    if [ "${ref_rc:-}" = "$first_rc" ]; then
        echo "boot-check: the published 26.3.0-1 fails the same way (rc=$first_rc) on this runner image" >&2
        if [ "${nodrv_rc:-}" = 0 ]; then
            # The rest of the checks still run, in the prefix that booted
            echo "boot-check: this build boots with the display driver off; checking the rest without it" >&2
            echo "::warning::the macOS display driver hangs wineboot on this runner image (26.3.0-1 too); booted with winemac.drv off, windows must be checked on a Mac"
            mode=no-display-driver init_seconds=$nodrv_seconds
            export WINEDLLOVERRIDES="winemac.drv="
        else
            # The addons were never installed; at least they are in the package
            for d in "$root/share/wine/mono/wine-mono-"* "$root/share/wine/gecko/wine-gecko-"*-x86 \
                "$root/share/wine/gecko/wine-gecko-"*-x86_64; do
                [ -d "$d" ] || fail "addons-missing" "" "the bundled Wine Mono or Gecko is missing in share/wine"
            done
            echo "boot-check: the boot is not checked here and must be checked on a Mac" >&2
            echo "::warning::boot not checked: this runner image cannot boot a prefix (26.3.0-1 fails too)"
            echo "result=env-cannot-boot rc=$first_rc" > "$out/boot.txt"
            exit 0
        fi
    else
        fail "init-failed rc=$first_rc" "$out/wineboot.log" "prefix initialization exited $first_rc"
    fi
fi
echo "boot-check: prefix initialized in $init_seconds s${mode:+ (mode $mode)}"

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
if [ -n "$mode" ]; then
    echo "result=pass mode=$mode $summary" | tee "$out/boot.txt"
    exit 0
fi
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
