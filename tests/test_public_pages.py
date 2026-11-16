"""The public pages can be read without JavaScript: the server fills the app shell with the page's build-time HTML for visitors
without a session (AI assistants, search engines, link previews), and serves llms.txt, llms-full.txt, sitemap.xml and robots.txt."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ragintegrity.api.app import STATIC, create_app
from ragintegrity.config import Settings

KEY = "k" * 40
PW = "a-long-unusual-passphrase"
BASE = "https://ragguard.example.com"
ROOT = Path(__file__).parent.parent
MANIFEST = STATIC / "prerender" / "pages.json"

pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="the web interface was built without pre-rendered pages")


def client(tmp_path, mode="app", **kw) -> TestClient:
    settings = Settings(_env_file=None, mode=mode, database_url=f"sqlite:///{tmp_path / 'p.db'}", secret_key=KEY, **kw)
    return TestClient(create_app(settings=settings))


def root_of(page: str) -> str:
    m = re.search(r'<div id="root">(.*)</div>\s*<noscript>', page, re.S)
    assert m, "no root element"
    return m.group(1)


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_a_visitor_without_a_session_gets_the_page_text_title_and_canonical(tmp_path):
    with client(tmp_path, app_url=BASE) as c:
        home = c.get("/")
        guide = c.get("/guides/find-documents-with-two-versions-in-the-index")
        chapter = c.get("/help/01-getting-started/")  # a trailing slash is the same page
    assert home.status_code == 200 and home.headers["cache-control"] == "no-store"
    assert "Know when your RAG index is wrong" in text_of(root_of(home.text))
    assert "<title>RAGGuard: know when your RAG index is wrong, before your users do</title>" in home.text
    assert f'<link rel="canonical" href="{BASE}/" />' in home.text
    assert "Count the distinct versions per document" in text_of(root_of(guide.text))
    assert "<title>Find documents with two versions in the index · RAGGuard</title>" in guide.text
    assert "HAVING count(DISTINCT source_hash) &gt; 1" in guide.text  # the SQL is there, as text
    assert f'href="{BASE}/help/01-getting-started"' in chapter.text and "Getting started" in root_of(chapter.text)


def test_signed_in_users_and_private_pages_get_the_plain_shell(tmp_path):
    with client(tmp_path) as c:
        private = c.get("/issues")
        unknown = c.get("/guides/no-such-guide")
        assert c.post("/api/auth/register", json={"email": "alice@example.com", "password": PW}).status_code == 201
        home = c.get("/")
    shell = (STATIC / "index.html").read_bytes().decode("utf-8")
    for r in (private, unknown, home):
        assert r.status_code == 200 and r.text == shell  # nothing injected: the app renders it as before


def test_the_ai_files_carry_this_deployments_address(tmp_path):
    with client(tmp_path, app_url=BASE) as c:
        llms, full, sitemap, robots = c.get("/llms.txt"), c.get("/llms-full.txt"), c.get("/sitemap.xml"), c.get("/robots.txt")
    assert llms.status_code == 200 and llms.headers["content-type"].startswith("text/plain")
    assert llms.text.startswith("# RAGGuard\n\n> ") and "{BASE}" not in llms.text and "{BASE}" not in full.text
    for path in manifest():
        if path.startswith(("/guides", "/help/")):
            assert f"({BASE}{path})" in llms.text, path
        assert f"<loc>{BASE}{path}</loc>" in sitemap.text, path
    assert sitemap.headers["content-type"].startswith("application/xml")
    assert f"Sitemap: {BASE}/sitemap.xml" in robots.text and "Disallow: /api/" in robots.text
    assert "# Find documents with two versions in the index" in full.text


def test_without_a_configured_address_the_request_address_is_used(tmp_path):
    with client(tmp_path) as c:
        assert "(http://testserver/guides)" in c.get("/llms.txt").text
        assert 'rel="canonical"' not in c.get("/").text  # never built from a request's Host header


def test_single_user_servers_publish_nothing(tmp_path):
    with client(tmp_path, mode="demo") as c:
        assert c.get("/").text == (STATIC / "index.html").read_bytes().decode("utf-8")
        assert c.get("/llms.txt").status_code == 404 and c.get("/sitemap.xml").status_code == 404
        assert c.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"


def test_every_guide_and_chapter_has_a_prerendered_page():
    pages = manifest()
    guides = sorted(p for p in (ROOT / "docs" / "guides").glob("*.md") if p.stem != "README")
    readme = (ROOT / "docs" / "guides" / "README.md").read_text(encoding="utf-8")
    for g in guides:
        slug = re.sub(r"^\d+-", "", g.stem)
        assert f"/guides/{slug}" in pages, g.name
        assert f"]({g.name})" in readme, f"docs/guides/README.md does not link {g.name}"
        text = g.read_text(encoding="utf-8")
        assert re.search(r"^# .+$", text, re.M) and re.search(r"^> .+$", text, re.M), f"{g.name} needs a '# ' title and a '> ' summary"
    for chapter in (ROOT / "docs" / "user-guide").glob("[0-9]*.md"):
        assert f"/help/{chapter.stem}" in pages, chapter.name
    assert {"/", "/guides", "/help", "/privacy", "/terms"} <= set(pages)
    for meta in pages.values():
        assert (STATIC / "prerender" / meta["file"]).stat().st_size > 1000 and meta["title"] and meta["description"]


def test_the_app_routes_every_public_page():
    app = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    prerender = (ROOT / "frontend" / "src" / "prerender.tsx").read_text(encoding="utf-8")
    for route in ('path="guides"', 'path="guides/:slug"', 'path="privacy"', 'path="terms"'):
        assert app.count(route) == 2, route  # signed out and signed in
        assert route in prerender, route
