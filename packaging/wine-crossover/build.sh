#!/bin/sh
# Builds Wine from CodeWeavers' CrossOver sources into an install tree laid out
# like CrossOver's own (bin/, lib/wine/<arch>-unix|windows/, share/wine/), so
# Cartouche's run script and ntdll patcher find files where they expect them.
#
#   ./build.sh <work folder>             build into <work folder>/install
#   ./build.sh --dry-run <work folder>   print the commands only
#
# Needs an x86_64 Mac with Xcode, Homebrew and the formulas in pins.env, and the
# pinned downloads in <work folder>/downloads (fetch.sh): the sources,
# llvm-mingw, Wine Mono, Wine Gecko and FFmpeg. CI only: a full build takes
# about an hour and a half. GStreamer for winegstreamer is built first, from the
# sources' own GStreamer tree (build-gstreamer.sh).
set -eu

here="$(cd "$(dirname "$0")" && pwd -P)"
. "${PINS_FILE:-$here/pins.env}"

dry=
if [ "${1:-}" = "--dry-run" ]; then dry=1; shift; fi
[ $# -eq 1 ] || { echo "usage: build.sh [--dry-run] <work folder>" >&2; exit 2; }
work=$1

run() {
    if [ -n "$dry" ]; then echo "+ $*"; else "$@"; fi
}

source_tar="$work/downloads/crossover-sources-$CX_VERSION.tar.gz"
mingw_tar="$work/downloads/llvm-mingw-$LLVM_MINGW_VERSION.tar.xz"
mono_tar="$work/downloads/wine-mono-$WINE_MONO_VERSION-x86.tar.xz"
gecko_x86_tar="$work/downloads/wine-gecko-$WINE_GECKO_VERSION-x86.tar.xz"
gecko_x86_64_tar="$work/downloads/wine-gecko-$WINE_GECKO_VERSION-x86_64.tar.xz"
mono_license="$work/downloads/wine-mono-$WINE_MONO_VERSION-COPYING"
gecko_license="$work/downloads/wine-gecko-$WINE_GECKO_VERSION-LICENSE"
gecko_license_html="$work/downloads/wine-gecko-$WINE_GECKO_VERSION-license.html"
ffmpeg_tar="$work/downloads/ffmpeg-$FFMPEG_VERSION.tar.xz"
src="$work/src"
build="$work/build"
deps="$work/deps"
install="$work/install"
gst="$work/gst"
ffmpeg="$work/ffmpeg"

# Without --dry-run, refuse anything but the pinned inputs
if [ -z "$dry" ]; then
    [ "$(uname -m)" = x86_64 ] || { echo "build.sh: needs an x86_64 Mac (the runner is x86_64 code run by Rosetta)" >&2; exit 1; }
    for pin in "$source_tar:$CX_SOURCE_SHA256" "$mingw_tar:$LLVM_MINGW_SHA256" \
        "$mono_tar:$WINE_MONO_SHA256" "$gecko_x86_tar:$WINE_GECKO_X86_SHA256" \
        "$gecko_x86_64_tar:$WINE_GECKO_X86_64_SHA256" "$mono_license:$WINE_MONO_LICENSE_SHA256" \
        "$gecko_license:$WINE_GECKO_LICENSE_SHA256" "$gecko_license_html:$WINE_GECKO_LICENSE_HTML_SHA256" \
        "$ffmpeg_tar:$FFMPEG_SHA256"; do
        f=${pin%:*} want=${pin##*:}
        [ "$(shasum -a 256 "$f" | cut -d' ' -f1)" = "$want" ] || { echo "build.sh: $f does not match its pin" >&2; exit 1; }
    done
fi

[ -d "$XCODE_APP" ] && export DEVELOPER_DIR="$XCODE_APP/Contents/Developer"
export MACOSX_DEPLOYMENT_TARGET

run rm -rf "$src" "$build" "$deps" "$install" "$work/llvm-mingw" "$work/gst-link"
run mkdir -p "$src" "$build" "$deps/lib" "$install" "$work/llvm-mingw"
run tar -xzf "$source_tar" -C "$src"
run tar -xJf "$mingw_tar" -C "$work/llvm-mingw" --strip-components 1
# The addon versions this Wine asks for are the pinned ones
addons="$src/sources/wine/dlls/appwiz.cpl/addons.c"
for want in "MONO_VERSION \"$WINE_MONO_VERSION\"" "GECKO_VERSION \"$WINE_GECKO_VERSION\""; do
    [ -n "$dry" ] || grep -q "^#define $want" "$addons" \
        || { echo "build.sh: $addons does not define $want; update pins.env" >&2; exit 1; }
done
# The GStreamer tree in the sources is the pinned version
gst_meson="$src/sources/gstreamer/subprojects/gstreamer/meson.build"
[ -n "$dry" ] || grep -q "^  version : '$GST_VERSION',\$" "$gst_meson" \
    || { echo "build.sh: $gst_meson is not GStreamer $GST_VERSION; update pins.env" >&2; exit 1; }
PATH="$work/llvm-mingw/bin:$PATH"

if [ -n "$dry" ]; then brew() { echo "/usr/local/opt/$2"; }; fi
for f in bison flex; do PATH="$(brew --prefix "$f")/bin:$PATH"; done
export PATH

# GStreamer and the LGPL FFmpeg under gst-libav, into $gst and $ffmpeg
sh "$here/build-gstreamer.sh" ${dry:+--dry-run} "$src/sources/gstreamer" "$ffmpeg_tar" "$work"

# The dylibs Wine links or dlopens, copied with @rpath names before configure
# sees them, so the names it records are the bundled ones
lib_of() {
    case "$1" in
        freetype) echo "$(brew --prefix freetype)/lib/libfreetype.6.dylib" ;;
        gnutls) echo "$(brew --prefix gnutls)/lib/libgnutls.30.dylib" ;;
        molten-vk) echo "$(brew --prefix molten-vk)/lib/libMoltenVK.dylib" ;;
        sdl2) echo "$(brew --prefix sdl2)/lib/libSDL2-2.0.0.dylib" ;;
        sdl3) echo "$(brew --prefix sdl3)/lib/libSDL3.dylib" ;;
        *) echo "build.sh: no library known for $1" >&2; return 1 ;;
    esac
}
libs=
for f in $BREW_LINK_DEPS; do libs="$libs $(lib_of "$f")"; done
# The GStreamer libraries winegstreamer links (pkg-config names below); the
# plugins go to lib/gstreamer-1.0, where libgstreamer looks by default (it
# finds itself with dladdr), and gst-inspect-1.0 to libexec/gstreamer-1.0
gst_modules="gstreamer-1.0 gstreamer-video-1.0 gstreamer-audio-1.0 gstreamer-tag-1.0"
for l in gstreamer base video audio tag; do libs="$libs $gst/lib/libgst$l-1.0.0.dylib"; done
places=
for p in $(awk '!/^#/ && NF == 3 { print $3 }' "$here/gstreamer-plugins.txt"); do
    places="$places --place $deps/lib/gstreamer-1.0 @loader_path/.. $gst/lib/gstreamer-1.0/libgst$p.dylib"
done
places="$places --place $deps/libexec/gstreamer-1.0 @executable_path/../../lib $gst/bin/gst-inspect-1.0"
# shellcheck disable=SC2086
run sh "$here/bundle-deps.sh" --origins "$deps/origins.txt" --search "$gst/lib" --search "$ffmpeg/lib" \
    $places "$deps/lib" $libs

# winegstreamer links the bundled copies: unversioned names for configure's
# -l flags, pointing at them, so the names recorded are their @rpath ones
gst_cflags=
gst_libs="-L$work/gst-link"
run mkdir -p "$work/gst-link"
if [ -z "$dry" ]; then
    # shellcheck disable=SC2086
    gst_cflags=$(PKG_CONFIG_PATH="$gst/lib/pkgconfig" pkg-config --cflags $gst_modules)
    # shellcheck disable=SC2086
    for l in $(PKG_CONFIG_PATH="$gst/lib/pkgconfig" pkg-config --libs-only-l $gst_modules); do
        n=${l#-l}
        # Anything not bundled (-lm, -liconv) is the SDK's; check-deps.sh
        # catches it if it is not
        f=$(ls "$deps/lib/lib$n".[0-9]*.dylib 2>/dev/null | head -n 1) || true
        [ -z "$f" ] || ln -sf "$f" "$work/gst-link/lib$n.dylib"
        gst_libs="$gst_libs $l"
    done
fi

# lib/wine/x86_64-unix/../../ is lib/, where the bundled dylibs go
ldflags="-L$deps/lib -Wl,-rpath,@loader_path/../../ -Wl,-headerpad_max_install_names"

cd "$build" 2>/dev/null || [ -n "$dry" ]
run "$src/sources/wine/configure" \
    --prefix="$install" \
    --enable-archs=i386,x86_64 \
    --disable-tests \
    --with-mingw \
    --with-coreaudio \
    --with-freetype \
    --with-gstreamer \
    --with-gnutls \
    --with-opencl \
    --with-sdl \
    --with-vulkan \
    --without-alsa --without-capi --without-dbus --without-ffmpeg --without-fontconfig --without-gphoto \
    --without-gssapi --without-inotify --without-krb5 --without-netapi \
    --without-oss --without-pcap --without-pulse --without-sane --without-udev --without-usb \
    --without-v4l2 --without-wayland --without-x \
    "LDFLAGS=$ldflags" \
    "GSTREAMER_CFLAGS=$gst_cflags" "GSTREAMER_LIBS=$gst_libs" \
    "CFLAGS=-O2 -mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET"
run make -j"$(sysctl -n hw.ncpu)"
run make install-lib
# configure skips winegstreamer quietly when GStreamer does not link
[ -n "$dry" ] || [ -f "$install/lib/wine/x86_64-unix/winegstreamer.so" ] \
    || { echo "build.sh: winegstreamer.so was not built; see config.log" >&2; exit 1; }
run cp -R "$deps/lib/." "$install/lib/"
run cp -R "$deps/libexec" "$install/"
# Shared addons: wine-mono-<ver>/ and wine-gecko-<ver>-<arch>/ under share/wine
run mkdir -p "$install/share/wine/mono" "$install/share/wine/gecko"
run tar -xJf "$mono_tar" -C "$install/share/wine/mono"
run tar -xJf "$gecko_x86_tar" -C "$install/share/wine/gecko"
run tar -xJf "$gecko_x86_64_tar" -C "$install/share/wine/gecko"
# Every bundled library's license, under share/licenses/<package>/
licenses="$install/share/licenses"
# GStreamer's and FFmpeg's notices, from the trees they were built from; their
# sources are the CodeWeavers tarball and the FFmpeg tarball on the release
run mkdir -p "$licenses/gstreamer" "$licenses/ffmpeg"
run cp "$src/sources/gstreamer/LICENSE" "$licenses/gstreamer/LICENSE"
for m in gstreamer gst-plugins-base gst-plugins-good gst-plugins-bad gst-plugins-ugly gst-libav; do
    run cp "$src/sources/gstreamer/subprojects/$m/COPYING" "$licenses/gstreamer/COPYING.$m"
done
for f in LICENSE.md COPYING.LGPLv2.1 CREDITS; do
    run cp "$work/gst-build/ffmpeg/$f" "$licenses/ffmpeg/$f"
done
run sh "$here/collect-licenses.sh" --local "$gst" gstreamer --local "$ffmpeg" ffmpeg \
    "$deps/origins.txt" "$licenses" "$work/brew-sources"
run mkdir -p "$licenses/wine-mono" "$licenses/wine-gecko"
run cp "$mono_license" "$licenses/wine-mono/COPYING"
run cp "$gecko_license" "$licenses/wine-gecko/LICENSE"
run cp "$gecko_license_html" "$licenses/wine-gecko/license.html"
run sh "$here/check-deps.sh" "$install"
run python3 "$here/check_dlopen.py" "$install"
run sh "$here/check-sdl.sh" "$install"
run sh "$here/check-licenses.sh" "$install"
run sh "$here/check-gstreamer.sh" "$install"
[ -n "$dry" ] || "$install/bin/wine" --version
