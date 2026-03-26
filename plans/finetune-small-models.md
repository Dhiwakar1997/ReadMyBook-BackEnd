# Plan: Replace Expensive LLM Calls with Fine-tuned Small Models

## Goal
Reduce cost and latency by replacing general-purpose LLM calls with fine-tuned small models trained on ReadMyBook's own production data. Three targets identified, ordered by impact and ease of implementation.

---

## Phase 1: Data Collection Pipeline (Prerequisite for all fine-tuning)

### Step 1.1 — Add a Training Data Logger to the Ask Graph

**What**: Create a logging mechanism that persists full input/output pairs for each LLM-calling node in the ask graph.

**Files to create/modify**:
- `ai_engine/data/training_data_model.py` — SQLAlchemy model for training samples
- `ai_engine/data/training_data_repository.py` — Repository for CRUD operations
- `ai_engine/graph/askGraph/ask_nodes.py` — Add logging after each node execution

**Schema**:
```python
class TrainingDataSample(Base):
    __tablename__ = "training_data_samples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    node_name = Column(String, indexed=True)          # "query_refiner", "chat_agent", "category_classifier"
    input_data = Column(JSON)                          # Full input to the node
    output_data = Column(JSON)                         # Full output from the node
    document_id = Column(String, indexed=True)
    category = Column(String, nullable=True)
    eval_faithfulness = Column(Float, nullable=True)   # Backfilled from EvalRecord
    eval_relevancy = Column(Float, nullable=True)      # Backfilled from EvalRecord
    is_approved = Column(Boolean, default=False)       # Manual review flag
    created_at = Column(DateTime, default=datetime.utcnow)
```

**Implementation**:
1. Create model and repository
2. In `ask_nodes.py`, after each node returns, log `(input_state, output_state)` in a background thread (same pattern as eval/billing)
3. After eval runs, backfill `eval_faithfulness` and `eval_relevancy` on the corresponding training samples
4. Add a config flag `ENABLE_TRAINING_DATA_LOGGING=true` (env var, default off)

### Step 1.2 — Add Training Data Export Script

**What**: Script to export high-quality samples as JSONL for OpenAI fine-tuning API.

**File to create**:
- `scripts/export_training_data.py`

**Logic**:
1. Query `training_data_samples` WHERE `eval_faithfulness > 0.8 AND eval_relevancy > 0.8`
2. Group by `node_name`
3. Format into OpenAI fine-tuning JSONL:
   ```json
   {"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
   ```
4. Output separate files: `query_refiner_train.jsonl`, `chat_agent_train.jsonl`, `category_classifier_train.jsonl`

### Step 1.3 — Let It Collect Data

- Deploy with `ENABLE_TRAINING_DATA_LOGGING=true`
- Wait for sufficient samples:
  - Query Refiner: ~500-1000 samples minimum
  - Chat Agent per category: ~200-500 samples per category
  - Category Classifier: ~300-500 samples
- Monitor via a simple SQL query: `SELECT node_name, COUNT(*) FROM training_data_samples GROUP BY node_name`

---

## Phase 2: Fine-tune Query Refiner (Highest ROI)

### Why First
- Hit on every single request (100% traffic)
- Well-defined structured output (`QueryRefinerResponse`)
- Low risk — bad refinement still passes to chat_agent which has original query
- Currently uses GPT-4.1-mini — can potentially drop to GPT-4.1-nano or a self-hosted model

### Step 2.1 — Prepare Training Data

**Input format** (from logged data):
```json
{
  "messages": [
    {"role": "system", "content": "<QueryRefinerSystemPrompt>"},
    {"role": "user", "content": "Chat history: [...]\n\nUser query: <raw query>"},
    {"role": "assistant", "content": "{\"refined_query\": \"...\", \"user_query_language\": \"...\", \"chat_summary\": \"...\", \"is_followup\": true, \"requires_deep_analysis\": false, \"is_unclear\": false}"}
  ]
}
```

**Quality filters**:
- Exclude samples where downstream `is_refusal=True` (query led to refusal)
- Exclude samples where `is_unclear=True` (edge cases, keep only a small % for balance)
- Include samples where the refined query led to high eval scores

### Step 2.2 — Fine-tune via OpenAI API

```bash
# Upload training file
openai api files.create -f query_refiner_train.jsonl -p fine-tune

# Create fine-tuning job
openai api fine_tuning.jobs.create \
  -m gpt-4.1-mini \
  -t file-<id> \
  --suffix "rmb-query-refiner-v1"
```

**Hyperparameters**:
- Epochs: 3-4
- Learning rate multiplier: auto (let OpenAI decide)
- Batch size: auto

### Step 2.3 — Integrate Fine-tuned Model

**File to modify**: `ai_engine/graph/askGraph/ask_config.py`

```python
# Add fine-tuned model config
FINETUNED_REFINER_MODEL = os.getenv("FINETUNED_REFINER_MODEL", None)

# In model config:
refiner_model = FINETUNED_REFINER_MODEL or "openai:gpt-4.1-mini"
```

**File to modify**: `ai_engine/graph/askGraph/ask_nodes.py`
- Update `query_refiner` node to use the fine-tuned model ID when configured
- No other changes needed — structured output schema stays the same

### Step 2.4 — A/B Test

**Approach**: Route a percentage of traffic to the fine-tuned model.

**File to modify**: `ai_engine/graph/askGraph/ask_nodes.py`

```python
import random

AB_TEST_FINETUNED_RATIO = float(os.getenv("AB_TEST_FINETUNED_RATIO", "0.0"))

def query_refiner(state):
    use_finetuned = (
        FINETUNED_REFINER_MODEL
        and random.random() < AB_TEST_FINETUNED_RATIO
    )
    model = FINETUNED_REFINER_MODEL if use_finetuned else refiner_model
    # ... rest of node logic
    # Log which model was used in node_costs
```

**Evaluation**:
- Compare eval scores (faithfulness, relevancy) between base and fine-tuned
- Compare latency (from node_costs)
- Compare cost (from OpenAI callbacks)
- Target: Same or better eval scores, lower latency, lower cost

### Step 2.5 — Rollout

- If A/B test passes: set `FINETUNED_REFINER_MODEL` in production, set ratio to 1.0
- Monitor for 1 week via dashboard eval records
- Remove A/B test code once stable

---

## Phase 3: Fine-tune Category Classifier (Worker Pipeline)

### Why Second
- Eliminates an LLM call entirely from the document processing worker
- Classification is a well-understood ML task — doesn't need a large model
- Data is clean: `original_documents` table has `(text, category, sub_categories)` pairs

### Step 3.1 — Extract Training Data

**Script**: `scripts/export_category_data.py`

```python
# Query original_documents with non-null category
# For each, download first ~2000 tokens of markdown from Azure Blob
# Output: category_train.jsonl
# Format: {"text": "<first 2000 tokens>", "category": "technical_engineering", "sub_categories": ["programming", "algorithms"]}
```

### Step 3.2 — Choose Approach

**Option A: OpenAI Fine-tune (Simpler)**
- Fine-tune GPT-4.1-nano on classification task
- Input: document excerpt → Output: `{"category": "...", "sub_categories": [...]}`
- Cost: ~$0.001 per classification vs current LLM call

**Option B: Self-hosted Classifier (Cheaper long-term)**
- Fine-tune a small transformer (e.g., `distilbert-base-uncased` or `microsoft/deberta-v3-small`)
- Host on Azure Container Instance alongside worker
- Zero per-request cost after deployment
- Better for high-volume worker pipeline

**Recommendation**: Start with Option A for speed, migrate to Option B if volume justifies it.

### Step 3.3 — Integrate

**File to modify**: `worker/enrichmentHelper.py`

```python
FINETUNED_CLASSIFIER_MODEL = os.getenv("FINETUNED_CLASSIFIER_MODEL", None)

def classify_category(text):
    if FINETUNED_CLASSIFIER_MODEL:
        # Use fine-tuned model
        ...
    else:
        # Existing LLM call
        ...
```

### Step 3.4 — Validate

- Run classification on 100 existing documents with known categories
- Compare accuracy: fine-tuned vs current LLM
- Target: >90% exact match on category, >80% overlap on sub_categories

---

## Phase 4: Fine-tune Chapter Detector (Worker Pipeline)

### Why Third
- Eliminates another LLM call from worker pipeline
- Chapter detection from markdown headings is a pattern recognition task
- Lower priority since it runs once per document (not per user query)

### Step 4.1 — Extract Training Data

**Script**: `scripts/export_chapter_data.py`

- Query documents with known chapter structures
- For each: download markdown, pair with detected chapters from metadata JSON
- Format: `{"markdown_headings": [...], "chapters": [{"title": "...", "page": N, "content_index": N}]}`

### Step 4.2 — Fine-tune

- Fine-tune GPT-4.1-nano on heading-to-chapter mapping
- Or use a rule-based + small ML hybrid (many chapter detection patterns are regex-solvable)

### Step 4.3 — Integrate

**File to modify**: `worker/metadataHelper.py`
- Replace LLM call in chapter detection with fine-tuned model
- Keep LLM as fallback for edge cases

---

## Phase 5: Custom Embedding Model (Advanced, Optional)

### When to Consider
- Only after phases 1-4 are complete and you have significant query volume
- If retrieval quality (measured by faithfulness scores) is a bottleneck

### Approach
1. Collect `(query, positive_chunk, negative_chunk)` triplets from production:
   - Positive: chunks that appeared in high-scoring responses
   - Negative: chunks retrieved but not referenced (from `retrieval_chunks` vs `reference_contents`)
2. Fine-tune `sentence-transformers/all-MiniLM-L6-v2` or similar with contrastive loss
3. Self-host on Azure, replace OpenAI embedding calls
4. Re-index Qdrant collection with new embeddings

### Impact
- Eliminate embedding API cost entirely ($0.13/1M tokens currently)
- Potentially better retrieval for domain-specific vocabulary
- Lower dimensionality (384 vs 3072) = faster Qdrant search, less storage

---

## Cost & Timeline Estimates

| Phase | Effort | Data Needed | Expected Cost Reduction |
|-------|--------|-------------|------------------------|
| Phase 1: Data Pipeline | 2-3 days dev | N/A (infrastructure) | None (prerequisite) |
| Phase 2: Query Refiner | 1-2 days dev + 2-4 weeks data collection | 500-1000 samples | 30-50% on refiner calls |
| Phase 3: Category Classifier | 1-2 days dev | 300+ documents | ~100% (eliminate call) |
| Phase 4: Chapter Detector | 1 day dev | 200+ documents | ~100% (eliminate call) |
| Phase 5: Custom Embeddings | 1-2 weeks dev | 10K+ query-chunk pairs | ~100% (self-hosted) |

## Risk Mitigation

- **Always keep the original model as fallback** — env var toggle for instant rollback
- **A/B test before full rollout** — use existing eval pipeline to compare
- **Monitor eval scores post-deployment** — set alerts if faithfulness drops below threshold
- **Version your training data** — tag each fine-tune job with the data snapshot used
- **Retrain periodically** — as document types and user patterns evolve, retrain quarterly

## Files Summary

| File | Action |
|------|--------|
| `ai_engine/data/training_data_model.py` | Create — training sample SQLAlchemy model |
| `ai_engine/data/training_data_repository.py` | Create — repository for training data CRUD |
| `ai_engine/graph/askGraph/ask_nodes.py` | Modify — add training data logging, A/B test routing |
| `ai_engine/graph/askGraph/ask_config.py` | Modify — add fine-tuned model config vars |
| `worker/enrichmentHelper.py` | Modify — swap classifier to fine-tuned model |
| `worker/metadataHelper.py` | Modify — swap chapter detector to fine-tuned model |
| `scripts/export_training_data.py` | Create — export JSONL for fine-tuning |
| `scripts/export_category_data.py` | Create — export category classification data |
| `scripts/export_chapter_data.py` | Create — export chapter detection data |
| `app.py` | Modify — import new model for table creation |
