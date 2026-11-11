"""
POCO AI Studio & Bot — User Access Whitelist Manager
Controls which Telegram users are authorized to use the bot in PM and groups.
Persists whitelist in data/allowed_users.json.
"""

import os
import json
import time
import hmac
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Message, CallbackQuery, TelegramObject, User
import config

logger = logging.getLogger(__name__)

DATA_DIR = config.BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_USERS_FILE = DATA_DIR / "allowed_users.json"

# Permanent super-admins (always allowed, cannot be revoked)
DEFAULT_ADMIN_USERNAMES = ["germanustinf", "german792", "german_ustinf"]

# In-memory cached state
_access_cache: Optional[Dict[str, Any]] = None


def _load_access_data() -> Dict[str, Any]:
    global _access_cache
    if _access_cache is not None:
        return _access_cache

    default_data = {
        "admins": {
            "usernames": list(DEFAULT_ADMIN_USERNAMES),
            "user_ids": []
        },
        "allowed_usernames": list(DEFAULT_ADMIN_USERNAMES),
        "allowed_user_ids": [],
        "details": {
            "germanustinf": {
                "username": "GermanUstinf",
                "added_at": time.time(),
                "added_by": "system",
                "role": "superadmin"
            }
        }
    }

    if not ALLOWED_USERS_FILE.exists():
        _access_cache = default_data
        _save_access_data()
        return _access_cache

    try:
        content = ALLOWED_USERS_FILE.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, dict):
            # Ensure required structures exist
            if "admins" not in data or not isinstance(data["admins"], dict):
                data["admins"] = {"usernames": list(DEFAULT_ADMIN_USERNAMES), "user_ids": []}
            if "allowed_usernames" not in data or not isinstance(data["allowed_usernames"], list):
                data["allowed_usernames"] = list(DEFAULT_ADMIN_USERNAMES)
            if "allowed_user_ids" not in data or not isinstance(data["allowed_user_ids"], list):
                data["allowed_user_ids"] = []
            if "details" not in data or not isinstance(data["details"], dict):
                data["details"] = {}

            # Always ensure GermanUstinf is in admins and allowed
            for adm in DEFAULT_ADMIN_USERNAMES:
                if adm not in [u.lower() for u in data["admins"]["usernames"]]:
                    data["admins"]["usernames"].append(adm)
                if adm not in [u.lower() for u in data["allowed_usernames"]]:
                    data["allowed_usernames"].append(adm)

            _access_cache = data
        else:
            _access_cache = default_data
    except Exception as e:
        logger.error(f"Error loading allowed_users.json: {e}")
        _access_cache = default_data

    return _access_cache


def _save_access_data():
    global _access_cache
    if _access_cache is None:
        return
    try:
        tmp_file = ALLOWED_USERS_FILE.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(_access_cache, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_file.replace(ALLOWED_USERS_FILE)
    except Exception as e:
        logger.error(f"Error saving allowed_users.json: {e}")


def is_admin(user: Optional[User]) -> bool:
    """Check if the user is an admin / owner."""
    if not user:
        return False

    data = _load_access_data()

    # Check username
    if user.username:
        u_lower = user.username.strip().lower()
        if u_lower in [adm.lower() for adm in data["admins"].get("usernames", [])]:
            return True
        if u_lower in DEFAULT_ADMIN_USERNAMES:
            return True
        if u_lower in [adm.lower() for adm in getattr(config, "ADMIN_TELEGRAM_USERNAMES", [])]:
            return True

    # Check user ID
    if user.id:
        if user.id in data["admins"].get("user_ids", []):
            return True
        if user.id in getattr(config, "ADMIN_TELEGRAM_IDS", []):
            return True
            return True
        env_admin_ids = [
            int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()
        ]
        if user.id in env_admin_ids:
            return True

    return False


def is_user_allowed(user: Optional[User]) -> bool:
    """Check if the user is authorized to use the bot."""
    if not user:
        return False

    if is_admin(user):
        return True

    data = _load_access_data()
    uid = user.id
    uname = (user.username or "").strip().lower()

    # 1. Check user ID
    if uid and uid in data.get("allowed_user_ids", []):
        return True

    # 2. Check username
    if uname and uname in [u.lower() for u in data.get("allowed_usernames", [])]:
        # Auto-learn user ID for future requests
        if uid and uid not in data.get("allowed_user_ids", []):
            data["allowed_user_ids"].append(uid)
            if uname in data.get("details", {}):
                data["details"][uname]["user_id"] = uid
            _save_access_data()
        return True

    return False


def allow_user(
    identifier: str,
    added_by: str = "",
    target_user: Optional[User] = None
) -> Tuple[bool, str]:
    """Grant bot access to a user by username or numeric Telegram user ID."""
    data = _load_access_data()
    clean_id = (identifier or "").strip()

    if target_user:
        uid = target_user.id
        uname = (target_user.username or "").strip().lower()
        disp_name = target_user.full_name or f"User {uid}"

        if uid not in data["allowed_user_ids"]:
            data["allowed_user_ids"].append(uid)
        if uname and uname not in data["allowed_usernames"]:
            data["allowed_usernames"].append(uname)

        key = uname if uname else str(uid)
        data["details"][key] = {
            "user_id": uid,
            "username": target_user.username or "",
            "name": disp_name,
            "added_at": time.time(),
            "added_by": added_by or "admin",
            "role": "user"
        }
        _save_access_data()
        u_label = f"@{target_user.username}" if target_user.username else disp_name
        return True, f"✅ Доступ разрешен для <b>{u_label}</b> (ID: <code>{uid}</code>)!"

    if not clean_id:
        return False, "⚠️ Укажите @username или числовой ID пользователя. Например: <code>/allow @GermanUstinf</code>"

    # If it's a numeric ID
    if clean_id.lstrip("-").isdigit():
        uid = int(clean_id)
        if uid not in data["allowed_user_ids"]:
            data["allowed_user_ids"].append(uid)
        data["details"][str(uid)] = {
            "user_id": uid,
            "username": "",
            "name": f"User {uid}",
            "added_at": time.time(),
            "added_by": added_by or "admin",
            "role": "user"
        }
        _save_access_data()
        return True, f"✅ Доступ разрешен для ID: <code>{uid}</code>!"

    # It's a username
    clean_uname = clean_id.lstrip("@").strip().lower()
    if not clean_uname:
        return False, "⚠️ Некорректный username."

    if clean_uname not in data["allowed_usernames"]:
        data["allowed_usernames"].append(clean_uname)

    data["details"][clean_uname] = {
        "user_id": None,
        "username": clean_id.lstrip("@"),
        "name": f"@{clean_id.lstrip('@')}",
        "added_at": time.time(),
        "added_by": added_by or "admin",
        "role": "user"
    }
    _save_access_data()
    return True, f"✅ Доступ разрешен для <b>@{clean_id.lstrip('@')}</b>!"


def revoke_user(
    identifier: str,
    target_user: Optional[User] = None
) -> Tuple[bool, str]:
    """Revoke bot access from a user."""
    data = _load_access_data()

    if target_user:
        uid = target_user.id
        uname = (target_user.username or "").strip().lower()

        if uname in DEFAULT_ADMIN_USERNAMES:
            return False, "⚠️ Нельзя отозвать доступ у создателя @GermanUstinf!"

        changed = False
        if uid in data["allowed_user_ids"]:
            data["allowed_user_ids"].remove(uid)
            changed = True
        if uname and uname in data["allowed_usernames"]:
            data["allowed_usernames"].remove(uname)
            changed = True

        data["details"].pop(uname, None)
        data["details"].pop(str(uid), None)

        if changed:
            _save_access_data()
        u_label = f"@{target_user.username}" if target_user.username else target_user.full_name
        return True, f"🚫 Доступ для <b>{u_label}</b> закрыт."

    clean_id = (identifier or "").strip()
    if not clean_id:
        return False, "⚠️ Укажите @username или ID пользователя. Например: <code>/revoke @username</code>"

    # If numeric ID
    if clean_id.lstrip("-").isdigit():
        uid = int(clean_id)
        if uid in [u.get("user_id") for u in data["details"].values() if u.get("role") in ("admin", "superadmin")]:
            return False, "⚠️ Нельзя отозвать доступ у администратора!"

        changed = False
        if uid in data["allowed_user_ids"]:
            data["allowed_user_ids"].remove(uid)
            changed = True

        entry = data["details"].pop(str(uid), None)
        if entry and entry.get("username"):
            bound_uname = entry["username"].lower()
            if bound_uname in data["allowed_usernames"]:
                data["allowed_usernames"].remove(bound_uname)
                data["details"].pop(bound_uname, None)
                changed = True

        # Also search details by user_id
        for key, val in list(data["details"].items()):
            if val.get("user_id") == uid:
                data["details"].pop(key, None)
                if val.get("username") and val["username"].lower() in data["allowed_usernames"]:
                    data["allowed_usernames"].remove(val["username"].lower())
                changed = True

        if changed:
            _save_access_data()
            return True, f"🚫 Доступ для ID: <code>{uid}</code> закрыт."
        return False, f"⚠️ Пользователь с ID <code>{uid}</code> не найден в списке доступа."

    # Username
    clean_uname = clean_id.lstrip("@").strip().lower()
    if clean_uname in DEFAULT_ADMIN_USERNAMES:
        return False, "⚠️ Нельзя отозвать доступ у создателя @GermanUstinf!"

    changed = False
    if clean_uname in data["allowed_usernames"]:
        data["allowed_usernames"].remove(clean_uname)
        changed = True

    entry = data["details"].pop(clean_uname, None)
    if entry and entry.get("user_id"):
        bound_uid = entry["user_id"]
        if bound_uid in data["allowed_user_ids"]:
            data["allowed_user_ids"].remove(bound_uid)
            changed = True
        data["details"].pop(str(bound_uid), None)

    # Search details by username match
    for key, val in list(data["details"].items()):
        if (val.get("username") or "").lower() == clean_uname:
            data["details"].pop(key, None)
            if val.get("user_id") and val["user_id"] in data["allowed_user_ids"]:
                data["allowed_user_ids"].remove(val["user_id"])
            changed = True

    if changed:
        _save_access_data()
        return True, f"🚫 Доступ для <b>@{clean_id.lstrip('@')}</b> закрыт."

    return False, f"⚠️ Пользователь <b>@{clean_id.lstrip('@')}</b> не найден в списке доступа."


def get_allowed_users_list() -> List[Dict[str, Any]]:
    """Return list of allowed users with details."""
    data = _load_access_data()
    result = []
    seen = set()

    # Priority to details
    for key, info in data.get("details", {}).items():
        uname = info.get("username")
        uid = info.get("user_id")
        ident = f"@{uname.lower()}" if uname else str(uid)
        seen.add(ident)
        result.append(info)

    # Any remaining usernames
    for uname in data.get("allowed_usernames", []):
        ident = f"@{uname.lower()}"
        if ident not in seen:
            seen.add(ident)
            result.append({
                "username": uname,
                "user_id": None,
                "name": f"@{uname}",
                "role": "admin" if uname.lower() in DEFAULT_ADMIN_USERNAMES else "user",
                "added_by": "system"
            })

    # Any remaining user IDs
    for uid in data.get("allowed_user_ids", []):
        ident = str(uid)
        if ident not in seen:
            seen.add(ident)
            result.append({
                "username": "",
                "user_id": uid,
                "name": f"ID: {uid}",
                "role": "user",
                "added_by": "system"
            })

    return result


def authenticate_admin(user: User, password: str) -> bool:
    """Authenticate an admin using the secret admin password."""
    admin_pwd = (
        getattr(config, "ADMIN_PASSWORD", "")
        or os.getenv("ADMIN_PASSWORD", "")
        or os.getenv("TOKEN4", "")
        or getattr(config, "API_PASSWORD", "")
    ).strip()

    if not admin_pwd or not password:
        return False

    if hmac.compare_digest(password.strip(), admin_pwd):
        data = _load_access_data()
        uid = user.id
        uname = (user.username or "").strip().lower()

        if uid not in data["admins"]["user_ids"]:
            data["admins"]["user_ids"].append(uid)
        if uid not in data["allowed_user_ids"]:
            data["allowed_user_ids"].append(uid)

        if uname:
            if uname not in data["admins"]["usernames"]:
                data["admins"]["usernames"].append(uname)
            if uname not in data["allowed_usernames"]:
                data["allowed_usernames"].append(uname)

        _save_access_data()
        return True

    return False


class AccessControlMiddleware(BaseMiddleware):
    """
    Aiogram middleware that enforces whitelist access control.
    Blocks unauthorized users in both PM and groups from triggering commands,
    prompts, references, and callback buttons.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Handle CallbackQuery
        if isinstance(event, CallbackQuery):
            user = event.from_user
            if not user or is_user_allowed(user):
                return await handler(event, data)

            await event.answer(
                "⛔ У вас нет доступа к боту! Доступ выдается администратором @GermanUstinf.",
                show_alert=True
            )
            return None

        # Handle Message
        if isinstance(event, Message):
            user = event.from_user
            if not user:
                return await handler(event, data)

            text = (event.text or event.caption or "").strip()

            # Always let admin auth command through
            if text.startswith("/admin"):
                return await handler(event, data)

            # If user is authorized, proceed normally
            if is_user_allowed(user):
                return await handler(event, data)

            # User is NOT authorized:
            if event.chat.type == ChatType.PRIVATE:
                await event.reply(
                    "⛔ <b>Доступ ограничен</b>\n\n"
                    "У вас нет разрешения на использование бота <b>Poco AI</b>.\n"
                    "Для получения доступа обратитесь к администратору: @GermanUstinf",
                    parse_mode="HTML"
                )
                return None

            if event.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                # In groups, only answer if the unauthorized user explicitly addressed the bot
                is_command = text.startswith("/")
                is_reply_to_bot = False
                if event.reply_to_message and event.reply_to_message.from_user:
                    is_reply_to_bot = bool(event.reply_to_message.from_user.is_bot)

                bot_username = ""
                try:
                    bot_info = await event.bot.get_me()
                    bot_username = (bot_info.username or "").lower()
                except Exception:
                    pass

                is_mention = (f"@{bot_username}" in text.lower()) if bot_username else False

                if is_command or is_reply_to_bot or is_mention:
                    user_tag = user.mention_html(user.full_name)
                    await event.reply(
                        f"⛔ {user_tag}, у вас нет доступа к боту <b>Poco AI</b>!\n"
                        f"Доступ выдается администратором: @GermanUstinf",
                        parse_mode="HTML"
                    )
                return None

        return await handler(event, data)
