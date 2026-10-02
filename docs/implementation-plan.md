# Combined RAG Implementation Record

Goal: retain Google Drive, Basic Auth, FastAPI, and Docker; use LlamaIndex for retrieval and LangChain for generation; add a streaming web interface.

Architecture decisions: LlamaIndex SentenceSplitter performs page-aware chunking, OpenAIEmbedding generates vectors, and ChromaVectorStore provides persistence. Each file version is atomically published through a SQLite manifest, and retrieval filters for active versions only; failed staging data and previous versions remain stored but are not retrieved. The default directory and collection do not modify an existing database. LangChain handles only follow-up question rewriting and generation. SQLite stores browser identities and successful conversation turns.

Constraints: do not call real models, ingest production material, modify credentials, or delete the backup branch. Back up the existing untracked web interface to `/tmp` first; do not commit unrelated untracked files.

- [x] Ingestion: test page numbers, stable IDs, deduplication, failed updates, and file isolation; replace the chunker, vector store, and ingestion entry point; remove the previous embedding wrapper.
- [x] Conversation: adapt NodeWithScore, history-based rewriting, context limits, and citation validation; replace the previous LLM wrapper with LangChain.
- [x] API: implement SQLite ownership, minimal legacy requests, SSE token/[DONE] compatibility, timeouts, errors, cancellation, latency, and token usage.
- [x] Web interface: implement same-origin authentication, safe rendering, source cards, unvalidated streaming state, new conversations, and a mobile layout.
- [x] Verification: run the full pytest suite, browser checks, dependency compatibility checks, and script imports; add documentation and dependency locking; remove the previous implementation after citation checks and before committing.

Priority review areas: concurrent ingestion, publication failure, history writes during cancellation, expired cookies, malicious links and HTML, and legacy-database rollback. Real Google/OpenAI verification and backup/restore exercises are still required before production deployment.

Verification record: Python 3.12.11; 31 pytest tests passed; `pip check` passed; real LangChain/LlamaIndex client APIs were exercised for standard and streaming calls through `httpx.MockTransport`. Playwright desktop and mobile tests passed. An independent review found an edge case where a save thread could write history after the request timeout; two failing regressions were added, and deadline/cancellation checks now occur before commit. Citation-failure logs retain timing for completed stages. The Docker build could not be verified because fetching Docker Hub metadata for the base image timed out. No real model or Drive calls were made.

Final regression additions: timing out while acquiring a conversation lock does not leave the conversation busy; Uvicorn/uvloop uses relative remaining durations to avoid differences between clock bases; corresponding regression tests were added.
