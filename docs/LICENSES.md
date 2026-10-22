# Licenses and the source offer

This document is for users, packagers and anyone checking that Cartouche Wine meets its license obligations. It is not legal advice.

## What is under which license

| Part | License | Where |
| --- | --- | --- |
| Wine, as in CodeWeavers' CrossOver 26.3 sources | GNU Lesser General Public License, version 2.1 or later | `COPYING.LIB`, `LICENSE`, `AUTHORS` at the top of the archive |
| Bundled libraries (FreeType, GnuTLS, MoltenVK, SDL2, SDL3, GLib and their dependencies) | Each has its own | `share/licenses/<package>/` |
| GStreamer 1.24.4 libraries, plugins (`lib/gstreamer-1.0`) and `gst-inspect-1.0` (from 26.3.0-3) | LGPL 2.1 or later; built with `-Dgpl=disabled`, only LGPL plugins (`mpegpsdemux` is MPL-1.1/LGPL dual-licensed) | `share/licenses/gstreamer/` |
| FFmpeg 6.1.6 (from 26.3.0-3) | LGPL 2.1 or later: configured without `--enable-gpl`, `--enable-version3` or `--enable-nonfree`, decoders only | `share/licenses/ffmpeg/` |
| Wine Mono | Its own licenses (`COPYING` of the tagged source) | `share/licenses/wine-mono/` |
| Wine Gecko | Its own licenses (`LICENSE`, `license.html`) | `share/licenses/wine-gecko/` |
| The build scripts in this repository | Not decided | <!-- TODO verify: no LICENSE file in the repository --> |

`share/licenses/dylibs.txt` maps every `lib/*.dylib`, GStreamer plugin and tool to its package. `share/licenses/formulas.txt` lists the Homebrew formulas and their versions. `check-licenses.sh` fails the build if a bundled dylib, plugin or tool, Wine Mono or Wine Gecko has no license files. `check-gstreamer.sh` fails if a GStreamer plugin does not declare LGPL.

License files come from the Homebrew keg and from the formula's source archive, because kegs keep only some of them.

## The source offer

The LGPL requires that anyone who gets the binaries can get the source and rebuild them. Cartouche Wine meets this in four ways. Every release has:

1. **CodeWeavers' source tarball**, `crossover-sources-<version>.tar.gz`, attached to the same release as the archive. It is the file the build downloaded. Its URL and SHA-256 are in `SOURCE.md` and `pins.env`.
2. **The source archives of the bundled Homebrew libraries**, attached as `brew-<formula>-<version>.<ext>`.
3. **GStreamer and FFmpeg** (from 26.3.0-3). GStreamer is built from `sources/gstreamer` inside CodeWeavers' tarball (item 1). FFmpeg's release tarball is attached as `ffmpeg-<version>.tar.xz`; its URL and SHA-256 are in `SOURCE.md` and `pins.env`.
4. **The build scripts**, in this repository. `SOURCE.md` links to `packaging/wine-crossover` at the exact commit.

`SOURCE.md` is inside the archive and is also the release description. It names the toolchain: Xcode, llvm-mingw, the deployment target, the Homebrew formulas (versions in `BUILDINFO.txt`).

We add no source patches to Wine ([CHANGES.md](CHANGES.md)). The tarball and the scripts are therefore the complete corresponding source for Wine. Wine Mono and Wine Gecko are bundled as the binary tarballs published by WineHQ. Their sources are at the tags named in `pins.env`. <!-- TODO verify: whether Mono and Gecko source needs to be attached to the release as well -->

## Rebuilding

Follow [BUILDING.md](BUILDING.md). With the pinned inputs you get a build from the same sources. Because Homebrew formulas change versions, the bundled libraries can differ from a release. `BUILDINFO.txt` and the attached `brew-*` archives show the versions that were used.

You may replace a bundled LGPL library with your own build. The libraries are separate dylibs in `lib/` loaded through `@rpath`. <!-- TODO verify: replacement keeps the archive working when the replacement is ABI-compatible and re-signed -->

## Patents

26.3.0-3 includes decoders for H.264, AAC, WMV/VC-1 and WMA, the same set as other free Wine builds for macOS. HEVC and E-AC-3 decoders are left out on purpose, and no encoder, x264, x265 or openh264 is built. This has had no legal review.

## What is never shipped

- Apple's Game Porting Toolkit and D3DMetal. Apple's license forbids redistributing them. `packaging/redist-scan.sh` fails the build if they appear in an archive, by file name and by SHA-256. Cartouche can load D3DMetal from the user's own installation.

## Trademarks

Wine is a trademark of its owners. CrossOver is a registered trademark of CodeWeavers, Inc. This project uses these names only to say what the software is built from. It is not CrossOver and is not endorsed by CodeWeavers or WineHQ. <!-- TODO verify: exact trademark wording and owners -->

## Third-party notices

The notices for what a release contains are inside the release archive under `share/licenses/`. Not decided: whether a repository-level `THIRD-PARTY-LICENSES` file will repeat them.
