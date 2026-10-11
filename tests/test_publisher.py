"""測試 publisher 的純函式與可替換頁面流程。"""

from pathlib import Path

import pytest

from ithome_editor.config import AppConfig, IthomeConfig, ServerConfig
from ithome_editor.publisher import Publisher, parse_editor_url, replace_local_images, sha256_file
from ithome_editor.storage import Storage


class FakeLocator:
    """模擬 Playwright locator。"""

    def __init__(self, text="已登入"):
        self.text = text

    def inner_text(self, timeout=0):
        return self.text


class FakePage:
    """模擬 Playwright page。"""

    def __init__(self, login_text="已登入", url="https://ithelp.ithome.com.tw/articles/1/draft", goto_url=None):
        self.calls = []
        self.login_text = login_text
        self.url = url
        self.goto_calls = []
        self.goto_url = goto_url

    def locator(self, _selector):
        return FakeLocator(self.login_text)

    def goto(self, url, wait_until=None):
        self.goto_calls.append((url, wait_until))
        if self.goto_url is not None:
            self.url = self.goto_url

    def evaluate(self, script, payload=None):
        self.calls.append((script, payload))
        if payload and payload.get("filename"):
            return {"url": "https://ithelp.ithome.com.tw/upload/images/x.png"}
        return None


class FakeContext:
    """模擬 Playwright context。"""

    def __init__(self, *pages):
        self.pages = list(pages)

    def new_page(self):
        return self.pages[0]


class FakeBrowser:
    """模擬 Playwright browser。"""

    def __init__(self, *pages):
        self.contexts = [FakeContext(*pages)]


def make_config(tmp_path: Path) -> AppConfig:
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


def test_replace_local_images_uses_official_format():
    body = "![alt](images/a.png)\n![keep](images/missing.png)"
    out = replace_local_images(body, {"images/a.png": "https://example.com/a.png"})
    assert "![https://example.com/a.png](https://example.com/a.png)" in out
    assert "![keep](images/missing.png)" in out


def test_sha256_file(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("abc", encoding="utf-8")
    assert sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_parse_editor_url():
    assert parse_editor_url("https://ithelp.ithome.com.tw/articles/1/draft") == ("1", "draft")
    assert parse_editor_url("https://ithelp.ithome.com.tw/articles/1/edit") == ("1", "edit")
    assert parse_editor_url("https://ithelp.ithome.com.tw/articles/1/draft/") == ("1", "draft")
    assert parse_editor_url("https://ithelp.ithome.com.tw/articles/1/edit?foo=bar#top") == ("1", "edit")
    assert parse_editor_url("https://ithelp.ithome.com.tw/articles/1") is None
    assert parse_editor_url("https://ithelp.ithome.com.tw/users/1/draft") is None


def test_find_or_open_page_matches_edit_when_draft_given(tmp_path):
    config = make_config(tmp_path)
    page = FakePage(url="https://ithelp.ithome.com.tw/articles/1/edit")
    publisher = Publisher(config)
    publisher.browser = FakeBrowser(page)

    found = publisher.find_or_open_page("https://ithelp.ithome.com.tw/articles/1/draft")

    assert found is page
    assert page.goto_calls == []
    assert publisher.last_page_url == page.url


def test_find_or_open_page_prefers_same_kind(tmp_path):
    config = make_config(tmp_path)
    edit_page = FakePage(url="https://ithelp.ithome.com.tw/articles/1/edit")
    draft_page = FakePage(url="https://ithelp.ithome.com.tw/articles/1/draft")
    publisher = Publisher(config)
    publisher.browser = FakeBrowser(edit_page, draft_page)

    found = publisher.find_or_open_page("https://ithelp.ithome.com.tw/articles/1/draft")

    assert found is draft_page
    assert publisher.last_page_url == draft_page.url


def test_find_or_open_page_rejects_redirect(tmp_path):
    config = make_config(tmp_path)
    page = FakePage(
        url="https://ithelp.ithome.com.tw/articles/2/edit",
        goto_url="https://ithelp.ithome.com.tw/articles/1",
    )
    publisher = Publisher(config)
    publisher.browser = FakeBrowser(page)

    with pytest.raises(RuntimeError, match="不是編輯頁"):
        publisher.find_or_open_page("https://ithelp.ithome.com.tw/articles/1/draft")


def test_assert_logged_in_rejects_empty_text(tmp_path):
    config = make_config(tmp_path)
    publisher = Publisher(config)
    with pytest.raises(RuntimeError, match="尚未登入"):
        publisher.assert_logged_in(FakePage(login_text=""))


def test_publish_uploads_once_then_reuses(tmp_path):
    config = make_config(tmp_path)
    storage = Storage(config.server.articles_dir)
    storage.create_article("demo", "標題")
    storage.save("demo", "標題", "正文\n![本地](images/a.png)", "https://ithelp.ithome.com.tw/articles/1/draft")
    image = storage.article_dir("demo") / "images" / "a.png"
    image.write_bytes(b"image")

    page = FakePage()
    publisher = Publisher(config, storage)
    publisher.browser = FakeBrowser(page)
    published, log = publisher.publish("demo")

    assert "![https://ithelp.ithome.com.tw/upload/images/x.png](https://ithelp.ithome.com.tw/upload/images/x.png)" in published
    assert log[0].startswith("使用編輯頁：")
    assert any("已上傳" in line for line in log)
    assert storage.load_uploads("demo")["images/a.png"]["sha256"] == sha256_file(image)

    page.calls.clear()
    published_again, log_again = publisher.publish("demo")
    assert published_again == published
    assert any("略過已上傳" in line for line in log_again)
    assert not any(call[1] and call[1].get("filename") for call in page.calls)
