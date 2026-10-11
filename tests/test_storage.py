"""測試文章儲存與圖片路徑安全規則。"""

import json

import pytest

from ithome_editor.storage import Storage, editor_article_id


def test_create_save_load_and_list(tmp_path):
    storage = Storage(tmp_path)
    storage.create_article("day-01", "第一天")
    storage.save("day-01", "第一天修正", "hello\n![x](images/a.png)")
    article = storage.load("day-01")
    rows = storage.list_articles()

    assert article.title == "第一天修正"
    assert article.body.startswith("hello")
    assert rows[0]["slug"] == "day-01"
    assert rows[0]["image_count"] == 1
    assert rows[0]["unuploaded_count"] == 1


def test_reject_bad_slug_and_path_traversal(tmp_path):
    storage = Storage(tmp_path)
    with pytest.raises(ValueError):
        storage.create_article("../bad", "錯誤")
    with pytest.raises(ValueError):
        storage.create_article("bad/name", "錯誤")


def test_save_image_sanitizes_and_deduplicates(tmp_path):
    storage = Storage(tmp_path)
    storage.create_article("demo", "示範")
    first = storage.save_image("demo", "../a b.png", b"one")
    second = storage.save_image("demo", "a_b.png", b"two")

    assert first == "images/a_b.png"
    assert second == "images/a_b-1.png"


def test_save_image_rejects_size_and_extension(tmp_path):
    storage = Storage(tmp_path)
    storage.create_article("demo", "示範")
    with pytest.raises(ValueError):
        storage.save_image("demo", "bad.txt", b"x")
    with pytest.raises(ValueError):
        storage.save_image("demo", "big.png", b"x" * (5 * 1024 * 1024 + 1))


def test_save_image_keeps_suffix_for_chinese_names(tmp_path):
    storage = Storage(tmp_path)
    storage.create_article("demo", "示範")

    assert storage.save_image("demo", "截圖.png", b"one") == "images/image.png"
    assert storage.save_image("demo", "截圖 2026.PNG", b"two") == "images/2026.png"
    with pytest.raises(ValueError):
        storage.save_image("demo", "abc.txt", b"x")


def test_import_file(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# 標題\n", encoding="utf-8")
    storage = Storage(tmp_path / "articles")
    storage.import_file(source, "imported", "匯入")
    assert storage.load("imported").body == "# 標題\n"


def test_delete_record_removes_list_entry_but_keeps_article_file(tmp_path):
    storage = Storage(tmp_path)
    storage.create_article("demo", "示範")
    article_path = tmp_path / "demo" / "article.md"

    storage.delete_record("demo")

    assert "demo" not in {item["slug"] for item in storage.list_articles()}
    assert article_path.exists()


def test_delete_article_removes_directory(tmp_path):
    storage = Storage(tmp_path)
    storage.create_article("demo", "示範")
    article_dir = tmp_path / "demo"

    storage.delete_article("demo")

    assert not article_dir.exists()


def test_delete_missing_article_raises_file_not_found(tmp_path):
    storage = Storage(tmp_path)

    with pytest.raises(FileNotFoundError):
        storage.delete_record("missing")
    with pytest.raises(FileNotFoundError):
        storage.delete_article("missing")


def test_delete_rejects_path_traversal_slug(tmp_path):
    storage = Storage(tmp_path)

    with pytest.raises(ValueError):
        storage.delete_record("../bad")
    with pytest.raises(ValueError):
        storage.delete_article("../bad")


def test_meta_defaults_for_new_and_legacy(tmp_path):
    storage = Storage(tmp_path)
    article = storage.create_article("demo", "示範")

    assert article.series == ""
    assert article.day is None
    assert article.saved_draft is False
    assert article.saved_draft_at is None

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "article.md").write_text("舊文章", encoding="utf-8")
    (legacy_dir / "meta.json").write_text(
        json.dumps(
            {
                "title": "舊文章",
                "slug": "legacy",
                "draft_url": None,
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    legacy = storage.load("legacy")

    assert legacy.series == ""
    assert legacy.day is None
    assert legacy.saved_draft is False
    assert legacy.saved_draft_at is None


def test_save_series_and_day(tmp_path):
    storage = Storage(tmp_path)
    storage.create_article("demo", "示範")

    article = storage.save("demo", "示範", "內容", series=" 鐵人賽A ", day=3)
    kept = storage.save("demo", "示範", "內容更新")

    assert article.series == "鐵人賽A"
    assert article.day == 3
    assert kept.series == "鐵人賽A"
    assert kept.day == 3

    cleared = storage.save("demo", "示範", "內容", day=None)
    assert cleared.day is None
    assert cleared.series == "鐵人賽A"


def test_mark_saved_draft_rewrites_draft_to_edit(tmp_path):
    storage = Storage(tmp_path)
    storage.create_article("demo", "示範")
    article = storage.save("demo", "示範", "內容", "https://ithelp.ithome.com.tw/articles/10423260/draft")
    meta_path = tmp_path / "demo" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["updated_at"] = "2026-01-01 00:00:00"
    storage._write_json(meta_path, meta)

    saved = storage.mark_saved_draft("demo", True)
    unsaved = storage.mark_saved_draft("demo", False)

    assert article.draft_url == "https://ithelp.ithome.com.tw/articles/10423260/draft"
    assert saved.draft_url == "https://ithelp.ithome.com.tw/articles/10423260/edit"
    assert saved.saved_draft is True
    assert saved.saved_draft_at
    assert saved.updated_at == "2026-01-01 00:00:00"
    assert unsaved.saved_draft is False
    assert unsaved.saved_draft_at is None
    assert unsaved.draft_url == "https://ithelp.ithome.com.tw/articles/10423260/edit"


def test_editor_article_id():
    assert editor_article_id("https://ithelp.ithome.com.tw/articles/1/draft") == "1"
    assert editor_article_id("https://ithelp.ithome.com.tw/articles/1/edit") == "1"
    assert editor_article_id("https://ithelp.ithome.com.tw/articles/1/edit/") == "1"
    assert editor_article_id(None) is None
    assert editor_article_id("https://ithelp.ithome.com.tw/articles/1") is None


def test_list_articles_includes_article_id_and_defaults(tmp_path):
    storage = Storage(tmp_path)
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "article.md").write_text("", encoding="utf-8")
    (legacy_dir / "uploads.json").write_text("{}", encoding="utf-8")
    (legacy_dir / "meta.json").write_text(
        json.dumps(
            {
                "title": "舊文章",
                "slug": "legacy",
                "draft_url": "https://ithelp.ithome.com.tw/articles/10423260/edit",
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    row = storage.list_articles()[0]

    assert row["article_id"] == "10423260"
    assert row["series"] == ""
    assert row["day"] is None
    assert row["saved_draft"] is False
