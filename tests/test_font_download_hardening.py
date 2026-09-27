"""The font fetch is a network call whose bytes are loaded into the PDF engine.

`utils.pdf_generator._download_font` therefore has to treat the network as
untrusted. These tests pin that contract, because a single `# nosec B310`
marker is only defensible while the mitigation underneath it is enforced by
something other than that comment.
"""
import io
import urllib.request

import pytest

from utils import pdf_generator as pg


class _FakeResponse(io.BytesIO):
    """Minimal stand-in for the object urlopen returns."""

    def __init__(self, payload=b"", headers=None, final_url="https://x/f.ttf"):
        super().__init__(payload)
        self.headers = headers or {}
        self._final_url = final_url

    def geturl(self):
        return self._final_url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def test_every_configured_font_source_is_https():
    """The allowlist is only meaningful if the constants obey it."""
    assert pg.FONT_SOURCES
    for name, url in pg.FONT_SOURCES.items():
        assert url.lower().startswith("https://"), name


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "http://example.com/f.ttf",
    "ftp://example.com/f.ttf",
    "/etc/passwd",
    "",
])
def test_non_https_urls_are_refused_before_any_socket_is_opened(url, monkeypatch):
    def explode(*a, **k):
        raise AssertionError("urlopen must not be reached")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    with pytest.raises(ValueError):
        pg._download_font(url, "unused.ttf")


def test_redirect_to_plain_http_is_refused(monkeypatch):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **k: _FakeResponse(b"x", final_url="http://evil/f.ttf"))
    with pytest.raises(ValueError):
        pg._download_font("https://ok/f.ttf", "unused.ttf")


def test_oversized_body_is_refused_and_nothing_is_written(monkeypatch, tmp_path):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **k: _FakeResponse(b"x" * 32))
    monkeypatch.setattr(pg, "MAX_FONT_BYTES", 16)
    dest = tmp_path / "f.ttf"
    with pytest.raises(ValueError):
        pg._download_font("https://ok/f.ttf", str(dest))
    assert not dest.exists()


def test_oversized_content_length_is_refused_before_reading(monkeypatch, tmp_path):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **k: _FakeResponse(b"x", headers={"Content-Length": "99999999"}))
    dest = tmp_path / "f.ttf"
    with pytest.raises(ValueError):
        pg._download_font("https://ok/f.ttf", str(dest))
    assert not dest.exists()


def test_a_healthy_https_fetch_is_written(monkeypatch, tmp_path):
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **k: _FakeResponse(b"ttf-bytes"))
    dest = tmp_path / "f.ttf"
    pg._download_font("https://ok/f.ttf", str(dest))
    assert dest.read_bytes() == b"ttf-bytes"


def test_a_fetch_timeout_is_always_supplied(monkeypatch, tmp_path):
    seen = {}

    def capture(request, timeout=None):
        seen["timeout"] = timeout
        return _FakeResponse(b"x")

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    pg._download_font("https://ok/f.ttf", str(tmp_path / "f.ttf"))
    assert seen["timeout"] == pg.FONT_FETCH_TIMEOUT


def test_ensure_fonts_survives_a_network_failure(monkeypatch):
    """The offline contract: a dead network must not stop PDFs generating."""

    def refuse(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(pg, "_ARABIC_FONT_READY", False)
    pg.ensure_fonts()  # must not raise
