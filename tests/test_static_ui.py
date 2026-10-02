from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


def test_static_ui_and_security_headers(tmp_path):
    with TestClient(create_app(Settings(session_db=tmp_path/'s.db'))) as client:
        page = client.get('/')
        assert page.status_code == 200
        assert 'id="chat-form"' in page.text and 'data-endpoint="/chat/stream"' in page.text
        assert 'lang="zh-CN"' in page.text
        assert 'HttpOnly' in page.headers['set-cookie']
        assert "script-src 'self'" in page.headers['content-security-policy']
        assert client.get('/style.css').status_code == 200
        js = client.get('/app.js').text
        assert '.innerHTML' not in js
        assert 'textContent' in js and "['https:', 'http:']" in js
