import json
import tempfile
import unittest
from pathlib import Path

from catalog import news
from catalog.report import Report


class NewsTests(unittest.TestCase):
    def load(self, value):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / news.FILE
            path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
            report = Report()
            return news.load(path, report), report

    def test_items_come_out_newest_first_and_trimmed(self):
        items, report = self.load([
            {"id": "older", "date": "2026-10-01T09:00:00Z", "title": " Older ", "body": "One.\n\nTwo.\n"},
            {"id": "newer", "date": "2026-10-11T09:00:00Z", "title": "Newer", "body": "Text."}])
        self.assertFalse(report.failed)
        self.assertEqual([item["id"] for item in items], ["newer", "older"])
        self.assertEqual((items[1]["title"], items[1]["body"]), ("Older", "One.\n\nTwo."))

    def test_a_missing_file_is_no_news(self):
        report = Report()
        self.assertEqual(news.load(Path("/nonexistent/news.json"), report), [])
        self.assertFalse(report.failed)

    def test_bad_items_are_errors(self):
        good = {"id": "a", "date": "2026-10-11T09:00:00Z", "title": "T", "body": "B"}
        for bad in ({**good, "id": "Has Spaces"}, {**good, "date": "11 October"}, {**good, "title": ""},
                    {**good, "title": "two\nlines"}, {**good, "body": "x" * 2001}, {**good, "extra": "field"},
                    {k: v for k, v in good.items() if k != "body"}, "text"):
            items, report = self.load([bad])
            self.assertEqual(items, [], bad)
            self.assertTrue(report.failed, bad)
        items, report = self.load([good, good])       # the same id twice
        self.assertTrue(report.failed)
        for whole in ("{}", "not json"):
            items, report = self.load(whole)
            self.assertTrue(report.failed, whole)


if __name__ == "__main__":
    unittest.main()
