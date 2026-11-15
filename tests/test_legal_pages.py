"""The Privacy Policy and the Terms of Service must stay reachable and true to the product.

They are Markdown in docs/legal, shown at /privacy and /terms. These checks keep the pages linked from the places people look for them,
and keep the facts the policy states (the contact address, the cookie name, the session length) equal to the code.
"""

from __future__ import annotations

import re
from pathlib import Path

from ragintegrity.api import app as api_app
from ragintegrity.config import Settings

ROOT = Path(__file__).parent.parent
LEGAL = ROOT / "docs" / "legal"
FRONTEND = ROOT / "frontend" / "src"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def contact_email() -> str:
    m = re.search(r'CONTACT_EMAIL = "([^"]+)"', read(FRONTEND / "pages" / "landing" / "contact.ts"))
    assert m
    return m.group(1)


def test_both_documents_exist_with_a_date_and_the_contact_address():
    for name, title in (("privacy.md", "# Privacy Policy"), ("terms.md", "# Terms of Service")):
        text = read(LEGAL / name)
        assert text.startswith(title)
        assert re.search(r"\*Last updated: \d{1,2} \w+ \d{4}\*", text)
        assert contact_email() in text


def test_the_policy_names_the_real_cookie_and_session_length():
    text = read(LEGAL / "privacy.md")
    assert f"`{api_app.COOKIE}`" in text
    days = Settings.model_fields["session_days"].default  # the default, not whatever this machine's environment sets
    assert f"up to {days} days" in text
    assert f"after {days} days" in text


def test_the_app_serves_both_pages_signed_out_and_signed_in():
    app = read(FRONTEND / "App.tsx")
    for doc in ("privacy", "terms"):
        assert app.count(f'path="{doc}" element={{<LegalPage doc="{doc}" />}}') == 2, doc


def test_the_pages_are_linked_from_the_footer_and_the_sign_up_form():
    footer = read(FRONTEND / "pages" / "landing" / "nav.tsx")
    auth = read(FRONTEND / "pages" / "auth" / "index.tsx")
    for path in ("/privacy", "/terms"):
        assert f'to="{path}"' in footer
        assert f'to="{path}"' in auth


def test_the_two_documents_link_to_each_other():
    assert "](/terms)" in read(LEGAL / "privacy.md")
    assert "](/privacy)" in read(LEGAL / "terms.md")
