"""Which pull requests are merged without a maintainer, and the command that merges them."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import catalog.__main__ as cli
from catalog.automerge import UPDATE_BOT, UPDATE_BRANCH, bump_reasons, new_app_reasons, update_pull_reasons
from catalog.policy import Change
from catalog.records import load_catalog, load_record
from catalog.report import Report

from helpers import record, reservation, write_record

NEW = dict(version="01.000.010", sha256="b" * 64,
           artifact_url="https://github.com/example/example-app/releases/download/01.000.010/PPSA01234.zip",
           icon_url="https://raw.githubusercontent.com/example/example-app/01.000.010/sce_sys/icon0.png")
MODIFIED = [Change("M", "apps/PPSA01234.json", "100644")]


def github(newest="01.000.010", owner_type="User", member=False):
    return mock.Mock(releases=lambda owner, repo: [{"tag_name": newest, "draft": False}],
                     account_type=lambda login: owner_type, is_public_member=lambda org, user: member)


class BumpReasonsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, name, data):
        return load_record(write_record(Path(self.tmp.name) / name, data), Report())

    def reasons(self, author="example", changes=MODIFIED, old=None, new=None, hub=None, **fields):
        old = old or self.load("old", record())
        new = new or self.load("new", record(**{**NEW, **fields}))
        return bump_reasons(author, changes, old, new, hub or github())

    def test_the_developer_moving_the_app_to_its_newest_release_is_merged(self):
        self.assertEqual(self.reasons(), [])
        self.assertEqual(self.reasons(author="Example"), [])

    def test_a_public_member_of_the_owning_organization_counts_as_the_developer(self):
        self.assertEqual(self.reasons(author="member", hub=github(owner_type="Organization", member=True)), [])
        self.assertIn("@member does not own example/example-app",
                      self.reasons(author="member", hub=github(owner_type="Organization")))

    def test_someone_else_is_left_for_a_maintainer(self):
        self.assertEqual(self.reasons(author="stranger"), ["@stranger does not own example/example-app"])

    def test_a_new_app_a_removal_and_several_files_are_left_for_a_maintainer(self):
        self.assertEqual(self.reasons(changes=[Change("A", "apps/PPSA01234.json", "100644")]), ["it adds a new app"])
        self.assertEqual(self.reasons(changes=[Change("D", "apps/PPSA01234.json")]), ["it removes an app"])
        self.assertIn("2 files", self.reasons(changes=MODIFIED + [Change("M", "apps/PPSA09999.json", "100644")])[0])
        self.assertIn("not an app's record", self.reasons(changes=[Change("M", "catalog/policy.py", "100644")])[0])
        self.assertEqual(self.reasons(changes=[Change("M", "apps/PPSA01234.json", "100755")]),
                         ["the record is not a regular file"])

    def test_a_change_beyond_the_release_is_left_for_a_maintainer(self):
        for fields in ({"name": "Another Name"}, {"description": "Another sentence about the app."},
                       {"author": "Someone"}, {"kind": "game"}, {"license": "MIT"}):
            with self.subTest(fields=fields):
                new = self.load("changed", record(**{**NEW, **fields}))
                self.assertIn("more than the release", self.reasons(new=new)[0])

    def test_a_release_that_is_not_the_newest_is_left_for_a_maintainer(self):
        self.assertIn("not the newest", self.reasons(hub=github(newest="01.000.020"))[0])

    def test_the_same_file_under_a_new_version_is_left_for_a_maintainer(self):
        self.assertIn("it does not point at a new file", self.reasons(sha256="a" * 64))

    def test_an_icon_outside_the_repository_is_left_for_a_maintainer(self):
        reasons = self.reasons(icon_url="https://raw.githubusercontent.com/other/place/main/icon0.png")
        self.assertEqual(reasons, ["the icon moves to an address outside the app's repository"])

    def test_a_reservation_and_an_unreadable_record_are_left_for_a_maintainer(self):
        held = self.load("held", reservation(titleid="PPSA01234"))
        self.assertEqual(self.reasons(old=held), ["it changes a reservation"])
        self.assertEqual(bump_reasons("example", MODIFIED, None, None, github()),
                         ["the listed or the proposed record could not be read"])

    def test_a_github_failure_is_left_for_a_maintainer(self):
        hub = github()
        hub.releases = mock.Mock(side_effect=cli.GitHubError("down"))
        self.assertEqual(self.reasons(hub=hub), ["GitHub could not be asked: down"])


ADDED = [Change("A", "apps/PPSA04321.json", "100644")]


def second(**fields):
    """A second app of the same developer, from a repository of their own."""
    return record(**{"titleid": "PPSA04321", "name": "Second App", "version": "01.000.000",
                     "source_repo": "https://github.com/example/second-app",
                     "artifact_url": "https://github.com/example/second-app/releases/download/01.000.000/PPSA04321.zip",
                     "icon_url": "https://raw.githubusercontent.com/example/second-app/01.000.000/icon0.png",
                     **fields})


class UpdatePullTests(unittest.TestCase):
    """The catalog bot's pull request of pending updates, several records at once."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def load(self, name, data):
        return load_record(write_record(Path(self.tmp.name) / name, data), Report())

    def pair(self, **fields):
        return self.load("old", record()), self.load("new", record(**{**NEW, **fields}))

    def reasons(self, pairs=None, changes=None, author=UPDATE_BOT, head=UPDATE_BRANCH, fork=False, hub=None):
        pairs = pairs if pairs is not None else [self.pair(), self.pair()]
        changes = changes if changes is not None else [Change("M", f"apps/PPSA0123{n}.json", "100644")
                                                       for n in range(len(pairs))]
        return update_pull_reasons(author, head, fork, changes, pairs, hub or github())

    def test_the_bots_pull_request_of_release_bumps_is_merged_though_it_changes_several_apps(self):
        self.assertEqual(self.reasons(), [])

    def test_only_the_bot_from_its_own_branch_of_this_repository(self):
        self.assertEqual(self.reasons(author="stranger"), ["@stranger is not the catalog bot"])
        self.assertIn("not the bot's", self.reasons(head="catalog-update/removals")[0])
        self.assertIn("not the bot's", self.reasons(fork=True)[0])

    def test_one_record_that_is_not_a_plain_bump_holds_back_the_whole_pull_request(self):
        reasons = self.reasons(pairs=[self.pair(), self.pair(name="Another Name")])
        self.assertEqual(len(reasons), 1)
        self.assertTrue(reasons[0].startswith("apps/PPSA01231.json: it changes more than the release"))

    def test_a_removal_a_new_app_or_a_file_that_is_not_a_record_holds_it_back(self):
        pairs = [self.pair(), self.pair()]
        for change, fragment in ((Change("D", "apps/PPSA01231.json"), "adds or removes"),
                                 (Change("A", "apps/PPSA01231.json", "100644"), "adds or removes"),
                                 (Change("M", "catalog/policy.py", "100644"), "not an app's record"),
                                 (Change("M", "apps/PPSA01231.json", "100755"), "not a regular file")):
            with self.subTest(change=change):
                changes = [Change("M", "apps/PPSA01230.json", "100644"), change]
                self.assertTrue(any(fragment in r for r in self.reasons(pairs=pairs, changes=changes)))

    def test_an_empty_pull_request_or_an_unreadable_record_is_left_alone(self):
        self.assertEqual(self.reasons(pairs=[], changes=[]), ["it changes no app's record"])
        self.assertTrue(any("could not be read" in r for r in self.reasons(pairs=[(None, None)])))

    def test_the_release_must_still_be_the_newest(self):
        self.assertTrue(any("not the newest" in r for r in self.reasons(hub=github(newest="01.000.020"))))


class NewAppReasonsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        write_record(Path(self.tmp.name) / "apps", record())
        self.listed = load_catalog(Path(self.tmp.name) / "apps", Report())

    def tearDown(self):
        self.tmp.cleanup()

    def second(self, **fields):
        return load_record(write_record(Path(self.tmp.name) / "new", second(**fields)), Report())

    def reasons(self, author="example", changes=ADDED, new=None, hub=None):
        return new_app_reasons(author, changes, new or self.second(), self.listed, hub or github())

    def test_a_developer_with_a_listed_app_adding_another_of_their_own_is_merged(self):
        self.assertEqual(self.reasons(), [])
        self.assertEqual(self.reasons(author="Example"), [])

    def test_a_member_of_the_organization_that_owns_a_listed_app_counts(self):
        hub = github(owner_type="Organization", member=True)
        self.assertEqual(self.reasons(author="member", hub=hub), [])

    def test_a_developer_without_a_listed_app_is_left_for_a_maintainer(self):
        hub = github(owner_type="Organization", member=False)
        hub.account_type = lambda login: "User" if login == "newcomer" else "Organization"
        new = self.second(source_repo="https://github.com/newcomer/app",
                          artifact_url="https://github.com/newcomer/app/releases/download/01.000.000/PPSA04321.zip",
                          icon_url="https://raw.githubusercontent.com/newcomer/app/01.000.000/icon0.png")
        self.assertEqual(self.reasons(author="newcomer", new=new, hub=hub), ["@newcomer has no app in the catalog yet"])

    def test_someone_who_does_not_own_the_new_apps_repository_is_left_for_a_maintainer(self):
        self.assertEqual(self.reasons(author="stranger"), ["@stranger does not own example/second-app"])

    def test_a_modification_a_removal_a_reservation_and_several_files_are_left_for_a_maintainer(self):
        self.assertEqual(self.reasons(changes=MODIFIED), ["it is not a new app"])
        self.assertIn("2 files", self.reasons(changes=ADDED + MODIFIED)[0])
        self.assertEqual(self.reasons(changes=[Change("A", "apps/PPSA04321.json", "100755")]),
                         ["the record is not a regular file"])
        held = load_record(write_record(Path(self.tmp.name) / "held", reservation()), Report())
        self.assertEqual(self.reasons(new=held), ["it adds a reservation"])
        self.assertEqual(new_app_reasons("example", ADDED, None, self.listed, github()),
                         ["the proposed record could not be read"])


def run(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class AutomergeCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin, self.clone = root / "origin", root / "clone"
        self.origin.mkdir()
        self.git = lambda *a: run(self.origin, "git", *a)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        write_record(self.origin / "apps", record())
        self.git("add", ".")
        self.git("commit", "-q", "-m", "base")

    def tearDown(self):
        self.tmp.cleanup()

    def automerge(self, files, author="example", draft=False, env=None, merge=True, refuse=False):
        self.git("checkout", "-q", "-b", "pr")
        for path, content in files.items():
            target = self.origin / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "pr")
        sha = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/pull/1/head", "HEAD")
        self.git("checkout", "-q", "main")
        run(self.origin.parent, "git", "clone", "-q", str(self.origin), str(self.clone))
        event = self.clone.parent / "event.json"
        event.write_text(json.dumps({"pull_request": {
            "number": 1, "title": "Update Example App", "draft": draft, "user": {"login": author},
            "head": {"sha": sha}, "base": {"ref": "main"}}}), encoding="utf-8")
        reader, writer = github(), mock.Mock()
        if refuse:
            writer.merge_pull.side_effect = cli.GitHubError("GitHub API returned HTTP 405")
        variables = {"GITHUB_EVENT_PATH": str(event), "GITHUB_STEP_SUMMARY": "", "GITHUB_OUTPUT": "",
                     "GITHUB_REPOSITORY": "owner/catalog", "MERGE_TOKEN": "token",
                     **(env or {})}
        with mock.patch.object(cli, "ROOT", self.clone), mock.patch.object(cli, "APPS", self.clone / "apps"), \
                mock.patch.object(cli, "GitHub", lambda token=None: writer if token else reader), \
                mock.patch.dict(os.environ, variables), mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            status = cli.main(["automerge"] + (["--merge"] if merge else []))
        return status, writer, sha

    def bump(self, **fields):
        return {"apps/PPSA01234.json": json.dumps(record(**{**NEW, **fields}), indent=2)}

    def test_a_developers_release_bump_is_approved_and_merged_at_the_checked_commit(self):
        status, writer, sha = self.automerge(self.bump())
        self.assertEqual(status, 0)
        writer.approve_pull.assert_called_once()
        self.assertEqual(writer.approve_pull.call_args.args[:3], ("owner/catalog", 1, sha))
        writer.merge_pull.assert_called_once_with("owner/catalog", 1, sha, "Update Example App (#1)")

    def test_nothing_is_merged_without_the_switch(self):
        status, writer, _ = self.automerge(self.bump(), merge=False)
        self.assertEqual(status, 0)
        writer.merge_pull.assert_not_called()

    def second(self, **fields):
        return {"apps/PPSA04321.json": json.dumps(second(**fields))}

    def test_another_app_of_a_developer_who_has_one_is_approved_and_merged(self):
        status, writer, sha = self.automerge(self.second())
        self.assertEqual(status, 0)
        self.assertEqual(writer.approve_pull.call_args.args[:3], ("owner/catalog", 1, sha))
        writer.merge_pull.assert_called_once_with("owner/catalog", 1, sha, "Update Example App (#1)")

    def test_a_new_app_of_someone_without_a_listed_app_is_left_for_a_maintainer(self):
        status, writer, _ = self.automerge(self.second(), author="stranger")
        self.assertEqual(status, 0)
        writer.approve_pull.assert_not_called()
        writer.merge_pull.assert_not_called()

    def test_another_account_a_draft_and_a_renamed_app_are_left_for_a_maintainer(self):
        for name, arguments in (("stranger", {"author": "stranger"}), ("draft", {"draft": True})):
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                _, writer, _ = self.automerge(self.bump(), **arguments)
                writer.merge_pull.assert_not_called()
        self.tearDown()
        self.setUp()
        _, writer, _ = self.automerge(self.bump(name="Another Name"))
        writer.merge_pull.assert_not_called()

    def test_a_refused_merge_is_reported_and_does_not_fail_the_check(self):
        status, writer, _ = self.automerge(self.bump(), refuse=True)
        self.assertEqual(status, 0)
        writer.merge_pull.assert_called_once()


if __name__ == "__main__":
    unittest.main()
