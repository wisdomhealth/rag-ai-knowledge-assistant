from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_root_serves_chat_page() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="chat-form"' in response.text
    assert 'data-endpoint="/chat"' in response.text


def test_static_assets_live_under_app_static() -> None:
    assert (ROOT_DIR / "app/static/index.html").is_file()
    assert (ROOT_DIR / "app/static/style.css").is_file()
    assert not (ROOT_DIR / "index.html").exists()
    assert not (ROOT_DIR / "style.css").exists()
