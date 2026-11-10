import asyncio
import logging
from pathlib import Path
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


async def get_media_dimensions(file_path: Path) -> tuple[int, int]:
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
        from PIL import Image
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


async def apply_watermark(input_path: Path, output_path: Path) -> bool:
    """Overlays the animated Poco AI watermark onto a video, cycling corners every time the watermark disappears.
    For Watermark.webm (5.0s clip with built-in appear & disappear at the end of the clip):
      - Loops infinitely (-stream_loop -1)
      - Switches to a new corner at the end of every 5.0s cycle right when the watermark disappears:
        0..5s: Top-Right (TR) -> 5..10s: Bottom-Left (BL) -> 10..15s: Bottom-Right (BR) -> 15..20s: Top-Left (TL), repeating cyclically.
    Returns True if successful, False if failed.
    """
    watermark_src = get_watermark_src()
    if not watermark_src.exists():
        logger.warning(f"Watermark file not found at {watermark_src}, skipping overlay.")
        return False

    vw, vh = await get_media_dimensions(input_path)
    wm_w = calculate_watermark_width(vw, vh)
    ext = watermark_src.suffix.lower()
    is_webm = ext == ".webm"
    is_gif = ext == ".gif"

    if is_webm:
        c_sec = WEBM_CYCLE_SEC
        filter_str = (
            f"[1:v]scale={wm_w}:-1,format=yuva420p[wm];"
            f"[0:v][wm]overlay="
            f"x='if(mod(floor(t/{c_sec}),2), 24, W-w-24)':"
            f"y='if(between(mod(floor(t/{c_sec}),4), 1, 2), H-h-24, 24)':"
            "shortest=1[outv]"
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
    elif is_gif:
        v_expr = "clip(min(mod(t,2.2)/0.35, (2.2-mod(t,2.2))/0.35), 0, 1)"
        s_expr = f"(3 - 2*{v_expr})*{v_expr}*{v_expr}"
        filter_str = (
            f"[1:v]scale={wm_w}:-1[wm_base];"
            f"[wm_base]scale=w='2*max(1, trunc(iw*{s_expr}/2))':h='ow':eval=frame[wm_pop];"
            "[0:v][wm_pop]overlay="
            "x='if(mod(floor(t/2.2),2), 24, W-w-24)':"
            "y='if(between(mod(floor(t/2.2),4), 1, 2), H-h-24, 24)':"
            f"enable='gt({v_expr}, 0.02)':"
            "shortest=1[outv]"
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
    else:
        v_expr = "clip(min(mod(t,2.2)/0.35, (2.2-mod(t,2.2))/0.35), 0, 1)"
        s_expr = f"(3 - 2*{v_expr})*{v_expr}*{v_expr}"
        filter_str = (
            f"[1:v]colorkey=0x000000:0.12:0.02,scale={wm_w}:-1[wm_base];"
            f"[wm_base]scale=w='2*max(1, trunc(iw*{s_expr}/2))':h='ow':eval=frame[wm_pop];"
            "[0:v][wm_pop]overlay="
            "x='if(mod(floor(t/2.2),2), 24, W-w-24)':"
            "y='if(between(mod(floor(t/2.2),4), 1, 2), H-h-24, 24)':"
            f"enable='gt({v_expr}, 0.02)':"
            "shortest=1[outv]"
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

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            logger.info(f"Successfully applied cyclic corner watermark ({watermark_src.name}, w={wm_w}) to {output_path}")
            return True
        else:
            err_msg = stderr.decode("utf-8", errors="ignore")
            logger.error(f"FFmpeg watermark failed (code {proc.returncode}): {err_msg[:400]}")
            return False
    except Exception as e:
        logger.error(f"Error applying watermark: {e}", exc_info=True)
        return False


async def apply_watermark_image(input_path: Path, output_path: Path) -> bool:
    """Overlays the Poco AI watermark onto a static image file."""
    watermark_src = get_watermark_src()
    if not watermark_src.exists():
        logger.warning(f"Watermark file not found at {watermark_src}, skipping overlay.")
        return False

    vw, vh = await get_media_dimensions(input_path)
    wm_w = calculate_watermark_width(vw, vh)
    ext = watermark_src.suffix.lower()
    is_webm = ext == ".webm"
    is_gif = ext == ".gif"

    if is_webm:
        # Seek to t=3.0s of Watermark.webm where the watermark is at 100% full visibility
        filter_str = (
            f"[1:v]scale={wm_w}:-1,format=yuva420p[wm];"
            "[0:v][wm]overlay=W-w-24:24[outv]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-ss", "3.0",
            "-i", str(watermark_src),
            "-filter_complex", filter_str,
            "-map", "[outv]",
            "-frames:v", "1",
            str(output_path)
        ]
    elif is_gif:
        filter_str = (
            f"[1:v]scale={wm_w}:-1[wm];"
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
    else:
        filter_str = (
            f"[1:v]colorkey=0x000000:0.12:0.02,scale={wm_w}:-1[wm];"
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

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            logger.info(f"Successfully applied watermark ({watermark_src.name}, w={wm_w}) to image {output_path}")
            return True
        else:
            err_msg = stderr.decode("utf-8", errors="ignore")
            logger.error(f"FFmpeg watermark failed for image (code {proc.returncode}): {err_msg[:400]}")
            return False
    except Exception as e:
        logger.error(f"Error applying watermark to image: {e}", exc_info=True)
        return False
