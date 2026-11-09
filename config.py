import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "9263926523:AAG3WQ4-r7TU92SEh7P1zcT5Zz3HbW4g-yw").strip()

# Backend 0: DaVinci AI Studio (Seedance 2.5/2.0/Fast/Mini/1.5, Kling 4, Flux 3/Max, LTX 2.5 Pro, Gemini Omni 1.2, Nano Banana, ElevenLabs)
DAVINCI_API_BASE_URL = os.getenv("DAVINCI_API_BASE_URL", "https://api-dev.davinci.ai").rstrip("/")
DAVINCI_ORIGIN = os.getenv("DAVINCI_ORIGIN", "https://web-landing-444069746542.europe-west3.run.app").rstrip("/")
DAVINCI_STORAGE_BUCKET = os.getenv("DAVINCI_STORAGE_BUCKET", "davinci-web-dev.appspot.com")
DAVINCI_FIREBASE_API_KEY = os.getenv("DAVINCI_FIREBASE_API_KEY", "AIzaSyC8aJxeof2CTgI5vpgbno58TtEfH4GiTnA")
DAVINCI_DEFAULT_UID = os.getenv("DAVINCI_DEFAULT_UID", "lF0zVRP0ENh76gHK9r6BQhq0R6g1")
DAVINCI_TOKEN = (
    os.getenv("DAVINCI_TOKEN")
    or "eyJhbGciOiJSUzI1NiIsImtpZCI6IjkwNGIwZjkxYmU2ZWIwODY3ZGFiYmFhYjU4N2RmYzJlMzNmMDBhMjQiLCJ0eXAiOiJKV1QifQ.eyJuYW1lIjoi0JPQtdGA0LzQsNC9IiwicGljdHVyZSI6Imh0dHBzOi8vbGgzLmdvb2dsZXVzZXJjb250ZW50LmNvbS9hLS9BTFYtVWpWM2NGaVpRdzNMTUp5d0pHclAxTFZjelhBOVU2VHRMRXZVNVdNYmVwLTNFTGYzOGJwdm5kWFQ0bEFZOFNaLW5UdlcyOGlZRlJyamloY1lYeGRSUmNwOVo1aGRndV9HOF9sSHh5ZzAtT1JwMnNNdm9vaFd3dDJkNnZNYWY4My1welE3TEhGU1kyVFdESkk1c2hESk1GSndSd1VsSDl3eVA5emE2Mzk4YmQxYlMxSHF3cTdvNHFOQ0M3SXk0U1VIWDNDM1ZTWkduNlhZc3Foa0pBOWRnVFlIbzNUSmg0OXcxVFFMQ0o1bnVqSVhjU0pzclhxUUlpNjZEVHZWb1RBaE9JNUxFalNsWWFZNW9jUkRaVG9OY2VYMTM5YW4xVzRNV3l1Tk9WaUlJV2lNNXYySllCX3RUUEZrblNJVHh6ME9aS0tkZ2VDYXZ5Z3NhZ0Y0WG9fTzdqeUtVOWNCeWJUWVBqQ0dOYVJfUzRfTWxuWWFTaXJHM1hFdE53ZXQ1WVZGRVRkWUpZeXJVSWdMSk1NdFdlYkJxRmVlWHZ1VTRjWHVvWU9LWFNuRnNfWlJsTVF5TjA3Q2tleHlrWnBYMmFZYUFiZEQ1RkttYzcwU0hxX3huNlRyTzQtYWZvQ0VwcEQzaktmNXlQbEdSVVhJZERWS0NBTnVqUTdRVGk2aFhmT3UzYlI0QkxUd2RHZVdIZEdfcm0tWnhMQVgtRF9ON1NqaU40eElSM1hZS191cWFzT3VzSkNLRTgzNEx2emFyaFdia0hRNjVIYzk0cEJMWDZybm44b1lXelJQT1E5QkZYUkJWQlN5MDJ4NWxlam9CMWRQRVZBTUFpaHowRkJTZmxkOE5vRXRUUWFldlljRXJpc2doTVZvMER4b2MyanFnclpCT3hkX2pQYXh5ODN4VENvT25tenpHZU13bkxhb255SG5YNXpjSGJaVDhoemlJRmRNQVpZNnF3R3RTTzl5TkV4RE8zLVBmM2c2ZkpmM2FTOWRiV3FWdnRISEREcE4xR2hDOWNKTkhFNHQ4WkRZMTAtXzdWWUxlMTlzekdPdUh4aURaZGRxOHFfaGl3TGlqZ1hOOWY3dndVVUZVMnppaFp1enBwN2hMSXhKR1dtQWc1c1BnaTdXZXNCcEhIODM5NWRsMVFKRU9jQ3FXZGVubmtmampVdjRHVWVmdy1uNXpDWUVvd21HVUJRdTEtX0N5bm1WZW1RZ3U5SThXSG1ZYWQtRVFBcnlJV0FWS3JTbndDeXFjM25lN2s2Z0RXMGlGSy1SZXBZNlBhUWxzOElVTi0yM1NCczNiZ3NoMVY4SUNjT050WnBBalVmTml3eHdWUndCNEJDWU1OVEUtM045dWZPVlYtSFY2RWdsZDFwTG1oUTZRcEQ2R2FfcGZIUmJNWk43dG5tc0JZNC16RlZGRWt1eUlNUmZzd289czk2LWMiLCJpc3MiOiJodHRwczovL3NlY3VyZXRva2VuLmdvb2dsZS5jb20vZGF2aW5jaS13ZWItZGV2IiwiYXVkIjoiZGF2aW5jaS13ZWItZGV2IiwiYXV0aF90aW1lIjoxNzk0MTUxMjM5LCJ1c2VyX2lkIjoibEYwelZSUDBFTmg3NmdISzlyNkJRaHEwUjZnMSIsInN1YiI6ImxGMHpWUlAwRU5oNzZnSEs5cjZCUWhxMFI2ZzEiLCJpYXQiOjE3OTQxNTEyMzksImV4cCI6MTc5NDE1NDgzOSwiZW1haWwiOiJ1c3Rpbm92Z2VybWFuZkBnbWFpbC5jb20iLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwiZmlyZWJhc2UiOnsiaWRlbnRpdGllcyI6eyJnb29nbGUuY29tIjpbIjExNzM1NDk0OTk4MTU2NjgxMzk0NCJdLCJlbWFpbCI6WyJ1c3Rpbm92Z2VybWFuZkBnbWFpbC5jb20iXX0sInNpZ25faW5fcHJvdmlkZXIiOiJnb29nbGUuY29tIn19.Ed6g-ihiFtDlfmh7AZixsXiqHYovI5BS_7Fe2WBnh9R1RcXetngz15aGFzzxvaKh1k5FnnpIcuyT6coKzKbkn-rubRN2M2w9uwt5e3LNuhFaDlyeXnuOqmc7CSK7IlbeIz6Sdjp1hSb1LyIXDGMYllh2AUssFZoVK-xlX-qcXqEMlFq8YihwS784q8sb9SvcevNvSSXgErY1HlHi13AnhQk3WxS47hCoY3xgKkbao-wDoEk8qNGt-4GjObE62pWrHoLC7RwzSXytIFyKwaOxqh5qux9QOdClvAKtPJvXn82mB9y3AhMISqKEYcDBFYTRlxqLVmluE7Lg5ea1HzRfwQ"
).strip()
DAVINCI_REFRESH_TOKEN = (
    os.getenv("DAVINCI_REFRESH_TOKEN")
    or "AMf-vBwqWC2ZLPdsCT8f8qQKOWSdZJ28w3QVq8OgR-_l30hjq5B_ASbuzFXGVnBIL-GLuc1jqKNN63OGMQHX4sFIcNuEHaYK9ZveI75bQ-goIhBgfcLFMN4-fyJ31svEjXA1bE-80ylZZLtiqOtjxMHosycWzP51jk4haNN4vZ4AIanMxp9irMGxZ0GuiDGiKLFileRGrHyJf1LOcBYGAmmN573ThdBbqc5lmw04M3c-LyrmP78whbYfhvswR82IN_7C2e81D_47ecIJ5pqx5jglrRe8AMpPVcOSo2zt2cbWcxsyb4fckt11DAPChvPhH3iZ1SN30mqIwqqDe3y_PeahyLHP0yzSx2x-HcbNMTusoXN3euAIvyQMN-aeT43Qmr-_WkiuZPFCaK3JwK-JJbwvQ2lpgkYMEIQ5rhaAyOXKJLloxGytyQOl0r3GEXW0YsgNejkHdS2fb3K5UZof5DvdAoIxUJmtvSC6ssLO3H2SJVvy4tKo8-Sc0zHB_gwoTRUOpvgrhTdDVtw1fyREreEUGKrQiJxpXABo1LQH2oKd46e3hPGhAQWSmM7MxrNosddA3zO6mRjO9EG-uiPnz5cRzV1b9_hDu9VeQVXg85piTywXj8P9zYuyFzjcrWNgpie7pTCco3bUBqByvOdsW4Sh2klaDL-5iAbiXmgZplU4Tc5nt5e0Tho5-adNIZdHUBXIRpi6pzSh974bsKeuiCUi2JieDrKFj4dsxzxKnt7hRCKPGWAjOkW_r4QDl7SYwMMrOZZxjbqgptrsELSrBO1AvhcFcntRFDLj_OeRQeaz-9fROKo6_CK3g-5C4zgAj4su4ipzxO84jney8ae23UunmNYQmDVmliLuuvat-Ld3_PlfY5eaKkzIi_U9fvHBSDHSLVkD1iTDvxlFxhGuYZZv8QCepquXJLWXc2D7zTDHyx4IMNgeQjqAinscxxM-eZl6cnxxMKyasSDvjh-1WbzDZJtP6r_bQIp-8Dg-p3X-Vbq0miF5DO4jnSjGFkTPnVTFmOChB8wg40-lTpKjSaMhi6wk9lMX8SsVeGQ7uoWykhFpTOCiawoib18V5T3rpCI_DRCGXwetHLaM1vxOiqVsml_-YULvGJ1bVV2IQQUZuBHBBaDM1vanqAlRdpGg_nVh7oYEoLKwF8re7rZQ54dsaBMTKPo0Euxp44nXvyJgnvwffyurqc7eBesnfWxEEtYF5S8Ry1uX1Y7NdymxCGXiQv6N0h1coiDBQWWGskMbzGvGRHdaPcAjIZ4cODVorvLEnnDF5IHqNbcuBf0YkNQldL23w1NOzdq-uotNec1vmTyxJ2P7WR-eeKDIzcO7BejklIwSUw1kW4yUWNgX2DI-O2DVYRqkHrT5bymeqYptJrqnwB0QbzKVGkT1c54Ct1QruFt7zqL8abBHH3v4AkZ1zX42pZYLVroj5lqQ6jWULCuPkNxDzrRRoFzrCmeIQPH5H5GUtsPelvyy3gLTMFEQYq-X9NvvwUrqxbh2CIBdNDTmehcix1uwp6SKWlg_UOp8XQGCECJrNPGE0WWElysqjcE_KMTukEQurJnQ4Ejx8D-_eD1KYzx3XJNbK8gnZIvQKrOtdXTDtDyWsRYPKEGLuTDQ3L9ToNRXCk5Ox3W7Ryxqh3m8yDhiiNv0swTHKYSGQQ-TO_tlNvsWWoaDI6nuh_phjV5kmGfSari8-pooWVDHMJ3YbaAv-Tuw5eQ9t3Zr_5--fmPCIRSxCiDcRRGDt24xCp0ckszxW8qnzCO_47Pma4sfHkNNqTe0p79F6lgoIY_5VvDtdJ2zQnP9nnNe09eC52nqEw"
).strip()

# Administration & Access Control
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "GermanUstinf2026!").strip()
ADMIN_TELEGRAM_USERNAMES = [u.strip().lstrip("@").lower() for u in os.getenv("ADMIN_TELEGRAM_USERNAMES", "GermanUstinf,germanustinf").split(",") if u.strip()]
ADMIN_TELEGRAM_IDS = [int(x.strip()) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").split(",") if x.strip().isdigit()]
CREATOR_TG_USERNAME = "@GermanUstinf"
CREATOR_TG_URL = "https://t.me/GermanUstinf"
COMMUNITY_TG_URL = "https://t.me/+GnpMk7j_aQ8wOTA6"

# Legacy/Fallback Backends
API_BASE_URL = os.getenv("API_BASE_URL", "https://111.229.36.38").rstrip("/")
API_EMAIL = os.getenv("API_EMAIL", "pocofon_bot_service@local.net")
API_PASSWORD = os.getenv("API_PASSWORD", "SeedancePass2026!")
API_V2_BASE_URL = os.getenv("API_V2_BASE_URL", "http://39.109.117.93:8092").rstrip("/")
API_GROK_BASE_URL = os.getenv("API_GROK_BASE_URL", "http://49.233.205.130:8006").rstrip("/")
API_MINIMAX_BASE_URL = os.getenv("API_MINIMAX_BASE_URL", "http://120.55.55.62/ecommerce-poster-trio").rstrip("/")

# Available Models (Video, Voice, and Image)
MODELS = {
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
        "durations": [5, 10, 15, 20, 30],
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
        "durations": [5, 8, 10, 15],
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
        "durations": [5, 8, 10, 15],
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
        "durations": [5, 8, 10, 15],
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
        "durations": [5, 8, 10, 12],
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
        "durations": [5, 10, 15, 20, 30],
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
        "durations": [5, 10, 15, 20],
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
        "durations": [5, 10, 15, 20],
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
        "durations": [5, 10, 15, 20],
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
        "durations": [6, 8, 10],
        "desc": "Кинематографичная модель LTX 2.5 Pro со звуком и референсом (до 10с)"
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
        "durations": [5, 8, 10, 15],
        "desc": "Google Gemini Omni Flash 1.2 (видео до 15с, 4K + мульти-референсы)"
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
        "durations": [5, 6, 7, 9, 10, 12, 15],
        "desc": "Флагман MiniMax H3 (до 15с, 2K/768p, мульти-референсы до 9 фото)"
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
        "durations": [5, 10, 15, 20, 30],
        "desc": "Alibaba Wan 3.0 Prime (до 30с, мульти-референсы до 10 фото, звук)"
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
        "name": "ElevenLabs TTS V3",
        "short": "🎙 ElevenLabs",
        "category": "video",
        "backend": "davinci_voice",
        "api_id": "eleven-v3",
        "has_audio": True,
        "multi_ref": True,
        "ref_limit": 5,
        "desc": "ElevenLabs V3: студийная озвучка текста и обработка референсов"
    },

    # --- EXISTING GROK & MINIMAX VIDEO MODELS ---
    "grok": {
        "name": "Grok Imagine Video",
        "short": "🌌 Grok Imagine",
        "category": "video",
        "backend": "grok",
        "channel": "auto",
        "has_audio": False,
        "multi_ref": False,
        "ref_limit": 1,
        "durations": [5, 8, 10],
        "desc": "xAI Grok Video (быстрая генерация ~20с)"
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
        elif api_id == "ltx25Pro":
            return int(dur * 6)
        elif api_id == "geminiOmniFlash12":
            return int(dur * 28)
        elif api_id == "minimaxH3":
            return int(dur * 17)
        elif api_id == "minimax-hailuo-2-3":
            return int(dur * 10)
        elif api_id == "pixversev6":
            return int(dur * 19)
        elif api_id == "wan30Prime":
            return int(dur * 11)
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

VIDEO_MODEL_KEYS = [k for k, v in MODELS.items() if v.get("category", "video") == "video"]
IMAGE_MODEL_KEYS = [k for k, v in MODELS.items() if v.get("category") == "image"]

DEFAULT_MODEL = "s2_5"
DEFAULT_IMAGE_MODEL = "nano_banana_2_1"
DEFAULT_DURATION = 5
DEFAULT_RESOLUTION = "720p"
DEFAULT_IMAGE_RESOLUTION = "1K"
DEFAULT_RATIO = "16:9"
DEFAULT_IMAGE_RATIO = "1:1"
DEFAULT_AUDIO = True

MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "10"))

DURATION_OPTIONS = [5, 10, 15, 20, 30]
RESOLUTION_OPTIONS = ["480p", "720p", "1080p"]
IMAGE_RESOLUTION_OPTIONS = ["1K", "2K", "4K"]
RATIO_OPTIONS = ["16:9", "9:16", "1:1"]
IMAGE_RATIO_OPTIONS = ["1:1", "16:9", "9:16", "4:3", "3:4"]
