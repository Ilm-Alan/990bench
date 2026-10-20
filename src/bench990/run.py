"""Generate assignments and run models on them in the sandbox.

    python -m bench990.run generate --out data/assignments.jsonl
    python -m bench990.run run --model ollama/kimi-k3 --assignments data/assignments.jsonl --out runs/proto
    python -m bench990.run grade runs/proto
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import assignments as A
from . import pages
from .agent import ToolResult, client_for, run_loop
from .sandbox import Sandbox

SYSTEM = """You are a data analyst on a Linux workstation. You have a `bash` tool, which runs a shell command in /work and returns its output, truncated to 8000 characters. Each command may run for at most 600 seconds; process large data in steps or in the background. There is no internet access. /data/README.md describes the IRS data available on this machine.{extra}

Complete the assignment yourself, write the deliverable exactly as specified, check it, and then call `submit`. Do not ask questions; nobody will answer them."""
DOCUMENT_TOOLS = """

Returns are available only as page images: `open_return` lists a return's pages and the form or schedule on each, and `view_page` shows you one page."""


def _fn(name: str, description: str, props: dict[str, object], required: list[str]) -> dict[str, object]:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": props, "required": required}}}


BASH = _fn("bash", "Run a bash command in /work and return stdout and stderr.", {"command": {"type": "string"}}, ["command"])
SUBMIT = _fn("submit", "Finish the assignment. Call once, after /work/answer.json is written.", {}, [])
OPEN = _fn("open_return", "List the pages of a return (by OBJECT_ID) and the form or schedule each page belongs to.",
           {"object_id": {"type": "string"}}, ["object_id"])
VIEW = _fn("view_page", "Show one page of a return as an image.",
           {"object_id": {"type": "string"}, "page": {"type": "integer"}}, ["object_id", "page"])
MODES = {"data": [BASH, SUBMIT], "documents": [BASH, OPEN, VIEW, SUBMIT]}


def _document_tool(name: str, args: dict[str, object], fidelity: str) -> ToolResult:
    oid = str(args.get("object_id", "")).strip()
    if not pages.exists(oid):
        return f"error: no return with OBJECT_ID {oid!r}"
    if name == "open_return":
        return pages.describe(oid)
    try:
        number = int(args.get("page", 0))
    except (TypeError, ValueError):
        return "error: page must be an integer"
    total = pages.page_count(oid)
    if not 1 <= number <= total:
        return f"error: return {oid} has pages 1-{total}"
    return f"Return {oid}, page {number} of {total}", [pages.png_bytes(oid, number, fidelity)]


def run_one(model_spec: str, a: A.Assignment, out: Path, max_steps: int, deadline_s: float, mode: str = "data",
            fidelity: str = "clean", keep_images: int | None = None,
            max_prompt_tokens: int | None = None) -> dict[str, object]:
    work = out / a.id / "work"
    client, model = client_for(model_spec)
    documents = mode == "documents"
    tools = {s["function"]["name"] for s in MODES[mode]}
    with client, Sandbox(work, documents=documents) as box:
        def call(name: str, args: dict[str, object]) -> ToolResult:
            if name == "bash" and "command" in args:
                return box.bash(str(args["command"]), timeout=600)
            if documents and name in tools - {"bash", "submit"}:
                return _document_tool(name, args, fidelity)
            return f"error: unknown tool or missing arguments; tools are {sorted(tools)}"

        extra = DOCUMENT_TOOLS if documents else ""
        system = SYSTEM.format(extra=extra)
        result = run_loop(client, model, system, a.prompt, MODES[mode], call, max_steps=max_steps,
                          deadline_s=deadline_s, keep_images=keep_images, max_prompt_tokens=max_prompt_tokens)
    answer_path = work / "answer.json"
    try:
        answer = json.loads(answer_path.read_text())
        grade = A.grade(a, answer)
    except (OSError, json.JSONDecodeError) as exc:
        answer, grade = None, {"passed": False, "score": 0.0, "checks": [], "error": f"no readable answer.json: {exc}"}
    record = {"assignment": a.id, "kind": a.kind, "model": model_spec, "mode": mode, "fidelity": fidelity,
              "keep_images": keep_images, **result, "answer": answer, "grade": grade}
    (out / a.id / "result.json").write_text(json.dumps(record, indent=1))
    return record


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--out", type=Path, default=Path("data/assignments.jsonl"))
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--counts", default="due_diligence=2,follow_money=2,compensation=2")
    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--assignments", type=Path, default=Path("data/assignments.jsonl"))
    r.add_argument("--only", nargs="*", help="assignment ids")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--parallel", type=int, default=3)
    r.add_argument("--max-steps", type=int, default=250)
    r.add_argument("--deadline", type=float, default=5400)
    r.add_argument("--mode", choices=sorted(MODES), default="data")
    args = ap.parse_args()

    if args.cmd == "generate":
        counts = {k: int(v) for k, v in (p.split("=") for p in args.counts.split(","))}
        items = A.generate(counts, seed=args.seed)
        A.save(items, args.out)
        for a in items:
            print(f"{a.kind:14} {a.id}")
        return

    items = [a for a in A.load(args.assignments) if not args.only or a.id in args.only]
    out = args.out / args.mode / args.model.replace("/", "_").replace(":", "-")
    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(args.parallel) as pool:
        futures = [pool.submit(run_one, args.model, a, out, args.max_steps, args.deadline, args.mode) for a in items]
        for fut in futures:
            rec = fut.result()
            g = rec["grade"]
            status = "INFRA" if rec["infra_error"] else "PASS" if g["passed"] else "FAIL"
            print(f"{status} {rec['kind']:14} {rec['assignment']:28} score={g['score']:.2f} "
                  f"calls={rec['tool_calls']:3} {rec['seconds']:7}s tokens={rec['usage']['prompt_tokens']:,}"
                  f"{' ERR ' + str(rec['error'])[:200] if rec['error'] else ''}"
                  f"{' GRADE ' + g['error'][:200] if g['error'] else ''}", flush=True)


if __name__ == "__main__":
    main()
