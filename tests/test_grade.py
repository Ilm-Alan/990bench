from bench990.assignments import Assignment, grade

DILIGENCE = Assignment("d", "due_diligence", "", [
    {"applicant": 1, "ein": "012345678", "period_end": "2024-06-30", "total_revenue": 1000, "program_share": 81.3,
     "top_comp": 50000, "insider_transactions": False},
    {"applicant": 2, "ein": "987654321", "period_end": "2023-12-31", "total_revenue": 2000, "program_share": 0.0,
     "top_comp": 0, "insider_transactions": True},
])


def _answer(**overrides):
    rows = [dict(r) for r in DILIGENCE.expected]
    rows[0].update(overrides)
    return rows


def test_equivalent_formats_pass():
    answer = _answer(ein="01-2345678", total_revenue="$1,000", program_share="81.3%", insider_transactions="false")
    assert grade(DILIGENCE, answer)["passed"]


def test_one_wrong_cell_fails_whole_deliverable():
    result = grade(DILIGENCE, _answer(top_comp=50001))
    assert not result["passed"]
    assert result["score"] == round(11 / 12, 3)


def test_rounding_tolerance_is_half_a_tenth():
    assert grade(DILIGENCE, _answer(program_share=81.35))["passed"]
    assert not grade(DILIGENCE, _answer(program_share=81.4))["passed"]


def test_missing_applicant_fails():
    assert not grade(DILIGENCE, _answer()[:1])["passed"]


def test_malformed_answer_scores_zero():
    result = grade(DILIGENCE, {"not": "a list"})
    assert not result["passed"] and result["score"] == 0.0 and result["error"]


def test_follow_money_is_order_insensitive_but_exact():
    a = Assignment("m", "follow_money", "", {"considered": ["111111111", "222222222"], "dependent": ["222222222"]})
    assert grade(a, {"considered": ["222222222", "11-1111111"], "dependent": ["222222222"]})["passed"]
    assert not grade(a, {"considered": ["222222222", "111111111"], "dependent": []})["passed"]


def test_compensation_order_matters():
    a = Assignment("c", "compensation", "", [{"ein": "111111111", "person": "A", "total": 300},
                                             {"ein": "222222222", "person": "B", "total": 200}])
    assert grade(a, [{"ein": "111111111", "person": "x", "total": 300}, {"ein": "222222222", "person": "y", "total": 200}])["passed"]
    assert not grade(a, [{"ein": "222222222", "total": 200}, {"ein": "111111111", "total": 300}])["passed"]


def test_ledger_rows_are_a_multiset():
    rows = [{"funder_ein": "111111111", "recipient_ein": "222222222", "cash": 5000, "noncash": 0},
            {"funder_ein": "111111111", "recipient_ein": "222222222", "cash": 5000, "noncash": 0},
            {"funder_ein": "111111111", "recipient_ein": "", "cash": 900, "noncash": 100}]
    a = Assignment("l", "grant_ledger", "", rows)
    assert grade(a, [rows[2], {**rows[0], "recipient_ein": "22-2222222", "cash": "$5,000"}, rows[1]])["passed"]
    missing_duplicate = grade(a, rows[1:])
    assert not missing_duplicate["passed"] and missing_duplicate["score"] == round(2 / 3, 3)
    assert not grade(a, rows + [rows[2]])["passed"]
