"""Pull the student-run IIEST wiki at https://iiest-town.github.io/.

A third source, and the most trustworthy of the three: a deliberately curated
documentation site rather than a chat log or an upvoted comment. It covers the
same ground newcomers ask about — hostels, departments, campus, ragging, clubs.

The site is a static generator with a sitemap, and every page body sits in a
single `<article class="prose">` whose `<h2>`/`<h3>`/`<h4>` headings already
split the content by topic. So the shape is handed to us:

  * a heading that ends in "?" is a real FAQ entry — question and answer are
    taken verbatim, no model involved and therefore nothing to invent.
  * every other section becomes a document row and goes through the same
    extraction model as the subreddit wiki pages.

Both land in data/corpus/wiki.jsonl and are curated downstream exactly like
every other source. Section anchors are kept, so a citation points at the
paragraph rather than the page.

Only stdlib HTTP and HTML parsing — the CI runner installs requirements.txt on
every 10-minute poll, and this is not worth a dependency.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from .. import config

log = logging.getLogger(__name__)

USER_AGENT = "auto-mod-r-iiests/0.1 (+https://github.com/AngadBasandrai/auto-mod-r-iiests)"

# Tags whose text is chrome, not content.
_SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "form", "svg", "button"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCKS = {"p", "li", "tr", "div", "blockquote", "pre", "dt", "dd", "br"}

# Unfilled stubs. The wiki is young and half-written sections are common; they
# render as an ellipsis, a stray markdown marker, or a lone dash.
_PLACEHOLDER = re.compile(r"^(?:[-*#>.\s]|\.\.\.|…|tbd|wip|todo|coming soon|n/?a)*$", re.I)


@dataclass
class Section:
    """One heading and the text under it."""

    heading: str
    anchor: str
    lines: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        return "\n".join(self.lines).strip()

    def is_question(self) -> bool:
        return self.heading.rstrip().endswith("?")


class _ArticleParser(HTMLParser):
    """Extract headings and block text from the page's <article>.

    Deliberately forgiving: the site's markdown renders slightly malformed HTML
    in places (a <p> inside a <ul>), which a strict parser would choke on.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.sections: list[Section] = []
        self._in_article = 0
        self._skip_depth = 0
        self._heading_tag: str | None = None
        self._heading_anchor = ""
        self._buffer: list[str] = []
        self._current: Section | None = None

    # -- helpers ------------------------------------------------------------
    def _flush_block(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
        self._buffer.clear()
        if not text or _PLACEHOLDER.match(text):
            return
        if self._current is None:
            # Text before the first subheading (the page lede).
            self._current = Section(heading=self.title or "Overview", anchor="")
            self.sections.append(self._current)
        self._current.lines.append(text)

    def _close_heading(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
        self._buffer.clear()
        self._heading_tag = None
        if not text:
            return
        if not self.title:
            self.title = text
            # <h1> names the page; it does not open a section of its own.
            return
        self._current = Section(heading=text, anchor=self._heading_anchor)
        self.sections.append(self._current)

    # -- HTMLParser interface ----------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "article":
            self._in_article += 1
            return
        if not self._in_article:
            return
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in _HEADINGS:
            self._flush_block()
            self._heading_tag = tag
            self._heading_anchor = attributes.get("id") or ""
            return
        # The anchor inside a heading is a permalink widget, not content.
        if tag == "a" and self._heading_tag and "heading-link" in (attributes.get("class") or ""):
            return
        if tag in _BLOCKS and not self._heading_tag:
            self._flush_block()

    def handle_endtag(self, tag: str) -> None:
        if tag == "article":
            if self._in_article:
                self._flush_block()
                self._in_article -= 1
            return
        if not self._in_article:
            return
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in _HEADINGS and self._heading_tag:
            self._close_heading()
            return
        if tag in _BLOCKS and not self._heading_tag:
            self._flush_block()

    def handle_data(self, data: str) -> None:
        if not self._in_article or self._skip_depth:
            return
        self._buffer.append(data)

    def close(self) -> None:  # noqa: D102
        super().close()
        self._flush_block()


def parse_article(html: str) -> tuple[str, list[Section]]:
    """Return (page title, sections) for one rendered wiki page."""
    parser = _ArticleParser()
    parser.feed(html)
    parser.close()
    sections = [s for s in parser.sections if s.body]
    return parser.title, sections


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def fetch(url: str, *, timeout: int = 20, retries: int = 3) -> str:
    """GET a URL as text. Retries transient failures, gives up quietly."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            last = exc
        except Exception as exc:  # noqa: BLE001 - network flakiness is expected
            last = exc
        if attempt < retries:
            time.sleep(2 * attempt)
    raise RuntimeError(f"Could not fetch {url}: {last}")


def discover_urls(base_url: str, skip_paths: list[str]) -> list[str]:
    """Page URLs from the site's sitemap, minus the ones with nothing to say."""
    sitemap = urllib.parse.urljoin(base_url, "sitemap.xml")
    urls = re.findall(r"<loc>\s*(.*?)\s*</loc>", fetch(sitemap), flags=re.S)

    kept: list[str] = []
    for url in urls:
        path = urllib.parse.urlparse(url).path.strip("/")
        if any(path == s.strip("/") or path.startswith(s.strip("/") + "/") for s in skip_paths):
            continue
        kept.append(url)

    log.info("Sitemap: %d URLs, %d after skips", len(urls), len(kept))
    return kept


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------
def _skip_matcher(patterns: list[str]) -> re.Pattern[str] | None:
    """One compiled alternation for the editor-instruction headings."""
    if not patterns:
        return None
    return re.compile(r"^(?:" + "|".join(patterns) + r")$", re.I)


def rows_from_page(
    url: str,
    html: str,
    *,
    min_section_chars: int = 20,
    skip_headings: list[str] | None = None,
) -> list[dict]:
    """Turn one page into corpus rows.

    Question-headed sections become answered pairs directly. Everything else
    becomes a document for the extraction model, one row per section so a fact
    about hostels never gets blended with a fact about placements.
    """
    title, sections = parse_article(html)
    if not sections:
        log.debug("No article content at %s", url)
        return []

    skip = _skip_matcher(skip_headings or [])

    # /departments/civil/ -> "civil"; used as the topic hint.
    path_parts = [p for p in urllib.parse.urlparse(url).path.strip("/").split("/") if p]
    topic_hint = path_parts[0] if path_parts else "general"

    rows: list[dict] = []
    for section in sections:
        body = section.body
        if len(body) < min_section_chars:
            continue
        # A question heading is always a real entry, even if it happens to
        # collide with a skip word.
        if skip is not None and not section.is_question() and skip.match(section.heading.strip()):
            log.debug("Skipping editor-instruction section %r on %s", section.heading, url)
            continue
        ref = f"{url}#{section.anchor}" if section.anchor else url

        if section.is_question():
            rows.append(
                {
                    "source": "student_wiki",
                    "ref": ref,
                    "title": title,
                    "question": section.heading,
                    "answers": [body],
                    "topic": topic_hint,
                }
            )
        else:
            rows.append(
                {
                    "source": "student_wiki",
                    "ref": ref,
                    "title": f"{title} — {section.heading}" if title else section.heading,
                    "topic": topic_hint,
                    "text": f"{section.heading}\n\n{body}",
                }
            )

    return rows


def run(out_path: Path | None = None, *, limit: int | None = None) -> list[dict]:
    """Crawl the wiki and write data/corpus/wiki.jsonl. Returns the rows."""
    cfg = config.get("ingest.wiki", {}) or {}
    base_url = cfg.get("base_url", "https://iiest-town.github.io/")
    if not cfg.get("enabled", True):
        log.info("ingest.wiki.enabled is false — skipping %s", base_url)
        return []

    out_path = out_path or config.WIKI_RAW_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    urls = discover_urls(base_url, cfg.get("skip_paths", []))
    if limit:
        urls = urls[:limit]

    rows: list[dict] = []
    for url in urls:
        try:
            html = fetch(url)
        except Exception as exc:  # noqa: BLE001 - one dead page must not kill the crawl
            log.warning("Skipping %s: %s", url, exc)
            continue
        page_rows = rows_from_page(
            url,
            html,
            min_section_chars=cfg.get("min_section_chars", 20),
            skip_headings=cfg.get("skip_headings", []),
        )
        log.info("%-58s %2d sections", urllib.parse.urlparse(url).path, len(page_rows))
        rows.extend(page_rows)
        time.sleep(cfg.get("delay_seconds", 0.5))

    direct = sum(1 for r in rows if "answers" in r)
    log.info(
        "Wiki: %d rows from %d pages (%d ready-made Q&A, %d sections to extract)",
        len(rows),
        len(urls),
        direct,
        len(rows) - direct,
    )

    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    log.info("Wrote %d rows -> %s", len(rows), out_path)
    return rows
