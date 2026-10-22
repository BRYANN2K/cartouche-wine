# What differs from CodeWeavers' CrossOver sources

This document is for people who want to know exactly what Cartouche Wine changes compared with the CrossOver 26.3 open-source tarball, and why. It ends with a changelog per release.

## Source patches

**None.** `build.sh` unpacks `crossover-sources-26.3.0.tar.gz` (SHA-256 `ac99c8ca4b3848f3e81784135f023df266b61c2345726ea55a50b3e030dd6872`) and builds `sources/wine` as it is. No `patch` step exists. Anyone can rebuild the binaries from CodeWeavers' tarball and the scripts in this repository.

Upstream behavior that Cartouche relies on lives in CodeWeavers' sources, not here. One example: CodeWeavers' Rosetta 2 workarounds for the 32-bit syscall thunk (marked "CW HACK" in their sources). `crossover-sources-26.3.0.tar.gz` (the pinned SHA-256) carries `CW HACK 20760` in `sources/wine/dlls/wow64cpu/cpu.c`: under Rosetta 2 the 32-to-64 syscall thunk returns with `lretq`, which avoids a SIGUSR1 race ([WineHQ bug 60494](https://bugs.winehq.org/show_bug.cgi?id=60494)).

## Build configuration

`build.sh` runs `configure` with these options.

### Enabled

| Option | Why |
| --- | --- |
| `--enable-archs=i386,x86_64` | New WoW64: 32-bit and 64-bit Windows programs run from one x86_64 Unix side. macOS has no 32-bit support. |
| `--with-mingw` | Builds the PE side with llvm-mingw (pinned) instead of the host compiler. |
| `--with-coreaudio` | Audio output on macOS. |
| `--with-freetype` | Font rendering. Library bundled. |
| `--with-gnutls` | TLS for Wine's secure channel (`schannel`). Library bundled. |
| `--with-opencl` | OpenCL through Apple's framework. <!-- TODO verify: the commit history does not state the reason --> |
| `--with-sdl` | Game controllers through SDL (`winebus`). Libraries bundled. |
| `--with-gstreamer` | Game video and audio through the bundled GStreamer/FFmpeg stack (26.3.0-3 development recipe). |
| `--with-vulkan` | Vulkan through MoltenVK (bundled). |
| `--disable-tests` | Wine's own test suite is not built. It is not needed to run Wine and makes the build longer. |

OpenGL is left to `configure` (commit 738ffef): the macOS driver uses `OpenGL.framework` and needs no EGL, so no flag forces it.

### Disabled

`--without-alsa --without-capi --without-dbus --without-fontconfig --without-gphoto --without-gssapi --without-ffmpeg --without-inotify --without-krb5 --without-netapi --without-oss --without-pcap --without-pulse --without-sane --without-udev --without-usb --without-v4l2 --without-wayland --without-x`

Two groups:

- **Linux-only subsystems** with nothing to use on macOS: ALSA, OSS, PulseAudio, udev, inotify, v4l2, Wayland, X11, D-Bus.
- **Optional libraries** that Cartouche does not ship, so the archive stays self-contained: fontconfig, gphoto, GSSAPI, Kerberos, netapi, pcap, SANE, libusb and CAPI. <!-- TODO verify: the exact reason per flag is not in the commit messages -->

Versions 26.3.0-1 and 26.3.0-2 used `--without-gstreamer`. The 26.3.0-3 recipe enables GStreamer and disables Wine’s direct FFmpeg backend; FFmpeg is used through GStreamer instead.

### Compiler and linker flags

| Flag | Why |
| --- | --- |
| `CFLAGS=-O2 -mmacosx-version-min=15.0` | Optimized, with the deployment target from `pins.env`. |
| `LDFLAGS=-L<deps>/lib` | Wine links against the bundled copies, so the names it records are the bundled ones. |
| `-Wl,-rpath,@loader_path/../../` | From `lib/wine/x86_64-unix/`, this is `lib/`, where the bundled dylibs sit. |
| `-Wl,-headerpad_max_install_names` | Leaves room to rewrite install names later. |

The install uses `make install-lib` into a CrossOver-like layout: `bin/`, `lib/wine/<arch>-unix|windows/`, `share/wine/`. Cartouche's run script and ntdll patcher look there.

## Bundled libraries

Copied by `bundle-deps.sh`. It follows each dylib's load commands, copies every non-system dependency, sets its id to `@rpath/<name>`, rewrites references, and signs it ad hoc.

| Library | Why |
| --- | --- |
| FreeType | Fonts. |
| GnuTLS | TLS. |
| MoltenVK | Vulkan on Metal. |
| SDL2 (Homebrew `sdl2` is sdl2-compat) | The SDL2 API Wine's controller backend uses. |
| SDL3 | sdl2-compat opens `libSDL3.dylib` with `dlopen`. Added in 26.3.0-2. |
| Their dependencies | Whatever the load commands show. Listed in `share/licenses/dylibs.txt`. |

The build does not use anything from Homebrew at run time. `check-deps.sh` fails if a Mach-O file loads a library outside macOS and the package, or searches a folder that is not `@...`.

## Bundled addons

| Addon | Version | Why |
| --- | --- | --- |
| Wine Mono | 10.4.1 | The version Wine 11.0 asks for. `build.sh` reads it from `addons.c` and stops if it differs from the pin. Unpacked into `share/wine/mono`. |
| Wine Gecko | 2.47.4 (x86 and x86_64) | Same, in `share/wine/gecko`. |

Wine looks in these folders before it offers a download. A new prefix then never shows the download prompt, and `boot-check.sh` fails if wineboot does not use the bundled Mono.

## Checks added

| Check | What it stops |
| --- | --- |
| `fetch.sh` | A pinned download that changed. |
| `check-deps.sh` | Load commands and rpaths that point outside macOS and the package. |
| `check_dlopen.py` | Libraries named in the binaries' strings that are neither bundled nor in macOS. `dlopen-allow.txt` lists the exceptions with a reason. |
| `check-sdl.sh` | SDL3 missing at run time. It compiles `check-sdl.c` for x86_64, loads the bundled `libSDL2-2.0.0.dylib` and calls `SDL_Init` for game controllers, which makes sdl2-compat load SDL3. |
| `check-licenses.sh` | A bundled dylib, Mono or Gecko without its license. |
| `verify.sh` | An archive that does not match its checksum, is missing files, or whose `wine --version` fails. |
| `boot-check.sh` | A prefix that does not initialize, addons that are downloaded instead of used, or console programs that do not run. |
| `redist-scan.sh` | Apple Game Porting Toolkit files in a release. |

`dlopen-allow.txt` allows these names without bundling them:

- Libraries disabled with `--without-*` (D-Bus, fontconfig, Kerberos, GSSAPI, netapi, v4l2, X11, GLX, EGL, GLES) that `configure` may still name.
- `libodbc`: used only if the user has a driver manager.
- `libvulkan`: SDL3 and winevulkan try a Vulkan loader first, then MoltenVK.
- `libsteam_api`: SDL3's optional Steam Controller hook, used only inside a Steam game.
- `libd3dshared`: D3DMetal from the user's own Game Porting Toolkit, never redistributed.

## Packaging additions

`package.sh` adds to Wine's tree:

- `LICENSE`, `COPYING.LIB` and `AUTHORS`, copied from the source tarball.
- `SOURCE.md`: where the source is.
- `BUILDINFO.txt`: source version, revision, commit, llvm-mingw version, Homebrew versions, Xcode version.
- `share/licenses/`: the licenses of the bundled libraries.

The archive has a single top folder, files in sorted order, owner `root:wheel`, and is compressed with `xz -9e`. The release gets a `.sha256` file and a `manifest-entry.json` for the app.

## Naming

The display name is **Cartouche Wine**. The id, tag and file names stay `wine-crossover-<version>-<revision>` (commit f9d04ad), because installed users and the app's manifest refer to them. The name does not use "CrossOver" as a product name.

## Changelog

### 26.3.0-3 (in progress)

**GStreamer for media playback.** The recipe is on `main`; no 26.3.0-3 release has been published.

- Builds GStreamer 1.24.4 from the pinned CodeWeavers source archive and FFmpeg 6.1.6 from a separately pinned source archive.
- Bundles the selected plugins, their libraries and license files; includes FFmpeg sources in the release workflow.
- Configures Wine with `--with-gstreamer --without-ffmpeg` and checks plugin loading with `check-gstreamer.sh`.
- Full macOS compilation, relocation, prefix boot and game playback still need validation. Earlier Linux results are documented in [the implementation notes](26.3.0-3-gstreamer.md), alongside the remaining checks.

### 26.3.0-2 (prerelease)

- **SDL3 bundled.** Homebrew's SDL2 is sdl2-compat and loads `libSDL3.dylib` at run time. `bundle-deps.sh` follows load commands only, so SDL3 was missing and `winebus` saw no controller. The build now bundles SDL3 and `check-sdl.sh` checks that SDL game controllers initialize in the build and in the unpacked archive. (3f12db4)
- **Wine Mono 10.4.1 and Wine Gecko 2.47.4 bundled**, so prefixes never offer a download. `build.sh` checks the versions against Wine's `addons.c`, `verify.sh` checks the files, `boot-check.sh` checks that Mono is used. (397cf08)
- **dlopen check.** `check_dlopen.py` and `dlopen-allow.txt` catch libraries that are opened by name. First run names `libsteam_api` and `libd3dshared`, now allowed with reasons. (f1ff196, 237e9f0)
- **Headless boot check.** It initializes a prefix, installs the addons in a second pass and runs `wine cmd` and `wine reg`. The winecfg window is timed only when a GUI session exists. (2b10e26, eb1ae1f and later boot-check commits)
- **Licenses.** The license of every bundled library, Wine Mono and Wine Gecko goes into `share/licenses/`. `check-licenses.sh` fails without them. (7af8952)
- **Source archives** of the bundled Homebrew libraries are attached to the release (LGPL source offer). (379b267)
- **Display name** "Cartouche Wine". (f9d04ad)
- **Release publishing** happens from the repository's default branch. (f0ad19e)
- **Workflow actions** are pinned by commit and run on Node 24. (31ecbab)
- **collect-licenses retries** a formula's source fetch up to four times, because a GNU mirror can be broken. (39adcc4)
- Known issue: on GitHub's `macos-15-intel` image of 2026-10-22, the first `wineboot` hangs for both this build and 26.3.0-1. The boot check reports `env-cannot-boot` and the boot must be tested on a real Mac. (4c3a5dd)

### 26.3.0-1

- First release, published 2026-10-20 (tag `wine-crossover-26.3.0-1`).
- The recipe builds CodeWeavers' CrossOver 26.3.0 sources with llvm-mingw, bundles the Homebrew libraries and packages one `tar.xz` with a manifest entry, the notices and a source offer.
- The tag already had `check-deps.sh`, `verify.sh`, `boot-check.sh`, `redist-scan.sh` and the CI workflow. It had no dlopen check, no bundled SDL3, Mono or Gecko, and no license collection.
- The archive is written to an absolute output folder, because `tar` runs from the staging folder. (fef50c2)
- OpenGL is left to `configure`. (738ffef)
- Builds are published from `BRYANN2K/cartouche-wine`. (d1d17aa)

## Not decided

- What 26.3.0-3 ships for GStreamer.
- The license of the build scripts in this repository.
