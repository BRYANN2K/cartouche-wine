<div align="center">

# Cartouche Wine

**Wine built from CodeWeavers' open-source CrossOver 26.3 sources, packaged for the Cartouche game launcher on Apple silicon.**

[![Release](https://img.shields.io/github/v/release/BRYANN2K/cartouche-wine?include_prereleases&filter=wine-crossover-*&style=flat-square&label=release&color=A98BF5)](https://github.com/BRYANN2K/cartouche-wine/releases)
[![License](https://img.shields.io/badge/license-LGPL--2.1-2563EB?style=flat-square)](docs/LICENSES.md)
[![Platform](https://img.shields.io/badge/macOS-Apple%20silicon%20(x86__64%20under%20Rosetta%202)-1D2027?style=flat-square&logo=apple&logoColor=white)](#install-and-use)
[![CI](https://img.shields.io/github/actions/workflow/status/BRYANN2K/cartouche-wine/wine-crossover.yml?branch=wine-build&style=flat-square&label=build)](https://github.com/BRYANN2K/cartouche-wine/actions/workflows/wine-crossover.yml)

[What it is](#what-it-is) · [What we add](#what-we-add-on-top-of-crossover-263-and-why) · [Install and use](#install-and-use) · [Build](#building-from-source) · [Releases](#ci-and-release-flow) · [Licenses](#licenses-and-the-source-offer) · [Docs](#documentation)

</div>

---

> **This is not a CodeWeavers product.** It is not CrossOver, and CodeWeavers does not make, review or support it.
> If you want a supported way to run Windows software on a Mac, [buy CrossOver](https://www.codeweavers.com/crossover).
> Do not ask CodeWeavers or WineHQ for help with this build. Report problems here.

**Cartouche Wine is the Wine build that ships with [Cartouche](#install-and-use).** Cartouche is a free macOS game launcher for Apple silicon. It runs Windows games through Steam Play inside Mac Steam, through Epic, GOG and Amazon, through Windows installers, and runs consoles through RetroArch.

This repository holds the build, packaging and CI that produce one file per release: `wine-crossover-<version>-x86_64.tar.xz`. The Cartouche app installs and updates that file through a signed manifest. The repository contains no Wine source. It downloads CodeWeavers' published source tarball, checks its SHA-256 and builds it.

## What it is

Three projects meet here.

- **[Wine](https://www.winehq.org/)** is the open-source Windows compatibility layer. WineHQ and its contributors write it. It is under the LGPL.
- **[CrossOver](https://www.codeweavers.com/crossover)** is CodeWeavers' commercial product built on Wine. CodeWeavers pays many of Wine's main developers and publishes the open-source part of CrossOver as a [source tarball](https://www.codeweavers.com/crossover/source) under the LGPL. That tarball holds Wine 11.0 plus CodeWeavers' changes, including fixes for macOS and Rosetta 2.
- **Cartouche Wine** is that tarball, built unchanged by a pinned recipe, with the dependencies bundled into the archive so it runs on a Mac that has no Homebrew.

We apply **no source patches** to CodeWeavers' sources. Everything we change is in the build flags, the bundled libraries, the checks and the packaging. [docs/CHANGES.md](docs/CHANGES.md) lists each change.

The build is x86_64 code. Apple silicon runs it through Rosetta 2. It is built with the new WoW64 layout (`--enable-archs=i386,x86_64`), so 32-bit Windows programs run without 32-bit Unix libraries.

| | Wine (WineHQ) | CrossOver | Cartouche Wine |
| --- | --- | --- | --- |
| Source | wine-11.0 and later | Wine 11.0 plus CodeWeavers' changes | The CrossOver 26.3 source tarball, no patches added |
| Product | Source code | Commercial app, support | Free build for the Cartouche launcher |
| Support | WineHQ community | CodeWeavers | Issues on this repository only |
| Ships | Source | The CrossOver app | `tar.xz` with Wine and its libraries |

## What we add on top of CrossOver 26.3, and why

The full list, with commits and checks, is in [docs/CHANGES.md](docs/CHANGES.md).

| What | Why |
| --- | --- |
| Pinned inputs: source tarball, llvm-mingw, Wine Mono, Wine Gecko, all checked by SHA-256 (`fetch.sh`, `pins.env`) | A build is repeatable, and a changed upstream file stops the build. |
| Every needed Homebrew dylib copied into `lib/` with `@rpath` names, ad-hoc signed | The archive runs on a Mac with no Homebrew. arm64 refuses unsigned code, and editing load commands breaks signatures. |
| FreeType, GnuTLS, MoltenVK, SDL2 (sdl2-compat) and SDL3 bundled | Fonts, TLS, Vulkan on Metal and game controllers. |
| SDL3 added in 26.3.0-2 | Homebrew's SDL2 is sdl2-compat and opens `libSDL3.dylib` at run time. Load commands do not show that, so SDL3 was missing and Wine saw no controller. |
| Wine Mono 10.4.1 and Wine Gecko 2.47.4 in `share/wine/` | These are the versions Wine 11.0 asks for. `build.sh` checks that. A fresh prefix then never offers a download. |
| A `dlopen` check (`check_dlopen.py`, `dlopen-allow.txt`) | `otool` only sees load commands. Libraries opened by name at run time were how SDL3 went missing. |
| A boot check (`boot-check.sh`) | A build that starts `wine --version` can still fail to create a prefix. The check creates one, installs the addons and runs console programs. |
| License of every bundled library, plus its source archive, in the release | The LGPL source offer, and the licenses of the libraries we ship. |
| `--without-*` for Linux-only and unused subsystems; `--with-mingw` using llvm-mingw | A Mac build needs no ALSA, X11 and so on, and PE files must be cross-compiled. |
| Wine laid out like CrossOver (`bin/`, `lib/wine/<arch>-unix\|windows/`, `share/wine/`) | Cartouche's run script and its ntdll patcher look for files there. |
| Display name "Cartouche Wine"; ids, tags and file names stay `wine-crossover-*` | The name must say that this is not CrossOver. Renaming ids would break installed users. |
| A scan that fails on Apple Game Porting Toolkit files (`packaging/redist-scan.sh`) | Apple's license forbids redistributing them. |
| In progress for 26.3.0-3: GStreamer | Media playback in games (Media Foundation) needs Wine's `winegstreamer`. 26.3.0-2 builds `--without-gstreamer`. |

## What is inside a release archive

Each release `wine-crossover-<version>-<revision>` has these assets:

| Asset | Purpose |
| --- | --- |
| `wine-crossover-<version>-<revision>-x86_64.tar.xz` | Wine and its libraries. |
| `...-x86_64.tar.xz.sha256` | Checksum of the archive. |
| `manifest-entry.json` | The entry (URL, size, SHA-256) the app pins. |
| `SOURCE.md` | The source offer, also inside the archive. |
| `crossover-sources-<version>.tar.gz` | A copy of CodeWeavers' source tarball. |
| `brew-<formula>-<version>.<ext>` | The source of each bundled Homebrew library. |

The archive unpacks into one folder named like the release:

```text
wine-crossover-26.3.0-2/
  bin/                      wine, wineserver and friends
  lib/*.dylib               bundled libraries (FreeType, GnuTLS, MoltenVK, SDL2, SDL3, and their dependencies)
  lib/wine/x86_64-unix/     Wine's Unix side (x86_64, run by Rosetta 2)
  lib/wine/x86_64-windows/  PE modules, 64-bit
  lib/wine/i386-windows/    PE modules, 32-bit
  share/wine/               wine.inf, mono/ and gecko/ addons
  share/licenses/<package>/ licenses of bundled libraries, Wine Mono and Wine Gecko
  share/licenses/dylibs.txt which dylib comes from which package
  share/licenses/formulas.txt formulas and versions
  LICENSE COPYING.LIB AUTHORS   Wine's notices
  SOURCE.md                 where to get the source
  BUILDINFO.txt             versions of the toolchain and libraries
```

## Install and use

### Inside Cartouche

Nothing to do by hand. Cartouche lists Cartouche Wine in **Settings > Runners**, downloads the archive, checks its SHA-256 against the pinned entry and unpacks it. Once a day the app reads a newer manifest from this repository, checks its Ed25519 signature and offers **Update** when a new build is listed. Old builds stay in the manifest, so installed users can update from them.

### Standalone

You can use a release without the app. You need an Apple silicon Mac with Rosetta 2:

```sh
softwareupdate --install-rosetta --agree-to-license
```

Download the archive and its `.sha256` from the [releases](https://github.com/BRYANN2K/cartouche-wine/releases), then:

```sh
shasum -a 256 -c wine-crossover-26.3.0-2-x86_64.tar.xz.sha256
tar -xJf wine-crossover-26.3.0-2-x86_64.tar.xz
export WINEPREFIX="$HOME/.wine-cartouche"
wine-crossover-26.3.0-2/bin/wine winecfg
```

Notes:

- The first start of a new prefix can take many minutes under Rosetta 2. Wait for it. Do not start a game before it ends.
- Wine Mono and Wine Gecko are in the archive, so Wine does not ask to download them.
- If macOS blocks the files you downloaded in a browser, remove the quarantine flag with `xattr -dr com.apple.quarantine wine-crossover-26.3.0-2`. <!-- TODO verify: Gatekeeper behavior on the extracted archive; not tested for this documentation -->
- Apple's D3DMetal (Game Porting Toolkit) is not included, because Apple's license forbids redistributing it. Cartouche can load it from the user's own copy.

## Building from source

You need an x86_64 environment with Xcode 16.4, Homebrew and about an hour. The short version:

```sh
. packaging/wine-crossover/pins.env
brew install $BREW_BUILD_DEPS $BREW_LINK_DEPS
# download and verify the pinned files with packaging/wine-crossover/fetch.sh, then:
sh packaging/wine-crossover/build.sh "$PWD/work"
```

[docs/BUILDING.md](docs/BUILDING.md) has the prerequisites, every step and troubleshooting. `build.sh --dry-run <folder>` prints the commands and builds nothing.

## CI and release flow

Two workflows run in this repository.

1. **`wine-crossover`** builds, checks and, on request, publishes a prerelease. It needs no secret. The checks are: the script tests, a dry run, `verify.sh`, the dlopen and license checks, the Game Porting Toolkit scan and the boot check.
2. **`runner-manifest`** promotes a tested release into the signed manifest the app reads. It runs in the `release` environment, which holds the **`SPARKLE_PRIVATE_KEY`** secret. That secret is the same EdDSA key Cartouche uses to sign its Sparkle updates. It is one base64 line.

```text
workflow_dispatch (publish) -> build -> checks -> prerelease wine-crossover-<ver>-<rev>
        -> test on a real Mac (boot a prefix, controller test)
        -> workflow_dispatch runner-manifest (build_id, confirm_tested)
        -> manifest/runners.json committed, signed, uploaded to the `manifest` release
        -> the app downloads it within a day and shows Update
```

Nothing promotes a build by itself. GitHub's `macos-15-intel` image could no longer boot a Wine prefix on 2026-10-22, so the boot check reports `env-cannot-boot` there and a person must test the build on a Mac first. Details are in [docs/RELEASING.md](docs/RELEASING.md) and [manifest/README.md](manifest/README.md).

## Versioning

Releases are named `wine-crossover-<CX_VERSION>-<BUILD_REVISION>`, for example `wine-crossover-26.3.0-2`.

- `26.3.0` is the CrossOver source version. A new CodeWeavers tarball means a new version and the revision goes back to 1.
- The last number is the build revision. It goes up when the same sources are built again with a changed script, library or toolchain.
- A release tag is never reused. CI refuses to publish a tag that exists.

| Release | State | In short |
| --- | --- | --- |
| `wine-crossover-26.3.0-1` | Released 2026-10-20 | First build. |
| `wine-crossover-26.3.0-2` | Prerelease | SDL3 for controllers, Mono and Gecko bundled, dlopen and boot checks, licenses and source archives, the display name. |
| `26.3.0-3` | In progress | GStreamer for media playback. |

See [docs/CHANGES.md](docs/CHANGES.md).

## Licenses and the source offer

Wine is under the GNU Lesser General Public License, version 2.1 or later. The bundled libraries, Wine Mono and Wine Gecko keep their own licenses. The archive carries `LICENSE`, `COPYING.LIB`, `AUTHORS` and `share/licenses/`. Every release also carries CodeWeavers' source tarball and the source archives of the bundled Homebrew libraries. [docs/LICENSES.md](docs/LICENSES.md) explains how the offer is met and how to rebuild the binaries from it.

The license of the build scripts in this repository: Not decided. <!-- TODO verify: no LICENSE file in the repository yet -->

## Credits

- **[CodeWeavers](https://www.codeweavers.com/)** publishes the CrossOver sources under the LGPL and employs many of Wine's developers. Their Rosetta 2 and macOS fixes are what make this build useful. Thank you. Buy [CrossOver](https://www.codeweavers.com/crossover) if you want support.
- **[WineHQ](https://www.winehq.org/)** and the Wine contributors write Wine, Wine Mono and Wine Gecko.
- **[llvm-mingw](https://github.com/mstorsjo/llvm-mingw)** by Martin Storsjo provides the cross compiler for the Windows side.
- The projects we bundle: FreeType, GnuTLS, MoltenVK, SDL and their dependencies. Their licenses are in each release.
- **[Gcenx](https://github.com/Gcenx/macOS_Wine_builds)** builds Wine for macOS and shaped what people expect from such a build. Cartouche lists those builds next to this one.

## Documentation

| Document | For |
| --- | --- |
| [docs/BUILDING.md](docs/BUILDING.md) | Building locally: prerequisites, pins, steps, troubleshooting. |
| [docs/CHANGES.md](docs/CHANGES.md) | Every difference from the CrossOver sources, and the changelog per release. |
| [docs/RELEASING.md](docs/RELEASING.md) | CI, checks, publishing and promoting the manifest. |
| [docs/LICENSES.md](docs/LICENSES.md) | LGPL obligations and the source offer. |
| [manifest/README.md](manifest/README.md) | The runner manifest and its signing. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Reporting issues with logs, and contributing. |
| [SECURITY.md](SECURITY.md) | Reporting security problems. |
