"""LlamaIndex owns indexing, embedding and retrieval; SQLite publishes versions."""
from __future__ import annotations

import asyncio
import sqlite3
from collections import defaultdict
from contextlib import closing

import chromadb
from filelock import FileLock
from llama_index.core import VectorStoreIndex
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from app.config import Settings


class VectorStoreError(RuntimeError):
    pass


class AsyncChromaVectorStore(ChromaVectorStore):
    async def aquery(self, query, **kwargs):
        return await asyncio.to_thread(self.query, query, **kwargs)


class KnowledgeIndex:
    def __init__(self, settings: Settings, embed_model=None):
        self.settings = settings
        if embed_model is None:
            if not settings.openai_api_key:
                raise VectorStoreError('OPENAI_API_KEY is not configured')
            embed_model = OpenAIEmbedding(api_key=settings.openai_api_key, model=settings.openai_embedding_model,
                                          dimensions=settings.embedding_dimensions,
                                          embed_batch_size=settings.embedding_batch_size,
                                          timeout=settings.request_timeout, max_retries=0)
        self.embed_model = embed_model
        settings.vector_store_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(settings.vector_store_dir))
        self.collection = self.client.get_or_create_collection(settings.chroma_collection,
            metadata={'hnsw:space': 'cosine', 'schema': 'llama-v1',
                      'embedding_model': settings.openai_embedding_model, 'dimensions': settings.embedding_dimensions})
        metadata = self.collection.metadata or {}
        self.legacy = metadata.get('schema') != 'llama-v1'
        if not self.legacy and (metadata.get('embedding_model') != settings.openai_embedding_model or
                               metadata.get('dimensions') != settings.embedding_dimensions):
            raise VectorStoreError('The embedding model or dimensions do not match the collection; use a new collection')
        self.vector_store = AsyncChromaVectorStore(chroma_collection=self.collection)
        self.index = VectorStoreIndex.from_vector_store(self.vector_store, embed_model=embed_model)
        self.manifest_path = settings.vector_store_dir / 'versions.sqlite3'
        with closing(sqlite3.connect(self.manifest_path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS versions (collection TEXT, file_id TEXT, version TEXT, PRIMARY KEY(collection,file_id))')
        self.lock = FileLock(str(settings.vector_store_dir / 'ingest.lock'), timeout=settings.request_timeout)

    def ingest(self, nodes) -> int:
        if self.legacy:
            raise VectorStoreError('Legacy collections are read-only; configure a new CHROMA_COLLECTION for ingestion')
        grouped = defaultdict(list)
        for node in nodes:
            grouped[node.metadata['file_id']].append(node)
        added = 0
        # One local writer across processes; old versions remain readable during staging.
        with self.lock:
            for file_id, file_nodes in grouped.items():
                version = file_nodes[0].metadata['version']
                if any(n.metadata['version'] != version for n in file_nodes):
                    raise ValueError('A file must contain one complete version')
                ids = [n.node_id for n in file_nodes]
                existing = set(self.collection.get(where={'file_id': file_id}, include=[])['ids'])
                missing = [n for n in file_nodes if n.node_id not in existing]
                # LlamaIndex index handles embedding once; Chroma stores serialized nodes.
                if missing:
                    self.index.insert_nodes(missing)
                written = set(self.collection.get(where={'file_id': file_id}, include=[])['ids'])
                if not set(ids) <= written:
                    raise VectorStoreError('The new version was not written completely; the current version remains active')
                with closing(sqlite3.connect(self.manifest_path)) as db, db:
                    db.execute('INSERT OR REPLACE INTO versions VALUES (?,?,?)',
                               (self.settings.chroma_collection, file_id, version))
                added += len(missing)
        return added

    def _filters(self):
        if self.legacy:
            if not self.collection.count():
                raise VectorStoreError('The knowledge base is empty; ingest documents first')
            return None
        with closing(sqlite3.connect(self.manifest_path)) as db:
            versions = [row[0] for row in db.execute('SELECT version FROM versions WHERE collection=?',
                                                   (self.settings.chroma_collection,))]
        if not versions:
            raise VectorStoreError('The knowledge base is empty; ingest documents first')
        return MetadataFilters(filters=[MetadataFilter(key='version', value=versions, operator=FilterOperator.IN)])

    async def aretrieve(self, question: str, top_k: int):
        filters = await asyncio.to_thread(self._filters)
        retriever = self.index.as_retriever(similarity_top_k=top_k, filters=filters)
        return await retriever.aretrieve(question)
