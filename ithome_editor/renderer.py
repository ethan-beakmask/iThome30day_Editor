"""重現 iT邦幫忙官方 Markdown 預覽行為的渲染器。"""

from __future__ import annotations

import re
import unicodedata
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token


BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
ALIGN_STYLE_RE = re.compile(r'\sstyle="text-align:\s*(left|center|right)\s*"', re.IGNORECASE)
ALIGN_VALUE_RE = re.compile(r"text-align:\s*(left|center|right)", re.IGNORECASE)


def _strip_html_block(tokens: list[Token], idx: int, *_args) -> str:
    text = re.sub(r"<[^>]+>", "", tokens[idx].content).strip()
    if not text:
        return ""
    return f"<p>{text}</p>\n"


def _empty_html_inline(_tokens: list[Token], _idx: int, *_args) -> str:
    return ""


def _del_open(*_args) -> str:
    return "<del>"


def _del_close(*_args) -> str:
    return "</del>"


def _image_rule(image_base_url: str, renderer: RendererHTML):
    def render(tokens: list[Token], idx: int, options, env) -> str:
        src = tokens[idx].attrGet("src")
        if image_base_url and src and src.startswith("images/"):
            base = image_base_url.rstrip("/")
            tokens[idx].attrSet("src", f"{base}/{src}")
        return renderer.image(tokens, idx, options, env)

    return render


def _table_open_rule(renderer: RendererHTML):
    def render(tokens: list[Token], idx: int, options, env) -> str:
        if env.get("include_table_indices"):
            table_indices = env.get("table_indices", {})
            if idx in table_indices:
                tokens[idx].attrSet("data-table-index", str(table_indices[idx]))
        return renderer.renderToken(tokens, idx, options, env)

    return render


def make_markdown(image_base_url: str = "") -> MarkdownIt:
    """建立符合官方預覽規格的 MarkdownIt 實例。"""

    md = MarkdownIt(
        "commonmark",
        {"html": True, "breaks": True, "linkify": True, "xhtmlOut": True},
    ).enable(["table", "strikethrough", "linkify"])
    md.renderer.rules["s_open"] = _del_open
    md.renderer.rules["s_close"] = _del_close
    md.renderer.rules["html_inline"] = _empty_html_inline
    md.renderer.rules["html_block"] = _strip_html_block
    md.renderer.rules["image"] = _image_rule(image_base_url, md.renderer)
    md.renderer.rules["table_open"] = _table_open_rule(md.renderer)
    return md


def render_markdown(text: str, image_base_url: str = "") -> str:
    """將 Markdown 轉成 HTML。"""

    return make_markdown(image_base_url=image_base_url).render(text)


def render_with_tables(text: str, image_base_url: str = "") -> tuple[str, list[dict]]:
    """將 Markdown 轉成 HTML，並回傳可編輯表格資訊。"""

    md = make_markdown(image_base_url=image_base_url)
    env: dict = {"include_table_indices": True, "table_indices": {}}
    tokens = md.parse(text, env)
    tables = _extract_tables(tokens, text, env["table_indices"])
    html = md.renderer.render(tokens, md.options, env)
    return html, tables


def serialize_table(aligns: list[str], header: list[str], rows: list[list[str]]) -> str:
    """將表格資料序列化成對齊好讀的 Markdown 表格。"""

    if not header:
        raise ValueError("表格至少需要一個欄位")
    col_count = len(header)
    normalized_aligns = [(aligns[idx] if idx < len(aligns) else "") for idx in range(col_count)]
    normalized_header = [_escape_cell(str(cell)) for cell in header[:col_count]]
    normalized_rows = [
        [_escape_cell(str(row[idx]) if idx < len(row) else "") for idx in range(col_count)]
        for row in rows
    ]
    widths = []
    for col in range(col_count):
        values = [normalized_header[col], *[row[col] for row in normalized_rows]]
        widths.append(max(3, *[_display_width(value) for value in values]))

    lines = [
        _serialize_row(normalized_header, widths),
        _serialize_row([_align_marker(normalized_aligns[idx], widths[idx]) for idx in range(col_count)], widths),
    ]
    lines.extend(_serialize_row(row, widths) for row in normalized_rows)
    return "\n".join(lines)


def replace_lines(text: str, start_line: int, end_line: int, new_block: str) -> str:
    """替換指定行範圍，並沿用原文字的換行符號。"""

    lines = text.splitlines(keepends=True)
    if start_line < 0 or end_line < start_line or end_line > len(lines):
        raise ValueError("行號超出範圍")
    if not lines and (start_line != 0 or end_line != 0):
        raise ValueError("行號超出範圍")

    newline = _detect_newline(text)
    prefix = "".join(lines[:start_line])
    suffix = "".join(lines[end_line:])
    old_range = lines[start_line:end_line]
    old_ended_with_newline = bool(old_range and _line_ending(old_range[-1]))
    should_separate_suffix = bool(suffix) or old_ended_with_newline
    block = _block_with_newline(new_block, newline, should_separate_suffix)
    return prefix + block + suffix


def normalize_html(html: str) -> list[str]:
    """正規化 HTML，供本地渲染與官方預覽逐行比對。"""

    html = ALIGN_STYLE_RE.sub(lambda m: f' align="{m.group(1).lower()}"', html)
    html = re.sub(r"<br\s*/?>\n", "<br>", html, flags=re.IGNORECASE)
    html = BR_RE.sub("<br>", html)
    return [line.strip() for line in html.splitlines() if line.strip()]


def _extract_tables(tokens: list[Token], text: str, table_indices: dict[int, int]) -> list[dict]:
    source_lines = text.splitlines()
    tables = []
    table_index = 0
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token.type != "table_open":
            idx += 1
            continue
        table_indices[idx] = table_index
        start_line, end_line = token.map or [0, 0]
        close_idx = _find_table_close(tokens, idx)
        aligns = _extract_aligns(tokens[idx:close_idx])
        header, rows = _extract_table_cells_from_source(source_lines[start_line:end_line])
        if len(aligns) < len(header):
            aligns.extend([""] * (len(header) - len(aligns)))
        tables.append(
            {
                "index": table_index,
                "start_line": start_line,
                "end_line": end_line,
                "aligns": aligns[: len(header)],
                "header": header,
                "rows": rows,
            }
        )
        table_index += 1
        idx = close_idx + 1
    return tables


def _find_table_close(tokens: list[Token], start_idx: int) -> int:
    for idx in range(start_idx + 1, len(tokens)):
        if tokens[idx].type == "table_close":
            return idx
    return len(tokens)


def _extract_aligns(tokens: list[Token]) -> list[str]:
    aligns = []
    in_header = False
    for token in tokens:
        if token.type == "thead_open":
            in_header = True
        elif token.type == "thead_close":
            break
        elif in_header and token.type == "th_open":
            style = token.attrGet("style") or ""
            match = ALIGN_VALUE_RE.search(style)
            aligns.append(match.group(1).lower() if match else "")
    return aligns


def _extract_table_cells_from_source(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    if not lines:
        return [], []
    header = _split_table_row(lines[0])
    rows = [_split_table_row(line) for line in lines[2:]]
    return header, rows


def _split_table_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not _is_escaped_pipe(line, len(line) - 1):
        line = line[:-1]

    cells = []
    current = []
    for idx, char in enumerate(line):
        if char == "|" and not _is_escaped_pipe(line, idx):
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append("".join(current).strip())
    return cells


def _is_escaped_pipe(text: str, idx: int) -> bool:
    return idx > 0 and text[idx - 1] == "\\"


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def _escape_cell(text: str) -> str:
    chars = []
    for idx, char in enumerate(text):
        if char == "|" and (idx == 0 or text[idx - 1] != "\\"):
            chars.append("\\|")
        else:
            chars.append(char)
    return "".join(chars)


def _pad_cell(text: str, width: int) -> str:
    return text + (" " * max(0, width - _display_width(text)))


def _serialize_row(cells: list[str], widths: list[int]) -> str:
    padded = [_pad_cell(cells[idx], widths[idx]) for idx in range(len(widths))]
    return "| " + " | ".join(padded) + " |"


def _align_marker(align: str, width: int) -> str:
    width = max(3, width)
    if align == "left":
        return ":" + "-" * (width - 1)
    if align == "center":
        return ":" + "-" * (width - 2) + ":"
    if align == "right":
        return "-" * (width - 1) + ":"
    return "-" * width


def _detect_newline(text: str) -> str:
    match = re.search(r"\r\n|\r|\n", text)
    return match.group(0) if match else "\n"


def _line_ending(line: str) -> str:
    match = re.search(r"(\r\n|\r|\n)$", line)
    return match.group(0) if match else ""


def _block_with_newline(new_block: str, newline: str, add_trailing_newline: bool) -> str:
    if not new_block:
        return ""
    block = new_block.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    if add_trailing_newline and not block.endswith(newline):
        block += newline
    return block
