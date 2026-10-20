"""Aggregate study runs: pass rates with Wilson intervals, value accuracy with bootstrap intervals,
cost per correct deliverable, and a failure taxonomy read from the graded answers.

    python -m bench990.analysis            # writes docs/study-results.md and docs/study-*.png
"""

from __future__ import annotations

import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import assignments as A
from .corpus import ROOT
from .study import RUNS, STUDY, cells

DOCS = ROOT / "docs"
FIELDS = ("ein", "period_end", "total_revenue", "program_share", "top_comp", "insider_transactions")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap(values: list[float], reps: int = 2000, seed: int = 0) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(reps))
    return (means[int(0.025 * reps)], means[int(0.975 * reps) - 1])


def _digits(v: object) -> str:
    return re.sub(r"\D", "", str(v))


def _edits(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def classify(a: A.Assignment, answer: object) -> Counter[str]:
    """One label per wrong applicant, from the most basic error found."""
    labels: Counter[str] = Counter()
    got = {}
    if isinstance(answer, list):
        for x in answer:
            try:
                got[int(x["applicant"])] = x
            except (TypeError, KeyError, ValueError):
                continue
    f = A.filings()
    for exp in a.expected:
        g = got.get(exp["applicant"])
        if g is None:
            labels["applicant omitted"] += 1
            continue
        if A._ein(g.get("ein", "")) != exp["ein"]:
            labels["wrong organization"] += 1
            continue
        if str(g.get("period_end", ""))[:10] != exp["period_end"]:
            other = set(f[f.ein == exp["ein"]].period_end)
            labels["wrong return (tax year mapped to the wrong period)" if str(g.get("period_end"))[:10] in other
                   else "wrong period end"] += 1
            continue
        wrong = [k for k in FIELDS[2:] if not A.grade(A.Assignment("x", "due_diligence", "", [exp]), [{**exp, k: g.get(k)}])["passed"]]
        if not wrong:
            continue
        k = wrong[0]
        if k == "program_share":
            v = A._num(g.get(k))
            labels["program share off by rounding" if v is not None and abs(v - exp[k]) <= 0.15 else "program share wrong"] += 1
        elif k == "insider_transactions":
            labels["Schedule L judged wrong"] += 1
        elif _edits(_digits(g.get(k)), _digits(exp[k])) <= 2:
            labels[f"{k}: misread digits"] += 1
        else:
            labels[f"{k}: wrong line or value"] += 1
    return labels


def load() -> list[dict[str, object]]:
    plan = {(r["fidelity"], r["assignment"]): r for r in map(json.loads, (STUDY / "runs.jsonl").read_text().splitlines())}
    items = {a.id: a for a in A.load(STUDY / "assignments.jsonl")}
    rows = []
    for path in sorted(RUNS.glob("*/*/*/result.json")):
        rec = json.loads(path.read_text())
        if rec["infra_error"]:
            continue
        r = plan.get((rec["fidelity"], rec["assignment"]))
        if r is None:
            continue
        a = items[rec["assignment"]]
        stopped = rec["error"] is not None
        rows.append({**rec, "cell": r["cell"], "dial": r["dial"], "n": r["n"], "trap_share": r["trap_share"],
                     "stopped": stopped,
                     "labels": classify(a, rec["answer"]) if not stopped and not rec["grade"]["passed"] else Counter()})
    return rows


def summarize(rows: list[dict[str, object]]) -> str:
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by[(r["model"], r["cell"])].append(r)
    order = [c.name for c in cells()]
    lines = ["| Model | Cell | Runs | Passed | Wrong values | Stopped by budget | Pass rate (95% CI) | "
             "Value accuracy, finished runs | Mean tool calls | Mean prompt tokens | Prompt tokens per correct deliverable |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for (model, cell), rs in sorted(by.items(), key=lambda kv: (kv[0][0], order.index(kv[0][1]))):
        k, n = sum(r["grade"]["passed"] for r in rs), len(rs)
        stopped = sum(r["stopped"] for r in rs)
        lo, hi = wilson(k, n)
        acc = [r["grade"]["score"] for r in rs if not r["stopped"]]
        acc_cell = f"{sum(acc) / len(acc):.1%}" if acc else "n/a"
        tokens = sum(r["usage"]["prompt_tokens"] for r in rs)
        per_correct = f"{tokens / k:,.0f}" if k else "n/a"
        lines.append(f"| {model.split('/')[-1]} | {cell} | {n} | {k} | {n - k - stopped} | {stopped} | "
                     f"{k}/{n} ({lo:.0%}–{hi:.0%}) | {acc_cell} | {sum(r['tool_calls'] for r in rs) / n:.0f} | "
                     f"{tokens / n:,.0f} | {per_correct} |")
    labels: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        labels[r["model"].split("/")[-1]].update(r["labels"])
    lines += ["", "Errors in finished runs, one label per wrong applicant:", "",
              "| Model | Error | Wrong applicants |", "| --- | --- | --- |"]
    for model, c in sorted(labels.items()):
        lines += [f"| {model} | {label} | {count} |" for label, count in c.most_common()]
    return "\n".join(lines) + "\n"


def chart(rows: list[dict[str, object]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8), sharey=True)
    dials = [("horizon", "Applicants per assignment", lambda c: c.n, {"baseline", "horizon"}),
             ("traps", "Share of applicants with a fiscal-year trap", lambda c: c.trap_share, {"baseline", "traps"}),
             ("fidelity", "Page fidelity", lambda c: ["clean", "bilevel", "coarse"].index(c.fidelity), {"baseline", "fidelity"})]
    models = sorted({r["model"] for r in rows})
    for ax, (dial, label, x_of, members) in zip(axes, dials):
        for model in models:
            pts = []
            for c in cells():
                if c.dial not in members:
                    continue
                rs = [r for r in rows if r["model"] == model and r["cell"] == c.name]
                if rs:
                    k = sum(r["grade"]["passed"] for r in rs)
                    lo, hi = wilson(k, len(rs))
                    pts.append((x_of(c), k / len(rs), lo, hi))
            pts.sort()
            if len(pts) > 1:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                err = [[y - p[2] for y, p in zip(ys, pts)], [p[3] - y for y, p in zip(ys, pts)]]
                ax.errorbar(xs, ys, yerr=err, marker="o", capsize=3, label=model.split("/")[-1])
            elif pts:
                p = pts[0]
                ax.errorbar([p[0]], [p[1]], yerr=[[p[1] - p[2]], [p[3] - p[1]]], marker="s", capsize=3,
                            linestyle="none", label=model.split("/")[-1])
        ax.set_xlabel(label)
        ax.set_ylim(-0.05, 1.05)
        if dial == "fidelity":
            ax.set_xticks([0, 1, 2], ["clean", "1-bit", "coarse 1-bit"])
    axes[0].set_ylabel("Pass rate (whole deliverable correct)")
    axes[0].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(DOCS / "study-pass-rate.png", dpi=150)


def main() -> None:
    rows = load()
    (DOCS / "study-results.md").write_text(summarize(rows))
    chart(rows)
    print(summarize(rows))


if __name__ == "__main__":
    main()
