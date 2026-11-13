import asyncio
import html
import io
import logging
import re
import time
from typing import Dict, Any, Optional, List, Tuple

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BufferedInputFile,
    InputMediaPhoto,
)
import image_utils
import access_manager
import config
import history_manager

from config import (
    BOT_TOKEN,
    MODELS,
    VIDEO_MODEL_KEYS,
    IMAGE_MODEL_KEYS,
    DEFAULT_MODEL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_DURATION,
    DEFAULT_RESOLUTION,
    DEFAULT_IMAGE_RESOLUTION,
    DEFAULT_RATIO,
    DEFAULT_IMAGE_RATIO,
    DEFAULT_AUDIO,
    DURATION_OPTIONS,
    RESOLUTION_OPTIONS,
    IMAGE_RESOLUTION_OPTIONS,
    RATIO_OPTIONS,
    IMAGE_RATIO_OPTIONS,
    calculate_credit_cost,
    VOICE_MODEL_KEY,
    MOTION_MODEL_KEY,
    MOTION_MODEL_KEYS,
    VOICES,
    DEFAULT_VOICE_ID,
)
from api_client import (
    SeedanceAPIClient,
    SeedanceV2Client,
    GrokVideoClient,
    MiniMaxClient,
    QwenImageClient,
    DaVinciClient,
)
from queue_worker import GenerationQueue, GenerationJob
from watermark_utils import extract_frame_from_video, extract_audio_from_video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

router = Router()

# Marker of the code version (visible in the menu) to confirm the latest bot.py is deployed
BUILD_ID = "multiref-v5-video-2026-11-09"


class UserInputState(StatesGroup):
    waiting_for_prompt = State()
    waiting_for_duration = State()


# Active draft per user
user_drafts: Dict[int, Dict[str, Any]] = {}
# Persistent user preferences across requests
user_prefs: Dict[int, Dict[str, Any]] = {}


def get_user_prefs(user_id: int) -> Dict[str, Any]:
    if user_id not in user_prefs:
        user_prefs[user_id] = {
            "model_key": DEFAULT_MODEL,
            "image_model_key": DEFAULT_IMAGE_MODEL,
            "duration": DEFAULT_DURATION,
            "resolution": DEFAULT_RESOLUTION,
            "image_resolution": DEFAULT_IMAGE_RESOLUTION,
            "ratio": DEFAULT_RATIO,
            "image_ratio": DEFAULT_IMAGE_RATIO,
            "audio": DEFAULT_AUDIO,
            "ref_mode": "ref",
            "voice_id": DEFAULT_VOICE_ID,
            "voice_mode": "tts",
        }
    if user_prefs[user_id].get("model_key") not in VIDEO_MODEL_KEYS:
        user_prefs[user_id]["model_key"] = DEFAULT_MODEL
    return user_prefs[user_id]


PLACEHOLDER_PROMPTS = (
    "Кинематографичное видео с плавной динамикой",
    "Фотореалистичное изображение в высоком разрешении",
    "Анимировать фото, реалистичное кинематографичное видео",
    "Стилизовать изображение по референсу в высоком качестве",
    "Анимировать сцену, плавное движение",
    "Сгенерируй видео под прикрепленный звук",
)


def voice_text_of(draft: Dict[str, Any]) -> str:
    """Text to speak. Video/photo placeholder prompts are not speech."""
    text = (draft.get("prompt") or "").strip()
    return "" if text in PLACEHOLDER_PROMPTS else text


def tabs_row(active: str, owner_id: int) -> List[InlineKeyboardButton]:
    """Three top tabs: video / photo / voice. ✅ stays for old clients, style=primary colors it on new ones."""
    items = [("video", "🎬 Видео"), ("image", "🖼 Фото"), ("motion", "🕺 Motion")]
    row = []
    for key, label in items:
        if key == active:
            row.append(InlineKeyboardButton(text=f"✅ {label}", callback_data=f"tab:{key}:{owner_id}", style="primary"))
        else:
            row.append(InlineKeyboardButton(text=label, callback_data=f"tab:{key}:{owner_id}"))
    return row


def build_settings_keyboard(draft: Dict[str, Any], owner_id: int) -> InlineKeyboardMarkup:
    """Build dynamic interactive inline keyboard for either Video Menu or Image Menu."""
    sync_draft_references(draft)
    menu_mode = draft.get("menu_mode", "video")
    if menu_mode == "image":
        return build_image_settings_keyboard(draft, owner_id)
    if menu_mode == "motion":
        return build_motion_settings_keyboard(draft, owner_id)
    return build_video_settings_keyboard(draft, owner_id)


def build_motion_settings_keyboard(draft: Dict[str, Any], owner_id: int) -> InlineKeyboardMarkup:
    """Motion Control: модель (3.0 / 2.6), разрешение, запуск, отмена."""
    cur_model = draft.get("model_key", MOTION_MODEL_KEY)
    cur_res = draft.get("resolution", "720p")
    rows = [tabs_row("motion", owner_id)]
    model_row = []
    for mk, label in (("klingMotionControl3", "3.0"), ("klingMotionControl26", "2.6")):
        active = mk == cur_model
        model_row.append(InlineKeyboardButton(
            text=("✅ " if active else "") + f"Kling {label}",
            callback_data=f"mmodel:{mk}:{owner_id}",
            **({"style": "primary"} if active else {}),
        ))
    rows.append(model_row)
    res_row = []
    for r in ("720p", "1080p"):
        active = r == cur_res
        res_row.append(InlineKeyboardButton(
            text=("✅ " if active else "") + r,
            callback_data=f"mres:{r}:{owner_id}",
            **({"style": "primary"} if active else {}),
        ))
    rows.append(res_row)
    ready = bool(draft.get("motion_image")) and bool(draft.get("ref_video"))
    rows.append([InlineKeyboardButton(text="🕺 Запустить", callback_data=f"gen:{owner_id}", **({"style": "success"} if ready else {}))])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"can:{owner_id}", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_video_settings_keyboard(draft: Dict[str, Any], owner_id: int) -> InlineKeyboardMarkup:
    """Video & Voice 3-step wizard menu:
    Step 1 (model): Choose video model
    Step 2 (duration): Choose exact seconds (individual button for each second 1..model_max)
    Step 3 (quality): Resolution, aspect ratio, audio toggle & launch
    """
    cur_model = draft.get("model_key", DEFAULT_MODEL)
    if cur_model not in VIDEO_MODEL_KEYS:
        cur_model = DEFAULT_MODEL
        draft["model_key"] = cur_model

    minfo = MODELS.get(cur_model, MODELS[DEFAULT_MODEL])
    step = draft.get("step", "model")

    # If voice model, wizard has model step or voice quality step
    if minfo.get("backend") == "davinci_voice":
        if step != "model":
            cost = calculate_credit_cost(cur_model, 0, "")
            btn_label = f"🎙 Озвучить (~{cost} кр.)" if cost > 0 else "🎙 Озвучить"
            rows = [
                [
                    InlineKeyboardButton(text="🔄 Сменить модель", callback_data=f"wstep:model:{owner_id}"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data=f"can:{owner_id}", style="danger")
                ],
                [
                    InlineKeyboardButton(text=btn_label, callback_data=f"gen:{owner_id}", style="success")
                ]
            ]
            return InlineKeyboardMarkup(inline_keyboard=rows)

    # STEP 1: Model Selection
    if step == "model":
        rows = [
            tabs_row("video", owner_id)
        ]
        # Video Models grid (2 per row)
        cur_row = []
        for mkey in VIDEO_MODEL_KEYS:
            m = MODELS[mkey]
            lbl = m["short"]
            is_active = mkey == cur_model
            btn_kwargs = {"style": "primary"} if is_active else {}
            if is_active:
                lbl = f"✅ {lbl}"
            cur_row.append(InlineKeyboardButton(text=lbl, callback_data=f"sm:{mkey}:{owner_id}", **btn_kwargs))
            if len(cur_row) == 2:
                rows.append(cur_row)
                cur_row = []
        if cur_row:
            rows.append(cur_row)

        # Photo Reference Row
        ref_images: List[bytes] = draft.get("ref_images", [])
        ref_count = len(ref_images)
        ref_limit = minfo.get("ref_limit", 1)
        ref_mode = draft.get("ref_mode", "ref")
        if ref_count == 0:
            rows.append([
                InlineKeyboardButton(
                    text=f"📎 Добавить фото-референс (до {ref_limit} шт.)",
                    callback_data=f"ref_hint:{owner_id}",
                    style="primary"
                )
            ])
        else:
            grid_lbl = "✅ 🔲 Сетка 3×3 (снять)" if draft.get("has_grid") else "🔲 Сетка на референс"
            if minfo.get("multi_ref"):
                mode_lbl = (
                    f"🎯 Референс ({ref_count}/{ref_limit} фото)"
                    if ref_mode == "ref"
                    else f"🎬 Старт-кадр ({ref_count} фото)"
                )
                rows.append([
                    InlineKeyboardButton(text=mode_lbl, callback_data=f"rmode:{owner_id}"),
                    InlineKeyboardButton(text=grid_lbl, callback_data=f"rgrid:{owner_id}"),
                    InlineKeyboardButton(text="🗑 Очистить", callback_data=f"rclear:{owner_id}", style="danger"),
                ])
            else:
                rows.append([
                    InlineKeyboardButton(text=f"📎 Референс: {ref_count} фото ✅", callback_data=f"ref_hint:{owner_id}"),
                    InlineKeyboardButton(text=grid_lbl, callback_data=f"rgrid:{owner_id}"),
                    InlineKeyboardButton(text="🗑 Удалить", callback_data=f"rclear:{owner_id}", style="danger"),
                ])

        # Video Reference Row
        if draft.get("ref_video"):
            rows.append([
                InlineKeyboardButton(text="🎞 Видео-референс прикреплен ✅ (Удалить 🗑)", callback_data=f"rclearvideo:{owner_id}", style="danger")
            ])
        else:
            rows.append([
                InlineKeyboardButton(text="🎞 Прикрепить видео (отправьте видеоролик)", callback_data=f"video_hint:{owner_id}", style="primary")
            ])

        # Audio Reference Row
        if draft.get("audio_bytes"):
            rows.append([
                InlineKeyboardButton(text="🎵 Аудио-референс прикреплен ✅ (Удалить 🗑)", callback_data=f"rclearaudio:{owner_id}", style="danger")
            ])
        else:
            rows.append([
                InlineKeyboardButton(text="🎵 Прикрепить аудио (отправьте голос / mp3)", callback_data=f"audio_hint:{owner_id}", style="primary")
            ])

        # Cancel button
        rows.append([
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"can:{owner_id}", style="danger")
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    # STEP 2: Duration Selection (every second 1..max_dur is its own button)
    if step == "duration":
        model_durs = minfo.get("durations", list(range(1, 31)))
        max_dur = max(model_durs) if model_durs else 15
        cur_dur = int(draft.get("duration", DEFAULT_DURATION))
        if cur_dur > max_dur:
            cur_dur = max_dur
            draft["duration"] = max_dur

        rows = []
        cur_row = []
        for d in range(1, max_dur + 1):
            is_active = d == cur_dur
            lbl = f"✅ {d}с" if is_active else f"{d}с"
            btn_kwargs = {"style": "primary"} if is_active else {}
            cur_row.append(InlineKeyboardButton(text=lbl, callback_data=f"sd:{d}:{owner_id}", **btn_kwargs))
            if len(cur_row) == 5:
                rows.append(cur_row)
                cur_row = []
        if cur_row:
            rows.append(cur_row)

        rows.append([
            InlineKeyboardButton(text="⬅️ Назад к выбору модели", callback_data=f"wstep:model:{owner_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"can:{owner_id}", style="danger")
        ])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    # STEP 3: Quality & Launch
    model_durs = minfo.get("durations", list(range(1, 31)))
    max_dur = max(model_durs) if model_durs else 15
    dur = max(1, min(max_dur, int(draft.get("duration", DEFAULT_DURATION))))
    draft["duration"] = dur
    res = draft.get("resolution", DEFAULT_RESOLUTION)
    ratio = draft.get("ratio", DEFAULT_RATIO)
    audio = draft.get("audio", DEFAULT_AUDIO)

    rows = []

    # Resolution Row
    res_buttons = []
    for r in RESOLUTION_OPTIONS:
        is_active = r == res
        label = f"✅ {r}" if is_active else r
        btn_kwargs = {"style": "primary"} if is_active else {}
        res_buttons.append(InlineKeyboardButton(text=label, callback_data=f"sr:{r}:{owner_id}", **btn_kwargs))
    rows.append(res_buttons)

    # Ratio Row
    ratio_labels = {"16:9": "16:9 🖥", "9:16": "9:16 📱", "1:1": "1:1 ⏹"}
    ratio_buttons = []
    for rat in RATIO_OPTIONS:
        lbl = ratio_labels.get(rat, rat)
        is_active = rat == ratio
        btn_kwargs = {"style": "primary"} if is_active else {}
        if is_active:
            lbl = f"✅ {lbl}"
        ratio_buttons.append(InlineKeyboardButton(text=lbl, callback_data=f"sa:{rat}:{owner_id}", **btn_kwargs))
    rows.append(ratio_buttons)

    # Audio toggle for models supporting audio generation
    if minfo.get("has_audio") and minfo.get("backend") != "minimax":
        audio_label = "🔊 Звук: Вкл ✅" if audio else "🔇 Звук: Выкл"
        audio_kwargs = {"style": "success"} if audio else {}
        rows.append([InlineKeyboardButton(text=audio_label, callback_data=f"tg:{'1' if not audio else '0'}:{owner_id}", **audio_kwargs)])

    # Navigation buttons to return to Step 1 or Step 2
    rows.append([
        InlineKeyboardButton(text=f"🔄 Модель: {minfo.get('short', cur_model)}", callback_data=f"wstep:model:{owner_id}"),
        InlineKeyboardButton(text=f"⏱ Длительность: {dur}с", callback_data=f"wstep:duration:{owner_id}")
    ])

    # Action row
    cost = calculate_credit_cost(cur_model, dur, res)
    btn_text = f"🚀 Сгенерировать видео (~{cost} кр.)" if cost > 0 else "🚀 Сгенерировать видео"
    rows.append([
        InlineKeyboardButton(text=btn_text, callback_data=f"gen:{owner_id}", style="success"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"can:{owner_id}", style="danger")
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_image_settings_keyboard(draft: Dict[str, Any], owner_id: int) -> InlineKeyboardMarkup:
    """Dedicated Image Generation Menu (Nano Banana 2.1/Pro, Flux 3 Image/Klein, Qwen Image 3.0)."""
    cur_model = draft.get("model_key", DEFAULT_IMAGE_MODEL)
    if cur_model not in IMAGE_MODEL_KEYS:
        cur_model = DEFAULT_IMAGE_MODEL
        draft["model_key"] = cur_model

    minfo = MODELS.get(cur_model, MODELS[DEFAULT_IMAGE_MODEL])
    res = draft.get("image_resolution", DEFAULT_IMAGE_RESOLUTION)
    ratio = draft.get("image_ratio", DEFAULT_IMAGE_RATIO)
    ref_images: List[bytes] = draft.get("ref_images", [])

    # Top Switcher Row: Video Menu vs Image Menu
    switcher_row = tabs_row("image", owner_id)

    # Image Models grid (2 per row)
    model_rows = []
    cur_row = []
    for mkey in IMAGE_MODEL_KEYS:
        m = MODELS[mkey]
        lbl = m["short"]
        is_active = mkey == cur_model
        btn_kwargs = {"style": "primary"} if is_active else {}
        if is_active:
            lbl = f"✅ {lbl}"
        cur_row.append(InlineKeyboardButton(text=lbl, callback_data=f"sm:{mkey}:{owner_id}", **btn_kwargs))
        if len(cur_row) == 2:
            model_rows.append(cur_row)
            cur_row = []
    if cur_row:
        model_rows.append(cur_row)

    rows = [switcher_row, *model_rows]

    # Reference Row (Available for ALL Image models)
    ref_count = len(ref_images)
    ref_limit = minfo.get("ref_limit", 10)
    if ref_count == 0:
        rows.append([
            InlineKeyboardButton(
                text=f"📎 Добавить фото-референс (до {ref_limit} шт.)",
                callback_data=f"ref_hint:{owner_id}",
                style="primary"
            )
        ])
    else:
        grid_lbl = "✅ 🔲 Сетка 3×3 (снять)" if draft.get("has_grid") else "🔲 Сетка на референс"
        rows.append([
            InlineKeyboardButton(
                text=f"📎 Референсы: {ref_count}/{ref_limit} фото ✅",
                callback_data=f"ref_hint:{owner_id}"
            ),
            InlineKeyboardButton(text=grid_lbl, callback_data=f"rgrid:{owner_id}"),
            InlineKeyboardButton(text="🗑 Очистить", callback_data=f"rclear:{owner_id}", style="danger"),
        ])

    # Image Quality / Resolution Row (1K, 2K, 4K)
    res_buttons = []
    for r in IMAGE_RESOLUTION_OPTIONS:
        is_active = r == res
        lbl = f"✅ {r}" if is_active else r
        btn_kwargs = {"style": "primary"} if is_active else {}
        res_buttons.append(InlineKeyboardButton(text=lbl, callback_data=f"sir:{r}:{owner_id}", **btn_kwargs))
    rows.append(res_buttons)

    # Image Aspect Ratio Row (1:1, 16:9, 9:16, 4:3, 3:4)
    ratio_buttons = []
    for rat in IMAGE_RATIO_OPTIONS:
        is_active = rat == ratio
        lbl = f"✅ {rat}" if is_active else rat
        btn_kwargs = {"style": "primary"} if is_active else {}
        ratio_buttons.append(InlineKeyboardButton(text=lbl, callback_data=f"sia:{rat}:{owner_id}", **btn_kwargs))
    rows.append(ratio_buttons)

    # Action row
    cost = calculate_credit_cost(cur_model, 1, res)
    btn_text = f"🎨 Сгенерировать фото (~{cost} кр.)" if cost > 0 else "🎨 Сгенерировать фото"
    rows.append([
        InlineKeyboardButton(text=btn_text, callback_data=f"gen:{owner_id}", style="success"),
        InlineKeyboardButton(text="❌ Отмена", callback_data=f"can:{owner_id}", style="danger")
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def sync_draft_references(draft: Dict[str, Any]) -> None:
    """Ensure draft['ref_images'] matches current model capabilities and preserves all uploaded refs."""
    cur_model = draft.get("model_key", DEFAULT_MODEL)
    minfo = MODELS.get(cur_model, MODELS[DEFAULT_MODEL])
    ref_limit = minfo.get("ref_limit", 30 if minfo.get("category") == "video" else 10)

    # Collect all raw uploaded images
    all_refs = list(draft.get("all_uploaded_refs") or [])
    if not all_refs:
        existing = list(draft.get("orig_ref_images") or draft.get("ref_images") or [])
        if not existing and draft.get("image_bytes"):
            existing = [draft["image_bytes"]]
        all_refs = existing
        draft["all_uploaded_refs"] = list(all_refs)

    if not all_refs:
        draft["ref_images"] = []
        draft["orig_ref_images"] = None
        draft["image_bytes"] = None
        return

    # Effective base refs based on current model
    if minfo.get("multi_ref"):
        base_refs = list(all_refs[:ref_limit])
    else:
        base_refs = list(all_refs[:1])

    if draft.get("has_grid"):
        current_orig = draft.get("orig_ref_images") or []
        if current_orig != base_refs:
            draft["orig_ref_images"] = list(base_refs)
            draft["ref_images"] = [
                image_utils.overlay_grid(b, rows=3, cols=3, thickness_mode="thick", color="contrast")
                for b in base_refs if b
            ]
    else:
        draft["orig_ref_images"] = None
        draft["ref_images"] = base_refs

    draft["image_bytes"] = draft["ref_images"][0] if draft["ref_images"] else None


def get_user_display_name(user) -> str:
    """Format user display name with @username if available, else html mention."""
    if not user:
        return ""
    username = getattr(user, "username", None)
    if username:
        return f"@{username}"
    full_name = getattr(user, "full_name", "") or getattr(user, "first_name", "") or "Пользователь"
    if hasattr(user, "mention_html"):
        return user.mention_html(full_name)
    return full_name


def format_draft_text(draft: Dict[str, Any]) -> str:
    sync_draft_references(draft)
    menu_mode = draft.get("menu_mode", "video")
    if menu_mode == "image":
        return format_image_draft_text(draft)
    if menu_mode == "motion":
        return format_motion_draft_text(draft)
    return format_video_draft_text(draft)


def format_motion_draft_text(draft: Dict[str, Any]) -> str:
    has_img = bool(draft.get("motion_image"))
    has_vid = bool(draft.get("ref_video"))
    sec = int(draft.get("motion_sec") or 0)
    res = draft.get("resolution", "720p")
    model_name = MODELS.get(draft.get("model_key", MOTION_MODEL_KEY), MODELS[MOTION_MODEL_KEY])["name"]
    step1 = "✅ Фото персонажа" if has_img else "1️⃣ Пришли фото персонажа"
    if has_vid:
        step2 = "✅ Видео с движением"
    elif has_img:
        step2 = "2️⃣ Пришли видео с движением"
    else:
        step2 = "2️⃣ Видео с движением (после фото)"
    if has_vid and sec and not (3 <= sec <= 30):
        warn = f"\n⚠️ Видео {sec} сек — нужно от 3 до 30 сек"
    else:
        warn = ""
    dur = f"⏱ Длительность: <b>{sec} сек</b> (как у видео)\n" if sec else ""
    return (
        f"🕺 <b>{html.escape(model_name)}</b> · {res}\n\n"
        f"{step1}\n{step2}\n{dur}"
        "<i>Персонаж повторит движения из видео.</i>"
        f"{warn}"
    )


def format_video_draft_text(draft: Dict[str, Any]) -> str:
    prompt = draft.get("prompt", "—")
    cur_model = draft.get("model_key", DEFAULT_MODEL)
    if cur_model not in VIDEO_MODEL_KEYS:
        cur_model = DEFAULT_MODEL
    minfo = MODELS.get(cur_model, MODELS[DEFAULT_MODEL])
    step = draft.get("step", "model")

    ref_images: List[bytes] = draft.get("ref_images", [])
    ref_count = len(ref_images)
    ref_limit = minfo.get("ref_limit", 1)
    ref_mode = draft.get("ref_mode", "ref")

    if ref_count > 0:
        grid_note = " <i>(с толстой сеткой 3×3)</i>" if draft.get("has_grid") else ""
        if minfo.get("multi_ref"):
            mode_str = "Референс персонажа/сцены" if ref_mode == "ref" else "Первый кадр (Start Frame)"
            ref_badge = f"📎 Прикреплено: <b>{ref_count} из {ref_limit} фото</b> ({mode_str}){grid_note}"
        else:
            ref_badge = f"🖼 Прикреплено: <b>{ref_count} фото</b> (Image-to-Video){grid_note}"
    else:
        ref_badge = f"📝 По тексту <i>(отправьте фото в чат, чтобы добавить референс — до {ref_limit} шт.)</i>"

    user_line = f"👤 <b>Автор:</b> {draft.get('user_name')}\n" if draft.get("user_name") else ""
    video_line = "🎞 <b>Видео-референс:</b> прикреплен к видео ✅\n" if draft.get("ref_video") else ""
    audio_ref_line = "🎵 <b>Аудио-референс:</b> прикреплен к видео ✅\n" if draft.get("audio_bytes") else ""

    if minfo.get("backend") == "davinci_voice":
        audio_ref = "🎵 Аудио-референс прикреплен (Voice Changer)" if draft.get("audio_bytes") else ref_badge
        cost = calculate_credit_cost(cur_model, 0, "")
        cost_line = f"💳 <b>Стоимость:</b> ~{cost} кредитов\n" if cost > 0 else ""
        return (
            f"🎙 <b>Меню озвучки ElevenLabs V3</b>\n\n"
            f"{user_line}"
            f"🤖 <b>Модель:</b> {minfo['name']} — <i>{minfo['desc']}</i>\n"
            f"📝 <b>Текст для озвучки:</b> <i>{html.escape(str(prompt))}</i>\n"
            f"📌 <b>Референс:</b> {audio_ref}\n"
            f"{cost_line}\n"
            f"👇 <i>Нажмите «Озвучить» или переключите модель:</i>\n"
            f"<code>build: {BUILD_ID}</code>"
        )

    model_durs = minfo.get("durations", list(range(1, 31)))
    max_dur = max(model_durs) if model_durs else 15
    dur = max(1, min(max_dur, int(draft.get("duration", DEFAULT_DURATION))))
    draft["duration"] = dur

    if step == "model":
        return (
            f"🎬 <b>Шаг 1 из 3: Выберите модель для видео</b>\n\n"
            f"{user_line}"
            f"📝 <b>Промпт:</b> <i>{html.escape(str(prompt))}</i>\n"
            f"📌 <b>Референсы:</b> {ref_badge}\n"
            f"{video_line}"
            f"{audio_ref_line}\n"
            f"👇 <i>Выберите нейросеть для генерации ниже:</i>\n"
            f"<code>build: {BUILD_ID}</code>"
        )

    if step == "duration":
        return (
            f"⏱ <b>Шаг 2 из 3: Выберите длительность видео</b>\n\n"
            f"{user_line}"
            f"🤖 <b>Модель:</b> {minfo['name']} (максимум {max_dur} сек)\n"
            f"📝 <b>Промпт:</b> <i>{html.escape(str(prompt))}</i>\n"
            f"📌 <b>Референсы:</b> {ref_badge}\n"
            f"{video_line}"
            f"{audio_ref_line}\n"
            f"⏱ Выбрано: <b>{dur} сек</b>\n\n"
            f"👇 <i>Нажмите кнопку с нужным количеством секунд (от 1 до {max_dur}с):</i>\n"
            f"<code>build: {BUILD_ID}</code>"
        )

    # step == "quality"
    dur_str = f"{dur} сек"
    res = draft.get("resolution", DEFAULT_RESOLUTION)
    ratio = draft.get("ratio", DEFAULT_RATIO)
    audio = draft.get("audio", DEFAULT_AUDIO)
    audio_line = f"🔊 <b>Звук:</b> {'Включен ✅' if audio else 'Выключен 🔇'}\n" if minfo.get("has_audio") else ""

    cost = calculate_credit_cost(cur_model, dur, res)
    cost_line = f"💳 <b>Стоимость:</b> ~{cost} кредитов\n" if cost > 0 else "💳 <b>Стоимость:</b> Бесплатно\n"

    return (
        f"⚙️ <b>Шаг 3 из 3: Настройка качества и запуск</b>\n\n"
        f"{user_line}"
        f"🤖 <b>Модель:</b> {minfo['name']}\n"
        f"⏱ <b>Длительность:</b> {dur_str}\n"
        f"📝 <b>Промпт:</b> <i>{html.escape(str(prompt))}</i>\n"
        f"📌 <b>Референсы:</b> {ref_badge}\n"
        f"{video_line}"
        f"{audio_ref_line}"
        f"📐 <b>Разрешение и формат:</b> {res} | {ratio}\n"
        f"{audio_line}"
        f"{cost_line}\n"
        f"👇 <i>Выберите настройки качества и нажмите «Сгенерировать видео»:</i>\n"
        f"<code>build: {BUILD_ID}</code>"
    )


def format_image_draft_text(draft: Dict[str, Any]) -> str:
    prompt = draft.get("prompt", "—")
    cur_model = draft.get("model_key", DEFAULT_IMAGE_MODEL)
    if cur_model not in IMAGE_MODEL_KEYS:
        cur_model = DEFAULT_IMAGE_MODEL
    minfo = MODELS.get(cur_model, MODELS[DEFAULT_IMAGE_MODEL])

    res = draft.get("image_resolution", DEFAULT_IMAGE_RESOLUTION)
    ratio = draft.get("image_ratio", DEFAULT_IMAGE_RATIO)
    ref_images: List[bytes] = draft.get("ref_images", [])
    ref_count = len(ref_images)
    ref_limit = minfo.get("ref_limit", 10)

    if ref_count > 0:
        grid_note = " <i>(с толстой сеткой 3×3)</i>" if draft.get("has_grid") else ""
        ref_badge = f"📎 Прикреплено: <b>{ref_count} из {ref_limit} фото-референсов</b> ✅{grid_note}"
    else:
        ref_badge = f"📝 По тексту <i>(пришлите фото в чат для добавления референса — до {ref_limit} шт.)</i>"

    user_line = f"👤 <b>Автор:</b> {draft.get('user_name')}\n" if draft.get("user_name") else ""
    cost = calculate_credit_cost(cur_model, 1, res)
    cost_line = f"💳 <b>Стоимость:</b> ~{cost} кр.\n" if cost > 0 else "💳 <b>Стоимость:</b> Бесплатно\n"

    return (
        f"🖼 <b>Отдельное меню генерации изображений</b>\n\n"
        f"{user_line}"
        f"🤖 <b>Фото-модель:</b> {minfo['name']} — <i>{minfo['desc']}</i>\n"
        f"📝 <b>Промпт:</b> <i>{html.escape(str(prompt))}</i>\n"
        f"📌 <b>Референсы:</b> {ref_badge}\n"
        f"📐 <b>Качество и пропорции:</b> {res} | {ratio}\n"
        f"{cost_line}\n"
        f"💡 <i>Отправьте фото в чат, чтобы добавить референс, или нажмите «Сгенерировать фото»:</i>"
    )


async def probe_video_seconds(data: bytes) -> int:
    """Длительность видео в секундах (ffprobe). 0 — если не удалось определить."""
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(data)
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return max(1, int(round(float(out.decode().strip()))))
    except Exception:
        return 0
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


DRAFT_IDLE_SEC = 15 * 60  # черновик живёт 15 минут без действий


def touch_draft(draft: Dict[str, Any]) -> None:
    draft["touched_at"] = time.time()


def fresh_draft(user_id: int) -> Optional[Dict[str, Any]]:
    """Active draft only. Stale drafts are dropped so old menus stop catching new messages."""
    d = user_drafts.get(user_id)
    if d and time.time() - d.get("touched_at", 0) > DRAFT_IDLE_SEC:
        user_drafts.pop(user_id, None)
        return None
    return d


def create_draft_for_user(
    user_id: int,
    prompt: str,
    image_bytes: Optional[bytes] = None,
    ref_images: Optional[List[bytes]] = None,
    user_name: str = "",
    message_id: Optional[int] = None,
    menu_mode: str = "video",
    audio_bytes: Optional[bytes] = None,
    ref_video: Optional[bytes] = None,
) -> Dict[str, Any]:
    prev_draft = fresh_draft(user_id)
    if ref_video is None and prev_draft:
        ref_video = prev_draft.get("ref_video")
    if audio_bytes is None and prev_draft:
        audio_bytes = prev_draft.get("audio_bytes")

    prefs = get_user_prefs(user_id)
    refs: List[bytes] = []
    if ref_images:
        refs.extend([b for b in ref_images if b])
    elif image_bytes:
        refs.append(image_bytes)

    active_model = prefs["image_model_key"] if menu_mode == "image" else prefs["model_key"]
    if menu_mode == "motion":
        active_model = MOTION_MODEL_KEY
    if menu_mode == "image" and active_model not in IMAGE_MODEL_KEYS:
        active_model = DEFAULT_IMAGE_MODEL
    elif menu_mode == "video" and active_model not in VIDEO_MODEL_KEYS:
        active_model = DEFAULT_MODEL

    if menu_mode == "video" and len(refs) > 1:
        cur_minfo = MODELS.get(active_model, {})
        if not cur_minfo.get("multi_ref"):
            active_model = DEFAULT_MODEL
            prefs["model_key"] = DEFAULT_MODEL

    model_durs = MODELS.get(active_model, {}).get("durations", [5])
    max_d = max(model_durs) if model_durs else 15
    init_dur = min(max_d, max(1, int(prefs.get("duration", DEFAULT_DURATION))))

    draft = {
        "prompt": prompt,
        "image_bytes": refs[0] if refs else None,
        "ref_images": list(refs),
        "all_uploaded_refs": list(refs),
        "ref_mode": prefs.get("ref_mode", "ref"),
        "menu_mode": menu_mode,
        "step": "model" if menu_mode == "video" else "main",
        "model_key": active_model,
        "duration": init_dur,
        "resolution": prefs["resolution"],
        "image_resolution": prefs.get("image_resolution", DEFAULT_IMAGE_RESOLUTION),
        "ratio": prefs["ratio"],
        "image_ratio": prefs.get("image_ratio", DEFAULT_IMAGE_RATIO),
        "audio": prefs["audio"],
        "audio_bytes": audio_bytes,
        "ref_video": ref_video,
        "owner_id": user_id,
        "user_name": user_name,
        "original_message_id": message_id,
        "menu_message_id": None,
        "menu_chat_id": None,
    }
    if menu_mode == "motion":
        draft["resolution"] = "720p"
    sync_draft_references(draft)
    user_drafts[user_id] = draft
    touch_draft(draft)
    return draft


# --- Command Handlers ---

@router.message(CommandStart())
@router.message(Command("help"))
async def handle_start_and_help(message: Message, state: FSMContext):
    await state.clear()
    first_name = message.from_user.first_name if message.from_user else "друг"
    uid = message.from_user.id if message.from_user else 0

    start_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎬 Видео", callback_data=f"open_menu:video:{uid}", style="success"),
            InlineKeyboardButton(text="🖼 Фото", callback_data=f"open_menu:image:{uid}", style="primary"),
            InlineKeyboardButton(text="🕺 Motion", callback_data=f"open_menu:motion:{uid}", style="primary"),
        ]
    ])

    in_group = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    how = (
        "Напишите <code>/video текст</code>, <code>/image текст</code> или <code>/voice текст</code>"
        if in_group
        else "Просто напишите, что создать, или выберите ниже"
    )
    text = (
        f"👋 <b>{html.escape(first_name)}, это Poco AI</b>\n"
        f"Видео, фото и Motion за пару тапов.\n\n"
        f"{how} 👇\n\n"
        f"<blockquote>📎 Фото с подписью станет референсом\n"
        f"💳 /balance · 🔲 /grid · 🤖 /model</blockquote>"
    )
    if in_group:
        await message.reply(text, reply_markup=start_kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=start_kb, parse_mode="HTML")


async def extract_image_bytes(message: Message, bot: Bot) -> Optional[bytes]:
    """Extract image bytes from message directly (photo/doc) or from reply_to_message."""
    try:
        if message.photo:
            photo = message.photo[-1]
            file_info = await bot.get_file(photo.file_id)
            buf = io.BytesIO()
            await bot.download_file(file_info.file_path, destination=buf)
            return buf.getvalue()

        if message.document:
            is_img = (message.document.mime_type and message.document.mime_type.startswith("image/")) or (
                message.document.file_name and message.document.file_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            )
            if is_img:
                file_info = await bot.get_file(message.document.file_id)
                buf = io.BytesIO()
                await bot.download_file(file_info.file_path, destination=buf)
                return buf.getvalue()

        if message.reply_to_message:
            if message.reply_to_message.photo:
                photo = message.reply_to_message.photo[-1]
                file_info = await bot.get_file(photo.file_id)
                buf = io.BytesIO()
                await bot.download_file(file_info.file_path, destination=buf)
                return buf.getvalue()

            if message.reply_to_message.document:
                doc = message.reply_to_message.document
                is_img = (doc.mime_type and doc.mime_type.startswith("image/")) or (
                    doc.file_name and doc.file_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                )
                if is_img:
                    file_info = await bot.get_file(doc.file_id)
                    buf = io.BytesIO()
                    await bot.download_file(file_info.file_path, destination=buf)
                    return buf.getvalue()
    except Exception as e:
        logger.warning(f"Failed to extract image bytes: {e}")

    return None


# --- In-Memory Rolling Media Cache (Multi-Reference & Album Tracking) ---
media_group_cache: Dict[str, List[bytes]] = {}
recent_chat_media: Dict[int, Tuple[Optional[str], bytes]] = {}
recent_user_photos: Dict[Tuple[int, int], List[Tuple[float, int, bytes]]] = {}


def remember_photo(chat_id: int, user_id: int, message_id: int, media_group_id: Optional[str], img_bytes: bytes):
    """Store recent photo in rolling memory for multi-reference extraction."""
    if not img_bytes:
        return
    now = time.time()
    recent_chat_media[message_id] = (media_group_id, img_bytes)
    if len(recent_chat_media) > 300:
        oldest_k = next(iter(recent_chat_media))
        del recent_chat_media[oldest_k]

    if media_group_id:
        group_list = media_group_cache.setdefault(media_group_id, [])
        if not any(b == img_bytes for b in group_list):
            group_list.append(img_bytes)
        if len(media_group_cache) > 100:
            oldest_g = next(iter(media_group_cache))
            del media_group_cache[oldest_g]

    u_key = (chat_id, user_id)
    u_list = recent_user_photos.setdefault(u_key, [])
    u_list.append((now, message_id, img_bytes))
    recent_user_photos[u_key] = [(ts, mid, b) for (ts, mid, b) in u_list if now - ts < 600][-20:]


def get_recent_photos_for_user(chat_id: int, user_id: int, max_age_sec: float = 120.0) -> List[bytes]:
    """Retrieve recent photos sent by this user in this chat within max_age_sec."""
    now = time.time()
    u_key = (chat_id, user_id)
    entries = recent_user_photos.get(u_key, [])
    return [b for (ts, mid, b) in entries if now - ts <= max_age_sec]


async def get_all_photos_for_message_or_reply(message: Message, bot: Bot) -> List[bytes]:
    """Find ALL reference photos: from attached photo(s), album, reply to photo/album, or recent user uploads."""
    refs: List[bytes] = []

    # 1. Direct attachment on this message
    direct_img = await extract_image_bytes(message, bot)
    if direct_img:
        refs.append(direct_img)
        remember_photo(message.chat.id, message.from_user.id, message.message_id, message.media_group_id, direct_img)

    # If this message was part of an album
    if message.media_group_id and message.media_group_id in media_group_cache:
        album_imgs = media_group_cache[message.media_group_id]
        if album_imgs:
            return list(album_imgs)

    # 2. Check reply_to_message
    rep = message.reply_to_message
    if rep:
        # Replying to an album!
        if rep.media_group_id and rep.media_group_id in media_group_cache:
            album_imgs = media_group_cache[rep.media_group_id]
            if album_imgs:
                return list(album_imgs)

        # Replying to a cached message
        if rep.message_id in recent_chat_media:
            gid, b = recent_chat_media[rep.message_id]
            if gid and gid in media_group_cache:
                return list(media_group_cache[gid])
            if b:
                refs.append(b)
        else:
            rep_img = await extract_image_bytes(rep, bot)
            if rep_img:
                refs.append(rep_img)
                remember_photo(message.chat.id, rep.from_user.id if rep.from_user else message.from_user.id, rep.message_id, rep.media_group_id, rep_img)

        # If user replied to one photo, but sent multiple photos in the chat within the last 120s:
        rep_uid = rep.from_user.id if rep.from_user else message.from_user.id
        recent = get_recent_photos_for_user(message.chat.id, rep_uid, max_age_sec=120.0)
        if len(refs) <= 1 and len(recent) > 1:
            return list(recent)

        if refs:
            return refs

    # 3. If no direct reply or attachment, retrieve recent photos from this user in this chat
    if not refs:
        recent = get_recent_photos_for_user(message.chat.id, message.from_user.id, max_age_sec=60.0)
        if recent:
            return list(recent)

    return refs


def _is_admin_user(message: Message) -> bool:
    user_un = (message.from_user.username or "").lower().strip()
    return (
        (bool(user_un) and user_un in [u.lower() for u in getattr(config, "ADMIN_TELEGRAM_USERNAMES", [])])
        or message.from_user.id in getattr(config, "ADMIN_TELEGRAM_IDS", [])
    )


@router.message(Command("token", "set_token"))
async def handle_set_token(message: Message, command: CommandObject, queue: GenerationQueue):
    """Update DaVinci x-token on the fly without restarting the bot."""
    if not _is_admin_user(message):
        await message.reply("🔒 Доступ только для создателя @GermanUstinf.", parse_mode="HTML")
        return
    raw = (command.args or "").strip()
    if not raw:
        await message.reply(
            "🔑 <b>Обновление токена DaVinci AI:</b>\n"
            "Отправьте: <code>/token ваш_x_token</code>",
            parse_mode="HTML",
        )
        return
    parts = raw.split()
    new_tok = parts[0].strip()
    new_ref = parts[1].strip() if len(parts) > 1 else None
    queue.davinci_client.set_token(new_tok, new_ref)
    await message.reply("✅ <b>Токен DaVinci AI успешно обновлен и сохранен!</b>", parse_mode="HTML")


@router.message(Command("id", "whoami", ignore_case=True, ignore_mention=True))
async def handle_id_command(message: Message):
    """Show Telegram user profile, user_id and chat_id."""
    user_id = message.from_user.id
    user_un = message.from_user.username
    chat_id = message.chat.id
    chat_type = message.chat.type
    await message.reply(
        f"👤 <b>Ваш профиль в Telegram:</b>\n"
        f"• <b>ID:</b> <code>{user_id}</code>\n"
        f"• <b>Username:</b> @{user_un or 'отсутствует'}\n"
        f"• <b>Имя:</b> {html.escape(message.from_user.full_name or '')}\n"
        f"• <b>Чат ID:</b> <code>{chat_id}</code> ({chat_type})",
        parse_mode="HTML",
    )


@router.message(Command("admin", "auth", ignore_case=True, ignore_mention=True))
async def handle_admin_auth_command(message: Message, command: CommandObject):
    """Authenticate Telegram user as admin with the master password."""
    raw = (command.args or "").strip()
    user_id = message.from_user.id
    user_un = (message.from_user.username or "").lower().strip()

    if access_manager.verify_admin_password(raw):
        if user_id not in config.ADMIN_TELEGRAM_IDS:
            config.ADMIN_TELEGRAM_IDS.append(user_id)
        await message.reply(
            f"👑 <b>Вы успешно авторизованы как Администратор!</b>\n\n"
            f"👤 <b>Username:</b> @{user_un or 'не задан'}\n"
            f"🆔 <b>Ваш ID:</b> <code>{user_id}</code>\n\n"
            f"✨ Теперь вам доступны команды:\n"
            f"• <code>/genkey [заметка]</code> — генерация ключа доступа\n"
            f"• <code>/keys</code> — просмотр активных ключей\n"
            f"• <code>/token [x-token]</code> — обновление токена DaVinci",
            parse_mode="HTML",
        )
    else:
        await message.reply(
            f"🔑 <b>Авторизация администратора:</b>\n"
            f"Отправьте команду с мастер-паролем:\n"
            f"<code>/admin ваш_пароль</code>\n\n"
            f"<i>Ваш ID: <code>{user_id}</code>, Username: @{user_un or 'не задан'}</i>",
            parse_mode="HTML",
        )


@router.message(Command("genkey", "key", "createkey", "создатьключ", ignore_case=True, ignore_mention=True))
async def handle_genkey_command(message: Message, command: CommandObject):
    """Generate a new random access key for POCO AI Studio (restricted to German / Admins)."""
    user_un = (message.from_user.username or "").lower().strip()
    user_id = message.from_user.id
    args = (command.args or "").strip()

    is_admin = (
        user_un in [u.lower() for u in getattr(config, "ADMIN_TELEGRAM_USERNAMES", [])]
        or user_id in getattr(config, "ADMIN_TELEGRAM_IDS", [])
        or access_manager.verify_admin_password(args)
    )
    if not is_admin:
        await message.reply(
            f"🔒 <b>Доступ запрещен.</b>\n"
            f"Генерация ключей доступна только создателю бота @GermanUstinf.\n\n"
            f"👤 Ваш username: @{user_un or 'отсутствует'}\n"
            f"🆔 Ваш ID: <code>{user_id}</code>\n\n"
            f"💡 Чтобы войти с паролем создателя, введите: <code>/admin ваш_пароль</code>",
            parse_mode="HTML",
        )
        return

    note = "" if access_manager.verify_admin_password(args) else args
    note = note or f"Telegram от @{message.from_user.username or user_id}"
    new_key = access_manager.generate_key(note=note, created_by=f"@{message.from_user.username or user_id}")

    await message.reply(
        f"✨ <b>Новый ключ доступа к POCO AI Studio сгенерирован:</b>\n\n"
        f"🔑 <code>{new_key}</code>\n\n"
        f"📝 <b>Заметка:</b> {html.escape(note)}\n"
        f"🌐 <b>Сайт студии:</b> http://localhost:7860\n\n"
        f"<i>Нажмите на ключ в сообщении выше, чтобы скопировать и отправить пользователю!</i>",
        parse_mode="HTML",
    )


@router.message(Command("keys", "ключи", ignore_case=True, ignore_mention=True))
async def handle_list_keys_command(message: Message):
    """List recent access keys (restricted to German / Admins)."""
    user_un = (message.from_user.username or "").lower().strip()
    user_id = message.from_user.id

    is_admin = (
        user_un in [u.lower() for u in getattr(config, "ADMIN_TELEGRAM_USERNAMES", [])]
        or user_id in getattr(config, "ADMIN_TELEGRAM_IDS", [])
    )
    if not is_admin:
        await message.reply(
            f"🔒 Доступ только для создателя @GermanUstinf.\n"
            f"Авторизация: <code>/admin ваш_пароль</code>",
            parse_mode="HTML",
        )
        return

    keys = access_manager.get_all_keys()[:15]
    if not keys:
        await message.reply("Список ключей пуст. Создайте ключ командой /genkey [заметка]", parse_mode="HTML")
        return

    lines = ["🔑 <b>Последние ключи доступа к сайту:</b>\n"]
    for k in keys:
        status_icon = "🟢" if k.get("active", True) else "🔴"
        bind_status = "📱 <i>Используется</i>" if k.get("bound_client_id") else "⚪ <i>Свободен</i>"
        lines.append(
            f"{status_icon} <code>{k['key']}</code> — <i>{html.escape(k.get('note', ''))}</i> ({bind_status}, входов: {k.get('used_count', 0)})"
        )
    lines.append("\n<i>Создать новый: <code>/genkey [заметка]</code></i>")
    lines.append("<i>Сбросить привязку: <code>/unbind КЛЮЧ</code></i>")
    await message.reply("\n".join(lines), parse_mode="HTML")


@router.message(Command("unbind", "resetkey", "сброситьключ", ignore_case=True, ignore_mention=True))
async def handle_unbind_key_command(message: Message, command: CommandObject):
    """Unbind a key from its device so another person can use it."""
    user_un = (message.from_user.username or "").lower().strip()
    user_id = message.from_user.id
    is_admin = (
        user_un in [u.lower() for u in getattr(config, "ADMIN_TELEGRAM_USERNAMES", [])]
        or user_id in getattr(config, "ADMIN_TELEGRAM_IDS", [])
    )
    if not is_admin:
        await message.reply("🔒 Доступ только для создателя @GermanUstinf.", parse_mode="HTML")
        return

    target_key = (command.args or "").strip().upper()
    if not target_key:
        await message.reply("Использование: <code>/unbind POCO-XXXX-XXXX-XXXX</code>", parse_mode="HTML")
        return

    ok = access_manager.unbind_key(target_key)
    if ok:
        await message.reply(f"✅ Привязка ключа <code>{target_key}</code> сброшена! Теперь его можно активировать на новом устройстве.", parse_mode="HTML")
    else:
        await message.reply(f"❌ Ключ <code>{target_key}</code> не найден в базе.", parse_mode="HTML")


@router.message(Command("last", "sync"))
async def handle_last_command(message: Message, command: CommandObject, queue: GenerationQueue):
    """Fetch and send the latest completed video(s)/image(s) from the DaVinci website with watermark."""
    raw = (command.args or "").strip()
    count = int(raw) if raw.isdigit() else 1
    status_msg = await message.reply(
        "📥 <b>Забираю готовую генерацию с сайта и накладываю ватермарку...</b>",
        parse_mode="HTML",
    )
    try:
        sent = await queue.deliver_latest_from_davinci(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            user_name=get_user_display_name(message.from_user),
            reply_to_message_id=message.message_id,
            count=count,
        )
        if sent > 0:
            try:
                await status_msg.delete()
            except Exception:
                pass
        else:
            await status_msg.edit_text("⚠️ На сайте пока нет завершенных генераций.", parse_mode="HTML")
    except Exception as e:
        await status_msg.edit_text(f"❌ <b>Ошибка получения файла с сайта:</b> {html.escape(str(e))}", parse_mode="HTML")


@router.message(Command("balance", "credits", "account", "баланс", "кредиты"))
async def handle_balance_command(message: Message, queue: GenerationQueue):
    """View current DaVinci AI account credit balance, plan tier, and generation stats."""
    status_msg = await message.reply(
        "🔄 <b>Запрашиваю актуальный баланс кредитов...</b>",
        parse_mode="HTML"
    )
    try:
        data = await queue.davinci_client.get_account_balance()
        total = data["total_credits"]
        consumable = data["consumable_credits"]
        plan = data["plan_credits"]
        tier = data["tier_name"]
        renewal = data["renewal_date"]
        gen_count = data["generation_count"]
        auto_refill = "Включено ✅" if data["auto_refill"] else "Выключено ❌"

        text = (
            f"💳 <b>Баланс Poco AI</b>\n\n"
            f"💰 <b>Всего кредитов:</b> <code>{total:,}</code>\n"
            f"├ <i>Пополняемые (Consumable):</i> <code>{consumable:,}</code>\n"
            f"└ <i>Тарифные (Plan):</i> <code>{plan:,}</code>\n\n"
            f"👑 <b>Тариф:</b> {tier} (Premium ✅)\n"
            f"📅 <b>Продление подписки:</b> {renewal}\n"
            f"📊 <b>Всего генераций на аккаунте:</b> {gen_count}\n"
            f"⚙️ <b>Авто-пополнение кредитов:</b> {auto_refill}\n\n"
            f"💡 <i>Перед каждой генерацией в меню показывается точная стоимость задачи в кредитах!</i>"
        )
        await status_msg.edit_text(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Failed to fetch balance: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ <b>Не удалось получить баланс кредитов:</b>\n{html.escape(str(e))}",
            parse_mode="HTML"
        )


# --- Photos & Documents Handling (Universal Reference Support) ---

# Buffers for Telegram albums (media groups) and rapid photo batches
media_group_buffers: Dict[str, Dict[str, Any]] = {}
MEDIA_GROUP_DEBOUNCE_SEC = 1.5


async def show_or_update_menu(message: Message, bot: Bot, draft: Dict[str, Any], user_id: int):
    touch_draft(draft)
    """Edit the already open settings menu in place (no duplicate menus), or send a new one."""
    text = format_draft_text(draft)
    kb = build_settings_keyboard(draft, user_id)
    mid = draft.get("menu_message_id")
    if mid and draft.get("menu_chat_id") == message.chat.id:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=mid,
                text=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
            return
        except Exception as e:
            if "not modified" in str(e).lower():
                return
            logger.debug(f"Failed to edit existing menu message: {e}")
    sent = await message.reply(text=text, reply_markup=kb, parse_mode="HTML")
    draft["menu_message_id"] = sent.message_id
    draft["menu_chat_id"] = sent.chat.id


MAX_TG_DOWNLOAD_BYTES = 20 * 1024 * 1024  # Telegram Bot API download limit


def _message_video_file(message: Message):
    """Return (file_id, file_size) for a video-like attachment on the message, else None."""
    if message.video:
        return message.video.file_id, message.video.file_size
    if message.video_note:
        return message.video_note.file_id, message.video_note.file_size
    if message.animation:
        return message.animation.file_id, message.animation.file_size
    doc = message.document
    if doc and (
        (doc.mime_type and doc.mime_type.startswith("video/"))
        or (doc.file_name and doc.file_name.lower().endswith((".mp4", ".mov", ".webm", ".mkv")))
    ):
        return doc.file_id, doc.file_size
    return None


def _is_video_message(message: Message) -> bool:
    return _message_video_file(message) is not None


async def extract_video_bytes(message: Message, bot: Bot) -> Optional[bytes]:
    """Download a video from the message (or from the message it replies to). Raises ValueError if too big."""
    for m in (message, message.reply_to_message):
        if not m:
            continue
        info = _message_video_file(m)
        if not info:
            continue
        file_id, size = info
        if size and size > MAX_TG_DOWNLOAD_BYTES:
            raise ValueError("too_big")
        file_info = await bot.get_file(file_id)
        buf = io.BytesIO()
        await bot.download_file(file_info.file_path, destination=buf)
        return buf.getvalue()
    return None


@router.message(_is_video_message)
async def handle_video_reference(message: Message, bot: Bot, state: FSMContext):
    """Video as a reference: attach it to the draft so the selected model edits the video by the prompt."""
    user_id = message.from_user.id
    caption = (message.caption or "").strip()
    is_group = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

    clean_prompt = re.sub(
        r"^/(video|gen|prompt|v|s2)(@\w+)?\s*", "", caption, flags=re.I
    )
    if is_group:
        bot_info = await bot.me()
        clean_prompt = clean_prompt.replace(f"@{bot_info.username}", "").strip()
        addressed = (
            caption.lower().startswith(("/video", "/gen", "/prompt", "/v", "/s2"))
            or f"@{bot_info.username}".lower() in caption.lower()
            or (message.reply_to_message and message.reply_to_message.from_user
                and message.reply_to_message.from_user.id == bot_info.id)
            or fresh_draft(user_id) is not None
        )
        if not addressed:
            return
    clean_prompt = clean_prompt.strip()

    try:
        video_bytes = await extract_video_bytes(message, bot)
    except ValueError:
        await message.reply("⚠️ Видео больше 20 МБ — Telegram не даёт боту скачать такой файл. Пришлите видео короче/легче.")
        return
    except Exception as e:
        logger.error(f"Failed to download reference video: {e}", exc_info=True)
        await message.reply("⚠️ Не удалось скачать видео. Попробуйте ещё раз.")
        return
    if not video_bytes:
        return

    draft_m = fresh_draft(user_id)
    if draft_m and draft_m.get("menu_mode") == "motion":
        draft_m["ref_video"] = video_bytes
        draft_m["motion_sec"] = await probe_video_seconds(video_bytes)
        draft_m["model_key"] = draft_m.get("model_key") if draft_m.get("model_key") in MOTION_MODEL_KEYS else MOTION_MODEL_KEY
        await show_or_update_menu(message, bot, draft_m, user_id)
        return

    logger.info(f"[refs] video reference from user {user_id}: {len(video_bytes)} bytes, caption={bool(clean_prompt)}")

    # Extract first frame and audio track from the reference video
    first_frame = await extract_frame_from_video(video_bytes)
    video_audio = await extract_audio_from_video(video_bytes)

    draft = fresh_draft(user_id)
    if draft and draft.get("menu_mode", "video") == "video":
        if clean_prompt:
            draft["prompt"] = clean_prompt
    else:
        photos = get_recent_photos_for_user(message.chat.id, user_id, max_age_sec=60.0)
        draft = create_draft_for_user(
            user_id=user_id,
            prompt=clean_prompt or "Измени видео, сохранив движение и композицию",
            image_bytes=photos[0] if photos else first_frame,
            ref_images=photos if photos else ([first_frame] if first_frame else []),
            user_name=get_user_display_name(message.from_user),
            message_id=message.message_id,
            menu_mode="video",
            ref_video=video_bytes,
        )

    draft["ref_video"] = video_bytes
    if first_frame and not draft.get("ref_images") and not draft.get("image_bytes"):
        draft["image_bytes"] = first_frame
        draft["ref_images"] = [first_frame]
        draft["all_uploaded_refs"] = [first_frame]
    if video_audio and not draft.get("audio_bytes"):
        draft["audio_bytes"] = video_audio

    cur_model = draft.get("model_key", DEFAULT_MODEL)
    if not MODELS.get(cur_model, {}).get("video_ref"):
        draft["model_key"] = DEFAULT_MODEL
        get_user_prefs(user_id)["model_key"] = DEFAULT_MODEL
    sync_draft_references(draft)

    info_parts = []
    if first_frame:
        info_parts.append("• 🖼 Извлечен первый кадр (старт-кадр сцены)")
    if video_audio:
        info_parts.append("• 🎵 Извлечена звуковая дорожка из видео")
    hint_text = "\n".join(info_parts)
    try:
        await message.reply(
            f"🎞 <b>Видео принято в работу!</b>\n\n{hint_text}\n\n"
            f"💡 <i>Модели Seedance 2.5 и Kling 4.0 генерируют анимацию по фото и промпту (Image-to-Video). Опишите в промпте, что должен делать персонаж (например: «персонаж танцует брейк-данс под эту музыку»)!</i>",
            parse_mode="HTML"
        )
    except Exception:
        pass

    draft["menu_message_id"] = None
    await show_or_update_menu(message, bot, draft, user_id)



@router.message(F.photo)
@router.message(F.document)
async def handle_photo(message: Message, bot: Bot, state: FSMContext):
    if message.document:
        doc = message.document
        is_img = (doc.mime_type and doc.mime_type.startswith("image/")) or (
            doc.file_name and doc.file_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        )
        if not is_img:
            return

    # Extract bytes and immediately record into our rolling media memory
    img_bytes = await extract_image_bytes(message, bot)
    if img_bytes:
        remember_photo(
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            message_id=message.message_id,
            media_group_id=message.media_group_id,
            img_bytes=img_bytes,
        )

    draft_m = fresh_draft(message.from_user.id)
    if img_bytes and draft_m and draft_m.get("menu_mode") == "motion":
        draft_m["motion_image"] = img_bytes
        draft_m["model_key"] = draft_m.get("model_key") if draft_m.get("model_key") in MOTION_MODEL_KEYS else MOTION_MODEL_KEY
        await show_or_update_menu(message, bot, draft_m, message.from_user.id)
        return

    group_id = message.media_group_id
    # Buffer both albums and rapid multi-photo uploads by the same user
    key = f"{message.chat.id}:{group_id}" if group_id else f"{message.chat.id}:user_{message.from_user.id}"
    buf = media_group_buffers.setdefault(key, {"messages": [], "images": [], "task": None})
    buf["messages"].append(message)
    if img_bytes:
        buf["images"].append(img_bytes)

    if buf["task"] and not buf["task"].done():
        buf["task"].cancel()

    async def _flush():
        try:
            await asyncio.sleep(MEDIA_GROUP_DEBOUNCE_SEC)
        except asyncio.CancelledError:
            return
        data = media_group_buffers.pop(key, None)
        if not data:
            return
        msgs = sorted(data["messages"], key=lambda m: m.message_id)
        imgs = data.get("images", [])
        if group_id:
            cached_imgs = list(media_group_cache.get(group_id) or [])
            combined_imgs: List[bytes] = []
            for b in (imgs + cached_imgs):
                if not any(x == b for x in combined_imgs):
                    combined_imgs.append(b)
            imgs = combined_imgs
        try:
            await process_photo_batch(msgs, bot, state, direct_bytes=imgs)
        except Exception as e:
            logger.error(f"Photo batch processing failed: {e}", exc_info=True)

    buf["task"] = asyncio.create_task(_flush())


async def process_photo_batch(
    messages: List[Message],
    bot: Bot,
    state: FSMContext,
    direct_bytes: Optional[List[bytes]] = None,
):
    """Handle one photo or a whole album (all photos become references of ONE draft/menu)."""
    message = next((m for m in messages if (m.caption or "").strip()), messages[0])
    caption = (message.caption or "").strip()
    is_group = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    user_id = message.from_user.id

    images: List[bytes] = []
    if direct_bytes:
        images.extend([b for b in direct_bytes if b])
    else:
        for m in messages:
            img = await extract_image_bytes(m, bot)
            if img:
                images.append(img)
                remember_photo(m.chat.id, m.from_user.id, m.message_id, m.media_group_id, img)

    if not images:
        return

    logger.info(
        f"[refs] batch from user {user_id}: {len(messages)} msg(s), {len(images)} image(s), "
        f"unique={len(set(images))}, has_draft={fresh_draft(user_id) is not None}"
    )

    # In groups, process photos if addressed OR if the user currently has an active draft open
    if is_group:
        bot_info = await bot.me()
        bot_username = f"@{bot_info.username}".lower()
        cap_lower = caption.lower()
        addressed = (
            caption.startswith(("/video", "/gen", "/prompt", "/v", "/s2", "/image", "/poster", "/img", "/pic", "/photo", "/banana", "/qwen", "/voice", "/tts", "/eleven", "/elevenlabs", "/grid", "/сетка", "/mesh"))
            or bot_username in cap_lower
            or (message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id)
            or (not caption and fresh_draft(user_id) is not None)
        )
        if not addressed:
            return

    # Check for direct /grid command in caption
    if bool(re.search(r"^/(grid|сетка|mesh)", caption, re.I)):
        grid_args = re.sub(r"^/(grid|сетка|mesh)(@\w+)?\s*", "", caption, flags=re.I).strip()
        await process_grid_image(message, bot, images[0], grid_args)
        return

    is_image_cmd = bool(re.search(r"^/(image|poster|img|pic|photo|banana|qwen)", caption, re.I))
    is_voice_cmd = bool(re.search(r"^/(motion|mc|dance)", caption, re.I))
    clean_prompt = re.sub(
        r"^/(video|gen|prompt|v|s2|image|poster|img|pic|photo|banana|qwen|voice|tts|eleven|elevenlabs)(@\w+)?\s*",
        "",
        caption,
        flags=re.I,
    )
    if is_group:
        bot_info = await bot.me()
        bot_username = f"@{bot_info.username}".lower()
        clean_prompt = clean_prompt.replace(f"@{bot_info.username}", "").replace(bot_username, "").strip()
    else:
        clean_prompt = clean_prompt.strip()

    if not clean_prompt and message.reply_to_message:
        clean_prompt = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()

    # If user already has an active draft open -> attach photos to draft!
    if fresh_draft(user_id) is not None:
        draft = user_drafts[user_id]
        if clean_prompt:
            draft["prompt"] = clean_prompt

        all_refs = list(draft.get("all_uploaded_refs") or draft.get("orig_ref_images") or draft.get("ref_images") or [])
        for img in images:
            if not any(b == img for b in all_refs):
                all_refs.append(img)
        draft["all_uploaded_refs"] = list(all_refs)

        cur_model = draft.get("model_key", DEFAULT_MODEL)
        minfo = MODELS.get(cur_model, MODELS[DEFAULT_MODEL])
        if draft.get("menu_mode", "video") == "video" and len(all_refs) > 1 and not minfo.get("multi_ref"):
            cur_model = DEFAULT_MODEL
            draft["model_key"] = DEFAULT_MODEL
            get_user_prefs(user_id)["model_key"] = DEFAULT_MODEL

        sync_draft_references(draft)
        logger.info(
            f"[refs] draft of user {user_id}: model={draft.get('model_key')} "
            f"now {len(draft['ref_images'])} ref(s) (total stored: {len(all_refs)})"
        )
        await show_or_update_menu(message, bot, draft, user_id)
        return

    if not is_group and not clean_prompt:
        data = await state.get_data()
        existing_refs: List[bytes] = list(data.get("ref_images") or [])
        for img in images:
            if not any(b == img for b in existing_refs):
                existing_refs.append(img)
        await state.set_state(UserInputState.waiting_for_prompt)
        await state.update_data(image_bytes=existing_refs[0], ref_images=existing_refs)
        quick_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🎬 Открыть меню Видео", callback_data=f"open_menu:video:{user_id}", style="success"),
                InlineKeyboardButton(text="🖼 Открыть меню Фото", callback_data=f"open_menu:image:{user_id}", style="primary"),
            ]
        ])
        await message.answer(
            f"🖼 <b>Фото-референс получен ({len(existing_refs)} шт.)!</b>\n\n"
            f"• Напишите текстом промпт (что нужно сделать по этому референсу)\n"
            f"• Или отправьте ещё фото, если нужно несколько референсов\n"
            f"• Или сразу откройте нужное меню кнопкой ниже:",
            reply_markup=quick_kb,
            parse_mode="HTML"
        )
        return

    if not clean_prompt:
        clean_prompt = (
            "Стилизовать изображение по референсу в высоком качестве"
            if is_image_cmd
            else "Анимировать фото, реалистичное кинематографичное видео"
        )

    menu_mode = "image" if is_image_cmd else ("motion" if is_voice_cmd else "video")
    cur_prefs = get_user_prefs(user_id)
    cur_model = cur_prefs.get("image_model_key" if menu_mode == "image" else "model_key", DEFAULT_IMAGE_MODEL if menu_mode == "image" else DEFAULT_MODEL)
    minfo = MODELS.get(cur_model, MODELS[DEFAULT_MODEL])

    if menu_mode == "video" and len(images) > 1 and not minfo.get("multi_ref"):
        cur_model = DEFAULT_MODEL
        cur_prefs["model_key"] = DEFAULT_MODEL

    draft = create_draft_for_user(
        user_id=user_id,
        prompt=clean_prompt,
        image_bytes=images[0],
        ref_images=images,
        user_name=get_user_display_name(message.from_user),
        message_id=message.message_id,
        menu_mode=menu_mode,
    )
    draft["model_key"] = MOTION_MODEL_KEY if is_voice_cmd else cur_model

    sync_draft_references(draft)
    await show_or_update_menu(message, bot, draft, user_id)


@router.message(F.voice | F.audio)
async def handle_voice_or_audio(message: Message, bot: Bot, state: FSMContext):
    """Support attaching voice/audio reference for ANY video model or ElevenLabs."""
    is_group = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    caption_text = (message.caption or "").strip()
    is_eleven = "eleven" in caption_text.lower() or "озвуч" in caption_text.lower()

    if is_group and not is_eleven and not (message.caption and "видео" in message.caption.lower()):
        if message.from_user.id not in user_drafts:
            return

    try:
        media_obj = message.voice or message.audio
        file_info = await bot.get_file(media_obj.file_id)
        buf = io.BytesIO()
        await bot.download_file(file_info.file_path, destination=buf)
        audio_bytes = buf.getvalue()
    except Exception as e:
        logger.warning(f"Failed to download audio reference: {e}")
        return

    user_id = message.from_user.id
    draft = fresh_draft(user_id)

    if False:  # вкладка голоса отключена
        # Voice tab: the recording is the source for revoicing
        draft["audio_bytes"] = audio_bytes
        draft["voice_mode"] = "changer"
        get_user_prefs(user_id)["voice_mode"] = "changer"
    elif draft and draft.get("menu_mode", "video") == "video" and not is_eleven:
        # Attach audio reference to the user's active video draft!
        draft["audio_bytes"] = audio_bytes
        if caption_text:
            draft["prompt"] = caption_text
    elif is_eleven:
        # "озвуч"/eleven in caption → open the Voice tab in revoice mode
        draft = create_draft_for_user(
            user_id=user_id,
            prompt=caption_text,
            user_name=get_user_display_name(message.from_user),
            message_id=message.message_id,
            menu_mode="video",
            audio_bytes=audio_bytes,
        )
    else:
        prompt = caption_text or "Сгенерируй видео под прикрепленный звук"
        draft = create_draft_for_user(
            user_id=user_id,
            prompt=prompt,
            user_name=get_user_display_name(message.from_user),
            message_id=message.message_id,
            menu_mode="video",
            audio_bytes=audio_bytes,
        )

    sync_draft_references(draft)
    await show_or_update_menu(message, bot, draft, user_id)


@router.message(UserInputState.waiting_for_prompt, F.text)
async def handle_waiting_prompt(message: Message, bot: Bot, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    ref_images: List[bytes] = list(data.get("ref_images") or [])
    image_bytes = data.get("image_bytes")
    if image_bytes and not ref_images:
        ref_images = [image_bytes]
    if not ref_images:
        ref_images = await get_all_photos_for_message_or_reply(message, bot)

    target_mode = "video"
    model_override = None

    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        cmd_arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/cancel", "/stop"):
            await state.clear()
            await message.reply("❌ Ввод отменен.", parse_mode="HTML")
            return
        elif cmd in ("/image", "/poster", "/img", "/pic", "/photo", "/banana", "/qwen"):
            target_mode = "image"
            text = cmd_arg
        elif cmd in ("/video", "/gen", "/prompt", "/v", "/s2"):
            target_mode = "video"
            text = cmd_arg
        elif cmd in ("/voice", "/tts", "/eleven", "/elevenlabs"):
            target_mode = "video"
            text = cmd_arg
        else:
            await state.clear()
            return

    await state.clear()

    if not text:
        text = (
            "Стилизовать изображение по референсу в высоком качестве"
            if target_mode == "image"
            else "Анимировать фото, реалистичное кинематографичное видео"
        )

    draft = create_draft_for_user(
        user_id=message.from_user.id,
        prompt=text,
        image_bytes=ref_images[0] if ref_images else None,
        ref_images=ref_images,
        user_name=get_user_display_name(message.from_user),
        message_id=message.message_id,
        menu_mode=target_mode,
    )
    if model_override:
        draft["model_key"] = model_override

    await show_or_update_menu(message, bot, draft, message.from_user.id)


@router.message(UserInputState.waiting_for_duration, F.text)
async def handle_custom_duration_input(message: Message, bot: Bot, state: FSMContext):
    user_id = message.from_user.id
    draft = fresh_draft(user_id)
    text = (message.text or "").strip().lower()
    m = re.search(r'\b(\d{1,2})\b', text)
    if m:
        val = int(m.group(1))
        cur_model = draft.get("model_key", DEFAULT_MODEL) if draft else DEFAULT_MODEL
        model_durs = MODELS.get(cur_model, {}).get("durations", list(range(1, 31)))
        max_dur = max(model_durs) if model_durs else 30
        if 1 <= val <= max_dur:
            if draft:
                draft["duration"] = val
                draft["step"] = "quality"
                get_user_prefs(user_id)["duration"] = val
            await state.clear()
            await message.reply(f"✅ <b>Длительность установлена:</b> {val} сек!", parse_mode="HTML")
            if draft:
                draft["menu_message_id"] = None
                await show_or_update_menu(message, bot, draft, user_id)
            return
        else:
            await message.reply(f"⚠️ Для модели {MODELS.get(cur_model, {}).get('name', 'видео')} допустимо от 1 до {max_dur} сек.")
            return
    await message.reply("⚠️ Пожалуйста, отправьте число секунд (например: 1, 2, 3, 5, 10...).")


@router.message(Command("dur", "duration"), ~F.photo, ~F.document)
async def handle_duration_command(message: Message, command: CommandObject, bot: Bot):
    user_id = message.from_user.id
    draft = fresh_draft(user_id)
    arg = (command.args or "").strip()
    if not arg:
        await message.reply("⏱ Укажите секунды: например <code>/dur 3</code> или <code>/dur 7</code>", parse_mode="HTML")
        return
    m = re.search(r'\b(\d{1,2})\b', arg)
    if m:
        val = int(m.group(1))
        cur_model = draft.get("model_key", DEFAULT_MODEL) if draft else DEFAULT_MODEL
        model_durs = MODELS.get(cur_model, {}).get("durations", list(range(1, 31)))
        max_dur = max(model_durs) if model_durs else 30
        if 1 <= val <= max_dur:
            if draft:
                draft["duration"] = val
                draft["step"] = "quality"
                get_user_prefs(user_id)["duration"] = val
                await message.reply(f"✅ <b>Длительность установлена:</b> {val} сек!", parse_mode="HTML")
                draft["menu_message_id"] = None
                await show_or_update_menu(message, bot, draft, user_id)
            else:
                get_user_prefs(user_id)["duration"] = val
                await message.reply(f"✅ <b>Длительность сохранена:</b> {val} сек!", parse_mode="HTML")
            return
        else:
            await message.reply(f"⚠️ Для модели {MODELS.get(cur_model, {}).get('name', 'видео')} допустимо от 1 до {max_dur} сек.", parse_mode="HTML")
            return
    await message.reply("⚠️ Пожалуйста, укажите число (например: <code>/dur 4</code>).", parse_mode="HTML")


# --- Command Handlers (Text Only, Photos Handled Above) ---

@router.message(Command("video", "gen", "prompt", "v", "s2"), ~F.photo, ~F.document)
async def handle_video_command(message: Message, command: CommandObject, bot: Bot, state: FSMContext):
    """Open Video Generation Menu."""
    data = await state.get_data()
    state_refs: List[bytes] = list(data.get("ref_images") or [])
    await state.clear()

    user_id = message.from_user.id
    user_name = get_user_display_name(message.from_user)
    prompt_args = (command.args or "").strip()

    found_refs = await get_all_photos_for_message_or_reply(message, bot)
    ref_images = state_refs if state_refs else found_refs

    reply_video: Optional[bytes] = None
    if message.reply_to_message and _is_video_message(message.reply_to_message):
        try:
            reply_video = await extract_video_bytes(message.reply_to_message, bot)
        except ValueError:
            await message.reply("⚠️ Видео больше 20 МБ — бот не может его скачать.")
            return
        except Exception as e:
            logger.error(f"Failed to download replied video: {e}", exc_info=True)

    if not prompt_args and message.reply_to_message:
        prompt_args = (message.reply_to_message.caption or message.reply_to_message.text or "").strip()

    if not prompt_args and reply_video:
        prompt_args = "Измени видео, сохранив движение и композицию"
    if not prompt_args and ref_images:
        prompt_args = "Анимировать фото, плавное реалистичное кинематографичное движение"

    if not prompt_args and not ref_images:
        prompt_args = "Кинематографичная сцена, высокая детализация"

    draft = create_draft_for_user(
        user_id=user_id,
        prompt=prompt_args,
        image_bytes=ref_images[0] if ref_images else None,
        ref_images=ref_images,
        user_name=user_name,
        message_id=message.message_id,
        menu_mode="video",
    )
    if reply_video:
        draft["ref_video"] = reply_video
        if not MODELS.get(draft.get("model_key", DEFAULT_MODEL), {}).get("video_ref"):
            draft["model_key"] = DEFAULT_MODEL
            get_user_prefs(user_id)["model_key"] = DEFAULT_MODEL
        sync_draft_references(draft)
    await show_or_update_menu(message, bot, draft, user_id)


@router.message(Command("image", "poster", "img", "pic", "photo", "banana", "qwen"), ~F.photo, ~F.document)
async def handle_image_command(message: Message, command: CommandObject, bot: Bot, state: FSMContext):
    """Open Dedicated Image Generation Menu (Nano Banana, Flux 3 Image, Qwen Image)."""
    data = await state.get_data()
    state_refs: List[bytes] = list(data.get("ref_images") or [])
    await state.clear()

    user_id = message.from_user.id
    user_name = get_user_display_name(message.from_user)
    prompt_args = (command.args or "").strip()

    found_refs = await get_all_photos_for_message_or_reply(message, bot)
    ref_images = state_refs if state_refs else found_refs

    if not prompt_args and message.reply_to_message:
        prompt_args = (message.reply_to_message.caption or message.reply_to_message.text or "").strip()

    if not prompt_args and ref_images:
        prompt_args = "Стилизовать и улучшить изображение с сохранением деталей референса"

    if not prompt_args and not ref_images:
        prompt_args = "Фотореалистичный кадр в высоком разрешении, студийный свет"

    draft = create_draft_for_user(
        user_id=user_id,
        prompt=prompt_args,
        image_bytes=ref_images[0] if ref_images else None,
        ref_images=ref_images,
        user_name=user_name,
        message_id=message.message_id,
        menu_mode="image",
    )
    await show_or_update_menu(message, bot, draft, user_id)


@router.message(Command("voice", "tts", "eleven", "elevenlabs"), ~F.photo, ~F.document)
async def handle_voice_command(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    await message.reply("🎙 Озвучка временно отключена, скоро вернём. Пока доступны 🎬 Видео, 🖼 Фото и 🕺 Motion.")


@router.message(Command("motion", "mc", "dance", ignore_case=True, ignore_mention=True), ~F.photo, ~F.document)
async def handle_motion_command(message: Message, bot: Bot, state: FSMContext):
    """Open Motion Control: photo of the character first, then a video with the movement."""
    await state.clear()
    user_id = message.from_user.id
    draft = create_draft_for_user(
        user_id=user_id,
        prompt="",
        user_name=get_user_display_name(message.from_user),
        message_id=message.message_id,
        menu_mode="motion",
    )
    draft["model_key"] = MOTION_MODEL_KEY
    draft["resolution"] = "720p"
    await show_or_update_menu(message, bot, draft, user_id)


@router.message(Command("model"))
async def handle_model_command(message: Message):
    user_id = message.from_user.id
    prefs = get_user_prefs(user_id)
    cur_model = prefs["model_key"]

    buttons = []
    for mkey, minfo in MODELS.items():
        if minfo.get("hidden") or minfo.get("category") == "motion":
            continue
        cat_icon = "🖼" if minfo.get("category") == "image" else "🎬"
        is_active = mkey == cur_model
        lbl = f"✅ {cat_icon} {minfo['name']}" if is_active else f"{cat_icon} {minfo['name']}"
        btn_kwargs = {"style": "primary"} if is_active else {}
        buttons.append([InlineKeyboardButton(text=lbl, callback_data=f"pref_mod:{mkey}:{user_id}", **btn_kwargs)])

    await message.reply(
        f"🤖 <b>Выбор модели по умолчанию для {get_user_display_name(message.from_user)}</b>\n\n"
        f"Текущая модель: <b>{MODELS[cur_model]['name']}</b>\n"
        f"<i>{MODELS[cur_model]['desc']}</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("pref_mod:"))
async def on_set_pref_model(call: CallbackQuery):
    parts = call.data.split(":")
    mkey = parts[1]
    owner_id = int(parts[2]) if len(parts) > 2 else call.from_user.id

    if call.from_user.id != owner_id:
        await call.answer("⚠️ Это меню другого участника. Напишите команду /model для себя!", show_alert=True)
        return

    if mkey not in MODELS:
        await call.answer("Неизвестная модель", show_alert=True)
        return

    prefs = get_user_prefs(call.from_user.id)
    if MODELS[mkey].get("category") == "image":
        prefs["image_model_key"] = mkey
    else:
        prefs["model_key"] = mkey

    buttons = []
    for k, minfo in MODELS.items():
        cat_icon = "🖼" if minfo.get("category") == "image" else "🎬"
        is_active = k == mkey
        lbl = f"✅ {cat_icon} {minfo['name']}" if is_active else f"{cat_icon} {minfo['name']}"
        btn_kwargs = {"style": "primary"} if is_active else {}
        buttons.append([InlineKeyboardButton(text=lbl, callback_data=f"pref_mod:{k}:{owner_id}", **btn_kwargs)])

    try:
        await call.message.edit_text(
            f"🤖 <b>Выбор модели по умолчанию для {get_user_display_name(call.from_user)}</b>\n\n"
            f"Текущая модель: <b>{MODELS[mkey]['name']}</b>\n"
            f"<i>{MODELS[mkey]['desc']}</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer(f"Выбрана {MODELS[mkey]['name']}")


# --- Interactive Image Grid (Сетка на изображение) ---

grid_sessions: Dict[str, Dict[str, Any]] = {}

GRID_DIM_OPTIONS = [(2, 2), (3, 3), (4, 4), (5, 5), (8, 8)]
GRID_COLORS = ["contrast", "white", "black", "red", "green", "yellow", "cyan"]
GRID_COLOR_NAMES = {
    "contrast": "Контраст",
    "white": "Белый",
    "black": "Черный",
    "red": "Красный",
    "green": "Зеленый",
    "yellow": "Желтый",
    "cyan": "Голубой",
}
GRID_THICKNESS_MODES = ["thick", "heavy", "medium"]
GRID_THICKNESS_NAMES = {
    "thick": "Толстая",
    "heavy": "Очень толстая",
    "medium": "Средняя",
}


def parse_grid_args(arg_str: str) -> Dict[str, Any]:
    res = {
        "rows": 3,
        "cols": 3,
        "color": "contrast",
        "thickness_mode": "thick",
        "show_labels": False,
    }
    if not arg_str:
        return res

    tokens = arg_str.lower().split()
    for tok in tokens:
        m = re.match(r"^(\d{1,2})[xх×](\d{1,2})$", tok)
        if m:
            res["rows"] = max(2, min(50, int(m.group(1))))
            res["cols"] = max(2, min(50, int(m.group(2))))
            continue
        if tok.isdigit() and int(tok) in (2, 3, 4, 5, 6, 7, 8, 9, 10):
            res["rows"] = int(tok)
            res["cols"] = int(tok)
            continue
        for c_key in GRID_COLORS:
            if tok in (c_key, GRID_COLOR_NAMES[c_key].lower()):
                res["color"] = c_key
                break
        for t_key in GRID_THICKNESS_MODES:
            if tok in (t_key, GRID_THICKNESS_NAMES[t_key].lower()):
                res["thickness_mode"] = t_key
                break
        if tok in ("номера", "номер", "labels", "label", "цифры", "буквы", "numbers"):
            res["show_labels"] = True

    return res


def build_grid_keyboard(grid_id: str, data: Dict[str, Any]) -> InlineKeyboardMarkup:
    cur_r = data.get("rows", 3)
    cur_c = data.get("cols", 3)
    cur_col = data.get("color", "contrast")
    cur_th = data.get("thickness_mode", "thick")
    show_lbl = data.get("show_labels", False)

    dim_btns = []
    for (r, c) in GRID_DIM_OPTIONS:
        text = f"{r}×{c}"
        if r == cur_r and c == cur_c:
            text = f"✅ {text}"
        dim_btns.append(InlineKeyboardButton(text=text, callback_data=f"g_dim:{grid_id}:{r}:{c}"))

    col_label = f"🎨 Цвет: {GRID_COLOR_NAMES.get(cur_col, cur_col)}"
    th_label = f"📏 Толщина: {GRID_THICKNESS_NAMES.get(cur_th, cur_th)}"
    style_btns = [
        InlineKeyboardButton(text=col_label, callback_data=f"g_col:{grid_id}"),
        InlineKeyboardButton(text=th_label, callback_data=f"g_th:{grid_id}"),
    ]

    lbl_text = "🔢 Номера: Вкл ✅" if show_lbl else "🔢 Номера: Выкл"
    lbl_btns = [
        InlineKeyboardButton(text=lbl_text, callback_data=f"g_lbl:{grid_id}")
    ]

    action_btns = [
        InlineKeyboardButton(text="🎬 В меню Видео", callback_data=f"g_use_vid:{grid_id}"),
        InlineKeyboardButton(text="🖼 В меню Фото", callback_data=f"g_use_img:{grid_id}"),
    ]

    return InlineKeyboardMarkup(inline_keyboard=[dim_btns, style_btns, lbl_btns, action_btns])


def format_grid_caption(session: Dict[str, Any]) -> str:
    r = session.get("rows", 3)
    c = session.get("cols", 3)
    col = GRID_COLOR_NAMES.get(session.get("color", "contrast"), "Контраст")
    th = GRID_THICKNESS_NAMES.get(session.get("thickness_mode", "thick"), "Толстая")
    lbl = "Да (A1, A2...)" if session.get("show_labels") else "Нет"
    return (
        f"🔲 <b>Сетка наложена ({r}×{c})</b>\n\n"
        f"🎨 <b>Цвет линий:</b> {col}\n"
        f"📏 <b>Толщина линий:</b> {th}\n"
        f"🔢 <b>Номера ячеек:</b> {lbl}\n\n"
        f"<i>Нажимайте кнопки ниже для переключения сетки или отправки в меню генерации:</i>"
    )


async def process_grid_image(message: Message, bot: Bot, image_bytes: bytes, args: str = ""):
    opts = parse_grid_args(args)
    gridded = image_utils.overlay_grid(
        image_bytes,
        rows=opts["rows"],
        cols=opts["cols"],
        thickness_mode=opts["thickness_mode"],
        color=opts["color"],
        show_labels=opts["show_labels"],
    )
    grid_id = f"{message.chat.id}_{message.message_id}_{int(time.time())}"
    session = {
        "grid_id": grid_id,
        "owner_id": message.from_user.id,
        "chat_id": message.chat.id,
        "orig_bytes": image_bytes,
        "current_bytes": gridded,
        "rows": opts["rows"],
        "cols": opts["cols"],
        "color": opts["color"],
        "thickness_mode": opts["thickness_mode"],
        "show_labels": opts["show_labels"],
        "user_name": get_user_display_name(message.from_user),
    }
    grid_sessions[grid_id] = session
    if len(grid_sessions) > 100:
        oldest_k = next(iter(grid_sessions))
        del grid_sessions[oldest_k]

    kb = build_grid_keyboard(grid_id, session)
    caption = format_grid_caption(session)
    await message.reply_photo(
        photo=BufferedInputFile(gridded, filename="grid.jpg"),
        caption=caption,
        reply_markup=kb,
        parse_mode="HTML"
    )


@router.message(Command("grid", "сетка", "mesh"))
async def handle_grid_command(message: Message, command: CommandObject, bot: Bot):
    args = (command.args or "").strip()

    img_bytes = await extract_image_bytes(message, bot)
    if not img_bytes and message.reply_to_message:
        rep = message.reply_to_message
        if rep.message_id in recent_chat_media:
            _, img_bytes = recent_chat_media[rep.message_id]
        else:
            img_bytes = await extract_image_bytes(rep, bot)

    if not img_bytes:
        recent = get_recent_photos_for_user(message.chat.id, message.from_user.id, max_age_sec=120.0)
        if recent:
            img_bytes = recent[-1]

    if not img_bytes:
        await message.reply(
            "🔲 <b>Накладывание толстой сетки на изображение</b>\n\n"
            "• Отправьте фото с подписью <code>/grid</code> или <code>/сетка</code>\n"
            "• Или <b>ответьте (Reply)</b> на любое фото в чате командой <code>/grid</code>\n\n"
            "<b>Дополнительные параметры (необязательно):</b>\n"
            "• <code>/grid 2x2</code>, <code>/grid 4x4</code>, <code>/grid 5x5</code> — размер сетки\n"
            "• <code>/grid red</code>, <code>/grid white</code>, <code>/grid yellow</code> — цвет линий\n"
            "• <code>/grid heavy</code>, <code>/grid medium</code> — толщина линий\n"
            "• <code>/grid номера</code> — добавить метки ячеек (A1, A2...)\n\n"
            "<i>Под фото появятся интерактивные кнопки для мгновенной смены размера и стилей!</i>",
            parse_mode="HTML"
        )
        return

    await process_grid_image(message, bot, img_bytes, args)


@router.callback_query(F.data.startswith("g_dim:"))
async def on_grid_dimension(call: CallbackQuery):
    parts = call.data.split(":")
    grid_id = parts[1]
    rows = int(parts[2])
    cols = int(parts[3])
    session = grid_sessions.get(grid_id)
    if not session:
        await call.answer("Сессия сетки устарела. Отправьте /grid заново.", show_alert=True)
        return

    session["rows"] = rows
    session["cols"] = cols
    gridded = image_utils.overlay_grid(
        session["orig_bytes"],
        rows=rows,
        cols=cols,
        thickness_mode=session["thickness_mode"],
        color=session["color"],
        show_labels=session["show_labels"],
    )
    session["current_bytes"] = gridded
    kb = build_grid_keyboard(grid_id, session)
    caption = format_grid_caption(session)
    try:
        await call.message.edit_media(
            media=InputMediaPhoto(media=BufferedInputFile(gridded, filename="grid.jpg"), caption=caption, parse_mode="HTML"),
            reply_markup=kb,
        )
    except Exception as e:
        logger.debug(f"Failed to edit grid media: {e}")
    await call.answer(f"Сетка: {rows}×{cols}")


@router.callback_query(F.data.startswith("g_col:"))
async def on_grid_color(call: CallbackQuery):
    parts = call.data.split(":")
    grid_id = parts[1]
    session = grid_sessions.get(grid_id)
    if not session:
        await call.answer("Сессия сетки устарела", show_alert=True)
        return

    cur_idx = GRID_COLORS.index(session["color"]) if session["color"] in GRID_COLORS else 0
    next_col = GRID_COLORS[(cur_idx + 1) % len(GRID_COLORS)]
    session["color"] = next_col
    gridded = image_utils.overlay_grid(
        session["orig_bytes"],
        rows=session["rows"],
        cols=session["cols"],
        thickness_mode=session["thickness_mode"],
        color=next_col,
        show_labels=session["show_labels"],
    )
    session["current_bytes"] = gridded
    kb = build_grid_keyboard(grid_id, session)
    caption = format_grid_caption(session)
    try:
        await call.message.edit_media(
            media=InputMediaPhoto(media=BufferedInputFile(gridded, filename="grid.jpg"), caption=caption, parse_mode="HTML"),
            reply_markup=kb,
        )
    except Exception as e:
        logger.debug(f"Failed to edit grid media: {e}")
    await call.answer(f"Цвет: {GRID_COLOR_NAMES.get(next_col, next_col)}")


@router.callback_query(F.data.startswith("g_th:"))
async def on_grid_thickness(call: CallbackQuery):
    parts = call.data.split(":")
    grid_id = parts[1]
    session = grid_sessions.get(grid_id)
    if not session:
        await call.answer("Сессия сетки устарела", show_alert=True)
        return

    cur_idx = GRID_THICKNESS_MODES.index(session["thickness_mode"]) if session["thickness_mode"] in GRID_THICKNESS_MODES else 0
    next_th = GRID_THICKNESS_MODES[(cur_idx + 1) % len(GRID_THICKNESS_MODES)]
    session["thickness_mode"] = next_th
    gridded = image_utils.overlay_grid(
        session["orig_bytes"],
        rows=session["rows"],
        cols=session["cols"],
        thickness_mode=next_th,
        color=session["color"],
        show_labels=session["show_labels"],
    )
    session["current_bytes"] = gridded
    kb = build_grid_keyboard(grid_id, session)
    caption = format_grid_caption(session)
    try:
        await call.message.edit_media(
            media=InputMediaPhoto(media=BufferedInputFile(gridded, filename="grid.jpg"), caption=caption, parse_mode="HTML"),
            reply_markup=kb,
        )
    except Exception as e:
        logger.debug(f"Failed to edit grid media: {e}")
    await call.answer(f"Толщина: {GRID_THICKNESS_NAMES.get(next_th, next_th)}")


@router.callback_query(F.data.startswith("g_lbl:"))
async def on_grid_labels(call: CallbackQuery):
    parts = call.data.split(":")
    grid_id = parts[1]
    session = grid_sessions.get(grid_id)
    if not session:
        await call.answer("Сессия сетки устарела", show_alert=True)
        return

    session["show_labels"] = not session.get("show_labels", False)
    gridded = image_utils.overlay_grid(
        session["orig_bytes"],
        rows=session["rows"],
        cols=session["cols"],
        thickness_mode=session["thickness_mode"],
        color=session["color"],
        show_labels=session["show_labels"],
    )
    session["current_bytes"] = gridded
    kb = build_grid_keyboard(grid_id, session)
    caption = format_grid_caption(session)
    try:
        await call.message.edit_media(
            media=InputMediaPhoto(media=BufferedInputFile(gridded, filename="grid.jpg"), caption=caption, parse_mode="HTML"),
            reply_markup=kb,
        )
    except Exception as e:
        logger.debug(f"Failed to edit grid media: {e}")
    await call.answer("Номера ячеек: Вкл" if session["show_labels"] else "Номера ячеек: Выкл")


@router.callback_query(F.data.startswith("g_use_vid:"))
async def on_grid_use_video(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    grid_id = parts[1]
    session = grid_sessions.get(grid_id)
    if not session:
        await call.answer("Сессия сетки устарела", show_alert=True)
        return

    user_id = call.from_user.id
    gridded_bytes = session["current_bytes"]
    draft = create_draft_for_user(
        user_id=user_id,
        prompt="Анимировать фото с сохранением композиции по сетке",
        image_bytes=gridded_bytes,
        ref_images=[gridded_bytes],
        user_name=get_user_display_name(call.from_user),
        message_id=call.message.message_id,
        menu_mode="video",
    )
    draft["has_grid"] = True
    draft["orig_ref_images"] = [session["orig_bytes"]]
    await show_or_update_menu(call.message, bot, draft, user_id)
    await call.answer("Открыто меню Видео с сеткой на референсе")


@router.callback_query(F.data.startswith("g_use_img:"))
async def on_grid_use_image(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    grid_id = parts[1]
    session = grid_sessions.get(grid_id)
    if not session:
        await call.answer("Сессия сетки устарела", show_alert=True)
        return

    user_id = call.from_user.id
    gridded_bytes = session["current_bytes"]
    draft = create_draft_for_user(
        user_id=user_id,
        prompt="Стилизовать изображение с сохранением пропорций и сетки",
        image_bytes=gridded_bytes,
        ref_images=[gridded_bytes],
        user_name=get_user_display_name(call.from_user),
        message_id=call.message.message_id,
        menu_mode="image",
    )
    draft["has_grid"] = True
    draft["orig_ref_images"] = [session["orig_bytes"]]
    await show_or_update_menu(call.message, bot, draft, user_id)
    await call.answer("Открыто меню Фото с сеткой на референсе")


# --- Text Handling (Mentions in groups, plain text in private) ---

@router.message(F.text)
async def handle_text(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    text = message.text.strip()
    if text.startswith("/"):
        return

    user_id = message.from_user.id
    is_group = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

    if is_group:
        bot_info = await bot.me()
        bot_username = f"@{bot_info.username}".lower()
        text_lower = text.lower()
        is_mentioned = bot_username in text_lower or (
            message.reply_to_message and message.reply_to_message.from_user.id == bot_info.id
        )
        if not is_mentioned:
            return

        clean_prompt = text.replace(f"@{bot_info.username}", "").replace(bot_username, "").strip()
        image_bytes = await extract_image_bytes(message, bot)

        if not clean_prompt and image_bytes:
            clean_prompt = "Анимировать сцену, плавное движение"

        if not clean_prompt:
            await message.reply(
                "ℹ️ <i>Напишите промпт после упоминания бота. Например:</i>\n"
                "<code>@POCOFONAIbot полет дракона над горами</code>",
                parse_mode="HTML"
            )
            return

        # If user already has an active draft open in this chat, update its prompt without wiping references!
        if fresh_draft(user_id) is not None:
            draft = user_drafts[user_id]
            draft["prompt"] = clean_prompt
            await show_or_update_menu(message, bot, draft, user_id)
            return

        found_refs = await get_all_photos_for_message_or_reply(message, bot)
        draft = create_draft_for_user(
            user_id=message.from_user.id,
            prompt=clean_prompt,
            image_bytes=found_refs[0] if found_refs else None,
            ref_images=found_refs,
            user_name=get_user_display_name(message.from_user),
            message_id=message.message_id
        )
        await show_or_update_menu(message, bot, draft, message.from_user.id)
        return

    # Private chat:
    draft_m = fresh_draft(user_id)
    if draft_m and draft_m.get("menu_mode") == "motion":
        await message.reply("🕺 В Motion текст не нужен: пришлите фото персонажа, потом видео с движением.")
        return
    # If user already has an active draft open, update its prompt without wiping references!
    if fresh_draft(user_id) is not None:
        draft = user_drafts[user_id]
        draft["prompt"] = text
        await show_or_update_menu(message, bot, draft, user_id)
        return

    # If replying to a photo/album in private chat:
    found_refs = await get_all_photos_for_message_or_reply(message, bot)
    draft = create_draft_for_user(
        user_id=message.from_user.id,
        prompt=text,
        image_bytes=found_refs[0] if found_refs else None,
        ref_images=found_refs,
        user_name=get_user_display_name(message.from_user),
        message_id=message.message_id
    )
    await show_or_update_menu(message, bot, draft, message.from_user.id)


# --- Callback Query Handlers (with owner check for group safety) ---

async def verify_callback_owner(call: CallbackQuery, owner_id: int) -> bool:
    if call.from_user.id != owner_id:
        await call.answer(
            "⚠️ Это меню принадлежит другому участнику.\nИспользуйте /video или /image для создания своей генерации!",
            show_alert=True
        )
        return False
    return True


@router.callback_query(F.data.startswith("open_menu:"))
async def on_open_menu_from_button(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    target_mode = parts[1]
    if target_mode == "voice":  # старые кнопки из прошлых сообщений
        target_mode = "video"
    owner_id = int(parts[2]) if len(parts) > 2 else call.from_user.id
    if not await verify_callback_owner(call, owner_id):
        return

    data = await state.get_data()
    ref_images: List[bytes] = list(data.get("ref_images") or [])
    await state.clear()

    uid = call.from_user.id
    default_prompt = (
        "Фотореалистичное изображение в высоком разрешении"
        if target_mode == "image"
        else "" if target_mode == "motion"
        else "Кинематографичное видео с плавной динамикой"
    )
    draft = user_drafts.get(uid)
    if draft:
        draft["menu_mode"] = target_mode
        draft["step"] = "model" if target_mode == "video" else "main"
        if target_mode == "motion":
            draft["model_key"] = MOTION_MODEL_KEY
            draft["resolution"] = draft.get("resolution", "720p")
        if ref_images:
            draft["ref_images"] = list(ref_images)
            draft["image_bytes"] = ref_images[0]
        if target_mode == "image" and draft.get("model_key") not in IMAGE_MODEL_KEYS:
            draft["model_key"] = get_user_prefs(uid).get("image_model_key", DEFAULT_IMAGE_MODEL)
        elif target_mode == "video" and draft.get("model_key") not in VIDEO_MODEL_KEYS:
            draft["model_key"] = get_user_prefs(uid).get("model_key", DEFAULT_MODEL)
    else:
        draft = create_draft_for_user(
            user_id=uid,
            prompt=default_prompt,
            ref_images=ref_images,
            user_name=get_user_display_name(call.from_user),
            message_id=call.message.message_id,
            menu_mode=target_mode,
        )

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, uid),
            parse_mode="HTML",
        )
    except Exception:
        sent = await call.message.answer(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, uid),
            parse_mode="HTML",
        )
        draft["menu_message_id"] = sent.message_id
        draft["menu_chat_id"] = sent.chat.id
    await call.answer()


@router.callback_query(F.data.startswith("tab:"))
async def on_switch_menu_tab(call: CallbackQuery):
    parts = call.data.split(":")
    target_mode = parts[1]
    owner_id = int(parts[2])

    if not await verify_callback_owner(call, owner_id):
        return

    draft = user_drafts.get(owner_id)
    if not draft:
        await call.answer("Начните с отправки запроса /video или /image", show_alert=True)
        return

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    draft["menu_mode"] = target_mode
    draft["step"] = "model" if target_mode == "video" else "main"
    prefs = get_user_prefs(owner_id)
    if target_mode == "image":
        draft["model_key"] = prefs.get("image_model_key", DEFAULT_IMAGE_MODEL)
    elif target_mode == "motion":
        draft["model_key"] = draft.get("model_key") if draft.get("model_key") in MOTION_MODEL_KEYS else MOTION_MODEL_KEY
        draft.setdefault("resolution", "720p")
    else:
        mk = prefs.get("model_key", DEFAULT_MODEL)
        draft["model_key"] = mk if mk in VIDEO_MODEL_KEYS else DEFAULT_MODEL

    sync_draft_references(draft)

    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer({"image": "🖼 Фото", "motion": "🕺 Motion"}.get(target_mode, "🎬 Видео"))


@router.callback_query(F.data.startswith("mres:"))
async def on_motion_resolution(call: CallbackQuery):
    _, res, owner = call.data.split(":")
    owner_id = int(owner)
    if not await verify_callback_owner(call, owner_id):
        return
    draft = fresh_draft(owner_id)
    if not draft or draft.get("menu_mode") != "motion":
        await call.answer("Откройте Motion заново: /motion", show_alert=True)
        return
    draft["resolution"] = res if res in ("720p", "1080p") else "720p"
    get_user_prefs(owner_id)["resolution"] = draft["resolution"]
    try:
        await call.message.edit_text(text=format_draft_text(draft), reply_markup=build_settings_keyboard(draft, owner_id), parse_mode="HTML")
    except Exception:
        pass
    await call.answer(f"🕺 {draft['resolution']}")


@router.callback_query(F.data.startswith("mmodel:"))
async def on_motion_model(call: CallbackQuery):
    _, key, owner = call.data.split(":")
    owner_id = int(owner)
    if not await verify_callback_owner(call, owner_id):
        return
    draft = fresh_draft(owner_id)
    if not draft or draft.get("menu_mode") != "motion":
        await call.answer("Откройте Motion заново: /motion", show_alert=True)
        return
    draft["model_key"] = key if key in MOTION_MODEL_KEYS else MOTION_MODEL_KEY
    try:
        await call.message.edit_text(text=format_draft_text(draft), reply_markup=build_settings_keyboard(draft, owner_id), parse_mode="HTML")
    except Exception:
        pass
    await call.answer(MODELS[draft["model_key"]]["short"])


@router.callback_query(F.data.startswith("ref_hint:"))
async def on_ref_hint(call: CallbackQuery):
    owner_id = int(call.data.split(":")[1])
    if not await verify_callback_owner(call, owner_id):
        return
    await call.answer(
        "📎 Просто отправьте одно или несколько фото прямо в этот чат — они автоматически прикрепятся как референс к вашему запросу!",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("rmode:"))
async def on_toggle_ref_mode(call: CallbackQuery):
    owner_id = int(call.data.split(":")[1])
    if not await verify_callback_owner(call, owner_id):
        return
    draft = user_drafts.get(owner_id)
    if not draft:
        await call.answer("Начните с отправки запроса", show_alert=True)
        return

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    cur_mode = draft.get("ref_mode", "ref")
    new_mode = "start" if cur_mode == "ref" else "ref"
    draft["ref_mode"] = new_mode
    get_user_prefs(owner_id)["ref_mode"] = new_mode

    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer(
        "Режим фото: Референс персонажа/объекта"
        if new_mode == "ref"
        else "Режим фото: Первый кадр видео (Start Frame)"
    )


@router.callback_query(F.data.startswith("rclear:"))
async def on_clear_refs(call: CallbackQuery):
    owner_id = int(call.data.split(":")[1])
    if not await verify_callback_owner(call, owner_id):
        return
    draft = user_drafts.get(owner_id)
    if not draft:
        await call.answer("Начните с отправки запроса", show_alert=True)
        return

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    draft["all_uploaded_refs"] = []
    draft["ref_video"] = None
    draft["ref_images"] = []
    draft["orig_ref_images"] = None
    draft["has_grid"] = False
    draft["image_bytes"] = None
    draft["audio_bytes"] = None

    # Clear recent user photos so ghost references don't reappear
    u_key = (call.message.chat.id, owner_id)
    recent_user_photos.pop(u_key, None)

    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer("🗑 Референсы очищены")


@router.callback_query(F.data.startswith("rclearaudio:"))
async def on_clear_audio_ref(call: CallbackQuery):
    owner_id = int(call.data.split(":")[1])
    if not await verify_callback_owner(call, owner_id):
        return
    draft = user_drafts.get(owner_id)
    if not draft:
        await call.answer("Начните с отправки запроса", show_alert=True)
        return
    draft["audio_bytes"] = None
    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer("🗑 Аудио-референс удален")


@router.callback_query(F.data.startswith("audio_hint:"))
async def on_audio_hint(call: CallbackQuery):
    await call.answer(
        "🎵 Отправьте голосовое сообщение или аудиофайл (mp3/wav) в чат — оно прикрепится как звук к вашему видео!",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("rclearvideo:"))
async def on_clear_video_ref(call: CallbackQuery):
    owner_id = int(call.data.split(":")[1])
    if not await verify_callback_owner(call, owner_id):
        return
    draft = user_drafts.get(owner_id)
    if not draft:
        await call.answer("Начните с отправки запроса", show_alert=True)
        return
    draft["ref_video"] = None
    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await call.answer("🗑 Видео-референс удален")


@router.callback_query(F.data.startswith("video_hint:"))
async def on_video_hint(call: CallbackQuery):
    await call.answer(
        "🎞 Отправьте видеоролик (до 20 МБ) в чат — он прикрепится как референс к вашему видео!",
        show_alert=True,
    )


@router.callback_query(F.data.startswith("rgrid:"))
async def on_toggle_reference_grid(call: CallbackQuery):
    parts = call.data.split(":")
    owner_id = int(parts[1])
    if not await verify_callback_owner(call, owner_id):
        return

    draft = user_drafts.get(owner_id)
    if not draft or not (draft.get("all_uploaded_refs") or draft.get("ref_images")):
        await call.answer("Сначала прикрепите фото-референс", show_alert=True)
        return

    has_grid = not draft.get("has_grid", False)
    draft["has_grid"] = has_grid
    sync_draft_references(draft)
    msg = "🔲 Наложена толстая сетка 3×3 на референсы" if has_grid else "Сетка снята с референсов"

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer(msg)


@router.callback_query(F.data.startswith("grid_gen:"))
async def on_grid_for_generated_image(call: CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    owner_id = int(parts[1])
    img_bytes = await extract_image_bytes(call.message, bot)
    if not img_bytes:
        await call.answer("Не удалось загрузить изображение", show_alert=True)
        return
    await call.answer("Наложение сетки...")
    await process_grid_image(call.message, bot, img_bytes, "")


@router.callback_query(F.data.startswith("wstep:"))
async def on_wizard_step(call: CallbackQuery):
    parts = call.data.split(":")
    target_step = parts[1]
    owner_id = int(parts[2])

    if not await verify_callback_owner(call, owner_id):
        return

    draft = user_drafts.get(owner_id)
    if not draft:
        await call.answer("Начните с отправки запроса /video", show_alert=True)
        return

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    draft["step"] = target_step

    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("sm:"))
async def on_set_model(call: CallbackQuery):
    parts = call.data.split(":")
    mkey = parts[1]
    owner_id = int(parts[2])

    if not await verify_callback_owner(call, owner_id):
        return

    draft = user_drafts.get(owner_id)
    if not draft or mkey not in MODELS:
        await call.answer("Начните с отправки запроса /video или /image", show_alert=True)
        return

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    draft["model_key"] = mkey
    minfo = MODELS[mkey]
    if minfo.get("category") == "image":
        draft["menu_mode"] = "image"
        draft["step"] = "main"
        get_user_prefs(owner_id)["image_model_key"] = mkey
    else:
        draft["menu_mode"] = "video"
        get_user_prefs(owner_id)["model_key"] = mkey
        model_durs = minfo.get("durations", [5])
        max_dur = max(model_durs) if model_durs else 15
        if int(draft.get("duration", DEFAULT_DURATION)) > max_dur:
            draft["duration"] = max_dur
            get_user_prefs(owner_id)["duration"] = max_dur

        if minfo.get("backend") == "davinci_voice":
            draft["step"] = "quality"
        else:
            draft["step"] = "duration"

    sync_draft_references(draft)

    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer(f"Модель: {MODELS[mkey]['name']}")


@router.callback_query(F.data.startswith("sd:"))
async def on_set_duration(call: CallbackQuery):
    parts = call.data.split(":")
    dur = int(parts[1])
    owner_id = int(parts[2])

    if not await verify_callback_owner(call, owner_id):
        return

    draft = user_drafts.get(owner_id)
    if not draft:
        await call.answer("Начните с отправки запроса /video", show_alert=True)
        return

    cur_model = draft.get("model_key", DEFAULT_MODEL)
    model_durs = MODELS.get(cur_model, {}).get("durations", list(range(1, 31)))
    max_dur = max(model_durs) if model_durs else 15
    dur = max(1, min(max_dur, dur))

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    draft["duration"] = dur
    draft["step"] = "quality"
    get_user_prefs(owner_id)["duration"] = dur

    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer(f"⏱ {dur} сек")


@router.callback_query(F.data.startswith("sd_dec:"))
async def on_dec_duration(call: CallbackQuery):
    parts = call.data.split(":")
    owner_id = int(parts[1])
    if not await verify_callback_owner(call, owner_id):
        return
    draft = user_drafts.get(owner_id)
    if not draft:
        return
    dur = max(1, int(draft.get("duration", DEFAULT_DURATION)) - 1)
    draft["duration"] = dur
    get_user_prefs(owner_id)["duration"] = dur
    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer(f"⏱ {dur} сек")


@router.callback_query(F.data.startswith("sd_inc:"))
async def on_inc_duration(call: CallbackQuery):
    parts = call.data.split(":")
    owner_id = int(parts[1])
    if not await verify_callback_owner(call, owner_id):
        return
    draft = user_drafts.get(owner_id)
    if not draft:
        return
    dur = min(30, int(draft.get("duration", DEFAULT_DURATION)) + 1)
    draft["duration"] = dur
    get_user_prefs(owner_id)["duration"] = dur
    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer(f"⏱ {dur} сек")


@router.callback_query(F.data.startswith("sd_custom:"))
async def on_custom_duration_prompt(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    owner_id = int(parts[1])
    if not await verify_callback_owner(call, owner_id):
        return
    await state.set_state(UserInputState.waiting_for_duration)
    await call.message.reply(
        "⏱ <b>Введите точную длительность видео в секундах:</b>\n"
        "<i>Например: 1, 2, 3, 4, 7, 10, 15... (любое число от 1 до 30)</i>",
        parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("sr:"))
async def on_set_resolution(call: CallbackQuery):
    parts = call.data.split(":")
    res = parts[1]
    owner_id = int(parts[2])

    if not await verify_callback_owner(call, owner_id):
        return

    draft = user_drafts.get(owner_id)
    if not draft:
        await call.answer("Начните с отправки запроса /video", show_alert=True)
        return

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    draft["resolution"] = res
    get_user_prefs(owner_id)["resolution"] = res

    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("sir:"))
async def on_set_image_resolution(call: CallbackQuery):
    parts = call.data.split(":")
    res = parts[1]
    owner_id = int(parts[2])

    if not await verify_callback_owner(call, owner_id):
        return

    draft = user_drafts.get(owner_id)
    if not draft:
        await call.answer("Начните с отправки запроса /image", show_alert=True)
        return

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    draft["image_resolution"] = res
    get_user_prefs(owner_id)["image_resolution"] = res

    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer(f"Качество фото: {res}")


@router.callback_query(F.data.startswith("sa:"))
async def on_set_ratio(call: CallbackQuery):
    parts = call.data.split(":")
    ratio = f"{parts[1]}:{parts[2]}" if len(parts) == 4 else parts[1]
    owner_id = int(parts[-1])

    if not await verify_callback_owner(call, owner_id):
        return

    draft = user_drafts.get(owner_id)
    if not draft:
        await call.answer("Начните с отправки запроса /video", show_alert=True)
        return

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    draft["ratio"] = ratio
    get_user_prefs(owner_id)["ratio"] = ratio

    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("sia:"))
async def on_set_image_ratio(call: CallbackQuery):
    parts = call.data.split(":")
    ratio = f"{parts[1]}:{parts[2]}" if len(parts) == 4 else parts[1]
    owner_id = int(parts[-1])

    if not await verify_callback_owner(call, owner_id):
        return

    draft = user_drafts.get(owner_id)
    if not draft:
        await call.answer("Начните с отправки запроса /image", show_alert=True)
        return

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    draft["image_ratio"] = ratio
    get_user_prefs(owner_id)["image_ratio"] = ratio

    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer(f"Пропорции фото: {ratio}")


@router.callback_query(F.data.startswith("tg:"))
async def on_toggle_audio(call: CallbackQuery):
    parts = call.data.split(":")
    val = parts[1] == "1"
    owner_id = int(parts[2])

    if not await verify_callback_owner(call, owner_id):
        return

    draft = user_drafts.get(owner_id)
    if not draft:
        await call.answer("Начните с отправки запроса /video", show_alert=True)
        return

    draft["menu_message_id"] = call.message.message_id
    draft["menu_chat_id"] = call.message.chat.id
    draft["audio"] = val
    get_user_prefs(owner_id)["audio"] = val

    try:
        await call.message.edit_text(
            text=format_draft_text(draft),
            reply_markup=build_settings_keyboard(draft, owner_id),
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("can:"))
async def on_cancel_draft(call: CallbackQuery):
    owner_id = int(call.data.split(":")[1])
    if not await verify_callback_owner(call, owner_id):
        return

    user_drafts.pop(owner_id, None)
    try:
        await call.message.edit_text(
            "❌ <b>Генерация отменена.</b> Для нового запроса используйте /video или /image.",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("gen:"))
async def on_start_generate(call: CallbackQuery, queue: GenerationQueue):
    owner_id = int(call.data.split(":")[1])
    if not await verify_callback_owner(call, owner_id):
        return

    peek = user_drafts.get(owner_id)
    if peek and peek.get("menu_mode") == "motion":
        if not peek.get("motion_image"):
            await call.answer("📸 Сначала пришлите фото персонажа", show_alert=True)
            return
        if not peek.get("ref_video"):
            await call.answer("🎞 Теперь пришлите видео с движением", show_alert=True)
            return
        sec = int(peek.get("motion_sec") or 0)
        if sec and not (3 <= sec <= 30):
            await call.answer(f"Видео {sec} сек — нужно от 3 до 30 сек", show_alert=True)
            return

    draft = user_drafts.pop(owner_id, None)
    if not draft:
        await call.answer("Параметры устарели. Отправьте новый запрос /video или /image.", show_alert=True)
        return

    # Clear recent user photos so next request starts completely fresh
    u_key = (call.message.chat.id, owner_id)
    recent_user_photos.pop(u_key, None)

    sync_draft_references(draft)
    menu_mode = draft.get("menu_mode", "video")
    model_key = draft.get("model_key", DEFAULT_IMAGE_MODEL if menu_mode == "image" else DEFAULT_MODEL)
    if menu_mode == "motion":
        model_key = model_key if model_key in MOTION_MODEL_KEYS else MOTION_MODEL_KEY
    model_info = MODELS.get(model_key, MODELS[DEFAULT_MODEL])
    prompt = draft.get("prompt", "")
    duration = draft["duration"]
    resolution = draft["image_resolution"] if menu_mode == "image" else draft["resolution"]
    ratio = draft["image_ratio"] if menu_mode == "image" else draft["ratio"]
    audio = draft["audio"]
    ref_images: List[bytes] = list(draft.get("ref_images") or [])
    if not ref_images and draft.get("image_bytes"):
        ref_images = [draft["image_bytes"]]
    if model_info.get("multi_ref"):
        ref_images = ref_images[: model_info.get("ref_limit", 30)]
    else:
        ref_images = ref_images[:1]

    if menu_mode == "motion":
        ref_images = [draft["motion_image"]]
        duration = int(draft.get("motion_sec") or 0) or -1
    job = GenerationJob(
        user_id=call.from_user.id,
        chat_id=call.message.chat.id,
        status_message_id=call.message.message_id,
        model_key=model_key,
        prompt=prompt,
        duration=duration,
        resolution=resolution,
        ratio=ratio,
        generate_audio=audio,
        image_bytes=ref_images[0] if ref_images else None,
        user_name=draft.get("user_name") or get_user_display_name(call.from_user),
        reply_to_message_id=draft.get("original_message_id"),
        ref_images=ref_images,
        ref_mode=draft.get("ref_mode", "ref"),
        audio_bytes=draft.get("audio_bytes"),
        ref_video=draft.get("ref_video"),
        voice_id=draft.get("voice_id", "") if menu_mode == "voice" else "",
        voice_mode=draft.get("voice_mode", "tts") if menu_mode == "voice" else "tts",
    )

    pos = await queue.add_job(job)
    cost = calculate_credit_cost(model_key, duration, resolution)
    chips = []
    if menu_mode == "image":
        chips.append(f"{resolution} · {ratio}")
    elif menu_mode == "motion":
        chips.append(f"🕺 {resolution}")
    else:
        dur_label = "Авто" if duration == -1 else f"{duration} сек"
        chips.append(f"{dur_label} · {resolution} · {ratio}")
    if ref_images:
        chips.append(f"📎 {len(ref_images)}")
    if job.ref_video:
        chips.append("🎞 видео-реф")
    if cost > 0:
        chips.append(f"💳 ~{cost} кр.")
    quote = f"\n<blockquote expandable>{html.escape(prompt[:500])}</blockquote>" if prompt else ""

    try:
        await call.message.edit_text(
            f"⏳ <b>В очереди #{pos}</b>\n"
            f"<b>{html.escape(model_info['name'])}</b>  ·  " + "  ·  ".join(chips) +
            f"{quote}",
            parse_mode="HTML"
        )
    except Exception:
        pass
    await call.answer()


# --- Main Service Runner ---

async def main():
    token_to_use = (BOT_TOKEN or "").strip()
    if not token_to_use:
        raise RuntimeError("BOT_TOKEN не задан! Пожалуйста, укажите BOT_TOKEN в файле .env")
    bot = Bot(token=token_to_use)
    dp = Dispatcher(storage=MemoryStorage())

    api_client = SeedanceAPIClient()
    v2_client = SeedanceV2Client()
    grok_client = GrokVideoClient()
    minimax_client = MiniMaxClient()
    qwen_client = QwenImageClient()
    davinci_client = DaVinciClient()
    queue = GenerationQueue(
        bot=bot,
        api_client=api_client,
        v2_client=v2_client,
        grok_client=grok_client,
        minimax_client=minimax_client,
        qwen_client=qwen_client,
        davinci_client=davinci_client,
    )

    dp["queue"] = queue
    dp.include_router(router)

    logger.info("Starting Queue Worker...")
    queue.start()

    logger.info("Starting Telegram Bot Polling...")
    try:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Cleared pending Telegram updates and webhooks.")
        except Exception as e:
            logger.warning(f"Failed to clear webhook: {e}")

        while True:
            try:
                await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
                logger.warning("Polling stopped unexpectedly. Reconnecting in 3 seconds...")
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"Polling connection issue: {e}. Reconnecting in 3 seconds...")
                await asyncio.sleep(3)
    finally:
        await queue.stop()
        await api_client.close()
        await v2_client.close()
        await grok_client.close()
        await minimax_client.close()
        await qwen_client.close()
        await davinci_client.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
