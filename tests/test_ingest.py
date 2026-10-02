import asyncio
from dataclasses import replace
from app.services.drive_loader import DriveFile, GoogleDriveLoader
from app.services.models import DocumentPage
from app.config import Settings
from scripts.ingest_drive import ingest
from app.services.drive_auth import get_drive_service


def test_ingest_entrypoint_groups_complete_files(tmp_path):
    from llama_index.core.embeddings import MockEmbedding
    from app.db.vector_store import KnowledgeIndex
    page = DocumentPage('a.pdf', 'a', 'https://example.com', 1, 'required identity document')
    class Loader:
        async def iter_folder_documents(self, folders):
            for p in [page, replace(page, page_number=2), replace(page, file_id='b', page_number=None)]:
                yield p
    settings = Settings(vector_store_dir=tmp_path, embedding_dimensions=8, chunk_size=64, chunk_overlap=8)
    store = KnowledgeIndex(settings, MockEmbedding(embed_dim=8))
    assert asyncio.run(ingest(Loader(), settings, store)) == 3
    assert asyncio.run(ingest(Loader(), settings, store)) == 0
    assert callable(get_drive_service)


def test_pdf_parser_page_numbers(monkeypatch):
    class PDFPage:
        def __init__(self, text): self.text = text
        def extract_text(self): return self.text
    class Reader:
        def __init__(self, data): self.pages = [PDFPage('first'), PDFPage(''), PDFPage('third')]
    monkeypatch.setattr('app.services.drive_loader.PdfReader', Reader)
    file = DriveFile('file', 'a.pdf', 'application/pdf', 'https://example.com')
    pages = GoogleDriveLoader(None)._extract_pages(file, b'fake')
    assert [p.page_number for p in pages] == [1, 3]
