import asyncio
import base64
import copy
import html
import io
import json
import logging
import os
import re
import tempfile
import threading
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
from config import BASE_DIR
import image_utils

logger = logging.getLogger(__name__)

# Show the user's @username badge next to the watermark (disabled: only the POCO AI watermark is shown)
SHOW_USERNAME_BADGE = False

# Exact duration of one full appear -> hold -> disappear cycle in all watermark webms (125 frames @ 25fps = 5.0s)
WEBM_CYCLE_SEC = 5.0

DEFAULT_WATERMARK_ID = "poco"
WATERMARK_PREFS_FILE = BASE_DIR / "data" / "watermark_prefs.json"
WATERMARK_PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)

GITHUB_SYNC_TOKEN = os.getenv("GH_PAT") or os.getenv("GITHUB_TOKEN") or ""
GITHUB_REPO = os.getenv("GITHUB_REPOSITORY") or "german792/pocofon-bot2"

WATERMARK_PRESETS: Dict[str, Dict[str, Any]] = {
    "poco": {
        "id": "poco",
        "label": "🟢 Наша (POCO AI)",
        "short": "POCO AI",
        "desc": "Фирменный оранжевый POCO + зелёная сетка",
        "width_scale": 1.0,
        "still_ss": "3.0",
        "candidates": [
            "Watermark.webm",
            "watermark.webm",
            "static/brand/watermark.webm",
            "Watermark.gif",
            "static/brand/green_watermark_crop.png",
        ],
    },
    "tecno": {
        "id": "tecno",
        "label": "🔵 TECNO AI",
        "short": "TECNO AI",
        "desc": "Неоново-синий логотип TECNO AI · POCO AI",
        "width_scale": 1.25,
        "still_ss": "3.5",
        "candidates": [
            "tecno_poco_ai_watermark_v2_alpha.webm",
        ],
    },
    "xp": {
        "id": "xp",
        "label": "🪟 Windows AI",
        "short": "Windows AI",
        "desc": "Ретро-логотип Windows XP AI · POCO AI",
        "width_scale": 1.55,
        "still_ss": "3.5",
        "candidates": [
            "windows_xp_poco_ai_watermark_alpha.webm",
        ],
    },
    "iphone": {
        "id": "iphone",
        "label": "🍎 iPhone AI",
        "short": "iPhone AI",
        "desc": "Логотип Apple iPhone · POCO AI",
        "width_scale": 1.35,
        "still_ss": "3.5",
        "candidates": [
            "iphone_v2_poco_ai_watermark_alpha.webm",
        ],
    },
    "samsung": {
        "id": "samsung",
        "label": "🔷 Samsung AI",
        "short": "Samsung AI",
        "desc": "Синий овал Samsung · POCO AI",
        "width_scale": 1.35,
        "still_ss": "3.5",
        "candidates": [
            "samsung_v2_poco_ai_watermark_alpha.webm",
        ],
    },
    "nokia": {
        "id": "nokia",
        "label": "📞 Nokia 3310",
        "short": "Nokia 3310",
        "desc": "Легендарная Nokia 3310 · POCO AI",
        "width_scale": 1.45,
        "still_ss": "3.5",
        "candidates": [
            "nokia_v2_poco_ai_watermark_alpha.webm",
        ],
    },
    "realme": {
        "id": "realme",
        "label": "💛 realme AI",
        "short": "realme AI",
        "desc": "Фирменный жёлтый realme · POCO AI",
        "width_scale": 1.45,
        "still_ss": "3.5",
        "candidates": [
            "realme_poco_ai_watermark_alpha.webm",
        ],
    },
    "cmf": {
        "id": "cmf",
        "label": "🔴 CMF AI",
        "short": "CMF AI",
        "desc": "Точечный логотип CMF by Nothing · POCO AI",
        "width_scale": 1.45,
        "still_ss": "3.5",
        "candidates": [
            "cmf_v2_poco_ai_watermark_alpha.webm",
        ],
    },
    "sora": {
        "id": "sora",
        "label": "☁️ Sora 2",
        "short": "Sora 2",
        "desc": "Плавающий логотип Sora 2 · работает на всех форматах",
        "width_scale": 1.15,
        "still_ss": "0.2",
        "overlay_mode": "sora",
        "candidates": [
            "sora2_poco_ai_watermark_alpha.webm",
            "Sora 2.mp4",
        ],
    },
}

_prefs_lock = threading.RLock()
_prefs_cache: Optional[Dict[str, Any]] = None
_gh_sha: Optional[str] = None
_gh_loaded: bool = False


def _fetch_prefs_from_github_once() -> None:
    global _prefs_cache, _gh_sha, _gh_loaded
    if _gh_loaded:
        return
    _gh_loaded = True
    if not GITHUB_SYNC_TOKEN or not GITHUB_REPO:
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/data/watermark_prefs.json"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {GITHUB_SYNC_TOKEN}",
                "User-Agent": "poco-bot-wm-sync",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urllib.request.urlopen(req, timeout=6.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            _gh_sha = res.get("sha")
            raw_bytes = base64.b64decode(res.get("content", ""))
            gh_data = json.loads(raw_bytes.decode("utf-8"))
            if isinstance(gh_data, dict):
                _prefs_cache = {
                    "default": gh_data.get("default", DEFAULT_WATERMARK_ID),
                    "users": dict(gh_data.get("users") or {}),
                    "user_badge": dict(gh_data.get("user_badge") or {}),
                }
                WATERMARK_PREFS_FILE.write_text(json.dumps(_prefs_cache, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug(f"GitHub watermark prefs fetch note: {e}")


def _sync_prefs_to_github_worker(snapshot: Dict[str, Any]) -> None:
    global _gh_sha
    if not GITHUB_SYNC_TOKEN or not GITHUB_REPO:
        return
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/data/watermark_prefs.json"
        if not _gh_sha:
            try:
                chk_req = urllib.request.Request(
                    url,
                    headers={
                        "Authorization": f"Bearer {GITHUB_SYNC_TOKEN}",
                        "User-Agent": "poco-bot-wm-sync",
                    },
                )
                with urllib.request.urlopen(chk_req, timeout=5.0) as chk_resp:
                    _gh_sha = json.loads(chk_resp.read().decode("utf-8")).get("sha")
            except Exception:
                pass
        payload_dict: Dict[str, Any] = {
            "message": "bot: update watermark prefs [skip ci]",
            "content": base64.b64encode(json.dumps(snapshot, indent=2, ensure_ascii=False).encode("utf-8")).decode("ascii"),
        }
        if _gh_sha:
            payload_dict["sha"] = _gh_sha
        put_req = urllib.request.Request(
            url,
            data=json.dumps(payload_dict).encode("utf-8"),
            method="PUT",
            headers={
                "Authorization": f"Bearer {GITHUB_SYNC_TOKEN}",
                "User-Agent": "poco-bot-wm-sync",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(put_req, timeout=8.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            _gh_sha = (res.get("content") or {}).get("sha") or _gh_sha
    except Exception as e:
        logger.debug(f"GitHub watermark prefs sync skipped: {e}")


def _load_prefs() -> Dict[str, Any]:
    global _prefs_cache
    with _prefs_lock:
        if _prefs_cache is not None:
            return _prefs_cache
        _fetch_prefs_from_github_once()
        if _prefs_cache is not None:
            return _prefs_cache
        data: Dict[str, Any] = {"default": DEFAULT_WATERMARK_ID, "users": {}, "user_badge": {}}
        if WATERMARK_PREFS_FILE.exists():
            try:
                raw = json.loads(WATERMARK_PREFS_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data["default"] = raw.get("default", DEFAULT_WATERMARK_ID)
                    data["users"] = dict(raw.get("users") or {})
                    data["user_badge"] = dict(raw.get("user_badge") or {})
            except Exception as e:
                logger.warning(f"Failed to read {WATERMARK_PREFS_FILE}: {e}")
        _prefs_cache = data
        return _prefs_cache


def _save_prefs(data: Dict[str, Any]) -> None:
    snapshot = copy.deepcopy(data)
    try:
        tmp = WATERMARK_PREFS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(WATERMARK_PREFS_FILE)
    except Exception as e:
        logger.warning(f"Failed to save watermark prefs: {e}")
    if GITHUB_SYNC_TOKEN and GITHUB_REPO:
        threading.Thread(target=_sync_prefs_to_github_worker, args=(snapshot,), daemon=True).start()


def _resolve_preset_file(preset_id: str) -> Optional[Path]:
    preset = WATERMARK_PRESETS.get(preset_id)
    if not preset:
        return None
    for rel in preset["candidates"]:
        p = BASE_DIR / rel
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def list_available_watermarks() -> List[Dict[str, Any]]:
    """Return ordered list of watermark presets whose media file exists on disk."""
    out: List[Dict[str, Any]] = []
    for pid, preset in WATERMARK_PRESETS.items():
        if _resolve_preset_file(pid) is not None:
            out.append(preset)
    return out


def get_default_watermark_id() -> str:
    data = _load_prefs()
    pid = str(data.get("default") or DEFAULT_WATERMARK_ID)
    if _resolve_preset_file(pid) is not None:
        return pid
    return DEFAULT_WATERMARK_ID


def set_default_watermark_id(watermark_id: str) -> str:
    if watermark_id not in WATERMARK_PRESETS or _resolve_preset_file(watermark_id) is None:
        watermark_id = DEFAULT_WATERMARK_ID
    with _prefs_lock:
        data = _load_prefs()
        data["default"] = watermark_id
        _save_prefs(data)
    return watermark_id


def get_user_watermark_id(user_id: Optional[int] = None) -> str:
    data = _load_prefs()
    if user_id is not None:
        u_choice = (data.get("users") or {}).get(str(user_id))
        if u_choice in WATERMARK_PRESETS and _resolve_preset_file(u_choice) is not None:
            return u_choice
    return get_default_watermark_id()


def set_user_watermark_id(user_id: int, watermark_id: str) -> str:
    if watermark_id not in WATERMARK_PRESETS or _resolve_preset_file(watermark_id) is None:
        watermark_id = DEFAULT_WATERMARK_ID
    with _prefs_lock:
        data = _load_prefs()
        data.setdefault("users", {})[str(user_id)] = watermark_id
        _save_prefs(data)
    return watermark_id


def get_user_watermark_username_enabled(user_id: Optional[int] = None) -> bool:
    if user_id is None:
        return False
    data = _load_prefs()
    return bool((data.get("user_badge") or {}).get(str(user_id), False))


def set_user_watermark_username_enabled(user_id: int, enabled: bool) -> bool:
    flag = bool(enabled)
    with _prefs_lock:
        data = _load_prefs()
        data.setdefault("user_badge", {})[str(user_id)] = flag
        _save_prefs(data)
    return flag


def resolve_watermark_id(watermark_id: Optional[str] = None, user_id: Optional[int] = None) -> str:
    if watermark_id and watermark_id in WATERMARK_PRESETS and _resolve_preset_file(watermark_id) is not None:
        return watermark_id
    return get_user_watermark_id(user_id)


def get_watermark_info(watermark_id: Optional[str] = None, user_id: Optional[int] = None) -> Dict[str, Any]:
    pid = resolve_watermark_id(watermark_id, user_id)
    return WATERMARK_PRESETS.get(pid, WATERMARK_PRESETS[DEFAULT_WATERMARK_ID])


def get_watermark_src(watermark_id: Optional[str] = None, user_id: Optional[int] = None) -> Path:
    """Find the active watermark file based on user selection or global fallback."""
    pid = resolve_watermark_id(watermark_id, user_id)
    found = _resolve_preset_file(pid)
    if found is not None:
        return found
    for fallback_id in WATERMARK_PRESETS:
        alt = _resolve_preset_file(fallback_id)
        if alt is not None:
            return alt
    return BASE_DIR / "Watermark.webm"


WATERMARK_SRC = get_watermark_src()


def _load_ui_font(size: int, bold: bool = False):
    """Load a crisp scalable TTF font across Windows and Ubuntu CI hosts."""
    candidates = (
        [
            "arialbd.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]
        if bold
        else [
            "arial.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        ]
    )
    for font_path in candidates:
        try:
            return ImageFont.truetype(font_path, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


async def render_watermark_preview_card() -> Optional[bytes]:
    """Render a side-by-side preview PNG of all available watermark presets."""
    presets = list_available_watermarks()
    if not presets:
        return None
    card_w, row_h = 760, 148
    canvas = Image.new("RGB", (card_w, max(row_h, len(presets) * row_h + 16)), (24, 28, 36))
    draw = ImageDraw.Draw(canvas)
    font_title = _load_ui_font(22, bold=True)
    font_sub = _load_ui_font(15, bold=False)

    y = 12
    for idx, preset in enumerate(presets, start=1):
        src = _resolve_preset_file(preset["id"])
        if not src:
            continue
        draw.rounded_rectangle((16, y, card_w - 16, y + row_h - 12), radius=12, fill=(36, 41, 52), outline=(65, 75, 95), width=1)
        try:
            decode_args = ["-c:v", "libvpx-vp9"] if src.suffix.lower() == ".webm" else []
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-v", "error", *decode_args,
                "-i", str(src),
                "-ss", preset.get("still_ss", "3.0"),
                "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            if proc.returncode == 0 and out:
                with Image.open(io.BytesIO(out)) as im:
                    rgba = im.convert("RGBA")
                    rgba.thumbnail((230, 114), Image.Resampling.LANCZOS)
                    px = 34 + (230 - rgba.width) // 2
                    py = y + (row_h - 12 - rgba.height) // 2
                    canvas.paste(rgba, (px, py), rgba)
        except Exception:
            pass
        title = f"{idx}. {preset['short']}"
        draw.text((295, y + 34), title, fill=(245, 248, 255), font=font_title)
        draw.text((295, y + 68), preset.get("desc", ""), fill=(165, 178, 200), font=font_sub)
        y += row_h

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


async def get_media_dimensions(file_path: Path) -> Tuple[int, int]:
    """Returns display (width, height) of a video or image file using ffprobe, with fallback to PIL."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height:stream_tags=rotate:stream_side_data=rotation",
            "-of", "json",
            str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8.0)
        info = json.loads(stdout.decode("utf-8", "ignore").strip() or "{}")
        streams = info.get("streams") or []
        if streams:
            st = streams[0]
            vw = int(st.get("width") or 0)
            vh = int(st.get("height") or 0)
            rot_val = (st.get("tags") or {}).get("rotate")
            if rot_val is None:
                for sd in st.get("side_data_list") or []:
                    if sd.get("rotation") is not None:
                        rot_val = sd.get("rotation")
                        break
            if rot_val is not None:
                try:
                    if abs(int(round(float(rot_val)))) % 180 == 90:
                        vw, vh = vh, vw
                except Exception:
                    pass
            if vw > 0 and vh > 0:
                return vw, vh
    except Exception as e:
        logger.debug(f"ffprobe dimension check failed for {file_path.name}: {e}")

    try:
        with Image.open(file_path) as im:
            return im.size
    except Exception:
        pass

    return 1280, 720


def calculate_watermark_width(video_w: int, video_h: int, width_scale: float = 1.0) -> int:
    """Calculates watermark width proportional to video/image resolution and watermark aspect."""
    # 22% of width for portrait / vertical video, 16% for landscape; scaled for wider banners
    base_ratio = 0.22 if video_h > video_w else 0.16
    max_ratio = 0.45 if video_h > video_w else 0.34
    ratio = min(max_ratio, base_ratio * max(0.5, float(width_scale or 1.0)))
    target_w = max(90, int(video_w * ratio))
    if target_w % 2 != 0:
        target_w += 1
    return target_w


def calculate_badge_height(video_w: int, video_h: int, wm_w: int) -> int:
    """Compute prominent badge height scaled cleanly for 480p/720p/1080p/4K videos & images."""
    return max(36, min(88, int(min(video_w, video_h) * 0.075), int(wm_w * 0.42)))


def make_username_badge(
    username: str,
    height: int = 48,
    max_width: Optional[int] = None,
) -> Tuple[Path, int, int]:
    """Generate a large, high-contrast glass pill badge with the user's @username."""
    clean_user = html.unescape(re.sub(r"<[^>]+>", "", str(username or ""))).strip()
    if clean_user and not clean_user.startswith("@") and " " not in clean_user:
        clean_user = f"@{clean_user}"
    if not clean_user:
        clean_user = "@POCO_AI"

    bh = max(28, int(height))
    font_size = max(16, int(bh * 0.58))
    pad_x = max(14, int(bh * 0.38))

    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    font = _load_ui_font(font_size, bold=True)
    bbox = draw.textbbox((0, 0), clean_user, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    if max_width and max_width > 60:
        while tw + pad_x * 2 > max_width and font_size > 14:
            font_size = max(14, font_size - 2)
            font = _load_ui_font(font_size, bold=True)
            bbox = draw.textbbox((0, 0), clean_user, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]

    bw = tw + pad_x * 2
    bh = max(bh, th + max(14, int(font_size * 0.52)))
    badge = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(badge)
    border_w = max(2, bh // 20)
    d.rounded_rectangle(
        (0, 0, bw - 1, bh - 1),
        radius=bh // 2,
        fill=(10, 16, 20, 222),
        outline=(39, 254, 120, 235),
        width=border_w,
    )
    tx = (bw - tw) // 2 - bbox[0]
    ty = (bh - th) // 2 - bbox[1]
    d.text((tx, ty), clean_user, fill=(255, 255, 255, 255), font=font)

    badge_path = BASE_DIR / f"badge_{uuid.uuid4().hex[:8]}.png"
    badge.save(badge_path)
    return badge_path, bw, bh


async def _run_ffmpeg_command(cmd: list[str], timeout: float = 120.0) -> Tuple[int, str]:
    """Helper to run ffmpeg subprocess and capture return code & stderr."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    err_text = stderr.decode("utf-8", errors="ignore")
    return proc.returncode, err_text


def _should_render_username_badge(
    username: Optional[str],
    user_id: Optional[int],
    show_username: Optional[bool],
) -> bool:
    if not username:
        return False
    if SHOW_USERNAME_BADGE:
        return True
    if show_username is not None:
        return bool(show_username)
    return get_user_watermark_username_enabled(user_id)


def _badge_combo_tail(
    base_label: str,
    pos_expr: str,
    badge_w: int,
    badge_h: int,
    shortest: bool,
) -> str:
    short_opt = ":shortest=1" if shortest else ""
    if badge_w > 0 and badge_h > 0:
        return (
            f"[wm]pad=w=max(iw\\,{badge_w}):h=ih+{badge_h + 6}:x=(ow-iw)/2:y=0:color=0x00000000[wm_pad];"
            f"[wm_pad][2:v]overlay=(W-w)/2:H-h[wm_combo];"
            f"[{base_label}][wm_combo]overlay={pos_expr}{short_opt}[outv]"
        )
    return f"[{base_label}][wm]overlay={pos_expr}{short_opt}[outv]"


async def apply_watermark(
    input_path: Path,
    output_path: Path,
    username: Optional[str] = None,
    audio_ref_path: Optional[Path] = None,
    target_duration: Optional[int] = None,
    watermark_id: Optional[str] = None,
    user_id: Optional[int] = None,
    show_username: Optional[bool] = None,
) -> bool:
    """Overlays the animated watermark + optional username badge onto a video,
    cycling corners every time the watermark disappears (every 5.0s).
    Optionally muxes an audio reference onto the final video.
    """
    preset = get_watermark_info(watermark_id=watermark_id, user_id=user_id)
    watermark_src = get_watermark_src(watermark_id=watermark_id, user_id=user_id)
    if not watermark_src.exists():
        logger.warning(f"Watermark file not found at {watermark_src}, skipping overlay.")
        return False

    vw, vh = await get_media_dimensions(input_path)
    wm_w = calculate_watermark_width(vw, vh, width_scale=float(preset.get("width_scale", 1.0)))
    ext = watermark_src.suffix.lower()
    is_webm = ext == ".webm"
    is_sora = preset.get("overlay_mode") == "sora"

    if is_sora:
        mx = max(18, min(56, int(vw * 0.045)))
        my = max(18, min(56, int(vh * 0.045)))
        mid_right = "gte(mod(t,10),2)*lt(mod(t,10),4.5)+gte(mod(t,10),9)"
        bot_left = "gte(mod(t,10),4.5)*lt(mod(t,10),6.5)"
        cycle_expr_x = f"if({mid_right}, W-w-{mx}, {mx})"
        cycle_expr_y = f"if({mid_right}, trunc((H-h)*0.48), if({bot_left}, H-h-{my}, {my}))"
    else:
        c_sec = WEBM_CYCLE_SEC
        cycle_expr_x = f"if(mod(floor(t/{c_sec}),2), 24, W-w-24)"
        cycle_expr_y = f"if(between(mod(floor(t/{c_sec}),4), 1, 2), H-h-24, 24)"

    base_prep = "[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2[base];"
    non_webm_prep = (
        f"[1:v]crop=132:52:28:84,chromakey=0x05ba06:0.22:0.06,scale={wm_w}:-1,format=yuva420p[wm];"
        if is_sora and not is_webm
        else f"[1:v]scale={wm_w}:-1,format=yuva420p[wm];"
    )

    badge_path: Optional[Path] = None
    badge_w, badge_h = 0, 0
    if _should_render_username_badge(username, user_id, show_username):
        try:
            target_bh = calculate_badge_height(vw, vh, wm_w)
            max_bw = max(120, min(int(vw * 0.54), vw - 48))
            badge_path, badge_w, badge_h = make_username_badge(
                username or "", height=target_bh, max_width=max_bw
            )
        except Exception as e:
            logger.warning(f"Could not generate username badge: {e}")
            badge_path = None
            badge_w, badge_h = 0, 0

    has_audio_ref = audio_ref_path is not None and audio_ref_path.exists() and audio_ref_path.stat().st_size > 0
    dur_args = ["-t", str(target_duration)] if target_duration and target_duration > 0 else []

    video_pos_expr = f"x='{cycle_expr_x}':y='{cycle_expr_y}'"
    try:
        if is_webm:
            audio_input_idx = 3 if badge_path else 2
            filter_str = (
                f"{base_prep}"
                f"[1:v]scale={wm_w}:-1,format=yuva420p[wm];"
                f"{_badge_combo_tail('base', video_pos_expr, badge_w, badge_h, shortest=True)}"
            )
            cmd_primary = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-c:v", "libvpx-vp9",
                "-stream_loop", "-1",
                "-i", str(watermark_src),
            ]
            if badge_path:
                cmd_primary.extend(["-loop", "1", "-i", str(badge_path)])

            if has_audio_ref:
                cmd_primary.extend(["-stream_loop", "-1", "-i", str(audio_ref_path)])

            cmd_primary.extend([
                "-filter_complex", filter_str,
                "-map", "[outv]",
            ])

            if has_audio_ref:
                cmd_primary.extend([
                    "-map", f"{audio_input_idx}:a",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", "veryfast",
                    "-crf", "22",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",
                    *dur_args,
                    str(output_path)
                ])
            else:
                cmd_primary.extend([
                    "-map", "0:a?",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", "veryfast",
                    "-crf", "22",
                    "-c:a", "copy",
                    *dur_args,
                    str(output_path)
                ])

            try:
                rc, err = await _run_ffmpeg_command(cmd_primary, timeout=120.0)
                if rc == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    logger.info(f"Successfully applied watermark with user badge ({username if badge_path else None}) and audio to {output_path}")
                    return True
                logger.warning(f"libvpx-vp9 watermark attempt failed (code {rc}), trying fallback...")
            except Exception as e:
                logger.warning(f"Primary watermark attempt error: {e}")

            # Fallback with colorkey / chromakey
            fb_key = "chromakey=0x05ba06:0.22:0.06" if is_sora else "colorkey=0x000000:0.15:0.02"
            filter_str_fb = (
                f"{base_prep}"
                f"[1:v]{fb_key},scale={wm_w}:-1,format=yuva420p[wm];"
                f"{_badge_combo_tail('base', video_pos_expr, badge_w, badge_h, shortest=True)}"
            )
            cmd_fb = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-stream_loop", "-1",
                "-i", str(watermark_src),
            ]
            if badge_path:
                cmd_fb.extend(["-loop", "1", "-i", str(badge_path)])

            if has_audio_ref:
                cmd_fb.extend(["-stream_loop", "-1", "-i", str(audio_ref_path)])

            cmd_fb.extend([
                "-filter_complex", filter_str_fb,
                "-map", "[outv]",
            ])

            if has_audio_ref:
                cmd_fb.extend([
                    "-map", f"{audio_input_idx}:a",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", "veryfast",
                    "-crf", "22",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",
                    *dur_args,
                    str(output_path)
                ])
            else:
                cmd_fb.extend([
                    "-map", "0:a?",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", "veryfast",
                    "-crf", "22",
                    "-c:a", "copy",
                    *dur_args,
                    str(output_path)
                ])

            rc, err = await _run_ffmpeg_command(cmd_fb, timeout=120.0)
            return rc == 0 and output_path.exists() and output_path.stat().st_size > 0

        else:
            # Fallback for MP4/GIF/PNG watermarks
            audio_input_idx = 3 if badge_path else 2
            filter_str = (
                f"{base_prep}"
                f"{non_webm_prep}"
                f"{_badge_combo_tail('base', video_pos_expr, badge_w, badge_h, shortest=True)}"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-stream_loop", "-1",
                "-i", str(watermark_src),
            ]
            if badge_path:
                cmd.extend(["-loop", "1", "-i", str(badge_path)])
            if has_audio_ref:
                cmd.extend([
                    "-stream_loop", "-1", "-i", str(audio_ref_path),
                    "-filter_complex", filter_str,
                    "-map", "[outv]",
                    "-map", f"{audio_input_idx}:a",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "22",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", *dur_args, str(output_path),
                ])
            else:
                cmd.extend([
                    "-filter_complex", filter_str,
                    "-map", "[outv]",
                    "-map", "0:a?",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "22",
                    "-c:a", "copy", *dur_args, str(output_path),
                ])
            rc, err = await _run_ffmpeg_command(cmd, timeout=120.0)
            return rc == 0 and output_path.exists() and output_path.stat().st_size > 0

    finally:
        if badge_path and badge_path.exists():
            try:
                badge_path.unlink(missing_ok=True)
            except Exception:
                pass


async def apply_watermark_image(
    input_path: Path,
    output_path: Path,
    username: Optional[str] = None,
    watermark_id: Optional[str] = None,
    user_id: Optional[int] = None,
    show_username: Optional[bool] = None,
) -> bool:
    """Overlays the selected watermark + optional username badge onto a static image file."""
    preset = get_watermark_info(watermark_id=watermark_id, user_id=user_id)
    watermark_src = get_watermark_src(watermark_id=watermark_id, user_id=user_id)
    if not watermark_src.exists():
        logger.warning(f"Watermark file not found at {watermark_src}, skipping overlay.")
        return False

    vw, vh = await get_media_dimensions(input_path)
    wm_w = calculate_watermark_width(vw, vh, width_scale=float(preset.get("width_scale", 1.0)))
    still_ss = str(preset.get("still_ss", "3.0"))
    ext = watermark_src.suffix.lower()
    is_webm = ext == ".webm"
    is_sora = preset.get("overlay_mode") == "sora"
    if is_sora:
        mx = max(18, min(56, int(vw * 0.045)))
        my = max(18, min(56, int(vh * 0.045)))
        img_overlay_pos = f"{mx}:{my}"
    else:
        img_overlay_pos = "W-w-24:24"

    badge_path: Optional[Path] = None
    badge_w, badge_h = 0, 0
    if _should_render_username_badge(username, user_id, show_username):
        try:
            target_bh = calculate_badge_height(vw, vh, wm_w)
            max_bw = max(120, min(int(vw * 0.54), vw - 48))
            badge_path, badge_w, badge_h = make_username_badge(
                username or "", height=target_bh, max_width=max_bw
            )
        except Exception as e:
            logger.warning(f"Could not generate username badge for image: {e}")
            badge_path = None
            badge_w, badge_h = 0, 0

    try:
        still_trim = f"trim=start={still_ss},setpts=PTS-STARTPTS,trim=end_frame=1,"
        if is_webm:
            filter_str = (
                f"[1:v]{still_trim}scale={wm_w}:-1,format=yuva420p[wm];"
                f"{_badge_combo_tail('0:v', img_overlay_pos, badge_w, badge_h, shortest=False)}"
            )
            cmd_primary = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-c:v", "libvpx-vp9",
                "-i", str(watermark_src),
            ]
            if badge_path:
                cmd_primary.extend(["-i", str(badge_path)])
            cmd_primary.extend(["-filter_complex", filter_str, "-map", "[outv]", "-frames:v", "1", str(output_path)])

            try:
                rc, err = await _run_ffmpeg_command(cmd_primary, timeout=60.0)
                if rc == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return True
            except Exception as e:
                logger.warning(f"Primary image watermark attempt error: {e}")

            # Fallback
            fb_key = "chromakey=0x05ba06:0.22:0.06" if is_sora else "colorkey=0x000000:0.15:0.02"
            filter_str_fb = (
                f"[1:v]{still_trim}{fb_key},scale={wm_w}:-1,format=yuva420p[wm];"
                f"{_badge_combo_tail('0:v', img_overlay_pos, badge_w, badge_h, shortest=False)}"
            )
            cmd_fb = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-i", str(watermark_src),
            ]
            if badge_path:
                cmd_fb.extend(["-i", str(badge_path)])
            cmd_fb.extend(["-filter_complex", filter_str_fb, "-map", "[outv]", "-frames:v", "1", str(output_path)])

            rc, err = await _run_ffmpeg_command(cmd_fb, timeout=60.0)
            return rc == 0 and output_path.exists() and output_path.stat().st_size > 0

        else:
            non_webm_img_prep = (
                f"[1:v]crop=132:52:28:84,chromakey=0x05ba06:0.22:0.06,scale={wm_w}:-1,format=yuva420p[wm];"
                if is_sora
                else f"[1:v]colorkey=0x000000:0.15:0.02,scale={wm_w}:-1,format=yuva420p[wm];"
            )
            filter_str = (
                f"{non_webm_img_prep}"
                f"{_badge_combo_tail('0:v', img_overlay_pos, badge_w, badge_h, shortest=False)}"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-i", str(watermark_src),
            ]
            if badge_path:
                cmd.extend(["-i", str(badge_path)])
            cmd.extend([
                "-filter_complex", filter_str,
                "-map", "[outv]",
                "-frames:v", "1",
                str(output_path)
            ])
            rc, err = await _run_ffmpeg_command(cmd, timeout=60.0)
            return rc == 0 and output_path.exists() and output_path.stat().st_size > 0

    finally:
        if badge_path and badge_path.exists():
            try:
                badge_path.unlink(missing_ok=True)
            except Exception:
                pass


async def overlay_grid_video(
    video_bytes: bytes,
    rows: int = 3,
    cols: int = 3,
    thickness_mode: str = "thick",
    color: str = "contrast",
    show_labels: bool = False,
) -> bytes:
    """Overlay an adaptive high-contrast grid across all frames of a video while keeping audio."""
    if not video_bytes:
        return video_bytes
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        in_path = tmp_dir / "in.mp4"
        grid_path = tmp_dir / "grid.png"
        out_path = tmp_dir / "out.mp4"
        in_path.write_bytes(video_bytes)

        vw, vh = await get_media_dimensions(in_path)
        ew = max(2, (vw // 2) * 2)
        eh = max(2, (vh // 2) * 2)
        grid_png = image_utils.render_grid_overlay_png(
            ew,
            eh,
            rows=rows,
            cols=cols,
            thickness_mode=thickness_mode,
            color=color,
            show_labels=show_labels,
        )
        grid_path.write_bytes(grid_png)

        filter_str = (
            "[0:v]setpts=PTS-STARTPTS,scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1[base];"
            "[1:v]format=rgba,setsar=1[grid];"
            "[base][grid]overlay=0:0:shortest=1[outv]"
        )
        base_cmd = [
            "ffmpeg", "-y",
            "-i", str(in_path),
            "-loop", "1",
            "-i", str(grid_path),
            "-filter_complex", filter_str,
            "-map", "[outv]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "veryfast",
            "-crf", "21",
        ]
        rc, err = await _run_ffmpeg_command([*base_cmd, "-c:a", "copy", str(out_path)], timeout=180.0)
        if rc != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            # Retry re-encoding audio to AAC in case container had Opus/Vorbis/PCM audio
            rc, err = await _run_ffmpeg_command(
                [*base_cmd, "-c:a", "aac", "-b:a", "128k", str(out_path)],
                timeout=180.0,
            )
        if rc != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg video grid overlay failed ({rc}): {err[-300:]}")
        return out_path.read_bytes()


async def extract_frame_from_video(video_bytes: bytes) -> Optional[bytes]:
    """Extract the first high-res frame from video bytes using ffmpeg."""
    if not video_bytes:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", "pipe:0",
            "-vframes", "1",
            "-f", "image2",
            "-q:v", "2",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(input=video_bytes), timeout=25.0)
        if proc.returncode == 0 and out:
            return out
    except Exception:
        pass

    # Robust fallback via temp file
    temp_in = BASE_DIR / f"tmp_in_{uuid.uuid4().hex[:8]}.mp4"
    temp_out = BASE_DIR / f"tmp_out_{uuid.uuid4().hex[:8]}.jpg"
    try:
        temp_in.write_bytes(video_bytes)
        cmd = ["ffmpeg", "-y", "-i", str(temp_in), "-vframes", "1", "-q:v", "2", str(temp_out)]
        rc, _ = await _run_ffmpeg_command(cmd, timeout=30.0)
        if rc == 0 and temp_out.exists() and temp_out.stat().st_size > 0:
            return temp_out.read_bytes()
    except Exception as e:
        logger.debug(f"Temp file frame extraction failed: {e}")
    finally:
        temp_in.unlink(missing_ok=True)
        temp_out.unlink(missing_ok=True)
    return None


async def extract_audio_from_video(video_bytes: bytes) -> Optional[bytes]:
    """Extract audio track from video bytes using ffmpeg."""
    if not video_bytes:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", "pipe:0",
            "-vn",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            "-f", "mp3",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(input=video_bytes), timeout=25.0)
        if proc.returncode == 0 and out and len(out) > 500:
            return out
    except Exception:
        pass

    # Robust fallback via temp file
    temp_in = BASE_DIR / f"tmp_in_{uuid.uuid4().hex[:8]}.mp4"
    temp_out = BASE_DIR / f"tmp_out_{uuid.uuid4().hex[:8]}.mp3"
    try:
        temp_in.write_bytes(video_bytes)
        cmd = ["ffmpeg", "-y", "-i", str(temp_in), "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(temp_out)]
        rc, _ = await _run_ffmpeg_command(cmd, timeout=30.0)
        if rc == 0 and temp_out.exists() and temp_out.stat().st_size > 500:
            return temp_out.read_bytes()
    except Exception as e:
        logger.debug(f"Temp file audio extraction failed: {e}")
    finally:
        temp_in.unlink(missing_ok=True)
        temp_out.unlink(missing_ok=True)
    return None

