"""測試 Flask API 的表格預覽與套用流程。"""

from datetime import datetime
from pathlib import Path

from ithome_editor.config import AppConfig, IthomeConfig, ServerConfig
from ithome_editor.webapp import create_app


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


def test_api_render_returns_tables(tmp_path):
    app = create_app(make_config(tmp_path))
    client = app.test_client()

    res = client.post("/ithome/api/render", json={"slug": "demo", "body": "| a |\n|---|\n| b |\n"})
    data = res.get_json()

    assert res.status_code == 200
    assert data["ok"] is True
    assert 'data-table-index="0"' in data["html"]
    assert data["tables"][0]["header"] == ["a"]
    assert data["tables"][0]["rows"] == [["b"]]


def test_api_table_serialize(tmp_path):
    app = create_app(make_config(tmp_path))
    client = app.test_client()

    res = client.post("/ithome/api/table/serialize", json={"aligns": ["left"], "header": ["a"], "rows": [["b"]]})
    data = res.get_json()

    assert res.status_code == 200
    assert data == {"ok": True, "markdown": "| a   |\n| :-- |\n| b   |"}


def test_api_table_apply_returns_body_and_line_delta(tmp_path):
    app = create_app(make_config(tmp_path))
    client = app.test_client()
    body = "前\n| a |\n|---|\n| b |\n後\n"

    res = client.post(
        "/ithome/api/table/apply",
        json={
            "body": body,
            "start_line": 1,
            "end_line": 4,
            "aligns": ["left", "right"],
            "header": ["a", "b"],
            "rows": [["1", "2"], ["3", "4"]],
        },
    )
    data = res.get_json()

    assert res.status_code == 200
    assert data["ok"] is True
    assert data["line_delta"] == 1
    assert data["body"] == "前\n| a   | b   |\n| :-- | --: |\n| 1   | 2   |\n| 3   | 4   |\n後\n"


def test_api_table_validation_errors(tmp_path):
    app = create_app(make_config(tmp_path))
    client = app.test_client()

    res = client.post("/ithome/api/table/serialize", json={"aligns": ["bad"], "header": ["a"], "rows": []})
    assert res.status_code == 400
    assert res.get_json()["ok"] is False

    res = client.post("/ithome/api/table/apply", json={"body": "", "start_line": 0, "end_line": 0, "aligns": [], "header": [], "rows": []})
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_api_delete_record_success(tmp_path):
    app = create_app(make_config(tmp_path))
    client = app.test_client()
    storage = app.config["STORAGE"]
    storage.create_article("demo", "示範")

    res = client.delete("/ithome/api/articles/demo", json={"mode": "record"})

    assert res.status_code == 200
    assert res.get_json() == {"ok": True}
    assert storage.list_articles() == []
    assert (tmp_path / "articles" / "demo" / "article.md").exists()


def test_api_delete_rejects_bad_mode(tmp_path):
    app = create_app(make_config(tmp_path))
    client = app.test_client()
    app.config["STORAGE"].create_article("demo", "示範")

    res = client.delete("/ithome/api/articles/demo", json={"mode": "bad"})
    data = res.get_json()

    assert res.status_code == 400
    assert data == {"ok": False, "error": "mode 只能是 record 或 all"}


def test_api_save_validates_day(tmp_path):
    app = create_app(make_config(tmp_path))
    client = app.test_client()
    storage = app.config["STORAGE"]
    storage.create_article("demo", "示範")

    res = client.put("/ithome/api/articles/demo", json={"title": "示範", "body": "", "day": "abc"})
    assert res.status_code == 400
    assert res.get_json() == {"ok": False, "error": "Day 必須是正整數"}

    res = client.put("/ithome/api/articles/demo", json={"title": "示範", "body": "", "day": ""})
    assert res.status_code == 200
    assert storage.load("demo").day is None

    res = client.put("/ithome/api/articles/demo", json={"title": "示範", "body": "", "day": 5})
    assert res.status_code == 200
    assert storage.load("demo").day == 5

    # 缺鍵不更動，空字串清空
    res = client.put("/ithome/api/articles/demo", json={"title": "示範", "body": ""})
    assert res.status_code == 200
    assert storage.load("demo").day == 5
    res = client.put("/ithome/api/articles/demo", json={"title": "示範", "body": "", "day": ""})
    assert res.status_code == 200
    assert storage.load("demo").day is None


def test_api_saved_draft_marks_and_rewrites_url(tmp_path):
    app = create_app(make_config(tmp_path))
    client = app.test_client()
    storage = app.config["STORAGE"]
    storage.create_article("demo", "示範")
    storage.save("demo", "示範", "", "https://ithelp.ithome.com.tw/articles/10423260/draft")

    res = client.post("/ithome/api/articles/demo/saved-draft", json={"saved": True})
    data = res.get_json()

    assert res.status_code == 200
    assert data["ok"] is True
    assert data["article"]["saved_draft"] is True
    assert data["article"]["draft_url"] == "https://ithelp.ithome.com.tw/articles/10423260/edit"
    assert data["article"]["article_id"] == "10423260"


def test_index_page_renders_tabs(tmp_path):
    app = create_app(make_config(tmp_path))
    client = app.test_client()

    res = client.get("/ithome/")
    html = res.get_data(as_text=True)

    assert res.status_code == 200
    assert "其他年份" in html
    assert str(datetime.now().year) in html
