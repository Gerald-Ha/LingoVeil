from __future__ import annotations
import json
import sys

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import cv2
import numpy as np

from PIL import Image, ImageDraw, ImageFont
OVERLAY_PADDING_X = 12
OVERLAY_PADDING_Y = 8
OVERLAY_MAX_EXPAND_RATIO = 1.35
OVERLAY_MAX_LINES = 12
OVERLAY_INNER_PAD = 6
OVERLAY_MAX_FONT_SIZE = 48
OVERLAY_MAX_FONT_SIZE_CAP = 96
OVERLAY_MIN_FONT_SIZE = 8
OVERLAY_LINE_GAP = 2
RESPONSIVE_LINE_GAP = 2
RESPONSIVE_MAX_LINES = 16
OVERLAY_MODE_TRANSLATION = "translation_in_image"
OVERLAY_MODE_BBOX = "bounding_boxes"
OVERLAY_MODE_ORIGINAL = "original"
OVERLAY_MODE_CONTAINER = "translation_in_container"
OVERLAY_MODE_OCR_BBOX = "translation_in_ocr_bbox"
OVERLAY_MODE_MASKED = "translation_in_masked_bubble"
OVERLAY_MODE_RESPONSIVE = "translation_in_responsive_textbox"
OVERLAY_MODE_EXACT_GROUP = "translation_in_exact_group_bbox"
RENDER_MASKED_BUBBLE = "masked_bubble"
RENDER_RECTANGULAR = "rectangular_text_box"
RENDER_FALLBACK = "fallback_bbox_expand"
RENDER_RESPONSIVE_TEXTBOX = "responsive_textbox"
RENDER_EXACT_GROUP_BBOX = "exact_group_bbox"
EXACT_MIN_FONT_SIZE = 6
EXACT_MAX_FONT_SIZE_CAP = 96
EXACT_LINE_GAP = 2
EXACT_MAX_LINES = 24
EXACT_OVERFLOW_MSG = "Deutscher Text passt nicht vollständig in OCR-Gruppen-Box"
BUBBLE_SEARCH_EXPAND_X = 2.5
BUBBLE_SEARCH_EXPAND_Y = 2.5
BUBBLE_MAX_AREA_RATIO = 0.35
BUBBLE_MIN_AREA_RATIO = 1.20
BUBBLE_LIGHT_THRESHOLD = 220
BUBBLE_MIN_WHITENESS_RATIO = 0.72
BUBBLE_INNER_MARGIN_X = 8
BUBBLE_INNER_MARGIN_Y = 6
FALLBACK_PADDING_X = 16
FALLBACK_PADDING_Y = 12
FALLBACK_MAX_EXPAND_RATIO = 1.60
BUBBLE_MASK_CLOSE_KERNEL = 5
BUBBLE_MASK_ERODE_KERNEL = 5
BUBBLE_MASK_ERODE_ITERATIONS = 1
BUBBLE_KEEP_BORDER_PX = 3
DETECTION_BUBBLE_LIGHT = "bubble_light_region"
DETECTION_FALLBACK = "fallback_bbox_expand"
CONTAINER_SPEECH_BUBBLE = "speech_bubble"
CONTAINER_RECTANGULAR = "rectangular_text_box"
CONTAINER_FALLBACK = "fallback"
OVERLAY_BG_COLOR = (248, 248, 248, 255)

OVERLAY_TEXT_COLOR = (24, 24, 24, 255)

OVERLAY_BBOX_COLOR = (255, 120, 0, 255)

DEBUG_COLOR_OCR = (0, 200, 0, 180)

DEBUG_COLOR_SEARCH = (255, 220, 0, 140)

DEBUG_COLOR_CONTAINER = (60, 120, 255, 160)

DEBUG_COLOR_INNER = (180, 80, 220, 180)

DEBUG_COLOR_FALLBACK = (255, 140, 0, 180)

DEBUG_COLOR_COMPONENT_MASK = (60, 120, 255, 120)

DEBUG_COLOR_INNER_MASK = (180, 80, 220, 120)

FONT_CANDIDATES = (
    "DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf",
    "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/google-droid-sans-fonts/DroidSans.ttf",
)

LOADING_TEXT = "Übersetzung wird geladen …"
ERROR_TEXT = "Übersetzung fehlgeschlagen"
@dataclass
class OverlayFitResult:
    font_size: int
    lines: list[str]
    line_count: int
    text_width: int
    text_height: int
    fits: bool
    truncated: bool = False
@dataclass
class BubbleCandidate:
    source_bbox: tuple[int, int, int, int]
    search_bbox: tuple[int, int, int, int]
    detected_bbox: tuple[int, int, int, int] | None
    inner_text_bbox: tuple[int, int, int, int]
    detection_method: str
    confidence: float
    whiteness_ratio: float
    area_ratio: float
    fallback_used: bool
    warnings: list[str]
    container_type: str = CONTAINER_FALLBACK
    component_mask: np.ndarray | None = None
    inner_fill_mask: np.ndarray | None = None
    mask_bbox: tuple[int, int, int, int] | None = None
    mask_area: int = 0
    inner_mask_area: int = 0
@dataclass
class OverlayGroupInfo:
    group_id: str
    roi_bbox: tuple[int, int, int, int]
    overlay_bbox: tuple[int, int, int, int]
    canvas_bbox: tuple[int, int, int, int] = (0, 0, 0, 0)

    ocr_text: str = ""
    translated_text: str = ""
    display_text: str = ""
    font_size: int = 0
    line_count: int = 0
    fits: bool = True
    truncated: bool = False
    lines: list[str] = field(default_factory=list)

    overlap_warning: bool = False
    cache_source: str = ""
    engine: str = ""
    status: str = ""
@dataclass
class BubbleOverlayGroupInfo(OverlayGroupInfo):
    bubble: BubbleCandidate | None = None
    render_mode: str = RENDER_FALLBACK
    mask_present: bool = False
    border_preserved: bool = False
    render_bbox: tuple[int, int, int, int] = (0, 0, 0, 0)

    text_bbox: tuple[int, int, int, int] = (0, 0, 0, 0)

    padding_x: int = 0
    padding_y: int = 0
    dynamic_max_font_size: int = 0
    used_width: int = 0
    used_height: int = 0
    available_width: int = 0
    available_height: int = 0
    occupancy_ratio: float = 0.0
    bbox_unchanged: bool = False
    overflow_reason: str | None = None
    group_bbox: tuple[int, int, int, int] = (0, 0, 0, 0)

_MEASURE_DRAW: ImageDraw.ImageDraw | None = None
def load_overlay_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)

        except OSError:
            continue
    return ImageFont.load_default()

def _measure_draw() -> ImageDraw.ImageDraw:
    global _MEASURE_DRAW
    if _MEASURE_DRAW is None:
        _MEASURE_DRAW = ImageDraw.Draw(Image.new("RGB", (4, 4)))

    return _MEASURE_DRAW
def _clamp(value: float, minimum: float, maximum: float) -> int:
    return int(max(minimum, min(maximum, round(value))))

def _exact_bbox_padding(box_width: int, box_height: int) -> tuple[int, int]:
    pad_x = _clamp(box_width * 0.025, 1, 4)

    pad_y = _clamp(box_height * 0.025, 1, 4)

    return pad_x, pad_y
def _exact_dynamic_max_font_size(
    box_width: int,
    box_height: int,
    *,
    min_font_size: int = EXACT_MIN_FONT_SIZE,
    max_font_size_cap: int = EXACT_MAX_FONT_SIZE_CAP,
) -> int:
    return min(
        max_font_size_cap,
        max(min_font_size, int(box_height * 0.85)),
        max(min_font_size, int(box_width * 0.55)),
    )

def _exact_line_gap(font_size: int) -> int:
    return max(EXACT_LINE_GAP, int(round(font_size * 0.12)))

def _dynamic_padding(box_width: int, box_height: int) -> tuple[int, int]:
    short_side = min(box_width, box_height)

    if short_side < 40:
        scale = 0.02
    elif short_side < 80:
        scale = 0.03
    else:
        scale = 0.04
    pad_x = _clamp(box_width * scale, 2, 10)

    pad_y = _clamp(box_height * scale, 2, 10)

    return pad_x, pad_y
def _dynamic_max_font_size(
    box_width: int,
    box_height: int,
    *,
    min_font_size: int = OVERLAY_MIN_FONT_SIZE,
    max_font_size_cap: int = OVERLAY_MAX_FONT_SIZE_CAP,
) -> int:
    return min(
        max_font_size_cap,
        max(min_font_size, int(box_height * 0.75)),
        max(min_font_size, int(box_width * 0.45)),
    )

def _text_width_draw(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    text: str,
) -> float:
    if not text:
        return 0.0
    bbox = draw.textbbox((0, 0), text, font=font)

    return float(bbox[2] - bbox[0])

def _line_height_draw(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
) -> int:
    bbox = draw.textbbox((0, 0), "HgAy", font=font)

    return max(1, int(bbox[3] - bbox[1]))

def _measure_text_block(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    lines: list[str],
    *,
    line_gap: int = RESPONSIVE_LINE_GAP,
) -> tuple[int, int]:
    if not lines:
        return 0, 0
    max_w = 0
    total_h = 0
    for idx, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line or " ", font=font)

        line_w = int(bbox[2] - bbox[0])

        line_h = int(bbox[3] - bbox[1])

        max_w = max(max_w, line_w)

        total_h += line_h
        if idx < len(lines) - 1:
            total_h += line_gap
    return max_w, total_h
def _text_width(font: ImageFont.ImageFont, text: str) -> float:
    if hasattr(font, "getlength"):
        return float(font.getlength(text))

    bbox = font.getbbox(text)

    return float(bbox[2] - bbox[0])

def _line_height(font: ImageFont.ImageFont) -> int:
    bbox = font.getbbox("Ay")

    return max(1, int(bbox[3] - bbox[1]))

def _int_bbox(bbox: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    return (
        int(round(min(x1, x2))),
        int(round(min(y1, y2))),
        int(round(max(x1, x2))),
        int(round(max(y1, y2))),
    )

def _bbox_area(bbox: tuple[int, int, int, int]) -> int:
    return max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])

def _intersection_area(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int]
) -> int:
    x1 = max(a[0], b[0])

    y1 = max(a[1], b[1])

    x2 = min(a[2], b[2])

    y2 = min(a[3], b[3])

    return max(0, x2 - x1) * max(0, y2 - y1)

def _clip_bbox_to_roi(
    bbox: tuple[int, int, int, int], roi_size: tuple[int, int]
) -> tuple[int, int, int, int]:
    roi_w, roi_h = roi_size
    x1, y1, x2, y2 = bbox
    x1 = max(0, min(x1, roi_w))

    y1 = max(0, min(y1, roi_h))

    x2 = max(0, min(x2, roi_w))

    y2 = max(0, min(y2, roi_h))

    if x2 <= x1:
        x2 = min(roi_w, x1 + 1)

    if y2 <= y1:
        y2 = min(roi_h, y1 + 1)

    return (int(x1), int(y1), int(x2), int(y2))

def roi_bbox_to_canvas_bbox(
    bbox: tuple[int, int, int, int],
    roi_size: tuple[int, int],
    displayed_image_size: tuple[int, int],
    displayed_image_offset: tuple[int, int],
) -> tuple[int, int, int, int]:
    roi_w, roi_h = roi_size
    disp_w, disp_h = displayed_image_size
    off_x, off_y = displayed_image_offset
    if roi_w <= 0 or roi_h <= 0 or disp_w <= 0 or disp_h <= 0:
        return bbox
    sx = disp_w / roi_w
    sy = disp_h / roi_h
    x1, y1, x2, y2 = bbox
    cx1 = int(round(off_x + x1 * sx))

    cy1 = int(round(off_y + y1 * sy))

    cx2 = int(round(off_x + x2 * sx))

    cy2 = int(round(off_y + y2 * sy))

    img_x1, img_y1 = off_x, off_y
    img_x2, img_y2 = off_x + disp_w, off_y + disp_h
    left = max(img_x1, min(cx1, cx2))

    top = max(img_y1, min(cy1, cy2))

    right = min(img_x2, max(cx1, cx2))

    bottom = min(img_y2, max(cy1, cy2))

    return (left, top, right, bottom)

def expand_overlay_bbox(
    bbox: tuple[float, float, float, float],
    roi_size: tuple[int, int],
    *,
    padding_x: int = OVERLAY_PADDING_X,
    padding_y: int = OVERLAY_PADDING_Y,
    max_expand_ratio: float = OVERLAY_MAX_EXPAND_RATIO,
) -> tuple[int, int, int, int]:
    roi_w, roi_h = roi_size
    x1, y1, x2, y2 = bbox
    w = max(1.0, x2 - x1)

    h = max(1.0, y2 - y1)

    target_w = min(roi_w, w * max_expand_ratio + 2 * padding_x)

    target_h = min(roi_h, h * max_expand_ratio + 2 * padding_y)

    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    nx1 = int(max(0, round(cx - target_w / 2)))

    ny1 = int(max(0, round(cy - target_h / 2)))

    nx2 = int(min(roi_w, round(nx1 + target_w)))

    ny2 = int(min(roi_h, round(ny1 + target_h)))

    if nx2 <= nx1:
        nx2 = min(roi_w, nx1 + 1)

    if ny2 <= ny1:
        ny2 = min(roi_h, ny1 + 1)

    return (nx1, ny1, nx2, ny2)

def expand_search_bbox(
    source_bbox: tuple[int, int, int, int],
    roi_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = source_bbox
    w = max(1, x2 - x1)

    h = max(1, y2 - y1)

    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    sw = min(roi_size[0], w * BUBBLE_SEARCH_EXPAND_X)

    sh = min(roi_size[1], h * BUBBLE_SEARCH_EXPAND_Y)

    nx1 = int(max(0, round(cx - sw / 2)))

    ny1 = int(max(0, round(cy - sh / 2)))

    nx2 = int(min(roi_size[0], round(nx1 + sw)))

    ny2 = int(min(roi_size[1], round(ny1 + sh)))

    return _clip_bbox_to_roi((nx1, ny1, nx2, ny2), roi_size)

def fallback_bbox_expand(
    source_bbox: tuple[int, int, int, int],
    roi_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = source_bbox
    w = max(1, x2 - x1)

    h = max(1, y2 - y1)

    target_w = min(roi_size[0], w * FALLBACK_MAX_EXPAND_RATIO + 2 * FALLBACK_PADDING_X)

    target_h = min(roi_size[1], h * FALLBACK_MAX_EXPAND_RATIO + 2 * FALLBACK_PADDING_Y)

    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    nx1 = int(round(cx - target_w / 2))

    ny1 = int(round(cy - target_h / 2))

    nx2 = int(round(nx1 + target_w))

    ny2 = int(round(ny1 + target_h))

    return _clip_bbox_to_roi((nx1, ny1, nx2, ny2), roi_size)

def compute_inner_text_bbox(
    container_bbox: tuple[int, int, int, int],
    roi_size: tuple[int, int],
    *,
    margin_x: int = BUBBLE_INNER_MARGIN_X,
    margin_y: int = BUBBLE_INNER_MARGIN_Y,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = container_bbox
    inner = (
        x1 + margin_x,
        y1 + margin_y,
        x2 - margin_x,
        y2 - margin_y,
    )

    return _clip_bbox_to_roi(inner, roi_size)

def _build_component_masks(
    labels: np.ndarray,
    label_id: int,
    search_bbox: tuple[int, int, int, int],
    global_bbox: tuple[int, int, int, int],
) -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    sx1, sy1, _, _ = search_bbox
    gx1, gy1, gx2, gy2 = global_bbox
    lx = gx1 - sx1
    ly = gy1 - sy1
    lw = max(1, gx2 - gx1)

    lh = max(1, gy2 - gy1)

    comp_full = (labels == label_id).astype(np.uint8) * 255
    component_mask = comp_full[ly : ly + lh, lx : lx + lw].copy()

    close_k = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (BUBBLE_MASK_CLOSE_KERNEL, BUBBLE_MASK_CLOSE_KERNEL),
    )

    component_mask = cv2.morphologyEx(component_mask, cv2.MORPH_CLOSE, close_k)

    erode_k = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (BUBBLE_MASK_ERODE_KERNEL, BUBBLE_MASK_ERODE_KERNEL),
    )

    inner_fill_mask = cv2.erode(
        component_mask, erode_k, iterations=BUBBLE_MASK_ERODE_ITERATIONS
    )

    if int(np.count_nonzero(inner_fill_mask)) < int(np.count_nonzero(component_mask) * 0.12):
        small_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

        inner_fill_mask = cv2.erode(component_mask, small_k, iterations=1)

    mask_bbox = (gx1, gy1, gx2, gy2)

    return component_mask, inner_fill_mask, mask_bbox
def compute_mask_inner_text_bbox(
    inner_fill_mask: np.ndarray,
    mask_bbox: tuple[int, int, int, int],
    roi_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    if inner_fill_mask.size == 0 or not np.any(inner_fill_mask > 0):
        return compute_inner_text_bbox(mask_bbox, roi_size)

    ys, xs = np.where(inner_fill_mask > 0)

    min_x = int(xs.min()) + BUBBLE_KEEP_BORDER_PX
    min_y = int(ys.min()) + BUBBLE_KEEP_BORDER_PX
    max_x = int(xs.max()) - BUBBLE_KEEP_BORDER_PX
    max_y = int(ys.max()) - BUBBLE_KEEP_BORDER_PX
    if max_x <= min_x or max_y <= min_y:
        min_x = int(xs.min())

        min_y = int(ys.min())

        max_x = int(xs.max())

        max_y = int(ys.max())

    x1, y1, _, _ = mask_bbox
    global_bbox = (
        x1 + min_x,
        y1 + min_y,
        x1 + max_x + 1,
        y1 + max_y + 1,
    )

    return _clip_bbox_to_roi(global_bbox, roi_size)

def compute_mask_responsive_text_bbox(
    inner_fill_mask: np.ndarray,
    mask_bbox: tuple[int, int, int, int],
    roi_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    if inner_fill_mask.size == 0 or not np.any(inner_fill_mask > 0):
        return compute_inner_text_bbox(mask_bbox, roi_size)

    mask_u8 = (inner_fill_mask > 0).astype(np.uint8)

    dist = cv2.distanceTransform(mask_u8, cv2.DIST_L2, 5)

    _, max_val, _, max_loc = cv2.minMaxLoc(dist)

    if max_val < 5:
        return compute_mask_inner_text_bbox(inner_fill_mask, mask_bbox, roi_size)

    cx, cy = max_loc
    ys, xs = np.where(mask_u8 > 0)

    min_x, max_x = int(xs.min()), int(xs.max())

    min_y, max_y = int(ys.min()), int(ys.max())

    half_w = int(max_val * 0.88)

    half_h = int(max_val * 0.82)

    lx1 = max(min_x, cx - half_w)

    ly1 = max(min_y, cy - half_h)

    lx2 = min(max_x, cx + half_w)

    ly2 = min(max_y, cy + half_h)

    mx1, my1, _, _ = mask_bbox
    return _clip_bbox_to_roi(
        (mx1 + lx1, my1 + ly1, mx1 + lx2 + 1, my1 + ly2 + 1),
        roi_size,
    )

def _estimate_fill_color(
    rgb_region: np.ndarray,
    inner_mask: np.ndarray,
) -> tuple[int, int, int]:
    active = inner_mask > 0
    if not np.any(active):
        return OVERLAY_BG_COLOR[:3]
    pixels = rgb_region[active]
    median = np.median(pixels, axis=0)

    return tuple(
        int(np.clip(v, 230, 255)) for v in median
    )

def _is_rectangular_narrative_box(bubble: BubbleCandidate) -> bool:
    if bubble.detected_bbox is None:
        return False
    w = max(1, bubble.detected_bbox[2] - bubble.detected_bbox[0])

    h = max(1, bubble.detected_bbox[3] - bubble.detected_bbox[1])

    aspect = w / h
    if bubble.mask_area > 0:
        extent = bubble.mask_area / max(1, w * h)

        if extent >= 0.93 and (aspect >= 2.2 or aspect <= 0.45):
            return True
    if bubble.container_type == CONTAINER_RECTANGULAR:
        return aspect >= 2.0 or aspect <= 0.5
    return False
def _resolve_render_mode(
    bubble: BubbleCandidate,
    gui_display_mode: str,
) -> str:
    if gui_display_mode == OVERLAY_MODE_RESPONSIVE:
        return RENDER_RESPONSIVE_TEXTBOX
    if gui_display_mode == OVERLAY_MODE_OCR_BBOX:
        return RENDER_FALLBACK
    if gui_display_mode == OVERLAY_MODE_CONTAINER:
        if bubble.fallback_used or bubble.detected_bbox is None:
            return RENDER_FALLBACK
        return RENDER_RECTANGULAR
    if gui_display_mode == OVERLAY_MODE_MASKED:
        if bubble.fallback_used or bubble.inner_fill_mask is None:
            return RENDER_FALLBACK
        if _is_rectangular_narrative_box(bubble):
            return RENDER_RECTANGULAR
        return RENDER_MASKED_BUBBLE
    return RENDER_FALLBACK
def _adaptive_inner_pad(box_w: int, box_h: int) -> tuple[int, int]:
    short_side = min(box_w, box_h)

    if short_side < 60:
        return (4, 3)

    if short_side < 120:
        return (6, 4)

    return (8, 6)

def _seed_points_for_ocr(
    ocr_local: tuple[int, int, int, int],
    gray: np.ndarray,
    light_mask: np.ndarray,
) -> list[tuple[int, int]]:
    x1, y1, x2, y2 = ocr_local
    h, w = gray.shape[:2]
    seeds: list[tuple[int, int]] = []
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    offsets = [
        (0, 0), (-6, 0), (6, 0), (0, -6), (0, 6),
        (-10, -8), (10, 8), (-8, 10), (8, -10),
        (x1 - cx, y1 - cy), (x2 - cx - 1, y2 - cy - 1),
    ]
    for dx, dy in offsets:
        sx = int(np.clip(cx + dx, 0, w - 1))

        sy = int(np.clip(cy + dy, 0, h - 1))

        seeds.append((sx, sy))

    region = light_mask[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
    if region.size > 0 and np.any(region):
        ys, xs = np.where(region)

        idx = len(xs) // 2
        seeds.append((int(xs[idx]) + max(0, x1), int(ys[idx]) + max(0, y1)))

    best_val = -1
    best_pt = (cx, cy)

    pad = 8
    rx1, ry1 = max(0, x1 - pad), max(0, y1 - pad)

    rx2, ry2 = min(w, x2 + pad), min(h, y2 + pad)

    for yy in range(ry1, ry2, 4):
        for xx in range(rx1, rx2, 4):
            val = int(gray[yy, xx])

            if val > best_val:
                best_val = val
                best_pt = (xx, yy)

    seeds.append(best_pt)

    return seeds
def _classify_container_type(
    bbox: tuple[int, int, int, int],
    *,
    fallback: bool,
) -> str:
    if fallback:
        return CONTAINER_FALLBACK
    w = max(1, bbox[2] - bbox[0])

    h = max(1, bbox[3] - bbox[1])

    aspect = w / h
    if 0.55 <= aspect <= 1.8 and min(w, h) >= 30:
        return CONTAINER_SPEECH_BUBBLE
    return CONTAINER_RECTANGULAR
def detect_light_region_container(
    roi_image: Image.Image,
    source_bbox: tuple[int, int, int, int],
    roi_size: tuple[int, int],
) -> BubbleCandidate:
    search_bbox = expand_search_bbox(source_bbox, roi_size)

    sx1, sy1, sx2, sy2 = search_bbox
    warnings: list[str] = []
    crop = roi_image.crop((sx1, sy1, sx2, sy2))

    rgb = np.array(crop.convert("RGB"))

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    _, binary = cv2.threshold(
        gray, BUBBLE_LIGHT_THRESHOLD, 255, cv2.THRESH_BINARY
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))

    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)

    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    ocr_local = (
        source_bbox[0] - sx1,
        source_bbox[1] - sy1,
        source_bbox[2] - sx1,
        source_bbox[3] - sy1,
    )

    ocr_area = max(1, _bbox_area(source_bbox))

    roi_area = max(1, roi_size[0] * roi_size[1])

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary)

    seeds = _seed_points_for_ocr(ocr_local, gray, binary > 0)

    best_score = -1.0
    best_bbox: tuple[int, int, int, int] | None = None
    best_whiteness = 0.0
    best_area_ratio = 0.0
    best_label_id = -1
    for label in range(1, num_labels):
        lx, ly, lw, lh, area = stats[label]
        if lw < 4 or lh < 4:
            continue
        comp_local = (lx, ly, lx + lw, ly + lh)

        comp_global = _clip_bbox_to_roi(
            (lx + sx1, ly + sy1, lx + lw + sx1, ly + lh + sy1), roi_size
        )

        overlap = _intersection_area(comp_local, ocr_local)

        if overlap < ocr_area * 0.25:
            continue
        comp_area = _bbox_area(comp_global)

        area_ratio = comp_area / ocr_area
        if area_ratio < BUBBLE_MIN_AREA_RATIO:
            continue
        if comp_area > roi_area * BUBBLE_MAX_AREA_RATIO:
            continue
        mask = labels == label
        region_gray = gray[mask]
        if region_gray.size == 0:
            continue
        whiteness = float(np.mean(region_gray >= BUBBLE_LIGHT_THRESHOLD))

        if whiteness < BUBBLE_MIN_WHITENESS_RATIO:
            continue
        seed_hit = any(labels[sy, sx] == label for sx, sy in seeds if 0 <= sy < labels.shape[0] and 0 <= sx < labels.shape[1])

        score = comp_area * whiteness * (1.2 if seed_hit else 1.0)

        if score > best_score:
            best_score = score
            best_bbox = comp_global
            best_whiteness = whiteness
            best_area_ratio = area_ratio
            best_label_id = label
    if best_bbox is not None and best_label_id >= 0:
        component_mask, inner_fill_mask, mask_bbox = _build_component_masks(
            labels, best_label_id, search_bbox, best_bbox
        )

        inner = compute_mask_inner_text_bbox(inner_fill_mask, mask_bbox, roi_size)

        if _bbox_area(inner) < ocr_area * 0.8:
            inner = compute_inner_text_bbox(best_bbox, roi_size)

            warnings.append("Masken-Innenfläche klein – rechteckiger Fallback")

        ctype = _classify_container_type(best_bbox, fallback=False)

        return BubbleCandidate(
            source_bbox=source_bbox,
            search_bbox=search_bbox,
            detected_bbox=best_bbox,
            inner_text_bbox=inner,
            detection_method=DETECTION_BUBBLE_LIGHT,
            confidence=min(1.0, best_whiteness),
            whiteness_ratio=best_whiteness,
            area_ratio=best_area_ratio,
            fallback_used=False,
            warnings=warnings,
            container_type=ctype,
            component_mask=component_mask,
            inner_fill_mask=inner_fill_mask,
            mask_bbox=mask_bbox,
            mask_area=int(np.count_nonzero(component_mask)),
            inner_mask_area=int(np.count_nonzero(inner_fill_mask)),
        )

    warnings.append("Keine helle Textfläche gefunden")

    fb = fallback_bbox_expand(source_bbox, roi_size)

    inner = compute_inner_text_bbox(fb, roi_size)

    return BubbleCandidate(
        source_bbox=source_bbox,
        search_bbox=search_bbox,
        detected_bbox=None,
        inner_text_bbox=inner,
        detection_method=DETECTION_FALLBACK,
        confidence=0.0,
        whiteness_ratio=0.0,
        area_ratio=_bbox_area(fb) / ocr_area,
        fallback_used=True,
        warnings=warnings,
        container_type=CONTAINER_FALLBACK,
    )

def detect_text_container(
    roi_image: Image.Image,
    source_bbox: tuple[float, float, float, float],
    roi_size: tuple[int, int],
) -> BubbleCandidate:
    return detect_light_region_container(
        roi_image, _int_bbox(source_bbox), roi_size
    )

def _line_layout_cost(
    line: str,
    line_width: float,
    max_width: int,
    word_count: int,
    total_words: int,
) -> float:
    if max_width <= 0:
        return 0.0
    width_ratio = line_width / max_width
    balance = abs(0.72 - width_ratio) * 2.0
    short_penalty = 0.0
    if word_count == 1 and total_words > 2:
        short_penalty += 3.5
    if line_width < max_width * 0.28 and word_count <= 2:
        short_penalty += 2.0
    long_penalty = 0.0
    if line_width > max_width * 0.98:
        long_penalty += 1.5
    return balance + short_penalty + long_penalty
def _best_line_layout_dp(
    words: list[str],
    font: ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
    *,
    max_lines: int = RESPONSIVE_MAX_LINES,
) -> list[str] | None:
    n = len(words)

    if n == 0:
        return [""]
    if n == 1:
        return words
    inf = 1e12
    dp_cost = [inf] * (n + 1)

    dp_lines: list[list[str] | None] = [None] * (n + 1)

    dp_cost[0] = 0.0
    dp_lines[0] = []
    for i in range(1, n + 1):
        for j in range(i):
            line_words = words[j:i]
            line = " ".join(line_words)

            line_w = _text_width_draw(draw, font, line)

            if line_w > max_width:
                continue
            prev_lines = dp_lines[j]
            if prev_lines is None:
                continue
            if len(prev_lines) >= max_lines:
                continue
            cost = dp_cost[j] + _line_layout_cost(
                line, line_w, max_width, len(line_words), n
            )

            if cost < dp_cost[i]:
                dp_cost[i] = cost
                dp_lines[i] = prev_lines + [line]
    result = dp_lines[n]
    if result is None:
        return None
    if len(result) > max_lines:
        return None
    return result
def _break_word_to_fit(
    word: str,
    font: ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    if not word:
        return [""]
    if _text_width_draw(draw, font, word) <= max_width:
        return [word]
    parts: list[str] = []
    current = ""
    for ch in word:
        candidate = current + ch
        if current and _text_width_draw(draw, font, candidate) > max_width:
            parts.append(current)

            current = ch
        else:
            current = candidate
    if current:
        parts.append(current)

    if len(parts) >= 2 and len(parts[-1]) == 1 and len(parts[-2]) > 2:
        merged = parts[-2][:-1] + parts[-1]
        if _text_width_draw(draw, font, merged) <= max_width:
            parts[-2] = merged
            parts.pop()

    return parts if parts else [word]
def _prepare_words_for_width(
    words: list[str],
    font: ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw,
) -> tuple[list[str], bool]:
    prepared: list[str] = []
    word_break_used = False
    for word in words:
        if _text_width_draw(draw, font, word) <= max_width:
            prepared.append(word)

        else:
            broken = _break_word_to_fit(word, font, max_width, draw)

            if len(broken) > 1:
                word_break_used = True
            prepared.extend(broken)

    return prepared, word_break_used
def fit_text_exact_bbox(
    text: str,
    box_width: int,
    box_height: int,
    *,
    font_path: str | None = None,
    min_font_size: int = EXACT_MIN_FONT_SIZE,
    max_font_size_cap: int = EXACT_MAX_FONT_SIZE_CAP,
    max_lines: int = EXACT_MAX_LINES,
) -> dict[str, Any]:
    pad_x, pad_y = _exact_bbox_padding(box_width, box_height)

    available_w = max(1, box_width - 2 * pad_x)

    available_h = max(1, box_height - 2 * pad_y)

    dynamic_max = _exact_dynamic_max_font_size(
        box_width,
        box_height,
        min_font_size=min_font_size,
        max_font_size_cap=max_font_size_cap,
    )

    cleaned = text.strip() or " "
    words = cleaned.split()

    draw = _measure_draw()

    best: dict[str, Any] | None = None
    lo, hi = min_font_size, dynamic_max
    while lo <= hi:
        mid = (lo + hi + 1) // 2
        font = (
            ImageFont.truetype(font_path, mid)

            if font_path
            else load_overlay_font(mid)

        )

        prepared, _ = _prepare_words_for_width(words, font, available_w, draw)

        lines = _best_line_layout_dp(
            prepared,
            font,
            available_w,
            draw,
            max_lines=max_lines,
        )

        if lines is None:
            hi = mid - 1
            continue
        used_w, used_h = _measure_text_block(
            draw, font, lines, line_gap=_exact_line_gap(mid)

        )

        if used_w <= available_w and used_h <= available_h:
            area = max(1, available_w * available_h)

            occupancy = min(1.0, (used_w * used_h) / area)

            best = {
                "font_size": mid,
                "lines": lines,
                "line_count": len(lines),
                "fits": True,
                "truncated": False,
                "padding_x": pad_x,
                "padding_y": pad_y,
                "used_width": used_w,
                "used_height": used_h,
                "available_width": available_w,
                "available_height": available_h,
                "occupancy_ratio": round(occupancy, 4),
                "dynamic_max_font_size": dynamic_max,
                "overflow_reason": None,
            }

            lo = mid + 1
        else:
            hi = mid - 1
    if best is not None:
        return best
    font = (
        ImageFont.truetype(font_path, min_font_size)

        if font_path
        else load_overlay_font(min_font_size)

    )

    prepared, word_break_used = _prepare_words_for_width(
        words, font, available_w, draw
    )

    lines = _best_line_layout_dp(
        prepared, font, available_w, draw, max_lines=max_lines
    )

    overflow_reason: str | None = None
    if lines is None:
        lines = wrap_text_to_box(cleaned, font, available_w)

        overflow_reason = EXACT_OVERFLOW_MSG
    truncated = len(lines) > max_lines
    if truncated:
        lines = lines[:max_lines]
        overflow_reason = EXACT_OVERFLOW_MSG
    used_w, used_h = _measure_text_block(
        draw,
        font,
        lines,
        line_gap=_exact_line_gap(min_font_size),
    )

    fits = (
        used_h <= available_h
        and used_w <= available_w
        and not truncated
        and lines is not None
    )

    if not fits and overflow_reason is None:
        overflow_reason = EXACT_OVERFLOW_MSG
    if word_break_used and overflow_reason is None:
        overflow_reason = "word_break_required"
    area = max(1, available_w * available_h)

    occupancy = min(1.0, (used_w * used_h) / area)

    return {
        "font_size": min_font_size,
        "lines": lines,
        "line_count": len(lines),
        "fits": fits,
        "truncated": truncated or not fits,
        "padding_x": pad_x,
        "padding_y": pad_y,
        "used_width": used_w,
        "used_height": used_h,
        "available_width": available_w,
        "available_height": available_h,
        "occupancy_ratio": round(occupancy, 4),
        "dynamic_max_font_size": dynamic_max,
        "overflow_reason": overflow_reason,
    }

def fit_translation_text_responsive(
    text: str,
    box_width: int,
    box_height: int,
    *,
    font_path: str | None = None,
    min_font_size: int = OVERLAY_MIN_FONT_SIZE,
    max_font_size_cap: int = OVERLAY_MAX_FONT_SIZE_CAP,
    max_lines: int = RESPONSIVE_MAX_LINES,
) -> dict[str, Any]:
    pad_x, pad_y = _dynamic_padding(box_width, box_height)

    available_w = max(1, box_width - 2 * pad_x)

    available_h = max(1, box_height - 2 * pad_y)

    dynamic_max = _dynamic_max_font_size(
        box_width, box_height,
        min_font_size=min_font_size,
        max_font_size_cap=max_font_size_cap,
    )

    cleaned = text.strip() or " "
    words = cleaned.split()

    draw = _measure_draw()

    best: dict[str, Any] | None = None
    lo, hi = min_font_size, dynamic_max
    while lo <= hi:
        mid = (lo + hi + 1) // 2
        font = (
            ImageFont.truetype(font_path, mid)

            if font_path
            else load_overlay_font(mid)

        )

        lines = _best_line_layout_dp(
            words, font, available_w, draw, max_lines=max_lines
        )

        if lines is None:
            hi = mid - 1
            continue
        used_w, used_h = _measure_text_block(draw, font, lines)

        fits = used_w <= available_w and used_h <= available_h
        if fits:
            area = max(1, available_w * available_h)

            occupancy = min(1.0, (used_w * used_h) / area)

            best = {
                "font_size": mid,
                "lines": lines,
                "line_count": len(lines),
                "fits": True,
                "truncated": False,
                "padding_x": pad_x,
                "padding_y": pad_y,
                "used_width": used_w,
                "used_height": used_h,
                "available_width": available_w,
                "available_height": available_h,
                "occupancy_ratio": round(occupancy, 4),
                "dynamic_max_font_size": dynamic_max,
            }

            lo = mid + 1
        else:
            hi = mid - 1
    if best is not None:
        return best
    font = (
        ImageFont.truetype(font_path, min_font_size)

        if font_path
        else load_overlay_font(min_font_size)

    )

    lines = _best_line_layout_dp(
        words, font, available_w, draw, max_lines=max_lines
    )

    if lines is None:
        lines = wrap_text_to_box(cleaned, font, available_w)

    truncated = len(lines) > max_lines
    if truncated:
        lines = lines[:max_lines]
        if lines:
            last = lines[-1]
            while (
                _text_width_draw(draw, font, last + "…") > available_w
                and len(last) > 1
            ):
                last = last[:-1]
            lines[-1] = last + "…"
    used_w, used_h = _measure_text_block(draw, font, lines)

    area = max(1, available_w * available_h)

    occupancy = min(1.0, (used_w * used_h) / area)

    return {
        "font_size": min_font_size,
        "lines": lines,
        "line_count": len(lines),
        "fits": used_h <= available_h and used_w <= available_w and not truncated,
        "truncated": truncated,
        "padding_x": pad_x,
        "padding_y": pad_y,
        "used_width": used_w,
        "used_height": used_h,
        "available_width": available_w,
        "available_height": available_h,
        "occupancy_ratio": round(occupancy, 4),
        "dynamic_max_font_size": dynamic_max,
    }

def _responsive_fit_to_overlay_result(fit: dict[str, Any]) -> OverlayFitResult:
    return OverlayFitResult(
        font_size=int(fit["font_size"]),
        lines=list(fit["lines"]),
        line_count=int(fit["line_count"]),
        text_width=int(fit["used_width"]),
        text_height=int(fit["used_height"]),
        fits=bool(fit["fits"]),
        truncated=bool(fit.get("truncated", False)),
    )

def _exact_fit_to_overlay_result(fit: dict[str, Any]) -> OverlayFitResult:
    return _responsive_fit_to_overlay_result(fit)

def wrap_text_to_box(
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    if max_width <= 0:
        return [text]
    words = text.split()

    if not words:
        return [""]
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join(current + [word]) if current else word
        if _text_width(font, trial) <= max_width:
            current.append(word)

        else:
            if current:
                lines.append(" ".join(current))

                current = [word]
            else:
                lines.append(word)

                current = []
    if current:
        lines.append(" ".join(current))

    return lines
def fit_translation_text(
    text: str,
    box_width: int,
    box_height: int,
    *,
    min_font_size: int = OVERLAY_MIN_FONT_SIZE,
    max_font_size: int = OVERLAY_MAX_FONT_SIZE,
    padding_x: int | None = None,
    padding_y: int | None = None,
    inner_pad: int | None = None,
    max_lines: int = OVERLAY_MAX_LINES,
) -> OverlayFitResult:
    if inner_pad is None:
        pad_x, pad_y = _adaptive_inner_pad(box_width, box_height)

    else:
        pad_x = pad_y = inner_pad
    if padding_x is not None:
        pad_x = padding_x
    if padding_y is not None:
        pad_y = padding_y
    usable_w = max(1, box_width - 2 * pad_x)

    usable_h = max(1, box_height - 2 * pad_y)

    cleaned = text.strip() or " "
    lo, hi = min_font_size, max_font_size
    best_fit: OverlayFitResult | None = None
    while lo <= hi:
        mid = (lo + hi + 1) // 2
        font = load_overlay_font(mid)

        line_h = _line_height(font)

        lines = wrap_text_to_box(cleaned, font, usable_w)

        if len(lines) > max_lines:
            hi = mid - 1
            continue
        total_h = len(lines) * line_h + max(0, len(lines) - 1) * OVERLAY_LINE_GAP
        max_line_w = max((_text_width(font, ln) for ln in lines), default=0.0)

        candidate = OverlayFitResult(
            font_size=mid,
            lines=lines,
            line_count=len(lines),
            text_width=int(round(max_line_w)),
            text_height=int(total_h),
            fits=total_h <= usable_h and max_line_w <= usable_w,
            truncated=False,
        )

        if candidate.fits:
            best_fit = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    if best_fit is not None:
        return best_fit
    font = load_overlay_font(min_font_size)

    line_h = _line_height(font)

    lines = wrap_text_to_box(cleaned, font, usable_w)

    truncated = len(lines) > max_lines
    if truncated:
        lines = lines[:max_lines]
        if lines:
            last = lines[-1]
            while _text_width(font, last + "…") > usable_w and len(last) > 1:
                last = last[:-1]
            lines[-1] = last + "…"
    total_h = len(lines) * line_h + max(0, len(lines) - 1) * OVERLAY_LINE_GAP
    max_line_w = max((_text_width(font, ln) for ln in lines), default=0.0)

    return OverlayFitResult(
        font_size=min_font_size,
        lines=lines,
        line_count=len(lines),
        text_width=int(round(max_line_w)),
        text_height=int(total_h),
        fits=False,
        truncated=truncated,
    )

def detect_overlay_collisions(
    overlays: list[tuple[str, tuple[int, int, int, int]]],
) -> dict[str, bool]:
    warnings: dict[str, bool] = {gid: False for gid, _ in overlays}

    items = list(overlays)

    for i, (gid_a, box_a) in enumerate(items):
        ax1, ay1, ax2, ay2 = box_a
        for gid_b, box_b in items[i + 1 :]:
            bx1, by1, bx2, by2 = box_b
            if ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1:
                overlap = _intersection_area(box_a, box_b)

                smaller = min(_bbox_area(box_a), _bbox_area(box_b))

                if smaller > 0 and overlap / smaller > 0.15:
                    warnings[gid_a] = True
                    warnings[gid_b] = True
    return warnings
def _draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    bbox: tuple[int, int, int, int],
    fill: tuple[int, ...],
    radius: int = 4,
) -> None:
    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(bbox, radius=radius, fill=fill)

    else:
        draw.rectangle(bbox, fill=fill)

def _draw_debug_rect(
    draw: ImageDraw.ImageDraw,
    bbox: tuple[int, int, int, int],
    color: tuple[int, ...],
    width: int = 2,
) -> None:
    x1, y1, x2, y2 = bbox
    draw.rectangle([x1, y1, x2, y2], outline=color[:3], width=width)

def _draw_centered_text_block(
    draw: ImageDraw.ImageDraw,
    bbox: tuple[int, int, int, int],
    lines: list[str],
    font: ImageFont.ImageFont,
    *,
    pad_x: int,
    pad_y: int,
    line_gap: int = RESPONSIVE_LINE_GAP,
) -> None:
    x1, y1, x2, y2 = bbox
    box_w = x2 - x1
    box_h = y2 - y1
    used_w, used_h = _measure_text_block(draw, font, lines, line_gap=line_gap)

    y_cursor = y1 + pad_y + max(0, (box_h - 2 * pad_y - used_h) // 2)

    for line in lines:
        line_bbox = draw.textbbox((0, 0), line or " ", font=font)

        line_w = int(line_bbox[2] - line_bbox[0])

        line_h = int(line_bbox[3] - line_bbox[1])

        x = x1 + pad_x + max(0, (box_w - 2 * pad_x - line_w) // 2)

        draw.text(
            (x - line_bbox[0], y_cursor - line_bbox[1]),
            line,
            fill=OVERLAY_TEXT_COLOR[:3],
            font=font,
        )

        y_cursor += line_h + line_gap
def _draw_mask_debug(
    draw: ImageDraw.ImageDraw,
    info: BubbleOverlayGroupInfo,
) -> None:
    b = info.bubble
    if b is None:
        return
    _draw_debug_rect(draw, info.roi_bbox, DEBUG_COLOR_OCR, 1)

    _draw_debug_rect(draw, b.search_bbox, DEBUG_COLOR_SEARCH, 1)

    if b.detected_bbox:
        _draw_debug_rect(draw, b.detected_bbox, DEBUG_COLOR_CONTAINER, 1)

    _draw_debug_rect(draw, b.inner_text_bbox, DEBUG_COLOR_INNER, 1)

    if b.mask_bbox and b.component_mask is not None:
        mx1, my1, mx2, my2 = b.mask_bbox
        comp = Image.fromarray(b.component_mask).convert("L")

        tint = Image.new("RGBA", comp.size, DEBUG_COLOR_COMPONENT_MASK)

        draw.bitmap((mx1, my1), comp, fill=DEBUG_COLOR_COMPONENT_MASK[:3])

    if b.mask_bbox and b.inner_fill_mask is not None:
        mx1, my1, _, _ = b.mask_bbox
        inner = Image.fromarray(b.inner_fill_mask).convert("L")

        overlay = Image.new("RGBA", inner.size, DEBUG_COLOR_INNER_MASK)

        draw.bitmap((mx1, my1), inner, fill=DEBUG_COLOR_INNER_MASK[:3])

    if info.render_mode == RENDER_FALLBACK:
        _draw_debug_rect(draw, info.overlay_bbox, DEBUG_COLOR_FALLBACK, 2)

def _apply_mask_fill_to_array(
    base_rgb: np.ndarray,
    bubble: BubbleCandidate,
) -> None:
    if (
        bubble.mask_bbox is None
        or bubble.inner_fill_mask is None
        or bubble.inner_fill_mask.size == 0
    ):
        return
    x1, y1, x2, y2 = bubble.mask_bbox
    region = base_rgb[y1:y2, x1:x2]
    if (
        region.shape[0] != bubble.inner_fill_mask.shape[0]
        or region.shape[1] != bubble.inner_fill_mask.shape[1]
    ):
        return
    fill_color = _estimate_fill_color(region, bubble.inner_fill_mask)

    mask = bubble.inner_fill_mask > 0
    for c in range(3):
        region[:, :, c] = np.where(mask, fill_color[c], region[:, :, c])

    base_rgb[y1:y2, x1:x2] = region
def _render_group_on_array(
    base_rgb: np.ndarray,
    info: OverlayGroupInfo,
) -> np.ndarray:
    if not info.display_text:
        return base_rgb
    arr = base_rgb.copy()

    render_mode = RENDER_FALLBACK
    bubble: BubbleCandidate | None = None
    if isinstance(info, BubbleOverlayGroupInfo):
        render_mode = info.render_mode
        bubble = info.bubble
    text_bbox = info.overlay_bbox
    render_bbox = text_bbox
    pad_x, pad_y = _dynamic_padding(
        text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
    )

    if isinstance(info, BubbleOverlayGroupInfo):
        if info.render_bbox != (0, 0, 0, 0):
            render_bbox = info.render_bbox
        if info.text_bbox != (0, 0, 0, 0):
            text_bbox = info.text_bbox
        if info.padding_x or info.padding_y:
            pad_x, pad_y = info.padding_x, info.padding_y
    font = load_overlay_font(info.font_size or 12)

    lines = info.lines or wrap_text_to_box(
        info.display_text,
        font,
        max(1, text_bbox[2] - text_bbox[0] - 2 * pad_x),
    )

    if render_mode == RENDER_MASKED_BUBBLE and bubble is not None:
        _apply_mask_fill_to_array(arr, bubble)

        pil = Image.fromarray(arr)

        draw = ImageDraw.Draw(pil)

        _draw_centered_text_block(
            draw, text_bbox, lines, font, pad_x=pad_x, pad_y=pad_y
        )

        return np.array(pil.convert("RGB"))

    pil = Image.fromarray(arr)

    draw = ImageDraw.Draw(pil)

    fill_target = render_bbox
    if render_mode == RENDER_RECTANGULAR and bubble and bubble.detected_bbox:
        fill_target = bubble.detected_bbox
    elif render_mode in (RENDER_RESPONSIVE_TEXTBOX, RENDER_EXACT_GROUP_BBOX):
        fill_target = render_bbox
    fx1, fy1, fx2, fy2 = fill_target
    if render_mode == RENDER_EXACT_GROUP_BBOX:
        draw.rectangle([fx1, fy1, fx2, fy2], fill=OVERLAY_BG_COLOR[:3])

    else:
        _draw_rounded_rect(draw, (fx1, fy1, fx2, fy2), OVERLAY_BG_COLOR)

    _draw_centered_text_block(
        draw,
        text_bbox,
        lines,
        font,
        pad_x=pad_x,
        pad_y=pad_y,
        line_gap=(
            _exact_line_gap(info.font_size or 12)

            if render_mode == RENDER_EXACT_GROUP_BBOX
            else RESPONSIVE_LINE_GAP
        ),
    )

    if render_mode == RENDER_EXACT_GROUP_BBOX and not info.fits:
        warn_x = max(fx1 + 2, fx2 - 14)

        warn_y = max(fy1 + 2, fy1)

        draw.text((warn_x, warn_y), "!", fill=(200, 40, 40), font=font)

    return np.array(pil.convert("RGB"))

def render_overlay_to_pillow(
    base_image: Image.Image,
    groups: list[OverlayGroupInfo],
    *,
    display_mode: str = OVERLAY_MODE_TRANSLATION,
    show_debug: bool = False,
) -> Image.Image:
    if display_mode == OVERLAY_MODE_ORIGINAL and not show_debug:
        return base_image.copy()

    if display_mode == OVERLAY_MODE_BBOX:
        img = base_image.convert("RGBA")

        draw = ImageDraw.Draw(img)

        for info in groups:
            x1, y1, x2, y2 = info.roi_bbox
            draw.rectangle([x1, y1, x2, y2], outline=OVERLAY_BBOX_COLOR[:3], width=2)

        return img.convert("RGB")

    translation_modes = (
        OVERLAY_MODE_TRANSLATION,
        OVERLAY_MODE_CONTAINER,
        OVERLAY_MODE_OCR_BBOX,
        OVERLAY_MODE_MASKED,
        OVERLAY_MODE_RESPONSIVE,
        OVERLAY_MODE_EXACT_GROUP,
    )

    base_rgb = np.array(base_image.convert("RGB"))

    if display_mode in translation_modes:
        for info in groups:
            base_rgb = _render_group_on_array(base_rgb, info)

    img = Image.fromarray(base_rgb)

    if show_debug:
        draw = ImageDraw.Draw(img)

        for info in groups:
            if isinstance(info, BubbleOverlayGroupInfo) and info.bubble:
                _draw_mask_debug(draw, info)

    return img.convert("RGB")

def _display_text_for_status(german: str, status: str) -> str:
    if status in ("wird übersetzt", "wartet auf Stabilisierung", "wartet auf OCR"):
        return LOADING_TEXT
    if status == "Übersetzungsfehler":
        return ERROR_TEXT
    if german:
        return german
    return LOADING_TEXT
def _detect_bubble_cached(
    gid: str,
    roi_image: Image.Image,
    bbox: tuple[float, float, float, float],
    roi_size: tuple[int, int],
    bubble_cache: dict[str, BubbleCandidate] | None,
) -> BubbleCandidate:
    if bubble_cache is not None and gid in bubble_cache:
        return bubble_cache[gid]
    try:
        bubble = detect_text_container(roi_image, bbox, roi_size)

    except Exception:
        source = _int_bbox(bbox)

        fb = fallback_bbox_expand(source, roi_size)

        bubble = BubbleCandidate(
            source_bbox=source,
            search_bbox=expand_search_bbox(source, roi_size),
            detected_bbox=None,
            inner_text_bbox=compute_inner_text_bbox(fb, roi_size),
            detection_method=DETECTION_FALLBACK,
            confidence=0.0,
            whiteness_ratio=0.0,
            area_ratio=1.0,
            fallback_used=True,
            warnings=["Container-Erkennung fehlgeschlagen"],
            container_type=CONTAINER_FALLBACK,
        )

    if bubble_cache is not None:
        bubble_cache[gid] = bubble
    return bubble
def _fit_for_mode(
    display_text: str,
    overlay_bbox: tuple[int, int, int, int],
    gui_display_mode: str,
) -> tuple[OverlayFitResult, dict[str, Any] | None]:
    box_w = overlay_bbox[2] - overlay_bbox[0]
    box_h = overlay_bbox[3] - overlay_bbox[1]
    if gui_display_mode == OVERLAY_MODE_EXACT_GROUP:
        ef = fit_text_exact_bbox(display_text, box_w, box_h)

        return _exact_fit_to_overlay_result(ef), ef
    if gui_display_mode in (OVERLAY_MODE_RESPONSIVE, OVERLAY_MODE_MASKED):
        rf = fit_translation_text_responsive(display_text, box_w, box_h)

        return _responsive_fit_to_overlay_result(rf), rf
    fit = fit_translation_text(display_text, box_w, box_h)

    return fit, None
def build_overlay_groups(
    *,
    grouped: list[tuple[str, tuple[float, float, float, float], str, str, str, str, str]],
    roi_size: tuple[int, int],
    canvas_size: tuple[int, int] = (0, 0),
    canvas_offset: tuple[int, int] = (0, 0),
    roi_image: Image.Image | None = None,
    use_container_detection: bool = False,
    gui_display_mode: str = OVERLAY_MODE_EXACT_GROUP,
    bubble_cache: dict[str, BubbleCandidate] | None = None,
) -> list[OverlayGroupInfo]:
    raw_overlays: list[tuple[str, tuple[int, int, int, int]]] = []
    infos: list[OverlayGroupInfo] = []
    for gid, bbox, ocr_text, german, status, cache_source, engine in grouped:
        if status in ("verworfen",):
            continue
        roi_bbox = _int_bbox(bbox)

        group_bbox = _clip_bbox_to_roi(roi_bbox, roi_size)

        display_text = _display_text_for_status(german, status)

        bubble: BubbleCandidate | None = None
        render_mode = RENDER_FALLBACK
        mask_present = False
        border_preserved = False
        render_bbox = (0, 0, 0, 0)

        text_bbox = (0, 0, 0, 0)

        responsive_fit: dict[str, Any] | None = None
        bbox_unchanged = False
        if gui_display_mode == OVERLAY_MODE_EXACT_GROUP:
            render_mode = RENDER_EXACT_GROUP_BBOX
            render_bbox = expand_overlay_bbox(
                bbox,
                roi_size,
                padding_x=0,
                padding_y=0,
                max_expand_ratio=1.25,
            )

            overlay_bbox = render_bbox
            text_bbox = render_bbox
            bbox_unchanged = render_bbox == group_bbox
        elif gui_display_mode == OVERLAY_MODE_RESPONSIVE:
            render_mode = RENDER_RESPONSIVE_TEXTBOX
            if roi_image is not None:
                bubble = _detect_bubble_cached(
                    gid, roi_image, bbox, roi_size, bubble_cache
                )

                if bubble.detected_bbox and not bubble.fallback_used:
                    render_bbox = bubble.detected_bbox
                else:
                    render_bbox = fallback_bbox_expand(roi_bbox, roi_size)

            else:
                render_bbox = fallback_bbox_expand(roi_bbox, roi_size)

            overlay_bbox = render_bbox
            text_bbox = render_bbox
        elif use_container_detection and roi_image is not None:
            bubble = _detect_bubble_cached(
                gid, roi_image, bbox, roi_size, bubble_cache
            )

            render_mode = _resolve_render_mode(bubble, gui_display_mode)

            mask_present = (
                bubble.inner_fill_mask is not None and bubble.mask_area > 0
            )

            border_preserved = (
                render_mode == RENDER_MASKED_BUBBLE and mask_present
            )

            if gui_display_mode == OVERLAY_MODE_OCR_BBOX:
                overlay_bbox = expand_overlay_bbox(bbox, roi_size)

                render_bbox = overlay_bbox
            elif render_mode == RENDER_RECTANGULAR and bubble.detected_bbox:
                overlay_bbox = compute_inner_text_bbox(
                    bubble.detected_bbox, roi_size
                )

                render_bbox = bubble.detected_bbox
            elif (
                gui_display_mode == OVERLAY_MODE_MASKED
                and bubble.inner_fill_mask is not None
                and bubble.mask_bbox
            ):
                overlay_bbox = compute_mask_responsive_text_bbox(
                    bubble.inner_fill_mask, bubble.mask_bbox, roi_size
                )

                render_bbox = bubble.mask_bbox
            else:
                overlay_bbox = bubble.inner_text_bbox
                render_bbox = bubble.detected_bbox or overlay_bbox
            text_bbox = overlay_bbox
        else:
            overlay_bbox = expand_overlay_bbox(bbox, roi_size)

            render_bbox = overlay_bbox
            text_bbox = overlay_bbox
        fit, responsive_fit = _fit_for_mode(
            display_text, overlay_bbox, gui_display_mode
        )

        if gui_display_mode == OVERLAY_MODE_EXACT_GROUP:
            source_w = max(1, group_bbox[2] - group_bbox[0])

            source_h = max(1, group_bbox[3] - group_bbox[1])

            source_fit = fit_text_exact_bbox(ocr_text, source_w, source_h)

            source_relative_cap = max(
                EXACT_MIN_FONT_SIZE,
                int(source_fit["font_size"] * 0.85),
            )

            expanded_w = max(1, overlay_bbox[2] - overlay_bbox[0])

            expanded_h = max(1, overlay_bbox[3] - overlay_bbox[1])

            responsive_fit = fit_text_exact_bbox(
                display_text,
                expanded_w,
                expanded_h,
                max_font_size_cap=source_relative_cap,
            )

            occupancy = float(responsive_fit["occupancy_ratio"])

            if occupancy < 0.50:
                adaptive_factor = 1.25 if occupancy < 0.30 else 1.0
                adaptive_cap = max(
                    source_relative_cap,
                    min(
                        EXACT_MAX_FONT_SIZE_CAP,
                        int(source_fit["font_size"] * adaptive_factor),
                    ),
                )

                responsive_fit = fit_text_exact_bbox(
                    display_text,
                    expanded_w,
                    expanded_h,
                    max_font_size_cap=adaptive_cap,
                )

            fit = _exact_fit_to_overlay_result(responsive_fit)

        if bubble is not None:
            info: OverlayGroupInfo = BubbleOverlayGroupInfo(
                group_id=gid,
                roi_bbox=roi_bbox,
                overlay_bbox=overlay_bbox,
                ocr_text=ocr_text,
                translated_text=german,
                display_text=display_text,
                font_size=fit.font_size,
                line_count=fit.line_count,
                fits=fit.fits,
                truncated=fit.truncated,
                lines=list(fit.lines),
                cache_source=cache_source,
                engine=engine,
                status=status,
                bubble=bubble,
                render_mode=render_mode,
                mask_present=mask_present,
                border_preserved=border_preserved,
                render_bbox=render_bbox,
                text_bbox=text_bbox,
                bbox_unchanged=bbox_unchanged,
                group_bbox=group_bbox,
            )

        else:
            info = BubbleOverlayGroupInfo(
                group_id=gid,
                roi_bbox=roi_bbox,
                overlay_bbox=overlay_bbox,
                ocr_text=ocr_text,
                translated_text=german,
                display_text=display_text,
                font_size=fit.font_size,
                line_count=fit.line_count,
                fits=fit.fits,
                truncated=fit.truncated,
                lines=list(fit.lines),
                cache_source=cache_source,
                engine=engine,
                status=status,
                render_mode=render_mode,
                render_bbox=render_bbox,
                text_bbox=text_bbox,
                bbox_unchanged=bbox_unchanged,
                group_bbox=group_bbox,
            )

        if responsive_fit is not None:
            info.padding_x = int(responsive_fit["padding_x"])

            info.padding_y = int(responsive_fit["padding_y"])

            info.dynamic_max_font_size = int(
                responsive_fit["dynamic_max_font_size"]
            )

            info.used_width = int(responsive_fit["used_width"])

            info.used_height = int(responsive_fit["used_height"])

            info.available_width = int(responsive_fit["available_width"])

            info.available_height = int(responsive_fit["available_height"])

            info.occupancy_ratio = float(responsive_fit["occupancy_ratio"])

            if "overflow_reason" in responsive_fit:
                info.overflow_reason = responsive_fit.get("overflow_reason")

        if canvas_size[0] > 0:
            info.canvas_bbox = roi_bbox_to_canvas_bbox(
                overlay_bbox, roi_size, canvas_size, canvas_offset
            )

        infos.append(info)

        raw_overlays.append((gid, overlay_bbox))

    collisions = detect_overlay_collisions(raw_overlays)

    for info in infos:
        info.overlap_warning = collisions.get(info.group_id, False)

    return infos
def save_overlay_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    tmp.replace(path)

def _make_test_image(
    size: tuple[int, int],
    bg: tuple[int, int, int],
    shapes: list[tuple[str, tuple[int, int, int, int], tuple[int, int, int]]],
    *,
    outlines: list[tuple[tuple[int, int, int, int], tuple[int, int, int], int]] | None = None,
    polygons: list[tuple[list[tuple[int, int]], tuple[int, int, int]]] | None = None,
) -> Image.Image:
    img = Image.new("RGB", size, bg)

    draw = ImageDraw.Draw(img)

    for kind, bbox, color in shapes:
        x1, y1, x2, y2 = bbox
        if kind == "rect":
            draw.rectangle([x1, y1, x2, y2], fill=color)

        elif kind == "ellipse":
            draw.ellipse([x1, y1, x2, y2], fill=color)

    if polygons:
        for points, color in polygons:
            draw.polygon(points, fill=color)

    if outlines:
        for bbox, color, width in outlines:
            x1, y1, x2, y2 = bbox
            draw.ellipse([x1, y1, x2, y2], outline=color, width=width)

    return img
def _build_test_overlay_info(
    gid: str,
    ocr_bbox: tuple[int, int, int, int],
    roi_image: Image.Image,
    roi_size: tuple[int, int],
    text: str = "Hallo!",
    *,
    gui_display_mode: str = OVERLAY_MODE_MASKED,
) -> BubbleOverlayGroupInfo:
    bubble = detect_text_container(roi_image, ocr_bbox, roi_size)

    render_mode = _resolve_render_mode(bubble, gui_display_mode)

    if gui_display_mode == OVERLAY_MODE_OCR_BBOX:
        overlay_bbox = expand_overlay_bbox(ocr_bbox, roi_size)

    elif render_mode == RENDER_RECTANGULAR and bubble.detected_bbox:
        overlay_bbox = compute_inner_text_bbox(bubble.detected_bbox, roi_size)

    else:
        overlay_bbox = bubble.inner_text_bbox
    fit = fit_translation_text(
        text,
        overlay_bbox[2] - overlay_bbox[0],
        overlay_bbox[3] - overlay_bbox[1],
    )

    return BubbleOverlayGroupInfo(
        group_id=gid,
        roi_bbox=ocr_bbox,
        overlay_bbox=overlay_bbox,
        display_text=text,
        font_size=fit.font_size,
        line_count=fit.line_count,
        fits=fit.fits,
        lines=list(fit.lines),
        bubble=bubble,
        render_mode=render_mode,
        mask_present=bubble.inner_fill_mask is not None and bubble.mask_area > 0,
        border_preserved=render_mode == RENDER_MASKED_BUBBLE,
    )

def run_self_test() -> int:
    errors: list[str] = []
    def check(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            errors.append(f"{name}: {detail}")

    roi_size = (1292, 1069)

    disp_size = (1000, 827)

    offset = (20, 30)

    bbox = (100, 120, 250, 180)

    canvas = roi_bbox_to_canvas_bbox(bbox, roi_size, disp_size, offset)

    exp_x1 = int(round(20 + 100 * 1000 / 1292))

    exp_y1 = int(round(30 + 120 * 827 / 1069))

    check("O1_x1", canvas[0] == exp_x1, f"{canvas[0]} != {exp_x1}")

    check("O1_y1", canvas[1] == exp_y1, f"{canvas[1]} != {exp_y1}")

    check("O1_order", canvas[0] < canvas[2] and canvas[1] < canvas[3])

    fit_short = fit_translation_text("Hallo!", 200, 80)

    check("O2_fits", fit_short.fits is True, str(fit_short.font_size))

    check("O2_large_font", fit_short.font_size >= 16, str(fit_short.font_size))

    long_text = "Herzlichen Glückwunsch zur erfolgreichen Vertreibung der Teufel!"
    fit_long = fit_translation_text(long_text, 180, 90)

    check("O3_lines", fit_long.line_count >= 2, str(fit_long.line_count))

    check("O3_no_crash", fit_long.font_size >= 8)

    very_long = " ".join(["Wort"] * 80)

    fit_vlong = fit_translation_text(very_long, 120, 50, max_lines=4)

    check("O4_min_font", fit_vlong.font_size == 8)

    check("O4_fits_false", fit_vlong.fits is False or fit_vlong.truncated)

    bbox_a = (10, 10, 100, 60)

    bbox_b = (200, 10, 290, 60)

    groups_o5 = [
        ("G01", bbox_a, "Welcome back!", "Willkommen zurück!", "übersetzt", "", "bergamot"),
        ("G04", bbox_b, "Welcome back!", "Willkommen zurück!", "übersetzt", "", "bergamot"),
    ]
    infos_o5 = build_overlay_groups(grouped=groups_o5, roi_size=(400, 200))

    check("O5_two_overlays", len(infos_o5) == 2)

    check("O5_same_text", infos_o5[0].display_text == infos_o5[1].display_text)

    near_a = (10, 10, 120, 80)

    near_b = (100, 20, 210, 90)

    infos_o6 = build_overlay_groups(
        grouped=[
            ("G01", near_a, "A", "Alpha", "übersetzt", "", ""),
            ("G02", near_b, "B", "Beta", "übersetzt", "", ""),
        ],
        roi_size=(300, 200),
    )

    check("O6_overlap", any(i.overlap_warning for i in infos_o6))

    for cw, ch in ((800, 600), (1200, 900), (500, 400)):
        cbox = roi_bbox_to_canvas_bbox(bbox, roi_size, (cw, ch), (10, 10))

        check(f"O7_{cw}x{ch}", cbox[2] > cbox[0] and cbox[3] > cbox[1])

    tmp_dir = Path("/tmp/lingoveil_overlay_selftest")

    tmp_dir.mkdir(parents=True, exist_ok=True)

    png_path = tmp_dir / "overlay_test.png"
    base = Image.new("RGB", (300, 200), (40, 40, 40))

    rendered = render_overlay_to_pillow(
        base, infos_o5, display_mode=OVERLAY_MODE_TRANSLATION
    )

    rendered.save(png_path)

    check("O8_exists", png_path.is_file())

    check("O8_size", rendered.size == (300, 200))

    try:
        Image.open(png_path).verify()

        check("O8_valid_png", True)

    except Exception as exc:
        check("O8_valid_png", False, str(exc))

    code_b = run_bubble_self_test(quiet=True)

    check("B_all", code_b == 0, "bubble tests failed")

    code_m = run_mask_self_test(quiet=True)

    check("M_all", code_m == 0, "mask tests failed")

    code_rsp = run_responsive_self_test(quiet=True)

    check("RSP_all", code_rsp == 0, "responsive tests failed")

    code_egb = run_exact_bbox_self_test(quiet=True)

    check("EGB_all", code_egb == 0, "exact bbox tests failed")

    if errors:
        print("OVERLAY SELF-TEST FEHLGESCHLAGEN:")

        for err in errors:
            print(f"  - {err}")

        return 1
    print("OVERLAY SELF-TEST OK (O1–O8, B1–B10, M1–M10, RSP1–RSP10, EGB1–EGB11)")

    return 0
def run_bubble_self_test(*, quiet: bool = False) -> int:
    errors: list[str] = []
    def check(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            errors.append(f"{name}: {detail}")

    img_b1 = _make_test_image(
        (400, 300),
        (80, 80, 80),
        [("rect", (60, 50, 280, 200), (250, 250, 250))],
    )

    ocr_b1 = (120, 90, 220, 130)

    cand_b1 = detect_text_container(img_b1, ocr_b1, (400, 300))

    check("B1_detected", cand_b1.detected_bbox is not None)

    check("B1_no_fallback", cand_b1.fallback_used is False)

    if cand_b1.detected_bbox:
        check(
            "B1_larger",
            _bbox_area(cand_b1.detected_bbox) > _bbox_area(_int_bbox(ocr_b1)),
        )

    img_b2 = _make_test_image(
        (400, 300),
        (60, 60, 60),
        [("ellipse", (50, 40, 250, 220), (245, 245, 245))],
    )

    ocr_b2 = (110, 100, 190, 150)

    cand_b2 = detect_text_container(img_b2, ocr_b2, (400, 300))

    check("B2_detected", cand_b2.detected_bbox is not None)

    if cand_b2.detected_bbox:
        check(
            "B2_larger",
            _bbox_area(cand_b2.detected_bbox) > _bbox_area(_int_bbox(ocr_b2)),
        )

    img_b3 = Image.new("RGB", (300, 200), (30, 30, 30))

    cand_b3 = detect_text_container(img_b3, (50, 50, 120, 90), (300, 200))

    check("B3_fallback", cand_b3.fallback_used is True)

    img_b4 = Image.new("RGB", (400, 300), (250, 250, 250))

    cand_b4 = detect_text_container(img_b4, (180, 140, 220, 170), (400, 300))

    check(
        "B4_not_full_roi",
        cand_b4.fallback_used or (
            cand_b4.detected_bbox is not None
            and _bbox_area(cand_b4.detected_bbox) < 400 * 300 * 0.5
        ),
    )

    sample = "Willkommen zurück!"
    fit_b5 = fit_translation_text(sample, 100, 50, max_font_size=28)

    check("B5_font", fit_b5.font_size >= 10, str(fit_b5.font_size))

    fit_b6 = fit_translation_text(sample, 300, 150, max_font_size=42)

    check("B6_larger", fit_b6.font_size > fit_b5.font_size, f"{fit_b6.font_size} vs {fit_b5.font_size}")

    fit_b7 = fit_translation_text(
        "Herzlichen Glückwunsch zur erfolgreichen Vertreibung der Teufel!",
        200,
        100,
    )

    check("B7_lines", fit_b7.line_count >= 2)

    check("B7_no_crash", len(fit_b7.lines) > 0)

    umlaut_text = "Sie sind zurück! God's teachings."
    fit_b8 = fit_translation_text(umlaut_text, 180, 80)

    rendered_b8 = render_overlay_to_pillow(
        Image.new("RGB", (200, 100), (200, 200, 200)),
        [
            OverlayGroupInfo(
                group_id="G01",
                roi_bbox=(0, 0, 200, 100),
                overlay_bbox=(0, 0, 200, 100),
                display_text=umlaut_text,
                font_size=fit_b8.font_size,
                lines=fit_b8.lines,
            )

        ],
    )

    check("B8_render", rendered_b8.size == (200, 100))

    bubble_bbox = cand_b1.inner_text_bbox if cand_b1.inner_text_bbox else (0, 0, 100, 100)

    for cw, ch in ((600, 400), (900, 700)):
        cbox = roi_bbox_to_canvas_bbox(bubble_bbox, (400, 300), (cw, ch), (5, 5))

        check(f"B9_{cw}x{ch}", cbox[2] > cbox[0])

    img_b10 = _make_test_image(
        (300, 200),
        (70, 70, 70),
        [
            ("rect", (20, 30, 140, 120), (250, 250, 250)),
            ("rect", (100, 40, 220, 130), (248, 248, 248)),
        ],
    )

    infos_b10 = build_overlay_groups(
        grouped=[
            ("G01", (40, 55, 110, 95), "A", "Alpha", "übersetzt", "", ""),
            ("G02", (130, 60, 200, 100), "B", "Beta", "übersetzt", "", ""),
        ],
        roi_size=(300, 200),
        roi_image=img_b10,
        use_container_detection=True,
        gui_display_mode=OVERLAY_MODE_CONTAINER,
    )

    check("B10_warn", any(i.overlap_warning for i in infos_b10))

    if errors:
        if not quiet:
            print("BUBBLE SELF-TEST FEHLGESCHLAGEN:")

            for err in errors:
                print(f"  - {err}")

        return 1
    if not quiet:
        print("BUBBLE SELF-TEST OK (B1–B10)")

    return 0
def run_mask_self_test(*, quiet: bool = False) -> int:
    errors: list[str] = []
    def check(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            errors.append(f"{name}: {detail}")

    roi_m = (400, 300)

    short_text = "Hallo!"
    long_text = "Herzlichen Glückwunsch zur erfolgreichen Vertreibung der Teufel!"
    tmp_dir = Path("/tmp/lingoveil_mask_selftest")

    tmp_dir.mkdir(parents=True, exist_ok=True)

    img_m1 = _make_test_image(
        roi_m,
        (40, 40, 40),
        [("ellipse", (70, 50, 310, 230), (248, 248, 248))],
        outlines=[((70, 50, 310, 230), (20, 20, 20), 4)],
    )

    ocr_m1 = (140, 110, 240, 160)

    info_m1 = _build_test_overlay_info("G01", ocr_m1, img_m1, roi_m)

    check("M1_mask", info_m1.mask_present is True)

    check("M1_mode", info_m1.render_mode == RENDER_MASKED_BUBBLE)

    orig_m1 = np.array(img_m1.convert("RGB"))

    rendered_m1 = render_overlay_to_pillow(
        img_m1, [info_m1], display_mode=OVERLAY_MODE_MASKED
    )

    arr_m1 = np.array(rendered_m1)

    corner = orig_m1[10, 10]
    corner_after = arr_m1[10, 10]
    check("M1_corner_unchanged", np.allclose(corner, corner_after, atol=8))

    if info_m1.bubble and info_m1.bubble.mask_bbox:
        bx1, by1, bx2, by2 = info_m1.bubble.mask_bbox
        outside_x = max(0, bx1 - 12)

        check(
            "M1_outside_dark",
            int(arr_m1[outside_x, by1 + 5, 0]) < 120,
            str(int(arr_m1[outside_x, by1 + 5, 0])),
        )

    img_m2 = _make_test_image(
        roi_m,
        (50, 50, 50),
        [("ellipse", (80, 60, 280, 210), (245, 245, 245))],
        polygons=[([(150, 210), (190, 260), (120, 230)], (245, 245, 245))],
        outlines=[((80, 60, 280, 210), (15, 15, 15), 3)],
    )

    ocr_m2 = (130, 100, 220, 150)

    info_m2 = _build_test_overlay_info("G02", ocr_m2, img_m2, roi_m)

    rendered_m2 = render_overlay_to_pillow(
        img_m2, [info_m2], display_mode=OVERLAY_MODE_MASKED
    )

    tail_before = np.array(img_m2.crop((115, 235, 200, 270)).convert("RGB"))

    tail_after = np.array(rendered_m2.crop((115, 235, 200, 270)).convert("RGB"))

    check(
        "M2_tail_visible",
        np.mean(np.abs(tail_after.astype(int) - tail_before.astype(int))) < 40,
    )

    img_m3 = _make_test_image(
        roi_m,
        (60, 60, 60),
        [("rect", (50, 40, 340, 120), (250, 250, 250))],
    )

    ocr_m3 = (120, 55, 280, 95)

    info_m3 = _build_test_overlay_info("G03", ocr_m3, img_m3, roi_m)

    check("M3_rect_mode", info_m3.render_mode == RENDER_RECTANGULAR)

    img_m4 = Image.new("RGB", roi_m, (25, 25, 25))

    info_m4 = _build_test_overlay_info("G04", (100, 100, 180, 140), img_m4, roi_m)

    check("M4_fallback", info_m4.render_mode == RENDER_FALLBACK)

    rendered_m4 = render_overlay_to_pillow(
        img_m4, [info_m4], display_mode=OVERLAY_MODE_MASKED
    )

    check("M4_no_crash", rendered_m4.size == roi_m)

    img_m5 = _make_test_image(
        (500, 400),
        (45, 45, 45),
        [("ellipse", (60, 50, 440, 340), (248, 248, 248))],
    )

    info_m5 = _build_test_overlay_info(
        "G05", (200, 150, 300, 220), img_m5, (500, 400), short_text
    )

    img_m6 = _make_test_image(
        (300, 220),
        (45, 45, 45),
        [("ellipse", (90, 70, 210, 150), (248, 248, 248))],
    )

    info_m6 = _build_test_overlay_info(
        "G06", (120, 95, 180, 125), img_m6, (300, 220), short_text
    )

    check(
        "M6_smaller_font",
        info_m6.font_size < info_m5.font_size,
        f"{info_m6.font_size} vs {info_m5.font_size}",
    )

    img_m7 = _make_test_image(
        roi_m,
        (55, 55, 55),
        [("ellipse", (60, 40, 340, 250), (248, 248, 248))],
    )

    info_m7 = _build_test_overlay_info(
        "G07", (130, 100, 270, 180), img_m7, roi_m, long_text
    )

    check("M7_lines", info_m7.line_count >= 2, str(info_m7.line_count))

    check("M7_fits", info_m7.fits is True)

    img_m8 = img_m1.copy()

    orig_m8 = np.array(img_m8.convert("RGB"))

    info_m8 = _build_test_overlay_info("G08", ocr_m1, img_m8, roi_m, short_text)

    rendered_m8 = render_overlay_to_pillow(
        img_m8, [info_m8], display_mode=OVERLAY_MODE_MASKED
    )

    arr_m8 = np.array(rendered_m8)

    for px, py in ((8, 8), (8, roi_m[1] - 10), (roi_m[0] - 10, 8)):
        diff = int(np.max(np.abs(arr_m8[py, px].astype(int) - orig_m8[py, px].astype(int))))

        check(f"M8_outside_{px}_{py}", diff <= 8, str(diff))

    debug_m9 = render_overlay_to_pillow(
        img_m1, [info_m1], display_mode=OVERLAY_MODE_MASKED, show_debug=True
    )

    debug_path = tmp_dir / "mask_debug.png"
    debug_m9.save(debug_path)

    try:
        Image.open(debug_path).verify()

        check("M9_valid_png", True)

    except Exception as exc:
        check("M9_valid_png", False, str(exc))

    check("M9_size", debug_m9.size == roi_m)

    bubble_bbox = info_m1.overlay_bbox
    for cw, ch in ((640, 480), (900, 700)):
        cbox = roi_bbox_to_canvas_bbox(bubble_bbox, roi_m, (cw, ch), (8, 8))

        check(f"M10_{cw}x{ch}", cbox[2] > cbox[0] and cbox[3] > cbox[1])

    if errors:
        if not quiet:
            print("MASK SELF-TEST FEHLGESCHLAGEN:")

            for err in errors:
                print(f"  - {err}")

        return 1
    if not quiet:
        print("MASK SELF-TEST OK (M1–M10)")

    return 0
def run_responsive_self_test(*, quiet: bool = False) -> int:
    errors: list[str] = []
    def check(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            errors.append(f"{name}: {detail}")

    hallo = "Hallo!"
    wide_text = "Wenn alle zusammen sind, brauchen wir einen Wächter."
    long_text = "Herzlichen Glückwunsch zur erfolgreichen Vertreibung der Teufel!"
    umlaut_text = "ÄÖÜ äöü ß God's teachings!"
    fit_rsp1a = fit_translation_text_responsive(hallo, 100, 60)

    fit_rsp1b = fit_translation_text_responsive(hallo, 300, 200)

    check(
        "RSP1_larger",
        fit_rsp1b["font_size"] > fit_rsp1a["font_size"],
        f"{fit_rsp1b['font_size']} vs {fit_rsp1a['font_size']}",
    )

    fit_rsp2 = fit_translation_text_responsive(wide_text, 320, 120)

    check("RSP2_lines", fit_rsp2["line_count"] <= 4, str(fit_rsp2["line_count"]))

    if fit_rsp2["lines"]:
        avg_len = sum(len(ln) for ln in fit_rsp2["lines"]) / len(fit_rsp2["lines"])

        check("RSP2_no_tiny_lines", avg_len >= 8, str(avg_len))

        single_word_lines = sum(1 for ln in fit_rsp2["lines"] if len(ln.split()) == 1)

        check(
            "RSP2_few_single_word",
            single_word_lines <= 1,
            str(single_word_lines),
        )

    fit_rsp3 = fit_translation_text_responsive(wide_text, 90, 220)

    check("RSP3_multiline", fit_rsp3["line_count"] >= 2, str(fit_rsp3["line_count"]))

    check("RSP3_fits", fit_rsp3["fits"] is True)

    check(
        "RSP3_no_clip",
        fit_rsp3["used_height"] <= fit_rsp3["available_height"],
        str(fit_rsp3),
    )

    fit_rsp4 = fit_translation_text_responsive(long_text, 240, 140)

    check("RSP4_lines", fit_rsp4["line_count"] >= 2)

    check("RSP4_fits", fit_rsp4["fits"] is True)

    check("RSP4_font", fit_rsp4["font_size"] >= 8)

    very_long = " ".join(["Wort"] * 60)

    fit_rsp5 = fit_translation_text_responsive(very_long, 180, 90)

    check("RSP5_min_or_fits_false", fit_rsp5["font_size"] == 8 or not fit_rsp5["fits"])

    fit_rsp6 = fit_translation_text_responsive(umlaut_text, 220, 90)

    rendered_rsp6 = render_overlay_to_pillow(
        Image.new("RGB", (240, 110), (250, 250, 250)),
        [
            BubbleOverlayGroupInfo(
                group_id="G01",
                roi_bbox=(0, 0, 240, 110),
                overlay_bbox=(0, 0, 240, 110),
                render_bbox=(0, 0, 240, 110),
                text_bbox=(0, 0, 240, 110),
                display_text=umlaut_text,
                font_size=fit_rsp6["font_size"],
                lines=fit_rsp6["lines"],
                padding_x=fit_rsp6["padding_x"],
                padding_y=fit_rsp6["padding_y"],
                render_mode=RENDER_RESPONSIVE_TEXTBOX,
            )

        ],
        display_mode=OVERLAY_MODE_RESPONSIVE,
    )

    check("RSP6_render", rendered_rsp6.size == (240, 110))

    check("RSP6_fits", fit_rsp6["fits"] is True)

    pad_small = fit_translation_text_responsive(hallo, 60, 40)

    pad_large = fit_translation_text_responsive(hallo, 300, 200)

    check(
        "RSP7_padding",
        pad_small["padding_x"] <= pad_large["padding_x"]
        and pad_small["padding_y"] <= pad_large["padding_y"],
        f"{pad_small['padding_x']}/{pad_large['padding_x']}",
    )

    check(
        "RSP8_occupancy",
        fit_rsp1b["occupancy_ratio"] >= 0.25,
        str(fit_rsp1b["occupancy_ratio"]),
    )

    check(
        "RSP8_better_than_legacy",
        fit_rsp1b["font_size"] >= fit_translation_text(hallo, 300, 200).font_size,
    )

    bbox_rsp = (40, 30, 200, 150)

    for cw, ch in ((500, 400), (900, 700)):
        cbox = roi_bbox_to_canvas_bbox(bbox_rsp, (400, 300), (cw, ch), (6, 6))

        check(f"RSP9_{cw}x{ch}", cbox[2] > cbox[0] and cbox[3] > cbox[1])

    infos_rsp10 = build_overlay_groups(
        grouped=[("G01", (50, 40, 150, 100), "Hi", "Hallo!", "übersetzt", "", "")],
        roi_size=(400, 300),
        gui_display_mode=OVERLAY_MODE_RESPONSIVE,
    )

    check("RSP10_group", len(infos_rsp10) == 1)

    if infos_rsp10:
        info = infos_rsp10[0]
        check(
            "RSP10_mode",
            isinstance(info, BubbleOverlayGroupInfo)

            and info.render_mode == RENDER_RESPONSIVE_TEXTBOX,
        )

        check("RSP10_occupancy_field", info.occupancy_ratio > 0)

    if errors:
        if not quiet:
            print("RESPONSIVE SELF-TEST FEHLGESCHLAGEN:")

            for err in errors:
                print(f"  - {err}")

        return 1
    if not quiet:
        print("RESPONSIVE SELF-TEST OK (RSP1–RSP10)")

    return 0
def run_exact_bbox_self_test(*, quiet: bool = False) -> int:
    errors: list[str] = []
    def check(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            errors.append(f"{name}: {detail}")

    hallo = "Hallo!"
    wide_text = "Wenn alle zusammen sind, brauchen wir einen Wächter."
    long_text = "Herzlichen Glückwunsch zur erfolgreichen Vertreibung der Teufel!"
    umlaut_text = "ÄÖÜ äöü ß God's teachings!"
    group_bbox = (100, 100, 180, 190)

    infos_egb1 = build_overlay_groups(
        grouped=[("G01", group_bbox, "Hi", hallo, "übersetzt", "", "")],
        roi_size=(400, 300),
        gui_display_mode=OVERLAY_MODE_EXACT_GROUP,
    )

    check("EGB1_group", len(infos_egb1) == 1)

    if infos_egb1:
        info = infos_egb1[0]
        check(
            "EGB1_render_bbox",
            info.render_bbox == group_bbox,
            f"{info.render_bbox} != {group_bbox}",
        )

        check("EGB1_unchanged", info.bbox_unchanged is True)

        check("EGB1_mode", info.render_mode == RENDER_EXACT_GROUP_BBOX)

    fit_egb2 = fit_text_exact_bbox(hallo, 100, 60)

    check("EGB2_fits", fit_egb2["fits"] is True)

    check("EGB2_padding_small", fit_egb2["padding_x"] <= 4)

    fit_egb3 = fit_text_exact_bbox(hallo, 300, 200)

    check(
        "EGB3_larger_font",
        fit_egb3["font_size"] > fit_egb2["font_size"],
        f"{fit_egb3['font_size']} vs {fit_egb2['font_size']}",
    )

    fit_egb4 = fit_text_exact_bbox(wide_text, 320, 120)

    check("EGB4_lines", fit_egb4["line_count"] <= 4, str(fit_egb4["line_count"]))

    if fit_egb4["lines"]:
        single_word_lines = sum(1 for ln in fit_egb4["lines"] if len(ln.split()) == 1)

        check("EGB4_few_single_word", single_word_lines <= 1, str(single_word_lines))

    fit_egb5 = fit_text_exact_bbox(wide_text, 90, 220)

    check("EGB5_multiline", fit_egb5["line_count"] >= 2)

    check(
        "EGB5_no_clip",
        fit_egb5["used_height"] <= fit_egb5["available_height"],
    )

    fit_egb6 = fit_text_exact_bbox(long_text, 240, 140)

    check("EGB6_lines", fit_egb6["line_count"] >= 2)

    check("EGB6_no_crash", fit_egb6["font_size"] >= EXACT_MIN_FONT_SIZE)

    very_long = " ".join(["Wort"] * 80)

    fit_egb7 = fit_text_exact_bbox(very_long, 80, 40)

    check("EGB7_fits_false", fit_egb7["fits"] is False)

    check("EGB7_overflow", fit_egb7["overflow_reason"] is not None)

    fit_egb8 = fit_text_exact_bbox(umlaut_text, 220, 90)

    check("EGB8_fits", fit_egb8["fits"] is True)

    check(
        "EGB8_no_clip",
        fit_egb8["used_height"] <= fit_egb8["available_height"],
    )

    box_a = (20, 40, 120, 100)

    box_b = (140, 45, 240, 105)

    infos_egb9 = build_overlay_groups(
        grouped=[
            ("G01", box_a, "A", "Alpha", "übersetzt", "", ""),
            ("G02", box_b, "B", "Beta", "übersetzt", "", ""),
        ],
        roi_size=(300, 200),
        gui_display_mode=OVERLAY_MODE_EXACT_GROUP,
    )

    check("EGB9_two", len(infos_egb9) == 2)

    if len(infos_egb9) == 2:
        check("EGB9_a_bbox", infos_egb9[0].render_bbox == box_a)

        check("EGB9_b_bbox", infos_egb9[1].render_bbox == box_b)

        check("EGB9_no_expand_a", infos_egb9[0].overlay_bbox == box_a)

        check("EGB9_no_expand_b", infos_egb9[1].overlay_bbox == box_b)

    grouped_one = [("G01", (50, 40, 200, 150), "Hi", wide_text, "übersetzt", "", "")]
    infos_small_canvas = build_overlay_groups(
        grouped=grouped_one,
        roi_size=(400, 300),
        canvas_size=(500, 400),
        canvas_offset=(10, 10),
        gui_display_mode=OVERLAY_MODE_EXACT_GROUP,
    )

    infos_large_canvas = build_overlay_groups(
        grouped=grouped_one,
        roi_size=(400, 300),
        canvas_size=(900, 700),
        canvas_offset=(20, 15),
        gui_display_mode=OVERLAY_MODE_EXACT_GROUP,
    )

    if infos_small_canvas and infos_large_canvas:
        s, l = infos_small_canvas[0], infos_large_canvas[0]
        check("EGB10_font_stable", s.font_size == l.font_size)

        check("EGB10_lines_stable", s.lines == l.lines)

        check("EGB10_bbox_stable", s.render_bbox == l.render_bbox)

        check(
            "EGB10_canvas_differs",
            s.canvas_bbox != l.canvas_bbox or s.canvas_bbox == (0, 0, 0, 0),
        )

    infos_default = build_overlay_groups(
        grouped=[("G01", (60, 50, 160, 120), "Hi", hallo, "übersetzt", "", "")],
        roi_size=(400, 300),
    )

    check("EGB11_default_mode", len(infos_default) == 1)

    if infos_default:
        check(
            "EGB11_exact",
            infos_default[0].render_mode == RENDER_EXACT_GROUP_BBOX,
        )

    if errors:
        if not quiet:
            print("EXACT-BBOX SELF-TEST FEHLGESCHLAGEN:")

            for err in errors:
                print(f"  - {err}")

        return 1
    if not quiet:
        print("EXACT-BBOX SELF-TEST OK (EGB1–EGB11)")

    return 0
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--bubble-self-test":
        raise SystemExit(run_bubble_self_test())

    if len(sys.argv) > 1 and sys.argv[1] == "--mask-self-test":
        raise SystemExit(run_mask_self_test())

    if len(sys.argv) > 1 and sys.argv[1] == "--responsive-self-test":
        raise SystemExit(run_responsive_self_test())

    if len(sys.argv) > 1 and sys.argv[1] == "--exact-bbox-self-test":
        raise SystemExit(run_exact_bbox_self_test())

    raise SystemExit(run_self_test())
