import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()

# Google Vids Chrome Profile Automation
GOOGLE_VIDS_URL = os.getenv("GOOGLE_VIDS_URL", "https://docs.google.com/videos/u/0/").strip()
GOOGLE_VIDS_PROFILES = os.getenv("GOOGLE_VIDS_PROFILES", "").strip()
GOOGLE_VIDS_HEADLESS = os.getenv("GOOGLE_VIDS_HEADLESS", "0").strip().lower() in ("1", "true", "yes")
GOOGLE_VIDS_TIMEOUT_SEC = int(os.getenv("GOOGLE_VIDS_TIMEOUT_SEC", "420"))
GOOGLE_VIDS_CHROME_PATH = os.getenv("GOOGLE_VIDS_CHROME_PATH", "").strip()
GOOGLE_VIDS_FOR_OMNI = os.getenv("GOOGLE_VIDS_FOR_OMNI", "0").strip().lower() in ("1", "true", "yes")

# Legacy DaVinci env vars (kept only for backwards-compatible imports)
DAVINCI_API_BASE_URL = os.getenv("DAVINCI_API_BASE_URL", "https://api-dev.davinci.ai").rstrip("/")
DAVINCI_ORIGIN = os.getenv("DAVINCI_ORIGIN", "https://web-landing-444069746542.europe-west3.run.app").rstrip("/")
DAVINCI_STORAGE_BUCKET = os.getenv("DAVINCI_STORAGE_BUCKET", "davinci-web-dev.appspot.com")
DAVINCI_FIREBASE_API_KEY = os.getenv("DAVINCI_FIREBASE_API_KEY", "AIzaSyC8aJxeof2CTgI5vpgbno58TtEfH4GiTnA")
DAVINCI_DEFAULT_UID = os.getenv("DAVINCI_DEFAULT_UID", "lF0zVRP0ENh76gHK9r6BQhq0R6g1")
DAVINCI_TOKEN = (os.getenv("DAVINCI_TOKEN") or "").strip()
DAVINCI_REFRESH_TOKEN = (os.getenv("DAVINCI_REFRESH_TOKEN") or "").strip()

# Administration & Access Control
ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD") or "").strip()
ADMIN_TELEGRAM_USERNAMES = [
    u.strip().lstrip("@").lower()
    for u in os.getenv("ADMIN_TELEGRAM_USERNAMES", "GermanUstinf,germanustinf,german792,german_ustinf").split(",")
    if u.strip()
]
KEY_SIGNING_SECRET = (os.getenv("KEY_SIGNING_SECRET") or ADMIN_PASSWORD).strip()
ADMIN_TELEGRAM_IDS = [int(x.strip()) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip().isdigit()]
CREATOR_TG_USERNAME = "@GermanUstinf"
CREATOR_TG_URL = "https://t.me/GermanUstinf"
COMMUNITY_TG_URL = "https://t.me/+GnpMk7j_aQ8wOTA6"

# Legacy Fallback Env Vars (kept for api_client.py compatibility)
API_BASE_URL = os.getenv("API_BASE_URL", "https://111.229.36.38").rstrip("/")
API_EMAIL = os.getenv("API_EMAIL", "pocofon_bot_service@local.net")
API_PASSWORD = os.getenv("API_PASSWORD", "")
API_V2_BASE_URL = os.getenv("API_V2_BASE_URL", "http://39.109.117.93:8092").rstrip("/")
API_GROK_BASE_URL = os.getenv("API_GROK_BASE_URL", "http://49.233.205.130:8006").rstrip("/")
API_MINIMAX_BASE_URL = os.getenv("API_MINIMAX_BASE_URL", "http://120.55.55.62/ecommerce-poster-trio").rstrip("/")

# =====================================================================
# ALL MODELS FROM ARK API KEY (VIDEO + IMAGE + TEXT)
# =====================================================================
MODELS = {
    # --- VIDEO MODELS (7) ---
    "seedance_2_5_flash": {
        "name": "Seedance 2.5 Flash",
        "short": "⚡ Seed 2.5 Flash",
        "category": "video",
        "backend": "ark_video",
        "api_id": "dreamina-seedance-2-5-flash-261115",
        "has_audio": True,
        "multi_ref": True,
        "ref_limit": 4,
        "supports_frames": ["start", "end"],
        "durations": [5, 10, 15],
        "resolutions": ["480p", "720p", "1080p"],
        "ratios": ["16:9", "9:16", "1:1"],
        "desc": "Seedance 2.5 Flash: быстрое видео до 15с со звуком",
    },
    "seedance_2_5": {
        "name": "Seedance 2.5",
        "short": "✨ Seedance 2.5",
        "category": "video",
        "backend": "ark_video",
        "api_id": "dreamina-seedance-2-5-260628",
        "has_audio": True,
        "multi_ref": True,
        "ref_limit": 4,
        "supports_frames": ["start", "end"],
        "durations": [5, 10, 15],
        "resolutions": ["480p", "720p", "1080p"],
        "ratios": ["16:9", "9:16", "1:1"],
        "desc": "Seedance 2.5: флагманское видео до 15с со звуком",
    },
    "seedance_2_0_fast": {
        "name": "Seedance 2.0 Fast",
        "short": "🚀 Seed 2.0 Fast",
        "category": "video",
        "backend": "ark_video",
        "api_id": "dreamina-seedance-2-0-fast-260128",
        "has_audio": True,
        "multi_ref": True,
        "ref_limit": 4,
        "supports_frames": ["start", "end"],
        "durations": [5, 10, 15],
        "resolutions": ["480p", "720p", "1080p"],
        "ratios": ["16:9", "9:16", "1:1"],
        "desc": "Seedance 2.0 Fast: быстрая генерация видео со звуком",
    },
    "seedance_2_0": {
        "name": "Seedance 2.0",
        "short": "🎬 Seedance 2.0",
        "category": "video",
        "backend": "ark_video",
        "api_id": "dreamina-seedance-2-0-260128",
        "has_audio": True,
        "multi_ref": True,
        "ref_limit": 4,
        "supports_frames": ["start", "end"],
        "durations": [5, 10, 15],
        "resolutions": ["480p", "720p", "1080p"],
        "ratios": ["16:9", "9:16", "1:1"],
        "desc": "Seedance 2.0: видео до 15с со звуком",
    },
    "seedance_2_0_mini": {
        "name": "Seedance 2.0 Mini",
        "short": "💨 Seed 2.0 Mini",
        "category": "video",
        "backend": "ark_video",
        "api_id": "dreamina-seedance-2-0-mini-260615",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 2,
        "supports_frames": ["start", "end"],
        "durations": [5, 10],
        "resolutions": ["480p", "720p"],
        "ratios": ["16:9", "9:16", "1:1"],
        "desc": "Seedance 2.0 Mini: лёгкая и быстрая генерация",
    },
    "seedance_1_0_pro_fast": {
        "name": "Seedance 1.0 Fast",
        "short": "⚡ Seed 1.0 Fast",
        "category": "video",
        "backend": "ark_video",
        "api_id": "seedance-1-0-pro-fast-251015",
        "has_audio": False,
        "multi_ref": False,
        "ref_limit": 2,
        "supports_frames": ["start", "end"],
        "durations": [5, 10],
        "resolutions": ["480p", "720p", "1080p"],
        "ratios": ["16:9", "9:16", "1:1"],
        "desc": "Seedance 1.0 Pro Fast: 5–10с, до 1080p",
    },
    "seedance_1_0_pro": {
        "name": "Seedance 1.0 Pro",
        "short": "🎞 Seed 1.0 Pro",
        "category": "video",
        "backend": "ark_video",
        "api_id": "seedance-1-0-pro-250528",
        "has_audio": False,
        "multi_ref": False,
        "ref_limit": 2,
        "supports_frames": ["start", "end"],
        "durations": [5, 10],
        "resolutions": ["480p", "720p", "1080p"],
        "ratios": ["16:9", "9:16", "1:1"],
        "desc": "Seedance 1.0 Pro: 5–10с, до 1080p",
    },

    # --- IMAGE MODELS (8) ---
    "seedream_5_5": {
        "name": "Seedream 5.5",
        "short": "🌟 Seedream 5.5",
        "category": "image",
        "backend": "ark_image",
        "api_id": "dola-seedream-5-5-261028",
        "ref_limit": 1,
        "resolutions": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "desc": "Seedream 5.5: новейшая генерация и редактирование фото",
    },
    "seedream_5_0_pro": {
        "name": "Seedream 5.0 Pro",
        "short": "💎 Seedream 5 Pro",
        "category": "image",
        "backend": "ark_image",
        "api_id": "dola-seedream-5-0-pro-260628",
        "ref_limit": 1,
        "resolutions": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "desc": "Seedream 5.0 Pro: максимальная детализация",
    },
    "seedream_5_0_flash": {
        "name": "Seedream 5.0 Flash",
        "short": "⚡ Seedream 5F",
        "category": "image",
        "backend": "ark_image",
        "api_id": "dola-seedream-5-0-flash-260915",
        "ref_limit": 1,
        "resolutions": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "desc": "Seedream 5.0 Flash: быстрая генерация изображений",
    },
    "seedream_5_0": {
        "name": "Seedream 5.0",
        "short": "🎨 Seedream 5.0",
        "category": "image",
        "backend": "ark_image",
        "api_id": "seedream-5-0-260128",
        "ref_limit": 1,
        "resolutions": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "desc": "Seedream 5.0: генерация фото",
    },
    "seedream_4_5": {
        "name": "Seedream 4.5",
        "short": "🖼 Seedream 4.5",
        "category": "image",
        "backend": "ark_image",
        "api_id": "seedream-4-5-251128",
        "ref_limit": 1,
        "resolutions": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "desc": "Seedream 4.5: генерация фото",
    },
    "seedream_4_0_new": {
        "name": "Seedream 4.0 (2026)",
        "short": "✨ Seedream 4 New",
        "category": "image",
        "backend": "ark_image",
        "api_id": "seedream-4-0-20260415",
        "ref_limit": 1,
        "resolutions": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "desc": "Seedream 4.0 (2026): генерация фото",
    },
    "seedream_4_0": {
        "name": "Seedream 4.0",
        "short": "📷 Seedream 4.0",
        "category": "image",
        "backend": "ark_image",
        "api_id": "seedream-4-0-250828",
        "ref_limit": 1,
        "resolutions": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "desc": "Seedream 4.0: генерация фото",
    },
    "seedream_3_0": {
        "name": "Seedream 3.0",
        "short": "🖌 Seedream 3.0",
        "category": "image",
        "backend": "ark_image",
        "api_id": "seedream-3-0-t2i-250415",
        "ref_limit": 0,
        "resolutions": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "desc": "Seedream 3.0: текст-в-изображение",
    },

    # --- TEXT / LLM / TRANSLATION MODELS (16) ---
    "deepseek_v4_1_flash": {
        "name": "DeepSeek V4.1 Flash",
        "short": "⚡ DS V4.1 Flash",
        "category": "text",
        "backend": "ark_text",
        "api_id": "deepseek-v4-1-flash-261017",
        "ref_limit": 2,
        "desc": "DeepSeek V4.1 Flash: быстрая текстовая модель",
    },
    "deepseek_v4_1_eco": {
        "name": "DeepSeek V4.1 Eco",
        "short": "💨 DS V4.1 Eco",
        "category": "text",
        "backend": "ark_text",
        "api_id": "deepseek-v4-1-flash-economy-261017",
        "ref_limit": 0,
        "desc": "DeepSeek V4.1 Flash Economy",
    },
    "deepseek_v4_1_0910": {
        "name": "DeepSeek V4.1 (0910)",
        "short": "⚡ DS V4.1 0910",
        "category": "text",
        "backend": "ark_text",
        "api_id": "deepseek-v4-1-flash-260910",
        "ref_limit": 0,
        "desc": "DeepSeek V4.1 Flash (0910)",
    },
    "deepseek_v4_pro_ga": {
        "name": "DeepSeek V4 Pro GA",
        "short": "🧠 DS V4 Pro GA",
        "category": "text",
        "backend": "ark_text",
        "api_id": "deepseek-v4-pro-ga-260813",
        "ref_limit": 0,
        "desc": "DeepSeek V4 Pro GA: сложные задачи и анализ",
    },
    "deepseek_v4_flash_ga": {
        "name": "DeepSeek V4 Flash GA",
        "short": "⚡ DS V4 Flash GA",
        "category": "text",
        "backend": "ark_text",
        "api_id": "deepseek-v4-flash-ga-260731",
        "ref_limit": 0,
        "desc": "DeepSeek V4 Flash GA",
    },
    "deepseek_v4_pro": {
        "name": "DeepSeek V4 Pro",
        "short": "🧠 DS V4 Pro",
        "category": "text",
        "backend": "ark_text",
        "api_id": "deepseek-v4-pro-260425",
        "ref_limit": 0,
        "desc": "DeepSeek V4 Pro",
    },
    "deepseek_v4_flash": {
        "name": "DeepSeek V4 Flash",
        "short": "⚡ DS V4 Flash",
        "category": "text",
        "backend": "ark_text",
        "api_id": "deepseek-v4-flash-260425",
        "ref_limit": 0,
        "desc": "DeepSeek V4 Flash",
    },
    "deepseek_v3_1": {
        "name": "DeepSeek V3.1",
        "short": "💬 DeepSeek V3.1",
        "category": "text",
        "backend": "ark_text",
        "api_id": "deepseek-v3-1-250821",
        "ref_limit": 0,
        "desc": "DeepSeek V3.1",
    },
    "glm_5_3_flash": {
        "name": "GLM 5.3 Flash",
        "short": "✨ GLM 5.3 Flash",
        "category": "text",
        "backend": "ark_text",
        "api_id": "glm-5-3-flash-260828",
        "ref_limit": 0,
        "desc": "GLM 5.3 Flash",
    },
    "glm_5_2": {
        "name": "GLM 5.2",
        "short": "💬 GLM 5.2",
        "category": "text",
        "backend": "ark_text",
        "api_id": "glm-5-2-260617",
        "ref_limit": 0,
        "desc": "GLM 5.2",
    },
    "seed_2_1_turbo": {
        "name": "Seed 2.1 Turbo",
        "short": "🚀 Seed 2.1 Turbo",
        "category": "text",
        "backend": "ark_text",
        "api_id": "dola-seed-2-1-turbo-260628",
        "ref_limit": 2,
        "desc": "Seed 2.1 Turbo",
    },
    "seed_2_0_pro": {
        "name": "Seed 2.0 Pro",
        "short": "🧠 Seed 2.0 Pro",
        "category": "text",
        "backend": "ark_text",
        "api_id": "seed-2-0-pro-260328",
        "ref_limit": 2,
        "desc": "Seed 2.0 Pro",
    },
    "seed_2_0_lite": {
        "name": "Seed 2.0 Lite",
        "short": "💨 Seed 2.0 Lite",
        "category": "text",
        "backend": "ark_text",
        "api_id": "seed-2-0-lite-260428",
        "ref_limit": 2,
        "desc": "Seed 2.0 Lite",
    },
    "seed_2_0_mini": {
        "name": "Seed 2.0 Mini",
        "short": "⚡ Seed 2.0 Mini",
        "category": "text",
        "backend": "ark_text",
        "api_id": "seed-2-0-mini-260428",
        "ref_limit": 2,
        "desc": "Seed 2.0 Mini",
    },
    "seed_2_0_code": {
        "name": "Seed 2.0 Code",
        "short": "💻 Seed 2.0 Code",
        "category": "text",
        "backend": "ark_text",
        "api_id": "seed-2-0-code-preview-260328",
        "ref_limit": 0,
        "desc": "Seed 2.0 Code: программирование и код",
    },
    "seed_translation": {
        "name": "Seed Translation",
        "short": "🌐 Translation",
        "category": "text",
        "backend": "ark_text",
        "api_id": "seed-translation-250915",
        "ref_limit": 0,
        "desc": "Seed Translation: перевод текста",
    },
}

def calculate_credit_cost(model_key: str, duration: int = 5, resolution: str = "720p", generate_audio: bool = True) -> int:
    """Return estimated credit cost for UI display (actual billing is handled server-side by PromptWise)."""
    return 0


COMPACT_MODEL_LABELS = {k: v["short"] for k, v in MODELS.items()}


def get_model_grid_label(model_key: str) -> str:
    """Return a concise button label for dense 3-column model grids."""
    if model_key in COMPACT_MODEL_LABELS:
        return COMPACT_MODEL_LABELS[model_key]
    m = MODELS.get(model_key, {})
    return m.get("short") or m.get("name") or model_key


VIDEO_MODEL_KEYS = [
    k for k, v in MODELS.items()
    if v.get("category") == "video" and not v.get("hidden")
]
IMAGE_MODEL_KEYS = [
    k for k, v in MODELS.items()
    if v.get("category") == "image" and not v.get("hidden")
]
TEXT_MODEL_KEYS = [
    k for k, v in MODELS.items()
    if v.get("category") == "text" and not v.get("hidden")
]
VOICE_MODEL_KEYS = [k for k, v in MODELS.items() if v.get("category") == "voice"]
MUSIC_MODEL_KEYS = [k for k, v in MODELS.items() if v.get("category") == "music"]

VOICE_MODEL_KEY = ""
MUSIC_MODEL_KEY = ""
MOTION_MODEL_KEY = ""
MOTION_MODEL_KEYS = []

# Live ElevenLabs voice IDs from staging.promptwise.com/api/generate-audio?action=voices
VOICES = [
    {"id": "LxN8dyndjhJGesWKq1RH", "name": "Savannah", "emoji": "👩"},
    {"id": "3CDfug1pbx1pBSfHIkPR", "name": "Amelia", "emoji": "🎙"},
    {"id": "FUfBrNit0NNZAwb58KWH", "name": "Angela", "emoji": "👧"},
    {"id": "vmVmHDKBkkCgbLVIOJRb", "name": "Charlie", "emoji": "👨"},
    {"id": "nIHefZ8GOsC19mjvAhSN", "name": "Shaan", "emoji": "🧑"},
    {"id": "bKrvJaCHEqucAEpSzACi", "name": "Brian", "emoji": "🎩"},
    {"id": "851ejYcv2BoNPjrkw93G", "name": "Tony", "emoji": "⚡"},
    {"id": "nbcvT3C2tyOd2OsRAtUf", "name": "Maya", "emoji": "🌟"},
    {"id": "MClEFoImJXBTgLwdLI5n", "name": "Ivy", "emoji": "💎"},
]
DEFAULT_VOICE_ID = VOICES[0]["id"]

# Kept for backwards compatibility with any imports
MUSIC_GENRES = [{"key": "", "label": "Авто"}]
MUSIC_DURATIONS = [
    {"key": "15", "label": "15с"},
    {"key": "30", "label": "30с"},
    {"key": "60", "label": "60с"},
    {"key": "120", "label": "120с"},
]
MUSIC_MOODS = [{"key": "", "label": "Авто"}]
MUSIC_THEMES = [{"key": "", "label": "Авто"}]

DEFAULT_MODEL = "seedance_2_5_flash"
DEFAULT_IMAGE_MODEL = "seedream_5_5"
DEFAULT_TEXT_MODEL = "deepseek_v4_1_flash"
DEFAULT_DURATION = 5
DEFAULT_RESOLUTION = "720p"
DEFAULT_IMAGE_RESOLUTION = "1K"
DEFAULT_RATIO = "16:9"
DEFAULT_IMAGE_RATIO = "1:1"
DEFAULT_AUDIO = True

MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "10"))

DURATION_OPTIONS = list(range(1, 31))
RESOLUTION_OPTIONS = ["480p", "720p", "1080p", "4k"]
IMAGE_RESOLUTION_OPTIONS = ["1K", "2K", "4K"]
RATIO_OPTIONS = ["16:9", "9:16", "1:1"]
IMAGE_RATIO_OPTIONS = ["1:1", "16:9", "9:16", "4:3", "3:4"]
