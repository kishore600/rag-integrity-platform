"""The Help pages show docs/user-guide inside the app (frontend/src/pages/help). These tests keep the two in step.

The page reads the Markdown files at build time, lists the chapters from the README's contents tables, links screenshots by file
name, and plays the video from public/help-media. Anything that would break one of those quietly is checked here.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ragintegrity.api.app import create_app
from ragintegrity.config import Settings
from ragintegrity.connectors.factory import build_connectors
from ragintegrity.demo.world import TARGET_FP, DemoWorld
from ragintegrity.ledger import Ledger
from ragintegrity.service import IntegrityService

ROOT = Path(__file__).parent.parent
GUIDE = ROOT / "docs" / "user-guide"
HELP = ROOT / "frontend" / "src" / "pages" / "help"
MEDIA = ["RAGGuard-walkthrough.mp4", "RAGGuard-walkthrough.vtt", "RAGGuard-walkthrough-poster.jpg"]

# the same pattern as parseIndex() in frontend/src/pages/help/content.ts
ROW = re.compile(r"^\|\s*\[(\d+)\.\s+([^\]]+)\]\(([\w-]+)\.md\)\s*\|\s*(.*?)\s*\|\s*$")
CHAPTER_FILE = re.compile(r"^\d\d-[\w-]+\.md$")


def chapters() -> list[Path]:
    return sorted(p for p in GUIDE.iterdir() if CHAPTER_FILE.match(p.name))


def test_the_contents_page_lists_every_chapter_exactly_once():
    rows = [m for line in (GUIDE / "README.md").read_text(encoding="utf-8").splitlines() if (m := ROW.match(line))]
    listed = [m.group(3) for m in rows]
    files = [p.stem for p in chapters()]
    assert len(listed) == len(set(listed)), "a chapter is listed twice in docs/user-guide/README.md"
    assert sorted(listed) == files, "docs/user-guide/README.md and the chapter files disagree: the Help contents page is built from the README"
    for m in rows:  # "[7. Integrity issues](07-integrity-issues.md)": the number in the label is the number in the file name
        assert int(m.group(1)) == int(m.group(3)[:2]), f"{m.group(3)} is labelled chapter {m.group(1)}"


def slugs(markdown: str) -> set[str]:
    """The heading ids the page produces (rehype-slug, which follows GitHub: lower case, no punctuation, spaces to hyphens)."""
    seen: dict[str, int] = {}
    out: set[str] = set()
    fenced = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        m = None if fenced else re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if not m:
            continue
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1))
        slug = re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        out.add(slug if n == 0 else f"{slug}-{n}")
    return out


# Links to files outside the guide folder cannot work inside the app; the page shows them as plain text. Keep that list short.
OUTSIDE = {"../", "../../README.md", "../../GUIDE.md", "../repair-webhook.md"}


def test_every_link_in_the_guide_works_in_the_app():
    ids = {p.name: slugs(p.read_text(encoding="utf-8")) for p in GUIDE.glob("*.md")}
    problems: list[str] = []
    for page in sorted(GUIDE.glob("*.md")):
        text = page.read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)  # code samples are not links
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if re.match(r"^(https?:|mailto:)", target):
                continue
            path, _, fragment = target.partition("#")
            if not path:  # a link inside the same page
                if fragment not in ids[page.name]:
                    problems.append(f"{page.name}: #{fragment} is not a heading of this page")
            elif target in OUTSIDE or path in OUTSIDE:
                assert (page.parent / path).resolve().exists(), f"{page.name}: {path} does not exist"
            elif path.startswith("images/"):
                if not (GUIDE / path).is_file():
                    problems.append(f"{page.name}: missing picture {path}")
            elif path.startswith("video/"):
                if not (GUIDE / path).is_file():
                    problems.append(f"{page.name}: missing video file {path}")
            elif path.endswith(".md"):
                if not (GUIDE / path).is_file():
                    problems.append(f"{page.name}: missing chapter {path}")
                elif fragment and fragment not in ids[path]:
                    problems.append(f"{page.name}: {path}#{fragment} is not a heading of {path}")
            else:
                problems.append(f"{page.name}: a link the Help page cannot follow: {target}")
    assert not problems, "\n".join(problems)


def test_screenshots_have_the_sizes_the_page_reserves_room_for():
    """The page gives every picture its width and height up front (so lazy loading does not move the text)."""
    wrong = []
    for png in sorted((GUIDE / "images").glob("*.png")):
        size = struct.unpack(">II", png.read_bytes()[16:24])
        want = (780, 1688) if png.name.startswith("mobile-") else (1440, 810)
        if size != want:
            wrong.append(f"{png.name} is {size[0]}x{size[1]}, expected {want[0]}x{want[1]}")
    assert not wrong, "update markdown.tsx (img) for the new picture size:\n" + "\n".join(wrong)


def test_the_video_buttons_match_the_table_in_chapter_19():
    ts = re.findall(r'\{ t: (\d+), title: "([^"]+)" \}', (HELP / "video.tsx").read_text(encoding="utf-8"))
    page = (GUIDE / "19-video-walkthrough.md").read_text(encoding="utf-8")
    table = [(int(m) * 60 + int(s), title) for m, s, title in re.findall(r"^\|\s*(\d+):(\d\d)\s*\|\s*\*\*([^*]+)\*\*", page, flags=re.M)]
    assert table, "chapter 19 has no timestamp table"
    assert [(int(t), title) for t, title in ts] == table, "frontend/src/pages/help/video.tsx (VIDEO_CHAPTERS) and the table in chapter 19 differ"


@pytest.mark.parametrize("name", MEDIA)
def test_the_served_copies_of_the_video_files_are_the_documented_ones(name):
    """docs/user-guide/video is the master; `npm run build` copies it to public/help-media (Vercel's CDN) and into the built files."""
    master = (GUIDE / "video" / name).read_bytes()
    assert (ROOT / "public" / "help-media" / name).read_bytes() == master, "run `npm run build` in frontend/ and commit public/help-media"
    assert (ROOT / "src" / "ragintegrity" / "api" / "static" / "help-media" / name).read_bytes() == master, "run `npm run build` in frontend/ and commit the build"


def test_missing_help_media_is_a_404_not_the_app_page(tmp_path):
    """The player tries the CDN path first and falls back to /static/help-media/: on a server without the CDN the first must be a real 404."""
    settings = Settings(_env_file=None, mode="demo", database_url=f"sqlite:///{tmp_path / 's.db'}", grace_minutes=0,
                        **{f"target_{k}": v for k, v in TARGET_FP.to_dict().items()})
    svc = IntegrityService(settings, Ledger(settings.database_url), build_connectors(settings, DemoWorld(seed=5, docs_per_tenant=5)))
    with TestClient(create_app(svc, settings)) as c:
        missing = c.get("/help-media/RAGGuard-walkthrough.mp4")
        assert missing.status_code == 404 and "text/html" not in missing.headers.get("content-type", "")
        assert c.get("/help").status_code == 200 and "text/html" in c.get("/help").headers["content-type"]  # the Help pages are app routes
        assert c.get("/help/20-isolation").status_code == 200
        video = c.get("/static/help-media/RAGGuard-walkthrough.mp4", headers={"Range": "bytes=0-99"})
        assert video.status_code == 206 and video.headers["content-type"] == "video/mp4"
        assert c.get("/static/help-media/RAGGuard-walkthrough.vtt").headers["content-type"].startswith("text/vtt")
