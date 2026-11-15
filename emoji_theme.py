import copy
import logging
from typing import Dict, Optional, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import TelegramMethod
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

# Curated 100% ANIMATED custom emojis (YellowColorEmoji, greenrandom1, LoadingsEmoji, ilovegun — zero static)
EMOJI_PACK: Dict[str, Tuple[str, str]] = {
    # greenrandom1 (animated .webm — neon green POCO aesthetic)
    "spark": ("5393346680202470010", "✨"),
    "wand": ("5391215461595619398", "✨"),
    "flame": ("5391291190458983255", "🔥"),
    "console": ("5393392481733713694", "🎮"),
    "mask": ("5390810553553789663", "🎭"),
    "cosmos": ("5390810553553789663", "🎭"),
    "gem": ("5393151890550694497", "💎"),
    "check": ("5391117231398592540", "✅"),
    "pin": ("5393348750376706864", "📌"),
    "link": ("5390823932376915757", "🔗"),
    "cash": ("5393513166019763957", "💵"),
    "mega": ("5390852146017083847", "📣"),
    "globe": ("5391254988179643937", "🌐"),
    "back": ("5391091830962004343", "⬅️"),
    "next": ("5393457035092172735", "➡️"),
    "down": ("5393555299648937543", "👇"),
    "up": ("5391212523837988003", "☝️"),
    "gift": ("5391086187374978074", "🎁"),
    "dot": ("5391076601007972395", "🟢"),
    "planet": ("5393503493753413560", "🪐"),
    "astro": ("5391143293260143367", "👽"),
    "eye": ("5391324545175002432", "👁"),
    "alchemy": ("5391332692727966064", "🧪"),
    "book": ("5390953258137166783", "📖"),
    "voice": ("5391036812430945263", "🎙"),
    "heart": ("5393564950440451455", "💚"),
    "crystal": ("5391143843015956922", "🌟"),
    # YellowColorEmoji (animated .webm — golden yellow accents)
    "bolt": ("5474610502279637013", "⚡"),
    "fire": ("5474342835622782187", "🔥"),
    "rocket": ("5474342835622782187", "🚀"),
    "nova": ("5474241190926755356", "🌟"),
    "twinkle": ("5474524319465874968", "✨"),
    "uhd": ("5474136007177679142", "📐"),
    "vip": ("5474209240665041113", "👑"),
    "star": ("5188612843401914868", "⭐"),
    "card": ("5474641619317698626", "💳"),
    "coin": ("5188663180418623845", "🪙"),
    "idea": ("5188367033833630878", "💡"),
    "party": ("5188614183431710025", "🎉"),
    "check_y": ("5474484535183811843", "✅"),
    "gem_y": ("5188264839381788929", "💎"),
    "warn": ("5188414871179372207", "⚠️"),
    "alert": ("5474259474602534008", "❌"),
    "ban": ("5188476607039286175", "❌"),
    "mail": ("5474356317525126077", "📩"),
    "dot_y": ("5474382439516219269", "🟡"),
    "dance": ("5188174202686939924", "🕺"),
    # LoadingsEmoji (animated .tgs — spinners, loaders & geometric UI)
    "load_orbit": ("6003326057363540975", "⏳"),
    "load_ring": ("6001553618849762672", "🔄"),
    "load_atom": ("6003384297120074872", "⚛️"),
    "load_pulse": ("6003367185970368385", "🌀"),
    "load_gears": ("6003859951863205054", "⚙️"),
    "load_hourglass": ("6003342034641882211", "⏳"),
    "load_dual": ("6003497512457997922", "🔄"),
    "load_dots": ("6003714666004483380", "⏳"),
    "load_starburst": ("6003708133359227206", "🔄"),
    "load_neon": ("6003687135264115944", "🔄"),
    "grid": ("6003358179423948133", "🔲"),
    "replay": ("6001346176224334172", "🔄"),
    "chat": ("6003378662122982771", "💬"),
    "cube": ("6003414791387877649", "🧊"),
    # ilovegun (animated .webm — golden & neon tactical action accents)
    "shot": ("5343845137711637758", "💥"),
    "aim_green": ("5348537264928465455", "🎯"),
    "ak_gold": ("5199598948838285850", "🔫"),
}

LOADER_CYCLE_KEYS = (
    "load_neon",
    "load_orbit",
    "load_atom",
    "load_pulse",
    "load_dual",
    "load_dots",
)

CUSTOM_EMOJI_TEXT_ENABLED = True
CUSTOM_EMOJI_BUTTONS_ENABLED = True


def ce(key: str, fallback: Optional[str] = None) -> str:
    """Return HTML `<tg-emoji>` tag for a curated pack key (safe fallback on non-premium clients)."""
    cid, default_fb = EMOJI_PACK.get(key, ("", "✨"))
    fb = fallback if fallback is not None else default_fb
    if not CUSTOM_EMOJI_TEXT_ENABLED or not cid:
        return fb
    return f'<tg-emoji emoji-id="{cid}">{fb}</tg-emoji>'


def loader_emoji(stage: str = "", elapsed: int = 0) -> str:
    """Pick an animated LoadingsEmoji `<tg-emoji>` suited to the current generation stage."""
    low = (stage or "").lower()
    if "отправка" in low or "запуск" in low:
        return ce("load_hourglass", "⏳")
    if "скачива" in low or "отправля" in low or "накладыва" in low:
        return ce("load_starburst", "📤")
    if "монта" in low or "сборк" in low or "постобработ" in low:
        return ce("load_gears", "⚙️")
    key = LOADER_CYCLE_KEYS[(max(0, elapsed) // 4) % len(LOADER_CYCLE_KEYS)]
    return ce(key, "⏳")


def cbtn(
    text: str,
    callback_data: str,
    icon_key: Optional[str] = None,
    fallback_emoji: str = "",
    style: Optional[str] = None,
) -> InlineKeyboardButton:
    """Build an InlineKeyboardButton with native Bot API 9.4 animated `icon_custom_emoji_id`."""
    kwargs = {}
    if style:
        kwargs["style"] = style
    cid = EMOJI_PACK.get(icon_key, ("", ""))[0] if icon_key else ""
    if CUSTOM_EMOJI_BUTTONS_ENABLED and cid:
        kwargs["icon_custom_emoji_id"] = cid
        label = text
    else:
        label = f"{fallback_emoji} {text}".strip() if fallback_emoji else text
    return InlineKeyboardButton(text=label, callback_data=callback_data, **kwargs)


def strip_markup_button_icons(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """Return a copy of InlineKeyboardMarkup with `icon_custom_emoji_id` cleared from all buttons."""
    new_rows = []
    for row in markup.inline_keyboard:
        new_row = []
        for btn in row:
            data = btn.model_dump(exclude_none=True)
            data.pop("icon_custom_emoji_id", None)
            new_row.append(InlineKeyboardButton(**data))
        new_rows.append(new_row)
    return InlineKeyboardMarkup(inline_keyboard=new_rows)


class SmartEmojiBot(Bot):
    """Bot subclass that auto-falls back gracefully if Telegram rejects button custom emojis."""

    async def __call__(self, method: TelegramMethod, request_timeout: Optional[int] = None):
        global CUSTOM_EMOJI_BUTTONS_ENABLED
        try:
            return await super().__call__(method, request_timeout=request_timeout)
        except TelegramBadRequest as err:
            msg = str(err)
            markup = getattr(method, "reply_markup", None)
            if isinstance(markup, InlineKeyboardMarkup) and (
                "BUTTON_CUSTOM_EMOJI_INVALID" in msg or "CUSTOM_EMOJI_INVALID" in msg
            ):
                logger.warning(
                    "Telegram rejected button custom emoji (%s); disabling button custom emoji icons and retrying cleanly.",
                    msg,
                )
                CUSTOM_EMOJI_BUTTONS_ENABLED = False
                patched = copy.copy(method)
                patched.reply_markup = strip_markup_button_icons(markup)
                return await super().__call__(patched, request_timeout=request_timeout)
            raise
