#!/bin/sh
# Checks what a Windows program sees of the GPU through a runner's wined3d:
# the RTX cards report NVIDIA 581.57 (x.x.15.8157), the RTX 50 cards exist, and
# VideoDriverVersion replaces the version (patches/0001-wined3d-gpu-identity.patch).
#
#   ./check-gpu-identity.sh <runner root> <llvm-mingw folder> <scratch folder>
#
# Boots a new prefix in <scratch folder>/prefix (about 25 s and 1 GB); never
# touches another prefix.
set -eu

[ $# -eq 3 ] || { echo "usage: check-gpu-identity.sh <runner root> <llvm-mingw folder> <scratch folder>" >&2; exit 2; }
here="$(cd "$(dirname "$0")" && pwd -P)"
runner=$1 mingw=$2
mkdir -p "$3"
scratch=$(cd "$3" && pwd -P)
exe="$scratch/gpu-identity.exe"
"$mingw/bin/x86_64-w64-mingw32-clang" -O2 -o "$exe" "$here/gpu-identity.c" -ld3d9 -ldxgi

export WINEPREFIX="$scratch/prefix" WINEDLLOVERRIDES="mscoree,mshtml=" WINEDEBUG=err+all,fixme-all
[ -f "$WINEPREFIX/system.reg" ] || { "$runner/bin/wine" wineboot -i >/dev/null 2>&1; "$runner/bin/wineserver" -w; }

failed=0
expect() {
    # The console ends lines with CRLF
    out=$(WINE_D3D_CONFIG=$1 "$runner/bin/wine" "$exe" 2>&1 | tr -d '\r') || true
    if printf '%s\n' "$out" | grep -Eq "$2"; then
        echo "ok: $1"
    else
        echo "FAILED: WINE_D3D_CONFIG=$1 should print /$2/, got:" >&2
        printf '%s\n' "$out" >&2
        failed=1
    fi
}
expect "VideoPciVendorID=0x10de,VideoPciDeviceID=0x2684" '^d3d9 10de:2684 [0-9]+\.[0-9]+\.15\.8157 NVIDIA GeForce RTX 4090$'
expect "VideoPciVendorID=0x10de,VideoPciDeviceID=0x2b85" '^d3d9 10de:2b85 [0-9]+\.[0-9]+\.15\.8157 NVIDIA GeForce RTX 5090$'
expect "VideoPciVendorID=0x10de,VideoPciDeviceID=0x2c02" '^d3d9 10de:2c02 [0-9]+\.[0-9]+\.15\.8157 NVIDIA GeForce RTX 5080$'
expect "VideoPciVendorID=0x10de,VideoPciDeviceID=0x0640" '^d3d9 10de:0640 [0-9]+\.[0-9]+\.13\.4052 '
expect "VideoPciVendorID=0x10de,VideoPciDeviceID=0x2684,VideoDriverVersion=32.0.15.9174" '^d3d9 10de:2684 32\.0\.15\.9174 '
expect "VideoDriverVersion=31.0.101.5333" '^d3d9 [0-9a-f]{4}:[0-9a-f]{4} 31\.0\.101\.5333 '
expect "VideoDriverVersion=32.0.15" 'Invalid value for VideoDriverVersion'
"$runner/bin/wineserver" -k 2>/dev/null || true
exit $failed
