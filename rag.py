"""
rag.py — Retrieval-Augmented Generation pipeline for Pressflow
==============================================================
Architecture:
  1. STORE   — Save every translation to PostgreSQL
  2. RETRIEVE — Find similar past translations using full-text search (ozgurpolitika_archive)
  3. GENERATE — Send to Claude with retrieved examples as context
"""

import os
import time
import psycopg2
import psycopg2.extras
from anthropic import Anthropic

# ── Config ────────────────────────────────────────────────────────────────────

DATABASE_URL   = os.environ.get("DATABASE_URL", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL   = "claude-haiku-4-5-20251001"
TOP_K          = 5
MIN_WORDS_FOR_CLAUDE = 15

# ── Database setup ────────────────────────────────────────────────────────────

def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS translations (
            id          SERIAL PRIMARY KEY,
            source      TEXT,
            author      TEXT,
            url         TEXT UNIQUE,
            title_orig  TEXT,
            title_tr    TEXT,
            orig_para   TEXT NOT NULL,
            tr_para     TEXT NOT NULL,
            embedding   vector(1024),
            created_at  TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS translations_embedding_idx
        ON translations
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS terminology (
            id          SERIAL PRIMARY KEY,
            term_orig   TEXT NOT NULL UNIQUE,
            term_tr     TEXT NOT NULL,
            source      TEXT,
            created_at  TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("[RAG] Database initialized ✓")


# ── Embeddings — DISABLED, full-text search kullaniliyor ─────────────────────

def get_embedding(text: str):
    return None


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
    if not orig_para.strip() or not tr_para.strip():
        return
    try:
        conn = get_conn()
        cur  = conn.cursor()
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


def store_article_translations(article: dict):
    source     = article.get("source", "")
    author     = article.get("author", "")
    url        = article.get("url", "")
    title_orig = article.get("title", "")
    title_tr   = article.get("title_tr", "")

    for para in article.get("paragraphs", []):
        store_translation(
            orig_para  = para.get("original", ""),
            tr_para    = para.get("translated", ""),
            source     = source,
            author     = author,
            url        = url,
            title_orig = title_orig,
            title_tr   = title_tr,
        )
        time.sleep(0.02)

    print(f"[STORE] Saved {len(article.get('paragraphs', []))} paragraphs — {source}")


# ── Retrieve — Full-text search on ozgurpolitika_archive ─────────────────────

def retrieve_similar(
    text:   str,
    source: str = "",
    author: str = "",
    top_k:  int = TOP_K,
) -> list[dict]:
    """
    Turkce DeepL ceviriyle ozgurpolitika_archive'de full-text arama yapar.
    """
    if not text.strip():
        return []

    keywords = [w for w in text.split() if len(w) > 4][:8]
    if not keywords:
        return []

    query_str = " | ".join(keywords)

    try:
        conn = get_conn()
        cur  = conn.cursor()

        cur.execute("""
            SELECT
                paragraph   AS orig_para,
                paragraph   AS tr_para,
                %s          AS source,
                author,
                ts_rank(to_tsvector('simple', paragraph),
                        to_tsquery('simple', %s)) AS similarity
            FROM ozgurpolitika_archive
            WHERE to_tsvector('simple', paragraph) @@ to_tsquery('simple', %s)
            ORDER BY similarity DESC
            LIMIT %s;
        """, (source or "ozgurpolitika", query_str, query_str, top_k))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        results = []
        for row in rows:
            results.append({
                "orig_para":  row["orig_para"],
                "tr_para":    row["tr_para"],
                "source":     row["source"],
                "author":     row["author"],
                "similarity": float(row["similarity"]),
                "score":      float(row["similarity"]),
            })

        print(f"[RAG] Full-text search: {len(results)} sonuc bulundu")
        return results

    except Exception as e:
        print(f"[RETRIEVE] Error: {e}")
        return []


# ── Terminology ───────────────────────────────────────────────────────────────

def get_terminology() -> dict:
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


# ── Generate ──────────────────────────────────────────────────────────────────

def should_use_claude(text: str, examples: list, terms: dict) -> tuple[bool, str]:
    word_count = len(text.split())

    if word_count < MIN_WORDS_FOR_CLAUDE:
        return False, f"too_short ({word_count} words)"

    if examples:
        return True, f"rag_hit (similarity={examples[0]['similarity']:.2f})"

    if terms:
        term_matches = [t for t in terms if t.lower() in text.lower()]
        if term_matches:
            return True, f"term_match ({', '.join(term_matches[:2])})"

    return False, "no_context"


def rag_translate_paragraph(
    text:     str,
    source:   str = "",
    author:   str = "",
    deepl_tr: str = "",
) -> str:
    """
    DeepL Turkce ceviriyle arsivde arama yap, Claude ile iyilestir.
    RAG fail olursa deepl_tr doner — hicbir zaman bos donmez.
    """
    if not ANTHROPIC_KEY or not text.strip():
        return deepl_tr or text

    # Turkce DeepL ceviriyle ara (arsiv Turkce!)
    search_text = deepl_tr if deepl_tr else text
    examples = retrieve_similar(search_text, source=source, author=author)

    terms = get_terminology()

    use_claude, reason = should_use_claude(text, examples, terms)
    print(f"[RAG] Claude={'YES' if use_claude else 'NO'} reason={reason}")

    if not use_claude:
        return deepl_tr or text

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
            examples_text += f"\n[Example {i}]\nTurkish context: {ex['tr_para'][:200]}\n"

    terms_text = ""
    if terms:
        term_matches = {k: v for k, v in terms.items() if k.lower() in text.lower()}
        if term_matches:
            terms_text = "\n\n## Terminology Glossary (use these exact translations):\n"
            for orig, tr in term_matches.items():
                terms_text += f"- {orig} -> {tr}\n"

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
            model       = CLAUDE_MODEL,
            max_tokens  = 600,
            temperature = 0,
            system      = system_prompt,
            messages    = [{"role": "user", "content": user_prompt}],
            timeout     = 15,
        )
        improved = response.content[0].text.strip()
        return improved if improved else deepl_tr
    except Exception as e:
        print(f"[RAG] Claude error: {e}")
        return deepl_tr


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
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
            "rag_ready": total > 10,
        }
    except Exception as e:
        print(f"[STATS] Error: {e}")
        return {"total_paragraphs": 0, "sources": 0, "authors": 0, "terminology_terms": 0, "rag_ready": False}
