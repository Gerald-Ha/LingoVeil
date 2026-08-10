<img align="left" width="80" alt="favicon" src="https://github.com/user-attachments/assets/cb22d006-7eeb-4627-9782-493af6320e6b" />

# LingoVeil
<br>

**Mangas, Comics und Bildinhalte in deiner Sprache lesen – ohne Texte aus Sprechblasen manuell kopieren zu müssen.**

LingoVeil ist ein selbst gehostetes Übersetzungstool mit besonderem Fokus auf **Comics und Mangas**.  
Es erkennt Text direkt aus Bildern, übersetzt ihn in die gewünschte Sprache und erstellt daraus eine übersetzte Ansicht der Seite.

Damit richtet sich LingoVeil nicht nur an technisch versierte Nutzer, sondern vor allem an Leser, die Mangas oder Comics lesen möchten, obwohl sie die ursprüngliche Sprache – beispielsweise Englisch – nicht ausreichend beherrschen.

LingoVeil kann einzelne Bilder und PDFs verarbeiten, Webseiten laden und bietet für ausgewählte Manga-Seiten einen eigenen Lesemodus mit Chaptern, Bookmarks und Lesefortschritt.

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

## Warum LingoVeil?

Viele Übersetzungstools sind auf normalen Fließtext ausgelegt. Bei Mangas und Comics steckt der Text dagegen direkt im Bild – verteilt auf Sprechblasen, Panels und unterschiedliche Bereiche einer Seite.

LingoVeil übernimmt diesen Ablauf weitgehend automatisch:

1. **Bild oder Manga-Seite laden**
2. **Text im Bild erkennen**
3. **Text übersetzen**
4. **Übersetzte Seite anzeigen**
5. **Weiterlesen, ohne jeden Text einzeln kopieren zu müssen**

Der Schwerpunkt liegt dabei auf einem möglichst angenehmen Lesefluss.

---

## Das kann LingoVeil

### Manga- und Comic-Übersetzung

- OCR-Erkennung für Text innerhalb von Bildern
- Übersetzung direkt aus Manga-, Comic- und Webseitenbildern
- Unterstützung für direkte Bild-URLs und PDFs
- Wechsel zwischen **Original** und **Übersetzung**
- Zoom, Verschieben und automatische Anpassung an das Fenster
- verschiedene lokale Übersetzungsengines
- frei wählbare Zielsprache abhängig von der verwendeten Engine

### Spezieller Manga-Modus

Für einige Manga-Seiten bietet LingoVeil zusätzliche Funktionen:

| Plattform | Unterstützung |
|---|---|
| **MangaDex** | Chapter-Auswahl, nach Volumes gruppierte Chapter und direkter Bildabruf |
| **MangaRead** | Manga-Hauptseite mit vollständiger Chapter-Auswahl |
| **MangaTown** | Chapter-Auswahl und Zusammenführung mehrerer Chapter-Seiten |

Direkte Chapter-Links können ebenfalls geöffnet werden.

Bei unterstützten Manga-Seiten erkennt LingoVeil außerdem Titel, Volume und Chapter und speichert diese Informationen automatisch in der History.

---

## Bookmarks und Lesefortschritt

Mangas können direkt in LingoVeil als Bookmark gespeichert werden.

Dabei merkt sich LingoVeil unter anderem:

- den Manga
- das zuletzt gelesene Chapter
- bereits gelesene Chapter
- Datum und Uhrzeit des letzten Lesens
- vorhandene Übersetzungen und Bilder innerhalb des konfigurierten Cache-Limits

Beim nächsten Öffnen eines Bookmarks erscheint wieder die Chapter-Auswahl. Das zuletzt gelesene Chapter wird hervorgehoben.

Die Chapter-Reihenfolge kann bei Bedarf umgedreht werden.

---

## Automatische Benachrichtigungen für neue Chapter

Optional kann LingoVeil gespeicherte Manga-Bookmarks regelmäßig auf neue Chapter prüfen.

Wenn der Server für E-Mail-Versand eingerichtet wurde, kann jeder Benutzer selbst entscheiden, ob er Benachrichtigungen erhalten möchte.

Neue Chapter werden in einer gemeinsamen E-Mail zusammengefasst, anstatt für jedes Chapter eine einzelne Nachricht zu senden.

Die Funktion ist standardmäßig deaktiviert.

---

## Übersetzungsengines

LingoVeil unterstützt mehrere Übersetzungswege.

### SeamlessM4T v2 Large

**Empfohlen, wenn Übersetzungsqualität und Sprachauswahl wichtiger als Geschwindigkeit sind.**

- unterstützt 96 Text-Zielsprachen
- kann längere Zusammenhänge besser berücksichtigen
- vollständig lokal verwendbar
- benötigt deutlich mehr Arbeitsspeicher und Rechenleistung
- Modelldownload ungefähr **8,7 GiB**
- auf CPU vergleichsweise langsam
- Lizenz des Modells: **CC-BY-NC-4.0**

### Bergamot

**Empfohlen für schwächere Hardware oder schnellere Übersetzungen.**

Bergamot ist kleiner und startet schneller. In der mit LingoVeil verwendeten Modellregistry stehen Übersetzungen vom erkannten englischen Text in folgende Sprachen zur Verfügung:

- Bulgarisch
- Tschechisch
- Deutsch
- Spanisch
- Estnisch
- Französisch
- Italienisch
- Portugiesisch
- Russisch
- Ukrainisch

### LanguageTool

LanguageTool kann optional zusammen mit Bergamot verwendet werden.

OCR erkennt Text nicht immer fehlerfrei. LanguageTool kann den erkannten englischen Ausgangstext vor der Übersetzung auf ausgewählte Rechtschreib- und Grammatikfehler prüfen.

Es ist **keine eigene Übersetzungsengine**.

### LM Studio

Administratoren können zusätzlich ein eigenes über **LM Studio** bereitgestelltes Modell verwenden.

Die LM-Studio-Konfiguration ist ausschließlich für Administratoren sichtbar.

### Ollama / TranslateGemma

Administratoren können unter **Optionen → Modelle → Local LLM → Ollama** einen eigenständigen Ollama-Server anbinden. LingoVeil verwendet dabei direkt die nativen Endpunkte `/api/tags`, `/api/show` und `/api/chat` und keinen OpenAI-kompatiblen Proxy.

Die empfohlene Docker-Einrichtung lässt Ollama sicher an `127.0.0.1:11434` gebunden und installiert eine eingeschränkte LingoVeil-Bridge:

```bash
ollama pull translategemma:4b
sudo python3 scripts/install_lingoveil_ollama_bridge.py
docker compose up -d --force-recreate lingoveil-live
```

Nach der Installation muss `lingoveil-live` neu erstellt werden, damit der Container den generierten Bridge-Token aus `.env` einliest. Danach **Optionen → Modelle → Ollama → Verbindung testen** öffnen. Erst nach einem erfolgreichen Test lässt sich Ollama als Engine auswählen.

Der Installer erkennt Dockers `host-gateway` dynamisch; eine Docker-IP oder ein Subnetz muss nicht eingetragen werden. Die Bridge lauscht ausschließlich an diesem Host-Gateway auf Port `11435`, leitet nur `GET /api/tags`, `POST /api/show` und `POST /api/chat` an das lokale Ollama weiter und verlangt ein generiertes Bearer-Token. Ihr unprivilegierter Laufzeitprozess besitzt keinen Docker-Socket-Zugriff. Ein erneuter Installer-Aufruf aktualisiert die Bridge und erhält das Token. Deinstallation:

```bash
sudo python3 scripts/uninstall_lingoveil_ollama_bridge.py
```

Verwendet die Host-Firewall wie UFW eine standardmäßige Deny-Regel, kann sie auch den Zugriff von Containern auf die Host-Bridge blockieren. Typische Symptome sind die Installer-Meldung `Bridge host test succeeded, but Docker test failed` oder ein Timeout bei **Verbindung testen**. Die Compose-Konfiguration gibt LingoVeils Docker-Bridge den festen Interfacenamen `lingoveil0`, der nach einem Serverneustart sowie nach `docker compose down` und anschließendem `up` unverändert bleibt. Unter Ubuntu mit UFW wird ausschließlich dieses Interface für das erkannte Host-Gateway freigegeben:

```bash
OLLAMA_BRIDGE_ADDRESS="$(docker network inspect bridge --format '{{range .IPAM.Config}}{{if .Gateway}}{{.Gateway}}{{end}}{{end}}')"
if [ -z "$OLLAMA_BRIDGE_ADDRESS" ] || ! ip link show lingoveil0 >/dev/null 2>&1; then
  echo 'Host-Gateway oder lingoveil0 fehlt; zuerst das aktualisierte Compose-Netz neu erstellen' >&2
else
  printf 'interface=lingoveil0 destination=%s\n' "$OLLAMA_BRIDGE_ADDRESS"
  sudo ufw allow in on lingoveil0 to "$OLLAMA_BRIDGE_ADDRESS" port 11435 proto tcp comment 'LingoVeil Ollama Bridge'
  docker exec lingoveil-live python -c "import socket; s=socket.create_connection(('host.docker.internal', 11435), 5); print('Bridge reachable'); s.close()"
fi
```

Das ausgegebene Ziel muss vor dem Anwenden der Regel geprüft werden. Port `11435` niemals für `Anywhere` oder das LAN freigeben; die Regel muss auf `lingoveil0` begrenzt bleiben. Installationen mit einer älteren Compose-Datei müssen das Netz vor dem Hinzufügen dieser Regel einmal mit `docker compose down && docker compose up -d` neu erstellen. Anschließend den Installer erneut ausführen und `lingoveil-live` neu erstellen, damit der neue Token geladen wird. Ist UFW inaktiv oder der Container-Test bereits erfolgreich, wird keine Firewall-Regel benötigt. Vorhandene Regeln lassen sich mit `sudo ufw status numbered` prüfen und mit `sudo ufw delete <Nummer>` entfernen.

Die Standard-URL lautet `http://host.docker.internal:11435`. Sie bleibt für bereits abgesicherte entfernte oder direkt erreichbare Ollama-Server editierbar. Als Expertenalternative kann Ollama an `0.0.0.0:11434` lauschen; dies exponiert Ollama jedoch ohne einschränkende Firewall auf allen Host-Interfaces und wird daher nicht empfohlen. Erfolgreich getestet ist `translategemma:4b`; weitere Varianten gelten weiterhin nur als bekannt und ungetestet. Bei einem Laufzeitfehler deaktiviert LingoVeil Ollama, ohne stillschweigend die Engine zu wechseln.

---

## Mehrere Benutzer

LingoVeil unterstützt mehrere getrennte Benutzerkonten.

Jeder Benutzer besitzt seine eigene:

- History
- Manga-Bookmarks
- Lesefortschritte
- Einstellungen
- Zielsprache
- Backup-Datei

Das **erste erfolgreich registrierte Konto wird Administrator**.

Danach sind weitere Registrierungen standardmäßig deaktiviert. Der Administrator kann sie unter:

**Optionen → Admin → Registrierung**

aktivieren oder wieder sperren.

Der Administrator verwaltet außerdem installierte Modelle sowie die optionale LM-Studio-Verbindung.

> **Hinweis:** Mehrere Benutzer teilen sich dieselbe CPU, GPU und den verfügbaren Arbeitsspeicher des Servers. Viele gleichzeitige Übersetzungen können deshalb auf schwächerer Hardware langsamer werden.

---
## Smartphone und Tablet

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/user-attachments/assets/8e2665df-a010-445e-8df8-ab7a662ac75e" target="_blank">
        <img height="500" alt="translate2" src="https://github.com/user-attachments/assets/8e2665df-a010-445e-8df8-ab7a662ac75e" />
      </a>
    </td>
  </tr>
</table>

LingoVeil besitzt eine **responsive Benutzeroberfläche** und passt sich automatisch an kleinere Displays an. Dadurch lässt sich LingoVeil nicht nur am Desktop, sondern auch bequem auf **Smartphones und Tablets** verwenden.

Wenn sich dein Smartphone im selben Netzwerk wie der LingoVeil-Server befindet, kannst du LingoVeil direkt über die lokale IP-Adresse des Servers aufrufen, zum Beispiel:

```text
http://192.168.1.100:8765
```

Ist LingoVeil über eine eigene Domain und HTTPS erreichbar, kannst du es auch außerhalb deines Heimnetzwerks wie eine normale Webseite öffnen:

```text
https://lingoveil.example.org
```

So kann der eigentliche LingoVeil-Server beispielsweise auf einem PC, Homeserver oder NAS laufen, während Mangas bequem auf dem Smartphone gelesen und übersetzt werden.



---
# Installation

LingoVeil Live wird mit Docker betrieben.

## Voraussetzungen

Du benötigst:

- Docker
- Docker Compose
- ausreichend freien Speicherplatz für die gewünschten Modelle
- optional eine NVIDIA-GPU für schnellere Verarbeitung

Für den normalen Betrieb sind keine manuell vorbereiteten Datenordner notwendig. LingoVeil verwendet Docker Volumes und speichert seine Daten dadurch dauerhaft außerhalb des eigentlichen Containers.

---

## 1. Konfiguration anlegen

Im LingoVeil-Projektordner:

```bash
cp .env.example .env
```

Öffne anschließend `.env`.

Vor dem ersten Start müssen die beiden Werte mit `change-me` durch **dasselbe sichere Passwort** ersetzt werden.

Beispiel:

```dotenv
LINGOVEIL_POSTGRES_PASSWORD=mein-langes-sicheres-passwort
LINGOVEIL_DATABASE_URL=postgresql://lingoveil:mein-langes-sicheres-passwort@postgres:5432/lingoveil
```

Der voreingestellte PostgreSQL-Port auf dem Host ist:

```dotenv
LINGOVEIL_POSTGRES_PORT=5434
```

Normalerweise muss dieser Wert nicht geändert werden.

---

## 2. LingoVeil starten

```bash
docker compose up -d --build
```

Status prüfen:

```bash
docker compose ps
```

Danach im Browser öffnen:

```text
http://localhost:8765
```

Beim ersten Aufruf registrierst du das Administratorkonto.

---

## 3. LingoVeil stoppen oder neu starten

Stoppen:

```bash
docker compose stop
```

Starten:

```bash
docker compose up -d
```

Neu starten:

```bash
docker compose restart
```

Container entfernen, gespeicherte Daten aber behalten:

```bash
docker compose down
```

> **Achtung:** `docker compose down -v` löscht zusätzlich die Docker Volumes und damit gespeicherte Daten. Dieser Befehl sollte nicht zum normalen Stoppen verwendet werden.

---

## NVIDIA-GPU verwenden

CPU-Betrieb ist der Standard und funktioniert ohne zusätzliche GPU-Konfiguration.

Für NVIDIA-GPUs werden ein kompatibler NVIDIA-Treiber und das NVIDIA Container Toolkit benötigt.

LingoVeil anschließend mit der GPU-Konfiguration starten:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

Wenn CUDA nicht zur Verfügung steht, kann weiterhin die CPU verwendet werden.

---

# Bedienung

## Einen Manga oder ein Bild übersetzen

Nach der Anmeldung kannst du eine unterstützte URL öffnen.

Je nach URL lädt LingoVeil entweder:

- ein einzelnes Bild
- eine PDF-Datei
- eine Webseite mit Bildern
- direkt ein Manga-Chapter
- oder die Chapter-Auswahl eines unterstützten Mangas

Anschließend übernimmt LingoVeil OCR und Übersetzung.

Bereits vorhandene Übersetzungen derselben Engine und Zielsprache können aus der History wiederverwendet werden, wodurch ein erneutes Öffnen deutlich schneller sein kann.

Mit **Erneut übersetzen** lässt sich jederzeit eine neue Übersetzung für die aktuell gewählte Engine und Sprache erzwingen.

---

## Oberfläche und Übersetzungssprache

Unter:

**Optionen → Allgemein**

gibt es zwei voneinander unabhängige Spracheinstellungen.

### Oberflächensprache

Bestimmt die Sprache der LingoVeil-Oberfläche.

Aktuell:

- Deutsch
- Englisch

### Zielsprache der Übersetzung

Bestimmt, in welche Sprache Manga-, Comic- und Bildtexte übersetzt werden.

Welche Zielsprachen verfügbar sind, hängt von der ausgewählten Übersetzungsengine ab.

---

## Prefetch

LingoVeil kann nachfolgende Bilder bereits im Hintergrund übersetzen.

Dadurch muss beim Weiterblättern seltener auf die nächste Übersetzung gewartet werden.

Der Standardwert ist:

```text
10 Bilder
```

Ein höherer Wert kann das Lesen flüssiger machen, benötigt aber mehr:

- CPU-Leistung
- GPU-Leistung
- Arbeitsspeicher
- Zeit in der Übersetzungswarteschlange

Auf schwächerer Hardware ist ein kleiner Wert sinnvoll.

---

# Backup und Wiederherstellung

## Persönliches Backup

Unter:

**Optionen → Backup / Restore**

kann jeder Benutzer seine persönlichen LingoVeil-Daten exportieren.

Enthalten sind:

- persönliche Einstellungen
- History
- Bookmarks
- Lesefortschritt

Nicht enthalten sind unter anderem:

- Passwort
- Sessions
- Benutzerrolle
- SMTP-Zugangsdaten
- Serverkonfiguration
- installierte Modelle

Das Backup kann später wieder in LingoVeil importiert werden.

---

<details>
<summary><strong>Server-Backup für Administratoren</strong></summary>

Für ein vollständiges Server-Backup sollten PostgreSQL sowie die Docker Volumes gesichert werden.

Ein PostgreSQL-Dump kann beispielsweise so erstellt werden:

```bash
docker compose exec -T postgres pg_dump -U lingoveil -d lingoveil -Fc > lingoveil-postgres.dump
```

Die wichtigsten Volumes sind:

| Volume | Inhalt |
|---|---|
| `lingoveil-postgres` | Benutzer, History, Bookmarks, Jobs und Einstellungen |
| `lingoveil-models` | installierte Modelle |
| `lingoveil-data` | LingoVeil-Konfiguration |
| `lingoveil-cache` | Bilder, Renderings und Cache-Daten |

</details>

---

# Optionale E-Mail-Einrichtung

E-Mail wird für folgende Funktionen verwendet:

- Benachrichtigungen über neue Manga-Chapter
- Passwort-Wiederherstellung

Ohne SMTP-Konfiguration funktioniert LingoVeil weiterhin normal. Die entsprechenden E-Mail-Funktionen werden dann nicht angeboten.

<details>
<summary><strong>SMTP konfigurieren</strong></summary>

Beispiel für `.env`:

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

Für Port `587` wird normalerweise STARTTLS verwendet:

```dotenv
LINGOVEIL_SMTP_USE_TLS=true
```

Für implizites SSL auf Port `465`:

```dotenv
LINGOVEIL_SMTP_USE_TLS=false
```

`LINGOVEIL_PUBLIC_URL` ist optional.

</details>

---

# Öffentlicher Betrieb

Wenn LingoVeil nicht nur im eigenen Netzwerk, sondern öffentlich über das Internet erreichbar sein soll, sollten mindestens folgende Punkte umgesetzt werden:

- HTTPS verwenden
- ein starkes PostgreSQL-Passwort setzen
- Secure Session Cookies aktivieren
- einen Reverse Proxy verwenden
- Rate-Limits beziehungsweise vergleichbaren Schutz konfigurieren

Bei HTTPS:

```dotenv
LINGOVEIL_SESSION_COOKIE_SECURE=true
```

PostgreSQL ist in der Standardkonfiguration nur über `127.0.0.1` vom Host erreichbar.

---

# Updates

LingoVeil prüft standardmäßig beim Start und anschließend ungefähr alle 6 Stunden auf eine neue Version.

Vergleiche bei einem Update einer bestehenden Installation deine `.env` mit `.env.example` und ergänze neu eingeführte Variablen manuell. Ersetze nicht die vollständige `.env`, da sie installationsspezifische Passwörter und Secrets enthält. Version 3.1.5 ergänzt diese Ollama-Einstellungen:

```dotenv
LINGOVEIL_OLLAMA_BASE_URL=http://host.docker.internal:11435
LINGOVEIL_OLLAMA_BRIDGE_TOKEN=
LINGOVEIL_OLLAMA_MODEL=translategemma:4b
LINGOVEIL_OLLAMA_TIMEOUT_SEC=120
LINGOVEIL_OLLAMA_KEEP_ALIVE=2m
```

Der Bridge-Installer trägt `LINGOVEIL_OLLAMA_BRIDGE_TOKEN` automatisch ein. Wenn `LINGOVEIL_OLLAMA_KEEP_ALIVE` und `LINGOVEIL_ENGINE_IDLE_MINUTES` übereinstimmen, gibt Ollama sein Modell im gleichen Zeitfenster wie die lokalen LingoVeil-Worker frei.

Die automatische Prüfung kann in `.env` deaktiviert werden:

```dotenv
update=false
```

Eine manuelle Prüfung über:

**Info & Support → Check-Update**

bleibt weiterhin möglich.

Mit:

```dotenv
update=true
```

wird die automatische Prüfung wieder aktiviert.

---

# Erweiterte Konfiguration

Für die meisten Installationen reichen die Standardwerte aus.

<details>
<summary><strong>Wichtige Umgebungsvariablen anzeigen</strong></summary>

| Variable | Standard | Bedeutung |
|---|---:|---|
| `LINGOVEIL_LIVE_PORT` | `8765` | Web-Port von LingoVeil |
| `LINGOVEIL_POSTGRES_PORT` | `5434` | optionaler PostgreSQL-Port auf dem Host |
| `LINGOVEIL_SESSION_HOURS` | `72` | Lebensdauer einer Anmeldung |
| `LINGOVEIL_SESSION_COOKIE_SECURE` | `false` | bei HTTPS auf `true` setzen |
| `LINGOVEIL_SMTP_*` | leer | optionale E-Mail-Konfiguration |
| `LINGOVEIL_PUBLIC_URL` | leer | öffentliche URL für Links in E-Mails |
| `LINGOVEIL_BERGAMOT_LANGUAGETOOL_ENABLED` | `false` | lokale LanguageTool-Korrektur für Bergamot |
| `LINGOVEIL_ENGINE_IDLE_MINUTES` | `2` | EasyOCR, Bergamot und Seamless nach dieser Leerlaufzeit entladen; `0` deaktiviert den Timer |
| `LINGOVEIL_OLLAMA_BASE_URL` | `http://host.docker.internal:11435` | URL der Bridge oder nativen Ollama-API |
| `LINGOVEIL_OLLAMA_BRIDGE_TOKEN` | leer | Secret des empfohlenen Bridge-Installers |
| `LINGOVEIL_OLLAMA_MODEL` | `translategemma:4b` | exakter Ollama-Modellname |
| `LINGOVEIL_OLLAMA_TIMEOUT_SEC` | `120` | Timeout für Ollama-Anfragen in Sekunden |
| `LINGOVEIL_OLLAMA_KEEP_ALIVE` | `2m` | Keep-alive-Wert für das Ollama-Modell |
| `update` | `true` | automatische Update-Prüfung |

</details>

<details>
<summary><strong>LanguageTool für Bergamot aktivieren</strong></summary>

Nach der Installation über:

**Optionen → Modelle → LanguageTool (local)**

in `.env`:

```dotenv
LINGOVEIL_BERGAMOT_LANGUAGETOOL_ENABLED=true
LINGOVEIL_BERGAMOT_LANGUAGETOOL_TIMEOUT_SEC=5
```

Anschließend:

```bash
docker compose up -d --force-recreate lingoveil-live
```

</details>

---

# Grenzen

LingoVeil nimmt dir viel Arbeit ab, aber OCR und automatische Übersetzung sind nicht in jeder Situation fehlerfrei.

Besonders schwierig können beispielsweise sein:

- sehr kleine Schrift
- stark stilisierte Schriftarten
- handschriftlicher Text
- schlechte oder stark komprimierte Bilder
- ungewöhnliche Sprechblasen oder überlagerte Texte

Außerdem gilt:

- Webseitenanalyse führt kein JavaScript aus
- Logins und Paywalls werden nicht umgangen
- große Modelle benötigen entsprechend viel RAM und Speicherplatz
- CPU-Übersetzung kann je nach Modell und Hardware langsam sein
- die GPU-Konfiguration wurde nicht auf jeder NVIDIA-Hardware getestet

---

# Fehlerbehebung

Containerstatus:

```bash
docker compose ps
```

Logs anzeigen:

```bash
docker compose logs -f
```

Healthcheck:

```bash
curl http://localhost:8765/api/health
```

Bei Problemen sollten zuerst geprüft werden:

- läuft der Container?
- ist genügend Speicherplatz vorhanden?
- konnte das gewünschte Modell vollständig geladen werden?
- ist PostgreSQL erreichbar?
- stehen genügend RAM beziehungsweise GPU-Speicher zur Verfügung?

---
