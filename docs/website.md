# Website

The store at <https://darkxex.github.io/ps5-homebrew-catalog/> is a static site generated from
`apps/` by `python3 -m catalog build` and published to the repository's GitHub Pages site by GitHub
Actions after every merge to `main`. There is no server-side code, database or tracking.

## What the build produces

```text
dist/
├── _headers, _redirects        header and redirect rules (GitHub Pages ignores them)
├── 404.html, robots.txt
├── index.html                  the catalog: Discover, and a section each for apps, games, tools and coming soon
├── tv/                         TV mode: the catalog as a 10-foot interface
├── app/<TITLEID>/              one page per app: download, install steps, sha256
├── api/v1/                     the store API: per-app files, index, versions, PNG icons, signed manifest
├── catalog/v1.json             the older single-file feed
└── assets/                     content-hashed CSS, JS, WebP icons and each app's ambient picture
```

- **One catalog page, as a store front.** `/` opens on **Discover**: a stage
  that shows one app big (the five newest in turn, eight seconds each, or the
  tile under the pointer) over shelves: New in the catalog (apps listed in the
  last thirty days), Recently updated (apps with a release published after
  they were listed, by the release's date), Most liked, one shelf per
  category, Coming soon. Editing a listing, such as a new category or a
  corrected description, doesn't make an app "updated". The tabs in the top bar switch to a section, which is a grid of
  the same tiles. The section, the search and the order live in the URL
  (`?section=games&q=…&sort=updated`), so any view can be linked. The old
  `/list/` and `?view=list` addresses open the catalog. The site used to live
  under `/ps5/`; every `/ps5/…` URL redirects to the same page at the root.
- **Search and order.** The search box (or `/`) finds apps by name, developer,
  title ID or description, across every section. A section is ordered by name
  or by most recently updated.
- **An app's page** is a complete static page: the app over its own colours,
  its facts as chips (version, size, licence, format), a panel with the
  download, the install steps and the SHA-256. Direct links, link previews and
  search engines see everything.
- **Each app's colours come from its icon.** The build takes the icon's two
  main hues and paints a small soft picture from them (96 x 54 pixels), used
  behind the app on the stage, on its tile and on its page, and puts the main
  hue in the stylesheet as that app's accent. This is the picture ProsperoStore
  makes on the console, by the same rules. A grey icon gets the theme's violet.
  It needs Pillow; without it every app gets the theme's own picture.
- **Phones.** The top bar wraps and its tabs scroll sideways, shelves scroll
  with a finger, grids go to two columns and then one, and an app's download
  panel moves up under its name.
- **Updated dates.** Each app shows when its record last changed on `main`,
  taken from the git history of `apps/<TITLEID>.json`. The build deepens a
  shallow clone first so dates stay correct in CI.
- **Release notes.** An app's page shows what its developer wrote on the listed
  GitHub release, read from GitHub at build time (again at most once a day,
  since developers edit them). The text is the developer's and nobody reviews
  it, so only headings, paragraphs and lists are kept: images, links' targets
  and raw HTML are dropped (`catalog/notes.py`). Long notes are cut, with a
  link to the release; a release without notes has no such section.
- **Coming soon.** Title ID reservations appear as cards with the shared
  "Coming soon" picture (`site/shared/coming-soon.png`) in place of an icon,
  and no download; see [Reserving a title ID](submitting.md#reserving-a-title-id).
- Every metadata value is HTML-escaped; descriptions render as plain text.
- Icons are fetched from `icon_url`, resized to 512 px WebP (when Pillow is
  installed) and served from the site, so visitors never hit the original host.
  The deploy job keeps them in a CI cache and fetches an icon again only when its
  copy is older than a day, so a changed picture at the same address shows up
  with the next deploy after that. A broken icon becomes a placeholder with a build warning.
- Search waits for a pause in typing. A shelf shows at most 20 tiles; its
  section shows them all.
- Without JavaScript the catalog page is the plain grid of every app, and every
  app page is complete; the script adds Discover, the sections, search, the
  order and the copy buttons. The pages carry no inline styles or scripts, as
  the content security policy requires.
- **Comments and likes** are the app's GitHub Discussion
  ([how they get there](automation.md#comments-and-likes)). The page's script
  reads them from the `comments-data` branch through raw.githubusercontent.com,
  the one address besides the site itself the content security policy lets it
  fetch from: an app's page has Like and Comment buttons with their counts and
  the latest comments, every tile shows the app's likes and comments (zero
  included), Discover gets a ranked "Most liked" shelf once an app
  has a like, and the sections can be ordered by "Most liked". TV mode shows
  the counts on every tile and in an app's details with its latest comments,
  can order by "Most liked", and shows two QR codes there: one for the app's
  page, to download it, and one for its discussion, to like or comment. They
  are drawn in the page by a bundled library
  ([qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator), MIT);
  no address is sent anywhere to make them. Everything is
  shown as plain text. Writing happens on GitHub, through the link on the page.
  When the files can't be read the page keeps only that link.
- The page of an app withdrawn in the last 30 days redirects to the front page,
  and its API file is replaced by one that says `"status": "withdrawn"`.
  A host can keep serving a file for a while after a deployment drops
  it; the redirect at that address takes over at once.
- The build fails, and the previous deployment stays online, if any record
  is invalid.

## TV mode

`/tv/` is the catalog as a 10-foot interface for a television, driven by a
controller or a TV remote: a rail of sections (All, Apps, Games, Tools, Coming
soon), a grid of large tiles, and a full-screen page per app with the install
steps, the short link to open on a phone, and the SHA-256.

- **Controls.** The PS5 browser turns the controller into keys: the D-pad
  moves, ✕ (Enter) opens, ○ (Escape) goes back, △ (F1) changes the sort and □
  (F2) jumps to the rail. On an app's page, Left and Right step through the
  apps and Up and Down scroll. The TV remote's channel and track keys work too.
  Other browsers get the same controls from a connected gamepad (a DualSense
  over USB or Bluetooth, for example) through the Gamepad API, and the
  keyboard's arrows, Enter and Escape always work.
- **Automatic.** TV browsers are sent to TV mode before the regular page is
  drawn: the PS5 browser and common smart-TV browsers (Tizen, webOS, Android
  TV, Fire TV and others), recognised by their user agent. An app page opens
  the same app in TV mode, and catalog filters carry over.
- **Your choice sticks.** "Exit TV mode" returns to the regular layout and
  remembers it on that browser (`?layout=web`); the header's "TV mode" link
  (`?layout=tv`) goes back to the automatic choice. Both links work on any
  device.
- **Same data, no extra requests.** The build embeds the catalog in the page
  as JSON, and `tv.js` draws it with DOM APIs, so metadata is never parsed as
  HTML. The section, sort and open app live in the URL hash.

TV mode was inspired by [tv4play](https://github.com/ps5-payload-dev/tv4play)
by ps5-payload-dev, a 10-foot web app for the PS5 whose README documents how
the console's browser presents the controller.

## Store API: `api/v1/`

The build publishes the catalog as static JSON for the console store, for apps
that check themselves for updates, and for other clients: one file per app, a
compact index, a version map, PNG icons, and a signed manifest of all of it.
**[Store API](api.md)** is its
specification, including how clients find updates and how the API is versioned.

Besides the records, it carries each release's download size, release date and
content version. They come from GitHub's API and from the `param.json` in the
app's repository; no artifact is downloaded. Each belongs to one exact file, so
it is looked up once and kept in the build's cache next to the icons. An
offline build (`--no-icons`) leaves them `null`.

## Older feed: `catalog/v1.json`

The first feed, kept for clients that already use it. New clients should use
the [store API](api.md).

```json
{
  "schema": 1,
  "name": "PS5 Homebrew Catalog",
  "homepage": "https://darkxex.github.io/ps5-homebrew-catalog/",
  "source": { "repository": "https://github.com/…/ps5-homebrew-catalog", "commit": "<sha>" },
  "apps": [
    { "…all twelve record fields…": "",
      "format": "zip | ffpkg | ffpfsc",
      "updated": "2026-09-28T22:30:46-04:00",
      "page": "https://darkxex.github.io/ps5-homebrew-catalog/app/PPSA01234/",
      "icon": "https://darkxex.github.io/ps5-homebrew-catalog/assets/icon-PPSA01234.<hash>.webp" }
  ],
  "coming_soon": [
    { "…all twelve fields, links and sha256 null…": "", "updated": "…", "page": "…", "icon": "…" }
  ]
}
```

The feed is minified. `apps` holds only installable releases; reservations are
listed separately in `coming_soon`. Both are sorted by title ID. `updated` is
`null` when the history isn't available. The feed is served with
`Access-Control-Allow-Origin: *` and a five-minute cache.

## Design

The site uses the **Farlight** theme: ProsperoStore's own look, so the catalog
looks the same on the web and on the console. From the store it takes the
colours (a warm white for all words, a deep indigo, a violet mid tone and one
gold for calls to action), the faces (Inter, and Montserrat for headlines), the
measurements (the stylesheet's unit is one pixel of the store's 1920 x 1080
canvas), the stage, shelves and tiles of its Discover screen, and the glass
panel of its app page. Its templates, stylesheet and script are in
`site/themes/farlight/`.

The earlier **Holo** theme (every app a holographic trading card, with a list
view and format filters) is still in `site/themes/holo/` and builds with
`--theme holo`; `site/shared/` holds its script and the images both themes
use. A theme may bring its own `app.js` and `favicon.svg`; otherwise the
shared ones are used.

## Build and preview locally

```sh
pip install -r requirements.txt            # optional: WebP icons
python3 -m catalog build                   # writes dist/
python3 -m http.server --directory dist 8000
```

Open <http://localhost:8000/>. Useful options: `--no-icons` (offline,
placeholders, and no release facts in the API), `--base /path/` (serve under a sub-path), `--site-url` (origin used in the
feed and canonical links), `--out`.

## Deployment

Every merge to `main` (or a run started by hand: Actions > CI > Run workflow on
`main`) runs the tests and
verifies the changed records, then the **Build and sign the website** job builds
the site for `https://darkxex.github.io/ps5-homebrew-catalog/`, signs the store API with `CATALOG_SIGNING_KEY` (a
secret of the environment still named `cloudflare-pages`, which accepts only
`main`), and the **Publish the website to GitHub Pages** job publishes it. A
broken or unverified catalog is never published, and a failed run leaves the
last good site online.

One-time setup, by the repository's owner:

- **Settings → Pages:** source **GitHub Actions**.
- **Settings → Environments:** `github-pages` allows deployments from `main`;
  the environment that holds `CATALOG_SIGNING_KEY` allows only `main`.

GitHub Pages ignores `_headers` and `_redirects`: the site has no custom
security headers or cache rules there, and a withdrawn app's page answers with
the 404 page.
