"""Seam: the program-name suffix rule of the analysis service.

The `program_suffixes` list of the cross-repository agreement file feeds every
copy of the rule in this repository. The client repository `llamaindex-spec-rag`
runs the same list against each of its copies, so a suffix that one side lacks
turns one test red. This repository keeps one definition: `_KNOWN_SUFFIXES`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from service import analyze_service

AGREEMENT_PATH = Path(__file__).resolve().parent / "cross_repository_agreement.json"
PROGRAM_SUFFIXES = json.loads(AGREEMENT_PATH.read_text(encoding="utf-8"))["program_suffixes"]

SEVEN_SUFFIXES = {".aspx.cs", ".ascx.cs", ".aspx", ".ascx", ".cshtml", ".vue", ".cs"}


@pytest.mark.parametrize("case", PROGRAM_SUFFIXES, ids=[case["input"] for case in PROGRAM_SUFFIXES])
def test_the_service_rule_strips_each_agreed_name(case: dict) -> None:
    assert analyze_service._normalize_program(case["input"]) == case["stripped"]


@pytest.mark.parametrize("case", PROGRAM_SUFFIXES, ids=[case["input"] for case in PROGRAM_SUFFIXES])
def test_the_service_rule_ignores_the_directory_of_a_path(case: dict) -> None:
    assert analyze_service._normalize_program("Views/Home/" + case["input"]) == case["stripped"]


def test_the_agreed_list_covers_all_seven_suffixes() -> None:
    covered = {
        suffix
        for suffix in SEVEN_SUFFIXES
        if any(case["input"].lower().endswith(suffix) for case in PROGRAM_SUFFIXES)
    }

    assert covered == SEVEN_SUFFIXES


def test_the_service_keeps_one_definition_of_the_suffix_list() -> None:
    source = (PROJECT_ROOT / "service" / "analyze_service.py").read_text(encoding="utf-8")
    full_lists = re.findall(r'\(\s*"\.aspx\.cs",\s*"\.ascx\.cs"', source)

    assert len(full_lists) == 1
    assert set(analyze_service._KNOWN_SUFFIXES) == SEVEN_SUFFIXES
