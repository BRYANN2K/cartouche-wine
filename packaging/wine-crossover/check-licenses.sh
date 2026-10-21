#!/bin/sh
# Fails unless every bundled dylib (lib/*.dylib) is mapped to a package in
# share/licenses/dylibs.txt whose folder holds its license files, and Wine Mono
# and Wine Gecko, when bundled, have theirs.
#
#   ./check-licenses.sh <package root>
set -eu

[ $# -eq 1 ] || { echo "usage: check-licenses.sh <package root>" >&2; exit 2; }
root=$1
licenses="$root/share/licenses"
bad=$(mktemp)
trap 'rm -f "$bad"' EXIT

has_files() { [ -d "$1" ] && [ -n "$(find "$1" -type f | head -n 1)" ]; }

for lib in "$root"/lib/*.dylib; do
    [ -e "$lib" ] || continue
    leaf=$(basename "$lib")
    pkg=$(awk -v l="$leaf" '$1 == l { print $2; exit }' "$licenses/dylibs.txt" 2>/dev/null || true)
    if [ -z "$pkg" ]; then
        echo "$leaf has no entry in share/licenses/dylibs.txt" >> "$bad"
    elif ! has_files "$licenses/$pkg"; then
        echo "$leaf comes from $pkg, which has no files in share/licenses/$pkg" >> "$bad"
    fi
done
[ ! -d "$root/share/wine/mono" ] || has_files "$licenses/wine-mono" || echo "Wine Mono has no license in share/licenses/wine-mono" >> "$bad"
[ ! -d "$root/share/wine/gecko" ] || has_files "$licenses/wine-gecko" || echo "Wine Gecko has no license in share/licenses/wine-gecko" >> "$bad"

if [ -s "$bad" ]; then
    echo "check-licenses: bundled code without its license:" >&2
    sed 's/^/    /' "$bad" >&2
    exit 1
fi
echo "==> check-licenses: every bundled library in $root has its license"
