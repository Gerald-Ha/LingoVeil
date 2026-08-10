const params = new URLSearchParams(window.location.search);

const sessionToken = params.get("token") || "";
const initialSessionCode = (params.get("code") || "").replace(/\D/g, "").slice(0, 4);

let translationCacheTtlMs = 5 * 60 * 1000;
const THUMB_PREVIEW_MAX_CONCURRENT = 3;
const translationCache = new Map();

const prefetchInFlight = new Set();

const translatingItems = new Set();

const queuedTranslationItems = new Set();

const translationQueue = [];
let translationQueueActive = false;
let thumbPreviewActive = 0;
const thumbPreviewQueue = [];
let thumbObserver = null;
const ENGINE_STORAGE_KEY = "lingoveil.browser.engine";
const VALID_ENGINES = new Set(["bergamot", "seamless_m4t", "lm_studio", "ollama"]);

const ENGINE_LABELS = {
  bergamot: "Bergamot lokal",
  seamless_m4t: "SeamlessM4T lokal",
  lm_studio: "LM Studio",
  ollama: "Ollama",
};

function loadSavedEngine() {
  try {
    const saved = localStorage.getItem(ENGINE_STORAGE_KEY);

    if (saved && VALID_ENGINES.has(saved)) return saved;
  } catch (_) {
  }

  return null;
}

function saveEngineChoice(engine) {
  if (!VALID_ENGINES.has(engine)) return;
  try {
    localStorage.setItem(ENGINE_STORAGE_KEY, engine);
  } catch (_) {
  }
}

function applySavedEngine() {
  const saved = loadSavedEngine();

  if (saved) {
    $("engine-select").value = saved;
  }
}

const state = {
  connected: false,
  sessionCode: initialSessionCode,
  imageId: null,
  selectedPageImageId: null,
  source: "page_analyze",
  galleryImages: [],
  processing: false,
  previewMode: "fit",
  previewZoom: 1,
  lastResult: null,
  confirmedEngine: null,
  translationVisible: true,
  currentTranslatedSrc: null,
  currentOriginalSrc: null,
  panX: 0,
  panY: 0,
  lastAppliedZoom: 1,
  sessionPanelManuallyHidden: false,
  prefetchCount: 10,
  targetLanguage: "deu",
  activeHistoryEntryId: null,
  urlErrorContext: null,
  libraryTab: "history",
  bookmarks: [],
  currentCatalog: null,
  catalogSortAscending: false,
  pendingBookmarkRemoval: null,
  bookmarkEditMode: false,
  chapterNavigation: null,
};

const FIELD_ERRORS = {
  page_analyze: "err-page-analyze",
};

function $(id) {
  return document.getElementById(id);
}

function initMobileHeaderMenu() {
  const toggle = $("mobile-menu-toggle");

  const menu = $("mobile-header-menu");

  if (!toggle || !menu) return;
  const setOpen = (open) => {
    menu.classList.toggle("open", open);

    toggle.setAttribute("aria-expanded", String(open));

    toggle.setAttribute("aria-label", open ? "Menü schließen" : "Menü öffnen");
  };

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();

    setOpen(toggle.getAttribute("aria-expanded") !== "true");
  });

  menu.addEventListener("click", (event) => {
    if (event.target.closest("button")) setOpen(false);
  });

  $("engine-select")?.addEventListener("change", () => setOpen(false));

  document.addEventListener("click", (event) => {
    if (!menu.contains(event.target) && !toggle.contains(event.target)) setOpen(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setOpen(false);

      toggle.focus();
    }
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 736) setOpen(false);
  });
}

function initMobileSections() {
  const sections = [
    ["source-section-toggle", ".source-heading", "Eingabequelle"],
    ["history-section-toggle", ".history-heading", "History und Bookmarks"],
    ["gallery-section-toggle", ".gallery-header", "Gefundene Bilder"],
  ];
  sections.forEach(([toggleId, headingSelector, label]) => {
    const toggle = $(toggleId);

    const heading = toggle?.closest(headingSelector);

    if (!toggle || !heading) return;
    const setOpen = (open) => {
      toggle.setAttribute("aria-expanded", String(open));

      toggle.setAttribute("aria-label", `${label} ${open ? "zuklappen" : "aufklappen"}`);
    };

    const invert = () => setOpen(toggle.getAttribute("aria-expanded") !== "true");

    toggle.addEventListener("click", (event) => {
      event.stopPropagation();

      invert();
    });

    heading.addEventListener("click", (event) => {
      if (event.target.closest("button, input, select, a")) return;
      invert();
    });
  });
}

function normalizeSessionCode(value) {
  return (value || "").replace(/\D/g, "").slice(0, 4);
}

function authQuery() {
  const query = new URLSearchParams();

  if (sessionToken) {
    query.set("token", sessionToken);
  } else if (state.sessionCode) {
    query.set("code", state.sessionCode);
  }

  const encoded = query.toString();

  return encoded ? `?${encoded}` : "";
}

function authHeaders() {
  if (sessionToken) return { "X-Session-Token": sessionToken };

  if (state.sessionCode) return { "X-Session-Code": state.sessionCode };

  return {};
}

function withAuth(path) {
  const [base, query = ""] = path.split("?");

  const merged = new URLSearchParams(query);

  if (sessionToken) {
    merged.set("token", sessionToken);
  } else if (state.sessionCode) {
    merged.set("code", state.sessionCode);
  }

  const suffix = merged.toString();

  return suffix ? `${base}?${suffix}` : base;
}

function setStatus(msg) {
  const status = $("status");

  if (status) status.textContent = msg;
}

function setSessionHint(msg, { error = false } = {}) {
  const hint = $("session-hint");

  hint.textContent = msg;
  hint.style.color = error ? "var(--error)" : "";
}

function setSessionPanelConnected(connected) {
  state.connected = connected;
  $("session-code-input").disabled = sessionToken !== "";
  $("btn-connect").disabled = sessionToken !== "";
  $("session-panel").classList.toggle("connected", connected);

  updateSessionPanelVisibility();
}

function updateSessionPanelVisibility() {
  const shouldHide = state.connected && !state.sessionPanelManuallyHidden;
  const panel = $("session-panel");

  panel.classList.toggle("hidden", shouldHide);

  panel.hidden = shouldHide;
  panel.setAttribute("aria-hidden", shouldHide ? "true" : "false");
}

function setAppInteractive(enabled) {
  [
    "engine-select",
    "btn-analyze-page",
    "btn-fit",
    "zoom-slider",
    "btn-toggle-translation",
    "btn-preview-prev",
    "btn-preview-next",
    "btn-preview-chapter-prev",
    "btn-preview-chapter-next",
    "btn-translate-gallery",
    "url-page",
  ].forEach((id) => {
    const el = $(id);

    if (el) el.disabled = !enabled;
  });

  if (enabled) updateGalleryNavButtons();
}

function setFieldError(source, msg) {
  const id = FIELD_ERRORS[source];
  if (!id) return;
  const el = $(id);

  if (!msg) {
    el.textContent = "";
    el.classList.add("hidden");

    return;
  }

  el.textContent = msg;
  el.classList.remove("hidden");
}

function clearFieldErrors() {
  Object.values(FIELD_ERRORS).forEach((id) => {
    const el = $(id);

    el.textContent = "";
    el.classList.add("hidden");
  });
}

function setProcessing(active) {
  state.processing = active;
  $("btn-translate-gallery").disabled = active || !state.selectedPageImageId;
  $("btn-analyze-page").disabled = active;
  updateGalleryNavButtons();
}

function pageImageCacheKey(imageId, engine) {
  return `page:${imageId}:${engine}:${state.targetLanguage}`;
}

function getCachedTranslation(key) {
  const entry = translationCache.get(key);

  if (!entry) return null;
  if (Date.now() > entry.expiresAt) {
    if (entry.blobUrl) URL.revokeObjectURL(entry.blobUrl);

    translationCache.delete(key);

    return null;
  }

  return entry;
}

function revokeCacheEntry(entry) {
  if (!entry) return;
  if (entry.blobUrl) URL.revokeObjectURL(entry.blobUrl);

  if (entry.originalBlobUrl) URL.revokeObjectURL(entry.originalBlobUrl);
}

function galleryItemById(imageId) {
  return state.galleryImages.find((item) => item.id === imageId) || null;
}

async function fetchInputBlobUrl() {
  const response = await fetch(withAuth(`/api/input?t=${Date.now()}`), {
    headers: authHeaders(),
  });

  if (!response.ok) return null;
  const blob = await response.blob();

  return URL.createObjectURL(blob);
}

async function resolveOriginalSource(imageId = null) {
  const item = imageId ? galleryItemById(imageId) : null;
  if (item?.preview_url) return item.preview_url;
  return fetchInputBlobUrl();
}

async function storeTranslationCache(key, result, imageId = null) {
  const existing = translationCache.get(key);

  if (existing) revokeCacheEntry(existing);

  const renderedPath = result?.rendered_url
    || (imageId ? null : `/api/rendered?t=${Date.now()}`);

  if (!renderedPath) {
    throw new Error("Der Übersetzungsjob hat kein benutzerspezifisches Rendering geliefert.");
  }

  const response = await fetch(
    withAuth(renderedPath),
    { headers: authHeaders() }

  );

  if (!response.ok) return;
  const blob = await response.blob();

  const blobUrl = URL.createObjectURL(blob);

  let originalSrc = null;
  let originalBlobUrl = null;
  const item = imageId ? galleryItemById(imageId) : null;
  if (item?.preview_url) {
    originalSrc = item.preview_url;
  } else {
    originalBlobUrl = await fetchInputBlobUrl();

    originalSrc = originalBlobUrl;
  }

  translationCache.set(key, {
    result,
    blobUrl,
    originalSrc,
    originalBlobUrl,
    expiresAt: Date.now() + translationCacheTtlMs,
  });
}

async function loadPersistentHistoryTranslation(item, engine) {
  const stored = item?.cached_translations?.[translationVariantKey(engine)]
    || item?.cached_translations?.[engine];
  if (!stored?.rendered_url || !stored?.result_url) return null;
  const [result, renderedResponse] = await Promise.all([
    api(stored.result_url),
    fetch(withAuth(stored.rendered_url), { headers: authHeaders() }),
  ]);

  const legacyTarget = (engine === "seamless_m4t" || engine === "ollama") ? "deu" : "de";
  const expectedTarget = engineTargetLanguage(engine);

  if (String(result.target_language || legacyTarget) !== expectedTarget) {
    return null;
  }

  if (!renderedResponse.ok) {
    throw new Error("Gespeicherte History-Übersetzung konnte nicht geladen werden.");
  }

  const blobUrl = URL.createObjectURL(await renderedResponse.blob());

  const cached = {
    result: {...result, history_cache_hit: true},
    blobUrl,
    originalSrc: item.preview_url || blobUrl,
    originalBlobUrl: null,
    expiresAt: Date.now() + translationCacheTtlMs,
  };

  const key = pageImageCacheKey(item.id, engine);

  const previous = translationCache.get(key);

  if (previous) revokeCacheEntry(previous);

  translationCache.set(key, cached);

  return cached;
}

function getUpcomingImages(count = state.prefetchCount) {
  if (!state.selectedPageImageId) return [];
  const filtered = getFilteredImages();

  const idx = filtered.findIndex((item) => item.id === state.selectedPageImageId);

  if (idx < 0) return [];
  const images = [];
  for (let i = 1; i <= count; i += 1) {
    const next = filtered[idx + i];
    if (!next) break;
    images.push(next);
  }

  return images;
}

function drainTranslationQueue() {
  if (translationQueueActive || translationQueue.length === 0) return;
  const job = translationQueue.shift();

  translationQueueActive = true;
  Promise.resolve()

    .then(job.task)

    .then(job.resolve, job.reject)

    .finally(() => {
      translationQueueActive = false;
      drainTranslationQueue();
    });
}

function enqueueTranslation(task, {key = "", priority = false} = {}) {
  return new Promise((resolve, reject) => {
    const job = {task, key, resolve, reject};

    if (priority) {
      translationQueue.unshift(job);
    } else {
      translationQueue.push(job);
    }

    drainTranslationQueue();
  });
}

function promoteQueuedTranslation(imageId, engine) {
  const key = translationItemKey(imageId, engine);

  const index = translationQueue.findIndex((job) => job.key === key);

  if (index <= 0) return;
  const [job] = translationQueue.splice(index, 1);

  translationQueue.unshift(job);
}

function drainThumbPreviewQueue() {
  while (thumbPreviewActive < THUMB_PREVIEW_MAX_CONCURRENT && thumbPreviewQueue.length > 0) {
    const img = thumbPreviewQueue.shift();

    if (!img || !img.isConnected || img.src || !img.dataset.src) continue;
    thumbPreviewActive += 1;
    const done = () => {
      thumbPreviewActive = Math.max(0, thumbPreviewActive - 1);

      drainThumbPreviewQueue();
    };

    img.addEventListener("load", done, { once: true });

    img.addEventListener("error", done, { once: true });

    img.src = img.dataset.src;
  }
}

function queueThumbPreview(img) {
  if (!img?.dataset?.src || img.src) return;
  thumbPreviewQueue.push(img);

  drainThumbPreviewQueue();
}

function observeThumbImage(img) {
  if (!("IntersectionObserver" in window)) {
    queueThumbPreview(img);

    return;
  }

  if (!thumbObserver) {
    thumbObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const target = entry.target;
          thumbObserver.unobserve(target);

          queueThumbPreview(target);
        });
      },
      { root: null, rootMargin: "160px", threshold: 0.01 },
    );
  }

  thumbObserver.observe(img);
}

function resetThumbPreviewQueue() {
  thumbPreviewQueue.length = 0;
}

async function translatePageImageSilent(item, engine) {
  const imageId = item.id;
  const key = pageImageCacheKey(imageId, engine);

  const queueKey = translationItemKey(imageId, engine);

  if (getCachedTranslation(key) || itemIsTranslated(item, engine)) return;
  if (queuedTranslationItems.has(queueKey)) return;
  queuedTranslationItems.add(queueKey);

  prefetchInFlight.add(imageId);

  updateQueuedItemStatus(imageId);

  try {
    await enqueueTranslation(async () => {
      queuedTranslationItems.delete(queueKey);

      updateQueuedItemStatus(imageId);

      try {
        setItemTranslating(imageId, engine, true);

        const result = item.pdf_id != null
          ? await runTranslationBackgroundJob("pdf-page", {
              pdf_id: item.pdf_id,
              page_number: item.page_number ?? 0,
              engine,
            })

          : await runTranslationBackgroundJob("page-image", {
              image_id: imageId,
              engine,
            });

        if (String(result.target_language || "") !== engineTargetLanguage(engine)) {
          console.info(
            `Veraltete Vorab-Übersetzung verworfen: ${result.target_language || "unbekannt"}`
          );

          return;
        }

        if (!Array.isArray(item.translated_engines)) item.translated_engines = [];
        if (!item.translated_engines.includes(result.engine || engine)) {
          item.translated_engines.push(result.engine || engine);
        }

        if (galleryItemById(imageId)) {
          await storeTranslationCache(key, result, imageId);
        }

        markItemTranslated(imageId, result.engine || engine);

        const label = item ? `#${item.index + 1}` : imageId;
        console.info(`Vorab-Übersetzung bereit: ${label} (${engineLabel(engine)})`);
      } finally {
        setItemTranslating(imageId, engine, false);
      }
    }, {key: queueKey});
  } catch (err) {
    console.warn(`Vorab-Übersetzung fehlgeschlagen (${imageId}):`, err.message);

    if (!item.history_id || item.history_id === state.activeHistoryEntryId) {
      showUrlLoadError(
        `Ein Bild der Seite konnte nicht geladen werden.\n\n${err.message}`,
        item.history_id || state.activeHistoryEntryId || item.url || "background",
      );
    }
  } finally {
    queuedTranslationItems.delete(queueKey);

    prefetchInFlight.delete(imageId);

    updateQueuedItemStatus(imageId);
  }
}

async function waitForPrefetch(imageId) {
  while (prefetchInFlight.has(imageId)) {
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
}

function enqueuePrefetchImages(images, engine = selectedEngine()) {
  if (state.prefetchCount <= 0) return;
  images.slice(0, state.prefetchCount).forEach((item) => {
    void translatePageImageSilent(item, engine);
  });
}

function schedulePrefetch() {
  if (selectedSource() !== "page_analyze" || !state.selectedPageImageId) return;
  if (state.prefetchCount <= 0) return;
  enqueuePrefetchImages(getUpcomingImages(state.prefetchCount));
}

async function loadHistory() {
  try {
    const {entries} = await api("/api/history");

    renderHistory(entries || []);
  } catch (err) {
    console.warn("History konnte nicht geladen werden:", err.message);
  }
}

async function loadBookmarks() {
  try {
    const {bookmarks} = await api("/api/bookmarks");

    state.bookmarks = bookmarks || [];
    renderBookmarks(state.bookmarks);
  } catch (err) {
    console.warn("Bookmarks konnten nicht geladen werden:", err.message);
  }
}

function renderHistory(entries) {
  const list = $("history-list");

  if (state.libraryTab === "history") {
    $("library-count").textContent = String(entries.length);
  }

  list.replaceChildren();

  if (!entries.length) {
    const empty = document.createElement("p");

    empty.className = "hint";
    empty.textContent = "Noch keine URL gespeichert.";
    list.append(empty);

    return;
  }

  entries.forEach((entry) => {
    const button = document.createElement("button");

    button.type = "button";
    button.className = "history-entry";
    button.dataset.historyId = entry.id;
    button.title = entry.url;
    const active = entry.id === state.activeHistoryEntryId;
    button.classList.toggle("active", active);

    if (active) button.setAttribute("aria-current", "page");

    const metadata = entry.metadata || {};

    const url = document.createElement("span");

    url.className = metadata.manga_title ? "history-title" : "history-url";
    url.textContent = metadata.manga_title || entry.url;
    const meta = document.createElement("span");

    meta.className = "history-meta";
    const location = [
      metadata.volume ? `Volume ${metadata.volume}` : "",
      metadata.chapter ? `Chapter ${metadata.chapter}` : "",
    ].filter(Boolean).join(" · ");

    meta.textContent =
      `${location ? `${location} · ` : ""}` +
      `${entry.translated_count}/${entry.image_count} Bilder übersetzt`;
    button.append(url, meta);

    button.addEventListener("click", () => openHistoryEntry(entry.id));

    list.append(button);
  });
}

function renderBookmarks(bookmarks) {
  const list = $("bookmark-list");

  const query = $("bookmark-search").value.trim().toLocaleLowerCase();

  const visible = query
    ? bookmarks.filter((bookmark) =>
        `${bookmark.title} ${bookmark.url}`.toLocaleLowerCase().includes(query))

    : bookmarks;
  if (state.libraryTab === "bookmarks") {
    $("library-count").textContent = query
      ? `${visible.length}/${bookmarks.length}`
      : String(bookmarks.length);
  }

  list.replaceChildren();

  if (!visible.length) {
    const empty = document.createElement("p");

    empty.className = "hint";
    empty.textContent = bookmarks.length
      ? "Keine passenden Bookmarks gefunden."
      : "Noch keine Manga-Bookmarks gespeichert.";
    list.append(empty);

    return;
  }

  visible.forEach((bookmark) => {
    const wrap = document.createElement("div");

    wrap.className = "bookmark-entry-wrap";
    wrap.classList.toggle("editing", state.bookmarkEditMode);

    const button = document.createElement("button");

    button.type = "button";
    button.className = "history-entry bookmark-entry";
    button.title = bookmark.url;
    const title = document.createElement("span");

    title.className = "history-title";
    title.textContent = bookmark.title;
    const meta = document.createElement("span");

    meta.className = "history-meta";
    const last = bookmark.last_read_at
      ? `Zuletzt gelesen: ${formatReadDate(bookmark.last_read_at)}`
      : "Noch kein Chapter gelesen";
    meta.textContent = last;
    button.append(title);

    const newest = (bookmark.new_chapters || [])[0];
    if (newest) {
      const update = document.createElement("span");

      update.className = "bookmark-new-chapter";
      const suffix = bookmark.new_chapters.length > 1
        ? ` (+${bookmark.new_chapters.length - 1})`
        : "";
      update.textContent = `New Chapter ${newest.chapter || newest.label}${suffix}`;
      button.append(update);
    }

    button.append(meta);

    button.addEventListener("click", () => openBookmark(bookmark));

    wrap.append(button);

    if (state.bookmarkEditMode) {
      const remove = document.createElement("button");

      remove.type = "button";
      remove.className = "bookmark-entry-remove";
      remove.textContent = "×";
      const removeLabel = window.LingoVeilI18n?.t("Bookmark entfernen")

        || "Bookmark entfernen";
      remove.setAttribute("aria-label", `${removeLabel}: ${bookmark.title}`);

      remove.title = removeLabel;
      remove.addEventListener("click", () => openBookmarkRemoval(bookmark, "sidebar"));

      wrap.append(remove);
    }

    list.append(wrap);
  });
}

function setLibraryTab(tab) {
  state.libraryTab = tab === "bookmarks" ? "bookmarks" : "history";
  const bookmarksActive = state.libraryTab === "bookmarks";
  $("history-list").classList.toggle("hidden", bookmarksActive);

  $("bookmark-list").classList.toggle("hidden", !bookmarksActive);

  $("tab-history").classList.toggle("active", !bookmarksActive);

  $("tab-bookmarks").classList.toggle("active", bookmarksActive);

  $("tab-history").setAttribute("aria-selected", String(!bookmarksActive));

  $("tab-bookmarks").setAttribute("aria-selected", String(bookmarksActive));

  $("bookmark-search-wrap").classList.toggle("hidden", !bookmarksActive);

  $("btn-bookmarks-refresh").classList.toggle("hidden", !bookmarksActive);

  $("btn-bookmarks-edit").classList.toggle("hidden", !bookmarksActive);

  if (!bookmarksActive && state.bookmarkEditMode) {
    state.bookmarkEditMode = false;
    $("btn-bookmarks-edit").classList.remove("active");

    $("btn-bookmarks-edit").setAttribute("aria-pressed", "false");

    $("btn-bookmarks-edit").textContent = "✎";
    renderBookmarks(state.bookmarks);
  }

  $("library-count").textContent = String(
    bookmarksActive
      ? state.bookmarks.length
      : $("history-list").querySelectorAll(".history-entry").length
  );
}

async function refreshBookmarkUpdates() {
  const button = $("btn-bookmarks-refresh");

  if (button.disabled) return;
  button.disabled = true;
  button.classList.add("checking");

  setStatus("Bookmarks werden auf neue Chapter geprüft …");

  try {
    const result = await api("/api/bookmarks/check-updates", {method: "POST"});

    await loadBookmarks();

    if (result.status === "running") {
      setStatus("Die Bookmark-Prüfung läuft bereits.");
    } else {
      const errors = result.errors?.length ? ` · ${result.errors.length} Fehler` : "";
      setStatus(
        `${result.checked} Bookmark(s) geprüft · ` +
        `${result.new_chapters} neue Chapter${errors}`
      );
    }
  } catch (err) {
    if (isTransientNetworkError(err)) {
      setStatus("Verbindung kurz unterbrochen · Bookmark-Prüfung läuft serverseitig weiter");
    } else {
      showUrlLoadError(`Bookmarks konnten nicht geprüft werden.\n\n${err.message}`);
    }
  } finally {
    button.disabled = false;
    button.classList.remove("checking");
  }
}

async function openBookmark(bookmark) {
  if (state.processing) return;
  showMangaCatalogLoading(bookmark);

  setProcessing(true);

  setStatus("Bookmark wird geöffnet …");

  try {
    const catalog = await api("/api/url/manga-catalog", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url: bookmark.url}),
    });

    if (!catalog.is_catalog) {
      throw new Error("Für diesen Bookmark ist keine Chapter-Auswahl verfügbar.");
    }

    showMangaCatalog(catalog);

    setStatus(`${catalog.title}: Chapter auswählen`);
  } catch (err) {
    showMangaCatalogError(bookmark, err);

    setStatus("Bookmark konnte nicht geöffnet werden.");
  } finally {
    setProcessing(false);
  }
}

function showMangaCatalogLoading(bookmark) {
  const dialog = $("manga-catalog-dialog");

  const content = $("manga-catalog-content");

  $("manga-catalog-title").textContent = bookmark.title || "Chapter auswählen";
  $("manga-catalog-site").textContent = "Chapter werden geladen";
  content.className = "manga-catalog-content catalog-loading";
  content.setAttribute("aria-busy", "true");

  content.setAttribute("aria-live", "polite");

  const loading = document.createElement("div");

  loading.className = "manga-catalog-loading-state";
  const spinner = document.createElement("span");

  spinner.className = "manga-catalog-spinner";
  spinner.setAttribute("aria-hidden", "true");

  const title = document.createElement("strong");

  title.textContent = "Chapter werden geladen …";
  const hint = document.createElement("span");

  hint.textContent = "Der aktuelle Katalog wird von der Quellseite abgerufen.";
  loading.append(spinner, title, hint);

  content.replaceChildren(loading);

  if (!dialog.open) dialog.showModal();
}

function showMangaCatalogError(bookmark, error) {
  const content = $("manga-catalog-content");

  content.className = "manga-catalog-content catalog-error";
  content.removeAttribute("aria-busy");

  const stateNode = document.createElement("div");

  stateNode.className = "manga-catalog-error-state";
  const title = document.createElement("strong");

  title.textContent = "Chapter konnten nicht geladen werden";
  const message = document.createElement("span");

  message.textContent = error?.message || "Unbekannter Fehler";
  const retry = document.createElement("button");

  retry.type = "button";
  retry.className = "primary";
  retry.textContent = "Erneut versuchen";
  retry.addEventListener("click", () => void openBookmark(bookmark));

  stateNode.append(title, message, retry);

  content.replaceChildren(stateNode);
}

function updateActiveHistoryEntry() {
  document.querySelectorAll(".history-entry").forEach((entry) => {
    const active = entry.dataset.historyId === state.activeHistoryEntryId;
    entry.classList.toggle("active", active);

    if (active) entry.setAttribute("aria-current", "page");

    else entry.removeAttribute("aria-current");
  });
}

async function openHistoryEntry(entryId) {
  if (state.processing) return;
  setProcessing(true);

  clearFieldErrors();

  setStatus("History wird geöffnet …");

  try {
    const result = await api(`/api/history/${entryId}/open`, {method: "POST"});

    $("url-page").value = result.url || "";
    state.galleryImages = (result.images || []).map((item, index) => ({
      id: item.id,
      history_id: item.history_id || result.history_id || entryId,
      preview_url: item.preview_url,
      url: item.url,
      width: item.width || 0,
      height: item.height || 0,
      translated_engines: item.translated_engines || [],
      cached_translations: item.cached_translations || {},
      index,
    }));

    state.selectedPageImageId = null;
    state.lastResult = null;
    state.activeHistoryEntryId = result.history_id || entryId;
    state.chapterNavigation = result.chapter_navigation || null;
    updateActiveHistoryEntry();

    setPreviewEmpty();

    renderGallery();

    enqueuePrefetchImages(state.galleryImages, selectedEngine());

    setStatus(`${state.galleryImages.length} Bilder aus History geladen`);

    if (state.chapterNavigation?.enabled && state.galleryImages.length) {
      setProcessing(false);

      await selectGalleryImage(state.galleryImages[0].id);
    }
  } catch (err) {
    setStatus(`History-Fehler: ${err.message}`);
  } finally {
    setProcessing(false);
  }
}

window.addEventListener("lingoveil:settings-updated", (event) => {
  state.prefetchCount = Math.max(0, Math.min(100, Number(event.detail?.prefetch_count ?? 10)));

  translationCacheTtlMs = Math.max(
    30, Math.min(3600, Number(event.detail?.browser_cache_ttl_sec ?? 300))

  ) * 1000;
  const nextTarget = String(event.detail?.target_language || "deu");

  if (nextTarget !== state.targetLanguage) {
    translationCache.forEach(revokeCacheEntry);

    translationCache.clear();

    state.targetLanguage = nextTarget;
    renderGallery();
  }

  void configureEngineOptions(event.detail, {is_admin: true});

  enqueuePrefetchImages(state.galleryImages, selectedEngine());
});

window.addEventListener("lingoveil:history-cleared", () => {
  state.activeHistoryEntryId = null;
  renderHistory([]);
});

async function api(path, options = {}) {
  const headers = {
    ...authHeaders(),
    ...(options.headers || {}),
  };

  const response = await fetch(path, { ...options, headers });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    if (response.status === 401) {
      window.location.replace("/login.html");
    }

    const err = new Error(data.error || data.detail || `HTTP ${response.status}`);

    console.error("API-Fehler:", path, err.message, data);

    throw err;
  }

  return data;
}

function isTransientNetworkError(err) {
  return err instanceof TypeError || err?.message === "Failed to fetch";
}

async function runTranslationBackgroundJob(kind, payload) {
  let job;
  while (!job) {
    try {
      job = await api(`/api/translation-jobs/${kind}`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload),
      });
    } catch (err) {
      if (!isTransientNetworkError(err)) throw err;
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }

  while (true) {
    let current;
    try {
      current = await api(`/api/translation-jobs/${encodeURIComponent(job.job_id)}`);
    } catch (err) {
      if (!isTransientNetworkError(err)) throw err;
      await new Promise((resolve) => setTimeout(resolve, 1000));

      continue;
    }

    if (current.status === "succeeded") return current.result;
    if (current.status === "failed" || current.status === "cancelled") {
      throw new Error(current.error || "Der Übersetzungsauftrag ist fehlgeschlagen.");
    }

    await new Promise((resolve) => setTimeout(resolve, 750));
  }
}

async function connectSession(code, { silent = false } = {}) {
  const candidateCode = normalizeSessionCode(code);

  state.sessionCode = candidateCode;
  $("session-code-input").value = candidateCode;
  if (!sessionToken && candidateCode && candidateCode.length !== 4) {
    setSessionPanelConnected(false);

    if (!silent) {
      setSessionHint("Bitte genau 4 Ziffern eingeben.", { error: true });

      setStatus("Bitte Zugangscode eingeben.");
    }

    return false;
  }

  try {
    const status = await api("/api/status");

    state.sessionCode = candidateCode;
    setSessionPanelConnected(true);

    setAppInteractive(true);

    window.dispatchEvent(new CustomEvent("lingoveil:authenticated", {
      detail: { code: state.sessionCode, token: sessionToken },
    }));

    $("session-code-input").value = "";
    if (!sessionToken && window.location.search) {
      window.history.replaceState({}, document.title, window.location.pathname);
    }

    const deviceUrl = status.lan_urls?.[0] || status.local_url || "Verbunden";
    const portText = deviceUrl.replace(/^https?:\/\//, "");

    setSessionHint(`Verbunden mit ${portText}. Code akzeptiert.`);

    if (status.active_engine) {
      state.confirmedEngine = status.active_engine;
      updateEngineBadge({ mode: "selected", engineId: status.active_engine });
    }

    return true;
  } catch (err) {
    setSessionPanelConnected(false);

    setAppInteractive(false);

    if (!silent) {
      setSessionHint(`Verbindung fehlgeschlagen: ${err.message}`, { error: true });

      setStatus(`Verbindung fehlgeschlagen: ${err.message}`);
    }

    return false;
  }
}

function selectedEngine() {
  return $("engine-select").value;
}

function fallbackToBergamot() {
  $("engine-select").value = "bergamot";
  saveEngineChoice("bergamot");

  updateEngineBadge({ mode: "selected", engineId: "bergamot" });
}

async function persistEngineSelection(engine) {
  return api("/api/settings/engine", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({engine}),
  });
}

function showEngineUnavailable(message) {
  fallbackToBergamot();

  delete $("engine-error-dialog").dataset.noFallback;
  $("engine-error-fallback-hint").hidden = false;
  clearFieldErrors();

  setStatus("Bergamot lokal ausgewählt");

  $("engine-error-message").textContent = message;
  const dialog = $("engine-error-dialog");

  if (!dialog.open) dialog.showModal();
}

function showOllamaUnavailable() {
  const option = $("engine-select")?.querySelector('option[value="ollama"]');

  if (option) option.disabled = true;
  const dialog = $("ollama-error-dialog");

  if (dialog && !dialog.open) dialog.showModal();
}

function showEngineConfigurationError(message) {
  clearFieldErrors();

  $("engine-error-message").textContent = message;
  const dialog = $("engine-error-dialog");

  dialog.dataset.noFallback = "true";
  $("engine-error-fallback-hint").hidden = true;
  if (!dialog.open) dialog.showModal();
}

function showUrlLoadError(message, context = "foreground") {
  if (state.urlErrorContext === context) return;
  state.urlErrorContext = context;
  clearFieldErrors();

  setStatus(`Inhalt konnte nicht geladen werden: ${message}`);

  $("url-error-message").textContent = message;
  const dialog = $("url-error-dialog");

  if (!dialog.open) dialog.showModal();
}

function formatReadDate(value) {
  if (!value) return "";
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

async function toggleCatalogBookmark(catalog) {
  if (catalog.bookmarked) {
    openBookmarkRemoval(catalog, "catalog");

    return;
  }

  try {
    await api("/api/bookmarks", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        url: catalog.url,
        title: catalog.title,
        site: catalog.site,
      }),
    });

    catalog.bookmarked = true;
    await loadBookmarks();

    showMangaCatalog(catalog, {preserveOrder: true});
  } catch (err) {
    showUrlLoadError(`Bookmark konnte nicht gespeichert werden.\n\n${err.message}`);
  }
}

function openBookmarkRemoval(bookmark, source = "catalog") {
  state.pendingBookmarkRemoval = {bookmark, source};

  const english = window.LingoVeilI18n?.language === "en";
  $("bookmark-remove-message").textContent = english
    ? `Remove “${bookmark.title}” from bookmarks?`
    : `„${bookmark.title}“ aus den Bookmarks entfernen?`;
  const dialog = $("bookmark-remove-dialog");

  if (!dialog.open) dialog.showModal();
}

async function confirmBookmarkRemoval(deleteReadingData) {
  const pending = state.pendingBookmarkRemoval;
  if (!pending) return;
  const {bookmark, source} = pending;
  try {
    await api("/api/bookmarks", {
      method: "DELETE",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        url: bookmark.url,
        delete_reading_data: deleteReadingData,
      }),
    });

    bookmark.bookmarked = false;
    if (state.chapterNavigation?.manga_url === bookmark.url) {
      state.chapterNavigation = null;
      updateChapterNavButtons();
    }

    if (deleteReadingData) {
      bookmark.last_read_url = "";
      bookmark.last_read_at = "";
      bookmark.read_chapters = {};
    }

    $("bookmark-remove-dialog").close();

    state.pendingBookmarkRemoval = null;
    await loadBookmarks();

    if (source === "catalog") {
      showMangaCatalog(bookmark, {preserveOrder: true});
    }
  } catch (err) {
    showUrlLoadError(`Bookmark konnte nicht entfernt werden.\n\n${err.message}`);
  }
}

function showMangaCatalog(catalog, {preserveOrder = false} = {}) {
  const dialog = $("manga-catalog-dialog");

  const content = $("manga-catalog-content");

  state.currentCatalog = catalog;
  if (!preserveOrder) state.catalogSortAscending = false;
  $("manga-catalog-title").textContent = catalog.title || "Chapter auswählen";
  $("manga-catalog-site").textContent = {
    mangadex: "MangaDex",
    mangatown: "MangaTown",
    mangaread: "MangaRead",
  }[catalog.site] || "";
  content.removeAttribute("aria-busy");

  content.className = "manga-catalog-content";
  content.replaceChildren();

  content.classList.toggle(
    "single-group",
    (catalog.groups || []).length === 1,
  );

  let groups = (catalog.groups || []).map((group) => ({
    ...group,
    chapters: [...(group.chapters || [])],
  }));

  if (state.catalogSortAscending) {
    groups = groups.reverse().map((group) => ({
      ...group,
      chapters: [...group.chapters].reverse(),
    }));
  }

  groups.forEach((group, groupIndex) => {
    const section = document.createElement("details");

    section.className = "manga-catalog-group";
    section.open = catalog.groups.length === 1 || groupIndex === 0;
    const summary = document.createElement("summary");

    const count = (group.chapters || []).length;
    const summaryLabel = document.createElement("span");

    summaryLabel.textContent = `${group.label || "Chapter"} (${count})`;
    summary.append(summaryLabel);

    if (groupIndex === 0) {
      const controls = document.createElement("span");

      controls.className = "manga-catalog-summary-actions";
      const order = document.createElement("button");

      order.type = "button";
      order.className = "manga-order-button";
      order.textContent = state.catalogSortAscending
        ? "Reihenfolge: invertiert"
        : "Reihenfolge: aktuell";
      order.addEventListener("click", (event) => {
        event.preventDefault();

        event.stopPropagation();

        state.catalogSortAscending = !state.catalogSortAscending;
        showMangaCatalog(catalog, {preserveOrder: true});
      });

      const bookmark = document.createElement("button");

      bookmark.type = "button";
      bookmark.className = "manga-bookmark-button";
      bookmark.classList.toggle("bookmarked", Boolean(catalog.bookmarked));

      bookmark.textContent = catalog.bookmarked ? "✓ Bookmarked" : "Bookmark this";
      bookmark.addEventListener("click", (event) => {
        event.preventDefault();

        event.stopPropagation();

        void toggleCatalogBookmark(catalog);
      });

      controls.append(order, bookmark);

      summary.append(controls);
    }

    const chapters = document.createElement("div");

    chapters.className = "manga-chapter-list";
    (group.chapters || []).forEach((chapter) => {
      const button = document.createElement("button");

      button.type = "button";
      button.className = "manga-chapter-entry";
      const label = document.createElement("span");

      label.textContent = chapter.label || `Chapter ${chapter.chapter || ""}`;
      button.append(label);

      if (chapter.url === catalog.last_read_url) {
        button.classList.add("last-read");

        const readAt = document.createElement("small");

        readAt.textContent = `Zuletzt gelesen: ${formatReadDate(catalog.last_read_at)}`;
        button.append(readAt);
      }

      button.title = chapter.url;
      button.addEventListener("click", () => {
        $("url-page").value = chapter.url;
        dialog.close();

        $("btn-analyze-page").click();
      });

      chapters.append(button);
    });

    section.append(summary, chapters);

    content.append(section);
  });

  if (!preserveOrder) {
    content.classList.add("catalog-reveal");

    requestAnimationFrame(() => {
      requestAnimationFrame(() => content.classList.add("is-visible"));
    });
  }

  if (!dialog.open) dialog.showModal();
}

async function configureEngineOptions(settings, user) {
  const select = $("engine-select");

  const lmStudioOption = select?.querySelector('option[value="lm_studio"]');

  const ollamaOption = select?.querySelector('option[value="ollama"]');

  await refreshSeamlessAvailability();

  if (lmStudioOption) {
    const configured = Boolean(
      user?.is_admin && settings?.lm_studio_base_url && settings?.lm_studio_model
    );

    lmStudioOption.hidden = !configured;
    lmStudioOption.disabled = !configured;
    lmStudioOption.title = configured ? "" : "LM Studio ist noch nicht konfiguriert.";
  }

  if (ollamaOption) {
    const available = settings?.ollama_status === "AVAILABLE";
    ollamaOption.disabled = !available;
    ollamaOption.title = available ? "" : "Ollama muss zuerst erfolgreich getestet werden.";
  }

  const selectedOption = select?.selectedOptions?.[0];
  if (selectedOption?.value === "ollama" && selectedOption.disabled) {
    showOllamaUnavailable();
  } else if (!selectedOption || selectedOption.disabled || selectedOption.hidden) {
    fallbackToBergamot();

    await persistEngineSelection("bergamot");
  }
}

let seamlessAvailabilityRequest = null;
function refreshSeamlessAvailability() {
  if (seamlessAvailabilityRequest) return seamlessAvailabilityRequest;
  const seamlessOption = $("engine-select")?.querySelector('option[value="seamless_m4t"]');

  if (!seamlessOption) return Promise.resolve(false);

  seamlessAvailabilityRequest = api("/api/engines/seamless_m4t/availability")

    .then((availability) => {
      seamlessOption.disabled = !availability.available;
      seamlessOption.title = availability.reason || "";
      return Boolean(availability.available);
    })

    .catch((error) => {
      seamlessOption.disabled = true;
      seamlessOption.title = error.message;
      return false;
    })

    .finally(() => { seamlessAvailabilityRequest = null; });

  return seamlessAvailabilityRequest;
}

async function validateEngineSelection() {
  const engine = selectedEngine();

  const option = $("engine-select").selectedOptions[0];
  if (option?.disabled || option?.hidden) {
    if (engine === "ollama") {
      showOllamaUnavailable();

      return false;
    }

    fallbackToBergamot();

    return false;
  }

  if (engine === "bergamot") {
    saveEngineChoice(engine);

    await persistEngineSelection(engine);

    return true;
  }

  $("engine-select").disabled = true;
  try {
    const result = await api(`/api/engines/${engine}/availability`);

    if (!result.available) {
      showEngineUnavailable(result.reason || `${engineLabel(engine)} ist nicht verfügbar.`);

      return false;
    }

    saveEngineChoice(engine);

    await persistEngineSelection(engine);

    return true;
  } catch (err) {
    if (engine === "ollama") {
      showEngineConfigurationError(err.message);
    } else {
      showEngineUnavailable(`${engineLabel(engine)} konnte nicht geprüft werden: ${err.message}`);
    }

    return false;
  } finally {
    $("engine-select").disabled = false;
  }
}

function engineLabel(engineId) {
  return ENGINE_LABELS[engineId] || engineId;
}

function updateEngineBadge({ mode = "selected", engineId = null } = {}) {
  const badge = $("engine-badge");

  if (!badge) return;
  const engine = engineId || selectedEngine();

  badge.classList.remove(
    "engine-bergamot",
    "engine-seamless_m4t",
    "engine-lm_studio",
    "engine-ollama",
    "confirmed",
    "processing"
  );

  badge.classList.add(`engine-${engine}`);

  if (mode === "processing") {
    badge.classList.add("processing");

    badge.textContent = `Übersetzt: ${engineLabel(engine)} …`;
    badge.title = `Übersetzung läuft mit ${engineLabel(engine)}`;
    return;
  }

  if (mode === "confirmed") {
    badge.classList.add("confirmed");

    badge.textContent = `Verwendet: ${engineLabel(engine)}`;
    badge.title = `Zuletzt bestätigt vom Server: ${engineLabel(engine)}`;
    return;
  }

  badge.textContent = `Auswahl: ${engineLabel(engine)}`;
  badge.title = `Ausgewählte Engine: ${engineLabel(engine)}`;
}

function selectedSource() {
  return "page_analyze";
}

function isTextInputFocused() {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

function updateSourcePanels() {
  state.source = "page_analyze";
  clearFieldErrors();
}

function formatEngineUsed(result) {
  if (result.engine) return engineLabel(result.engine);

  if (result.engine_display_name) return result.engine_display_name;
  return engineLabel(selectedEngine());
}

function updatePreviewMeta() {
  updatePreviewContext();
}

function updatePreviewContext() {
  const navigation = state.chapterNavigation || {};

  const bookmarkedChapter = Boolean(navigation.enabled && navigation.manga_title);

  $("preview-title").textContent = bookmarkedChapter
    ? navigation.manga_title
    : "Vorschau";
  const meta = $("preview-meta");

  const imageIndex = getFilteredImages().findIndex(
    (item) => item.id === state.selectedPageImageId
  );

  const imageLabel = imageIndex >= 0 ? `#${imageIndex + 1}` : "";
  const chapterLabel = bookmarkedChapter
    ? navigation.chapter_label || "Chapter"
    : "";
  meta.textContent = [chapterLabel, imageLabel].filter(Boolean).join(" - ");
}

function hasPreviewContent() {
  return Boolean(state.currentTranslatedSrc || state.currentOriginalSrc);
}

function syncZoomControls() {
  const slider = $("zoom-slider");

  const label = $("zoom-label");

  const pct = Math.round((state.previewZoom || 1) * 100);

  slider.value = String(pct);

  label.textContent = `${pct} %`;
  slider.disabled = !hasPreviewContent();
}

const PREVIEW_ZOOM_MIN = 0.25;
const PREVIEW_ZOOM_MAX = 3;
function clampPreviewZoom(zoom) {
  return Math.min(PREVIEW_ZOOM_MAX, Math.max(PREVIEW_ZOOM_MIN, zoom));
}

function getEffectivePreviewZoom() {
  if (state.previewMode === "zoom") return state.previewZoom || 1;
  const img = $("preview-image");

  const nw = img.naturalWidth || 0;
  if (nw <= 0) return 1;
  return img.getBoundingClientRect().width / nw;
}

function applyPanTransform() {
  const layer = $("preview-pan-layer");

  layer.style.setProperty("--pan-x", `${state.panX}px`);

  layer.style.setProperty("--pan-y", `${state.panY}px`);
}

function resetPreviewPan() {
  state.panX = 0;
  state.panY = 0;
  applyPanTransform();
}

function resetPreviewFit() {
  state.previewMode = "fit";
  state.previewZoom = 1;
  state.lastAppliedZoom = 0;
  resetPreviewPan();

  if (hasPreviewContent()) {
    applyPreviewMode({ resetPan: true });
  }
}

function applyPreviewMode({ resetPan = false, keepPan = false } = {}) {
  const viewport = $("preview-viewport");

  const img = $("preview-image");

  const nw = img.naturalWidth || 0;
  const zoom = state.previewZoom || 1;
  if (resetPan || (!keepPan && zoom !== state.lastAppliedZoom)) {
    resetPreviewPan();
  }

  state.lastAppliedZoom = zoom;
  viewport.classList.remove("viewport-fit", "viewport-scroll", "is-panning");

  img.classList.remove("preview-fit", "preview-sized");

  img.style.width = "";
  img.style.height = "";
  img.style.maxWidth = "";
  img.style.maxHeight = "";
  img.style.transform = "";
  if (state.previewMode === "fit") {
    viewport.classList.add("viewport-fit");

    img.classList.add("preview-fit");

    const pad = 16;
    img.style.maxWidth = `${Math.max(1, viewport.clientWidth - pad)}px`;
    img.style.maxHeight = `${Math.max(1, viewport.clientHeight - pad)}px`;
  } else {
    viewport.classList.add("viewport-scroll");

    img.classList.add("preview-sized");

    if (nw > 0) {
      img.style.width = `${Math.round(nw * zoom)}px`;
    }
  }

  $("btn-fit").classList.toggle("active-tool", state.previewMode === "fit");

  syncZoomControls();

  applyPanTransform();
}

function setPreviewPlaceholderMode(mode, message = "") {
  const viewport = $("preview-viewport");

  const placeholder = $("preview-placeholder");

  const idle = $("preview-placeholder-idle");

  const loading = $("preview-placeholder-loading");

  const loadingText = $("preview-loading-text");

  setPreviewProcessing(false);

  $("preview-pan-layer").classList.add("hidden");

  placeholder.classList.remove("hidden");

  viewport.classList.add("viewport-empty", "viewport-fit");

  viewport.classList.remove("viewport-scroll", "is-panning");

  if (mode === "loading") {
    idle.classList.add("hidden");

    loading.classList.remove("hidden");

    loadingText.textContent = message || "Wird geladen …";
  } else {
    idle.classList.remove("hidden");

    loading.classList.add("hidden");
  }
}

function setPreviewLoading(message = "Wird geladen …") {
  setPreviewPlaceholderMode("loading", message);

  $("btn-toggle-translation").disabled = true;
}

function setPreviewEmpty() {
  setPreviewPlaceholderMode("idle");

  $("btn-toggle-translation").disabled = true;
  state.currentTranslatedSrc = null;
  state.currentOriginalSrc = null;
  resetPreviewPan();

  updateTranslationToggleButton();
}

function setPreviewProcessing(active, message = "Wird gerade übersetzt …") {
  const viewport = $("preview-viewport");

  const overlay = $("preview-processing-overlay");

  const text = $("preview-processing-text");

  viewport.classList.toggle("preview-processing", active);

  overlay.classList.toggle("hidden", !active);

  if (active) text.textContent = message;
}

function updateTranslationToggleButton() {
  const btn = $("btn-toggle-translation");

  const hasPreview = Boolean(state.currentTranslatedSrc || state.currentOriginalSrc);

  btn.disabled = !hasPreview;
  btn.classList.toggle("active-off", hasPreview && !state.translationVisible);

  const label = state.translationVisible ? "Übersetzung aus" : "Übersetzung an";
  btn.textContent = window.LingoVeilI18n?.t(label) || label;
}

function setPreviewSources(
  translatedSrc,
  originalSrc,
  { resetView = false, processing = false } = {},
) {
  state.currentTranslatedSrc = translatedSrc || null;
  state.currentOriginalSrc = originalSrc || translatedSrc || null;
  setPreviewProcessing(processing);

  updateTranslationToggleButton();

  applyTranslationVisibility({ resetView });
}

function applyTranslationVisibility({ resetView = false } = {}) {
  const src = state.translationVisible
    ? state.currentTranslatedSrc || state.currentOriginalSrc
    : state.currentOriginalSrc || state.currentTranslatedSrc;
  if (!src) {
    setPreviewEmpty();

    return;
  }

  showPreviewImage(src, null, { preservePan: !resetView });
}

function showPreviewImage(src, onReady, { preservePan = false } = {}) {
  const img = $("preview-image");

  const placeholder = $("preview-placeholder");

  const panLayer = $("preview-pan-layer");

  const viewport = $("preview-viewport");

  viewport.classList.remove("viewport-empty");

  placeholder.classList.add("hidden");

  const savedPanX = state.panX;
  const savedPanY = state.panY;
  const finishLoad = () => {
    panLayer.classList.remove("hidden");

    applyPreviewMode({ resetPan: !preservePan });

    if (preservePan) {
      state.panX = savedPanX;
      state.panY = savedPanY;
      applyPanTransform();
    }

    updateTranslationToggleButton();

    if (onReady) onReady();
  };

  if (preservePan && img.src === src && img.complete && img.naturalWidth > 0) {
    finishLoad();

    return;
  }

  img.onload = finishLoad;
  if (img.src !== src) {
    img.src = src;
  } else if (img.complete && img.naturalWidth > 0) {
    finishLoad();
  }
}

function applyCachedPreview(cached) {
  state.lastResult = cached.result;
  setPreviewSources(cached.blobUrl, cached.originalSrc || cached.blobUrl, { resetView: true });

  updatePreviewMeta(cached.result, true);
}

async function updatePreview(imageId = null, result = null) {
  const renderedPath = result?.rendered_url
    || (imageId ? null : `/api/rendered?t=${Date.now()}`);

  if (!renderedPath) {
    throw new Error("Der Übersetzungsjob hat kein benutzerspezifisches Rendering geliefert.");
  }

  const renderedUrl = withAuth(renderedPath);

  const originalSrc = await resolveOriginalSource(imageId);

  setPreviewSources(renderedUrl, originalSrc || renderedUrl, { resetView: true });
}

function isSmallIcon(item) {
  const w = item.width || 0;
  const h = item.height || 0;
  return w > 0 && h > 0 && (w < 120 || h < 120);
}

function getFilteredImages() {
  return state.galleryImages;
}

function updateGalleryCount() {
  const total = state.galleryImages.length;
  if (total === 0) {
    $("gallery-count").textContent = "0 Bilder";
  } else {
    $("gallery-count").textContent = `${total} Bild${total === 1 ? "" : "er"} gefunden`;
  }
}

function updateGallerySelectionLabel() {
  if (!state.selectedPageImageId) {
    $("selected-image-label").textContent = "Kein Bild ausgewählt";
    $("btn-translate-gallery").disabled = true;
    return;
  }

  const item = state.galleryImages.find((i) => i.id === state.selectedPageImageId);

  const idx = item ? item.index + 1 : "?";
  const dims = item && item.width ? ` (${item.width}×${item.height})` : "";
  $("selected-image-label").textContent = `Ausgewähltes Bild: #${idx}${dims}`;
  $("btn-translate-gallery").disabled = state.processing;
}

function updateGalleryNavButtons() {
  const filtered = getFilteredImages();

  const idx = filtered.findIndex((i) => i.id === state.selectedPageImageId);

  $("btn-preview-prev").disabled = idx <= 0 || state.processing;
  $("btn-preview-next").disabled = idx < 0 || idx >= filtered.length - 1 || state.processing;
  updateChapterNavButtons();
}

function updateChapterNavButtons() {
  const navigation = state.chapterNavigation || {};

  const previousDisabled =
    state.processing || !navigation.enabled || !navigation.previous_url;
  const nextDisabled =
    state.processing || !navigation.enabled || !navigation.next_url;
  $("btn-preview-chapter-prev").disabled = previousDisabled;
  $("btn-preview-chapter-next").disabled = nextDisabled;
  updatePreviewContext();
}

function navigateChapter(direction) {
  if (state.processing) return;
  const navigation = state.chapterNavigation || {};

  const target = direction < 0
    ? navigation.previous_url
    : navigation.next_url;
  if (!navigation.enabled || !target) return;
  $("url-page").value = target;
  $("btn-analyze-page").click();
}

function scrollThumbIntoView(thumbEl) {
  if (!thumbEl) return;
  thumbEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function classifyInputUrl(url) {
  const trimmed = url.trim();

  const path = trimmed.split("?")[0].toLowerCase();

  if (/\.pdf$/i.test(path)) return "pdf";
  if (/\.(png|jpe?g|webp)$/i.test(path)) return "image";
  return "page";
}

function buildPdfGalleryItems(pdfId, pageCount) {
  return Array.from({ length: pageCount }, (_, index) => ({
    id: `${pdfId}_p${index}`,
    pdf_id: pdfId,
    page_number: index,
    preview_url: withAuth(`/api/pdf-preview/${pdfId}/${index}`),
    url: "",
    width: 0,
    height: 0,
    translated_engines: [],
    index,
  }));
}

async function processSelectedItem(engine, {force = false} = {}) {
  const item = state.selectedPageImageId ? galleryItemById(state.selectedPageImageId) : null;
  if (item?.pdf_id != null) {
    return runTranslationBackgroundJob("pdf-page", {
      pdf_id: item.pdf_id,
      page_number: item.page_number ?? 0,
      engine,
    });
  }

  if (!state.selectedPageImageId) {
    throw new Error("Bitte ein Bild auswählen.");
  }

  return runTranslationBackgroundJob("page-image", {
    image_id: state.selectedPageImageId,
    engine,
    force,
  });
}

async function selectGalleryImage(imageId, { autoTranslate = true } = {}) {
  if (state.processing) return;
  resetPreviewFit();

  state.selectedPageImageId = imageId;
  document.querySelectorAll(".thumb").forEach((t) => {
    t.classList.toggle("selected", t.dataset.id === imageId);
  });

  const thumb = document.querySelector(`.thumb[data-id="${imageId}"]`);

  scrollThumbIntoView(thumb);

  updateGallerySelectionLabel();

  updateGalleryNavButtons();

  const item = state.galleryImages.find((i) => i.id === imageId);

  if (item) setStatus(`Bild #${item.index + 1} ausgewählt`);

  if (autoTranslate && selectedSource() === "page_analyze") {
    await handleTranslate({ force: false });
  }
}

function createThumbElement(item, displayIndex) {
  const div = document.createElement("div");

  div.className = "thumb";
  div.dataset.id = item.id;
  if (isSmallIcon(item)) div.classList.add("thumb-small");

  const wrap = document.createElement("div");

  wrap.className = "thumb-img-wrap";
  const img = document.createElement("img");

  img.alt = `Bild ${displayIndex + 1}`;
  img.loading = "lazy";
  img.addEventListener("load", () => {
    if (!item.width) {
      item.width = img.naturalWidth;
      item.height = img.naturalHeight;
      if (isSmallIcon(item)) div.classList.add("thumb-small");

      const label = div.querySelector(".thumb-label");

      if (label && item.width) {
        updateThumbLabel(label, item);
      }
    }
  });

  img.addEventListener("error", () => {
    wrap.replaceChildren();

    const err = document.createElement("div");

    err.className = "thumb-error";
    err.textContent = "Ladefehler";
    wrap.appendChild(err);
  });

  if (item.preview_url) {
    if (item.pdf_id != null) {
      img.dataset.src = item.preview_url;
      observeThumbImage(img);
    } else {
      img.src = item.preview_url;
    }
  }

  wrap.appendChild(img);

  const label = document.createElement("div");

  label.className = "thumb-label";
  updateThumbLabel(label, item);

  div.appendChild(wrap);

  div.appendChild(label);

  div.addEventListener("click", () => selectGalleryImage(item.id));

  if (state.selectedPageImageId === item.id) div.classList.add("selected");

  return div;
}

function itemIsTranslated(item, engine = selectedEngine()) {
  if (Array.isArray(item?.translated_variants)) {
    return item.translated_variants.includes(translationVariantKey(engine));
  }

  return Array.isArray(item?.translated_engines) && item.translated_engines.includes(engine);
}

function engineTargetLanguage(engine = selectedEngine()) {
  if (engine === "seamless_m4t" || engine === "ollama") return state.targetLanguage;
  const targets = {
    bul: "bg", ces: "cs", deu: "de", spa: "es", est: "et",
    fra: "fr", ita: "it", por: "pt", rus: "ru", ukr: "uk",
  };

  return targets[state.targetLanguage] || "de";
}

function translationVariantKey(engine = selectedEngine()) {
  return `${engine}:${engineTargetLanguage(engine)}`;
}

function translationItemKey(imageId, engine = selectedEngine()) {
  return `${imageId}:${engine}`;
}

function itemIsTranslating(item, engine = selectedEngine()) {
  return Boolean(item?.id) && translatingItems.has(translationItemKey(item.id, engine));
}

function itemIsQueued(item, engine = selectedEngine()) {
  return Boolean(item?.id) && queuedTranslationItems.has(translationItemKey(item.id, engine));
}

function updateThumbLabel(label, item) {
  const dimText = item.width ? `${item.width}×${item.height}` : "…";
  const translating = itemIsTranslating(item);

  const queued = itemIsQueued(item);

  const translated = itemIsTranslated(item);

  const statusName = translating
    ? "translating"
    : queued
      ? "queued"
      : translated
        ? "translated"
        : "open";
  const statusText = translating
    ? "· Wird übersetzt …"
    : queued
      ? "· Warteschlange"
      : translated
        ? "· Übersetzt"
        : "· Offen";
  label.replaceChildren(document.createTextNode(`#${item.index + 1} · ${dimText}`));

  const status = document.createElement("span");

  status.className = `thumb-translation-status ${statusName}`;
  status.textContent = statusText;
  label.appendChild(status);
}

function setItemTranslating(imageId, engine, translating) {
  if (!imageId || !engine) return;
  const key = translationItemKey(imageId, engine);

  if (translating) translatingItems.add(key);

  else translatingItems.delete(key);

  const item = galleryItemById(imageId);

  const thumb = document.querySelector(`.thumb[data-id="${imageId}"]`);

  const label = thumb?.querySelector(".thumb-label");

  if (item && label) updateThumbLabel(label, item);
}

function updateQueuedItemStatus(imageId) {
  const item = galleryItemById(imageId);

  const thumb = document.querySelector(`.thumb[data-id="${imageId}"]`);

  const label = thumb?.querySelector(".thumb-label");

  if (item && label) updateThumbLabel(label, item);
}

function markItemTranslated(imageId, engine) {
  const item = galleryItemById(imageId);

  if (!item || !engine) return;
  if (!Array.isArray(item.translated_engines)) item.translated_engines = [];
  if (!item.translated_engines.includes(engine)) item.translated_engines.push(engine);

  if (!Array.isArray(item.translated_variants)) item.translated_variants = [];
  const variant = translationVariantKey(engine);

  if (!item.translated_variants.includes(variant)) item.translated_variants.push(variant);

  const thumb = document.querySelector(`.thumb[data-id="${imageId}"]`);

  const label = thumb?.querySelector(".thumb-label");

  if (label) updateThumbLabel(label, item);

  const wrap = thumb?.querySelector(".thumb-img-wrap");

  if (wrap?.querySelector(".thumb-error")) {
    const img = document.createElement("img");

    img.alt = `Bild ${item.index + 1}`;
    img.loading = "lazy";
    img.draggable = false;
    img.addEventListener("load", () => {
      item.width = img.naturalWidth;
      item.height = img.naturalHeight;
      if (label) updateThumbLabel(label, item);
    });

    img.src = withAuth(`/api/page-image-preview/${imageId}?t=${Date.now()}`);

    wrap.replaceChildren(img);
  }
}

function renderGallery() {
  resetThumbPreviewQueue();

  const grid = $("page-images");

  grid.replaceChildren();

  const filtered = getFilteredImages();

  updateGalleryCount();

  $("gallery-empty").classList.toggle("hidden", filtered.length > 0);

  filtered.forEach((item, i) => {
    grid.appendChild(createThumbElement(item, i));
  });

  updateGallerySelectionLabel();

  updateGalleryNavButtons();
}

async function navigateGallery(delta) {
  if (state.processing) return;
  const filtered = getFilteredImages();

  if (!filtered.length) return;
  let idx = filtered.findIndex((i) => i.id === state.selectedPageImageId);

  if (idx < 0) idx = delta > 0 ? -1 : filtered.length;
  const next = filtered[idx + delta];
  if (next) await selectGalleryImage(next.id);
}

async function handleTranslate({ force = false } = {}) {
  if (state.processing) return;
  const engine = selectedEngine();

  const source = selectedSource();

  saveEngineChoice(engine);

  clearFieldErrors();

  if (source === "page_analyze" && state.selectedPageImageId && !force) {
    const cacheKey = pageImageCacheKey(state.selectedPageImageId, engine);

    let cached = getCachedTranslation(cacheKey);

    const selectedItem = galleryItemById(state.selectedPageImageId);

    const originalSrc = await resolveOriginalSource(state.selectedPageImageId);

    if (originalSrc) {
      setPreviewSources(null, originalSrc, {resetView: true});
    }

    if (!cached && itemIsTranslated(selectedItem, engine)) {
      setPreviewLoading("Gespeicherte Übersetzung wird geladen …");

      try {
        cached = await loadPersistentHistoryTranslation(selectedItem, engine);
      } catch (err) {
        console.warn("Persistente History-Übersetzung ist unvollständig:", err.message);
      }
    }

    if (!cached) {
      setPreviewProcessing(true);

      promoteQueuedTranslation(state.selectedPageImageId, engine);

      setStatus(
        itemIsTranslating(selectedItem, engine)

          ? `OCR & Übersetzung mit ${engineLabel(engine)} …`
          : "Ausgewähltes Bild wurde in der Warteschlange priorisiert …"
      );

      await waitForPrefetch(state.selectedPageImageId);

      cached = getCachedTranslation(cacheKey);
    }

    if (cached) {
      applyCachedPreview(cached);

      const groups = cached.result.group_count ?? cached.result.groups?.length ?? 0;
      const usedEngine = cached.result.engine || engine;
      markItemTranslated(state.selectedPageImageId, usedEngine);

      updateEngineBadge({ mode: "confirmed", engineId: usedEngine });

      setStatus(
        `Aus Zwischenspeicher – ${groups} Gruppe(n), Engine: ${formatEngineUsed(cached.result)}`
      );

      schedulePrefetch();

      return;
    }
  }

  setProcessing(true);

  const originalSrc = source === "page_analyze"
    ? await resolveOriginalSource(state.selectedPageImageId)

    : null;
  if (originalSrc) {
    setPreviewSources(null, originalSrc, {resetView: true, processing: true});
  } else {
    setPreviewLoading("Übersetzung läuft …");
  }

  updateEngineBadge({ mode: "processing", engineId: engine });

  setStatus(`Verarbeite mit ${engineLabel(engine)} …`);

  let prefetchAfterSuccess = false;
  let activeTranslationId = null;
  try {
    let result;
    if (source === "page_analyze") {
      if (!state.selectedPageImageId) throw new Error("Bitte ein Webseiten-Bild auswählen.");

      activeTranslationId = state.selectedPageImageId;
      setItemTranslating(activeTranslationId, engine, true);

      setStatus(`OCR & Übersetzung mit ${engineLabel(engine)} …`);

      result = await enqueueTranslation(
        () => processSelectedItem(engine, {force}),
        {
          key: translationItemKey(activeTranslationId, engine),
          priority: true,
        },
      );
    } else {
      throw new Error("Unbekannte Eingabequelle.");
    }

    state.lastResult = result;
    if (String(result.target_language || "") !== engineTargetLanguage(engine)) {
      throw new Error(
        "Die Zielsprache wurde während des Auftrags geändert; das veraltete Ergebnis wurde verworfen."
      );
    }

    state.confirmedEngine = result.engine || engine;
    const pageImageId = source === "page_analyze" ? state.selectedPageImageId : null;
    await updatePreview(pageImageId, result);

    updatePreviewMeta(result);

    updateEngineBadge({ mode: "confirmed", engineId: state.confirmedEngine });

    if (source === "page_analyze" && state.selectedPageImageId) {
      const cacheKey = pageImageCacheKey(state.selectedPageImageId, engine);

      await storeTranslationCache(cacheKey, result, state.selectedPageImageId);

      markItemTranslated(state.selectedPageImageId, result.engine || engine);

      prefetchAfterSuccess = true;
    }

    const groups = result.group_count ?? result.groups?.length ?? 0;
    const engineName = formatEngineUsed(result);

    const serverEngine = result.engine ? ` [${result.engine}]` : "";
    setStatus(`Fertig – ${groups} Gruppe(n) · ${engineName}${serverEngine}`);
  } catch (err) {
    setStatus(`Fehler: ${err.message}`);

    if (engine === "ollama") {
      showOllamaUnavailable();

      updateEngineBadge({ mode: "selected" });

      if (!state.currentTranslatedSrc) setPreviewEmpty();

      return;
    }

    showUrlLoadError(
      err.message,
      state.activeHistoryEntryId || state.selectedPageImageId || "translation",
    );

    updateEngineBadge({ mode: "selected" });

    if (!state.currentTranslatedSrc) setPreviewEmpty();
  } finally {
    setPreviewProcessing(false);

    if (activeTranslationId) setItemTranslating(activeTranslationId, engine, false);

    setProcessing(false);

    updateGalleryNavButtons();

    if (prefetchAfterSuccess) schedulePrefetch();
  }
}

$("engine-select").addEventListener("change", async () => {
  const available = await validateEngineSelection();

  if (!available) return;
  renderGallery();

  if (!state.processing) {
    updateEngineBadge({ mode: "selected" });

    if (state.lastResult && state.selectedPageImageId) {
      schedulePrefetch();
    }
  }
});

$("engine-select").addEventListener("pointerdown", () => {
  void refreshSeamlessAvailability();
});

$("engine-select").addEventListener("focus", () => {
  void refreshSeamlessAvailability();
});

window.addEventListener("lingoveil:models-updated", () => {
  void refreshSeamlessAvailability();
});

$("btn-engine-error-close").addEventListener("click", () => {
  $("engine-error-dialog").close();

  delete $("engine-error-dialog").dataset.noFallback;
  $("engine-error-fallback-hint").hidden = false;
});

$("btn-ollama-error-close").addEventListener("click", () => {
  $("ollama-error-dialog").close();
});

$("ollama-error-dialog").addEventListener("cancel", () => {
  $("ollama-error-dialog").close();
});

window.addEventListener("lingoveil:ollama-availability", (event) => {
  const option = $("engine-select")?.querySelector('option[value="ollama"]');

  if (option) option.disabled = !event.detail?.available;
});

$("engine-error-dialog").addEventListener("cancel", () => {
  if ($("engine-error-dialog").dataset.noFallback !== "true") fallbackToBergamot();

  delete $("engine-error-dialog").dataset.noFallback;
});

$("btn-url-error-close").addEventListener("click", () => {
  $("url-error-dialog").close();
});

$("btn-manga-catalog-close").addEventListener("click", () => {
  $("manga-catalog-dialog").close();
});

$("tab-history").addEventListener("click", () => setLibraryTab("history"));

$("tab-bookmarks").addEventListener("click", () => setLibraryTab("bookmarks"));

$("btn-bookmarks-refresh").addEventListener("click", () => {
  setLibraryTab("bookmarks");

  void refreshBookmarkUpdates();
});

$("btn-bookmarks-edit").addEventListener("click", () => {
  state.bookmarkEditMode = !state.bookmarkEditMode;
  const button = $("btn-bookmarks-edit");

  button.classList.toggle("active", state.bookmarkEditMode);

  button.setAttribute("aria-pressed", String(state.bookmarkEditMode));

  button.textContent = state.bookmarkEditMode ? "✓" : "✎";
  const editTitle = state.bookmarkEditMode ? "Bearbeiten beenden" : "Bookmarks bearbeiten";
  const translatedEditTitle = window.LingoVeilI18n?.t(editTitle) || editTitle;
  button.title = translatedEditTitle;
  button.setAttribute("aria-label", translatedEditTitle);

  renderBookmarks(state.bookmarks);
});

$("bookmark-search").addEventListener("input", () => renderBookmarks(state.bookmarks));

$("btn-bookmark-remove-cancel").addEventListener("click", () => {
  state.pendingBookmarkRemoval = null;
  $("bookmark-remove-dialog").close();
});

$("btn-bookmark-remove-keep").addEventListener("click", () => {
  void confirmBookmarkRemoval(false);
});

$("btn-bookmark-remove-delete").addEventListener("click", () => {
  void confirmBookmarkRemoval(true);
});

$("bookmark-remove-dialog").addEventListener("cancel", () => {
  state.pendingBookmarkRemoval = null;
});

$("btn-connect").addEventListener("click", () => {
  connectSession($("session-code-input").value);
});

$("session-code-input").addEventListener("input", (ev) => {
  ev.target.value = normalizeSessionCode(ev.target.value);
});

$("session-code-input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter") {
    ev.preventDefault();

    connectSession($("session-code-input").value);
  }
});

$("btn-translate-gallery").addEventListener("click", () => handleTranslate({ force: true }));

$("btn-analyze-page").addEventListener("click", async () => {
  const url = $("url-page").value.trim();

  state.urlErrorContext = null;
  clearFieldErrors();

  if (!url) {
    setFieldError("page_analyze", "Bitte URL eingeben.");

    return setStatus("Bitte URL eingeben.");
  }

  setProcessing(true);

  const inputKind = classifyInputUrl(url);

  setStatus(
    inputKind === "image"
      ? "Bild wird geladen …"
      : inputKind === "pdf"
        ? "PDF wird geladen …"
        : "Webseite wird analysiert …"
  );

  try {
    let galleryImages = [];
    let activeHistoryEntryId = null;
    let chapterNavigation = null;
    if (inputKind === "page") {
      const catalog = await api("/api/url/manga-catalog", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      if (catalog.is_catalog) {
        showMangaCatalog(catalog);

        setStatus(`${catalog.title || "Manga"}: Chapter auswählen`);

        return;
      }
    }

    if (inputKind === "image") {
      const result = await api("/api/url/image", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      galleryImages = [
        {
          id: result.image_id,
          preview_url: url,
          url,
          width: 0,
          height: 0,
          translated_engines: [],
          index: 0,
        },
      ];
    } else if (inputKind === "pdf") {
      const result = await api("/api/url/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      galleryImages = buildPdfGalleryItems(result.pdf_id, result.page_count || 0);
    } else {
      const result = await api("/api/url/page-images", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });

      activeHistoryEntryId = result.history_id || null;
      chapterNavigation = result.chapter_navigation || null;
      if (!result.images?.length) {
        setStatus(result.message || "Keine Bilder gefunden.");

        showUrlLoadError(
          result.message || "Auf der angegebenen Seite wurden keine ladbaren Bilder gefunden.",
          url,
        );

        state.galleryImages = [];
        renderGallery();

        return;
      }

      galleryImages = result.images.map((item, index) => ({
        id: item.id,
        history_id: item.history_id || result.history_id || null,
        preview_url: item.preview_url,
        url: item.url,
        width: item.width || 0,
        height: item.height || 0,
        translated_engines: item.translated_engines || [],
        cached_translations: item.cached_translations || {},
        index,
      }));
    }

    state.galleryImages = galleryImages;
    state.activeHistoryEntryId = activeHistoryEntryId;
    state.chapterNavigation = chapterNavigation;
    state.selectedPageImageId = null;
    state.lastResult = null;
    renderGallery();

    enqueuePrefetchImages(state.galleryImages, selectedEngine());

    if (!state.galleryImages.length) {
      setStatus("Keine Inhalte gefunden.");

      setFieldError("page_analyze", "Keine Inhalte gefunden.");

      return;
    }

    const countLabel =
      inputKind === "pdf"
        ? `${state.galleryImages.length} PDF-Seite(n) geladen`
        : inputKind === "image"
          ? "Direktes Bild geladen"
          : `${state.galleryImages.length} Bilder gefunden`;
    setStatus(countLabel);

    await loadHistory();

    await loadBookmarks();

    if (
      state.galleryImages.length === 1
      || (state.chapterNavigation?.enabled && state.galleryImages.length)

    ) {
      setProcessing(false);

      await selectGalleryImage(state.galleryImages[0].id);
    }
  } catch (err) {
    setStatus(`Fehler: ${err.message}`);

    showUrlLoadError(
      `Die angegebene Seite konnte nicht geladen werden.\n\n${err.message}`,
      url,
    );
  } finally {
    setProcessing(false);
  }
});

$("btn-fit").addEventListener("click", () => {
  state.previewMode = "fit";
  applyPreviewMode({ resetPan: true });
});

$("btn-preview-prev").addEventListener("click", () => navigateGallery(-1));

$("btn-preview-next").addEventListener("click", () => navigateGallery(1));

$("btn-preview-chapter-prev").addEventListener("click", () => navigateChapter(-1));

$("btn-preview-chapter-next").addEventListener("click", () => navigateChapter(1));

$("zoom-slider").addEventListener("input", () => {
  if (!hasPreviewContent()) return;
  const pct = Number($("zoom-slider").value);

  state.previewMode = "zoom";
  state.previewZoom = pct / 100;
  applyPreviewMode();
});

function initPreviewPan() {
  const viewport = $("preview-viewport");

  let dragging = false;
  let pinching = false;
  let startX = 0;
  let startY = 0;
  let startPanX = 0;
  let startPanY = 0;
  let pinchStartDistance = 0;
  let pinchStartZoom = 1;
  function pointerPoint(e) {
    if (e.touches && e.touches.length) return e.touches[0];
    if (e.changedTouches && e.changedTouches.length) return e.changedTouches[0];
    return e;
  }

  function touchDistance(touches) {
    const dx = touches[0].clientX - touches[1].clientX;
    const dy = touches[0].clientY - touches[1].clientY;
    return Math.hypot(dx, dy);
  }

  function touchCenter(touches) {
    return {
      x: (touches[0].clientX + touches[1].clientX) / 2,
      y: (touches[0].clientY + touches[1].clientY) / 2,
    };
  }

  function focalOffset(clientX, clientY) {
    const rect = viewport.getBoundingClientRect();

    return {
      x: clientX - rect.left - rect.width / 2,
      y: clientY - rect.top - rect.height / 2,
    };
  }

  function beginZoomModeFromFit() {
    const effectiveZoom = getEffectivePreviewZoom();

    state.previewMode = "zoom";
    state.previewZoom = clampPreviewZoom(effectiveZoom);

    applyPreviewMode({ resetPan: true });

    return effectiveZoom;
  }

  function applyZoomAtFocal(targetZoom, focalX, focalY, baseZoom, basePanX, basePanY) {
    const newZoom = clampPreviewZoom(targetZoom);

    const ratio = newZoom / baseZoom;
    const focal = focalOffset(focalX, focalY);

    state.previewMode = "zoom";
    state.previewZoom = newZoom;
    state.panX = basePanX + focal.x * (1 - ratio);

    state.panY = basePanY + focal.y * (1 - ratio);

    applyPreviewMode({ keepPan: true });

    applyPanTransform();

    syncZoomControls();
  }

  function applyPinchZoom(scale, focalX, focalY) {
    applyZoomAtFocal(
      pinchStartZoom * scale,
      focalX,
      focalY,
      pinchStartZoom,
      startPanX,
      startPanY,
    );
  }

  function zoomBaseFromCurrentMode() {
    if (state.previewMode === "fit") {
      return {
        zoom: beginZoomModeFromFit(),
        panX: 0,
        panY: 0,
      };
    }

    return {
      zoom: getEffectivePreviewZoom(),
      panX: state.panX,
      panY: state.panY,
    };
  }

  function onPanStart(e) {
    if (!hasPreviewContent() || pinching) return;
    if (e.button !== undefined && e.button !== 0) return;
    dragging = true;
    viewport.classList.add("is-panning");

    const pt = pointerPoint(e);

    startX = pt.clientX;
    startY = pt.clientY;
    startPanX = state.panX;
    startPanY = state.panY;
    e.preventDefault();
  }

  function onPanMove(e) {
    if (!dragging || pinching) return;
    const pt = pointerPoint(e);

    state.panX = startPanX + (pt.clientX - startX);

    state.panY = startPanY + (pt.clientY - startY);

    applyPanTransform();

    e.preventDefault();
  }

  function onPanEnd() {
    dragging = false;
    viewport.classList.remove("is-panning");
  }

  function onPinchStart(e) {
    if (!hasPreviewContent()) return;
    dragging = false;
    pinching = true;
    viewport.classList.add("is-panning");

    pinchStartDistance = touchDistance(e.touches);

    if (state.previewMode === "fit") {
      pinchStartZoom = beginZoomModeFromFit();

      startPanX = 0;
      startPanY = 0;
    } else {
      pinchStartZoom = getEffectivePreviewZoom();

      startPanX = state.panX;
      startPanY = state.panY;
    }

    e.preventDefault();
  }

  function onPinchMove(e) {
    if (!pinching || e.touches.length < 2) return;
    const distance = touchDistance(e.touches);

    if (pinchStartDistance <= 0) return;
    const center = touchCenter(e.touches);

    applyPinchZoom(distance / pinchStartDistance, center.x, center.y);

    e.preventDefault();
  }

  function onPinchEnd(e) {
    if (!pinching) return;
    if (e.touches.length >= 2) return;
    pinching = false;
    viewport.classList.remove("is-panning");

    syncZoomControls();

    if (e.touches.length === 1) {
      const pt = e.touches[0];
      dragging = true;
      viewport.classList.add("is-panning");

      startX = pt.clientX;
      startY = pt.clientY;
      startPanX = state.panX;
      startPanY = state.panY;
    }
  }

  viewport.addEventListener("mousedown", onPanStart);

  window.addEventListener("mousemove", onPanMove);

  window.addEventListener("mouseup", onPanEnd);

  window.addEventListener("blur", onPanEnd);

  viewport.addEventListener(
    "touchstart",
    (e) => {
      if (e.touches.length >= 2) onPinchStart(e);

      else onPanStart(e);
    },
    { passive: false },
  );

  viewport.addEventListener(
    "touchmove",
    (e) => {
      if (pinching || e.touches.length >= 2) onPinchMove(e);

      else onPanMove(e);
    },
    { passive: false },
  );

  viewport.addEventListener(
    "touchend",
    (e) => {
      onPinchEnd(e);

      if (e.touches.length === 0) onPanEnd();
    },
    { passive: false },
  );

  viewport.addEventListener(
    "touchcancel",
    (e) => {
      pinching = false;
      onPanEnd();
    },
    { passive: false },
  );

  document.addEventListener(
    "wheel",
    (e) => {
      if (!viewport.contains(e.target)) return;
      if (!hasPreviewContent() || pinching) return;
      e.preventDefault();

      const factor = e.deltaY < 0 ? 1.08 : 0.92;
      const base = zoomBaseFromCurrentMode();

      applyZoomAtFocal(
        base.zoom * factor,
        e.clientX,
        e.clientY,
        base.zoom,
        base.panX,
        base.panY,
      );
    },
    { passive: false, capture: true },
  );
}

$("btn-toggle-translation").addEventListener("click", () => {
  if (!state.currentTranslatedSrc && !state.currentOriginalSrc) return;
  state.translationVisible = !state.translationVisible;
  updateTranslationToggleButton();

  applyTranslationVisibility();
});

document.addEventListener("keydown", (ev) => {
  if (isTextInputFocused()) return;
  if (selectedSource() !== "page_analyze") return;
  if (ev.key === "ArrowLeft") {
    ev.preventDefault();

    navigateGallery(-1);
  } else if (ev.key === "ArrowRight") {
    ev.preventDefault();

    navigateGallery(1);
  } else if (ev.key === "Enter" && state.selectedPageImageId) {
    ev.preventDefault();

    handleTranslate({ force: true });
  }
});

window.addEventListener("beforeunload", () => {
  translationCache.forEach((entry) => revokeCacheEntry(entry));
});

async function init() {
  initMobileHeaderMenu();

  initMobileSections();

  $("session-code-input").value = initialSessionCode;
  updateSourcePanels();

  renderGallery();

  updateEngineBadge({ mode: "selected" });

  setPreviewEmpty();

  syncZoomControls();

  initPreviewPan();

  setAppInteractive(false);

  setSessionPanelConnected(false);

  try {
    const connected = await connectSession(sessionToken ? "0000" : initialSessionCode, {
      silent: true,
    });

    if (!connected) {
      state.sessionPanelManuallyHidden = false;
      updateSessionPanelVisibility();

      setStatus("Bitte Zugangscode eingeben.");

      setSessionHint("Adresse im Desktop-Fenster öffnen und 4-stelligen Code eingeben.");

      return;
    }

    state.sessionPanelManuallyHidden = false;
    updateSessionPanelVisibility();

    const status = await api("/api/status");

    const {settings, user} = await api("/api/settings");

    state.targetLanguage = String(settings.target_language || "deu");

    window.LingoVeilI18n?.setLanguage(settings.interface_language || "de");

    await configureEngineOptions(settings, user);

    const configuredOption = $("engine-select")?.querySelector(
      `option[value="${settings.engine}"]`
    );

    if (
      settings.engine && VALID_ENGINES.has(settings.engine)

      && configuredOption && !configuredOption.disabled && !configuredOption.hidden
    ) {
      $("engine-select").value = settings.engine;
      saveEngineChoice(settings.engine);
    } else if (settings.engine === "ollama") {
      $("engine-select").value = "ollama";
      saveEngineChoice("ollama");

      showOllamaUnavailable();
    } else {
      fallbackToBergamot();
    }

    state.prefetchCount = Math.max(0, Math.min(100, Number(settings.prefetch_count ?? 10)));

    translationCacheTtlMs = Math.max(
      30, Math.min(3600, Number(settings.browser_cache_ttl_sec ?? 300))

    ) * 1000;
    await loadHistory();

    await loadBookmarks();

    await validateEngineSelection();

    const counters = status.request_counters || {};

    const totalRequests = Object.values(counters).reduce((sum, n) => sum + (n || 0), 0);

    if (status.active_engine && totalRequests > 0) {
      state.confirmedEngine = status.active_engine;
      updateEngineBadge({ mode: "confirmed", engineId: status.active_engine });

      setStatus(`Bereit · Zuletzt verwendet: ${engineLabel(status.active_engine)}`);
    } else {
      setStatus("Bereit");
    }
  } catch (err) {
    setStatus(`Verbindung fehlgeschlagen: ${err.message}`);

    setSessionHint(`Verbindung fehlgeschlagen: ${err.message}`, { error: true });
  }
}

init();
