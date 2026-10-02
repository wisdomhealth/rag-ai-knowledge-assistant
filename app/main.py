from contextlib import asynccontextmanager
import asyncio
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse

from app.api.auth import owner
from app.api.chat import router
from app.config import get_settings
from app.db.sessions import SessionStore
from app.db.vector_store import KnowledgeIndex
from app.services.rag import RagPipeline
from app.utils.logger import configure_logging

STATIC_DIR = Path(__file__).resolve().parent / 'static'


def create_app(settings=None, rag=None):
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        app.state.sessions = await asyncio.to_thread(SessionStore, settings.session_db)
        app.state.rag = rag
        if rag is None and settings.openai_api_key:
            store = await asyncio.to_thread(KnowledgeIndex, settings)
            app.state.rag = RagPipeline(store, settings)
        yield

    app = FastAPI(title='AI Knowledge Assistant', version='2.0.0', lifespan=lifespan)
    app.state.settings = settings
    app.include_router(router)

    @app.middleware('http')
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['Cache-Control'] = 'no-store'
        token = getattr(request.state, 'session_token', None)
        if token:
            response.set_cookie('rag_session', token, httponly=True, secure=settings.cookie_secure,
                                samesite='strict', max_age=settings.session_ttl_seconds)
        return response

    @app.get('/', include_in_schema=False, dependencies=[Depends(owner)])
    async def page():
        return FileResponse(STATIC_DIR / 'index.html')

    @app.get('/style.css', include_in_schema=False)
    async def style():
        return FileResponse(STATIC_DIR / 'style.css', media_type='text/css')

    @app.get('/app.js', include_in_schema=False)
    async def script():
        return FileResponse(STATIC_DIR / 'app.js', media_type='text/javascript')

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'configured': bool(settings.openai_api_key or rag)}

    return app


app = create_app()
