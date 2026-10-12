import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from catalog import signing

OPENSSL = shutil.which("openssl")


def make_key(directory: Path, name: str) -> str:
    """A throwaway Ed25519 key: returns the private PEM, writes <name>.pub.pem into directory."""
    private = directory / f"{name}.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)], check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(directory / f"{name}.pub.pem")],
                   check=True, capture_output=True)
    pem = private.read_text(encoding="utf-8")
    private.unlink()
    return pem


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.api = Path(self.tmp.name) / "api" / "v1"
        (self.api / "apps").mkdir(parents=True)
        (self.api / "versions.json").write_text('{"schema":3}\n', encoding="utf-8")
        (self.api / "apps" / "PPSA01234.json").write_text('{"titleid":"PPSA01234"}\n', encoding="utf-8")
        (self.api / "icons").mkdir()
        (self.api / "icons" / "PPSA01234.png").write_bytes(b"png")

    def test_manifest_lists_every_json_file_and_nothing_else(self):
        path = signing.write_manifest(self.api, 3, 41, "abc")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((manifest["schema"], manifest["sequence"], manifest["commit"]), (3, 41, "abc"))
        self.assertEqual(sorted(manifest["files"]), ["apps/PPSA01234.json", "versions.json"])
        # The news is signed by itself: a released store refuses a manifest that names it.
        (self.api / signing.NEWS).write_text('{"schema":3,"news":[]}\n', encoding="utf-8")
        manifest = json.loads(signing.write_manifest(self.api, 3, 41, "abc").read_text(encoding="utf-8"))
        self.assertEqual(sorted(manifest["files"]), ["apps/PPSA01234.json", "versions.json"])
        self.assertEqual(manifest["files"]["versions.json"],
                         hashlib.sha256((self.api / "versions.json").read_bytes()).hexdigest())
        # Writing it again gives the same bytes, and never lists itself.
        before = path.read_bytes()
        self.assertEqual(signing.write_manifest(self.api, 3, 41, "abc").read_bytes(), before)

    def test_published_keys_are_two_distinct_ed25519_keys(self):
        keys = signing.public_keys()
        self.assertEqual(len(keys), 2)
        for identifier, path in keys.items():
            self.assertEqual(len(identifier), 16)
            self.assertEqual(len(signing.raw_public_key(path.read_text(encoding="utf-8"))), 32)
            self.assertNotIn("PRIVATE", path.read_text(encoding="utf-8"))

    @unittest.skipUnless(OPENSSL, "needs the openssl program")
    def test_sign_and_verify(self):
        keys = Path(self.tmp.name) / "keys"
        keys.mkdir()
        private = make_key(keys, "test")
        signing.write_manifest(self.api, 3, 41, "abc")
        identifier = signing.sign(self.api, private, keys)
        signature = self.api / signing.SIGNATURE
        self.assertEqual(signature.stat().st_size, 64)
        self.assertEqual(identifier, next(iter(signing.public_keys(keys))))
        self.assertTrue(signing.verify(self.api / signing.MANIFEST, signature, keys / "test.pub.pem"))
        # One changed byte in the manifest and the signature no longer holds.
        manifest = self.api / signing.MANIFEST
        manifest.write_text(manifest.read_text(encoding="utf-8").replace('"sequence":41', '"sequence":42'), encoding="utf-8")
        self.assertFalse(signing.verify(manifest, signature, keys / "test.pub.pem"))
        # Rebuilding the manifest removes the stale signature.
        signing.write_manifest(self.api, 3, 42, "abc")
        self.assertFalse(signature.exists())
        # With news in the build, the same key signs it too; a rebuild removes that signature as well.
        news = self.api / signing.NEWS
        news.write_text('{"schema":3,"news":[]}\n', encoding="utf-8")
        self.assertFalse((self.api / signing.NEWS_SIGNATURE).exists())
        signing.sign(self.api, private, keys)
        news_signature = self.api / signing.NEWS_SIGNATURE
        self.assertEqual(news_signature.stat().st_size, 64)
        self.assertTrue(signing.verify(news, news_signature, keys / "test.pub.pem"))
        self.assertFalse(signing.verify(self.api / signing.MANIFEST, news_signature, keys / "test.pub.pem"))
        signing.write_manifest(self.api, 3, 43, "abc")
        self.assertFalse(news_signature.exists())

    @unittest.skipUnless(OPENSSL, "needs the openssl program")
    def test_a_key_that_is_not_published_is_refused(self):
        published, other = Path(self.tmp.name) / "published", Path(self.tmp.name) / "other"
        published.mkdir()
        other.mkdir()
        make_key(published, "published")
        stranger = make_key(other, "stranger")
        signing.write_manifest(self.api, 3, 41, "abc")
        with self.assertRaisesRegex(signing.SigningError, "not one of the published public keys"):
            signing.sign(self.api, stranger, published)
        self.assertFalse((self.api / signing.SIGNATURE).exists())

    @unittest.skipUnless(OPENSSL, "needs the openssl program")
    def test_refuses_garbage_keys_and_unnumbered_builds(self):
        keys = Path(self.tmp.name) / "keys"
        keys.mkdir()
        private = make_key(keys, "test")
        signing.write_manifest(self.api, 3, 0, "abc")
        with self.assertRaisesRegex(signing.SigningError, "no sequence number"):
            signing.sign(self.api, private, keys)
        signing.write_manifest(self.api, 3, 41, "abc")
        with self.assertRaisesRegex(signing.SigningError, "could not sign") as caught:
            signing.sign(self.api, "not a key", keys)
        self.assertNotIn("not a key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
