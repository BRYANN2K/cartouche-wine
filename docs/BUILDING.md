# Building Cartouche Wine locally

This document is for people who want to build the `wine-crossover-<version>-x86_64.tar.xz` archive on their own Mac. Every step comes from the scripts in `packaging/wine-crossover/`. CI runs the same scripts ([RELEASING.md](RELEASING.md)).

The development recipe includes GStreamer and FFmpeg. Allow additional build time; a full macOS build of 26.3.0-3 is still pending validation.

## Prerequisites

| Need | Detail |
| --- | --- |
| An x86_64 process | `build.sh` exits unless `uname -m` is `x86_64`. CI uses a `macos-15-intel` runner. <!-- TODO verify: building on Apple silicon inside an `arch -x86_64` shell with Intel Homebrew in /usr/local; the script allows it but it was not tested for this documentation --> |
| Xcode | The version in `pins.env` (`XCODE_APP`, now `/Applications/Xcode_16.4.app`). If the folder exists, `build.sh` sets `DEVELOPER_DIR` to it. |
| Homebrew | With the formulas in `pins.env`: build tools `bison flex pkgconf meson ninja nasm`, link libraries `freetype gnutls molten-vk sdl2 sdl3`, and `glib` for GStreamer (`BREW_GST_DEPS`). |
| Python 3 | For `check_dlopen.py`, `manifest_entry.py` and the tests. |
| Network | To fetch the pinned downloads. |
| Disk | Several GB for the sources, the build tree and the install tree. <!-- TODO verify: measured disk use --> |

The deployment target is macOS 15.0 (`MACOSX_DEPLOYMENT_TARGET` in `pins.env`).

## What is pinned

`packaging/wine-crossover/pins.env` is the only place with versions and hashes. The scripts and the workflow both source it.

| Pin | Value now | What it is |
| --- | --- | --- |
| `CX_VERSION` | `26.3.0` | CodeWeavers' CrossOver source version. |
| `CX_SOURCE_URL`, `CX_SOURCE_SHA256` | see file | The LGPL tarball from CodeWeavers (149054023 bytes, Wine 11.0 inside). |
| `BUILD_REVISION` | `3` | Bumped when the same sources are built again with a changed script or toolchain. |
| `LLVM_MINGW_VERSION` and hash | `20261006` | Cross compiler for the PE side. |
| `XCODE_APP`, `MACOSX_DEPLOYMENT_TARGET` | Xcode 16.4, 15.0 | Toolchain. |
| `BREW_BUILD_DEPS`, `BREW_LINK_DEPS`, `BREW_GST_DEPS` | see above | Homebrew formulas. Versions are whatever Homebrew has. They are recorded in `BUILDINFO.txt`. |
| `GST_VERSION` | `1.24.4` | The GStreamer in `sources/gstreamer` of the tarball. No download; `build.sh` checks it. |
| `FFMPEG_VERSION`, `FFMPEG_URL`, `FFMPEG_SHA256` | `6.1.6` | FFmpeg for gst-libav, checked against the FFmpeg release key when pinned. |
| `WINE_MONO_*`, `WINE_GECKO_*` | 10.4.1, 2.47.4 | Addons and their license files, with hashes. |

A new CodeWeavers tarball means a new `CX_VERSION`, its SHA-256, and `BUILD_REVISION` back to 1.

## Steps

All commands run from the repository root. `work/` is any folder you like.

### 1. Fetch the pinned downloads

`fetch.sh <url> <sha256> <destination>` downloads a file and keeps it only if its SHA-256 matches. An existing file with the right hash is reused. A mismatch deletes the download and exits 1.

```sh
. packaging/wine-crossover/pins.env
f=packaging/wine-crossover/fetch.sh
d=work/downloads
sh $f "$CX_SOURCE_URL" "$CX_SOURCE_SHA256" "$d/crossover-sources-$CX_VERSION.tar.gz"
sh $f "$LLVM_MINGW_URL" "$LLVM_MINGW_SHA256" "$d/llvm-mingw-$LLVM_MINGW_VERSION.tar.xz"
sh $f "$WINE_MONO_URL" "$WINE_MONO_SHA256" "$d/wine-mono-$WINE_MONO_VERSION-x86.tar.xz"
sh $f "$WINE_GECKO_X86_URL" "$WINE_GECKO_X86_SHA256" "$d/wine-gecko-$WINE_GECKO_VERSION-x86.tar.xz"
sh $f "$WINE_GECKO_X86_64_URL" "$WINE_GECKO_X86_64_SHA256" "$d/wine-gecko-$WINE_GECKO_VERSION-x86_64.tar.xz"
sh $f "$WINE_MONO_LICENSE_URL" "$WINE_MONO_LICENSE_SHA256" "$d/wine-mono-$WINE_MONO_VERSION-COPYING"
sh $f "$WINE_GECKO_LICENSE_URL" "$WINE_GECKO_LICENSE_SHA256" "$d/wine-gecko-$WINE_GECKO_VERSION-LICENSE"
sh $f "$WINE_GECKO_LICENSE_HTML_URL" "$WINE_GECKO_LICENSE_HTML_SHA256" "$d/wine-gecko-$WINE_GECKO_VERSION-license.html"
sh $f "$FFMPEG_URL" "$FFMPEG_SHA256" "$d/ffmpeg-$FFMPEG_VERSION.tar.xz"
```

The file names matter: `build.sh` looks for exactly these names and refuses to run if a file does not match its pin.

### 2. Install the Homebrew formulas

```sh
brew install $BREW_BUILD_DEPS $BREW_LINK_DEPS $BREW_GST_DEPS
```

### 3. Build

```sh
sh packaging/wine-crossover/build.sh "$PWD/work"
```

Use `build.sh --dry-run <folder>` first to see the commands. A dry run does not need the downloads or Homebrew formulas. CI runs it on a macOS runner.

What `build.sh` does, in order:

1. Checks the architecture and the SHA-256 of every download.
2. Sets `DEVELOPER_DIR` and `MACOSX_DEPLOYMENT_TARGET`.
3. Empties `src`, `build`, `deps`, `install` and `llvm-mingw` under the work folder, then unpacks the sources and llvm-mingw.
4. Checks that `dlls/appwiz.cpl/addons.c` in the sources defines the Mono and Gecko versions in `pins.env`, and that `sources/gstreamer` is `GST_VERSION`. If they differ, update the pins.
5. Puts llvm-mingw, `bison` and `flex` first in `PATH`.
6. Runs `build-gstreamer.sh`: FFmpeg (LGPL, decoders only) into `work/ffmpeg`, then GStreamer core, base, good, bad, ugly and gst-libav with meson into `work/gst`, only the plugins in `gstreamer-plugins.txt`. `build-gstreamer.sh --dry-run` prints the commands. [CHANGES.md](CHANGES.md#gstreamer-from-2630-3) explains the choices.
7. Copies the five link libraries, the GStreamer libraries winegstreamer links, and every non-system dylib they load into `deps/lib` with `bundle-deps.sh`; the plugins go to `deps/lib/gstreamer-1.0` and `gst-inspect-1.0` to `deps/libexec/gstreamer-1.0`. Names become `@rpath/...`, and each copy is ad-hoc signed. `deps/origins.txt` records where each file came from.
8. Runs Wine's `configure` against that folder, with `GSTREAMER_CFLAGS` and `GSTREAMER_LIBS` pointing at the bundled GStreamer. [CHANGES.md](CHANGES.md) lists the flags and why.
9. `make`, then `make install-lib` into `install/`. Stops if `winegstreamer.so` was not built.
10. Copies `deps/lib` and `deps/libexec` into `install/`.
11. Unpacks Wine Mono and Wine Gecko into `install/share/wine/mono` and `gecko`.
12. Runs `collect-licenses.sh`: license files of every bundled formula go into `install/share/licenses/<formula>/`, their source archives into `work/brew-sources/`. GStreamer's and FFmpeg's notices are copied from their trees, Mono's and Gecko's from the pinned downloads.
13. Runs the checks: `check-deps.sh`, `check_dlopen.py`, `check-sdl.sh`, `check-licenses.sh`, `check-gstreamer.sh`.
14. Runs `install/bin/wine --version`.

### 4. Package

```sh
sh packaging/wine-crossover/package.sh work/install \
  work/downloads/crossover-sources-$CX_VERSION.tar.gz out
```

`package.sh` writes into `out/`:

- `wine-crossover-<version>-<revision>-x86_64.tar.xz`, with `LICENSE`, `COPYING.LIB`, `AUTHORS` (taken from the source tarball), `SOURCE.md` and `BUILDINFO.txt` inside. Owner and file order do not depend on the build machine.
- the `.sha256` file;
- `manifest-entry.json`, made by `manifest_entry.py`;
- `tag`, a one-line file with the release tag.

`REPOSITORY` (default `BRYANN2K/cartouche-wine`) sets the download URL in the entry. `GITHUB_SHA` sets the commit recorded in `SOURCE.md` and `BUILDINFO.txt`.

### 5. Verify

```sh
sh packaging/wine-crossover/verify.sh out/wine-crossover-*-x86_64.tar.xz
```

This checks the archive the way the app gets it: the checksum, one top folder, the expected files, Mono and Gecko, the four checks again, and `wine --version` in a scratch home. Then run the boot check:

```sh
mkdir -p work/runner && tar -xJf out/*-x86_64.tar.xz -C work/runner
sh packaging/wine-crossover/boot-check.sh "work/runner/$(cat out/tag)" out/boot 180
```

See [RELEASING.md](RELEASING.md) for what it checks and its options.

### The script tests

```sh
python3 -m unittest discover -s packaging/tests -p 'test_wine_crossover.py'
```

CI runs these tests and a dry run on every pull request that touches `packaging/wine-crossover/`.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `build.sh: needs an x86_64 Mac` | The shell is arm64. Use an x86_64 environment. |
| `fetch: ... has SHA-256 X, the pin is Y` | The file changed upstream or the download broke. Do not edit the pin without checking the new file. |
| `build.sh: <file> does not match its pin` | A file in `work/downloads` has another name or content. Fetch it again. |
| `addons.c does not define MONO_VERSION ...` | Wine asks for other Mono or Gecko versions than `pins.env`. Update the pins and hashes together. |
| `bundle-deps: cannot find @rpath/...` | A dylib's dependency is not next to it. Check that the Homebrew formula is installed and up to date. |
| `check-deps: the package depends on files outside it` | A Mach-O file loads or searches a path outside macOS and the package, such as `/usr/local/...`. Make `bundle-deps.sh` copy that library, or fix the rpath. |
| `check-dlopen: these may be dlopened but are neither in the package nor in macOS` | A binary names a dylib that is not bundled. Bundle it (`BREW_LINK_DEPS`), or allow it with a reason in `dlopen-allow.txt` if it is optional or supplied by the user. |
| `build.sh: .../meson.build is not GStreamer ...` | The source tarball's GStreamer is not `GST_VERSION`. Check the new tarball and update the pin. |
| `build-gstreamer: FFmpeg is not configured LGPL 2.1+` | A configure flag turned on GPL, version 3 or nonfree code. Remove it. |
| `build-gstreamer: not built: libgst<name>.dylib` | A meson option in `gstreamer-plugins.txt` is wrong, or a dependency of that plugin is missing. Read the module's `meson-logs/meson-log.txt` under `work/gst-build`. |
| `build.sh: winegstreamer.so was not built` | `configure` could not link GStreamer. Look for `gstreamer` in `work/build/config.log`. |
| `check-gstreamer: ...` | A plugin is missing, does not load (blacklisted), loads from outside the package, is not LGPL, or an element is missing. Run `libexec/gstreamer-1.0/gst-inspect-1.0 <plugin>` from the install tree to see why. |
| `check-sdl: missing libSDL3.dylib` or the SDL probe fails | SDL3 did not reach `lib/`. sdl2-compat loads SDL3 at run time, so it must be in `BREW_LINK_DEPS`. |
| `collect-licenses: could not fetch the source of <formula>` | `brew fetch` failed four times. A mirror may be down (this happened with a GNU mirror). Run again later. |
| `collect-licenses: no license file found for <formula>` | The keg and the source hold no file that looks like a license. Look at the formula and extend `is_license` or the search depth. |
| `check-licenses: bundled code without its license` | A dylib in `lib/` has no line in `share/licenses/dylibs.txt`, or its folder is empty. |
| `package.sh: ... is not the pinned source tarball` | The tarball passed to `package.sh` is not the one in `pins.env`. |
| First `wine` start in a new prefix looks stuck | It can take many minutes under Rosetta 2. The boot check allows 1200 s. Wine itself gives up waiting for wineboot after 300 s (`run_wineboot boot event wait timed out`, then `could not load kernel32.dll, status c0000135`). |

If a Wine problem is not in the list, collect logs as described in [CONTRIBUTING.md](../CONTRIBUTING.md).
