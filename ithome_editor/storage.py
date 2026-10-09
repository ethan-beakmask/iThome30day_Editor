"""文章、圖片與上傳紀錄的本地儲存管理。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
from typing import Any


SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
FILENAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
LOCAL_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((images/[^)\s]+)\)")
ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024


@dataclass
class Article:
    """文章內容與中繼資料。"""

    slug: str
    title: str
    body: str
    draft_url: str | None
    created_at: str
    updated_at: str


def now_text() -> str:
    """回傳儲存用的目前時間字串。"""

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Storage:
    """管理 articles 目錄下的文章資料。"""

    def __init__(self, articles_dir: str | Path):
        self.articles_dir = Path(articles_dir).resolve()
        self.articles_dir.mkdir(parents=True, exist_ok=True)

    def validate_slug(self, slug: str) -> str:
        if not SLUG_RE.fullmatch(slug or ""):
            raise ValueError("slug 只能包含英文字母、數字、底線與連字號")
        return slug

    def article_dir(self, slug: str) -> Path:
        slug = self.validate_slug(slug)
        path = (self.articles_dir / slug).resolve()
        if self.articles_dir not in path.parents and path != self.articles_dir:
            raise ValueError("文章路徑不合法")
        return path

    def list_articles(self) -> list[dict[str, Any]]:
        rows = []
        for meta_path in sorted(self.articles_dir.glob("*/meta.json")):
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            slug = data["slug"]
            body = (meta_path.parent / "article.md").read_text(encoding="utf-8") if (meta_path.parent / "article.md").exists() else ""
            images = self.find_local_images(body)
            uploads = self.load_uploads(slug)
            rows.append(
                {
                    **data,
                    "image_count": len(images),
                    "unuploaded_count": sum(1 for image in images if image not in uploads),
                }
            )
        rows.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return rows

    def create_article(self, slug: str, title: str) -> Article:
        path = self.article_dir(slug)
        if path.exists():
            raise ValueError("文章已存在")
        path.mkdir(parents=True)
        (path / "images").mkdir()
        stamp = now_text()
        meta = {"title": title, "slug": slug, "draft_url": None, "created_at": stamp, "updated_at": stamp}
        (path / "article.md").write_text("", encoding="utf-8")
        self._write_json(path / "meta.json", meta)
        self._write_json(path / "uploads.json", {})
        return self.load(slug)

    def load(self, slug: str) -> Article:
        path = self.article_dir(slug)
        if not path.exists():
            raise FileNotFoundError("找不到文章")
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        body = (path / "article.md").read_text(encoding="utf-8")
        return Article(
            slug=meta["slug"],
            title=meta["title"],
            body=body,
            draft_url=meta.get("draft_url"),
            created_at=meta["created_at"],
            updated_at=meta["updated_at"],
        )

    def save(self, slug: str, title: str, body: str, draft_url: str | None = None) -> Article:
        path = self.article_dir(slug)
        if not path.exists():
            raise FileNotFoundError("找不到文章")
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        meta["title"] = title
        meta["updated_at"] = now_text()
        if draft_url is not None:
            meta["draft_url"] = draft_url or None
        (path / "article.md").write_text(body, encoding="utf-8")
        self._write_json(path / "meta.json", meta)
        return self.load(slug)

    def save_image(self, slug: str, filename: str, data: bytes) -> str:
        if len(data) > MAX_IMAGE_SIZE:
            raise ValueError("圖片超過 5MB")
        source_name = Path(filename).name
        suffix = Path(source_name).suffix.lower()
        if suffix not in ALLOWED_IMAGE_EXTS:
            raise ValueError("圖片副檔名只允許 png、jpg、jpeg、gif、webp")
        stem = FILENAME_RE.sub("_", Path(source_name).stem).strip("._") or "image"
        safe_name = f"{stem}{suffix}"
        images_dir = self.article_dir(slug) / "images"
        images_dir.mkdir(exist_ok=True)
        target = self._unique_path(images_dir, safe_name)
        target.write_bytes(data)
        return f"images/{target.name}"

    def find_local_images(self, body: str) -> list[str]:
        found = []
        for match in LOCAL_IMAGE_RE.finditer(body):
            path = match.group(1)
            if path not in found:
                found.append(path)
        return found

    def import_file(self, path: str | Path, slug: str, title: str) -> Article:
        src = Path(path).expanduser().resolve()
        if src.suffix.lower() not in {".md", ".txt"}:
            raise ValueError("只能匯入 .md 或 .txt 檔案")
        article = self.create_article(slug, title)
        self.save(slug, title, src.read_text(encoding="utf-8"))
        return article

    def load_uploads(self, slug: str) -> dict[str, dict[str, str]]:
        path = self.article_dir(slug) / "uploads.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def save_uploads(self, slug: str, uploads: dict[str, dict[str, str]]) -> None:
        self._write_json(self.article_dir(slug) / "uploads.json", uploads)

    def write_published(self, slug: str, body: str) -> None:
        (self.article_dir(slug) / "article.published.md").write_text(body, encoding="utf-8")

    def image_path(self, slug: str, image_path: str) -> Path:
        if not image_path.startswith("images/"):
            raise ValueError("圖片路徑不合法")
        target = (self.article_dir(slug) / image_path).resolve()
        base = (self.article_dir(slug) / "images").resolve()
        if base not in target.parents:
            raise ValueError("圖片路徑不合法")
        return target

    def _unique_path(self, directory: Path, filename: str) -> Path:
        stem = Path(filename).stem
        suffix = Path(filename).suffix
        candidate = (directory / filename).resolve()
        counter = 1
        while candidate.exists():
            candidate = (directory / f"{stem}-{counter}{suffix}").resolve()
            counter += 1
        if directory.resolve() not in candidate.parents:
            raise ValueError("圖片路徑不合法")
        return candidate

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        shutil.move(str(tmp), str(path))
