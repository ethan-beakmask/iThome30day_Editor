"""透過 Playwright 控制已登入瀏覽器完成圖片上傳與草稿寫入。"""

from __future__ import annotations

import base64
from datetime import datetime
import difflib
import hashlib
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .config import AppConfig
from .renderer import normalize_html, render_markdown
from .storage import LOCAL_IMAGE_RE, Storage


def sha256_file(path: Path) -> str:
    """計算檔案 SHA-256。"""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_local_images(body: str, mapping: dict[str, str]) -> str:
    """把 Markdown 中的本地圖片連結替換成已上傳 URL。"""

    def repl(match: re.Match[str]) -> str:
        local = match.group(1)
        url = mapping.get(local)
        if not url:
            return match.group(0)
        return f"![{url}]({url})"

    return LOCAL_IMAGE_RE.sub(repl, body)


def parse_editor_url(url: str) -> tuple[str, str] | None:
    """解析 ithelp 文章編輯頁 URL，回傳文章 id 與頁面種類。"""

    parsed = urlparse(url)
    match = re.fullmatch(r"/articles/(\d+)/(draft|edit)/?", parsed.path)
    if not match:
        return None
    return match.group(1), match.group(2)


class Publisher:
    """封裝 ithelp 上稿流程。"""

    def __init__(self, config: AppConfig, storage: Storage | None = None):
        self.config = config
        self.storage = storage or Storage(config.server.articles_dir)
        self._playwright = None
        self.browser = None
        self.last_page_url = None

    def connect(self):
        """連線到使用者已啟動的 Chrome 遠端除錯埠。"""

        try:
            self._playwright = sync_playwright().start()
            self.browser = self._playwright.chromium.connect_over_cdp(self.config.ithome.cdp_url)
            return self.browser
        except Exception as exc:
            raise RuntimeError(
                f"無法連線 Chrome 遠端除錯埠 {self.config.ithome.cdp_url}，請確認 Chrome 以 --remote-debugging-port 啟動"
            ) from exc

    def close(self) -> None:
        """關閉 Playwright 控制物件（只斷開 CDP 連線，不會關掉使用者的 Chrome）。"""

        if self.browser:
            self.browser.close()
            self.browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def __enter__(self) -> "Publisher":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def find_or_open_page(self, url: str):
        """尋找既有分頁；找不到時開新分頁。"""

        browser = self.browser or self.connect()
        contexts = browser.contexts or [browser.new_context()]
        parsed_target = parse_editor_url(url)
        if parsed_target:
            target_article_id, target_kind = parsed_target
            fallback_page = None
            for context in contexts:
                for page in context.pages:
                    parsed_page = parse_editor_url(page.url)
                    if not parsed_page:
                        continue
                    page_article_id, page_kind = parsed_page
                    if page_article_id != target_article_id:
                        continue
                    if page_kind == target_kind:
                        self.last_page_url = page.url
                        return page
                    fallback_page = fallback_page or page
            if fallback_page:
                self.last_page_url = fallback_page.url
                return fallback_page
        else:
            for context in contexts:
                for page in context.pages:
                    if page.url == url or page.url.startswith(url):
                        self.last_page_url = page.url
                        return page

        page = contexts[0].new_page()
        page.goto(url, wait_until="networkidle")
        self.last_page_url = page.url
        if parsed_target:
            parsed_page = parse_editor_url(page.url)
            if not parsed_page or parsed_page[0] != parsed_target[0]:
                raise RuntimeError(
                    f"開啟 {url} 後落在 {page.url}，不是編輯頁；請在瀏覽器開好該文章的 /draft 或 /edit 頁再試"
                )
        return page

    def assert_logged_in(self, page) -> None:
        """確認目前 ithelp 分頁已登入。"""

        locator = page.locator("xpath=/html/body/div[1]/nav/div[1]/div/ul[2]/li[7]/a/span[2]")
        try:
            text = locator.inner_text(timeout=3000).strip()
        except PlaywrightTimeoutError as exc:
            raise RuntimeError("尚未登入 iT邦幫忙，請先在 Chrome 分頁登入後再試") from exc
        if not text:
            raise RuntimeError("尚未登入 iT邦幫忙，請先在 Chrome 分頁登入後再試")

    def upload_image(self, page, local_path: Path) -> str:
        """用瀏覽器 fetch 上傳圖片並回傳官方 URL。"""

        raw = local_path.read_bytes()
        payload = {
            "site": self.config.ithome.site,
            "filename": local_path.name,
            "content_type": _content_type(local_path),
            "base64": base64.b64encode(raw).decode("ascii"),
        }
        result = page.evaluate(
            """
            async (payload) => {
              const tokenEl = document.querySelector('input[name=_token]');
              if (!tokenEl) return {error: '找不到 _token'};
              const bytes = Uint8Array.from(atob(payload.base64), c => c.charCodeAt(0));
              const blob = new Blob([bytes], {type: payload.content_type});
              const fd = new FormData();
              fd.append('images[]', blob, payload.filename);
              fd.append('_token', tokenEl.value);
              const response = await fetch(payload.site + '/api/upload', {
                method: 'POST',
                body: fd,
                credentials: 'include'
              });
              const text = await response.text();
              let data = null;
              try { data = JSON.parse(text); } catch (_err) {}
              if (!response.ok || !data || !data.url) {
                return {error: '上傳失敗', status: response.status, text};
              }
              return {url: data.url};
            }
            """,
            payload,
        )
        if not result or not result.get("url"):
            status = result.get("status", "") if isinstance(result, dict) else ""
            text = result.get("text", "") if isinstance(result, dict) else ""
            error = result.get("error", "上傳失敗") if isinstance(result, dict) else "上傳失敗"
            raise RuntimeError(f"{error} HTTP {status}：{text[:300]}")
        return result["url"]

    def publish(self, slug: str, draft_url: str | None = None, fill: bool = True) -> tuple[str, list[str]]:
        """上傳本地圖片、產生最終稿，必要時寫入 ithelp 草稿頁。"""

        article = self.storage.load(slug)
        target_url = draft_url or article.draft_url
        if not target_url:
            raise ValueError("缺少草稿 URL")
        page = self.find_or_open_page(target_url)
        self.assert_logged_in(page)

        log: list[str] = [f"使用編輯頁：{self.last_page_url}"]
        uploads = self.storage.load_uploads(slug)
        mapping: dict[str, str] = {}
        missing: list[str] = []
        for image in self.storage.find_local_images(article.body):
            path = self.storage.image_path(slug, image)
            if not path.exists():
                missing.append(image)
                continue
            digest = sha256_file(path)
            if image in uploads and uploads[image].get("sha256") == digest:
                mapping[image] = uploads[image]["url"]
                log.append(f"略過已上傳：{image}")
                continue
            url = self.upload_image(page, path)
            uploads[image] = {"url": url, "sha256": digest, "uploaded_at": _now()}
            self.storage.save_uploads(slug, uploads)
            mapping[image] = url
            log.append(f"已上傳：{image} -> {url}")
        if missing:
            raise FileNotFoundError("找不到圖片：" + "、".join(missing))

        published_md = replace_local_images(article.body, mapping)
        self.storage.write_published(slug, published_md)
        log.append("已產生 article.published.md")

        if fill:
            page.evaluate(
                """
                ({title, body}) => {
                  const subject = document.querySelector('input[name=subject]');
                  if (!subject) throw new Error('找不到標題欄位');
                  subject.value = title;
                  subject.dispatchEvent(new Event('input', {bubbles: true}));
                  const simplemde = window.$ && window.$('#SimpleMDE_0').data('simplemde');
                  if (!simplemde) throw new Error('找不到 SimpleMDE');
                  simplemde.value(body);
                  const textarea = document.querySelector('#SimpleMDE_0');
                  if (textarea) textarea.dispatchEvent(new Event('input', {bubbles: true}));
                }
                """,
                {"title": article.title, "body": published_md},
            )
            log.append("已寫入 ithelp 編輯頁，請到瀏覽器按儲存草稿或發表／更新")
        return published_md, log

    def official_preview(self, page, md: str) -> str:
        """透過瀏覽器向官方 /api/preview 取得 HTML。"""

        result = page.evaluate(
            """
            async ({site, md}) => {
              const tokenEl = document.querySelector('input[name=_token]');
              if (!tokenEl) return {error: '找不到 _token'};
              const body = new URLSearchParams();
              body.set('description', md);
              body.set('_token', tokenEl.value);
              const response = await fetch(site + '/api/preview', {
                method: 'POST',
                body,
                credentials: 'include',
                headers: {'X-Requested-With': 'XMLHttpRequest'}
              });
              const text = await response.text();
              if (!response.ok) return {error: '官方預覽失敗', status: response.status, text};
              return {html: text};
            }
            """,
            {"site": self.config.ithome.site, "md": md},
        )
        if not result or not result.get("html"):
            status = result.get("status", "") if isinstance(result, dict) else ""
            text = result.get("text", "") if isinstance(result, dict) else ""
            raise RuntimeError(f"官方預覽失敗 HTTP {status}：{text[:300]}")
        return result["html"]

    def check(self, slug: str, draft_url: str | None = None) -> tuple[bool, str]:
        """比對本地渲染結果與官方預覽。"""

        article = self.storage.load(slug)
        target_url = draft_url or article.draft_url
        if not target_url:
            raise ValueError("缺少草稿 URL")
        uploads = self.storage.load_uploads(slug)
        mapping = {path: item["url"] for path, item in uploads.items() if item.get("url")}
        body = replace_local_images(article.body, mapping)
        local_lines = normalize_html(render_markdown(body, image_base_url=""))
        page = self.find_or_open_page(target_url)
        self.assert_logged_in(page)
        official_lines = normalize_html(self.official_preview(page, body))
        diff = "\n".join(difflib.unified_diff(local_lines, official_lines, fromfile="local", tofile="official", lineterm=""))
        if not diff:
            return True, f"使用編輯頁：{self.last_page_url}"
        return False, diff


def _content_type(path: Path) -> str:
    mapping = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
    return mapping.get(path.suffix.lower(), "application/octet-stream")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
