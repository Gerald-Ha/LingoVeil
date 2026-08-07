# LingoVeil Bergamot Sidecar

Lokaler Node.js-Sidecar für `@browsermt/bergamot-translator` (WebAssembly).

## Installation

```bash
cd sidecar/bergamot
npm install
```

`postinstall` patcht `translator-worker.js` für Node.js ESM (22+).

## Start

```bash
node bergamot_sidecar.mjs
```

Kommunikation: JSONL auf stdin/stdout, Logs auf stderr.

## Protokoll

- `ping` → `pong`
- `translate` mit `blocks: [{id, text}, ...]` → `translation_result`
- `shutdown` → `shutdown_complete`

## Test

```bash
./scripts/run_bergamot_sidecar_test.sh
```

## Lizenz

- npm-Paket: **MPL-2.0** (`@browsermt/bergamot-translator` 0.4.9)
- EN→DE-Modelle: Mozilla Bergamot-Modelle (Registry `https://bergamot.s3.amazonaws.com/models/index.json`)

Modelle werden beim ersten Übersetzen per HTTPS geladen und im Sidecar-Prozess im RAM gehalten (kein separater Projekt-Cache).
