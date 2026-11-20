"""
POCO AI Bot — Per-User Daily Video Generation Limits
Tracks daily video quota (default: 30 videos/day per user, resets at 00:00 MSK / UTC+3).
Persists to data/daily_limits.json and syncs to GitHub with [skip ci] when GH_PAT is set
so limits survive 5-hour GitHub Actions restarts.
"""

import base64
import json
import logging
import os
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import config

logger = logging.getLogger(__name__)

DAILY_VIDEO_LIMIT = int(os.getenv("DAILY_VIDEO_LIMIT", "30") or "30")
MSK_TZ = timezone(timedelta(hours=3))

DATA_DIR = config.BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LIMITS_FILE = DATA_DIR / "daily_limits.json"

GITHUB_SYNC_TOKEN = os.getenv("GH_PAT") or os.getenv("GITHUB_TOKEN") or ""
GITHUB_REPO = os.getenv("GITHUB_REPOSITORY") or "german792/pocofon-bot2"

_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None
_gh_sha: Optional[str] = None
_gh_loaded = False


def _today_msk() -> str:
    return datetime.now(MSK_TZ).strftime("%Y-%m-%d")


def time_until_reset_text() -> str:
    """Human-readable time left until 00:00 MSK."""
    now = datetime.now(MSK_TZ)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    delta_sec = max(60, int((tomorrow - now).total_seconds()))
    hours = delta_sec // 3600
    minutes = (delta_sec % 3600) // 60
    if hours > 0 and minutes > 0:
        return f"{hours} ч {minutes} мин"
    if hours > 0:
        return f"{hours} ч"
    return f"{minutes} мин"


def _fetch_from_github_sync() -> None:
    global _cache, _gh_sha, _gh_loaded
    if _gh_loaded:
        return
    _gh_loaded = True
    if not GITHUB_SYNC_TOKEN or not GITHUB_REPO:
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/data/daily_limits.json"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {GITHUB_SYNC_TOKEN}",
                "User-Agent": "poco-bot-limits-sync",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            _gh_sha = res.get("sha")
            raw = base64.b64decode(res.get("content", ""))
            gh_data = json.loads(raw.decode("utf-8"))
            if isinstance(gh_data, dict):
                _cache = gh_data
                logger.info(f"Loaded daily_limits.json from GitHub ({GITHUB_REPO})")
    except Exception as e:
        logger.debug(f"GitHub daily_limits fetch note: {e}")


def _sync_to_github_worker(snapshot: Dict[str, Any]) -> None:
    global _gh_sha
    if not GITHUB_SYNC_TOKEN or not GITHUB_REPO:
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/data/daily_limits.json"
        if not _gh_sha:
            try:
                chk_req = urllib.request.Request(
                    url,
                    headers={
                        "Authorization": f"Bearer {GITHUB_SYNC_TOKEN}",
                        "User-Agent": "poco-bot-limits-sync",
                    },
                )
                with urllib.request.urlopen(chk_req, timeout=5.0) as chk_resp:
                    _gh_sha = json.loads(chk_resp.read().decode("utf-8")).get("sha")
            except Exception:
                pass

        content_bytes = json.dumps(snapshot, indent=2, ensure_ascii=False).encode("utf-8")
        payload: Dict[str, Any] = {
            "message": "Update daily_limits.json [skip ci]",
            "content": base64.b64encode(content_bytes).decode("ascii"),
        }
        if _gh_sha:
            payload["sha"] = _gh_sha

        put_req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {GITHUB_SYNC_TOKEN}",
                "User-Agent": "poco-bot-limits-sync",
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        with urllib.request.urlopen(put_req, timeout=7.0) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            _gh_sha = resp_data.get("content", {}).get("sha")
    except Exception as e:
        logger.warning(f"Failed to sync daily_limits.json to GitHub: {e}")


def _load_data_unlocked() -> Dict[str, Any]:
    global _cache
    today = _today_msk()
    if _cache is None:
        _fetch_from_github_sync()
    if _cache is None and LIMITS_FILE.exists():
        try:
            loaded = json.loads(LIMITS_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                _cache = loaded
        except Exception as e:
            logger.warning(f"Failed to read daily_limits.json: {e}")
    if not isinstance(_cache, dict):
        _cache = {"date": today, "videos": {}}
    if _cache.get("date") != today:
        _cache = {"date": today, "videos": {}}
    if not isinstance(_cache.get("videos"), dict):
        _cache["videos"] = {}
    return _cache


def _save_data_unlocked(data: Dict[str, Any]) -> None:
    try:
        tmp = LIMITS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(LIMITS_FILE)
    except Exception as e:
        logger.warning(f"Failed to save daily_limits.json: {e}")
    snapshot = {"date": data.get("date"), "videos": dict(data.get("videos") or {})}
    threading.Thread(target=_sync_to_github_worker, args=(snapshot,), daemon=True).start()


def get_video_quota(user_id: int) -> Dict[str, Any]:
    """Return current user's daily video usage and remaining quota."""
    with _lock:
        data = _load_data_unlocked()
        used = int(data["videos"].get(str(user_id), 0) or 0)
        remaining = max(0, DAILY_VIDEO_LIMIT - used)
        return {
            "used": used,
            "limit": DAILY_VIDEO_LIMIT,
            "remaining": remaining,
            "date": data["date"],
            "reset_in_text": time_until_reset_text(),
        }


def try_consume_video(user_id: int, is_admin: bool = False) -> Tuple[bool, Dict[str, Any]]:
    """Atomically check and consume 1 video from the user's daily quota.
    Admins are tracked for stats but never blocked.
    """
    with _lock:
        data = _load_data_unlocked()
        uid = str(user_id)
        used = int(data["videos"].get(uid, 0) or 0)
        if not is_admin and used >= DAILY_VIDEO_LIMIT:
            return False, {
                "used": used,
                "limit": DAILY_VIDEO_LIMIT,
                "remaining": 0,
                "date": data["date"],
                "reset_in_text": time_until_reset_text(),
            }
        used += 1
        data["videos"][uid] = used
        _save_data_unlocked(data)
        return True, {
            "used": used,
            "limit": DAILY_VIDEO_LIMIT,
            "remaining": max(0, DAILY_VIDEO_LIMIT - used),
            "date": data["date"],
            "reset_in_text": time_until_reset_text(),
        }


def refund_video(user_id: int) -> None:
    """Refund 1 video back to the user's daily quota if generation failed."""
    with _lock:
        data = _load_data_unlocked()
        uid = str(user_id)
        used = int(data["videos"].get(uid, 0) or 0)
        if used > 0:
            data["videos"][uid] = used - 1
            _save_data_unlocked(data)
