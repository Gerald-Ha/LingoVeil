#!/usr/bin/env node
/**
 * LingoVeil Bergamot Sidecar – JSONL über stdin/stdout, Logs auf stderr.
 */
import readline from "node:readline";
import { BatchTranslator } from "@browsermt/bergamot-translator/translator.js";

const LOG_PREFIX = "[Bergamot-Sidecar]";

function log(...args) {
  console.error(LOG_PREFIX, ...args);
}

function send(obj) {
  process.stdout.write(`${JSON.stringify(obj)}\n`);
}

let translator = null;
let shuttingDown = false;
const requestQueue = [];
let processing = false;

async function ensureTranslator() {
  if (translator) {
    return translator;
  }
  log("Initialisiere BatchTranslator (workers=1, batchSize=8, cacheSize=1000) …");
  const t0 = Date.now();
  translator = new BatchTranslator({
    workers: 1,
    batchSize: 8,
    cacheSize: 1000,
  });
  log(`BatchTranslator bereit (${Date.now() - t0} ms)`);
  return translator;
}

async function handlePing(msg) {
  await ensureTranslator();
  send({
    type: "pong",
    request_id: msg.request_id,
    engine: "bergamot",
    ready: true,
  });
}

async function handleTranslate(msg) {
  const requestId = msg.request_id;
  const sourceLang = msg.source_lang || "en";
  const targetLang = msg.target_lang || "de";
  const blocks = Array.isArray(msg.blocks) ? msg.blocks : [];

  if (!blocks.length) {
    send({
      type: "error",
      request_id: requestId,
      error_code: "empty_blocks",
      message: "Keine Blöcke zum Übersetzen",
    });
    return;
  }

  const tr = await ensureTranslator();
  const t0 = Date.now();

  try {
    const tasks = blocks.map(async (block) => {
      const id = String(block.id ?? "");
      const text = String(block.text ?? "");
      if (!id || !text.trim()) {
        return { id, translation: "" };
      }
      const response = await tr.translate({
        from: sourceLang,
        to: targetLang,
        text,
        html: false,
      });
      return {
        id,
        translation: response?.target?.text ?? "",
      };
    });

    const results = await Promise.all(tasks);
    send({
      type: "translation_result",
      request_id: requestId,
      engine: "bergamot",
      translations: results.map((r) => ({
        id: r.id,
        translation: r.translation,
      })),
      duration_ms: Date.now() - t0,
    });
  } catch (err) {
    send({
      type: "error",
      request_id: requestId,
      error_code: "translate_failed",
      message: String(err?.message ?? err),
    });
  }
}

async function handleShutdown(msg) {
  if (shuttingDown) {
    return;
  }
  shuttingDown = true;
  send({
    type: "shutdown_complete",
    request_id: msg.request_id,
  });
  if (translator) {
    try {
      await translator.delete();
    } catch (err) {
      log("Shutdown translator.delete():", err);
    }
    translator = null;
  }
  log("Sidecar beendet.");
  process.exit(0);
}

async function processMessage(msg) {
  const type = msg?.type;
  if (!type || !msg.request_id) {
    return;
  }
  switch (type) {
    case "ping":
      await handlePing(msg);
      break;
    case "translate":
      await handleTranslate(msg);
      break;
    case "shutdown":
      await handleShutdown(msg);
      break;
    default:
      send({
        type: "error",
        request_id: msg.request_id,
        error_code: "unknown_type",
        message: `Unbekannter Typ: ${type}`,
      });
  }
}

function enqueueLine(line) {
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    log("Ungültige JSON-Zeile ignoriert:", line.slice(0, 200));
    return;
  }
  requestQueue.push(msg);
  drainQueue();
}

async function drainQueue() {
  if (processing || shuttingDown) {
    return;
  }
  processing = true;
  while (requestQueue.length > 0 && !shuttingDown) {
    const msg = requestQueue.shift();
    try {
      await processMessage(msg);
    } catch (err) {
      log("Verarbeitungsfehler:", err);
      if (msg?.request_id) {
        send({
          type: "error",
          request_id: msg.request_id,
          error_code: "internal_error",
          message: String(err?.message ?? err),
        });
      }
    }
  }
  processing = false;
}

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });

rl.on("line", (line) => {
  if (!line.trim()) {
    return;
  }
  enqueueLine(line);
});

rl.on("close", async () => {
  if (shuttingDown) {
    return;
  }
  while (requestQueue.length > 0 || processing) {
    await drainQueue();
    if (processing) {
      await new Promise((r) => setTimeout(r, 20));
    }
  }
  log("stdin geschlossen – beende Sidecar");
  if (translator) {
    await translator.delete();
    translator = null;
  }
  process.exit(0);
});

process.on("SIGTERM", () => {
  handleShutdown({ request_id: "sigterm" }).catch(() => process.exit(1));
});

process.on("SIGINT", () => {
  handleShutdown({ request_id: "sigint" }).catch(() => process.exit(1));
});

log("Sidecar gestartet, warte auf JSONL-Anfragen …");
