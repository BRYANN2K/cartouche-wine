#!/bin/sh
# Copies the license files of every Homebrew formula a bundled dylib came from
# into <licenses folder>/<formula>/, and maps each dylib to its formula in
# <licenses folder>/dylibs.txt. The files come from the keg and from the
# formula's source (brew fetch -s), because kegs keep only some of them.
#
#   ./collect-licenses.sh <origins file> <licenses folder>
#
# The origins file is the one bundle-deps.sh --origins writes. Exits 1 when a
# dylib is not from a keg or a formula has no license file.
set -eu

[ $# -eq 2 ] || { echo "usage: collect-licenses.sh <origins file> <licenses folder>" >&2; exit 2; }
origins=$1 dest=$2
mkdir -p "$dest"
: > "$dest/dylibs.txt"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

is_license() {
    case "$(basename "$1" | tr '[:upper:]' '[:lower:]')" in
        copying*|license*|licence*|notice*|copyright*|ftl.txt|gpl*.txt|lgpl*.txt|mpl*.txt) return 0 ;;
        *) return 1 ;;
    esac
}

# License files at the top of a source tree, or in its doc, docs or LICENSES folder
source_licenses() {
    awk '{ n = $0; sub(/^\.\//, "", n); k = split(n, a, "/") }
        k == 2 || (k == 3 && a[2] ~ /^(doc|docs|LICENSES)$/)' | while IFS= read -r f; do
        if is_license "$f"; then echo "$f"; fi
    done
}

while read -r leaf path; do
    case "$path" in
        */Cellar/*/*/*) ;;
        *) echo "collect-licenses: $leaf comes from $path, not a Homebrew keg" >&2; exit 1 ;;
    esac
    rest=${path#*/Cellar/}
    formula=${rest%%/*}
    version=${rest#*/}
    version=${version%%/*}
    keg=${path%%/Cellar/*}/Cellar/$formula/$version
    echo "$leaf $formula" >> "$dest/dylibs.txt"
    [ -d "$dest/$formula" ] && continue
    mkdir -p "$dest/$formula"

    for f in "$keg"/* "$keg"/share/doc/*/*; do
        if [ -f "$f" ] && is_license "$f"; then cp "$f" "$dest/$formula/"; fi
    done

    brew fetch --quiet --build-from-source "$formula" > /dev/null
    src=$(brew --cache --build-from-source "$formula")
    if [ -d "$src" ]; then
        (cd "$src" && find . -maxdepth 2 -type f | sed 's|^\./|x/|') | source_licenses | while IFS= read -r f; do
            mkdir -p "$dest/$formula/$(dirname "${f#*/}")"
            cp "$src/${f#*/}" "$dest/$formula/${f#*/}"
        done
    elif tar -tf "$src" > "$tmp/list" 2>/dev/null; then
        source_licenses < "$tmp/list" > "$tmp/wanted"
        if [ -s "$tmp/wanted" ]; then
            rm -rf "$tmp/x"
            mkdir "$tmp/x"
            tar -xf "$src" -C "$tmp/x" -T "$tmp/wanted"
            while IFS= read -r f; do
                rel=${f#./}
                rel=${rel#*/}
                mkdir -p "$dest/$formula/$(dirname "$rel")"
                cp "$tmp/x/$f" "$dest/$formula/$rel"
            done < "$tmp/wanted"
        fi
    fi

    [ -n "$(ls -A "$dest/$formula")" ] || { echo "collect-licenses: no license file found for $formula" >&2; exit 1; }
    echo "$formula $version" >> "$dest/formulas.txt"
done < "$origins"
echo "==> collect-licenses: $(wc -l < "$dest/dylibs.txt" | tr -d ' ') dylibs mapped in $dest"
