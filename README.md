# Zhiku · AI Knowledge Assistant

Zhiku is a FastAPI-based Retrieval-Augmented Generation (RAG) application for asking questions about documents stored in Google Drive. It provides a Chinese web chat interface, synchronous and streaming APIs, source citations, persistent conversations, and optional HTTP Basic authentication.

## Features

- Imports PDF, DOCX, and TXT files from one or more Google Drive folders
- Preserves file names, Drive links, PDF page numbers, and stable chunk metadata
- Uses LlamaIndex for document nodes, chunking, OpenAI embeddings, Chroma indexing, and retrieval
- Uses LangChain for conversation-aware question rewriting, prompts, and OpenAI chat generation
- Requires numbered citations and returns structured source metadata with every successful answer
- Supports standard JSON responses and Server-Sent Events (SSE) streaming
- Persists browser identities, conversations, and successful turns in SQLite
- Prevents overlapping requests within the same conversation
- Includes optional HTTP Basic authentication and same-origin request protection
- Serves a responsive HTML/CSS/JavaScript chat interface directly from FastAPI

## Architecture

```text
Google Drive
    │
    ├── PDF / DOCX / TXT extraction
    ├── LlamaIndex Document + SentenceSplitter
    ├── OpenAIEmbedding
    └── ChromaVectorStore + version manifest

User question + conversation history
    │
    ├── LangChain standalone-question rewrite when needed
    ├── LlamaIndex asynchronous retrieval
    ├── numbered context with source metadata
    ├── LangChain ChatOpenAI generation
    └── citation validation → answer + sources
```

LlamaIndex owns indexing, embedding, and retrieval. LangChain owns message handling, prompts, question rewriting, and answer generation. FastAPI owns HTTP endpoints, authentication, sessions, error handling, and the web interface.

## Project Structure

```text
app/
  api/
    auth.py              Basic Auth, browser identity, same-origin checks
    chat.py              Conversation, chat, and streaming endpoints
  db/
    sessions.py          SQLite-backed sessions and conversation history
    vector_store.py      LlamaIndex and persistent Chroma integration
  services/
    chunker.py           Page-aware node creation and stable IDs
    drive_auth.py        Google OAuth and Drive API client
    drive_loader.py      Google Drive listing, download, and text extraction
    models.py            Shared document models
    rag.py               Retrieval, generation, streaming, and citations
  static/
    index.html           Chat interface
    app.js               Browser behavior and SSE handling
    style.css            Responsive styling
  config.py              Environment-based application settings
  main.py                FastAPI application and static routes
docs/
  evaluation.md          Real-model evaluation prompts
scripts/
  ingest_drive.py        Google Drive ingestion command
tests/                   Unit, integration, API, and browser tests
Dockerfile
requirements.txt         Direct dependencies
requirements.lock        Verified transitive dependency constraints
```

## Requirements

- Python 3.12 or newer
- An OpenAI API key
- A Google Cloud project with the Google Drive API enabled
- A Google OAuth Desktop app client JSON file
- Read access to at least one Google Drive folder

## Installation

Create a virtual environment and install the locked dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -c requirements.lock
```

Copy the environment template:

```bash
cp .env.example .env
```

`requirements.txt` lists the direct application and test dependencies. `requirements.lock` constrains the complete verified dependency set so local, CI, and Docker environments resolve consistently.

## Configuration

Set at least the following values in `.env`:

```dotenv
OPENAI_API_KEY=your-openai-api-key
GOOGLE_DRIVE_FOLDER_ID=folder-id-1,folder-id-2
GOOGLE_OAUTH_CREDENTIALS_FILE=credentials.json
GOOGLE_OAUTH_TOKEN_FILE=token.json
```

Available settings:

| Setting | Default | Description |
|---|---:|---|
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` | Chat model used for rewriting and answer generation |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model used for ingestion and retrieval |
| `OPENAI_EMBEDDING_DIMENSIONS` | `1536` | Embedding dimensions; must match the Chroma collection |
| `VECTOR_STORE_DIR` | `data/chroma_v2` | Persistent Chroma and version-manifest directory |
| `CHROMA_COLLECTION` | `google_drive_llama_v1` | Chroma collection name |
| `CHUNK_SIZE` | `768` | Target chunk size |
| `CHUNK_OVERLAP` | `100` | Overlap between adjacent chunks |
| `EMBEDDING_BATCH_SIZE` | `64` | OpenAI embedding batch size |
| `RETRIEVAL_TOP_K` | `5` | Maximum retrieved nodes per question |
| `CONTEXT_MAX_CHARS` | `16000` | Maximum retrieved context supplied to the model |
| `HISTORY_MAX_TURNS` | `6` | Maximum conversation turns considered for rewriting |
| `HISTORY_MAX_CHARS` | `8000` | Character budget for conversation history |
| `REQUEST_TIMEOUT` | `90` | End-to-end request timeout in seconds |
| `MAX_OUTPUT_TOKENS` | `2000` | Maximum generated answer tokens |
| `SESSION_DB` | `data/sessions.sqlite3` | SQLite session database path |
| `SESSION_TTL_SECONDS` | `604800` | Anonymous browser identity lifetime |
| `COOKIE_SECURE` | `false` | Set to `true` when serving through HTTPS |
| `API_BASIC_AUTH_USERNAME` | empty | Optional Basic Auth username |
| `API_BASIC_AUTH_PASSWORD` | empty | Optional Basic Auth password |

Both Basic Auth values must be configured together. `CHUNK_OVERLAP` must be nonnegative and smaller than `CHUNK_SIZE`; numeric limits must be positive.

## Google Drive Setup

1. Enable the Google Drive API in your Google Cloud project.
2. Configure the OAuth consent screen.
3. Create an OAuth client with the **Desktop app** application type.
4. Download the client JSON and save it as `credentials.json`, or update `GOOGLE_OAUTH_CREDENTIALS_FILE`.
5. Add the target folder IDs to `GOOGLE_DRIVE_FOLDER_ID`.
6. Ensure the Google account used during OAuth can read those folders.

The first ingestion opens a browser for read-only Google authorization. The resulting OAuth token is stored in `token.json` by default and is reused and refreshed automatically.

Credential files, OAuth tokens, `.env`, Chroma data, and SQLite databases are excluded from Git and Docker build contexts.

## Ingesting Documents

Review your collection settings and potential OpenAI embedding charges, then run:

```bash
python scripts/ingest_drive.py --confirm-cost
```

The `--confirm-cost` flag is required because ingestion may call the OpenAI Embeddings API.

The ingestion pipeline:

1. Lists supported files directly inside each configured Drive folder.
2. Downloads PDF, DOCX, and TXT content.
3. Preserves physical page numbers for PDFs.
4. Cleans text and creates page-aware LlamaIndex nodes.
5. Generates stable file versions and chunk IDs.
6. Embeds missing nodes and writes them to persistent Chroma storage.
7. Publishes a file version only after all of its nodes have been written successfully.

Running ingestion again is safe. Unchanged chunks are skipped. When a file changes, the new complete version becomes searchable only after successful ingestion; an interrupted update does not replace the currently published version.

## Running the Application

Start FastAPI with Uvicorn:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open the chat interface:

```text
http://127.0.0.1:8000/
```

The interface supports streaming answers, follow-up questions, source cards, new conversations, cancellation, keyboard submission, and responsive mobile layouts.

Check application health:

```bash
curl http://127.0.0.1:8000/health
```

Example response:

```json
{"status":"ok","configured":true}
```

`configured` indicates whether an OpenAI-backed RAG pipeline is available. The health endpoint does not perform an end-to-end OpenAI or knowledge-base query.

## API

Interactive OpenAPI documentation is available at:

```text
http://127.0.0.1:8000/docs
```

### Create a Conversation

```bash
curl -c /tmp/rag-cookie.txt -b /tmp/rag-cookie.txt \
  -X POST http://127.0.0.1:8000/conversations
```

```json
{
  "conversation_id": "c787d59a-50aa-448a-927f-b2ce5d5d3d82",
  "request_id": "8cb22ab4-e923-4851-9db8-5e997cc733a8"
}
```

### Ask a Question

The `conversation_id` is optional. If omitted, the server creates a conversation automatically.

```bash
curl -c /tmp/rag-cookie.txt -b /tmp/rag-cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{"question":"What documents are required?"}' \
  http://127.0.0.1:8000/chat
```

Example response shape:

```json
{
  "answer": "The application requires an identity document. [1]",
  "conversation_id": "c787d59a-50aa-448a-927f-b2ce5d5d3d82",
  "request_id": "8cb22ab4-e923-4851-9db8-5e997cc733a8",
  "sources": [
    {
      "citation_id": 1,
      "chunk_id": "...",
      "file_name": "policy.pdf",
      "file_id": "...",
      "source_link": "https://drive.google.com/...",
      "page_number": 3,
      "snippet": "..."
    }
  ],
  "usage": null,
  "retrieval_ms": 24.8,
  "generation_ms": 402.1,
  "rewrite_ms": 0.0,
  "rewrite_usage": null,
  "latency_ms": 431.6
}
```

To continue a conversation, send its ID with the next question:

```json
{
  "question": "What about international applicants?",
  "conversation_id": "c787d59a-50aa-448a-927f-b2ce5d5d3d82"
}
```

### Stream an Answer

```bash
curl -N -c /tmp/rag-cookie.txt -b /tmp/rag-cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{"question":"Summarize the application requirements."}' \
  http://127.0.0.1:8000/chat/stream
```

The endpoint returns Server-Sent Events:

```text
data: {"type":"start","conversation_id":"...","request_id":"...","validated":false}

data: {"type":"sources","sources":[...],"validated":false}

data: {"token":"The application","validated":false}

data: {"type":"complete","answer":"... [1]","sources":[...],"validated":true,...}

data: [DONE]
```

Streamed tokens remain unvalidated until the `complete` event. If generation or citation validation fails, the stream emits an `event: error` payload and does not send `complete` or `[DONE]`.

### Retrieve Conversation History

```bash
curl -c /tmp/rag-cookie.txt -b /tmp/rag-cookie.txt \
  http://127.0.0.1:8000/conversations/{conversation_id}
```

Only successful turns owned by the current browser identity or authenticated user are returned.

### Error Responses

| Status | Meaning |
|---:|---|
| `400` / `422` | Invalid request payload |
| `401` | Missing or invalid Basic Auth credentials |
| `403` | Cross-origin write request rejected |
| `404` | Conversation does not exist or belongs to another identity |
| `409` | The conversation already has an active request |
| `429` | OpenAI rate limit reached |
| `502` | Upstream generation failure or invalid citations |
| `503` | OpenAI is not configured or the knowledge base is unavailable |
| `504` | Request timed out |

Error responses include the request ID when processing reached the chat pipeline. Use the `X-Request-ID` response header and server logs for troubleshooting.

## Authentication and Security

For local development, Basic Auth may remain disabled. Each browser then receives an opaque, expiring `rag_session` cookie that owns its conversations. Knowing another conversation ID is not sufficient to access its history.

For shared or remote environments, configure both:

```dotenv
API_BASIC_AUTH_USERNAME=your-username
API_BASIC_AUTH_PASSWORD=use-a-strong-password
COOKIE_SECURE=true
```

When Basic Auth is enabled, conversations belong to the authenticated username. The application also:

- Uses HttpOnly, SameSite=Strict session cookies
- Rejects cross-site write requests
- Adds Content Security Policy and `X-Content-Type-Options` headers
- Disables response caching
- Accepts only HTTP/HTTPS source links
- Renders model output as text rather than executable HTML
- Treats retrieved documents and conversation history as untrusted input
- Excludes secrets and full document contents from normal application logs

Run behind HTTPS before enabling `COOKIE_SECURE=true`. A reverse proxy must preserve the original host and scheme and disable buffering for SSE responses.

## Data and Persistence

- Chroma vectors and the version manifest are stored under `VECTOR_STORE_DIR`.
- Conversation identities and successful turns are stored in `SESSION_DB`.
- Failed, cancelled, timed-out, or citation-invalid answers are not added to successful history.
- Retrieval uses only published file versions.
- Back up the complete vector-store directory, including `versions.sqlite3`.

The current storage design targets a single host. Multi-host deployment requires shared or external vector and session storage.

## Docker

Build the image:

```bash
docker build -t rag-ai-knowledge-assistant .
```

Run the API with persistent local data:

```bash
docker run --rm -p 8000:8000 \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  rag-ai-knowledge-assistant
```

The Docker image preloads the tiktoken `cl100k_base` encoding. Local credentials, tokens, vector data, session databases, and output directories are excluded from the image by `.dockerignore`.

For the simplest OAuth flow, run ingestion on the host first, then mount the resulting `data` directory into the API container.

## Testing

Run the automated test suite and dependency consistency check:

```bash
python -m pytest -q
python -m pip check
```

The tests use mocked model and embedding clients, temporary Chroma collections, and temporary SQLite databases. They cover ingestion, stable IDs, deduplication, version publication, retrieval, citations, sessions, authentication, streaming, errors, cancellation, timeouts, security headers, and the static interface.

Optional browser acceptance tests require Node.js and Playwright:

```bash
# Terminal 1
python tests/ui_server.py

# Terminal 2
node tests/browser.cjs
```

Set `PLAYWRIGHT_MODULE` if Playwright is installed outside the project. Browser screenshots are written to `/tmp/rag-chat-desktop.png` and `/tmp/rag-chat-mobile.png`.

Real-model evaluation examples are available in [`docs/evaluation.md`](docs/evaluation.md). Running them requires valid credentials and may incur API charges.

## Current Limitations

- Google Drive folders are not traversed recursively.
- Native Google Docs files are not exported or ingested.
- Scanned PDFs require OCR before ingestion.
- Cloud file deletions do not automatically remove stored vectors.
- Old physical file versions remain in Chroma after a newer version is published.
- The built-in web interface does not automatically reopen the last conversation after a page reload.
- Local Chroma and SQLite storage are intended for a single-host deployment.

## License

No license file is currently included in this repository.
