from __future__ import annotations

import asyncio
import json
from contextlib import aclosing
from dataclasses import asdict
from time import perf_counter, monotonic
from threading import Event

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from openai import APITimeoutError, RateLimitError

from app.api.auth import owner
from app.db.sessions import SessionError
from app.db.vector_store import VectorStoreError
from app.services.rag import CitationError
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=['chat'])


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=64)

    @field_validator('question')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('问题不能为空')
        return value.strip()


def error_info(exc):
    if isinstance(exc, SessionError):
        return 409 if '正在回答' in str(exc) else 404, 'invalid_session', str(exc)
    if isinstance(exc, (TimeoutError, APITimeoutError)):
        return 504, 'timeout', '请求超时，请稍后重试'
    if isinstance(exc, RateLimitError):
        return 429, 'rate_limit', '模型服务限流，请稍后重试'
    if isinstance(exc, CitationError):
        return 502, 'invalid_citation', str(exc)
    if isinstance(exc, VectorStoreError):
        return 503, 'knowledge_unavailable', str(exc)
    return 502, 'upstream_error', '检索或模型服务暂不可用，请使用 request_id 联系管理员'


def log_result(request_id, started, result=None, error=None):
    result = result or {}
    logger.info(json.dumps(dict(request_id=request_id, retrieval_ms=result.get('retrieval_ms'),
        generation_ms=result.get('generation_ms'), rewrite_ms=result.get('rewrite_ms'),
        total_ms=round((perf_counter()-started)*1000, 2), usage=result.get('usage'),
        rewrite_usage=result.get('rewrite_usage'), error_type=error), ensure_ascii=False))


async def prepare(request, payload, identity, deadline, cancelled):
    sessions = request.app.state.sessions
    cid = payload.conversation_id or await asyncio.to_thread(sessions.create, identity)
    try:
        await asyncio.to_thread(sessions.acquire, cid, identity, request.state.request_id,
                                request.app.state.settings.request_timeout, deadline, cancelled)
        history = await asyncio.to_thread(sessions.history, cid, identity, request.app.state.settings.history_max_turns)
        return cid, history
    except BaseException:
        cancelled.set()
        await asyncio.shield(asyncio.to_thread(sessions.release, cid, request.state.request_id))
        raise


@router.post('/conversations')
async def new_conversation(request: Request, identity=Depends(owner)):
    return {'conversation_id': await asyncio.to_thread(request.app.state.sessions.create, identity),
            'request_id': request.state.request_id}


@router.get('/conversations/{cid}')
async def history(cid: str, request: Request, identity=Depends(owner)):
    try:
        turns = await asyncio.to_thread(request.app.state.sessions.history, cid, identity, request.app.state.settings.history_max_turns)
        return {'conversation_id': cid, 'turns': turns}
    except SessionError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post('/chat')
async def chat(payload: ChatRequest, request: Request, identity=Depends(owner)):
    started, cid = perf_counter(), None
    rid = request.state.request_id
    cancelled = Event()
    metrics = {}
    deadline = monotonic() + request.app.state.settings.request_timeout
    try:
        async with asyncio.timeout(max(0, deadline - monotonic())):
            cid, previous = await prepare(request, payload, identity, deadline, cancelled)
            if request.app.state.rag is None:
                raise VectorStoreError('OPENAI_API_KEY 未配置')
            result = asdict(await request.app.state.rag.answer(payload.question, previous, metrics=metrics))
            if await request.is_disconnected():
                raise asyncio.CancelledError()
            await asyncio.to_thread(request.app.state.sessions.save, cid, identity, rid,
                                    payload.question, result['answer'], result['sources'], deadline, cancelled)
        log_result(rid, started, result)
        return {**result, 'conversation_id': cid, 'request_id': rid, 'latency_ms': round((perf_counter()-started)*1000, 2)}
    except asyncio.CancelledError:
        cancelled.set()
        log_result(rid, started, metrics, error='cancelled')
        raise
    except Exception as exc:
        cancelled.set()
        status, code, detail = error_info(exc)
        log_result(rid, started, metrics, error=code)
        raise HTTPException(status, {'code': code, 'message': detail, 'request_id': rid}) from exc
    finally:
        if cid:
            await asyncio.to_thread(request.app.state.sessions.release, cid, rid)


@router.post('/chat/stream')
async def stream_chat(payload: ChatRequest, request: Request, identity=Depends(owner)):
    started = perf_counter()
    rid = request.state.request_id
    cancelled = Event()
    metrics = {}
    deadline = monotonic() + request.app.state.settings.request_timeout
    try:
        async with asyncio.timeout(max(0, deadline - monotonic())):
            cid, previous = await prepare(request, payload, identity, deadline, cancelled)
    except Exception as exc:
        cancelled.set()
        status, code, detail = error_info(exc)
        log_result(rid, started, metrics, error=code)
        raise HTTPException(status, {'code': code, 'message': detail, 'request_id': rid}) from exc

    def frame(data):
        return 'data: ' + json.dumps(data, ensure_ascii=False) + '\n\n'

    async def events():
        try:
            yield frame({'type': 'start', 'conversation_id': cid, 'request_id': rid, 'validated': False})
            async with asyncio.timeout(max(0, deadline - monotonic())):
                if request.app.state.rag is None:
                    raise VectorStoreError('OPENAI_API_KEY 未配置')
                async with aclosing(request.app.state.rag.stream_answer(payload.question, previous, metrics=metrics)) as stream:
                    async for event in stream:
                        if await request.is_disconnected():
                            raise asyncio.CancelledError()
                        if event.get('type') == 'complete':
                            await asyncio.to_thread(request.app.state.sessions.save, cid, identity, rid,
                                                    payload.question, event['answer'], event['sources'], deadline, cancelled)
                            event.update(conversation_id=cid, request_id=rid, latency_ms=round((perf_counter()-started)*1000, 2))
                            log_result(rid, started, event)
                        yield frame(event)
            yield 'data: [DONE]\n\n'
        except asyncio.CancelledError:
            cancelled.set()
            log_result(rid, started, metrics, error='cancelled')
            raise
        except Exception as exc:
            cancelled.set()
            _, code, detail = error_info(exc)
            log_result(rid, started, metrics, error=code)
            yield 'event: error\n' + frame({'type': 'error', 'code': code, 'detail': detail, 'validated': False, 'request_id': rid})
        finally:
            await asyncio.shield(asyncio.to_thread(request.app.state.sessions.release, cid, rid))

    return StreamingResponse(events(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
