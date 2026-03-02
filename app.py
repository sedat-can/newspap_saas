import os
import uuid
import time
import feedparser
import trafilatura
import deepl
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_file
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from config import RSS_FEEDS, DEEPL_API_KEY, TARGET_LANGUAGE

app = Flask(__name__)
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

extra_feeds = []
# Load config feeds into mutable list so they can also be deleted at runtime
runtime_feeds = [dict(f) for f in RSS_FEEDS]

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
            })
        return articles
    except Exception as e:
        print(f"[ERROR] {source['name']}: {e}")
        return []

def extract_full_text(url):
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
            return text or ""
    except Exception as e:
        print(f"[EXTRACT ERROR] {url}: {e}")
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

def build_docx(articles_data):
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(1); section.bottom_margin = Inches(1)
        section.left_margin = Inches(1.2); section.right_margin = Inches(1.2)

    tp = doc.add_paragraph()
    tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = tp.add_run("HAFTALIK HABER ÖZETİ")
    r.bold = True; r.font.size = Pt(22)
    r.font.color.rgb = RGBColor(0x1A, 0x3A, 0x6B)

    dp = doc.add_paragraph()
    dp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    dr = dp.add_run(datetime.now().strftime("%d %B %Y"))
    dr.font.size = Pt(11); dr.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    doc.add_paragraph()

    for i, art in enumerate(articles_data, 1):
        meta = doc.add_paragraph()
        sr = meta.add_run(f"[{i}]  {art['source'].upper()}")
        sr.bold = True; sr.font.size = Pt(9)
        sr.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

        titlep = doc.add_paragraph()
        tr_run = titlep.add_run(art.get("title_tr", art["title"]))
        tr_run.bold = True; tr_run.font.size = Pt(14)
        tr_run.font.color.rgb = RGBColor(0x1A, 0x3A, 0x6B)

        op = doc.add_paragraph()
        or_run = op.add_run(f"Orijinal: {art['title']}")
        or_run.italic = True; or_run.font.size = Pt(9)
        or_run.font.color.rgb = RGBColor(0xAA, 0xAA, 0xAA)

        for chunk in art.get("paragraphs", []):
            bp = doc.add_paragraph(chunk.get("translated", ""))
            for r in bp.runs: r.font.size = Pt(11)

        up = doc.add_paragraph()
        ur = up.add_run(f"Kaynak: {art['url']}")
        ur.font.size = Pt(8); ur.font.color.rgb = RGBColor(0x00, 0x70, 0xC0)

        div = doc.add_paragraph("─" * 80)
        div.runs[0].font.size = Pt(8)
        div.runs[0].font.color.rgb = RGBColor(0xCC, 0xCC, 0xCC)

    fp = doc.add_paragraph()
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = fp.add_run(f"Otomatik oluşturuldu • {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    fr.font.size = Pt(8); fr.font.color.rgb = RGBColor(0xAA, 0xAA, 0xAA)

    filename = f"haberler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    doc.save(os.path.join(OUTPUT_DIR, filename))
    return filename

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/feeds", methods=["GET"])
def api_get_feeds():
    return jsonify({"feeds": runtime_feeds + extra_feeds})

@app.route("/api/feeds/add", methods=["POST"])
def api_add_feed():
    data = request.json
    name = data.get("name", "").strip()
    url  = data.get("url", "").strip()
    if not name or not url:
        return jsonify({"error": "Ad ve URL gerekli"}), 400
    feed = {"name": name, "url": url, "extra": True}
    extra_feeds.append(feed)
    return jsonify({"ok": True, "feed": feed})

@app.route("/api/feeds/delete", methods=["POST"])
def api_delete_feed():
    global extra_feeds, runtime_feeds
    name = request.json.get("name", "")
    extra_feeds   = [f for f in extra_feeds   if f["name"] != name]
    runtime_feeds = [f for f in runtime_feeds if f["name"] != name]
    return jsonify({"ok": True})

@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    all_feeds = runtime_feeds + extra_feeds
    all_articles = []
    for source in all_feeds:
        all_articles.extend(fetch_feed(source))
    return jsonify({"articles": all_articles, "count": len(all_articles)})

@app.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.json
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
        if not body:
            body = art.get("summary", "")
        try:
            title_tr = translator.translate_text(art["title"], target_lang=TARGET_LANGUAGE).text
        except:
            title_tr = art["title"]
        paragraphs = translate_paragraphs(translator, body)
        results.append({**art, "title_tr": title_tr, "paragraphs": paragraphs})

    filename = build_docx(results)
    return jsonify({"filename": filename, "articles": results})

@app.route("/api/download/<filename>")
def api_download(filename):
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "Dosya bulunamadı"}), 404
    return send_file(filepath, as_attachment=True, download_name=filename)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
