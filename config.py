# ============================================================
#  YAPILANDIRMA — Feedly OPML'den otomatik oluşturuldu
# ============================================================

import os
DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY", "") 
TARGET_LANGUAGE = "TR"                        # Türkçe

RSS_FEEDS = [
    # ── french_left ──────────────────────────────────────────
    {"name": "Le Monde diplomatique",  "url": "http://mondediplo.com/backend"},

    # ── Usa_left ─────────────────────────────────────────────
    {"name": "Monthly Review",         "url": "http://monthlyreview.org/feed"},
    {"name": "Vox",                    "url": "http://www.vox.com/rss/index.xml"},
    {"name": "The Nation",             "url": "http://www.thenation.com/rss/articles"},
    {"name": "Jacobin",                "url": "http://jacobinmag.com/feed/"},

    # ── Left ─────────────────────────────────────────────────
    {"name": "Tribune",                "url": "https://tribunemag.co.uk/feed/"},
]
