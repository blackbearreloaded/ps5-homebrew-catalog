import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from catalog import draft as draft_module
from catalog.draft import draft_record, license_section, parse_repo

from helpers import record, write_record

PARAM = {"titleId": "PPSA07777", "contentId": "UP9000-PPSA07777_00-EXAMPLE000000001",
         "contentVersion": "01.000.000",
         "localizedParameters": {"defaultLanguage": "en-US", "en-US": {"titleName": "Example Port"}}}
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + (512).to_bytes(4, "big") * 2


class FakeGitHub:
    def __init__(self, license_id=None, assets=None, paths=None, param=PARAM, readme=""):
        self.license_id = license_id
        self.assets = assets if assets is not None else [
            {"name": "Example-v1.2.0.zip", "size": 1000, "digest": "sha256:" + "d" * 64}]
        self.paths = paths if paths is not None else ["README.md", "sce_sys/param.json", "sce_sys/icon0.png"]
        self.param = param
        self.readme = readme

    def repo(self, owner, name):
        return {"full_name": "Dev/Example", "private": False, "archived": False, "fork": False,
                "license": {"spdx_id": self.license_id} if self.license_id else None}

    def releases(self, owner, name):
        return [{"tag_name": "v1.2.0", "prerelease": True, "draft": False, "assets": self.assets,
                 "published_at": "2026-09-01T00:00:00Z"}]

    def release_by_tag(self, owner, name, tag):
        return self.releases(owner, name)[0]

    def tree(self, owner, name, ref):
        return self.paths

    def file_text(self, owner, name, path, ref):
        return json.dumps(self.param) if path.endswith("param.json") else self.readme

    def user(self, login):
        return {"name": "Dev Person"}


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.apps = Path(self.tmp.name) / "apps"
        write_record(self.apps, record())
        patcher = mock.patch.object(draft_module.artifacts, "fetch_small", lambda url, limit: PNG)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_repo(self):
        self.assertEqual(parse_repo("https://github.com/Dev/Example.git"), ("Dev", "Example"))
        self.assertEqual(parse_repo("Dev/Example"), ("Dev", "Example"))
        with self.assertRaises(ValueError):
            parse_repo("Example")

    def test_facts_are_drafted_and_judgment_left_open(self):
        result = draft_record("Dev/Example", FakeGitHub(license_id="MIT"), self.apps)
        self.assertEqual(result.blockers, [])
        r = result.record
        self.assertEqual((r["titleid"], r["name"], r["version"], r["license"]), ("PPSA07777", "Example Port", "1.2.0", "MIT"))
        self.assertEqual(r["artifact_url"], "https://github.com/Dev/Example/releases/download/v1.2.0/Example-v1.2.0.zip")
        self.assertEqual(r["sha256"], "d" * 64)
        self.assertEqual(r["icon_url"], "https://raw.githubusercontent.com/Dev/Example/v1.2.0/sce_sys/icon0.png")
        self.assertEqual(r["author"], "Dev Person")
        self.assertEqual((r["kind"], r["description"]), ("", ""))

    def test_missing_license_is_a_todo(self):
        result = draft_record("Dev/Example", FakeGitHub(), self.apps)
        self.assertEqual(result.record["license"], "")
        self.assertTrue(any("no license" in item for item in result.todo))

    def test_blockers(self):
        cases = {
            "no sce_sys/param.json": FakeGitHub(paths=["README.md"]),
            "not a PS5 (PPSA) title ID": FakeGitHub(param=dict(PARAM, titleId="CUSA01234")),
            "no .zip, .ffpkg or .ffpfsc": FakeGitHub(assets=[{"name": "x.elf", "digest": "sha256:" + "d" * 64}]),
            "no digest": FakeGitHub(assets=[{"name": "x.zip"}]),
        }
        for expected, github in cases.items():
            with self.subTest(expected=expected):
                self.assertTrue(any(expected in b for b in draft_record("Dev/Example", github, self.apps).blockers))

    def test_already_listed_title_id_blocks(self):
        github = FakeGitHub(param=dict(PARAM, titleId="PPSA01234"))
        self.assertTrue(any("already listed" in b for b in draft_record("Dev/Example", github, self.apps).blockers))

    def test_license_section(self):
        readme = "# App\nintro\n## License and terms\nCode is **MIT**.\n\nMore.\n## Next\nno"
        self.assertEqual(license_section(readme), "Code is **MIT**. More.")
        self.assertEqual(license_section("# App\nno license heading"), "")


if __name__ == "__main__":
    unittest.main()
