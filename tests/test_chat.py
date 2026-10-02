import asyncio
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk
from llama_index.core.schema import NodeWithScore, TextNode

from app.config import Settings
from app.main import create_app
from app.services.rag import RagPipeline, to_documents, validate_citations, CitationError
from app.db.vector_store import VectorStoreError


class Retriever:
    def __init__(self):
        self.queries = []
        self.error = None

    async def aretrieve(self, question, top_k):
        self.queries.append(question)
        if self.error:
            raise self.error
        return [NodeWithScore(node=TextNode(id_='chunk-1', text='An identity document is required; processing is available on business days.', metadata={
            'file_name': 'Application Guide.pdf', 'file_id': 'file-1', 'source_link': 'https://example.com/doc', 'page_number': 2}), score=.9)]


class Model:
    def __init__(self, answer='An identity document is required. [1]'):
        self.answer = answer
        self.prompts = []
        self.closed = False
        self.error = None

    async def ainvoke(self, messages):
        self.prompts.append(messages)
        if self.error:
            raise self.error
        if 'Rewrite' in messages[0].content:
            return AIMessage(content='What documents are required for this application?')
        return AIMessage(content=self.answer, usage_metadata={'input_tokens': 30, 'output_tokens': 5, 'total_tokens': 35})

    async def astream(self, messages):
        self.prompts.append(messages)
        try:
            yield AIMessageChunk(content=self.answer[:3])
            if self.error:
                raise self.error
            yield AIMessageChunk(content=self.answer[3:])
        finally:
            self.closed = True


@pytest.fixture
def bundle(tmp_path):
    settings = Settings(session_db=tmp_path/'sessions.db', vector_store_dir=tmp_path/'chroma')
    retriever, model = Retriever(), Model()
    rag = RagPipeline(retriever, settings, model)
    app = create_app(settings, rag)
    with TestClient(app) as client:
        yield app, client, model, retriever


def test_old_request_and_conversation_followup(bundle):
    app, client, model, retriever = bundle
    result = client.post('/chat', json={'question': 'How do I apply?'})
    assert result.status_code == 200
    data = result.json()
    assert data['sources'][0] == dict(citation_id=1, chunk_id='chunk-1', file_name='Application Guide.pdf', file_id='file-1',
        source_link='https://example.com/doc', page_number=2, snippet='An identity document is required; processing is available on business days.')
    assert data['request_id'] == result.headers['X-Request-ID']
    assert data['latency_ms'] >= 0 and data['usage']['total_tokens'] == 35
    cid = data['conversation_id']
    assert client.post('/chat', json={'question': 'What documents does it require?', 'conversation_id': cid}).status_code == 200
    assert retriever.queries == ['How do I apply?', 'What documents are required for this application?']
    assert len(model.prompts) == 3  # one rewrite + two answers, two retrievals
    assert len(client.get(f'/conversations/{cid}').json()['turns']) == 2


def test_browser_isolation_and_forged_cookie(bundle):
    app, client, _, _ = bundle
    cid = client.post('/conversations').json()['conversation_id']
    token = client.cookies.get('rag_session')
    assert token
    with TestClient(app) as attacker:
        attacker.cookies.set('rag_session', 'forged')
        assert attacker.get(f'/conversations/{cid}').status_code == 404
        assert attacker.post('/chat', json={'question': 'hello', 'conversation_id': cid}).status_code == 404
    assert client.post('/chat', json={'question': 'hello', 'conversation_id': cid}).status_code == 200


def test_stream_legacy_protocol_and_sources(bundle):
    _, client, model, _ = bundle
    response = client.post('/chat/stream', json={'question': 'Documents?'})
    assert response.status_code == 200
    assert '"token":' in response.text and 'data: [DONE]' in response.text
    assert '"type": "sources"' in response.text and '"validated": true' in response.text
    assert '"latency_ms":' in response.text
    assert model.closed


@pytest.mark.parametrize('stream', [False, True])
def test_invalid_citation_not_saved(bundle, stream):
    _, client, model, _ = bundle
    model.answer = 'Fabricated claim. [99]'
    cid = client.post('/conversations').json()['conversation_id']
    response = client.post('/chat/stream' if stream else '/chat', json={'question': 'hi', 'conversation_id': cid})
    if stream:
        assert 'event: error' in response.text
        assert 'invalid_citation' in response.text and '[DONE]' not in response.text
        assert '"type": "complete"' not in response.text
    else:
        assert response.status_code == 502
    assert client.get(f'/conversations/{cid}').json()['turns'] == []


@pytest.mark.parametrize('error,status', [(VectorStoreError('The knowledge base is empty'), 503), (TimeoutError(), 504), (RuntimeError('SECRET'), 502)])
def test_explicit_errors_and_no_sensitive_leak(bundle, error, status):
    _, client, model, retriever = bundle
    retriever.error = error
    response = client.post('/chat', json={'question': 'hi'})
    assert response.status_code == status
    assert 'SECRET' not in response.text
    assert response.json()['detail']['request_id']


def test_partial_model_failure_not_saved(bundle):
    _, client, model, _ = bundle
    model.error = RuntimeError('private')
    cid = client.post('/conversations').json()['conversation_id']
    response = client.post('/chat/stream', json={'question': 'hi', 'conversation_id': cid})
    assert '"token":' in response.text and 'event: error' in response.text
    assert 'private' not in response.text and '[DONE]' not in response.text
    assert client.get(f'/conversations/{cid}').json()['turns'] == []


def test_adapter_null_page_and_bad_link(bundle):
    docs = to_documents([NodeWithScore(node=TextNode(text='hello', id_='abc', metadata={'page_number': 0, 'file_id': 'x'}))])
    assert docs[0].metadata['chunk_id'] == 'abc' and docs[0].metadata['page_number'] is None
    for answer in ('uncited', 'bad [0]', 'bad [2]'):
        with pytest.raises(CitationError):
            validate_citations(answer, 1)


def test_basic_auth_and_csrf(tmp_path):
    settings = Settings(session_db=tmp_path/'s.db', api_basic_auth_username='reader', api_basic_auth_password='local-test-password')
    app = create_app(settings, RagPipeline(Retriever(), settings, Model()))
    with TestClient(app) as client:
        assert client.get('/').status_code == 401
        assert 'Basic' in client.get('/').headers['www-authenticate']
        assert client.post('/chat', json={'question': 'hi'}, auth=('reader', 'wrong')).status_code == 401
        assert client.get('/', auth=('reader', 'local-test-password')).status_code == 200
        assert client.post('/conversations', auth=('reader', 'local-test-password'), headers={'Origin': 'https://evil.example'}).status_code == 403


def test_missing_key_and_blank_question(tmp_path):
    with TestClient(create_app(Settings(session_db=tmp_path/'s.db'))) as client:
        assert client.get('/').status_code == 200
        response = client.post('/chat', json={'question': 'hi'})
        assert response.status_code == 503 and 'OPENAI_API_KEY' in response.text
        assert client.post('/chat', json={'question': '  '}).status_code == 422


def test_cancel_closes_upstream_without_success():
    model, retriever = Model(), Retriever()
    rag = RagPipeline(retriever, Settings(), model)
    async def run():
        stream = rag.stream_answer('hi')
        assert (await anext(stream))['type'] == 'sources'
        assert 'token' in await anext(stream)
        await stream.aclose()
    asyncio.run(run())
    assert model.closed


@pytest.mark.parametrize('stream', [False, True])
def test_save_timeout_does_not_record_success(tmp_path, monkeypatch, stream):
    import time
    settings = Settings(session_db=tmp_path/'s.db', request_timeout=.05)
    app = create_app(settings, RagPipeline(Retriever(), settings, Model()))
    with TestClient(app) as client:
        store = app.state.sessions
        import threading
        marker = threading.local()
        original_save, original_check = store.save, store.check
        def slow_check(*args):
            original_check(*args)
            if getattr(marker, 'saving', False):
                time.sleep(.15)
        def slow_save(*args, **kwargs):
            marker.saving = True
            try:
                return original_save(*args, **kwargs)
            finally:
                marker.saving = False
        monkeypatch.setattr(store, 'save', slow_save)
        monkeypatch.setattr(store, 'check', slow_check)
        cid = client.post('/conversations').json()['conversation_id']
        response = client.post('/chat/stream' if stream else '/chat', json={'question': 'hi', 'conversation_id': cid})
        assert 'timeout' in response.text
        time.sleep(.2)
        assert client.get(f'/conversations/{cid}').json()['turns'] == []


def test_failed_citation_logs_completed_stage_timings(bundle, caplog):
    import json
    import logging
    _, client, model, _ = bundle
    model.answer = 'bad [99]'
    with caplog.at_level(logging.INFO, logger='app.api.chat'):
        assert client.post('/chat', json={'question': 'hi'}).status_code == 502
    events = [json.loads(r.message) for r in caplog.records if r.name == 'app.api.chat']
    assert events[-1]['retrieval_ms'] is not None
    assert events[-1]['generation_ms'] is not None
    assert events[-1]['error_type'] == 'invalid_citation'


@pytest.mark.parametrize('stream', [False, True])
def test_acquire_timeout_does_not_leave_conversation_busy(tmp_path, monkeypatch, stream):
    import time
    settings = Settings(session_db=tmp_path/'s.db', request_timeout=.05)
    app = create_app(settings, RagPipeline(Retriever(), settings, Model()))
    with TestClient(app) as client:
        store = app.state.sessions
        original = store.acquire
        def slow_acquire(*args, **kwargs):
            time.sleep(.15)
            return original(*args, **kwargs)
        monkeypatch.setattr(store, 'acquire', slow_acquire)
        cid = client.post('/conversations').json()['conversation_id']
        response = client.post('/chat/stream' if stream else '/chat', json={'question': 'hi', 'conversation_id': cid})
        assert response.status_code == 504
        time.sleep(.2)
        monkeypatch.setattr(store, 'acquire', original)
        assert client.post('/chat', json={'question': 'retry', 'conversation_id': cid}).status_code == 200


def test_chat_under_uvloop(tmp_path):
    pytest.importorskip('uvloop')
    settings = Settings(session_db=tmp_path/'s.db', request_timeout=5)
    app = create_app(settings, RagPipeline(Retriever(), settings, Model()))
    with TestClient(app, backend_options={'use_uvloop': True}) as client:
        assert client.post('/chat', json={'question': 'hi'}).status_code == 200
        assert '[DONE]' in client.post('/chat/stream', json={'question': 'hi'}).text
