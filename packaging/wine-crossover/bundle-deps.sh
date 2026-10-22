#!/bin/sh
# Copies dylibs and every non-system dylib they load into one folder, and makes
# them find each other through @rpath, so the package needs nothing from Homebrew.
#
#   ./bundle-deps.sh [--origins <file>] [--search <dir>]... [--place <dir> <rpath> <file>]...
#                    <out folder> <dylib>...
#
# Wine is then configured against this folder, so the library names it dlopens
# are @rpath names too. --origins appends "<file name> <real path it was
# copied from>" lines, which collect-licenses.sh reads. --search adds a folder
# where @rpath dependencies are looked for. --place copies a file that is not a
# library of <out folder> (a GStreamer plugin, a tool) into <dir> instead,
# gives it the LC_RPATH <rpath> that leads to <out folder>, and bundles what it
# loads into <out folder>.
set -eu

origins=/dev/null
search=
tab=$(printf '\t')
placed=$(mktemp)
queue=$(mktemp)
done_list=$(mktemp)
trap 'rm -f "$queue" "$queue.next" "$done_list" "$placed"' EXIT
while [ $# -gt 0 ]; do
    case "$1" in
        --origins) origins=$2; shift 2 ;;
        --search) search="$search
$2"; shift 2 ;;
        --place)
            [ $# -ge 4 ] || { echo "bundle-deps: --place needs <dir> <rpath> <file>" >&2; exit 2; }
            mkdir -p "$2"
            printf '%s\t%s\t%s\n' "$(basename "$4")" "$(cd "$2" && pwd -P)" "$3" >> "$placed"
            echo "$4" >> "$queue"
            shift 4 ;;
        *) break ;;
    esac
done
[ $# -ge 1 ] || { echo "usage: bundle-deps.sh [--origins <file>] [--search <dir>]... [--place <dir> <rpath> <file>]... <out folder> <dylib>..." >&2; exit 2; }
out=$1
shift
[ $# -ge 1 ] || [ -s "$placed" ] || { echo "bundle-deps: nothing to bundle" >&2; exit 2; }
mkdir -p "$out"
out=$(cd "$out" && pwd -P)

is_system() {
    case "$1" in
        /usr/lib/*|/System/*) return 0 ;;
        *) return 1 ;;
    esac
}

# Dependencies of $1, one per line, without its own id
deps() {
    otool -L "$1" | tail -n +2 | sed -E 's/^[[:space:]]+//; s/ \(compatibility.*$//' | while IFS= read -r dep; do
        [ "$dep" = "$(otool -D "$1" | tail -n +2)" ] && continue
        echo "$dep"
    done
}

# Where a dependency of $2 named $1 lives on this machine
locate() {
    dir=$(dirname "$2")
    real=$(dirname "$(realpath "$2")")
    case "$1" in
        @loader_path/*) echo "$dir/${1#@loader_path/}" ;;
        @rpath/*)
            for d in "$dir" "$real" "$out" $search; do
                if [ -f "$d/${1#@rpath/}" ]; then echo "$d/${1#@rpath/}"; return; fi
            done
            echo "bundle-deps: cannot find $1 needed by $2" >&2
            return 1 ;;
        *) echo "$1" ;;
    esac
}

for lib in "$@"; do echo "$lib" >> "$queue"; done

while [ -s "$queue" ]; do
    lib=$(head -n 1 "$queue")
    tail -n +2 "$queue" > "$queue.next"; mv "$queue.next" "$queue"
    leaf=$(basename "$lib")
    grep -qxF "$leaf" "$done_list" && continue
    echo "$leaf" >> "$done_list"
    [ -f "$lib" ] || { echo "bundle-deps: $lib does not exist" >&2; exit 1; }
    echo "$leaf $(realpath "$lib")" >> "$origins"

    place=$(awk -F '\t' -v l="$leaf" '$1 == l { print $2 "\t" $3; exit }' "$placed")
    if [ -n "$place" ]; then
        copy="${place%%$tab*}/$leaf"
    else
        copy="$out/$leaf"
    fi
    cp -fL "$lib" "$copy"
    chmod u+w "$copy"
    # Meson keeps the -L folders of pkg-config dependencies as LC_RPATH: drop
    # every search path into the build machine
    for path in $(otool -l "$copy" | awk '/cmd LC_RPATH/ { getline; getline; print $2 }'); do
        case "$path" in
            @*) ;;
            *) install_name_tool -delete_rpath "$path" "$copy" ;;
        esac
    done
    if [ -n "$place" ]; then
        # A plugin or a tool must find the libraries in <out folder>; a tool
        # or a bundle has no install name to set
        rpath=${place#*$tab}
        otool -l "$copy" | grep -q "path $rpath (" || install_name_tool -add_rpath "$rpath" "$copy"
        install_name_tool -id "@rpath/$leaf" "$copy" 2>/dev/null || true
    else
        install_name_tool -id "@rpath/$leaf" "$copy" 2>/dev/null
    fi
    for dep in $(deps "$lib"); do
        is_system "$dep" && continue
        found=$(locate "$dep" "$lib")
        install_name_tool -change "$dep" "@rpath/$(basename "$found")" "$copy" 2>/dev/null
        echo "$found" >> "$queue"
    done
    # Editing load commands breaks the signature, and arm64 refuses unsigned code
    codesign --force --sign - "$copy" 2>/dev/null
done

echo "==> bundle-deps: $(wc -l < "$done_list" | tr -d ' ') dylibs in $out"
