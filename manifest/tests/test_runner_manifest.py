"""Tests for manifest/runner_manifest.py: the rules, add-entry, bump and signing."""
import base64
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "manifest" / "runner_manifest.py"
sys.path.insert(0, str(SCRIPT.parent))
import runner_manifest as rm  # noqa: E402

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
except ImportError:  # the signing tests need it; CI installs it
    Ed25519PrivateKey = None

# The app's SUPublicEDKey (app/Info.plist in the app repository)
APP_PUBLIC_KEY = "GQF06ayCCpIxh8XlQPQYWTwbYO2SckfWqr9rYCuJrqI="


def entry(build_id="wine-crossover-26.3.0-3", **changes):
    e = {
        "id": build_id,
        "kind": "wineBuild",
        "origin": "cartouche",
        "name": "Cartouche Wine",
        "version": "26.3.0",
        "displayVersion": "26.3",
        "url": f"https://github.com/BRYANN2K/cartouche-wine/releases/download/{build_id}/{build_id}-x86_64.tar.xz",
        "size": 1234,
        "sha256": "a" * 64,
        "root": build_id,
        "loader": "bin/wine",
        "flavors": ["rosetta"],
    }
    e.update(changes)
    return e


def manifest(*builds, revision=3):
    return {"format": 1, "revision": revision, "builds": list(builds)}


def run(*args, env=None):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, env=env)


class Rules(unittest.TestCase):

    def test_the_canonical_manifest_is_valid(self):
        doc = rm.load(ROOT / "manifest" / "runners.json")
        self.assertEqual(rm.problems(doc), [])
        ids = [b["id"] for b in doc["builds"]]
        for kept in ("wine-crossover-26.3.0-1", "wine-crossover-26.3.0-2", "wine-stable-11.0_1", "wine-devel-11.18"):
            self.assertIn(kept, ids)

    def test_the_canonical_manifest_is_in_the_signed_layout(self):
        path = ROOT / "manifest" / "runners.json"
        self.assertEqual(path.read_text(encoding="utf-8"), rm.dumps(rm.load(path)))

    def test_a_valid_manifest_has_no_problems(self):
        self.assertEqual(rm.problems(manifest(entry())), [])

    def test_bad_builds_are_reported(self):
        cases = {
            "url": dict(url="http://github.com/x/y.tar.xz"),
            "host": dict(url="https://example.com/x/y.tar.xz"),
            "size": dict(size=0),
            "sha256": dict(sha256="TODO-FILL-AFTER-RELEASE"),
            "root": dict(root="../outside"),
            "loader": dict(loader="/bin/wine"),
            "flavors": dict(flavors=["arm64"]),
            "kind": dict(kind="gptk"),
            "id": dict(id=".hidden"),
            "origin": dict(origin="crossover"),
        }
        for label, change in cases.items():
            with self.subTest(label):
                self.assertNotEqual(rm.problems(manifest(entry(**change))), [])

    def test_a_build_listed_twice_is_reported(self):
        self.assertIn("build wine-crossover-26.3.0-3 is listed twice", rm.problems(manifest(entry(), entry())))

    def test_the_format_must_be_1(self):
        self.assertTrue(rm.problems({"format": 2, "revision": 1, "builds": []}))

    def test_the_revision_must_grow_over_the_published_copy(self):
        previous = manifest(entry(), revision=4)
        self.assertTrue(rm.problems(manifest(entry(), revision=4), previous))
        self.assertEqual(rm.problems(manifest(entry(), revision=5), previous), [])

    def test_a_published_pin_cannot_change(self):
        previous = manifest(entry(), revision=4)
        found = rm.problems(manifest(entry(sha256="b" * 64), revision=5), previous)
        self.assertIn("build wine-crossover-26.3.0-3 changes its published pin", found)

    def test_a_published_build_may_be_dropped(self):
        previous = manifest(entry(), entry("wine-crossover-26.3.0-4"), revision=4)
        self.assertEqual(rm.problems(manifest(entry(), revision=5), previous), [])


class AddEntryAndBump(unittest.TestCase):

    def test_a_new_build_goes_first_among_its_origin_and_keeps_the_older_ones(self):
        winehq = entry("wine-devel-11.18", origin="winehq", name="Wine",
                       url="https://github.com/Gcenx/macOS_Wine_builds/releases/download/11.18/w.tar.xz")
        doc = manifest(winehq, entry("wine-crossover-26.3.0-2"))
        self.assertTrue(rm.add_entry(doc, entry(), "wine-crossover-26.3.0-3"))
        self.assertEqual([b["id"] for b in doc["builds"]],
                         ["wine-devel-11.18", "wine-crossover-26.3.0-3", "wine-crossover-26.3.0-2"])

    def test_adding_the_same_entry_twice_changes_nothing(self):
        doc = manifest(entry())
        self.assertFalse(rm.add_entry(doc, entry()))
        self.assertEqual(doc, manifest(entry()))

    def test_an_id_with_another_pin_is_refused(self):
        with self.assertRaises(ValueError):
            rm.add_entry(manifest(entry()), entry(size=99))

    def test_an_invalid_entry_is_refused(self):
        with self.assertRaises(ValueError):
            rm.add_entry(manifest(), entry(url="https://example.com/x.tar.xz"))

    def test_the_entry_must_belong_to_the_requested_release(self):
        with self.assertRaises(ValueError):
            rm.add_entry(manifest(), entry(), "wine-crossover-26.3.0-4")
        other = entry(url="https://github.com/BRYANN2K/cartouche-wine/releases/download/other/x.tar.xz")
        with self.assertRaises(ValueError):
            rm.add_entry(manifest(), other, "wine-crossover-26.3.0-3")

    def test_bump_goes_above_the_file_and_the_published_copy(self):
        doc = manifest(revision=3)
        self.assertEqual(rm.bump(doc), 4)
        self.assertEqual(rm.bump(doc, manifest(revision=9)), 10)
        self.assertEqual(rm.bump(doc, manifest(revision=2)), 11)

    def test_the_commands_update_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / "runners.json").write_text(rm.dumps(manifest(entry("wine-crossover-26.3.0-2"))))
            (tmp / "entry.json").write_text(json.dumps(entry()))
            (tmp / "published.json").write_text(json.dumps(manifest(entry("wine-crossover-26.3.0-2"), revision=7)))
            r = run("add-entry", tmp / "runners.json", "--from", tmp / "entry.json", "--build-id", "wine-crossover-26.3.0-3")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run("check", tmp / "runners.json", "--published", tmp / "published.json")
            self.assertEqual(r.returncode, 1)
            self.assertIn("is not above the published 7", r.stderr)
            r = run("bump", tmp / "runners.json", "--published", tmp / "published.json")
            self.assertEqual(r.returncode, 0, r.stderr)
            r = run("check", tmp / "runners.json", "--published", tmp / "published.json")
            self.assertEqual(r.returncode, 0, r.stderr)
            doc = rm.load(tmp / "runners.json")
            self.assertEqual(doc["revision"], 8)
            self.assertEqual([b["id"] for b in doc["builds"]], ["wine-crossover-26.3.0-3", "wine-crossover-26.3.0-2"])

    def test_add_entry_refuses_a_changed_pin_and_leaves_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            before = rm.dumps(manifest(entry()))
            (tmp / "runners.json").write_text(before)
            (tmp / "entry.json").write_text(json.dumps(entry(size=5)))
            r = run("add-entry", tmp / "runners.json", "--from", tmp / "entry.json")
            self.assertEqual(r.returncode, 1)
            self.assertEqual((tmp / "runners.json").read_text(), before)


@unittest.skipIf(Ed25519PrivateKey is None, "needs the cryptography package")
class Signing(unittest.TestCase):

    def setUp(self):
        self.seed = bytes(range(32))
        key = Ed25519PrivateKey.from_private_bytes(self.seed)
        self.public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.data = rm.dumps(manifest(entry())).encode()
        self.expected = key.sign(self.data)

    def expanded(self):
        h = bytearray(hashlib.sha512(self.seed).digest())
        h[0] &= 248
        h[31] &= 127
        h[31] |= 64
        return bytes(h)

    def test_every_sparkle_key_layout_gives_the_same_signature(self):
        layouts = {
            "seed": self.seed,
            "seed+public": self.seed + self.public,
            "legacy expanded+public": self.expanded() + self.public,
        }
        for label, secret in layouts.items():
            with self.subTest(label):
                signature, public = rm.sign(self.data, base64.b64encode(secret).decode())
                self.assertEqual(public, self.public)
                self.assertEqual(signature, self.expected)

    def test_a_key_whose_public_half_does_not_match_is_refused(self):
        for secret in (self.seed + bytes(32), self.expanded() + bytes(32)):
            with self.assertRaises(ValueError):
                rm.sign(self.data, base64.b64encode(secret).decode())

    def test_a_key_of_another_length_or_not_base64_is_refused(self):
        for text in (base64.b64encode(bytes(48)).decode(), "not base64!"):
            with self.assertRaises(ValueError):
                rm.sign(self.data, text)

    def test_sign_and_verify_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / "runners.json").write_bytes(self.data)
            public = base64.b64encode(self.public).decode()
            env = dict(os.environ, SPARKLE_PRIVATE_KEY=base64.b64encode(self.seed).decode() + "\n")
            r = run("sign", tmp / "runners.json", "--out", tmp / "runners.json.sig", "--public-key", public, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn(base64.b64encode(self.seed).decode(), r.stdout + r.stderr)
            self.assertEqual(base64.b64decode((tmp / "runners.json.sig").read_text().strip()), self.expected)
            r = run("verify", tmp / "runners.json", tmp / "runners.json.sig", "--public-key", public)
            self.assertEqual(r.returncode, 0, r.stderr)
            # Any other byte, or another key, fails
            (tmp / "runners.json").write_bytes(self.data + b" ")
            self.assertEqual(run("verify", tmp / "runners.json", tmp / "runners.json.sig", "--public-key", public).returncode, 1)
            (tmp / "runners.json").write_bytes(self.data)
            self.assertEqual(run("verify", tmp / "runners.json", tmp / "runners.json.sig",
                                 "--public-key", APP_PUBLIC_KEY).returncode, 1)

    def test_sign_refuses_a_key_other_than_the_apps(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / "runners.json").write_bytes(self.data)
            env = dict(os.environ, SPARKLE_PRIVATE_KEY=base64.b64encode(self.seed).decode())
            r = run("sign", tmp / "runners.json", "--out", tmp / "sig", "--public-key", APP_PUBLIC_KEY, env=env)
            self.assertEqual(r.returncode, 1)
            self.assertIn("does not match", r.stderr)
            self.assertFalse((tmp / "sig").exists())

    def test_sign_without_a_key_fails(self):
        env = {k: v for k, v in os.environ.items() if k != "SPARKLE_PRIVATE_KEY"}
        r = run("sign", ROOT / "manifest" / "runners.json", "--out", "/nonexistent/sig", env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("SPARKLE_PRIVATE_KEY is not set", r.stderr)

    def test_sign_update_text_is_read_like_the_app_reads_it(self):
        signature = base64.b64encode(self.expected).decode()
        self.assertEqual(rm.read_signature(f'sparkle:edSignature="{signature}" length="12"'), self.expected)
        self.assertEqual(rm.read_signature(signature + "\n"), self.expected)


if __name__ == "__main__":
    unittest.main()
