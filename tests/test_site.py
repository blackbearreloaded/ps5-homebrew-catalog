import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from catalog.report import Report
from catalog import site
from catalog.site import THEMES, build_site

try:
    import PIL  # noqa: F401
    HAVE_PILLOW = True
except ImportError:
    HAVE_PILLOW = False

from helpers import record, reservation, write_record


class SiteBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.apps = root / "apps"
        self.out = root / "dist"
        write_record(self.apps, record(name="Evil <script>alert(1)</script>",
                                       description='Quote " and <b>tags</b> & ampersands.'))
        write_record(self.apps, record(
            titleid="PPSA04321", name="Image Game", kind="game", version="2", sha256="b" * 64,
            artifact_url="https://github.com/example/example-app/releases/download/2/PPSA04321.ffpkg"))
        write_record(self.apps, reservation())

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def icon_png():
        """A 64 x 64 plain red PNG."""
        import io
        from PIL import Image
        output = io.BytesIO()
        Image.new("RGB", (64, 64), (255, 0, 0)).save(output, "PNG")
        return output.getvalue()

    def build(self, **options):
        report = Report()
        with mock.patch.dict("os.environ", {"CF_PAGES_COMMIT_SHA": "abc1234def"}):
            options.setdefault("fetch_icons", False)
            count = build_site(self.out, self.apps, report, **options)
        return count, report

    def test_builds_pages_feed_and_config(self):
        count, report = self.build()
        self.assertEqual((count, report.failed), (3, False))
        root = self.out
        for path in ("index.html", "app/PPSA01234/index.html", "app/PPSA04321/index.html",
                     "app/PPSA05555/index.html",
                     "catalog/v1.json", "favicon.svg", "404.html", "tv/index.html"):
            self.assertTrue((root / path).is_file(), path)
        for path in ("_headers", "_redirects", "404.html", "robots.txt"):
            self.assertTrue((self.out / path).is_file(), path)
        redirects = (self.out / "_redirects").read_text(encoding="utf-8")
        self.assertNotIn("/ / 302", redirects)
        self.assertIn("/list/ /?view=list 301", redirects)
        # Links from when the site lived under /ps5/ keep working.
        self.assertIn("/ps5/list/ /?view=list 301", redirects)
        self.assertIn("/ps5 / 301", redirects)
        self.assertIn("/ps5/* /:splat 301", redirects)
        self.assertFalse((root / "list").exists())

    def test_footer_shows_when_the_catalog_last_changed(self):
        with mock.patch.object(site, "source_commit_time", lambda commit: "2026-10-03T04:05:00Z"):
            self.build()
        page = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn('abc1234</a> · last updated <time datetime="2026-10-03T04:05:00Z">3 Oct 2026, 04:05 UTC</time>.',
                      page)
        self.assertIn('Maintained by <a href="https://github.com/blackbearreloaded">BlackBearReloaded</a> · Built from', page)
        self.assertIn('<a class="notice"', page)
        self.assertIn('href="https://github.com/blackbearreloaded/ProsperoStore"', page)
        tv = (self.out / "tv" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<p class="tv-credit">Maintained by BlackBearReloaded · Built from abc1234 · last updated '
                      '<time datetime="2026-10-03T04:05:00Z">3 Oct 2026, 04:05 UTC</time></p>', tv)
        self.assertEqual(site._commit_time_html(None), "")

    def test_metadata_is_escaped(self):
        self.build()
        for page in (self.out / "index.html", self.out / "app" / "PPSA01234" / "index.html"):
            html = page.read_text(encoding="utf-8")
            self.assertNotIn("<script>alert", html)
            self.assertNotIn("<b>tags</b>", html)
            self.assertIn("&lt;script&gt;", html)

    def test_version_label(self):
        from catalog.site import version_label
        self.assertEqual(version_label("01.000.005"), "v01.000.005")
        self.assertEqual(version_label("vk-285-113"), "vk-285-113")
        self.assertEqual(version_label("v1.0"), "v1.0")

    def test_api(self):
        self.build()
        api = self.out / "api" / "v1"
        app = json.loads((api / "apps" / "PPSA01234.json").read_text(encoding="utf-8"))
        self.assertEqual((app["schema"], app["status"], app["format"], app["artifact_name"], app["tag"]),
                         (3, "available", "zip", "PPSA01234.zip", "01.000.000"))
        self.assertEqual(app["sha256"], "a" * 64)                      # every record field is there
        self.assertEqual(app["page"], "https://homebrew.page/app/PPSA01234/")
        self.assertEqual(app["release_url"], "https://github.com/example/example-app/releases/tag/01.000.000")
        # An offline build knows no release facts and has no icons; the fields are present and null.
        self.assertEqual([app[k] for k in ("size", "released", "prerelease", "content_version", "icon", "icon_small",
                                           "icon_hash", "release_notes", "release_notes_truncated")], [None] * 9)
        self.assertNotIn("notes-title", (self.out / "app" / "PPSA01234" / "index.html").read_text(encoding="utf-8"))
        soon = json.loads((api / "apps" / "PPSA05555.json").read_text(encoding="utf-8"))
        self.assertEqual((soon["status"], soon["artifact_url"], soon["format"], soon["tag"]),
                         ("coming_soon", None, None, None))
        index = json.loads((api / "index.json").read_text(encoding="utf-8"))
        self.assertEqual((index["schema"], index["count"], index["commit"]), (3, 3, "abc1234def"))
        self.assertEqual([a["titleid"] for a in index["apps"]], ["PPSA01234", "PPSA04321", "PPSA05555"])
        self.assertNotIn("description", index["apps"][0])
        versions = json.loads((api / "versions.json").read_text(encoding="utf-8"))
        self.assertEqual(versions, {"schema": 3, "apps": {
            "PPSA01234": {"content_version": None, "version": "01.000.000"},
            "PPSA04321": {"content_version": None, "version": "2"}}})
        self.assertIn("/api/*\n  Access-Control-Allow-Origin: *", (self.out / "_headers").read_text(encoding="utf-8"))
        self.assertIn("/api/*/manifest.sig\n  Content-Type: application/octet-stream",
                      (self.out / "_headers").read_text(encoding="utf-8"))
        # The manifest names every JSON file of the API by its hash; the build itself never signs.
        import hashlib
        manifest = json.loads((api / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(manifest["files"]), ["apps/PPSA01234.json", "apps/PPSA04321.json", "apps/PPSA05555.json",
                                                     "index.json", "versions.json"])
        self.assertEqual(manifest["files"]["index.json"], hashlib.sha256((api / "index.json").read_bytes()).hexdigest())
        self.assertEqual((manifest["schema"], manifest["commit"]), (3, "abc1234def"))
        self.assertIsInstance(manifest["sequence"], int)
        self.assertFalse((api / "manifest.sig").exists())

    def test_a_mirror_of_the_api_links_pages_to_the_website(self):
        self.build(site_url="https://owner.github.io", base="/catalog/", pages_url="https://homebrew.page/")
        app = json.loads((self.out / "catalog" / "api" / "v1" / "apps" / "PPSA01234.json").read_text(encoding="utf-8"))
        self.assertEqual(app["page"], "https://homebrew.page/app/PPSA01234/")
        index = json.loads((self.out / "catalog" / "api" / "v1" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["count"], 3)

    def test_safety_labels_come_from_scan_summaries(self):
        from catalog import facts as facts_module
        from catalog import scan as scan_module
        sha = "a" * 64
        summary = {"scanner": scan_module.SCANNER, "sha256": sha, "titleid": "PPSA01234", "sandbox": "leaves",
                   "routes": ["payload"], "payloads": [{"path": "PPSA01234/helper.elf", "sha256": "b" * 64}],
                   "network": True, "attested": False, "workflow": None}
        scans = self.out.parent / "scans"
        scans.mkdir()
        (scans / f"{sha}.json").write_text(json.dumps(summary), encoding="utf-8")
        (scans / f"{'c' * 64}.json").write_text("not json", encoding="utf-8")
        known = facts_module.Facts(uploader="actions")
        with mock.patch.object(facts_module, "cached", lambda record, github, cache, fetch=None: (known, None)):
            self.build(scans=scans)
        api = self.out / "api" / "v1"
        app = json.loads((api / "apps" / "PPSA01234.json").read_text(encoding="utf-8"))
        self.assertEqual(app["safety"], {"sandbox": "leaves", "routes": ["payload"], "helpers": 1,
                                         "helpers_unapproved": 1, "network": True, "build": "workflow",
                                         "build_workflow": None})
        index = json.loads((api / "index.json").read_text(encoding="utf-8"))
        self.assertEqual([a["sandbox"] for a in index["apps"]], ["leaves", None, None])
        page = (self.out / "app" / "PPSA01234" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<h2 id="safety-title">Safety</h2>', page)
        self.assertIn("Leaves the sandbox", page)
        self.assertIn("1 helper(s) not reviewed", page)
        self.assertIn("Released by a workflow", page)
        # Without summaries nothing is claimed.
        self.build()
        app = json.loads((self.out / "api" / "v1" / "apps" / "PPSA01234.json").read_text(encoding="utf-8"))
        self.assertIsNone(app["safety"])
        self.assertNotIn("safety-title", (self.out / "app" / "PPSA01234" / "index.html").read_text(encoding="utf-8"))

    def test_api_release_facts_and_icons(self):
        from catalog import facts as facts_module
        known = facts_module.Facts(size=4096, released="2026-09-01T10:00:00Z", prerelease=False,
                                   content_version="01.000.000", param_path="sce_sys/param.json",
                                   notes="## Fixed\n- <b>Menus</b> open [faster](https://example.com) "
                                         "<script>alert(1)</script>\n\n**Full Changelog**: https://x/y")
        png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + (512).to_bytes(4, "big") * 2
        with mock.patch.object(site, "_icon", lambda url, cache: (png, "png", png)), \
                mock.patch.object(site, "png_icons", lambda data: {512: b"large", 256: b"small"}), \
                mock.patch.object(facts_module, "cached", lambda record, github, cache, fetch=None:
                                  (facts_module.Facts(), None) if record.reserved else (known, None)):
            self.build(fetch_icons=True, github=object())
        api = self.out / "api" / "v1"
        app = json.loads((api / "apps" / "PPSA01234.json").read_text(encoding="utf-8"))
        self.assertEqual((app["size"], app["released"], app["prerelease"], app["content_version"]),
                         (4096, "2026-09-01T10:00:00Z", False, "01.000.000"))
        self.assertEqual((app["release_notes"], app["release_notes_truncated"]),
                         ("Fixed\n- Menus open faster alert(1)", False))
        page = (self.out / "app" / "PPSA01234" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<h2 id="notes-title">Release notes</h2>', page)
        self.assertIn("<li>Menus open faster alert(1)</li>", page)
        self.assertNotIn("<script>alert", page)
        self.assertIn('rel="nofollow">See this release on GitHub</a>', page)
        # An icon's address changes with the picture, so no cache can answer it with an older one.
        import hashlib
        fingerprint = hashlib.sha256(png).hexdigest()[:16]
        self.assertEqual(app["icon"], f"https://homebrew.page/api/v1/icons/PPSA01234.png?v={fingerprint}")
        self.assertEqual(app["icon_small"], f"https://homebrew.page/api/v1/icons/PPSA01234-256.png?v={fingerprint}")
        self.assertEqual((api / "icons" / "PPSA01234-256.png").read_bytes(), b"small")
        # The fingerprint is of the developer's image, so it changes only when that image does.
        import hashlib
        self.assertEqual(app["icon_hash"], hashlib.sha256(png).hexdigest()[:16])
        index = json.loads((api / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["apps"][0]["icon_hash"], app["icon_hash"])
        self.assertIsNone(index["apps"][2]["icon_hash"])               # the reservation has no icon
        versions = json.loads((api / "versions.json").read_text(encoding="utf-8"))
        self.assertEqual(versions["apps"]["PPSA01234"], {"content_version": "01.000.000", "version": "01.000.000"})

    def test_tv_mode(self):
        self.build()
        html = (self.out / "tv" / "index.html").read_text(encoding="utf-8")
        # The metadata is data for tv.js; no value can close the JSON <script> element.
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("</script>alert", html)
        raw = html.split('<script type="application/json" id="tv-data">', 1)[1].split("</script>", 1)[0]
        data = json.loads(raw)
        by_id = {a["titleid"]: a for a in data["apps"]}
        self.assertEqual(by_id["PPSA01234"]["name"], "Evil <script>alert(1)</script>")
        self.assertEqual(by_id["PPSA01234"]["short_url"], "homebrew.page/app/PPSA01234/")
        self.assertTrue(by_id["PPSA01234"]["steps"][0].startswith("Download PPSA01234.zip"))
        self.assertTrue(by_id["PPSA05555"]["soon"])
        self.assertNotIn("sha256", by_id["PPSA05555"])
        self.assertIn('data-kind="soon"', html)
        self.assertIn('href="/tv/?layout=tv"', (self.out / "index.html").read_text(encoding="utf-8"))
        self.assertIn('href="/?layout=web"', html)

    def test_feed(self):
        self.build()
        feed = json.loads((self.out / "catalog" / "v1.json").read_text(encoding="utf-8"))
        self.assertEqual(feed["schema"], 1)
        self.assertEqual(feed["source"]["commit"], "abc1234def")
        self.assertEqual([a["titleid"] for a in feed["apps"]], ["PPSA01234", "PPSA04321"])
        self.assertEqual([a["format"] for a in feed["apps"]], ["zip", "ffpkg"])
        self.assertTrue(feed["apps"][0]["page"].endswith("homebrew.page/app/PPSA01234/"))
        self.assertEqual([a["titleid"] for a in feed["coming_soon"]], ["PPSA05555"])
        self.assertIsNone(feed["coming_soon"][0]["artifact_url"])
        self.assertIsNone(feed["coming_soon"][0]["source_repo"])

    def test_reservation_pages(self):
        self.build()
        root = self.out
        page = (root / "app" / "PPSA05555" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Not released yet", page)
        self.assertNotIn("rel=\"nofollow\"", page)
        self.assertNotIn("None", page)
        html = (root / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('data-status="soon"'), 1)
        self.assertIn('class="tile tile--soon', html)
        self.assertIn('data-status="available"', html)

    def test_catalog_page_is_the_store_front(self):
        self.build()
        html = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('class="tile-item"'), 3)
        for hook in ("data-tabs", "data-stage", "data-shelves", "data-tiles", "data-search", "data-sort",
                     'data-section="soon"', 'data-base="/"'):
            self.assertIn(hook, html)
        # The content security policy allows no inline styles: colours come from the stylesheet.
        for page in self.out.rglob("*.html"):
            self.assertNotIn(" style=", page.read_text(encoding="utf-8"), page)

    def test_sizes_are_worded_as_people_say_them(self):
        self.assertEqual((site.size_label(38_797_312), site.size_label(1_500_000), site.size_label(None)),
                         ("37 MB", "1.4 MB", ""))

    def test_a_build_without_pillow_uses_the_themes_own_picture(self):
        with mock.patch.object(site, "make_ambient", lambda icon: None):
            self.build()
        html = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertEqual(len(list((self.out / "assets").glob("ambient.*.png"))), 1)
        self.assertIn('data-accent="#42358f"', html)

    @unittest.skipUnless(HAVE_PILLOW, "needs Pillow")
    def test_each_app_gets_its_picture_and_colour(self):
        png = self.icon_png()
        with mock.patch.object(site, "_icon", lambda url, cache: (png, "png", png)):
            self.build(fetch_icons=True)
        html = (self.out / "index.html").read_text(encoding="utf-8")
        pictures = sorted(path.name for path in (self.out / "assets").glob("ambient-*.png"))
        self.assertEqual([name.split(".")[0] for name in pictures],
                         ["ambient-PPSA01234", "ambient-PPSA04321", "ambient-PPSA05555"])
        self.assertIn(f'src="/assets/{pictures[0]}"', html)
        css = next((self.out / "assets").glob("farlight.*.css")).read_text(encoding="utf-8")
        # The test icon is plain red; the reservation takes its colour from the shared picture.
        self.assertIn(".tone-PPSA01234{--tone:#ff0000}", css)
        self.assertRegex(css, r"\.tone-PPSA05555\{--tone:#[0-9a-f]{6}\}")
        self.assertIn('data-accent="#ff0000"', html)
        # A grey icon, or none, gets the theme's own violet.
        self.assertEqual(site.make_ambient(None)[1], "#42358f")

    def test_holo_catalog_page_holds_both_views_and_filters(self):
        self.build(theme="holo")
        html = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('class="lrow '), 3)
        self.assertEqual(html.count('class="card-item"'), 3)
        self.assertEqual(html.count("data-grid"), 2)
        for hook in ("data-search", "data-status-filter", "data-format-filter", "data-sort",
                     'data-view-button="cards"', 'data-view-button="list"', 'data-base="/"'):
            self.assertIn(hook, html)

    def test_feed_is_minified(self):
        self.build()
        text = (self.out / "catalog" / "v1.json").read_text(encoding="utf-8")
        self.assertEqual(text.count("\n"), 1)

    def test_install_steps_follow_format(self):
        self.build()
        zip_page = (self.out / "app" / "PPSA01234" / "index.html").read_text(encoding="utf-8")
        image_page = (self.out / "app" / "PPSA04321" / "index.html").read_text(encoding="utf-8")
        self.assertIn("extract it", zip_page)
        self.assertIn("Copy the file as-is", image_page)

    def test_every_theme_builds(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                count, report = self.build(theme=theme)
                self.assertEqual(count, 3)
                html = (self.out / "index.html").read_text(encoding="utf-8")
                self.assertNotIn("$", html.replace("$ ", ""))

    def test_invalid_catalog_builds_nothing(self):
        write_record(self.apps, record(titleid="PPSA05555", name="Broken", sha256="nope"))
        count, report = self.build()
        self.assertTrue(report.failed)
        self.assertFalse(self.out.exists())

    def test_refuses_to_replace_foreign_directory(self):
        self.out.mkdir()
        (self.out / "keep.txt").write_text("mine", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.build()
        self.assertTrue((self.out / "keep.txt").exists())


class IconCacheTests(unittest.TestCase):
    PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + (512).to_bytes(4, "big") * 2)

    def test_icons_are_fetched_once_and_pruned(self):
        from catalog import site
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            apps, cache = root / "apps", root / "cache"
            write_record(apps, record())
            fetches = []

            def fake_fetch(url, limit):
                fetches.append(url)
                return self.PNG

            with mock.patch.object(site.artifacts, "fetch_small", fake_fetch), \
                    mock.patch.object(site, "process_icon", lambda data: (data, "png")):
                for n in range(2):
                    site.build_site(root / f"out{n}", apps, Report(), icon_cache=cache)
                self.assertEqual(len(fetches), 1)
                self.assertEqual(len(list(cache.glob("*.img"))), 1)
                write_record(apps, record(icon_url="https://example.com/new.png"))
                site.build_site(root / "out3", apps, Report(), icon_cache=cache)
                self.assertEqual(len(fetches), 2)
                self.assertEqual(len(list(cache.glob("*.img"))), 1)


if __name__ == "__main__":
    unittest.main()
