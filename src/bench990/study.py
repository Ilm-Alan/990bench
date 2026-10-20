"""Reliability study: where do agents stop being reliable at due diligence from page images?

One assignment family (due diligence, document mode) varied along three dials, one at a time
around a baseline of 10 applicants, half with fiscal-year traps, clean pages:

- horizon: 5, 10, 20, 40 applicants
- trap share: 0%, 50%, 100% of applicants with a live fiscal-year trap
- page fidelity: clean grayscale, IRS-style 1-bit, coarse 1-bit

Every run uses the same harness and keeps only the six most recent page images in context, so
long assignments test note-keeping rather than context size. A run stops as a failure once its
cumulative prompt tokens pass 400,000 per applicant.

    python -m bench990.study plan
    python -m bench990.study run --model ollama/deepseek-v4.1-flash:1017 [--dials baseline,horizon]
"""

from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from . import assignments as A
from . import crosscheck, visibility
from .corpus import ROOT
from .run import run_one

STUDY = ROOT / "data" / "study"
RUNS = ROOT / "runs" / "study"
INSTANCES = 4
KEEP_IMAGES = 6
TOKENS_PER_APPLICANT = 400_000
BASELINE = (10, 0.5, "clean")


@dataclass(frozen=True)
class Cell:
    dial: str
    n: int
    trap_share: float
    fidelity: str

    @property
    def name(self) -> str:
        return f"n{self.n}-t{round(self.trap_share * 100)}-{self.fidelity}"


def cells() -> list[Cell]:
    n, t, f = BASELINE
    out = [Cell("baseline", n, t, f)]
    out += [Cell("horizon", size, t, f) for size in (5, 20, 40)]
    out += [Cell("traps", n, share, f) for share in (0.0, 1.0)]
    out += [Cell("fidelity", n, t, fid) for fid in ("bilevel", "coarse")]
    return out


def plan() -> None:
    STUDY.mkdir(parents=True, exist_ok=True)
    instances: dict[tuple[int, float], list[A.Assignment]] = {}
    for c in cells():
        key = (c.n, c.trap_share)
        if key in instances:
            continue
        made: list[A.Assignment] = []
        for i in range(INSTANCES * 3):
            if len(made) == INSTANCES:
                break
            a = A.due_diligence(random.Random(f"{c.n}-{c.trap_share}-{i}"), n=c.n, trap_share=c.trap_share)
            if a is None or not crosscheck.check(a) or visibility.missing(a):
                print(f"rejected instance {i} for {key}")
                continue
            made.append(a)
            print(f"{a.id}: validated", flush=True)
        if len(made) < INSTANCES:
            raise SystemExit(f"only {len(made)} valid instances for {key}")
        instances[key] = made
    A.save([a for made in instances.values() for a in made], STUDY / "assignments.jsonl")
    runs = [{"cell": c.name, **asdict(c), "assignment": a.id}
            for c in cells() for a in instances[(c.n, c.trap_share)]]
    (STUDY / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
    print(f"{len(runs)} runs over {sum(map(len, instances.values()))} assignments")


def run(model: str, dials: set[str] | None, parallel: int) -> None:
    items = {a.id: a for a in A.load(STUDY / "assignments.jsonl")}
    todo = []
    for r in map(json.loads, (STUDY / "runs.jsonl").read_text().splitlines()):
        if dials and r["dial"] not in dials:
            continue
        out = RUNS / model.replace("/", "_").replace(":", "-") / r["fidelity"]
        done = out / r["assignment"] / "result.json"
        if done.exists() and not json.loads(done.read_text())["infra_error"]:
            continue
        todo.append((r, out))
    print(f"{len(todo)} runs to do", flush=True)

    def one(job: tuple[dict, Path]) -> None:
        r, out = job
        rec = run_one(model, items[r["assignment"]], out, max_steps=400, deadline_s=7200, mode="documents",
                      fidelity=r["fidelity"], keep_images=KEEP_IMAGES,
                      max_prompt_tokens=TOKENS_PER_APPLICANT * r["n"])
        g = rec["grade"]
        status = "INFRA" if rec["infra_error"] else "PASS" if g["passed"] else "FAIL"
        print(f"{status} {r['cell']:18} {r['assignment']:34} score={g['score']:.3f} calls={rec['tool_calls']:3} "
              f"tokens={rec['usage']['prompt_tokens']:,}{' ERR ' + str(rec['error'])[:160] if rec['error'] else ''}",
              flush=True)

    with ThreadPoolExecutor(parallel) as pool:
        list(pool.map(one, todo))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--dials", help="comma-separated: baseline,horizon,traps,fidelity")
    r.add_argument("--parallel", type=int, default=2)
    args = ap.parse_args()
    if args.cmd == "plan":
        plan()
    else:
        run(args.model, set(args.dials.split(",")) if args.dials else None, args.parallel)


if __name__ == "__main__":
    main()
