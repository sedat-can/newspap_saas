"""
scraper.py — Yeni Özgür Politika arşiv scraper'ı
=================================================
Kullanım:
  python scraper.py              → Son 6 ay, tüm kategoriler
  python scraper.py --months 3   → Son 3 ay
  python scraper.py --test       → Sadece 5 makale (test modu)
"""

import os
import time
import argparse
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urljoin

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

REQUEST_DELAY = 1.5

def get_page(url, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"  [!] Hata ({attempt+1}/{retries}): {url} -> {e}")
            time.sleep(3)
    return None


def parse_date(text):
    if not text:
        return None
    text = text.strip()
    tr_months = {
        "Ocak": "01", "Subat": "02", "Mart": "03", "Nisan": "04",
        "Mayis": "05", "Haziran": "06", "Temmuz": "07", "Agustos": "08",
        "Eylul": "09", "Ekim": "10", "Kasim": "11", "Aralik": "12",
        "Şubat": "02", "Mayıs": "05", "Ağustos": "08", "Eylül": "09", "Kasım": "11", "Aralık": "12"
    }
    for tr, num in tr_months.items():
        text = text.replace(tr, num)
    for fmt in ("%d %m %Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def get_article_links(category, months_back=6, max_pages=50):
    links = []
    for page_num in range(1, max_pages + 1):
        if page_num == 1:
            url = f"{BASE_URL}{category}"
        else:
            url = f"{BASE_URL}{category}?page={page_num}"

        print(f"  -> Sayfa {page_num}: {url}")
        soup = get_page(url)
        if not soup:
            break

        page_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("/haberi-"):
                full_url = urljoin(BASE_URL, href)
                if full_url not in links and full_url not in page_links:
                    page_links.append(full_url)

        if not page_links:
            print(f"  -> Makale bulunamadi, sayfalama bitti.")
            break

        links.extend(page_links)
        time.sleep(REQUEST_DELAY)

    return list(dict.fromkeys(links))


def parse_article(url):
    soup = get_page(url)
    if not soup:
        return None

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content", "")

    author = ""
    author_el = soup.find("a", class_=lambda c: c and "yazar" in c.lower()) or \
                soup.find("span", class_=lambda c: c and "yazar" in c.lower()) or \
                soup.find("div", class_=lambda c: c and "author" in c.lower())
    if author_el:
        author = author_el.get_text(strip=True)

    pub_date = None
    date_el = soup.find("time") or \
              soup.find("span", class_=lambda c: c and "tarih" in (c or "").lower()) or \
              soup.find("div", class_=lambda c: c and "date" in (c or "").lower())
    if date_el:
        dt_attr = date_el.get("datetime") or date_el.get_text(strip=True)
        pub_date = parse_date(dt_attr)

    paragraphs = []
    seen = set()

    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) > 50 and text not in seen:
            paragraphs.append(text)
            seen.add(text)

    if len(paragraphs) < 2:
        paragraphs = []
        seen = set()
        for tag in soup.find_all(["p", "div", "span", "strong"]):
            text = tag.get_text(strip=True)
            if (len(text) > 80 and
                text not in seen and
                not any(c.name in ["p", "div"] for c in tag.children if hasattr(c, 'name'))):
                paragraphs.append(text)
                seen.add(text)

    if not paragraphs:
        return None

    return {
        "url":        url,
        "title":      title,
        "author":     author or "Yeni Ozgur Politika",
        "date":       pub_date,
        "text":       "\n\n".join(paragraphs),
        "paragraphs": paragraphs,
    }


def init_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ozgurpolitika_archive (
            id          SERIAL PRIMARY KEY,
            url         TEXT,
            title       TEXT,
            author      TEXT,
            pub_date    TIMESTAMP,
            paragraph   TEXT,
            para_index  INTEGER,
            scraped_at  TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_url_para
        ON ozgurpolitika_archive(url, para_index);
    """)


def store_to_rag(article):
    try:
        import psycopg2
        import psycopg2.extras

        db_url = os.environ.get("DATABASE_URL")
        if not db_url:
            print("  [!] DATABASE_URL yok, veritabanina kaydedilemiyor.")
            return False

        conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
        cur  = conn.cursor()

        init_table(cur)
        conn.commit()

        saved = 0
        for i, para in enumerate(article["paragraphs"]):
            try:
                cur.execute("""
                    INSERT INTO ozgurpolitika_archive
                        (url, title, author, pub_date, paragraph, para_index)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url, para_index) DO NOTHING
                """, (
                    article["url"],
                    article["title"],
                    article["author"],
                    article["date"],
                    para,
                    i,
                ))
                saved += 1
            except Exception as e:
                conn.rollback()
                print(f"  [!] Paragraf kayit hatasi: {e}")

        conn.commit()
        cur.close()
        conn.close()
        return saved > 0

    except Exception as e:
        print(f"  [!] DB hatasi: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Yeni Ozgur Politika scraper")
    parser.add_argument("--months",   type=int, default=6,    help="Kac aylik arsiv (varsayilan: 6)")
    parser.add_argument("--test",     action="store_true",    help="Test modu: sadece 5 makale")
    parser.add_argument("--category", type=str, default=None, help="Tek kategori")
    args = parser.parse_args()

    categories = [args.category] if args.category else CATEGORIES
    test_mode  = args.test

    print(f"\n{'='*60}")
    print(f"Yeni Ozgur Politika Scraper")
    print(f"Mod: {'TEST (5 makale)' if test_mode else f'Son {args.months} ay'}")
    print(f"Kategoriler: {len(categories)}")
    print(f"{'='*60}\n")

    all_links    = []
    total_saved  = 0
    total_failed = 0

    for cat in categories:
        print(f"\nKategori: {cat}")
        links = get_article_links(cat, months_back=args.months, max_pages=3 if test_mode else 50)
        print(f"  -> {len(links)} makale linki bulundu")
        all_links.extend(links)

        if test_mode and len(all_links) >= 5:
            break

    all_links = list(dict.fromkeys(all_links))
    if test_mode:
        all_links = all_links[:5]

    print(f"\nToplam benzersiz link: {len(all_links)}")
    print(f"{'='*60}\n")

    for i, url in enumerate(all_links, 1):
        print(f"[{i}/{len(all_links)}] {url}")

        article = parse_article(url)
        if not article:
            print(f"  x Ayristirilamadi, atliyorum.")
            total_failed += 1
            time.sleep(REQUEST_DELAY)
            continue

        print(f"  Baslik  : {article['title'][:60]}...")
        print(f"  Yazar   : {article['author']}")
        print(f"  Paragraf: {len(article['paragraphs'])}")

        if store_to_rag(article):
            print(f"  Kaydedildi")
            total_saved += 1
        else:
            print(f"  Cekildi (DB kaydi atlandi)")
            total_saved += 1

        time.sleep(REQUEST_DELAY)

    print(f"\n{'='*60}")
    print(f"Tamamlandi!")
    print(f"   Basarili : {total_saved}")
    print(f"   Basarisiz: {total_failed}")
    print(f"   Toplam   : {len(all_links)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
