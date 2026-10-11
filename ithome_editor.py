#!/usr/bin/env python3
"""iThome 鐵人賽本地 Markdown 編輯器 CLI。"""

from __future__ import annotations

import argparse
import logging
import sys

from ithome_editor.assets import ensure_ithelp_css
from ithome_editor.config import load_config
from ithome_editor.publisher import Publisher
from ithome_editor.renderer import render_markdown
from ithome_editor.storage import Storage
from ithome_editor.webapp import create_app


class HelpParser(argparse.ArgumentParser):
    """在 help 輸出最後補一列空白列。"""

    def format_help(self) -> str:
        text = super().format_help()
        text = text.replace("usage:", "用法:")
        text = text.replace("positional arguments:", "位置參數:")
        text = text.replace("options:", "選項:")
        text = text.replace("show this help message and exit", "顯示說明後離開")
        return text + "\n"


def build_parser() -> argparse.ArgumentParser:
    """建立中文命令列解析器。"""

    parser = HelpParser(description="iThome 鐵人賽本地 Markdown 編輯器")
    parser._positionals.title = "位置參數"
    parser._optionals.title = "選項"
    sub = parser.add_subparsers(dest="command", title="子命令")

    serve = sub.add_parser("serve", help="啟動 Web 編輯器")
    serve.add_argument("--host", help="綁定位址，只允許 127.0.0.1")
    serve.add_argument("--port", type=int, help="服務連接埠")
    serve.add_argument("--debug", action="store_true", help="啟用 Flask 除錯模式")
    serve.add_argument("--refresh-css", action="store_true", help="強制重新下載 iT邦幫忙樣式檔")

    sub.add_parser("list", help="列出文章")

    new = sub.add_parser("new", help="新增文章")
    new.add_argument("slug", help="文章 slug，只能含英數、底線與連字號")
    new.add_argument("--title", required=True, help="文章標題")

    imp = sub.add_parser("import", help="匯入 Markdown 或文字檔")
    imp.add_argument("path", help="檔案路徑")
    imp.add_argument("--slug", required=True, help="文章 slug")
    imp.add_argument("--title", required=True, help="文章標題")

    render = sub.add_parser("render", help="輸出本地渲染 HTML")
    render.add_argument("slug", help="文章 slug")
    render.add_argument("-o", "--output", help="輸出 HTML 檔案")

    check = sub.add_parser("check", help="與官方預覽比對")
    check.add_argument("slug", help="文章 slug")
    check.add_argument("--draft-url", help="草稿頁 URL")

    publish = sub.add_parser("publish", help="準備上稿並寫入草稿頁")
    publish.add_argument("slug", help="文章 slug")
    publish.add_argument("--draft-url", help="草稿頁 URL")
    publish.add_argument("--no-fill", action="store_true", help="只產生 article.published.md，不寫入草稿頁")
    return parser


def setup_logging(config) -> None:
    """設定 stderr 與檔案 logging。"""

    config.server.log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(), logging.FileHandler(config.server.log_file, encoding="utf-8")],
    )


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    config = load_config()
    setup_logging(config)
    storage = Storage(config.server.articles_dir)

    try:
        if args.command == "serve":
            host = args.host or config.server.host
            if host != "127.0.0.1":
                raise ValueError("基於安全限制，服務只能綁定 127.0.0.1")
            port = args.port or config.server.port
            try:
                ensure_ithelp_css(config, force=args.refresh_css)
            except RuntimeError as exc:
                print(f"錯誤：{exc}", file=sys.stderr)
                return 1
            app = create_app(config)
            app.run(host=host, port=port, debug=args.debug)
            return 0
        if args.command == "list":
            for item in storage.list_articles():
                print(f"{item['slug']}\t{item['title']}\t{item['updated_at']}\t未上傳圖片 {item['unuploaded_count']}")
            return 0
        if args.command == "new":
            article = storage.create_article(args.slug, args.title)
            print(f"已新增：{article.slug}")
            return 0
        if args.command == "import":
            article = storage.import_file(args.path, args.slug, args.title)
            print(f"已匯入：{article.slug}")
            return 0
        if args.command == "render":
            article = storage.load(args.slug)
            html = render_markdown(article.body)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as handle:
                    handle.write(html)
            else:
                print(html, end="")
            return 0
        if args.command == "check":
            with Publisher(config, storage) as publisher:
                identical, diff = publisher.check(args.slug, args.draft_url)
            print(f"一致（{diff}）" if identical else diff)
            return 0 if identical else 1
        if args.command == "publish":
            with Publisher(config, storage) as publisher:
                published, log = publisher.publish(args.slug, args.draft_url, fill=not args.no_fill)
            for line in log:
                print(line)
            print(published)
            return 0
    except Exception as exc:
        logging.error("執行失敗：%s", exc)
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
