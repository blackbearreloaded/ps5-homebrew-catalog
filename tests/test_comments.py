import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import catalog.__main__ as cli
from catalog import comments
from catalog.records import Record

from helpers import record, reservation, write_record


def node(number, titleid, title=None, category=comments.ACTIVE, locked=False, likes=0, replies=(), total=None):
    return {
        "id": f"D_{number}", "number": number, "title": title or f"Example App ({titleid})",
        "body": f"Comments for the app.\n\n<!-- titleid: {titleid} -->", "url": f"https://github.com/o/r/discussions/{number}",
        "locked": locked, "category": {"name": category}, "upvoteCount": likes,
        "comments": {"totalCount": len(replies) if total is None else total, "nodes": list(replies)},
    }


def reply(login, text, date="2026-10-12T10:00:00Z", minimized=False):
    return {"author": {"login": login} if login else None, "createdAt": date, "bodyText": text, "isMinimized": minimized}


def listed(titleid="PPSA01234", **fields):
    return Record(Path(f"{titleid}.json"), record(titleid=titleid, **fields))


class CleanTests(unittest.TestCase):
    def test_plain_single_line_text(self):
        self.assertEqual(comments.clean("Works  great\n\non 12.70!\tThanks"), "Works great on 12.70! Thanks")

    def test_addresses_and_invisible_characters_are_dropped(self):
        self.assertEqual(comments.clean("see https://evil.example/x?y=1 and www.evil.example now"), "see and now")
        self.assertEqual(comments.clean("a‮b​c\x07d"), "abcd")

    def test_long_text_is_cut(self):
        cut = comments.clean("x" * 600)
        self.assertEqual((len(cut), cut[-1]), (comments.MAX_TEXT, "…"))


class ThreadTests(unittest.TestCase):
    def test_reads_marker_likes_and_latest_comments_newest_first(self):
        replies = [reply("alice", "first", "2026-10-10T00:00:00Z"), reply("troll", "spam"),
                   reply("bob", "hidden", minimized=True), reply(None, "from a deleted account"),
                   reply("carol", "https://only.a.link"), reply("dave", "last", "2026-10-12T00:00:00Z")]
        threads = comments.read_threads(
            [node(7, "PPSA01234", likes=41, replies=replies, total=9), {**node(8, "PPSA01234"), "number": 8},
             {**node(9, "PPSA09999"), "body": "no marker here"}], out_of_scope={"troll"})
        self.assertEqual(list(threads), ["PPSA01234"])
        thread = threads["PPSA01234"]
        self.assertEqual((thread.number, thread.likes, thread.comments), (7, 41, 9))
        self.assertEqual([(c["author"], c["text"]) for c in thread.latest],
                         [("dave", "last"), ("ghost", "from a deleted account"), ("alice", "first")])

    def test_scope_reads_names(self):
        self.assertEqual(comments.read_scope(" @Troll, other\nThird "), {"troll", "other", "third"})


class PlanTests(unittest.TestCase):
    def test_create_rename_withdraw_and_restore(self):
        records = [listed("PPSA01234"), listed("PPSA02222", name="Renamed"), listed("PPSA03333"),
                   Record(Path("PPSA05555.json"), reservation(titleid="PPSA05555"))]
        threads = comments.read_threads([
            node(1, "PPSA02222", title="Old name (PPSA02222)"),
            node(2, "PPSA03333", category=comments.WITHDRAWN, locked=True),
            node(3, "PPSA04444"),
            node(4, "PPSA06666", category=comments.WITHDRAWN, locked=True),
        ])
        actions = comments.plan(records, threads)
        self.assertEqual([(a[0], getattr(a[1], "titleid", None)) for a in actions], [
            ("create", "PPSA01234"), ("rename", "PPSA02222"), ("restore", "PPSA03333"), ("withdraw", "PPSA04444")])
        self.assertEqual(actions[1][2], "Renamed (PPSA02222)")
        self.assertIn("lock discussion #3", comments.describe(actions[3]))

    def test_nothing_to_do_and_a_hand_locked_discussion_stays_locked(self):
        self.assertEqual(comments.plan([listed()], comments.read_threads([node(1, "PPSA01234", locked=True)])), [])

    def test_apply_sends_the_mutations(self):
        calls = []
        github = mock.Mock(graphql=lambda query, variables: calls.append((query, variables)) or {})
        threads = comments.read_threads([node(2, "PPSA03333", category=comments.WITHDRAWN, locked=True), node(3, "PPSA04444")])
        categories = {comments.ACTIVE: "C_active", comments.WITHDRAWN: "C_gone"}
        with mock.patch.object(comments.time, "sleep") as sleep:
            comments.apply([("create", listed("PPSA01234")), ("create", listed("PPSA02222")),
                            ("restore", threads["PPSA03333"]), ("withdraw", threads["PPSA04444"])],
                           github, "R_1", categories)
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual([q for q, _ in calls], [comments.CREATE, comments.CREATE, comments.UPDATE, comments.UNLOCK,
                                                 comments.UPDATE, comments.LOCK])
        self.assertEqual(calls[0][1]["category"], "C_active")
        self.assertIn("<!-- titleid: PPSA01234 -->", calls[0][1]["body"])
        self.assertEqual(calls[4][1], {"id": "D_3", "category": "C_gone"})


    def test_a_refused_action_does_not_hold_up_the_rest(self):
        calls = []
        refuse = {"D_1", "PPSA02222"}

        def graphql(query, variables):
            calls.append((query, variables))
            if variables.get("id") in refuse or variables.get("title", "").endswith("(PPSA02222)"):
                raise comments.GitHubError("Resource not accessible by integration")
            return {}

        threads = comments.read_threads([node(1, "PPSA01111", title="Old name (PPSA01111)"), node(4, "PPSA04444")])
        categories = {comments.ACTIVE: "C_active", comments.WITHDRAWN: "C_gone"}
        with mock.patch.object(comments.time, "sleep"):
            refused = comments.apply([("rename", threads["PPSA01111"], "New name (PPSA01111)"),
                                      ("create", listed("PPSA01234")), ("create", listed("PPSA02222")),
                                      ("create", listed("PPSA03333")), ("withdraw", threads["PPSA04444"])],
                                     mock.Mock(graphql=graphql), "R_1", categories)
        # The rename is refused and the creations go on; once a creation is refused no more are
        # tried, and the withdrawal still happens.
        self.assertEqual([(q, v.get("title") or v.get("id")) for q, v in calls], [
            (comments.UPDATE, "New name (PPSA01111)"), (comments.CREATE, "Example App (PPSA01234)"),
            (comments.CREATE, "Example App (PPSA02222)"), (comments.UPDATE, "D_4"), (comments.LOCK, "D_4")])
        self.assertEqual(len(refused), 2)
        self.assertIn("rename discussion #1", refused[0])
        self.assertIn("Resource not accessible by integration", refused[1])

class PayloadTests(unittest.TestCase):
    def test_index_and_one_file_per_listed_app_with_a_discussion(self):
        threads = comments.read_threads([
            node(7, "PPSA01234", likes=3, replies=[reply("alice", "nice")]),
            node(8, "PPSA02222", category=comments.WITHDRAWN), node(9, "PPSA04444")])
        files = comments.payload([listed("PPSA01234"), listed("PPSA02222"), listed("PPSA03333")], threads)
        self.assertEqual(sorted(files), ["v1/apps/PPSA01234.json", "v1/index.json"])
        self.assertEqual(files["v1/index.json"], {"schema": 1, "apps": {"PPSA01234": {
            "discussion": 7, "url": "https://github.com/o/r/discussions/7", "likes": 3, "comments": 1}}})
        self.assertEqual(files["v1/apps/PPSA01234.json"]["latest"],
                         [{"author": "alice", "date": "2026-10-12T10:00:00Z", "text": "nice"}])


class CommandTests(unittest.TestCase):
    def run_command(self, graphql, *arguments):
        with tempfile.TemporaryDirectory() as tmp:
            apps = Path(tmp) / "apps"
            write_record(apps, record(titleid="PPSA01234"))
            out = Path(tmp) / "out"
            with mock.patch.object(cli, "APPS", apps), mock.patch.object(cli, "GitHub", lambda: mock.Mock(graphql=graphql)), \
                    mock.patch.object(comments.time, "sleep"):
                code = cli.main(["comments", "--repository", "o/r", "--out", str(out), *arguments])
            written = {p.relative_to(out).as_posix(): json.loads(p.read_text(encoding="utf-8"))
                       for p in out.rglob("*.json")} if out.exists() else {}
        return code, written

    def test_does_nothing_until_discussions_are_set_up(self):
        off = {"repository": {"id": "R", "hasDiscussionsEnabled": False, "discussionCategories": {"nodes": []}}}
        self.assertEqual(self.run_command(lambda query, variables: off, "--sync"), (0, {}))
        no_category = {"repository": {"id": "R", "hasDiscussionsEnabled": True,
                                      "discussionCategories": {"nodes": [{"id": "C", "name": "General"}]}}}
        self.assertEqual(self.run_command(lambda query, variables: no_category, "--sync"), (0, {}))

    def test_sync_creates_the_discussion_and_writes_the_files(self):
        state = {"nodes": []}

        def graphql(query, variables):
            if query == comments.SETUP:
                return {"repository": {"id": "R", "hasDiscussionsEnabled": True, "discussionCategories": {"nodes": [
                    {"id": "C1", "name": comments.ACTIVE}, {"id": "C2", "name": comments.WITHDRAWN}]}}}
            if query == comments.LIST:
                return {"repository": {"discussions": {"pageInfo": {"hasNextPage": False, "endCursor": None},
                                                       "nodes": state["nodes"]}}}
            self.assertEqual(query, comments.CREATE)
            state["nodes"] = [node(1, "PPSA01234", likes=2)]
            return {}

        code, written = self.run_command(graphql)
        self.assertEqual((code, written["v1/index.json"]["apps"]), (0, {}))   # without --sync nothing is created

        def refusing(query, variables):
            if query == comments.CREATE:
                raise cli.GitHubError("Something went wrong")
            return graphql(query, variables)

        # A refused creation is a warning, and what exists is still written.
        code, written = self.run_command(refusing, "--sync")
        self.assertEqual((code, written["v1/index.json"]["apps"]), (0, {}))
        code, written = self.run_command(graphql, "--sync")
        self.assertEqual(code, 0)
        self.assertEqual(written["v1/index.json"]["apps"]["PPSA01234"]["likes"], 2)
        self.assertEqual(written["v1/apps/PPSA01234.json"]["titleid"], "PPSA01234")


if __name__ == "__main__":
    unittest.main()
