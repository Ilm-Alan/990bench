"""Page images of returns for document mode, rendered on first request and cached on disk."""

from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pypdfium2 as pdfium

from . import corpus, render

CACHE = corpus.ROOT / "data" / "pages"
_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
_guard = threading.Lock()
# pdfium is not thread-safe: concurrent use corrupts its heap and aborts the process. Every pdfium
# call in this package (rendering, rasterizing, text extraction) runs under this lock.
PDFIUM = threading.RLock()


def ensure(object_id: str) -> list[dict[str, object]]:
    """Render the return if needed; return its table of contents."""
    out = CACHE / object_id
    toc = out / f"{object_id}.toc.json"
    with _guard:
        lock = _locks[object_id]
    with lock:
        if not toc.exists():
            with PDFIUM:
                render.render(object_id, out)
    return json.loads(toc.read_text())


def page(object_id: str, number: int) -> Path:
    return CACHE / object_id / f"{object_id}_p{number:03d}.png"


def page_count(object_id: str) -> int:
    toc = ensure(object_id)
    return int(toc[-1]["last_page"]) if toc else 0


def describe(object_id: str) -> str:
    """Contents line a reader sees when opening the return."""
    toc = ensure(object_id)
    lines = [f"Return {object_id}: {page_count(object_id)} pages"]
    lines += [f"  pages {d['first_page']}-{d['last_page']}: {d['document']}" if d["first_page"] != d["last_page"]
              else f"  page {d['first_page']}: {d['document']}" for d in toc]
    return "\n".join(lines)


@lru_cache(maxsize=64)
def text_of(object_id: str) -> str:
    """Text layer of the rendered PDF, used only to check that graded values are visible."""
    ensure(object_id)
    with PDFIUM:
        pdf = pdfium.PdfDocument(CACHE / object_id / f"{object_id}.pdf")
        text = "\n".join(p.get_textpage().get_text_range() for p in pdf)
        pdf.close()
    return text


def visible(object_id: str, value: int | str) -> bool:
    # Chromium's text layer on continued table pages splits glyphs across lines, so compare without whitespace.
    text = re.sub(r"\s+", "", text_of(object_id))
    needle = f"{value:,}" if isinstance(value, int) else re.sub(r"\s+", "", str(value))
    return needle in text


def exists(object_id: str) -> bool:
    return corpus.get(object_id) is not None


# Page fidelity: (dpi, bilevel). "clean" is the grayscale render; "bilevel" matches the IRS's own
# 1-bit page images; "coarse" is 1-bit at a lower resolution, like a poor copy.
FIDELITY = {"clean": (150, False), "bilevel": (150, True), "coarse": (100, True)}


def png_bytes(object_id: str, number: int, fidelity: str = "clean") -> bytes:
    if fidelity == "clean":
        return page(object_id, number).read_bytes()
    path = CACHE / object_id / fidelity / f"{object_id}_p{number:03d}.png"
    if not path.exists():
        dpi, bilevel = FIDELITY[fidelity]
        with PDFIUM:
            pdf = pdfium.PdfDocument(CACHE / object_id / f"{object_id}.pdf")
            image = pdf[number - 1].render(scale=dpi / 72, grayscale=True).to_pil()
            pdf.close()
        if bilevel:
            image = image.point(lambda v: 255 if v >= 160 else 0, mode="1")
        path.parent.mkdir(exist_ok=True)
        image.save(path, optimize=True)
    return path.read_bytes()
