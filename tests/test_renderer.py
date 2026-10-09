"""測試 Markdown renderer 是否貼近官方預覽輸出。"""

from pathlib import Path

import pytest

from ithome_editor.renderer import normalize_html, render_markdown, render_with_tables, replace_lines, serialize_table


FIXTURES = Path(__file__).parent / "fixtures"


def test_render_sample_matches_official_after_normalize():
    md = (FIXTURES / "sample.md").read_text(encoding="utf-8")
    official = (FIXTURES / "sample.official.html").read_text(encoding="utf-8")
    assert normalize_html(render_markdown(md)) == normalize_html(official)


def test_rewrite_local_image_src_only():
    html = render_markdown("![images/a.png](images/a.png)", image_base_url="/ithome/articles/demo")
    assert 'src="/ithome/articles/demo/images/a.png"' in html
    assert 'alt="images/a.png"' in html


def test_extract_multiple_tables_with_line_ranges_and_fence():
    text = "\n".join(
        [
            "前文",
            "",
            "| a | b |",
            "|---|---|",
            "| 1 | 2 |",
            "",
            "```",
            "| not | table |",
            "|---|---|",
            "```",
            "",
            "| c | d |",
            "|---|---|",
            "| 3 | 4 |",
            "",
            "後文",
        ]
    )
    _html, tables = render_with_tables(text)

    assert len(tables) == 2
    assert tables[0]["start_line"] == 2
    assert tables[0]["end_line"] == 5
    assert tables[1]["start_line"] == 11
    assert tables[1]["end_line"] == 14


def test_extract_aligns_and_raw_cells():
    text = "\n".join(
        [
            "| left | center | right | none |",
            "|:--|:-:|--:|---|",
            r"| **粗體** | [連結](https://x) | a\|b | c |",
        ]
    )
    _html, tables = render_with_tables(text)

    assert tables[0]["aligns"] == ["left", "center", "right", ""]
    assert tables[0]["rows"][0] == ["**粗體**", "[連結](https://x)", r"a\|b", "c"]


def test_serialize_table_formats_widths_and_escapes_pipes():
    markdown = serialize_table(
        ["left", "center", "right", ""],
        ["中", "bb", "c", "d"],
        [["aa", "測試", "x|y", "z"], ["too", "few"]],
    )

    assert markdown.splitlines() == [
        "| 中  | bb   | c    | d   |",
        "| :-- | :--: | ---: | --- |",
        r"| aa  | 測試 | x\|y | z   |",
        "| too | few  |      |     |",
    ]


def test_serialize_table_with_empty_rows_and_uneven_columns():
    markdown = serialize_table([""], ["a", "b"], [])

    assert markdown == "| a   | b   |\n| --- | --- |"
    assert serialize_table(["left"], ["a"], [["1", "2"]]) == "| a   |\n| :-- |\n| 1   |"


def test_serialize_round_trip_is_stable():
    original = serialize_table(["left", "center", "right"], ["欄位1", "b|c", "d"], [[r"e\|f", "**粗體**", "中"]])
    _html, tables = render_with_tables(original)
    table = tables[0]

    assert serialize_table(table["aligns"], table["header"], table["rows"]) == original


def test_replace_lines_normal_and_out_of_range():
    assert replace_lines("a\nb\nc\n", 1, 2, "x\ny") == "a\nx\ny\nc\n"
    assert replace_lines("a\r\nb\r\nc\r\n", 1, 3, "x") == "a\r\nx\r\n"
    with pytest.raises(ValueError):
        replace_lines("a\n", 1, 3, "x")


def test_table_index_only_in_render_with_tables():
    text = "| a |\n|---|\n| b |\n"

    assert "data-table-index" not in render_markdown(text)
    html, tables = render_with_tables(text)
    assert 'data-table-index="0"' in html
    assert tables[0]["header"] == ["a"]
