/* Farlight: the catalog's pages behaving as ProsperoStore does.

   Discover is a stage that shows one app big (the featured ones in turn, or
   the tile under the pointer) over shelves; the other sections are a grid;
   one gold line glides under the section in view. Without this script the
   page is the plain grid of every app. No inline styles or handlers: the
   site's content security policy allows neither. */

// Layout switch. It runs while <head> is parsed, so a TV never draws this page:
// TV browsers (the PS5's included) are sent to TV mode, which a controller can
// drive. `?layout=web` keeps this layout from then on (TV mode's "Exit" link
// sets it); `?layout=tv`, used by the TV mode links, returns to automatic choice.
(function () {
  "use strict";
  var TV_BROWSER = /PlayStation 5|SMART-TV|SmartTV|Tizen|Web0S|WebOS|NetCast|BRAVIA|Android TV|GoogleTV|HbbTV|CrKey|AFT[A-Z]/i;
  var KEY = "catalog-layout";
  function stored(value) { // read, or write when value is given (null removes); storage may be blocked
    try {
      if (value === undefined) return window.localStorage.getItem(KEY);
      if (value === null) window.localStorage.removeItem(KEY); else window.localStorage.setItem(KEY, value);
    } catch (error) { /* private mode or disabled storage */ }
    return null;
  }
  try {
    var params = new URLSearchParams(window.location.search);
    var forced = params.get("layout");
    if (forced === "web") stored("web");
    if (forced === "tv") stored(null);
    if (forced) {
      params.delete("layout");
      var rest = params.toString();
      window.history.replaceState(window.history.state, "", window.location.pathname + (rest ? "?" + rest : "") + window.location.hash);
    }
    var tv = forced ? forced === "tv" : stored() !== "web" && TV_BROWSER.test(navigator.userAgent);
    var script = document.currentScript;
    if (!tv || !script) return;
    var base = new URL(script.src, window.location.href).pathname.replace(/assets\/[^/]*$/, "");
    var path = window.location.pathname;
    var app = path.slice(base.length).match(/^app\/([A-Z]{4}[0-9]{5})\/?$/);
    var state = new URLSearchParams();
    if (app) state.set("app", app[1]);
    else if (path === base || path === base + "index.html") {
      var kinds = { apps: "app", games: "game", tools: "tool", soon: "soon" };
      if (kinds[params.get("section")]) state.set("kind", kinds[params.get("section")]);
      if (/^[a-z-]+$/.test(params.get("category") || "")) state.set("kind", "cat:" + params.get("category"));
      if (params.get("sort") === "updated") state.set("sort", "updated");
    } else return; // other pages (404) stay as they are
    var hash = state.toString();
    window.location.replace(base + "tv/" + (hash ? "#" + hash : ""));
  } catch (error) { /* no URL API: keep this layout */ }
})();

(function () {
  "use strict";

  var root = document.documentElement;
  root.classList.add("js");

  var SECTIONS = {
    discover: { title: "Discover" },
    apps: { title: "Apps", kind: "app" },
    games: { title: "Games", kind: "game" },
    tools: { title: "Tools", kind: "tool" },
    soon: { title: "Coming soon", soon: true }
  };
  var BANNER_SECONDS = 8;
  var FEATURED = 5;
  var NEW_AND_UPDATED = 12;
  var SHELF_TILES = 20; // a shelf is a taste; the section has them all
  var MOST_LIKED = 10;

  var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function $(selector, scope) { return (scope || document).querySelector(selector); }
  function $$(selector, scope) { return Array.prototype.slice.call((scope || document).querySelectorAll(selector)); }

  function setTint(colour) {
    if (/^#[0-9a-f]{6}$/i.test(colour || "")) root.style.setProperty("--tint", colour);
  }

  function copyButtons() {
    $$("[data-copy]").forEach(function (button) {
      button.addEventListener("click", function () {
        var text = button.getAttribute("data-copy");
        var done = function () {
          button.textContent = "Copied";
          button.classList.add("is-done");
          setTimeout(function () { button.textContent = "Copy"; button.classList.remove("is-done"); }, 1600);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () {});
      });
    });
  }

  /* ---- Likes and comments: read from the catalog's comments files, shown as plain text ---- */

  function commentsFile(path, done) {
    var from = document.body.getAttribute("data-comments");
    if (!from || !window.fetch) return;
    window.fetch(from + path, { credentials: "omit" }).then(function (answer) {
      return answer.ok ? answer.json() : null;
    }).then(function (data) {
      if (data && data.schema === 1) done(data);
    }).catch(function () { /* unreachable or malformed: the page stays as it was built */ });
  }

  /* ---- The top bar: the sections and the line under the one in view ---- */

  function moveLine(section) {
    var line = $("[data-tab-line]");
    var tabs = $("[data-tabs]");
    if (!line || !tabs) return;
    var current = null;
    $$(".tab", tabs).forEach(function (tab) {
      var on = tab.getAttribute("data-section") === section;
      tab.classList.toggle("is-current", on);
      if (on) { tab.setAttribute("aria-current", "page"); current = tab; } else tab.removeAttribute("aria-current");
    });
    if (!current) { line.classList.remove("is-shown"); return; }
    // The line is inset from the word's box, as in the store.
    var inset = Math.min(18, current.offsetWidth * 0.18);
    line.style.width = Math.max(8, current.offsetWidth - 2 * inset) + "px";
    line.style.transform = "translateX(" + (current.offsetLeft + inset) + "px)";
    line.classList.add("is-shown");
  }

  /* ---- The home page ---- */

  function home() {
    var body = document.body;
    var base = body.getAttribute("data-base") || "/";
    var list = $("[data-tiles]");
    var items = $$("[data-app]", list);
    var apps = items.map(function (item) {
      return {
        item: item,
        id: item.getAttribute("data-titleid"),
        name: item.getAttribute("data-title"),
        sortName: item.getAttribute("data-name"),
        author: item.getAttribute("data-by"),
        kind: item.getAttribute("data-app-kind"),
        kindLabel: item.getAttribute("data-kind-label"),
        category: item.getAttribute("data-category") || "",
        categoryLabel: item.getAttribute("data-category-label") || "",
        categoryRank: Number(item.getAttribute("data-category-rank")) || 0,
        soon: item.getAttribute("data-status") === "soon",
        updated: item.getAttribute("data-updated") || "",
        text: (item.getAttribute("data-search-text") || "").toLowerCase(),
        url: item.getAttribute("data-url"),
        icon: item.getAttribute("data-icon"),
        ambient: item.getAttribute("data-ambient"),
        accent: item.getAttribute("data-accent"),
        description: item.getAttribute("data-description"),
        version: item.getAttribute("data-version"),
        size: item.getAttribute("data-size"),
        likes: 0,
        comments: 0
      };
    });
    var byName = function (a, b) { return a.sortName < b.sortName ? -1 : a.sortName > b.sortName ? 1 : 0; };
    var byUpdated = function (a, b) { return a.updated < b.updated ? 1 : a.updated > b.updated ? -1 : byName(a, b); };
    var byLikes = function (a, b) { return b.likes - a.likes || byName(a, b); };
    var ORDERS = { name: { label: "Name", by: byName }, updated: { label: "Recently updated", by: byUpdated },
                   liked: { label: "Most liked", by: byLikes } };
    var likesKnown = false; // "Most liked" is offered once the likes have arrived
    // The categories, in the catalog's order, as the tiles carry them.
    var categories = [];
    apps.forEach(function (app) {
      if (app.category && !categoryNamed(app.category)) categories.push({ key: app.category, label: app.categoryLabel, rank: app.categoryRank });
    });
    categories.sort(function (a, b) { return a.rank - b.rank; });
    function categoryNamed(key) { return categories.filter(function (one) { return one.key === key; })[0]; }

    var search = $("[data-search]");
    var state = { section: "discover", query: "", sort: "name", category: "" };

    function readAddress() {
      var params = new URLSearchParams(window.location.search);
      var section = params.get("section") || "";
      state.section = SECTIONS[section] ? section : "discover";
      state.query = (params.get("q") || "").trim();
      state.sort = ORDERS[params.get("sort")] ? params.get("sort") : "name";
      state.category = categoryNamed(params.get("category") || "") ? params.get("category") : "";
      if (search && search.value !== state.query) search.value = state.query;
    }
    function writeAddress(push) {
      var params = new URLSearchParams();
      if (state.section !== "discover") params.set("section", state.section);
      if (state.category) params.set("category", state.category);
      if (state.query) params.set("q", state.query);
      if (state.sort !== "name") params.set("sort", state.sort);
      var address = base + (params.toString() ? "?" + params.toString() : "");
      if (address === window.location.pathname + window.location.search) return;
      window.history[push ? "pushState" : "replaceState"](null, "", address);
    }

    /* The grid of one section, or of a search. */
    var title = $("[data-section-title]");
    var count = $("[data-section-count]");
    var empty = $("[data-empty]");
    var sortName = $("[data-sort-name]");
    function showGrid() {
      var terms = state.query.toLowerCase().split(/\s+/).filter(Boolean);
      var section = SECTIONS[state.section];
      var shown = apps.filter(function (app) {
        if (terms.length) return terms.every(function (term) { return app.text.indexOf(term) !== -1; });
        if (state.category && app.category !== state.category) return false;
        if (section.soon) return app.soon;
        if (section.kind) return app.kind === section.kind && !app.soon;
        return true;
      });
      shown.sort(ORDERS[state.sort].by);
      apps.forEach(function (app) { app.item.hidden = true; });
      shown.forEach(function (app, index) {
        app.item.hidden = false;
        list.appendChild(app.item);
        // Tiles arrive one after another, a row at a time.
        var tile = app.item.firstElementChild;
        if (tile && !calm) tile.style.animationDelay = Math.min(index, 11) * 35 + "ms";
      });
      var category = !terms.length && state.category ? categoryNamed(state.category) : null;
      var heading = section.title === "Discover" ? "PS5 homebrew" : section.title;
      if (category) heading = section.title === "Discover" ? category.label : section.title + " · " + category.label;
      title.textContent = terms.length ? "Results for “" + state.query + "”" : heading;
      count.textContent = shown.length;
      empty.hidden = shown.length !== 0;
      sortName.textContent = ORDERS[state.sort].label;
      document.title = (terms.length ? "Search" : category ? category.label : section.title) + " — PS5 Homebrew Store";
      paintCategories(terms.length > 0);
    }

    /* The category chips over a grid: those the section has, each with how many it holds. */
    var categoryBox = $("[data-cats]");
    function paintCategories(searching) {
      if (!categoryBox) return;
      var section = SECTIONS[state.section];
      var pool = apps.filter(function (app) {
        if (section.soon) return app.soon;
        if (section.kind) return app.kind === section.kind && !app.soon;
        return true;
      });
      var present = categories.filter(function (one) { return pool.some(function (app) { return app.category === one.key; }); });
      categoryBox.textContent = "";
      categoryBox.hidden = searching || (present.length < 2 && !state.category);
      if (categoryBox.hidden) return;
      [{ key: "", label: "All" }].concat(present).forEach(function (one) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "cat";
        button.setAttribute("aria-pressed", String(state.category === one.key));
        button.textContent = one.label;
        var number = document.createElement("span");
        number.textContent = one.key ? pool.filter(function (app) { return app.category === one.key; }).length : pool.length;
        button.appendChild(number);
        button.addEventListener("click", function () { showCategory(one.key); });
        categoryBox.appendChild(button);
      });
    }
    function showCategory(key) {
      state.category = key;
      writeAddress(true);
      render();
    }

    /* Discover: the shelves, made once from the same tiles. */
    var shelvesBox = $("[data-shelves]");
    var featured = [];
    var shelvesReady = false;
    function buildShelves() {
      if (shelvesReady) return;
      shelvesReady = true;
      var available = apps.filter(function (app) { return !app.soon; });
      var fresh = available.slice().sort(byUpdated).slice(0, NEW_AND_UPDATED);
      featured = fresh.slice(0, FEATURED);
      addShelf({ title: "New and updated", apps: fresh });
      categories.forEach(function (one) {
        addShelf({ title: one.label, category: one.key, apps: available.filter(function (app) { return app.category === one.key; }).sort(byName) });
      });
      addShelf({ title: "Coming soon", apps: apps.filter(function (app) { return app.soon; }).sort(byName) });
      paintStats();
      addLikedShelf();
    }

    /* One shelf: its title, a row of tiles copied from the grid, and the two buttons that page it.
       `dress` may add to each tile; `before` is the shelf it goes in front of (the end without it). */
    function addShelf(shelf, before) {
      if (!shelf.apps.length) return;
      var section = document.createElement("section");
      section.className = "shelf";
      var heading = document.createElement("h2");
      heading.className = "shelf__title";
      heading.textContent = shelf.title;
      var number = document.createElement("span");
      number.className = "count";
      number.textContent = shelf.apps.length;
      heading.appendChild(number);
      if (shelf.category) {
        var all = document.createElement("a");
        all.className = "shelf__all";
        all.href = base + "?category=" + encodeURIComponent(shelf.category);
        all.textContent = "See all";
        all.addEventListener("click", function (event) {
          if (event.metaKey || event.ctrlKey || event.shiftKey || event.button) return;
          event.preventDefault();
          showCategory(shelf.category);
          window.scrollTo({ top: 0, behavior: calm ? "auto" : "smooth" });
        });
        heading.appendChild(all);
      }
      var row = document.createElement("div");
      row.className = "shelf__row";
      var tiles = document.createElement("ul");
      tiles.className = "shelf__tiles";
      shelf.apps.slice(0, SHELF_TILES).forEach(function (app, position) {
        var entry = document.createElement("li");
        var tile = app.item.firstElementChild.cloneNode(true);
        tile.style.animationDelay = "";
        tile.setAttribute("data-shelf-app", app.id);
        if (shelf.dress) shelf.dress(tile, app, position);
        entry.appendChild(tile);
        tiles.appendChild(entry);
      });
      row.appendChild(tiles);
      ["prev", "next"].forEach(function (way) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "shelf__go shelf__go--" + way;
        button.setAttribute("aria-label", way === "prev" ? "Earlier in " + shelf.title : "More of " + shelf.title);
        button.textContent = way === "prev" ? "‹" : "›";
        button.addEventListener("click", function () {
          tiles.scrollBy({ left: (way === "prev" ? -0.8 : 0.8) * tiles.clientWidth, behavior: calm ? "auto" : "smooth" });
        });
        row.appendChild(button);
      });
      var ends = function () {
        var buttons = $$(".shelf__go", row);
        buttons[0].disabled = tiles.scrollLeft < 8;
        buttons[1].disabled = tiles.scrollLeft + tiles.clientWidth > tiles.scrollWidth - 8;
      };
      tiles.addEventListener("scroll", ends, { passive: true });
      window.addEventListener("resize", ends);
      setTimeout(ends, 0);
      section.appendChild(heading);
      section.appendChild(row);
      shelvesBox.insertBefore(section, before || null);
    }

    /* Likes and comments on a tile, bottom right, zero included; without `app` they are taken off. */
    function dressTile(tile, app) {
      var old = $(".tile__stats", tile);
      if (old) tile.removeChild(old);
      tile.classList.toggle("has-stats", !!app);
      if (!app) return;
      var stats = document.createElement("span");
      stats.className = "tile__stats";
      stats.setAttribute("role", "img");
      stats.setAttribute("aria-label", app.likes + (app.likes === 1 ? " like, " : " likes, ") + app.comments + (app.comments === 1 ? " comment" : " comments"));
      var likes = document.createElement("b");
      likes.textContent = "▲ " + app.likes;
      stats.appendChild(likes);
      var comments = document.createElement("span");
      var bubble = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      bubble.setAttribute("viewBox", "0 0 24 24");
      var shape = document.createElementNS("http://www.w3.org/2000/svg", "path");
      shape.setAttribute("d", "M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-6l-5 4v-4H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z");
      shape.setAttribute("fill", "none");
      shape.setAttribute("stroke", "currentColor");
      shape.setAttribute("stroke-width", "2");
      shape.setAttribute("stroke-linejoin", "round");
      bubble.appendChild(shape);
      comments.appendChild(bubble);
      comments.appendChild(document.createTextNode(app.comments));
      stats.appendChild(comments);
      tile.appendChild(stats);
    }
    /* Every tile of every app: the grid's own, and the shelves' copies (the ranked shelf says it in words). */
    function paintStats() {
      if (!likesKnown) return;
      apps.forEach(function (app) {
        dressTile(app.item.firstElementChild, app);
        $$('[data-shelf-app="' + app.id + '"]', shelvesBox).forEach(function (tile) {
          if (!tile.hasAttribute("data-ranked")) dressTile(tile, app);
        });
      });
    }

    /* "Most liked": the apps people upvoted, in order, each with its place and what it has so far.
       It goes second, once the likes are known, and only when some app has one. */
    var likedShelfReady = false;
    function addLikedShelf() {
      if (likedShelfReady || !shelvesReady || !likesKnown) return;
      likedShelfReady = true;
      var liked = apps.filter(function (app) { return !app.soon && app.likes > 0; }).sort(byLikes).slice(0, MOST_LIKED);
      addShelf({ title: "Most liked", apps: liked, dress: function (tile, app, position) {
        tile.setAttribute("data-ranked", "");
        dressTile(tile, null);
        var rank = document.createElement("span");
        rank.className = "tile__rank";
        rank.textContent = position + 1;
        tile.appendChild(rank);
        var line = $(".tile__author", tile);
        if (!line) return;
        line.textContent = "";
        var likes = document.createElement("b");
        likes.textContent = "▲ " + app.likes;
        line.appendChild(likes);
        line.appendChild(document.createTextNode((app.likes === 1 ? " like" : " likes") + "  ·  " + app.comments + (app.comments === 1 ? " comment" : " comments")));
      } }, shelvesBox.children[1]);
    }

    /* The stage: the featured apps in turn, or the tile the pointer is on. */
    var stage = $("[data-stage]");
    var words = $("[data-stage-words]", stage);
    var fields = $$("[data-stage-field]", stage);
    var cover = $("[data-stage-cover]", stage);
    var icon = $("[data-stage-icon]", stage);
    var dots = $("[data-stage-dots]", stage);
    var onStage = null;
    var banner = 0;
    var bannerTimer = 0;
    var held = false;
    var field = 0;
    var wordsTimer = 0;

    function kickerFor(app, featuredNow) {
      if (app.soon) return "Coming soon";
      if (featuredNow) return banner === 0 ? "New release" : "Featured";
      return app.categoryLabel || app.kindLabel;
    }
    function fillWords(app, kicker) {
      $("[data-stage-kicker]", stage).textContent = kicker;
      $("[data-stage-title]", stage).textContent = app.name;
      var meta = [app.author, app.categoryLabel || app.kindLabel];
      if (app.version) meta.push(app.version.replace(/^v(?=\d)/, ""));
      if (app.size) meta.push(app.size);
      $("[data-stage-meta]", stage).textContent = meta.join("  ·  ");
      $("[data-stage-text]", stage).textContent = app.description;
      $("[data-stage-link]", stage).setAttribute("href", app.url);
      $("[data-stage-mark]", stage).hidden = !app.soon;
    }
    function show(app, featuredNow) {
      if (!app || (onStage === app && !featuredNow)) return;
      var first = onStage === null;
      var changed = onStage !== app;
      onStage = app;
      var kicker = kickerFor(app, featuredNow);
      setTint(app.accent);
      if (changed) {
        // The picture: the next field fades in over the last one.
        field = 1 - field;
        fields[field].src = app.ambient;
        fields[field].classList.add("is-shown");
        fields[1 - field].classList.remove("is-shown");
      }
      clearTimeout(wordsTimer);
      if (first || calm || !changed) {
        fillWords(app, kicker);
        icon.src = app.icon;
        return;
      }
      // The old words leave quickly to the left; the new arrive a beat later.
      words.classList.add("is-leaving");
      cover.classList.add("is-changing");
      wordsTimer = setTimeout(function () {
        fillWords(app, kicker);
        icon.src = app.icon;
        words.classList.remove("is-leaving");
        words.classList.add("is-arriving");
        void words.offsetWidth;
        words.classList.remove("is-arriving");
        cover.classList.remove("is-changing");
      }, 150);
    }
    function drawDots() {
      dots.textContent = "";
      if (featured.length < 2) return;
      featured.forEach(function (app, index) {
        var dot = document.createElement("i");
        if (index === banner) dot.className = "is-current";
        dots.appendChild(dot);
      });
    }
    function showBanner(index) {
      banner = (index + featured.length) % featured.length;
      drawDots();
      show(featured[banner], true);
    }
    function startBanner() {
      clearInterval(bannerTimer);
      if (featured.length < 2 || calm) return;
      bannerTimer = setInterval(function () {
        if (!held && !document.hidden && state.section === "discover" && !state.query && !state.category) showBanner(banner + 1);
      }, BANNER_SECONDS * 1000);
    }
    function hold(tile) {
      var id = tile.getAttribute("data-shelf-app");
      var app = apps.filter(function (one) { return one.id === id; })[0];
      if (!app) return;
      held = true;
      stage.classList.add("is-held");
      show(app, false);
    }
    function release() {
      if (!held) return;
      held = false;
      stage.classList.remove("is-held");
      if (featured.length) { show(featured[banner], true); startBanner(); drawDots(); }
    }
    shelvesBox.addEventListener("pointerover", function (event) {
      var tile = event.target.closest && event.target.closest("[data-shelf-app]");
      if (tile && event.pointerType !== "touch") hold(tile);
    });
    shelvesBox.addEventListener("pointerleave", release);
    shelvesBox.addEventListener("focusin", function (event) {
      var tile = event.target.closest && event.target.closest("[data-shelf-app]");
      if (tile) hold(tile);
    });
    shelvesBox.addEventListener("focusout", function (event) {
      if (!shelvesBox.contains(event.relatedTarget)) release();
    });

    function render() {
      var discover = state.section === "discover" && !state.query && !state.category;
      body.classList.toggle("is-discover", discover);
      moveLine(state.query ? "" : state.section);
      if (discover) {
        buildShelves();
        if (featured.length && onStage === null) { showBanner(0); startBanner(); }
        else if (featured.length && !held) show(featured[banner], true);
        document.title = "PS5 Homebrew Store — community apps, games and tools";
      } else {
        showGrid();
        setTint("#42358f");
      }
    }

    $$("[data-tabs] .tab").forEach(function (tab) {
      tab.addEventListener("click", function (event) {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button) return;
        event.preventDefault();
        state.section = tab.getAttribute("data-section");
        state.query = "";
        state.category = "";
        if (search) search.value = "";
        writeAddress(true);
        render();
        window.scrollTo({ top: 0, behavior: calm ? "auto" : "smooth" });
      });
    });
    if (search) {
      var typing = 0;
      search.addEventListener("input", function () {
        clearTimeout(typing);
        typing = setTimeout(function () {
          state.query = search.value.trim();
          writeAddress(false);
          render();
        }, 120);
      });
    }
    var sort = $("[data-sort]");
    if (sort) sort.addEventListener("click", function () {
      var order = likesKnown ? ["name", "updated", "liked"] : ["name", "updated"];
      state.sort = order[(order.indexOf(state.sort) + 1) % order.length];
      writeAddress(false);
      showGrid();
    });
    commentsFile("index.json", function (data) {
      apps.forEach(function (app) {
        var entry = data.apps && data.apps[app.id];
        app.likes = entry && entry.likes > 0 ? Math.floor(entry.likes) : 0;
        app.comments = entry && entry.comments > 0 ? Math.floor(entry.comments) : 0;
      });
      likesKnown = true;
      paintStats();
      addLikedShelf();
      if (state.sort === "liked" && !(state.section === "discover" && !state.query)) showGrid();
    });
    window.addEventListener("popstate", function () { readAddress(); render(); });
    window.addEventListener("resize", function () { moveLine(state.query ? "" : state.section); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { moveLine(state.query ? "" : state.section); });

    readAddress();
    render();
  }

  /* ---- An app's page ---- */

  function page() {
    var article = $("[data-accent]");
    if (article) setTint(article.getAttribute("data-accent"));
    var search = $("[data-search]");
    var base = document.body.getAttribute("data-base") || "/";
    if (search) search.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && search.value.trim()) window.location.href = base + "?q=" + encodeURIComponent(search.value.trim());
    });
    var comments = $("[data-comments-for]");
    if (comments) commentsFile("apps/" + comments.getAttribute("data-comments-for") + ".json", function (data) {
      showReactions(data);
      showComments(comments, data);
    });
  }

  /* The Like and Comment buttons: where they lead, and how many there are so far (zero included). */
  function showReactions(data) {
    var address = /^https:\/\/github\.com\/[^\s"<>]+$/.test(data.url || "") ? data.url : "";
    $$("[data-react], [data-comments-link]").forEach(function (link) { if (address) link.setAttribute("href", address); });
    ["likes", "comments"].forEach(function (what) {
      var count = $('[data-count="' + what + '"]');
      if (count) count.textContent = String(data[what] > 0 ? Math.floor(data[what]) : 0);
    });
  }

  /* Everything in the file is other people's text: it goes in as text, never as markup. */
  function showComments(box, data) {
    var list = $("[data-comments-list]", box);
    var latest = Array.isArray(data.latest) ? data.latest.slice(0, 10) : [];
    if (!list || !latest.length) return;
    latest.forEach(function (comment) {
      if (!comment || typeof comment.text !== "string" || !comment.text) return;
      var entry = document.createElement("li");
      var by = document.createElement("span");
      by.className = "comments__by";
      var author = document.createElement("b");
      author.textContent = String(comment.author || "someone").slice(0, 40);
      by.appendChild(author);
      var when = new Date(comment.date);
      if (!isNaN(when)) by.appendChild(document.createTextNode("  ·  " + when.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })));
      var text = document.createElement("span");
      text.className = "comments__text";
      text.textContent = comment.text.slice(0, 500);
      entry.appendChild(by);
      entry.appendChild(text);
      list.appendChild(entry);
    });
    list.hidden = !list.children.length;
    if (list.hidden) return;
    var none = $("[data-comments-none]", box);
    var more = $("[data-comments-more]", box);
    if (none) none.hidden = true;
    if (more) {
      more.hidden = false;
      if (data.comments > latest.length) $("a", more).textContent = "Read all " + Math.floor(data.comments) + " comments on GitHub";
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    copyButtons();
    // "/" goes to the search, as the store's Triangle does.
    document.addEventListener("keydown", function (event) {
      var search = $("[data-search]");
      if (!search || event.metaKey || event.ctrlKey || event.altKey) return;
      var typing = /^(INPUT|TEXTAREA|SELECT)$/.test((event.target.tagName || ""));
      if (event.key === "/" && !typing) { event.preventDefault(); search.focus(); }
      else if (event.key === "Escape" && event.target === search) { search.value = ""; search.dispatchEvent(new Event("input")); search.blur(); }
    });
    if ($("[data-tiles]")) home(); else page();
  });
})();
