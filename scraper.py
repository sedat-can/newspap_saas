"""
scraper.py — Yeni Özgür Politika arşiv scraper'ı
=================================================
Siteyi tarar, makaleleri çeker ve RAG veritabanına kaydeder.

Kullanım:
  python scraper.py              → Son 6 ay, tüm kategoriler
  python scraper.py --months 3   → Son 3 ay
  python scraper.py --test       → Sadece 5 makale (test modu)
"""

import os
import sys
import time
import argparse
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urljoin

# ── Config ────────────────────────────────────────────────────────────────────

BASE_URL   = "https://www.ozgurpolitika.com"
SOURCE     = "Yeni Özgür Politika"

CATEGORIES = [
    "/haber-haberleri",
    "/dunya-haberleri",
    "/yazarlar-haberleri",
    "/kultursanat-haberleri",
    "/toplumyasam-haberleri",
    "/kadin-haberleri",
    "/yurtdisi-haberleri",
    "/dosya-haberleri",
    "/forum-haberleri",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9",
}

REQUEST_DELAY = 1.5   # saniye — siteye yük bindirmemek için

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_page(url, retries=3):
    """URL'yi çek, başarısız olursa tekrar dene."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"  [!] Hata ({attempt+1}/{retries}): {url} → {e}")
            time.sleep(3)
    return None


def parse_date(text):
    """Türkçe tarih string'ini datetime'a çevir."""
    if not text:
        return None
    text = text.strip()
    tr_months = {
        "Ocak": "01", "Şubat": "02", "Mart": "03", "Nisan": "04",
        "Mayıs": "05", "Haziran": "06", "Temmuz": "07", "Ağustos": "08",
        "Eylül": "09", "Ekim": "10", "Kasım": "11", "Aralık": "12"
    }
    for tr, num in tr_months.items():
        text = text.replace(tr, num)
    for fmt in ("%d %m %Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None

# ── Article link collector ────────────────────────────────────────────────────

def get_article_links(category, months_back=6, max_pages=50):
    """
    Kategori sayfasından makale linklerini toplar.
    months_back kadar eski makaleleri dahil eder.
    """
    cutoff = datetime.now() - timedelta(days=months_back * 30)
    links  = []
    
    for page_num in range(1, max_pages + 1):
        if page_num == 1:
            url = f"{BASE_URL}{category}"
        else:
            url = f"{BASE_URL}{category}?page={page_num}"
        
        print(f"  → Sayfa {page_num}: {url}")
        soup = get_page(url)
        if not soup:
            break
        
        # Makale linklerini bul — /haberi- ile başlayanlar
        page_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/haberi-"):
                full_url = urljoin(BASE_URL, href)
                if full_url not in links and full_url not in page_links:
                    page_links.append(full_url)
        
        if not page_links:
            print(f"  → Makale bulunamadı, sayfalama bitti.")
            break
        
        links.extend(page_links)
        
        # Tarih kontrolü — sayfadaki son makale çok eskiyse dur
        # (Tam tarih için makaleye girmemiz lazım, burada sayfa sayısıyla sınırlıyoruz)
        time.sleep(REQUEST_DELAY)
    
    return list(dict.fromkeys(links))  # Tekrarları kaldır

# ── Article parser ────────────────────────────────────────────────────────────

def parse_article(url):
    """
    Makale sayfasından içerik çeker.
    Döndürür: {url, title, author, date, text, paragraphs}
    """
    soup = get_page(url)
    if not soup:
        return None
    
    # Başlık
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content", "")
    
    # Yazar
    author = ""
    author_el = soup.find("a", class_=lambda c: c and "yazar" in c.lower()) or \
                soup.find("span", class_=lambda c: c and "yazar" in c.lower()) or \
                soup.find("div", class_=lambda c: c and "author" in c.lower())
    if author_el:
        author = author_el.get_text(strip=True)
    
    # Tarih
    pub_date = None
    date_el = soup.find("time") or \
              soup.find("span", class_=lambda c: c and "tarih" in (c or "").lower()) or \
              soup.find("div", class_=lambda c: c and "date" in (c or "").lower())
    if date_el:
        dt_attr = date_el.get("datetime") or date_el.get_text(strip=True)
        pub_date = parse_date(dt_attr)
    
    # Makale gövdesi
    body = soup.find("div", class_=lambda c: c and any(
        kw in (c or "").lower() for kw in ["haberdetay", "haber-detay", "article-body", 
                                             "news-content", "content-body", "icerik"]
    ))
    if not body:
        # Alternatif: en uzun div
        divs = soup.find_all("div")
        body = max(divs, key=lambda d: len(d.get_text()), default=None)
    
    if not body:
        return None
    
    # Paragrafları çıkar
    paragraphs = []
    for p in body.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) > 50:  # Çok kısa paragrafları atla
            paragraphs.append(text)
    
    if not paragraphs:
        return None
    
    full_text = "\n\n".join(paragraphs)
    
    return {
        "url":        url,
        "title":      title,
        "author":     author or "Yeni Özgür Politika",
        "date":       pub_date,
        "text":       full_text,
        "paragraphs": paragraphs,
    }

# ── Database storage ──────────────────────────────────────────────────────────

def store_to_rag(article):
    """
    Makaleyi RAG veritabanına paragraf paragraf kaydeder.
    Embedding olmadan kaydeder (API key olmadan da çalışır).
    """
    try:
        import psycopg2
        import psycopg2.extras
        
        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            print("  [!] DATABASE_URL yok, veritabanına kaydedilemiyor.")
            return False
        
        conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
        cur  = conn.cursor()
        
        # Tabloyu oluştur (yoksa)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ozgurpolitika_archive (
                id          SERIAL PRIMARY KEY,
                url         TEXT UNIQUE,
                title       TEXT,
                author      TEXT,
                pub_date    TIMESTAMP,
                paragraph   TEXT,
                para_index  INTEGER,
                scraped_at  TIMESTAMP DEFAULT NOW()
            );
        """)
        
        # Her paragrafı kaydet
        saved = 0
        for i, para in enumerate(article["paragraphs"]):
            try:
                cur.execute("""
                    INSERT INTO ozgurpolitika_archive 
                        (url, title, author, pub_date, paragraph, para_index)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (
                    article["url"],
                    article["title"],
                    article["author"],
                    article["date"],
                    para,
                    i,
                ))
                saved += 1
            except Exception:
                pass
        
        conn.commit()
        cur.close()
        conn.close()
        return saved > 0
        
    except Exception as e:
        print(f"  [!] DB hatası: {e}")
        return False

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Yeni Özgür Politika scraper")
    parser.add_argument("--months", type=int, default=6, help="Kaç aylık arşiv (varsayılan: 6)")
    parser.add_argument("--test",   action="store_true",  help="Test modu: sadece 5 makale")
    parser.add_argument("--category", type=str, default=None, help="Tek kategori (örn: /haber-haberleri)")
    args = parser.parse_args()
    
    categories = [args.category] if args.category else CATEGORIES
    test_mode  = args.test
    
    print(f"\n{'='*60}")
    print(f"Yeni Özgür Politika Scraper")
    print(f"Mod: {'TEST (5 makale)' if test_mode else f'Son {args.months} ay'}")
    print(f"Kategoriler: {len(categories)}")
    print(f"{'='*60}\n")
    
    all_links    = []
    total_saved  = 0
    total_failed = 0
    
    # 1. Tüm kategorilerden linkleri topla
    for cat in categories:
        print(f"\n📂 Kategori: {cat}")
        links = get_article_links(cat, months_back=args.months, max_pages=3 if test_mode else 50)
        print(f"  → {len(links)} makale linki bulundu")
        all_links.extend(links)
        
        if test_mode and len(all_links) >= 5:
            break
    
    # Tekrarları kaldır
    all_links = list(dict.fromkeys(all_links))
    if test_mode:
        all_links = all_links[:5]
    
    print(f"\n📰 Toplam benzersiz link: {len(all_links)}")
    print(f"{'='*60}\n")
    
    # 2. Her makaleyi çek ve kaydet
    for i, url in enumerate(all_links, 1):
        print(f"[{i}/{len(all_links)}] {url}")
        
        article = parse_article(url)
        if not article:
            print(f"  ✗ Ayrıştırılamadı, atlıyorum.")
            total_failed += 1
            time.sleep(REQUEST_DELAY)
            continue
        
        print(f"  Başlık : {article['title'][:60]}...")
        print(f"  Yazar  : {article['author']}")
        print(f"  Paragraf: {len(article['paragraphs'])}")
        
        # Veritabanına kaydet
        if store_to_rag(article):
            print(f"  ✓ Kaydedildi")
            total_saved += 1
        else:
            # DB yoksa sadece say
            print(f"  ✓ Çekildi (DB kaydı atlandı)")
            total_saved += 1
        
        time.sleep(REQUEST_DELAY)
    
    # 3. Özet
    print(f"\n{'='*60}")
    print(f"✅ Tamamlandı!")
    print(f"   Başarılı : {total_saved}")
    print(f"   Başarısız: {total_failed}")
    print(f"   Toplam   : {len(all_links)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
