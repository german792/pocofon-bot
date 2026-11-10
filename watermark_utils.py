import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
from config import BASE_DIR

logger = logging.getLogger(__name__)

# Exact duration of one full appear -> hold -> disappear cycle in Watermark.webm (125 frames @ 25fps = 5.0s)
WEBM_CYCLE_SEC = 5.0


def get_watermark_src() -> Path:
    """Find the best available watermark file across repository locations."""
    candidates = [
        BASE_DIR / "Watermark.webm",
        BASE_DIR / "watermark.webm",
        BASE_DIR / "static" / "brand" / "watermark.webm",
        BASE_DIR / "Watermark.gif",
        BASE_DIR / "Watermark.GIF",
        BASE_DIR / "watermark.gif",
        BASE_DIR / "static" / "brand" / "green_watermark_crop.png",
        BASE_DIR / "animation.gif.mp4",
    ]
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            return c
    return BASE_DIR / "Watermark.webm"


WATERMARK_SRC = get_watermark_src()


async def get_media_dimensions(file_path: Path) -> Tuple[int, int]:
    """Returns (width, height) of a video or image file using ffprobe, with fallback to PIL."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x",
            str(file_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8.0)
        out = stdout.decode().strip()
        if "x" in out:
            parts = out.split("\n")[0].split("x")
            return int(parts[0]), int(parts[1])
    except Exception as e:
        logger.debug(f"ffprobe dimension check failed for {file_path.name}: {e}")

    try:
        with Image.open(file_path) as im:
            return im.size
    except Exception:
        pass

    return 1280, 720


def calculate_watermark_width(video_w: int, video_h: int) -> int:
    """Calculates watermark width proportional to video/image resolution."""
    # 22% of width for portrait / vertical video, 16% for landscape
    ratio = 0.22 if video_h > video_w else 0.16
    target_w = max(90, int(video_w * ratio))
    if target_w % 2 != 0:
        target_w += 1
    return target_w


def make_username_badge(username: str, height: int = 28) -> Tuple[Path, int, int]:
    """Generates a stylish semi-transparent glass pill badge with the user's @username."""
    clean_user = re.sub(r'<[^>]+>', '', str(username)).strip()
    if clean_user and not clean_user.startswith("@"):
        clean_user = f"@{clean_user}"
    if not clean_user:
        clean_user = "@POCO"

    try:
        font = ImageFont.truetype("arial.ttf", size=max(12, int(height * 0.52)))
    except Exception:
        font = ImageFont.load_default()

    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), clean_user, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    pad_x = 10
    bw = tw + pad_x * 2
    bh = height
    badge = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(badge)
    # Dark glass pill with neon-green border
    d.rounded_rectangle(
        (0, 0, bw - 1, bh - 1),
        radius=bh // 2,
        fill=(10, 20, 16, 200),
        outline=(39, 254, 120, 230),
        width=1
    )
    tx = pad_x
    ty = (bh - th) // 2 - bbox[1]
    d.text((tx, ty), clean_user, fill=(245, 255, 250, 255), font=font)

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


async def apply_watermark(
    input_path: Path,
    output_path: Path,
    username: Optional[str] = None,
    audio_ref_path: Optional[Path] = None
) -> bool:
    """Overlays the animated Poco AI watermark + username badge onto a video,
    cycling corners every time the watermark disappears (every 5.0s).
    Optionally muxes an audio reference onto the final video.
    """
    watermark_src = get_watermark_src()
    if not watermark_src.exists():
        logger.warning(f"Watermark file not found at {watermark_src}, skipping overlay.")
        return False

    vw, vh = await get_media_dimensions(input_path)
    wm_w = calculate_watermark_width(vw, vh)
    ext = watermark_src.suffix.lower()
    is_webm = ext == ".webm"

    c_sec = WEBM_CYCLE_SEC
    cycle_expr_x = f"x='if(mod(floor(t/{c_sec}),2), 24, W-w-24)'"
    cycle_expr_y = f"y='if(between(mod(floor(t/{c_sec}),4), 1, 2), H-h-24, 24)'"

    badge_path: Optional[Path] = None
    badge_w, badge_h = 0, 0
    if username:
        try:
            badge_h = max(22, int(wm_w * 0.16))
            badge_path, badge_w, badge_h = make_username_badge(username, height=badge_h)
        except Exception as e:
            logger.warning(f"Could not generate username badge: {e}")
            badge_path = None

    has_audio_ref = audio_ref_path is not None and audio_ref_path.exists() and audio_ref_path.stat().st_size > 0

    try:
        if is_webm:
            if badge_path:
                # Composite watermark + username badge into one stream [wm_combo]
                filter_str = (
                    f"[1:v]scale={wm_w}:-1,format=yuva420p[wm];"
                    f"[wm]pad=w=max(iw\\,{badge_w}):h=ih+{badge_h + 4}:x=(ow-iw)/2:y=0:color=0x00000000[wm_pad];"
                    f"[wm_pad][2:v]overlay=(W-w)/2:H-h[wm_combo];"
                    f"[0:v][wm_combo]overlay={cycle_expr_x}:{cycle_expr_y}:shortest=1[outv]"
                )
                cmd_primary = [
                    "ffmpeg", "-y",
                    "-i", str(input_path),
                    "-c:v", "libvpx-vp9",
                    "-stream_loop", "-1",
                    "-i", str(watermark_src),
                    "-loop", "1",
                    "-i", str(badge_path),
                ]
                audio_input_idx = 3
            else:
                filter_str = (
                    f"[1:v]scale={wm_w}:-1,format=yuva420p[wm];"
                    f"[0:v][wm]overlay={cycle_expr_x}:{cycle_expr_y}:shortest=1[outv]"
                )
                cmd_primary = [
                    "ffmpeg", "-y",
                    "-i", str(input_path),
                    "-c:v", "libvpx-vp9",
                    "-stream_loop", "-1",
                    "-i", str(watermark_src),
                ]
                audio_input_idx = 2

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
                    "-preset", "veryfast",
                    "-crf", "22",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",
                    str(output_path)
                ])
            else:
                cmd_primary.extend([
                    "-map", "0:a?",
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "22",
                    "-c:a", "copy",
                    str(output_path)
                ])

            try:
                rc, err = await _run_ffmpeg_command(cmd_primary, timeout=120.0)
                if rc == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    logger.info(f"Successfully applied watermark with user badge ({username}) and audio to {output_path}")
                    return True
                logger.warning(f"libvpx-vp9 watermark attempt failed (code {rc}), trying fallback...")
            except Exception as e:
                logger.warning(f"Primary watermark attempt error: {e}")

            # Fallback with colorkey
            if badge_path:
                filter_str_fb = (
                    f"[1:v]colorkey=0x000000:0.15:0.02,scale={wm_w}:-1,format=yuva420p[wm];"
                    f"[wm]pad=w=max(iw\\,{badge_w}):h=ih+{badge_h + 4}:x=(ow-iw)/2:y=0:color=0x00000000[wm_pad];"
                    f"[wm_pad][2:v]overlay=(W-w)/2:H-h[wm_combo];"
                    f"[0:v][wm_combo]overlay={cycle_expr_x}:{cycle_expr_y}:shortest=1[outv]"
                )
                cmd_fb = [
                    "ffmpeg", "-y",
                    "-i", str(input_path),
                    "-stream_loop", "-1",
                    "-i", str(watermark_src),
                    "-loop", "1",
                    "-i", str(badge_path),
                ]
            else:
                filter_str_fb = (
                    f"[1:v]colorkey=0x000000:0.15:0.02,scale={wm_w}:-1,format=yuva420p[wm];"
                    f"[0:v][wm]overlay={cycle_expr_x}:{cycle_expr_y}:shortest=1[outv]"
                )
                cmd_fb = [
                    "ffmpeg", "-y",
                    "-i", str(input_path),
                    "-stream_loop", "-1",
                    "-i", str(watermark_src),
                ]

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
                    "-preset", "veryfast",
                    "-crf", "22",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",
                    str(output_path)
                ])
            else:
                cmd_fb.extend([
                    "-map", "0:a?",
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "22",
                    "-c:a", "copy",
                    str(output_path)
                ])

            rc, err = await _run_ffmpeg_command(cmd_fb, timeout=120.0)
            return rc == 0 and output_path.exists() and output_path.stat().st_size > 0

        else:
            # Fallback for GIF/PNG
            filter_str = (
                f"[1:v]scale={wm_w}:-1,format=yuva420p[wm];"
                f"[0:v][wm]overlay={cycle_expr_x}:{cycle_expr_y}:shortest=1[outv]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-stream_loop", "-1",
                "-i", str(watermark_src),
                "-filter_complex", filter_str,
                "-map", "[outv]",
                "-map", "0:a?",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "22",
                "-c:a", "copy",
                str(output_path)
            ]
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
    username: Optional[str] = None
) -> bool:
    """Overlays the Poco AI watermark + username badge onto a static image file."""
    watermark_src = get_watermark_src()
    if not watermark_src.exists():
        logger.warning(f"Watermark file not found at {watermark_src}, skipping overlay.")
        return False

    vw, vh = await get_media_dimensions(input_path)
    wm_w = calculate_watermark_width(vw, vh)
    ext = watermark_src.suffix.lower()
    is_webm = ext == ".webm"

    badge_path: Optional[Path] = None
    badge_w, badge_h = 0, 0
    if username:
        try:
            badge_h = max(22, int(wm_w * 0.16))
            badge_path, badge_w, badge_h = make_username_badge(username, height=badge_h)
        except Exception as e:
            logger.warning(f"Could not generate username badge for image: {e}")
            badge_path = None

    try:
        if is_webm:
            if badge_path:
                filter_str = (
                    f"[1:v]scale={wm_w}:-1,format=yuva420p[wm];"
                    f"[wm]pad=w=max(iw\\,{badge_w}):h=ih+{badge_h + 4}:x=(ow-iw)/2:y=0:color=0x00000000[wm_pad];"
                    f"[wm_pad][2:v]overlay=(W-w)/2:H-h[wm_combo];"
                    "[0:v][wm_combo]overlay=W-w-24:24[outv]"
                )
                cmd_primary = [
                    "ffmpeg", "-y",
                    "-i", str(input_path),
                    "-c:v", "libvpx-vp9",
                    "-ss", "3.0",
                    "-i", str(watermark_src),
                    "-i", str(badge_path),
                    "-filter_complex", filter_str,
                    "-map", "[outv]",
                    "-frames:v", "1",
                    str(output_path)
                ]
            else:
                filter_str = (
                    f"[1:v]scale={wm_w}:-1,format=yuva420p[wm];"
                    "[0:v][wm]overlay=W-w-24:24[outv]"
                )
                cmd_primary = [
                    "ffmpeg", "-y",
                    "-i", str(input_path),
                    "-c:v", "libvpx-vp9",
                    "-ss", "3.0",
                    "-i", str(watermark_src),
                    "-filter_complex", filter_str,
                    "-map", "[outv]",
                    "-frames:v", "1",
                    str(output_path)
                ]

            try:
                rc, err = await _run_ffmpeg_command(cmd_primary, timeout=60.0)
                if rc == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return True
            except Exception as e:
                logger.warning(f"Primary image watermark attempt error: {e}")

            # Fallback
            if badge_path:
                filter_str_fb = (
                    f"[1:v]colorkey=0x000000:0.15:0.02,scale={wm_w}:-1,format=yuva420p[wm];"
                    f"[wm]pad=w=max(iw\\,{badge_w}):h=ih+{badge_h + 4}:x=(ow-iw)/2:y=0:color=0x00000000[wm_pad];"
                    f"[wm_pad][2:v]overlay=(W-w)/2:H-h[wm_combo];"
                    "[0:v][wm_combo]overlay=W-w-24:24[outv]"
                )
                cmd_fb = [
                    "ffmpeg", "-y",
                    "-i", str(input_path),
                    "-ss", "3.0",
                    "-i", str(watermark_src),
                    "-i", str(badge_path),
                    "-filter_complex", filter_str_fb,
                    "-map", "[outv]",
                    "-frames:v", "1",
                    str(output_path)
                ]
            else:
                filter_str_fb = (
                    f"[1:v]colorkey=0x000000:0.15:0.02,scale={wm_w}:-1,format=yuva420p[wm];"
                    "[0:v][wm]overlay=W-w-24:24[outv]"
                )
                cmd_fb = [
                    "ffmpeg", "-y",
                    "-i", str(input_path),
                    "-ss", "3.0",
                    "-i", str(watermark_src),
                    "-filter_complex", filter_str_fb,
                    "-map", "[outv]",
                    "-frames:v", "1",
                    str(output_path)
                ]

            rc, err = await _run_ffmpeg_command(cmd_fb, timeout=60.0)
            return rc == 0 and output_path.exists() and output_path.stat().st_size > 0

        else:
            filter_str = (
                f"[1:v]colorkey=0x000000:0.15:0.02,scale={wm_w}:-1,format=yuva420p[wm];"
                "[0:v][wm]overlay=W-w-24:24[outv]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-i", str(watermark_src),
                "-filter_complex", filter_str,
                "-map", "[outv]",
                "-frames:v", "1",
                str(output_path)
            ]
            rc, err = await _run_ffmpeg_command(cmd, timeout=60.0)
            return rc == 0 and output_path.exists() and output_path.stat().st_size > 0

    finally:
        if badge_path and badge_path.exists():
            try:
                badge_path.unlink(missing_ok=True)
            except Exception:
                pass
