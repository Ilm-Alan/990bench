"""Both ground-truth routes, end to end, on a five-return synthetic corpus.

The generator reads the SQLite catalog and fact tables; the cross-check finds returns through the
IRS index CSV and reads the XML with its own XPaths. Here both run on hand-written returns whose
correct answers are written out below, so a wrong path, a lost sign or a wrong-year return in
either route fails the test.
"""

from __future__ import annotations

import copy
import random
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from bench990 import assignments as A
from bench990 import corpus, crosscheck, facts

CACHES = (A.filings, A.facts, A.bmf, A.identity_ok, A.year_returns, crosscheck.index, corpus._zip, corpus._members)

RETURN = """<Return xmlns="http://www.irs.gov/efile" returnVersion="2024v5.0">
  <ReturnHeader>
    <TaxPeriodEndDt>{end}</TaxPeriodEndDt>
    <ReturnTypeCd>990</ReturnTypeCd>
    <TaxPeriodBeginDt>{begin}</TaxPeriodBeginDt>
    <Filer>
      <EIN>{ein}</EIN>
      <BusinessName><BusinessNameLine1Txt>{name}</BusinessNameLine1Txt></BusinessName>
      <USAddress><CityNm>{city}</CityNm><StateAbbreviationCd>OH</StateAbbreviationCd></USAddress>
    </Filer>
    <TaxYr>{tax_year}</TaxYr>
  </ReturnHeader>
  <ReturnData>
    <IRS990>
      {amended}
      <CYTotalRevenueAmt>{revenue}</CYTotalRevenueAmt>
      {part7}
      <TotalFunctionalExpensesGrp>
        <TotalAmt>{expenses}</TotalAmt>
        <ProgramServicesAmt>{program}</ProgramServicesAmt>
      </TotalFunctionalExpensesGrp>
    </IRS990>
    {schedule_l}
  </ReturnData>
</Return>"""
PART7 = "<Form990PartVIISectionAGrp><PersonNm>{}</PersonNm><ReportableCompFromOrgAmt>{}</ReportableCompFromOrgAmt></Form990PartVIISectionAGrp>"

CALENDAR, FISCAL, AMENDED, NAMESAKE = "010000001", "020000002", "030000003", "040000004"
# object_id -> (batch zip holding it, batch named in the index, return fields)
RETURNS = {
    # Calendar-year filer: two Part VII rows, Schedule L filed with no transactions.
    "202500000000000001": ("2025_TEOS_XML_05A", "2025_TEOS_XML_05a", dict(
        ein=CALENDAR, name="ALDER FOOD BANK", city="AKRON", tax_year=2024, begin="2024-01-01", end="2024-12-31",
        amended="", revenue=1250000, expenses=1000000, program=813000,
        part7=PART7.format("A", 90000) + PART7.format("B", 116723), schedule_l="<IRS990ScheduleL/>")),
    # June fiscal year: the tax-year-2023 return ends in 2024 (the trap) and must not be used.
    "202400000000000002": ("2025_TEOS_XML_05A", "2025_TEOS_XML_05a", dict(
        ein=FISCAL, name="BIRCH CLINIC", city="DAYTON", tax_year=2023, begin="2023-07-01", end="2024-06-30",
        amended="", revenue=999, expenses=100000, program=50000, part7=PART7.format("C", 70000), schedule_l="")),
    # Its tax-year-2024 return: negative revenue, no Part VII rows, one Schedule L transaction. The IRS
    # index names the first half of a split batch for returns stored in the second.
    "202500000000000002": ("2025_TEOS_XML_05B", "2025_TEOS_XML_05a", dict(
        ein=FISCAL, name="BIRCH CLINIC", city="DAYTON", tax_year=2024, begin="2024-07-01", end="2025-06-30",
        amended="", revenue=-5273, expenses=200000, program=150400, part7="",
        schedule_l="<IRS990ScheduleL><BusTrInvolveInterestedPrsnGrp/></IRS990ScheduleL>")),
    # An original and an amended return for the same year: no single return to grade against.
    "202500000000000003": ("2025_TEOS_XML_05A", "2025_TEOS_XML_05a", dict(
        ein=AMENDED, name="CEDAR ARTS", city="TOLEDO", tax_year=2024, begin="2024-01-01", end="2024-12-31",
        amended="", revenue=500, expenses=400, program=300, part7="", schedule_l="")),
    "202500000000000033": ("2025_TEOS_XML_05A", "2025_TEOS_XML_05a", dict(
        ein=AMENDED, name="CEDAR ARTS", city="TOLEDO", tax_year=2024, begin="2024-01-01", end="2024-12-31",
        amended="<AmendedReturnInd>X</AmendedReturnInd>", revenue=600, expenses=400, program=300, part7="", schedule_l="")),
    # A clean return whose name, city and state also belong to another EIN in the Business Master File.
    "202500000000000004": ("2025_TEOS_XML_05A", "2025_TEOS_XML_05a", dict(
        ein=NAMESAKE, name="DOGWOOD TRUST", city="CANTON", tax_year=2024, begin="2024-01-01", end="2024-12-31",
        amended="", revenue=700, expenses=400, program=300, part7="", schedule_l="")),
}
BMF = [(CALENDAR, "ALDER FOOD BANK", "AKRON"), (FISCAL, "BIRCH CLINIC", "DAYTON"), (AMENDED, "CEDAR ARTS", "TOLEDO"),
       (NAMESAKE, "DOGWOOD TRUST", "CANTON"), ("049999999", "DOGWOOD TRUST", "CANTON")]
ANSWERS = {
    CALENDAR: {"period_end": "2024-12-31", "total_revenue": 1250000, "program_share": 81.3, "top_comp": 116723,
               "insider_transactions": False},
    FISCAL: {"period_end": "2025-06-30", "total_revenue": -5273, "program_share": 75.2, "top_comp": 0,
             "insider_transactions": True},
}


@pytest.fixture
def assignment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[A.Assignment]:
    """A two-applicant due-diligence assignment generated from the synthetic corpus."""
    raw = tmp_path / "raw"
    raw.mkdir()
    monkeypatch.setattr(corpus, "RAW", raw)
    monkeypatch.setattr(crosscheck, "RAW", raw)
    monkeypatch.setattr(corpus, "DB", tmp_path / "corpus.sqlite")
    # The builders fan out to worker processes, which would not see the patched paths.
    monkeypatch.setattr(corpus, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(facts, "ProcessPoolExecutor", ThreadPoolExecutor)
    for cached in CACHES:
        cached.cache_clear()

    columns = "RETURN_ID,FILING_TYPE,EIN,TAX_PERIOD,SUB_DATE,TAXPAYER_NAME,RETURN_TYPE,DLN,OBJECT_ID,XML_BATCH_ID\n"
    rows = []
    for object_id, (stored_in, indexed_as, fields) in RETURNS.items():
        with zipfile.ZipFile(raw / f"{stored_in}.zip", "a") as zf:
            zf.writestr(f"{object_id}_public.xml", RETURN.format(**fields))
        rows.append(f",EFILE,{fields['ein']},{fields['end'][:4]}{fields['end'][5:7]},2025,{fields['name']},990,,{object_id},{indexed_as}\n")
    (raw / "index_2025.csv").write_text(columns + "".join(rows))
    for year in (2024, 2026):
        (raw / f"index_{year}.csv").write_text(columns)
    (raw / "bmf_eo1.csv").write_text("EIN,NAME,CITY,STATE\n" + "".join(f"{ein},{name},{city},OH\n" for ein, name, city in BMF))
    corpus.build(sorted({stored_in for stored_in, _, _ in RETURNS.values()}), workers=1)
    facts.build(workers=1)

    made = A.due_diligence(random.Random(0), n=2, trap_share=0.5)
    assert made is not None
    yield made
    for cached in CACHES:
        cached.cache_clear()


def test_generator_uses_the_one_unambiguous_return_and_its_values(assignment: A.Assignment) -> None:
    answers = {row["ein"]: {k: v for k, v in row.items() if k not in ("applicant", "ein")} for row in assignment.expected}
    assert answers == ANSWERS
    assert assignment.meta["traps"] == 1
    assert sorted(assignment.meta["object_ids"]) == ["202500000000000001", "202500000000000002"]
    assert AMENDED not in A.year_returns(2024).index
    assert NAMESAKE not in A.identity_ok()


def test_second_route_agrees_with_the_generator(assignment: A.Assignment) -> None:
    assert crosscheck.check(assignment)


@pytest.mark.parametrize(("field", "wrong"), [
    ("period_end", "2024-06-30"), ("total_revenue", 5273), ("program_share", 75.3), ("top_comp", 90000),
    ("insider_transactions", False),
])
def test_second_route_rejects_a_reference_answer_it_cannot_reproduce(assignment: A.Assignment, field: str, wrong: object) -> None:
    drifted = copy.deepcopy(assignment)
    row = next(r for r in drifted.expected if r["ein"] == FISCAL)
    row[field] = wrong
    assert not crosscheck.check(drifted)


def test_second_route_refuses_an_organization_without_a_single_original_return(assignment: A.Assignment) -> None:
    with pytest.raises(ValueError, match=AMENDED):
        crosscheck.the_return(AMENDED, 2024)
    with pytest.raises(ValueError, match=CALENDAR):
        crosscheck.the_return(CALENDAR, 2023)
    ambiguous = copy.deepcopy(assignment)
    ambiguous.expected[0]["ein"] = AMENDED
    assert not crosscheck.check(ambiguous)
