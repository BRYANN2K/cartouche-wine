<div align="center">

# Cartouche Wine

**Windows games on macOS, powered by Wine.**

Wine built from CodeWeavers’ open-source CrossOver sources,\
with the libraries needed by the Cartouche launcher bundled alongside it.

[![Release](https://img.shields.io/github/v/release/BRYANN2K/cartouche-wine?include_prereleases&filter=wine-crossover-*&style=flat-square&label=download&color=8b5cf6)](https://github.com/BRYANN2K/cartouche-wine/releases)
[![Build](https://img.shields.io/github/actions/workflow/status/BRYANN2K/cartouche-wine/wine-crossover.yml?branch=main&style=flat-square&label=build)](https://github.com/BRYANN2K/cartouche-wine/actions/workflows/wine-crossover.yml)
![Platform](https://img.shields.io/badge/macOS-15%2B-18181b?style=flat-square&logo=apple&logoColor=white)
![Architecture](https://img.shields.io/badge/Apple_silicon-via_Rosetta_2-18181b?style=flat-square)

[Download](https://github.com/BRYANN2K/cartouche-wine/releases) · [Build from source](docs/BUILDING.md) · [Changelog](docs/CHANGES.md) · [Report an issue](https://github.com/BRYANN2K/cartouche-wine/issues)

</div>

## What is this?

Cartouche Wine is the Windows compatibility runtime used by **Cartouche**, a macOS game launcher. This repository contains the recipes, checks and workflows that build that runtime. It does not contain the launcher or a copy of the Wine source tree.

The recipe downloads CodeWeavers’ published CrossOver source archive, verifies its checksum and builds Wine **without adding Wine source patches**. It packages the result with its dependencies so users do not need Homebrew.

| Project | Its role |
| --- | --- |
| [Wine](https://www.winehq.org/) | The open-source compatibility layer that runs Windows programs. |
| [CrossOver](https://www.codeweavers.com/crossover) | CodeWeavers’ commercial product. Its published open-source components are the basis of this build. |
| **Cartouche Wine** | An independent build of those components, packaged for Cartouche. |

Cartouche Wine is maintained independently of CodeWeavers and WineHQ. For commercial support, use [CrossOver](https://www.codeweavers.com/crossover). For problems with this build, [open an issue here](https://github.com/BRYANN2K/cartouche-wine/issues).

## Choose a version

| Version | Status | Main changes |
| --- | --- | --- |
| [26.3.0-2](https://github.com/BRYANN2K/cartouche-wine/releases/tag/wine-crossover-26.3.0-2) | Published prerelease | SDL3 for controllers, bundled Mono and Gecko, dependency and license checks. |
| [26.3.0-1](https://github.com/BRYANN2K/cartouche-wine/releases/tag/wine-crossover-26.3.0-1) | Previous release | First packaged build. |
| **26.3.0-3** | In development on `main` | GStreamer and FFmpeg for game video playback. Full macOS build and game validation remain pending. |

A published archive is not a guarantee that every game works. New builds enter Cartouche’s update manifest only after a separate promotion step requiring a real Mac boot and controller test. See [release checks and known CI limits](docs/RELEASING.md).

## Install and run

**Requirements:** macOS 15 or later and Rosetta 2 on Apple silicon. The runtime is x86_64; its WoW64 layout supports both 32-bit and 64-bit Windows programs.

### With Cartouche

Open **Settings → Runners** and select **Cartouche Wine**. The launcher downloads and verifies the selected archive. Updates are offered through a signed runner manifest.

### Without the launcher

Install Rosetta 2 if needed:

```sh
softwareupdate --install-rosetta --agree-to-license
```

Download these two files from the [26.3.0-2 release](https://github.com/BRYANN2K/cartouche-wine/releases/tag/wine-crossover-26.3.0-2) into the same folder:

- `wine-crossover-26.3.0-2-x86_64.tar.xz`
- `wine-crossover-26.3.0-2-x86_64.tar.xz.sha256`

Then verify, extract and initialize a dedicated Wine prefix:

```sh
shasum -a 256 -c wine-crossover-26.3.0-2-x86_64.tar.xz.sha256
tar -xJf wine-crossover-26.3.0-2-x86_64.tar.xz
export WINEPREFIX="$HOME/.wine-cartouche"
./wine-crossover-26.3.0-2/bin/wine winecfg
```

The first prefix initialization can take several minutes under Rosetta. Wait for it to finish before launching a game. Keep the same `WINEPREFIX` when running your Windows executable:

```sh
./wine-crossover-26.3.0-2/bin/wine /path/to/game.exe
```

## What is bundled?

- **Wine**, built from the pinned CrossOver 26.3.0 sources.
- **FreeType and GnuTLS** for fonts and TLS.
- **MoltenVK** for Vulkan on Metal; **SDL2 and SDL3** for controllers.
- **Wine Mono 10.4.1 and Wine Gecko 2.47.4**, available locally during prefix setup.
- Dependency licenses, source information and a build record.

The development recipe for **26.3.0-3** also builds GStreamer 1.24.4 and FFmpeg 6.1.6. These are **not included in 26.3.0-2**. See the [GStreamer implementation and pending validation](docs/CHANGES.md#gstreamer-from-2630-3).

Apple’s Game Porting Toolkit and D3DMetal are not bundled. The recipe includes a redistribution scan to keep them out of release archives.

## Build and contribute

Development uses a single branch: **`main`**. Release tags use `wine-crossover-<source-version>-<build-revision>`.

A full build needs an x86_64 macOS environment, Xcode and Homebrew. Follow the [build guide](docs/BUILDING.md) for downloads, dependencies, packaging and verification. To inspect the recipe without downloading or compiling Wine:

```sh
sh packaging/wine-crossover/build.sh --dry-run "$PWD/work"
```

Before proposing a change, run the [local checks](CONTRIBUTING.md). Build and manifest publication are manually dispatched workflows; a commit to `main` does not publish a Wine release.

## Documentation

| Guide | What you will find |
| --- | --- |
| [Building](docs/BUILDING.md) | Prerequisites, pinned downloads, build commands and troubleshooting. |
| [Changes](docs/CHANGES.md) | Build choices and differences from the upstream sources. |
| [Releasing](docs/RELEASING.md) | CI checks, release assets and promotion requirements. |
| [Runner manifest](manifest/README.md) | The version list, signatures and update workflow. |
| [Licenses](docs/LICENSES.md) | Component licenses, notices and corresponding sources. |
| [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) | Bug reports, contributions and security reports. |

## Credits and licenses

This build depends on the work of **[WineHQ and its contributors](https://www.winehq.org/)**, **[CodeWeavers](https://www.codeweavers.com/)**, **[llvm-mingw](https://github.com/mstorsjo/llvm-mingw)** and the bundled library projects. [Gcenx’s macOS Wine builds](https://github.com/Gcenx/macOS_Wine_builds) are also a reference for this project.

Wine is licensed under **LGPL-2.1-or-later**. Bundled components retain their own licenses; release archives include their notices. Source assets and coverage vary by release—see [the license and source guide](docs/LICENSES.md). The build scripts in this repository do not yet have a declared license.
