<img align="left" width="80" alt="favicon" src="https://github.com/user-attachments/assets/cb22d006-7eeb-4627-9782-493af6320e6b" />

# LingoVeil
<br>


**Read manga, comics, and image-based content in your own language — without manually copying text from speech bubbles.**

LingoVeil is a self-hosted translation tool with a particular focus on **comics and manga**.  
It detects text directly inside images, translates it into your chosen language, and creates a translated view of the page.

LingoVeil is not only intended for technically experienced users, but especially for readers who want to enjoy manga or comics even if they do not understand the original language — for example, English — well enough.

LingoVeil can process individual images and PDFs, load websites, and provides a dedicated reading mode for selected manga sites with chapters, bookmarks, and reading progress.

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/user-attachments/assets/11d06c31-6358-4688-9105-0e2ec97edc60" target="_blank">
        <img width="600" alt="translate1" src="https://github.com/user-attachments/assets/11d06c31-6358-4688-9105-0e2ec97edc60" />
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/user-attachments/assets/82dee316-9406-43eb-9d97-83e2722db473" target="_blank">
        <img width="600" alt="translate2" src="https://github.com/user-attachments/assets/82dee316-9406-43eb-9d97-83e2722db473" />
      </a>
    </td>
  </tr>
</table>

<img width="800" height="auto" alt="Dashboard" src="https://github.com/user-attachments/assets/9eae4834-23bf-42e1-bc42-5adcbd2d844f" />


---

## Why LingoVeil?

Many translation tools are designed for regular text. In manga and comics, however, the text is part of the image itself — spread across speech bubbles, panels, and different areas of a page.

LingoVeil automates most of this process:

1. **Load an image or manga page**
2. **Detect text inside the image**
3. **Translate the text**
4. **Display the translated page**
5. **Keep reading without having to copy each piece of text manually**

The main focus is to provide the smoothest possible reading experience.

---

## What LingoVeil Can Do

### Manga and Comic Translation

- OCR detection for text inside images
- Translation directly from manga, comic, and website images
- Support for direct image URLs and PDFs
- Switch between **Original** and **Translation**
- Zoom, pan, and automatic fit-to-window
- Multiple local translation engines
- Freely selectable target language depending on the selected engine

### Dedicated Manga Mode

For selected manga websites, LingoVeil provides additional features:

| Platform | Support |
|---|---|
| **MangaDex** | Chapter selection, chapters grouped by volume, and direct image retrieval |
| **MangaRead** | Manga main page with complete chapter selection |
| **MangaTown** | Chapter selection and merging of multiple chapter pages |

Direct chapter links can also be opened.

For supported manga websites, LingoVeil also detects the title, volume, and chapter and automatically stores this information in the history.

---

## Smartphone and Tablet

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/user-attachments/assets/8e2665df-a010-445e-8df8-ab7a662ac75e" target="_blank">
        <img height="500" alt="translate2" src="https://github.com/user-attachments/assets/8e2665df-a010-445e-8df8-ab7a662ac75e" />
      </a>
    </td>
  </tr>
</table>


LingoVeil has a **responsive user interface** that automatically adapts to smaller displays. This means LingoVeil can be used comfortably not only on desktop computers, but also on **smartphones and tablets**.

If your smartphone is connected to the same network as the LingoVeil server, you can access LingoVeil directly through the server's local IP address, for example:

```text
http://192.168.1.100:8765
```

If LingoVeil is available through your own domain with HTTPS, you can also access it outside your home network just like a normal website:

```text
https://lingoveil.example.org
```

This allows the actual LingoVeil server to run on a PC, home server, or NAS while manga can be comfortably read and translated on a smartphone.

---

## Bookmarks and Reading Progress

Manga can be saved directly as bookmarks in LingoVeil.

<img width="auto" height="500" alt="bookmarked" src="https://github.com/user-attachments/assets/ed270baf-1233-4450-9e8e-c0da7b67c3ef" />


LingoVeil remembers, among other things:

- the manga
- the last chapter read
- chapters that have already been read
- date and time of the last reading session
- existing translations and images within the configured cache limit

The next time a bookmark is opened, the chapter selection is shown again. The most recently read chapter is highlighted.

The chapter order can also be reversed if needed.

---

## Automatic Notifications for New Chapters

Optionally, LingoVeil can regularly check saved manga bookmarks for new chapters.

If the server has been configured for sending email, each user can decide individually whether they want to receive notifications.

New chapters are grouped into a single email instead of sending a separate message for every chapter.

This feature is disabled by default.

---

## Translation Engines

LingoVeil supports several translation methods.

### SeamlessM4T v2 Large

**Recommended when translation quality and language selection are more important than speed.**

- supports 96 target text languages
- can take longer context into account more effectively
- can be used entirely locally
- requires significantly more RAM and processing power
- model download is approximately **8.7 GiB**
- comparatively slow when used on CPU
- model license: **CC-BY-NC-4.0**

### Bergamot

**Recommended for lower-end hardware or faster translations.**

Bergamot is smaller and starts faster. In the model registry used by LingoVeil, translations from detected English text are available for the following languages:

- Bulgarian
- Czech
- German
- Spanish
- Estonian
- French
- Italian
- Portuguese
- Russian
- Ukrainian

### LanguageTool

LanguageTool can optionally be used together with Bergamot.

OCR does not always recognize text perfectly. LanguageTool can check the detected English source text for selected spelling and grammar issues before translation.

It is **not a translation engine of its own**.

### LM Studio

Administrators can additionally use their own model provided through **LM Studio**.

The LM Studio configuration is visible to administrators only.

### Ollama / TranslateGemma

Administrators can connect a standalone Ollama server under **Options → Models → Local LLM → Ollama**. LingoVeil uses Ollama's native `/api/tags`, `/api/show`, and `/api/chat` endpoints; it does not use an OpenAI-compatible proxy.

The recommended Docker setup keeps Ollama safely bound to `127.0.0.1:11434` and installs a restricted LingoVeil bridge:

```bash
ollama pull translategemma:4b
sudo python3 scripts/install_lingoveil_ollama_bridge.py
docker compose up -d --force-recreate lingoveil-live
```

Recreating `lingoveil-live` is required after installation so that the container reads the generated bridge token from `.env`. Then open **Options → Models → Ollama → Test connection**. Ollama can only be selected after a successful test.

The installer dynamically detects Docker's `host-gateway`; no Docker subnet or IP needs to be entered. The bridge listens only on that host-gateway at port `11435`, forwards only `GET /api/tags`, `POST /api/show`, and `POST /api/chat` to loopback Ollama, and requires a generated Bearer token. Its unprivileged runtime process has no Docker socket access. Re-running the installer updates the bridge while preserving its token. To remove it:

```bash
sudo python3 scripts/uninstall_lingoveil_ollama_bridge.py
```

If a host firewall such as UFW uses a default-deny policy, it may also block containers from reaching the host bridge. A typical symptom is that the installer reports `Bridge host test succeeded, but Docker test failed` or that **Test connection** times out. The Compose configuration gives LingoVeil's Docker bridge the stable interface name `lingoveil0`, which remains the same after a server restart or `docker compose down` followed by `up`. On Ubuntu with UFW, allow only that interface to reach the detected host-gateway:

```bash
OLLAMA_BRIDGE_ADDRESS="$(docker network inspect bridge --format '{{range .IPAM.Config}}{{if .Gateway}}{{.Gateway}}{{end}}{{end}}')"
if [ -z "$OLLAMA_BRIDGE_ADDRESS" ] || ! ip link show lingoveil0 >/dev/null 2>&1; then
  echo 'Host-gateway or lingoveil0 missing; recreate the updated Compose network first' >&2
else
  printf 'interface=lingoveil0 destination=%s\n' "$OLLAMA_BRIDGE_ADDRESS"
  sudo ufw allow in on lingoveil0 to "$OLLAMA_BRIDGE_ADDRESS" port 11435 proto tcp comment 'LingoVeil Ollama Bridge'
  docker exec lingoveil-live python -c "import socket; s=socket.create_connection(('host.docker.internal', 11435), 5); print('Bridge reachable'); s.close()"
fi
```

Review the printed destination before applying the rule. Never allow port `11435` from `Anywhere` or the LAN; the rule must remain limited to `lingoveil0`. Installations created with an older Compose file must recreate the network once with `docker compose down && docker compose up -d` before adding this rule. Then run the installer again and recreate `lingoveil-live` so it loads the new token. If UFW is inactive or the container test already succeeds, no firewall rule is needed. Existing rules can be reviewed and removed with `sudo ufw status numbered` and `sudo ufw delete <number>`.

The default URL is `http://host.docker.internal:11435`. It remains editable for users who already operate a secured remote or directly reachable Ollama server. As an advanced alternative, Ollama can listen on `0.0.0.0:11434`, but that exposes it on every host interface unless a firewall restricts access and is therefore not recommended. LingoVeil has successfully tested `translategemma:4b`; other variants remain known but untested. A runtime connection failure disables Ollama without silently switching engines.

---

## Multiple Users

LingoVeil supports multiple separate user accounts.

Each user has their own:

- history
- manga bookmarks
- reading progress
- settings
- target language
- backup file

The **first successfully registered account becomes the administrator**.

After that, additional registrations are disabled by default. The administrator can enable or disable them under:

**Options → Admin → Registration**

The administrator also manages installed models and the optional LM Studio connection.

> **Note:** Multiple users share the same CPU, GPU, and available system memory of the server. Many simultaneous translations may therefore be slower on lower-end hardware.

---
# Installation

LingoVeil Live runs using Docker.

## Requirements

You need:

- Docker
- Docker Compose
- sufficient free storage space for the desired models
- optionally an NVIDIA GPU for faster processing

For normal operation, no manually prepared data directories are required. LingoVeil uses Docker volumes, which means its data is stored persistently outside the actual container.

---

## 1. Create the Configuration

Inside the LingoVeil project directory:

```bash
cp .env.example .env
```

Then open `.env`.

Before the first start, both values containing `change-me` must be replaced with **the same secure password**.

Example:

```dotenv
LINGOVEIL_POSTGRES_PASSWORD=my-long-secure-password
LINGOVEIL_DATABASE_URL=postgresql://lingoveil:my-long-secure-password@postgres:5432/lingoveil
```

The default PostgreSQL port on the host is:

```dotenv
LINGOVEIL_POSTGRES_PORT=5434
```

Normally, this value does not need to be changed.

---

## 2. Start LingoVeil

```bash
docker compose up -d --build
```

Check the status:

```bash
docker compose ps
```

Then open in your browser:

```text
http://localhost:8765
```

On the first visit, register the administrator account.

---

## 3. Stop or Restart LingoVeil

Stop:

```bash
docker compose stop
```

Start:

```bash
docker compose up -d
```

Restart:

```bash
docker compose restart
```

Remove containers while keeping stored data:

```bash
docker compose down
```

> **Warning:** `docker compose down -v` also removes the Docker volumes and therefore deletes stored data. This command should not be used for normal shutdowns.

---

## Using an NVIDIA GPU

CPU mode is the default and works without any additional GPU configuration.

For NVIDIA GPUs, a compatible NVIDIA driver and the NVIDIA Container Toolkit are required.

Then start LingoVeil with the GPU configuration:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

If CUDA is not available, the CPU can still be used.

---

# Usage

## Translate a Manga or Image

After signing in, you can open a supported URL.

Depending on the URL, LingoVeil loads either:

- a single image
- a PDF file
- a website containing images
- a manga chapter directly
- or the chapter selection of a supported manga

LingoVeil then handles OCR and translation.

Existing translations using the same engine and target language can be reused from the history, which can make reopening content significantly faster.

Using **Translate Again**, you can force a new translation at any time for the currently selected engine and language.

---

## Interface and Translation Language

Under:

**Options → General**

there are two independent language settings.

### Interface Language

Determines the language of the LingoVeil user interface.

Currently available:

- German
- English

### Translation Target Language

Determines the language into which manga, comic, and image text is translated.

The available target languages depend on the selected translation engine.

---

## Prefetch

LingoVeil can translate upcoming images in the background before they are opened.

This means you are less likely to have to wait for the next translation while turning pages.

The default value is:

```text
10 images
```

A higher value can make reading smoother, but requires more:

- CPU performance
- GPU performance
- system memory
- time in the translation queue

A lower value is recommended on lower-end hardware.

---

# Backup and Restore

## Personal Backup

Under:

**Options → Backup / Restore**

each user can export their personal LingoVeil data.

Included are:

- personal settings
- history
- bookmarks
- reading progress

Not included are, among other things:

- password
- sessions
- user role
- SMTP credentials
- server configuration
- installed models

The backup can later be imported back into LingoVeil.

---

<details>
<summary><strong>Server Backup for Administrators</strong></summary>

For a complete server backup, PostgreSQL and the Docker volumes should be backed up.

For example, a PostgreSQL dump can be created as follows:

```bash
docker compose exec -T postgres pg_dump -U lingoveil -d lingoveil -Fc > lingoveil-postgres.dump
```

The most important volumes are:

| Volume | Contents |
|---|---|
| `lingoveil-postgres` | users, history, bookmarks, jobs, and settings |
| `lingoveil-models` | installed models |
| `lingoveil-data` | LingoVeil configuration |
| `lingoveil-cache` | images, renderings, and cache data |

</details>

---

# Optional Email Setup

Email is used for the following features:

- notifications about new manga chapters
- password recovery

Without SMTP configuration, LingoVeil continues to work normally. The corresponding email features will simply not be available.

<details>
<summary><strong>Configure SMTP</strong></summary>

Example `.env` configuration:

```dotenv
LINGOVEIL_SMTP_HOST=smtp.example.org
LINGOVEIL_SMTP_PORT=587
LINGOVEIL_SMTP_USE_TLS=true
LINGOVEIL_SMTP_USERNAME=lingoveil@example.org
LINGOVEIL_SMTP_PASSWORD=...
LINGOVEIL_SMTP_FROM=lingoveil@example.org
LINGOVEIL_SMTP_FROM_NAME=LingoVeil Manga Updates
LINGOVEIL_PUBLIC_URL=https://lingoveil.example.org
```

For port `587`, STARTTLS is normally used:

```dotenv
LINGOVEIL_SMTP_USE_TLS=true
```

For implicit SSL on port `465`:

```dotenv
LINGOVEIL_SMTP_USE_TLS=false
```

`LINGOVEIL_PUBLIC_URL` is optional.

</details>

---

# Public Deployment

If LingoVeil is intended to be accessible publicly over the internet rather than only within your own network, at least the following measures should be implemented:

- use HTTPS
- set a strong PostgreSQL password
- enable secure session cookies
- use a reverse proxy
- configure rate limits or comparable protection

When using HTTPS:

```dotenv
LINGOVEIL_SESSION_COOKIE_SECURE=true
```

In the default configuration, PostgreSQL is only accessible from the host through `127.0.0.1`.

---

# Updates

By default, LingoVeil checks for a new version at startup and then approximately every 6 hours.

When updating an existing installation, compare your `.env` with `.env.example` and add newly introduced variables manually. Do not replace the complete `.env`, because it contains installation-specific passwords and secrets. Version 3.1.7 adds these Ollama settings:

```dotenv
LINGOVEIL_OLLAMA_BASE_URL=http://host.docker.internal:11435
LINGOVEIL_OLLAMA_BRIDGE_TOKEN=
LINGOVEIL_OLLAMA_MODEL=translategemma:4b
LINGOVEIL_OLLAMA_TIMEOUT_SEC=120
LINGOVEIL_OLLAMA_KEEP_ALIVE=2m
```

The bridge installer fills `LINGOVEIL_OLLAMA_BRIDGE_TOKEN` automatically. Matching `LINGOVEIL_OLLAMA_KEEP_ALIVE` to `LINGOVEIL_ENGINE_IDLE_MINUTES` lets Ollama release its model on the same schedule as LingoVeil's local workers.

The automatic check can be disabled in `.env`:

```dotenv
update=false
```

A manual check through:

**Info & Support → Check Update**

remains available.

With:

```dotenv
update=true
```

automatic update checks are enabled again.

---

# Advanced Configuration

For most installations, the default values are sufficient.

<details>
<summary><strong>Show Important Environment Variables</strong></summary>

| Variable | Default | Description |
|---|---:|---|
| `LINGOVEIL_LIVE_PORT` | `8765` | LingoVeil web port |
| `LINGOVEIL_POSTGRES_PORT` | `5434` | optional PostgreSQL port on the host |
| `LINGOVEIL_SESSION_HOURS` | `72` | login session lifetime |
| `LINGOVEIL_SESSION_COOKIE_SECURE` | `false` | set to `true` when using HTTPS |
| `LINGOVEIL_SMTP_*` | empty | optional email configuration |
| `LINGOVEIL_PUBLIC_URL` | empty | public URL for links in emails |
| `LINGOVEIL_BERGAMOT_LANGUAGETOOL_ENABLED` | `false` | local LanguageTool correction for Bergamot |
| `LINGOVEIL_ENGINE_IDLE_MINUTES` | `2` | unload EasyOCR, Bergamot and Seamless after this idle period; `0` disables the timer |
| `LINGOVEIL_OLLAMA_BASE_URL` | `http://host.docker.internal:11435` | bridge or native Ollama API URL |
| `LINGOVEIL_OLLAMA_BRIDGE_TOKEN` | empty | secret generated by the recommended bridge installer |
| `LINGOVEIL_OLLAMA_MODEL` | `translategemma:4b` | exact Ollama model name |
| `LINGOVEIL_OLLAMA_TIMEOUT_SEC` | `120` | Ollama request timeout in seconds |
| `LINGOVEIL_OLLAMA_KEEP_ALIVE` | `2m` | Ollama model keep-alive value |
| `update` | `true` | automatic update check |

</details>

<details>
<summary><strong>Enable LanguageTool for Bergamot</strong></summary>

After installation through:

**Options → Models → LanguageTool (local)**

set the following in `.env`:

```dotenv
LINGOVEIL_BERGAMOT_LANGUAGETOOL_ENABLED=true
LINGOVEIL_BERGAMOT_LANGUAGETOOL_TIMEOUT_SEC=5
```

Then run:

```bash
docker compose up -d --force-recreate lingoveil-live
```

</details>

---

# Limitations

LingoVeil handles much of the work automatically, but OCR and machine translation are not perfect in every situation.

The following can be particularly difficult, for example:

- very small text
- heavily stylized fonts
- handwritten text
- low-quality or heavily compressed images
- unusual speech bubbles or overlapping text

In addition:

- website analysis does not execute JavaScript
- logins and paywalls are not bypassed
- large models require a corresponding amount of RAM and storage space
- CPU translation can be slow depending on the model and hardware
- the GPU configuration has not been tested on every NVIDIA GPU

---

# Troubleshooting

Container status:

```bash
docker compose ps
```

Show logs:

```bash
docker compose logs -f
```

Health check:

```bash
curl http://localhost:8765/api/health
```

If you experience problems, check the following first:

- is the container running?
- is enough storage space available?
- was the selected model loaded completely?
- is PostgreSQL reachable?
- is enough RAM or GPU memory available?

---
