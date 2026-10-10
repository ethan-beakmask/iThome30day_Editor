"""頁尾身分列：確認頁面顯示執行目錄與 git 短碼。"""

from dataclasses import fields

from ithome_editor.config import AppConfig, IthomeConfig, ServerConfig
from ithome_editor.webapp import PROJECT_ROOT, build_info, create_app


def _make_app(tmp_path):
    ithome_kwargs = {"cdp_url": "http://127.0.0.1:9222", "site": "https://ithelp.ithome.com.tw"}
    if any(f.name == "account" for f in fields(IthomeConfig)):
        ithome_kwargs["account"] = "tester"
    config = AppConfig(
        ithome=IthomeConfig(**ithome_kwargs),
        server=ServerConfig(
            host="127.0.0.1",
            port=5451,
            prefix="/ithome",
            articles_dir=tmp_path / "articles",
            log_file=tmp_path / "app.log",
        ),
        project_root=tmp_path,
    )
    return create_app(config)


def test_build_info_reports_project_root():
    info = build_info()
    assert info["root"] == str(PROJECT_ROOT)
    assert info["rev"]


def test_footer_shows_build_info(tmp_path):
    client = _make_app(tmp_path).test_client()
    html = client.get("/ithome/").get_data(as_text=True)
    assert str(PROJECT_ROOT) in html
    assert build_info()["rev"] in html
