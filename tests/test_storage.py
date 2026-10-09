"""測試文章儲存與圖片路徑安全規則。"""

import pytest

from ithome_editor.storage import Storage


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
