# Zhiku · Google Drive Document Q&A

A Chinese web chat interface and RAG API built with FastAPI. The application has one combined pipeline:

```text
Google Drive → page-aware parsing → LlamaIndex Document / SentenceSplitter
             → LlamaIndex OpenAIEmbedding → ChromaVectorStore → Chroma

Question + server-side history → LangChain standalone-question rewrite when needed
                               → LlamaIndex aretrieve (one question embedding, one retrieval)
                               → NodeWithScore → LangChain Document → numbered context
                               → LangChain ChatPromptTemplate / ChatOpenAI → answer + sources
```

LlamaIndex handles nodes, chunking, embeddings, the vector index, and asynchronous retrieval; QueryEngine is not used to generate answers. LangChain handles messages, follow-up question rewriting, prompts, and standard/streaming generation; there is no second retriever. FastAPI handles endpoints, authentication, sessions, and the static web interface. The application has no Agent, LangGraph, or switchable RAG backends.

## Installation and Configuration

Use Python **3.12** or a compatible newer version (the locked dependencies require at least 3.12). This project was verified with Python 3.12.11. Run:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -c requirements.lock
cp .env.example .env
```

`requirements.txt` pins direct dependencies; `requirements.lock` pins the transitive dependencies from the verified environment. Core versions include langchain-core 0.3.86, langchain-openai 0.3.35, llama-index-core 0.12.52, llama-index-embeddings-openai 0.3.1, llama-index-vector-stores-chroma 0.4.2, and chromadb 1.5.9. Only the required framework components are installed. LlamaIndex workflows is a transitive dependency, but the application does not use workflows or Agents.

Set `OPENAI_API_KEY` and `GOOGLE_DRIVE_FOLDER_ID` in `.env` (use a comma-separated list for multiple folders). When retaining an existing `.env`, add new settings manually instead of overwriting credentials.

| Setting | Default / Description |
|---|---|
| OPENAI_CHAT_MODEL | gpt-4o-mini |
| OPENAI_EMBEDDING_MODEL | text-embedding-3-small |
| OPENAI_EMBEDDING_DIMENSIONS | 1536; ingestion and retrieval must match |
| VECTOR_STORE_DIR | data/chroma_v2; a new directory avoids opening the old production database |
| CHROMA_COLLECTION | google_drive_llama_v1; use a new collection for the initial migration |
| CHUNK_SIZE / CHUNK_OVERLAP | 768 / 100, counted in tokenizer tokens |
| EMBEDDING_BATCH_SIZE | 64 |
| RETRIEVAL_TOP_K | 5 |
| CONTEXT_MAX_CHARS | 16000, the retrieved-context character budget |
| HISTORY_MAX_TURNS / HISTORY_MAX_CHARS | 6 / 8000; retains a limited number of complete history turns |
| REQUEST_TIMEOUT | 90 seconds, covering question rewriting, retrieval, and generation |
| MAX_OUTPUT_TOKENS | 2000 |
| SESSION_DB | data/sessions.sqlite3 |
| SESSION_TTL_SECONDS | 604800, browser cookie identity lifetime |
| COOKIE_SECURE | false for local HTTP; set to true for HTTPS deployments |
| API_BASIC_AUTH_USERNAME / PASSWORD | Basic Auth is disabled when both are empty; both must be configured together |

The old `CHUNK_MIN_TOKENS`, `CHUNK_MAX_TOKENS`, and `CHUNK_OVERLAP_TOKENS` settings were removed and replaced by the names above. Initial chunking may download tiktoken's cl100k_base encoding table; this does not call a model or incur model charges. Cache the encoding table before running offline. There is no silent fallback tokenizer because that would cause chunk boundaries to drift across environments.

## Google Drive Authentication and Ingestion

1. Enable the Drive API in a Google Cloud project, configure the OAuth consent screen, and create a **Desktop app** OAuth client.
2. Save the client file as `credentials.json`, or set `GOOGLE_OAUTH_CREDENTIALS_FILE`.
3. Set `GOOGLE_DRIVE_FOLDER_ID`; the signed-in account must be able to read the configured folders.
4. Complete the read-only authorization flow in a local browser during the first ingestion. The token is stored in `token.json`; change its path with `GOOGLE_OAUTH_TOKEN_FILE`. Later runs reuse and refresh it.

`app/services/drive_auth.py` is present, and the script imports `get_drive_service` directly. PDF, DOCX, and TXT files are supported, file listings are paginated, and shared drives are supported. PDFs retain physical page numbers; DOCX/TXT page numbers are null. Scanned PDFs without extractable text do not produce nodes. OCR, native Google Docs export, recursive subfolder traversal, and cloud deletion synchronization are not currently implemented.

**The initial migration requires re-chunking and re-embedding and may incur OpenAI API charges.** The script requires an explicit cost-confirmation argument. No real ingestion was run during development.

```bash
python scripts/ingest_drive.py --help
# Run only after reviewing the new directory, collection, and cost settings in .env:
python scripts/ingest_drive.py --confirm-cost
```

Each page creates a LlamaIndex Document and is split with SentenceSplitter. Nodes store `chunk_id`, `file_id`, `file_name`, `source_link`, `page_number`, `chunk_index`, `content_hash`, `chunk_version`, and the complete file `version`. Chroma stores 0 for an unknown page number; the API converts it back to null.

Stable IDs include the file identity, complete file content and source metadata, chunk version/parameters, and position. Re-ingesting identical input does not add nodes or repeat embedding. Changes to file content, source metadata, or chunk parameters create a new version and require the entire file to be embedded again.

### File Updates and Failure Recovery

Run the same ingestion command again. The application first writes every node for the new version and verifies the IDs, then publishes the file version transactionally through `versions.sqlite3`. Retrieval uses a LlamaIndex metadata filter to query only published versions. If ingestion fails, the old version remains active; partially staged nodes are excluded from retrieval and can be completed on the next run. Old versions are deactivated but remain on disk. This version does not automatically delete their physical data and does not remove unrelated files.

A local file lock serializes concurrent ingestion processes; reads do not wait for the lock, and in-flight requests use the version snapshot from when they began. New requests see only the newly published version. Backup and restore the entire Chroma directory, including `versions.sqlite3`; do not discard the version manifest separately. If file parsing fails or yields no text, the old version stays active and the empty result is not treated as a deletion instruction. There is no need to delete old code again after merging into master: all required deletions are already included in the development branch commits.

### Switching to the New Collection and Rolling Back

The initial migration defaults to `data/chroma_v2` / `google_drive_llama_v1` while preserving the original `data/chroma` / `google_drive_docs`. You may also use another new collection name in a separate test copy. Do not direct new ingestion into the old collection.

The same combined pipeline can query the old collection. Stop the service, back up the old directory first (copying it to a rollback directory is recommended so a newer Chroma version cannot upgrade the original data format), point `VECTOR_STORE_DIR` to the copy, set `CHROMA_COLLECTION=google_drive_docs`, configure the embedding model and dimensions actually used by the old database, and restart. LlamaIndex ChromaVectorStore provides the old-schema adapter. The old collection does not contain reliable model metadata, so its configuration must be confirmed manually. The ingestion program refuses to write to old-schema collections.

When rolling back the code, also use the original backup directory and dependency versions. This work does not delete the original code backup branch. To return to the new collection, restore the new directory/collection settings and restart. Do not declare the old collection as the new schema or manually modify collection metadata.

## Running the Service and Web Interface

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open the [chat page](http://127.0.0.1:8000/) to stream responses, ask follow-up questions, inspect cited sources, create conversations, and stop generation. Press Enter to send and Shift+Enter for a new line. The responsive interface uses plain HTML/CSS/JavaScript. Text is rendered through `textContent`, so model-generated HTML is never executed; source links accept only http/https URLs.

After Basic Auth is configured, opening the home page triggers the browser's native login dialog, and later requests call same-origin APIs. API keys, Google credentials, and tokens are never sent to the frontend. Without Basic Auth, the service is suitable only for a local or trusted network: visitors can query the knowledge base, but every browser receives a server-generated, registered, expiring HttpOnly/SameSite cookie and cannot read another user's history using only their conversation_id. With Basic Auth enabled, sessions are bound to the authenticated username; one username represents one user. If the model key is not configured, the home page and health check remain available, while chat requests return a clear 503 response.

Sessions and successful turns are persisted in SQLite and survive service restarts. The current web interface does not automatically reopen the last conversation, but the API can retrieve recent history for a specified session. After the cookie expires, an anonymous user can no longer access history belonging to the previous identity. History is used only to understand questions; business conclusions must be generated from documents retrieved for the current request. Concurrent requests within the same session return 409 to prevent interleaved history, while different sessions can run concurrently.

## API and Streaming Protocol

Legacy requests may continue to send only `question`:

```bash
curl -c /tmp/rag-cookie.txt -b /tmp/rag-cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{"question":"What documents are required for the application?"}' http://127.0.0.1:8000/chat
```

When authentication is enabled, add `-u 'username:password'`; never put real passwords in shared scripts or source control. For follow-up requests, send the `conversation_id` from the response. Anonymous clients must preserve the cookie.

- `POST /conversations`: creates and returns a conversation_id.
- `GET /conversations/{id}`: returns a limited number of recent successful turns visible to the current user.
- `POST /chat`: returns answer, conversation_id, request_id, sources, latency_ms, available usage data, and per-stage timing.
- `POST /chat/stream`: returns an SSE stream.
- `GET /health`: reports process liveness and whether the model is configured; it does **not** prove end-to-end availability of the remote API or knowledge base.

Each source contains `citation_id`, `chunk_id`, `file_name`, `file_id`, `source_link`, `page_number`, and `snippet`. Source numbering starts at 1. The snippet previews the actual passage supplied to the model and is limited to 500 characters.

SSE preserves the legacy `{"token":"..."}` payload and the `[DONE]` marker on successful completion. Clients remain compatible by ignoring unknown fields in the new messages:

```text
data: {"type":"start","conversation_id":"...","request_id":"...","validated":false}

data: {"type":"sources","sources":[...],"validated":false}

data: {"token":"An ID card is required.","validated":false}

data: {"type":"complete","answer":"An ID card is required. [1]","sources":[...],"validated":true,"latency_ms":321,...}

data: [DONE]
```

Errors use `event: error` and a JSON payload containing `type`, error `code`, `detail`, `request_id`, and `validated:false`; they do not send `complete` or `[DONE]`. Standard endpoints return an HTTP status and `detail.code/message/request_id`. A valid citation requires at least one `[number]`, and every number must identify a source from the current request. This validates only citation format and range; it **does not prove factual accuracy or that a citation supports the conclusion**. When the available material is insufficient, the model should identify what is missing and cite the relevant material it inspected.

An empty knowledge base or missing model key returns 503; inaccessible or nonexistent sessions return 404; busy sessions return 409; timeouts return 504; rate limits return 429; citation errors and upstream failures return 502. After a streaming response has started, errors are reported through SSE. Streamed text remains unvalidated until the `complete` event, and the web interface clearly marks errors and interruptions. Cancellation closes the asynchronous generation stream and attempts to cancel upstream work; failed and incomplete responses are not stored in successful history. Synchronous Chroma queries and database operations run outside the FastAPI event loop; local work already running in a thread cannot be forcibly stopped.

Logs record request_id, retrieval/generation/rewrite/total duration, error type, and token usage when the model provides it; otherwise usage is null. Incomplete stage metrics may be null on failure. Complete prompts, document text, and secrets are not logged by default, and LangSmith tracing is disabled. Reverse proxies must disable SSE buffering and forward the correct same-origin host/scheme; cross-site write requests are rejected.

## Docker

```bash
docker build -t rag-ai-knowledge-assistant .
docker run --rm -p 8000:8000 --env-file .env \
  -v "$PWD/data:/app/data" rag-ai-knowledge-assistant
```

`.dockerignore` excludes `.env`, Google credentials, tokens, the knowledge base, and local output so they are not copied into the image. The API container does not need Google credentials when querying previously ingested vectors. Complete OAuth ingestion locally first, then mount the token and client files separately:

```bash
docker run --rm --env-file .env -v "$PWD/data:/app/data" \
  -v "$PWD/credentials.json:/app/credentials.json:ro" \
  -v "$PWD/token.json:/app/token.json" \
  rag-ai-knowledge-assistant python scripts/ingest_drive.py --confirm-cost
```

The current design targets a single host with local Chroma and SQLite. Multi-host deployments require dedicated storage services. A Docker build was attempted, but fetching metadata for Docker Hub's python:3.12-slim image timed out, so container build/runtime verification is not complete. Real Google/OpenAI end-to-end verification has also not been performed.

## Testing and Manual Acceptance

```bash
python -m pytest -q
python -m pip check
```

Automated tests use mocked chat/embedding services, temporary Chroma collections, and temporary SQLite databases; they do not depend on production data. Coverage includes page numbers, stable IDs, deduplication, file version updates/failure retention/isolation, old-collection query protection, metadata adaptation, standard/streaming requests, follow-up rewriting, citation errors, session persistence/isolation, timeouts/service failures, authentication, and static-page security.

Manual browser verification additionally requires Node and Playwright:

```bash
# Terminal 1: local-only offline test service with a temporary session database
python tests/ui_server.py
# Terminal 2: install Playwright in a temporary npm environment and cache Chromium
node tests/browser.cjs
```

Set `PLAYWRIGHT_MODULE` to an externally installed Playwright module to avoid adding a frontend dependency to the application. The script verifies sending, Enter/Shift+Enter, streaming validation state, source cards, new conversations, safe display of malicious HTML, citation failures, cancellation without history writes, and the mobile layout. Screenshots are written to `/tmp/rag-chat-desktop.png` and `/tmp/rag-chat-mobile.png`.

Example questions for real-model acceptance are available in [docs/evaluation.md](docs/evaluation.md). Configure real credentials and explicitly approve API charges before running them. Automated tests do not judge byte-for-byte model answers and do not replace business-level factual verification.

## Official API References

The implementation refers to [LlamaIndex SentenceSplitter](https://developers.llamaindex.ai/python/framework-api-reference/node_parsers/sentence_splitter/), [ChromaVectorStore](https://developers.llamaindex.ai/python/framework-api-reference/storage/vector_store/chroma/), [OpenAIEmbedding](https://developers.llamaindex.ai/python/framework-api-reference/embeddings/openai/), and [LangChain ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai). Official pages may change over time; the installed versions in this project were separately verified through local API and integration tests.
