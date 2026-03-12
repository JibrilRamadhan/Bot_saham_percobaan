# IHSG Radar Bot & AI Screener
## Bot Telegram Asisten Pribadi Pasar Saham Indonesia

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 📋 Deskripsi

Bot Telegram yang berfungsi sebagai **radar pasar saham Indonesia (IHSG)** yang menggabungkan:
- **Analisa Teknikal** (EMA Crossover, Volume Surge, RSI) menggunakan `pandas_ta`
- **Analisa Fundamental** (Sentimen Berita AI) menggunakan **Google Gemini API**
- **Notifikasi Otomatis** setiap 15 menit pada jam bursa (09:00–16:00 WIB)
- **Screening Interaktif** on-demand via command Telegram

> ⚠️ **Disclaimer**: Bot ini hanya alat bantu analisa. **BUKAN** rekomendasi beli/jual saham. Selalu lakukan riset mandiri (DYOR).

---

## 🗂️ Struktur File

```
BotScalpingTele/
├── bot.py              # Entry point utama, handler komando Telegram & scheduler
├── config.py           # Konfigurasi & environment variables
├── data_fetcher.py     # Fetch data yfinance + kalkulasi indikator teknikal
├── news_scraper.py     # Scraper berita dari RSS feed portal keuangan Indonesia
├── ai_analyzer.py      # Integrasi Gemini API untuk analisa sentimen berita
├── requirements.txt    # Daftar dependensi Python
├── .env.example        # Template file environment variables
├── .env                # (Buat sendiri) File konfigurasi pribadi Anda
└── README.md           # Dokumentasi ini
```

---

## ⚡ Cara Instalasi & Setup

### 1. Clone / Download Project

```bash
# Jika menggunakan git
git clone <url-repository>
cd BotScalpingTele

# Atau cukup download dan ekstrak folder
```

### 2. Buat Virtual Environment (Disarankan)

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependensi

```bash
pip install -r requirements.txt
```

> **Catatan**: Jika `pandas-ta` gagal install, coba:
> ```bash
> pip install pandas-ta --no-build-isolation
> ```

### 4. Buat File `.env`

Salin file template dan isi dengan credential Anda:

```bash
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

Buka `.env` dan isi variabel berikut:

```env
TELEGRAM_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
GEMINI_API_KEY=your_gemini_api_key_here
```

### 5. Cara Mendapatkan Credentials

#### 🤖 Telegram Bot Token
1. Buka Telegram, cari **@BotFather**
2. Ketik `/newbot` dan ikuti instruksinya
3. Salin token yang diberikan ke `TELEGRAM_TOKEN`

#### 💬 Telegram Chat ID
1. Buka Telegram, cari **@userinfobot**
2. Ketik `/start` — bot akan menampilkan ID Anda
3. Salin ID ke `TELEGRAM_CHAT_ID`

> Untuk mengirim ke grup: tambahkan bot ke grup, lalu gunakan ID grup (diawali `-`)

#### 🧠 Gemini API Key
1. Buka [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Klik **"Create API Key"**
3. Salin key ke `GEMINI_API_KEY`

---

## 🚀 Menjalankan Bot

```bash
python bot.py
```

Bot akan:
1. Memvalidasi semua konfigurasi
2. Terhubung ke Telegram
3. Menjadwalkan radar scan setiap 15 menit
4. Siap menerima command dari pengguna

---

## 📱 Perintah Telegram

| Command | Deskripsi | Contoh |
|---------|-----------|--------|
| `/start` | Tampilkan menu utama dan info bot | `/start` |
| `/screening [KODE]` | Analisa lengkap satu saham secara instan | `/screening INET` |
| `/watchlist` | Tampilkan daftar saham pantauan radar | `/watchlist` |
| `/help` | Panduan dan tips penggunaan | `/help` |

> **Tips**: Kode saham bisa ditulis tanpa `.JK` — bot otomatis menambahkannya.

---

## 🔥 Cara Kerja Radar Otomatis

```
Setiap 15 Menit (Jam 09:00 - 16:00 WIB)
          │
          ▼
[Scan Semua Saham Watchlist]
          │
          ▼
┌─────────────────────────────────────┐
│  CEK 3 KONDISI TEKNIKAL (Semua harus│
│  terpenuhi):                        │
│  ✅ EMA_5 crossover ke atas EMA_13  │
│  ✅ Volume > 2× rata-rata 20 candle  │
│  ✅ RSI_14 < 70 (tidak overbought)  │
└─────────────────────────────────────┘
          │ Jika Valid
          ▼
[Ambil 3-5 Berita Terbaru Saham]
          │
          ▼
[Analisa Sentimen via Gemini AI]
          │
          ├── Bullish/Neutral → ✅ KIRIM ALERT ke Telegram
          │
          └── Bearish → ⛔ ABAIKAN (filter pelindung aktif)
```

---

## ⚙️ Kustomisasi

Edit file `config.py` untuk menyesuaikan:

```python
# Daftar saham watchlist
WATCHLIST = ["BBCA", "TLKM", "SIDO", "INET", "AMMN", "BREN"]

# Parameter indikator teknikal
EMA_FAST = 5           # EMA periode cepat
EMA_SLOW = 13          # EMA periode lambat
RSI_PERIOD = 14        # RSI periode
VOLUME_SMA = 20        # SMA volume untuk deteksi surge
RSI_OVERBOUGHT = 70.0  # Batas RSI overbought
VOLUME_SURGE_MULTIPLIER = 2.0  # Threshold volume surge

# Jam bursa (diatur juga via .env)
MARKET_OPEN_HOUR = 9
MARKET_CLOSE_HOUR = 16
RADAR_INTERVAL_MINUTES = 15
```

---

## 🛠️ Troubleshooting

### Bot tidak mengirim notifikasi?
- Pastikan `TELEGRAM_CHAT_ID` sudah benar
- Coba `/start` pada chat bot terlebih dahulu (Telegram memblokir bot yang belum diinisialisasi)
- Periksa apakah bursa sedang buka (Senin-Jumat, 09:00-16:00 WIB)

### Error `yfinance` atau data kosong?
- Ini normal saat bursa tutup atau server YF sedang down
- Bot akan otomatis retry dan melanjutkan ke saham berikutnya

### Error Gemini API `quota exceeded`?
- Gunakan akun Google yang berbeda atau tunggu hingga quota reset (biasanya tengah malam)
- Bot memiliki mekanisme retry otomatis dengan jeda waktu

### `pandas-ta` tidak bisa diinstall?
```bash
pip install --upgrade pip setuptools wheel
pip install pandas-ta --no-build-isolation
```

---

## 📦 Dependensi Utama

| Library | Versi | Fungsi |
|---------|-------|--------|
| `python-telegram-bot` | ≥20.7 | Framework bot Telegram (async) |
| `yfinance` | ≥0.2.40 | Sumber data OHLCV saham |
| `pandas-ta` | ≥0.3.14b | Kalkulasi indikator teknikal |
| `google-generativeai` | ≥0.7.0 | Gemini API untuk analisa AI |
| `feedparser` | ≥6.0.10 | Parser RSS feed berita |
| `beautifulsoup4` | ≥4.12.0 | Web scraping halaman berita |
| `python-dotenv` | ≥1.0.0 | Manajemen environment variables |
| `pytz` | ≥2024.1 | Manajemen timezone WIB |

---

## 📄 Lisensi

MIT License — Bebas digunakan dan dimodifikasi untuk keperluan pribadi.
