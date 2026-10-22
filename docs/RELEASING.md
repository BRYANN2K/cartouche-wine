# Releasing Cartouche Wine

This document is for maintainers. It covers how CI builds, checks and publishes a release, and how a tested release reaches the Cartouche app through the signed manifest. For the manifest file format and script, see [manifest/README.md](../manifest/README.md).

## The flow

```text
1. bump pins.env (BUILD_REVISION, or CX_VERSION for new sources), merge to the default branch
2. run workflow "wine-crossover" with publish=true   -> prerelease wine-crossover-<ver>-<rev>
3. test the archive on a real Mac                    -> boot a fresh prefix, controller test
4. run workflow "runner-manifest" (build_id, confirm_tested)
                                                     -> signed manifest on the `manifest` release
5. the app downloads the manifest within a day       -> Settings > Runners shows Update
```

Nothing reaches the app until step 4. A prerelease is never "latest".

## 1. Prepare

- A script, library or toolchain change with the same sources: raise `BUILD_REVISION` in `packaging/wine-crossover/pins.env`.
- New CodeWeavers tarball: change `CX_VERSION`, `CX_SOURCE_URL`, `CX_SOURCE_SHA256`, `CX_SOURCE_SIZE`, and set `BUILD_REVISION=1`.
- Update [CHANGES.md](CHANGES.md).
- A pull request that touches `packaging/wine-crossover/**`, `packaging/tests/test_wine_crossover.py` or the workflow runs the `scripts` job (see below).

CI refuses to publish a tag that already exists. Never reuse a tag.

## 2. Build and publish: workflow `wine-crossover`

File: `.github/workflows/wine-crossover.yml`. It needs no secret and has `contents: read` except in the publish job.

Triggers:

- `pull_request` on the paths above: only the `scripts` job runs.
- `workflow_dispatch` with the boolean input `publish` (default false): the `build` job runs, and `publish` runs if the input is true **and** the ref is the repository's default branch.

### Job `scripts` (macos-15)

- Runs `packaging/tests/test_wine_crossover.py`.
- Runs `build.sh --dry-run`.

### Job `build` (runner `vars.WINE_RUNNER`, default `macos-15-intel`; 300 minutes)

The runner is x86_64 because Wine's Unix side is x86_64 code that Rosetta 2 runs.

1. Select the pinned Xcode (`xcode-select -s`).
2. Cache `work/downloads`, keyed by the hash of `pins.env`.
3. `fetch.sh` for the source tarball, llvm-mingw, Wine Mono, Wine Gecko, their license files, and FFmpeg.
4. `brew install` the formulas in `pins.env` (`BREW_BUILD_DEPS`, `BREW_LINK_DEPS`, `BREW_GST_DEPS`).
5. `build.sh work`. This builds GStreamer and FFmpeg first (`build-gstreamer.sh`), then Wine, and runs `check-deps.sh`, `check_dlopen.py`, `check-sdl.sh`, `check-licenses.sh` and `check-gstreamer.sh` on the install tree.
6. `package.sh`: writes the archive, `.sha256`, `manifest-entry.json` and `tag` into `out/`, and copies the Homebrew source archives to `out/brew-sources/brew-<formula>-<version>.<ext>` and the FFmpeg tarball to `out/`. The entry is also written to the job summary.
7. `verify.sh`: re-runs the five checks on the packaged archive and runs `wine --version`. Output goes to `out/verify.txt`.
8. `redist-scan.sh`: fails if the archive holds Apple Game Porting Toolkit files.
9. Boot check, below.
10. Upload `out/` as the artifact `wine-crossover` (also when a step failed).

### The boot check

`boot-check.sh <runner root> <out folder> [window limit] [init limit]`; CI runs it with `BOOT_DIAG=1` and a 180 s window limit.

It uses a scratch home and prefix, and checks:

1. **Prefix initialization.** `wineboot -i` with Mono and Gecko overridden off (`WINEDLLOVERRIDES=mscoree,mshtml=`, so wineboot never waits on their install) and `WINEDEBUG=err+all,+loaddll`, then `wineserver -w`. Limit: `BOOT_INIT_LIMIT`, default 1200 s. The first boot can take many minutes under Rosetta 2. Wine itself gives up waiting for wineboot after 300 s (`run_wineboot boot event wait timed out`), so no limit here should be below about 330 s.
2. **Addons.** A second `wineboot -u` with the addons on. It fails when the log shows a download (`Got URL`, `mono runtime not found`) or no `mono runtime is at` line. This proves the bundled Mono is used.
3. **Registry files.** `system.reg`, `user.reg` and `userdef.reg` exist and are not empty.
4. **Console programs.** `wine cmd /c ver` and `wine reg query` run, each limited by `BOOT_CMD_LIMIT` (default 300 s).
5. **Window, only with a GUI session.** If `launchctl managername` is `Aqua` (or `BOOT_GUI=1`), it starts `winecfg`, waits for a window with `wait-window.swift`, and saves `winecfg.png`. `BOOT_GUI=0` turns this off. Without a GUI session (headless runner) this part is skipped.

It writes `boot.txt` and its logs into the output folder. The `result=` line is one of:

| Result | Meaning |
| --- | --- |
| `pass mode=headless` or `pass mode=gui` | All checks passed. |
| `init-timeout`, `init-failed`, `addons-timeout`, `addons-failed` | The prefix or the addons did not finish. |
| `addon-download` | wineboot did not use the bundled Mono. |
| `no-registry`, `cmd-failed`, `reg-failed` | A later step failed. |
| `timeout` | No winecfg window in time (GUI only). |
| `pass mode=no-display-driver` | The first boot failed and 26.3.0-1 fails the same way, but this build boots with the macOS display driver off; the addons, registry and console checks then passed in that prefix. Windows are not checked. The check warns. |
| `env-cannot-boot` | The first boot failed, 26.3.0-1 fails the same way on this runner, and the build does not boot with the display driver off either. The bundled Mono and Gecko folders must still be there (`addons-missing` otherwise). The check warns and exits 0. |

A failed first boot always prints the first error lines, the last DLL each thread loaded, and `hung.txt`: the Wine processes still running and the prefix's `system32` and `syswow64`. Where macOS allows it, a 2 s stack sample of each Windows process goes to `hung-sample-<pid>.txt` and its call graph to the log.

With `BOOT_DIAG=1`, a failed first boot also boots, each in a fresh prefix with a `BOOT_DIAG_LIMIT` (default 600 s) limit: the published 26.3.0-1 (checked by SHA-256; `BOOT_REF_ROOT` points at another unpacked build instead), then this build with `winemac.drv` disabled. This tells a runner problem from a build problem, and a display problem from the rest.

**Known limit.** On the `macos-15-intel` image of 2026-10-22, the first `wineboot` hangs for both 26.3.0-1 and the new build. The reference failure points to a runner environment problem. A pass with the display driver disabled still cannot prove GUI behavior in CI. Test every release on a Mac before step 4.

### Job `publish` (ubuntu-latest, `contents: write`)

Runs only if `publish` is true and the ref is the default branch.

1. Downloads the artifact.
2. Fetches the source tarball (hash-checked) to attach it.
3. Stops with an error if the release tag exists.
4. Extracts `SOURCE.md` from the archive and uses it as the release notes.
5. `gh release create <tag> --prerelease --latest=false --title "Cartouche Wine <ver>-<rev>"` with: the archive, its `.sha256`, `manifest-entry.json`, `SOURCE.md`, the source tarball, the FFmpeg tarball and `brew-*` archives.
6. Prints a reminder that the build reaches the app only through step 4.

## 3. Test on a real Mac

Install the archive (as a runner in Cartouche, or by hand as in the [README](../README.md#install-and-use)). Boot a fresh prefix and pass a controller test. Only then continue.

## 4. Promote: workflow `runner-manifest`

File: `.github/workflows/runner-manifest.yml`. This is the only way a build reaches the app.

Inputs: `build_id` (for example `wine-crossover-26.3.0-3`) and `confirm_tested` (tick it only after step 3).

The job `check` always runs (also on pull requests that touch `manifest/**`): script tests and `runner_manifest.py check manifest/runners.json`. Job `publish` runs only on `workflow_dispatch` from the default branch, in the **`release` environment**.

Steps of `publish`:

1. Stops unless `confirm_tested` is true and `build_id` looks like `wine-crossover-<version>-<revision>`.
2. Downloads `manifest-entry.json` from the release and checks that the archive named in it is on the release with the same size.
3. Downloads the published `runners.json` from the `manifest` release if it exists.
4. `add-entry` puts the build first among the Cartouche builds and keeps older ones. `bump` raises `revision` above the file and the published copy. `check` verifies the result against the published copy (the revision must grow, a published build must keep its exact pin).
5. Signs the exact bytes with `SPARKLE_PRIVATE_KEY` and verifies the signature against the app's public key.
6. Commits `manifest/runners.json` to the default branch as `github-actions[bot]`.
7. Creates the `manifest` release on the first run (prerelease, not latest), then uploads `runners.json` and `runners.json.sig` with `--clobber`.
8. Downloads both files from the public URL and checks that they are identical to the committed file and that the signature verifies.

Running it again for a build that is already listed re-signs and republishes with a higher revision.

Published URLs:

```text
https://github.com/BRYANN2K/cartouche-wine/releases/download/manifest/runners.json
https://github.com/BRYANN2K/cartouche-wine/releases/download/manifest/runners.json.sig
```

### The `release` environment and `SPARKLE_PRIVATE_KEY`

- Create the environment `release` in Settings > Environments of this repository.
- Add the secret `SPARKLE_PRIVATE_KEY` to it. It is the same EdDSA key as Cartouche's Sparkle updates: the content of the key file exported by Sparkle's `generate_keys -x`, one base64 line. The script accepts a 32-byte seed, a 64-byte seed plus public key, or Sparkle's legacy 96-byte layout.
- Restrict the environment to the default branch. Requiring a reviewer is a good idea.
- Never commit the key. The workflow passes it through an environment variable and never prints it. It refuses a key whose public half is not the app's `SUPublicEDKey` (`APP_PUBLIC_KEY` in the workflow).
- Allow `github-actions[bot]` to push to the default branch, or the run stops before it publishes.

The `wine-crossover` workflow does not use this environment and needs no secret.

### Roll back

<!-- TODO verify: no rollback procedure is written down. -->
Not decided. Because every promotion raises `revision` and keeps old builds, a rollback is a new promotion.

## Not decided

- A rollback procedure for a bad manifest.
- Whether a prerelease is ever marked as a full release.
