# 📰 Haber Çevirici — Kurulum ve Kullanım

## Proje Yapısı

```
news_translator/
├── app.py            ← Flask uygulaması (ana kod)
├── config.py         ← API anahtarı + 17 site URL'si buraya
├── requirements.txt  ← Python bağımlılıkları
├── templates/
│   └── index.html    ← Web arayüzü
└── output/           ← Oluşturulan .docx dosyaları burada saklanır
```

---

## 1. Kurulum

```bash
# Klasöre gir
cd news_translator

# Sanal ortam oluştur (tavsiye edilir)
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# Bağımlılıkları yükle
pip install -r requirements.txt
```

---

## 2. Yapılandırma

`config.py` dosyasını aç ve şunları düzenle:

### DeepL API Anahtarı
```python
DEEPL_API_KEY = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:fx"
```
→ DeepL API anahtarını https://www.deepl.com/pro-api adresinden ücretsiz alabilirsin.

### 17 Haber Sitesi
```python
RSS_FEEDS = [
    {"name": "Site Adı",  "url": "https://siteadi.com/rss"},
    ...
]
```
Her sitenin RSS/Atom feed URL'sini bulun ve listeye ekleyin.

**İpucu:** Bir sitenin RSS feed'ini bulmak için genellikle:
- `https://siteadi.com/rss`
- `https://siteadi.com/feed`
- `https://siteadi.com/rss.xml`
adreslerini deneyin.

---

## 3. Çalıştırma

```bash
python app.py
```

Tarayıcıda şu adrese git: **http://localhost:5000**

---

## 4. Kullanım Akışı

1. **"Haberleri Getir"** düğmesine bas → Tüm sitelerden son haberler yüklenir
2. Başlık arama kutusunu kullanarak haberleri filtrele
3. Çevirmek istediğin haberleri **işaretle** (checkbox)
4. **"Çevir & İndir (.docx)"** düğmesine bas
5. DeepL otomatik çevirir → .docx dosyası indirilir

---

## Notlar

- DeepL ücretsiz planda aylık **500.000 karakter** çeviri yapabilirsin.
- Makaleler her seferinde canlı olarak çekilir; eski haberler kaybolabilir.
- `output/` klasöründe tüm oluşturulan belgeler saklanır.
