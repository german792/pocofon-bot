import asyncio
import html
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any
from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from api_client import (
    SeedanceAPIClient,
    SeedanceV2Client,
    GrokVideoClient,
    MiniMaxClient,
    QwenImageClient,
    DaVinciClient,
    translate_server_error,
)
from config import MODELS, BASE_DIR, DEFAULT_MODEL, MAX_CONCURRENT_JOBS, calculate_credit_cost
import image_utils
import history_manager
from watermark_utils import (
    apply_watermark,
    apply_watermark_image,
    extract_frame_from_video,
    extract_audio_from_video,
)

logger = logging.getLogger(__name__)

VIDEOS_DIR = BASE_DIR / "videos"
VIDEOS_DIR.mkdir(exist_ok=True)


def render_progress_bar(percent: int, width: int = 12) -> str:
    """Render a compact modern progress bar for Telegram HTML messages."""
    percent = max(0, min(100, percent))
    filled = int(round(width * percent / 100))
    empty = width - filled
    bar = "▰" * filled + "▱" * empty
    return f"{bar}  <b>{percent}%</b>"


def _quote(text: str, limit: int = 500) -> str:
    """Prompt as a collapsible blockquote (keeps cards short on a phone screen)."""
    text = (text or "").strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return f"<blockquote expandable>{html.escape(text)}</blockquote>"


def _telegram_photo_ready(path: Path) -> Path:
    """Telegram отклоняет фото тяжелее ~10 МБ или с суммой сторон больше 10000 px.
    Большие 2K/4K результаты переводим в JPEG нужного размера; маленькие не трогаем."""
    from PIL import Image
    with Image.open(path) as src:
        w, h = src.size
        small_enough = path.stat().st_size <= 9_500_000 and max(w, h) <= 4096 and (w + h) <= 9500
        if small_enough:
            return path
        im = src.convert("RGB")
    scale = min(1.0, 2560 / max(w, h), 9000 / (w + h))
    if scale < 1.0:
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    out = path.with_name(path.stem + ".tg.jpg")
    for q in (95, 90, 85, 80, 75):
        im.save(out, "JPEG", quality=q, optimize=True)
        if out.stat().st_size <= 9_500_000:
            break
    return out


RESULT_EFFECT_ID = "5046509860389126442"  # 🎉 message effect (private chats only)
SPINNER_FRAMES = ("🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘")


async def _make_cover(video_path) -> Optional[Path]:
    """Grab a nice poster frame (~1 s in) so the video looks good in the chat list."""
    try:
        cover = Path(str(video_path)).with_suffix(".cover.jpg")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(video_path),
            "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(cover),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=20)
        if cover.exists() and cover.stat().st_size > 0:
            return cover
    except Exception as e:
        logger.debug(f"cover extraction failed: {e}")
    return None


def _result_keyboard(user_id: int, kind: str = "video", extra_rows=None) -> InlineKeyboardMarkup:
    """Buttons under a finished result: quick way to start the next generation."""
    rows = list(extra_rows or [])
    if kind == "image":
        rows.append([
            InlineKeyboardButton(text="🖼 Ещё фото", callback_data=f"open_menu:image:{user_id}", style="success"),
            InlineKeyboardButton(text="🎬 В видео", callback_data=f"open_menu:video:{user_id}", style="primary"),
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="🎬 Ещё видео", callback_data=f"open_menu:video:{user_id}", style="success"),
            InlineKeyboardButton(text="🖼 Фото", callback_data=f"open_menu:image:{user_id}", style="primary"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def estimate_progress(elapsed: int, duration: int, status: str, server_progress: Optional[float] = None) -> int:
    """Calculate smooth estimated progress percentage based on elapsed seconds and server progress."""
    if status == "queued":
        return min(10, max(2, elapsed // 2))
    target_sec = 85 + (max(5, duration) - 5) * 4
    if elapsed <= target_sec * 0.85:
        pct = int((elapsed / (target_sec * 0.85)) * 85)
        est = max(5, min(85, pct))
    else:
        overtime = elapsed - target_sec * 0.85
        extra = int(13 * (1 - 1 / (1 + overtime / 30.0)))
        est = min(98, 85 + extra)

    if server_progress is not None and server_progress > 0:
        srv_pct = min(98, int(server_progress * 100))
        return max(est, srv_pct)
    return est


@dataclass(eq=False)
class GenerationJob:
    user_id: int
    chat_id: int
    status_message_id: int
    model_key: str
    prompt: str
    duration: int
    resolution: str
    ratio: str
    generate_audio: bool
    image_bytes: Optional[bytes]
    user_name: str = ""
    reply_to_message_id: Optional[int] = None
    ref_images: List[bytes] = field(default_factory=list)
    ref_mode: str = "ref"
    audio_bytes: Optional[bytes] = None
    ref_video: Optional[bytes] = None
    voice_id: str = ""
    voice_mode: str = "tts"
    motion_orient: str = "image"
    job_id: str = field(default_factory=lambda: f"tg_{uuid.uuid4().hex[:12]}")

    def get_all_ref_images(self) -> List[bytes]:
        if self.ref_images:
            return self.ref_images
        if self.image_bytes:
            return [self.image_bytes]
        return []


class GenerationQueue:
    def __init__(
        self,
        bot: Bot,
        api_client: SeedanceAPIClient,
        v2_client: SeedanceV2Client,
        grok_client: Optional[GrokVideoClient] = None,
        minimax_client: Optional[MiniMaxClient] = None,
        qwen_client: Optional[QwenImageClient] = None,
        davinci_client: Optional[DaVinciClient] = None,
    ):
        self.bot = bot
        self.api_client = api_client
        self.v2_client = v2_client
        self.grok_client = grok_client or GrokVideoClient()
        self.minimax_client = minimax_client or MiniMaxClient()
        self.qwen_client = qwen_client or QwenImageClient()
        self.davinci_client = davinci_client or DaVinciClient()
        self.queue: asyncio.Queue[GenerationJob] = asyncio.Queue()
        self.worker_tasks: List[asyncio.Task] = []
        self.is_running = False
        self.active_count: int = 0
        self.max_concurrent_jobs = MAX_CONCURRENT_JOBS
        self._last_msg_text: dict[int, str] = {}

    def start(self):
        """Initialize runner (no queue: tasks launch immediately)."""
        if not self.is_running:
            self.is_running = True
            logger.info("GenerationQueue started in direct mode (no queue).")

    async def stop(self):
        """Stop all active tasks cleanly."""
        self.is_running = False
        for t in list(self.worker_tasks):
            t.cancel()
        for t in list(self.worker_tasks):
            try:
                await t
            except asyncio.CancelledError:
                pass
        self.worker_tasks.clear()

    def get_queue_size(self) -> int:
        """Returns number of currently running jobs."""
        return self.active_count

    async def add_job(self, job: GenerationJob) -> int:
        """Launch generation task immediately without queuing."""
        self.active_count += 1
        task = asyncio.create_task(self._run_direct(job))
        self.worker_tasks.append(task)
        task.add_done_callback(lambda t: self.worker_tasks.remove(t) if t in self.worker_tasks else None)
        return self.active_count

    async def _run_direct(self, job: GenerationJob):
        try:
            await self._process_job(job)
        except Exception as e:
            logger.error(f"Error processing job for user {job.user_id}: {e}", exc_info=True)
            await self._update_status(
                job,
                f"❌ <b>Произошла ошибка при генерации:</b>\n{html.escape(str(e))}\nПопробуйте повторить запрос."
            )
        finally:
            self._last_msg_text.pop(job.status_message_id, None)
            self.active_count = max(0, self.active_count - 1)

    async def _update_status(self, job: GenerationJob, text: str):
        """Safely edit status message in Telegram, skipping identical text."""
        if self._last_msg_text.get(job.status_message_id) == text:
            return
        try:
            await asyncio.wait_for(
                self.bot.edit_message_text(
                    chat_id=job.chat_id,
                    message_id=job.status_message_id,
                    text=text,
                    parse_mode="HTML",
                    request_timeout=12.0,
                ),
                timeout=15.0,
            )
            self._last_msg_text[job.status_message_id] = text
        except Exception as e:
            logger.warning(f"Could not edit status message: {e}")

    def _format_progress_message(self, job: GenerationJob, pct: int, elapsed: int, stage: str) -> str:
        model_info = MODELS.get(job.model_key, MODELS[DEFAULT_MODEL])
        model_name = html.escape(str(model_info["name"]))
        backend = model_info["backend"]
        dur_label = "Авто" if job.duration == -1 else f"{job.duration} сек"
        bar = render_progress_bar(pct)
        safe_stage = html.escape(str(stage))
        ref_count = len(job.get_all_ref_images())
        cost = calculate_credit_cost(job.model_key, job.duration, job.resolution)
        user_line = f"👤 {job.user_name}\n" if job.user_name else ""

        chips = []
        if backend in ("davinci_image", "qwen_image"):
            head = f"🖼 <b>{model_name}</b> · создаю изображение"
            chips.append(f"{job.resolution} · {job.ratio}")
        elif backend == "davinci_voice":
            head = f"🎙 <b>{model_name}</b> · озвучиваю текст"
        else:
            head = f"🎬 <b>{model_name}</b> · создаю видео"
            chips.append(f"{dur_label} · {job.resolution} · {job.ratio}")
            if backend == "minimax":
                chips.append("🔊 музыка")
            elif model_info.get("has_audio"):
                chips.append("🔊 звук" if job.generate_audio else "🔇 без звука")
        if ref_count > 0:
            chips.append(f"📎 {ref_count}")
        if cost > 0:
            chips.append(f"💳 ~{cost} кр.")
        chips_line = "   ".join(chips)

        return (
            f"{head}\n"
            f"{user_line}\n"
            f"{_quote(job.prompt)}\n"
            f"{bar}\n"
            f"<i>{SPINNER_FRAMES[(elapsed // 3) % len(SPINNER_FRAMES)]} {safe_stage} · {elapsed} с</i>\n\n"
            f"{chips_line}"
        )

    async def _worker_loop(self, worker_id: int = 1):
        """Concurrent processing loop for worker task."""
        while self.is_running:
            job = await self.queue.get()
            self.active_count += 1
            try:
                await self._process_job(job)
            except Exception as e:
                logger.error(f"Worker {worker_id} error processing job for user {job.user_id}: {e}", exc_info=True)
                await self._update_status(
                    job,
                    f"❌ <b>Произошла ошибка при генерации:</b>\n{html.escape(str(e))}\nПопробуйте повторить запрос."
                )
            finally:
                self._last_msg_text.pop(job.status_message_id, None)
                self.active_count = max(0, self.active_count - 1)
                self.queue.task_done()

    def _get_client_for_backend(self, backend: str):
        if backend in ("davinci", "davinci_image", "davinci_voice", "davinci_motion"):
            return self.davinci_client
        if backend == "v2":
            return self.v2_client
        if backend == "grok":
            return self.grok_client
        if backend == "minimax":
            return self.minimax_client
        if backend == "qwen_image":
            return self.qwen_client
        return self.api_client

    async def _process_job(self, job: GenerationJob):
        model_info = MODELS.get(job.model_key, MODELS[DEFAULT_MODEL])
        model_name = model_info["name"]
        dur_label = "Авто" if job.duration == -1 else f"{job.duration} сек"
        ref_count = len(job.get_all_ref_images())

        await self._update_status(
            job,
            self._format_progress_message(job, pct=2, elapsed=0, stage="Отправка задачи на сервер...")
        )

        history_manager.log_task_start(
            task_id=job.job_id,
            source="telegram",
            user_id=str(job.user_id),
            username=str(job.user_id),
            model_key=job.model_key,
            model_name=model_name,
            category=model_info.get("category", "video"),
            prompt=job.prompt,
            duration=job.duration if job.duration > 0 else 5,
            resolution=job.resolution,
            ratio=job.ratio,
            has_audio=job.generate_audio,
        )

        media_url, error_raw, total_elapsed, backend = await self._execute_task(job, model_info)

        if not media_url:
            history_manager.fail_task(job.job_id, error_raw, total_elapsed)
            error_friendly = translate_server_error(error_raw)
            await self._update_status(
                job,
                f"❌ <b>Генерация не удалась ({model_name}):</b>\n{error_friendly}"
            )
            return

        client = self._get_client_for_backend(backend)
        direct_link = client.get_full_url(media_url)
        history_manager.complete_task(
            job.job_id,
            direct_link,
            model_info.get("category", "video"),
            total_elapsed,
        )

        # --- BRANCH 1: IMAGE GENERATION (Nano Banana, Flux 3 Image, Qwen Image) ---
        if backend in ("davinci_image", "qwen_image"):
            ts = int(asyncio.get_event_loop().time())
            temp_file = VIDEOS_DIR / f"{job.model_key}_{job.user_id}_{ts}.png"
            raw_file = VIDEOS_DIR / f"raw_{job.model_key}_{job.user_id}_{ts}.png"

            await self._update_status(
                job,
                self._format_progress_message(
                    job,
                    pct=99,
                    elapsed=total_elapsed,
                    stage="📥 Скачиваю изображение с сервера..."
                )
            )

            temp_file = None
            img_bytes = None
            for dl_attempt in range(1, 4):
                try:
                    logger.info(f"Downloading image from {direct_link} (attempt {dl_attempt})...")
                    img_bytes = await asyncio.wait_for(client.download_image(media_url), timeout=120.0)
                    if img_bytes:
                        break
                except Exception as dl_err:
                    logger.warning(f"Image download attempt {dl_attempt} failed: {dl_err}")
                    await asyncio.sleep(2)
            if img_bytes:
                raw_file.write_bytes(img_bytes)
                temp_file = raw_file
                try:
                    wm_out = VIDEOS_DIR / f"{job.model_key}_{job.user_id}_{ts}.png"
                    wm_ok = await apply_watermark_image(raw_file, wm_out, username=job.user_name)
                    if wm_ok and wm_out.exists() and wm_out.stat().st_size > 0:
                        raw_file.unlink(missing_ok=True)
                        temp_file = wm_out
                except Exception as wm_err:
                    logger.warning(f"Watermark skipped: {wm_err}")

            await self._update_status(
                job,
                self._format_progress_message(
                    job,
                    pct=100,
                    elapsed=total_elapsed,
                    stage="📤 Отправляю изображение в Telegram..."
                )
            )

            user_line = f"👤 {job.user_name}\n" if job.user_name else ""
            ref_part = f"  ·  📎 {ref_count}" if ref_count > 0 else ""
            caption = (
                f"🖼 <b>Изображение готово</b>\n"
                f"{user_line}\n"
                f"{_quote(job.prompt)}\n"
                f"<b>{html.escape(str(model_name))}</b>  ·  {job.resolution} · {job.ratio}{ref_part}  ·  ⚡ {total_elapsed} с"
            )

            if not (temp_file and temp_file.exists()):
                await self._update_status(
                    job,
                    "❌ <b>Изображение не получилось забрать с сервера.</b>\nПопробуйте ещё раз: баланс не списан, если генерация не прошла."
                )
                return

            grid_kb = _result_keyboard(
                job.user_id, "image",
                extra_rows=[[InlineKeyboardButton(text="🔲 Наложить толстую сетку", callback_data=f"grid_gen:{job.user_id}")]],
            )
            try:
                send_path = await asyncio.to_thread(_telegram_photo_ready, temp_file)
            except Exception as prep_err:
                logger.warning(f"Photo prep failed, sending as is: {prep_err}")
                send_path = temp_file

            sent_ok = False
            for attempt in range(1, 3):
                try:
                    await self.bot.send_photo(
                        chat_id=job.chat_id,
                        photo=FSInputFile(str(send_path), filename=f"image_{job.user_id}{send_path.suffix}"),
                        caption=caption,
                        parse_mode="HTML",
                        reply_to_message_id=job.reply_to_message_id,
                        allow_sending_without_reply=True,
                        reply_markup=grid_kb,
                    )
                    sent_ok = True
                    break
                except Exception as upload_err:
                    logger.warning(f"send_photo attempt {attempt} failed: {upload_err}")
                    await asyncio.sleep(2)
            if not sent_ok:
                # Telegram не принял как фото (слишком большой): шлём файлом без сжатия
                try:
                    await self.bot.send_document(
                        chat_id=job.chat_id,
                        document=FSInputFile(str(send_path), filename=f"image_{job.user_id}{send_path.suffix}"),
                        caption=caption,
                        parse_mode="HTML",
                        reply_to_message_id=job.reply_to_message_id,
                        allow_sending_without_reply=True,
                        reply_markup=grid_kb,
                    )
                    sent_ok = True
                except Exception as doc_err:
                    logger.error(f"send_document failed too: {doc_err}")

            for p in {temp_file, send_path, raw_file}:
                try:
                    if p and p.exists():
                        p.unlink()
                except Exception:
                    pass

            if not sent_ok:
                await self._update_status(
                    job,
                    "❌ <b>Не удалось отправить изображение.</b>\nПопробуйте ещё раз, можно взять меньшее разрешение."
                )
                return

            try:
                await self.bot.delete_message(chat_id=job.chat_id, message_id=job.status_message_id)
            except Exception:
                await self._update_status(
                    job,
                    "🎉 <b>Генерация завершена!</b>\n<i>Изображение отправлено сообщением выше ☝️</i>"
                )
            return

        # --- BRANCH 2: VOICE GENERATION (ElevenLabs TTS V3 / Voice Changer) ---
        if backend == "davinci_voice":
            ts = int(asyncio.get_event_loop().time())
            audio_file = VIDEOS_DIR / f"elevenlabs_{job.user_id}_{ts}.mp3"

            await self._update_status(
                job,
                self._format_progress_message(
                    job,
                    pct=99,
                    elapsed=total_elapsed,
                    stage="📥 Скачиваю аудиодорожку ElevenLabs..."
                )
            )

            try:
                audio_bytes = await self.davinci_client.download_audio(media_url)
                audio_file.write_bytes(audio_bytes)
            except Exception as dl_err:
                logger.error(f"Audio download failed: {dl_err}", exc_info=True)
                await self._update_status(
                    job,
                    "❌ <b>Ошибка загрузки аудиофайла с сервера ElevenLabs.</b>"
                )
                return

            await self._update_status(
                job,
                self._format_progress_message(
                    job,
                    pct=100,
                    elapsed=total_elapsed,
                    stage="📤 Отправляю озвучку в Telegram..."
                )
            )

            user_line = f"👤 {job.user_name}\n" if job.user_name else ""
            caption = (
                f"🎙 <b>Озвучка готова</b>\n"
                f"{user_line}\n"
                f"{_quote(job.prompt)}\n"
                f"<b>{html.escape(str(model_name))}</b>  ·  ⚡ {total_elapsed} с"
            )

            audio_input = FSInputFile(str(audio_file), filename=f"elevenlabs_{job.user_id}.mp3")
            for attempt in range(1, 3):
                try:
                    await self.bot.send_audio(
                        chat_id=job.chat_id,
                        audio=audio_input,
                        caption=caption,
                        title=job.prompt[:40] or "ElevenLabs V3",
                        performer="Poco AI • ElevenLabs",
                        parse_mode="HTML",
                        reply_to_message_id=job.reply_to_message_id,
                        allow_sending_without_reply=True,
                    )
                    break
                except Exception as upload_err:
                    logger.warning(f"send_audio attempt {attempt} failed: {upload_err}")
                    await asyncio.sleep(2)

            try:
                audio_file.unlink(missing_ok=True)
            except Exception:
                pass

            try:
                await self.bot.delete_message(chat_id=job.chat_id, message_id=job.status_message_id)
            except Exception:
                pass
            return

        # --- BRANCH 3: VIDEO GENERATION ---
        ts = int(asyncio.get_event_loop().time())
        temp_file = VIDEOS_DIR / f"{job.model_key}_{job.user_id}_{ts}.mp4"

        await self._update_status(
            job,
            self._format_progress_message(
                job,
                pct=99,
                elapsed=total_elapsed,
                stage="📥 Скачиваю видео с сервера..."
            )
        )

        try:
            logger.info(f"Downloading video from {direct_link}...")
            video_bytes = await client.download_video(media_url)
            raw_file = VIDEOS_DIR / f"raw_{job.model_key}_{job.user_id}_{ts}.mp4"
            raw_file.write_bytes(video_bytes)
            logger.info(f"Saved raw video to {raw_file} ({len(video_bytes)} bytes)")

            logger.info("Applying watermark and audio to video...")
            temp_audio_ref: Optional[Path] = None
            if job.audio_bytes:
                temp_audio_ref = VIDEOS_DIR / f"ref_audio_{job.user_id}_{ts}.mp3"
                temp_audio_ref.write_bytes(job.audio_bytes)

            try:
                wm_ok = await apply_watermark(
                    raw_file,
                    temp_file,
                    username=job.user_name,
                    audio_ref_path=temp_audio_ref,
                    target_duration=job.duration
                )
            finally:
                if temp_audio_ref and temp_audio_ref.exists():
                    temp_audio_ref.unlink(missing_ok=True)

            if not wm_ok or not temp_file.exists() or temp_file.stat().st_size == 0:
                logger.warning("Watermarking failed or skipped, falling back to raw video.")
                temp_file = raw_file
            else:
                raw_file.unlink(missing_ok=True)
                logger.info(f"Watermarked video ready at {temp_file} ({temp_file.stat().st_size} bytes)")
        except Exception as dl_err:
            logger.error(f"Download failed: {dl_err}", exc_info=True)
            await self._update_status(
                job,
                "❌ <b>Ошибка загрузки видео</b>\n\n"
                "Не удалось получить видеофайл с сервера генерации. Пожалуйста, попробуйте повторить запрос позже.",
            )
            return

        await self._update_status(
            job,
            self._format_progress_message(
                job,
                pct=100,
                elapsed=total_elapsed,
                stage="📤 Отправляю файл в Telegram..."
            )
        )

        try:
            await self.bot.send_chat_action(chat_id=job.chat_id, action="upload_video")
        except Exception:
            pass

        user_line = f"👤 {job.user_name}\n" if job.user_name else ""
        ref_part = f"  ·  📎 {ref_count}" if ref_count > 0 else ""
        caption = (
            f"🎬 <b>Видео готово</b>\n"
            f"{user_line}\n"
            f"{_quote(job.prompt)}\n"
            f"<b>{html.escape(str(model_name))}</b>  ·  {dur_label} · {job.resolution} · {job.ratio}{ref_part}  ·  ⚡ {total_elapsed} с"
        )

        video_input = FSInputFile(str(temp_file), filename=f"video_{job.user_id}.mp4")

        sent_successfully = False
        cover_path = await _make_cover(temp_file)
        for attempt in range(1, 3):
            try:
                logger.info(f"Sending video to Telegram (attempt {attempt})...")
                # First attempt: with poster frame and 🎉 effect (private chats). Fallback: plain send.
                extra: Dict[str, Any] = {}
                if attempt == 1:
                    if cover_path:
                        extra["cover"] = FSInputFile(str(cover_path))
                    if job.chat_id > 0:
                        extra["message_effect_id"] = RESULT_EFFECT_ID
                await asyncio.wait_for(
                    self.bot.send_video(
                        chat_id=job.chat_id,
                        video=video_input,
                        caption=caption,
                        parse_mode="HTML",
                        supports_streaming=True,
                        request_timeout=90.0,
                        reply_to_message_id=job.reply_to_message_id,
                        allow_sending_without_reply=True,
                        reply_markup=_result_keyboard(job.user_id, "video"),
                        **extra,
                    ),
                    timeout=95.0
                )
                sent_successfully = True
                logger.info("Video successfully sent to user.")
                break
            except Exception as upload_err:
                logger.warning(f"send_video attempt {attempt} failed: {upload_err}")
                await asyncio.sleep(2)

        try:
            temp_file.unlink(missing_ok=True)
            if cover_path:
                cover_path.unlink(missing_ok=True)
        except Exception:
            pass

        if sent_successfully:
            try:
                await self.bot.delete_message(chat_id=job.chat_id, message_id=job.status_message_id)
            except Exception:
                pass
        else:
            logger.error("Could not upload video to Telegram after retries.")
            await self._update_status(
                job,
                "⚠️ <b>Видео сгенерировано</b>, но из-за временной сетевой ошибки Telegram не удалось передать файл в чат.\n\n"
                "Пожалуйста, повторите генерацию через несколько секунд."
            )

    async def _execute_task(self, job: GenerationJob, model_info: dict):
        """Submit and poll single task on the selected backend. Returns (media_url, error_raw, elapsed, actual_backend)."""
        backend = model_info["backend"]
        grok_retried_alt_channel = False
        grok_current_channel = model_info.get("channel", "auto")
        all_refs = job.get_all_ref_images()

        try:
            if backend == "davinci":
                if not all_refs and job.ref_video:
                    v_frame = await extract_frame_from_video(job.ref_video)
                    if v_frame:
                        all_refs = [v_frame]
                if not job.audio_bytes and job.ref_video:
                    v_audio = await extract_audio_from_video(job.ref_video)
                    if v_audio:
                        job.audio_bytes = v_audio

                prepared_refs = [
                    image_utils.prepare_user_image(b, job.ratio) for b in all_refs if b
                ]
                logger.info(f"Submitting DaVinci video task with {len(prepared_refs)} reference image(s) for user {job.user_id}")
                task_id = await self.davinci_client.create_video_task(
                    model_id=model_info["api_id"],
                    prompt=job.prompt,
                    duration=job.duration,
                    resolution=job.resolution,
                    ratio=job.ratio,
                    generate_audio=job.generate_audio,
                    ref_images=prepared_refs,
                    ref_mode=job.ref_mode,
                    ref_video=job.ref_video,
                    audio_bytes=job.audio_bytes,
                )

            elif backend == "davinci_motion":
                imgs = [b for b in all_refs if b]
                if not imgs or not job.ref_video:
                    raise RuntimeError("Для Motion Control нужны фото персонажа и видео с движением")
                task_id = await self.davinci_client.create_motion_control_task(
                    image_bytes=imgs[0],
                    video_bytes=job.ref_video,
                    resolution=job.resolution,
                    model_id=model_info.get("api_id", "klingMotionControl3"),
                    character_orientation=job.motion_orient,
                )
                logger.info(f"[motion] user={job.user_id} orient={job.motion_orient} res={job.resolution}")

            elif backend == "davinci_image":
                prepared_refs = [
                    image_utils.prepare_user_image(b, job.ratio) for b in all_refs if b
                ]
                task_id = await self.davinci_client.create_image_task(
                    model_key=model_info["api_id"],
                    prompt=job.prompt,
                    resolution=job.resolution,
                    ratio=job.ratio,
                    ref_images=prepared_refs,
                )

            elif backend == "davinci_voice":
                voice_kwargs = {"voice_id": job.voice_id} if job.voice_id else {}
                task_id = await self.davinci_client.create_voice_task(
                    prompt=job.prompt,
                    audio_bytes=job.audio_bytes if job.voice_mode == "changer" else None,
                    **voice_kwargs,
                )

            elif backend == "v2":
                img_bytes = (
                    image_utils.prepare_user_image(job.image_bytes, job.ratio)
                    if job.image_bytes
                    else None
                )
                task_id = await self.v2_client.create_task(
                    model_api_id=model_info["api_id"],
                    prompt=job.prompt,
                    duration=job.duration,
                    resolution=job.resolution,
                    ratio=job.ratio,
                    image_bytes=img_bytes
                )
            elif backend == "grok":
                img_bytes = (
                    image_utils.prepare_user_image(job.image_bytes, job.ratio)
                    if job.image_bytes
                    else None
                )
                try:
                    task_id = await self.grok_client.create_task(
                        prompt=job.prompt,
                        duration=job.duration,
                        resolution=job.resolution,
                        ratio=job.ratio,
                        channel=grok_current_channel,
                        image_bytes=img_bytes
                    )
                except Exception as grok_sub_err:
                    logger.warning(f"Grok submit failed ({grok_sub_err}), falling back to Seedance 2.0 Fast...")
                    backend = "v2"
                    task_id = await self.v2_client.create_task(
                        model_api_id="doubao-seedance-2-0-fast-260128",
                        prompt=job.prompt,
                        duration=job.duration,
                        resolution=job.resolution,
                        ratio=job.ratio,
                        image_bytes=img_bytes
                    )
            elif backend == "minimax":
                style = model_info.get("style", "minimalist-hero")
                task_id = await self.minimax_client.create_task(
                    prompt=job.prompt,
                    duration=15,
                    resolution=job.resolution,
                    ratio=job.ratio,
                    style=style,
                    image_bytes=job.image_bytes
                )
            elif backend == "qwen_image":
                task_id = await self.qwen_client.create_task(
                    prompt=job.prompt,
                    image_bytes=job.image_bytes
                )
            else:
                img_bytes = (
                    image_utils.prepare_user_image(job.image_bytes, job.ratio)
                    if job.image_bytes
                    else image_utils.generate_text_seed_image(job.ratio)
                )
                task_id = await self.api_client.create_task(
                    prompt=job.prompt,
                    duration=job.duration,
                    resolution=job.resolution,
                    ratio=job.ratio,
                    generate_audio=job.generate_audio,
                    image_bytes=img_bytes
                )
        except Exception as e:
            logger.error(f"Failed to submit task ({backend}): {e}")
            return None, str(e), 0, backend

        logger.info(f"Task created with ID {task_id} on {backend} ({model_info['name']}) for user {job.user_id}")

        media_url = None
        error_raw = None
        start_time = asyncio.get_event_loop().time()
        consecutive_poll_errors = 0
        poll_count = 0

        client = self._get_client_for_backend(backend)
        poll_sleep = 3 if backend in ("grok", "minimax", "qwen_image", "davinci_image", "davinci_voice") else 5

        while True:
            await asyncio.sleep(poll_sleep)
            poll_count += 1
            elapsed = int(asyncio.get_event_loop().time() - start_time)

            try:
                task_info = await asyncio.wait_for(client.get_task(task_id), timeout=25.0)
                consecutive_poll_errors = 0
            except Exception as poll_exc:
                consecutive_poll_errors += 1
                logger.warning(f"Polling warning for {task_id} ({consecutive_poll_errors}/20): {poll_exc}")
                if consecutive_poll_errors >= 20:
                    error_raw = f"Потеряно соединение с сервером: {poll_exc}"
                    break
                continue

            status = task_info.get("status")
            srv_progress = task_info.get("progress")
            logger.info(f"Task {task_id} status: {status} ({elapsed}s)")

            if status == "succeeded":
                if backend in ("qwen_image", "davinci_image"):
                    media_url = task_info.get("imageUrl") or task_info.get("videoUrl")
                elif backend == "davinci_voice":
                    media_url = task_info.get("audioUrl") or task_info.get("videoUrl")
                else:
                    media_url = task_info.get("videoUrl")
                break
            elif status == "failed":
                err_str = str(task_info.get("error", "Неизвестная ошибка"))
                if backend == "grok" and any(k in err_str for k in ("额度", "配额", "账号池", "Лимит запросов", "недоступен")):
                    img_bytes = image_utils.prepare_user_image(job.image_bytes, job.ratio) if job.image_bytes else None
                    if not grok_retried_alt_channel:
                        grok_retried_alt_channel = True
                        alt_ch = "console" if grok_current_channel in ("auto", "web") else "web"
                        try:
                            task_id = await self.grok_client.create_task(
                                prompt=job.prompt,
                                duration=job.duration,
                                resolution=job.resolution,
                                ratio=job.ratio,
                                channel=alt_ch,
                                image_bytes=img_bytes
                            )
                            grok_current_channel = alt_ch
                            continue
                        except Exception as alt_err:
                            logger.warning(f"Grok alt channel '{alt_ch}' failed: {alt_err}")

                    try:
                        backend = "v2"
                        client = self.v2_client
                        poll_sleep = 5
                        task_id = await self.v2_client.create_task(
                            model_api_id="doubao-seedance-2-0-fast-260128",
                            prompt=job.prompt,
                            duration=job.duration,
                            resolution=job.resolution,
                            ratio=job.ratio,
                            image_bytes=img_bytes
                        )
                        continue
                    except Exception as fb_v2_err:
                        logger.error(f"Fallback to Seedance 2.0 Fast failed: {fb_v2_err}")

                error_raw = err_str
                break

            if poll_count == 1 or poll_count % 2 == 0:
                if backend in ("qwen_image", "davinci_image"):
                    pct = min(95, max(15, elapsed * 4))
                    stage = task_info.get("stage", f"Генерация изображения ({model_info['name']})...")
                elif backend == "davinci_voice":
                    pct = min(95, max(25, elapsed * 10))
                    stage = task_info.get("stage", "Синтез речи ElevenLabs V3...")
                else:
                    pct = estimate_progress(elapsed, job.duration, status, srv_progress)
                    if status == "queued":
                        stage = "Запуск на сервере..."
                    elif pct < 35:
                        stage = "Анализ сцены и генерация начальных кадров..."
                    elif pct < 75:
                        stage = "Рендеринг движений и деталей..."
                    else:
                        stage = "Финальная сборка и постобработка видео..."

                await self._update_status(
                    job,
                    self._format_progress_message(job, pct=pct, elapsed=elapsed, stage=stage)
                )

            if elapsed > 3600:
                error_raw = "Превышено максимальное время генерации (60 минут)"
                break

        return media_url, error_raw, int(asyncio.get_event_loop().time() - start_time), backend

    async def deliver_latest_from_davinci(
        self,
        chat_id: int,
        user_id: int,
        user_name: str,
        reply_to_message_id: int,
        count: int = 1,
    ) -> int:
        """Download, watermark, and send the latest completed DaVinci video/image items to Telegram."""
        items = await self.davinci_client.get_latest_completed(count=max(1, min(5, count)))
        sent = 0
        for idx, it in enumerate(items):
            media_url = it["url"]
            media_type = it["mediaType"]
            model_name = it["model_name"]
            prompt = it["prompt"]
            dur = it["duration"]
            res = it["resolution"]
            dim = it["dimension"]
            ts = int(asyncio.get_event_loop().time()) + idx

            if media_type == "IMAGE":
                raw_file = VIDEOS_DIR / f"raw_last_{user_id}_{ts}.png"
                out_file = VIDEOS_DIR / f"last_{user_id}_{ts}.png"
                img_bytes = await self.davinci_client.download_image(media_url)
                raw_file.write_bytes(img_bytes)
                wm_ok = await apply_watermark_image(raw_file, out_file)
                if not wm_ok or not out_file.exists() or out_file.stat().st_size == 0:
                    out_file = raw_file
                else:
                    raw_file.unlink(missing_ok=True)

                caption = (
                    f"🖼 <b>Изображение готово</b>\n\n"
                    f"{_quote(prompt)}\n"
                    f"<b>{html.escape(str(model_name))}</b>  ·  {res} · {dim}"
                )
                await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=FSInputFile(str(out_file), filename=f"image_{user_id}.png"),
                    caption=caption,
                    parse_mode="HTML",
                    reply_to_message_id=reply_to_message_id,
                    allow_sending_without_reply=True,
                )
                out_file.unlink(missing_ok=True)
                sent += 1
            else:
                raw_file = VIDEOS_DIR / f"raw_last_{user_id}_{ts}.mp4"
                out_file = VIDEOS_DIR / f"last_{user_id}_{ts}.mp4"
                vid_bytes = await self.davinci_client.download_video(media_url)
                raw_file.write_bytes(vid_bytes)
                wm_ok = await apply_watermark(raw_file, out_file)
                if not wm_ok or not out_file.exists() or out_file.stat().st_size == 0:
                    out_file = raw_file
                else:
                    raw_file.unlink(missing_ok=True)

                caption = (
                    f"🎬 <b>Видео готово</b>\n\n"
                    f"{_quote(prompt)}\n"
                    f"<b>{html.escape(str(model_name))}</b>  ·  {dur} сек · {res} · {dim}"
                )
                await self.bot.send_video(
                    chat_id=chat_id,
                    video=FSInputFile(str(out_file), filename=f"video_{user_id}.mp4"),
                    caption=caption,
                    parse_mode="HTML",
                    supports_streaming=True,
                    request_timeout=90.0,
                    reply_to_message_id=reply_to_message_id,
                    allow_sending_without_reply=True,
                )
                out_file.unlink(missing_ok=True)
                sent += 1
        return sent
