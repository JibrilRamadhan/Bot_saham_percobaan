"""
ai_analyzer.py - Analisa Sentimen Berita menggunakan Groq (Primary) + Gemini (Fallback)
========================================================================================
Arsitektur Double-Layer AI:
  1. GROQ API (Primary)  → LLaMA 3.3 70B, 30 RPM gratis, respons < 1 detik
  2. Gemini API (Fallback) → Gemini 2.0 Flash, dipakai jika Groq gagal/rate limit

Cache 30 menit mencegah pemanggilan API berulang untuk saham yang sama.
"""

import json
import logging
import time
import re
from datetime import datetime, timedelta
from typing import Optional

from groq import Groq
from google import genai
from google.genai import types

import config

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
# CLIENT INITIALIZATION (Lazy)
# ----------------------------------------------------------------
_groq_client = None
_gemini_client = None


def get_groq_client() -> Groq:
    """Lazy initialization Groq client."""
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=config.GROQ_API_KEY)
    return _groq_client


def get_gemini_client() -> genai.Client:
    """Lazy initialization Gemini client."""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _gemini_client


# ----------------------------------------------------------------
# SENTIMENT CACHE (in-memory, TTL 30 menit)
# ----------------------------------------------------------------
_sentiment_cache: dict = {}


def _get_cached_sentiment(kode_saham: str) -> dict | None:
    """Ambil sentimen dari cache jika masih valid."""
    if kode_saham not in _sentiment_cache:
        return None
    cached = _sentiment_cache[kode_saham]
    age = datetime.now() - cached["timestamp"]
    if age < timedelta(minutes=config.SENTIMENT_CACHE_TTL_MINUTES):
        sisa = int((timedelta(minutes=config.SENTIMENT_CACHE_TTL_MINUTES) - age).total_seconds() / 60)
        logger.info(f"[AI] 💾 Cache hit {kode_saham} (valid {sisa} mnt lagi) — skip API call")
        return cached["result"]
    del _sentiment_cache[kode_saham]
    return None


def _save_to_cache(kode_saham: str, result: dict) -> None:
    """Simpan hasil sentimen ke cache."""
    _sentiment_cache[kode_saham] = {"result": result, "timestamp": datetime.now()}
    logger.info(f"[AI] 💾 Cache disimpan untuk {kode_saham} (TTL: {config.SENTIMENT_CACHE_TTL_MINUTES} mnt)")


# ----------------------------------------------------------------
# PROMPT SISTEM
# ----------------------------------------------------------------
SYSTEM_PROMPT = """Kamu adalah analis saham profesional yang ahli dalam pasar saham Indonesia (IHSG).
Tugasmu adalah menganalisa sentimen berita saham berdasarkan headline yang diberikan.

ATURAN:
- Jawab HANYA dengan format JSON yang valid, tidak ada teks lain di luar JSON.
- Nilai 'sentimen' HANYA boleh: "Bullish", "Bearish", atau "Neutral".
- 'alasan_singkat' maksimal 2 kalimat dalam Bahasa Indonesia.
- 'skor_keyakinan' adalah angka 1-10.

FORMAT JSON WAJIB:
{
  "sentimen": "Bullish/Bearish/Neutral",
  "alasan_singkat": "Penjelasan singkat tentang sentimen",
  "skor_keyakinan": 8,
  "kata_kunci": ["kata1", "kata2"]
}"""


def _build_user_prompt(kode_bersih: str, headlines: list[str]) -> str:
    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
    return (
        f"Analisa sentimen untuk saham {kode_bersih} berdasarkan "
        f"{len(headlines)} headline berita berikut:\n\n{numbered}\n\n"
        f"Berikan analisa sentimen dalam format JSON sesuai instruksi."
    )


# ----------------------------------------------------------------
# GROQ INFERENCE (Primary)
# ----------------------------------------------------------------
def _analyze_with_groq(kode_bersih: str, headlines: list[str]) -> dict | None:
    """
    Panggil Groq API (LLaMA 3.3 70B).
    Mengembalikan dict hasil atau None jika gagal.
    """
    if not config.GROQ_API_KEY:
        logger.warning("[AI] GROQ_API_KEY tidak diset, skip Groq.")
        return None

    user_prompt = _build_user_prompt(kode_bersih, headlines)

    for attempt in range(1, 3):  # Max 2 percobaan untuk Groq
        try:
            logger.info(f"[AI] 🔵 Groq ({config.GROQ_MODEL}) — {kode_bersih} (percobaan {attempt})")
            client = get_groq_client()
            chat = client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=500,
                response_format={"type": "json_object"},  # Paksa output JSON
            )
            response_text = chat.choices[0].message.content.strip()
            result = _parse_response(response_text)
            logger.info(f"[AI] ✅ Groq — {kode_bersih}: {result['sentimen']} ({result['skor_keyakinan']}/10)")
            return result

        except Exception as e:
            error_str = str(e).lower()
            if any(k in error_str for k in ["rate", "429", "too many", "quota"]):
                logger.warning(f"[AI] Groq rate limit (percobaan {attempt}/2), tunggu 10s...")
                time.sleep(10)
            else:
                logger.error(f"[AI] Groq error (percobaan {attempt}/2): {e}")
                if attempt < 2:
                    time.sleep(2)

    logger.warning("[AI] Groq gagal semua percobaan, pindah ke Gemini fallback...")
    return None


# ----------------------------------------------------------------
# GEMINI INFERENCE (Fallback)
# ----------------------------------------------------------------
def _analyze_with_gemini(kode_bersih: str, headlines: list[str]) -> dict | None:
    """
    Panggil Gemini API (gemini-2.0-flash) sebagai fallback.
    Mengembalikan dict hasil atau None jika gagal.
    """
    if not config.GEMINI_API_KEY:
        logger.warning("[AI] GEMINI_API_KEY tidak diset, skip Gemini fallback.")
        return None

    full_prompt = f"{SYSTEM_PROMPT}\n\n{_build_user_prompt(kode_bersih, headlines)}"

    for attempt in range(1, 3):
        try:
            logger.info(f"[AI] 🟡 Gemini ({config.GEMINI_MODEL}) fallback — {kode_bersih} (percobaan {attempt})")
            client = get_gemini_client()
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    top_p=0.8,
                    max_output_tokens=500,
                ),
            )
            result = _parse_response(response.text.strip())
            logger.info(f"[AI] ✅ Gemini fallback — {kode_bersih}: {result['sentimen']} ({result['skor_keyakinan']}/10)")
            return result

        except Exception as e:
            error_str = str(e).lower()
            if any(k in error_str for k in ["rate", "429", "quota", "resource_exhausted"]):
                wait = 15 * attempt
                logger.warning(f"[AI] Gemini rate limit, tunggu {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"[AI] Gemini error (percobaan {attempt}/2): {e}")
                if attempt < 2:
                    time.sleep(3)

    return None


# ----------------------------------------------------------------
# FUNGSI UTAMA
# ----------------------------------------------------------------
def analyze_sentiment(kode_saham: str, headlines: list[str], max_retry: int = 3) -> dict:
    """
    Analisa sentimen berita dengan sistem Double-Layer:
      1. Cek cache (jika < 30 menit, pakai cache)
      2. Coba Groq (primary, lebih cepat & rate limit lebih besar)
      3. Fallback ke Gemini jika Groq gagal
      4. Return Neutral sebagai default aman jika semua gagal
    """
    kode_bersih = kode_saham.upper().replace(".JK", "")

    # 1. Cek cache
    cached = _get_cached_sentiment(kode_bersih)
    if cached is not None:
        return {**cached, "dari_cache": True}

    # 2. Tidak ada berita → langsung Neutral
    if not headlines:
        logger.warning(f"[AI] Tidak ada berita untuk {kode_bersih} — default Neutral")
        return {
            "sentimen": "Neutral",
            "alasan_singkat": "Tidak ada berita terbaru ditemukan untuk saham ini.",
            "skor_keyakinan": 3,
            "kata_kunci": [],
            "headlines_dianalisa": 0,
        }

    # 3. Coba Groq (primary)
    result = _analyze_with_groq(kode_bersih, headlines)

    # 4. Fallback Gemini jika Groq gagal
    if result is None:
        result = _analyze_with_gemini(kode_bersih, headlines)

    # 5. Semua gagal → Neutral aman
    if result is None:
        logger.error(f"[AI] ❌ Semua AI provider gagal untuk {kode_bersih}")
        return {
            "sentimen": "Neutral",
            "alasan_singkat": "Analisa AI tidak tersedia saat ini. Sinyal teknikal tetap valid.",
            "skor_keyakinan": 0,
            "kata_kunci": [],
            "headlines_dianalisa": len(headlines),
        }

    result["headlines_dianalisa"] = len(headlines)
    _save_to_cache(kode_bersih, result)
    return result


# ----------------------------------------------------------------
# FILTER SINYAL
# ----------------------------------------------------------------
def is_signal_approved(sentiment_result: dict) -> bool:
    """
    Bullish/Neutral → kirim alert.
    Bearish → filter, jangan kirim.
    """
    return sentiment_result.get("sentimen", "Neutral") in ("Bullish", "Neutral")


# ----------------------------------------------------------------
# RESPONSE PARSER
# ----------------------------------------------------------------
def _parse_response(response_text: str) -> dict:
    """Parse JSON dari respons AI. 3 layer fallback."""
    cleaned = re.sub(r"```(?:json)?\s*", "", response_text).replace("```", "").strip()

    try:
        return _validate(json.loads(cleaned))
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*?\}", cleaned, re.DOTALL)
    if match:
        try:
            return _validate(json.loads(match.group()))
        except json.JSONDecodeError:
            pass

    # Text fallback
    tl = response_text.lower()
    sentimen = "Bullish" if "bullish" in tl else ("Bearish" if "bearish" in tl else "Neutral")
    return {"sentimen": sentimen, "alasan_singkat": "Analisa (fallback teks).", "skor_keyakinan": 4, "kata_kunci": []}


def _validate(data: dict) -> dict:
    """Validasi & normalisasi output JSON dari AI."""
    valid = {"Bullish", "Bearish", "Neutral"}
    sentimen = data.get("sentimen", "Neutral")
    for v in valid:
        if sentimen.lower() == v.lower():
            sentimen = v
            break
    else:
        sentimen = "Neutral"

    return {
        "sentimen": sentimen,
        "alasan_singkat": str(data.get("alasan_singkat", "Tidak ada keterangan.")),
        "skor_keyakinan": max(0, min(10, int(data.get("skor_keyakinan", 5)))),
        "kata_kunci": data.get("kata_kunci", []),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test = [
        "INET Catat Pertumbuhan Pelanggan Fiber Optik 40% YoY",
        "Indointernet Ekspansi Jaringan ke Kota Tier 2",
        "Analis Rekomendasikan BUY untuk INET dengan Target Rp 15.000",
    ]
    hasil = analyze_sentiment("INET", test)
    print(f"Sentimen: {hasil['sentimen']} | Keyakinan: {hasil['skor_keyakinan']}/10")
    print(f"Alasan: {hasil['alasan_singkat']}")
