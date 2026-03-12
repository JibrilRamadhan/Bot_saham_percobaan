"""
bot.py - Main Entry Point: Bot Telegram IHSG Radar & AI Screener
================================================================
File utama yang mengintegrasikan semua modul dan menjalankan bot Telegram.

Fitur utama:
1. RADAR OTOMATIS: Background job setiap 15 menit selama jam bursa (09:00-16:00 WIB)
   - Scan semua saham di watchlist
   - Deteksi sinyal teknikal (EMA Crossover + Volume Surge + RSI)
   - Validasi dengan sentimen AI (Gemini)
   - Kirim notifikasi ke Telegram jika sinyal valid + sentimen Bullish/Neutral

2. COMMAND INTERAKTIF:
   - /start  : Tampilkan menu dan info bot
   - /screening [KODE] : Analisa lengkap on-demand untuk satu saham
   - /watchlist : Tampilkan daftar saham pantauan
   - /radar [on/off] : Toggle radar otomatis (admin)
   - /help   : Bantuan dan panduan penggunaan
"""

import asyncio
import logging
import html
from datetime import datetime, time as dtime

import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
from telegram.constants import ParseMode

import config
from config import validate_config, WIB
from data_fetcher import full_screening, format_ticker, get_clean_code
from news_scraper import get_news_for_stock
from ai_analyzer import analyze_sentiment, is_signal_approved

# ----------------------------------------------------------------
# KONFIGURASI LOGGING
# ----------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
# Kurangi noise dari library pihak ketiga
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("yfinance").setLevel(logging.WARNING)
logging.getLogger("peewee").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
# TEMPLATE PESAN TELEGRAM
# ----------------------------------------------------------------
EMOJI = {
    "rocket": "🚀", "chart_up": "📈", "chart_down": "📉", "warning": "⚠️",
    "check": "✅", "cross": "❌", "target": "🎯", "fire": "🔥",
    "bell": "🔔", "news": "📰", "robot": "🤖", "clock": "🕐",
    "money": "💰", "radar": "📡", "star": "⭐", "info": "ℹ️",
    "bullish": "🟢", "bearish": "🔴", "neutral": "🟡",
}

SENTIMENT_EMOJI = {
    "Bullish": EMOJI["bullish"],
    "Bearish": EMOJI["bearish"],
    "Neutral": EMOJI["neutral"],
}

SENTIMENT_LABEL = {
    "Bullish": "BULLISH 📈",
    "Bearish": "BEARISH 📉",
    "Neutral": "NEUTRAL ➡️",
}


def format_number(n: float) -> str:
    """Format angka besar menjadi format Rupiah yang mudah dibaca."""
    if n >= 1_000_000_000_000:
        return f"{n/1_000_000_000_000:.1f}T"
    elif n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}M"
    elif n >= 1_000_000:
        return f"{n/1_000_000:.1f}jt"
    elif n >= 1_000:
        return f"{n/1_000:.1f}rb"
    return f"{n:.0f}"


def build_signal_alert_message(screening_data: dict, sentiment_data: dict) -> str:
    """
    Membuat pesan notifikasi sinyal lengkap untuk dikirim ke Telegram.
    
    Args:
        screening_data: Hasil dari data_fetcher.full_screening()
        sentiment_data: Hasil dari ai_analyzer.analyze_sentiment()
        
    Returns:
        String pesan HTML yang siap dikirim ke Telegram.
    """
    kode = screening_data["kode"]
    nama = html.escape(screening_data.get("nama_perusahaan", kode))
    harga = screening_data["harga_terakhir"]
    perubahan = screening_data["perubahan_pct"]
    kondisi = screening_data["kondisi"]
    pivot = screening_data.get("pivot_points", {})
    sentimen = sentiment_data.get("sentimen", "Neutral")
    alasan = html.escape(sentiment_data.get("alasan_singkat", ""))
    skor = sentiment_data.get("skor_keyakinan", 0)

    perubahan_emoji = EMOJI["chart_up"] if perubahan >= 0 else EMOJI["chart_down"]
    perubahan_str = f"{perubahan:+.2f}%"
    waktu_wib = datetime.now(WIB).strftime("%H:%M WIB")

    rsi_val = kondisi["rsi"]["nilai"]
    vol_ratio = kondisi["volume"]["rasio"]

    msg = f"""
{EMOJI["bell"]} <b>SINYAL RADAR TERDETEKSI!</b> {EMOJI["fire"]}
━━━━━━━━━━━━━━━━━━━━━━━━

{EMOJI["chart_up"]} <b>{kode}</b> | <i>{nama}</i>
{EMOJI["money"]} Harga: <code>Rp {harga:,.0f}</code> {perubahan_emoji} {perubahan_str}

━━━━━━━━━━━━━━━━━━━━━━━━
🔎 <b>ANALISA TEKNIKAL</b>
━━━━━━━━━━━━━━━━━━━━━━━━
{EMOJI["check"]} EMA Crossover: <b>YA</b> (EMA{config.EMA_FAST} menembus EMA{config.EMA_SLOW} ke atas)
   └ EMA{config.EMA_FAST}: <code>{kondisi['crossover']['ema_fast_sekarang']:,.2f}</code> | EMA{config.EMA_SLOW}: <code>{kondisi['crossover']['ema_slow_sekarang']:,.2f}</code>

{EMOJI["fire"]} Volume Surge: <b>YA</b> (×{vol_ratio:.1f} di atas rata-rata)
   └ Vol: <code>{format_number(kondisi['volume']['volume_sekarang'])}</code> | SMA: <code>{format_number(kondisi['volume']['volume_sma'])}</code>

{EMOJI["check"]} RSI: <b>{rsi_val:.1f}</b> ({'Aman ✓' if rsi_val < 70 else 'Overbought ⚠️'})

━━━━━━━━━━━━━━━━━━━━━━━━
{EMOJI["robot"]} <b>ANALISA FUNDAMENTAL AI</b>
━━━━━━━━━━━━━━━━━━━━━━━━
{SENTIMENT_EMOJI.get(sentimen, '⚪')} Sentimen: <b>{SENTIMENT_LABEL.get(sentimen, sentimen)}</b>
{EMOJI["star"]} Keyakinan AI: <b>{skor}/10</b>
{EMOJI["news"]} Analisa: <i>{alasan}</i>

━━━━━━━━━━━━━━━━━━━━━━━━
{EMOJI["target"]} <b>LEVEL KUNCI (Pivot Point)</b>
━━━━━━━━━━━━━━━━━━━━━━━━
🔴 R2: <code>Rp {pivot.get('R2', 0):,.0f}</code>
🟠 R1: <code>Rp {pivot.get('R1', 0):,.0f}</code>
⚪ PP: <code>Rp {pivot.get('PP', 0):,.0f}</code>
🟢 S1: <code>Rp {pivot.get('S1', 0):,.0f}</code>
🔵 S2: <code>Rp {pivot.get('S2', 0):,.0f}</code>

{EMOJI["clock"]} Waktu: {waktu_wib}
{EMOJI["info"]} <i>⚠️ Ini bukan rekomendasi beli/jual. DYOR!</i>
""".strip()
    return msg


def build_screening_message(screening_data: dict, sentiment_data: dict, headlines: list[str]) -> str:
    """
    Membuat pesan hasil screening lengkap untuk command /screening.
    """
    kode = screening_data["kode"]
    nama = html.escape(screening_data.get("nama_perusahaan", kode))
    harga = screening_data["harga_terakhir"]
    perubahan = screening_data["perubahan_pct"]
    kondisi = screening_data["kondisi"]
    pivot = screening_data.get("pivot_points", {})
    sentimen = sentiment_data.get("sentimen", "Neutral")
    alasan = html.escape(sentiment_data.get("alasan_singkat", ""))
    skor = sentiment_data.get("skor_keyakinan", 0)
    sinyal_valid = screening_data.get("sinyal_valid", False)

    perubahan_emoji = EMOJI["chart_up"] if perubahan >= 0 else EMOJI["chart_down"]
    perubahan_str = f"{perubahan:+.2f}%"
    waktu_wib = datetime.now(WIB).strftime("%d %b %Y, %H:%M WIB")

    rsi_val = kondisi["rsi"]["nilai"]
    vol_ratio = kondisi["volume"]["rasio"]

    # Status EMA
    ema_fast = kondisi["crossover"]["ema_fast_sekarang"]
    ema_slow = kondisi["crossover"]["ema_slow_sekarang"]
    ema_status = f"{EMOJI['check']} EMA{config.EMA_FAST} di atas EMA{config.EMA_SLOW}" if ema_fast > ema_slow else f"{EMOJI['cross']} EMA{config.EMA_FAST} di bawah EMA{config.EMA_SLOW}"

    # Volume status
    vol_status = f"{EMOJI['fire']} SURGE (×{vol_ratio:.1f})" if kondisi["volume"]["status"] else f"{EMOJI['warning']} Normal (×{vol_ratio:.1f})"

    # RSI status
    if rsi_val < 30:
        rsi_status = f"{EMOJI['bullish']} OVERSOLD ({rsi_val:.1f}) - Peluang Beli"
    elif rsi_val > 70:
        rsi_status = f"{EMOJI['bearish']} OVERBOUGHT ({rsi_val:.1f}) - Hati-hati"
    else:
        rsi_status = f"{EMOJI['neutral']} Normal ({rsi_val:.1f})"

    # Sinyal keseluruhan
    if sinyal_valid and sentimen in ("Bullish", "Neutral"):
        sinyal_overall = f"{EMOJI['rocket']} <b>POTENSI ENTRY</b> - Semua kondisi terpenuhi!"
    elif sinyal_valid and sentimen == "Bearish":
        sinyal_overall = f"{EMOJI['warning']} <b>WASPADA</b> - Teknikal bullish namun sentimen negatif"
    elif not sinyal_valid:
        sinyal_overall = f"{EMOJI['clock']} <b>TUNGGU</b> - Belum ada crossover yang valid"
    else:
        sinyal_overall = f"{EMOJI['info']} <b>PANTAU</b>"

    # Berita terbaru
    berita_str = ""
    if headlines:
        berita_list = "\n".join(f"  • {html.escape(h[:80])}{'...' if len(h) > 80 else ''}" for h in headlines[:3])
        berita_str = f"""
{EMOJI["news"]} <b>BERITA TERBARU</b>
{berita_list}

"""

    msg = f"""
{EMOJI["radar"]} <b>SCREENING: {kode}</b> | <i>{nama}</i>
━━━━━━━━━━━━━━━━━━━━━━━━

{EMOJI["money"]} Harga: <code>Rp {harga:,.0f}</code> {perubahan_emoji} {perubahan_str}

━━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>INDIKATOR TEKNIKAL</b>
━━━━━━━━━━━━━━━━━━━━━━━━
📉 {ema_status}
   └ EMA{config.EMA_FAST}: <code>{ema_fast:,.2f}</code> | EMA{config.EMA_SLOW}: <code>{ema_slow:,.2f}</code>

📊 Volume: {vol_status}
   └ Saat ini: <code>{format_number(kondisi['volume']['volume_sekarang'])}</code> | Avg: <code>{format_number(kondisi['volume']['volume_sma'])}</code>

💹 RSI: {rsi_status}

━━━━━━━━━━━━━━━━━━━━━━━━
{EMOJI["robot"]} <b>ANALISA AI</b>
━━━━━━━━━━━━━━━━━━━━━━━━
{SENTIMENT_EMOJI.get(sentimen, '⚪')} Sentimen: <b>{SENTIMENT_LABEL.get(sentimen, sentimen)}</b> ({skor}/10)
💬 <i>{alasan}</i>
{berita_str}
━━━━━━━━━━━━━━━━━━━━━━━━
{EMOJI["target"]} <b>SUPPORT & RESISTANCE</b>
━━━━━━━━━━━━━━━━━━━━━━━━
🔴 R2: <code>Rp {pivot.get('R2', 0):,.0f}</code>
🟠 R1: <code>Rp {pivot.get('R1', 0):,.0f}</code>
⚪ PP: <code>Rp {pivot.get('PP', 0):,.0f}</code>
🟢 S1: <code>Rp {pivot.get('S1', 0):,.0f}</code>
🔵 S2: <code>Rp {pivot.get('S2', 0):,.0f}</code>

━━━━━━━━━━━━━━━━━━━━━━━━
🏁 <b>KESIMPULAN:</b> {sinyal_overall}
━━━━━━━━━━━━━━━━━━━━━━━━

{EMOJI["clock"]} {waktu_wib}
{EMOJI["info"]} <i>⚠️ Bukan rekomendasi beli/jual. DYOR!</i>
""".strip()
    return msg


# ----------------------------------------------------------------
# COMMAND HANDLERS
# ----------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk command /start - Menampilkan halaman selamat datang."""
    user = update.effective_user
    nama = user.first_name if user else "Trader"

    keyboard = [
        [
            InlineKeyboardButton("📡 Watchlist", callback_data="watchlist"),
            InlineKeyboardButton("❓ Bantuan", callback_data="help"),
        ],
        [
            InlineKeyboardButton("📊 Contoh Screening BBCA", callback_data="screen_BBCA"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    pesan = f"""
{EMOJI["rocket"]} <b>Selamat datang, {html.escape(nama)}!</b>

{EMOJI["radar"]} <b>IHSG Radar Bot & AI Screener</b>
Asisten pribadi pantau pasar saham Indonesia.

━━━━━━━━━━━━━━━━━━━━━━━━
{EMOJI["star"]} <b>KEMAMPUAN BOT</b>
━━━━━━━━━━━━━━━━━━━━━━━━
{EMOJI["bell"]} <b>Radar Otomatis</b> — Scan setiap 15 menit jam bursa
{EMOJI["chart_up"]} <b>Teknikal</b> — EMA Crossover, Volume Surge, RSI
{EMOJI["robot"]} <b>AI Analyst</b> — Sentimen berita via Gemini AI
{EMOJI["target"]} <b>Support & Resistance</b> — Pivot Point Klasik

━━━━━━━━━━━━━━━━━━━━━━━━
📋 <b>PERINTAH TERSEDIA</b>
━━━━━━━━━━━━━━━━━━━━━━━━
/screening [KODE] — Analisa lengkap saham
  <i>Contoh: /screening INET</i>

/watchlist — Daftar saham radar otomatis

/help — Panduan dan tips penggunaan

━━━━━━━━━━━━━━━━━━━━━━━━
{EMOJI["info"]} Bot akan mengirim alert otomatis saat mendeteksi sinyal kuat!
""".strip()

    await update.message.reply_text(pesan, parse_mode=ParseMode.HTML, reply_markup=reply_markup)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk command /help - Menampilkan panduan penggunaan."""
    pesan = f"""
{EMOJI["info"]} <b>PANDUAN PENGGUNAAN</b>
━━━━━━━━━━━━━━━━━━━━━━━━

{EMOJI["chart_up"]} <b>Cara Screening Saham:</b>
Ketik: <code>/screening KODE_SAHAM</code>
Contoh: <code>/screening INET</code>
Bot akan otomatis menambahkan .JK

━━━━━━━━━━━━━━━━━━━━━━━━
{EMOJI["bell"]} <b>Cara Kerja Radar:</b>
1. Bot scan saham setiap 15 menit
2. Cek 3 kondisi teknikal:
   • EMA{config.EMA_FAST} crossover EMA{config.EMA_SLOW} ↗️
   • Volume > {config.VOLUME_SURGE_MULTIPLIER}× rata-rata {EMOJI["fire"]}
   • RSI &lt; {config.RSI_OVERBOUGHT} (tidak overbought)
3. Jika valid → Cek sentimen berita via AI
4. Kirim alert jika sentimen Bullish/Neutral

━━━━━━━━━━━━━━━━━━━━━━━━
{EMOJI["robot"]} <b>Tentang AI Analyst:</b>
Bot menggunakan Google Gemini AI untuk membaca
dan menganalisa headline berita terbaru.
Sentimen Bearish = sinyal diabaikan (filter pelindung).

━━━━━━━━━━━━━━━━━━━━━━━━
{EMOJI["target"]} <b>Level Support & Resistance:</b>
Dihitung menggunakan metode Pivot Point Klasik
berdasarkan data OHLC hari sebelumnya.

━━━━━━━━━━━━━━━━━━━━━━━━
{EMOJI["warning"]} <b>Disclaimer:</b>
Bot ini adalah alat bantu analisa.
BUKAN rekomendasi beli atau jual saham.
Selalu lakukan riset mandiri (DYOR).
""".strip()

    await update.message.reply_text(pesan, parse_mode=ParseMode.HTML)


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk command /watchlist - Menampilkan saham yang dipantau."""
    watchlist_str = "\n".join(
        f"  {i+1}. <code>{kode}</code>" for i, kode in enumerate(config.WATCHLIST)
    )
    pesan = f"""
{EMOJI["radar"]} <b>WATCHLIST RADAR</b>
━━━━━━━━━━━━━━━━━━━━━━━━

Saham yang dipantau radar otomatis:
{watchlist_str}

{EMOJI["clock"]} Interval Scan: Setiap <b>{config.RADAR_INTERVAL_MINUTES} menit</b>
{EMOJI["chart_up"]} Jam Aktif: <b>09:00 - 16:00 WIB</b>

{EMOJI["info"]} Gunakan /screening [KODE] untuk analisa saham manapun.
""".strip()
    await update.message.reply_text(pesan, parse_mode=ParseMode.HTML)


async def cmd_screening(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler untuk command /screening [KODE_SAHAM].
    Melakukan analisa lengkap on-demand untuk satu saham.
    """
    # Validasi input
    if not context.args:
        await update.message.reply_text(
            f"{EMOJI['warning']} Mohon sertakan kode saham.\n"
            f"Contoh: <code>/screening INET</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    kode_input = context.args[0].strip().upper().replace(".JK", "")

    # Kirim pesan "typing" indicator
    await update.message.reply_chat_action("typing")

    # Kirim pesan loading sementara
    loading_msg = await update.message.reply_text(
        f"{EMOJI['clock']} Sedang menganalisa <b>{kode_input}</b>...\n"
        f"Mengambil data & berita terbaru {EMOJI['radar']}",
        parse_mode=ParseMode.HTML,
    )

    try:
        # 1. Ambil data & kalkulasi teknikal
        screening_data = await asyncio.get_event_loop().run_in_executor(
            None, full_screening, kode_input
        )

        if screening_data is None:
            await loading_msg.edit_text(
                f"{EMOJI['cross']} Gagal mengambil data untuk <b>{kode_input}</b>.\n\n"
                f"Kemungkinan penyebab:\n"
                f"• Kode saham tidak valid\n"
                f"• Server yfinance timeout\n"
                f"• Saham tidak terdaftar di BEI\n\n"
                f"Pastikan menggunakan kode saham BEI yang valid.",
                parse_mode=ParseMode.HTML,
            )
            return

        # 2. Ambil berita terbaru
        headlines = await asyncio.get_event_loop().run_in_executor(
            None, get_news_for_stock, kode_input
        )

        # 3. Analisa sentimen AI
        sentiment_data = await asyncio.get_event_loop().run_in_executor(
            None, analyze_sentiment, kode_input, headlines
        )

        # 4. Buat & kirim pesan hasil screening
        pesan = build_screening_message(screening_data, sentiment_data, headlines)
        await loading_msg.edit_text(pesan, parse_mode=ParseMode.HTML)

        logger.info(f"[BOT] Screening berhasil untuk {kode_input}")

    except Exception as e:
        logger.error(f"[BOT] Error saat screening {kode_input}: {e}")
        await loading_msg.edit_text(
            f"{EMOJI['cross']} Terjadi error saat menganalisa <b>{kode_input}</b>.\n"
            f"Silakan coba lagi dalam beberapa saat.",
            parse_mode=ParseMode.HTML,
        )


# ----------------------------------------------------------------
# CALLBACK QUERY HANDLER (untuk tombol inline keyboard)
# ----------------------------------------------------------------
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Menangani tombol inline keyboard dari pesan bot."""
    query = update.callback_query
    await query.answer()

    if query.data == "watchlist":
        await query.message.reply_chat_action("typing")
        await cmd_watchlist(update._replace(message=query.message), context)

    elif query.data == "help":
        await cmd_help(update._replace(message=query.message), context)

    elif query.data.startswith("screen_"):
        kode = query.data.replace("screen_", "")
        context.args = [kode]
        await query.message.reply_chat_action("typing")
        # Simulasikan command /screening
        upd_mock = update._replace(message=query.message)
        await cmd_screening(upd_mock, context)


# ----------------------------------------------------------------
# BACKGROUND JOB: RADAR OTOMATIS
# ----------------------------------------------------------------
def is_market_open() -> bool:
    """Memeriksa apakah saat ini adalah jam bursa BEI (09:00 - 16:00 WIB, Senin-Jumat)."""
    now_wib = datetime.now(WIB)
    # Periksa hari kerja (0=Senin, 4=Jumat)
    if now_wib.weekday() >= 5:  # Sabtu atau Minggu
        return False
    # Periksa jam bursa
    open_time = dtime(config.MARKET_OPEN_HOUR, 0)
    close_time = dtime(config.MARKET_CLOSE_HOUR, 0)
    current_time = now_wib.time()
    return open_time <= current_time <= close_time


async def radar_scan_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Background job yang dijalankan secara berkala oleh scheduler.
    Scan semua saham di watchlist dan kirim alert jika ada sinyal valid.
    """
    if not is_market_open():
        logger.info("[RADAR] Bursa tutup, scan dilewati.")
        return

    waktu_sekarang = datetime.now(WIB).strftime("%H:%M WIB")
    logger.info(f"[RADAR] 🔍 Mulai scan {len(config.WATCHLIST)} saham pukul {waktu_sekarang}")

    sinyal_ditemukan = 0

    for kode_saham in config.WATCHLIST:
        try:
            logger.info(f"[RADAR] Memproses: {kode_saham}")

            # 1. Ambil & kalkulasi data teknikal
            screening_data = await asyncio.get_event_loop().run_in_executor(
                None, full_screening, kode_saham
            )

            if screening_data is None:
                logger.warning(f"[RADAR] Skip {kode_saham}: data tidak tersedia")
                continue

            # 2. Cek apakah sinyal teknikal valid
            if not screening_data.get("sinyal_valid", False):
                logger.info(f"[RADAR] {kode_saham}: Tidak ada sinyal teknikal")
                continue

            logger.info(f"[RADAR] 🔔 Sinyal teknikal terdeteksi untuk {kode_saham}! Cek fundamental...")

            # 3. Ambil berita terbaru (hanya jika sinyal teknikal valid)
            headlines = await asyncio.get_event_loop().run_in_executor(
                None, get_news_for_stock, kode_saham
            )

            # 4. Analisa sentimen berita via Gemini AI
            sentiment_data = await asyncio.get_event_loop().run_in_executor(
                None, analyze_sentiment, kode_saham, headlines
            )

            # 5. Filter: Hanya kirim jika sentimen Bullish atau Neutral
            if not is_signal_approved(sentiment_data):
                sentimen = sentiment_data.get("sentimen", "Bearish")
                logger.info(
                    f"[RADAR] ⛔ Sinyal {kode_saham} difilter (sentimen: {sentimen}). "
                    f"Filter pelindung aktif."
                )
                continue

            # 6. Kirim notifikasi ke Telegram!
            pesan = build_signal_alert_message(screening_data, sentiment_data)
            await context.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=pesan,
                parse_mode=ParseMode.HTML,
            )
            sinyal_ditemukan += 1
            logger.info(f"[RADAR] ✅ Alert terkirim untuk {kode_saham}")

            # Jeda antar saham untuk menghindari rate limit
            await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"[RADAR] Error saat memproses {kode_saham}: {e}")
            continue

    logger.info(f"[RADAR] Scan selesai. {sinyal_ditemukan} sinyal ditemukan dari {len(config.WATCHLIST)} saham.")


# ----------------------------------------------------------------
# SETUP & RUN BOT
# ----------------------------------------------------------------
async def post_init(application: Application) -> None:
    """Fungsi yang dipanggil setelah bot berhasil diinisialisasi."""
    logger.info("[BOT] ✅ Bot berhasil terhubung ke Telegram.")

    # Set daftar perintah yang muncul di Telegram
    commands = [
        BotCommand("start", "Mulai dan tampilkan menu utama"),
        BotCommand("screening", "Analisa lengkap saham (contoh: /screening INET)"),
        BotCommand("watchlist", "Tampilkan daftar saham pantauan radar"),
        BotCommand("help", "Panduan dan tips penggunaan bot"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("[BOT] Daftar command berhasil di-set di Telegram.")


def main() -> None:
    """Fungsi utama: Inisialisasi dan jalankan bot Telegram."""
    # Validasi konfigurasi sebelum memulai
    validate_config()

    logger.info("[BOT] 🚀 Memulai IHSG Radar Bot & AI Screener...")
    logger.info(f"[BOT] 📋 Watchlist: {', '.join(config.WATCHLIST)}")
    logger.info(f"[BOT] ⏰ Radar setiap {config.RADAR_INTERVAL_MINUTES} menit (jam {config.MARKET_OPEN_HOUR}:00 - {config.MARKET_CLOSE_HOUR}:00 WIB)")

    # Buat aplikasi bot dengan JobQueue untuk scheduler
    application = (
        ApplicationBuilder()
        .token(config.TELEGRAM_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Daftarkan semua command handler
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("watchlist", cmd_watchlist))
    application.add_handler(CommandHandler("screening", cmd_screening))
    application.add_handler(CallbackQueryHandler(handle_callback))

    # Setup job scheduler (radar otomatis)
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            callback=radar_scan_job,
            interval=config.RADAR_INTERVAL_MINUTES * 60,  # Konversi ke detik
            first=10,  # Mulai 10 detik setelah bot aktif
            name="radar_scan",
        )
        logger.info(f"[BOT] ⏰ Radar dijadwalkan setiap {config.RADAR_INTERVAL_MINUTES} menit.")
    else:
        logger.warning("[BOT] ⚠️ JobQueue tidak tersedia! Radar otomatis tidak akan berjalan.")
        logger.warning("[BOT] Pastikan 'python-telegram-bot[job-queue]' sudah terinstall.")

    logger.info("[BOT] ✅ Bot siap! Tekan Ctrl+C untuk berhenti.")

    # Jalankan bot (blocking)
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,  # Abaikan update yang antri saat bot mati
    )


if __name__ == "__main__":
    main()
