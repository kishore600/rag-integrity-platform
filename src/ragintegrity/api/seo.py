"""Make the public pages readable without JavaScript: for AI assistants, search engines and link previews.

The web interface is a single-page app, so the HTML shell it ships is empty until JavaScript runs, and most AI crawlers do not run
JavaScript. `npm run build` therefore renders the public pages at build time (frontend/src/prerender.tsx) into
``static/prerender``. For a visitor without a session, the server puts a page's HTML inside ``<div id="root">`` and sets that page's
title, description and canonical address; the app then replaces it as usual. Signed-in visitors get the plain shell, so they never
see a signed-out page flash before the app.

Also served from the build: ``/llms.txt`` and ``/llms-full.txt`` (https://llmstxt.org), ``/sitemap.xml`` and ``/robots.txt``.
"""

from __future__ import annotations

import html
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT_DIV = '<div id="root"></div>'
_TITLE = re.compile(r"<title>.*?</title>", re.S)
_DESCRIPTION = re.compile(r'<meta name="description" content="[^"]*"\s*/?>')
_OG_TITLE = re.compile(r'<meta property="og:title" content="[^"]*"\s*/?>')
_OG_DESCRIPTION = re.compile(r'<meta property="og:description" content="[^"]*"\s*/?>')


class PublicPages:
    def __init__(self, static: Path) -> None:
        self.static = static
        self.dir = static / "prerender"

    @lru_cache(maxsize=1)  # noqa: B019 - one instance per app; the build does not change while the server runs
    def manifest(self) -> dict[str, dict[str, Any]]:
        try:
            return json.loads((self.dir / "pages.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}  # a build without pre-rendered pages: every page is served as the plain shell

    def paths(self) -> list[str]:
        return sorted(self.manifest())

    @staticmethod
    def normalize(path: str) -> str:
        path = "/" + path.strip("/")
        return path

    def page(self, path: str, shell: str, base: str | None) -> str | None:
        """The shell with this page's HTML and metadata filled in, or None when the path has no pre-rendered page."""
        meta = self.manifest().get(self.normalize(path))
        if meta is None or ROOT_DIV not in shell:
            return None
        try:
            body = (self.dir / meta["file"]).read_text(encoding="utf-8")
        except OSError:
            return None
        title = html.escape(meta["title"], quote=True)
        description = html.escape(meta["description"], quote=True)
        out = shell.replace(ROOT_DIV, f'<div id="root">{body}</div>', 1)
        out = _TITLE.sub(lambda _: f"<title>{title}</title>", out, count=1)
        out = _DESCRIPTION.sub(lambda _: f'<meta name="description" content="{description}" />', out, count=1)
        out = _OG_TITLE.sub(lambda _: f'<meta property="og:title" content="{title}" />', out, count=1)
        out = _OG_DESCRIPTION.sub(lambda _: f'<meta property="og:description" content="{description}" />', out, count=1)
        if base:
            canonical = html.escape(base + (self.normalize(path) if path.strip("/") else "/"), quote=True)
            out = out.replace("</head>", f'    <link rel="canonical" href="{canonical}" />\n  </head>', 1)
        return out

    def text_file(self, name: str, base: str) -> str | None:
        """llms.txt or llms-full.txt, with this deployment's address in its links."""
        try:
            return (self.static / name).read_text(encoding="utf-8").replace("{BASE}", base)
        except OSError:
            return None

    def sitemap(self, base: str) -> str:
        urls = "".join(f"  <url><loc>{html.escape(base + (p if p != '/' else '/'))}</loc></url>\n" for p in self.paths())
        return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n'

    @staticmethod
    def robots(base: str) -> str:
        # The app's private pages need a session anyway; the API and the static build are of no use to a crawler.
        return f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {base}/sitemap.xml\n"
