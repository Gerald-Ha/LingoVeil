from __future__ import annotations
import json
import sys
import time

from pathlib import Path
from typing import Any
def send(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)

def main() -> int:
    if len(sys.argv) != 5:
        print("Ungültige Worker-Argumente", file=sys.stderr, flush=True)

        return 2
    from lingoveil_seamless_m4t import SeamlessM4TTextTranslator
    translator = SeamlessM4TTextTranslator(
        Path(sys.argv[1]),
        device_preference=sys.argv[2],
        source_lang=sys.argv[3],
        target_lang=sys.argv[4],
        log_fn=lambda msg: print(f"[SeamlessM4T] {msg}", file=sys.stderr, flush=True),
    )

    for raw_line in sys.stdin:
        try:
            request = json.loads(raw_line)

            request_id = request.get("request_id", "")

            message_type = request.get("type")

            if message_type == "start":
                translator.start()

                send(
                    {
                        "type": "ready",
                        "request_id": request_id,
                        "device_mode": translator.device_mode,
                        "torch_dtype": translator.torch_dtype,
                        "load_duration_sec": translator.load_duration_sec,
                    }

                )

            elif message_type == "translate":
                started = time.monotonic()

                translations = translator.translate_blocks(
                    list(request.get("blocks", [])),
                    source_lang=str(request.get("source_lang", "eng")),
                    target_lang=str(request.get("target_lang", "deu")),
                )

                send(
                    {
                        "type": "translation_result",
                        "request_id": request_id,
                        "translations": translations,
                        "duration_sec": time.monotonic() - started,
                    }

                )

            elif message_type == "shutdown":
                translator.close()

                send({"type": "shutdown_complete", "request_id": request_id})

                return 0
            else:
                send(
                    {
                        "type": "error",
                        "request_id": request_id,
                        "message": f"Unbekannter Nachrichtentyp: {message_type}",
                    }

                )

        except Exception as exc:
            send(
                {
                    "type": "error",
                    "request_id": locals().get("request_id", ""),
                    "message": str(exc),
                }

            )

    translator.close()

    return 0
if __name__ == "__main__":
    raise SystemExit(main())
