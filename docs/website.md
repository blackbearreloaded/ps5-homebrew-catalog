# Website

The store at <https://homebrew.page/> is a static site generated from
`apps/` by `python3 -m catalog build` and deployed to Cloudflare Pages by GitHub
Actions on every push to `main`. There is no server-side code, database or tracking.

## What the build produces

```text
dist/
├── _headers, _redirects        Cloudflare Pages security headers, caching, redirects
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
  tile under the pointer) over shelves: New and updated, Apps, Games, Tools,
  Coming soon. The tabs in the top bar switch to a section, which is a grid of
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
  The deploy job keeps them in a CI cache, so each icon URL is fetched only once
  across deploys. A broken icon becomes a placeholder with a build warning.
- Search waits for a pause in typing. A shelf shows at most 20 tiles; its
  section shows them all.
- Without JavaScript the catalog page is the plain grid of every app, and every
  app page is complete; the script adds Discover, the sections, search, the
  order and the copy buttons. The pages carry no inline styles or scripts, as
  the content security policy requires.
- The build fails, and Cloudflare keeps the previous deployment, if any record
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
  "homepage": "https://homebrew.page/",
  "source": { "repository": "https://github.com/…/ps5-homebrew-catalog", "commit": "<sha>" },
  "apps": [
    { "…all eleven record fields…": "",
      "format": "zip | ffpkg | ffpfsc",
      "updated": "2026-09-28T22:30:46-04:00",
      "page": "https://homebrew.page/app/PPSA01234/",
      "icon": "https://homebrew.page/assets/icon-PPSA01234.<hash>.webp" }
  ],
  "coming_soon": [
    { "…all eleven fields, links and sha256 null…": "", "updated": "…", "page": "…", "icon": "…" }
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

The **Deploy website to Cloudflare Pages** job in [CI](../.github/workflows/ci.yml)
builds `dist/` and uploads it with Cloudflare's Direct Upload (`wrangler pages
deploy`). It runs only on `main`, after the tests and the record verification
pass, so a broken or unverified catalog is never published. Cloudflare has no
access to this repository.

### What stays private

- **Nothing about the Cloudflare account is in the repository.** The API token
  and account ID are GitHub encrypted secrets. They aren't stored in files or
  history, they're masked in logs, and pull requests and forks can't read them.
- **The secrets reach only the deploy job.** They're environment secrets of
  `cloudflare-pages`, and that environment accepts only the `main` branch. The
  pull request workflows never use it.
- **Public logs stay clean.** Actions logs of a public repository are
  world-readable, so the deploy step keeps wrangler's output out of the log and
  prints only success, or on failure the error codes and messages with account
  IDs, emails, URLs and quoted values masked (`catalog/redact.py`). Wrangler
  telemetry is off.
- **The token can do one thing.** It can edit Cloudflare Pages in one account.
  It can't read DNS, billing or anything else, and you can revoke it at any time.
- **The site reveals nothing about the account.** Visitors see `homebrew.page`
  and the project's `*.pages.dev` name. Keep WHOIS privacy on for the domain;
  Cloudflare Registrar redacts owner details by default.

### API mirror

After the site is uploaded, the same job builds the store API once more for
this repository's GitHub Pages address, signs it, and a second job publishes
it there. It exists for consoles whose network blocks the main site
([Store API: mirror](api.md#mirror)). Only the API is published; the mirror's
front page is one static file, `site/mirror/index.html`. GitHub Pages must be
enabled for the repository with "GitHub Actions" as its source.

### Fallback deploy

When GitHub's hosted runners are down, merges reach `main` but the site stays
on the previous build. [Deploy fallback](../.github/workflows/deploy-fallback.yml)
runs the same deploy on a machine the maintainer controls.

- **It never runs by itself.** Its only trigger is a manual start, the job
  requires the repository owner and `main`, and it targets a runner labelled
  `catalog-fallback`. No pull request, push or schedule can reach that runner.
- **No runner is kept registered.** The maintainer registers one for a single
  job (`config.sh --ephemeral --labels catalog-fallback`), starts it, runs the
  workflow, and the runner unregisters itself when the job ends. Never install
  it as a service: a standing self-hosted runner on a public repository is the
  risk, not this file.
- **The secrets stay in GitHub** and reach the job through the
  `cloudflare-pages` environment, as in the normal deploy.
- **The machine needs** Python 3 with Pillow and `cryptography`, `git` and
  `curl`; Node is fetched by the workflow.

```sh
cd ~/actions-runner
./config.sh --unattended --ephemeral --replace --name fallback --labels catalog-fallback \
    --url https://github.com/<owner>/ps5-homebrew-catalog \
    --token "$(gh api -X POST repos/<owner>/ps5-homebrew-catalog/actions/runners/registration-token -q .token)"
./run.sh &                                   # "Listening for Jobs"
gh workflow run deploy-fallback.yml --repo <owner>/ps5-homebrew-catalog
```

The workflow repeats the deploy job of `ci.yml`; change both together.

### One-time setup

1. **No project to create by hand.** The deploy job creates the Pages project
   (named after `CLOUDFLARE_PAGES_PROJECT`) on its first run. Don't use the
   dashboard's "Connect to Git", which installs Cloudflare's GitHub app and
   links the accounts.
2. **Create an API token.** Go to **My Profile → API Tokens → Create Token →
   Custom token**:
   - Permissions: **Account → Cloudflare Pages → Edit** (nothing else)
   - Account resources: **Include → your account**
   - TTL: optional; for example one year, with a reminder to rotate it
3. **Find the account ID.** It's shown in the Workers & Pages overview sidebar,
   and in the dashboard URL.
4. **Add them to GitHub**, not to the repository files. In the repository's
   **Settings → Environments → New environment**, create `cloudflare-pages`:
   - **Deployment branches and tags:** Selected branches → `main`
   - **Environment secrets:** `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`
5. **Switch deployment on.** Under **Settings → Secrets and variables → Actions
   → Variables**, add the repository variable `CLOUDFLARE_PAGES_PROJECT` =
   `homebrew-page`. The deploy job is skipped while this variable is missing.
6. **Deploy.** Go to **Actions → CI → Run workflow** on `main`, or push. Check
   `https://homebrew-page.pages.dev/`. If the name is taken on `pages.dev`,
   Cloudflare adds a suffix; the project's page in the dashboard shows the address.
7. **Connect the domain.** In the Pages project, go to **Custom domains → Set up
   a domain →** `homebrew.page`. An apex domain needs its DNS on Cloudflare; the
   certificate and records are then created automatically.

After that, every merge to `main` goes live within a couple of minutes. A failed
build or upload leaves the last good deployment online. To stop deployments,
delete the variable; to cut access entirely, revoke the token.
