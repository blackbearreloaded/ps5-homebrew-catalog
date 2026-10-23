"""`is_curator` against a throwaway git repository: listing another developer's app earns the role."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import catalog.__main__ as cli

from helpers import record, reservation, write_record


class CuratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run_git("init", "-q", "-b", "main")

    def tearDown(self):
        self.tmp.cleanup()

    def run_git(self, *args, **env):
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True,
                       env={**os.environ, **env})

    def commit(self, who, data, filename=None):
        """Add a record in a commit written by the given account."""
        write_record(self.root / "apps", data, filename)
        self.run_git("add", ".")
        self.run_git("commit", "-q", "-m", "list", GIT_AUTHOR_NAME=who, GIT_AUTHOR_EMAIL=f"{who}@users.noreply.github.com",
                     GIT_COMMITTER_NAME=who, GIT_COMMITTER_EMAIL=f"{who}@users.noreply.github.com")

    def is_curator(self, login, api_author=None):
        github = mock.Mock(commit_author=lambda repo, sha: api_author or login)
        with mock.patch.object(cli, "ROOT", self.root), \
                mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/catalog"}):
            return cli.is_curator(login, github)

    def test_listing_an_app_from_someone_elses_repository_makes_a_curator(self):
        self.commit("carla", record())
        self.assertTrue(self.is_curator("carla"))

    def test_listing_only_your_own_apps_or_reservations_does_not(self):
        self.commit("example", record())
        self.commit("example", reservation(), "PPSA05555.json")
        self.assertFalse(self.is_curator("example"))

    def test_an_account_that_listed_nothing_is_not_a_curator(self):
        self.commit("carla", record())
        self.assertFalse(self.is_curator("mallory"))

    def test_the_api_decides_who_wrote_a_commit_that_only_mentions_the_login(self):
        self.commit("carla", record())
        self.assertFalse(self.is_curator("carla", api_author="someone-else"))


if __name__ == "__main__":
    unittest.main()
