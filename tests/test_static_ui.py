from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_root_serves_chat_page() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'id="chat-form"' in response.text
    assert 'data-endpoint="/chat"' in response.text
