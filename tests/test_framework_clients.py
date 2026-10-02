"""Exercise installed framework/SDK APIs against an in-memory HTTP transport."""
import asyncio
import json

import httpx
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from llama_index.embeddings.openai import OpenAIEmbedding


def test_installed_clients_with_mock_http():
    calls = []
    def handle(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path.endswith('/embeddings'):
            return httpx.Response(200, json={'object': 'list', 'model': body['model'],
                'data': [{'object': 'embedding', 'index': i, 'embedding': [0.5]*8} for i, _ in enumerate(body['input'])],
                'usage': {'prompt_tokens': 2, 'total_tokens': 2}})
        if body.get('stream'):
            events = [
                {'id': 'test', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'gpt-4o-mini',
                 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': '资料 [1]'}, 'finish_reason': None}]},
                {'id': 'test', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'gpt-4o-mini',
                 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]},
                {'id': 'test', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'gpt-4o-mini', 'choices': [],
                 'usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}}]
            return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                                  text=''.join('data: '+json.dumps(e)+'\n\n' for e in events)+'data: [DONE]\n\n')
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 1, 'model': 'gpt-4o-mini',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '资料 [1]'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}})

    transport = httpx.MockTransport(handle)
    async def run():
        async with httpx.AsyncClient(transport=transport) as async_http:
            with httpx.Client(transport=transport) as sync_http:
                embedding = OpenAIEmbedding(api_key='offline-test', model='text-embedding-3-small', dimensions=8,
                    http_client=sync_http, async_http_client=async_http, max_retries=0)
                assert len(embedding.get_text_embedding('document')) == 8
                assert len(await embedding.aget_query_embedding('question')) == 8
                model = ChatOpenAI(api_key='offline-test', model='gpt-4o-mini', http_client=sync_http,
                                   http_async_client=async_http, stream_usage=True, max_retries=0)
                message = await model.ainvoke([HumanMessage('question')])
                assert message.content == '资料 [1]' and message.usage_metadata['total_tokens'] == 5
                chunks = [chunk async for chunk in model.astream([HumanMessage('question')])]
                assert ''.join(chunk.content for chunk in chunks) == '资料 [1]'
                assert chunks[-1].usage_metadata['total_tokens'] == 5
    asyncio.run(run())
    assert len(calls) == 4
    assert all(body['dimensions'] == 8 for path, body in calls if path.endswith('/embeddings'))
    assert calls[-1][1]['stream_options']['include_usage'] is True
