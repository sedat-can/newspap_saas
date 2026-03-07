# 📰 Pressflow — AI-Powered News Translation Pipeline

> A production RAG system for multilingual news translation, built for a political news outlet. Translates political journalism from 6+ international sources into Turkish using a custom Retrieval-Augmented Generation pipeline.

**Live Demo:** [newspapsaas-production.up.railway.app](https://newspapsaas-production.up.railway.app)

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      PRESSFLOW PIPELINE                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   RSS Feeds (6+ sources)                                    │
│        │                                                    │
│        ▼                                                    │
│   Article Fetcher                                           │
│   (feedparser + beautifulsoup4)                             │
│        │                                                    │
│        ▼                                                    │
│   DeepL API (base translation)                              │
│        │                                                    │
│        ▼                                                    │
│   RAG Retrieval ◄── pgvector similarity ◄── Archive DB      │
│   (top-5 similar past translations)    (1400+ paragraphs)   │
│        │                                                    │
│        ▼                                                    │
│   Claude API (context-aware refinement)                     │
│        │                                                    │
│        ▼                                                    │
│   Side-by-side viewer + .docx export                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## ✨ Features

### Translation Pipeline
- **DeepL API** for high-quality base translation (EN/FR/DE → TR)
- **RAG refinement** using Claude API with retrieved context
- **Terminology glossary** — exact term overrides
- **Author/source-aware** retrieval with similarity score boosting

### RAG System
- **PostgreSQL + pgvector** for vector similarity search
- **Voyage multilingual embeddings** (1024-dim vectors)
- **Cosine similarity** with source/author boosting (+0.05 same source, +0.10 same author)
- **News archive scraper** — 107 articles, 1400+ paragraphs indexed
- Graceful degradation (falls back to DeepL-only without API keys)

### Web Interface
- RSS feed manager with persistent PostgreSQL storage
- Article detail drawer with full text preview
- Translation basket — select multiple articles, batch translate
- **Side-by-side viewer** with paragraph highlighting and sync scroll
- **In-browser TTS** (Web Speech API) — Neural Turkish voice support
- Editable translation pane with live character/word count
- **.docx export** with source, author, and bilingual layout

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.13, Flask, Gunicorn |
| Translation | DeepL API, Claude API (Anthropic) |
| Vector DB | PostgreSQL + pgvector |
| Embeddings | Voyage multilingual-2 (1024-dim) |
| Scraping | requests, BeautifulSoup4 |
| Frontend | Vanilla JS, CSS |
| Deployment | Railway (CI/CD via GitHub) |
| Documents | python-docx |

---

## 📁 Project Structure

```
pressflow/
├── app.py              # Flask app + API routes
├── rag.py              # RAG pipeline (store, retrieve, generate)
├── scraper.py          # News archive scraper
├── config.py           # RSS feeds + API keys
├── requirements.txt
├── Procfile
└── templates/
    └── index.html      # Single-page app UI
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- PostgreSQL with pgvector extension
- DeepL API key (free tier: 500k chars/month)

### Local Setup

```bash
git clone https://github.com/sedat-can/newspap_saas
cd newspap_saas

pip install -r requirements.txt

export DEEPL_API_KEY=your_deepl_key
export DATABASE_URL=postgresql://localhost/pressflow
export ANTHROPIC_API_KEY=your_anthropic_key  # Optional — enables RAG

python app.py
```

Open `http://localhost:5000`

### Build the RAG Database

```bash
# Test with 5 articles first
python scraper.py --test

# Scrape last 6 months
python scraper.py --months 6
```

### Deploy to Railway

1. Fork this repo
2. Connect to [Railway](https://railway.app)
3. Add PostgreSQL database
4. Set environment variables: `DEEPL_API_KEY`, `ANTHROPIC_API_KEY`
5. Push → auto-deploys

---

## 🧠 How the RAG Pipeline Works

```python
# 1. DeepL base translation
deepl_tr = deepl.translate(paragraph, target_lang="TR")

# 2. Find similar past translations (pgvector cosine similarity)
examples = retrieve_similar(
    text=paragraph,
    source="Jacobin",
    author="Naomi Klein",
    top_k=5,
    min_similarity=0.72
)

# 3. Claude refinement with context
improved = claude.messages.create(
    model="claude-haiku-4-5-20251001",
    temperature=0,  # minimize hallucination
    messages=[{
        "role": "user",
        "content": f"Reference translations: {examples}\n"
                   f"Glossary: {terms}\n"
                   f"Improve this translation: {deepl_tr}"
    }]
)

# 4. Store for future retrieval (system improves over time)
store_translation(paragraph, improved, embedding, source, author)
```

---

## 📊 RAG Database Schema

```sql
CREATE TABLE translations (
    id          SERIAL PRIMARY KEY,
    source      TEXT,
    author      TEXT,
    orig_para   TEXT,
    tr_para     TEXT,
    embedding   vector(1024),
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ON translations USING ivfflat (embedding vector_cosine_ops);

CREATE TABLE news_archive (
    id          SERIAL PRIMARY KEY,
    url         TEXT,
    title       TEXT,
    paragraph   TEXT,
    para_index  INTEGER,
    scraped_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE terminology (
    term_orig TEXT UNIQUE,
    term_tr   TEXT NOT NULL,
    source    TEXT
);
```

---

## 📈 Portfolio Notes

This project demonstrates:

- **RAG architecture** — vector similarity search, embedding generation, retrieval pipeline
- **LLM orchestration** — prompt engineering, context injection, hallucination mitigation (temperature=0)
- **Vector databases** — pgvector, cosine similarity, IVFFlat indexing
- **Production deployment** — Gunicorn, Railway CI/CD, environment management
- **Data pipeline** — web scraping at scale, paragraph extraction, bulk indexing
- **API design** — RESTful Flask endpoints, graceful degradation

---

## 📄 License

MIT

---

*Built for a political news outlet.*
