"""Notes for the reviewer about a new listing that builds on an app already in the catalog."""

import unittest
from pathlib import Path

from catalog.github import GitHubError
from catalog.policy import derivative_notes
from catalog.records import Record

from helpers import record, reservation


def listing(titleid, name, owner, repo):
    return Record(Path(f"{titleid}.json"), record(
        titleid=titleid, name=name, source_repo=f"https://github.com/{owner}/{repo}",
        artifact_url=f"https://github.com/{owner}/{repo}/releases/download/1/{titleid}.zip"))


class FakeGitHub:
    def __init__(self, repo=None, error=False):
        self.answer, self.error = repo or {}, error

    def repo(self, owner, name):
        if self.error:
            raise GitHubError("down")
        return self.answer


LISTED = [listing("PPSA99008", "ProsperoEden", "blackbearreloaded", "ProsperoEden"),
          listing("PPSA99310", "Mario 64", "griches", "PS5_Ghostship")]


class DerivativeNotesTests(unittest.TestCase):
    def test_an_unrelated_app_gets_no_note(self):
        new = listing("PPSA01234", "Example App", "example", "example-app")
        self.assertEqual(derivative_notes(new, LISTED, FakeGitHub({"fork": False})), [])

    def test_a_fork_of_a_listed_app_names_the_listing(self):
        new = listing("PPSA01234", "Switch Look", "someone", "SwitchPS5")
        hub = FakeGitHub({"fork": True, "parent": {"full_name": "BlackBearReloaded/ProsperoEden"}})
        [note] = derivative_notes(new, LISTED, hub)
        self.assertIn("fork of BlackBearReloaded/ProsperoEden, which is listed as ProsperoEden (PPSA99008)", note)

    def test_a_fork_of_a_fork_is_matched_through_its_source(self):
        new = listing("PPSA01234", "Vulkan Harkinian", "someone", "PS5_Shipwright")
        hub = FakeGitHub({"fork": True, "parent": {"full_name": "middle/fork"},
                          "source": {"full_name": "griches/PS5_Ghostship"}})
        [note] = derivative_notes(new, LISTED, hub)
        self.assertIn("listed as Mario 64 (PPSA99310)", note)

    def test_a_fork_of_something_unlisted_is_still_noted(self):
        new = listing("PPSA01234", "Example App", "example", "example-app")
        hub = FakeGitHub({"fork": True, "parent": {"full_name": "libretro/swanstation"}})
        [note] = derivative_notes(new, LISTED, hub)
        self.assertIn("fork of libretro/swanstation: check that it is a distinct app", note)

    def test_a_name_that_contains_a_listed_name_is_noted(self):
        new = listing("PPSA01234", "ProsperoEden Switch UI", "example", "example-app")
        [note] = derivative_notes(new, LISTED, FakeGitHub())
        self.assertIn("its name contains 'ProsperoEden', the name of PPSA99008", note)
        held = Record(Path("PPSA05555.json"), reservation(name="prosperoeden switch edition"))
        self.assertEqual(len(derivative_notes(held, LISTED, FakeGitHub())), 1)

    def test_a_name_is_matched_as_whole_words_only(self):
        new = listing("PPSA01234", "ProsperoEdenX", "example", "example-app")
        self.assertEqual(derivative_notes(new, LISTED, FakeGitHub()), [])

    def test_the_app_itself_and_a_github_failure_give_no_note(self):
        self.assertEqual(derivative_notes(LISTED[0], LISTED, FakeGitHub({"fork": False})), [])
        new = listing("PPSA01234", "Example App", "example", "example-app")
        self.assertEqual(derivative_notes(new, LISTED, FakeGitHub(error=True)), [])


if __name__ == "__main__":
    unittest.main()
