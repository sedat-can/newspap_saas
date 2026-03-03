import os, uuid, time, json, feedparser, trafilatura, deepl
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_file
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from config import RSS_FEEDS, DEEPL_API_KEY, TARGET_LANGUAGE

app = Flask(__name__)
OUTPUT_DIR  = os.path.join(os.path.dirname(__file__), "output")
FEEDS_FILE  = os.path.join(os.path.dirname(__file__), "feeds.json")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Persistent feed storage ──────────────────────────────────────────────────

def load_feeds():
    """Load user-managed feeds from JSON. Merge with config on first run."""
    if os.path.exists(FEEDS_FILE):
        with open(FEEDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # First run: seed from config
    feeds = [{"name": s["name"], "url": s["url"], "enabled": True, "builtin": True}
             for s in RSS_FEEDS]
    save_feeds(feeds)
    return feeds

def save_feeds(feeds):
    with open(FEEDS_FILE, "w", encoding="utf-8") as f:
        json.dump(feeds, f, ensure_ascii=False, indent=2)

# ── Article helpers ──────────────────────────────────────────────────────────

def fetch_feed(source):
    try:
        feed = feedparser.parse(source["url"])
        articles = []
        for entry in feed.entries[:25]:
            articles.append({
                "id":      str(uuid.uuid4()),
                "source":  source["name"],
                "title":   entry.get("title", "No title").strip(),
                "url":     entry.get("link", ""),
                "summary": entry.get("summary", ""),
                "date":    entry.get("published", ""),
                "author":  entry.get("author", ""),
            })
        return articles
    except Exception as e:
        print(f"[ERROR] {source['name']}: {e}")
        return []

def extract_full_text(url):
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            return trafilatura.extract(downloaded, include_comments=False, include_tables=False) or ""
    except Exception as e:
        print(f"[EXTRACT] {url}: {e}")
    return ""

def translate_paragraphs(translator, text):
    if not text or not text.strip():
        return []
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    result = []
    for para in paragraphs:
        try:
            tr = translator.translate_text(para, target_lang=TARGET_LANGUAGE)
            result.append({"original": para, "translated": tr.text})
            time.sleep(0.05)
        except:
            result.append({"original": para, "translated": para})
    return result

# ── DOCX builder ─────────────────────────────────────────────────────────────

def build_docx(articles_data):
    doc = Document()
    for sec in doc.sections:
        sec.top_margin = sec.bottom_margin = Inches(1)
        sec.left_margin = sec.right_margin = Inches(1.2)

    # Cover
    tp = doc.add_paragraph(); tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = tp.add_run("HAFTALIK HABER ÖZETİ")
    r.bold = True; r.font.size = Pt(22); r.font.color.rgb = RGBColor(0x1A,0x3A,0x6B)
    dp = doc.add_paragraph(); dp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    dr = dp.add_run(datetime.now().strftime("%d %B %Y"))
    dr.font.size = Pt(11); dr.font.color.rgb = RGBColor(0x55,0x55,0x55)
    doc.add_paragraph()

    for i, art in enumerate(articles_data, 1):
        # Meta line: source + author
        meta = doc.add_paragraph()
        author_str = f"  ·  {art.get('author','')}" if art.get('author') else ""
        sr = meta.add_run(f"[{i}]  {art.get('source','').upper()}{author_str}")
        sr.bold = True; sr.font.size = Pt(9); sr.font.color.rgb = RGBColor(0x88,0x88,0x88)

        # Translated title
        titlep = doc.add_paragraph()
        tr_r = titlep.add_run(art.get("title_tr") or art.get("title",""))
        tr_r.bold = True; tr_r.font.size = Pt(14); tr_r.font.color.rgb = RGBColor(0x1A,0x3A,0x6B)

        # Original title
        op = doc.add_paragraph()
        or_r = op.add_run(f"Orijinal: {art.get('title','')}")
        or_r.italic = True; or_r.font.size = Pt(9); or_r.font.color.rgb = RGBColor(0xAA,0xAA,0xAA)

        # Body
        for chunk in art.get("paragraphs", []):
            bp = doc.add_paragraph(chunk.get("translated",""))
            for r in bp.runs: r.font.size = Pt(11)

        # Source URL
        if art.get("url"):
            up = doc.add_paragraph()
            ur = up.add_run(f"Kaynak: {art['url']}")
            ur.font.size = Pt(8); ur.font.color.rgb = RGBColor(0x00,0x70,0xC0)

        # Author line (if present)
        if art.get("author"):
            authp = doc.add_paragraph()
            authr = authp.add_run(f"Yazar: {art['author']}")
            authr.font.size = Pt(9); authr.font.color.rgb = RGBColor(0x66,0x66,0x88)

        div = doc.add_paragraph("─" * 80)
        div.runs[0].font.size = Pt(8); div.runs[0].font.color.rgb = RGBColor(0xCC,0xCC,0xCC)

    fp = doc.add_paragraph(); fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = fp.add_run(f"Otomatik oluşturuldu • {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    fr.font.size = Pt(8); fr.font.color.rgb = RGBColor(0xAA,0xAA,0xAA)

    filename = f"haberler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    doc.save(os.path.join(OUTPUT_DIR, filename))
    return filename

def build_text_docx(title, source, author, paragraphs):
    """Build docx for a manually pasted + translated text."""
    doc = Document()
    for sec in doc.sections:
        sec.top_margin = sec.bottom_margin = Inches(1)
        sec.left_margin = sec.right_margin = Inches(1.2)

    # Header meta
    meta = doc.add_paragraph()
    meta_str = []
    if source: meta_str.append(f"Kaynak: {source}")
    if author: meta_str.append(f"Yazar: {author}")
    mr = meta.add_run("  ·  ".join(meta_str))
    mr.font.size = Pt(9); mr.font.color.rgb = RGBColor(0x88,0x88,0x88)

    if title:
        tp = doc.add_paragraph()
        tr = tp.add_run(title)
        tr.bold = True; tr.font.size = Pt(16); tr.font.color.rgb = RGBColor(0x1A,0x3A,0x6B)

    doc.add_paragraph()

    for chunk in paragraphs:
        # Original
        op = doc.add_paragraph(chunk.get("original",""))
        for r in op.runs:
            r.font.size = Pt(10); r.font.color.rgb = RGBColor(0x88,0x88,0xAA)
            r.italic = True
        # Translated
        tp2 = doc.add_paragraph(chunk.get("translated",""))
        for r in tp2.runs: r.font.size = Pt(11)
        doc.add_paragraph()

    dp = doc.add_paragraph(); dp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    dr = dp.add_run(f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    dr.font.size = Pt(8); dr.font.color.rgb = RGBColor(0xAA,0xAA,0xAA)

    filename = f"metin_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    doc.save(os.path.join(OUTPUT_DIR, filename))
    return filename

# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/feeds", methods=["GET"])
def api_get_feeds():
    return jsonify({"feeds": load_feeds()})

@app.route("/api/feeds/add", methods=["POST"])
def api_add_feed():
    data = request.json
    name = data.get("name","").strip()
    url  = data.get("url","").strip()
    if not name or not url:
        return jsonify({"error": "Ad ve URL gerekli"}), 400
    feeds = load_feeds()
    if any(f["name"] == name for f in feeds):
        return jsonify({"error": "Bu isimde kaynak zaten var"}), 400
    feeds.append({"name": name, "url": url, "enabled": True, "builtin": False})
    save_feeds(feeds)
    return jsonify({"ok": True})

@app.route("/api/feeds/toggle", methods=["POST"])
def api_toggle_feed():
    name = request.json.get("name","")
    feeds = load_feeds()
    for f in feeds:
        if f["name"] == name:
            f["enabled"] = not f.get("enabled", True)
            break
    save_feeds(feeds)
    return jsonify({"ok": True, "feeds": feeds})

@app.route("/api/feeds/delete", methods=["POST"])
def api_delete_feed():
    name = request.json.get("name","")
    feeds = load_feeds()
    feeds = [f for f in feeds if f["name"] != name]
    save_feeds(feeds)
    return jsonify({"ok": True})

@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    feeds = [f for f in load_feeds() if f.get("enabled", True)]
    all_articles = []
    for source in feeds:
        all_articles.extend(fetch_feed(source))
    return jsonify({"articles": all_articles, "count": len(all_articles)})

@app.route("/api/translate", methods=["POST"])
def api_translate():
    data     = request.json
    selected = data.get("articles", [])
    if not selected:
        return jsonify({"error": "Makale seçilmedi"}), 400
    if DEEPL_API_KEY == "YOUR_DEEPL_API_KEY_HERE":
        return jsonify({"error": "config.py dosyasına DeepL API anahtarını ekleyin"}), 400
    try:
        translator = deepl.Translator(DEEPL_API_KEY)
    except Exception as e:
        return jsonify({"error": f"DeepL hatası: {e}"}), 500

    results = []
    for art in selected:
        body = extract_full_text(art["url"]) if art.get("url") else ""
        if not body: body = art.get("summary","")
        try: title_tr = translator.translate_text(art["title"], target_lang=TARGET_LANGUAGE).text
        except: title_tr = art["title"]
        results.append({**art, "title_tr": title_tr, "paragraphs": translate_paragraphs(translator, body)})

    filename = build_docx(results)
    return jsonify({"filename": filename, "articles": results})

@app.route("/api/translate-text", methods=["POST"])
def api_translate_text():
    """Translate a manually pasted block of text."""
    data   = request.json
    text   = data.get("text","").strip()
    source = data.get("source","").strip()
    author = data.get("author","").strip()
    title  = data.get("title","").strip()

    if not text:
        return jsonify({"error": "Metin boş olamaz"}), 400
    if DEEPL_API_KEY == "YOUR_DEEPL_API_KEY_HERE":
        return jsonify({"error": "config.py dosyasına DeepL API anahtarını ekleyin"}), 400
    try:
        translator = deepl.Translator(DEEPL_API_KEY)
    except Exception as e:
        return jsonify({"error": f"DeepL hatası: {e}"}), 500

    paragraphs = translate_paragraphs(translator, text)
    title_tr   = ""
    if title:
        try: title_tr = translator.translate_text(title, target_lang=TARGET_LANGUAGE).text
        except: title_tr = title

    filename = build_text_docx(title_tr or title, source, author, paragraphs)
    return jsonify({
        "filename":   filename,
        "title_tr":   title_tr,
        "paragraphs": paragraphs,
        "source":     source,
        "author":     author,
    })

@app.route("/api/article", methods=["POST"])
def api_article():
    """Fetch full article text for detail view."""
    url = request.json.get("url", "")
    if not url:
        return jsonify({"error": "URL gerekli"}), 400
    body = extract_full_text(url)
    return jsonify({"body": body})

@app.route("/api/fetch-text", methods=["POST"])
def api_fetch_text():
    url = request.json.get("url","").strip()
    if not url:
        return jsonify({"text":""})
    text = extract_full_text(url)
    return jsonify({"text": text})

@app.route("/api/download/<filename>")
def api_download(filename):
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "Dosya bulunamadı"}), 404
    return send_file(filepath, as_attachment=True, download_name=filename)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
