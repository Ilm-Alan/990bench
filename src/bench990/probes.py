"""Component test of the misread-digits failure: can a model read one number off a dense table?

Each probe is one value printed in a dense table (Part VII compensation, Schedule J base pay,
Schedule I cash grants) on a rendered return page, with the row's identifying text (a person's
name or a recipient's EIN). The model is asked to transcribe every number in that row, and the
probe passes if the target value appears exactly. Conditions show the same row three ways:

- page150: the full page at 150 dpi, as agents see it in the study
- page300: the full page at 300 dpi
- strip300: a strip of the page around the row, full width, at 300 dpi (a "zoom")

The provider resizes every image to about the same token cost, so the strip shows the row at
several times the effective resolution of the full page.

    python -m bench990.probes build [--n 400]
    python -m bench990.probes run --model ollama/deepseek-v4.1-flash:1017
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pypdfium2 as pdfium

from . import assignments as A
from . import corpus, pages
from .agent import client_for

PROBES = corpus.ROOT / "data" / "probes"
RESULTS = corpus.ROOT / "runs" / "probes"
CONDITIONS = ("page150", "page300", "strip300")
STRIP_MARGIN_PT = 36  # half an inch above and below the row

QUESTION = ("This image is {what} of a US nonprofit's IRS Form 990. Find the row for {key}. "
            "Transcribe every number printed in that row exactly as printed, in order, separated by semicolons. "
            "Reply with the numbers only.")


def _compact(text: str) -> tuple[str, list[int]]:
    """Page text without whitespace, and for each kept character its index in the text page."""
    keep, index = [], []
    for i, ch in enumerate(text):
        if not ch.isspace():
            keep.append(ch)
            index.append(i)
    return "".join(keep), index


def locate(pdf: pdfium.PdfDocument, page_no: int, needle: str) -> tuple[float, float] | None:
    """Vertical extent (bottom, top in PDF points) of the only occurrence of `needle` on the page."""
    tp = pdf[page_no - 1].get_textpage()
    compact, index = _compact(tp.get_text_range())
    hits = [m.start() for m in re.finditer(re.escape(needle), compact)]
    if len(hits) != 1:
        return None
    boxes = [tp.get_charbox(index[k]) for k in range(hits[0], hits[0] + len(needle))]
    return min(b[1] for b in boxes), max(b[3] for b in boxes)


def _page_of(pdf: pdfium.PdfDocument, needle: str, key: str) -> int | None:
    """The single page where both the value (once) and the row key appear."""
    found = []
    for i in range(len(pdf)):
        compact, _ = _compact(pdf[i].get_textpage().get_text_range())
        if compact.count(needle) == 1 and re.sub(r"\s+", "", key) in compact:
            found.append(i + 1)
    return found[0] if len(found) == 1 else None


def build(n: int, seed: int = 0) -> None:
    rng = random.Random(seed)
    con = corpus.connect()
    pool = A.year_returns(A.TAX_YEAR)
    # Returns with both Schedule I and Schedule J yield all three kinds of probe from one render.
    rich = {r[0] for r in con.execute("SELECT DISTINCT object_id FROM grants")} & \
        {r[0] for r in con.execute("SELECT object_id FROM facts WHERE has_j = 1")}
    ids = sorted(set(pool.object_id) & rich)
    rng.shuffle(ids)
    probes: list[dict[str, object]] = []
    per_kind = {"part7": n // 3, "sched_j": n // 3, "grants": n - 2 * (n // 3)}
    queries = {
        "part7": ("SELECT person, comp_org FROM part7 WHERE object_id = ? AND comp_org >= 10000", "person"),
        "sched_j": ("SELECT person, base FROM sched_j WHERE object_id = ? AND base >= 10000", "person"),
        "grants": ("SELECT recipient_ein, cash FROM grants WHERE object_id = ? AND cash >= 10000 AND recipient_ein IS NOT NULL", "ein"),
    }
    for oid in ids:
        if all(sum(p["kind"] == k for p in probes) >= v for k, v in per_kind.items()):
            break
        candidates = []
        for kind, (sql, key_type) in queries.items():
            if sum(p["kind"] == kind for p in probes) >= per_kind[kind]:
                continue
            rows = con.execute(sql, (oid,)).fetchall()
            rng.shuffle(rows)
            candidates += [(kind, key_type, key, int(value)) for key, value in rows[:2] if key]
        if not candidates:
            continue
        try:
            pages.ensure(oid)
        except Exception as exc:  # a few returns crash Chromium's PDF printer; skip them
            print(f"skip {oid}: render failed ({type(exc).__name__})", flush=True)
            continue
        pdf = pdfium.PdfDocument(pages.CACHE / oid / f"{oid}.pdf")
        for kind, key_type, key, value in candidates:
            needle = f"{value:,}"
            shown_key = f"{key[:2]}-{key[2:]}" if key_type == "ein" else key
            page_no = _page_of(pdf, needle, shown_key)
            if page_no is None:
                continue
            extent = locate(pdf, page_no, needle)
            if extent is None:
                continue
            key_text = f"the recipient with EIN {shown_key}" if key_type == "ein" else f"the person named {key}"
            probes.append({"id": f"{oid}-{kind}-{len(probes)}", "object_id": oid, "kind": kind, "page": page_no,
                           "value": value, "key": key_text, "extent": extent})
            print(f"{len(probes):4} {kind:8} {oid} p{page_no} {needle}", flush=True)
    PROBES.mkdir(parents=True, exist_ok=True)
    (PROBES / "probes.jsonl").write_text("".join(json.dumps(p) + "\n" for p in probes))
    print(f"{len(probes)} probes")


def image(p: dict[str, object], condition: str) -> bytes:
    dpi = 150 if condition == "page150" else 300
    with pages.PDFIUM:
        pdf = pdfium.PdfDocument(pages.CACHE / p["object_id"] / f"{p['object_id']}.pdf")
        page = pdf[p["page"] - 1]
        img = page.render(scale=dpi / 72, grayscale=True).to_pil()
        height = page.get_height()
        page.close()
        pdf.close()
    if condition == "strip300":
        bottom, top = p["extent"]
        scale = dpi / 72
        y0 = max(0, int((height - top - STRIP_MARGIN_PT) * scale))
        y1 = min(img.height, int((height - bottom + STRIP_MARGIN_PT) * scale))
        img = img.crop((0, y0, img.width, y1))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def ask(client, model: str, p: dict[str, object], condition: str) -> dict[str, object]:
    what = "a strip cut from one page" if condition == "strip300" else "one page"
    content = [{"type": "text", "text": QUESTION.format(what=what, key=p["key"])},
               {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(image(p, condition)).decode()}}]
    resp = client.post("/chat/completions", json={"model": model, "messages": [{"role": "user", "content": content}]})
    if resp.status_code != 200:
        return {"error": f"http {resp.status_code}: {resp.text[:200]}", "infra": resp.status_code == 429 or resp.status_code >= 500}
    body = resp.json()
    answer = body["choices"][0]["message"].get("content") or ""
    numbers = [re.sub(r"[^\d]", "", tok) for tok in re.findall(r"\d[\d,]*", answer)]
    return {"answer": answer[:500], "correct": str(p["value"]) in numbers, "usage": body.get("usage", {})}


def run(model: str, parallel: int) -> None:
    probes = [json.loads(line) for line in (PROBES / "probes.jsonl").read_text().splitlines()]
    out = RESULTS / model.replace("/", "_").replace(":", "-")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "results.jsonl"
    done = {(r["id"], r["condition"]) for r in map(json.loads, path.read_text().splitlines())} if path.exists() else set()
    jobs = [(p, c) for p in probes for c in CONDITIONS if (p["id"], c) not in done]
    print(f"{len(jobs)} probe calls to do", flush=True)
    client, model_name = client_for(model)
    stop = threading.Event()

    def one(job: tuple[dict, str]) -> dict[str, object] | None:
        if stop.is_set():
            return None
        p, c = job
        r = ask(client, model_name, p, c)
        if r.get("infra"):
            if not stop.is_set():
                print("INFRA, stopping:", r["error"], flush=True)
            stop.set()
            return None
        return {"id": p["id"], "kind": p["kind"], "condition": c, "value": p["value"], **r}

    written = 0
    with client, ThreadPoolExecutor(parallel) as pool, path.open("a") as fh:
        for rec in pool.map(one, jobs):
            if rec is not None:
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                written += 1
    print(f"{written} results written", flush=True)


def mcnemar(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value for b and c discordant pairs."""
    from math import comb

    n, k = b + c, min(b, c)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2**n)


def report() -> str:
    from .analysis import wilson

    lines = ["| Model | Probes | Condition | Read correctly (95% CI) | Part VII | Schedule J | Schedule I | Mean prompt tokens |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    pairs = []
    for path in sorted(RESULTS.glob("*/results.jsonl")):
        # Calls the provider rejected (non-quota errors) are excluded; a probe counts only if all conditions ran.
        rows = [r for r in map(json.loads, path.read_text().splitlines()) if "correct" in r]
        model = path.parent.name
        by = {(r["id"], r["condition"]): r for r in rows}
        ids = sorted({r["id"] for r in rows if all((r["id"], c) in by for c in CONDITIONS)})
        if not ids:
            continue
        for c in CONDITIONS:
            rs = [by[(i, c)] for i in ids]
            k = sum(r["correct"] for r in rs)
            lo, hi = wilson(k, len(rs))
            kinds = []
            for kind in ("part7", "sched_j", "grants"):
                sub = [r for r in rs if r["kind"] == kind]
                kinds.append(f"{sum(r['correct'] for r in sub)}/{len(sub)}")
            tokens = sum(r["usage"].get("prompt_tokens", 0) for r in rs) / max(len(rs), 1)
            lines.append(f"| {model} | {len(ids)} | {c} | {k}/{len(rs)} = {k / len(rs):.1%} ({lo:.1%}–{hi:.1%}) | "
                         f"{' | '.join(kinds)} | {tokens:,.0f} |")
        for a, b in (("page150", "strip300"), ("page150", "page300")):
            only_a = sum(by[(i, a)]["correct"] and not by[(i, b)]["correct"] for i in ids)
            only_b = sum(by[(i, b)]["correct"] and not by[(i, a)]["correct"] for i in ids)
            pairs.append(f"| {model} | {a} vs {b} | {only_a} | {only_b} | {mcnemar(only_a, only_b):.2g} |")
    lines += ["", "| Model | Comparison | Right only in first | Right only in second | Exact McNemar p |",
              "| --- | --- | --- | --- | --- |", *pairs]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--n", type=int, default=400)
    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--parallel", type=int, default=4)
    sub.add_parser("report")
    args = ap.parse_args()
    if args.cmd == "build":
        build(args.n)
    elif args.cmd == "run":
        run(args.model, args.parallel)
    else:
        text = report()
        (corpus.ROOT / "docs" / "probe-results.md").write_text(text)
        print(text)


if __name__ == "__main__":
    main()
