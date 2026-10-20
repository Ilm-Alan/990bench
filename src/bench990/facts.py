"""Extract the facts reference solutions need into SQLite tables, in parallel per batch.

Tables (Form 990 only; 990-EZ and 990-PF lack these parts):
- `facts`: one row per filing with the Part I and Part IX totals assignments use, plus Schedule J and L flags.
- `grants`: Schedule I Part II rows (grants to domestic organizations).
- `sched_j`: Schedule J Part II rows (compensation of officers and key employees).
- `part7`: Part VII Section A rows.
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from lxml import etree

from . import corpus
from .corpus import NS, local, text

# Form 990 amounts kept per filing: column name -> path under IRS990.
FACT_FIELDS = {
    "cy_revenue": "CYTotalRevenueAmt",                         # Part I line 12, current year
    "p9_total": "TotalFunctionalExpensesGrp/TotalAmt",         # Part IX line 25, column (A)
    "p9_program": "TotalFunctionalExpensesGrp/ProgramServicesAmt",  # Part IX line 25, column (B)
}
FACT_COLUMNS = ("object_id", *FACT_FIELDS, "has_j", "l_transactions")

SCHEMA = f"""
DROP TABLE IF EXISTS facts; DROP TABLE IF EXISTS grants; DROP TABLE IF EXISTS sched_j; DROP TABLE IF EXISTS part7;
CREATE TABLE facts (object_id TEXT PRIMARY KEY, {', '.join(f'{c} INTEGER' for c in FACT_COLUMNS[1:])});
CREATE TABLE grants (object_id TEXT, row INTEGER, recipient_ein TEXT, recipient_name TEXT, cash INTEGER, noncash INTEGER, state TEXT);
CREATE TABLE sched_j (
  object_id TEXT, row INTEGER, person TEXT, title TEXT, base INTEGER, bonus INTEGER, other INTEGER, deferred INTEGER,
  nontaxable INTEGER, total_org INTEGER, total_related INTEGER
);
CREATE TABLE part7 (object_id TEXT, row INTEGER, person TEXT, title TEXT, comp_org INTEGER, comp_related INTEGER, other_comp INTEGER);
"""
INDEXES = """
CREATE INDEX grants_obj ON grants(object_id); CREATE INDEX grants_rec ON grants(recipient_ein);
CREATE INDEX sched_j_obj ON sched_j(object_id); CREATE INDEX part7_obj ON part7(object_id);
"""
L_GROUPS = ("DisqualifiedPersonExBnftTrGrp", "LoansBtwnOrgInterestedPrsnGrp", "GrntAsstBnftInterestedPrsnGrp", "BusTrInvolveInterestedPrsnGrp")


def _int(el: etree._Element | None, path: str) -> int | None:
    v = text(el, path)
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def _name(el: etree._Element) -> str | None:
    return text(el, "PersonNm") or text(el, "BusinessName/BusinessNameLine1Txt")


def extract(object_id: str, data: etree._Element) -> tuple[tuple, list[tuple], list[tuple], list[tuple]]:
    m = data.find(NS + "IRS990")
    sched = {local(d.tag): d for d in data if isinstance(d.tag, str)}
    sl = sched.get("IRS990ScheduleL")
    l_txn = sum(len(sl.findall(NS + g)) for g in L_GROUPS) if sl is not None else 0
    fact = (object_id, *(_int(m, path) for path in FACT_FIELDS.values()),
            int("IRS990ScheduleJ" in sched), l_txn)
    grants = []
    if (si := sched.get("IRS990ScheduleI")) is not None:
        for i, g in enumerate(si.findall(NS + "RecipientTable"), 1):
            grants.append((object_id, i, text(g, "RecipientEIN"), text(g, "RecipientBusinessName/BusinessNameLine1Txt"),
                           _int(g, "CashGrantAmt"), _int(g, "NonCashAssistanceAmt"), text(g, "USAddress/StateAbbreviationCd")))
    js = []
    if (sj := sched.get("IRS990ScheduleJ")) is not None:
        for i, g in enumerate(sj.findall(NS + "RltdOrgOfficerTrstKeyEmplGrp"), 1):
            js.append((object_id, i, _name(g), text(g, "TitleTxt"), _int(g, "BaseCompensationFilingOrgAmt"),
                       _int(g, "BonusFilingOrganizationAmount"), _int(g, "OtherCompensationFilingOrgAmt"),
                       _int(g, "DeferredCompensationFlngOrgAmt"), _int(g, "NontaxableBenefitsFilingOrgAmt"),
                       _int(g, "TotalCompensationFilingOrgAmt"), _int(g, "TotalCompensationRltdOrgsAmt")))
    p7 = [
        (object_id, i, _name(g), text(g, "TitleTxt"), _int(g, "ReportableCompFromOrgAmt"),
         _int(g, "ReportableCompFromRltdOrgAmt"), _int(g, "OtherCompensationAmt"))
        for i, g in enumerate(m.findall(NS + "Form990PartVIISectionAGrp"), 1)
    ]
    return fact, grants, js, p7


def _batch(job: tuple[str, list[str]]) -> tuple[list, list, list, list]:
    """Worker: no database access, so the parent can write while workers parse."""
    batch, ids = job
    out: tuple[list, list, list, list] = ([], [], [], [])
    for oid in ids:
        root = corpus.load_xml(batch, oid)
        fact, grants, js, p7 = extract(oid, root.find(NS + "ReturnData"))
        out[0].append(fact)
        out[1].extend(grants)
        out[2].extend(js)
        out[3].extend(p7)
    return out


def build(workers: int = 8) -> None:
    con = corpus.connect()
    con.executescript(SCHEMA)
    jobs = defaultdict(list)
    for batch, oid in con.execute("SELECT batch, object_id FROM filings WHERE return_type = '990' ORDER BY batch"):
        jobs[batch].append(oid)
    with ProcessPoolExecutor(workers) as pool:
        for batch, (facts, grants, js, p7) in zip(jobs, pool.map(_batch, jobs.items())):
            con.executemany(f"INSERT INTO facts VALUES ({','.join('?' * len(FACT_COLUMNS))})", facts)
            con.executemany("INSERT INTO grants VALUES (?,?,?,?,?,?,?)", grants)
            con.executemany(f"INSERT INTO sched_j VALUES ({','.join('?' * 11)})", js)
            con.executemany("INSERT INTO part7 VALUES (?,?,?,?,?,?,?)", p7)
            con.commit()
            print(f"{batch}: {len(facts)} filings, {len(grants)} grants, {len(js)} J rows", flush=True)
    con.executescript(INDEXES)
    con.commit()


if __name__ == "__main__":
    build()
