"""管理本機預覽所需的 iT邦幫忙樣式快取。"""

from __future__ import annotations

from datetime import timedelta
import logging
from pathlib import Path
import time
import urllib.request

from .config import AppConfig


CSS_FILES = {
    "style.css": "/css/style.css?202008271142",
    "railscasts.css": "/css/railscasts.css",
}
CACHE_MAX_AGE = timedelta(days=7).total_seconds()


def ensure_ithelp_css(config: AppConfig, force: bool = False) -> Path:
    """確保官方樣式檔已下載到本機快取目錄。"""

    cache_dir = config.project_root / "static" / "ithelp_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    site = config.ithome.site.rstrip("/")

    for filename, source_path in CSS_FILES.items():
        target = cache_dir / filename
        url = f"{site}{source_path}"
        if not force and target.exists() and not _is_stale(target):
            continue
        try:
            _download(url, target)
        except Exception as exc:
            if target.exists():
                logging.warning("下載 iT邦幫忙樣式檔失敗，沿用既有快取 %s：%s", target, exc)
                continue
            raise RuntimeError(f"需要網路連線以取得 iT邦幫忙的樣式檔：{url}；原始錯誤：{exc}") from exc
    return cache_dir


def _is_stale(path: Path) -> bool:
    return time.time() - path.stat().st_mtime > CACHE_MAX_AGE


def _download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        status = getattr(response, "status", None)
        if status is None and hasattr(response, "getcode"):
            status = response.getcode()
        if status and status >= 400:
            raise RuntimeError(f"HTTP {status}")
        data = response.read()
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)
