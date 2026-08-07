from __future__ import annotations
import json
import sys

from pathlib import Path
from typing import Any
def serialize_info(info: Any) -> dict[str, Any]:
    return {
        "id": info.group_id,
        "ocr_bbox": list(info.roi_bbox),
        "group_bbox": list(info.group_bbox or info.roi_bbox),
        "render_bbox": list(info.render_bbox),
        "text_bbox": list(info.text_bbox),
        "bbox_unchanged": info.bbox_unchanged,
        "ocr_text": info.ocr_text,
        "translation": info.translated_text,
        "display_text": info.display_text,
        "font_size": info.font_size,
        "line_count": info.line_count,
        "fits": info.fits,
        "occupancy_ratio": info.occupancy_ratio,
        "overflow_reason": info.overflow_reason,
        "render_mode": info.render_mode,
        "cache_source": info.cache_source,
    }

def main() -> int:
    from PIL import Image
    from lingoveil_overlay import (
        OVERLAY_MODE_EXACT_GROUP,
        build_overlay_groups,
        render_overlay_to_pillow,
    )

    for line in sys.stdin:
        request_id = ""
        try:
            request = json.loads(line)

            request_id = str(request.get("request_id", ""))

            kind = request.get("type")

            if kind == "start":
                print(json.dumps({"type": "ready", "request_id": request_id}), flush=True)

            elif kind == "render":
                input_path = Path(str(request["input_path"]))

                output_path = Path(str(request["output_path"]))

                with Image.open(input_path) as source:
                    image = source.convert("RGB")

                grouped = [tuple(item) for item in request.get("grouped", [])]
                infos = build_overlay_groups(
                    grouped=grouped,
                    roi_size=(image.width, image.height),
                    gui_display_mode=OVERLAY_MODE_EXACT_GROUP,
                )

                rendered = render_overlay_to_pillow(
                    image,
                    infos,
                    display_mode=OVERLAY_MODE_EXACT_GROUP,
                )

                output_path.parent.mkdir(parents=True, exist_ok=True)

                rendered.save(output_path, format="PNG")

                print(
                    json.dumps(
                        {
                            "type": "render_result",
                            "request_id": request_id,
                            "groups": [serialize_info(info) for info in infos],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

            elif kind == "shutdown":
                print(json.dumps({"type": "shutdown_complete", "request_id": request_id}), flush=True)

                return 0
            else:
                raise RuntimeError(f"Unbekannter Nachrichtentyp: {kind}")

        except Exception as exc:
            print(
                json.dumps({"type": "error", "request_id": request_id, "message": str(exc)}),
                flush=True,
            )

    return 0
if __name__ == "__main__":
    raise SystemExit(main())
