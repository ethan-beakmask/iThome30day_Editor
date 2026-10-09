"""讀取 iThome 編輯器設定檔。"""

from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class IthomeConfig:
    """iT邦幫忙網站與瀏覽器連線設定。"""

    cdp_url: str
    site: str


@dataclass(frozen=True)
class ServerConfig:
    """本機 Web 服務設定。"""

    host: str
    port: int
    prefix: str
    articles_dir: Path
    log_file: Path


@dataclass(frozen=True)
class AppConfig:
    """應用程式完整設定。"""

    ithome: IthomeConfig
    server: ServerConfig
    project_root: Path = PROJECT_ROOT


def _get_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """讀取 config.ini；不存在時改讀範例檔並印出警告。"""

    path = Path(config_path) if config_path else PROJECT_ROOT / "config.ini"
    if not path.exists():
        path = PROJECT_ROOT / "config.ini.example"
        print("警告：找不到 config.ini，改讀 config.ini.example。", file=sys.stderr)

    parser = ConfigParser(inline_comment_prefixes=(";", "#"))
    parser.read(path, encoding="utf-8")

    prefix = parser.get("server", "prefix", fallback="/ithome").strip() or "/ithome"
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    prefix = prefix.rstrip("/") or "/"

    return AppConfig(
        ithome=IthomeConfig(
            cdp_url=parser.get("ithome", "cdp_url", fallback="http://127.0.0.1:9222"),
            site=parser.get("ithome", "site", fallback="https://ithelp.ithome.com.tw").rstrip("/"),
        ),
        server=ServerConfig(
            host=parser.get("server", "host", fallback="127.0.0.1"),
            port=parser.getint("server", "port", fallback=5451),
            prefix=prefix,
            articles_dir=_get_path(parser.get("server", "articles_dir", fallback="articles")),
            log_file=_get_path(parser.get("server", "log_file", fallback="logs/ithome_editor.log")),
        ),
    )
