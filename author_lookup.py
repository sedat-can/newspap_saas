"""
author_lookup.py — Yazar terminoloji bulucu
============================================
Yazar adını alır, internette Türkçe kitaplarını/çevirilerini arar,
terminoloji çiftleri çıkarır ve glossary'e kaydeder.

Kullanım:
  python author_lookup.py "Naomi Klein"
  python author_lookup.py "David Harvey"
  python author_lookup.py --all   → DB'deki tüm yazarları tara
"""

import os
import time
import argparse
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

# ── Web arama ─────────────────────────────────────────────────────────────────

def search_wikipedia_tr(author_name):
    """Wikipedia Türkçe'de yazarı ara, sayfa metnini döndür."""
    try:
        # Wikipedia API
        url = "https://tr.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": author_name,
            "format": "json",
            "srlimit": 3,
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        results = data.get("query", {}).get("search", [])
        
        if not results:
            return ""
        
        # İlk sonucun tam metnini al
        page_title = results[0]["title"]
        content_url = f"https://tr.wikipedia.org/w/api.php"
        params2 = {
            "action": "query",
            "titles": page_title,
            "prop": "extracts",
            "exintro": True,
            "explaintext": True,
            "format": "json",
        }
        resp2 = requests.get(content_url, params=params2, headers=HEADERS, timeout=10)
        data2 = resp2.json()
        pages = data2.get("query", {}).get("pages", {})
        for page in pages.values():
            return page.get("extract", "")
        
    except Exception as e:
        print(f"  [!] Wikipedia hatasi: {e}")
    return ""


def search_wikipedia_en(author_name):
    """Wikipedia İngilizce'de yazarı ara — eser isimlerini bul."""
    try:
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": author_name,
            "format": "json",
            "srlimit": 1,
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        results = data.get("query", {}).get("search", [])
        
        if not results:
            return ""
        
        page_title = results[0]["title"]
        params2 = {
            "action": "query",
            "titles": page_title,
            "prop": "extracts",
            "exintro": True,
            "explaintext": True,
            "format": "json",
        }
        resp2 = requests.get(url, params=params2, headers=HEADERS, timeout=10)
        data2 = resp2.json()
        pages = data2.get("query", {}).get("pages", {})
        for page in pages.values():
            return page.get("extract", "")
        
    except Exception as e:
        print(f"  [!] Wikipedia EN hatasi: {e}")
    return ""


def search_kitapyurdu(author_name):
    """Kitapyurdu.com'da yazarın Türkçe kitaplarını ara."""
    try:
        query = author_name.replace(" ", "+")
        url = f"https://www.kitapyurdu.com/index.php?route=product/search&filter_name={query}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        books = []
        for title_el in soup.find_all("h3", class_=lambda c: c and "title" in (c or "").lower()):
            title = title_el.get_text(strip=True)
            if title and len(title) > 3:
                books.append(title)
        
        return books[:10]
    except Exception as e:
        print(f"  [!] Kitapyurdu hatasi: {e}")
    return []


# ── Claude ile terminoloji çıkarma ────────────────────────────────────────────

def extract_terminology_with_claude(author_name, wiki_tr, wiki_en, books):
    """
    Toplanan verilerden Claude ile terminoloji çiftleri çıkar.
    """
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("  [!] ANTHROPIC_API_KEY yok, terminoloji çıkarılamıyor.")
        return {}
    
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=anthropic_key)
        
        context = f"""Yazar: {author_name}

Wikipedia Türkçe:
{wiki_tr[:1500] if wiki_tr else 'Bulunamadı'}

Wikipedia İngilizce:
{wiki_en[:1500] if wiki_en else 'Bulunamadı'}

Türkçe kitap isimleri:
{chr(10).join(books) if books else 'Bulunamadı'}
"""
        
        prompt = f"""Aşağıdaki bilgilere dayanarak {author_name} isimli yazara özgü terminoloji çiftleri çıkar.

{context}

Görev:
Bu yazarın eserlerinde geçen önemli kavramların İngilizce → Türkçe karşılıklarını listele.
Özellikle Türkçe kitap isimlerinden yola çıkarak orijinal İngilizce terim adlarını tahmin et.

Kurallar:
- Sadece bu yazara özgü, önemli kavramları listele
- Genel kelimeler ekleme (ör: "the" → "bir")
- En az 5, en fazla 30 terim
- Emin olmadıklarını ekleme

Yanıtı SADECE şu JSON formatında ver, başka hiçbir şey yazma:
{{"terimler": [{{"en": "İngilizce terim", "tr": "Türkçe karşılık"}}]}}"""

        response = client.messages.create(
            model       = "claude-haiku-4-5-20251001",
            max_tokens  = 1000,
            temperature = 0,
            messages    = [{"role": "user", "content": prompt}],
        )
        
        import json
        text = response.content[0].text.strip()
        # JSON temizle
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        
        data = json.loads(text)
        terms = {}
        for item in data.get("terimler", []):
            en = item.get("en", "").strip()
            tr = item.get("tr", "").strip()
            if en and tr:
                terms[en] = tr
        
        return terms
        
    except Exception as e:
        print(f"  [!] Claude hatasi: {e}")
        return {}


# ── Veritabanı işlemleri ──────────────────────────────────────────────────────

def author_already_looked_up(author_name):
    """Bu yazar daha önce arandı mı?"""
    try:
        import psycopg2
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return False
        
        conn = psycopg2.connect(db_url)
        cur  = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS author_lookups (
                id          SERIAL PRIMARY KEY,
                author      TEXT UNIQUE,
                looked_up   TIMESTAMP DEFAULT NOW(),
                term_count  INTEGER DEFAULT 0
            );
        """)
        conn.commit()
        cur.execute("SELECT id FROM author_lookups WHERE author = %s", (author_name,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result is not None
    except Exception as e:
        print(f"  [!] DB kontrol hatasi: {e}")
        return False


def save_terms_to_glossary(author_name, terms):
    """Terimleri RAG glossary tablosuna kaydet."""
    if not terms:
        return 0
    
    try:
        import psycopg2
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            print("  [!] DATABASE_URL yok.")
            return 0
        
        conn = psycopg2.connect(db_url)
        cur  = conn.cursor()
        
        # RAG terminology tablosu (rag.py ile aynı)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS terminology (
                id        SERIAL PRIMARY KEY,
                term_orig TEXT UNIQUE,
                term_tr   TEXT NOT NULL,
                source    TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        
        # Author lookups tablosu
        cur.execute("""
            CREATE TABLE IF NOT EXISTS author_lookups (
                id          SERIAL PRIMARY KEY,
                author      TEXT UNIQUE,
                looked_up   TIMESTAMP DEFAULT NOW(),
                term_count  INTEGER DEFAULT 0
            );
        """)
        
        saved = 0
        for en, tr in terms.items():
            try:
                cur.execute("""
                    INSERT INTO terminology (term_orig, term_tr, source)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (term_orig) DO UPDATE SET term_tr = EXCLUDED.term_tr
                """, (en, tr, f"author:{author_name}"))
                saved += 1
            except Exception:
                pass
        
        # Yazar kaydını işaretle
        cur.execute("""
            INSERT INTO author_lookups (author, term_count)
            VALUES (%s, %s)
            ON CONFLICT (author) DO UPDATE SET term_count = EXCLUDED.term_count, looked_up = NOW()
        """, (author_name, saved))
        
        conn.commit()
        cur.close()
        conn.close()
        return saved
        
    except Exception as e:
        print(f"  [!] Terim kayit hatasi: {e}")
        return 0


def get_all_authors_from_db():
    """Veritabanındaki tüm yazarları listele."""
    try:
        import psycopg2
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            return []
        
        conn = psycopg2.connect(db_url)
        cur  = conn.cursor()
        
        # translations tablosundan yazarlar
        authors = []
        for table in ["translations", "ozgurpolitika_archive"]:
            try:
                cur.execute(f"""
                    SELECT DISTINCT author FROM {table}
                    WHERE author IS NOT NULL AND author != '' AND author != 'Yeni Ozgur Politika'
                """)
                rows = cur.fetchall()
                authors.extend([r[0] for r in rows])
            except Exception:
                pass
        
        cur.close()
        conn.close()
        return list(set(authors))
    except Exception as e:
        print(f"  [!] Yazar listeleme hatasi: {e}")
        return []


# ── Ana fonksiyon ─────────────────────────────────────────────────────────────

def lookup_author(author_name, force=False):
    """Tek bir yazar için terminoloji araması yap."""
    print(f"\n{'='*50}")
    print(f"Yazar: {author_name}")
    print(f"{'='*50}")
    
    # Daha önce arandı mı?
    if not force and author_already_looked_up(author_name):
        print(f"  ✓ Bu yazar daha önce arandı, atlıyorum. (--force ile zorlayabilirsin)")
        return
    
    # 1. Wikipedia TR
    print(f"  → Wikipedia TR aranıyor...")
    wiki_tr = search_wikipedia_tr(author_name)
    print(f"  → {len(wiki_tr)} karakter bulundu")
    time.sleep(1)
    
    # 2. Wikipedia EN
    print(f"  → Wikipedia EN aranıyor...")
    wiki_en = search_wikipedia_en(author_name)
    print(f"  → {len(wiki_en)} karakter bulundu")
    time.sleep(1)
    
    # 3. Kitapyurdu
    print(f"  → Kitapyurdu aranıyor...")
    books = search_kitapyurdu(author_name)
    print(f"  → {len(books)} kitap bulundu: {', '.join(books[:3])}")
    time.sleep(1)
    
    # 4. Claude ile terminoloji çıkar
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"  [!] ANTHROPIC_API_KEY yok — veri toplandı ama terim çıkarılamıyor.")
        print(f"  Toplanan veriler:")
        print(f"    Wikipedia TR: {wiki_tr[:200]}..." if wiki_tr else "    Wikipedia TR: Yok")
        print(f"    Kitaplar: {books}")
        return
    
    print(f"  → Claude ile terminoloji çıkarılıyor...")
    terms = extract_terminology_with_claude(author_name, wiki_tr, wiki_en, books)
    print(f"  → {len(terms)} terim bulundu")
    
    if terms:
        print(f"\n  Bulunan terimler:")
        for en, tr in list(terms.items())[:10]:
            print(f"    {en} → {tr}")
        if len(terms) > 10:
            print(f"    ... ve {len(terms)-10} tane daha")
    
    # 5. Glossary'e kaydet
    saved = save_terms_to_glossary(author_name, terms)
    print(f"\n  ✓ {saved} terim glossary'e kaydedildi!")


def main():
    parser = argparse.ArgumentParser(description="Yazar terminoloji bulucu")
    parser.add_argument("author", nargs="?", help="Yazar adı (örn: 'Naomi Klein')")
    parser.add_argument("--all",   action="store_true", help="DB'deki tüm yazarları tara")
    parser.add_argument("--force", action="store_true", help="Daha önce aranmış olsa bile tekrar ara")
    parser.add_argument("--list",  action="store_true", help="DB'deki yazarları listele")
    args = parser.parse_args()
    
    if args.list:
        authors = get_all_authors_from_db()
        print(f"\nDB'deki yazarlar ({len(authors)}):")
        for a in sorted(authors):
            print(f"  - {a}")
        return
    
    if args.all:
        authors = get_all_authors_from_db()
        print(f"\n{len(authors)} yazar bulundu, taranıyor...")
        for author in authors:
            lookup_author(author, force=args.force)
            time.sleep(2)
        return
    
    if args.author:
        lookup_author(args.author, force=args.force)
        return
    
    parser.print_help()


if __name__ == "__main__":
    main()
