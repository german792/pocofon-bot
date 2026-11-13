"""
POCO AI Studio & Bot — Cameo Character Presets Manager
Allows users (and admins for shared public characters) to save reusable character presets
under short @handles (e.g. @poco, @max) with 1-3 reference photos and appearance notes.
Persists in data/cameos.json and syncs asynchronously to GitHub ([skip ci]) like user_access.py.
"""

import base64
import io
import json
import logging
import os
import re
import threading
import time
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageOps

import config

logger = logging.getLogger(__name__)

DATA_DIR = config.BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CAMEOS_FILE = DATA_DIR / "cameos.json"

GITHUB_SYNC_TOKEN = os.getenv("GH_PAT") or os.getenv("GITHUB_TOKEN") or ""
GITHUB_REPO = os.getenv("GITHUB_REPOSITORY") or "german792/pocofon-bot2"

MAX_IMAGES_PER_CAMEO = 3
HANDLE_RE = re.compile(r"^[a-zа-яё0-9_]{2,24}$")
MENTION_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё0-9_@])@([A-Za-zА-Яа-яЁё0-9_]{2,24})\b")
RESERVED_HANDLES = {
    "video",
    "video1",
    "video2",
    "image",
    "image1",
    "image2",
    "all",
    "everyone",
    "here",
    "channel",
    "cameo",
}

_lock = threading.Lock()
_cameos_cache: Optional[Dict[str, Any]] = None
_gh_sha: Optional[str] = None
_gh_loaded = False


def normalize_handle(raw: str) -> str:
    """Normalize @handle to clean lowercase slug or return empty string if invalid/reserved."""
    clean = (raw or "").strip().lstrip("@").lower()
    if not clean or clean in RESERVED_HANDLES or not HANDLE_RE.match(clean):
        return ""
    return clean


def extract_handles_from_text(text: str) -> List[str]:
    """Extract unique valid Cameo handles referenced with @tag in text, preserving order."""
    seen: List[str] = []
    for m in MENTION_RE.finditer(text or ""):
        h = normalize_handle(m.group(1))
        if h and h not in seen:
            seen.append(h)
    return seen


def compress_cameo_image(img_bytes: bytes, max_side: int = 960, quality: int = 82) -> bytes:
    """Resize and JPEG-compress a Cameo reference photo so storage and sync stay lightweight."""
    with Image.open(io.BytesIO(img_bytes)) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            rgba = im.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()


def _fetch_from_github_once() -> None:
    global _cameos_cache, _gh_sha, _gh_loaded
    if _gh_loaded:
        return
    _gh_loaded = True
    if not GITHUB_SYNC_TOKEN or not GITHUB_REPO:
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/data/cameos.json"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {GITHUB_SYNC_TOKEN}",
                "User-Agent": "poco-bot-cameo-sync",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=6.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            _gh_sha = res.get("sha")
            raw_bytes = base64.b64decode(res.get("content", ""))
            gh_data = json.loads(raw_bytes.decode("utf-8"))
            if isinstance(gh_data, dict) and isinstance(gh_data.get("entries"), dict):
                _cameos_cache = gh_data
                CAMEOS_FILE.write_text(json.dumps(gh_data, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info(f"Loaded cameos.json from GitHub ({len(gh_data['entries'])} entries)")
    except Exception as e:
        logger.debug(f"GitHub cameo fetch note: {e}")


def _sync_to_github_worker(snapshot: Dict[str, Any]) -> None:
    global _gh_sha
    if not GITHUB_SYNC_TOKEN or not GITHUB_REPO:
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/data/cameos.json"
        if not _gh_sha:
            try:
                chk_req = urllib.request.Request(
                    url,
                    headers={
                        "Authorization": f"Bearer {GITHUB_SYNC_TOKEN}",
                        "User-Agent": "poco-bot-cameo-sync",
                    },
                )
                with urllib.request.urlopen(chk_req, timeout=5.0) as chk_resp:
                    chk_data = json.loads(chk_resp.read().decode("utf-8"))
                    _gh_sha = chk_data.get("sha")
            except Exception:
                pass

        content_bytes = json.dumps(snapshot, indent=2, ensure_ascii=False).encode("utf-8")
        payload: Dict[str, Any] = {
            "message": "Update cameos.json [skip ci]",
            "content": base64.b64encode(content_bytes).decode("ascii"),
        }
        if _gh_sha:
            payload["sha"] = _gh_sha

        put_req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {GITHUB_SYNC_TOKEN}",
                "User-Agent": "poco-bot-cameo-sync",
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        with urllib.request.urlopen(put_req, timeout=8.0) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            _gh_sha = resp_data.get("content", {}).get("sha")
            logger.info(f"Synced cameos.json to GitHub ({GITHUB_REPO})")
    except Exception as e:
        logger.warning(f"Failed to sync cameos.json to GitHub: {e}")


def _load_data() -> Dict[str, Any]:
    global _cameos_cache
    with _lock:
        if _cameos_cache is not None:
            return _cameos_cache
        _fetch_from_github_once()
        if _cameos_cache is not None:
            return _cameos_cache
        if CAMEOS_FILE.exists():
            try:
                loaded = json.loads(CAMEOS_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("entries"), dict):
                    for k, ent in loaded["entries"].items():
                        if isinstance(ent, dict) and not ent.get("id"):
                            ent["id"] = uuid.uuid4().hex[:8]
                    _cameos_cache = loaded
                    return _cameos_cache
            except Exception as e:
                logger.warning(f"Failed reading {CAMEOS_FILE}: {e}")
        _cameos_cache = {"entries": {}}
        return _cameos_cache


def _save_data(data: Dict[str, Any], sync_github: bool = True) -> None:
    snapshot = json.loads(json.dumps(data, ensure_ascii=False))
    CAMEOS_FILE.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    if sync_github and GITHUB_SYNC_TOKEN and GITHUB_REPO:
        t = threading.Thread(target=_sync_to_github_worker, args=(snapshot,), daemon=True)
        t.start()


def _entry_key(owner_id: int, handle: str, is_public: bool = False) -> str:
    return f"public:{handle}" if is_public else f"user:{owner_id}:{handle}"


def upsert_cameo(
    owner_id: int,
    owner_name: str,
    handle: str,
    images: List[bytes],
    description: str = "",
    is_public: bool = False,
) -> Dict[str, Any]:
    """Create or update a Cameo character preset with 1-3 compressed JPEG images."""
    clean_handle = normalize_handle(handle)
    if not clean_handle:
        raise ValueError("Некорректный @тег: используйте 2–24 буквы/цифры/_")
    clean_imgs = [compress_cameo_image(b) for b in images if b][:MAX_IMAGES_PER_CAMEO]
    if not clean_imgs:
        raise ValueError("Нужно минимум 1 изображение для Камео")

    data = _load_data()
    key = _entry_key(owner_id, clean_handle, is_public=is_public)
    now = time.time()
    prev = data["entries"].get(key) or {}
    entry = {
        "id": prev.get("id") or uuid.uuid4().hex[:8],
        "key": key,
        "handle": clean_handle,
        "owner_id": int(owner_id),
        "owner_name": owner_name or "",
        "is_public": bool(is_public),
        "description": (description or "").strip()[:300],
        "images": [base64.b64encode(b).decode("ascii") for b in clean_imgs],
        "created_at": prev.get("created_at", now),
        "updated_at": now,
    }
    data["entries"][key] = entry
    _save_data(data)
    return entry


def get_cameo(handle: str, user_id: int) -> Optional[Dict[str, Any]]:
    """Find a Cameo by @handle for user_id (personal takes precedence over public)."""
    clean = normalize_handle(handle)
    if not clean:
        return None
    entries = _load_data().get("entries", {})
    personal = entries.get(_entry_key(user_id, clean, is_public=False))
    if personal:
        return personal
    return entries.get(_entry_key(0, clean, is_public=True))


def get_cameo_by_key(key: str, user_id: int) -> Optional[Dict[str, Any]]:
    """Lookup Cameo by internal storage key or short id if visible to user_id."""
    entries = _load_data().get("entries", {})
    entry = entries.get(key)
    if not entry:
        for ent in entries.values():
            if ent.get("id") == key:
                entry = ent
                break
    if not entry:
        return None
    if entry.get("is_public") or int(entry.get("owner_id", 0)) == int(user_id):
        return entry
    return None


def list_cameos_for_user(user_id: int) -> List[Dict[str, Any]]:
    """Return user's personal Cameos first, then shared public Cameos not shadowed by handle."""
    entries = list(_load_data().get("entries", {}).values())
    personal = [e for e in entries if not e.get("is_public") and int(e.get("owner_id", 0)) == int(user_id)]
    personal_handles = {e.get("handle") for e in personal}
    public = [e for e in entries if e.get("is_public") and e.get("handle") not in personal_handles]
    personal.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    public.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return personal + public


def _resolve_entry_key(entries: Dict[str, Any], key_or_id: str) -> Optional[str]:
    if key_or_id in entries:
        return key_or_id
    for k, ent in entries.items():
        if ent.get("id") == key_or_id:
            return k
    return None


def update_cameo_description(key: str, requester_id: int, description: str, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    data = _load_data()
    entries = data.get("entries", {})
    real_key = _resolve_entry_key(entries, key)
    entry = entries.get(real_key) if real_key else None
    if not entry:
        return None
    if int(entry.get("owner_id", 0)) != int(requester_id) and not (is_admin and entry.get("is_public")):
        return None
    entry["description"] = (description or "").strip()[:300]
    entry["updated_at"] = time.time()
    _save_data(data)
    return entry


def toggle_cameo_public(key: str, requester_id: int, is_admin: bool = False) -> Optional[Dict[str, Any]]:
    if not is_admin:
        return None
    data = _load_data()
    entries = data.get("entries", {})
    real_key = _resolve_entry_key(entries, key)
    entry = entries.get(real_key) if real_key else None
    if not entry or not real_key:
        return None
    new_pub = not bool(entry.get("is_public"))
    owner_id = int(entry.get("owner_id") or requester_id)
    new_key = _entry_key(owner_id, entry["handle"], is_public=new_pub)
    entries.pop(real_key, None)
    entry["key"] = new_key
    entry["is_public"] = new_pub
    entry["updated_at"] = time.time()
    entries[new_key] = entry
    _save_data(data)
    return entry


def delete_cameo(key_or_handle: str, requester_id: int, is_admin: bool = False) -> bool:
    """Delete Cameo by storage key, short id, or @handle if permitted."""
    data = _load_data()
    entries = data.get("entries", {})
    target_key: Optional[str] = _resolve_entry_key(entries, key_or_handle)
    if not target_key:
        h = normalize_handle(key_or_handle)
        if h:
            k_pers = _entry_key(requester_id, h, is_public=False)
            k_pub = _entry_key(0, h, is_public=True)
            if k_pers in entries:
                target_key = k_pers
            elif k_pub in entries:
                target_key = k_pub
    if not target_key:
        return False
    entry = entries[target_key]
    if int(entry.get("owner_id", 0)) != int(requester_id) and not is_admin:
        return False
    entries.pop(target_key, None)
    _save_data(data)
    return True


def get_cameo_images(cameo: Dict[str, Any]) -> List[bytes]:
    out: List[bytes] = []
    for b64 in cameo.get("images") or []:
        try:
            out.append(base64.b64decode(b64))
        except Exception:
            pass
    return out


def resolve_cameos_for_generation(
    prompt: str,
    user_id: int,
    attached_handles: Optional[List[str]] = None,
    existing_refs: Optional[List[bytes]] = None,
    max_refs: int = 9,
    model_api_id: str = "",
    category: str = "video",
) -> Tuple[str, List[bytes], List[str]]:
    """Resolve @cameo handles (both explicitly attached and mentioned in prompt) into
    reference images and rewrite prompt tokens for the target model backend.

    Returns (final_prompt, merged_ref_images, used_handles).
    """
    base_refs = [b for b in (existing_refs or []) if b]
    clean_prompt = (prompt or "").strip()

    ordered_handles: List[str] = []
    for raw in list(attached_handles or []) + extract_handles_from_text(clean_prompt):
        h = normalize_handle(raw)
        if h and h not in ordered_handles:
            ordered_handles.append(h)

    matched: List[Tuple[str, Dict[str, Any], List[bytes]]] = []
    for h in ordered_handles:
        entry = get_cameo(h, user_id)
        if entry:
            imgs = get_cameo_images(entry)
            if imgs:
                matched.append((h, entry, imgs))

    if not matched:
        return clean_prompt, base_refs[:max_refs], []

    slots_left = max(0, max_refs - len(base_refs))
    if slots_left == 0:
        return clean_prompt, base_refs[:max_refs], []

    # Round-robin allocation guarantees at least 1 photo per Cameo before extra angles
    allocated: List[List[bytes]] = [[] for _ in matched]
    round_idx = 0
    while slots_left > 0:
        progressed = False
        for i, (_, _, imgs) in enumerate(matched):
            if round_idx < len(imgs) and slots_left > 0:
                allocated[i].append(imgs[round_idx])
                slots_left -= 1
                progressed = True
        if not progressed:
            break
        round_idx += 1

    merged_refs = list(base_refs)
    uses_image_tags = category == "video" and model_api_id in (
        "seedance25",
        "seedance2",
        "seedance2Fast",
        "seedance2Mini",
        "seedance",
        "wan30",
        "wan30Prime",
    )

    used_handles: List[str] = []
    extra_notes: List[str] = []

    for i, (h, entry, _) in enumerate(matched):
        imgs = allocated[i]
        if not imgs:
            continue
        start_idx = len(merged_refs) + 1
        merged_refs.extend(imgs)
        end_idx = len(merged_refs)
        used_handles.append(h)

        desc = (entry.get("description") or "").strip()
        pattern = re.compile(rf"(?<![A-Za-zА-Яа-яЁё0-9_@])@{re.escape(h)}\b", re.IGNORECASE)
        mentioned = bool(pattern.search(clean_prompt))

        if uses_image_tags:
            tags = " ".join(f"@Image{idx}" for idx in range(start_idx, end_idx + 1))
            first_repl = f"{tags} ({desc})" if desc else tags
            next_repl = f"@Image{start_idx}"
        else:
            ref_lbl = (
                f"референс-фото {start_idx}"
                if start_idx == end_idx
                else f"референс-фото {start_idx}–{end_idx}"
            )
            first_repl = f"{desc} (с {ref_lbl})" if desc else f"персонаж с {ref_lbl}"
            next_repl = f"персонаж с {ref_lbl}"

        if mentioned:
            done_first = False

            def _repl(_m: re.Match) -> str:
                nonlocal done_first
                if not done_first:
                    done_first = True
                    return first_repl
                return next_repl

            clean_prompt = pattern.sub(_repl, clean_prompt)
        elif desc:
            extra_notes.append(f"{first_repl}")

    if extra_notes:
        joined = "; ".join(extra_notes)
        if clean_prompt:
            clean_prompt = f"{clean_prompt} ({joined})"
        else:
            clean_prompt = joined

    return clean_prompt, merged_refs[:max_refs], used_handles
