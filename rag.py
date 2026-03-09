"""
rag.py — Retrieval-Augmented Generation pipeline for Pressflow
==============================================================
Architecture:
  1. STORE   — Save every translation to PostgreSQL with vector embeddings
  2. RETRIEVE — Find similar past translations using cosine similarity (pgvector)
  3. GENERATE — Send to Claude with retrieved examples as context

This makes translations:
  - Consistent in terminology across articles
  - Author-aware (learns each writer's style)
  - Source-aware (Jacobin ≠ The Nation tone)
  - Better over time (more data = better retrieval)
"""

import os
import json
import time
import psycopg2
import psycopg2.extras
from anthropic import Anthropic

# ── Config ────────────────────────────────────────────────────────────────────

DATABASE_URL   = os.environ.get("DATABASE_URL", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
EMBED_MODEL    = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CLAUDE_MODEL   = "claude-haiku-4-5-20251001"  # 10x cheaper than Sonnet
TOP_K          = 5                          # How many similar examples to retrieve
MIN_SIMILARITY = 0.72                       # Cosine similarity threshold (0-1)

# ── Database setup ────────────────────────────────────────────────────────────

def get_conn():
    """Get a PostgreSQL connection."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set — add PostgreSQL on Railway")
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    """
    Create tables and enable pgvector extension.
    Called once on startup.
    """
    conn = get_conn()
    cur  = conn.cursor()

    # Enable pgvector
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Main translations table — create without embedding column first
    cur.execute("""
        CREATE TABLE IF NOT EXISTS translations (
            id          SERIAL PRIMARY KEY,
            source      TEXT,
            author      TEXT,
            url         TEXT,
            title_orig  TEXT,
            title_tr    TEXT,
            orig_para   TEXT NOT NULL,
            tr_para     TEXT NOT NULL,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (url, orig_para)
        );
    """)

    # Index for fast vector search
    cur.execute("""
        CREATE INDEX IF NOT EXISTS translations_embedding_idx
        ON translations
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
    """)

    # Terminology table — explicit overrides
    cur.execute("""
        CREATE TABLE IF NOT EXISTS terminology (
            id          SERIAL PRIMARY KEY,
            term_orig   TEXT NOT NULL UNIQUE,        -- "settler colonialism"
            term_tr     TEXT NOT NULL,               -- "yerleşimci sömürgeciliği"
            source      TEXT,                        -- optional: which source uses this
            created_at  TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # RAG retrieval metrics table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rag_metrics (
            id              SERIAL PRIMARY KEY,
            source          TEXT,
            author          TEXT,
            results_found   INTEGER DEFAULT 0,
            avg_similarity  FLOAT DEFAULT 0,
            max_similarity  FLOAT DEFAULT 0,
            hit             BOOLEAN DEFAULT FALSE,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    conn.commit()
    cur.close()
    conn.close()

    # Fix schema in a SEPARATE connection (avoids aborted transaction issue)
    try:
        mconn = get_conn()
        mconn.autocommit = True
        mcur = mconn.cursor()

        # 1. Fix embedding column dimension
        mcur.execute("""
            SELECT pa.atttypmod
            FROM pg_attribute pa
            JOIN pg_class pc ON pc.oid = pa.attrelid
            WHERE pc.relname = 'translations'
              AND pa.attname = 'embedding'
              AND NOT pa.attisdropped
        """)
        row = mcur.fetchone()
        if row is None:
            mcur.execute("ALTER TABLE translations ADD COLUMN embedding vector(384);")
            print("[RAG] Embedding column added (384) ✓")
        elif row[0] != 384:
            print(f"[RAG] Wrong dim {row[0]}, fixing → 384 ...")
            mcur.execute("ALTER TABLE translations DROP COLUMN embedding;")
            mcur.execute("ALTER TABLE translations ADD COLUMN embedding vector(384);")
            mcur.execute("DROP INDEX IF EXISTS translations_embedding_idx;")
            print("[RAG] Embedding column fixed ✓")
        else:
            print("[RAG] Embedding column OK (384) ✓")

        # 2. Fix unique constraint: drop url-only, add (url, orig_para)
        mcur.execute("""
            SELECT constraint_name FROM information_schema.table_constraints
            WHERE table_name='translations' AND constraint_type='UNIQUE'
        """)
        constraints = [r[0] for r in mcur.fetchall()]
        for c in constraints:
            if 'url' in c.lower() and 'orig' not in c.lower():
                mcur.execute(f"ALTER TABLE translations DROP CONSTRAINT IF EXISTS {c};")
                print(f"[RAG] Dropped old constraint: {c}")
        # Add composite unique if not exists
        mcur.execute("""
            SELECT 1 FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu USING (constraint_name)
            WHERE tc.table_name='translations' AND tc.constraint_type='UNIQUE'
              AND ccu.column_name='orig_para'
        """)
        if not mcur.fetchone():
            try:
                mcur.execute("ALTER TABLE translations ADD CONSTRAINT translations_url_para_key UNIQUE (url, orig_para);")
                print("[RAG] Added UNIQUE(url, orig_para) ✓")
            except Exception:
                pass  # already exists

        mcur.close()
        mconn.close()
    except Exception as me:
        print(f"[RAG] Migration error: {me}")

    print("[RAG] Database initialized ✓")


# ── Embeddings ────────────────────────────────────────────────────────────────

import threading as _threading
_embed_model = None
_embed_ready = False
_embed_lock  = _threading.Lock()

def _load_model_bg():
    global _embed_model, _embed_ready
    try:
        from fastembed import TextEmbedding
        m = TextEmbedding(model_name=EMBED_MODEL, cache_dir="/tmp/fe")
        with _embed_lock:
            _embed_model = m
            _embed_ready = True
        print(f"[EMBED] Ready: {EMBED_MODEL}")
    except Exception as e:
        print(f"[EMBED] Load error: {e}")

_threading.Thread(target=_load_model_bg, daemon=True).start()

def _get_model():
    with _embed_lock:
        return _embed_model if _embed_ready else None

def get_embedding(text: str) -> list[float] | None:
    if not text or not text.strip():
        return None
    m = _get_model()
    if m is None:
        return None
    try:
        return list(m.embed([text[:1000]]))[0].tolist()
    except Exception as e:
        print(f"[EMBED] Error: {e}")
        return None

def get_embeddings_batch(texts: list[str]) -> list:
    if not texts:
        return []
    m = _get_model()
    if m is None:
        return [None] * len(texts)
    try:
        return [v.tolist() for v in m.embed([t[:1000] if t else " " for t in texts])]
    except Exception as e:
        print(f"[EMBED] Batch error: {e}")
        return [None] * len(texts)


# ── Store ─────────────────────────────────────────────────────────────────────

def store_translation(
    orig_para:  str,
    tr_para:    str,
    source:     str = "",
    author:     str = "",
    url:        str = "",
    title_orig: str = "",
    title_tr:   str = "",
):
    """
    Save a translated paragraph to the database with its embedding.
    Called automatically after every translation.
    """
    if not orig_para.strip() or not tr_para.strip():
        return

    embedding = get_embedding(orig_para)

    try:
        conn = get_conn()
        cur  = conn.cursor()

        if embedding:
            cur.execute("""
                INSERT INTO translations
                    (source, author, url, title_orig, title_tr, orig_para, tr_para, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO NOTHING;
            """, (source, author, url, title_orig, title_tr,
                  orig_para, tr_para, embedding))
        else:
            # Store without embedding (no API key)
            cur.execute("""
                INSERT INTO translations
                    (source, author, url, title_orig, title_tr, orig_para, tr_para)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (url) DO NOTHING;
            """, (source, author, url, title_orig, title_tr, orig_para, tr_para))

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[STORE] Error: {e}")


def _store_in_background(article: dict):
    source     = article.get("source", "")
    author     = article.get("author", "")
    url        = article.get("url", "")
    title_orig = article.get("title", "")
    title_tr   = article.get("title_tr", "")
    paragraphs = article.get("paragraphs", [])
    valid = [(p.get("original",""), p.get("translated",""))
             for p in paragraphs
             if p.get("original","").strip() and p.get("translated","").strip()]
    if not valid:
        return
    orig_texts = [o for o, _ in valid]
    tr_texts   = [t for _, t in valid]
    embeddings = get_embeddings_batch(orig_texts)
    try:
        conn = get_conn(); cur = conn.cursor(); saved = 0
        for orig, tr, emb in zip(orig_texts, tr_texts, embeddings):
            try:
                if emb:
                    cur.execute("""
                        INSERT INTO translations
                            (source,author,url,title_orig,title_tr,orig_para,tr_para,embedding)
                        SELECT %s,%s,%s,%s,%s,%s,%s,%s
                        WHERE NOT EXISTS (
                            SELECT 1 FROM translations WHERE url=%s AND orig_para=%s
                        )
                    """, (source,author,url,title_orig,title_tr,orig,tr,emb,url,orig))
                else:
                    cur.execute("""
                        INSERT INTO translations
                            (source,author,url,title_orig,title_tr,orig_para,tr_para)
                        SELECT %s,%s,%s,%s,%s,%s,%s
                        WHERE NOT EXISTS (
                            SELECT 1 FROM translations WHERE url=%s AND orig_para=%s
                        )
                    """, (source,author,url,title_orig,title_tr,orig,tr,url,orig))
                saved += 1
            except Exception as row_e:
                conn.rollback()
                print(f"[STORE] Row error: {row_e}")
        conn.commit(); cur.close(); conn.close()
        print(f"[STORE] Saved {saved}/{len(valid)} paragraphs — {source}")
    except Exception as e:
        print(f"[STORE] Error: {e}")

def store_article_translations(article: dict):
    import threading
    threading.Thread(target=_store_in_background, args=(article,), daemon=True).start()


# ── Retrieve ──────────────────────────────────────────────────────────────────

def retrieve_similar(
    text:   str,
    source: str = "",
    author: str = "",
    top_k:  int = TOP_K,
) -> list[dict]:
    """
    Find the most semantically similar past translations.
    Boosts results from same source/author.

    Returns list of dicts: {orig_para, tr_para, source, author, similarity}
    """
    if not _embed_ready:
        return []   # model still loading — skip to avoid blocking HTTP worker
    embedding = get_embedding(text)
    if not embedding:
        return []

    try:
        conn = get_conn()
        cur  = conn.cursor()

        # Cosine similarity search with optional source/author boost
        # Returns top_k * 2 candidates, then we re-rank
        cur.execute("""
            SELECT
                orig_para,
                tr_para,
                source,
                author,
                1 - (embedding <=> %s::vector) AS similarity
            FROM translations
            WHERE 1 - (embedding <=> %s::vector) > %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
        """, (embedding, embedding, MIN_SIMILARITY, embedding, top_k * 2))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        # Re-rank: boost same source/author
        results = []
        for row in rows:
            score = row["similarity"]
            if source and row["source"] == source:
                score += 0.05   # small boost for same publication
            if author and row["author"] == author:
                score += 0.10   # bigger boost for same author
            results.append({**dict(row), "score": score})

        results.sort(key=lambda x: x["score"], reverse=True)
        final = results[:top_k]

        # Log retrieval metrics
        try:
            similarities = [r["similarity"] for r in rows]
            avg_sim = sum(similarities) / len(similarities) if similarities else 0
            max_sim = max(similarities) if similarities else 0
            hit = len(final) > 0

            conn2 = get_conn()
            cur2  = conn2.cursor()
            cur2.execute("""
                INSERT INTO rag_metrics (source, author, results_found, avg_similarity, max_similarity, hit)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (source, author, len(final), round(avg_sim, 4), round(max_sim, 4), hit))
            conn2.commit()
            cur2.close()
            conn2.close()
        except Exception as me:
            print(f"[METRICS] Error: {me}")

        return final

    except Exception as e:
        print(f"[RETRIEVE] Error: {e}")
        return []


# ── Terminology ───────────────────────────────────────────────────────────────

def get_terminology() -> dict:
    """Load all terminology overrides as {original: turkish} dict."""
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("SELECT term_orig, term_tr FROM terminology;")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {r["term_orig"]: r["term_tr"] for r in rows}
    except:
        return {}


def add_term(term_orig: str, term_tr: str, source: str = ""):
    """Add or update a terminology override."""
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO terminology (term_orig, term_tr, source)
            VALUES (%s, %s, %s)
            ON CONFLICT (term_orig) DO UPDATE SET term_tr = EXCLUDED.term_tr;
        """, (term_orig, term_tr, source))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[TERM] Error: {e}")


# ── Generate (RAG-enhanced translation) ──────────────────────────────────────

MIN_WORDS_FOR_CLAUDE = 15  # Skip Claude for very short paragraphs

def should_use_claude(text: str, examples: list, terms: dict) -> tuple[bool, str]:
    """
    Smart decision: should we call Claude or just return DeepL?
    Returns (use_claude, reason)
    """
    word_count = len(text.split())

    # Too short — Claude adds no value
    if word_count < MIN_WORDS_FOR_CLAUDE:
        return False, f"too_short ({word_count} words)"

    # Has similar examples — Claude can match style
    if examples:
        return True, f"rag_hit (similarity={examples[0]['similarity']:.2f})"

    # Has terminology matches — Claude must apply glossary
    if terms:
        term_matches = [t for t in terms if t.lower() in text.lower()]
        if term_matches:
            return True, f"term_match ({', '.join(term_matches[:2])})"

    # No RAG examples, no term matches — DeepL is sufficient
    return False, "no_context"


def rag_translate_paragraph(
    text:       str,
    source:     str = "",
    author:     str = "",
    deepl_tr:   str = "",
) -> tuple:
    """
    Smart RAG translation:
    - Only calls Claude when RAG has examples OR terminology matches
    - Falls back to DeepL otherwise (saves ~60-70% API cost)
    """
    if not ANTHROPIC_KEY or not text.strip():
        return deepl_tr or text, False

    # Step 1: Retrieve similar examples
    examples = retrieve_similar(text, source=source, author=author)

    # Step 2: Get terminology
    terms = get_terminology()

    # Step 3: Smart decision — call Claude?
    use_claude, reason = should_use_claude(text, examples, terms)
    print(f"[RAG] Claude={'YES' if use_claude else 'NO'} reason={reason}")

    if not use_claude:
        return deepl_tr or text, False

    # Step 4: Build prompt
    system_prompt = """You are an expert Turkish translator specializing in left-wing political journalism.
Your job is to improve a machine translation using provided reference examples.

Rules:
- Keep the same meaning and tone as the original
- Use the terminology from the glossary exactly as specified
- Match the style of the reference examples
- Return ONLY the improved Turkish translation, nothing else
- Do not add explanations or notes"""

    examples_text = ""
    if examples:
        examples_text = "\n\n## Reference Translations (similar past work):\n"
        for i, ex in enumerate(examples[:3], 1):
            examples_text += f"\n[Example {i}]\nOriginal: {ex['orig_para'][:200]}\nTurkish: {ex['tr_para'][:200]}\n"

    terms_text = ""
    if terms:
        term_matches = {k: v for k, v in terms.items() if k.lower() in text.lower()}
        if term_matches:
            terms_text = "\n\n## Terminology Glossary (use these exact translations):\n"
            for orig, tr in term_matches.items():
                terms_text += f"- {orig} → {tr}\n"

    user_prompt = f"""## Source: {source or 'Unknown'} | Author: {author or 'Unknown'}
{examples_text}{terms_text}

## Original:
{text}

## DeepL translation:
{deepl_tr}

Improve the translation using the examples and glossary above. Return ONLY the Turkish translation."""

    try:
        client   = Anthropic(api_key=ANTHROPIC_KEY)
        response = client.messages.create(
            model      = CLAUDE_MODEL,
            max_tokens = 1000,
            temperature = 0,
            system     = system_prompt,
            messages   = [{"role": "user", "content": user_prompt}],
        )
        improved = response.content[0].text.strip()
        return (improved if improved else deepl_tr), True
    except Exception as e:
        print(f"[RAG] Claude error: {e}")
        return deepl_tr, False


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    """Return database statistics for the dashboard."""
    try:
        conn = get_conn()
        cur  = conn.cursor()

        cur.execute("SELECT COUNT(*) as total FROM translations;")
        total = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(DISTINCT source) as sources FROM translations;")
        sources = cur.fetchone()["sources"]

        cur.execute("SELECT COUNT(DISTINCT author) as authors FROM translations WHERE author != '';")
        authors = cur.fetchone()["authors"]

        cur.execute("SELECT COUNT(*) as terms FROM terminology;")
        terms = cur.fetchone()["terms"]

        cur.close()
        conn.close()

        return {
            "total_paragraphs": total,
            "sources": sources,
            "authors": authors,
            "terminology_terms": terms,
            "rag_ready": total > 10,  # Need at least 10 examples for good RAG
        }
    except Exception as e:
        print(f"[STATS] Error: {e}")
        return {"total_paragraphs": 0, "sources": 0, "authors": 0, "terminology_terms": 0, "rag_ready": False}
