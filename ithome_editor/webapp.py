"""Flask Web 編輯器應用程式。"""

from __future__ import annotations

from pathlib import Path
import subprocess
import traceback

from flask import Blueprint, Flask, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import HTTPException

from .config import AppConfig, load_config
from .publisher import Publisher
from .renderer import render_with_tables, replace_lines, serialize_table
from .storage import Storage


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_info() -> dict[str, str]:
    """回報程式所在目錄與 git 短碼，供頁尾辨識目前跑的是哪一棵工作樹。"""

    try:
        rev = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3, check=False,
        ).stdout.strip() or "no-git"
    except (OSError, subprocess.SubprocessError):
        rev = "no-git"
    return {"root": str(PROJECT_ROOT), "rev": rev}


def create_app(config: AppConfig | None = None) -> Flask:
    """建立 Flask 應用程式。"""

    config = config or load_config()
    prefix = config.server.prefix
    app = Flask(__name__, static_url_path=f"{prefix}/static", static_folder="../static", template_folder="../templates")
    app.config["APP_CONFIG"] = config
    app.config["STORAGE"] = Storage(config.server.articles_dir)
    app.config["BUILD_INFO"] = build_info()
    bp = Blueprint("main", __name__, url_prefix=prefix)

    @app.context_processor
    def _inject_build_info():
        return {"build_info": app.config["BUILD_INFO"]}

    @bp.get("/")
    def index():
        storage = _storage()
        return render_template("index.html", articles=storage.list_articles(), prefix=prefix)

    @bp.get("/edit/<slug>")
    def editor(slug: str):
        article = _storage().load(slug)
        return render_template("editor.html", article=article, prefix=prefix)

    @bp.get("/preview-frame")
    def preview_frame():
        return render_template("preview_frame.html", prefix=prefix)

    @bp.get("/articles/<slug>/images/<filename>")
    def image(slug: str, filename: str):
        path = _storage().image_path(slug, f"images/{filename}")
        return send_file(path)

    @bp.post("/api/articles")
    def api_create_article():
        data = _payload()
        article = _storage().create_article(data.get("slug", ""), data.get("title", ""))
        return jsonify({"ok": True, "article": _article_json(article)})

    @bp.get("/api/articles/<slug>")
    def api_get_article(slug: str):
        return jsonify({"ok": True, "article": _article_json(_storage().load(slug)), "uploads": _storage().load_uploads(slug)})

    @bp.put("/api/articles/<slug>")
    def api_save_article(slug: str):
        data = _payload()
        article = _storage().save(slug, data.get("title", ""), data.get("body", ""), data.get("draft_url"))
        return jsonify({"ok": True, "article": _article_json(article), "images": _image_status(slug, article.body)})

    @bp.delete("/api/articles/<slug>")
    def api_delete_article(slug: str):
        data = _payload()
        mode = data.get("mode")
        if mode == "record":
            _storage().delete_record(slug)
        elif mode == "all":
            _storage().delete_article(slug)
        else:
            return _json_error("mode 只能是 record 或 all", 400)
        return jsonify({"ok": True})

    @bp.post("/api/articles/<slug>/images")
    def api_upload_local_image(slug: str):
        file = request.files.get("image")
        if not file:
            return _json_error("缺少圖片檔案", 400)
        path = _storage().save_image(slug, file.filename or "image.png", file.read())
        return jsonify({"ok": True, "path": path, "markdown": f"![{path}]({path})"})

    @bp.post("/api/render")
    def api_render():
        data = _payload()
        slug = data.get("slug", "")
        body = data.get("body", "")
        html, tables = render_with_tables(body, image_base_url=f"{prefix}/articles/{slug}")
        return jsonify({"ok": True, "html": html, "tables": tables, "images": _image_status(slug, body)})

    @bp.post("/api/table/serialize")
    def api_table_serialize():
        data = _payload()
        try:
            aligns, header, rows = _table_payload(data)
            markdown = serialize_table(aligns, header, rows)
        except ValueError as exc:
            return _json_error(str(exc), 400)
        return jsonify({"ok": True, "markdown": markdown})

    @bp.post("/api/table/apply")
    def api_table_apply():
        data = _payload()
        try:
            body = data.get("body", "")
            start_line = int(data.get("start_line"))
            end_line = int(data.get("end_line"))
            aligns, header, rows = _table_payload(data)
            markdown = serialize_table(aligns, header, rows)
            new_body = replace_lines(body, start_line, end_line, markdown)
        except (TypeError, ValueError) as exc:
            return _json_error(str(exc), 400)
        old_count = end_line - start_line
        new_count = len(markdown.splitlines())
        return jsonify({"ok": True, "body": new_body, "line_delta": new_count - old_count})

    @bp.post("/api/articles/<slug>/publish")
    def api_publish(slug: str):
        data = _payload()
        with Publisher(_config(), _storage()) as publisher:
            published_md, log = publisher.publish(slug, data.get("draft_url"), fill=True)
        return jsonify({"ok": True, "log": log, "published_md": published_md})

    @bp.post("/api/articles/<slug>/check")
    def api_check(slug: str):
        data = _payload()
        with Publisher(_config(), _storage()) as publisher:
            identical, diff = publisher.check(slug, data.get("draft_url"))
        return jsonify({"ok": True, "identical": identical, "diff": diff})

    @bp.post("/api/articles/import")
    def api_import_article():
        data = _payload()
        article = _storage().import_file(data.get("path", ""), data.get("slug", ""), data.get("title", ""))
        return jsonify({"ok": True, "article": _article_json(article)})

    @app.errorhandler(Exception)
    def handle_error(exc: Exception):
        if isinstance(exc, HTTPException):
            if request.path.startswith(f"{prefix}/api/"):
                return _json_error(exc.description or exc.name, exc.code or 500)
            return exc
        app.logger.error("處理請求失敗：%s\n%s", exc, traceback.format_exc())
        if request.path.startswith(f"{prefix}/api/"):
            return _json_error(str(exc), 500)
        return str(exc), 500

    app.register_blueprint(bp)

    @app.get("/")
    def root_redirect():
        return redirect(url_for("main.index"))

    return app


def _config() -> AppConfig:
    return current_app_config()


def current_app_config() -> AppConfig:
    """取得目前 Flask 應用設定。"""

    from flask import current_app

    return current_app.config["APP_CONFIG"]


def _storage() -> Storage:
    from flask import current_app

    return current_app.config["STORAGE"]


def _payload() -> dict:
    if request.is_json:
        return request.get_json(silent=True) or {}
    return dict(request.form)


def _article_json(article) -> dict:
    return {
        "slug": article.slug,
        "title": article.title,
        "body": article.body,
        "draft_url": article.draft_url,
        "created_at": article.created_at,
        "updated_at": article.updated_at,
    }


def _image_status(slug: str, body: str) -> list[dict[str, str | bool]]:
    storage = _storage()
    uploads = storage.load_uploads(slug)
    rows = []
    for path in storage.find_local_images(body):
        item = uploads.get(path) or {}
        rows.append({"path": path, "uploaded": bool(item.get("url")), "url": item.get("url", "")})
    return rows


def _json_error(message: str, status: int):
    return jsonify({"ok": False, "error": message}), status


def _table_payload(data: dict) -> tuple[list[str], list[str], list[list[str]]]:
    aligns = data.get("aligns")
    header = data.get("header")
    rows = data.get("rows", [])
    allowed_aligns = {"left", "center", "right", ""}
    if not isinstance(aligns, list):
        raise ValueError("aligns 必須是陣列")
    if not isinstance(header, list) or not header:
        raise ValueError("header 至少需要一欄")
    if not isinstance(rows, list):
        raise ValueError("rows 必須是陣列")
    if any(align not in allowed_aligns for align in aligns):
        raise ValueError("aligns 只允許 left、center、right 或空字串")
    if not all(isinstance(row, list) for row in rows):
        raise ValueError("rows 每列都必須是陣列")
    return [str(align) for align in aligns], [str(cell) for cell in header], [[str(cell) for cell in row] for row in rows]
