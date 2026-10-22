# Contributing and reporting issues

This file is for people who want to report a problem with Cartouche Wine or change the build.

This is not CrossOver and CodeWeavers does not support it. Report problems here, not to CodeWeavers or WineHQ. Many bugs are Wine bugs. We can still tell you whether the packaging caused them.

## Report an issue

Open an issue on this repository. Please say:

- the release (for example `wine-crossover-26.3.0-2`) and your macOS version;
- whether you use Cartouche or run `bin/wine` by hand;
- what you did and what you expected;
- the logs below.

### Collect logs

Run the program from a terminal with a fresh log file:

```sh
export WINEPREFIX="$HOME/.wine-cartouche"
WINEDEBUG=err+all wine-crossover-26.3.0-2/bin/wine your.exe > wine.log 2>&1
```

Useful `WINEDEBUG` values:

| Value | Shows |
| --- | --- |
| `err+all` | Errors from every part. Start here. |
| `+loaddll` | Which DLLs load, and failures such as `could not load kernel32.dll`. |
| `+seh` | Exceptions, for crashes. |
| `+mfplat,+mscoree` | Media Foundation and .NET startup. |
| `-all` | Nothing. The default in the checks. |

Debug logs get large. Attach them as files and say which program and step they cover. Remove private paths and names if you want.

### Prefix will not start

The first start of a new prefix can take many minutes under Rosetta 2. Wait before you report. If it still does not finish, run the boot check from a checkout of this repository and attach the output:

```sh
tar -xJf wine-crossover-26.3.0-2-x86_64.tar.xz
BOOT_DIAG=1 sh /path/to/cartouche-wine/packaging/wine-crossover/boot-check.sh wine-crossover-26.3.0-2 ./boot-out 180
```

It writes `boot.txt`, `wineboot.log` and `addons.log` into `boot-out/`. `boot.txt` has a `result=` line (see [docs/RELEASING.md](docs/RELEASING.md#the-boot-check)). On a failure it also prints the first error lines and, with `BOOT_DIAG=1`, boots the published 26.3.0-1 for comparison.

## Change the build

- Read [docs/BUILDING.md](docs/BUILDING.md) and [docs/CHANGES.md](docs/CHANGES.md).
- Keep every version and hash in `packaging/wine-crossover/pins.env`.
- A new check or a new bundled library needs a reason in the commit message and in [docs/CHANGES.md](docs/CHANGES.md).
- Run `python3 -m unittest discover -s packaging/tests -p 'test_wine_crossover.py'` and `sh packaging/wine-crossover/build.sh --dry-run /tmp/wine-dry`.
- Do not add Apple Game Porting Toolkit files. `redist-scan.sh` rejects them.
- Do not add a Wine source patch without an issue first. Today the build has none, and that is a feature.

Security problems: see [SECURITY.md](SECURITY.md).
