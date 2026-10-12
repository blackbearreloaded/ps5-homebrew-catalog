import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import catalog.__main__ as cli

from catalog.policy import check_publisher
from catalog.records import Record
from catalog.report import Report
from catalog.updates import find_gone, find_update, is_release_bump, new_version, pick_asset

from helpers import record, reservation, write_record

OLD = record(
    titleid="PPSA01234", version="0.5.0",
    source_repo="https://github.com/example/example-app",
    artifact_url="https://github.com/example/example-app/releases/download/v0.5.0/example-0.5.0-PPSA01234.zip",
    icon_url="https://raw.githubusercontent.com/example/example-app/v0.5.0/sce_sys/icon0.png",
)


def asset(name, digest="sha256:" + "c" * 64):
    return {"name": name, "digest": digest, "size": 1000}


def release(tag, assets, prerelease=False, draft=False):
    return {"tag_name": tag, "assets": assets, "prerelease": prerelease, "draft": draft}


class FakeGitHub:
    def __init__(self, releases):
        self._releases = releases

    def releases(self, owner, name):
        return self._releases


class PickAssetTests(unittest.TestCase):
    def test_same_name_wins(self):
        chosen, how = pick_asset([asset("PPSA01234.zip"), asset("other.zip")], "PPSA01234.zip", "1", "1", "2")
        self.assertEqual((chosen["name"], how), ("PPSA01234.zip", "same file name"))

    def test_version_in_file_name(self):
        assets = [asset("example-0.6.0-PPSA01234.zip"), asset("sdk-0.6.0.zip")]
        chosen, how = pick_asset(assets, "example-0.5.0-PPSA01234.zip", "v0.5.0", "0.5.0", "v0.6.0")
        self.assertEqual(chosen["name"], "example-0.6.0-PPSA01234.zip")

    def test_only_file_of_that_type(self):
        chosen, how = pick_asset([asset("renamed.zip"), asset("notes.txt")], "old.zip", "1", "1", "2")
        self.assertEqual(chosen["name"], "renamed.zip")

    def test_ambiguous_or_missing(self):
        self.assertIsNone(pick_asset([asset("a.zip"), asset("b.zip")], "old.zip", "1", "1", "2")[0])
        self.assertIsNone(pick_asset([asset("a.ffpkg")], "old.zip", "1", "1", "2")[0])


class VersionTests(unittest.TestCase):
    def test_follows_the_tag_in_the_record_style(self):
        self.assertEqual(new_version("0.5.0", "v0.5.0", "v0.6.0"), "0.6.0")
        self.assertEqual(new_version("v0.5.0", "v0.5.0", "v0.6.0"), "v0.6.0")
        self.assertEqual(new_version("01.000.060", "01.000.060", "01.000.062"), "01.000.062")
        self.assertEqual(new_version("vk-285-112", "vk-285-112", "vk-290-001"), "vk-290-001")


class FindUpdateTests(unittest.TestCase):
    def find(self, releases, data=OLD, icon_exists=True):
        return find_update(Record(Path("PPSA01234.json"), data), FakeGitHub(releases),
                           icon_exists=lambda url: icon_exists)

    def test_proposes_the_newest_release_including_prereleases(self):
        update, reason = self.find([
            release("v0.7.0-beta", [asset("example-0.7.0-beta-PPSA01234.zip")], prerelease=True),
            release("v0.5.0", [asset("example-0.5.0-PPSA01234.zip")]),
        ])
        self.assertEqual(reason, "")
        self.assertTrue(update.prerelease)
        self.assertEqual(update.data["version"], "0.7.0-beta")
        self.assertEqual(update.data["sha256"], "c" * 64)
        self.assertTrue(update.data["artifact_url"].endswith("/v0.7.0-beta/example-0.7.0-beta-PPSA01234.zip"))
        self.assertIn("/v0.7.0-beta/", update.data["icon_url"])
        unchanged = {k for k in OLD if OLD[k] == update.data[k]}
        self.assertEqual(unchanged, set(OLD) - {"version", "artifact_url", "sha256", "icon_url"})

    def test_skips_drafts_and_up_to_date(self):
        update, reason = self.find([release("v0.9.0", [asset("x.zip")], draft=True),
                                    release("v0.5.0", [asset("example-0.5.0-PPSA01234.zip")])])
        self.assertEqual((update, reason), (None, "up to date"))

    def test_skips_releases_that_are_not_versions(self):
        update, reason = self.find([release("build-cache", [asset("ccache-clang18.tar")], prerelease=True),
                                    release("v0.6.0", [asset("example-0.6.0-PPSA01234.zip")])])
        self.assertEqual(reason, "")
        self.assertEqual(update.data["version"], "0.6.0")

    def test_keeps_icon_when_missing_at_new_tag(self):
        update, _ = self.find([release("v0.6.0", [asset("example-0.6.0-PPSA01234.zip")])], icon_exists=False)
        self.assertEqual(update.data["icon_url"], OLD["icon_url"])
        self.assertTrue(any("icon kept" in note for note in update.notes))

    def test_needs_a_digest(self):
        update, reason = self.find([release("v0.6.0", [asset("example-0.6.0-PPSA01234.zip", digest=None)])])
        self.assertIsNone(update)
        self.assertIn("no digest", reason)

    def test_gone_means_repository_release_or_file_not_found(self):
        listed = Record(Path("PPSA01234.json"), OLD)
        there = release("v0.5.0", [asset("example-0.5.0-PPSA01234.zip")])
        cases = [
            (None, there, "the repository no longer exists"),
            ({}, None, "the release v0.5.0 no longer exists"),
            ({}, release("v0.5.0", [asset("other.zip")]), "the release v0.5.0 no longer has example-0.5.0-PPSA01234.zip"),
            ({}, there, None),
        ]
        for repo, found, expected in cases:
            github = mock.Mock(repo=lambda owner, name: repo, release_by_tag=lambda owner, name, tag: found)
            self.assertEqual(find_gone(listed, github), expected)
        self.assertIsNone(find_gone(Record(Path("PPSA01234.json"), reservation(titleid="PPSA01234")), mock.Mock()))

    def test_reservations_are_skipped(self):
        self.assertEqual(self.find([], data=reservation(titleid="PPSA01234")), (None, "reservation"))


class BumpPolicyTests(unittest.TestCase):
    def setUp(self):
        self.github = FakeGitHub([release("v0.6.0", [asset("example-0.6.0-PPSA01234.zip")])])
        self.old = Record(Path("PPSA01234.json"), OLD)
        update, _ = find_update(self.old, self.github, icon_exists=lambda url: True)
        self.new = Record(Path("PPSA01234.json"), update.data)

    def test_newest_release_bump_is_recognised(self):
        self.assertTrue(is_release_bump(self.old, self.new, self.github))

    def test_other_changes_are_not_a_bump(self):
        renamed = Record(self.new.path, dict(self.new.data, name="Other Name"))
        self.assertFalse(is_release_bump(self.old, renamed, self.github))
        older = FakeGitHub([release("v0.7.0", [])])
        self.assertFalse(is_release_bump(self.old, self.new, older))

    def test_bot_may_open_a_bump_but_not_other_changes(self):
        report = Report()
        check_publisher("catalog-bot[bot]", False, self.old, self.new, self.github, report)
        self.assertFalse(report.failed)
        report = Report()
        renamed = Record(self.new.path, dict(self.new.data, name="Other Name"))
        github = FakeGitHub(self.github._releases)
        github.account_type = lambda login: "User"
        check_publisher("catalog-bot[bot]", False, self.old, renamed, github, report)
        self.assertTrue(report.failed)


OTHER = record(
    titleid="PPSA04321", name="Other App", version="1.0", sha256="b" * 64,
    source_repo="https://github.com/example/other-app",
    artifact_url="https://github.com/example/other-app/releases/download/1.0/other-PPSA04321.zip",
    icon_url="https://raw.githubusercontent.com/example/other-app/1.0/sce_sys/icon0.png",
)


class OpenPullRequestTests(unittest.TestCase):
    """One pull request, on one branch, carries every pending update."""

    def run_git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.origin, self.clone = root / "origin", root / "clone"
        self.origin.mkdir()
        self.run_git(self.origin, "init", "-q", "-b", "main")
        self.run_git(self.origin, "config", "user.email", "t@example.com")
        self.run_git(self.origin, "config", "user.name", "T")
        self.run_git(self.origin, "config", "receive.denyCurrentBranch", "ignore")
        write_record(self.origin / "apps", OLD)
        write_record(self.origin / "apps", OTHER)
        self.run_git(self.origin, "add", ".")
        self.run_git(self.origin, "commit", "-q", "-m", "base")
        self.run_git(root, "clone", "-q", str(self.origin), str(self.clone))
        self.run_git(self.clone, "config", "user.email", "bot@example.com")
        self.run_git(self.clone, "config", "user.name", "Bot")

        first, _ = find_update(Record(self.clone / "apps" / "PPSA01234.json", OLD),
                               FakeGitHub([release("v0.6.0", [asset("example-0.6.0-PPSA01234.zip")])]),
                               icon_exists=lambda url: True)
        second, _ = find_update(Record(self.clone / "apps" / "PPSA04321.json", OTHER),
                                FakeGitHub([release("2.0", [asset("other-PPSA04321.zip", "sha256:" + "d" * 64)])]),
                                icon_exists=lambda url: True)
        self.updates = [first, second]
        self.created, self.updated, self.closed, self.open_pr = [], [], [], {}
        self.github = mock.Mock(
            open_pull=lambda repo, branch: self.open_pr.get(branch),
            create_pull=lambda repo, head, base, title, body: self.created.append((head, title, body)) or {"number": 7},
            update_pull=lambda repo, number, title, body: self.updated.append((number, title, body)),
            close_pull=lambda repo, number: self.closed.append(number),
        )

    def open(self, updates):
        report = Report()
        with mock.patch.object(cli, "ROOT", self.clone), mock.patch.object(cli, "APPS", self.clone / "apps"):
            cli.open_updates_pr(updates, "example/catalog", self.github, report)
        return [item[2] for item in report.items]

    def pushed(self, titleid):
        return json.loads(self.run_git(self.origin, "show", f"catalog-update/all:apps/{titleid}.json"))

    def test_all_updates_share_one_pull_request(self):
        self.open(self.updates)
        (head, title, body), = self.created
        self.assertEqual((head, title), ("catalog-update/all", "Update 2 apps: Example App to 0.6.0, Other App to 2.0"))
        self.assertEqual((self.pushed("PPSA01234")["version"], self.pushed("PPSA04321")["version"]), ("0.6.0", "2.0"))
        self.assertIn("### Example App (`PPSA01234`): 0.5.0 → 0.6.0", body)
        self.assertIn('<!-- catalog-updates: {"PPSA01234": "v0.6.0", "PPSA04321": "2.0"} -->', body)
        # The working tree is back on main, untouched.
        self.assertEqual(json.loads((self.clone / "apps" / "PPSA01234.json").read_text())["version"], "0.5.0")

    def test_identical_run_changes_nothing_and_a_new_update_refreshes_it(self):
        self.open(self.updates[:1])
        self.assertEqual(self.created[0][1], "Update Example App to 0.6.0")
        self.open_pr["catalog-update/all"] = {"number": 7, "title": "Update Example App to 0.6.0"}
        self.assertIn("already proposes", self.open(self.updates[:1])[-1])
        self.assertEqual(self.updated, [])
        self.open(self.updates)
        self.assertEqual([(n, t) for n, t, _ in self.updated], [(7, "Update 2 apps: Example App to 0.6.0, Other App to 2.0")])
        self.assertEqual(self.pushed("PPSA04321")["version"], "2.0")

    def test_gone_apps_get_one_removal_pull_request(self):
        gone = [(Record(self.clone / "apps" / "PPSA01234.json", OLD), "the repository no longer exists")]
        with mock.patch.object(cli, "ROOT", self.clone), mock.patch.object(cli, "APPS", self.clone / "apps"):
            cli.open_removals_pr(gone, "example/catalog", self.github, Report())
            (head, title, body), = self.created
            self.assertEqual((head, title), ("catalog-update/removals", "Withdraw Example App: its source is gone"))
            self.assertIn("the repository no longer exists", body)
            self.assertEqual(self.run_git(self.clone, "diff", "--name-only", "origin/main",
                                          "origin/catalog-update/removals").split(), ["apps/PPSA01234.json"])
            # The working tree is back on main, with the record still there.
            self.assertTrue((self.clone / "apps" / "PPSA01234.json").is_file())
            self.open_pr["catalog-update/removals"] = {"number": 9, "title": title}
            report = Report()
            cli.open_removals_pr(gone, "example/catalog", self.github, report)
            self.assertIn("already proposes", report.items[-1][2])
            cli.open_removals_pr([], "example/catalog", self.github, Report())
            self.assertEqual(self.closed, [9])

    def test_stale_pull_request_is_closed(self):
        self.open_pr["catalog-update/all"] = {"number": 7, "title": "Update Example App to 0.6.0"}
        self.open([])
        self.assertEqual(self.closed, [7])
        self.assertNotIn("catalog-updates:", self.updated[0][2])
        self.assertEqual(self.created, [])


if __name__ == "__main__":
    unittest.main()
