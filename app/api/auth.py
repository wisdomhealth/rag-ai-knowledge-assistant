import asyncio
import secrets
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic(auto_error=False)


async def require_basic_auth(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)):
    settings = request.app.state.settings
    if not settings.auth_enabled:
        return None
    if credentials is None or not (
        secrets.compare_digest(credentials.username.encode(), settings.api_basic_auth_username.encode()) and
        secrets.compare_digest(credentials.password.encode(), settings.api_basic_auth_password.encode())
    ):
        raise HTTPException(401, '需要有效的登录凭证', headers={'WWW-Authenticate': 'Basic realm="Knowledge Assistant"'})
    return 'user:' + credentials.username


async def owner(request: Request, user=Depends(require_basic_auth)):
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD') and (
        request.headers.get('sec-fetch-site') == 'cross-site' or
        (origin and (urlsplit(origin).scheme, urlsplit(origin).netloc) != (request.url.scheme, request.url.netloc))
    ):
        raise HTTPException(403, '仅允许同源请求')
    if user:
        return user
    identity, token = await asyncio.to_thread(request.app.state.sessions.browser,
        request.cookies.get('rag_session'), request.app.state.settings.session_ttl_seconds)
    if token:
        request.state.session_token = token
    return identity
