# LingoVeil 3.1.5

Version 3.1.5 expands LingoVeil with a fully local Ollama/TranslateGemma integration and improves memory efficiency during longer Docker sessions.

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
