"""End-to-end test of `python3 -m catalog pr` against throwaway git repositories."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import catalog.__main__ as cli

from helpers import record, reservation, write_record


def run(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class PullRequestCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin = root / "origin"
        self.clone = root / "clone"
        self.origin.mkdir()
        git = lambda *a: run(self.origin, "git", *a)
        git("init", "-q", "-b", "main")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test")
        write_record(self.origin / "apps", record())
        git("add", ".")
        git("commit", "-q", "-m", "base")
        self.git = git

    def tearDown(self):
        self.tmp.cleanup()

    def open_pr(self, author, association, files, head_repo="someone/catalog"):
        """Commit files on a PR branch, publish it as refs/pull/1/head and clone main."""
        self.git("checkout", "-q", "-b", "pr")
        for path, content in files.items():
            target = self.origin / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "pr")
        self.git("update-ref", "refs/pull/1/head", "HEAD")
        self.git("checkout", "-q", "main")
        run(self.origin.parent, "git", "clone", "-q", str(self.origin), str(self.clone))
        event = self.clone.parent / "event.json"
        event.write_text(json.dumps({"pull_request": {
            "number": 1, "user": {"login": author}, "author_association": association,
            "head": {"repo": {"full_name": head_repo}}, "base": {"repo": {"full_name": "owner/catalog"}}}}),
            encoding="utf-8")
        return event

    def run_pr(self, event, commit_author="example"):
        verified = []
        self.output = self.clone.parent / "output.txt"
        self.output.write_text("", encoding="utf-8")
        github = mock.Mock(account_type=lambda login: "User", commit_author=lambda repo, sha: commit_author)
        with mock.patch.object(cli, "ROOT", self.clone), \
                mock.patch.object(cli, "APPS", self.clone / "apps"), \
                mock.patch.object(cli, "verify_record", lambda r, g, rep, previous=None: verified.append(r.titleid)), \
                mock.patch.object(cli, "GitHub", lambda: github), \
                mock.patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event), "GITHUB_STEP_SUMMARY": "",
                                             "GITHUB_REPOSITORY": "owner/catalog",
                                             "GITHUB_OUTPUT": str(self.output)}), \
                mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            status = cli.main(["pr"])
        return status, verified

    def new_record(self, **changes):
        data = record(titleid="PPSA04321", name="Second App", version="2", sha256="b" * 64,
                      artifact_url="https://github.com/example/example-app/releases/download/2/PPSA04321.zip")
        data.update(changes)
        return json.dumps(data)

    def test_owner_submission_is_verified(self):
        event = self.open_pr("example", "NONE", {"apps/PPSA04321.json": self.new_record()})
        self.assertEqual(self.run_pr(event), (0, ["PPSA04321"]))

    def test_someone_elses_repository_passes_the_check_and_waits_for_a_maintainer(self):
        event = self.open_pr("mallory", "NONE", {"apps/PPSA04321.json": self.new_record()})
        self.assertEqual(self.run_pr(event), (0, ["PPSA04321"]))
        self.assertIn("third_party=true", self.output.read_text(encoding="utf-8"))

    def test_the_owners_submission_is_not_marked_third_party(self):
        event = self.open_pr("example", "NONE", {"apps/PPSA04321.json": self.new_record()})
        self.run_pr(event)
        self.assertIn("third_party=false", self.output.read_text(encoding="utf-8"))

    def test_branch_in_this_repository_counts_as_maintainer(self):
        # Only accounts and apps with write access (the catalog bot's discovery job) can push branches here.
        event = self.open_pr("homebrew-page-bot[bot]", "NONE", {"apps/PPSA04321.json": self.new_record()},
                             head_repo="owner/catalog")
        self.assertEqual(self.run_pr(event), (0, ["PPSA04321"]))

    def test_pr_cannot_change_validator(self):
        event = self.open_pr("example", "CONTRIBUTOR", {
            "apps/PPSA04321.json": self.new_record(),
            "catalog/records.py": "FIELDS = ()\n",
        })
        self.assertEqual(self.run_pr(event)[0], 1)

    def test_catalog_wide_rules_use_merged_view(self):
        event = self.open_pr("example", "NONE", {"apps/PPSA04321.json": self.new_record(name="Example App")})
        self.assertEqual(self.run_pr(event)[0], 1)


    def test_anyone_can_reserve_a_free_title_id(self):
        event = self.open_pr("newdev", "NONE", {"apps/PPSA05555.json": json.dumps(reservation())})
        self.assertEqual(self.run_pr(event)[0], 0)

    def test_only_the_holder_can_change_a_reservation(self):
        write_record(self.origin / "apps", reservation())
        self.git("add", ".")
        self.git("commit", "-q", "-m", "reserve")
        changed = json.dumps(reservation(name="Renamed Game"))
        event = self.open_pr("mallory", "NONE", {"apps/PPSA05555.json": changed})
        self.assertEqual(self.run_pr(event, commit_author="example")[0], 1)

    def test_holder_can_update_a_reservation(self):
        write_record(self.origin / "apps", reservation())
        self.git("add", ".")
        self.git("commit", "-q", "-m", "reserve")
        changed = json.dumps(reservation(name="Renamed Game"))
        event = self.open_pr("example", "NONE", {"apps/PPSA05555.json": changed})
        self.assertEqual(self.run_pr(event, commit_author="example")[0], 0)


if __name__ == "__main__":
    unittest.main()
