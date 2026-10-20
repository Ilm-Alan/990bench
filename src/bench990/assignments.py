"""Long-horizon analyst assignments with answers computed from the IRS data, and their verifier.

Every assignment states its definitions exactly (form part, line, column, which return), names
organizations the way a colleague would (name, city, state), and asks for a JSON deliverable in
/work/answer.json. The reference answer is computed here from the same files the agent has.
Generators only pick instances whose answer is unambiguous under the stated rules; they never
look at model behaviour.

Difficulty is designed in, not selected for:
- Returns are requested by tax year. An organization whose fiscal year does not end in December
  files its tax-year-T return with a tax period ending in T+1, while its T-1 return ends in T, so
  matching the index's TAX_PERIOD to T picks the wrong return. Generators prefer organizations
  where that wrong return is present in the data ("live traps").
- Values come from the dense pages: Part IX columns, Part VII, Schedule I grant tables that run
  onto continuation pages, and Schedule J rows (i) and (ii).
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path

import pandas as pd

from . import corpus

DELIVERABLE = "Write your answer to /work/answer.json in exactly this format, then call submit."
TAX_YEAR = 2024


@dataclass
class Assignment:
    id: str
    kind: str
    prompt: str
    expected: object
    meta: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------- reference data


@cache
def filings() -> pd.DataFrame:
    df = pd.read_sql("SELECT * FROM filings", corpus.connect())
    df["key"] = df.name.str.upper().str.strip() + "|" + df.city.fillna("").str.upper().str.strip() + "|" + df.state.fillna("")
    df["end_year"] = df.period_end.str[:4].astype(int)
    return df


@cache
def facts() -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM facts", corpus.connect()).set_index("object_id")


@cache
def bmf() -> pd.DataFrame:
    parts = [pd.read_csv(p, dtype=str, usecols=["EIN", "NAME", "CITY", "STATE"]) for p in sorted(corpus.RAW.glob("bmf_eo*.csv"))]
    df = pd.concat(parts)
    df["key"] = df.NAME.str.upper().str.strip() + "|" + df.CITY.str.upper().str.strip() + "|" + df.STATE
    return df


@cache
def identity_ok() -> frozenset[str]:
    """EINs whose (name, city, state) is shared with no other EIN in the returns or the BMF,
    and which present one consistent identity across their returns."""
    f = filings()
    per_key = pd.concat([f[["key", "ein"]], bmf()[["key", "EIN"]].rename(columns={"EIN": "ein"})]).drop_duplicates()
    counts = per_key.groupby("key").ein.nunique()
    ok = f[f.key.isin(set(counts[counts == 1].index))]
    stable = ok.groupby("ein").key.nunique()
    return frozenset(stable[stable == 1].index)


@cache
def year_returns(year: int) -> pd.DataFrame:
    """Form 990s that are the organization's only 990-series return for the tax year, not amended,
    from organizations with no amended return at all. `trap` marks a live fiscal-year trap: the
    organization's previous return also ends in `year`."""
    f = filings()
    in_year = f[f.tax_year == year]
    counts = in_year.groupby("ein").size()
    amended_eins = set(f[f.amended == 1].ein)
    sole = in_year[in_year.ein.map(counts).eq(1) & (in_year.return_type == "990") & ~in_year.ein.isin(amended_eins)].copy()
    prior_ends_in_year = set(f[(f.tax_year == year - 1) & (f.end_year == year)].ein)
    sole["trap"] = (sole.end_year == year + 1) & sole.ein.isin(prior_ends_in_year)
    return sole.set_index("ein", drop=False)


@cache
def collided_names() -> frozenset[str]:
    return frozenset(filings().groupby("name").ein.nunique().loc[lambda s: s > 1].index)


def _who(row: pd.Series) -> str:
    return f"{row['name']} ({str(row['city']).title()}, {row['state']})"


def _pct(num: int, den: int) -> float:
    return round(num / den * 100 + 1e-9, 1)


def _pick(rng: random.Random, pool: pd.DataFrame, n: int, quotas: list[tuple[str, int]]) -> pd.DataFrame:
    """Sample n rows, first filling each (boolean column, minimum) quota."""
    order = pool.sample(frac=1, random_state=rng.randrange(2**31))
    chosen: list[str] = []
    for column, minimum in quotas:
        for ein in order[order[column]].ein:
            if sum(order.loc[e, column] for e in chosen) >= minimum or len(chosen) == n:
                break
            if ein not in chosen:
                chosen.append(ein)
    for ein in order.ein:
        if len(chosen) == n:
            break
        if ein not in chosen:
            chosen.append(ein)
    return order.loc[chosen] if len(chosen) == n else order.iloc[0:0]


# ---------------------------------------------------------------- A. due diligence


def _clear_of_rounding(num: int, den: int) -> bool:
    """False when the percentage sits on (or within 0.001 points of) a rounding boundary at one decimal."""
    tenths = num / den * 1000
    return abs(tenths - int(tenths) - 0.5) > 0.01


def due_diligence(rng: random.Random, n: int = 20, year: int = TAX_YEAR, trap_share: float = 0.5) -> Assignment | None:
    """`trap_share` of the applicants have a live fiscal-year trap; the rest have none."""
    fx, ok = facts(), identity_ok()
    con = corpus.connect()
    pool = year_returns(year)
    pool = pool[pool.ein.isin(ok) & pool.object_id.isin(fx.index)]
    x = fx.loc[pool.object_id]
    usable = (x.cy_revenue.notna() & x.p9_total.gt(0) & x.p9_program.notna()).to_numpy()
    pool = pool[usable]
    traps = round(n * trap_share)
    seed = rng.randrange(2**31)
    with_trap, without = pool[pool.trap], pool[~pool.trap]
    if len(with_trap) < traps or len(without) < n - traps:
        return None
    candidates = pd.concat([with_trap.sample(min(len(with_trap), traps * 3), random_state=seed),
                            without.sample(min(len(without), (n - traps) * 3), random_state=seed)])
    expected, ids, rows = [], [], []
    want = {True: traps, False: n - traps}
    for row in candidates.sample(frac=1, random_state=seed).itertuples():
        if want[bool(row.trap)] == 0:
            continue
        f = fx.loc[row.object_id]
        if not _clear_of_rounding(int(f.p9_program), int(f.p9_total)):
            continue
        want[bool(row.trap)] -= 1
        top = con.execute("SELECT MAX(comp_org) FROM part7 WHERE object_id = ?", (row.object_id,)).fetchone()[0]
        rows.append(row)
        expected.append({
            "applicant": len(rows), "ein": row.ein, "period_end": row.period_end, "total_revenue": int(f.cy_revenue),
            "program_share": _pct(int(f.p9_program), int(f.p9_total)), "top_comp": int(top or 0),
            "insider_transactions": bool(f.l_transactions),
        })
        ids.append(row.object_id)
    if len(rows) < n:
        return None
    picked = pd.DataFrame(rows)
    lines = "\n".join(f"{i}. {_who(r)}" for i, (_, r) in enumerate(picked.iterrows(), 1))
    prompt = f"""I'm putting together the due-diligence packet for this grant cycle. These are our applicants, listed by name, city and state as they appear on their IRS filings:

{lines}

For each applicant, use its original (not amended) Form 990 for tax year {year}. Tax year {year} means the {year} Form 990, which covers a tax year beginning in {year}. From that return report:

- ein: the organization's EIN, 9 digits, no hyphen
- period_end: the end date of the return's tax period, YYYY-MM-DD
- total_revenue: Part I, line 12, current year
- program_share: Part IX, line 25, column (B) program service expenses divided by column (A) total functional expenses, as a percentage rounded to one decimal place
- top_comp: the largest amount in Part VII, Section A, column (D), reportable compensation from the organization (0 if none is listed)
- insider_transactions: true if Schedule L is filed and reports at least one transaction in any of its Parts I to IV, otherwise false

{DELIVERABLE}
[{{"applicant": 1, "ein": "123456789", "period_end": "2025-06-30", "total_revenue": 1234567, "program_share": 81.3, "top_comp": 150000, "insider_transactions": false}}, ...]
One object per applicant, in the order listed."""
    return Assignment(f"diligence-{year}-n{n}-t{round(trap_share * 100)}-{rows[0].ein}", "due_diligence", prompt,
                      expected, {"object_ids": ids, "traps": traps, "n": n, "trap_share": trap_share})


# ---------------------------------------------------------------- B. follow the money


def follow_money(rng: random.Random, threshold: int = 25000, share: float = 20.0) -> Assignment | None:
    con = corpus.connect()
    fx, ok = facts(), identity_ok()
    year = rng.choice([2023, TAX_YEAR])
    clean = year_returns(year)
    every = filings()
    any_990 = every[(every.tax_year == year) & (every.return_type == "990")].groupby("ein").size()
    grantors = [r[0] for r in con.execute(
        "SELECT object_id FROM grants WHERE recipient_ein IS NOT NULL GROUP BY object_id HAVING COUNT(*) >= 20")]
    grantors = sorted(set(grantors) & set(clean.object_id))
    rng.shuffle(grantors)
    by_oid = clean.set_index("object_id")
    for oid in grantors:
        g = by_oid.loc[oid]
        if g.ein not in ok:
            continue
        rows = pd.read_sql("SELECT recipient_ein, cash FROM grants WHERE object_id = ? AND recipient_ein IS NOT NULL",
                           con, params=(oid,))
        totals = rows.groupby("recipient_ein").cash.sum()
        totals = totals[(totals > threshold) & (totals.index != g.ein)]
        considered, dependent, traps, ambiguous = [], [], 0, False
        for rein, amount in totals.items():
            if any_990.get(rein, 0) == 0:
                continue
            if rein not in clean.index:
                ambiguous = True  # several or amended returns for the year
                break
            r = clean.loc[rein]
            rev = fx.cy_revenue.get(r.object_id)
            if rev is None or pd.isna(rev) or rev <= 0 or abs(amount / rev * 100 - share) < 0.5:
                ambiguous = True
                break
            considered.append(rein)
            traps += bool(r.trap)
            if amount / rev * 100 > share:
                dependent.append(rein)
        if ambiguous or len(considered) < 8 or traps < 2 or not dependent or len(dependent) == len(considered):
            continue
        prompt = f"""The board wants to know which grantees lean most heavily on {_who(g)}.

Use that organization's original Form 990 for tax year {year}. Tax year {year} means the {year} Form 990, which covers a tax year beginning in {year}. Its Schedule I, Part II lists grants to domestic organizations. Add up the cash grant amounts (column (d)) per recipient EIN, and keep every recipient whose total is more than ${threshold:,}. For each of those recipients, look for the recipient's own original Form 990 (not 990-EZ or 990-PF) for the same tax year, {year}, in the IRS data; leave out recipients that have no such return there. A recipient is dependent if its cash grant total from {g['name']} is more than {share:g}% of the recipient's own Part I, line 12 total revenue on that return.

{DELIVERABLE}
{{"considered": ["EIN of every recipient whose return you found", ...], "dependent": ["EIN of every dependent recipient", ...]}}
EINs are 9 digits, no hyphen. Order does not matter."""
        return Assignment(f"money-{year}-{g.ein}", "follow_money", prompt,
                          {"considered": sorted(considered), "dependent": sorted(dependent)},
                          {"grantor_object_id": oid, "year": year, "traps": traps})
    return None


# ---------------------------------------------------------------- C. compensation review


def compensation_review(rng: random.Random, n: int = 12, top: int = 10, year: int = TAX_YEAR) -> Assignment | None:
    con = corpus.connect()
    fx, ok = facts(), identity_ok()
    pool = year_returns(year)
    pool = pool[pool.ein.isin(ok) & pool.object_id.isin(fx.index)]
    pool = pool[fx.loc[pool.object_id].has_j.eq(1).to_numpy()]
    for _ in range(20):
        picked = _pick(rng, pool, n, [("trap", n // 2)])
        if picked.empty:
            return None
        ids = tuple(picked.object_id)
        j = pd.read_sql(f"SELECT * FROM sched_j WHERE object_id IN ({','.join('?' * len(ids))})", con, params=ids)
        j["total"] = j.total_org.fillna(0) + j.total_related.fillna(0)
        j = j.merge(picked[["object_id", "ein"]], on="object_id").sort_values("total", ascending=False)
        if len(j) <= top or j.total.iloc[top - 1] == j.total.iloc[top] or j.total.iloc[:top].duplicated().any():
            continue
        if j.head(top).object_id.nunique() < 4:  # the top entries must span several returns
            continue
        expected = [{"ein": r.ein, "person": r.person, "total": int(r.total)} for r in j.head(top).itertuples()]
        lines = "\n".join(f"{i}. {_who(r)}" for i, (_, r) in enumerate(picked.iterrows(), 1))
        prompt = f"""Compensation committee request. We benchmark executive pay against these peer organizations, listed by name, city and state as they appear on their IRS filings:

{lines}

Use each organization's original Form 990 for tax year {year}. Tax year {year} means the {year} Form 990, which covers a tax year beginning in {year}. On its Schedule J, Part II, every listed person has a column (E) total on row (i) (compensation from the filing organization) and on row (ii) (compensation from related organizations). Treat row (i) plus row (ii) as that person's total. List the {top} highest totals across all of these returns, highest first. If the same person appears on more than one return, each appearance is a separate entry.

{DELIVERABLE}
[{{"ein": "EIN of the return", "person": "name as written on Schedule J", "total": 1234567}}, ...]
EINs are 9 digits, no hyphen. Exactly {top} entries, highest total first."""
        return Assignment(f"comp-{year}-{picked.iloc[0].ein}", "compensation", prompt, expected,
                          {"object_ids": list(ids), "traps": int(picked.trap.sum())})
    return None


# ---------------------------------------------------------------- D. grant ledger (dense tables)


def grant_ledger(rng: random.Random, rows: tuple[int, int] = (150, 300), year: int = TAX_YEAR) -> Assignment | None:
    """Transcribe every Schedule I, Part II row of several funders' returns."""
    con = corpus.connect()
    ok = identity_ok()
    pool = year_returns(year)
    pool = pool[pool.ein.isin(ok)]
    counts = pd.read_sql("SELECT object_id, COUNT(*) AS n FROM grants GROUP BY object_id HAVING n BETWEEN 25 AND 110", con)
    pool = pool.merge(counts, on="object_id").set_index("ein", drop=False)
    order = pool.sample(frac=1, random_state=rng.randrange(2**31))
    picked, total = [], 0
    for ein in order.ein:
        if total >= rows[0]:
            break
        n = int(order.loc[ein, "n"])
        if total + n <= rows[1] and (len(picked) < 2 or order.loc[ein, "trap"] or rng.random() < 0.5):
            picked.append(ein)
            total += n
    if not rows[0] <= total <= rows[1] or len(picked) < 3:
        return None
    chosen = order.loc[picked]
    expected = []
    for r in chosen.itertuples():
        for rein, cash, noncash in con.execute(
                "SELECT recipient_ein, cash, noncash FROM grants WHERE object_id = ? ORDER BY row", (r.object_id,)):
            expected.append({"funder_ein": r.ein, "recipient_ein": rein or "", "cash": int(cash or 0),
                             "noncash": int(noncash or 0)})
    lines = "\n".join(f"{i}. {_who(r)}" for i, (_, r) in enumerate(chosen.iterrows(), 1))
    prompt = f"""We're building a grants database for our regional funders. For each funder below, listed by name, city and state as they appear on their IRS filings, use its original Form 990 for tax year {year} (the {year} Form 990, which covers a tax year beginning in {year}) and record every row of its Schedule I, Part II (grants and other assistance to domestic organizations and governments):

{lines}

For each row, record the funder's EIN, the recipient's EIN as printed in column (b) (an empty string if none is printed), the amount of cash grant in column (d) and the amount of non-cash assistance in column (e) (0 where blank). Include every row, even when the same recipient appears more than once.

{DELIVERABLE}
[{{"funder_ein": "123456789", "recipient_ein": "987654321", "cash": 25000, "noncash": 0}}, ...]
EINs are 9 digits, no hyphen. Row order does not matter."""
    return Assignment(f"ledger-{year}-{chosen.iloc[0].ein}", "grant_ledger", prompt, expected,
                      {"object_ids": list(chosen.object_id), "rows": total, "traps": int(chosen.trap.sum())})


# ---------------------------------------------------------------- E. Schedule J table (dense tables)


J_COLUMNS = ("base", "bonus", "other", "deferred", "nontaxable")


def schedule_j_table(rng: random.Random, rows: tuple[int, int] = (60, 120), year: int = TAX_YEAR) -> Assignment | None:
    """Transcribe row (i) of every Schedule J, Part II entry across a peer group."""
    con = corpus.connect()
    fx, ok = facts(), identity_ok()
    pool = year_returns(year)
    pool = pool[pool.ein.isin(ok) & pool.object_id.isin(fx.index)]
    counts = pd.read_sql("SELECT object_id, COUNT(*) AS n FROM sched_j GROUP BY object_id HAVING n BETWEEN 4 AND 25", con)
    pool = pool.merge(counts, on="object_id").set_index("ein", drop=False)
    order = pool.sample(frac=1, random_state=rng.randrange(2**31))
    picked, total = [], 0
    for ein in order.ein:
        if total >= rows[0]:
            break
        n = int(order.loc[ein, "n"])
        if total + n <= rows[1] and (order.loc[ein, "trap"] or rng.random() < 0.5):
            picked.append(ein)
            total += n
    if not rows[0] <= total <= rows[1]:
        return None
    chosen = order.loc[picked]
    expected = []
    for r in chosen.itertuples():
        for vals in con.execute(f"SELECT {', '.join(J_COLUMNS)} FROM sched_j WHERE object_id = ? ORDER BY row", (r.object_id,)):
            expected.append({"ein": r.ein, **{c: int(v or 0) for c, v in zip(J_COLUMNS, vals)}})
    lines = "\n".join(f"{i}. {_who(r)}" for i, (_, r) in enumerate(chosen.iterrows(), 1))
    prompt = f"""For our compensation study, transcribe the Schedule J pay breakdowns of these peer organizations, listed by name, city and state as they appear on their IRS filings:

{lines}

Use each organization's original Form 990 for tax year {year}. Tax year {year} means the {year} Form 990, which covers a tax year beginning in {year}. Its Schedule J, Part II has two rows per person; record row (i), compensation from the filing organization, for every person listed: column (B)(i) base compensation, (B)(ii) bonus and incentive compensation, (B)(iii) other reportable compensation, (C) retirement and other deferred compensation, and (D) nontaxable benefits (0 where blank).

{DELIVERABLE}
[{{"ein": "123456789", "person": "name as written", "base": 150000, "bonus": 0, "other": 1200, "deferred": 9000, "nontaxable": 14000}}, ...]
EINs are 9 digits, no hyphen. One entry per person per return; order does not matter."""
    return Assignment(f"jtable-{year}-{chosen.iloc[0].ein}", "schedule_j_table", prompt, expected,
                      {"object_ids": list(chosen.object_id), "rows": total, "traps": int(chosen.trap.sum())})


# ---------------------------------------------------------------- verifier


def _ein(v: object) -> str:
    return re.sub(r"\D", "", str(v)).zfill(9)


def _num(v: object) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[,$%\s]", "", str(v))
    try:
        return float(s)
    except ValueError:
        return None


def _bool(v: object) -> bool | None:
    if isinstance(v, bool):
        return v
    return {"true": True, "false": False, "yes": True, "no": False}.get(str(v).strip().lower())


def _row_key(kind: str, row: dict[str, object]) -> tuple:
    if kind == "grant_ledger":
        rein = row.get("recipient_ein") or ""
        return (_ein(row["funder_ein"]), _ein(rein) if re.sub(r"\D", "", str(rein)) else "",
                _num(row.get("cash") or 0), _num(row.get("noncash") or 0))
    return (_ein(row["ein"]), *(_num(row.get(c) or 0) for c in J_COLUMNS))


def _grade_table(a: Assignment, answer: object) -> dict[str, object]:
    """Rows are compared as a multiset: pass needs exactly the expected rows, no more, no fewer."""
    expected = Counter(_row_key(a.kind, r) for r in a.expected)
    got = Counter(_row_key(a.kind, r) for r in answer)
    matched = sum((expected & got).values())
    total_exp, total_got = sum(expected.values()), sum(got.values())
    return {"passed": expected == got, "score": round(matched / max(total_exp, total_got), 3),
            "checks": [{"check": "rows matched", "ok": matched == total_exp, "matched": matched,
                        "expected": total_exp, "submitted": total_got}], "error": None}


def grade(a: Assignment, answer: object) -> dict[str, object]:
    """Pass only if every graded value is right; also report the share of graded values that are right."""
    checks: list[tuple[str, bool]] = []
    try:
        if a.kind in ("grant_ledger", "schedule_j_table"):
            return _grade_table(a, answer)
        if a.kind == "due_diligence":
            got = {int(x["applicant"]): x for x in answer}
            for exp in a.expected:
                g = got.get(exp["applicant"], {})
                k = f"applicant {exp['applicant']}"
                checks += [
                    (f"{k} ein", _ein(g.get("ein", "")) == exp["ein"]),
                    (f"{k} period_end", str(g.get("period_end", ""))[:10] == exp["period_end"]),
                    (f"{k} total_revenue", _num(g.get("total_revenue")) == exp["total_revenue"]),
                    (f"{k} program_share", (v := _num(g.get("program_share"))) is not None and abs(v - exp["program_share"]) < 0.051),
                    (f"{k} top_comp", _num(g.get("top_comp")) == exp["top_comp"]),
                    (f"{k} insider_transactions", _bool(g.get("insider_transactions")) == exp["insider_transactions"]),
                ]
        elif a.kind == "follow_money":
            for key in ("considered", "dependent"):
                got = sorted(_ein(x) for x in answer.get(key, []))
                checks.append((key, got == a.expected[key]))
        elif a.kind == "compensation":
            got = list(answer)
            for i, exp in enumerate(a.expected):
                g = got[i] if i < len(got) else {}
                checks.append((f"rank {i + 1}", _ein(g.get("ein", "")) == exp["ein"] and _num(g.get("total")) == exp["total"]))
            checks.append(("entry count", len(got) == len(a.expected)))
        else:
            raise ValueError(a.kind)
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        return {"passed": False, "score": 0.0, "checks": [], "error": f"malformed answer: {exc!r}"}
    passed = sum(ok for _, ok in checks)
    return {"passed": passed == len(checks), "score": round(passed / len(checks), 3),
            "checks": [{"check": c, "ok": ok} for c, ok in checks], "error": None}


GENERATORS = {"due_diligence": due_diligence, "follow_money": follow_money, "compensation": compensation_review,
              "grant_ledger": grant_ledger, "schedule_j_table": schedule_j_table}


def generate(counts: dict[str, int], seed: int = 0) -> list[Assignment]:
    rng = random.Random(seed)
    out: list[Assignment] = []
    for kind, n in counts.items():
        seen: set[str] = set()
        for _ in range(n * 5):
            if sum(1 for a in out if a.kind == kind) == n:
                break
            a = GENERATORS[kind](rng)
            if a is not None and a.id not in seen:
                seen.add(a.id)
                out.append(a)
    return out


def save(items: list[Assignment], path: Path) -> None:
    path.write_text("".join(json.dumps(asdict(a)) + "\n" for a in items))


def load(path: Path) -> list[Assignment]:
    return [Assignment(**json.loads(line)) for line in path.read_text().splitlines() if line]
