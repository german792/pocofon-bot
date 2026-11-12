import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()

# Backend 0: DaVinci AI Studio (Seedance 2.5/2.0/Fast/Mini/1.5, Kling 4, Flux 3/Max, LTX 2.5 Pro, Gemini Omni 1.2, Nano Banana, ElevenLabs)
DAVINCI_API_BASE_URL = os.getenv("DAVINCI_API_BASE_URL", "https://api-dev.davinci.ai").rstrip("/")
DAVINCI_ORIGIN = os.getenv("DAVINCI_ORIGIN", "https://web-landing-444069746542.europe-west3.run.app").rstrip("/")
DAVINCI_STORAGE_BUCKET = os.getenv("DAVINCI_STORAGE_BUCKET", "davinci-web-dev.appspot.com")
DAVINCI_FIREBASE_API_KEY = os.getenv("DAVINCI_FIREBASE_API_KEY", "AIzaSyC8aJxeof2CTgI5vpgbno58TtEfH4GiTnA")
DAVINCI_DEFAULT_UID = os.getenv("DAVINCI_DEFAULT_UID", "lF0zVRP0ENh76gHK9r6BQhq0R6g1")
DAVINCI_TOKEN = (os.getenv("DAVINCI_TOKEN") or "").strip()
DAVINCI_REFRESH_TOKEN = (os.getenv("DAVINCI_REFRESH_TOKEN") or "").strip()

# Administration & Access Control
ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD") or "").strip()
ADMIN_TELEGRAM_USERNAMES = [u.strip().lstrip("@").lower() for u in os.getenv("ADMIN_TELEGRAM_USERNAMES", "GermanUstinf,germanustinf,german792,german_ustinf").split(",") if u.strip()]
# Secret used to sign access keys. Falls back to ADMIN_PASSWORD so keys issued earlier stay valid.
KEY_SIGNING_SECRET = (os.getenv("KEY_SIGNING_SECRET") or ADMIN_PASSWORD).strip()
ADMIN_TELEGRAM_IDS = [int(x.strip()) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip().isdigit()]
CREATOR_TG_USERNAME = "@GermanUstinf"
CREATOR_TG_URL = "https://t.me/GermanUstinf"
COMMUNITY_TG_URL = "https://t.me/+GnpMk7j_aQ8wOTA6"

# Legacy/Fallback Backends
API_BASE_URL = os.getenv("API_BASE_URL", "https://111.229.36.38").rstrip("/")
API_EMAIL = os.getenv("API_EMAIL", "pocofon_bot_service@local.net")
API_PASSWORD = os.getenv("API_PASSWORD", "")
API_V2_BASE_URL = os.getenv("API_V2_BASE_URL", "http://39.109.117.93:8092").rstrip("/")
API_GROK_BASE_URL = os.getenv("API_GROK_BASE_URL", "http://49.233.205.130:8006").rstrip("/")
API_MINIMAX_BASE_URL = os.getenv("API_MINIMAX_BASE_URL", "http://120.55.55.62/ecommerce-poster-trio").rstrip("/")

# Available Models (Video, Voice, and Image)
MODELS = {
    # --- MOTION CONTROL (вкладка Motion: фото персонажа + видео с движением) ---
    "klingMotionControl3": {
        "name": "Kling Motion Control 3.0",
        "short": "🕺 Motion",
        "category": "motion",
        "backend": "davinci_motion",
        "api_id": "klingMotionControl3",
        "desc": "Фото персонажа + видео с движением",
        "video_ref": True,
    },
    # --- SEEDANCE MODELS (All replaced with DaVinci AI site versions) ---
    "s2_5": {
        "name": "Seedance 2.5",
        "short": "✨ Seedance 2.5",
        "category": "video",
        "backend": "davinci",
        "api_id": "seedance25",
        "has_audio": True,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 30,
        "durations": list(range(1, 31)),
        "desc": "Флагман Seedance 2.5 (до 30с, 1080p, звук и мульти-референсы)"
    },
    "s2_pro": {
        "name": "Seedance 2.0",
        "short": "🎬 Seedance 2.0",
        "category": "video",
        "backend": "davinci",
        "api_id": "seedance2",
        "has_audio": True,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 9,
        "durations": list(range(1, 16)),
        "desc": "Максимальное качество Seedance 2.0 со звуком и референсами (до 15с)"
    },
    "s2_fast": {
        "name": "Seedance 2.0 Fast",
        "short": "🚀 2.0 Fast",
        "category": "video",
        "backend": "davinci",
        "api_id": "seedance2Fast",
        "has_audio": True,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 9,
        "durations": list(range(1, 16)),
        "desc": "Быстрая версия Seedance 2.0 со звуком и референсами (до 15с)"
    },
    "s2_mini": {
        "name": "Seedance 2.0 Mini",
        "short": "⚡ 2.0 Mini",
        "category": "video",
        "backend": "davinci",
        "api_id": "seedance2Mini",
        "has_audio": True,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 9,
        "durations": list(range(1, 16)),
        "desc": "Ультрабыстрая Seedance 2.0 Mini со звуком и референсами (до 15с)"
    },
    "s1_5_pro": {
        "name": "Seedance 1.5 Pro",
        "short": "🎞 Seedance 1.5",
        "category": "video",
        "backend": "davinci",
        "api_id": "seedance",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "durations": list(range(1, 13)),
        "desc": "Классическая модель Seedance 1.5 Pro со звуком (до 12с)"
    },

    # --- NEW VIDEO & AUDIO MODELS ---
    "kling_4": {
        "name": "Kling 4.0",
        "short": "🎥 Kling 4.0",
        "category": "video",
        "backend": "davinci",
        "api_id": "kling4",
        "has_audio": False,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 10,
        "durations": list(range(1, 31)),
        "desc": "Новейший Kling 4.0 (до 30с, 1080p, до 10 фото-референсов)"
    },
    "kling_4_flash": {
        "name": "Kling 4.0 Flash",
        "short": "⚡ Kling 4 Flash",
        "category": "video",
        "backend": "davinci",
        "api_id": "kling4Flash",
        "has_audio": True,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 10,
        "durations": list(range(1, 21)),
        "desc": "Быстрый Kling 4.0 Flash со звуком и референсами (до 20с)"
    },
    "flux_3": {
        "name": "Flux 3 Video",
        "short": "🌊 Flux 3",
        "category": "video",
        "backend": "davinci",
        "api_id": "flux3",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "durations": list(range(1, 21)),
        "desc": "Видео-модель Flux 3 (до 20с, высокая детализация + звук + референс)"
    },
    "flux_3_max": {
        "name": "Flux 3 Max",
        "short": "🔥 Flux 3 Max",
        "category": "video",
        "backend": "davinci",
        "api_id": "flux3Max",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "durations": list(range(1, 21)),
        "desc": "Топовая видео-модель Flux 3 Max со звуком и референсом (до 20с)"
    },
    "ltx_25_pro": {
        "name": "LTX 2.5 Pro",
        "short": "🎞 LTX 2.5 Pro",
        "category": "video",
        "backend": "davinci",
        "api_id": "ltx25Pro",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "durations": list(range(1, 11)),
        "desc": "Кинематографичная модель LTX 2.5 Pro со звуком и референсом (до 10с)"
    },
    "ltx_25_fast": {
        "name": "LTX 2.5 Fast",
        "short": "⚡ LTX 2.5 Fast",
        "category": "video",
        "backend": "davinci",
        "api_id": "ltx25Fast",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "durations": list(range(1, 11)),
        "desc": "Сверхбыстрая кинематографичная модель LTX 2.5 Fast со звуком (до 10с, от 1с)"
    },
    "gemini_omni_12": {
        "name": "Gemini OmniFlash 1.2",
        "short": "💎 Gemini Omni 1.2",
        "category": "video",
        "backend": "davinci",
        "api_id": "geminiOmniFlash12",
        "has_audio": False,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 10,
        "durations": list(range(1, 16)),
        "desc": "Google Gemini Omni Flash 1.2 (видео до 15с, 4K + мульти-референсы)"
    },
    "gemini_omni_11": {
        "name": "Gemini OmniFlash 1.1",
        "short": "⚡ Gemini Omni 1.1",
        "category": "video",
        "backend": "davinci",
        "api_id": "geminiOmniFlash11",
        "has_audio": False,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 10,
        "durations": list(range(1, 16)),
        "desc": "Google Gemini Omni Flash 1.1 (видео до 15с, 4K + мульти-референсы, от 1с)"
    },
    "luma_dream_machine": {
        "name": "Luma Dream Machine",
        "short": "🌟 Luma Dream Machine",
        "category": "video",
        "backend": "davinci",
        "api_id": "luma-dream-machine",
        "has_audio": True,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 5,
        "durations": list(range(1, 16)),
        "desc": "Luma Dream Machine: кино-реализм нового уровня Luma AI (до 15с, от 1с)"
    },
    "luma_ray_32": {
        "name": "Luma Ray v3.2",
        "short": "⚡ Luma Ray 3.2",
        "category": "video",
        "backend": "davinci",
        "api_id": "luma-ray-3-2",
        "has_audio": True,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 5,
        "durations": list(range(1, 16)),
        "desc": "Luma Ray v3.2: следующее поколение AI видео Luma Ray со звуком (до 15с, от 1с)"
    },
    "minimax_h3": {
        "name": "MiniMax H3",
        "short": "⚡ MiniMax H3",
        "category": "video",
        "backend": "davinci",
        "api_id": "minimaxH3",
        "has_audio": False,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 9,
        "durations": list(range(1, 16)),
        "desc": "Флагман MiniMax H3 (до 15с, 2K/768p, мульти-референсы до 9 фото, от 1с!)"
    },
    "minimax_hailuo": {
        "name": "MiniMax Hailuo 2.3",
        "short": "🌊 Hailuo 2.3",
        "category": "video",
        "backend": "davinci",
        "api_id": "minimax-hailuo-2-3",
        "has_audio": False,
        "multi_ref": False,
        "video_ref": False,
        "ref_limit": 1,
        "durations": [5, 6, 10],
        "desc": "MiniMax Hailuo 2.3 (до 10с, 1080p, реалистичная физика движений)"
    },
    "pixverse_v6": {
        "name": "PixVerse V6",
        "short": "🎬 PixVerse V6",
        "category": "video",
        "backend": "davinci",
        "api_id": "pixversev6",
        "has_audio": True,
        "multi_ref": False,
        "video_ref": False,
        "ref_limit": 1,
        "durations": [5, 8, 10, 15],
        "desc": "PixVerse V6 (кинематографичный рендер до 15с, звук, спецэффекты)"
    },
    "wan_2_6": {
        "name": "Wan 2.6",
        "short": "✨ Wan 2.6",
        "category": "video",
        "backend": "davinci",
        "api_id": "wan26",
        "has_audio": True,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 10,
        "durations": list(range(1, 31)),
        "desc": "Alibaba Wan 2.6 (кинематографичная физика, мульти-референсы до 10 фото, звук, от 1с)"
    },
    "wan_3_prime": {
        "name": "Wan 3.0 Prime",
        "short": "✨ Wan 3 Prime",
        "category": "video",
        "backend": "davinci",
        "api_id": "wan30Prime",
        "has_audio": True,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 10,
        "durations": list(range(1, 31)),
        "desc": "Alibaba Wan 3.0 Prime (до 30с, мульти-референсы до 10 фото, звук, от 1с)"
    },
    "runway_alpha": {
        "name": "Runway Alpha 2.0",
        "short": "🎬 Runway Alpha 2.0",
        "category": "video",
        "backend": "davinci",
        "api_id": "runway-aleph",
        "has_audio": True,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 5,
        "durations": list(range(1, 21)),
        "desc": "Runway Alpha 2.0 (Aleph): кинематографичный рендер Runway с сайта DaVinci (от 1с)"
    },
    "pika_2_2": {
        "name": "Pika 2.2",
        "short": "⚡ Pika 2.2",
        "category": "video",
        "backend": "davinci",
        "api_id": "pika22",
        "has_audio": False,
        "multi_ref": False,
        "video_ref": False,
        "ref_limit": 1,
        "durations": [5, 10],
        "desc": "Pika 2.2 (быстрое видео до 10с, 1080p, визуальные эффекты)"
    },
    "elevenlabs": {
        "name": "ElevenLabs V3",
        "short": "🎙 ElevenLabs",
        "category": "video",  # остаётся "video" ради web.py/истории; в боте голос вынесен во вкладку «Голос»
        "backend": "davinci_voice",
        "api_id": "eleven-v3",
        "has_audio": True,
        "multi_ref": True,
        "ref_limit": 5,
        "desc": "Текст в голос и переозвучка"
    },

    # --- EXISTING GROK & MINIMAX VIDEO MODELS ---
    "grok": {
        "name": "Grok Imagine",
        "short": "🌌 Grok Imagine",
        "category": "video",
        "backend": "davinci",
        "api_id": "grok",
        "has_audio": True,
        "multi_ref": True,
        "video_ref": True,
        "ref_limit": 5,
        "durations": list(range(1, 16)),
        "desc": "xAI Grok Imagine: сверхбыстрая генерация видео со звуком с сайта DaVinci (от 1с)"
    },
    "grok_15": {
        "name": "Grok Imagine 1.5",
        "short": "🔮 Grok 1.5",
        "category": "video",
        "backend": "grok",
        "channel": "console",
        "has_audio": False,
        "multi_ref": False,
        "ref_limit": 1,
        "durations": [5, 8, 10],
        "desc": "xAI Grok Video 1.5 (Console канал)"
    },
    "minimax_hero": {
        "name": "MiniMax H3 (Hero)",
        "short": "🎬 MiniMax Hero",
        "category": "video",
        "backend": "minimax",
        "style": "minimalist-hero",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "durations": [15],
        "desc": "MiniMax H3: 15-сек коммерческое видео со звуком"
    },
    "minimax_cinema": {
        "name": "MiniMax H3 (Cinema)",
        "short": "🎥 MiniMax Cinema",
        "category": "video",
        "backend": "minimax",
        "style": "cinematic-lifestyle",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "durations": [15],
        "desc": "MiniMax H3: Кинематографичный лайфстайл со звуком"
    },
    "minimax_macro": {
        "name": "MiniMax H3 (Macro)",
        "short": "🔍 MiniMax Macro",
        "category": "video",
        "backend": "minimax",
        "style": "macro-detail",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "durations": [15],
        "desc": "MiniMax H3: Макросъемка текстур и деталей со звуком"
    },

    # --- IMAGE GENERATION MODELS (Dedicated Image Menu) ---
    "nano_banana_2_1": {
        "name": "Nano Banana 2.1",
        "short": "🍌 Nano Banana 2.1",
        "category": "image",
        "backend": "davinci_image",
        "api_id": "NANO_BANANA_2_1",
        "multi_ref": True,
        "ref_limit": 14,
        "desc": "Новейшая фото-модель Nano Banana 2.1 (до 4K и до 14 референсов)"
    },
    "nano_banana_pro": {
        "name": "Nano Banana Pro",
        "short": "🍌 Nano Banana Pro",
        "category": "image",
        "backend": "davinci_image",
        "api_id": "NANO_BANANA_2",
        "multi_ref": True,
        "ref_limit": 12,
        "desc": "Профессиональная фото-модель Nano Banana Pro (до 12 референсов)"
    },
    "nano_banana": {
        "name": "Nano Banana",
        "short": "🍌 Nano Banana",
        "category": "image",
        "backend": "davinci_image",
        "api_id": "NANO_BANANA",
        "multi_ref": True,
        "ref_limit": 4,
        "desc": "Быстрая генерация и редактирование фото Nano Banana (до 4 референсов)"
    },
    "flux_3_img": {
        "name": "Flux 3 Image",
        "short": "🎨 Flux 3 Image",
        "category": "image",
        "backend": "davinci_image",
        "api_id": "FLUX_3",
        "multi_ref": True,
        "ref_limit": 10,
        "desc": "Фотореалистичная генерация изображений Flux 3 (до 4K, 10 референсов)"
    },
    "flux_3_klein": {
        "name": "Flux 3 Klein",
        "short": "✨ Flux 3 Klein",
        "category": "image",
        "backend": "davinci_image",
        "api_id": "FLUX_3_KLEIN",
        "multi_ref": True,
        "ref_limit": 10,
        "desc": "Быстрая художественная модель Flux 3 Klein с поддержкой референсов"
    },
    "qwen_image_3": {
        "name": "Qwen Image 3.0",
        "short": "🖼 Qwen Image 3.0",
        "category": "image",
        "backend": "davinci_image",
        "api_id": "QWEN_IMAGE_3",
        "multi_ref": True,
        "ref_limit": 3,
        "desc": "Qwen Image 3.0 (точная генерация текста и сцен по референсам)"
    },
    "gpt_image_2_6_sunburst": {
        "name": "GPT Image 2.6 Sunburst",
        "short": "☀️ GPT 2.6 Sunburst",
        "category": "image",
        "backend": "davinci_image",
        "api_id": "GPT_IMAGE_2_6_SUNBURST",
        "multi_ref": True,
        "ref_limit": 10,
        "desc": "Новейшая модель OpenAI GPT Image 2.6 Sunburst с референсами (1 кредит)"
    },
    "gpt_image_2_6_flare": {
        "name": "GPT Image 2.6 Flare",
        "short": "✨ GPT 2.6 Flare",
        "category": "image",
        "backend": "davinci_image",
        "api_id": "GPT_IMAGE_2_6_FLARE",
        "multi_ref": True,
        "ref_limit": 10,
        "desc": "Новейшая модель OpenAI GPT Image 2.6 Flare с референсами (1 кредит)"
    },
    "qwen_image": {
        "name": "Qwen 3.0 Pro (Постер)",
        "short": "🪧 Qwen Постер",
        "category": "image",
        "backend": "qwen_image",
        "api_id": "qwen-image-3.0-pro",
        "multi_ref": False,
        "ref_limit": 1,
        "desc": "Qwen Image 3.0 Pro: генерация коммерческих постеров по фото/тексту"
    },
}

def calculate_credit_cost(model_key: str, duration: int = 5, resolution: str = "720p") -> int:
    """Calculate estimated DaVinci AI credit cost for a generation based on model and parameters."""
    model_info = MODELS.get(model_key, MODELS.get(DEFAULT_MODEL, {}))
    backend = model_info.get("backend")
    api_id = model_info.get("api_id")
    dur = max(4, duration) if duration > 0 else 5
    if model_info.get("backend") == "davinci_motion":
        return 0  # цена пока не задана: в интерфейсе кредиты не показываем

    # 1. Video models on DaVinci backend
    if backend == "davinci":
        if api_id == "seedance25":
            if dur <= 5:
                return 507
            elif dur <= 6:
                return 270
            elif dur <= 8:
                return 360
            elif dur <= 10:
                return 1013
            elif dur <= 15:
                return 1519
            elif dur <= 20:
                return 2025
            return 3038  # 30s
        elif api_id in ("seedance2", "seedance2Fast", "seedance2Mini"):
            return int(dur * 20)
        elif api_id == "seedance":
            return int(dur * 25)
        elif api_id == "kling4":
            return int(dur * 17)
        elif api_id == "kling4Flash":
            return int(dur * 15)
        elif api_id == "flux3":
            return int(dur * 30)
        elif api_id == "flux3Max":
            return int(dur * 36)
        elif api_id in ("ltx25Pro", "ltx25Fast"):
            return int(dur * 6)
        elif api_id in ("geminiOmniFlash12", "geminiOmniFlash11"):
            return int(dur * 28)
        elif api_id in ("luma-dream-machine", "luma-ray-3-2"):
            return int(dur * 22)
        elif api_id == "minimaxH3":
            return int(dur * 17)
        elif api_id == "minimax-hailuo-2-3":
            return int(dur * 10)
        elif api_id == "pixversev6":
            return int(dur * 19)
        elif api_id == "wan30Prime":
            return int(dur * 11)
        elif api_id == "wan26":
            return int(dur * 11)
        elif api_id == "grok":
            return int(dur * 14)
        elif api_id in ("runway-aleph", "runwayAlpha"):
            return int(dur * 20)
        elif api_id == "pika22":
            return int(dur * 5)
        return int(dur * 25)

    # 2. Image models on DaVinci backend
    if backend == "davinci_image":
        if api_id == "NANO_BANANA_2_1":
            return 38
        elif api_id == "NANO_BANANA_2":
            return 25
        elif api_id == "NANO_BANANA":
            return 10
        elif api_id in ("FLUX_3", "FLUX_3_KLEIN"):
            return 15
        elif api_id == "QWEN_IMAGE_3":
            return 10
        elif api_id in ("GPT_IMAGE_2_6_SUNBURST", "GPT_IMAGE_2_6_FLARE"):
            return 1
        return 15

    # 3. Voice models on DaVinci backend
    if backend == "davinci_voice":
        return 10

    # 4. External models (Grok, MiniMax, Qwen Image Pro, legacy fallbacks)
    return 0

VIDEO_MODEL_KEYS = [
    "s2_5",
    "s2_pro",
    "s2_fast",
    "s2_mini",
    "s1_5_pro",
    "kling_4",
    "kling_4_flash",
    "flux_3",
    "flux_3_max",
    "ltx_25_pro",
    "ltx_25_fast",
    "gemini_omni_12",
    "gemini_omni_11",
    "grok",
    "wan_2_6",
    "wan_3_prime",
    "minimax_h3",
    "runway_alpha",
    "luma_dream_machine",
    "luma_ray_32",
]
IMAGE_MODEL_KEYS = [k for k, v in MODELS.items() if v.get("category") == "image"]

# --- Voice tab (ElevenLabs) ---
VOICE_MODEL_KEY = "elevenlabs"  # вкладка голоса временно отключена
MOTION_MODEL_KEY = "klingMotionControl3"
# Голоса для вкладки «Голос». id — ElevenLabs voice_id. Первый — тот, что бот использовал раньше.
# Если сайт не принимает какой-то id, просто удали строку — остальные продолжат работать.
VOICES = [
    {"id": "UGTtbzgh3HObxRjWaSpr", "name": "Основной", "emoji": "🎙"},
    {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "emoji": "👩"},
    {"id": "EXAVITQu4vr4xnSehpDI", "name": "Bella", "emoji": "👧"},
    {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam", "emoji": "👨"},
    {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh", "emoji": "🧑"},
    {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni", "emoji": "🎩"},
]
DEFAULT_VOICE_ID = VOICES[0]["id"]

DEFAULT_MODEL = "s2_5"
DEFAULT_IMAGE_MODEL = "nano_banana_2_1"
DEFAULT_DURATION = 5
DEFAULT_RESOLUTION = "720p"
DEFAULT_IMAGE_RESOLUTION = "1K"
DEFAULT_RATIO = "16:9"
DEFAULT_IMAGE_RATIO = "1:1"
DEFAULT_AUDIO = True

MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "10"))

DURATION_OPTIONS = list(range(1, 31))
RESOLUTION_OPTIONS = ["480p", "720p", "1080p"]
IMAGE_RESOLUTION_OPTIONS = ["1K", "2K", "4K"]
RATIO_OPTIONS = ["16:9", "9:16", "1:1"]
IMAGE_RATIO_OPTIONS = ["1:1", "16:9", "9:16", "4:3", "3:4"]
