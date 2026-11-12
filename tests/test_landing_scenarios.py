"""The scenarios on the public home page must stay true to the product.

The page lists the situations RAGGuard catches. They are the same thirteen faults the practice lab plants on purpose, one of each, and
every finding the page names is a real issue type. If someone adds a fault to the lab (or renames one) without updating the page, or the
other way round, this fails.
"""

from __future__ import annotations

import re
from pathlib import Path

from ragintegrity.demo import lab
from ragintegrity.models import IssueType

LANDING = Path(__file__).parent.parent / "frontend" / "src" / "pages" / "landing"


def scenarios_source() -> str:
    return (LANDING / "scenarios.tsx").read_text(encoding="utf-8")


def test_the_home_page_lists_exactly_the_faults_of_the_practice_lab():
    on_the_page = re.findall(r'fault: "([a-z_]+)"', scenarios_source())
    planted = [name for name, _count in lab.LAB_PLAN]
    assert sorted(on_the_page) == sorted(planted)
    assert len(on_the_page) == len(set(on_the_page)) == 13


def test_every_finding_the_home_page_names_is_a_real_issue_type():
    shown = set(re.findall(r'shows: "([a-z_]+)"', scenarios_source()))
    assert shown and shown <= {t.value for t in IssueType}


def test_the_ratings_on_the_page_are_real_severities():
    ratings = set(re.findall(r'severity: "([a-z]+)"', scenarios_source()))
    assert ratings <= {"critical", "high", "medium", "low", "info"}


def test_the_menu_links_point_at_sections_that_exist():
    nav = (LANDING / "nav.tsx").read_text(encoding="utf-8")
    page = scenarios_source() + (LANDING / "sections.tsx").read_text(encoding="utf-8")
    for anchor in re.findall(r'href: "#([a-z-]+)"', nav):
        assert f'id="{anchor}"' in page, anchor
