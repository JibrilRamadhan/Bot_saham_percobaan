"""
ai_analyzer.py - Analisa Sentimen Berita menggunakan Gemini API
===============================================================
Modul ini bertanggung jawab untuk:
1. Mengirim headline berita ke Google Gemini API.
2. Mem-parsing respons JSON dari Gemini untuk mendapatkan sentimen.
3. Menerapkan error handling untuk rate limit dan API error.
"""

import json
import logging
import time
import re
from typing import Optional

from google import genai
from google.genai import types

import config

logger = logging.getLogger(__name__)

# Inisialisasi Gemini client dengan API Key dari konfigurasi
_client = None


def get_gemini_client() -> genai.Client:
    """Lazy initialization Gemini client untuk menghindari error di awal startup."""
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


# ----------------------------------------------------------------
# PROMPT SYSTEM UNTUK ANALISA SENTIMEN
# ----------------------------------------------------------------
SYSTEM_PROMPT = """Kamu adalah analis saham profesional yang ahli dalam pasar saham Indonesia (IHSG).
Tugasmu adalah menganalisa sentimen berita saham berdasarkan headline yang diberikan.

ATURAN:
- Jawab HANYA dengan format JSON yang valid, tidak ada teks lain di luar JSON.
- Nilai 'sentimen' HANYA boleh berisi salah satu dari: "Bullish", "Bearish", atau "Neutral".
- 'alasan_singkat' berisi penjelasan singkat maksimal 2 kalimat dalam Bahasa Indonesia.
- 'skor_keyakinan' adalah angka 1-10 yang menunjukkan seberapa yakin kamu dengan analisa ini.

FORMAT JSON WAJIB:
{
  "sentimen": "Bullish/Bearish/Neutral",
  "alasan_singkat": "Penjelasan singkat tentang sentimen",
  "skor_keyakinan": 8,
  "kata_kunci": ["kata1", "kata2"]
}"""


# ----------------------------------------------------------------
# FUNGSI ANALISA SENTIMEN UTAMA
# ----------------------------------------------------------------
def analyze_sentiment(
    kode_saham: str,
    headlines: list[str],
    max_retry: int = 3,
) -> dict:
    """
    Menganalisa sentimen sekelompok headline berita menggunakan Gemini API.
    
    Args:
        kode_saham: Kode saham yang akan dianalisa (misal: 'INET').
        headlines: List judul berita yang akan dianalisa.
        max_retry: Jumlah maksimum percobaan ulang jika API error.
        
    Returns:
        Dictionary berisi:
            - 'sentimen': 'Bullish', 'Bearish', atau 'Neutral'
            - 'alasan_singkat': Penjelasan singkat analisa
            - 'skor_keyakinan': Skor keyakinan 1-10
            - 'kata_kunci': List kata kunci yang ditemukan
            - 'headlines_dianalisa': Jumlah headlines yang dianalisa
            
        Jika tidak ada berita atau error, mengembalikan sentimen 'Neutral'.
    """
    kode_bersih = kode_saham.upper().replace(".JK", "")

    # Jika tidak ada berita, kembalikan Neutral sebagai default aman
    if not headlines:
        logger.warning(f"[AI] Tidak ada berita untuk {kode_bersih}, defaulting ke Neutral")
        return {
            "sentimen": "Neutral",
            "alasan_singkat": "Tidak ada berita terbaru yang ditemukan untuk saham ini.",
            "skor_keyakinan": 3,
            "kata_kunci": [],
            "headlines_dianalisa": 0,
        }

    # Buat prompt dengan daftar headline
    numbered_headlines = "\n".join(
        f"{i+1}. {headline}" for i, headline in enumerate(headlines)
    )
    user_prompt = f"""Analisa sentimen untuk saham {kode_bersih} berdasarkan {len(headlines)} headline berita berikut:

{numbered_headlines}

Berikan analisa sentimen dalam format JSON sesuai instruksi."""

    # Kombinasikan prompt
    full_prompt = f"{SYSTEM_PROMPT}\n\n{user_prompt}"

    # Coba kirim ke Gemini API dengan retry
    for attempt in range(1, max_retry + 1):
        try:
            logger.info(f"[AI] Mengirim {len(headlines)} headline ke Gemini untuk {kode_bersih} (percobaan {attempt})")

            client = get_gemini_client()
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,      # Rendah agar respons konsisten & faktual
                    top_p=0.8,
                    max_output_tokens=500,
                ),
            )
            response_text = response.text.strip()

            # Parse JSON dari respons Gemini
            result = _parse_gemini_response(response_text)
            result["headlines_dianalisa"] = len(headlines)
            
            logger.info(f"[AI] ✅ Sentimen untuk {kode_bersih}: {result['sentimen']} (keyakinan: {result['skor_keyakinan']}/10)")
            return result

        except Exception as e:
            error_str = str(e).lower()
            
            # Handle rate limit secara khusus
            if "quota" in error_str or "rate" in error_str or "429" in error_str:
                wait_time = 60 * attempt  # Tunggu lebih lama setiap retry
                logger.warning(f"[AI] Rate limit tercapai, menunggu {wait_time}s... (percobaan {attempt}/{max_retry})")
                time.sleep(wait_time)
            else:
                logger.error(f"[AI] Error Gemini API (percobaan {attempt}/{max_retry}): {e}")
                if attempt < max_retry:
                    time.sleep(5 * attempt)

    # Jika semua percobaan gagal, kembalikan Neutral sebagai fallback aman
    logger.error(f"[AI] ❌ Semua percobaan API gagal untuk {kode_bersih}")
    return {
        "sentimen": "Neutral",
        "alasan_singkat": "Analisa AI tidak tersedia saat ini (error API). Sinyal teknikal tetap valid.",
        "skor_keyakinan": 0,
        "kata_kunci": [],
        "headlines_dianalisa": len(headlines),
    }


def _parse_gemini_response(response_text: str) -> dict:
    """
    Mem-parsing respons teks dari Gemini menjadi dictionary Python.
    Menangani kasus di mana Gemini membungkus JSON dalam markdown code block.
    
    Args:
        response_text: String respons mentah dari Gemini.
        
    Returns:
        Dictionary hasil parsing JSON.
        
    Raises:
        ValueError: Jika respons tidak bisa di-parse.
    """
    # Hapus markdown code block jika ada (```json ... ```)
    cleaned = re.sub(r"```(?:json)?\s*", "", response_text)
    cleaned = cleaned.replace("```", "").strip()

    # Coba parse JSON langsung
    try:
        data = json.loads(cleaned)
        return _validate_sentiment_response(data)
    except json.JSONDecodeError:
        pass

    # Fallback: cari pola JSON di dalam teks menggunakan regex
    json_match = re.search(r"\{.*?\}", cleaned, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return _validate_sentiment_response(data)
        except json.JSONDecodeError:
            pass

    # Terakhir: analisa teks manual jika JSON gagal total
    logger.warning(f"[AI] Gagal parse JSON, menganalisa teks secara manual: {response_text[:100]}...")
    return _extract_sentiment_from_text(response_text)


def _validate_sentiment_response(data: dict) -> dict:
    """
    Memvalidasi dan membersihkan respons JSON dari Gemini.
    Memastikan semua field yang dibutuhkan ada dan valid.
    """
    valid_sentiments = {"Bullish", "Bearish", "Neutral"}
    sentimen = data.get("sentimen", "Neutral")
    
    # Normalisasi capitalization
    for valid in valid_sentiments:
        if sentimen.lower() == valid.lower():
            sentimen = valid
            break
    else:
        sentimen = "Neutral"

    return {
        "sentimen": sentimen,
        "alasan_singkat": str(data.get("alasan_singkat", "Tidak ada keterangan.")),
        "skor_keyakinan": max(0, min(10, int(data.get("skor_keyakinan", 5)))),
        "kata_kunci": data.get("kata_kunci", []),
    }


def _extract_sentiment_from_text(text: str) -> dict:
    """
    Fallback: Ekstrak sentimen dari teks biasa jika parsing JSON gagal.
    Mencari kata kunci 'Bullish', 'Bearish', atau 'Neutral' dalam teks.
    """
    text_lower = text.lower()
    if "bullish" in text_lower:
        sentimen = "Bullish"
    elif "bearish" in text_lower:
        sentimen = "Bearish"
    else:
        sentimen = "Neutral"
    
    return {
        "sentimen": sentimen,
        "alasan_singkat": "Analisa berhasil (fallback dari parsing teks).",
        "skor_keyakinan": 4,
        "kata_kunci": [],
    }


# ----------------------------------------------------------------
# FUNGSI FILTER: APAKAH SINYAL LAYAK DIKIRIM?
# ----------------------------------------------------------------
def is_signal_approved(sentiment_result: dict) -> bool:
    """
    Menentukan apakah sinyal teknikal layak dikirim berdasarkan sentimen AI.
    
    Aturan:
        - 'Bullish' → ✅ Kirim notifikasi (teknikal + fundamental sama-sama mendukung)
        - 'Neutral'  → ✅ Kirim notifikasi (teknikal valid, tidak ada hambatan fundamental)  
        - 'Bearish'  → ❌ JANGAN kirim (filter pelindung bekerja, hindari jebakan)
        
    Args:
        sentiment_result: Hasil dari fungsi analyze_sentiment().
        
    Returns:
        True jika sinyal boleh dikirim, False jika harus diabaikan.
    """
    sentimen = sentiment_result.get("sentimen", "Neutral")
    return sentimen in ("Bullish", "Neutral")


if __name__ == "__main__":
    # Test modul secara standalone
    logging.basicConfig(level=logging.INFO)
    test_headlines = [
        "INET.JK Catat Pertumbuhan Pelanggan Fiber Optik 40% YoY",
        "Indointernet Ekspansi Jaringan ke Kota Tier 2",
        "Analis Rekomendasikan BUY untuk INET dengan Target Price Rp 15.000",
    ]
    hasil = analyze_sentiment("INET", test_headlines)
    print(f"\nHasil Analisa:")
    print(f"Sentimen: {hasil['sentimen']}")
    print(f"Alasan: {hasil['alasan_singkat']}")
    print(f"Skor Keyakinan: {hasil['skor_keyakinan']}/10")
    print(f"Sinyal Disetujui: {is_signal_approved(hasil)}")
