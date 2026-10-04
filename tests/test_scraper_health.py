"""
Parser health tests: listing parsers must degrade gracefully when the
site markup changes (empty results, missing elements) and extract correctly
on the happy path. Uses a FakePage harness — no browser needed.
"""

from playwright.sync_api import TimeoutError as PWTimeout


class _Handle:
    def __init__(self, el):
        self._el = el

    def as_element(self):
        return self._el


class FakeEl:
    def __init__(self, text="", attrs=None, children=None, tag_name="div", parent=None):
        self._text = text
        self._attrs = attrs or {}
        self._children = children or {}
        self.tag_name = tag_name
        self._parent = parent if parent is not None else self

    def _lookup(self, sel):
        v = self._children.get(sel)
        if isinstance(v, list):
            return v
        return [v] if v else []

    def query_selector(self, sel):
        found = self._lookup(sel)
        return found[0] if found else None

    def query_selector_all(self, sel):
        return self._lookup(sel)

    def get_attribute(self, name):
        return self._attrs.get(name)

    def inner_text(self):
        return self._text

    def evaluate_handle(self, _expr):
        return _Handle(self._parent)

    def evaluate(self, expr):
        if "tagName" in expr:
            return self.tag_name.upper()
        return ""


class FakePage(FakeEl):
    def __init__(self, mapping=None, wait_ok=True, html="<html></html>"):
        super().__init__(children=mapping or {})
        self.wait_ok = wait_ok
        self._html = html
        self.clicked = []

    def wait_for_selector(self, sel, timeout=None):
        if not self.wait_ok:
            raise PWTimeout("timeout")

    def click(self, sel, timeout=None):
        self.clicked.append(sel)

    def content(self):
        return self._html


# --- finn -----------------------------------------------------------------


def _finn_card():
    link = FakeEl(text="Daglig leder", attrs={"href": "/job/ad/123"}, tag_name="a")
    return FakeEl(
        children={
            "a[href*='/job/ad/']": link,
            ".text-caption.s-text-subtle, .s-text-subtle strong, strong": FakeEl(
                text="Acme AS"
            ),
            "li.min-w-0 span, .job-card__pills li:first-child span": FakeEl(
                text="Oslo"
            ),
            "time, [datetime]": FakeEl(attrs={"datetime": "2024-05-01T09:00:00"}),
        },
        tag_name="article",
    )


def test_finn_parse_happy_path():
    from src.scraper.finn_scraper import _parse_listing_page

    page = FakePage(mapping={"article": [_finn_card()]})
    out = _parse_listing_page(page, "seafood")
    assert len(out) == 1
    assert out[0]["external_id"] == "123"
    assert out[0]["title"] == "Daglig leder"
    assert out[0]["company_name"] == "Acme AS"
    assert out[0]["location"] == "Oslo"
    assert out[0]["published_at"] == "2024-05-01"


def test_finn_parse_empty_page_returns_empty_and_snapshots(tmp_path, monkeypatch):
    from src.scraper import base
    from src.scraper.finn_scraper import _parse_listing_page

    monkeypatch.setattr(base, "SNAPSHOT_DIR", tmp_path)
    out = _parse_listing_page(FakePage(wait_ok=False), "seafood")
    assert out == []
    assert list(tmp_path.glob("finn_nocards_seafood_*.html"))


# --- nav -------------------------------------------------------------------


def _nav_link():
    container = FakeEl(
        text="Daglig leder\nArbeidsgiver: Acme AS\nSted: Oslo\nPublisert: 01.05.2024",
        tag_name="article",
    )
    link = FakeEl(
        text="Daglig leder",
        attrs={"href": "/stillinger/stilling/abc-123"},
        tag_name="a",
        parent=container,
    )
    return link


def test_nav_parse_happy_path():
    from src.scraper.nav_scraper import _parse_listing_page

    page = FakePage(mapping={"a[href*='/stillinger/stilling/']": [_nav_link()]})
    out = _parse_listing_page(page, "seafood")
    assert len(out) == 1
    assert out[0]["company_name"] == "Acme AS"
    assert out[0]["location"] == "Oslo"
    assert out[0]["source"] == "nav"


def test_nav_parse_empty_page_returns_empty(tmp_path, monkeypatch):
    from src.scraper import base
    from src.scraper.nav_scraper import _parse_listing_page

    monkeypatch.setattr(base, "SNAPSHOT_DIR", tmp_path)
    assert _parse_listing_page(FakePage(wait_ok=False), "seafood") == []
    assert list(tmp_path.glob("nav_nocards_seafood_*.html"))


# --- karrierestart / jobbnorge ----------------------------------------------


def _ks_card(base_url, job_path):
    link = FakeEl(text="Butikksjef", attrs={"href": f"{job_path}/42"}, tag_name="a")
    return FakeEl(
        children={
            f"a[href*='{job_path}/']": link,
            "h2, h3, h4, [class*='title']": FakeEl(text="Butikksjef"),
            "[class*='company'], [class*='employer'], strong": FakeEl(text="Acme AS"),
            "[class*='location'], [class*='place']": FakeEl(text="Bergen"),
            "time, [datetime]": FakeEl(attrs={"datetime": "2024-06-01T00:00:00"}),
        },
        tag_name="article",
    )


def test_karrierestart_parse_happy_path():
    from src.scraper.karrierestart_scraper import _parse_listing_page

    page = FakePage(
        mapping={
            "a[href*='/ledig-stilling/'], .job-listing, article": None,
            ".job-listing, article, .search-result-item, [class*='job-card']": [
                _ks_card("", "/ledig-stilling")
            ],
        }
    )
    # wait_for_selector succeeds (wait_ok default True)
    out = _parse_listing_page(page, "seafood")
    assert len(out) == 1
    assert out[0]["title"] == "Butikksjef"
    assert out[0]["source"] == "karrierestart"


# --- base helpers -------------------------------------------------------------


def test_accept_cookies_clicks_norwegian_variant():
    from src.scraper.base import accept_cookies

    page = FakePage()
    assert accept_cookies(page) is True
    assert page.clicked and "Godta" in page.clicked[0]


def test_check_selectors_counts():
    from src.scraper.base import check_selectors

    page = FakePage(mapping={"a": [FakeEl(), FakeEl()]})
    assert check_selectors(page, {"links": "a", "missing": "zzz"}) == {
        "links": 2,
        "missing": 0,
    }


def test_browser_context_shared_mode_closes():
    from unittest.mock import MagicMock

    from src.scraper.base import browser_context

    browser = MagicMock()
    ctx = MagicMock()
    browser.new_context.return_value = ctx
    with browser_context(browser) as yielded:
        assert yielded is ctx
    ctx.close.assert_called_once_with()
