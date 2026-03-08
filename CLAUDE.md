# ReadMyBook Backend

FastAPI backend for an AI-powered document processing and RAG platform. Converts PDFs into interactive digital books with AI-assisted Q&A, word explanations, and social features.

## Quick Start

```bash
# API server
python main.py  # Uvicorn on port 8000

# PDF processing worker (queue-driven)
python worker.py

# Mathpix fallback worker
python mathpix_worker.py
```

Environment: Python 3.11, `.env.dev` / `.env.prod` loaded via `ENV_FILE` env var (defaults to `.env.dev`).

## Project Structure

```
app.py              # FastAPI app, router registration, lifespan
main.py             # Uvicorn entrypoint
middleware.py        # JWT auth, document access, balance verification
core/db_client.py   # SQLAlchemy engines (API pool + Worker pool)

# Domain modules — each follows: data/ (model, schema, repository), route/, service/
users/  documents/  bookmarks/  highlights/  word_explanations/
posts/  follows/  connections/  notifications/  billing/  dashboard/

ai_engine/           # LangGraph-based AI pipeline
  graph/askGraph/    # RAG chat graph (query_refiner -> rag_retrieval -> chat_agent)
  graph/wordGraph/   # Word explanation graph
  prompts.py         # All system prompts
  data/qdrantRepository.py  # Qdrant vector DB client
  service/agentService.py   # AgentService orchestrates graph calls
  service/textEmbeddingService.py  # Dense + BM25 sparse embeddings

worker.py            # Azure Queue worker: PDF batching, marker-pdf conversion, merge, enrichment
worker_v2/           # Alternative converter with image extraction
mathpix_worker/      # Mathpix OCR fallback processor
shared/redis.py      # RedisService singleton
shared/azure_blob.py # Azure Blob Storage helpers
```

## Conventions

- **Module pattern**: `module/data/model.py` (SQLAlchemy), `module/data/schema.py` (Pydantic), `module/data/repository.py`, `module/service/`, `module/route/`
- **IDs**: ULID-based with prefixes (`doc_`, `og_doc_`, `wexp_`, `batch_`, etc.)
- **Auth**: JWT Bearer via `middleware.verify_access_token`; user context cached in Redis (24h TTL)
- **Document access**: `middleware.document_access_validator` checks Redis first, DB fallback, caches 5 days
- **AI endpoints**: Both sync and SSE streaming variants (`/ask` and `/ask/stream`, `/explain-word` and `/explain-word/stream`)
- **SSE format**: `event: {type}\ndata: {json}\n\n` via `ai_engine/graph/stream_utils.sse_event()`
- **Background work**: `threading.Thread(daemon=True)` for eval, billing deduction, word explanation persistence
- **DB sessions**: API uses `get_db()` (pool_size=5), workers use `get_worker_db()` (pool_size=1)
- **Redis keys**: `user:context:{id}`, `user:{id}:document_access`, `user:{id}:og_document_mapping`, `doc:{id}:meta`, `doc:{id}:images`, `billing:balance:{id}`
- **Billing**: Prepaid balance model; `verify_balance` middleware on paid endpoints; costs deducted after LLM calls
- **DB migrations**: `Base.metadata.create_all()` at startup; manual SQL in `migrations/`

## Key Dependencies

LangChain + LangGraph, OpenAI (GPT-4.1, GPT-4.1-mini, text-embedding-3-large), Qdrant, PostgreSQL + SQLAlchemy, Redis, Azure Blob/Queue/Key Vault, marker-pdf, Mathpix, Razorpay, FastEmbed (BM25)

## Claude Code Rules

### Auto-update memory
When you make code changes that affect information documented in the persistent memory files (`~/.claude/projects/.../memory/`), **proactively update the corresponding memory file** to keep it accurate. This includes changes to:
- Database models, schemas, or repository methods → update `documents.md` or relevant module memory
- Auth flow, middleware, or user model → update `authentication.md`
- AI engine graphs, nodes, prompts, config, or streaming → update `ai-engine.md`
- Project structure, Redis keys, worker pipeline, or billing → update `architecture.md`
- Any key fact (tech stack, patterns, conventions) → update `MEMORY.md`

Do not wait to be asked — update memory as part of completing the task.

### Frontend API change prompt
When you modify any **API request/response model** (Pydantic schemas in `data/schema.py` files) or **route signatures** (in `route/*_route.py` files), output a **copyable prompt block** in the chat summarizing the changes for the frontend team. Format:

```
## API Change: [METHOD] [path]

### What changed
- [Added/Removed/Renamed] field `field_name` (type) in [Request/Response] model

### Updated model shape
[Full Pydantic model with all fields and types]
```

This block should be easy to copy and paste into a frontend Claude Code session or share with the frontend developer.
