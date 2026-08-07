(() => {
  "use strict";
  const header = document.querySelector(".header-controls");

  const updateHeader = document.querySelector(".header-updates");

  if (!header) return;
  let inMemoryAccessCode = document.getElementById("session-code-input")?.value || "";
  const uiText = (value) => window.LingoVeilI18n?.t(value) || value;
  window.addEventListener("lingoveil:authenticated", (event) => {
    inMemoryAccessCode = event.detail?.token || event.detail?.code || "";
  });

  const authHeaders = () => ({
    "Content-Type": "application/json",
    "X-Session-Code": inMemoryAccessCode
  });

  const request = async (url, options = {}) => {
    const response = await fetch(url, {...options, headers: {...authHeaders(), ...(options.headers || {})}});

    const data = await response.json();

    if (!response.ok) {
      const detail = data.detail ?? data.error;
      let message = `HTTP ${response.status}`;
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail)) {
        message = detail.map((item) => item?.msg || JSON.stringify(item)).join("; ");
      } else if (detail && typeof detail === "object") {
        message = detail.message || JSON.stringify(detail);
      }

      throw new Error(message);
    }

    return data;
  };

  const dialog = document.createElement("dialog");

  dialog.className = "live-dialog";
  let modelPollTimer = null;
  let seamlessModelReady = false;
  const title = document.createElement("h2");

  const content = document.createElement("div");

  content.className = "live-dialog-content";
  let statusTarget = content;
  const actions = document.createElement("div");

  actions.className = "live-dialog-actions";
  const close = document.createElement("button");

  close.type = "button";
  close.textContent = "Schließen";
  close.className = "secondary";
  close.addEventListener("click", () => dialog.close());

  actions.append(close);

  dialog.append(title, content, actions);

  document.body.append(dialog);

  const show = (name) => {
    if (modelPollTimer) {
      clearTimeout(modelPollTimer);

      modelPollTimer = null;
    }

    title.textContent = name;
    dialog.classList.toggle("settings-dialog", name === "Optionen");

    content.replaceChildren();

    statusTarget = content;
    actions.replaceChildren(close);

    dialog.showModal();
  };

  const field = (label, value, type = "text") => {
    const wrap = document.createElement("label");

    wrap.className = "live-field";
    wrap.append(document.createTextNode(label));

    const input = document.createElement("input");

    input.className = "text-input";
    input.type = type;
    input.value = value;
    wrap.append(input);

    content.append(wrap);

    return input;
  };

  const selectField = (label, value, choices) => {
    const wrap = document.createElement("label");

    wrap.className = "live-field";
    wrap.append(document.createTextNode(label));

    const select = document.createElement("select");

    select.className = "text-input";
    choices.forEach(([choiceValue, choiceLabel]) => {
      const option = document.createElement("option");

      option.value = choiceValue;
      option.textContent = choiceLabel;
      option.selected = choiceValue === value;
      select.append(option);
    });

    wrap.append(select);

    content.append(wrap);

    return select;
  };

  const applyTheme = (theme) => {
    document.documentElement.dataset.theme = theme === "light" ? "light" : "dark";
    document.documentElement.style.colorScheme = theme === "light" ? "light" : "dark";
  };

  const TARGET_LANGUAGES = [
    "afr","amh","arb","ary","arz","asm","azj","bel","ben","bos","bul","cat","ceb","ces","ckb","cmn","cmn_Hant","cym","dan","deu","ell","eng","est","eus","fin","fra","fuv","gaz","gle","glg","guj","heb","hin","hrv","hun","hye","ibo","ind","isl","ita","jav","jpn","kan","kat","kaz","khk","khm","kir","kor","lao","lit","lug","luo","lvs","mai","mal","mar","mkd","mlt","mni","mya","nld","nno","nob","npi","nya","ory","pan","pbt","pes","pol","por","ron","rus","sat","slk","slv","sna","snd","som","spa","srp","swe","swh","tam","tel","tgk","tgl","tha","tur","ukr","urd","uzn","vie","yor","yue","zlm","zul"
  ];
  const BERGAMOT_TARGETS = new Set(["bul","ces","deu","spa","est","fra","ita","por","rus","ukr"]);

  const languageChoices = (locale) => {
    let names;
    try { names = new Intl.DisplayNames([locale], {type: "language"}); } catch (_) { names = null; }

    return TARGET_LANGUAGES.map((code) => {
      const intlCode = code === "cmn_Hant" ? "zh-Hant" : code.replace("_", "-");

      const name = names?.of(intlCode) || code;
      const engines = BERGAMOT_TARGETS.has(code) ? "Bergamot + SeamlessM4T" : "SeamlessM4T";
      return [code, `${name} (${engines})`];
    }).sort((a, b) => a[1].localeCompare(b[1], locale));
  };

  const showSavedPopup = () => {
    const popup = document.createElement("dialog");

    popup.className = "saved-popup";
    popup.setAttribute("aria-live", "polite");

    popup.textContent = window.LingoVeilI18n?.t("Gespeichert") || "Gespeichert";
    document.body.append(popup);

    popup.showModal();

    window.setTimeout(() => { popup.close(); popup.remove(); }, 1000);
  };

  const confirmHistoryDeletion = () => new Promise((resolve) => {
    const popup = document.createElement("dialog");

    popup.className = "live-dialog confirmation-dialog";
    const heading = document.createElement("h2");

    heading.textContent = uiText("History wirklich löschen?");

    const message = document.createElement("p");

    message.className = "hint confirmation-message";
    message.textContent = uiText(
      "Die gesamte URL-History und alle gespeicherten Übersetzungen werden endgültig gelöscht."
    );

    const popupActions = document.createElement("div");

    popupActions.className = "live-dialog-actions";
    const cancel = document.createElement("button");

    cancel.type = "button";
    cancel.className = "secondary";
    cancel.textContent = uiText("Abbrechen");

    const confirm = document.createElement("button");

    confirm.type = "button";
    confirm.className = "danger";
    confirm.textContent = uiText("Endgültig löschen");

    popupActions.append(cancel, confirm);

    popup.append(heading, message, popupActions);

    document.body.append(popup);

    let accepted = false;
    cancel.addEventListener("click", () => popup.close());

    confirm.addEventListener("click", () => {
      accepted = true;
      popup.close();
    });

    popup.addEventListener("close", () => {
      popup.remove();

      resolve(accepted);
    }, {once: true});

    popup.showModal();
  });

  const confirmBackupRestore = () => new Promise((resolve) => {
    const popup = document.createElement("dialog");

    popup.className = "live-dialog confirmation-dialog";
    const heading = document.createElement("h2");

    heading.textContent = uiText("Backup wiederherstellen?");

    const message = document.createElement("p");

    message.className = "hint confirmation-message";
    message.textContent = uiText(
      "Die aktuelle History und deine Bookmarks werden durch den Inhalt dieses Backups ersetzt."
    );

    const popupActions = document.createElement("div");

    popupActions.className = "live-dialog-actions";
    const cancel = document.createElement("button");

    cancel.type = "button";
    cancel.className = "secondary";
    cancel.textContent = uiText("Abbrechen");

    const confirm = document.createElement("button");

    confirm.type = "button";
    confirm.className = "primary";
    confirm.textContent = uiText("Wiederherstellen");

    popupActions.append(cancel, confirm);

    popup.append(heading, message, popupActions);

    document.body.append(popup);

    let accepted = false;
    cancel.addEventListener("click", () => popup.close());

    confirm.addEventListener("click", () => {
      accepted = true;
      popup.close();
    });

    popup.addEventListener("close", () => {
      popup.remove();

      resolve(accepted);
    }, {once: true});

    popup.showModal();
  });

  const status = (message, error = false) => {
    const node = document.createElement("p");

    node.className = error ? "field-error" : "hint";
    node.textContent = message;
    statusTarget.append(node);
  };

  const addButton = (name, handler, target = header) => {
    const button = document.createElement("button");

    button.type = "button";
    button.className = "secondary small";
    button.textContent = name;
    button.addEventListener("click", handler);

    target?.append(button);

    return button;
  };

  addButton("Optionen", async () => {
    show("Optionen");

    try {
      const {settings: s, warning, user, capabilities = {}} = await request("/api/settings");

      const isAdmin = Boolean(user?.is_admin);

      const tabs = document.createElement("div");

      tabs.className = "live-settings-tabs";
      const generalTab = document.createElement("button");

      generalTab.type = "button";
      generalTab.className = "live-settings-tab active";
      generalTab.textContent = "Allgemein";
      const accountTab = document.createElement("button");

      accountTab.type = "button";
      accountTab.className = "live-settings-tab";
      accountTab.textContent = "Konto";
      const mangaTab = document.createElement("button");

      mangaTab.type = "button";
      mangaTab.className = "live-settings-tab";
      mangaTab.textContent = "Manga";
      const backupTab = document.createElement("button");

      backupTab.type = "button";
      backupTab.className = "live-settings-tab";
      backupTab.textContent = "Backup / Restore";
      const modelsTab = document.createElement("button");

      modelsTab.type = "button";
      modelsTab.className = "live-settings-tab";
      modelsTab.textContent = "Modelle";
      const adminTab = document.createElement("button");

      adminTab.type = "button";
      adminTab.className = "live-settings-tab";
      adminTab.textContent = "Admin";
      tabs.append(generalTab, accountTab, mangaTab, backupTab);

      if (isAdmin) tabs.append(modelsTab, adminTab);

      content.append(tabs);

      const generalPanel = document.createElement("div");

      generalPanel.className = "live-settings-panel";
      const accountPanel = document.createElement("div");

      accountPanel.className = "live-settings-panel hidden";
      const mangaPanel = document.createElement("div");

      mangaPanel.className = "live-settings-panel hidden";
      const backupPanel = document.createElement("div");

      backupPanel.className = "live-settings-panel hidden";
      const modelsPanel = document.createElement("div");

      modelsPanel.className = "live-settings-panel hidden";
      const adminPanel = document.createElement("div");

      adminPanel.className = "live-settings-panel hidden";
      const panels = document.createElement("div");

      panels.className = "live-settings-panels";
      panels.append(generalPanel, accountPanel, mangaPanel, backupPanel, modelsPanel, adminPanel);

      content.append(panels);

      statusTarget = panels;
      if (warning) status(warning, true);

      let save = null;
      let clearHistory = null;
      const selectTab = (name) => {
        const showAccount = name === "account";
        const showManga = name === "manga";
        const showBackup = name === "backup";
        const showModels = name === "models";
        const showAdmin = name === "admin";
        if (!showModels && modelPollTimer) {
          clearTimeout(modelPollTimer);

          modelPollTimer = null;
        }

        generalPanel.classList.toggle(
          "hidden", showAccount || showManga || showBackup || showModels || showAdmin
        );

        accountPanel.classList.toggle("hidden", !showAccount);

        mangaPanel.classList.toggle("hidden", !showManga);

        backupPanel.classList.toggle("hidden", !showBackup);

        modelsPanel.classList.toggle("hidden", !showModels);

        adminPanel.classList.toggle("hidden", !showAdmin);

        generalTab.classList.toggle(
          "active", !showAccount && !showManga && !showBackup && !showModels && !showAdmin
        );

        accountTab.classList.toggle("active", showAccount);

        mangaTab.classList.toggle("active", showManga);

        backupTab.classList.toggle("active", showBackup);

        modelsTab.classList.toggle("active", showModels);

        adminTab.classList.toggle("active", showAdmin);

        const hideGeneralActions = showAccount || showBackup || showModels || showAdmin;
        if (save) save.classList.toggle("hidden", hideGeneralActions);

        panels.scrollTop = 0;
      };

      generalTab.addEventListener("click", () => selectTab("general"));

      accountTab.addEventListener("click", () => selectTab("account"));

      mangaTab.addEventListener("click", () => selectTab("manga"));

      backupTab.addEventListener("click", () => selectTab("backup"));

      if (isAdmin) {
        modelsTab.addEventListener("click", () => {
          selectTab("models");

          if (!modelsPanel.childElementCount) {
            const loading = document.createElement("p");

            loading.className = "hint";
            loading.textContent = "Modellstatus wird geladen …";
            modelsPanel.append(loading);
          }

          void refreshModels();
        });

        adminTab.addEventListener("click", () => {
          selectTab("admin");

          void refreshAdmin();
        });
      }

      const accountSettings = document.createElement("fieldset");

      accountSettings.className = "live-settings-group";
      const accountLegend = document.createElement("legend");

      accountLegend.textContent = "Kontodaten ändern";
      const accountHint = document.createElement("p");

      accountHint.className = "hint";
      accountHint.textContent =
        "Bestätige jede Änderung mit deinem aktuellen Passwort. " +
        "Lass das neue Passwort leer, wenn es unverändert bleiben soll.";
      accountSettings.append(accountLegend, accountHint);

      accountPanel.append(accountSettings);

      const accountUsername = field("Benutzername", user?.username || "");

      accountUsername.autocomplete = "username";
      accountUsername.minLength = 3;
      accountUsername.maxLength = 64;
      const accountEmail = field("E-Mail-Adresse", user?.email || "", "email");

      accountEmail.autocomplete = "email";
      accountEmail.maxLength = 320;
      const currentPassword = field("Aktuelles Passwort", "", "password");

      currentPassword.autocomplete = "current-password";
      currentPassword.maxLength = 1024;
      const newPassword = field("Neues Passwort (optional)", "", "password");

      newPassword.autocomplete = "new-password";
      newPassword.minLength = 8;
      newPassword.maxLength = 1024;
      const confirmPassword = field("Neues Passwort wiederholen", "", "password");

      confirmPassword.autocomplete = "new-password";
      confirmPassword.minLength = 8;
      confirmPassword.maxLength = 1024;
      accountSettings.append(
        accountUsername.closest(".live-field"),
        accountEmail.closest(".live-field"),
        currentPassword.closest(".live-field"),
        newPassword.closest(".live-field"),
        confirmPassword.closest(".live-field")

      );

      const saveAccount = document.createElement("button");

      saveAccount.type = "button";
      saveAccount.className = "primary";
      saveAccount.textContent = "Kontodaten speichern";
      const accountMessage = document.createElement("p");

      accountMessage.className = "hint";
      saveAccount.addEventListener("click", async () => {
        accountMessage.textContent = "";
        if (newPassword.value !== confirmPassword.value) {
          accountMessage.className = "field-error";
          accountMessage.textContent = "Die neuen Passwörter stimmen nicht überein.";
          return;
        }

        saveAccount.disabled = true;
        try {
          const result = await request("/api/account", {
            method: "PUT",
            body: JSON.stringify({
              username: accountUsername.value.trim(),
              email: accountEmail.value.trim(),
              current_password: currentPassword.value,
              new_password: newPassword.value
            })
          });

          accountUsername.value = result.user.username;
          accountEmail.value = result.user.email;
          currentPassword.value = "";
          newPassword.value = "";
          confirmPassword.value = "";
          accountMessage.className = "hint";
          accountMessage.textContent = "Kontodaten wurden gespeichert.";
          showSavedPopup();
        } catch (e) {
          accountMessage.className = "field-error";
          accountMessage.textContent = e.message;
        } finally {
          saveAccount.disabled = false;
        }
      });

      accountSettings.append(saveAccount, accountMessage);

      const general = document.createElement("fieldset");

      general.className = "live-settings-group";
      const legend = document.createElement("legend");

      legend.textContent = "Allgemein";
      general.append(legend);

      generalPanel.append(general);

      const theme = selectField("Theme", s.theme || "dark", [
        ["dark", "Dark"], ["light", "Light"]
      ]);

      const interfaceLanguage = selectField("Oberflächensprache", s.interface_language || "de", [
        ["de", "Deutsch"], ["en", "English"]
      ]);

      const language = selectField(
        "Zielsprache der Übersetzung", s.target_language || "deu",
        languageChoices(s.interface_language || "de")

      );

      const chapterEmailNotifications = selectField(
        "E-Mail bei neuen Bookmark-Chaptern",
        String(Boolean(s.chapter_email_notifications)),
        [["false", "Nein"], ["true", "Ja"]]
      );

      const smtpConfigured = Boolean(capabilities.smtp_configured);

      chapterEmailNotifications.disabled = !smtpConfigured;
      if (!smtpConfigured) {
        chapterEmailNotifications.value = "false";
        chapterEmailNotifications.title =
          "SMTP wurde vom Administrator noch nicht konfiguriert.";
        const smtpHint = document.createElement("span");

        smtpHint.className = "hint";
        smtpHint.textContent =
          "Nicht verfügbar: SMTP wurde vom Administrator noch nicht konfiguriert.";
        chapterEmailNotifications.closest(".live-field").append(smtpHint);
      }

      general.append(
        theme.closest(".live-field"), interfaceLanguage.closest(".live-field"),
        language.closest(".live-field"),
        chapterEmailNotifications.closest(".live-field")

      );

      clearHistory = document.createElement("button");

      clearHistory.type = "button";
      clearHistory.className = "secondary history-clear-inline";
      clearHistory.textContent = "History löschen";
      clearHistory.addEventListener("click", async () => {
        if (!await confirmHistoryDeletion()) return;
        try {
          await request("/api/history", {method: "DELETE"});

          window.dispatchEvent(new CustomEvent("lingoveil:history-cleared"));

          status("History und gespeicherte Übersetzungen wurden gelöscht.");
        } catch (e) {
          status(e.message, true);
        }
      });

      const clearHistorySetting = document.createElement("div");

      clearHistorySetting.className = "history-clear-setting";
      const clearHistoryTitle = document.createElement("strong");

      clearHistoryTitle.textContent = uiText("History & Übersetzungen");

      const clearHistoryHint = document.createElement("span");

      clearHistoryHint.className = "hint";
      clearHistoryHint.textContent = uiText(
        "Entfernt deine URL-History und alle darin gespeicherten Übersetzungen."
      );

      clearHistorySetting.append(clearHistoryTitle, clearHistoryHint, clearHistory);

      general.append(clearHistorySetting);

      const advanced = document.createElement("fieldset");

      advanced.className = "live-settings-group";
      const advancedLegend = document.createElement("legend");

      advancedLegend.textContent = "Browser";
      advanced.append(advancedLegend);

      generalPanel.append(advanced);

      const prefetch = field("Prefetch-Bilder (0–100)", s.prefetch_count, "number");

      prefetch.min = "0";
      prefetch.max = "100";
      const historyLimit = field("History-Einträge (1–100)", s.history_limit || 10, "number");

      historyLimit.min = "1";
      historyLimit.max = "100";
      const ttl = field("Browser-Cache (Sekunden)", s.browser_cache_ttl_sec, "number");

      const base = field("LM Studio Basis-URL", s.lm_studio_base_url);

      const model = field("LM Studio Modell", s.lm_studio_model);

      const timeout = field("LM Studio Timeout (s)", s.lm_studio_timeout_sec, "number");

      advanced.append(
        prefetch.closest(".live-field"), historyLimit.closest(".live-field"),
        ttl.closest(".live-field")

      );

      base.closest(".live-field").remove();

      model.closest(".live-field").remove();

      timeout.closest(".live-field").remove();

      const mangaSettings = document.createElement("fieldset");

      mangaSettings.className = "live-settings-group";
      const mangaLegend = document.createElement("legend");

      mangaLegend.textContent = "Bookmark-Cache";
      mangaSettings.append(mangaLegend);

      mangaPanel.append(mangaSettings);

      const bookmarkCacheLimit = field(
        "Gespeicherte Chapter je Bookmark (0 = unbegrenzt)",
        s.bookmark_chapter_cache_limit ?? 10,
        "number"
      );

      bookmarkCacheLimit.min = "0";
      bookmarkCacheLimit.step = "1";
      mangaSettings.append(bookmarkCacheLimit.closest(".live-field"));

      const mangaHint = document.createElement("p");

      mangaHint.className = "hint";
      mangaHint.textContent =
        "Das Limit entfernt nur ältere Bilder und Übersetzungsergebnisse. " +
        "Bookmark, Lesestatus und Datum bleiben im persönlichen Benutzerkonto erhalten.";
      mangaSettings.append(mangaHint);

      const backupSettings = document.createElement("fieldset");

      backupSettings.className = "live-settings-group";
      const backupLegend = document.createElement("legend");

      backupLegend.textContent = "Fortschritt sichern";
      const backupHint = document.createElement("p");

      backupHint.className = "hint";
      backupHint.textContent =
        "Sichert ausschließlich deine History, Bookmarks, Lesefortschritte, Einstellungen und Chapter-Datumsangaben " +
        "in einer portablen JSON-Datei. Bilder, Modelle und Übersetzungscache " +
        "werden nicht in das Fortschrittsbackup aufgenommen.";
      const backupActions = document.createElement("div");

      backupActions.className = "backup-restore-actions";
      const downloadBackup = document.createElement("button");

      downloadBackup.type = "button";
      downloadBackup.className = "primary";
      downloadBackup.textContent = "Backup herunterladen";
      const restoreInput = document.createElement("input");

      restoreInput.type = "file";
      restoreInput.accept = "application/json,.json";
      restoreInput.className = "text-input";
      const restoreBackup = document.createElement("button");

      restoreBackup.type = "button";
      restoreBackup.className = "secondary";
      restoreBackup.textContent = "Backup wiederherstellen";
      const backupMessage = document.createElement("p");

      backupMessage.className = "hint";
      const setBackupMessage = (message, error = false) => {
        backupMessage.textContent = message;
        backupMessage.className = error ? "field-error" : "hint";
      };

      downloadBackup.addEventListener("click", async () => {
        downloadBackup.disabled = true;
        setBackupMessage("Backup wird erstellt …");

        try {
          const response = await fetch("/api/progress/backup", {
            headers: {"X-Session-Code": inMemoryAccessCode}
          });

          if (!response.ok) {
            const data = await response.json().catch(() => ({}));

            throw new Error(data.detail || data.error || `HTTP ${response.status}`);
          }

          const blob = await response.blob();

          const disposition = response.headers.get("Content-Disposition") || "";
          const match = disposition.match(/filename="([^"]+)"/);

          const filename = match?.[1] || "lingoveil-progress.json";
          const url = URL.createObjectURL(blob);

          const link = document.createElement("a");

          link.href = url;
          link.download = filename;
          document.body.append(link);

          link.click();

          link.remove();

          URL.revokeObjectURL(url);

          setBackupMessage("Backup wurde heruntergeladen.");
        } catch (e) {
          setBackupMessage(e.message, true);
        } finally {
          downloadBackup.disabled = false;
        }
      });

      restoreBackup.addEventListener("click", async () => {
        const selected = restoreInput.files?.[0];
        if (!selected) {
          setBackupMessage("Bitte zuerst eine LingoVeil-JSON-Datei auswählen.", true);

          return;
        }

        if (!await confirmBackupRestore()) return;
        restoreBackup.disabled = true;
        setBackupMessage("Backup wird geprüft und wiederhergestellt …");

        try {
          const body = new FormData();

          body.append("file", selected);

          const response = await fetch("/api/progress/restore", {
            method: "POST",
            headers: {"X-Session-Code": inMemoryAccessCode},
            body
          });

          const data = await response.json().catch(() => ({}));

          if (!response.ok) {
            throw new Error(data.detail || data.error || `HTTP ${response.status}`);
          }

          setBackupMessage(
            `${data.history_entries} History-Einträge und ` +
            `${data.bookmarks} Bookmarks wiederhergestellt. Oberfläche wird neu geladen …`
          );

          window.setTimeout(() => window.location.reload(), 900);
        } catch (e) {
          setBackupMessage(e.message, true);

          restoreBackup.disabled = false;
        }
      });

      backupActions.append(downloadBackup, restoreBackup);

      backupSettings.append(
        backupLegend, backupHint, restoreInput, backupActions, backupMessage
      );

      backupPanel.append(backupSettings);

      const modelStatus = (message, error = false) => {
        const node = document.createElement("p");

        node.className = error ? "field-error" : "hint";
        node.textContent = message;
        modelsPanel.append(node);
      };

      const refreshModels = async () => {
        if (!dialog.open || modelsPanel.classList.contains("hidden")) return;
        modelsPanel.setAttribute("aria-busy", "true");

        try {
          const {models} = await request("/api/models");

          modelsPanel.replaceChildren();

          const lmStudioSettings = document.createElement("fieldset");

          lmStudioSettings.className = "live-settings-group";
          const lmStudioLegend = document.createElement("legend");

          lmStudioLegend.textContent = "LM Studio";
          const saveLmStudio = document.createElement("button");

          saveLmStudio.type = "button";
          saveLmStudio.className = "primary";
          saveLmStudio.textContent = uiText("LM Studio speichern");

          saveLmStudio.addEventListener("click", async () => {
            saveLmStudio.disabled = true;
            try {
              await request("/api/settings", {
                method: "PUT",
                body: JSON.stringify({
                  ...s,
                  lm_studio_base_url: base.value,
                  lm_studio_model: model.value,
                  lm_studio_timeout_sec: Number(timeout.value)
                })
              });

              showSavedPopup();
            } catch (e) {
              modelStatus(e.message, true);
            } finally {
              saveLmStudio.disabled = false;
            }
          });

          lmStudioSettings.append(
            lmStudioLegend,
            base.closest(".live-field"),
            model.closest(".live-field"),
            timeout.closest(".live-field"),
            saveLmStudio
          );

          modelsPanel.append(lmStudioSettings);

          let downloadRunning = false;
          models.forEach((model) => {
            const card = document.createElement("section");

            card.className = "live-model";
            const heading = document.createElement("h3");

            heading.textContent = model.name;
            const meta = document.createElement("p");

            meta.textContent =
              `${uiText(model.status)} · ${uiText(model.optional ? "optional" : "erforderlich")} · ${model.size}`;
            const note = document.createElement("p");

            note.textContent = model.error || model.notes || "";
            card.append(heading, meta, note);

            if (model.component === "seamless_m4t") {
              const installed = model.status === "installiert";
              if (installed && !seamlessModelReady) {
                window.dispatchEvent(new CustomEvent("lingoveil:models-updated", {
                  detail: {component: "seamless_m4t", status: "installed"}
                }));
              }

              seamlessModelReady = installed;
              const location = document.createElement("p");

              location.className = "hint";
              location.textContent = `${uiText("Persistenter Ordner:")} ${model.install_path}`;
              const license = document.createElement("label");

              license.className = "live-license";
              const accepted = document.createElement("input");

              accepted.type = "checkbox";
              accepted.checked = Boolean(model.license_accepted);

              license.append(
                accepted,
                document.createTextNode(
                  window.LingoVeilI18n?.language === "en"
                    ? ` I accept ${model.license}. The model may only be used in accordance with this license.`
                    : ` Ich akzeptiere ${model.license}. Das Modell darf nur entsprechend dieser Lizenz verwendet werden.`
                )

              );

              const download = document.createElement("button");

              download.type = "button";
              download.className = "primary";
              download.textContent = model.status === "installiert"
                ? uiText("Modell ist installiert")

                : model.download_status.startsWith("downloading")

                  ? uiText("Download läuft …")

                  : `${uiText("Herunterladen")} (${model.size})`;
              download.disabled = model.status === "installiert"
                || model.download_status.startsWith("downloading");

              downloadRunning ||= model.download_status.startsWith("downloading");

              download.addEventListener("click", async () => {
                if (!accepted.checked) {
                  modelStatus(
                    "Bitte zuerst die nichtkommerzielle CC-BY-NC-4.0-Lizenz akzeptieren.",
                    true
                  );

                  return;
                }

                download.disabled = true;
                download.textContent = uiText("Download wird gestartet …");

                try {
                  const result = await request(
                    "/api/models/seamless-m4t-v2-large/download",
                    {
                      method: "POST",
                      body: JSON.stringify({accept_license: true})
                    }

                  );

                  download.textContent = uiText("Download läuft im Hintergrund …");

                  modelStatus(
                    window.LingoVeilI18n?.language === "en"
                      ? `${result.message} You may close this window.`
                      : `${result.message} Das Fenster kann geschlossen werden.`
                  );

                  modelPollTimer = setTimeout(refreshModels, 1200);
                } catch (e) {
                  download.disabled = false;
                  download.textContent = `${uiText("Herunterladen")} (${model.size})`;
                  modelStatus(e.message, true);
                }
              });

              card.append(location, license, download);
            } else {
              const action = document.createElement("button");

              action.type = "button";
              action.className =
                model.status === "installiert" ? "secondary" : "primary";
              if (model.status === "installiert") {
                action.textContent = model.component === "bergamot"
                  ? uiText("Bereits im Docker-Image enthalten")

                  : uiText("Bereits installiert");

                action.disabled = true;
              } else if (model.download_available) {
                action.textContent = model.download_status === "downloading"
                  ? uiText("Download läuft …")

                  : `${uiText("Herunterladen")} (${model.size})`;
                action.disabled = model.download_status === "downloading";
                downloadRunning ||= model.download_status === "downloading";
                action.addEventListener("click", async () => {
                  action.disabled = true;
                  action.textContent = uiText("Download wird gestartet …");

                  try {
                    const result = await request(`/api/models/${model.id}/download`, {
                      method: "POST",
                      body: JSON.stringify({})
                    });

                    action.textContent = uiText("Download läuft …");

                    modelStatus(result.message);

                    modelPollTimer = setTimeout(refreshModels, 1200);
                  } catch (e) {
                    action.disabled = false;
                    action.textContent = `${uiText("Herunterladen")} (${model.size})`;
                    modelStatus(e.message, true);
                  }
                });
              } else {
                action.textContent = uiText("Kein separater Download erforderlich");

                action.disabled = true;
              }

              card.append(action);
            }

            modelsPanel.append(card);
          });

          modelStatus(
            "Downloads und Modelle bleiben im persistenten Modell-Volume erhalten."
          );

          if (downloadRunning) {
            modelPollTimer = setTimeout(refreshModels, 1500);
          }
        } catch (e) {
          modelsPanel.replaceChildren();

          modelStatus(e.message, true);
        } finally {
          modelsPanel.removeAttribute("aria-busy");
        }
      };

      const confirmAccountDeletion = (username) => new Promise((resolve) => {
        const popup = document.createElement("dialog");

        popup.className = "live-dialog confirmation-dialog";
        const heading = document.createElement("h2");

        heading.textContent = uiText("Benutzerkonto löschen?");

        const message = document.createElement("p");

        message.className = "hint confirmation-message";
        message.textContent = `${uiText("Das Benutzerkonto")} „${username}“ ${uiText("und alle zugehörigen Daten werden endgültig gelöscht.")}`;
        const popupActions = document.createElement("div");

        popupActions.className = "live-dialog-actions";
        const cancel = document.createElement("button");

        cancel.type = "button";
        cancel.className = "secondary";
        cancel.textContent = uiText("Abbrechen");

        const confirm = document.createElement("button");

        confirm.type = "button";
        confirm.className = "danger";
        confirm.textContent = uiText("Konto endgültig löschen");

        popupActions.append(cancel, confirm);

        popup.append(heading, message, popupActions);

        document.body.append(popup);

        let accepted = false;
        cancel.addEventListener("click", () => popup.close());

        confirm.addEventListener("click", () => { accepted = true; popup.close(); });

        popup.addEventListener("close", () => { popup.remove(); resolve(accepted); }, {once: true});

        popup.showModal();
      });

      const refreshAdmin = async () => {
        adminPanel.setAttribute("aria-busy", "true");

        try {
          const data = await request("/api/admin/users");

          adminPanel.replaceChildren();

          const registrationGroup = document.createElement("fieldset");

          registrationGroup.className = "live-settings-group";
          const registrationLegend = document.createElement("legend");

          registrationLegend.textContent = uiText("Registrierung");

          const registrationHint = document.createElement("p");

          registrationHint.className = "hint";
          registrationHint.textContent = uiText("Lege fest, ob neue Benutzerkonten registriert werden dürfen.");

          const registrationSelect = selectField("Neue Registrierungen", String(data.registration_enabled), [
            ["false", uiText("Deaktiviert")], ["true", uiText("Aktiviert")]
          ]);

          const registrationWrapper = registrationSelect.closest(".live-field");

          registrationWrapper.remove();

          const registrationSave = document.createElement("button");

          registrationSave.type = "button";
          registrationSave.className = "primary";
          registrationSave.textContent = uiText("Registrierung speichern");

          registrationSave.addEventListener("click", async () => {
            registrationSave.disabled = true;
            try {
              await request("/api/admin/registration", {
                method: "PUT",
                body: JSON.stringify({enabled: registrationSelect.value === "true"})
              });

              showSavedPopup();
            } catch (e) { status(e.message, true); }

            finally { registrationSave.disabled = false; }
          });

          registrationGroup.append(
            registrationLegend, registrationHint, registrationWrapper, registrationSave
          );

          adminPanel.append(registrationGroup);

          const accountsGroup = document.createElement("fieldset");

          accountsGroup.className = "live-settings-group";
          const accountsLegend = document.createElement("legend");

          accountsLegend.textContent = uiText("Benutzerkonten");

          accountsGroup.append(accountsLegend);

          data.users.forEach((account) => {
            const card = document.createElement("div");

            card.className = "live-admin-user";
            const identity = document.createElement("div");

            const name = document.createElement("strong");

            name.textContent = account.username;
            const email = document.createElement("span");

            email.className = "hint";
            email.textContent = account.email;
            identity.append(name, email);

            card.append(identity);

            if (account.role === "admin") {
              const badge = document.createElement("span");

              badge.className = "live-admin-badge";
              badge.textContent = uiText("Geschütztes Administratorkonto");

              card.append(badge);
            } else {
              const remove = document.createElement("button");

              remove.type = "button";
              remove.className = "danger small";
              remove.textContent = uiText("Konto löschen");

              remove.addEventListener("click", async () => {
                if (!await confirmAccountDeletion(account.username)) return;
                remove.disabled = true;
                try {
                  await request(`/api/admin/users/${encodeURIComponent(account.id)}`, {method: "DELETE"});

                  await refreshAdmin();
                } catch (e) { remove.disabled = false; status(e.message, true); }
              });

              card.append(remove);
            }

            accountsGroup.append(card);
          });

          adminPanel.append(accountsGroup);
        } catch (e) {
          adminPanel.replaceChildren();

          statusTarget = adminPanel;
          status(e.message, true);

          statusTarget = panels;
        } finally {
          adminPanel.removeAttribute("aria-busy");
        }
      };

      save = document.createElement("button");

      save.textContent = "Speichern";
      save.type = "button";
      save.className = "primary";
      save.addEventListener("click", async () => {
        try {
          const saved = await request("/api/settings", {method: "PUT", body: JSON.stringify({
            ...s, theme: theme.value, interface_language: interfaceLanguage.value,
            target_language: language.value,
            chapter_email_notifications: chapterEmailNotifications.value === "true",
            prefetch_count: Number(prefetch.value),
            history_limit: Number(historyLimit.value),
            bookmark_chapter_cache_limit: Number(bookmarkCacheLimit.value),
            browser_cache_ttl_sec: Number(ttl.value),
            lm_studio_base_url: base.value, lm_studio_model: model.value,
            lm_studio_timeout_sec: Number(timeout.value)
          })});

          applyTheme(theme.value);

          window.LingoVeilI18n?.setLanguage(interfaceLanguage.value);

          window.dispatchEvent(new CustomEvent("lingoveil:settings-updated", {
            detail: saved.settings
          }));

          status("Einstellungen atomisch gespeichert.");

          showSavedPopup();
        } catch (e) { status(e.message, true); }
      });

      actions.prepend(save);
    } catch (e) { status(e.message, true); }
  });

  request("/api/settings")

    .then(({settings}) => applyTheme(settings.theme))

    .catch(() => applyTheme("dark"));

  let appInfoButton = null;
  const updateAppInfoButton = (result) => {
    if (!appInfoButton) return;
    const hasUpdate = ["update_available", "blocked"].includes(result?.status);

    appInfoButton.textContent = hasUpdate ? "New Update" : uiText("Info & Support");

    appInfoButton.classList.toggle("new-update", hasUpdate);

    appInfoButton.setAttribute(
      "aria-label",
      hasUpdate ? uiText("Neues Update verfügbar") : uiText("Info & Support")

    );
  };

  appInfoButton = addButton("Info & Support", () => {
    const tr = (value) => window.LingoVeilI18n?.t(value) || value;
    show(tr("Info & Support"));

    const versionGroup = document.createElement("fieldset");

    versionGroup.className = "live-settings-group app-info-version";
    const versionLegend = document.createElement("legend");

    versionLegend.textContent = tr("Version Status");

    const statusGrid = document.createElement("dl");

    statusGrid.className = "app-info-status";
    const installedLabel = document.createElement("dt");

    installedLabel.textContent = tr("Installed Version:");

    const installedValue = document.createElement("dd");

    installedValue.textContent = "3.0.0";
    const latestLabel = document.createElement("dt");

    latestLabel.textContent = tr("Latest Version:");

    const latestValue = document.createElement("dd");

    latestValue.textContent = "–";
    const statusLabel = document.createElement("dt");

    statusLabel.textContent = "Status:";
    const statusValue = document.createElement("dd");

    statusValue.textContent = tr("Noch nicht geprüft");

    statusGrid.append(
      installedLabel, installedValue,
      latestLabel, latestValue,
      statusLabel, statusValue
    );

    const updateLink = document.createElement("a");

    updateLink.className = "secondary app-info-update-link hidden";
    updateLink.target = "_blank";
    updateLink.rel = "noopener noreferrer";
    updateLink.textContent = tr("Update öffnen");

    const checkUpdate = document.createElement("button");

    checkUpdate.type = "button";
    checkUpdate.className = "primary";
    checkUpdate.textContent = "Check-Update";
    const renderUpdate = (result) => {
      updateAppInfoButton(result);

      installedValue.textContent = result.installed_version || "3.0.0";
      latestValue.textContent =
        result.latest_version || result.installed_version || "–";
      const labels = {
        up_to_date: "✅ Up to date",
        update_available: "⬆️ Update available",
        blocked: "⚠️ Update required",
        error: "⚠️ Check unavailable"
      };

      statusValue.textContent = labels[result.status] || result.status || tr("Unbekannt");

      statusValue.dataset.status = result.status || "unknown";
      if (result.message) statusValue.title = result.message;
      else statusValue.removeAttribute("title");

      if (result.update_link) {
        updateLink.href = result.update_link;
        updateLink.classList.remove("hidden");
      } else {
        updateLink.removeAttribute("href");

        updateLink.classList.add("hidden");
      }
    };

    const runUpdateCheck = async (force) => {
      checkUpdate.disabled = true;
      checkUpdate.textContent = tr("Prüfung läuft …");

      try {
        const result = await request(`/api/app-update?force=${force ? "true" : "false"}`);

        renderUpdate(result);

        const address = result.donation_wallet?.address || "";
        walletAddress.textContent = address
          || tr("Wallet-Adresse derzeit nicht verfügbar.");

        walletAddress.dataset.address = address;
        copyWallet.disabled = !address;
      } catch (error) {
        renderUpdate({
          status: "error",
          installed_version: installedValue.textContent,
          message: error.message
        });
      } finally {
        checkUpdate.disabled = false;
        checkUpdate.textContent = "Check-Update";
      }
    };

    checkUpdate.addEventListener("click", () => void runUpdateCheck(true));

    versionGroup.append(
      versionLegend, statusGrid, checkUpdate, updateLink
    );

    const supportGroup = document.createElement("fieldset");

    supportGroup.className = "live-settings-group app-info-support";
    const supportLegend = document.createElement("legend");

    supportLegend.className = "app-info-support-title";
    const supportLegendText = document.createElement("span");

    supportLegendText.textContent = tr("Projekt unterstützen");

    const supportHeart = document.createElement("img");

    supportHeart.className = "app-info-support-heart";
    supportHeart.src = "/static/img/pixel-heart-logo.svg";
    supportHeart.alt = "";
    supportHeart.setAttribute("aria-hidden", "true");

    supportLegend.append(supportLegendText, supportHeart);

    const supportHint = document.createElement("p");

    supportHint.className = "hint app-info-support-copy";
    supportHint.textContent = tr(
      "LingoVeil Live wird kostenlos entwickelt und bereitgestellt. " +
      "Mit einer Spende kannst du die Weiterentwicklung und die laufenden Kosten unterstützen."
    );

    const supportNetworks = document.createElement("p");

    supportNetworks.className = "hint";
    supportNetworks.textContent = tr(
      "Unterstützung ist mit USDT oder USDC über Ethereum und BNB Smart Chain möglich."
    );

    const walletAddress = document.createElement("code");

    walletAddress.className = "app-info-wallet";
    walletAddress.textContent = tr("Wallet-Adresse wird geladen …");

    const copyWallet = document.createElement("button");

    copyWallet.type = "button";
    copyWallet.className = "secondary app-info-copy-wallet";
    copyWallet.textContent = tr("Adresse kopieren");

    copyWallet.disabled = true;
    copyWallet.addEventListener("click", async () => {
      const address = walletAddress.dataset.address || "";
      if (!address) return;
      const originalLabel = tr("Adresse kopieren");

      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(address);
        } else {
          const fallback = document.createElement("textarea");

          fallback.value = address;
          fallback.readOnly = true;
          fallback.className = "clipboard-fallback";
          document.body.append(fallback);

          fallback.focus();

          fallback.select();

          const copied = document.execCommand("copy");

          fallback.remove();

          if (!copied) throw new Error("copy_failed");
        }

        copyWallet.textContent = tr("Kopiert!");
      } catch (_) {
        copyWallet.textContent = tr("Kopieren fehlgeschlagen");
      }

      window.setTimeout(() => {
        copyWallet.textContent = originalLabel;
      }, 1500);
    });

    const walletRow = document.createElement("div");

    walletRow.className = "app-info-wallet-row";
    walletRow.append(walletAddress, copyWallet);

    supportGroup.append(
      supportLegend, supportHint, supportNetworks, walletRow
    );

    const feedbackGroup = document.createElement("fieldset");

    feedbackGroup.className = "live-settings-group";
    const feedbackLegend = document.createElement("legend");

    feedbackLegend.textContent = tr("Feedback");

    const feedbackHint = document.createElement("p");

    feedbackHint.className = "hint";
    feedbackHint.textContent = tr(
      "Falls du einen Fehler gefunden hast oder einen Verbesserungsvorschlag " +
      "einreichen möchtest, sende bitte eine E-Mail an den Entwickler."
    );

    const feedback = document.createElement("a");

    feedback.className = "secondary app-info-feedback";
    feedback.href =
      "mailto:contact@gerald-hasani.com?subject=" +
      encodeURIComponent("LingoVeil Feedback");

    feedback.textContent = "Send Feedback";
    feedbackGroup.append(feedbackLegend, feedbackHint, feedback);

    content.append(versionGroup, supportGroup, feedbackGroup);

    void runUpdateCheck(false);
  }, updateHeader);

  const logoutButton = addButton("Logout", async () => {
    const popup = document.createElement("dialog");

    popup.className = "live-dialog confirmation-dialog";
    const heading = document.createElement("h2");

    heading.textContent = uiText("Abmelden?");

    const message = document.createElement("p");

    message.className = "hint confirmation-message";
    message.textContent = uiText("Möchtest du dich wirklich von LingoVeil abmelden?");

    const popupActions = document.createElement("div");

    popupActions.className = "live-dialog-actions";
    const cancel = document.createElement("button");

    cancel.type = "button";
    cancel.className = "secondary";
    cancel.textContent = uiText("Abbrechen");

    const confirm = document.createElement("button");

    confirm.type = "button";
    confirm.className = "danger";
    confirm.textContent = uiText("Abmelden");

    popupActions.append(cancel, confirm);

    popup.append(heading, message, popupActions);

    document.body.append(popup);

    cancel.addEventListener("click", () => popup.close());

    confirm.addEventListener("click", async () => {
      confirm.disabled = true;
      try {
        await request("/api/logout", {method: "POST", body: JSON.stringify({})});

        window.location.replace("/login.html");
      } catch (error) {
        confirm.disabled = false;
        message.className = "field-error confirmation-message";
        message.textContent = error.message;
      }
    });

    popup.addEventListener("close", () => popup.remove(), {once: true});

    popup.showModal();
  }, updateHeader);

  logoutButton.classList.add("logout-button");

  logoutButton.title = uiText("Abmelden");

  logoutButton.setAttribute("aria-label", uiText("Abmelden"));

  request("/api/app-update?force=false")

    .then(updateAppInfoButton)

    .catch(() => updateAppInfoButton({status: "error"}));
})();
