from __future__ import annotations
import base64
import json
import sys

from io import BytesIO
from typing import Any
def send(payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            default=lambda value: value.item() if hasattr(value, "item") else list(value),
        ),
        flush=True,
    )

def main() -> int:
    import easyocr
    import numpy as np

    from PIL import Image
    reader: Any = None
    for raw_line in sys.stdin:
        request_id = ""
        try:
            request = json.loads(raw_line)

            request_id = str(request.get("request_id", ""))

            message_type = request.get("type")

            if message_type == "start":
                if reader is None:
                    print("[EasyOCR] Initialisiere Reader …", file=sys.stderr, flush=True)

                    reader = easyocr.Reader(["en"], gpu=False, verbose=False)

                send({"type": "ready", "request_id": request_id})

            elif message_type == "ocr":
                if reader is None:
                    raise RuntimeError("EasyOCR-Reader ist nicht initialisiert")

                image_bytes = base64.b64decode(str(request.get("image", "")), validate=True)

                with Image.open(BytesIO(image_bytes)) as image:
                    rgb = np.array(image.convert("RGB"))

                results = reader.readtext(rgb, detail=1, paragraph=False)

                send({"type": "ocr_result", "request_id": request_id, "results": results})

            elif message_type == "shutdown":
                send({"type": "shutdown_complete", "request_id": request_id})

                return 0
            else:
                raise RuntimeError(f"Unbekannter Nachrichtentyp: {message_type}")

        except Exception as exc:
            send({"type": "error", "request_id": request_id, "message": str(exc)})

    return 0
if __name__ == "__main__":
    raise SystemExit(main())
