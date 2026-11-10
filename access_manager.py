"""
POCO AI Studio — Access Key Manager
Handles cryptographically random key generation, validation, and admin authentication.
Keys are persisted in data/access_keys.json.
"""

import os
import json
import secrets
import string
import time
import hmac
from pathlib import Path
from typing import Dict, Any, List, Optional
import config

DATA_DIR = config.BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
KEYS_FILE = DATA_DIR / "access_keys.json"

# In-memory cache of keys
_keys_cache: Optional[Dict[str, Dict[str, Any]]] = None


def _load_keys() -> Dict[str, Dict[str, Any]]:
    global _keys_cache
    if _keys_cache is not None:
        return _keys_cache

    if not KEYS_FILE.exists():
        _keys_cache = {}
        # Pre-seed one initial master key for creator
        if getattr(config, "KEY_SIGNING_SECRET", ""):
            generate_key(note="Master key (GermanUstinf)", created_by="system")
        return _keys_cache

    try:
        data = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _keys_cache = data
        else:
            _keys_cache = {}
    except Exception:
        _keys_cache = {}

    return _keys_cache


def _save_keys():
    global _keys_cache
    if _keys_cache is None:
        return
    try:
        temp_file = KEYS_FILE.with_suffix(".tmp")
        temp_file.write_text(json.dumps(_keys_cache, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_file.replace(KEYS_FILE)
    except Exception as e:
        print(f"Error saving access keys: {e}")


def _generate_random_key_string() -> str:
    """Generate a random key in format: POCO-XXXX-XXXX (uppercase letters and digits)."""
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # excluded easily confused chars 0,1,O,I
    part1 = "".join(secrets.choice(alphabet) for _ in range(4))
    part2 = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"POCO-{part1}-{part2}"


_KEY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _signing_secret() -> bytes:
    """Shared secret used to sign keys, so the bot and the website agree without shared storage."""
    seed = getattr(config, "KEY_SIGNING_SECRET", "")
    if not seed:
        raise RuntimeError("KEY_SIGNING_SECRET (или ADMIN_PASSWORD) не задан — подписывать ключи нечем")
    return f"poco-access-key:{seed}".encode("utf-8")


def _mac_chars(nonce: str) -> str:
    digest = hmac.new(_signing_secret(), nonce.encode("utf-8"), "sha256").digest()
    return "".join(_KEY_ALPHABET[b % len(_KEY_ALPHABET)] for b in digest[:8])


def _make_signed_key() -> str:
    """Key format: POCO-NNNN-MMMM-MMMM (NNNN random, MMMMMMMM = HMAC of NNNN)."""
    nonce = "".join(secrets.choice(_KEY_ALPHABET) for _ in range(4))
    mac = _mac_chars(nonce)
    return f"POCO-{nonce}-{mac[:4]}-{mac[4:]}"


def _is_signed_key(key: str) -> bool:
    if not getattr(config, "KEY_SIGNING_SECRET", ""):
        return False
    parts = key.split("-")
    if len(parts) != 4 or parts[0] != "POCO" or len(parts[1]) != 4:
        return False
    expected = _mac_chars(parts[1])
    return hmac.compare_digest(parts[2] + parts[3], expected)


def _lookup(cleaned_key: str) -> Optional[Dict[str, Any]]:
    """Find key entry. Validly signed keys issued elsewhere (e.g. by the Telegram bot) are auto-registered."""
    keys = _load_keys()
    entry = keys.get(cleaned_key)
    if entry is not None:
        return None if entry.get("deleted") else entry
    if _is_signed_key(cleaned_key):
        entry = {
            "key": cleaned_key,
            "active": True,
            "created_at": time.time(),
            "created_by": "Telegram bot",
            "note": "Ключ из Telegram-бота",
            "used_count": 0,
            "last_used_at": None,
            "bound_client_id": None,
            "bound_at": None,
        }
        keys[cleaned_key] = entry
        _save_keys()
        return entry
    return None


def generate_key(note: str = "", created_by: str = "@GermanUstinf") -> str:
    """Generate and store a new signed access key (valid on both the bot and the website)."""
    keys = _load_keys()

    # Ensure key is unique
    for _ in range(100):
        key = _make_signed_key()
        if key not in keys:
            break
    else:
        key = _make_signed_key()

    keys[key] = {
        "key": key,
        "active": True,
        "created_at": time.time(),
        "created_by": created_by,
        "note": note.strip() if note else "Ключ доступа",
        "used_count": 0,
        "last_used_at": None,
        "bound_client_id": None,
        "bound_at": None,
    }
    _save_keys()
    return key


def verify_key(key: str, client_id: Optional[str] = None) -> tuple[Optional[Dict[str, Any]], str]:
    """
    Verify access key and enforce strict single-person (single-device) policy.
    Returns (entry, status) where status is one of:
      - 'OK': valid and bound to this person/device
      - 'ALREADY_BOUND': key was already activated by another person/device
      - 'REVOKED': key is deactivated by admin
      - 'INVALID': key does not exist or corrupted
    """
    if not key:
        return None, "INVALID"
    cleaned_key = key.strip().upper()
    entry = _lookup(cleaned_key)

    if not entry:
        return None, "INVALID"

    if not entry.get("active", True):
        return None, "REVOKED"

    bound_client = entry.get("bound_client_id")
    cleaned_cid = str(client_id).strip() if client_id else None

    # Strict single-device binding:
    if not bound_client:
        # First-time activation: bind key permanently to this person's client_id!
        if cleaned_cid:
            entry["bound_client_id"] = cleaned_cid
            entry["bound_at"] = time.time()
        entry["used_count"] = entry.get("used_count", 0) + 1
        entry["last_used_at"] = time.time()
        _save_keys()
        return entry, "OK"

    # Key is already bound to a device:
    if cleaned_cid and bound_client == cleaned_cid:
        # Same user continuing on their authorized device
        entry["used_count"] = entry.get("used_count", 0) + 1
        entry["last_used_at"] = time.time()
        _save_keys()
        return entry, "OK"

    # Mismatch! Another device/person is trying to use the already activated key
    return None, "ALREADY_BOUND"


def unbind_key(key: str) -> bool:
    """Reset device binding for a key so it can be re-bound to another device."""
    cleaned_key = key.strip().upper()
    entry = _lookup(cleaned_key)
    if entry:
        entry["bound_client_id"] = None
        entry["bound_at"] = None
        _save_keys()
        return True
    return False


def is_valid_key(key: str, client_id: Optional[str] = None) -> bool:
    """Check if key exists, is active, and allowed for client_id."""
    if not key:
        return False
    entry, status = verify_key(key, client_id=client_id)
    return status == "OK" and entry is not None


def get_all_keys() -> List[Dict[str, Any]]:
    """Get list of all keys sorted newest first."""
    keys = _load_keys()
    items = [k for k in keys.values() if not k.get("deleted")]
    items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return items


def revoke_key(key: str) -> bool:
    """Revoke (deactivate) an access key."""
    entry = _lookup(key.strip().upper())
    if entry:
        entry["active"] = False
        _save_keys()
        return True
    return False


def activate_key(key: str) -> bool:
    """Reactivate an access key."""
    entry = _lookup(key.strip().upper())
    if entry:
        entry["active"] = True
        _save_keys()
        return True
    return False


def delete_key(key: str) -> bool:
    """Permanently delete an access key (kept as a hidden tombstone so signed keys can't be re-accepted)."""
    cleaned_key = key.strip().upper()
    keys = _load_keys()
    entry = keys.get(cleaned_key)
    if entry:
        entry["active"] = False
        entry["deleted"] = True
        _save_keys()
        return True
    return False


def verify_admin_password(password: str) -> bool:
    """Secure constant-time comparison of admin password."""
    admin_pwd = getattr(config, "ADMIN_PASSWORD", "")
    if not password or not admin_pwd:
        return False
    return hmac.compare_digest(password.strip(), admin_pwd.strip())
