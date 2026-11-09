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
        initial_key = generate_key(note="Master key (GermanUstinf)", created_by="system")
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


def generate_key(note: str = "", created_by: str = "@GermanUstinf") -> str:
    """Generate and store a new unique random access key."""
    keys = _load_keys()
    
    # Ensure key is unique
    for _ in range(100):
        key = _generate_random_key_string()
        if key not in keys:
            break
    else:
        key = f"POCO-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"

    keys[key] = {
        "key": key,
        "active": True,
        "created_at": time.time(),
        "created_by": created_by,
        "note": note.strip() if note else "Ключ доступа",
        "used_count": 0,
        "last_used_at": None,
    }
    _save_keys()
    return key


def verify_key(key: str) -> Optional[Dict[str, Any]]:
    """
    Verify access key. Returns key metadata if valid & active, otherwise None.
    Increments usage count on successful verification.
    """
    if not key:
        return None
    cleaned_key = key.strip().upper()
    keys = _load_keys()

    if cleaned_key in keys:
        entry = keys[cleaned_key]
        if entry.get("active", True):
            entry["used_count"] = entry.get("used_count", 0) + 1
            entry["last_used_at"] = time.time()
            _save_keys()
            return entry
    return None


def is_valid_key(key: str) -> bool:
    """Check if key exists and is currently active."""
    if not key:
        return False
    cleaned_key = key.strip().upper()
    keys = _load_keys()
    entry = keys.get(cleaned_key)
    return bool(entry and entry.get("active", True))


def get_all_keys() -> List[Dict[str, Any]]:
    """Get list of all keys sorted newest first."""
    keys = _load_keys()
    items = list(keys.values())
    items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return items


def revoke_key(key: str) -> bool:
    """Revoke (deactivate) an access key."""
    cleaned_key = key.strip().upper()
    keys = _load_keys()
    if cleaned_key in keys:
        keys[cleaned_key]["active"] = False
        _save_keys()
        return True
    return False


def activate_key(key: str) -> bool:
    """Reactivate an access key."""
    cleaned_key = key.strip().upper()
    keys = _load_keys()
    if cleaned_key in keys:
        keys[cleaned_key]["active"] = True
        _save_keys()
        return True
    return False


def delete_key(key: str) -> bool:
    """Permanently delete an access key."""
    cleaned_key = key.strip().upper()
    keys = _load_keys()
    if cleaned_key in keys:
        del keys[cleaned_key]
        _save_keys()
        return True
    return False


def verify_admin_password(password: str) -> bool:
    """Secure constant-time comparison of admin password."""
    if not password:
        return False
    admin_pwd = getattr(config, "ADMIN_PASSWORD", "GermanUstinf2026!")
    return hmac.compare_digest(password.strip(), admin_pwd.strip())
