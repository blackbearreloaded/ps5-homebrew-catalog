import tempfile
import unittest
from pathlib import Path

from catalog.records import load_catalog, load_record
from catalog.report import Report

from helpers import record, reservation, write_record


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.apps = Path(self.tmp.name) / "apps"

    def tearDown(self):
        self.tmp.cleanup()

    def errors(self, data, filename=None):
        report = Report()
        load_record(write_record(self.apps, data, filename), report)
        return [message for level, _, message in report.items if level == "error"]

    def assertRejected(self, data, fragment, filename=None):
        errors = self.errors(data, filename)
        self.assertTrue(any(fragment in e for e in errors), f"{fragment!r} not in {errors}")

    def test_valid_record(self):
        self.assertEqual(self.errors(record()), [])

    def test_license_expression_and_prerelease_version(self):
        self.assertEqual(self.errors(record(
            license="MIT OR Apache-2.0", version="0.2.0-alpha.1",
            artifact_url="https://github.com/example/example-app/releases/download/v0.2.0-alpha.1/PPSA01234.zip")), [])

    def test_artifact_formats(self):
        for extension in (".zip", ".ffpfsc", ".ffpkg"):
            with self.subTest(extension=extension):
                self.assertEqual(self.errors(record(artifact_url=VALID_ARTIFACT.replace(".zip", extension))), [])

    def test_missing_and_extra_fields(self):
        data = record(extra="x")
        del data["sha256"]
        errors = self.errors(data)
        self.assertTrue(any("missing field(s): sha256" in e for e in errors))
        self.assertTrue(any("unexpected field(s): extra" in e for e in errors))

    def test_duplicate_key(self):
        path = self.apps / "PPSA01234.json"
        self.apps.mkdir(parents=True)
        path.write_text('{"titleid": "PPSA01234", "titleid": "PPSA01234"}', encoding="utf-8")
        report = Report()
        load_record(path, report)
        self.assertIn("duplicate JSON key", report.items[0][2])

    def test_filename_must_match(self):
        self.assertRejected(record(), "filename must be PPSA01234.json", filename="PPSA04321.json")

    def test_title_id_format_and_reserved(self):
        self.assertRejected(record(titleid="ppsa01234"), "four uppercase letters")
        self.assertRejected(record(titleid="PPSA99999"), "reserved")

    def test_sha256_format(self):
        self.assertRejected(record(sha256="A" * 64), "sha256 must be")
        self.assertRejected(record(sha256="a" * 63), "sha256 must be")

    def test_text_rules(self):
        self.assertRejected(record(name="Evil‮ppa"), "U+202E")
        self.assertRejected(record(description="line\nbreak"), "U+000A")
        self.assertRejected(record(name=" padded"), "whitespace")
        self.assertRejected(record(name="x" * 65), "longer than 64")
        self.assertRejected(record(kind="demo"), "kind must be")
        self.assertRejected(record(category="games"), "category must be")
        self.assertRejected(record(name=""), "must not be empty")
        self.assertRejected(record(version=5), "must be a string")

    def test_version_is_the_release_tag(self):
        url = "https://github.com/example/example-app/releases/download/{}/PPSA01234.zip"
        self.assertEqual(self.errors(record(version="0.6.0", artifact_url=url.format("v0.6.0"))), [])
        self.assertEqual(self.errors(record(version="v0.6.0", artifact_url=url.format("v0.6.0"))), [])
        self.assertEqual(self.errors(record(version="01.000.005", artifact_url=url.format("01.000.005"))), [])
        self.assertRejected(record(version="0.6.1", artifact_url=url.format("v0.6.0")), "version must match the release tag")
        self.assertRejected(record(version="1.0", artifact_url=url.format("release-1.0")), "'release-1.0'")
        # A leading v is dropped only before a digit: "vk-285" is its own version.
        self.assertEqual(self.errors(record(version="vk-285-112", artifact_url=url.format("vk-285-112"))), [])
        self.assertRejected(record(version="k-285-112", artifact_url=url.format("vk-285-112")), "use 'vk-285-112'")

    def test_url_rules(self):
        self.assertRejected(record(source_repo="http://github.com/example/example-app"), "source_repo")
        self.assertRejected(record(source_repo="https://github.com/example"), "source_repo")
        self.assertRejected(record(artifact_url="https://github.com/other/repo/releases/download/1/a.zip"),
                            "artifact_url")
        self.assertRejected(record(artifact_url="https://github.com/example/example-app/releases/latest/download/a.zip"),
                            "artifact_url")
        self.assertRejected(record(artifact_url="https://github.com/example/example-app/releases/download/latest/a.zip"),
                            "not 'latest'")
        self.assertRejected(record(artifact_url=VALID_ARTIFACT.replace(".zip", ".tar.gz")), "artifact_url")
        self.assertRejected(record(icon_url="https://example.com/icon.gif"), "icon_url")
        self.assertRejected(record(icon_url="https://user:pw@example.com/icon.png"), "icon_url")

    def test_reservation(self):
        report = Report()
        loaded = load_record(write_record(self.apps, reservation()), report)
        self.assertEqual(report.items, [])
        self.assertTrue(loaded.reserved)
        self.assertEqual(self.errors(reservation(version="0.1.0", license="MIT")), [])

    def test_reservation_urls_and_hash_must_all_be_null(self):
        for field, value in (("source_repo", "https://github.com/example/future-game"),
                             ("icon_url", "https://example.com/icon.png"),
                             ("sha256", "a" * 64)):
            with self.subTest(field=field):
                self.assertRejected(reservation(**{field: value}), f"{field} must be null in a reservation")

    def test_only_reservations_may_be_null(self):
        self.assertRejected(record(icon_url=None), "icon_url must not be null")
        self.assertRejected(record(version=None), "version must not be null")
        self.assertRejected(reservation(name=None), "name must not be null")
        data = reservation()
        del data["sha256"]
        self.assertRejected(data, "missing field(s): sha256")

    def test_catalog_uniqueness_and_stray_files(self):
        write_record(self.apps, record())
        write_record(self.apps, record(titleid="PPSA04321", name="EXAMPLE APP",
                                       artifact_url=VALID_ARTIFACT.replace("PPSA01234", "PPSA04321")))
        (self.apps / "notes.txt").write_text("x", encoding="utf-8")
        report = Report()
        load_catalog(self.apps, report)
        messages = [m for _, _, m in report.items]
        self.assertTrue(any("name duplicates" in m for m in messages))
        self.assertTrue(any("sha256 duplicates" in m for m in messages))
        self.assertTrue(any("only <TITLEID>.json" in m for m in messages))


VALID_ARTIFACT = record()["artifact_url"]

if __name__ == "__main__":
    unittest.main()
