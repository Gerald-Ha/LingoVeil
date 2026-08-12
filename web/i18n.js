(() => {
  "use strict";
  const STORAGE_KEY = "lingoveil-interface-language";
  const EN = {
    "Menü öffnen": "Open menu", "Engine": "Engine", "Übersetzungsengine": "Translation engine",
    "Auswahl: Bergamot lokal": "Selected: Bergamot local", "Eingabequelle": "Input source",
    "Eingabequelle aufklappen": "Expand input source", "URL-Eingabe": "URL input",
    "Webseite, Bild- oder PDF-URL": "Website, image or PDF URL", "Laden": "Load",
    "Bibliothek": "Library", "History": "History", "Bookmarks": "Bookmarks",
    "Bookmarks auf neue Chapter prüfen": "Check bookmarks for new chapters",
    "Jetzt auf neue Chapter prüfen": "Check for new chapters now",
    "Bookmarks bearbeiten": "Edit bookmarks", "Bearbeiten beenden": "Finish editing",
    "Bookmark entfernen": "Remove bookmark",
    "History und Bookmarks aufklappen": "Expand history and bookmarks",
    "Bookmarks durchsuchen": "Search bookmarks", "Bookmarks durchsuchen …": "Search bookmarks…",
    "Noch keine URL gespeichert.": "No URL saved yet.",
    "Noch keine Manga-Bookmarks gespeichert.": "No manga bookmarks saved yet.",
    "Keine passenden Bookmarks gefunden.": "No matching bookmarks found.",
    "Bilder übersetzt": "images translated", "Zuletzt gelesen:": "Last read:",
    "Noch kein Chapter gelesen": "No chapter read yet",
    "Für Download – gesamtes Chapter übersetzen": "Download – translate entire chapter",
    "Chapter ist für Offline-Lesen gespeichert": "Chapter is saved for offline reading",
    "Reihenfolge: invertiert": "Order: reversed", "Reihenfolge: aktuell": "Order: current",
    "Vorschau": "Preview", "Übersetzung aus": "Translation off",
    "Übersetzung an": "Translation on",
    "An Fenster anpassen": "Fit to window", "Vorheriges Chapter": "Previous chapter",
    "Nächstes Chapter": "Next chapter", "Vorherige Page": "Previous page", "Nächste Page": "Next page",
    "Noch keine Vorschau.": "No preview yet.", "Wird geladen …": "Loading…",
    "Gefiltert": "Filtered", "Wird übersetzt …": "Translating…",
    "Warteschlange": "Queued", "Übersetzt": "Translated", "Offen": "Open",
    "Wird gerade übersetzt …": "Translating…", "Gefundene Bilder": "Found images",
    "Gefundene Bilder aufklappen": "Expand found images", "0 Bilder": "0 images",
    "Kein Bild ausgewählt": "No image selected", "Erneut übersetzen": "Translate again",
    "Lade eine Webseite, um Bilder hier anzuzeigen.": "Load a website to display images here.",
    "Engine nicht verfügbar": "Engine unavailable", "Schließen": "Close",
    "Als sichere Alternative wurde Bergamot lokal ausgewählt.": "Bergamot local was selected as a safe fallback.",
    "Inhalt konnte nicht geladen werden": "Content could not be loaded",
    "Die ausgewählte Übersetzungsengine wurde nicht verändert.": "The selected translation engine was not changed.",
    "Chapter auswählen": "Select chapter", "Chapter-Auswahl schließen": "Close chapter selection",
    "Bookmark entfernen?": "Remove bookmark?", "Abbrechen": "Cancel",
    "Entfernen, Lesedaten behalten": "Remove and keep reading data",
    "Entfernen und Lesedaten löschen": "Remove and delete reading data",
    "Du kannst die gespeicherten Lesedaten und Chapter-Datumsangaben behalten oder ebenfalls löschen.":
      "You can keep the saved reading data and chapter dates or delete them as well.",
    "Optionen": "Options", "Allgemein": "General", "Konto": "Account", "Manga": "Manga",
    "Backup / Restore": "Backup / Restore", "Modelle": "Models", "Filter": "Filter", "Admin": "Admin",
    "OCR- und Übersetzungsfilter": "OCR and translation filter",
    "Bilder bis einschließlich einer der beiden Grenzgrößen werden weder vom OCR gescannt noch übersetzt. Mit 0 wird die jeweilige Grenze deaktiviert.":
      "Images at or below either limit are not scanned by OCR or translated. Set a limit to 0 to disable it.",
    "Bis Breite überspringen (Pixel)": "Skip up to width (pixels)",
    "Bis Höhe überspringen (Pixel)": "Skip up to height (pixels)",
    "Registrierung": "Registration", "Neue Registrierungen": "New registrations",
    "Aktiviert": "Enabled", "Deaktiviert": "Disabled",
    "Registrierung speichern": "Save registration setting",
    "Lege fest, ob neue Benutzerkonten registriert werden dürfen.":
      "Choose whether new user accounts may be registered.",
    "Benutzerkonten": "User accounts", "Geschütztes Administratorkonto": "Protected administrator account",
    "Konto löschen": "Delete account", "Benutzerkonto löschen?": "Delete user account?",
    "Das Benutzerkonto": "The user account",
    "und alle zugehörigen Daten werden endgültig gelöscht.": "and all associated data will be permanently deleted.",
    "Konto endgültig löschen": "Delete account permanently",
    "Theme": "Theme", "Oberflächensprache": "Interface language",
    "Zielsprache der Übersetzung": "Translation target language", "Browser": "Browser",
    "E-Mail bei neuen Bookmark-Chaptern": "Email me about new bookmark chapters",
    "SMTP wurde vom Administrator noch nicht konfiguriert.":
      "SMTP has not yet been configured by the administrator.",
    "Nicht verfügbar: SMTP wurde vom Administrator noch nicht konfiguriert.":
      "Unavailable: SMTP has not yet been configured by the administrator.",
    "Browser": "Browser", "Speichern": "Save", "Gespeichert": "Saved",
    "History löschen": "Delete history",
    "History & Übersetzungen": "History & translations",
    "Entfernt deine URL-History und alle darin gespeicherten Übersetzungen.":
      "Removes your URL history and all translations stored in it.",
    "History wirklich löschen?": "Delete history?",
    "Die gesamte URL-History und alle gespeicherten Übersetzungen werden endgültig gelöscht.":
      "Your entire URL history and all saved translations will be permanently deleted.",
    "Endgültig löschen": "Delete permanently",
    "Kontodaten ändern": "Change account details", "Benutzername": "Username",
    "E-Mail-Adresse": "Email address", "Aktuelles Passwort": "Current password",
    "Neues Passwort (optional)": "New password (optional)",
    "Neues Passwort wiederholen": "Repeat new password", "Kontodaten speichern": "Save account details",
    "Bookmark-Cache": "Bookmark cache", "Fortschritt sichern": "Back up progress",
    "Backup herunterladen": "Download backup", "Backup wiederherstellen": "Restore backup",
    "Backup wiederherstellen?": "Restore backup?", "Wiederherstellen": "Restore",
    "Die aktuelle History und deine Bookmarks werden durch den Inhalt dieses Backups ersetzt.":
      "Your current history and bookmarks will be replaced with the contents of this backup.",
    "Ja": "Yes", "Nein": "No", "Gespeicherte Chapter je Bookmark (0 = unbegrenzt)":
      "Saved chapters per bookmark (0 = unlimited)",
    "Prefetch-Bilder (0–100)": "Prefetch images (0–100)",
    "History-Einträge (1–100)": "History entries (1–100)",
    "Browser-Cache (Sekunden)": "Browser cache (seconds)",
    "LM Studio Basis-URL": "LM Studio base URL", "LM Studio Modell": "LM Studio model",
    "LM Studio Timeout (s)": "LM Studio timeout (s)", "LM Studio speichern": "Save LM Studio",
    "Lokale LLM": "Local LLM", "Ollama Basis-URL": "Ollama base URL",
    "Ollama Modell": "Ollama model", "Ollama Timeout (s)": "Ollama timeout (s)",
    "Ollama Keep-Alive": "Ollama keep-alive", "Verbindung testen": "Test connection",
    "Modelle aktualisieren": "Refresh models", "Status:": "Status:",
    "Nicht konfiguriert": "Not configured", "Nicht geprüft": "Not tested",
    "Verbunden": "Connected", "Nicht verfügbar": "Unavailable",
    "Unterstützt": "Supported", "Nicht offiziell unterstützt": "Not officially supported",
    "Ollama nicht verfügbar": "Ollama unavailable", "Verstanden": "Understood",
    "Die Verbindung zu Ollama ist fehlgeschlagen.": "The connection to Ollama failed.",
    "Ollama ist derzeit nicht erreichbar. Bitte wähle eine andere Übersetzungs-Engine.":
      "Ollama is currently unavailable. Please select another translation engine.",
    "Wenn du das Verbindungsproblem behoben hast, öffne Optionen → Modelle → Ollama und führe den Verbindungstest erneut aus.":
      "After resolving the connection issue, open Options → Models → Ollama and run the connection test again.",
    "Nach einem erfolgreichen Verbindungstest steht Ollama wieder als Übersetzungs-Engine zur Verfügung.":
      "Ollama will become available as a translation engine again after a successful connection test.",
    "Verbinden": "Connect"
    ,"Bestätige jede Änderung mit deinem aktuellen Passwort. Lass das neue Passwort leer, wenn es unverändert bleiben soll.":
      "Confirm every change with your current password. Leave the new password blank to keep it unchanged."
    ,"Das Limit entfernt nur ältere Bilder und Übersetzungsergebnisse. Bookmark, Lesestatus und Datum bleiben im persönlichen Benutzerkonto erhalten.":
      "The limit only removes older images and translation results. The bookmark, reading status and date remain in your personal account."
    ,"Sichert ausschließlich deine History, Bookmarks, Lesefortschritte, Einstellungen und Chapter-Datumsangaben in einer portablen JSON-Datei. Bilder, Modelle und Übersetzungscache werden nicht in das Fortschrittsbackup aufgenommen.":
      "Backs up only your history, bookmarks, reading progress, settings and chapter dates in a portable JSON file. Images, models and the translation cache are not included."
    ,"Einstellungen atomisch gespeichert.": "Settings saved."
    ,"Kontodaten wurden gespeichert.": "Account details saved."
    ,"History und gespeicherte Übersetzungen wurden gelöscht.": "History and saved translations were deleted."
    ,"Backup wird erstellt …": "Creating backup…", "Backup wurde heruntergeladen.": "Backup downloaded."
    ,"Bitte zuerst eine LingoVeil-JSON-Datei auswählen.": "Please select a LingoVeil JSON file first."
    ,"Backup wird geprüft und wiederhergestellt …": "Validating and restoring backup…"
    ,"Modellstatus wird geladen …": "Loading model status…"
    ,"Downloads und Modelle bleiben im persistenten Modell-Volume erhalten.":
      "Downloads and models remain in the persistent model volume."
    ,"Info & Support": "Info & Support", "Version Status": "Version status",
    "Abmelden": "Log out", "Abmelden?": "Log out?",
    "Möchtest du dich wirklich von LingoVeil abmelden?": "Do you really want to log out of LingoVeil?",
    "Projekt unterstützen": "Support the project",
    "LingoVeil Live wird kostenlos entwickelt und bereitgestellt. Mit einer Spende kannst du die Weiterentwicklung und die laufenden Kosten unterstützen.":
      "LingoVeil Live is developed and provided free of charge. Your donation supports continued development and ongoing costs.",
    "Unterstützung ist mit USDT oder USDC über Ethereum und BNB Smart Chain möglich.":
      "You can support the project with USDT or USDC on Ethereum or BNB Smart Chain.",
    "Wallet-Adresse wird geladen …": "Loading wallet address…",
    "Wallet-Adresse derzeit nicht verfügbar.": "Wallet address is currently unavailable.",
    "Adresse kopieren": "Copy address", "Kopiert!": "Copied!",
    "Kopieren fehlgeschlagen": "Copy failed",
    "Neues Update verfügbar": "New update available",
    "Installed Version:": "Installed version:", "Latest Version:": "Latest version:",
    "Noch nicht geprüft": "Not checked yet", "Update öffnen": "Open update",
    "Release Notes": "Release notes",
    "Unbekannt": "Unknown", "Prüfung läuft …": "Checking…",
    "Falls du einen Fehler gefunden hast oder einen Verbesserungsvorschlag einreichen möchtest, sende bitte eine E-Mail an den Entwickler.":
      "If you found a bug or would like to suggest an improvement, please email the developer."
    ,"optional": "optional", "erforderlich": "required", "installiert": "installed",
    "beschädigt": "damaged", "nicht installiert": "not installed",
    "LanguageTool (lokal)": "LanguageTool (local)",
    "Persistenter Ordner:": "Persistent directory:", "Modell ist installiert": "Model is installed",
    "Download läuft …": "Download in progress…", "Download wird gestartet …": "Starting download…",
    "Download läuft im Hintergrund …": "Download running in the background…",
    "Herunterladen": "Download",
    "Bereits im Docker-Image enthalten": "Already included in the Docker image",
    "Bereits installiert": "Already installed",
    "Kein separater Download erforderlich": "No separate download required",
    "Bitte zuerst die nichtkommerzielle CC-BY-NC-4.0-Lizenz akzeptieren.":
      "Please accept the non-commercial CC BY-NC 4.0 license first."
    ,"Sidecar-Verzeichnis vorhanden, aber node_modules fehlen.":
      "The sidecar directory exists, but node_modules is missing."
    ,"Ordner vorhanden, aber kein LanguageTool-Server-JAR gefunden.":
      "The directory exists, but no LanguageTool server JAR was found."
    ,"LanguageTool 6.6 (LGPL-2.1-or-later), lokal und optional.":
      "LanguageTool 6.6 (LGPL-2.1-or-later), local and optional."
    ,"Im Dev-Modus liegt der Sidecar bereits im Repository. Fuer spaetere AppImage-Releases muss entschieden werden, ob die Sidecar-Runtime eingebettet oder ueber ein separates Bundle ausgeliefert wird.":
      "In development mode, the sidecar is already included in the repository. A later AppImage release must decide whether to embed its runtime or ship it as a separate bundle."
    ,"Optionales lokales Offline-Modell fuer spaetere Sprach- und Audiofunktionen.":
      "Optional local offline model for language and audio features."
  };

  let language = localStorage.getItem(STORAGE_KEY) === "en" ? "en" : "de";
  const translateValue = (value) => {
    if (EN[value]) return EN[value];

    return value
      .replaceAll("Bilder übersetzt", EN["Bilder übersetzt"])
      .replaceAll("Zuletzt gelesen:", EN["Zuletzt gelesen:"]);
  };
  const t = (value) => language === "en" ? translateValue(value) : value;
  const translateNode = (root) => {
    if (language !== "en") return;
    if (root.nodeType === Node.TEXT_NODE) {
      const raw = root.nodeValue || "";
      const trimmed = raw.trim();

      const translated = trimmed ? translateValue(trimmed) : trimmed;

      if (translated !== trimmed) root.nodeValue = raw.replace(trimmed, translated);

      return;
    }

    if (!(root instanceof Element)) return;
    const translateAttributes = (element) => {
      ["aria-label", "title", "placeholder"].forEach((name) => {
        const value = element.getAttribute(name);

        if (value && EN[value]) element.setAttribute(name, EN[value]);
      });
    };

    translateAttributes(root);
    const elementWalker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);

    while (elementWalker.nextNode()) translateAttributes(elementWalker.currentNode);

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);

    while (walker.nextNode()) translateNode(walker.currentNode);
  };

  const apply = () => {
    document.documentElement.lang = language;
    translateNode(document.body);
  };

  const setLanguage = (next) => {
    const normalized = next === "en" ? "en" : "de";
    localStorage.setItem(STORAGE_KEY, normalized);

    if (language !== normalized && normalized === "de") {
      window.location.reload();

      return;
    }

    language = normalized;
    apply();
  };

  window.LingoVeilI18n = {t, apply, setLanguage, get language() { return language; }};

  document.addEventListener("DOMContentLoaded", apply);

  new MutationObserver((records) => {
    if (language !== "en") return;
    records.forEach((record) => record.addedNodes.forEach(translateNode));
  }).observe(document.documentElement, {childList: true, subtree: true});
})();
