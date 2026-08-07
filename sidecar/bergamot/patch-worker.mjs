#!/usr/bin/env node
/**
 * Patches @browsermt/bergamot-translator worker for Node.js ESM (require/__dirname).
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const workerPath = join(
  __dirname,
  "node_modules",
  "@browsermt",
  "bergamot-translator",
  "worker",
  "translator-worker.js",
);

if (!existsSync(workerPath)) {
  console.error(`[patch-worker] Worker nicht gefunden: ${workerPath}`);
  process.exit(1);
}

const marker = "/* lingoveil-esm-patch */";
let source = readFileSync(workerPath, "utf-8");

if (source.includes(marker)) {
  console.log("[patch-worker] Bereits gepatcht.");
  process.exit(0);
}

const patch = `${marker}
import { createRequire } from "node:module";
import { fileURLToPath as _fileURLToPath } from "node:url";
import { dirname as _dirname } from "node:path";
const require = createRequire(import.meta.url);
const __filename = _fileURLToPath(import.meta.url);
const __dirname = _dirname(__filename);

`;

source = patch + source;
writeFileSync(workerPath, source, "utf-8");
console.log("[patch-worker] translator-worker.js für Node ESM gepatcht.");
