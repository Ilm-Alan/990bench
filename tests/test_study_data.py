"""The committed study data and the statistics behind the reported tables.

These run without the IRS corpus: they check that the run plan, the assignments and their reference
answers in data/ fit together, and that the interval and test code reproduces the figures printed
in docs/report.md.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from bench990.analysis import wilson
from bench990.assignments import _clear_of_rounding, grade, load
from bench990.probes import PROBES, mcnemar
from bench990.study import INSTANCES, STUDY, cells

PLAN = [json.loads(line) for line in (STUDY / "runs.jsonl").read_text().splitlines()]
ASSIGNMENTS = {a.id: a for a in load(STUDY / "assignments.jsonl")}


def test_plan_runs_every_setting_four_times() -> None:
    assert Counter(r["cell"] for r in PLAN) == {c.name: INSTANCES for c in cells()}
    assert len(PLAN) == 32 and len(ASSIGNMENTS) == 24


def test_each_planned_assignment_fits_its_setting() -> None:
    for r in PLAN:
        a = ASSIGNMENTS[r["assignment"]]
        assert a.meta["n"] == r["n"] and a.meta["trap_share"] == r["trap_share"], a.id
        assert [row["applicant"] for row in a.expected] == list(range(1, r["n"] + 1)), a.id
        assert len(set(a.meta["object_ids"])) == r["n"], a.id


def test_fidelity_settings_reuse_the_baseline_assignments() -> None:
    by_cell = {cell: {r["assignment"] for r in PLAN if r["cell"] == cell} for cell in {r["cell"] for r in PLAN}}
    assert by_cell["n10-t50-bilevel"] == by_cell["n10-t50-coarse"] == by_cell["n10-t50-clean"]


@pytest.mark.parametrize("path", [STUDY / "assignments.jsonl", STUDY.parent / "assignments.jsonl"], ids=lambda p: p.parent.name)
def test_reference_answers_pass_the_grader(path: Path) -> None:
    for a in load(path):
        result = grade(a, a.expected)
        assert result["passed"] and result["score"] == 1.0, a.id


def test_a_packet_has_six_graded_values_per_applicant() -> None:
    sizes = {len(grade(a, a.expected)["checks"]) for a in ASSIGNMENTS.values()}
    assert sizes == {30, 60, 120, 240}


def test_probe_file_holds_the_planned_values() -> None:
    probes = [json.loads(line) for line in (PROBES / "probes.jsonl").read_text().splitlines()]
    assert len(probes) == len({p["id"] for p in probes}) == 401
    assert Counter(p["kind"] for p in probes[:193]) == {"part7": 72, "sched_j": 39, "grants": 82}


@pytest.mark.parametrize(("passed", "runs", "interval"), [
    (3, 4, "30%–95%"), (2, 4, "15%–85%"), (0, 4, "0%–49%"),
    (191, 193, "96.3%–99.7%"), (193, 193, "98.0%–100.0%"), (192, 193, "97.1%–99.9%"),
])
def test_wilson_intervals_match_the_reported_tables(passed: int, runs: int, interval: str) -> None:
    lo, hi = wilson(passed, runs)
    digits = 1 if "." in interval else 0
    assert f"{lo:.{digits}%}–{hi:.{digits}%}" == interval


def test_exact_mcnemar() -> None:
    assert mcnemar(1, 2) == 1.0  # full page vs strip, as reported
    assert mcnemar(0, 2) == 0.5  # 150 vs 300 dpi, as reported
    assert mcnemar(0, 0) == 1.0
    assert mcnemar(0, 6) == mcnemar(6, 0) == 2 / 64


def test_shares_on_a_rounding_boundary_are_never_asked() -> None:
    assert not _clear_of_rounding(8135, 10000)  # 81.35% rounds either way
    assert not _clear_of_rounding(813499, 1000000)  # within 0.001 points of the boundary
    assert _clear_of_rounding(8134, 10000)
    assert _clear_of_rounding(813, 1000)
