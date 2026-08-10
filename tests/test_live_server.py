from pathlib import Path
import tempfile
import unittest

class LiveSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.source = (cls.root / "app/live_server.py").read_text(encoding="utf-8")

    def test_shutdown_is_removed(self):
        self.assertIn('!= "/api/shutdown"', self.source)

    def test_health_does_not_process_images(self):
        health = self.source[self.source.index("def health()"):self.source.index('@app.get("/api/settings")')]
        self.assertNotIn("run_ocr", health)

        self.assertNotIn("process_image", health)

    def test_persistent_mounts_and_explicit_bind(self):
        compose = (self.root / "docker-compose.yml").read_text(encoding="utf-8")

        bind = (self.root / "docker-compose.bind.yml").read_text(encoding="utf-8")

        self.assertRegex(
            compose,
            r'"(?:127\.0\.0\.1|0\.0\.0\.0):\$\{LINGOVEIL_LIVE_PORT:-8765\}:',
        )

        self.assertIn('127.0.0.1:${LINGOVEIL_POSTGRES_PORT:-5434}:5432', compose)

        for text in (
            "lingoveil-models:/app/modelle",
            "lingoveil-data:/app/data",
            "lingoveil-cache:/app/cache",
        ):
            self.assertIn(text, compose)

        self.assertNotIn('user: "${LINGOVEIL_LIVE_UID', compose)

        for text in ("./modelle:/app/modelle", "./data:/app/data", "./cache:/app/cache"):
            self.assertIn(text, bind)

        self.assertIn('user: "${LINGOVEIL_LIVE_UID', bind)

    def test_no_desktop_dependencies(self):
        requirements = (self.root / "requirements.txt").read_text(encoding="utf-8").lower()

        for name in ("pyside", "tkinter", "pygobject"):
            self.assertNotIn(name, requirements)

    def test_translation_engines_have_configurable_idle_unload(self):
        compose = (self.root / "docker-compose.yml").read_text(encoding="utf-8")

        env_example = (self.root / ".env.example").read_text(encoding="utf-8")

        engine = (self.root / "src/lingoveil_translation_engine.py").read_text(
            encoding="utf-8"
        )

        worker = (self.root / "src/lingoveil_seamless_worker.py").read_text(
            encoding="utf-8"
        )

        worker_main = (
            self.root / "src/lingoveil_seamless_worker_main.py"
        ).read_text(encoding="utf-8")

        pipeline = (self.root / "src/lingoveil_browser_pipeline.py").read_text(
            encoding="utf-8"
        )

        ocr_worker = (self.root / "src/lingoveil_ocr_worker.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('LINGOVEIL_ENGINE_IDLE_MINUTES:-2', compose)

        self.assertIn("LINGOVEIL_ENGINE_IDLE_MINUTES=2", env_example)

        self.assertIn('get("LINGOVEIL_ENGINE_IDLE_MINUTES", "2")', engine)

        self.assertIn("def _idle_unload", engine)

        self.assertIn("SeamlessM4TWorkerClient", engine)

        self.assertNotIn("from lingoveil_seamless_m4t import", engine)

        self.assertIn("subprocess.Popen", worker)

        self.assertIn(
            "from lingoveil_seamless_m4t import SeamlessM4TTextTranslator",
            worker_main,
        )

        self.assertIn("EasyOcrWorker", pipeline)

        self.assertIn("def _idle_unload_ocr", pipeline)

        self.assertIn("subprocess.Popen", ocr_worker)

        self.assertIn("def _release_idle_memory", pipeline)

        self.assertIn('malloc_trim(0)', pipeline)

        self.assertIn("_page_image_preview_cache.clear()", pipeline)

        self.assertIn("_pdf_preview_cache.clear()", pipeline)

        self.assertIn("OverlayWorker", pipeline)

        self.assertNotIn("from lingoveil_overlay import", pipeline)

        self.assertIn("history.save_translation", pipeline)

        overlay_worker = (self.root / "src/lingoveil_overlay_worker.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("subprocess.Popen", overlay_worker)

    def test_access_code_is_kept_in_memory_after_field_is_cleared(self):
        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        self.assertIn("lingoveil:authenticated", controls)

        self.assertIn("inMemoryAccessCode", controls)

        self.assertIn('panel.hidden = shouldHide', browser)

        self.assertIn('$("session-code-input").value = "";', browser)

        self.assertIn("state.sessionCode = candidateCode;", browser)

        self.assertIn("window.history.replaceState", browser)

        self.assertIn("fetch(path, { ...options, headers })", browser)

    def test_login_cookie_and_preview_pointer_controls_exist(self):
        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        login = (self.root / "web/login.html").read_text(encoding="utf-8")

        server = (self.root / "src/lingoveil_browser_server.py").read_text(encoding="utf-8")

        self.assertIn('url = "/api/register"', login)

        self.assertIn('url = "/api/password-reset/request"', login)

        self.assertIn('url = "/api/password-reset/confirm"', login)

        self.assertIn('class="login-brand-logo"', login)

        self.assertIn('autocomplete="username"', login)

        self.assertIn('autocomplete="current-password"', login)

        self.assertIn("mindestens 8 Zeichen", login)

        self.assertIn("min_length=8", server)

        self.assertIn('key="lingoveil_session"', server)

        self.assertIn('"wheel",', browser)

        self.assertIn("{ passive: false }", browser)

        self.assertIn('viewport.addEventListener("mousedown", onPanStart)', browser)

        self.assertIn('window.addEventListener("mousemove", onPanMove)', browser)

        self.assertIn("capture: true", browser)

    def test_docker_build_is_standalone(self):
        compose = (self.root / "docker-compose.yml").read_text(encoding="utf-8")

        dockerfile = (self.root / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("context: .", compose)

        self.assertNotIn("alpha/", dockerfile)

        self.assertTrue((self.root / "src/lingoveil_browser_server.py").is_file())

        self.assertTrue((self.root / "web/app.js").is_file())

        self.assertTrue((self.root / "config/ocr_glossary.json").is_file())

        pipeline = (self.root / "src/lingoveil_browser_pipeline.py").read_text(
            encoding="utf-8"
        )

        server = (self.root / "src/lingoveil_browser_server.py").read_text(
            encoding="utf-8"
        )

        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        self.assertIn('f"/api/page-image-preview/{image_id}"', pipeline)

        self.assertIn("def page_image_preview", pipeline)

        self.assertIn('@app.get("/api/page-image-preview/{image_id}")', server)

        self.assertIn('wrap?.querySelector(".thumb-error")', browser)

    def test_tall_pages_use_tiled_ocr(self):
        pipeline = (self.root / "src/lingoveil_browser_pipeline.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("_run_ocr_preserving_detail", pipeline)

        self.assertIn("tile_height = 2400", pipeline)

        self.assertIn("OCR-Kachelung", pipeline)

        self.assertIn("_split_distant_ocr_groups", pipeline)

    def test_exact_overlay_growth_is_capped(self):
        overlay = (self.root / "src/lingoveil_overlay.py").read_text(encoding="utf-8")

        self.assertIn("max_expand_ratio=1.25", overlay)

        self.assertIn('source_fit["font_size"] * 0.85', overlay)

        self.assertIn("adaptive_factor = 1.25", overlay)

        self.assertIn("_exact_line_gap", overlay)

        self.assertIn("y_cursor - line_bbox[1]", overlay)

    def test_live_general_options_are_persisted_and_applied(self):
        server = self.source
        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        pipeline = (self.root / "src/lingoveil_browser_pipeline.py").read_text(
            encoding="utf-8"
        )

        styles = (self.root / "web/styles.css").read_text(encoding="utf-8")

        self.assertIn('"theme": "dark"', server)

        self.assertIn('{"dark", "light"}', server)

        self.assertIn("SEAMLESS_TARGET_LANGUAGES", server)

        self.assertIn("BERGAMOT_TARGET_LANGUAGES", server)

        self.assertIn("pipeline.apply_live_settings(current)", server)

        self.assertIn('selectField("Theme"', controls)

        self.assertIn('"Zielsprache der Übersetzung"', controls)

        self.assertIn('"Oberflächensprache"', controls)

        self.assertIn("showSavedPopup", controls)

        self.assertIn("capabilities.smtp_configured", controls)

        self.assertIn('"smtp_configured": mailer.configured', server)

        self.assertIn("chapterEmailNotifications.disabled", controls)

        self.assertIn("not mailer.configured", server)

        self.assertTrue((self.root / "web/i18n.js").is_file())

        self.assertIn("settings.interface_language", (self.root / "web/app.js").read_text(encoding="utf-8"))

        self.assertIn("applyTheme(theme.value)", controls)

        self.assertIn("def apply_live_settings", pipeline)

        self.assertIn(':root[data-theme="light"]', styles)

        self.assertIn("width: min(680px", styles)

    def test_seamless_download_requires_license_and_uses_model_mount(self):
        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        pipeline = (self.root / "src/lingoveil_browser_pipeline.py").read_text(
            encoding="utf-8"
        )

        browser_server = (
            self.root / "src/lingoveil_browser_server.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"seamless_license_accepted": False', self.source)

        self.assertIn("class SeamlessDownloadBody", self.source)

        self.assertIn("if not body.accept_license", self.source)

        self.assertIn('start_model_download("seamless-m4t-v2-large")', self.source)

        self.assertIn("model_download_worker.py", self.source)

        self.assertIn("/api/models/seamless-m4t-v2-large/download", controls)

        self.assertIn("CC-BY-NC-4.0", controls)

        self.assertIn("seamless_license_accepted", pipeline)

        self.assertIn("status_code=409", browser_server)

    def test_engine_precheck_modal_polling_and_languagetool_download(self):
        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        html = (self.root / "web/index.html").read_text(encoding="utf-8")

        manifest = (self.root / "src/core/model_manifest.py").read_text(
            encoding="utf-8"
        )

        dockerfile = (self.root / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("/api/engines/{engine_name}/availability", self.source)

        self.assertIn("validateEngineSelection", browser)

        self.assertIn("showEngineUnavailable", browser)

        self.assertIn('saveEngineChoice("bergamot")', browser)

        self.assertIn('id="engine-error-dialog"', html)

        self.assertIn('id="url-error-dialog"', html)

        self.assertIn("showUrlLoadError", browser)

        self.assertIn('persistEngineSelection("bergamot")', browser)

        self.assertIn(
            '"history_id": entry["id"]',
            (self.root / "src/lingoveil_browser_pipeline.py").read_text(
                encoding="utf-8"
            ),
        )

        self.assertIn("setTimeout(refreshModels", controls)

        self.assertIn("/api/models/${model.id}/download", controls)

        self.assertIn("LanguageTool-6.6.zip", manifest)

        self.assertIn(
            "53600506b399bb5ffe1e4c8dec794fd378212f14aaf38ccef9b6f89314d11631",
            manifest,
        )

        self.assertIn("default-jre-headless", dockerfile)

    def test_optional_engines_require_configuration_or_installed_model(self):
        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        html = (self.root / "web/index.html").read_text(encoding="utf-8")

        self.assertIn('"lm_studio_base_url": ""', self.source)

        self.assertIn('"lm_studio_model": ""', self.source)

        self.assertIn("configureEngineOptions", browser)

        self.assertIn("seamlessOption.disabled = !availability.available", browser)

        self.assertIn("lmStudioOption.hidden = !configured", browser)

        self.assertIn('<option value="seamless_m4t" disabled>', html)

        self.assertIn('<option value="lm_studio" disabled hidden>', html)

        self.assertNotIn('id="engine-badge"', html)

    def test_restored_history_refreshes_missing_assets_from_url(self):
        database = (self.root / "src/lingoveil_database.py").read_text(encoding="utf-8")

        history = (self.root / "src/lingoveil_history.py").read_text(encoding="utf-8")

        pipeline = (self.root / "src/lingoveil_browser_pipeline.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('entry["needs_refresh"] = True', database)

        self.assertIn('image["translations"] = {}', database)

        self.assertIn("missing_assets", pipeline)

        self.assertIn('not str(image.get("original_file", "")).strip()', pipeline)

        self.assertIn('return self.analyze_page_images(entry["url"])', pipeline)

        self.assertIn("self.asset_path(original_file)", history)

        self.assertIn('"translations": translations', history)

    def test_seamless_fast_tokenizer_dependencies_are_packaged(self):
        seamless = (self.root / "src/lingoveil_seamless_m4t.py").read_text(
            encoding="utf-8"
        )

        requirements = (self.root / "requirements.txt").read_text(encoding="utf-8")

        browser_server = (
            self.root / "src/lingoveil_browser_server.py"
        ).read_text(encoding="utf-8")

        self.assertIn("SeamlessM4TTokenizerFast.from_pretrained", seamless)

        self.assertIn("protobuf==6.33.4", requirements)

        self.assertIn("(RuntimeError, SeamlessM4TError)", browser_server)

    def test_history_and_prefetch_are_persistent_and_configurable(self):
        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        html = (self.root / "web/index.html").read_text(encoding="utf-8")

        pipeline = (self.root / "src/lingoveil_browser_pipeline.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"history_limit": 10', self.source)

        self.assertIn("prefetch_count: int = Field(ge=0, le=100)", self.source)

        self.assertIn('"prefetch_count": 10', self.source)

        self.assertIn("history_limit: int = Field(ge=1, le=100)", self.source)

        self.assertIn('History-Einträge (1–100)', controls)

        self.assertIn("Array.isArray(detail)", controls)

        styles = (self.root / "web/styles.css").read_text(encoding="utf-8")

        self.assertIn(".history-list::-webkit-scrollbar", styles)

        self.assertIn("touch-action: pan-y", styles)

        self.assertIn("-webkit-overflow-scrolling: touch", styles)

        self.assertIn('"/api/history"', self.source)

        self.assertIn('id="history-list"', html)

        self.assertNotIn('id="status"', html)

    def test_retranslation_respects_target_language_and_force(self):
        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        html = (self.root / "web/index.html").read_text(encoding="utf-8")

        pipeline = (self.root / "src/lingoveil_browser_pipeline.py").read_text(
            encoding="utf-8"
        )

        browser_server = (
            self.root / "src/lingoveil_browser_server.py"
        ).read_text(encoding="utf-8")

        self.assertIn("force: bool = False", browser_server)

        self.assertIn("force=body.force", browser_server)

        self.assertIn("history_ref and not force", pipeline)

        self.assertIn('result.get("target_language", legacy_target)', pipeline)

        self.assertIn('"target_language": self._target_language(engine_name)', pipeline)

        self.assertIn("target_lang=self._target_language(engine_name)", pipeline)

        self.assertIn("source_lang=self._source_language(engine_name)", pipeline)

        self.assertIn("processSelectedItem(engine, {force})", browser)

        self.assertIn("state.targetLanguage", browser)

        self.assertIn("result?.rendered_url", browser)

        self.assertIn('result["rendered_url"]', pipeline)

        self.assertIn("user_settings_provider", browser_server)

        self.assertIn('"target_language": target_language', browser_server)

        self.assertNotIn("Desktop-Modus weiter nutzen", html)

        self.assertIn("state.prefetchCount", browser)

        self.assertNotIn("prefetchGeneration", browser)

        self.assertNotIn("cancelPrefetch", browser)

        self.assertIn("queuedTranslationItems", browser)

        self.assertIn("Warteschlange", browser)

        self.assertIn("enqueuePrefetchImages(state.galleryImages", browser)

        self.assertIn('handleTranslate({ force: true })', browser)

        self.assertIn("openHistoryEntry", browser)

        self.assertIn("History löschen", controls)

        self.assertIn("general.append(clearHistorySetting)", controls)

        self.assertNotIn("actions.prepend(clearHistory)", controls)

        self.assertNotIn(
            'window.confirm("Gesamte URL-History und gespeicherte Übersetzungen löschen?")',
            controls,
        )

        self.assertIn("confirmHistoryDeletion", controls)

        self.assertIn('uiText("History wirklich löschen?")', controls)

        self.assertIn("history.save_translation", pipeline)

        self.assertIn("history.cached_translation", pipeline)

    def test_translation_jobs_continue_without_an_active_browser(self):
        server = (self.root / "src/lingoveil_browser_server.py").read_text(
            encoding="utf-8"
        )

        jobs = (self.root / "src/lingoveil_jobs.py").read_text(encoding="utf-8")

        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        pipeline = (self.root / "src/lingoveil_browser_pipeline.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('@app.post("/api/translation-jobs/page-image")', server)

        self.assertIn('@app.post("/api/translation-jobs/pdf-page")', server)

        self.assertIn('@app.get("/api/translation-jobs/{job_id}")', server)

        self.assertIn("def enqueue(", jobs)

        self.assertIn("Promise.resolve()", browser)

        self.assertIn(".then(job.task)", browser)

        self.assertIn("runTranslationBackgroundJob", browser)

        self.assertIn("isTransientNetworkError(err)", browser)

        self.assertIn('"translated_engines"', pipeline)

        self.assertIn('"cached_translations"', pipeline)

        self.assertIn('"/api/settings/engine"', self.source)

        self.assertIn("thumb-translation-status", browser)

        self.assertIn("markItemTranslated", browser)

        self.assertIn("setItemTranslating", browser)

        self.assertIn("Wird übersetzt", browser)

        self.assertIn("loadPersistentHistoryTranslation", browser)

        self.assertNotIn("applySavedEngine();", browser)

        self.assertIn("activeHistoryEntryId", browser)

        self.assertIn('aria-current", "page"', browser)

        self.assertNotIn("thumbnailScalePercent", browser)

    def test_selected_image_keeps_preview_and_is_prioritized(self):
        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        self.assertIn("const translationQueue = []", browser)

        self.assertIn("translationQueue.push(job)", browser)

        self.assertIn("drainTranslationQueue()", browser)

        self.assertIn("function promoteQueuedTranslation", browser)

        self.assertIn(
            "promoteQueuedTranslation(state.selectedPageImageId, engine)",
            browser,
        )

        self.assertIn("setPreviewSources(null, originalSrc", browser)

        self.assertIn("priority: true", browser)

    def test_mobile_preview_uses_the_full_screen_width(self):
        styles = (self.root / "web/styles.css").read_text(encoding="utf-8")

        html = (self.root / "web/index.html").read_text(encoding="utf-8")

        self.assertIn("@media (max-width: 736px)", styles)

        self.assertIn("padding: 6px 0", styles)

        self.assertIn("border-radius: 0", styles)

        self.assertIn("styles.css?v=20260807-18", html)

    def test_light_theme_main_panels_have_readable_contrast(self):
        styles = (self.root / "web/styles.css").read_text(encoding="utf-8")

        self.assertIn(':root[data-theme="light"] .sidebar', styles)

        self.assertIn(':root[data-theme="light"] .preview-main', styles)

        self.assertIn(
            ':root[data-theme="light"] .preview-viewport .preview-placeholder',
            styles,
        )

    def test_untranslated_image_is_blurred_while_translation_runs(self):
        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        html = (self.root / "web/index.html").read_text(encoding="utf-8")

        styles = (self.root / "web/styles.css").read_text(encoding="utf-8")

        self.assertIn('id="preview-processing-overlay"', html)

        self.assertIn("Wird gerade übersetzt …", html)

        self.assertIn("function setPreviewProcessing", browser)

        self.assertIn("state.currentTranslatedSrc || state.currentOriginalSrc", browser)

        self.assertIn("processing: true", browser)

        self.assertIn(".preview-viewport.preview-processing #preview-image", styles)

        self.assertIn("filter: blur(8px)", styles)

    def test_chapter_navigation_uses_generic_bookmark_snapshot(self):
        import sys

        sys.path.insert(0, str(self.root / "src"))

        from lingoveil_bookmarks import MangaBookmarkStore
        with tempfile.TemporaryDirectory() as temp:
            bookmarks = MangaBookmarkStore(Path(temp))

            bookmarks.add(
                url="https://reader.example/manga/example/",
                title="Example",
                site="future-adapter",
                catalog_chapters=[
                    {
                        "url": "https://reader.example/chapter/3",
                        "chapter": "3",
                        "label": "Chapter 3",
                    },
                    {
                        "url": "https://reader.example/chapter/2",
                        "chapter": "2",
                        "label": "Chapter 2",
                    },
                    {
                        "url": "https://reader.example/chapter/1",
                        "chapter": "1",
                        "label": "Chapter 1",
                    },
                ],
            )

            middle = bookmarks.chapter_navigation(
                "https://reader.example/chapter/2"
            )

            self.assertTrue(middle["enabled"])

            self.assertEqual(
                middle["previous_url"],
                "https://reader.example/chapter/1",
            )

            self.assertEqual(
                middle["next_url"],
                "https://reader.example/chapter/3",
            )

            self.assertEqual(middle["chapter_label"], "Chapter 2")

            self.assertFalse(
                bookmarks.chapter_navigation(
                    "https://unsupported.example/chapter/2"
                )["enabled"]
            )

        html = (self.root / "web/index.html").read_text(encoding="utf-8")

        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        self.assertEqual(html.count("chapter-nav preview-nav-button"), 2)

        self.assertNotIn('id="btn-gallery-prev"', html)

        self.assertNotIn('id="btn-gallery-chapter-prev"', html)

        self.assertIn('id="preview-title"', html)

        self.assertIn("result.chapter_navigation || null", browser)

        self.assertIn("function navigateChapter(direction)", browser)

        self.assertIn("function updatePreviewContext()", browser)

        self.assertIn('[chapterLabel, imageLabel].filter(Boolean).join(" - ")', browser)

        self.assertIn("styles.css?v=20260807-18", html)

        self.assertIn("app.js?v=20260807-8", html)

        self.assertIn("let translationCacheTtlMs = 5 * 60 * 1000", browser)

        self.assertIn("settings.browser_cache_ttl_sec ?? 300", browser)

        self.assertIn("Date.now() + translationCacheTtlMs", browser)

        self.assertNotIn("OCR-Gruppe(n) · Übersetzt mit:", browser)

        self.assertNotIn("state.chapterNavigation = null;\n  updateChapterNavButtons()", browser)

        self.assertIn(
            "state.chapterNavigation?.enabled && state.galleryImages.length",
            browser,
        )

        self.assertIn('id="preview-meta" aria-live="polite"', html)

        self.assertIn('"Übersetzung an": "Translation on"', (
            self.root / "web/i18n.js"
        ).read_text(encoding="utf-8"))

        self.assertIn("window.LingoVeilI18n?.t(label) || label", browser)

    def test_history_store_prunes_and_restores_cached_translation(self):
        import sys

        sys.path.insert(0, str(self.root / "src"))

        from lingoveil_history import LiveHistoryStore
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            store = LiveHistoryStore(root / "data", root / "cache", limit=2)

            first = store.touch(
                "https://example.com/one",
                [{"url": "https://example.com/one.jpg"}],
                metadata={
                    "manga_title": "Example Manga",
                    "volume": "2",
                    "chapter": "7",
                },
            )

            self.assertEqual(
                store.list_entries()[0]["metadata"]["manga_title"],
                "Example Manga",
            )

            rendered = root / "rendered.png"
            rendered.write_bytes(b"\x89PNG\r\n\x1a\nrendered")

            store.save_translation(
                entry_id=first["id"],
                image_key=first["images"][0]["key"],
                engine="bergamot",
                original=b"\xff\xd8\xfforiginal",
                rendered_path=rendered,
                result={"engine": "bergamot", "target_language": "it", "groups": []},
            )

            cached = store.cached_translation(
                first["id"], first["images"][0]["key"], "bergamot", "it"
            )

            self.assertIsNotNone(cached)

            store.save_translation(
                entry_id=first["id"],
                image_key=first["images"][0]["key"],
                engine="bergamot",
                original=b"\xff\xd8\xfforiginal",
                rendered_path=rendered,
                result={"engine": "bergamot", "target_language": "ar", "groups": []},
            )

            self.assertIsNotNone(store.cached_translation(
                first["id"], first["images"][0]["key"], "bergamot", "it"
            ))

            self.assertIsNotNone(store.cached_translation(
                first["id"], first["images"][0]["key"], "bergamot", "ar"
            ))

            store.touch(
                "https://example.com/two",
                [{"url": "https://example.com/two.jpg"}],
            )

            store.set_limit(1)

            self.assertEqual(len(store.list_entries()), 1)

            self.assertIsNone(store.get(first["id"]))

    def test_ten_rendered_pages_survive_worker_lifetimes(self):
        import sys

        sys.path.insert(0, str(self.root / "src"))

        from lingoveil_history import LiveHistoryStore
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            urls = [f"https://example.com/page-{number}.jpg" for number in range(10)]
            store = LiveHistoryStore(root / "data", root / "cache", limit=10)

            entry = store.touch("https://example.com/chapter", [{"url": url} for url in urls])

            rendered = root / "worker-output.png"
            rendered.write_bytes(b"\x89PNG\r\n\x1a\nrendered")

            for number, image in enumerate(entry["images"]):
                store.save_translation(
                    entry_id=entry["id"],
                    image_key=image["key"],
                    engine="bergamot",
                    original=b"\xff\xd8\xfforiginal",
                    rendered_path=rendered,
                    result={
                        "engine": "bergamot",
                        "target_language": "de",
                        "groups": [{"id": "g1", "translation": f"Seite {number + 1}"}],
                    },
                )

            reopened = LiveHistoryStore(root / "data", root / "cache", limit=10)

            for number, image in enumerate(entry["images"]):
                cached = reopened.cached_translation(
                    entry["id"], image["key"], "bergamot", "de"
                )

                self.assertIsNotNone(cached)

                self.assertEqual(
                    cached[0]["groups"][0]["translation"], f"Seite {number + 1}"
                )

    def test_fetch_strategy_is_learned_per_origin_and_gifs_are_blocked(self):
        import sys

        sys.path.insert(0, str(self.root / "src"))

        from lingoveil_fetch_strategies import FetchStrategyStore
        from lingoveil_image_pipeline import (
            extract_page_images,
            is_gif_url,
            is_social_preview_url,
        )

        calls = []
        def fetch(_url, **kwargs):
            calls.append(kwargs.get("request_headers", {}))

            if not kwargs.get("request_headers", {}).get("Referer"):
                raise RuntimeError("403 Forbidden")

            return b"\xff\xd8\xffimage", "image/jpeg"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fetch_strategies.json"
            store = FetchStrategyStore(path, fetch_fn=fetch)

            source = "https://www.mangatown.com/manga/title/chapter/9.html"
            result = store.download(
                "https://cdn.example/image.jpg",
                source_url=source,
                max_bytes=1024,
                allowed_content_types={"image/jpeg"},
            )

            self.assertEqual(result[1], "image/jpeg")

            self.assertEqual(calls, [{}, {"Referer": source}])

            saved = path.read_text(encoding="utf-8")

            self.assertIn("https://www.mangatown.com/", saved)

            self.assertNotIn("/manga/title/chapter/9.html", saved)

            calls.clear()

            store.download(
                "https://cdn.example/next.jpg",
                source_url="https://www.mangatown.com/manga/other/chapter.html",
                max_bytes=1024,
                allowed_content_types={"image/jpeg"},
            )

            self.assertEqual(
                calls[0],
                {"Referer": "https://www.mangatown.com/manga/other/chapter.html"},
            )

        images = extract_page_images(
            '<img src="cover.gif"><img src="page.jpg"><img src="anim.GIF?x=1">',
            "https://example.com/chapter/",
        )

        self.assertEqual([item["url"] for item in images], [
            "https://example.com/chapter/page.jpg"
        ])

        self.assertTrue(is_gif_url("https://example.com/loading.GIF?cache=1"))

        self.assertFalse(is_gif_url("https://example.com/page.jpg"))

        self.assertTrue(is_social_preview_url(
            "http://www.mangatown.com/media/images/fbshare.jpg"
        ))

        images = extract_page_images(
            (
                '<img src="page.jpg">'
                '<meta property="og:image" content="https://example.com/fbshare.jpg">'
            ),
            "https://example.com/chapter/",
        )

        self.assertEqual([item["url"] for item in images], [
            "https://example.com/chapter/page.jpg"
        ])

    def test_mangadex_adapter_returns_all_ordered_pages_with_stable_keys(self):
        import sys

        sys.path.insert(0, str(self.root / "src"))

        from lingoveil_mangadex import (
            mangadex_chapter_id,
            resolve_mangadex_chapter,
        )

        chapter_id = "9981c450-a704-4e48-b4ba-8a234730cd60"
        url = f"https://mangadex.org/chapter/{chapter_id}"
        payload = {
            "result": "ok",
            "baseUrl": "https://server-a.mangadex.network",
            "chapter": {
                "hash": "chapter-hash",
                "data": ["001.jpg", "002.png", "loading.gif"],
                "dataSaver": ["001-small.jpg", "002-small.png"],
            },
        }

        pages = resolve_mangadex_chapter(
            url,
            fetch_json=lambda _url: payload,
            validate_url=lambda value: value,
        )

        self.assertEqual(mangadex_chapter_id(url), chapter_id)

        self.assertIsNone(mangadex_chapter_id("https://example.com/chapter/" + chapter_id))

        self.assertEqual(
            [page["url"] for page in pages],
            [
                "https://server-a.mangadex.network/data/chapter-hash/001.jpg",
                "https://server-a.mangadex.network/data/chapter-hash/002.png",
            ],
        )

        self.assertEqual(
            pages[0]["key"],
            f"mangadex-{chapter_id}-chapter-hash-001.jpg",
        )

    def test_mangatown_adapter_collects_full_chapter_from_any_page(self):
        import sys

        sys.path.insert(0, str(self.root / "src"))

        from lingoveil_mangatown import (
            mangatown_chapter,
            resolve_mangatown_chapter,
        )

        root = "https://www.mangatown.com/manga/yu_ling_shi/v05/c149/"
        pages = {
            root: (
                '<select><option value="/manga/yu_ling_shi/v05/c149/">01</option>'
                '<option value="/manga/yu_ling_shi/v05/c149/2.html">02</option>'
                '<option value="/manga/yu_ling_shi/v05/c149/3.html">03</option>'
                '</select><img id="image" src="//cdn.example/v001.jpg">'
            ),
            root + "2.html": (
                '<select><option value="/manga/yu_ling_shi/v05/c149/">01</option>'
                '<option value="/manga/yu_ling_shi/v05/c149/2.html">02</option>'
                '<option value="/manga/yu_ling_shi/v05/c149/3.html">03</option>'
                '</select><img id="image" src="//cdn.example/v002.jpg">'
            ),
            root + "3.html": (
                '<select><option value="/manga/yu_ling_shi/v05/c149/">01</option>'
                '<option value="/manga/yu_ling_shi/v05/c149/2.html">02</option>'
                '<option value="/manga/yu_ling_shi/v05/c149/3.html">03</option>'
                '</select><img id="image" src="//cdn.example/v003.jpg">'
            ),
        }

        def fetch(url, **_kwargs):
            return pages[url]
        canonical, images = resolve_mangatown_chapter(
            root + "3.html",
            fetch_html=fetch,
            validate_url=lambda value: value,
        )

        self.assertEqual(mangatown_chapter(root + "2.html"), (root, 2))

        self.assertEqual(canonical, root)

        self.assertEqual(
            [image["url"] for image in images],
            [
                "https://cdn.example/v001.jpg",
                "https://cdn.example/v002.jpg",
                "https://cdn.example/v003.jpg",
            ],
        )

        self.assertEqual(
            [image["source_url"] for image in images],
            [root, root + "2.html", root + "3.html"],
        )

    def test_manga_catalogs_group_chapters_and_ignore_unrelated_links(self):
        import sys

        sys.path.insert(0, str(self.root / "src"))

        from lingoveil_manga_catalog import resolve_manga_catalog
        mangaread = resolve_manga_catalog(
            "https://www.mangaread.org/manga/example/",
            fetch_html=lambda _url, **_kwargs: (
                "<h1>Example Read</h1>"
                '<a href="/manga/example/chapter-2/">Chapter 2</a>'
                '<a href="/manga/example/chapter-1-5/">Chapter 1.5</a>'
                '<a href="/manga/other/chapter-99/">Chapter 99</a>'
            ),
        )

        self.assertEqual(mangaread["title"], "Example Read")

        self.assertEqual(
            [item["chapter"] for item in mangaread["groups"][0]["chapters"]],
            ["2", "1.5"],
        )

        mangatown = resolve_manga_catalog(
            "https://www.mangatown.com/manga/example/",
            fetch_html=lambda _url, **_kwargs: (
                "<h1>Example Town</h1>"
                '<a href="/manga/example/v02/c004">Unpublished 4</a>'
                '<a href="/manga/example/v02/c003/">Example 3</a>'
                '<a href="/manga/example/comments/">Comments</a>'
                '<a href="/manga/example/v01/c001/">Example 1</a>'
            ),
        )

        self.assertEqual(
            [item["chapter"] for item in mangatown["groups"][0]["chapters"]],
            ["3", "1"],
        )

        manga_id = "26bcd529-5228-4262-9f77-fbe2aa659217"
        chapter_id = "9981c450-a704-4e48-b4ba-8a234730cd60"
        def manga_json(url):
            if "/feed?" not in url:
                return {"data": {"attributes": {"title": {"en": "Example Dex"}}}}

            return {
                "total": 1,
                "data": [{
                    "id": chapter_id,
                    "attributes": {
                        "volume": "1",
                        "chapter": "2",
                        "translatedLanguage": "en",
                    },
                }],
            }

        mangadex = resolve_manga_catalog(
            f"https://mangadex.org/title/{manga_id}/example",
            fetch_json=manga_json,
        )

        self.assertEqual(mangadex["title"], "Example Dex")

        self.assertEqual(mangadex["groups"][0]["label"], "Volume 1")

        self.assertEqual(
            mangadex["groups"][0]["chapters"][0]["url"],
            f"https://mangadex.org/chapter/{chapter_id}",
        )

    def test_bookmarks_are_persistent_and_protect_history_entries(self):
        import sys

        sys.path.insert(0, str(self.root / "src"))

        from lingoveil_bookmarks import MangaBookmarkStore
        from lingoveil_history import LiveHistoryStore
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            bookmarks = MangaBookmarkStore(root / "data")

            manga_url = "https://www.mangaread.org/manga/example/"
            chapter_url = manga_url + "chapter-2/"
            self.assertTrue((root / "data" / "bookmarks.json").is_file())

            bookmarks.add(
                url=manga_url,
                title="Example",
                site="mangaread",
                catalog_chapters=[
                    {
                        "url": chapter_url,
                        "chapter": "2",
                        "label": "Chapter 2",
                    },
                ],
            )

            self.assertEqual(bookmarks.get_by_url(manga_url)["chapter_count"], 1)

            chapter_3_url = manga_url + "chapter-3/"
            updated = bookmarks.update_catalog_snapshot(
                manga_url,
                [
                    {
                        "url": chapter_3_url,
                        "chapter": "3",
                        "label": "Chapter 3",
                    },
                    {
                        "url": chapter_url,
                        "chapter": "2",
                        "label": "Chapter 2",
                    },
                ],
            )

            self.assertEqual(updated["chapter_count"], 2)

            self.assertEqual(updated["new_chapters"][0]["chapter"], "3")

            bookmarks.mark_read(
                manga_url=manga_url,
                chapter_url=chapter_3_url,
                volume="",
                chapter="3",
                label="Chapter 3",
            )

            restored = MangaBookmarkStore(root / "data").get_by_url(manga_url)

            self.assertEqual(restored["last_read_url"], chapter_3_url)

            self.assertEqual(restored["new_chapters"], [])

            history = LiveHistoryStore(
                root / "data",
                root / "cache",
                limit=1,
                protected_manga_urls=bookmarks.urls,
            )

            protected = history.touch(
                chapter_url,
                [{"url": "https://cdn.example/chapter-2.jpg"}],
                metadata={"manga_url": manga_url},
            )

            history.touch(
                "https://example.com/regular-1",
                [{"url": "https://example.com/regular-1.jpg"}],
            )

            history.touch(
                "https://example.com/regular-2",
                [{"url": "https://example.com/regular-2.jpg"}],
            )

            ids = {entry["id"] for entry in history.list_entries()}

            self.assertIn(protected["id"], ids)

            self.assertEqual(len(ids), 2)

            bookmarks.remove(manga_url, delete_reading_data=False)

            bookmarks.add(url=manga_url, title="Example", site="mangaread")

            self.assertEqual(
                bookmarks.get_by_url(manga_url)["last_read_url"],
                chapter_3_url,
            )

    def test_bookmark_ui_and_unlimited_manga_setting_exist(self):
        server = (self.root / "app/live_server.py").read_text(encoding="utf-8")

        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        html = (self.root / "web/index.html").read_text(encoding="utf-8")

        self.assertIn('"bookmark_chapter_cache_limit": 10', server)

        self.assertIn("bookmark_chapter_cache_limit: int = Field(ge=0)", server)

        self.assertNotIn("bookmark_chapter_cache_limit: int = Field(ge=0, le=", server)

        self.assertIn('mangaTab.textContent = "Manga"', controls)

        self.assertIn("Gespeicherte Chapter je Bookmark", controls)

        self.assertIn('id="tab-bookmarks"', html)

        self.assertIn('id="btn-bookmarks-refresh"', html)

        self.assertIn('id="btn-bookmarks-edit"', html)

        self.assertIn('id="bookmark-search"', html)

        self.assertIn('id="bookmark-remove-dialog"', html)

        self.assertIn("/api/bookmarks/check-updates", server)

        self.assertIn("12 * 60 * 60", server)

        self.assertIn("manga-bookmark-button", browser)

        self.assertIn("bookmark-new-chapter", browser)

        self.assertIn("bookmarkEditMode", browser)

        self.assertIn("bookmark-entry-remove", browser)

        self.assertIn('openBookmarkRemoval(bookmark, "sidebar")', browser)

        self.assertIn('window.LingoVeilI18n?.language === "en"', browser)

        self.assertIn('Remove “${bookmark.title}” from bookmarks?', browser)

        self.assertIn('if (source === "catalog")', browser)

        self.assertIn("showMangaCatalogLoading(bookmark)", browser)

        self.assertIn("manga-catalog-loading-state", browser)

        self.assertIn("catalog-reveal", browser)

        self.assertIn("last-read", browser)

    def test_progress_backup_restore_ui_and_api_exist(self):
        server = (self.root / "app/live_server.py").read_text(encoding="utf-8")

        pipeline = (self.root / "src/lingoveil_browser_pipeline.py").read_text(
            encoding="utf-8"
        )

        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        self.assertIn('backupTab.textContent = "Backup / Restore"', controls)

        self.assertIn("Backup herunterladen", controls)

        self.assertIn("Backup wiederherstellen", controls)

        self.assertIn("confirmBackupRestore", controls)

        self.assertIn("if (!await confirmBackupRestore()) return", controls)

        self.assertNotIn("Aktuelle History und Bookmarks durch den Inhalt dieses Backups ersetzen?", controls)

        self.assertIn("new FormData()", controls)

        self.assertIn('"/api/progress/backup"', controls)

        self.assertIn('"/api/progress/restore"', controls)

        self.assertIn('@app.get("/api/progress/backup")', server)

        self.assertIn('@app.post("/api/progress/restore")', server)

        self.assertIn("10 * 1024 * 1024", server)

        self.assertIn('"format": "lingoveil-live-progress"', pipeline)

        self.assertIn("def restore_progress(", pipeline)

        self.assertIn('"translations": {}', pipeline)

        self.assertIn("previous_history", pipeline)

        self.assertIn("previous_bookmarks", pipeline)

    def test_display_tab_is_removed_and_models_remain_admin_only(self):
        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        browser = (self.root / "web/app.js").read_text(encoding="utf-8")

        self.assertNotIn('displayTab.textContent = "Darstellung"', controls)

        self.assertIn('modelsTab.textContent = "Modelle"', controls)

        self.assertIn(
            "tabs.append(generalTab, accountTab, mangaTab, backupTab)",
            controls,
        )

        self.assertIn("if (isAdmin) tabs.append(modelsTab, adminTab)", controls)

        self.assertIn('base.closest(".live-field").remove()', controls)

        self.assertIn('model.closest(".live-field").remove()', controls)

        self.assertIn('timeout.closest(".live-field").remove()', controls)

        self.assertIn('advancedLegend.textContent = "Browser"', controls)

        self.assertNotIn('advancedLegend.textContent = isAdmin ? "Browser & LM Studio"', controls)

        self.assertIn('lmStudioLegend.textContent = "LM Studio"', controls)

        self.assertIn('saveLmStudio.textContent = uiText("LM Studio speichern")', controls)

        self.assertIn("lmStudioSettings.append(", controls)

        self.assertNotIn("displayPanel.className", controls)

        self.assertNotIn("Darstellung speichern", controls)

        self.assertNotIn("show_debug_areas: debug.value", controls)

        html = (self.root / "web/index.html").read_text(encoding="utf-8")

        self.assertIn("live-controls.js?v=20260807-14", html)

        self.assertIn("modelsPanel.className", controls)

        self.assertIn("void refreshModels()", controls)

        self.assertIn('new CustomEvent("lingoveil:models-updated"', controls)

        self.assertIn('addEventListener("pointerdown"', browser)

        self.assertIn('addEventListener("lingoveil:models-updated"', browser)

        self.assertIn("refreshSeamlessAvailability", browser)

        self.assertNotIn('addButton("Darstellung"', controls)

        self.assertNotIn('addButton("Modelle"', controls)

    def test_admin_controls_registration_users_and_auth_language(self):
        server = (self.root / "app/live_server.py").read_text(encoding="utf-8")

        database = (self.root / "src/lingoveil_database.py").read_text(encoding="utf-8")

        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        login = (self.root / "web/login.html").read_text(encoding="utf-8")

        self.assertIn('adminTab.textContent = "Admin"', controls)

        self.assertIn("if (isAdmin) tabs.append(modelsTab, adminTab)", controls)

        self.assertIn('request("/api/admin/users")', controls)

        self.assertIn('@app.put("/api/admin/registration")', server)

        self.assertIn('@app.delete("/api/admin/users/{user_id}")', server)

        self.assertIn("Depends(require_admin)", server)

        self.assertIn("if row[\"role\"] == \"admin\"", database)

        self.assertIn("if existing and existing[\"value\"] and not registration_enabled", database)

        self.assertIn('"interface_language": "en"', server)

        self.assertIn('fetch("/api/auth/config"', login)

        self.assertIn('<html lang="en">', login)

    def test_password_reset_is_smtp_gated_and_uses_expiring_hashed_codes(self):
        server = (self.root / "app/live_server.py").read_text(encoding="utf-8")

        database = (self.root / "src/lingoveil_database.py").read_text(encoding="utf-8")

        notifications = (self.root / "src/lingoveil_notifications.py").read_text(encoding="utf-8")

        login = (self.root / "web/login.html").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS password_reset_codes", database)

        self.assertIn("self.passwords.hash(code)", database)

        self.assertIn("interval '15 minutes'", database)

        self.assertIn('int(row["attempts"]) >= 5', database)

        self.assertIn("DELETE FROM user_sessions WHERE user_id", database)

        self.assertIn('@app.post("/api/password-reset/request")', server)

        self.assertIn('@app.post("/api/password-reset/confirm")', server)

        self.assertIn('"password_reset_available": mailer.configured', server)

        self.assertIn("def send_password_reset", notifications)

        self.assertIn('id="login-code"', login)

        self.assertLess(login.index('id="login-email"'), login.index('id="login-code"'))

        self.assertLess(login.index('id="login-code"'), login.index('id="login-password"'))

        self.assertLess(login.index('id="login-password"'), login.index('id="login-confirm-password"'))

    def test_options_modal_has_one_stable_scrollable_content_area(self):
        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        styles = (self.root / "web/styles.css").read_text(encoding="utf-8")

        self.assertIn('dialog.classList.toggle("settings-dialog"', controls)

        self.assertIn('panels.className = "live-settings-panels"', controls)

        self.assertIn("panels.scrollTop = 0", controls)

        self.assertIn(".live-dialog.settings-dialog", styles)

        self.assertIn("grid-template-rows: auto minmax(0, 1fr) auto", styles)

        self.assertIn(".settings-dialog .live-dialog-content", styles)

        self.assertIn(".live-settings-panels", styles)

        self.assertIn("scrollbar-gutter: stable", styles)

        self.assertIn(".settings-dialog .live-dialog-actions", styles)

    def test_postgresql_multi_user_security_and_queue_exist(self):
        database = (self.root / "src/lingoveil_database.py").read_text(encoding="utf-8")

        jobs = (self.root / "src/lingoveil_jobs.py").read_text(encoding="utf-8")

        notifications = (self.root / "src/lingoveil_notifications.py").read_text(encoding="utf-8")

        compose = (self.root / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("pg_advisory_xact_lock", database)

        self.assertIn("PasswordHasher", database)

        self.assertIn("user_sessions", database)

        self.assertIn("notification_deliveries", database)

        self.assertIn("class FairTranslationQueue", jobs)

        self.assertIn("deque", jobs)

        self.assertIn("FOR UPDATE OF n SKIP LOCKED", notifications)

        self.assertIn("chapter_email_notifications", notifications)

        self.assertIn("add_alternative", notifications)

        self.assertIn("_claim_batch", notifications)

        self.assertIn("postgres:17-alpine", compose)

        self.assertIn("Administratorrechte erforderlich", self.source)

    def test_chapter_notification_digest_is_localized_and_has_no_default_link(self):
        import sys

        sys.path.insert(0, str(self.root / "src"))

        from lingoveil_notifications import ChapterNotificationMailer
        mailer = ChapterNotificationMailer.__new__(ChapterNotificationMailer)

        mailer.sender = "lingoveil@example.test"
        mailer.sender_name = "LingoVeil Manga Updates"
        mailer.public_url = ""
        message = mailer._message({
            "email": "reader@example.test",
            "language": "en",
            "payloads": [
                {"title": "Manga One", "chapter": {"label": "Chapter 10"}},
                {"title": "Manga One", "chapter": {"label": "Chapter 11"}},
                {"title": "Manga Two", "chapter": {"label": "Chapter 3"}},
            ],
        })

        self.assertEqual(message["Subject"], "3 new manga chapter update(s)")

        self.assertEqual(
            message["From"], "LingoVeil Manga Updates <lingoveil@example.test>"
        )

        plain = message.get_body(preferencelist=("plain",)).get_content()

        html_body = message.get_body(preferencelist=("html",)).get_content()

        self.assertIn("Open LingoVeil to continue reading.", plain)

        self.assertNotIn("localhost", plain)

        self.assertEqual(html_body.count("Manga One"), 1)

        self.assertIn("#8aa4ff", html_body)

        self.assertIn("#33d17a", html_body)

    def test_account_data_can_be_updated_from_options(self):
        database = (self.root / "src/lingoveil_database.py").read_text(encoding="utf-8")

        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        self.assertIn('class AccountUpdateBody', self.source)

        self.assertIn('@app.put("/api/account")', self.source)

        self.assertIn("def update_account(", database)

        self.assertIn("Das aktuelle Passwort ist falsch", database)

        self.assertIn("DELETE FROM user_sessions WHERE user_id", database)

        self.assertIn('accountTab.textContent = "Konto"', controls)

        self.assertIn('request("/api/account"', controls)

        self.assertIn('currentPassword.autocomplete = "current-password"', controls)

        self.assertIn('newPassword.autocomplete = "new-password"', controls)

    def test_mobile_preview_navigation_is_compact_and_symmetric(self):
        html = (self.root / "web/index.html").read_text(encoding="utf-8")

        styles = (self.root / "web/styles.css").read_text(encoding="utf-8")

        self.assertIn('aria-label="Vorherige Page"', html)

        self.assertIn('aria-label="Nächste Page"', html)

        self.assertNotIn("← Vorheriges", html)

        self.assertNotIn("Nächstes →", html)

        self.assertIn(".preview-nav-button", styles)

        self.assertIn(".preview-nav-arrow.arrow-left", styles)

        self.assertIn(".preview-nav-arrow.arrow-right", styles)

    def test_desktop_preview_controls_remain_centered(self):
        styles = (self.root / "web/styles.css").read_text(encoding="utf-8")

        toolbar = styles[
            styles.index("@media (min-width: 901px)"):
            styles.index(".active-tool {")

        ]
        self.assertIn("@media (min-width: 901px)", toolbar)

        self.assertIn("display: grid", toolbar)

        self.assertIn("justify-items: center", toolbar)

        self.assertIn(".preview-toolbar > div:first-child", toolbar)

        self.assertIn("justify-self: start", toolbar)

        self.assertIn("justify-content: center", toolbar)

    def test_phone_navigation_uses_a_bottom_action_bar(self):
        styles = (self.root / "web/styles.css").read_text(encoding="utf-8")

        phone = styles[styles.index("@media (max-width: 736px)"):]
        self.assertIn(".preview-tools-row-nav", phone)

        self.assertIn("position: fixed", phone)

        self.assertIn("safe-area-inset-bottom", phone)

        self.assertIn("padding-bottom: calc(76px", phone)

    def test_compact_desktop_keeps_navigation_buttons_on_one_lower_row(self):
        styles = (self.root / "web/styles.css").read_text(encoding="utf-8")

        compact = styles[
            styles.index("@media (min-width: 901px) and (max-width: 1459px)"):
            styles.index(".active-tool {")

        ]
        self.assertIn("grid-template-columns: auto auto", compact)

        self.assertIn("row-gap: 12px", compact)

        self.assertIn(".preview-tools-row-nav", compact)

        self.assertIn("grid-column: 1 / -1", compact)

        self.assertIn("justify-content: center", compact)

    def test_narrow_desktop_splits_preview_controls_into_three_rows(self):
        styles = (self.root / "web/styles.css").read_text(encoding="utf-8")

        narrow = styles[
            styles.index("@media (min-width: 901px) and (max-width: 1070px)"):
            styles.index(".active-tool {")

        ]
        self.assertIn("grid-template-columns: minmax(0, 1fr)", narrow)

        self.assertIn(".preview-tools-row-primary .secondary.small", narrow)

        self.assertIn(".preview-tools-row-nav .secondary.small", narrow)

        self.assertIn(".preview-tools-row-zoom .zoom-control", narrow)

        self.assertIn('input[type="range"]', narrow)

    def test_header_has_three_balanced_regions(self):
        html = (self.root / "web/index.html").read_text(encoding="utf-8")

        styles = (self.root / "web/styles.css").read_text(encoding="utf-8")

        self.assertIn('class="header-brand"', html)

        self.assertIn('class="header-brand-logo"', html)

        self.assertIn('src="/static/img/favicon.png"', html)

        self.assertIn('rel="icon" type="image/png"', html)

        login = (self.root / "web/login.html").read_text(encoding="utf-8")

        self.assertIn('/static/img/favicon.png?v=20260807-1', login)

        self.assertIn('>LingoVeil</h1>', html)

        self.assertIn("height: 1.45em", styles)

        self.assertIn('class="header-controls"', html)

        self.assertIn('id="header-updates"', html)

        self.assertIn(
            "grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr)",
            styles,
        )

        self.assertIn("justify-self: center", styles)

    def test_app_info_and_backend_update_check_exist(self):
        controls = (self.root / "app/live-controls.js").read_text(encoding="utf-8")

        compose = (self.root / "docker-compose.yml").read_text(encoding="utf-8")

        example = (self.root / ".env.example").read_text(encoding="utf-8")

        updater = (self.root / "src/lingoveil_update.py").read_text(encoding="utf-8")

        documentation = (self.root / "Dokumentation.md").read_text(encoding="utf-8")

        self.assertIn("VERSION = APP_VERSION", self.source)

        self.assertIn('@app.get("/api/app-update")', self.source)

        self.assertIn("check_updates_periodically", self.source)

        self.assertIn("if update_checker.automatic_enabled:", self.source)

        self.assertIn(
            'retry_seconds = 60 if result["status"] == "error"',
            self.source,
        )

        self.assertIn('addButton("Info & Support"', controls)

        self.assertIn('const logoutButton = addButton("Logout"', controls)

        self.assertIn('request("/api/logout"', controls)

        self.assertIn('window.location.replace("/login.html")', controls)

        self.assertIn('heading.textContent = uiText("Abmelden?")', controls)

        self.assertIn('hasUpdate ? "New Update"', controls)

        self.assertIn('tr("Projekt unterstützen")', controls)

        self.assertIn('supportHeart.src = "/static/img/pixel-heart-logo.svg"', controls)

        self.assertIn("app-info-support-heart", controls)

        self.assertIn("result.donation_wallet?.address", controls)

        self.assertIn("navigator.clipboard && window.isSecureContext", controls)

        self.assertIn('document.execCommand("copy")', controls)

        self.assertIn('tr("Adresse kopieren")', controls)

        self.assertIn("updateAppInfoButton", controls)

        self.assertIn('request("/api/app-update?force=false")', controls)

        self.assertIn('"Check-Update"', controls)

        self.assertIn("contact@gerald-hasani.com", controls)

        self.assertIn("/api/app-update?force=", controls)

        self.assertIn('UPDATE_ENABLED: "${update:-true}"', compose)

        self.assertIn("update=true", example)

        self.assertIn("update-instance-id", updater)

        self.assertIn('DONATION_WALLET_ID = 1', updater)

        self.assertIn('"wallet_ids": [DONATION_WALLET_ID]', updater)

        self.assertIn("donation-wallet-1.json", updater)

        self.assertIn("0x[0-9a-fA-F]{40}", updater)

        self.assertIn("Authorization", updater)

        self.assertIn('APP_VERSION = "3.1.5"', updater)

        self.assertIn('UPDATE_PROJECT_ID = "lingoveil-docker"', updater)

        self.assertIn(
            "upd_4d5c02e8e4fad4c80f0ddd311e5e83816a4cbdea1b99808877a0a9977f15dc78",
            updater,
        )

        self.assertNotIn("upd_4d5c02e8", controls)

        self.assertIn("automatic_updates_enabled", updater)

        self.assertIn('if result["status"] != "error":', updater)

        self.assertIn("Fehlt `update`", documentation)

if __name__ == "__main__":
    unittest.main()
