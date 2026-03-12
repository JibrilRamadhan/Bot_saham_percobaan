"""
config.py - Konfigurasi Pusat & Environment Variables
======================================================
Memuat semua konfigurasi dari file .env menggunakan python-dotenv.
Semua modul lain mengimpor konfigurasi dari sini.
"""

import os
import pytz
from dotenv import load_dotenv

# Muat variabel dari file .env
load_dotenv()

# -------------------------------------------------------
# KONFIGURASI TELEGRAM
# -------------------------------------------------------
TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# -------------------------------------------------------
# KONFIGURASI GEMINI API
# -------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = "gemini-1.5-flash"  # Model cepat & hemat token untuk analisa berita

# -------------------------------------------------------
# KONFIGURASI WATCHLIST SAHAM
# -------------------------------------------------------
# Daftar saham yang akan dipantau secara otomatis oleh radar
WATCHLIST: list[str] = [
    "BBCA",  # Bank Central Asia
    "TLKM",  # Telkom Indonesia
    "SIDO",  # Sidomuncul
    "INET",  # Indointernet
    "AMMN",  # Amman Mineral
    "BREN",  # Barito Renewables
]

# -------------------------------------------------------
# KONFIGURASI ANALISA TEKNIKAL
# -------------------------------------------------------
# Parameter indikator
EMA_FAST: int = 5       # EMA periode cepat
EMA_SLOW: int = 13      # EMA periode lambat
RSI_PERIOD: int = 14    # RSI periode standar
VOLUME_SMA: int = 20    # SMA volume untuk deteksi surge

# Threshold sinyal
RSI_OVERBOUGHT: float = 70.0     # RSI di atas ini = overbought, abaikan sinyal beli
VOLUME_SURGE_MULTIPLIER: float = 2.0  # Volume harus > 2x rata-rata untuk trigger

# Parameter yfinance
YFINANCE_INTERVAL: str = "15m"   # Interval data: 15 menit
YFINANCE_PERIOD: str = "5d"      # Periode data: 5 hari terakhir

# -------------------------------------------------------
# KONFIGURASI JADWAL RADAR
# -------------------------------------------------------
WIB = pytz.timezone("Asia/Jakarta")
MARKET_OPEN_HOUR: int = int(os.getenv("MARKET_OPEN_HOUR", "9"))
MARKET_CLOSE_HOUR: int = int(os.getenv("MARKET_CLOSE_HOUR", "16"))
RADAR_INTERVAL_MINUTES: int = int(os.getenv("RADAR_INTERVAL_MINUTES", "15"))

# -------------------------------------------------------
# KONFIGURASI SCRAPER BERITA
# -------------------------------------------------------
# RSS Feed dari berbagai portal berita keuangan Indonesia
NEWS_RSS_FEEDS: list[dict] = [
    {
        "nama": "CNBC Indonesia",
        "url": "https://www.cnbcindonesia.com/rss/market",
    },
    {
        "nama": "Kontan",
        "url": "https://www.kontan.co.id/rss/investasi.rss",
    },
    {
        "nama": "Yahoo Finance ID",
        "url": "https://finance.yahoo.com/rss/headline?s={ticker}",  # {ticker} = placeholder
    },
    {
        "nama": "Bisnis.com",
        "url": "https://market.bisnis.com/rss/feed.aspx?category=market",
    },
]

# Jumlah berita yang akan diambil per saham
MAX_NEWS_ARTICLES: int = 5

# -------------------------------------------------------
# VALIDASI KONFIGURASI MINIMUM
# -------------------------------------------------------
def validate_config() -> None:
    """Memvalidasi bahwa semua konfigurasi wajib sudah terisi."""
    errors = []
    if not TELEGRAM_TOKEN:
        errors.append("TELEGRAM_TOKEN belum diset di file .env")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID belum diset di file .env")
    if not GEMINI_API_KEY:
        errors.append("GEMINI_API_KEY belum diset di file .env")

    if errors:
        error_msg = "\n".join(f"  ❌ {e}" for e in errors)
        raise EnvironmentError(
            f"[CONFIG] Konfigurasi tidak lengkap:\n{error_msg}\n"
            f"Salin .env.example ke .env dan isi nilainya."
        )
    print("[CONFIG] ✅ Semua konfigurasi berhasil dimuat.")


if __name__ == "__main__":
    validate_config()
