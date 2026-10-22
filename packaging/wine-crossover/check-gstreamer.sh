#!/bin/sh
# Checks the bundled GStreamer the way winegstreamer uses it: winegstreamer.so
# is built, every plugin in gstreamer-plugins.txt is in lib/gstreamer-1.0, and
# the bundled gst-inspect-1.0, run with no GStreamer variable set, finds them
# there (libgstreamer locates lib/gstreamer-1.0 next to itself), loads every
# one, sees each is LGPL, and has the elements Wine creates by name and the
# decoders games' videos need.
#
#   ./check-gstreamer.sh <package root>
#
# GST_PLUGIN_EXT (default dylib) lets the tests run it on a Linux build.
set -eu

here="$(cd "$(dirname "$0")" && pwd -P)"
[ $# -eq 1 ] || { echo "usage: check-gstreamer.sh <package root>" >&2; exit 2; }
root=$(cd "$1" && pwd -P)
plugins_file=${GST_PLUGINS_FILE:-$here/gstreamer-plugins.txt}
ext=${GST_PLUGIN_EXT:-dylib}
fail() { echo "check-gstreamer: $*" >&2; exit 1; }

# Created by name in dlls/winegstreamer, then the decoders, demuxers and
# parsers decodebin needs for H.264/AAC MP4, WMV/WMA (ASF) and MPEG files
GST_ELEMENTS="decodebin videoconvert audioconvert audioresample capsfilter deinterlace videoflip
appsrc appsink queue avdec_h264 avdec_wmv3 avdec_vc1 avdec_wmav2 avdec_aac avdec_mp3
avdec_mpeg2video qtdemux asfdemux matroskademux avidemux h264parse vc1parse mpegpsdemux"
# Plugins whose GST_PLUGIN_DEFINE does not say LGPL although their sources are:
# mpegpsdemux is MPL 1.1 or LGPL at the user's choice (gst/mpegdemux/*.c)
LICENSE_EXCEPTIONS="mpegpsdemux:unknown"

[ -f "$root/lib/wine/x86_64-unix/winegstreamer.so" ] || fail "lib/wine/x86_64-unix/winegstreamer.so is missing"
plugins=$(awk '!/^#/ && NF == 3 { print $3 }' "$plugins_file")
for p in $plugins; do
    [ -f "$root/lib/gstreamer-1.0/libgst$p.$ext" ] || fail "lib/gstreamer-1.0/libgst$p.$ext is missing"
done
inspect="$root/libexec/gstreamer-1.0/gst-inspect-1.0"
[ -x "$inspect" ] || fail "libexec/gstreamer-1.0/gst-inspect-1.0 is missing"

# Nothing from this machine: no GST_* variable, an empty home, a fresh registry
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/home"
gst() { env -i HOME="$tmp/home" PATH=/usr/bin:/bin GST_REGISTRY_1_0="$tmp/registry.bin" "$inspect" "$@"; }

blacklisted=$(gst -b 2>&1) || fail "gst-inspect-1.0 -b exited $?: $blacklisted"
echo "$blacklisted" | grep -q "Total count: 0 blacklisted" \
    || fail "plugins that do not load:
$blacklisted"

for p in $plugins; do
    details=$(gst "$p" 2>&1) || fail "plugin $p is not found: $details"
    file=$(echo "$details" | awk '$1 == "Filename" { print $2; exit }')
    case "$file" in
        "$root"/lib/gstreamer-1.0/*) ;;
        *) fail "plugin $p loads from '$file', not from the package" ;;
    esac
    license=$(echo "$details" | awk '$1 == "License" { print $2; exit }')
    [ "$license" = LGPL ] || case " $LICENSE_EXCEPTIONS " in
        *" $p:$license "*) ;;
        *) fail "plugin $p is licensed '$license', not LGPL" ;;
    esac
done

missing=
for e in $GST_ELEMENTS; do
    gst --exists "$e" || missing="$missing $e"
done
[ -z "$missing" ] || fail "elements not found:$missing"
echo "==> check-gstreamer: $(echo "$plugins" | wc -l | tr -d ' ') plugins load from $root/lib/gstreamer-1.0"
