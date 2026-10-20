"""Recompute every assignment's answer by a second, independent route and compare.

The generators read the SQLite catalog and fact tables. This module instead locates returns
through the IRS index CSVs (as an analyst would) and reads every value straight from the XML
with its own XPaths. An assignment is only kept if both routes agree.

    python -m bench990.crosscheck data/assignments.jsonl
"""

from __future__ import annotations

import sys
from functools import cache
from pathlib import Path

import pandas as pd
from lxml import etree

from . import assignments as A
from . import corpus
from .corpus import RAW

NS = {"e": "http://www.irs.gov/efile"}


@cache
def index() -> pd.DataFrame:
    df = pd.concat(pd.read_csv(RAW / f"index_{y}.csv", dtype=str) for y in (2024, 2025, 2026))
    df["XML_BATCH_ID"] = df.XML_BATCH_ID.str.upper()
    return df[df.RETURN_TYPE.isin(["990", "990EZ", "990PF"])].drop_duplicates("OBJECT_ID")


def xml(row: pd.Series) -> etree._Element:
    # The index labels both halves of a split batch with the "A" name.
    for batch in (row.XML_BATCH_ID, row.XML_BATCH_ID[:-1] + "B"):
        if (RAW / f"{batch}.zip").exists() and row.OBJECT_ID in corpus._members(batch):
            return corpus.load_xml(batch, row.OBJECT_ID)
    raise KeyError(row.OBJECT_ID)


def val(root: etree._Element, path: str) -> str | None:
    found = root.xpath(path, namespaces=NS)
    return found[0].text.strip() if found and found[0].text else None


def num(root: etree._Element, path: str) -> int | None:
    v = val(root, path)
    return int(v) if v is not None else None


def returns_for(ein: str) -> list[tuple[pd.Series, etree._Element]]:
    rows = index()[index().EIN == ein]
    return [(r, xml(r)) for _, r in rows.iterrows()]


def amended(root: etree._Element) -> bool:
    return val(root, "//e:ReturnData/*[1]/e:AmendedReturnInd") in {"X", "true", "1"}


def header(root: etree._Element, field: str) -> str | None:
    return val(root, f"/e:Return/e:ReturnHeader/{field}")


def originals_990(ein: str, tax_year: int) -> list[etree._Element]:
    return [root for _, root in returns_for(ein)
            if header(root, "e:ReturnTypeCd") == "990" and not amended(root) and int(header(root, "e:TaxYr")) == tax_year]


def the_return(ein: str, tax_year: int) -> etree._Element:
    """The organization's single original Form 990 for the tax year; anything else is ambiguous."""
    same_year = [root for _, root in returns_for(ein) if int(header(root, "e:TaxYr")) == tax_year]
    if len(same_year) != 1 or header(same_year[0], "e:ReturnTypeCd") != "990" or amended(same_year[0]):
        raise ValueError(f"{ein} has no single original Form 990 for {tax_year}")
    return same_year[0]


def _year(a: A.Assignment) -> int:
    return int(a.id.split("-")[1])


def due_diligence(a: A.Assignment) -> object:
    out = []
    f = "/e:Return/e:ReturnData/e:IRS990"
    for exp in a.expected:
        r = the_return(exp["ein"], _year(a))
        comps = [int(x.text) for x in r.xpath(f"{f}/e:Form990PartVIISectionAGrp/e:ReportableCompFromOrgAmt", namespaces=NS)]
        l_entries = r.xpath("//e:IRS990ScheduleL/*[self::e:DisqualifiedPersonExBnftTrGrp or self::e:LoansBtwnOrgInterestedPrsnGrp"
                            " or self::e:GrntAsstBnftInterestedPrsnGrp or self::e:BusTrInvolveInterestedPrsnGrp]", namespaces=NS)
        out.append({
            "applicant": exp["applicant"], "ein": exp["ein"], "period_end": header(r, "e:TaxPeriodEndDt"),
            "total_revenue": num(r, f"{f}/e:CYTotalRevenueAmt"),
            "program_share": round(num(r, f"{f}/e:TotalFunctionalExpensesGrp/e:ProgramServicesAmt")
                                   / num(r, f"{f}/e:TotalFunctionalExpensesGrp/e:TotalAmt") * 100 + 1e-9, 1),
            "top_comp": max(comps, default=0), "insider_transactions": bool(l_entries),
        })
    return out


def follow_money(a: A.Assignment) -> object:
    oid = a.meta["grantor_object_id"]
    row = index()[index().OBJECT_ID == oid].iloc[0]
    root = xml(row)
    year = int(header(root, "e:TaxYr"))
    totals: dict[str, int] = {}
    for g in root.xpath("//e:IRS990ScheduleI/e:RecipientTable", namespaces=NS):
        ein = val(g, "e:RecipientEIN")
        if ein:
            totals[ein] = totals.get(ein, 0) + (num(g, "e:CashGrantAmt") or 0)
    considered, dependent = [], []
    for ein, amount in totals.items():
        if amount <= 25000 or ein == row.EIN:
            continue
        rets = originals_990(ein, year)
        if not rets:
            continue
        if len(rets) > 1:
            raise ValueError(f"recipient {ein} has several original returns for {year}")
        rev = num(rets[0], "/e:Return/e:ReturnData/e:IRS990/e:CYTotalRevenueAmt")
        considered.append(ein)
        if amount / rev * 100 > 20:
            dependent.append(ein)
    return {"considered": sorted(considered), "dependent": sorted(dependent)}


def compensation(a: A.Assignment) -> object:
    year = _year(a)
    eins = _eins(a)
    entries = []
    for ein in eins:
        r = the_return(ein, year)
        for g in r.xpath("//e:IRS990ScheduleJ/e:RltdOrgOfficerTrstKeyEmplGrp", namespaces=NS):
            total = (num(g, "e:TotalCompensationFilingOrgAmt") or 0) + (num(g, "e:TotalCompensationRltdOrgsAmt") or 0)
            entries.append({"ein": ein, "total": total})
    entries.sort(key=lambda e: -e["total"])
    return entries[: len(a.expected)]


def _eins(a: A.Assignment) -> list[str]:
    return [index()[index().OBJECT_ID == oid].iloc[0].EIN for oid in a.meta["object_ids"]]


def grant_ledger(a: A.Assignment) -> object:
    rows = []
    for ein in _eins(a):
        for g in the_return(ein, _year(a)).xpath("//e:IRS990ScheduleI/e:RecipientTable", namespaces=NS):
            rows.append({"funder_ein": ein, "recipient_ein": val(g, "e:RecipientEIN") or "",
                         "cash": num(g, "e:CashGrantAmt") or 0, "noncash": num(g, "e:NonCashAssistanceAmt") or 0})
    return rows


J_FIELDS = {"base": "BaseCompensationFilingOrgAmt", "bonus": "BonusFilingOrganizationAmount",
            "other": "OtherCompensationFilingOrgAmt", "deferred": "DeferredCompensationFlngOrgAmt",
            "nontaxable": "NontaxableBenefitsFilingOrgAmt"}


def schedule_j_table(a: A.Assignment) -> object:
    rows = []
    for ein in _eins(a):
        for g in the_return(ein, _year(a)).xpath("//e:IRS990ScheduleJ/e:RltdOrgOfficerTrstKeyEmplGrp", namespaces=NS):
            rows.append({"ein": ein, **{k: num(g, f"e:{v}") or 0 for k, v in J_FIELDS.items()}})
    return rows


ROUTES = {"due_diligence": due_diligence, "follow_money": follow_money, "compensation": compensation,
          "grant_ledger": grant_ledger, "schedule_j_table": schedule_j_table}


def check(a: A.Assignment) -> bool:
    try:
        independent = ROUTES[a.kind](a)
    except ValueError as exc:
        print(f"  ambiguous: {exc}")
        return False
    if a.kind == "compensation":
        independent = [dict(e, person="") for e in independent]
    return A.grade(a, independent)["passed"]


def main() -> None:
    items = A.load(Path(sys.argv[1]))
    bad = 0
    for a in items:
        ok = check(a)
        bad += not ok
        print(f"{'AGREE' if ok else 'DISAGREE'} {a.kind:14} {a.id}", flush=True)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
