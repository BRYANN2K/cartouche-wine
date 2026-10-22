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
| `--with-gstreamer` | Builds `winegstreamer`, which plays games' videos and audio through Media Foundation, DirectShow and the WM ASF reader. GStreamer is built from CodeWeavers' tarball and bundled (see [GStreamer](#gstreamer-from-2630-3)). Since 26.3.0-3. |
| `--with-opencl` | OpenCL through Apple's framework. <!-- TODO verify: the commit history does not state the reason --> |
| `--with-sdl` | Game controllers through SDL (`winebus`). Libraries bundled. |
| `--with-vulkan` | Vulkan through MoltenVK (bundled). |
| `--disable-tests` | Wine's own test suite is not built. It is not needed to run Wine and makes the build longer. |

OpenGL is left to `configure` (commit 738ffef): the macOS driver uses `OpenGL.framework` and needs no EGL, so no flag forces it.

### Disabled

`--without-alsa --without-capi --without-dbus --without-ffmpeg --without-fontconfig --without-gphoto --without-gssapi --without-inotify --without-krb5 --without-netapi --without-oss --without-pcap --without-pulse --without-sane --without-udev --without-usb --without-v4l2 --without-wayland --without-x`

Three groups:

- **Linux-only subsystems** with nothing to use on macOS: ALSA, OSS, PulseAudio, udev, inotify, v4l2, Wayland, X11, D-Bus.
- **Optional libraries** that Cartouche does not ship, so the archive stays self-contained: fontconfig, gphoto, GSSAPI, Kerberos, netapi, pcap, SANE, libusb and CAPI. <!-- TODO verify: the exact reason per flag is not in the commit messages -->
- **`--without-ffmpeg`**: Wine's own FFmpeg backend (`winedmo`) is not built. Video goes through `winegstreamer`, and the only FFmpeg in the package is the decoders-only one under gst-libav.

Up to 26.3.0-2 the recipe also passed `--without-gstreamer`. 26.3.0-3 replaces it with `--with-gstreamer` and `--without-ffmpeg`.

`GSTREAMER_CFLAGS` and `GSTREAMER_LIBS` are set by `build.sh` from the bundled GStreamer, through unversioned links to the bundled copies, so `winegstreamer.so` records their `@rpath` names. `build.sh` fails if `winegstreamer.so` was not built, because `configure` skips it quietly when GStreamer does not link.

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
| GStreamer 1.24.4 libraries, 21 plugins and `gst-inspect-1.0` | `winegstreamer`. Built from CodeWeavers' tarball, not from Homebrew. Added in 26.3.0-3. |
| FFmpeg 6.1.6 (`libavcodec`, `libavformat`, `libavutil`, `libavfilter`, `libswresample`, `libswscale`) | The decoders under gst-libav. LGPL, decoders and parsers only. Added in 26.3.0-3. |
| GLib (Homebrew `glib`, with gettext's `libintl` and `pcre2`) | GStreamer is built on GLib. Added in 26.3.0-3. |
| Their dependencies | Whatever the load commands show. Listed in `share/licenses/dylibs.txt`. |

Plugins go to `lib/gstreamer-1.0` with the `LC_RPATH` `@loader_path/..`, and `gst-inspect-1.0` to `libexec/gstreamer-1.0` with `@executable_path/../../lib` (`bundle-deps.sh --place`). Every absolute `LC_RPATH` that meson leaves is removed.

The build does not use anything from Homebrew at run time. `check-deps.sh` fails if a Mach-O file loads a library outside macOS and the package, or searches a folder that is not `@...`.

## Bundled addons

| Addon | Version | Why |
| --- | --- | --- |
| Wine Mono | 10.4.1 | The version Wine 11.0 asks for. `build.sh` reads it from `addons.c` and stops if it differs from the pin. Unpacked into `share/wine/mono`. |
| Wine Gecko | 2.47.4 (x86 and x86_64) | Same, in `share/wine/gecko`. |

Wine looks in these folders before it offers a download. A new prefix then never shows the download prompt, and `boot-check.sh` fails if wineboot does not use the bundled Mono.

## GStreamer (from 26.3.0-3)

### Where it comes from

We build the GStreamer tree that ships inside CodeWeavers' CrossOver 26.3.0 source tarball. We do not use the official GStreamer.framework pkg or Homebrew's GStreamer.

What the tarball holds:

- `sources/gstreamer` is the GStreamer **1.24.4** monorepo (its `meson.build` says `version : '1.24.4'`; `build.sh` fails if it differs from `GST_VERSION`). It has `subprojects/gstreamer`, `gst-plugins-base`, `-good`, `-bad`, `-ugly` and `gst-libav`, about 198 MB.
- `sources/glib` (2.78.0) is there too. We do not build it; GLib comes from Homebrew.
- There is no FFmpeg. `subprojects/FFmpeg.wrap` is a git wrap that points at the `meson-6.1` branch of GStreamer's FFmpeg port.

Why this and not the official framework pkg:

- **One source offer.** GStreamer's corresponding source is the CodeWeavers tarball that every release already carries. A binary framework would need the matching source of each of its ~100 bundled libraries, plus cerbero's patches.
- **LGPL by construction.** Every module is configured with `--auto-features=disabled` and `-Dgpl=disabled`. Only the plugins in `packaging/wine-crossover/gstreamer-plugins.txt` are enabled. `check-gstreamer.sh` fails on any plugin that is not LGPL.
- **Reproducible in CI.** The inputs are the pinned tarball, one pinned FFmpeg tarball, and Homebrew's glib, meson, ninja and nasm. `--wrap-mode=nofallback` means meson never downloads anything.
- **Same version CodeWeavers ships the source for.**
- **Costs:** a longer CI build, and a plugin list we maintain ourselves.

The official LGPL framework stays the fallback if the source build stops working on the runner. Nothing for it is pinned.

### FFmpeg

gst-libav needs FFmpeg. `build-gstreamer.sh` builds **FFmpeg 6.1.6**, the latest point release of the 6.1 branch that the GStreamer tree's wrap names (released 2026-06-21). The tarball is pinned by URL and SHA-256 in `pins.env`. Its `.asc` was checked on 2026-10-22 against the FFmpeg release key `FCF9 86EA 15E6 E293 A564 4F10 B432 2F04 D676 58D8`.

It is configured:

- **LGPL 2.1 or later**: no `--enable-gpl`, `--enable-version3` or `--enable-nonfree`. `build-gstreamer.sh` checks `CONFIG_GPL`, `CONFIG_VERSION3` and `CONFIG_NONFREE` are 0 in `config.h` and stops otherwise.
- **Decoders and parsers only**: `--disable-everything --disable-programs --disable-network --disable-autodetect --disable-avdevice --disable-postproc`, shared libraries, then the decoders and parsers in the script one by one: H.264, MPEG-1/2/4, H.263, MS-MPEG4, WMV1/2/3, VC-1, VP6/8/9, Theora, FLV, Cinepak, MS Video 1, Indeo 2–5, MJPEG; AAC, MP1/2/3, AC-3, WMA (v1, v2, Pro, Voice, Lossless), Vorbis, Opus, FLAC, ALAC, MS/IMA ADPCM, A-law and µ-law.
- HEVC and E-AC-3 are left out on purpose. No encoder, x264, x265 or openh264 is built.

The FFmpeg tarball is attached to every release as `ffmpeg-6.1.6.tar.xz`, next to CodeWeavers' tarball (the LGPL source offer for it).

### Plugins

`gstreamer-plugins.txt` lists module, meson option and plugin file. `build-gstreamer.sh` enables exactly these, and fails if one was not built.

| Group | Plugins |
| --- | --- |
| Created by name in `dlls/winegstreamer` | `coreelements` (capsfilter, queue), `app` (appsrc, appsink), `playback` (decodebin), `typefindfunctions`, `videoconvertscale`, `audioconvert`, `audioresample`, `pbtypes`, `deinterlace`, `videofilter` (videoflip) |
| Demuxers and parsers decodebin picks | `isomp4`, `matroska`, `avi`, `wavparse`, `audioparsers`, `id3demux`, `videoparsersbad`, `mpegpsdemux`, `mpegtsdemux`, `asf` |
| Decoders | `libav` (the `avdec_*` elements, over the FFmpeg above) |

That is 21 plugins. Nothing from the GPL or patent-restricted options (x264, x265, openh264, faad, a52dec, dts, mpeg2dec) is built. orc is disabled, so videoconvert and audioconvert use their C paths.

### At run time

The app needs no change. libgstreamer finds its plugin folder relative to its own file with `dladdr` whenever `GST_PLUGIN_SYSTEM_PATH[_1_0]` is unset. `lib/libgstreamer-1.0.0.dylib` sits next to `lib/gstreamer-1.0`, so winegstreamer uses the bundled plugins with no environment variable. `check-gstreamer.sh` tests exactly this under `env -i`.

Recommended hardening for the launcher (optional, next to its `WINEDLLPATH` export):

```sh
export GST_PLUGIN_SYSTEM_PATH_1_0="$CX_ROOT/lib/gstreamer-1.0"
export GST_PLUGIN_PATH_1_0=""          # ignore a user's GST_PLUGIN_PATH
export GST_REGISTRY_1_0="$HOME/Library/Caches/Cartouche/gstreamer-1.0/registry-<runner id>.x86_64.bin"
```

Without `GST_REGISTRY_1_0`, the plugin cache is GLib's user cache file (`registry.x86_64.bin`), which a Homebrew GStreamer on an Intel Mac also uses. Both keep working, because each process drops plugins outside its own paths, but each rescans whenever the other has run. Without the variables, `~/.local/share/gstreamer-1.0/plugins` is scanned too.

There is no `bin/wine` wrapper script. The manifest's `loader` is `bin/wine`, the app uses it as `WINELOADER`, and the ntdll patcher expects the real binary layout.

## Checks added

| Check | What it stops |
| --- | --- |
| `fetch.sh` | A pinned download that changed. |
| `check-deps.sh` | Load commands and rpaths that point outside macOS and the package. |
| `check_dlopen.py` | Libraries named in the binaries' strings that are neither bundled nor in macOS. `dlopen-allow.txt` lists the exceptions with a reason. |
| `check-gstreamer.sh` | `winegstreamer.so` or a listed plugin missing. It runs the bundled `gst-inspect-1.0` under `env -i` with only a scratch registry and requires: no blacklisted plugin, every plugin loaded from inside the package, every plugin licensed LGPL (`mpegpsdemux` reports `unknown` because it is MPL-1.1/LGPL dual-licensed; it is the one exception), and the elements Wine creates plus the `avdec_*` decoders, demuxers and parsers games need. Runs in `build.sh` and `verify.sh`. Since 26.3.0-3. |
| `check-sdl.sh` | SDL3 missing at run time. It compiles `check-sdl.c` for x86_64, loads the bundled `libSDL2-2.0.0.dylib` and calls `SDL_Init` for game controllers, which makes sdl2-compat load SDL3. |
| `check-licenses.sh` | A bundled dylib, GStreamer plugin or tool, Mono or Gecko without its license. |
| `verify.sh` | An archive that does not match its checksum, is missing files, or whose `wine --version` fails. |
| `boot-check.sh` | A prefix that does not initialize, addons that are downloaded instead of used, or console programs that do not run. On a failed boot it dumps the Wine processes still running, their stacks and the prefix's `system32`. |
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
- `share/licenses/`: the licenses of the bundled libraries. GStreamer's and FFmpeg's come from the trees they were built from (`share/licenses/gstreamer`, `share/licenses/ffmpeg`); `collect-licenses.sh --local` maps the files built from them in `dylibs.txt`.
- `SOURCE.md` names GStreamer and FFmpeg with their source, and has a "GStreamer at run time" section. `BUILDINFO.txt` gains `gstreamer=` and `ffmpeg=`.

The archive has a single top folder, files in sorted order, owner `root:wheel`, and is compressed with `xz -9e`. The release gets a `.sha256` file and a `manifest-entry.json` for the app.

## Naming

The display name is **Cartouche Wine**. The id, tag and file names stay `wine-crossover-<version>-<revision>` (commit f9d04ad), because installed users and the app's manifest refer to them. The name does not use "CrossOver" as a product name.

## Changelog

### 26.3.0-3 (not released)

Branch `wine-crossover-26.3.0-3`. Not published, and not offered by the app.

**GStreamer for media playback.** Builds 26.3.0-1 and -2 were configured `--without-gstreamer`, so `winegstreamer` was missing and games could not play their videos through Media Foundation, DirectShow or the WM ASF reader (H.264/AAC MP4, WMV/WMA, MPEG). 26.3.0-3 builds Wine `--with-gstreamer` on a bundled, LGPL-only GStreamer. Details are in [GStreamer](#gstreamer-from-2630-3). (c23affa, dc0a873)

- **GStreamer 1.24.4** from `sources/gstreamer` in CodeWeavers' tarball, so its source offer is the tarball every release already carries. Core, base, good, bad, ugly and gst-libav, each built alone with meson, all optional features off, `-Dgpl=disabled`, no downloads.
- **FFmpeg 6.1.6**, LGPL 2.1+, decoders and parsers only, shared, for gst-libav. Pinned by URL and SHA-256, signature checked. Its tarball is attached to the release.
- **21 plugins**, listed in `gstreamer-plugins.txt`: what winegstreamer creates by name, the demuxers and parsers decodebin needs, and gst-libav.
- **GLib** from Homebrew (`BREW_GST_DEPS=glib`), bundled with gettext's `libintl` and `pcre2`, licensed and source-offered like the other Homebrew libraries.
- New scripts `build-gstreamer.sh` and `check-gstreamer.sh`. `bundle-deps.sh` gains `--search` and `--place`, `collect-licenses.sh` gains `--local`, `check-licenses.sh` covers plugins and tools, `verify.sh` runs `check-gstreamer.sh` on the unpacked archive.
- `--without-ffmpeg`: Wine's own FFmpeg backend is not built.
- **Boot check.** On a failed first boot it dumps the processes, their stacks and `system32`. With `BOOT_DIAG=1` it also boots the build with the macOS display driver off: when the published 26.3.0-1 hangs too and that boot works, the addons, registry and console checks run in that prefix (`result=pass mode=no-display-driver`). Diagnostic boots get 600 s, more than Wine's own 300 s wait for wineboot.
- `pins.env`: `BUILD_REVISION=3`, `GST_VERSION`, `FFMPEG_*`, `BREW_GST_DEPS`, and `meson ninja nasm` in `BREW_BUILD_DEPS`.

Checked on Linux x86_64 before CI (not on a Mac): `build-gstreamer.sh` built all 21 plugins with meson 1.12.1 and GLib 2.80; `check-gstreamer.sh` passed on a package-like tree with no `GST_*` variable set; `filesrc ! decodebin ! videoconvert ! fakesink` reached EOS on an H.264+AAC MP4, a WMV2+WMA2 ASF and an MPEG-2 PS file. The plugins plus the GStreamer and FFmpeg libraries were about 18 MB uncompressed there.

<!-- CI-RESULTS -->

Open questions:

- **Patents.** H.264, AAC, WMV/VC-1 and WMA decoders are in, the same exposure as every free Wine build for macOS. HEVC and E-AC-3 are left out on purpose. MPEG-2, MP3 and AC-3 patents have expired. openh264, x264 and x265 are not built. This has had no legal review and is not legal advice.
- **Plugin coverage.** Not built, so games that need them fail: Ogg/Vorbis/Theora as containers (`avdec_vorbis` and `avdec_theora` exist, but there is no Ogg demuxer), `mpg123` (MP3 goes through `avdec_mp3`), AV1, HEVC, and hardware decoding (no VideoToolbox, `--disable-autodetect`). Bink and Smacker games ship their own DLLs. Adding a plugin is one line in `gstreamer-plugins.txt`, plus its library if it has one.
- **orc is disabled.** Building with Homebrew `orc` (BSD-2) could speed up large-video conversion under Rosetta 2. Its JIT under Rosetta is untested.
- **Registry location.** Which folder GLib's `g_get_user_cache_dir()` returns on macOS for this GLib is unverified. A launcher that sets `GST_REGISTRY_1_0` avoids the question.
- **Homebrew Intel is Tier 3.** If x86_64 glib bottles stop, `brew install glib` builds from source. The alternative is building `sources/glib` from the CodeWeavers tarball, which needs proxy-libintl and pcre2 without wraps.
- **`gst-inspect-1.0` ships** in `libexec/gstreamer-1.0`, about 100 KB, for the checks and support. It is not on users' `PATH`.
- **No automated Media Foundation probe in CI.** A cutscene through `MFCreateSourceReaderFromURL` + `ReadSample` and DirectShow, with `WINEDEBUG=+mfplat,+quartz` and no `winegstreamer: failed to create`, is checked on a Mac by hand.

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

- The license of the build scripts in this repository.
