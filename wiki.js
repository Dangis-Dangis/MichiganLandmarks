/* Michigan Landmarks in-app Help overlay. */
(function (global) {
  "use strict";

  const CATALOG_URL = "./docs/index.json";
  const BUILD_INFO_URL = "./docs/build-info.json";
  const WIKI_DIR = "./docs/";

  const $ = (sel, root) => (root || document).querySelector(sel);

  let catalog = null;
  let buildInfo = null;
  let options = {
    onAction: function () {},
    getAboutContext: function () { return {}; },
  };
  let currentPageId = "home";
  let lastFocus = null;
  let ignoreHash = false;

  function panel() { return $("#wikiPanel"); }
  function isOpen() {
    const el = panel();
    return el && !el.classList.contains("hidden");
  }

  function parseHash(hash) {
    const raw = String(hash || "").replace(/^#/, "");
    if (!raw) return null;
    if (raw === "wiki" || raw === "wiki/") return { page: "home", heading: "" };
    if (raw.indexOf("wiki/") !== 0) return null;
    const rest = raw.slice("wiki/".length);
    const parts = rest.split("/").filter(Boolean);
    if (!parts.length) return { page: "home", heading: "" };
    return { page: parts[0], heading: parts.slice(1).join("/") };
  }

  function pageHash(pageId, heading) {
    if (!pageId || pageId === "home") return "#wiki";
    return heading ? "#wiki/" + pageId + "/" + heading : "#wiki/" + pageId;
  }

  function slugify(text) {
    return String(text || "")
      .trim()
      .toLowerCase()
      .replace(/['"]/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function pageById(id) {
    if (!catalog) return null;
    return (catalog.pages || []).find((p) => p.id === id) || null;
  }

  function setHash(pageId, heading, replace) {
    const next = pageHash(pageId, heading);
    if (location.hash === next) {
      openTo(pageId, heading);
      return;
    }
    ignoreHash = true;
    if (replace) history.replaceState(null, "", next);
    else location.hash = next;
    ignoreHash = false;
    openTo(pageId, heading);
  }

  function clearHash() {
    if (!parseHash(location.hash)) return;
    ignoreHash = true;
    history.replaceState(null, "", location.pathname + location.search);
    ignoreHash = false;
  }

  function resolveRelative(fromFile, href) {
    const base = new URL(fromFile, new URL(WIKI_DIR, location.href));
    return new URL(href, base);
  }

  function wikiTargetForUrl(url) {
    const origin = location.origin;
    if (url.origin !== origin && url.protocol !== "file:") return null;
    let path = url.pathname.replace(/\\/g, "/");
    const here = new URL("./", location.href).pathname.replace(/\\/g, "/");
    let rel = path;
    if (path.indexOf(here) === 0) rel = path.slice(here.length);
    rel = rel.replace(/^\.\//, "");

    const pages = (catalog && catalog.pages) || [];
    for (let i = 0; i < pages.length; i++) {
      const p = pages[i];
      const fileUrl = resolveRelative(p.file, "");
      const filePath = fileUrl.pathname.replace(/\\/g, "/");
      const fileRel = p.file.replace(/^\.\.\//, "");
      if (path === filePath || rel === fileRel ||
          rel === "docs/" + p.file || rel === "wiki/" + p.file ||
          rel.endsWith("/" + fileRel)) {
        const heading = url.hash ? url.hash.replace(/^#/, "") : "";
        return { page: p.id, heading: heading };
      }
      const name = p.file.split("/").pop();
      if (rel === name || rel.endsWith("/" + name) ||
          rel.endsWith("docs/" + name) || rel.endsWith("wiki/" + name)) {
        const heading = url.hash ? url.hash.replace(/^#/, "") : "";
        return { page: p.id, heading: heading };
      }
    }
    if (/LEGAL\.md$/i.test(path) || /\/LEGAL\.md$/i.test(rel) || rel === "LEGAL.md" ||
        rel === "docs/LEGAL.md") {
      return { page: "legal", heading: url.hash ? url.hash.replace(/^#/, "") : "" };
    }
    if (/legal\.html$/i.test(path) || /\/legal\.html$/i.test(rel) || rel === "legal.html") {
      return { page: "legal", heading: url.hash ? url.hash.replace(/^#/, "") : "" };
    }
    if (/CHANGELOG\.md$/i.test(path) || rel === "CHANGELOG.md") {
      return { page: "changelog", heading: url.hash ? url.hash.replace(/^#/, "") : "" };
    }
    return null;
  }

  function headingIdFromWikiHash(heading) {
    return heading || "";
  }

  function rewriteAnchor(a, pageFile) {
    const raw = a.getAttribute("href") || "";
    if (!raw) return;
    if (raw.indexOf("app:") === 0) {
      a.setAttribute("data-wiki-action", raw.slice(4));
      a.setAttribute("href", "#");
      return;
    }
    if (/^(mailto:|tel:)/i.test(raw)) return;
    if (/^https?:\/\//i.test(raw)) {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener");
      return;
    }
    if (raw.charAt(0) === "#" && raw.indexOf("#wiki") !== 0) {
      const id = raw.slice(1);
      a.setAttribute("href", pageHash(currentPageId, id));
      a.setAttribute("data-wiki-page", currentPageId);
      a.setAttribute("data-wiki-heading", id);
      return;
    }
    let url;
    try {
      url = resolveRelative(pageFile, raw);
    } catch (e) {
      return;
    }
    const target = wikiTargetForUrl(url);
    if (target) {
      a.setAttribute("href", pageHash(target.page, target.heading));
      a.setAttribute("data-wiki-page", target.page);
      if (target.heading) a.setAttribute("data-wiki-heading", target.heading);
      return;
    }
    if (url.protocol === "http:" || url.protocol === "https:") {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener");
    }
  }

  function rewriteImage(img, pageFile) {
    const src = img.getAttribute("src") || "";
    if (!src || /^(https?:|data:)/i.test(src)) return;
    try {
      const url = resolveRelative(pageFile, src);
      img.setAttribute("src", url.pathname + url.search);
    } catch (e) {
      img.removeAttribute("src");
    }
  }

  function applyHeadingIds(root) {
    root.querySelectorAll("h1, h2, h3, h4").forEach((h) => {
      if (!h.id) h.id = slugify(h.textContent);
    });
  }

  function fillTokens(text, ctx) {
    return String(text).replace(/\{\{([a-z_]+)\}\}/g, (m, key) => {
      if (Object.prototype.hasOwnProperty.call(ctx, key) && ctx[key] != null && ctx[key] !== "") {
        return String(ctx[key]);
      }
      return m;
    });
  }

  let markedReady = false;

  function parseMarkdown(src) {
    const markedLib = global.marked;
    if (!markedLib || typeof markedLib.parse !== "function") {
      throw new Error("marked library failed to load");
    }
    if (!markedReady && typeof markedLib.use === "function") {
      markedLib.use({
        gfm: true,
        breaks: false,
        renderer: {
          html: function () { return ""; },
        },
      });
      markedReady = true;
    }
    return markedLib.parse(src, { async: false });
  }

  async function fetchText(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error("fetch failed " + res.status + " " + url);
    return res.text();
  }

  function aboutContext() {
    const extra = options.getAboutContext() || {};
    const info = buildInfo || {};
    return Object.assign({
      app_version: info.app_version || "",
      pipeline_version: info.pipeline_version || "",
      maplibre_version: info.maplibre_version || "",
    }, extra);
  }

  async function renderPage(page, heading) {
    const body = $("#wikiBody");
    const nav = $("#wikiNav");
    const tools = $("#wikiHomeTools");
    const titleEl = $("#wikiTitle");
    const back = $("#wikiBack");
    if (!body) return;

    currentPageId = page.id;
    titleEl.textContent = page.title || "Help";
    const home = page.id === "home";
    if (tools) tools.classList.toggle("hidden", !home);
    if (nav) nav.classList.toggle("hidden", !home);
    if (back) {
      back.classList.toggle("hidden", home);
      back.disabled = home;
    }
    if (home) renderNav($("#wikiSearch") ? $("#wikiSearch").value : "");

    body.innerHTML = "<p class=\"muted\">Loading…</p>";
    try {
      const url = resolveRelative(page.file, "").href;
      const raw = await fetchText(url);
      if (page.type === "html") {
        const doc = new DOMParser().parseFromString(raw, "text/html");
        const main = doc.querySelector("main") || doc.body;
        body.innerHTML = "";
        const wrap = document.createElement("div");
        wrap.className = "wiki-article wiki-legal";
        wrap.appendChild(document.importNode(main, true));
        wrap.querySelectorAll("a").forEach((a) => rewriteAnchor(a, page.file));
        wrap.querySelectorAll("img").forEach((img) => rewriteImage(img, page.file));
        body.appendChild(wrap);
      } else {
        let md = raw;
        if (page.id === "about") md = fillTokens(md, aboutContext());
        const html = parseMarkdown(md);
        const wrap = document.createElement("div");
        wrap.className = "wiki-article";
        wrap.innerHTML = html;
        applyHeadingIds(wrap);
        wrap.querySelectorAll("a").forEach((a) => rewriteAnchor(a, page.file));
        wrap.querySelectorAll("img").forEach((img) => rewriteImage(img, page.file));
        body.innerHTML = "";
        body.appendChild(wrap);
      }
    } catch (err) {
      body.innerHTML = "<p class=\"muted\">Could not load this Help page.</p>";
      return;
    }

    const hid = headingIdFromWikiHash(heading);
    if (hid) {
        const target = document.getElementById(hid);
      if (target) target.scrollIntoView({ block: "start" });
      else body.scrollTop = 0;
    } else {
      body.scrollTop = 0;
    }
  }

  function renderNav(query) {
    const nav = $("#wikiNav");
    if (!nav || !catalog) return;
    const q = String(query || "").trim().toLowerCase();
    nav.innerHTML = "";
    (catalog.pages || []).forEach((p) => {
      if (!p.nav) return;
      if (q && (p.title || "").toLowerCase().indexOf(q) === -1 && (p.id || "").indexOf(q) === -1) {
        return;
      }
      const a = document.createElement("a");
      a.className = "wiki-nav-item";
      a.href = pageHash(p.id);
      a.setAttribute("data-wiki-page", p.id);
      a.textContent = p.title;
      nav.appendChild(a);
    });
  }

  async function openTo(pageId, heading) {
    const el = panel();
    if (!el) return;
    if (!catalog) await loadCatalog();
    const page = pageById(pageId) || pageById("home");
    if (!isOpen()) {
      lastFocus = document.activeElement;
      el.classList.remove("hidden");
      el.setAttribute("aria-hidden", "false");
    }
    await renderPage(page, heading || "");
    const focusEl = page.id === "home" ? $("#wikiSearch") : $("#wikiClose");
    if (focusEl) focusEl.focus();
  }

  function close() {
    const el = panel();
    if (!el || el.classList.contains("hidden")) {
      clearHash();
      return;
    }
    el.classList.add("hidden");
    el.setAttribute("aria-hidden", "true");
    clearHash();
    if (lastFocus && typeof lastFocus.focus === "function") {
      try { lastFocus.focus(); } catch (e) { /* ignore */ }
    }
  }

  function open(pageId, heading) {
    setHash(pageId || "home", heading || "", false);
  }

  function onHashChange() {
    if (ignoreHash) return;
    const parsed = parseHash(location.hash);
    if (!parsed) {
      if (isOpen()) {
        const el = panel();
        el.classList.add("hidden");
        el.setAttribute("aria-hidden", "true");
      }
      return;
    }
    openTo(parsed.page, parsed.heading);
  }

  function onPanelClick(e) {
    const actionEl = e.target.closest("[data-wiki-action]");
    if (actionEl) {
      e.preventDefault();
      const name = actionEl.getAttribute("data-wiki-action");
      close();
      options.onAction(name);
      return;
    }
    const link = e.target.closest("a[data-wiki-page]");
    if (link) {
      e.preventDefault();
      open(link.getAttribute("data-wiki-page"), link.getAttribute("data-wiki-heading") || "");
    }
  }

  function focusables() {
    const el = panel();
    if (!el) return [];
    return Array.prototype.slice.call(el.querySelectorAll(
      'button:not([disabled]):not(.hidden), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter((n) => n.offsetParent !== null && !n.classList.contains("hidden"));
  }

  function onKeydown(e) {
    if (!isOpen()) return;
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopImmediatePropagation();
      close();
      return;
    }
    if (e.key !== "Tab") return;
    const nodes = focusables();
    if (!nodes.length) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  async function loadCatalog() {
    const res = await fetch(CATALOG_URL);
    if (!res.ok) throw new Error("wiki catalog fetch failed");
    catalog = await res.json();
    try {
      const b = await fetch(BUILD_INFO_URL);
      if (b.ok) buildInfo = await b.json();
    } catch (e) {
      buildInfo = null;
    }
  }

  async function init(opts) {
    options = Object.assign(options, opts || {});
    const el = panel();
    if (!el) return;
    el.addEventListener("click", onPanelClick);
    $("#wikiClose").addEventListener("click", (e) => { e.preventDefault(); close(); });
    $("#wikiBack").addEventListener("click", (e) => {
      e.preventDefault();
      open("home");
    });
    const search = $("#wikiSearch");
    if (search) {
      search.addEventListener("input", () => renderNav(search.value));
    }
    document.addEventListener("keydown", onKeydown, true);
    window.addEventListener("hashchange", onHashChange);
    try {
      await loadCatalog();
    } catch (e) {
      catalog = { pages: [] };
    }
    onHashChange();
  }

  global.Wiki = {
    init: init,
    open: open,
    close: close,
    isOpen: isOpen,
  };
})(window);
