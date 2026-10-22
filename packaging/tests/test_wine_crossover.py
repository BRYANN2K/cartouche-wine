"""Tests for packaging/wine-crossover: the pinned fetch, the package and its checks.

The real build needs an x86_64 Mac and an hour, so it runs only in CI. These run
the same scripts on a fake install tree in a temporary folder.
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "packaging" / "wine-crossover"
sys.path.insert(0, str(SCRIPTS))
import manifest_entry  # noqa: E402


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def run(*args, env=None, check=False):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, env=env, check=check)


def write(path, text, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


@unittest.skipUnless(sys.platform == "darwin", "the scripts use macOS tools")
class WineCrossOverScripts(unittest.TestCase):

    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="wine-crossover-test-"))
        self.addCleanup(shutil.rmtree, self.work)

    # A source tarball with the notices package.sh copies, and pins that name it
    def fake_sources(self):
        src = self.work / "srcroot"
        for name in ("LICENSE", "COPYING.LIB", "AUTHORS"):
            write(src / "sources" / "wine" / name, f"{name} of the fake sources\n")
        tarball = self.work / "crossover-sources-26.3.0.tar.gz"
        run("tar", "-czf", tarball, "-C", src, "sources", check=True)
        pins = (SCRIPTS / "pins.env").read_text().replace(
            "CX_SOURCE_SHA256=ac99c8ca4b3848f3e81784135f023df266b61c2345726ea55a50b3e030dd6872",
            f"CX_SOURCE_SHA256={sha256(tarball)}")
        self.assertIn(sha256(tarball), pins)
        pins_file = self.work / "pins.env"
        pins_file.write_text(pins)
        return tarball, pins_file

    # What make install-lib leaves, with a shell script standing in for wine
    def fake_install(self, version="wine-11.0 (fake)"):
        install = self.work / "install"
        wine = f"#!/bin/sh\n[ \"$1\" = --version ] && echo '{version}'\n"
        write(install / "lib/wine/x86_64-unix/wine", wine, 0o755)
        (install / "bin").mkdir(parents=True)
        os.symlink("../lib/wine/x86_64-unix/wine", install / "bin/wine")
        write(install / "bin/wineserver", "#!/bin/sh\n", 0o755)
        write(install / "share/wine/wine.inf", "[Version]\n")
        for arch in ("x86_64-windows", "i386-windows"):
            write(install / "lib/wine" / arch / "ntdll.dll", f"MZ {arch}\n")
        write(install / "share/wine/mono/wine-mono-10.4.1/support/winemono-support.msi", "msi\n")
        for arch in ("x86", "x86_64"):
            write(install / f"share/wine/gecko/wine-gecko-2.47.4-{arch}/xul.dll", f"MZ {arch}\n")
        stub = self.work / "sdl.c"
        stub.write_text('int SDL_Init(unsigned f) { return 0; }\n'
                        'const char *SDL_GetError(void) { return ""; }\n'
                        'void SDL_Quit(void) {}\n')
        for name in ("libSDL2-2.0.0.dylib", "libSDL3.dylib"):
            run("cc", "-arch", "x86_64", "-dynamiclib", stub, "-install_name", "@rpath/" + name,
                "-o", install / "lib" / name, check=True)
        fake_gstreamer(install)
        fake_licenses(install)
        return install

    def package(self):
        tarball, pins = self.fake_sources()
        install = self.fake_install()
        out = self.work / "out"
        env = dict(os.environ, PINS_FILE=str(pins), REPOSITORY="owner/repo", GITHUB_SHA="abc123")
        r = run("sh", SCRIPTS / "package.sh", install, tarball, out, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return out

    def test_fetch_keeps_a_matching_file(self):
        served = self.work / "served.bin"
        served.write_bytes(b"pinned bytes")
        dest = self.work / "downloads" / "file.bin"
        r = run("sh", SCRIPTS / "fetch.sh", served.as_uri(), sha256(served), dest)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(dest.read_bytes(), b"pinned bytes")
        r = run("sh", SCRIPTS / "fetch.sh", "file:///nonexistent", sha256(served), dest)
        self.assertEqual(r.returncode, 0, "a file that already matches is reused without fetching")

    def test_fetch_refuses_a_wrong_hash_and_keeps_nothing(self):
        served = self.work / "served.bin"
        served.write_bytes(b"substituted bytes")
        dest = self.work / "downloads" / "file.bin"
        r = run("sh", SCRIPTS / "fetch.sh", served.as_uri(), "0" * 64, dest)
        self.assertEqual(r.returncode, 1)
        self.assertIn("the pin is", r.stderr)
        self.assertEqual(list((self.work / "downloads").iterdir()), [])

    def test_package_has_the_notices_source_offer_and_a_matching_entry(self):
        out = self.package()
        asset = out / "wine-crossover-26.3.0-3-x86_64.tar.xz"
        self.assertTrue(asset.is_file())
        self.assertEqual((out / "tag").read_text().strip(), "wine-crossover-26.3.0-3")
        self.assertEqual((out / f"{asset.name}.sha256").read_text().split()[0], sha256(asset))

        listing = run("tar", "-tJf", asset, check=True).stdout.split()
        self.assertTrue(all(p.startswith("wine-crossover-26.3.0-3") for p in listing))
        for f in ("LICENSE", "COPYING.LIB", "AUTHORS", "SOURCE.md", "BUILDINFO.txt", "bin/wine",
                  "lib/wine/x86_64-unix/wine", "lib/wine/i386-windows/ntdll.dll",
                  "lib/gstreamer-1.0/libgstlibav.dylib", "libexec/gstreamer-1.0/gst-inspect-1.0"):
            self.assertIn(f"wine-crossover-26.3.0-3/{f}", listing)
        offer = run("tar", "-xJOf", asset, "wine-crossover-26.3.0-3/SOURCE.md", check=True).stdout
        self.assertIn("https://media.codeweavers.com/pub/crossover/source/crossover-sources-26.3.0.tar.gz", offer)
        self.assertIn("https://github.com/owner/repo/releases/tag/wine-crossover-26.3.0-3", offer)
        self.assertIn("tree/abc123/packaging/wine-crossover", offer)
        self.assertIn("GNU Lesser General Public", offer)
        self.assertIn("Cartouche Wine 26.3.0-3: Wine built from CodeWeavers'", offer)
        self.assertIn("GStreamer 1.24.4", offer)
        self.assertIn("https://ffmpeg.org/releases/ffmpeg-6.1.6.tar.xz", offer)
        self.assertIn("ffmpeg-6.1.6.tar.xz", offer)
        self.assertIn("GST_REGISTRY_1_0", offer)
        info = run("tar", "-xJOf", asset, "wine-crossover-26.3.0-3/BUILDINFO.txt", check=True).stdout
        self.assertIn("gstreamer=1.24.4", info)
        self.assertIn("ffmpeg=6.1.6", info)

        entry = json.loads((out / "manifest-entry.json").read_text())
        self.assertEqual(entry, {
            "id": "wine-crossover-26.3.0-3", "kind": "wineBuild", "origin": "cartouche",
            "name": "Cartouche Wine", "version": "26.3.0", "displayVersion": "26.3",
            "url": "https://github.com/owner/repo/releases/download/wine-crossover-26.3.0-3/"
                   "wine-crossover-26.3.0-3-x86_64.tar.xz",
            "size": asset.stat().st_size, "sha256": sha256(asset),
            "root": "wine-crossover-26.3.0-3", "loader": "bin/wine", "flavors": ["rosetta"],
        })

    def test_package_refuses_sources_that_are_not_the_pinned_tarball(self):
        _, pins = self.fake_sources()
        other = self.work / "other.tar.gz"
        other.write_bytes(b"not the tarball")
        env = dict(os.environ, PINS_FILE=str(pins))
        r = run("sh", SCRIPTS / "package.sh", self.fake_install(), other, self.work / "out", env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not the pinned source tarball", r.stderr)

    def test_verify_runs_wine_from_the_archive(self):
        out = self.package()
        r = run("sh", SCRIPTS / "verify.sh", out / "wine-crossover-26.3.0-3-x86_64.tar.xz")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "wine-11.0 (fake)")

    def test_verify_requires_the_bundled_mono_and_gecko(self):
        tarball, pins = self.fake_sources()
        install = self.fake_install()
        shutil.rmtree(install / "share/wine/gecko/wine-gecko-2.47.4-x86_64")
        out = self.work / "out"
        env = dict(os.environ, PINS_FILE=str(pins))
        r = run("sh", SCRIPTS / "package.sh", install, tarball, out, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("sh", SCRIPTS / "verify.sh", out / "wine-crossover-26.3.0-3-x86_64.tar.xz", env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("share/wine/gecko/wine-gecko-2.47.4-x86_64/xul.dll is missing", r.stderr)

    def test_sdl_check_requires_the_runtime_loaded_sdl3(self):
        install = self.fake_install()
        (install / "lib/libSDL3.dylib").unlink()
        r = run("sh", SCRIPTS / "check-sdl.sh", install)
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing libSDL3.dylib", r.stderr)

    def test_verify_refuses_an_archive_that_does_not_match_its_hash(self):
        out = self.package()
        asset = out / "wine-crossover-26.3.0-3-x86_64.tar.xz"
        (out / f"{asset.name}.sha256").write_text(f"{'0' * 64}  {asset.name}\n")
        r = run("sh", SCRIPTS / "verify.sh", asset)
        self.assertEqual(r.returncode, 1)
        self.assertIn("has SHA-256", r.stderr)

    # Two real dylibs, one loading the other by an absolute path as Homebrew's do
    def dylibs(self):
        lib = self.work / "cellar"
        lib.mkdir()
        (self.work / "foo.c").write_text("int foo(void) { return 1; }\n")
        (self.work / "bar.c").write_text("int foo(void); int bar(void) { return foo(); }\n")
        run("cc", "-dynamiclib", "-o", lib / "libfoo.1.dylib", "-install_name", lib / "libfoo.1.dylib",
            self.work / "foo.c", check=True)
        run("cc", "-dynamiclib", "-o", lib / "libbar.2.dylib", "-install_name", lib / "libbar.2.dylib",
            self.work / "bar.c", lib / "libfoo.1.dylib", "-Wl,-headerpad_max_install_names", check=True)
        return lib

    def test_check_deps_catches_a_library_outside_the_package(self):
        lib = self.dylibs()
        r = run("sh", SCRIPTS / "check-deps.sh", lib)
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"loads {lib}/libfoo.1.dylib", r.stderr)

    def test_bundle_deps_copies_dependencies_and_names_them_through_rpath(self):
        lib = self.dylibs()
        bundled = self.work / "deps"
        r = run("sh", SCRIPTS / "bundle-deps.sh", bundled, lib / "libbar.2.dylib")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(p.name for p in bundled.iterdir()), ["libbar.2.dylib", "libfoo.1.dylib"])
        loads = run("otool", "-L", bundled / "libbar.2.dylib", check=True).stdout
        self.assertIn("@rpath/libbar.2.dylib", loads)
        self.assertIn("@rpath/libfoo.1.dylib", loads)
        self.assertNotIn(str(lib), loads)
        r = run("sh", SCRIPTS / "check-deps.sh", bundled)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_bundle_deps_places_plugins_beside_the_libraries_they_load(self):
        lib = self.dylibs()
        (self.work / "plugin.c").write_text("int bar(void); int plugin(void) { return bar(); }\n")
        plugin = self.work / "build" / "libgstfake.dylib"
        plugin.parent.mkdir()
        # Like a meson-installed plugin: an absolute LC_RPATH into the build machine
        run("cc", "-dynamiclib", "-o", plugin, self.work / "plugin.c", lib / "libbar.2.dylib",
            f"-Wl,-rpath,{lib}", "-Wl,-headerpad_max_install_names", check=True)
        bundled = self.work / "deps"
        r = run("sh", SCRIPTS / "bundle-deps.sh", "--search", lib,
                "--place", bundled / "gstreamer-1.0", "@loader_path/..", plugin, bundled)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(p.name for p in bundled.iterdir()),
                         ["gstreamer-1.0", "libbar.2.dylib", "libfoo.1.dylib"])
        placed = bundled / "gstreamer-1.0/libgstfake.dylib"
        commands = run("otool", "-l", placed, check=True).stdout
        self.assertIn("path @loader_path/.. (", commands)
        self.assertNotIn(str(lib), commands)
        self.assertIn("@rpath/libbar.2.dylib", run("otool", "-L", placed, check=True).stdout)
        r = run("sh", SCRIPTS / "check-deps.sh", bundled)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_dry_run_prints_the_pinned_configure_and_touches_nothing(self):
        work = self.work / "dry"
        r = run("sh", SCRIPTS / "build.sh", "--dry-run", work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(work.exists())
        self.assertIn("crossover-sources-26.3.0.tar.gz", r.stdout)
        configure = next(line for line in r.stdout.splitlines() if "sources/wine/configure" in line)
        for flag in ("--enable-archs=i386,x86_64", "--with-mingw", "--without-x", "--disable-tests",
                     "-Wl,-rpath,@loader_path/../../", "-mmacosx-version-min=15.0"):
            self.assertIn(flag, configure)
        self.assertIn("make install-lib", r.stdout)
        for tarball in ("wine-mono-10.4.1-x86.tar.xz", "wine-gecko-2.47.4-x86.tar.xz",
                        "wine-gecko-2.47.4-x86_64.tar.xz"):
            self.assertIn(tarball, r.stdout)
        self.assertIn("install/share/wine/mono", r.stdout)
        self.assertIn("install/share/wine/gecko", r.stdout)
        self.assertIn("check-deps.sh", r.stdout)


def listed_plugins():
    """The plugin names in gstreamer-plugins.txt."""
    return [line.split()[2] for line in (SCRIPTS / "gstreamer-plugins.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")]


ELEMENTS = ("decodebin videoconvert audioconvert audioresample capsfilter deinterlace videoflip appsrc appsink "
            "queue avdec_h264 avdec_wmv3 avdec_vc1 avdec_wmav2 avdec_aac avdec_mp3 avdec_mpeg2video qtdemux "
            "asfdemux matroskademux avidemux h264parse vc1parse mpegpsdemux").split()


def fake_gstreamer(install, elements=ELEMENTS, blacklisted=0, licenses=None, plugin_dir=None):
    """winegstreamer.so, the listed plugins and a gst-inspect-1.0 that answers
    like the real one: -b, --exists <element>, and <plugin> with its file and
    license. It fails when any GST_ variable but GST_REGISTRY_1_0 is set."""
    write(install / "lib/wine/x86_64-unix/winegstreamer.so", "unix lib\n")
    for name in listed_plugins():
        write(install / f"lib/gstreamer-1.0/libgst{name}.dylib", "plugin\n")
    licenses = dict({"mpegpsdemux": "unknown"}, **(licenses or {}))
    cases = "".join(f"    {name}) echo '  License                  {lic}' ;;\n" for name, lic in licenses.items())
    where = f"'{plugin_dir}'" if plugin_dir else '"$(cd "$(dirname "$0")/../../lib/gstreamer-1.0" && pwd -P)"'
    write(install / "libexec/gstreamer-1.0/gst-inspect-1.0", f"""#!/bin/sh
env | grep '^GST_' | grep -v '^GST_REGISTRY_1_0=' && exit 9
[ -n "$GST_REGISTRY_1_0" ] || exit 9
case "$1" in
-b) echo "Blacklisted files:"; echo; echo "Total count: {blacklisted} blacklisted files"; exit 0 ;;
--exists) case " {' '.join(elements)} " in *" $2 "*) exit 0 ;; *) exit 1 ;; esac ;;
esac
echo "Plugin Details:"
echo "  Name                     $1"
echo "  Filename                 {where}/libgst$1.dylib"
case "$1" in
{cases}    *) echo '  License                  LGPL' ;;
esac
""", 0o755)


def fake_licenses(install):
    """What build.sh leaves in share/licenses for the fake install's SDL dylibs."""
    licenses = install / "share/licenses"
    mapping = "libSDL2-2.0.0.dylib sdl2-compat\nlibSDL3.dylib sdl3\n"
    for f in sorted((install / "lib/gstreamer-1.0").glob("*")) + sorted((install / "libexec/gstreamer-1.0").glob("*")):
        mapping += f"{f.name} gstreamer\n"
    write(licenses / "dylibs.txt", mapping)
    for name in ("sdl2-compat", "sdl3"):
        write(licenses / name / "LICENSE.txt", "zlib\n")
    write(licenses / "gstreamer/COPYING.gst-libav", "LGPL\n")
    write(licenses / "ffmpeg/COPYING.LGPLv2.1", "LGPL\n")
    write(licenses / "wine-mono/COPYING", "MIT\n")
    write(licenses / "wine-gecko/LICENSE", "MPL\n")


def fake_runner(work, boot_secs=0, boot_rc=0, mono="mono runtime is at Z:\\wine\\mono", registry=True,
                cmd="Microsoft Windows 10.0.19045", needs_no_display=False, name="runner", addons=True):
    """A runner whose wine sleeps through the prefix install, writes the registry,
    answers cmd and reg, and never shows a window; wineserver exits at once.
    With needs_no_display, wineboot hangs up like on the macos-15-intel image
    unless winemac.drv is disabled."""
    root = work / name
    hives = "for f in system.reg user.reg userdef.reg; do echo WINE > \"$WINEPREFIX/$f\"; done" if registry else ":"
    hang = ""
    if needs_no_display:
        hang = """case "$WINEDLLOVERRIDES" in *winemac.drv=*) ;; *)
        echo '0024:err:environ:run_wineboot boot event wait timed out' >&2; exit 53 ;; esac
        """
    if addons:
        for d in ("mono/wine-mono-10.4.1", "gecko/wine-gecko-2.47.4-x86", "gecko/wine-gecko-2.47.4-x86_64"):
            (root / "share/wine" / d).mkdir(parents=True, exist_ok=True)
    write(root / "bin/wine", f"""#!/bin/sh
case "$1" in
    --version) echo "wine-11.0 (fake)" ;;
    wineboot) {hang}echo 'trace:mscoree:install_wine_mono {mono}' >&2; sleep {boot_secs}
        mkdir -p "$WINEPREFIX"; {hives}; exit {boot_rc} ;;
    cmd) echo '{cmd}' ;;
    reg) echo '    CurrentBuildNumber    REG_SZ    19045' ;;
    winecfg) sleep 10 ;;
esac
""", 0o755)
    write(root / "bin/wineserver", "#!/bin/sh\nexit 0\n", 0o755)
    return root


class BootCheck(unittest.TestCase):
    """boot-check.sh without a GUI session, as on a headless runner."""

    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="boot-check-test-"))
        self.addCleanup(shutil.rmtree, self.work)
        self.out = self.work / "boot"

    def boot(self, *args, **runner):
        env = dict(os.environ, BOOT_GUI="0", BOOT_CMD_LIMIT="5")
        return run("sh", SCRIPTS / "boot-check.sh", fake_runner(self.work, **runner), self.out, *args, env=env)

    def result(self):
        return (self.out / "boot.txt").read_text()

    def test_headless_passes_on_a_working_prefix_and_console(self):
        r = self.boot(1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cmd and reg ran", r.stdout)
        self.assertIn("result=pass mode=headless", self.result())
        self.assertIn("wine=wine-11.0 (fake)", self.result())
        self.assertFalse((self.out / "winecfg.log").exists(), "no window check without a GUI session")

    def test_fails_when_wineboot_writes_no_registry(self):
        r = self.boot(1, registry=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("did not write system.reg", r.stderr)
        self.assertIn("result=no-registry file=system.reg", self.result())

    def test_fails_when_console_programs_do_not_run(self):
        r = self.boot(1, cmd="")
        self.assertEqual(r.returncode, 1)
        self.assertIn("wine cmd /c ver exited", r.stderr)
        self.assertIn("result=cmd-failed", self.result())

    def test_fails_when_wineboot_would_download_mono(self):
        r = self.boot(1, mono="mono runtime not found")
        self.assertEqual(r.returncode, 1)
        self.assertIn("did not use the bundled Wine Mono", r.stderr)
        self.assertIn("result=addon-download", self.result())

    def test_fails_when_prefix_init_overruns_its_limit(self):
        r = self.boot(1, 1, boot_secs=10)
        self.assertEqual(r.returncode, 1)
        self.assertIn("did not finish within 1 s", r.stderr)
        self.assertIn("result=init-timeout init_limit=1", self.result())

    def test_reports_an_init_failure(self):
        r = self.boot(1, boot_rc=3)
        self.assertEqual(r.returncode, 1)
        self.assertIn("initialization exited 3", r.stderr)
        self.assertIn("result=init-failed rc=3", self.result())

    def test_a_failed_boot_dumps_processes_and_system32(self):
        r = self.boot(1, boot_rc=3)
        self.assertEqual(r.returncode, 1)
        self.assertIn("== processes", r.stderr)
        self.assertIn("== system32:", (self.out / "hung.txt").read_text())
        self.assertTrue((self.out / "hung-system32.txt").exists())

    def diag(self, runner, reference):
        env = dict(os.environ, BOOT_GUI="0", BOOT_CMD_LIMIT="5", BOOT_DIAG="1", BOOT_DIAG_LIMIT="20",
                   BOOT_REF_ROOT=str(fake_runner(self.work, **reference)))
        return run("sh", SCRIPTS / "boot-check.sh", fake_runner(self.work, **runner), self.out, 1, env=env)

    def test_runs_the_checks_without_display_driver_when_the_reference_hangs_too(self):
        r = self.diag(dict(needs_no_display=True), dict(name="ref", needs_no_display=True))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("first boot with no-display-driver: rc=0", r.stderr)
        self.assertIn("::warning::the macOS display driver hangs wineboot", r.stdout)
        self.assertIn("cmd and reg ran", r.stdout)
        self.assertIn("result=pass mode=no-display-driver", self.result())

    def test_still_checks_the_bundled_mono_without_display_driver(self):
        r = self.diag(dict(needs_no_display=True, mono="mono runtime not found"), dict(name="ref", needs_no_display=True))
        self.assertEqual(r.returncode, 1)
        self.assertIn("result=addon-download", self.result())

    def test_env_cannot_boot_when_nothing_boots_on_the_runner(self):
        r = self.diag(dict(boot_rc=53), dict(name="ref", boot_rc=53))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("result=env-cannot-boot rc=53", self.result())

    def test_env_cannot_boot_still_needs_the_bundled_addons(self):
        r = self.diag(dict(boot_rc=53, addons=False), dict(name="ref", boot_rc=53))
        self.assertEqual(r.returncode, 1)
        self.assertIn("result=addons-missing", self.result())

    def test_fails_when_only_this_build_cannot_boot(self):
        r = self.diag(dict(needs_no_display=True), dict(name="ref"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("first boot with reference-26.3.0-1: rc=0", r.stderr)
        self.assertIn("result=init-failed rc=53", self.result())

    @unittest.skipUnless(sys.platform == "darwin", "the window check uses swiftc and CoreGraphics")
    def test_with_a_gui_session_times_out_when_no_window_shows(self):
        env = dict(os.environ, BOOT_GUI="1")
        r = run("sh", SCRIPTS / "boot-check.sh", fake_runner(self.work), self.out, 1, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("prefix initialized", r.stdout)
        self.assertIn("no winecfg window within 1 s", r.stderr)
        self.assertIn("result=timeout limit=1", self.result())
        self.assertTrue((self.out / "windows.txt").exists())


class CheckDlopen(unittest.TestCase):
    """check_dlopen.py on fake Mach-O files: a magic number and some strings."""

    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="check-dlopen-test-"))
        self.addCleanup(shutil.rmtree, self.work)
        self.root = self.work / "pkg"
        self.system = self.work / "usrlib"
        write(self.system / "libz.1.dylib", "")
        self.allow = self.work / "allow.txt"
        self.allow.write_text("# optional\nlibodbc*.dylib  # no driver manager\n")

    def macho(self, rel, *strings):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xcf\xfa\xed\xfe\x07\x00\x00\x01" + b"".join(s.encode() + b"\0" for s in strings))

    def check(self):
        return run(sys.executable, SCRIPTS / "check_dlopen.py", self.root, "--allow", self.allow,
                   "--system-dir", self.system)

    # What the 26.3.0-1 build shipped: sdl2-compat, which dlopens SDL3, without SDL3
    def sdl2_compat_package(self):
        self.macho("lib/wine/x86_64-unix/winebus.so", "libSDL2-2.0.0.dylib", "SDL_Init")
        self.macho("lib/libSDL2-2.0.0.dylib", "@rpath/libSDL2-2.0.0.dylib", "@loader_path/libSDL3.dylib",
                   "libSDL3.dylib", "/usr/lib/libSystem.B.dylib")

    def test_a_dlopened_library_missing_from_the_package_fails(self):
        self.sdl2_compat_package()
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("lib/libSDL2-2.0.0.dylib names libSDL3.dylib", r.stderr)
        self.assertIn("lib/libSDL2-2.0.0.dylib names @loader_path/libSDL3.dylib", r.stderr)

    def test_bundled_system_and_allowed_names_pass(self):
        self.sdl2_compat_package()
        self.macho("lib/libSDL3.dylib", "@rpath/libSDL3.dylib", "libz.1.dylib")
        self.macho("lib/wine/x86_64-unix/odbc32.so", "libodbc.2.dylib")
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("check-dlopen: every dylib named", r.stdout)

    def test_a_build_machine_path_fails_even_if_the_name_is_bundled(self):
        self.macho("lib/libgnutls.30.dylib", "/usr/local/opt/gmp/lib/libgmp.10.dylib")
        self.macho("lib/libgmp.10.dylib", "@rpath/libgmp.10.dylib")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("names /usr/local/opt/gmp/lib/libgmp.10.dylib", r.stderr)

    def test_only_mach_o_files_and_whole_names_count(self):
        write(self.root / "share/wine/notes.txt", "libmissing.1.dylib\n")
        self.macho("lib/wine/x86_64-unix/ntdll.so", "lib%s.dylib", "%s.dylib", ".dylib")
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_allow_list_gives_a_reason_for_each_pattern(self):
        for line in (SCRIPTS / "dlopen-allow.txt").read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                self.assertIn("#", line, f"no reason for {line}")
                self.assertTrue(line.split()[0].endswith(".dylib"), line)


class Licenses(unittest.TestCase):
    """check-licenses.sh and collect-licenses.sh on fake trees and a fake brew."""

    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="licenses-test-"))
        self.addCleanup(shutil.rmtree, self.work)
        self.root = self.work / "pkg"
        for name in ("libSDL2-2.0.0.dylib", "libSDL3.dylib"):
            write(self.root / "lib" / name, "dylib\n")
        write(self.root / "share/wine/mono/wine-mono-10.4.1/support/winemono-support.msi", "msi\n")
        write(self.root / "share/wine/gecko/wine-gecko-2.47.4-x86/xul.dll", "MZ\n")
        fake_licenses(self.root)

    def check(self):
        return run("sh", SCRIPTS / "check-licenses.sh", self.root)

    def test_every_bundled_dylib_and_addon_has_a_license(self):
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_dylib_without_an_entry_fails(self):
        write(self.root / "lib/libnettle.8.dylib", "dylib\n")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("libnettle.8.dylib has no entry in share/licenses/dylibs.txt", r.stderr)

    def test_a_package_without_files_fails(self):
        shutil.rmtree(self.root / "share/licenses/sdl3")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("libSDL3.dylib comes from sdl3, which has no files in share/licenses/sdl3", r.stderr)

    def test_gstreamer_plugins_and_tools_need_an_entry_too(self):
        write(self.root / "lib/gstreamer-1.0/libgstlibav.dylib", "plugin\n")
        write(self.root / "libexec/gstreamer-1.0/gst-inspect-1.0", "tool\n", 0o755)
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("libgstlibav.dylib has no entry", r.stderr)
        self.assertIn("gst-inspect-1.0 has no entry", r.stderr)
        fake_licenses(self.root)
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_bundled_gecko_needs_its_license(self):
        shutil.rmtree(self.root / "share/licenses/wine-gecko")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("Wine Gecko has no license", r.stderr)

    # A Cellar with two kegs, a brew that serves their source tarballs, and the
    # origins file bundle-deps.sh would write for them
    def cellar(self, nettle_sources=True):
        cellar = self.work / "usr/local/Cellar"
        write(cellar / "gnutls/3.8.9/lib/libgnutls.30.dylib", "dylib\n")
        write(cellar / "gnutls/3.8.9/COPYING", "GPL\n")
        write(cellar / "gnutls/3.8.9/README.md", "readme\n")
        write(cellar / "nettle/3.10.1/lib/libnettle.8.dylib", "dylib\n")
        cache = self.work / "cache"
        for name, files in (("gnutls", {"LICENSE": "LGPL\n", "doc/COPYING.LESSER": "LGPL\n",
                                        "lib/deep/COPYING": "no\n", "NEWS": "news\n"}),
                            ("nettle", {"COPYING.LESSERv3": "LGPLv3\n", "COPYINGv2": "GPLv2\n"}
                             if nettle_sources else {"README": "readme\n"})):
            src = self.work / "src" / f"{name}-1.0"
            for rel, text in files.items():
                write(src / rel, text)
            cache.mkdir(exist_ok=True)
            run("tar", "-czf", cache / f"{name}.tar.gz", "-C", src.parent, src.name, check=True)
        bindir = self.work / "bin"
        write(bindir / "brew", f"""#!/bin/sh
case "$1" in
    fetch) exit 0 ;;
    --cache) for a; do f=$a; done; echo "{cache}/$f.tar.gz" ;;
esac
""", 0o755)
        origins = self.work / "origins.txt"
        origins.write_text(f"libgnutls.30.dylib {cellar}/gnutls/3.8.9/lib/libgnutls.30.dylib\n"
                           f"libnettle.8.dylib {cellar}/nettle/3.10.1/lib/libnettle.8.dylib\n"
                           f"libhogweed.6.dylib {cellar}/nettle/3.10.1/lib/libhogweed.6.dylib\n")
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
        return origins, env

    def test_collect_copies_keg_and_source_licenses_and_maps_each_dylib(self):
        origins, env = self.cellar()
        dest = self.work / "licenses"
        r = run("sh", SCRIPTS / "collect-licenses.sh", origins, dest, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((dest / "dylibs.txt").read_text(),
                         "libgnutls.30.dylib gnutls\nlibnettle.8.dylib nettle\nlibhogweed.6.dylib nettle\n")
        files = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
        self.assertEqual(files, ["dylibs.txt", "formulas.txt", "gnutls/COPYING", "gnutls/LICENSE",
                                 "gnutls/doc/COPYING.LESSER", "nettle/COPYING.LESSERv3", "nettle/COPYINGv2"])
        self.assertEqual((dest / "formulas.txt").read_text(), "gnutls 3.8.9\nnettle 3.10.1\n")

    def test_collect_copies_each_formula_source_for_the_source_offer(self):
        origins, env = self.cellar()
        sources = self.work / "sources"
        r = run("sh", SCRIPTS / "collect-licenses.sh", origins, self.work / "licenses", sources, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(p.name for p in sources.iterdir()),
                         ["gnutls-3.8.9.tar.gz", "nettle-3.10.1.tar.gz"])

    def test_collect_fails_for_a_formula_without_license_files(self):
        origins, env = self.cellar(nettle_sources=False)
        r = run("sh", SCRIPTS / "collect-licenses.sh", origins, self.work / "licenses", env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no license file found for nettle", r.stderr)

    def test_collect_maps_files_built_from_a_local_folder(self):
        origins, env = self.cellar()
        gst = self.work / "gst"
        write(gst / "lib/libgstreamer-1.0.0.dylib", "dylib\n")
        write(gst / "lib/gstreamer-1.0/libgstlibav.dylib", "plugin\n")
        ffmpeg = self.work / "ffmpeg"
        write(ffmpeg / "lib/libavcodec.60.31.102.dylib", "dylib\n")
        with origins.open("a") as f:
            f.write(f"libgstreamer-1.0.0.dylib {gst}/lib/libgstreamer-1.0.0.dylib\n"
                    f"libgstlibav.dylib {gst}/lib/gstreamer-1.0/libgstlibav.dylib\n"
                    f"libavcodec.60.dylib {ffmpeg}/lib/libavcodec.60.31.102.dylib\n")
        dest = self.work / "licenses"
        args = ("sh", SCRIPTS / "collect-licenses.sh", "--local", gst, "gstreamer", "--local", ffmpeg, "ffmpeg",
                origins, dest)
        write(dest / "gstreamer/COPYING.gstreamer", "LGPL\n")
        r = run(*args, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("libavcodec.60.dylib comes from ffmpeg, which has no license files", r.stderr)
        write(dest / "ffmpeg/COPYING.LGPLv2.1", "LGPL\n")
        r = run(*args, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        mapping = (dest / "dylibs.txt").read_text().splitlines()
        self.assertIn("libgstreamer-1.0.0.dylib gstreamer", mapping)
        self.assertIn("libgstlibav.dylib gstreamer", mapping)
        self.assertIn("libavcodec.60.dylib ffmpeg", mapping)
        self.assertIn("libgnutls.30.dylib gnutls", mapping)
        self.assertEqual((dest / "formulas.txt").read_text(), "gnutls 3.8.9\nnettle 3.10.1\n",
                         "local packages are not Homebrew formulas")

    def test_collect_refuses_a_dylib_from_outside_homebrew(self):
        origins = self.work / "origins.txt"
        origins.write_text("libfoo.1.dylib /opt/local/lib/libfoo.1.dylib\n")
        r = run("sh", SCRIPTS / "collect-licenses.sh", origins, self.work / "licenses")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a Homebrew keg", r.stderr)


class GStreamer(unittest.TestCase):
    """build-gstreamer.sh's dry run, the plugin list and check-gstreamer.sh."""

    def setUp(self):
        self.work = pathlib.Path(tempfile.mkdtemp(prefix="gstreamer-test-"))
        self.addCleanup(shutil.rmtree, self.work)
        self.root = self.work / "pkg"

    def check(self):
        return run("sh", SCRIPTS / "check-gstreamer.sh", self.root)

    def test_the_plugin_list_has_what_wine_creates_and_nothing_gpl(self):
        lines = [line.split() for line in (SCRIPTS / "gstreamer-plugins.txt").read_text().splitlines()
                 if line.strip() and not line.startswith("#")]
        modules = {"gstreamer", "gst-plugins-base", "gst-plugins-good", "gst-plugins-bad", "gst-plugins-ugly",
                   "gst-libav"}
        for fields in lines:
            self.assertEqual(len(fields), 3, fields)
            self.assertIn(fields[0], modules)
        plugins = {f[2] for f in lines}
        # decodebin, videoconvert, audioconvert, audioresample, capsfilter,
        # deinterlace, videoflip, appsrc/appsink, then the avdec_* decoders
        for needed in ("playback", "videoconvertscale", "audioconvert", "audioresample", "coreelements",
                       "deinterlace", "videofilter", "app", "typefindfunctions", "libav", "isomp4", "asf",
                       "videoparsersbad"):
            self.assertIn(needed, plugins)
        options = {f[1] for f in lines}
        for gpl in ("x264", "x265", "openh264", "faad", "a52dec", "dts", "mpeg2dec", "gpl", "resindvd"):
            self.assertNotIn(gpl, options)

    def test_dry_run_builds_lgpl_ffmpeg_and_only_the_listed_plugins(self):
        work = self.work / "dry"
        r = run("sh", SCRIPTS / "build-gstreamer.sh", "--dry-run", self.work / "gst-src",
                self.work / "ffmpeg.tar.xz", work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(work.exists())
        configure = next(line for line in r.stdout.splitlines() if "./configure" in line)
        for flag in ("--disable-everything", "--enable-shared", "--disable-programs", "--disable-autodetect",
                     "--enable-decoder=h264", "--enable-decoder=wmv3", "--enable-decoder=vc1",
                     "--enable-decoder=wmav2", "--enable-decoder=aac", "--enable-parser=h264"):
            self.assertIn(flag, configure.split())
        for flag in ("--enable-gpl", "--enable-nonfree", "--enable-version3", "--enable-decoder=hevc",
                     "--enable-libx264"):
            self.assertNotIn(flag, configure.split())
        setups = [line for line in r.stdout.splitlines() if line.startswith("+ meson setup")]
        self.assertEqual([s.split()[3].rsplit("/", 1)[1] for s in setups],
                         ["gstreamer", "gst-plugins-base", "gst-plugins-good", "gst-plugins-bad",
                          "gst-plugins-ugly", "gst-libav"])
        for s in setups:
            for flag in ("--auto-features=disabled", "--wrap-mode=nofallback", "-Dtests=disabled"):
                self.assertIn(flag, s.split())
        by_module = {s.split()[3].rsplit("/", 1)[1]: s.split() for s in setups}
        self.assertIn("-Dtools=enabled", by_module["gstreamer"])
        self.assertIn("-Dvideoconvertscale=enabled", by_module["gst-plugins-base"])
        self.assertIn("-Dasfdemux=enabled", by_module["gst-plugins-ugly"])
        self.assertIn("-Dgpl=disabled", by_module["gst-plugins-ugly"])
        self.assertIn("-Dgpl=disabled", by_module["gst-plugins-bad"])
        self.assertIn("-Dvideoparsers=enabled", by_module["gst-plugins-bad"])
        self.assertNotIn("-Dx264=enabled", by_module["gst-plugins-ugly"])

    def test_a_working_bundle_passes(self):
        fake_gstreamer(self.root)
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"{len(listed_plugins())} plugins load from", r.stdout)

    def test_a_missing_plugin_fails(self):
        fake_gstreamer(self.root)
        (self.root / "lib/gstreamer-1.0/libgstasf.dylib").unlink()
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("lib/gstreamer-1.0/libgstasf.dylib is missing", r.stderr)

    def test_winegstreamer_must_be_built(self):
        fake_gstreamer(self.root)
        (self.root / "lib/wine/x86_64-unix/winegstreamer.so").unlink()
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("winegstreamer.so is missing", r.stderr)

    def test_a_plugin_that_does_not_load_fails(self):
        fake_gstreamer(self.root, blacklisted=1)
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("plugins that do not load", r.stderr)

    def test_plugins_found_outside_the_package_fail(self):
        fake_gstreamer(self.root, plugin_dir="/usr/local/lib/gstreamer-1.0")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("not from the package", r.stderr)

    def test_a_gpl_plugin_fails(self):
        fake_gstreamer(self.root, licenses={"libav": "GPL"})
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("plugin libav is licensed 'GPL', not LGPL", r.stderr)

    def test_a_missing_decoder_fails(self):
        fake_gstreamer(self.root, elements=[e for e in ELEMENTS if e != "avdec_wmv3"])
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("elements not found: avdec_wmv3", r.stderr)

    def test_the_check_ignores_the_callers_gstreamer_variables(self):
        fake_gstreamer(self.root)
        env = dict(os.environ, GST_PLUGIN_PATH="/usr/local/lib/gstreamer-1.0", GST_PLUGIN_SYSTEM_PATH_1_0="/x")
        r = run("sh", SCRIPTS / "check-gstreamer.sh", self.root, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_build_dry_run_enables_winegstreamer_on_the_bundled_gstreamer(self):
        work = self.work / "dry"
        r = run("sh", SCRIPTS / "build.sh", "--dry-run", work)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(work.exists())
        out = r.stdout
        configure = next(line for line in out.splitlines() if "sources/wine/configure" in line)
        self.assertIn("--with-gstreamer", configure.split())
        self.assertNotIn("--without-gstreamer", configure)
        self.assertIn("--without-ffmpeg", configure.split())
        self.assertIn(f"GSTREAMER_LIBS=-L{work}/gst-link", configure)
        # build-gstreamer.sh's own dry run, from the pinned FFmpeg and the sources' GStreamer tree
        self.assertIn(f"{work}/downloads/ffmpeg-6.1.6.tar.xz", out)
        self.assertIn(f"meson setup {work}/gst-build/gst-libav {work}/src/sources/gstreamer/subprojects/gst-libav", out)
        self.assertLess(out.index("meson setup"), out.index("sources/wine/configure"))
        bundle = next(line for line in out.splitlines() if "bundle-deps.sh" in line)
        for name in listed_plugins():
            self.assertIn(f"--place {work}/deps/lib/gstreamer-1.0 @loader_path/.. {work}/gst/lib/gstreamer-1.0/"
                          f"libgst{name}.dylib", bundle)
        self.assertIn(f"--place {work}/deps/libexec/gstreamer-1.0 @executable_path/../../lib "
                      f"{work}/gst/bin/gst-inspect-1.0", bundle)
        self.assertIn(f"--search {work}/gst/lib --search {work}/ffmpeg/lib", bundle)
        collect = next(line for line in out.splitlines() if "collect-licenses.sh" in line)
        self.assertIn(f"--local {work}/gst gstreamer --local {work}/ffmpeg ffmpeg", collect)
        self.assertIn("COPYING.gst-libav", out)
        self.assertIn("COPYING.LGPLv2.1", out)
        self.assertIn("check-gstreamer.sh", out)
        self.assertIn(f"cp -R {work}/deps/libexec {work}/install/", out)


class ManifestEntry(unittest.TestCase):

    def test_url_must_be_https_and_name_the_archive(self):
        with tempfile.NamedTemporaryFile(suffix=".tar.xz") as f:
            name = pathlib.Path(f.name).name
            kw = dict(id="x", root="x", name="Cartouche Wine", version="26.3.0", display_version="26.3",
                      origin="cartouche")
            self.assertEqual(manifest_entry.entry(f.name, url=f"https://h/{name}", **kw)["size"], 0)
            with self.assertRaises(SystemExit):
                manifest_entry.entry(f.name, url=f"http://h/{name}", **kw)
            with self.assertRaises(SystemExit):
                manifest_entry.entry(f.name, url="https://h/other.tar.xz", **kw)

    def test_the_display_name_is_cartouche_wine_and_the_id_stays(self):
        with tempfile.NamedTemporaryFile(suffix=".tar.xz") as f:
            name = pathlib.Path(f.name).name
            r = run(sys.executable, SCRIPTS / "manifest_entry.py", f.name, "--id", "wine-crossover-26.3.0-3",
                    "--url", f"https://h/{name}", "--root", "wine-crossover-26.3.0-3",
                    "--version", "26.3.0", "--display-version", "26.3", check=True)
            entry = json.loads(r.stdout)
            self.assertEqual(entry["name"], "Cartouche Wine")
            self.assertEqual(entry["id"], "wine-crossover-26.3.0-3")


class Pins(unittest.TestCase):

    def test_pins_are_full_hashes_and_https(self):
        pins = dict(line.split("=", 1) for line in (SCRIPTS / "pins.env").read_text().splitlines()
                    if line and not line.startswith("#"))
        for key in ("CX_SOURCE_SHA256", "LLVM_MINGW_SHA256", "WINE_MONO_SHA256", "WINE_GECKO_X86_SHA256",
                    "WINE_GECKO_X86_64_SHA256", "WINE_MONO_LICENSE_SHA256", "WINE_GECKO_LICENSE_SHA256",
                    "WINE_GECKO_LICENSE_HTML_SHA256", "FFMPEG_SHA256"):
            self.assertRegex(pins[key], r"^[0-9a-f]{64}$")
        for key in ("CX_SOURCE_URL", "LLVM_MINGW_URL", "WINE_MONO_URL", "WINE_GECKO_X86_URL",
                    "WINE_GECKO_X86_64_URL", "WINE_MONO_LICENSE_URL", "WINE_GECKO_LICENSE_URL",
                    "WINE_GECKO_LICENSE_HTML_URL", "FFMPEG_URL"):
            self.assertTrue(pins[key].startswith("https://"))
        self.assertEqual(pins["FFMPEG_URL"], f"https://ffmpeg.org/releases/ffmpeg-{pins['FFMPEG_VERSION']}.tar.xz")
        self.assertRegex(pins["GST_VERSION"], r"^1\.\d*[02468]\.\d+$", "a stable GStreamer")
        self.assertIn("glib", pins["BREW_GST_DEPS"])
        for tool in ("meson", "ninja", "nasm"):
            self.assertIn(tool, pins["BREW_BUILD_DEPS"].strip('"').split())
        mono, gecko = pins["WINE_MONO_VERSION"], pins["WINE_GECKO_VERSION"]
        self.assertTrue(pins["WINE_MONO_URL"].endswith(f"/{mono}/wine-mono-{mono}-x86.tar.xz"))
        self.assertTrue(pins["WINE_GECKO_X86_URL"].endswith(f"/{gecko}/wine-gecko-{gecko}-x86.tar.xz"))
        self.assertTrue(pins["WINE_GECKO_X86_64_URL"].endswith(f"/{gecko}/wine-gecko-{gecko}-x86_64.tar.xz"))
        self.assertTrue(pins["CX_SOURCE_URL"].endswith(f"crossover-sources-{pins['CX_VERSION']}.tar.gz"))

    def test_workflow_actions_are_pinned_by_commit_with_their_version(self):
        workflow = (ROOT / ".github/workflows/wine-crossover.yml").read_text()
        uses = [line.split("uses:", 1)[1].strip() for line in workflow.splitlines() if "uses:" in line]
        self.assertTrue(uses)
        for use in uses:
            self.assertRegex(use, r"^actions/[a-z-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
