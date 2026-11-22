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
# ALL FREE MODELS (loremotion.com/generate & 160.30.161.35)
# =====================================================================
MODELS = {
    # --- FREE VIDEO MODELS ---
    "ltx_2_5": {
        "name": "LTX 2.5",
        "short": "⚡ LTX 2.5",
        "category": "video",
        "backend": "loremotion",
        "api_id": "ltx-2.3",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "supports_frames": [],
        "durations": list(range(1, 11)),
        "resolutions": ["480p", "720p"],
        "ratios": ["16:9", "9:16", "1:1"],
        "desc": "Бесплатная модель: 1–10с, 480p/720p со звуком",
    },
    "minimax_h3": {
        "name": "MiniMax H3",
        "short": "🎬 MiniMax H3",
        "category": "video",
        "backend": "loremotion",
        "api_id": "minimax-h3",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 2,
        "supports_frames": ["start", "end"],
        "durations": list(range(1, 16)),
        "resolutions": ["480p", "720p"],
        "ratios": ["16:9", "9:16", "1:1"],
        "desc": "Бесплатная модель: 480p до 15с / 720p до 5с, звук и первый/последний кадр",
    },
    "veo_3_1_fast": {
        "name": "Veo 3.1 Fast",
        "short": "🎥 Veo 3.1 Fast",
        "category": "video",
        "backend": "gencpu",
        "server_engine": "server11",
        "api_id": "Veo 3.1 Fast",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "supports_frames": [],
        "durations": [4, 6, 8],
        "resolutions": ["720p"],
        "ratios": ["16:9", "9:16"],
        "desc": "Бесплатная модель: 4/6/8с, 720p со звуком",
    },
    "veo_3_2_fast": {
        "name": "Veo 3.2 Fast",
        "short": "✨ Veo 3.2 Fast",
        "category": "video",
        "backend": "gencpu",
        "server_engine": "server11",
        "api_id": "Veo 3.2 Fast",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "supports_frames": [],
        "durations": [4, 6, 8],
        "resolutions": ["720p"],
        "ratios": ["16:9", "9:16"],
        "desc": "Бесплатная модель: 4/6/8с, 720p со звуком",
    },
    "veo_3_1_lite": {
        "name": "Veo 3.1 Lite",
        "short": "💨 Veo 3.1 Lite",
        "category": "video",
        "backend": "gencpu",
        "server_engine": "server11",
        "api_id": "Veo 3.1 Lite",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "supports_frames": [],
        "durations": [4, 6, 8],
        "resolutions": ["720p"],
        "ratios": ["16:9", "9:16"],
        "desc": "Бесплатная облегчённая модель: 4/6/8с, 720p со звуком",
    },
    "gencpu_ai": {
        "name": "Gen AI",
        "short": "🌟 Gen AI",
        "category": "video",
        "backend": "gencpu",
        "server_engine": "server7",
        "sv7_mode": "gencpu_ai",
        "api_id": "Gencpu AI",
        "has_audio": False,
        "multi_ref": False,
        "ref_limit": 1,
        "supports_frames": [],
        "durations": [5, 10, 15, 20],
        "resolutions": ["480p"],
        "ratios": ["16:9", "9:16", "1:1"],
        "desc": "Бесплатная модель: до 20с, 480p",
    },
    "seedance_2_5_lite": {
        "name": "Seedance 2.5 Lite",
        "short": "🎞 Seedance Lite",
        "category": "video",
        "backend": "gencpu",
        "server_engine": "server7",
        "sv7_mode": "seedance25_lite",
        "api_id": "Seedance 2.5 Lite",
        "has_audio": True,
        "multi_ref": False,
        "ref_limit": 1,
        "supports_frames": [],
        "durations": [5, 10, 15],
        "resolutions": ["480p"],
        "ratios": ["16:9", "9:16", "1:1"],
        "desc": "Бесплатная модель: 5–15с, 480p со звуком",
    },

    # --- FREE IMAGE MODELS ---
    "gencpu_image": {
        "name": "Gen AI Фото",
        "short": "🖼 Gen AI Фото",
        "category": "image",
        "backend": "gencpu_image",
        "server_engine": "server7",
        "sv7_mode": "gencpu_t2i",
        "api_id": "Gencpu AI",
        "ref_limit": 1,
        "resolutions": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "desc": "Бесплатная генерация и редактирование фото",
    },
    "krea_2_edit": {
        "name": "Krea 2 Edit",
        "short": "🪄 Krea 2 Edit",
        "category": "image",
        "backend": "loremotion_image",
        "api_id": "krea-2-identity-edit",
        "ref_limit": 1,
        "resolutions": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "desc": "Бесплатное редактирование фото по референсу (1K)",
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

DEFAULT_MODEL = "ltx_2_5"
DEFAULT_IMAGE_MODEL = "gencpu_image"
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
