#!/usr/bin/env python3
"""Fails when a Mach-O file in the package names a dylib it may dlopen that is
neither in the package nor part of macOS.

otool and check-deps.sh only see load commands. Wine's Unix side, and libraries
like sdl2-compat, open others by name at run time (SDL3 was missed this way), so
this reads every dylib name in the binaries' strings instead.

    check_dlopen.py <package root> [--allow FILE] [--system-dir DIR]...

A bare name passes when a file of that name is anywhere in the package, or in a
system folder (/usr/lib, or the dyld shared cache on macOS). An absolute path
passes only under /usr/lib or /System. Names matching a pattern in the allow
file (dlopen-allow.txt) are optional libraries left out on purpose.
"""
import argparse
import fnmatch
import os
import pathlib
import re
import sys

MACHO_MAGIC = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",
               b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}
TOKEN = re.compile(rb"[@A-Za-z0-9_+./-]*\.dylib(?![A-Za-z0-9_])")
BARE = re.compile(r"^lib[A-Za-z0-9_+.-]+\.dylib$")
SYSTEM_PREFIXES = ("/usr/lib/", "/System/")


def is_macho(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) in MACHO_MAGIC
    except OSError:
        return False


def dylib_names(path):
    """The dylib paths and names in a binary's bytes, once each."""
    data = pathlib.Path(path).read_bytes()
    names = set()
    for m in TOKEN.finditer(data):
        token = m.group().decode("ascii")
        if token.startswith("/") or token.startswith("@"):
            names.add(token)
        else:
            leaf = token.rsplit("/", 1)[-1]
            # Skips format strings and fragments such as "%s.dylib"
            if BARE.match(leaf):
                names.add(leaf)
    return names


def shared_cache_has(path):
    # System dylibs live only in the dyld shared cache since macOS 11
    try:
        from _ctypes import _dyld_shared_cache_contains_path
        if _dyld_shared_cache_contains_path(path):
            return True
    except (ImportError, OSError):
        pass
    try:
        import ctypes
        preflight = ctypes.CDLL("/usr/lib/libSystem.B.dylib").dlopen_preflight
        preflight.argtypes, preflight.restype = [ctypes.c_char_p], ctypes.c_bool
        return bool(preflight(path.encode()))
    except (OSError, AttributeError):
        return False


def load_allow(path):
    patterns = []
    for line in pathlib.Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            patterns.append(line)
    return patterns


def check(root, allow, system_dirs, use_shared_cache):
    root = pathlib.Path(root)
    bundled = {p.name for p in root.rglob("*")}

    def is_system(leaf):
        return any(os.path.exists(os.path.join(d, leaf)) for d in system_dirs) or (
            use_shared_cache and shared_cache_has("/usr/lib/" + leaf))

    bad, used = [], set()
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.is_symlink() or not is_macho(f):
            continue
        for name in sorted(dylib_names(f)):
            leaf = name.rsplit("/", 1)[-1]
            if name.startswith("/"):
                if name.startswith(SYSTEM_PREFIXES):
                    continue
            elif leaf in bundled or is_system(leaf):
                continue
            hit = next((p for p in allow if fnmatch.fnmatchcase(leaf, p) or fnmatch.fnmatchcase(name, p)), None)
            if hit:
                used.add(hit)
                continue
            bad.append(f"{f.relative_to(root)} names {name}")
    return bad, [p for p in allow if p not in used]


def main(argv=None):
    here = pathlib.Path(__file__).resolve().parent
    p = argparse.ArgumentParser()
    p.add_argument("root")
    p.add_argument("--allow", default=str(here / "dlopen-allow.txt"))
    p.add_argument("--system-dir", action="append", help="instead of /usr/lib and the dyld shared cache")
    a = p.parse_args(argv)
    system_dirs = a.system_dir or ["/usr/lib"]
    use_cache = a.system_dir is None and sys.platform == "darwin"
    bad, unused = check(a.root, load_allow(a.allow), system_dirs, use_cache)
    if bad:
        print("check-dlopen: these may be dlopened but are neither in the package nor in macOS:", file=sys.stderr)
        for line in bad:
            print(f"    {line}", file=sys.stderr)
        print("Bundle them (BREW_LINK_DEPS in pins.env) or allow them with a reason in dlopen-allow.txt.",
              file=sys.stderr)
        return 1
    for pattern in unused:
        print(f"check-dlopen: allowed but not named: {pattern}")
    print(f"==> check-dlopen: every dylib named in {a.root} is in the package or in macOS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
