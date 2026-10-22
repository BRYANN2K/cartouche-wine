#!/bin/sh
# Copies the license files of every Homebrew formula a bundled dylib came from
# into <licenses folder>/<formula>/, and maps each dylib to its formula in
# <licenses folder>/dylibs.txt. The files come from the keg and from the
# formula's source (brew fetch -s), because kegs keep only some of them.
#
#   ./collect-licenses.sh [--local <folder> <package>]... <origins file> <licenses folder> [<sources folder>]
#
# The origins file is the one bundle-deps.sh --origins writes. With a sources
# folder, each formula's source archive is also copied there as
# <formula>-<version>.<ext>, for the LGPL source offer. --local maps the files
# that came from <folder> (what build-gstreamer.sh built) to <package>, whose
# license files and source the caller provides in <licenses folder>/<package>.
# Exits 1 when a dylib is neither from a keg nor from a --local folder, or a
# formula or local package has no license file.
set -eu

locals=
while [ "${1:-}" = --local ]; do
    [ $# -ge 3 ] || { echo "collect-licenses: --local needs <folder> <package>" >&2; exit 2; }
    [ -d "$2" ] || { echo "collect-licenses: $2 is not a folder" >&2; exit 2; }
    locals="$locals$(cd "$2" && pwd -P) $3
"
    shift 3
done
[ $# -eq 2 ] || [ $# -eq 3 ] || { echo "usage: collect-licenses.sh [--local <folder> <package>]... <origins file> <licenses folder> [<sources folder>]" >&2; exit 2; }
origins=$1 dest=$2 sources=${3:-}
mkdir -p "$dest"
[ -z "$sources" ] || mkdir -p "$sources"
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

# The package of a file built from a --local folder, or nothing
local_package() {
    printf '%s' "$locals" | awk -v p="$1" 'NF {
        pkg = $NF; dir = substr($0, 1, length($0) - length(pkg) - 1)
        if (index(p, dir "/") == 1) { print pkg; exit }
    }'
}

while read -r leaf path; do
    pkg=$(local_package "$path")
    if [ -n "$pkg" ]; then
        echo "$leaf $pkg" >> "$dest/dylibs.txt"
        [ -n "$(ls -A "$dest/$pkg" 2>/dev/null)" ] \
            || { echo "collect-licenses: $leaf comes from $pkg, which has no license files in $dest/$pkg" >&2; exit 1; }
        continue
    fi
    case "$path" in
        */Cellar/*/*/*) ;;
        *) echo "collect-licenses: $leaf comes from $path, not a Homebrew keg or a --local folder" >&2; exit 1 ;;
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

    # ftpmirror.gnu.org picks a mirror per request, and one can be broken: try a few times
    n=0
    until brew fetch --quiet --build-from-source "$formula" > /dev/null; do
        n=$((n + 1))
        [ "$n" -lt 4 ] || { echo "collect-licenses: could not fetch the source of $formula" >&2; exit 1; }
        sleep 10
    done
    src=$(brew --cache --build-from-source "$formula")
    if [ -n "$sources" ]; then
        if [ -d "$src" ]; then
            tar -czf "$sources/$formula-$version.tar.gz" -C "$(dirname "$src")" "$(basename "$src")"
        else
            name=$(basename "$src")
            case "$name" in
                *.tar.*) ext=tar.${name##*.tar.} ;;
                *) ext=${name##*.} ;;
            esac
            cp "$src" "$sources/$formula-$version.$ext"
        fi
    fi
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
