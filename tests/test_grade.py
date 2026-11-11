"""The grader: which answer formats count as right, and what fails a deliverable."""

from bench990.assignments import Assignment, grade

DILIGENCE = Assignment("d", "due_diligence", "", [
    {"applicant": 1, "ein": "012345678", "period_end": "2024-06-30", "total_revenue": 1000, "program_share": 81.3,
     "top_comp": 50000, "insider_transactions": False},
    {"applicant": 2, "ein": "987654321", "period_end": "2023-12-31", "total_revenue": -2000, "program_share": 0.0,
     "top_comp": 0, "insider_transactions": True},
])
COMPENSATION = Assignment("c", "compensation", "", [{"ein": "111111111", "person": "A", "total": 300},
                                                    {"ein": "222222222", "person": "B", "total": 200}])
LEDGER_ROWS = [{"funder_ein": "111111111", "recipient_ein": "222222222", "cash": 5000, "noncash": 0},
               {"funder_ein": "111111111", "recipient_ein": "222222222", "cash": 5000, "noncash": 0},
               {"funder_ein": "111111111", "recipient_ein": "", "cash": 900, "noncash": 100}]
LEDGER = Assignment("l", "grant_ledger", "", LEDGER_ROWS)


def _answer(applicant: int = 1, **overrides: object) -> list[dict[str, object]]:
    rows = [dict(r) for r in DILIGENCE.expected]
    rows[applicant - 1].update(overrides)
    return rows


def test_equivalent_formats_pass() -> None:
    answer = _answer(ein="01-2345678", total_revenue="$1,000", program_share="81.3%", insider_transactions="false")
    assert grade(DILIGENCE, answer)["passed"]


def test_ein_written_as_a_number_keeps_its_leading_zero() -> None:
    assert grade(DILIGENCE, _answer(ein=12345678))["passed"]


def test_one_wrong_cell_fails_whole_deliverable() -> None:
    result = grade(DILIGENCE, _answer(top_comp=50001))
    assert not result["passed"]
    assert result["score"] == round(11 / 12, 3)


def test_rounding_tolerance_is_half_a_tenth() -> None:
    assert grade(DILIGENCE, _answer(program_share=81.35))["passed"]
    assert not grade(DILIGENCE, _answer(program_share=81.4))["passed"]


def test_negative_amounts_keep_their_sign() -> None:
    assert grade(DILIGENCE, _answer(2, total_revenue="-2,000"))["passed"]
    assert not grade(DILIGENCE, _answer(2, total_revenue=2000))["passed"]


def test_missing_value_is_not_read_as_zero_or_false() -> None:
    for field, blank in (("top_comp", None), ("program_share", ""), ("insider_transactions", None)):
        assert not grade(DILIGENCE, _answer(2, **{field: blank}))["passed"], field
    omitted = _answer()
    del omitted[1]["top_comp"]
    assert not grade(DILIGENCE, omitted)["passed"]


def test_missing_applicant_fails() -> None:
    assert not grade(DILIGENCE, _answer()[:1])["passed"]


def test_malformed_answer_scores_zero() -> None:
    for assignment in (DILIGENCE, COMPENSATION, LEDGER):
        for answer in ({"not": "a list"}, None, ["not a row"]):
            result = grade(assignment, answer)
            assert not result["passed"] and result["score"] == 0.0 and result["error"]


def test_follow_money_is_order_insensitive_but_exact() -> None:
    a = Assignment("m", "follow_money", "", {"considered": ["111111111", "222222222"], "dependent": ["222222222"]})
    assert grade(a, {"considered": ["222222222", "11-1111111"], "dependent": ["222222222"]})["passed"]
    assert not grade(a, {"considered": ["222222222", "111111111"], "dependent": []})["passed"]
    assert not grade(a, {"considered": ["222222222", "111111111", "333333333"], "dependent": ["222222222"]})["passed"]


def test_compensation_order_matters() -> None:
    right = [{"ein": "111111111", "person": "x", "total": 300}, {"ein": "222222222", "person": "y", "total": 200}]
    assert grade(COMPENSATION, right)["passed"]
    assert not grade(COMPENSATION, right[::-1])["passed"]


def test_compensation_needs_exactly_the_requested_entries() -> None:
    right = [{"ein": "111111111", "total": 300}, {"ein": "222222222", "total": 200}]
    assert not grade(COMPENSATION, right + [{"ein": "333333333", "total": 100}])["passed"]
    assert not grade(COMPENSATION, right[:1])["passed"]


def test_ledger_rows_are_a_multiset() -> None:
    rows = LEDGER_ROWS
    assert grade(LEDGER, [rows[2], {**rows[0], "recipient_ein": "22-2222222", "cash": "$5,000"}, rows[1]])["passed"]
    missing_duplicate = grade(LEDGER, rows[1:])
    assert not missing_duplicate["passed"] and missing_duplicate["score"] == round(2 / 3, 3)
    assert not grade(LEDGER, rows + [rows[2]])["passed"]
    nothing = grade(LEDGER, [])
    assert not nothing["passed"] and nothing["score"] == 0.0
