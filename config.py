# ============================================================
#  NEWS SOURCES CONFIGURATION
#  Replace the example RSS feed URLs below with your 17 sites.
#  Each entry: { "name": "Display Name", "url": "RSS Feed URL" }
# ============================================================
import os
DEEPL_API_KEY = os.environ.get("DEEPL_API_KEY", "YOUR_DEEPL_API_KEY_HERE")                        # Turkish
TARGET_LANGUAGE = "TR"
RSS_FEEDS = [
    {"name": "Reuters",             "url": "https://feeds.reuters.com/reuters/topNews"},
    {"name": "BBC News",            "url": "http://feeds.bbci.co.uk/news/rss.xml"},
    {"name": "Al Jazeera",          "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "AP News",             "url": "https://rsshub.app/apnews/topics/apf-topnews"},
    {"name": "The Guardian",        "url": "https://www.theguardian.com/world/rss"},
    {"name": "DW News",             "url": "https://rss.dw.com/rdf/rss-en-all"},
    {"name": "France 24",           "url": "https://www.france24.com/en/rss"},
    {"name": "Euronews",            "url": "https://www.euronews.com/rss"},
    {"name": "Site 9",              "url": "https://example.com/rss"},   # <-- replace
    {"name": "Site 10",             "url": "https://example.com/rss"},   # <-- replace
    {"name": "Site 11",             "url": "https://example.com/rss"},   # <-- replace
    {"name": "Site 12",             "url": "https://example.com/rss"},   # <-- replace
    {"name": "Site 13",             "url": "https://example.com/rss"},   # <-- replace
    {"name": "Site 14",             "url": "https://example.com/rss"},   # <-- replace
    {"name": "Site 15",             "url": "https://example.com/rss"},   # <-- replace
    {"name": "Site 16",             "url": "https://example.com/rss"},   # <-- replace
    {"name": "Site 17",             "url": "https://example.com/rss"},   # <-- replace
]
