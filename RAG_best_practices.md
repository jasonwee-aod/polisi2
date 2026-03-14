# RAG Best Practices — What We Haven't Implemented Yet

Audit of industry best practices for Retrieval-Augmented Generation systems, filtered to what Polisi does **not** currently do. Each item includes the problem it solves, implementation difficulty against our current stack (Postgres/pgvector, FastAPI, OpenAI embeddings, Claude), and a priority recommendation.

**Current stack:** Postgres (Supabase) with pgvector + tsvector, OpenAI `text-embedding-3-large` (3072-dim), Claude 3.5 Sonnet, FastAPI, Next.js frontend.

**Key industry stats:** 42% of AI projects failed in 2025 (2.5x increase from 2024). 78% of enterprises struggle to trust underlying data. Once users decide a system can't be trusted, they don't keep checking back. (Sources: HumanSignal, Analytics Vidhya)

---

## 1. Retrieval Quality

### 1.1 Cross-Encoder Reranking

**What:** After hybrid retrieval returns top-N candidates (we currently return 5), run a cross-encoder model that scores each (query, chunk) pair jointly. Cross-encoders are far more accurate than bi-encoders (embeddings) because they see both texts simultaneously, but too slow to run over the full corpus — hence the two-stage approach.

**Problem it solves:** Our RRF ranking is good but imperfect. A chunk can rank high because of keyword overlap (FTS) or embedding proximity without actually answering the question. Cross-encoder reranking catches these false positives before they dilute the LLM's context window.

**Measured impact:** 15-30% improvement in retrieval precision vs. embedding-based retrieval alone (Pinecone benchmarks).

**Options:**
- `ms-marco-MiniLM-L-12-v2` — free, runs locally, ~50ms for 20 candidates
- Cohere Rerank API — hosted, 100+ language support, ~$1/1000 queries, very accurate
- BGE Reranker — open-source, strong multilingual performance
- Claude Haiku as reranker — send each chunk with the question, ask "rate relevance 1-5", ~1s + cost

**Difficulty:** Low-Medium. Add a `Reranker` protocol to `retrieval.py`, call it between the SQL fetch and the return. No schema changes. The SQL function already over-fetches (4x `match_count`), so we'd just increase `retrieval_limit` and rerank down.

**Priority:** HIGH — single biggest quality improvement per unit of effort.

---

### 1.2 Query Expansion / Reformulation

**What:** Before retrieval, generate additional query variants to catch documents the original phrasing would miss. Two main approaches:

- **HyDE (Hypothetical Document Embeddings):** Ask the LLM to generate a hypothetical answer to the question, then embed *that* instead of the raw question. The hypothesis is closer in embedding space to the actual document than the question is.
- **Multi-query:** Generate 2-3 reformulations of the question (synonyms, Malay↔English translation, more specific phrasing), run retrieval for each, merge results.

**Problem it solves:** User questions are often short, vague, or in the wrong language for the document. "What help is there for students?" won't match a document titled "Skim Bantuan Pelajar IPT" well in embedding space, but a reformulated Malay query would.

**Difficulty:** Medium. Requires an extra LLM call (Haiku for cost). For HyDE, embed the hypothesis instead of the question in `PostgresRetriever.retrieve()`. For multi-query, run multiple retrieval calls and merge with RRF. Both are additive — no schema changes.

**Priority:** HIGH for a bilingual corpus like ours — query-document language mismatch is likely our #1 retrieval failure mode.

---

### 1.3 Conversation-Aware Retrieval

**What:** Use the last 3-5 conversation turns to reformulate the current query before retrieval. When a user asks "What about the eligibility criteria?", the system should understand "the" refers to the policy discussed in prior turns.

**Problem it solves:** Our retrieval is stateless — each query is independent. Follow-up questions with pronouns, anaphora, or implicit context retrieve irrelevant documents.

**Difficulty:** Medium. The conversation history is already in the DB (`messages` table). The change is to load the last N messages in `generate_reply()`, prepend them to a query-reformulation prompt (Haiku call), and use the reformulated query for retrieval. No schema changes.

**Priority:** HIGH — this is a basic conversational expectation that we don't meet.

---

### 1.4 Contextual Retrieval (Anthropic's Approach)

**What:** At indexing time, prepend a short context sentence to each chunk before embedding it. For example, a chunk about "Section 3.2: Eligibility" from "Surat Siaran KPM Bil. 5/2025" would be stored as: "This excerpt is from Surat Siaran KPM Bil. 5/2025, regarding education subsidy eligibility criteria. [original chunk text]". The embedding then captures the document-level context, not just the chunk's local text.

**Problem it solves:** Chunks lose their parent document context after splitting. A chunk that says "The applicant must be below 25 years old" is meaningless without knowing which programme this refers to.

**Measured impact (Anthropic benchmarks):** 35% reduction in retrieval failure with contextual retrieval alone; 49% with BM25 added; **67% with reranking on top**. Cost: ~$1.02 per million document tokens using prompt caching. The prompt used: *"Please give a short succinct context to situate this chunk within the overall document for the purposes of improving search retrieval of the chunk."*

**Difficulty:** Medium. Requires changes to the indexing pipeline (`chunking.py`): for each chunk, call Claude Haiku with the full document + chunk, ask for a 1-2 sentence context prefix. Then embed the prefixed version. Increases indexing cost (one Haiku call per chunk) but dramatically improves retrieval. Existing chunks would need re-indexing.

**Priority:** HIGH — proven technique with large measured gains, and we have the infrastructure (Claude API) already.

---

### 1.5 Metadata-Boosted Ranking

**What:** Incorporate document metadata (recency, authority, document type) as ranking signals alongside similarity. A recent pekeliling should rank higher than a 5-year-old one on the same topic. A primary legal source (Act of Parliament) should rank higher than a news summary.

**Problem it solves:** Our ranking treats all documents equally. A 2019 circular and a 2025 circular about the same topic may rank similarly by embeddings, but the user almost always wants the current one.

**Difficulty:** Low. Add a post-retrieval scoring step that multiplies RRF score by recency/authority weights. Could also be done in SQL by adding a `published_at` decay factor in `hybrid_match_documents()`. No new infrastructure.

**Priority:** MEDIUM — particularly important for legal/policy documents where superseded content is dangerous to cite.

---

## 2. Chunking & Indexing

### 2.1 Semantic Chunking

**What:** Instead of splitting at fixed character counts (our current 1400-char target), split at semantic boundaries — paragraph breaks, section headings, topic shifts. Use embedding similarity between consecutive sentences to detect topic changes.

**Problem it solves:** Fixed-size chunking can split mid-sentence, mid-table, or mid-argument. This creates chunks that are incomplete or misleading when retrieved.

**Measured impact:** Semantic chunking achieves 91-92% recall, +9% over simple fixed-size methods (Firecrawl/Weaviate benchmarks). However, page-level chunking won NVIDIA benchmarks (0.648 accuracy, lowest variance) for structured documents — which is what most of our policy PDFs are.

**Key insight from research:** "Overlap provided no measurable benefit and only increased indexing cost." Our 250-char overlap may be wasted computation.

**Difficulty:** Medium. Replace the `build_chunks()` function in `chunking.py`. Libraries like `langchain.text_splitter.SemanticChunker` do this, or we can implement a simple version: compute sentence embeddings, split where cosine similarity between adjacent sentences drops below a threshold.

**Priority:** MEDIUM — our current chunking with overlap partially mitigates this, but policy documents with numbered sections would benefit significantly. Consider testing page-level chunking for PDFs first (simpler, strong benchmarks).

---

### 2.2 Parent Document Retrieval

**What:** Store chunks for retrieval but retrieve the parent document (or a larger window) for LLM context. Small chunks (200-400 chars) are better for precise semantic matching; larger contexts (2000+ chars) are better for LLM comprehension. Use small chunks as retrieval keys but expand to the surrounding context when building the prompt.

**Problem it solves:** Retrieval-optimal chunk size ≠ comprehension-optimal chunk size. A small chunk matches precisely but the LLM sees too little context. A large chunk provides context but may not match the query well.

**Difficulty:** Medium. Requires storing both small chunks (for embedding) and large parent chunks (for context), linked by `chunk_index`. At retrieval time, look up the parent chunk. Schema change: add a `parent_chunk_text` column or a separate table.

**Priority:** MEDIUM — would improve answer quality for complex policy explanations.

---

### 2.3 Proposition-Based Chunking

**What:** Instead of splitting documents into text chunks, decompose them into atomic propositions (single facts). "The programme allocates RM500 million for 2025 and targets 200,000 beneficiaries" becomes two propositions. Each proposition is embedded and retrieved independently.

**Problem it solves:** Multi-fact chunks dilute retrieval — embedding a paragraph with 5 facts means the embedding is an average that matches none of the 5 facts precisely.

**Difficulty:** High. Requires an LLM call per chunk to decompose into propositions, a new storage schema, and significant re-indexing cost. Libraries like `llama-index` have `SentenceWindowNodeParser` and `SemanticSplitterNodeParser` for this.

**Priority:** LOW for now — high cost, moderate gain. Revisit after easier wins are captured.

---

### 2.4 Table-Aware Chunking

**What:** Detect tables in documents and keep them intact as single chunks rather than splitting them across chunk boundaries. Serialise tables as markdown or structured text with column headers repeated.

**Problem it solves:** Budget allocation tables, eligibility criteria tables, and comparison tables are common in Malaysian policy documents. Splitting them across chunks destroys their meaning.

**Difficulty:** Low-Medium. Our parsers already detect `block_type="table"`. The change is in `build_chunks()`: if a block is a table, emit it as its own chunk regardless of size, with the section heading as context.

**Priority:** MEDIUM-HIGH — tables are high-value content in policy documents and currently handled poorly.

---

## 3. Context Window Management

### 3.1 Lost-in-the-Middle Mitigation

**What:** Research shows LLMs perform worst on information placed in the middle of long contexts (the "lost in the middle" phenomenon, Liu et al. 2023). Place the most relevant chunks at the beginning and end of the context, with less relevant ones in the middle.

**Measured impact:** Performance degrades by 30%+ when critical info is in the middle of context. Claude 2.1 accuracy dropped to 27% for middle-positioned information (Stanford). The attention curve is U-shaped due to Rotary Position Embedding (RoPE) decay.

**Problem it solves:** If we pass 5 chunks in descending similarity order, chunks 2-4 may be effectively ignored by the LLM even though they contain useful information.

**Difficulty:** Very Low. Reorder chunks in `build_prompt()` / `build_skill_prompt()` before inserting into the user message. Put #1 first, #2 last, #3-4 in the middle. No infrastructure changes.

**Priority:** MEDIUM — easy to implement, measurable quality improvement for multi-chunk answers.

---

### 3.2 Context Deduplication

**What:** Before passing chunks to the LLM, remove near-duplicates. Two chunks from the same document with high text overlap (due to our 250-char overlap window, or because the same content appears in multiple scraped pages) waste context space.

**Problem it solves:** Redundant chunks consume limited context budget without adding information. In the worst case, 3 of 5 retrieved chunks could be from the same document's overlapping regions.

**Difficulty:** Very Low. After retrieval, deduplicate by (document_id, chunk_index ± 1) or by text similarity. A few lines in `generate_reply()`.

**Priority:** MEDIUM — cheap fix that could immediately improve context diversity.

---

### 3.3 Adaptive Context Window

**What:** Instead of always passing 3 or 5 chunks, vary the number based on query complexity and chunk relevance. A simple factual question needs 1-2 chunks; a policy comparison needs 5+. Also consider the similarity drop-off: if chunk #3 has 0.85 similarity and chunk #4 has 0.45, stop at #3.

**Problem it solves:** Fixed limits either waste context (simple queries) or underprovide (complex queries).

**Difficulty:** Low. Add a relevance threshold cutoff (e.g., drop chunks below 80% of the top chunk's similarity) and a complexity heuristic (query length, number of entities).

**Priority:** LOW-MEDIUM — nice optimisation but not a critical gap.

---

## 4. Evaluation & Monitoring

### 4.1 RAG Evaluation Framework (RAGAS)

**What:** Implement automated evaluation metrics for RAG quality. The RAGAS framework (Retrieval Augmented Generation Assessment) measures:

- **Faithfulness:** Does the answer only contain claims supported by the retrieved context? (Detects hallucination)
- **Answer Relevancy:** Does the answer actually address the question?
- **Context Precision:** Are the retrieved chunks relevant to the question?
- **Context Recall:** Did retrieval capture all the information needed to answer?

**Problem it solves:** We have zero visibility into answer quality. We don't know our hallucination rate, how often retrieval fails, or whether changes improve or degrade the system.

**Difficulty:** Medium. The `ragas` Python library can run evaluations against a test dataset. We need: (1) a golden dataset of 50-100 question-answer-context triples, (2) a scheduled evaluation job, (3) a dashboard to track scores over time. No production infrastructure changes — this runs offline.

**Priority:** HIGH — you can't improve what you can't measure.

---

### 4.2 Query & Response Logging

**What:** Log every query, the retrieved chunks (with similarity scores), the generated response, and latency metrics to a structured store. This enables debugging specific failures, measuring retrieval quality at scale, and identifying common query patterns.

**Problem it solves:** When a user reports a bad answer, we have no way to diagnose whether it was a retrieval failure (wrong chunks) or a generation failure (right chunks, wrong answer).

**Difficulty:** Low. Add a `query_logs` table or append to a JSONL file. Log in `ChatService.generate_reply()` after generation. Fields: user_id, question, skill, retrieved_chunk_ids, similarity_scores, response_kind, latency_ms, token_usage.

**Priority:** HIGH — essential for debugging and improvement. Should be one of the first things built.

---

### 4.3 User Feedback Collection

**What:** Add thumbs-up/thumbs-down buttons on each assistant message. Store feedback linked to the message, including the retrieved chunks and query. Use this to build a golden evaluation dataset and identify systematic retrieval failures.

**Problem it solves:** Automated metrics are proxies; user feedback is ground truth. It also identifies which topics/agencies have the worst coverage.

**Difficulty:** Low. Frontend: two buttons per assistant message. Backend: `POST /api/messages/{id}/feedback` endpoint writing to a `message_feedback` table. No LLM changes.

**Priority:** MEDIUM-HIGH — the feedback data compounds in value over time.

---

## 5. Prompt Engineering

### 5.1 Few-Shot Examples in System Prompts

**What:** Include 1-2 example question-answer pairs in the system prompt to demonstrate the expected citation format, tone, and structure. This is especially valuable for skills where the output format is complex (e.g., `parliament_question`, `policy_brief`).

**Problem it solves:** Despite detailed instructions, the LLM sometimes deviates from the expected format. Few-shot examples anchor the output format more reliably than instructions alone.

**Difficulty:** Very Low. Add example blocks to the `system_prompt_en` / `system_prompt_ms` fields in `skills.py`. No code changes beyond the prompt text.

**Priority:** MEDIUM — high-value for skills with strict format requirements.

---

### 5.2 Chain-of-Thought for Complex Queries

**What:** For complex queries (comparisons, multi-step reasoning, budget analysis), instruct the LLM to reason step-by-step before producing the final answer. The reasoning can be hidden from the user or shown as a "thinking" section.

**Problem it solves:** Complex policy questions require synthesizing information from multiple chunks. Without CoT, the LLM may jump to conclusions or miss connections between documents.

**Difficulty:** Very Low. Add "Think step-by-step before answering" to the system prompt for relevant skills (budget_analyst, state_comparator, fact_checker). Optionally parse out the reasoning.

**Priority:** LOW-MEDIUM — mainly benefits the complex analytical skills.

---

### 5.3 Post-Generation Citation Verification

**What:** After the LLM generates a response, programmatically verify that every `[n]` citation actually maps to a retrieved chunk and that the cited claim is supported by that chunk's text. Flag or remove unsupported citations.

**Problem it solves:** Research shows a strong negative correlation (r=-0.72) between citation rate and hallucination rate — but only if citations are real. "Citation hallucination" (citing a source that doesn't support the claim) is one of the 10 hidden production RAG failure modes.

**Difficulty:** Medium. Requires parsing the response for `[n]` markers, extracting the claim sentence, and checking it against the cited chunk (via embedding similarity or an LLM call). The `FACTUM` framework (arXiv:2601.05866) provides a reference implementation.

**Priority:** MEDIUM — important for a government policy tool where citing a circular that doesn't actually say what's claimed would erode trust.

---

### 5.4 Prompt Injection Detection

**What:** Before passing user input to the LLM, scan for common prompt injection patterns: "ignore previous instructions", "you are now", system prompt extraction attempts. Either refuse the request or sanitise the input.

**Problem it solves:** A malicious user could manipulate the chatbot into ignoring its grounding instructions, generating harmful content, or leaking system prompts. This is a real attack vector in production RAG systems.

**Difficulty:** Low-Medium. Add a lightweight classifier (regex-based for common patterns, or a Haiku call for sophisticated detection) as a pre-processing step in `generate_reply()`. The `rebuff` library provides a ready-made solution.

**Priority:** MEDIUM — important for a public-facing government tool. Low-severity now with rate limiting in place, but should be addressed before wide deployment.

---

## 6. Production Robustness

### 6.1 Embedding Cache

**What:** Cache query embeddings to avoid re-computing them for repeated or similar queries. At minimum, cache the exact query→embedding mapping; ideally, cache (query_hash → embedding) in Redis or a Postgres table.

**Problem it solves:** Every query currently makes a round-trip to OpenAI's embedding API (~100-300ms, $0.13/M tokens). Repeated queries (common in testing, demos, or popular topics) waste time and money.

**Difficulty:** Low. Add a `query_embeddings` cache table or use Python's `lru_cache` with a hash key. The embedding client (`OpenAIEmbeddingClient`) is the insertion point.

**Priority:** MEDIUM — reduces latency and cost, especially during development and demos.

---

### 6.2 Structured Logging & Observability

**What:** Replace print statements with structured JSON logging (Python `structlog` or `logging` with JSON formatter). Include: request_id, user_id, latency_ms, retrieval_count, top_similarity, skill_used, token_cost, error_type. Ship logs to a dashboard (Grafana, Datadog, or even a simple Supabase table).

**Problem it solves:** We can't diagnose production issues, track costs, or identify degradation trends without structured observability.

**Tool options:**
| Tool | Type | Strengths |
|------|------|-----------|
| Langfuse | Open-source, self-hostable | `@observe()` decorator, component-level evals, framework-agnostic |
| LangSmith | Commercial (LangChain) | Tight LangChain integration, online+offline evals, human annotation |
| Evidently AI | Open-source + cloud | 100+ built-in eval checks, synthetic test data generation |

**Difficulty:** Low-Medium. Langfuse setup is a few lines of code; the discipline of ongoing monitoring is the hard part.

**Priority:** MEDIUM-HIGH — becomes critical as user base grows.

---

### 6.3 Graceful Degradation Tiers

**What:** When components fail (OpenAI embedding API down, Anthropic rate limited, Postgres slow), degrade gracefully through defined tiers rather than returning a generic error:

1. **Full service:** Hybrid retrieval + Claude generation
2. **Embedding fallback:** FTS-only retrieval (no vector search) + Claude generation
3. **LLM fallback:** Retrieval only, return raw document excerpts without LLM synthesis
4. **Cache fallback:** Return cached responses for similar queries
5. **Maintenance mode:** Static message explaining the outage

**Problem it solves:** Any single point of failure (OpenAI, Anthropic, Postgres) currently breaks the entire service.

**Difficulty:** Medium. Requires try/catch chains in `generate_reply()` with progressive fallback logic. FTS-only retrieval needs a separate SQL function. Cache fallback needs a response cache.

**Priority:** MEDIUM — important for production reliability.

---

### 6.4 Connection Pooling

**What:** Our current code opens a new `psycopg.connect()` for every database operation (retrieval, conversation persistence, rate limiting). Use a connection pool (`psycopg_pool.ConnectionPool`) to reuse connections.

**Problem it solves:** Connection setup overhead (~50-100ms per connection to Supabase) adds unnecessary latency. Under concurrent load, we'd exhaust Supabase's connection limit.

**Difficulty:** Low. Replace `psycopg.connect(db_url)` calls with a shared pool. The `psycopg_pool` package supports this natively. Initialize in `dependencies.py`, pass to retriever and repository.

**Priority:** MEDIUM-HIGH — essential before scaling beyond a few concurrent users.

---

## 7. Multilingual-Specific

### 7.1 Cross-Lingual Query-Document Matching

**What:** Our corpus is mixed BM/EN but `text-embedding-3-large` is English-dominant. A Malay query may poorly match an English document and vice versa. Mitigations:

- **Query translation:** Translate the query to both BM and EN, embed both, retrieve from both, merge results
- **Multilingual embedding model:** Switch to a model specifically trained for Malay (e.g., `paraphrase-multilingual-MiniLM-L12-v2` from Sentence Transformers, or Cohere's `embed-multilingual-v3.0`)
- **Bilingual tsvector:** Add a second tsvector column with translated text

**Problem it solves:** Language mismatch is likely our #1 retrieval failure. A user asking in BM about a policy documented in English (or vice versa) gets poor results.

**Difficulty:** Medium. Query translation is the easiest (one Haiku call). Switching embedding models requires re-indexing the entire corpus. Bilingual tsvector requires indexing translated text.

**Priority:** HIGH — this is a core product issue for a bilingual Malaysian tool.

---

### 7.2 Language-Aware Chunking

**What:** Detect the language of each document/block during parsing and tag it in metadata. Use this to: (1) apply language-appropriate text processing, (2) boost same-language matches in retrieval, (3) inform the LLM which language the source is in.

**Problem it solves:** Our tsvector uses `'simple'` config (no stemming) because Postgres has no Malay stemmer. Language detection would allow using the `'english'` config for English documents (with stemming) while keeping `'simple'` for Malay.

**Difficulty:** Low. Add `langdetect` or `lingua` to the indexer, tag each chunk with its detected language. Adjust tsvector config per language.

**Priority:** LOW-MEDIUM — marginal improvement over `'simple'` config.

---

## 8. Advanced Architectures (Future)

### 8.1 Corrective RAG (CRAG)

**What:** After initial retrieval, evaluate whether the retrieved documents actually answer the question. If confidence is low, trigger corrective actions: query reformulation, web search, or explicit "I don't have enough information" response. Published by Shi et al. (2024).

**Problem it solves:** Our current system always generates an answer even when retrieval fails silently (high similarity score but irrelevant content). CRAG adds a self-check step.

**Difficulty:** Medium-High. Requires a relevance evaluator (lightweight LLM call) between retrieval and generation. If evaluation fails, triggers alternative retrieval strategies.

**Priority:** MEDIUM — becomes important as the corpus grows and retrieval noise increases.

---

### 8.2 Self-RAG

**What:** Train or prompt the LLM to generate special tokens that indicate when it needs more information, when it's uncertain, and when its response is grounded vs. speculative. Published by Asai et al. (2023).

**Problem it solves:** The LLM generates confidently even when it's hallucinating. Self-RAG makes the model self-aware of its grounding.

**Difficulty:** High. Requires fine-tuning or very careful prompting. Not practical with a hosted API model without extensive prompt engineering.

**Priority:** LOW — the prompting approach (explicit uncertainty markers) is achievable; the full Self-RAG architecture is not.

---

### 8.3 Graph RAG (Microsoft)

**What:** Build a knowledge graph from the corpus (entities + relationships), then use community detection to create hierarchical summaries. At query time, traverse the graph to find relevant entity clusters and use their summaries as context. Published by Microsoft Research (2024).

**Problem it solves:** Global questions ("What are Malaysia's education policies?") that no single chunk can answer. Graph RAG synthesizes across the entire corpus at indexing time.

**Difficulty:** High. Requires entity extraction, graph construction, community detection (Leiden algorithm), and summary generation during indexing. Significant infrastructure addition.

**Priority:** LOW — high effort, mainly benefits broad exploratory queries. Already noted in `infrastructure.md` as a future phase.

---

## 9. Known RAG Failure Modes (What To Test Against)

The following failure taxonomy (Gao et al.) should guide our evaluation dataset:

1. **Missing content** — the corpus simply doesn't contain the answer (scraper coverage gap)
2. **Missed top-ranked** — the right document exists but ranked too low (retrieval quality)
3. **Not in context** — retrieved but truncated or excluded from the LLM prompt (context management)
4. **Not extracted** — LLM fails to extract the answer from noisy context (prompt engineering)
5. **Wrong format** — answer is correct but structured incorrectly (skill prompt issues)
6. **Incorrect specificity** — answer is too broad or too narrow for the question
7. **Incomplete answer** — partial coverage of a multi-part question

Additional production-specific failures to watch for:
- **Temporal staleness** — outdated circulars returned confidently (metadata-boosted ranking would fix)
- **Cross-document contradictions** — conflicting sources not flagged (especially superseded pekeliling)
- **Embedding drift** — if OpenAI updates `text-embedding-3-large`, our stored embeddings become misaligned (re-indexing needed)

---

## Priority Summary

| Priority | Practice | Difficulty | Section |
|----------|----------|------------|---------|
| **HIGH** | Cross-encoder reranking | Low-Medium | 1.1 |
| **HIGH** | Query expansion / HyDE | Medium | 1.2 |
| **HIGH** | Conversation-aware retrieval | Medium | 1.3 |
| **HIGH** | Contextual retrieval (indexing) | Medium | 1.4 |
| **HIGH** | RAGAS evaluation framework | Medium | 4.1 |
| **HIGH** | Query & response logging | Low | 4.2 |
| **HIGH** | Cross-lingual query matching | Medium | 7.1 |
| **MED-HIGH** | User feedback collection | Low | 4.3 |
| **MED-HIGH** | Table-aware chunking | Low-Medium | 2.4 |
| **MED-HIGH** | Structured logging | Low-Medium | 6.2 |
| **MED-HIGH** | Connection pooling | Low | 6.4 |
| **MEDIUM** | Metadata-boosted ranking | Low | 1.5 |
| **MEDIUM** | Semantic chunking | Medium | 2.1 |
| **MEDIUM** | Parent document retrieval | Medium | 2.2 |
| **MEDIUM** | Lost-in-the-middle mitigation | Very Low | 3.1 |
| **MEDIUM** | Context deduplication | Very Low | 3.2 |
| **MEDIUM** | Few-shot examples in prompts | Very Low | 5.1 |
| **MEDIUM** | Citation verification | Medium | 5.3 |
| **MEDIUM** | Prompt injection detection | Low-Medium | 5.4 |
| **MEDIUM** | Embedding cache | Low | 6.1 |
| **MEDIUM** | Graceful degradation tiers | Medium | 6.3 |
| **LOW-MED** | Adaptive context window | Low | 3.3 |
| **LOW-MED** | Chain-of-thought prompts | Very Low | 5.2 |
| **LOW-MED** | Language-aware chunking | Low | 7.2 |
| **LOW** | Proposition-based chunking | High | 2.3 |
| **LOW** | Corrective RAG | Medium-High | 8.1 |
| **LOW** | Self-RAG | High | 8.2 |
| **LOW** | Graph RAG | High | 8.3 |

---

## Recommended Implementation Order

**Wave 1 — Quick wins (1-2 days each):**
- Query & response logging (4.2)
- Context deduplication (3.2)
- Lost-in-the-middle reordering (3.1)
- Few-shot examples in skill prompts (5.1)
- Connection pooling (6.4)

**Wave 2 — Core quality (3-5 days each):**
- Cross-encoder reranking (1.1)
- Conversation-aware retrieval (1.3)
- Cross-lingual query matching (7.1)
- User feedback collection (4.3)
- Table-aware chunking (2.4)

**Wave 3 — Deep improvements (1-2 weeks each):**
- Contextual retrieval at indexing time (1.4)
- Query expansion / HyDE (1.2)
- RAGAS evaluation framework (4.1)
- Semantic chunking (2.1)
- Structured logging & observability (6.2)

**Wave 4 — Advanced (future):**
- Everything in section 8 (CRAG, Self-RAG, Graph RAG)
- Parent document retrieval (2.2)
- Graceful degradation tiers (6.3)
