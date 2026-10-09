"""測試 iT邦幫忙樣式快取下載流程。"""

from pathlib import Path

import pytest

from ithome_editor.assets import ensure_ithelp_css
from ithome_editor.config import AppConfig, IthomeConfig, ServerConfig


class FakeResponse:
    """模擬 urllib 回應物件。"""

    status = 200

    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def make_config(tmp_path: Path) -> AppConfig:
    """建立測試用應用設定。"""

    return AppConfig(
        ithome=IthomeConfig(
            cdp_url="http://127.0.0.1:9222",
            site="https://ithelp.ithome.com.tw",
        ),
        server=ServerConfig(
            host="127.0.0.1",
            port=5451,
            prefix="/ithome",
            articles_dir=tmp_path / "articles",
            log_file=tmp_path / "app.log",
        ),
        project_root=tmp_path,
    )


def test_ensure_ithelp_css_downloads_missing_files(tmp_path, monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return FakeResponse(f"/* {request.full_url} */".encode("utf-8"))

    monkeypatch.setattr("ithome_editor.assets.urllib.request.urlopen", fake_urlopen)
    cache_dir = ensure_ithelp_css(make_config(tmp_path))

    assert (cache_dir / "style.css").exists()
    assert (cache_dir / "railscasts.css").exists()
    assert len(calls) == 2


def test_ensure_ithelp_css_skips_fresh_cache(tmp_path, monkeypatch):
    cache_dir = tmp_path / "static" / "ithelp_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "style.css").write_text("style", encoding="utf-8")
    (cache_dir / "railscasts.css").write_text("railscasts", encoding="utf-8")

    def fake_urlopen(_request, _timeout):
        raise AssertionError("不應重新下載新鮮快取")

    monkeypatch.setattr("ithome_editor.assets.urllib.request.urlopen", fake_urlopen)
    assert ensure_ithelp_css(make_config(tmp_path)) == cache_dir


def test_ensure_ithelp_css_raises_without_cache_on_failure(tmp_path, monkeypatch):
    def fake_urlopen(_request, _timeout):
        raise OSError("網路失敗")

    monkeypatch.setattr("ithome_editor.assets.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="需要網路連線以取得 iT邦幫忙的樣式檔"):
        ensure_ithelp_css(make_config(tmp_path))


def test_ensure_ithelp_css_uses_cache_on_failure(tmp_path, monkeypatch):
    cache_dir = tmp_path / "static" / "ithelp_cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "style.css").write_text("style", encoding="utf-8")
    (cache_dir / "railscasts.css").write_text("railscasts", encoding="utf-8")

    def fake_urlopen(_request, _timeout):
        raise OSError("網路失敗")

    monkeypatch.setattr("ithome_editor.assets.urllib.request.urlopen", fake_urlopen)
    assert ensure_ithelp_css(make_config(tmp_path), force=True) == cache_dir
