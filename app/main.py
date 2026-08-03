from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.chat import router as chat_router
from app.config import get_settings
from app.db.vector_store import ChromaVectorStore
from app.services.embedding import OpenAIEmbeddingService
from app.services.llm import OpenAIChatService
from app.services.rag import RagPipeline
from app.utils.logger import configure_logging, get_logger


logger = get_logger(__name__)
ROOT_DIR = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared RAG dependencies once for the FastAPI process."""
    configure_logging()
    settings = get_settings()

    # Keep vector store, embedding client, and LLM client on app.state so route
    # handlers can reuse long-lived objects instead of rebuilding them per request.
    vector_store = ChromaVectorStore(settings.vector_store_dir)
    vector_store.load()
    embeddings = OpenAIEmbeddingService(
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
        batch_size=settings.embedding_batch_size,
    )
    llm = OpenAIChatService(api_key=settings.openai_api_key, model=settings.openai_chat_model)
    app.state.rag = RagPipeline(
        embeddings=embeddings,
        llm=llm,
        vector_store=vector_store,
        top_k=settings.retrieval_top_k,
    )
    logger.info("Application startup complete")
    yield


app = FastAPI(
    title="Google Drive RAG API",
    version="1.0.0",
    description="Ask questions over Google Drive documents with OpenAI and Chroma.",
    lifespan=lifespan,
)
app.include_router(chat_router)


@app.get("/", include_in_schema=False)
async def chat_page() -> FileResponse:
    """Serve the browser chat interface."""
    return FileResponse(ROOT_DIR / "index.html")


@app.get("/style.css", include_in_schema=False)
async def stylesheet() -> FileResponse:
    """Serve the chat interface stylesheet without exposing the project folder."""
    return FileResponse(ROOT_DIR / "style.css", media_type="text/css")


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a minimal liveness response for health checks."""
    return {"status": "ok"}
