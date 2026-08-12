# LingoVeil 3.2.1

Version 3.2.1 fixes translation of text-based PDF files loaded through the URL input.

## PDF Translation Fixes

* Selectable PDF text is now extracted directly with its page coordinates and translated without starting OCR.
* Image-only PDFs and PDF pages without extractable text continue to use EasyOCR as a fallback.
* PDF translation results now include the target language, group count, text source, and rendered-image URL expected by the web interface.
* Completed PDF jobs are no longer incorrectly discarded by the browser as results for an outdated target language.

## Mobile Background Queue

* Configured prefetch pages are submitted immediately to the persistent backend queue instead of waiting in a browser-only JavaScript queue.
* Translation continues on the server when a mobile browser tab is suspended or the phone screen is turned off.
* Thumbnail states now follow the backend job state and distinguish queued work from the page currently being translated.

## Bookmark Chapter Downloads

* Every chapter in a bookmarked manga now has a download-arrow action that queues the complete chapter for translation.
* Chapter pages are submitted to the persistent backend queue in one action and remain available through the bookmark/history cache for later reading without translation delays.
* Downloading a chapter does not mark it as read or alter the last-read position.
* Cached chapters are tracked separately and pruned according to **Saved chapters per bookmark (0 = unlimited)**; `0` keeps all downloaded chapters.
* Reopened chapters now restore active backend states for every page, showing queued, translating, and translated pages accurately instead of displaying them as open.
* Selecting a page already present in the chapter-download queue reuses its existing job rather than creating a duplicate behind the whole chapter.
* Bookmark dialogs remain available while translations run, and dynamic thumbnail states follow the selected interface language.
* Image dimensions are resolved before filtering or automatic prefetch, preventing short banners and logos from starting translation before their size is known.
* Gallery selection is no longer globally blocked by another page's translation; cached translated pages open immediately, while stale async results cannot overwrite the newly selected preview.
* Chapter download icons now distinguish an incomplete/queued download (`…`) from a fully processed chapter (`✓`); filtered pages count as processed, while failed or cancelled pages keep the chapter incomplete.
* Starting a chapter download updates matching open gallery pages immediately and continues synchronizing queued, translating, translated, and failed states without requiring a page refresh.
* The chapter-selection dialog now shows each chapter's own last-read timestamp. Reading another chapter no longer removes the read marker from previously visited chapters.

# LingoVeil 3.1.7

Version 3.1.7 improves the English interface language, adds image filtering controls, expands LingoVeil with a fully local Ollama/TranslateGemma integration, and improves memory efficiency during longer Docker sessions.

## Interface Language Improvements

* The English interface translation has been improved throughout the application.
* Remaining German labels in History, Bookmarks, and the bookmark chapter dialog are now displayed in English when English is selected as the interface language.
* Dynamic status text, including translated-image counts, last-read information, empty reading states, and chapter ordering, is now translated correctly.
* Input placeholders, including bookmark search and website, image, or PDF URL fields, now follow the selected interface language.
* Nested accessibility labels, titles, and placeholders are translated reliably, including when the interface language changes while the application is running.

## OCR and Translation Image Filters

* A new **Filter** tab is available in the **Options** dialog.
* Minimum image width and height thresholds can be configured to automatically exclude small loaded images from OCR and translation.
* Images at or below either configured threshold are skipped, reducing unnecessary OCR and translation work and saving CPU, memory, and translation resources.
* Setting a threshold to `0` disables that individual filter.

## Ollama and TranslateGemma

* Ollama is available as a standalone translation engine alongside Bergamot, SeamlessM4T, and LM Studio.
* The integration directly uses Ollama's native `/api/tags`, `/api/show`, and `/api/chat` endpoints.
* `translategemma:4b` has been successfully tested; additional model variants can be tried, but are not automatically considered officially tested.
* Source and target languages are filtered based on the known capabilities of the selected model.
* Structured responses preserve the exact OCR group IDs. Incomplete or invalid model responses are retried selectively instead of being guessed.
* Ollama connection states are persistently tracked as not configured, not tested, available, or unavailable.
* If a runtime error occurs, Ollama is disabled and a clear error message is shown. LingoVeil does not silently switch to another engine.

## Secure Ollama Bridge for Docker

* The new LingoVeil Ollama Bridge allows Ollama to remain bound exclusively to `127.0.0.1:11434`.
* Docker reaches the bridge through `http://host.docker.internal:11435`.
* The bind address is dynamically determined from Docker's actual `host-gateway`; Docker IP addresses and subnets are not hardcoded.
* A cryptographically random Bearer token provides additional protection against access from other local containers.
* The bridge only allows `GET /api/tags`, `POST /api/show`, and `POST /api/chat`.
* The running unprivileged bridge process has no access to the Docker socket.
* Idempotent installation and uninstallation scripts, as well as systemd hardening, are included.

Installation:

```bash
ollama pull translategemma:4b
sudo python3 scripts/install_lingoveil_ollama_bridge.py
docker compose up -d --build
```

## Lower Memory Usage

* EasyOCR, overlay, and SeamlessM4T workers are terminated after the configured idle period.
* Preview and PDF caches are cleared during inactivity; garbage collection and `malloc_trim` release additional native memory.
* Ollama's `keep_alive` can be synchronized with `LINGOVEIL_ENGINE_IDLE_MINUTES`. Setting both to two minutes also causes the Ollama model to be unloaded promptly.
* In local long-running tests, the LingoVeil container stabilized at approximately 256 MiB RAM after idle unloading. Actual memory usage depends on the platform, images, concurrency, and installed components.
* Cache keys reliably separate engines, models, language pairs, and prompt versions.
* Identical OCR texts are translated only once and then correctly distributed to all associated text groups.

## Usability and Reliability

* LM Studio and Ollama can be configured together under “Local LLM”.
* Ollama can only be selected after a successful connection test.
* Languages that are incompatible with the selected model are not offered.
* The Docker bridge reliably detects start/stop transitions and waits for listener and port readiness during installation.
* The automatic update check now runs at startup and then every six hours.

## Note for Existing Installations

Do not overwrite the existing `.env` file. New variables from `.env.example` must be added manually; the bridge installer manages the token entry automatically.

For a shared two-minute idle period:

```dotenv
LINGOVEIL_ENGINE_IDLE_MINUTES=2
LINGOVEIL_OLLAMA_KEEP_ALIVE=2m
```
