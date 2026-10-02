"""Offline browser fixture. Run only as: python tests/ui_server.py."""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from langchain_core.messages import AIMessageChunk
from app.config import Settings
from app.main import create_app
from app.services.rag import RagPipeline
from test_chat import Model, Retriever


class BrowserModel(Model):
    async def astream(self, messages):
        question = messages[-1].content.rsplit('User question: ', 1)[-1]
        text = '无效引用 [99]' if question == '测试错误' else '需要身份证。[1] <img src=x onerror=alert(1)>'
        try:
            for token in text:
                await asyncio.sleep(.04)
                yield AIMessageChunk(content=token)
        finally:
            self.closed = True


if __name__ == '__main__':
    import uvicorn
    with tempfile.TemporaryDirectory(prefix='rag-ui-') as path:
        settings = Settings(session_db=Path(path)/'sessions.db', vector_store_dir=Path(path)/'chroma')
        uvicorn.run(create_app(settings, RagPipeline(Retriever(), settings, BrowserModel())), host='127.0.0.1', port=8765)
