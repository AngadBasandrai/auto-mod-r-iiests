"""Offline tests for the student-wiki crawler.

Everything here runs against a fixture copy of the real page markup — no
network, so the suite still passes with the site down or the wifi off.
"""

from automod.ingest import wiki_site

# Trimmed from https://iiest-town.github.io/hostels/. Preserves the two things
# that actually matter: content lives in <article class="prose">, and headings
# carry a permalink <a> whose text duplicates the heading.
PAGE = """
<html><head><title>Hostels</title></head><body>
<nav><a href="/">Home</a><a href="/campus/">Campus</a></nav>
<article class="prose">
  <h1>Hostels</h1>
  <p class="lede">A practical index for hostel life.</p>
  <h4 id="what-are-the-hostels-for-first-year-students"><a class="heading-link"
     href="#what-are-the-hostels-for-first-year-students"
     aria-label="Link to What are the Hostels for first year students?">What are the Hostels for first year students?</a></h4>
<p>First years are placed in H-9 and H-10, which are close to the main gate.</p>
<p>###</p>
<h3 id="food"><a class="heading-link" href="#food" aria-label="Link to Food">Food</a></h3>
<ul>
<li>Mess fees = 27.7k (Pay through this portal : - )</li>
<p>-</p>
</ul>
<h3 id="in-time"><a class="heading-link" href="#in-time" aria-label="Link to In-time">In-time</a></h3>
<ul>
<li>for the first two months, irrespective of gender, your hostel intime is 7PM</li>
<li>The intime gets extended to 10PM afterwards for the rest of the year.</li>
</ul>
<h3 id="stub"><a class="heading-link" href="#stub" aria-label="Link to Stub">Stub</a></h3>
<p>...</p>
</article>
<footer>Edit this page on GitHub</footer>
</body></html>
"""

URL = "https://iiest-town.github.io/hostels/"


def test_title_and_sections():
    title, sections = wiki_site.parse_article(PAGE)
    assert title == "Hostels"
    headings = [s.heading for s in sections]
    assert "Food" in headings
    assert "In-time" in headings
    # The <h1> names the page; it must not also open a section.
    assert headings.count("Hostels") <= 1


def test_navigation_and_footer_are_not_content():
    _, sections = wiki_site.parse_article(PAGE)
    blob = "\n".join(s.body for s in sections)
    assert "Edit this page on GitHub" not in blob
    assert "Campus" not in blob


def test_heading_permalink_text_is_not_duplicated_into_the_body():
    _, sections = wiki_site.parse_article(PAGE)
    food = next(s for s in sections if s.heading == "Food")
    assert "Link to Food" not in food.body
    assert food.heading == "Food"


def test_markdown_artifacts_are_dropped():
    _, sections = wiki_site.parse_article(PAGE)
    bodies = [s.body for s in sections]
    assert "###" not in bodies
    assert "-" not in bodies


def test_question_heading_becomes_a_direct_pair_with_its_anchor():
    rows = wiki_site.rows_from_page(URL, PAGE)
    direct = [r for r in rows if "answers" in r]
    assert len(direct) == 1
    row = direct[0]
    assert row["question"].endswith("?")
    assert "H-9" in row["answers"][0]
    assert row["ref"] == URL + "#what-are-the-hostels-for-first-year-students"
    assert row["source"] == "student_wiki"


def test_topic_headings_become_documents():
    rows = wiki_site.rows_from_page(URL, PAGE)
    docs = {r["text"].splitlines()[0]: r for r in rows if "text" in r}
    assert "In-time" in docs
    assert "7PM" in docs["In-time"]["text"]
    # Path-derived topic hint, used instead of whatever the model guesses.
    assert docs["In-time"]["topic"] == "hostels"


def test_stub_sections_are_skipped():
    rows = wiki_site.rows_from_page(URL, PAGE)
    assert not any("Stub" in (r.get("text") or r.get("question", "")) for r in rows)


def test_editor_instruction_headings_are_skipped():
    page = PAGE.replace(
        '<h3 id="in-time"><a class="heading-link" href="#in-time" aria-label="Link to In-time">In-time</a></h3>',
        '<h3 id="add-listings"><a class="heading-link" href="#add-listings" aria-label="Link to Add Listings">Add Listings</a></h3>',
    )
    rows = wiki_site.rows_from_page(URL, page, skip_headings=["add.*", "photos"])
    headings = [r["text"].splitlines()[0] for r in rows if "text" in r]
    assert "Add Listings" not in headings
    assert "Food" in headings


def test_a_question_heading_survives_the_skip_list():
    rows = wiki_site.rows_from_page(URL, PAGE, skip_headings=["what.*"])
    assert any("answers" in r for r in rows)


def test_page_with_no_article_yields_nothing():
    assert wiki_site.rows_from_page(URL, "<html><body><p>hi</p></body></html>") == []


def test_discover_urls_filters_skipped_paths(monkeypatch):
    sitemap = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset><url><loc>https://iiest-town.github.io/</loc></url>
    <url><loc>https://iiest-town.github.io/hostels/</loc></url>
    <url><loc>https://iiest-town.github.io/gallery/</loc></url>
    <url><loc>https://iiest-town.github.io/search/</loc></url>
    <url><loc>https://iiest-town.github.io/departments/civil/</loc></url>
    </urlset>"""
    monkeypatch.setattr(wiki_site, "fetch", lambda url, **kw: sitemap)

    urls = wiki_site.discover_urls(
        "https://iiest-town.github.io/", ["search", "gallery", "contribute"]
    )
    assert "https://iiest-town.github.io/gallery/" not in urls
    assert "https://iiest-town.github.io/search/" not in urls
    assert "https://iiest-town.github.io/hostels/" in urls
    assert "https://iiest-town.github.io/departments/civil/" in urls


def test_page_lede_is_not_treated_as_content():
    # The lede is a subtitle describing the page. Fed to the extraction model it
    # becomes several confident answers that answer nothing.
    _, sections = wiki_site.parse_article(PAGE)
    blob = "\n".join(s.body for s in sections)
    assert "A practical index for hostel life" not in blob
