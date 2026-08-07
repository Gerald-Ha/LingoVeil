#!/usr/bin/env python3
from __future__ import annotations
import io
import json
import os
import re
import sys
import threading
import time
import traceback

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import numpy as np

os.environ.setdefault("TQDM_DISABLE", "1")

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import gi

gi.require_version("Gst", "1.0")

from gi.repository import GLib, Gst
import tkinter as tk

from tkinter import ttk
from PIL import Image, ImageDraw, ImageFont
from portal_screencast import PortalScreenCast
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "selected_region.json"
ROI_LATEST_PATH = PROJECT_ROOT / "artifacts" / "grouped_ocr_roi_latest.png"
ROI_ANNOTATED_PATH = PROJECT_ROOT / "artifacts" / "grouped_ocr_roi_annotated.png"
OCR_CHECK_INTERVAL_SEC = 1.0
OCR_MAX_INTERVAL_SEC = 10.0
CHANGE_THRESHOLD_PCT = 2.5
COMPARE_SIZE = (160, 120)

MIN_ROI_SIZE = 20
FRAME_TIMEOUT_SEC = 15
UI_REFRESH_MS = 33
MIN_CONFIDENCE = 0.30
MIN_LATIN_LETTER_COUNT = 2
MIN_LATIN_RATIO = 0.55
MAX_SINGLE_BOX_AREA_RATIO = 0.22
SHORT_WORD_ALLOWLIST = frozenset({
    "I", "A", "NO", "GO", "TO", "OK", "AM", "AN", "AS", "AT", "BE", "BY",
    "DO", "HE", "IF", "IN", "IS", "IT", "ME", "MY", "OF", "ON", "OR", "SO",
    "UP", "US", "WE", "OH", "AH", "EH", "UM", "HI", "BYE",
})

GROUP_MAX_VERTICAL_GAP_FACTOR = 2.5
GROUP_MIN_HORIZONTAL_OVERLAP_RATIO = 0.15
GROUP_MAX_CENTER_X_DISTANCE_FACTOR = 3.5
GROUP_SAME_ROW_Y_TOLERANCE_FACTOR = 0.6
GROUP_ANNOTATION_COLOR = "#ff2222"
GROUP_LABEL_FONT_SIZE = 42
GROUP_LABEL_GAP_ABOVE_BOX = 2
def group_label_anchor_y(box_top: float) -> int:
    pass
    return max(0, int(box_top) - GROUP_LABEL_GAP_ABOVE_BOX)

RECOVERY_MIN_CONFIDENCE = 0.18
RECOVERY_MAX_VERTICAL_GAP_FACTOR = 3.0
WINDOW_DEFAULT_GEOMETRY = "1450x950"
WINDOW_MIN_WIDTH = 1050
WINDOW_MIN_HEIGHT = 750
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")

NON_LATIN_RE = re.compile(r"[^A-Za-z0-9\s'!?.,;:\-]")

PURE_NUMBER_RE = re.compile(r"^\d+$")

PUNCT_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)

@dataclass
class FrameData:
    image: Image.Image
    width: int
    height: int
@dataclass
class RoiRect:
    x: int
    y: int
    width: int
    height: int
@dataclass
class RawOcrBlock:
    bbox: list[list[float]]
    text: str
    normalized_text: str
    confidence: float
    width: float
    height: float
    area: float
    area_ratio: float
    center_x: float
    center_y: float
    timestamp: str
    run_number: int
    rect: tuple[float, float, float, float] = field(repr=False)

@dataclass
class FilterDecision:
    accepted: bool
    reason: str
@dataclass
class RejectedBlock:
    raw: RawOcrBlock
    reason: str
@dataclass
class GroupedTextBlock:
    id: int
    bbox: tuple[float, float, float, float]
    text: str
    lines: list[RawOcrBlock]
    average_confidence: float
    min_confidence: float
    ocr_run: int
@dataclass
class GroupingResult:
    raw_blocks: list[RawOcrBlock]
    accepted: list[RawOcrBlock]
    rejected: list[RejectedBlock]
    groups: list[GroupedTextBlock]
    run_number: int
    duration_sec: float
    roi_image: Image.Image
_stdout_guard = threading.RLock()

@contextmanager
def _suppress_stdout():
    pass
    with _stdout_guard:
        devnull = open(os.devnull, "w")

        old_stdout = sys.stdout
        sys.stdout = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout
            devnull.close()

def normalize_ocr_text(text: str) -> str:
    text = text.strip()

    text = re.sub(r"\s+", " ", text)

    return text
def _bbox_rect(bbox: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return min(xs), min(ys), max(xs), max(ys)

def _latin_letter_count(text: str) -> int:
    return len(LATIN_LETTER_RE.findall(text))

def _latin_ratio(text: str) -> float:
    if not text:
        return 0.0
    letters = _latin_letter_count(text)

    return letters / len(text)

def filter_english_candidate(
    text: str,
    confidence: float,
    area_ratio: float,
    *,
    min_confidence: float = MIN_CONFIDENCE,
    min_latin_count: int = MIN_LATIN_LETTER_COUNT,
    min_latin_ratio: float = MIN_LATIN_RATIO,
    max_area_ratio: float = MAX_SINGLE_BOX_AREA_RATIO,
) -> FilterDecision:
    normalized = normalize_ocr_text(text)

    upper = normalized.upper()

    if not normalized:
        return FilterDecision(False, "leerer Text")

    if upper in SHORT_WORD_ALLOWLIST:
        if confidence < min_confidence:
            return FilterDecision(False, f"Confidence unter {min_confidence}")

        return FilterDecision(True, "Allowlist kurzes englisches Wort")

    latin_count = _latin_letter_count(normalized)

    if latin_count == 0:
        return FilterDecision(False, "keine lateinischen Buchstaben")

    if PURE_NUMBER_RE.match(normalized):
        return FilterDecision(False, "reine Zahlen")

    if PUNCT_ONLY_RE.match(normalized):
        return FilterDecision(False, "ausschließlich Sonderzeichen")

    if confidence < min_confidence:
        return FilterDecision(False, f"Confidence unter {min_confidence}")

    if len(normalized) == 1 and normalized not in {"'", "-"}:
        return FilterDecision(False, "einzelnes unbrauchbares Zeichen")

    if area_ratio > max_area_ratio and latin_count < 6:
        return FilterDecision(
            False,
            f"sehr große Textbox ({area_ratio:.1%} des ROI) – vermutlich Sound-Effect",
        )

    ratio = _latin_ratio(normalized)

    if latin_count < min_latin_count and ratio < min_latin_ratio:
        return FilterDecision(
            False,
            f"zu wenig lateinische Buchstaben ({latin_count}, Anteil {ratio:.0%})",
        )

    if ratio < min_latin_ratio:
        return FilterDecision(
            False,
            f"lateinischer Buchstabenanteil unter {min_latin_ratio:.0%}",
        )

    return FilterDecision(True, "englischer Kandidat")

def _horizontal_overlap_ratio(
    rect_a: tuple[float, float, float, float],
    rect_b: tuple[float, float, float, float],
) -> float:
    ax1, _, ax2, _ = rect_a
    bx1, _, bx2, _ = rect_b
    overlap = max(0.0, min(ax2, bx2) - max(ax1, bx1))

    min_width = min(ax2 - ax1, bx2 - bx1)

    if min_width <= 0:
        return 0.0
    return overlap / min_width
def _can_group_lines(a: RawOcrBlock, b: RawOcrBlock) -> bool:
    ar, br = a.rect, b.rect
    avg_h = (a.height + b.height) / 2.0
    if avg_h <= 0:
        return False
    a_cy = (ar[1] + ar[3]) / 2.0
    b_cy = (br[1] + br[3]) / 2.0
    y_diff = abs(a_cy - b_cy)

    if y_diff <= avg_h * GROUP_SAME_ROW_Y_TOLERANCE_FACTOR:
        gap = br[0] - ar[2]
        if gap > avg_h * GROUP_MAX_CENTER_X_DISTANCE_FACTOR:
            return False
        overlap = _horizontal_overlap_ratio(ar, br)

        center_dist = abs(a.center_x - b.center_x)

        return overlap >= GROUP_MIN_HORIZONTAL_OVERLAP_RATIO or (
            center_dist <= avg_h * GROUP_MAX_CENTER_X_DISTANCE_FACTOR
        )

    upper, lower = (a, b) if ar[1] <= br[1] else (b, a)

    ur, lr = upper.rect, lower.rect
    vertical_gap = lr[1] - ur[3]
    if vertical_gap > avg_h * GROUP_MAX_VERTICAL_GAP_FACTOR:
        return False
    if vertical_gap < -avg_h * 0.35:
        return False
    overlap = _horizontal_overlap_ratio(ur, lr)

    center_dist = abs(upper.center_x - lower.center_x)

    if overlap >= GROUP_MIN_HORIZONTAL_OVERLAP_RATIO:
        return True
    return center_dist <= avg_h * GROUP_MAX_CENTER_X_DISTANCE_FACTOR
def _sort_blocks_for_grouping(blocks: list[RawOcrBlock]) -> list[RawOcrBlock]:
    return sorted(blocks, key=lambda b: (b.rect[1], b.center_x))

def _vertical_gap_between(
    rect_a: tuple[float, float, float, float],
    rect_b: tuple[float, float, float, float],
) -> float:
    if rect_a[3] < rect_b[1]:
        return rect_b[1] - rect_a[3]
    if rect_b[3] < rect_a[1]:
        return rect_a[1] - rect_b[3]
    return 0.0
def _is_vertically_nearby_line(a: RawOcrBlock, b: RawOcrBlock) -> bool:
    ar, br = a.rect, b.rect
    avg_h = (a.height + b.height) / 2.0
    if avg_h <= 0:
        return False
    gap = _vertical_gap_between(ar, br)

    if gap > avg_h * RECOVERY_MAX_VERTICAL_GAP_FACTOR:
        return False
    overlap = _horizontal_overlap_ratio(ar, br)

    center_dist = abs(a.center_x - b.center_x)

    return overlap >= GROUP_MIN_HORIZONTAL_OVERLAP_RATIO or (
        center_dist <= avg_h * GROUP_MAX_CENTER_X_DISTANCE_FACTOR
    )

def recover_adjacent_rejected_blocks(
    accepted: list[RawOcrBlock],
    rejected: list[RejectedBlock],
) -> tuple[list[RawOcrBlock], list[RejectedBlock]]:
    pass
    recovered: list[RawOcrBlock] = []
    still_rejected: list[RejectedBlock] = []
    known = list(accepted)

    for item in rejected:
        block = item.raw
        if block.confidence < RECOVERY_MIN_CONFIDENCE:
            still_rejected.append(item)

            continue
        if "Confidence unter" not in item.reason:
            still_rejected.append(item)

            continue
        if _latin_letter_count(block.normalized_text) < MIN_LATIN_LETTER_COUNT:
            still_rejected.append(item)

            continue
        if any(_is_vertically_nearby_line(block, neighbor) for neighbor in known):
            recovered.append(block)

            known.append(block)

        else:
            still_rejected.append(item)

    if recovered:
        accepted = accepted + recovered
    return accepted, still_rejected
def _join_group_lines(lines: list[RawOcrBlock]) -> str:
    ordered = sorted(lines, key=lambda b: (b.rect[1], b.center_x))

    parts: list[str] = []
    for block in ordered:
        text = block.normalized_text
        if not text:
            continue
        if parts and parts[-1].endswith("-"):
            parts[-1] = parts[-1][:-1] + text
        elif parts:
            parts.append(text)

        else:
            parts.append(text)

    return " ".join(parts)

def _union_rect(rects: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    )

def group_english_lines(blocks: list[RawOcrBlock], ocr_run: int) -> list[GroupedTextBlock]:
    if not blocks:
        return []
    sorted_blocks = _sort_blocks_for_grouping(blocks)

    groups: list[list[RawOcrBlock]] = []
    for block in sorted_blocks:
        placed = False
        for group in groups:
            if any(_can_group_lines(member, block) for member in group):
                group.append(block)

                placed = True
                break
        if not placed:
            groups.append([block])

    changed = True
    while changed and len(groups) > 1:
        changed = False
        merged: list[list[RawOcrBlock]] = []
        used = [False] * len(groups)

        for i, ga in enumerate(groups):
            if used[i]:
                continue
            current = list(ga)

            used[i] = True
            for j in range(i + 1, len(groups)):
                if used[j]:
                    continue
                if any(
                    _can_group_lines(a, b) for a in current for b in groups[j]
                ):
                    current.extend(groups[j])

                    used[j] = True
                    changed = True
            merged.append(current)

        groups = merged
    result: list[GroupedTextBlock] = []
    for idx, group_lines in enumerate(groups, start=1):
        rects = [line.rect for line in group_lines]
        confidences = [line.confidence for line in group_lines]
        result.append(
            GroupedTextBlock(
                id=idx,
                bbox=_union_rect(rects),
                text=_join_group_lines(group_lines),
                lines=sorted(group_lines, key=lambda b: (b.rect[1], b.center_x)),
                average_confidence=sum(confidences) / len(confidences),
                min_confidence=min(confidences),
                ocr_run=ocr_run,
            )

        )

    result.sort(key=lambda g: (g.bbox[1], g.bbox[0]))

    for i, group in enumerate(result, start=1):
        group.id = i
    return result
def process_ocr_raw(
    raw_entries: list[tuple[Any, str, float]],
    roi_width: int,
    roi_height: int,
    run_number: int,
    timestamp: str,
) -> tuple[list[RawOcrBlock], list[RawOcrBlock], list[RejectedBlock]]:
    roi_area = float(roi_width * roi_height)

    raw_blocks: list[RawOcrBlock] = []
    for entry in raw_entries:
        bbox, text, confidence = entry
        bbox_pts = [[float(p[0]), float(p[1])] for p in bbox]
        rect = _bbox_rect(bbox_pts)

        w = rect[2] - rect[0]
        h = rect[3] - rect[1]
        area = w * h
        normalized = normalize_ocr_text(str(text))

        raw_blocks.append(
            RawOcrBlock(
                bbox=bbox_pts,
                text=str(text).strip(),
                normalized_text=normalized,
                confidence=float(confidence),
                width=w,
                height=h,
                area=area,
                area_ratio=area / roi_area if roi_area > 0 else 0.0,
                center_x=(rect[0] + rect[2]) / 2.0,
                center_y=(rect[1] + rect[3]) / 2.0,
                timestamp=timestamp,
                run_number=run_number,
                rect=rect,
            )

        )

    accepted: list[RawOcrBlock] = []
    rejected: list[RejectedBlock] = []
    for block in raw_blocks:
        decision = filter_english_candidate(
            block.text,
            block.confidence,
            block.area_ratio,
        )

        if decision.accepted:
            accepted.append(block)

        else:
            rejected.append(RejectedBlock(raw=block, reason=decision.reason))

    accepted, rejected = recover_adjacent_rejected_blocks(accepted, rejected)

    return raw_blocks, accepted, rejected
class EasyOcrEngine:
    def __init__(self, log_fn) -> None:
        self.log = log_fn
        self.reader: Any = None
        self.error: Exception | None = None
        self.ready = threading.Event()

        self._thread = threading.Thread(target=self._init_reader, daemon=True)

        self._thread.start()

    def _init_reader(self) -> None:
        try:
            self.log("EasyOCR wird initialisiert (gpu=False, Sprache: en) …")

            with _suppress_stdout():
                import easyocr

                self.reader = easyocr.Reader(["en"], gpu=False, verbose=False)

            self.log("EasyOCR-Reader bereit.")

            self.ready.set()

        except Exception as exc:
            self.error = exc
            self.log(f"EasyOCR-Initialisierung fehlgeschlagen: {exc}")

            traceback.print_exc()

            self.ready.set()

    def wait_ready(self, timeout_sec: float = 300) -> bool:
        return self.ready.wait(timeout=timeout_sec)

    def run_ocr(self, roi_image: Image.Image) -> list[tuple[Any, str, float]]:
        if self.reader is None:
            raise RuntimeError("EasyOCR-Reader nicht verfügbar.")

        rgb = np.array(roi_image.convert("RGB"))

        with _suppress_stdout():
            return self.reader.readtext(rgb, detail=1, paragraph=False)

class RoiOcrGroupingTest:
    def __init__(self) -> None:
        self.portal = PortalScreenCast(log_prefix="[LingoVeil-Group]")

        self.ocr_engine = EasyOcrEngine(self.log)

        self.pipeline: Gst.Pipeline | None = None
        self.appsink: Gst.Element | None = None
        self.frame_lock = threading.Lock()

        self.latest_frame: FrameData | None = None
        self.frame_count = 0
        self.node_id: int | None = None
        self.pipewire_fd: int | None = None
        self.portal_size: tuple[int, int] | None = None
        self.source_label = "unbekannt"
        self.frame_roi: RoiRect | None = None
        self.state = "initialisiert"
        self.root: tk.Tk | None = None
        self.status_var: tk.StringVar | None = None
        self.groups_text: tk.Text | None = None
        self.rejected_text: tk.Text | None = None
        self.preview_canvas: tk.Canvas | None = None
        self.preview_photo: tk.PhotoImage | None = None
        self.preview_display_size = (0, 0)

        self.compare_reference: Image.Image | None = None
        self.last_change_pct = 0.0
        self.last_ocr_check_time = 0.0
        self.last_ocr_time: float | None = None
        self.ocr_run_number = 0
        self.last_ocr_duration = 0.0
        self.skip_reason = "–"
        self.ocr_active = False
        self.raw_blocks: list[RawOcrBlock] = []
        self.accepted_blocks: list[RawOcrBlock] = []
        self.rejected_blocks: list[RejectedBlock] = []
        self.grouped_blocks: list[GroupedTextBlock] = []
        self.ocr_worker_thread: threading.Thread | None = None
        self.ocr_request_lock = threading.Lock()

        self.ocr_pending_image: Image.Image | None = None
        self.ocr_shutdown = False
        self.shutting_down = False
        self.success = False
    def log(self, message: str) -> None:
        print(f"[LingoVeil-Group] {message}", flush=True)

    @staticmethod
    def _pil_to_photo(image: Image.Image) -> tk.PhotoImage:
        buffer = io.BytesIO()

        image.save(buffer, format="PNG")

        return tk.PhotoImage(data=buffer.getvalue())

    def setup_portal(self) -> None:
        self.log("[1/7] Portal-Session erstellen")

        self.log("[2/7] Monitor auswählen – GNOME-Portal-Dialog erscheint")

        fd, node_id, stream_info = self.portal.setup()

        self.pipewire_fd = fd
        self.node_id = node_id
        self.log(f"PipeWire-Node-ID: {node_id}")

        props = stream_info.get("properties", {})

        size = props.get("size")

        if size is not None:
            self.portal_size = (int(size[0]), int(size[1]))

            self.log(f"Portal-/Compositor-Größe: {self.portal_size[0]}×{self.portal_size[1]}")

        source_type = props.get("source_type")

        if source_type is not None:
            source_map = {1: "MONITOR", 2: "WINDOW", 4: "VIRTUAL"}

            self.source_label = source_map.get(int(source_type), str(source_type))

    def _sample_to_image(self, sample: Gst.Sample) -> FrameData | None:
        buffer = sample.get_buffer()

        if buffer is None:
            return None
        caps = sample.get_caps()

        if caps is None:
            return None
        structure = caps.get_structure(0)

        width = structure.get_value("width")

        height = structure.get_value("height")

        if not width or not height:
            return None
        success, map_info = buffer.map(Gst.MapFlags.READ)

        if not success:
            return None
        try:
            data = bytes(map_info.data)

        finally:
            buffer.unmap(map_info)

        fmt = structure.get_value("format")

        if fmt == "BGRA":
            image = Image.frombytes("RGBA", (width, height), data, "raw", "BGRA")

        elif fmt == "RGBA":
            image = Image.frombytes("RGBA", (width, height), data)

        else:
            image = Image.frombytes("RGB", (width, height), data)

        return FrameData(image=image.convert("RGBA"), width=width, height=height)

    def _on_new_sample(self, sink: Gst.Element) -> Gst.FlowReturn:
        if self.shutting_down:
            return Gst.FlowReturn.EOS
        sample = sink.emit("pull-sample")

        if sample is None:
            return Gst.FlowReturn.OK
        frame = self._sample_to_image(sample)

        if frame is None:
            return Gst.FlowReturn.OK
        with self.frame_lock:
            self.latest_frame = frame
            self.frame_count += 1
        return Gst.FlowReturn.OK
    def start_pipeline(self) -> None:
        self.log("[3/7] PipeWire-Stream öffnen")

        self.log("[4/7] GStreamer-Pipeline starten")

        pipeline_desc = (
            f"pipewiresrc fd={self.pipewire_fd} path={self.node_id} do-timestamp=true "
            "! videoconvert ! video/x-raw,format=RGBA "
            "! appsink name=sink emit-signals=true sync=false max-buffers=1 drop=true"
        )

        self.pipeline = Gst.parse_launch(pipeline_desc)

        self.appsink = self.pipeline.get_by_name("sink")

        self.appsink.connect("new-sample", self._on_new_sample)

        self.pipeline.set_state(Gst.State.PLAYING)

        bus = self.pipeline.get_bus()

        bus.add_signal_watch()

        bus.connect("message::error", self._on_bus_error)

    def _on_bus_error(self, bus: Gst.Bus, message: Gst.Message) -> None:
        err, debug = message.parse_error()

        self.log(f"GStreamer-Fehler: {err.message} ({debug})")

        if self.root is not None:
            self.root.after(0, self.shutdown)

    def _wait_for_first_frame(self) -> FrameData:
        self.log("[5/7] Warte auf ersten Frame")

        deadline = time.monotonic() + FRAME_TIMEOUT_SEC
        while time.monotonic() < deadline:
            with self.frame_lock:
                if self.latest_frame is not None:
                    frame = self.latest_frame
                    self.log(f"Tatsächliche Frame-Größe: {frame.width}×{frame.height}")

                    return frame
            time.sleep(0.05)

        raise TimeoutError("Kein Frame empfangen.")

    def _load_saved_roi(self, frame: FrameData) -> RoiRect | None:
        self.log("Prüfe gespeicherten ROI …")

        if not CONFIG_PATH.exists():
            self.log(f"Keine ROI-Konfiguration: {CONFIG_PATH}")

            return None
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)

        except json.JSONDecodeError as exc:
            self.log(f"ROI ungültig: JSON-Fehler ({exc})")

            return None
        if data.get("version") != 1:
            self.log(f"ROI ungültig: version={data.get('version')}")

            return None
        try:
            if int(data["frame_width"]) != frame.width or int(data["frame_height"]) != frame.height:
                self.log(
                    "ROI ungültig: Frame-Größe "
                    f"{data['frame_width']}×{data['frame_height']} != {frame.width}×{frame.height}"
                )

                return None
            roi = RoiRect(
                int(data["x"]), int(data["y"]),
                int(data["width"]), int(data["height"]),
            )

        except (KeyError, TypeError, ValueError) as exc:
            self.log(f"ROI ungültig: Felder ({exc})")

            return None
        if roi.width < MIN_ROI_SIZE or roi.height < MIN_ROI_SIZE:
            self.log(f"ROI ungültig: zu klein ({roi.width}×{roi.height})")

            return None
        if roi.x < 0 or roi.y < 0 or roi.x + roi.width > frame.width or roi.y + roi.height > frame.height:
            self.log("ROI ungültig: außerhalb des Frames")

            return None
        self.log("Gespeicherter ROI wurde geladen")

        self.log(f"ROI: x={roi.x}, y={roi.y}, width={roi.width}, height={roi.height}")

        return roi
    def _extract_roi_crop(self, frame: FrameData, roi: RoiRect) -> Image.Image:
        return frame.image.crop(
            (roi.x, roi.y, roi.x + roi.width, roi.y + roi.height)

        ).copy()

    def _compute_change_pct(self, current: Image.Image) -> float:
        if self.compare_reference is None:
            return 100.0
        cur = np.array(current.resize(COMPARE_SIZE).convert("L"), dtype=np.int16)

        ref = np.array(self.compare_reference.resize(COMPARE_SIZE).convert("L"), dtype=np.int16)

        return float(np.abs(cur - ref).mean()) / 255.0 * 100.0
    def _should_run_ocr(self, change_pct: float, now: float) -> tuple[bool, str]:
        if self.last_ocr_time is None:
            return True, "erster OCR-Lauf"
        if change_pct >= CHANGE_THRESHOLD_PCT:
            return True, f"Änderung {change_pct:.2f}% >= {CHANGE_THRESHOLD_PCT}%"
        if now - self.last_ocr_time >= OCR_MAX_INTERVAL_SEC:
            return True, f"Maximalintervall {OCR_MAX_INTERVAL_SEC}s"
        return False, f"keine ausreichende Änderung ({change_pct:.2f}%)"
    def _request_ocr(self, roi_image: Image.Image) -> None:
        with self.ocr_request_lock:
            self.ocr_pending_image = roi_image.copy()

    def _ocr_worker(self) -> None:
        while not self.ocr_shutdown:
            image: Image.Image | None = None
            with self.ocr_request_lock:
                if self.ocr_pending_image is not None:
                    image = self.ocr_pending_image
                    self.ocr_pending_image = None
            if image is None:
                time.sleep(0.05)

                continue
            if not self.ocr_engine.ready.wait(timeout=0.1):
                with self.ocr_request_lock:
                    self.ocr_pending_image = image
                continue
            if self.ocr_engine.error or self.ocr_engine.reader is None:
                if self.root is not None:
                    self.root.after(0, lambda: self._set_skip_reason("OCR-Engine nicht bereit"))

                continue
            self.ocr_active = True
            if self.root is not None:
                self.root.after(0, self._update_status_only)

            start = time.monotonic()

            try:
                raw = self.ocr_engine.run_ocr(image)

            except Exception as exc:
                self.log(f"OCR-Fehler: {exc}")

                traceback.print_exc()

                self.ocr_active = False
                if self.root is not None:
                    self.root.after(0, lambda: self._set_skip_reason(f"OCR-Fehler: {exc}"))

                continue
            duration = time.monotonic() - start
            self.ocr_run_number += 1
            run_no = self.ocr_run_number
            timestamp = datetime.now(timezone.utc).isoformat()

            raw_blocks, accepted, rejected = process_ocr_raw(
                raw, image.width, image.height, run_no, timestamp
            )

            groups = group_english_lines(accepted, run_no)

            result = GroupingResult(
                raw_blocks=raw_blocks,
                accepted=accepted,
                rejected=rejected,
                groups=groups,
                run_number=run_no,
                duration_sec=duration,
                roi_image=image,
            )

            self.ocr_active = False
            if self.root is not None:
                self.root.after(0, lambda r=result: self._apply_grouping_result(r))

    def _set_skip_reason(self, reason: str) -> None:
        self.skip_reason = reason
        self._update_status_only()

    def _log_grouping_result(self, result: GroupingResult) -> None:
        self.log(f"OCR-Lauf {result.run_number}:")

        self.log(f"  Rohblöcke:          {len(result.raw_blocks)}")

        self.log(f"  akzeptiert:         {len(result.accepted)}")

        self.log(f"  verworfen:          {len(result.rejected)}")

        self.log(f"  Gruppen:            {len(result.groups)}")

        self.log(f"  OCR-Dauer:          {result.duration_sec:.2f} s")

        for item in result.rejected:
            self.log(
                f"  Verworfen: \"{item.raw.text}\" "
                f"(Conf {item.raw.confidence:.2f}) – {item.reason}"
            )

        for group in result.groups:
            line_texts = [ln.normalized_text for ln in group.lines]
            self.log(
                f"  Gruppe {group.id:02d}: bbox={tuple(round(v) for v in group.bbox)} "
                f"Ø {group.average_confidence:.2f}"
            )

            self.log(f"    Zeilen: {line_texts}")

            self.log(f"    Text: {group.text}")

    def _apply_grouping_result(self, result: GroupingResult) -> None:
        self.raw_blocks = result.raw_blocks
        self.accepted_blocks = result.accepted
        self.rejected_blocks = result.rejected
        self.grouped_blocks = result.groups
        self.last_ocr_duration = result.duration_sec
        self.last_ocr_time = time.monotonic()

        self.compare_reference = result.roi_image.copy()

        self.skip_reason = "–"
        self._log_grouping_result(result)

        self._save_grouped_images(result.roi_image, result.groups, result.accepted, result.rejected)

        self._refresh_result_panels()

        self._update_status_only()

    def _save_grouped_images(
        self,
        roi_image: Image.Image,
        groups: list[GroupedTextBlock],
        accepted: list[RawOcrBlock],
        rejected: list[RejectedBlock],
    ) -> None:
        ROI_LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)

        roi_image.save(ROI_LATEST_PATH)

        annotated = roi_image.copy()

        draw = ImageDraw.Draw(annotated)

        try:
            font = ImageFont.truetype("DejaVuSans.ttf", GROUP_LABEL_FONT_SIZE)

        except OSError:
            font = ImageFont.load_default()

        for block in accepted:
            draw.polygon(
                [(p[0], p[1]) for p in block.bbox],
                outline="#607d8b",
                width=1,
            )

        for item in rejected:
            draw.polygon(
                [(p[0], p[1]) for p in item.raw.bbox],
                outline="#ff5252",
                width=1,
            )

        for group in groups:
            x1, y1, x2, y2 = group.bbox
            draw.rectangle(
                [x1, y1, x2, y2], outline=GROUP_ANNOTATION_COLOR, width=3
            )

            draw.text(
                (x1, group_label_anchor_y(y1)),
                f"G{group.id:02d}",
                fill=GROUP_ANNOTATION_COLOR,
                font=font,
                anchor="lb",
            )

        annotated.save(ROI_ANNOTATED_PATH)

        self.log(f"Gespeichert: {ROI_LATEST_PATH}")

        self.log(f"Gespeichert: {ROI_ANNOTATED_PATH}")

    def _fit_image_to_canvas(
        self, image: Image.Image, canvas_width: int, canvas_height: int
    ) -> tuple[Image.Image, float, int, int]:
        if canvas_width < 2 or canvas_height < 2:
            return image, 1.0, 0, 0
        scale = min(canvas_width / image.width, canvas_height / image.height)

        display_w = max(1, int(round(image.width * scale)))

        display_h = max(1, int(round(image.height * scale)))

        resized = image.resize((display_w, display_h), Image.Resampling.BILINEAR)

        offset_x = (canvas_width - display_w) // 2
        offset_y = (canvas_height - display_h) // 2
        return resized, scale, offset_x, offset_y
    def _draw_preview(self, roi_image: Image.Image) -> Image.Image:
        preview = roi_image.copy()

        draw = ImageDraw.Draw(preview)

        line_w = max(1, int(preview.width / 500))

        bold_w = max(2, int(preview.width / 350))

        label_size = max(20, int(GROUP_LABEL_FONT_SIZE * preview.width / 900))

        try:
            font = ImageFont.truetype("DejaVuSans.ttf", label_size)

        except OSError:
            font = ImageFont.load_default()

        for block in self.accepted_blocks:
            draw.polygon(
                [(p[0], p[1]) for p in block.bbox],
                outline="#78909c",
                width=line_w,
            )

        for item in self.rejected_blocks:
            draw.polygon(
                [(p[0], p[1]) for p in item.raw.bbox],
                outline="#ef5350",
                width=line_w,
            )

        for group in self.grouped_blocks:
            x1, y1, x2, y2 = group.bbox
            draw.rectangle(
                [x1, y1, x2, y2], outline=GROUP_ANNOTATION_COLOR, width=bold_w
            )

            draw.text(
                (x1, group_label_anchor_y(y1)),
                f"G{group.id:02d}",
                fill=GROUP_ANNOTATION_COLOR,
                font=font,
                anchor="lb",
            )

        return preview
    def _build_ui(self) -> None:
        self.log("[6/7] Gruppierungs-Kontrollfenster öffnen")

        self.state = "Filter/Gruppierung aktiv"
        self.root = tk.Tk()

        self.root.title("LingoVeil – OCR-Gruppierungstest")

        self.root.geometry(WINDOW_DEFAULT_GEOMETRY)

        self.root.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

        self.status_var = tk.StringVar(value="Initialisiere …")

        tk.Label(self.root, textvariable=self.status_var, anchor="w", justify="left").pack(
            fill="x", padx=10, pady=8
        )

        paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashwidth=6)

        paned.pack(fill="both", expand=True, padx=10, pady=4)

        preview_frame = tk.LabelFrame(
            paned, text="ROI-Live-Vorschau (grau=Zeilen, rot=verworfen, grün=Gruppen)"
        )

        self.preview_canvas = tk.Canvas(preview_frame, bg="#202020", highlightthickness=0)

        self.preview_canvas.pack(fill="both", expand=True)

        paned.add(preview_frame, stretch="always")

        right_frame = tk.Frame(paned)

        notebook = ttk.Notebook(right_frame)

        notebook.pack(fill="both", expand=True)

        groups_tab = tk.Frame(notebook)

        self.groups_text = tk.Text(groups_tab, wrap="word", width=48, height=24)

        g_scroll = tk.Scrollbar(groups_tab, command=self.groups_text.yview)

        self.groups_text.configure(yscrollcommand=g_scroll.set)

        self.groups_text.pack(side="left", fill="both", expand=True)

        g_scroll.pack(side="right", fill="y")

        notebook.add(groups_tab, text="Gruppierte Blöcke")

        rejected_tab = tk.Frame(notebook)

        self.rejected_text = tk.Text(rejected_tab, wrap="word", width=48, height=24)

        r_scroll = tk.Scrollbar(rejected_tab, command=self.rejected_text.yview)

        self.rejected_text.configure(yscrollcommand=r_scroll.set)

        self.rejected_text.pack(side="left", fill="both", expand=True)

        r_scroll.pack(side="right", fill="y")

        notebook.add(rejected_tab, text="Verworfen / Diagnose")

        paned.add(right_frame, stretch="never")

        button_row = tk.Frame(self.root)

        button_row.pack(fill="x", padx=10, pady=10)

        tk.Button(button_row, text="OCR jetzt ausführen", command=self._on_ocr_now).pack(side="left")

        tk.Button(button_row, text="Ergebnisse leeren", command=self._on_clear_results).pack(side="left", padx=8)

        tk.Button(button_row, text="Bereich neu markieren", command=self._on_reselect_hint).pack(side="left", padx=8)

        tk.Button(button_row, text="Test beenden", command=self.shutdown).pack(side="right")

        self.ocr_worker_thread = threading.Thread(target=self._ocr_worker, daemon=True)

        self.ocr_worker_thread.start()

        self.root.after(UI_REFRESH_MS, self._glib_iterate)

        self.root.after(UI_REFRESH_MS, self._update_ui_loop)

        self.log("[7/7] Kontinuierliche ROI-OCR mit Gruppierung gestartet")

    def _on_ocr_now(self) -> None:
        with self.frame_lock:
            frame = self.latest_frame
            roi = self.frame_roi
        if frame is None or roi is None:
            return
        crop = self._extract_roi_crop(frame, roi)

        self._request_ocr(crop)

        self.skip_reason = "manuell angefordert"
        self.log("OCR manuell angefordert")

    def _on_clear_results(self) -> None:
        self.raw_blocks = []
        self.accepted_blocks = []
        self.rejected_blocks = []
        self.grouped_blocks = []
        self._refresh_result_panels()

        self.log("Ergebnisse geleert")

    def _on_reselect_hint(self) -> None:
        self.log("Hinweis: Für neue Bereichsauswahl bitte Test 4 ausführen:")

        self.log("  ./scripts/run_roi_monitor_ui_test.sh")

        self.skip_reason = "Neu-Markierung: bitte Test 4 verwenden"
    def _refresh_result_panels(self) -> None:
        if self.groups_text is not None:
            self.groups_text.delete("1.0", tk.END)

            for group in self.grouped_blocks:
                self.groups_text.insert(
                    tk.END,
                    f"[Gruppe {group.id:02d}]\n"
                    f"Confidence: Ø {group.average_confidence:.2f} | "
                    f"Min {group.min_confidence:.2f}\n"
                    f"{group.text}\n\n",
                )

        if self.rejected_text is not None:
            self.rejected_text.delete("1.0", tk.END)

            if self.raw_blocks:
                self.rejected_text.insert(tk.END, "=== Rohblöcke (Diagnose) ===\n\n")

                for idx, block in enumerate(self.raw_blocks, start=1):
                    self.rejected_text.insert(
                        tk.END,
                        f"[Roh {idx:02d}] Conf {block.confidence:.2f} – {block.normalized_text}\n",
                    )

                self.rejected_text.insert(tk.END, "\n")

            for item in self.rejected_blocks:
                self.rejected_text.insert(
                    tk.END,
                    f"[Verworfen]\n"
                    f"Text: {item.raw.text}\n"
                    f"Confidence: {item.raw.confidence:.2f}\n"
                    f"Grund: {item.reason}\n\n",
                )

    def _glib_iterate(self) -> None:
        if self.shutting_down or self.root is None:
            return
        context = GLib.MainContext.default()

        while context.iteration(False):
            pass
        self.root.after(UI_REFRESH_MS, self._glib_iterate)

    def _update_status_only(self) -> None:
        if self.status_var is None:
            return
        roi = self.frame_roi
        frame = self.latest_frame
        frame_size = f"{frame.width}×{frame.height}" if frame else "–"
        roi_coords = f"{roi.x}, {roi.y}" if roi else "–"
        roi_size = f"{roi.width}×{roi.height}" if roi else "–"
        last_ocr = (
            datetime.fromtimestamp(self.last_ocr_time).strftime("%H:%M:%S")

            if self.last_ocr_time
            else "–"
        )

        self.status_var.set(
            f"Zustand: {self.state} | Frames: {self.frame_count} | "
            f"Frame: {frame_size} | ROI: {roi_coords} | Größe: {roi_size} | "
            f"OCR-Läufe: {self.ocr_run_number} | Dauer: {self.last_ocr_duration:.2f}s | "
            f"Roh: {len(self.raw_blocks)} | Akzeptiert: {len(self.accepted_blocks)} | "
            f"Verworfen: {len(self.rejected_blocks)} | Gruppen: {len(self.grouped_blocks)} | "
            f"Änderung: {self.last_change_pct:.2f}% | OCR aktiv: {'Ja' if self.ocr_active else 'Nein'} | "
            f"Letzte OCR: {last_ocr} | Übersprungen: {self.skip_reason}"
        )

    def _update_ui_loop(self) -> None:
        if self.shutting_down or self.root is None:
            return
        with self.frame_lock:
            frame = self.latest_frame
            roi = self.frame_roi
        now = time.monotonic()

        if frame is not None and roi is not None and self.preview_canvas is not None:
            crop = self._extract_roi_crop(frame, roi)

            preview = self._draw_preview(crop)

            canvas_w = max(self.preview_canvas.winfo_width(), 1)

            canvas_h = max(self.preview_canvas.winfo_height(), 1)

            fitted, scale, off_x, off_y = self._fit_image_to_canvas(preview, canvas_w, canvas_h)

            self.preview_display_size = (fitted.width, fitted.height)

            self.preview_photo = self._pil_to_photo(fitted)

            self.preview_canvas.delete("all")

            self.preview_canvas.create_image(off_x, off_y, anchor="nw", image=self.preview_photo)

            if now - self.last_ocr_check_time >= OCR_CHECK_INTERVAL_SEC:
                self.last_ocr_check_time = now
                self.last_change_pct = self._compute_change_pct(crop)

                should_run, reason = self._should_run_ocr(self.last_change_pct, now)

                if should_run:
                    if self.ocr_active:
                        self._request_ocr(crop)

                        self.skip_reason = "OCR läuft – neuesten ROI vorgemerkt"
                    else:
                        self._request_ocr(crop)

                        self.skip_reason = reason
                else:
                    self.skip_reason = reason
        self._update_status_only()

        self.root.after(UI_REFRESH_MS, self._update_ui_loop)

    def shutdown(self) -> None:
        if self.shutting_down:
            return
        self.shutting_down = True
        self.ocr_shutdown = True
        self.state = "beendet"
        self.log("Beende Test …")

        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)

            self.pipeline = None
        self.portal.cleanup()

        if self.frame_roi is not None and self.frame_count > 0:
            self.success = True
        if self.root is not None:
            try:
                self.root.destroy()

            except tk.TclError:
                pass
            self.root = None
        self.log(f"Empfangene Frames gesamt: {self.frame_count}")

        self.log(f"OCR-Läufe gesamt: {self.ocr_run_number}")

        self.log("Portal-Session geschlossen")

        self.log("Test beendet")

    def run(self) -> int:
        try:
            self.ocr_engine.wait_ready(timeout_sec=300)

            if self.ocr_engine.error or self.ocr_engine.reader is None:
                self.log("FEHLER: EasyOCR konnte nicht initialisiert werden.")

                return 1
            self.setup_portal()

            self.start_pipeline()

            first_frame = self._wait_for_first_frame()

            roi = self._load_saved_roi(first_frame)

            if roi is None:
                self.log("FEHLER: Kein gültiger gespeicherter ROI.")

                self.log("Bitte zuerst Test 4 ausführen: ./scripts/run_roi_monitor_ui_test.sh")

                self.portal.cleanup()

                if self.pipeline is not None:
                    self.pipeline.set_state(Gst.State.NULL)

                return 1
            self.frame_roi = roi
            self._build_ui()

            self.root.mainloop()

        except Exception:
            self.log("FEHLER mit Traceback:")

            traceback.print_exc()

            self.shutdown()

            return 1
        if not self.success:
            return 1
        return 0
def main() -> int:
    print("=" * 60)

    print(" LingoVeil – OCR-Gruppierungstest")

    print("=" * 60)

    return RoiOcrGroupingTest().run()

if __name__ == "__main__":
    sys.exit(main())
