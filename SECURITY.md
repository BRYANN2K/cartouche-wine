# Security

This file is for people who found a security problem in Cartouche Wine's build, packaging or release process.

## Scope

- The scripts and workflows in this repository.
- The release archives and the signed runner manifest (`runners.json` and `runners.json.sig`).

Problems in Wine itself, or in CrossOver, are best reported upstream to [WineHQ](https://www.winehq.org/). Tell us as well if a release is affected, so we can rebuild.

## How the downloads are protected

- Every input of the build is pinned by SHA-256 (`packaging/wine-crossover/pins.env`).
- Each release has a `.sha256` file, and the manifest pins the archive by URL, size and SHA-256.
- The manifest is signed with Ed25519 (the Sparkle EdDSA key). The app checks the signature and refuses an unsigned or wrongly signed copy.
- The signing key is a secret in the `release` environment and is used only by the `runner-manifest` workflow ([docs/RELEASING.md](docs/RELEASING.md)).

## Report

Please do not open a public issue for a vulnerability. Use GitHub's private vulnerability reporting for this repository (Security tab > Report a vulnerability). <!-- TODO verify: private vulnerability reporting is enabled on the repository; otherwise name a contact address -->

Say which release is affected and how to reproduce it. We will answer as soon as we can. Not decided: a response time.
