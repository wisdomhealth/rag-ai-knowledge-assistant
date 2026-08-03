# rag-ai-knowledge-assistant

FastAPI service for asking questions over documents stored in Google Drive. It ingests supported Drive files, chunks and embeds their text with OpenAI embeddings, stores vectors in a local Chroma database, and answers questions with source citations.

## Features

- Google Drive ingestion for PDF, DOCX, and plain text files
- OpenAI embeddings and chat completions
- Persistent local Chroma vector store
- Non-streaming and Server-Sent Events streaming chat endpoints
- Optional HTTP Basic authentication for API access
- Dockerfile and pytest test suite included

## Project Structure

```text
app/
  api/                 FastAPI routes and optional Basic Auth
  db/                  Chroma vector store wrapper
  services/            Drive loading, chunking, embeddings, LLM, RAG pipeline
  utils/               Logging and text cleaning helpers
scripts/
  ingest_drive.py      Google Drive ingestion entrypoint
tests/                 Unit tests
data/chroma/           Local Chroma persistence directory
```

## Requirements

- Python 3.11+
- OpenAI API key
- Google OAuth desktop client JSON saved as `credentials.json`
- One or more Google Drive folder IDs accessible to the signed-in Google user

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file from the example and fill in your values:

```bash
cp .env.example .env
```

```bash
OPENAI_API_KEY=your-openai-api-key
GOOGLE_DRIVE_FOLDER_ID=drive-folder-id-1,drive-folder-id-2

# OAuth desktop client and cached token files
GOOGLE_OAUTH_CREDENTIALS_FILE=credentials.json
GOOGLE_OAUTH_TOKEN_FILE=token.json

# Optional model overrides
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_CHAT_MODEL=gpt-4o-mini

# Optional vector/chunking settings
VECTOR_STORE_DIR=data/chroma
CHUNK_MIN_TOKENS=1000
CHUNK_MAX_TOKENS=1500
CHUNK_OVERLAP_TOKENS=150
RETRIEVAL_TOP_K=5
EMBEDDING_BATCH_SIZE=64

# Optional API Basic Auth
API_BASIC_AUTH_USERNAME=
API_BASIC_AUTH_PASSWORD=
```

Notes:

- `GOOGLE_DRIVE_FOLDER_ID` accepts a comma-separated list.
- `credentials.json` must be an OAuth client JSON for a desktop app, not a service account JSON.
- On the first ingestion run, a browser opens for Google login and writes `token.json`.
- The signed-in Google account must be able to read the Drive folders and files.
- Basic Auth is disabled unless both `API_BASIC_AUTH_USERNAME` and `API_BASIC_AUTH_PASSWORD` are set.
- `.env`, OAuth credential/token files, and generated Chroma data are ignored by git.

## Ingest Google Drive Documents

Run ingestion before asking questions:

```bash
python scripts/ingest_drive.py
```

On the first run, the script starts a local OAuth browser flow. After login succeeds, `token.json` is generated automatically and reused by later runs.

The script:

1. Authenticates with Google Drive through OAuth InstalledAppFlow.
2. Lists supported files from the configured Drive folders.
3. Extracts text from PDF, DOCX, and TXT files.
4. Splits text into overlapping chunks.
5. Embeds new chunks with OpenAI.
6. Persists them in Chroma under `VECTOR_STORE_DIR`.

Existing chunks are skipped by chunk ID, so repeated runs only add new content.

## Run the API

```bash
uvicorn app.main:app --reload
```

Default local URL:

```text
http://127.0.0.1:8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Chat API

### Non-streaming

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"What does the document say about the onboarding process?"}'
```

Response shape:

```json
{
  "answer": "Answer text with source file names.",
  "sources": [
    {
      "file_name": "example.pdf",
      "file_id": "google-drive-file-id",
      "snippet": "Retrieved source snippet...",
      "source_link": "https://drive.google.com/...",
      "page_number": 1
    }
  ]
}
```

### Streaming

```bash
curl -N -X POST http://127.0.0.1:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"Summarize the latest policy document."}'
```

The stream uses Server-Sent Events and emits JSON token payloads:

```text
data: {"token":"..."}

data: [DONE]
```

### With Basic Auth

If Basic Auth is enabled:

```bash
curl -u "$API_BASIC_AUTH_USERNAME:$API_BASIC_AUTH_PASSWORD" \
  -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"What files mention refunds?"}'
```

## Docker

Build the image:

```bash
docker build -t rag-ai-knowledge-assistant .
```

Run the API:

```bash
docker run --rm -p 8000:8000 \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  -v "$PWD/credentials.json:/app/credentials.json:ro" \
  -v "$PWD/token.json:/app/token.json" \
  rag-ai-knowledge-assistant
```

Because this project uses an installed-app OAuth browser flow, run `python scripts/ingest_drive.py` locally first to generate `token.json` before running ingestion inside Docker.

To ingest inside Docker, override the command:

```bash
docker run --rm \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  -v "$PWD/credentials.json:/app/credentials.json:ro" \
  -v "$PWD/token.json:/app/token.json" \
  rag-ai-knowledge-assistant \
  python scripts/ingest_drive.py
```

## Tests

```bash
pytest
```

The current tests cover chunking, text cleaning, and vector store behavior.

## Troubleshooting

- `OPENAI_API_KEY is required`: set `OPENAI_API_KEY` in `.env` or the process environment.
- `GOOGLE_DRIVE_FOLDER_ID is required`: set one or more folder IDs before running ingestion.
- `Google OAuth client file not found`: download an OAuth desktop client JSON from Google Cloud and save it as `credentials.json`.
- Browser does not open during first login: run ingestion from a local terminal with browser access, or open the printed OAuth URL manually.
- `Vector store is empty`: run `python scripts/ingest_drive.py` before calling `/chat`.
- No files found during ingestion: confirm the signed-in Google account can access the Drive folder and it contains PDF, DOCX, or TXT files.
