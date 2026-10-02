import asyncio
from dataclasses import replace

import pytest

from app.config import Settings
from app.services.models import DocumentPage


def test_page_nodes_keep_metadata_and_stable_ids():
    from app.services.chunker import build_nodes
    pages = [DocumentPage('a.pdf', 'file-a', 'https://example.com/a', p, '材料是身份证。' * 80) for p in (1, 2)]
    nodes = build_nodes(pages, 64, 8)
    assert len(nodes) > 2
    assert {n.metadata['page_number'] for n in nodes} == {1, 2}
    assert all(n.metadata['file_id'] == 'file-a' and n.metadata['chunk_id'] == n.node_id for n in nodes)
    assert [n.node_id for n in nodes] == [n.node_id for n in build_nodes(pages, 64, 8)]
    assert all('content_hash' in n.metadata and 'chunk_version' in n.metadata for n in nodes)


def test_versions_deduplicate_and_isolate(tmp_path):
    from llama_index.core.embeddings import MockEmbedding
    from app.db.vector_store import KnowledgeIndex
    from app.services.chunker import build_nodes
    settings = Settings(openai_api_key='', google_drive_folder_ids=(), vector_store_dir=tmp_path, embedding_dimensions=8)
    store = KnowledgeIndex(settings, MockEmbedding(embed_dim=8))
    a = DocumentPage('a.pdf', 'a', 'https://example.com', 2, 'old policy')
    b = replace(a, file_id='b', text='other policy')
    assert store.ingest(build_nodes([a], 64, 8)) > 0
    assert store.ingest(build_nodes([a], 64, 8)) == 0
    store.ingest(build_nodes([b], 64, 8))
    store.ingest(build_nodes([replace(a, text='new policy')], 64, 8))
    found = asyncio.run(store.aretrieve('policy', 10))
    assert {n.node.text for n in found} == {'new policy', 'other policy'}


def test_failed_update_keeps_previous_file_and_other_files(tmp_path, monkeypatch):
    from llama_index.core.embeddings import MockEmbedding
    from app.db.vector_store import KnowledgeIndex
    from app.services.chunker import build_nodes
    settings = Settings(vector_store_dir=tmp_path, embedding_dimensions=8)
    store = KnowledgeIndex(settings, MockEmbedding(embed_dim=8))
    page = DocumentPage('a.pdf', 'a', 'https://example.com', 1, 'old evidence')
    other = replace(page, file_id='b', text='other evidence')
    store.ingest(build_nodes([page, other], 64, 8))
    insert = store.index.insert_nodes
    def partial(nodes):
        insert(nodes[:1])
        raise RuntimeError('failed second batch')
    monkeypatch.setattr(store.index, 'insert_nodes', partial)
    with pytest.raises(RuntimeError):
        store.ingest(build_nodes([replace(page, text='updated evidence. ' * 100)], 64, 8))
    found = asyncio.run(store.aretrieve('evidence', 10))
    assert {item.node.text for item in found} == {'old evidence', 'other evidence'}
    monkeypatch.setattr(store.index, 'insert_nodes', insert)
    store.ingest(build_nodes([replace(page, text='updated evidence. ' * 100)], 64, 8))
    found = asyncio.run(store.aretrieve('evidence', 50))
    assert all(item.node.text != 'old evidence' for item in found)
    assert any(item.node.text == 'other evidence' for item in found)


def test_legacy_collection_readonly_and_dimension_guard(tmp_path):
    import chromadb
    from llama_index.core.embeddings import MockEmbedding
    from app.db.vector_store import KnowledgeIndex, VectorStoreError
    collection = chromadb.PersistentClient(path=str(tmp_path)).create_collection('legacy_docs')
    collection.add(ids=['old-id'], documents=['legacy evidence'], embeddings=[[1.0]*8],
                   metadatas=[{'file_id': 'a', 'file_name': 'a.pdf', 'page_number': 0, 'chunk_id': 'old-id'}])
    settings = Settings(vector_store_dir=tmp_path, chroma_collection='legacy_docs', embedding_dimensions=8)
    legacy = KnowledgeIndex(settings, MockEmbedding(embed_dim=8))
    assert asyncio.run(legacy.aretrieve('evidence', 1))[0].node.text == 'legacy evidence'
    with pytest.raises(VectorStoreError):
        legacy.ingest([])
    fresh = replace(settings, chroma_collection='new_docs')
    KnowledgeIndex(fresh, MockEmbedding(embed_dim=8))
    with pytest.raises(VectorStoreError, match='维度'):
        KnowledgeIndex(replace(fresh, embedding_dimensions=16), MockEmbedding(embed_dim=16))
    assert collection.count() == 1


def test_empty_knowledge_no_embedding_call(tmp_path):
    from llama_index.core.embeddings import MockEmbedding
    from app.db.vector_store import KnowledgeIndex, VectorStoreError
    store = KnowledgeIndex(Settings(vector_store_dir=tmp_path, embedding_dimensions=8), MockEmbedding(embed_dim=8))
    with pytest.raises(VectorStoreError, match='为空'):
        asyncio.run(store.aretrieve('hello', 1))


def test_embedding_once_and_duplicate_skips_api(tmp_path):
    from pydantic import PrivateAttr
    from llama_index.core.embeddings import MockEmbedding
    from app.db.vector_store import KnowledgeIndex
    from app.services.chunker import build_nodes
    class CountingEmbedding(MockEmbedding):
        _texts: list = PrivateAttr(default_factory=list)
        _queries: list = PrivateAttr(default_factory=list)
        def _get_text_embedding(self, text):
            self._texts.append(text)
            return super()._get_text_embedding(text)
        async def _aget_query_embedding(self, query):
            self._queries.append(query)
            return await super()._aget_query_embedding(query)
    embed = CountingEmbedding(embed_dim=8)
    store = KnowledgeIndex(Settings(vector_store_dir=tmp_path, embedding_dimensions=8), embed)
    nodes = build_nodes([DocumentPage('a.txt', 'a', '', None, 'Evidence here.')], 64, 8)
    store.ingest(nodes)
    store.ingest(build_nodes([DocumentPage('a.txt', 'a', '', None, 'Evidence here.')], 64, 8))
    asyncio.run(store.aretrieve('Question?', 2))
    assert len(embed._texts) == 1
    assert embed._queries == ['Question?']
