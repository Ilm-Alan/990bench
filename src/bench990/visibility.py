"""Document-mode fairness: every value an answer depends on must be printed on the rendered pages.

The IRS stylesheets occasionally drop data (see docs/rendering.md), so an assignment is usable
in document mode only if each source value appears in the text layer of the right return's
render. Agents get PNGs without a text layer; the text layer is used only for this check.

    python -m bench990.visibility data/assignments.jsonl
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import assignments as A
from . import pages

MODES = {"due_diligence", "follow_money", "compensation", "grant_ledger", "schedule_j_table"}


def _date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{m}-{d}-{y}"


def requirements(a: A.Assignment) -> list[tuple[str, int | str]]:
    """(object_id, value) pairs that must be visible."""
    fx = A.facts()
    con = A.corpus.connect()
    need: list[tuple[str, int | str]] = []
    if a.kind == "due_diligence":
        for oid, exp in zip(a.meta["object_ids"], a.expected):
            x = fx.loc[oid]
            need += [(oid, exp["total_revenue"]), (oid, int(x.p9_total)), (oid, int(x.p9_program)),
                     (oid, exp["top_comp"]), (oid, _date(exp["period_end"]))]
    elif a.kind == "follow_money":
        oid = a.meta["grantor_object_id"]
        for (cash,) in con.execute("SELECT cash FROM grants WHERE object_id = ? AND cash > 0", (oid,)):
            need.append((oid, int(cash)))
        clean = A.year_returns(a.meta["year"])
        for ein in a.expected["considered"]:
            r = clean.loc[ein]
            need.append((r.object_id, int(fx.loc[r.object_id].cy_revenue)))
    elif a.kind == "compensation":
        for oid in a.meta["object_ids"]:
            for org, related in con.execute("SELECT total_org, total_related FROM sched_j WHERE object_id = ?", (oid,)):
                need += [(oid, int(v)) for v in (org, related) if v]
    elif a.kind == "grant_ledger":
        by_ein = {A.filings().set_index("object_id").loc[o].ein: o for o in a.meta["object_ids"]}
        for row in a.expected:
            oid = by_ein[row["funder_ein"]]
            need += [(oid, v) for v in (row["cash"], row["noncash"]) if v]
            if row["recipient_ein"]:
                need.append((oid, f"{row['recipient_ein'][:2]}-{row['recipient_ein'][2:]}"))
    elif a.kind == "schedule_j_table":
        by_ein = {A.filings().set_index("object_id").loc[o].ein: o for o in a.meta["object_ids"]}
        for row in a.expected:
            need += [(by_ein[row["ein"]], row[c]) for c in A.J_COLUMNS if row[c]]
    else:
        raise ValueError(f"{a.kind} is not offered in document mode")
    return need


def missing(a: A.Assignment) -> list[tuple[str, int | str]]:
    return [(oid, v) for oid, v in requirements(a) if not pages.visible(oid, v)]


def main() -> None:
    bad = 0
    for a in A.load(Path(sys.argv[1])):
        if a.kind not in MODES:
            print(f"SKIP     {a.kind:14} {a.id} (not a document-mode kind)")
            continue
        gone = missing(a)
        bad += bool(gone)
        print(f"{'VISIBLE' if not gone else 'MISSING'}  {a.kind:14} {a.id} {gone[:5] if gone else ''}", flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
