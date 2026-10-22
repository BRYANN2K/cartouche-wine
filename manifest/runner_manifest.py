#!/usr/bin/env python3
"""Keeps manifest/runners.json, the list of Wine builds the Cartouche app offers.

    runner_manifest.py check <runners.json> [--published <previous runners.json>]
    runner_manifest.py add-entry <runners.json> --from <manifest-entry.json> [--build-id <id>]
    runner_manifest.py bump <runners.json> [--published <previous runners.json>]
    runner_manifest.py sign <runners.json> --out <runners.json.sig> [--public-key <base64>]
    runner_manifest.py verify <runners.json> <runners.json.sig> --public-key <base64>

The app applies the same rules (RunnerManifest.swift in the app repository) and
ignores a copy that breaks them, so `check` only stops a bad copy earlier. A
published copy must have a higher revision than the previous one and keep the
pin of every build both list.

`sign` reads the Sparkle EdDSA private key from the SPARKLE_PRIVATE_KEY
environment variable (never from the command line, so it stays out of process
listings and logs) and writes the base64 Ed25519 signature of the exact file
bytes, which the app checks against SUPublicEDKey.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
from urllib.parse import urlparse

FORMAT = 1
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")


def problems(doc, previous=None):
    found = []
    if doc.get("format") != FORMAT:
        found.append(f"format {doc.get('format')} is not {FORMAT}")
    if not isinstance(doc.get("revision"), int) or isinstance(doc.get("revision"), bool):
        found.append("revision is not a number")
    seen = set()
    for b in doc.get("builds", []):
        at = f"build {b.get('id')}"
        if b.get("id") in seen:
            found.append(f"{at} is listed twice")
        seen.add(b.get("id"))
        if not ID.match(str(b.get("id", ""))):
            found.append(f"{at}: bad id")
        if b.get("kind") != "wineBuild":
            found.append(f"{at}: kind {b.get('kind')} is not downloadable")
        if b.get("origin") not in ("cartouche", "winehq"):
            found.append(f"{at}: origin {b.get('origin')}")
        for key in ("name", "version", "displayVersion"):
            if not isinstance(b.get(key), str) or not b[key]:
                found.append(f"{at}: {key} is missing")
        url = urlparse(str(b.get("url", "")))
        if url.scheme != "https" or url.hostname != "github.com":
            found.append(f"{at}: {b.get('url')} is not an https URL on github.com")
        if not isinstance(b.get("size"), int) or b["size"] <= 0:
            found.append(f"{at}: size {b.get('size')}")
        if not SHA256.match(str(b.get("sha256", ""))):
            found.append(f"{at}: {b.get('sha256')} is not a SHA-256")
        for key in ("root", "loader"):
            path = str(b.get(key, ""))
            if not path or path.startswith("/") or ".." in path.split("/"):
                found.append(f"{at}: {key} {path} leaves the runner folder")
        if not b.get("flavors") or any(f not in ("rosetta", "fex") for f in b["flavors"]):
            found.append(f"{at}: flavors {b.get('flavors')}")
    if previous is not None:
        if isinstance(doc.get("revision"), int) and doc["revision"] <= previous.get("revision", 0):
            found.append(f"revision {doc['revision']} is not above the published {previous.get('revision')}")
        before = {b["id"]: b for b in previous.get("builds", [])}
        for b in doc.get("builds", []):
            if b.get("id") in before and before[b["id"]] != b:
                found.append(f"build {b['id']} changes its published pin")
    return found


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dumps(doc):
    # One fixed layout, so the bytes CI signs are the bytes committed
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def save(path, doc):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(doc))


def add_entry(doc, entry, build_id=None):
    """Lists one build, newest of its origin first; returns False if it was already listed."""
    found = problems({"format": FORMAT, "revision": 0, "builds": [entry]})
    if build_id is not None:
        if entry.get("id") != build_id:
            found.append(f"entry id {entry.get('id')} is not {build_id}")
        if f"/releases/download/{build_id}/" not in str(entry.get("url", "")):
            found.append(f"entry url {entry.get('url')} is not on the {build_id} release")
    if found:
        raise ValueError("; ".join(found))
    builds = doc.setdefault("builds", [])
    for b in builds:
        if b.get("id") == entry["id"]:
            if b != entry:
                raise ValueError(f"build {entry['id']} is already listed with another pin")
            return False
    at = next((i for i, b in enumerate(builds) if b.get("origin") == entry.get("origin")), len(builds))
    builds.insert(at, entry)
    return True


def bump(doc, previous=None):
    """Raises the revision above both the file's and the published copy's."""
    published = previous.get("revision", 0) if previous else 0
    doc["revision"] = max(doc.get("revision", 0), published) + 1
    return doc["revision"]


# Ed25519 (RFC 8032) with an expanded secret key, for Sparkle's legacy 96-byte
# key files (64-byte expanded key + public key), which `cryptography` cannot
# load. Signing with the seed of the same key gives the same signature.
_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_GY = 4 * pow(5, _P - 2, _P) % _P


def _recover_x(y, sign):
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * pow(2, (_P - 1) // 4, _P) % _P
    if x & 1 != sign:
        x = _P - x
    return x


_G = (_recover_x(_GY, 0), _GY, 1, _recover_x(_GY, 0) * _GY % _P)


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    A = (y1 - x1) * (y2 - x2) % _P
    B = (y1 + x1) * (y2 + x2) % _P
    C = 2 * t1 * t2 * _D % _P
    Dd = 2 * z1 * z2 % _P
    E, F, G, H = B - A, Dd - C, Dd + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s, point):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = _add(q, point)
        point = _add(point, point)
        s >>= 1
    return q


def _encode(point):
    x, y, z, _ = point
    zi = pow(z, _P - 2, _P)
    x, y = x * zi % _P, y * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _h(*parts):
    return int.from_bytes(hashlib.sha512(b"".join(parts)).digest(), "little")


def sign_expanded(expanded, message):
    a = int.from_bytes(expanded[:32], "little")
    public = _encode(_mul(a, _G))
    r = _h(expanded[32:64], message) % _L
    R = _encode(_mul(r, _G))
    s = (r + _h(R, public, message) * a) % _L
    return R + s.to_bytes(32, "little"), public


def sign(data, secret_b64):
    """Returns (signature, public key) for Sparkle's exported key in any of its layouts."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    try:
        secret = base64.b64decode("".join(secret_b64.split()), validate=True)
    except ValueError:
        raise ValueError("the private key is not base64") from None
    if len(secret) in (32, 64):
        # A 32-byte seed, or a 64-byte seed followed by its public key
        key = Ed25519PrivateKey.from_private_bytes(secret[:32])
        public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        if len(secret) == 64 and secret[32:] != public:
            raise ValueError("the 64-byte private key does not end with its own public key")
        return key.sign(data), public
    if len(secret) == 96:
        # Sparkle's legacy layout: 64-byte expanded key followed by its public key
        signature, public = sign_expanded(secret[:64], data)
        if secret[64:] != public:
            raise ValueError("the 96-byte private key does not end with its own public key")
        return signature, public
    raise ValueError(f"the private key holds {len(secret)} bytes, not 32, 64 or 96")


def verify(data, signature, public):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(public).verify(signature, data)
        return True
    except (InvalidSignature, ValueError):
        return False


def read_signature(text):
    # The app accepts a bare base64 signature, or sign_update's edSignature="..." text
    text = text.strip()
    quoted = re.search(r'edSignature="([^"]+)"', text)
    return base64.b64decode(quoted.group(1) if quoted else text, validate=True)


def fail(*found):
    print("runner-manifest:", *found, sep="\n    ", file=sys.stderr)
    return 1


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check")
    c.add_argument("manifest")
    c.add_argument("--published")
    a_ = sub.add_parser("add-entry")
    a_.add_argument("manifest")
    a_.add_argument("--from", dest="entry", required=True)
    a_.add_argument("--build-id")
    b = sub.add_parser("bump")
    b.add_argument("manifest")
    b.add_argument("--published")
    s = sub.add_parser("sign")
    s.add_argument("manifest")
    s.add_argument("--out", required=True)
    s.add_argument("--public-key", help="base64 key the derived public key must equal (SUPublicEDKey)")
    v = sub.add_parser("verify")
    v.add_argument("manifest")
    v.add_argument("signature")
    v.add_argument("--public-key", required=True)
    a = p.parse_args(argv)

    if a.command == "check":
        doc = load(a.manifest)
        found = problems(doc, load(a.published) if a.published else None)
        if found:
            return fail(*found)
        print(f"==> runner-manifest: revision {doc['revision']}, {len(doc['builds'])} builds, valid")
        return 0

    if a.command == "add-entry":
        doc, entry = load(a.manifest), load(a.entry)
        try:
            added = add_entry(doc, entry, a.build_id)
        except ValueError as e:
            return fail(str(e))
        save(a.manifest, doc)
        print(f"==> runner-manifest: {'added' if added else 'already lists'} {entry.get('id')}")
        return 0

    if a.command == "bump":
        doc = load(a.manifest)
        revision = bump(doc, load(a.published) if a.published else None)
        save(a.manifest, doc)
        print(f"==> runner-manifest: revision {revision}")
        return 0

    with open(a.manifest, "rb") as f:
        data = f.read()

    if a.command == "sign":
        secret = os.environ.get("SPARKLE_PRIVATE_KEY", "")
        if not secret.strip():
            return fail("SPARKLE_PRIVATE_KEY is not set")
        try:
            signature, public = sign(data, secret)
        except ValueError as e:
            return fail(str(e))
        if a.public_key and public != base64.b64decode(a.public_key, validate=True):
            return fail("SPARKLE_PRIVATE_KEY does not match the expected public key")
        if not verify(data, signature, public):
            return fail("the signature does not verify against the key's own public key")
        with open(a.out, "w", newline="\n") as f:
            f.write(base64.b64encode(signature).decode() + "\n")
        print(f"==> runner-manifest: signed with public key {base64.b64encode(public).decode()}")
        return 0

    # verify
    with open(a.signature) as f:
        try:
            signature = read_signature(f.read())
        except ValueError:
            return fail(f"{a.signature} is not a base64 signature")
    if not verify(data, signature, base64.b64decode(a.public_key, validate=True)):
        return fail(f"{a.signature} does not verify against {a.public_key}")
    print("==> runner-manifest: signature verifies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
