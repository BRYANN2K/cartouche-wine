# Runner manifest

`runners.json` is the list of Wine builds the Cartouche app offers in
**Settings > Runners**. The app ships a copy and, once a day, downloads a newer
one from this public repository:

    https://github.com/BRYANN2K/cartouche-wine/releases/download/manifest/runners.json
    https://github.com/BRYANN2K/cartouche-wine/releases/download/manifest/runners.json.sig

The app must point its runner feed at that URL (the old `compat-data` release of
the app repository is private, so the app cannot read it). The `.sig` is the
base64 Ed25519 signature of the exact bytes of `runners.json`, made with the
Sparkle EdDSA key; the app checks it against `SUPublicEDKey` from its
`Info.plist` and refuses an unsigned or wrongly signed copy.

`manifest/runners.json` in this repository is the canonical copy. CI edits,
signs and publishes it; do not hand-edit a pin that has been published.

## From build to app

1. **Build.** Run the `wine-crossover` workflow with `publish` on the default
   branch. It creates a prerelease `wine-crossover-<version>-<revision>` with
   the archive and its `manifest-entry.json` (id, URL, size, SHA-256). Nothing
   reaches the app yet.
2. **Test on a real Mac.** Install the archive, boot a fresh prefix and pass a
   controller test. GitHub's macOS Intel image can no longer boot a prefix, so
   this step cannot be done by CI.
3. **Promote.** Run the `runner-manifest` workflow on the default branch with
   `build_id` (for example `wine-crossover-26.3.0-3`) and `confirm_tested`
   ticked. It:
   - checks that the release's `manifest-entry.json` pins the archive actually
     on that release;
   - adds the entry to `manifest/runners.json`, first among the Cartouche
     builds, and keeps every older build so installed users can still update
     from them;
   - raises `revision` above both the file and the published copy;
   - checks the result against the published copy (the revision must grow, a
     build already published must keep its exact pin);
   - signs the bytes with `SPARKLE_PRIVATE_KEY` and verifies the signature
     against `SUPublicEDKey`;
   - commits `manifest/runners.json` to the default branch, then uploads
     `runners.json` and `runners.json.sig` to the `manifest` release (created
     on the first run) and checks the downloaded copy verifies.
4. **App.** Within a day the app downloads the new manifest, verifies it and
   shows **Update** for the new build in **Settings > Runners**.

Running the workflow again for a build already listed just re-signs and
republishes with a higher revision.

## Configuration

- **Secret `SPARKLE_PRIVATE_KEY`** in the environment `release` of this public
  repository (Settings > Environments > release). Its value is the content of
  the key file exported by Sparkle's `generate_keys -x` (one base64 line, the
  same value as the app repository's secret). A 32-byte seed, a 64-byte
  seed + public key or Sparkle's legacy 96-byte layout are all accepted. Restrict
  the environment to the default branch and, ideally, require a reviewer. The
  workflow passes the key only through an environment variable and never prints
  it; it refuses a key whose public half is not the app's `SUPublicEDKey`.
- **Default branch writable by `github-actions[bot]`.** The workflow pushes the
  updated `manifest/runners.json`; if the branch is protected, allow GitHub
  Actions to push or the run stops before publishing.

## Script

`runner_manifest.py` holds the same rules as the app's `RunnerManifest.swift`:

    python3 manifest/runner_manifest.py check manifest/runners.json [--published old.json]
    python3 manifest/runner_manifest.py add-entry manifest/runners.json --from manifest-entry.json [--build-id ID]
    python3 manifest/runner_manifest.py bump manifest/runners.json [--published old.json]
    SPARKLE_PRIVATE_KEY=... python3 manifest/runner_manifest.py sign manifest/runners.json --out runners.json.sig --public-key KEY
    python3 manifest/runner_manifest.py verify manifest/runners.json runners.json.sig --public-key KEY

Tests (`sign` and `verify` need the `cryptography` package):

    python3 -m unittest discover -s manifest/tests -p 'test_*.py'
