#!/bin/sh
# Builds the GStreamer that winegstreamer links and loads: LGPL FFmpeg (decoders
# only) from its pinned release tarball, then GStreamer core, base, good, bad,
# ugly and gst-libav from the GStreamer tree in CodeWeavers' CrossOver sources
# (sources/gstreamer, the same LGPL source offer as Wine), each built alone with
# only the plugins in gstreamer-plugins.txt enabled.
#
#   ./build-gstreamer.sh [--dry-run] <gstreamer source tree> <ffmpeg tarball> <work folder>
#
# Installs FFmpeg into <work folder>/ffmpeg and GStreamer into <work folder>/gst,
# and fails when a listed plugin was not built. GLib comes from pkg-config
# (Homebrew's glib on the build Mac). Runs on Linux too, which is how the plugin
# options are tested without a Mac. Needs meson, ninja, pkg-config and nasm.
set -eu

here="$(cd "$(dirname "$0")" && pwd -P)"

dry=
if [ "${1:-}" = "--dry-run" ]; then dry=1; shift; fi
[ $# -eq 3 ] || { echo "usage: build-gstreamer.sh [--dry-run] <gstreamer source tree> <ffmpeg tarball> <work folder>" >&2; exit 2; }
gst_src=$1 ffmpeg_tar=$2 work=$3
plugins_file=${GST_PLUGINS_FILE:-$here/gstreamer-plugins.txt}

run() {
    if [ -n "$dry" ]; then echo "+ $*"; else "$@"; fi
}

case "$(uname -s)" in
    Darwin) so=dylib ;;
    *) so=so ;;
esac
jobs=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)

ff_prefix="$work/ffmpeg"
gst_prefix="$work/gst"
build="$work/gst-build"

# FFmpeg: LGPL 2.1 or later (no --enable-gpl, --enable-version3 or
# --enable-nonfree), shared libraries, decoders and parsers only. HEVC and
# E-AC-3 are left out on purpose (see docs/CHANGES.md, "GStreamer").
FFMPEG_DECODERS="h264 mpeg1video mpeg2video mpeg4 h263 msmpeg4v1 msmpeg4v2 msmpeg4v3
wmv1 wmv2 wmv3 wmv3image vc1 vc1image vp6 vp6a vp6f vp8 vp9 theora flv cinepak
msvideo1 indeo2 indeo3 indeo4 indeo5 mjpeg
aac aac_latm mp1 mp1float mp2 mp2float mp3 mp3float ac3 wmav1 wmav2 wmapro
wmavoice wmalossless vorbis opus flac alac adpcm_ms adpcm_ima_wav adpcm_ima_qt
pcm_alaw pcm_mulaw"
FFMPEG_PARSERS="h264 h263 mpeg4video mpegvideo vc1 vp8 vp9 aac aac_latm mpegaudio ac3 flac opus vorbis"

ff_flags="--prefix=$ff_prefix --enable-shared --disable-static --disable-programs
--disable-doc --disable-network --disable-autodetect --disable-everything
--disable-avdevice --disable-postproc --enable-pic"
for d in $FFMPEG_DECODERS; do ff_flags="$ff_flags --enable-decoder=$d"; done
for p in $FFMPEG_PARSERS; do ff_flags="$ff_flags --enable-parser=$p"; done

if [ "$so" = dylib ]; then
    # Room for bundle-deps.sh to rewrite the install names
    ff_flags="$ff_flags --cc=clang --arch=x86_64 --extra-ldflags=-Wl,-headerpad_max_install_names"
    [ -z "${MACOSX_DEPLOYMENT_TARGET:-}" ] \
        || ff_flags="$ff_flags --extra-cflags=-mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET"
    export LDFLAGS="${LDFLAGS:+$LDFLAGS }-Wl,-headerpad_max_install_names"
fi

run rm -rf "$ff_prefix" "$gst_prefix" "$build"
run mkdir -p "$build/ffmpeg"
run tar -xJf "$ffmpeg_tar" -C "$build/ffmpeg" --strip-components 1
# shellcheck disable=SC2086
if [ -n "$dry" ]; then
    echo "+ (cd $build/ffmpeg && ./configure $(echo $ff_flags))"
else
    (cd "$build/ffmpeg" && ./configure $ff_flags)
    # The configured FFmpeg must not be GPL or nonfree
    grep -q '^#define CONFIG_GPL 0' "$build/ffmpeg/config.h" \
        && grep -q '^#define CONFIG_NONFREE 0' "$build/ffmpeg/config.h" \
        && grep -q '^#define CONFIG_VERSION3 0' "$build/ffmpeg/config.h" \
        || { echo "build-gstreamer: FFmpeg is not configured LGPL 2.1+" >&2; exit 1; }
fi
run make -C "$build/ffmpeg" -j"$jobs"
run make -C "$build/ffmpeg" install

export PKG_CONFIG_PATH="$gst_prefix/lib/pkgconfig:$ff_prefix/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"

# The meson options of one module's listed plugins, as -D<option>=enabled
plugin_options() {
    awk -v m="$1" '$1 == m && $2 != "-" { printf " -D%s=enabled", $2 }' "$plugins_file"
}

# Every module: release build, every optional feature off unless listed, no
# downloaded subprojects, no tests, docs, examples or translations
common="--prefix=$gst_prefix --libdir=lib --buildtype=release --auto-features=disabled
--wrap-mode=nofallback -Ddoc=disabled -Dtests=disabled -Dpackage-origin=https://github.com/BRYANN2K/cartouche-wine"

for module in gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly gst-libav; do
    opts=$(plugin_options "$module")
    case "$module" in
        gstreamer)
            # gst-inspect-1.0 checks the plugins in verify.sh; option parsing
            # carries winegstreamer's --gst-disable-registry-fork
            opts="$opts -Dtools=enabled -Dexamples=disabled -Dbenchmarks=disabled -Dintrospection=disabled
-Dnls=disabled -Dptp-helper=disabled -Dlibunwind=disabled -Dlibdw=disabled -Dbash-completion=disabled
-Dcheck=disabled -Dcoretracers=disabled" ;;
        gst-plugins-base)
            opts="$opts -Dexamples=disabled -Dtools=disabled -Dintrospection=disabled -Dnls=disabled -Dorc=disabled -Dgl=disabled" ;;
        gst-plugins-good|gst-plugins-bad)
            opts="$opts -Dexamples=disabled -Dnls=disabled -Dorc=disabled" ;;
        gst-plugins-ugly)
            opts="$opts -Dnls=disabled -Dorc=disabled -Dgpl=disabled" ;;
    esac
    case "$module" in gst-plugins-bad) opts="$opts -Dgpl=disabled -Dintrospection=disabled" ;; esac
    # shellcheck disable=SC2086
    run meson setup "$build/$module" "$gst_src/subprojects/$module" $common $opts
    run meson compile -C "$build/$module" -j "$jobs"
    run meson install -C "$build/$module" --no-rebuild
done

# Every listed plugin was built
[ -z "$dry" ] || exit 0
missing=
for p in $(awk '!/^#/ && NF == 3 { print $3 }' "$plugins_file"); do
    [ -f "$gst_prefix/lib/gstreamer-1.0/libgst$p.$so" ] || missing="$missing libgst$p.$so"
done
[ -z "$missing" ] || { echo "build-gstreamer: not built:$missing" >&2; exit 1; }
echo "==> build-gstreamer: FFmpeg in $ff_prefix, GStreamer in $gst_prefix"
