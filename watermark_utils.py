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


async def _run_ffmpeg_command(cmd: list[str], timeout: float = 120.0) -> tuple[int, str]:
    """Helper to run ffmpeg subprocess and capture return code & stderr."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    err_text = stderr.decode("utf-8", errors="ignore")
    return proc.returncode, err_text


async def apply_watermark(input_path: Path, output_path: Path) -> bool:
    """Overlays the animated Poco AI watermark onto a video, cycling corners every time the watermark disappears.
    For Watermark.webm:
      - Uses libvpx-vp9 decoder to extract true embedded alpha channel (yuva420p) with no background.
      - Fallback to colorkey filter if libvpx-vp9 decoder is not compiled in.
      - Loops infinitely (-stream_loop -1)
      - Cycles corners every 5.0s (TR -> BL -> BR -> TL).
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

    c_sec = WEBM_CYCLE_SEC
    cycle_expr_x = f"x='if(mod(floor(t/{c_sec}),2), 24, W-w-24)'"
    cycle_expr_y = f"y='if(between(mod(floor(t/{c_sec}),4), 1, 2), H-h-24, 24)'"

    if is_webm:
        # Primary method: libvpx-vp9 decoder with native alpha channel
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
            rc, err = await _run_ffmpeg_command(cmd_primary, timeout=120.0)
            if rc == 0 and output_path.exists() and output_path.stat().st_size > 0:
                logger.info(f"Successfully applied alpha WebM watermark to {output_path}")
                return True
            logger.warning(f"libvpx-vp9 primary attempt failed (code {rc}), trying colorkey fallback...")
        except Exception as e:
            logger.warning(f"libvpx-vp9 overlay raised exception: {e}, falling back to colorkey...")

        # Fallback method: colorkey out any black background without libvpx-vp9 decoder
        filter_str_fallback = (
            f"[1:v]colorkey=0x000000:0.15:0.02,scale={wm_w}:-1,format=yuva420p[wm];"
            f"[0:v][wm]overlay={cycle_expr_x}:{cycle_expr_y}:shortest=1[outv]"
        )
        cmd_fallback = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-stream_loop", "-1",
            "-i", str(watermark_src),
            "-filter_complex", filter_str_fallback,
            "-map", "[outv]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
            "-c:a", "copy",
            str(output_path)
        ]
        try:
            rc, err = await _run_ffmpeg_command(cmd_fallback, timeout=120.0)
            if rc == 0 and output_path.exists() and output_path.stat().st_size > 0:
                logger.info(f"Successfully applied colorkey WebM watermark to {output_path}")
                return True
            logger.error(f"FFmpeg colorkey watermark fallback failed (code {rc}): {err[:400]}")
            return False
        except Exception as e:
            logger.error(f"Error in colorkey watermark fallback: {e}", exc_info=True)
            return False

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
        rc, err = await _run_ffmpeg_command(cmd, timeout=120.0)
        return rc == 0 and output_path.exists() and output_path.stat().st_size > 0

    else:
        # Static image watermark (e.g. green_watermark_crop.png)
        v_expr = "clip(min(mod(t,2.2)/0.35, (2.2-mod(t,2.2))/0.35), 0, 1)"
        s_expr = f"(3 - 2*{v_expr})*{v_expr}*{v_expr}"
        filter_str = (
            f"[1:v]colorkey=0x000000:0.15:0.02,scale={wm_w}:-1[wm_base];"
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
        rc, err = await _run_ffmpeg_command(cmd, timeout=120.0)
        return rc == 0 and output_path.exists() and output_path.stat().st_size > 0


async def apply_watermark_image(input_path: Path, output_path: Path) -> bool:
    """Overlays the Poco AI watermark onto a static image file with full alpha transparency."""
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
                logger.info(f"Successfully applied alpha WebM watermark to image {output_path}")
                return True
            logger.warning(f"libvpx-vp9 primary image attempt failed (code {rc}), trying colorkey fallback...")
        except Exception as e:
            logger.warning(f"libvpx-vp9 image overlay exception: {e}")

        # Fallback with colorkey
        filter_str_fallback = (
            f"[1:v]colorkey=0x000000:0.15:0.02,scale={wm_w}:-1,format=yuva420p[wm];"
            "[0:v][wm]overlay=W-w-24:24[outv]"
        )
        cmd_fallback = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-ss", "3.0",
            "-i", str(watermark_src),
            "-filter_complex", filter_str_fallback,
            "-map", "[outv]",
            "-frames:v", "1",
            str(output_path)
        ]
        rc, err = await _run_ffmpeg_command(cmd_fallback, timeout=60.0)
        return rc == 0 and output_path.exists() and output_path.stat().st_size > 0

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
        rc, err = await _run_ffmpeg_command(cmd, timeout=60.0)
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
