from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db.vector_store import KnowledgeIndex
from app.services.chunker import build_nodes
from app.services.drive_auth import get_drive_service
from app.services.drive_loader import GoogleDriveLoader
from app.utils.logger import configure_logging, get_logger

logger = get_logger(__name__)


async def ingest(loader, settings, store):
    # Loader yields every successfully parsed file contiguously. Never publish partial pages.
    pages = []
    added = 0
    async for page in loader.iter_folder_documents(settings.google_drive_folder_ids):
        if pages and pages[-1].file_id != page.file_id:
            nodes = await asyncio.to_thread(build_nodes, pages, settings.chunk_size, settings.chunk_overlap)
            added += await asyncio.to_thread(store.ingest, nodes)
            pages = []
        pages.append(page)
    if pages:
        nodes = await asyncio.to_thread(build_nodes, pages, settings.chunk_size, settings.chunk_overlap)
        added += await asyncio.to_thread(store.ingest, nodes)
    return added


async def main():
    parser = argparse.ArgumentParser(description='Google Drive → LlamaIndex → 新 Chroma 集合（可能产生 API 费用）')
    parser.add_argument('--confirm-cost', action='store_true', help='确认下载、分块和收费向量化')
    args = parser.parse_args()
    if not args.confirm_cost:
        parser.error('请审查集合配置和 API 费用后使用 --confirm-cost；未执行导入')
    configure_logging()
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError('OPENAI_API_KEY 未配置')
    if not settings.google_drive_folder_ids:
        raise ValueError('GOOGLE_DRIVE_FOLDER_ID 未配置')
    store = await asyncio.to_thread(KnowledgeIndex, settings)
    if store.legacy:
        raise ValueError('不允许向旧集合导入；请配置新的 CHROMA_COLLECTION')
    service = await asyncio.to_thread(get_drive_service, settings.google_oauth_credentials_file, settings.google_oauth_token_file)
    count = await ingest(GoogleDriveLoader(service), settings, store)
    logger.info('ingestion_complete added_chunks=%s', count)


if __name__ == '__main__':
    asyncio.run(main())
