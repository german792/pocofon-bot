import asyncio
import base64
import html
import json
import logging
import shutil
import tempfile
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List
import httpx
from config import (
    API_BASE_URL,
    API_EMAIL,
    API_PASSWORD,
    API_V2_BASE_URL,
    API_GROK_BASE_URL,
    API_MINIMAX_BASE_URL,
    DAVINCI_API_BASE_URL,
    DAVINCI_ORIGIN,
    DAVINCI_STORAGE_BUCKET,
    DAVINCI_FIREBASE_API_KEY,
    DAVINCI_DEFAULT_UID,
    DAVINCI_TOKEN,
    DAVINCI_REFRESH_TOKEN,
    BASE_DIR,
)

logger = logging.getLogger(__name__)

COOKIE_FILE = BASE_DIR / ".session_cookie"
DAVINCI_TOKEN_FILE = BASE_DIR / ".davinci_token"
DAVINCI_REFRESH_FILE = BASE_DIR / ".davinci_refresh_token"


def translate_server_error(raw_err: str) -> str:
    """Translate Chinese backend error messages to friendly Russian and escape HTML."""
    if not raw_err:
        return "Неизвестная ошибка сервера."
    raw_str = str(raw_err)
    if "503 Service Temporarily Unavailable" in raw_str or "502 Bad Gateway" in raw_str or "504 Gateway" in raw_str:
        return "Сервер этой модели временно перегружен (503). Выберите другую модель (например, Seedance 2.0 или Grok)!"
    if "服务暂时不可用" in raw_str:
        return "Сервис Seedance временно перегружен на стороне сайта. Попробуйте выбрать Grok Imagine или другую модель!"
    if "宽高比不支持" in raw_str:
        return "Соотношение сторон картинки не поддерживается. Используйте стандартные пропорции (16:9, 9:16 или 1:1)."
    if "最多跑 2 个任务" in raw_str or "同时最多" in raw_str:
        return "Сервер генерации сейчас занят предыдущими задачами. Подождите 1-2 минуты."
    if "边长需在" in raw_str:
        return "Размер изображения должен быть от 300 до 6000 пикселей."
    if "操作太频繁" in raw_str:
        return "Слишком много запросов к серверу, подождите немного."
    if "上游账号额度等待恢复" in raw_str or "配额" in raw_str:
        return "Лимит запросов к каналу Grok временно исчерпан. Попробуйте модель Seedance 2.0 или повторите через пару минут."
    if "当前账号池不支持该模型" in raw_str:
        return "Канал Grok временно недоступен в пуле аккаунтов. Выберите другую модель."
    if any(k in raw_str.lower() for k in ("sensitive", "moderation", "policy", "nsfw")) or any(k in raw_str for k in ("敏感", "违规", "审核")):
        return "Запрос отклонен цензурой/модерацией нейросети. Попробуйте смягчить описание."
    return html.escape(raw_str[:400])


class SeedanceV2Client:
    """Client for http://39.109.117.93:8092 (Seedance 2.0 / Fast / Mini)."""

    def __init__(self, base_url: str = API_V2_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            verify=False,
            timeout=httpx.Timeout(45.0, connect=10.0, read=30.0)
        )

    async def close(self):
        await self.client.aclose()

    async def upload_image(self, image_bytes: bytes) -> str:
        """Upload reference image and return server path (e.g. /uploads/...)."""
        files = {"file": ("reference.jpg", image_bytes, "image/jpeg")}
        resp = await self.client.post(f"{self.base_url}/api/upload", files=files)
        if resp.status_code != 200:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise RuntimeError(f"Ошибка загрузки фото на сервер 2.0 ({resp.status_code}): {detail}")
        url = resp.json().get("url")
        if not url:
            raise RuntimeError("Сервер 2.0 не вернул URL загруженного изображения")
        return url

    async def create_task(
        self,
        model_api_id: str,
        prompt: str,
        duration: int,
        resolution: str,
        ratio: str,
        image_bytes: Optional[bytes] = None
    ) -> str:
        """Create a generation job on Seedance 2.0 server. Returns job_id."""
        img_url = None
        mode = "t2v"
        if image_bytes:
            img_url = await self.upload_image(image_bytes)
            mode = "i2v"

        # Mini model supports up to 720p
        res = resolution
        if "mini" in model_api_id and res == "1080p":
            res = "720p"

        valid_durations = [4, 5, 6, 8, 10, 12]
        dur = duration if duration in valid_durations else 5

        payload = {
            "mode": mode,
            "prompt": prompt.strip(),
            "image": img_url,
            "last_image": None,
            "model": model_api_id,
            "dur": dur,
            "resolution": res,
            "ratio": ratio,
            "n": 1
        }

        last_detail = ""
        for attempt in range(12):
            resp = await self.client.post(f"{self.base_url}/api/jobs", json=payload)
            if resp.status_code == 200:
                jobs = resp.json().get("jobs", [])
                if not jobs:
                    raise RuntimeError("Сервер 2.0 не вернул созданную задачу")
                return jobs[0]["id"]

            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            last_detail = str(detail)

            if any(k in last_detail for k in ("最多跑", "同时最多", "操作太频繁")):
                logger.info(f"Seedance 2.0 server busy ({last_detail}), waiting 6s (attempt {attempt + 1}/12)...")
                await asyncio.sleep(6)
                continue
            break

        raise RuntimeError(translate_server_error(last_detail))

    async def get_task(self, job_id: str) -> Dict[str, Any]:
        """Fetch job status from /api/jobs."""
        resp = await self.client.get(f"{self.base_url}/api/jobs")
        if resp.status_code != 200:
            raise RuntimeError(f"Ошибка опроса задач 2.0 ({resp.status_code})")

        jobs = resp.json().get("jobs", [])
        for j in jobs:
            if j.get("id") == job_id:
                raw_status = j.get("status", "queued")
                norm_status = "succeeded" if raw_status == "success" else raw_status
                return {
                    "id": job_id,
                    "status": norm_status,
                    "progress": j.get("progress", 0.0),
                    "stage": j.get("stage", ""),
                    "videoUrl": j.get("url"),
                    "error": j.get("error"),
                }

        raise RuntimeError(f"Задача {job_id} не найдена на сервере")

    def get_full_url(self, video_path: str) -> str:
        return f"{self.base_url}{video_path}" if video_path.startswith("/") else video_path

    async def download_video(self, video_path: str) -> bytes:
        """Download final MP4 video using a dedicated fresh client to prevent socket stalls."""
        url = self.get_full_url(video_path)
        # Use dedicated client with stream reading to ensure fast, reliable downloads
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0, read=45.0)) as dl_client:
            resp = await dl_client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"Не удалось скачать видео с сервера 2.0 ({resp.status_code})")
            return resp.content


class SeedanceAPIClient:
    """Client for https://111.229.36.38 (Seedance 2.5 Studio)."""

    def __init__(self, base_url: str = API_BASE_URL, email: str = API_EMAIL, password: str = API_PASSWORD):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.client = httpx.AsyncClient(
            verify=False,
            timeout=httpx.Timeout(45.0, connect=10.0, read=30.0)
        )
        self.is_authenticated = False
        self._load_saved_cookie()

    def _load_saved_cookie(self):
        if COOKIE_FILE.exists():
            try:
                sid = COOKIE_FILE.read_text(encoding="utf-8").strip()
                if sid:
                    self.client.cookies.set("sid", sid)
                    logger.info("Loaded cached session cookie from disk.")
            except Exception as e:
                logger.warning(f"Failed to read cookie file: {e}")

    def _save_cookie(self):
        sid = self.client.cookies.get("sid")
        if sid:
            try:
                COOKIE_FILE.write_text(sid, encoding="utf-8")
                logger.info("Saved session cookie to disk.")
            except Exception as e:
                logger.warning(f"Failed to save cookie file: {e}")

    async def close(self):
        await self.client.aclose()

    async def authenticate(self) -> bool:
        logger.info(f"Authenticating as {self.email}...")
        try:
            login_resp = await self.client.post(
                f"{self.base_url}/api/auth/login",
                json={"email": self.email, "password": self.password}
            )
            if login_resp.status_code == 200:
                logger.info("Successfully logged in.")
                self.is_authenticated = True
                self._save_cookie()
                return True
            logger.warning(f"Login failed ({login_resp.status_code}): {login_resp.text}")
        except Exception as e:
            logger.warning(f"Login request error: {e}")

        logger.info("Attempting registration...")
        try:
            reg_resp = await self.client.post(
                f"{self.base_url}/api/auth/register",
                json={"email": self.email, "password": self.password}
            )
            if reg_resp.status_code == 200:
                logger.info("Successfully registered new account.")
                self.is_authenticated = True
                self._save_cookie()
                return True
        except Exception as e:
            logger.error(f"Registration request error: {e}")

        return False

    async def ensure_authenticated(self):
        if self.is_authenticated:
            return

        if self.client.cookies.get("sid"):
            try:
                me_resp = await self.client.get(f"{self.base_url}/api/me")
                if me_resp.status_code == 200 and me_resp.json().get("user"):
                    self.is_authenticated = True
                    logger.info("Existing session cookie is valid.")
                    return
            except Exception as e:
                logger.warning(f"Failed to check session: {e}")

        ok = await self.authenticate()
        if not ok:
            raise RuntimeError("Не удалось авторизоваться на сервере Seedance 2.5.")

    async def create_task(
        self,
        prompt: str,
        duration: int,
        resolution: str,
        ratio: str,
        generate_audio: bool,
        image_bytes: bytes
    ) -> str:
        await self.ensure_authenticated()

        data = {
            "prompt": prompt.strip(),
            "resolution": resolution,
            "ratio": ratio,
            "duration": str(duration),
            "generateAudio": "true" if generate_audio else "false",
            "refs": json.dumps(["file"])
        }
        files = {
            "file": ("reference.jpg", image_bytes, "image/jpeg"),
            "images": ("reference.jpg", image_bytes, "image/jpeg")
        }

        resp = await self.client.post(
            f"{self.base_url}/api/tasks",
            data=data,
            files=files
        )

        if resp.status_code == 401:
            self.is_authenticated = False
            await self.ensure_authenticated()
            resp = await self.client.post(
                f"{self.base_url}/api/tasks",
                data=data,
                files=files
            )

        if resp.status_code != 200:
            try:
                err_raw = resp.json().get("error", resp.text)
            except Exception:
                err_raw = resp.text
            err_msg = translate_server_error(err_raw)
            raise RuntimeError(err_msg)

        task_data = resp.json().get("task", {})
        task_id = task_data.get("id")
        if not task_id:
            raise RuntimeError("ID задачи не получен от сервера")
        return task_id

    async def get_task(self, task_id: str) -> Dict[str, Any]:
        resp = await self.client.get(f"{self.base_url}/api/tasks/{task_id}")
        if resp.status_code == 401:
            self.is_authenticated = False
            await self.ensure_authenticated()
            resp = await self.client.get(f"{self.base_url}/api/tasks/{task_id}")

        if resp.status_code != 200:
            raise RuntimeError(f"Ошибка проверки статуса задачи ({resp.status_code})")
        return resp.json().get("task", {})

    def get_full_url(self, video_path: str) -> str:
        return f"{self.base_url}{video_path}" if video_path.startswith("/") else video_path

    async def download_video(self, video_path: str) -> bytes:
        """Download final MP4 video using a dedicated fresh client with session cookie."""
        url = self.get_full_url(video_path)
        sid = self.client.cookies.get("sid", "")
        cookies = {"sid": sid} if sid else {}
        async with httpx.AsyncClient(verify=False, timeout=httpx.Timeout(60.0, connect=10.0, read=45.0), cookies=cookies) as dl_client:
            resp = await dl_client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"Не удалось скачать видео ({resp.status_code})")
            return resp.content


class GrokVideoClient:
    """Client for http://49.233.205.130:8006 (Grok Video Studio: Grok Imagine / Grok 1.5)."""

    def __init__(self, base_url: str = API_GROK_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(45.0, connect=10.0, read=30.0)
        )

    async def close(self):
        await self.client.aclose()

    async def upload_image(self, image_bytes: bytes) -> str:
        """Upload reference image to /api/upload and return server path (e.g. /api/uploads/xxx.jpg)."""
        files = {"file": ("reference.jpg", image_bytes, "image/jpeg")}
        resp = await self.client.post(f"{self.base_url}/api/upload", files=files)
        if resp.status_code != 200:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise RuntimeError(f"Ошибка загрузки фото в Grok Studio ({resp.status_code}): {detail}")
        url = resp.json().get("url")
        if not url:
            raise RuntimeError("Сервер Grok не вернул URL загруженного изображения")
        return url

    async def create_task(
        self,
        prompt: str,
        duration: int,
        resolution: str,
        ratio: str,
        channel: str = "auto",
        image_bytes: Optional[bytes] = None
    ) -> str:
        """Submit generation task to /api/video/generate. Returns request_id."""
        image_file = ""
        if image_bytes:
            image_file = await self.upload_image(image_bytes)

        # Valid Grok durations: 4, 6, 8, 10, 12, 15
        valid_durations = [4, 6, 8, 10, 12, 15]
        if duration in valid_durations:
            dur = duration
        elif duration == 5:
            dur = 6
        elif duration == -1:
            dur = 8
        else:
            dur = 8

        # Grok resolutions: 480p, 720p, 1080p
        res = resolution if resolution in ["480p", "720p", "1080p"] else "720p"

        # Aspect ratios: 16:9, 9:16, 1:1, etc.
        valid_ratios = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"]
        rat = ratio if ratio in valid_ratios else "16:9"

        effective_channel = channel or "auto"
        if image_file and effective_channel in ("auto", "web"):
            effective_channel = "console"

        payload = {
            "prompt": prompt.strip(),
            "duration": dur,
            "aspect_ratio": rat,
            "resolution": res,
            "channel": effective_channel,
            "image_file": image_file,
            "image_url": ""
        }

        resp = await self.client.post(
            f"{self.base_url}/api/video/generate",
            json=payload
        )

        if resp.status_code != 200:
            try:
                err_detail = resp.json().get("detail", resp.text)
            except Exception:
                err_detail = resp.text

            # If web/auto channel failed due to quota or busy status, try console channel
            if effective_channel in ("auto", "web"):
                logger.warning(f"Grok channel '{effective_channel}' failed ({err_detail}). Retrying with 'console' channel...")
                payload["channel"] = "console"
                try:
                    fb_resp = await self.client.post(f"{self.base_url}/api/video/generate", json=payload)
                    if fb_resp.status_code == 200:
                        fb_data = fb_resp.json()
                        req_id = fb_data.get("request_id")
                        if req_id:
                            return req_id
                except Exception as fb_err:
                    logger.warning(f"Grok fallback to console failed: {fb_err}")

            raise RuntimeError(translate_server_error(err_detail))

        data = resp.json()
        req_id = data.get("request_id")
        if not req_id:
            raise RuntimeError("Сервер Grok не вернул ID задачи")
        return req_id

    async def get_task(self, request_id: str) -> Dict[str, Any]:
        """Fetch task status from /api/video/{request_id}."""
        resp = await self.client.get(f"{self.base_url}/api/video/{request_id}")
        if resp.status_code != 200:
            raise RuntimeError(f"Ошибка проверки статуса Grok ({resp.status_code})")

        data = resp.json()
        raw_status = data.get("status", "pending")
        progress_val = float(data.get("progress", 0)) / 100.0

        if raw_status == "done":
            norm_status = "succeeded"
            video_url = f"/api/video/{request_id}/content"
        elif raw_status in ("failed", "error"):
            norm_status = "failed"
            video_url = None
        else:
            norm_status = "processing"
            video_url = None

        return {
            "id": request_id,
            "status": norm_status,
            "progress": progress_val,
            "stage": f"Grok {raw_status} ({int(data.get('progress', 0))}%)",
            "videoUrl": video_url,
            "error": data.get("detail") or data.get("error"),
        }

    def get_full_url(self, video_path: str) -> str:
        return f"{self.base_url}{video_path}" if video_path.startswith("/") else video_path

    async def download_video(self, video_path: str) -> bytes:
        """Download MP4 video stream from Grok server."""
        url = self.get_full_url(video_path)
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0, read=45.0)) as dl_client:
            resp = await dl_client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"Не удалось скачать видео Grok ({resp.status_code})")
            return resp.content


class MiniMaxClient:
    """Client for http://120.55.55.62/ecommerce-poster-trio (MiniMax H3 Video)."""

    def __init__(self, base_url: str = API_MINIMAX_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            verify=False,
            timeout=httpx.Timeout(60.0, connect=10.0, read=45.0)
        )

    async def close(self):
        await self.client.aclose()

    async def create_task(
        self,
        prompt: str,
        duration: int = 15,
        resolution: str = "768p",
        ratio: str = "1:1",
        style: str = "minimalist-hero",
        image_bytes: Optional[bytes] = None
    ) -> str:
        """Submit generation task to /api/video/generate. Returns runId."""
        import base64
        import io
        from PIL import Image

        if image_bytes:
            try:
                im = Image.open(io.BytesIO(image_bytes))
                w, h = im.size
                # MiniMax requires each side to be >= 256
                if w < 256 or h < 256:
                    scale = max(256 / w, 256 / h)
                    im = im.resize((int(w * scale), int(h * scale)))
                buf = io.BytesIO()
                im.convert("RGB").save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                data_url = f"data:image/png;base64,{b64}"
            except Exception as e:
                logger.warning(f"Image resize failed for MiniMax, using raw: {e}")
                b64 = base64.b64encode(image_bytes).decode("utf-8")
                data_url = f"data:image/png;base64,{b64}"
        else:
            # Generate a neutral clean 512x512 background for text-to-video
            im = Image.new("RGB", (512, 512), color=(240, 240, 245))
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            data_url = f"data:image/png;base64,{b64}"

        valid_styles = [
            "minimalist-hero", "cinematic-lifestyle", "macro-detail",
            "dynamic-showcase", "editorial-cut", "levitation"
        ]
        st = style if style in valid_styles else "minimalist-hero"

        clean_prompt = prompt.strip()
        payload = {
            "productImage": {
                "name": "input.png",
                "dataUrl": data_url
            },
            "productName": clean_prompt[:60],
            "sellingPoints": clean_prompt,
            "videoStyle": st
        }

        resp = await self.client.post(
            f"{self.base_url}/api/video/generate",
            json=payload
        )

        if resp.status_code != 200:
            try:
                err = resp.json().get("error", resp.text)
            except Exception:
                err = resp.text
            raise RuntimeError(f"Ошибка MiniMax H3: {err}")

        data = resp.json()
        run_id = data.get("runId")
        if not run_id:
            raise RuntimeError("Сервер MiniMax не вернул runId задачи")
        return run_id

    async def get_task(self, run_id: str) -> Dict[str, Any]:
        """Fetch task status from /api/video-status?runId={runId}."""
        resp = await self.client.get(f"{self.base_url}/api/video-status?runId={run_id}")
        if resp.status_code != 200:
            raise RuntimeError(f"Ошибка проверки статуса MiniMax ({resp.status_code})")

        data = resp.json()
        status = data.get("status", "running")

        if status in ("completed", "done", "succeeded"):
            norm_status = "succeeded"
            video_url = data.get("videoUrl") or data.get("remoteVideoUrl")
        elif status in ("failed", "error"):
            norm_status = "failed"
            video_url = None
        else:
            norm_status = "processing"
            video_url = None

        return {
            "id": run_id,
            "status": norm_status,
            "stage": data.get("current") or f"MiniMax {status}",
            "videoUrl": video_url,
            "error": data.get("error"),
        }

    def get_full_url(self, video_path: str) -> str:
        if video_path.startswith("http://") or video_path.startswith("https://"):
            return video_path
        return f"{self.base_url}/{video_path.lstrip('/')}" if video_path else self.base_url

    async def download_video(self, video_path: str) -> bytes:
        """Download MP4 video stream from MiniMax server."""
        url = self.get_full_url(video_path)
        async with httpx.AsyncClient(verify=False, timeout=httpx.Timeout(90.0, connect=15.0, read=75.0)) as dl_client:
            resp = await dl_client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"Не удалось скачать видео MiniMax ({resp.status_code})")
            return resp.content


class QwenImageClient:
    """Client for Alibaba Qwen Image 3.0 Pro via http://120.55.55.62/ecommerce-poster-trio."""

    def __init__(self, base_url: str = API_MINIMAX_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            verify=False,
            timeout=httpx.Timeout(60.0, connect=10.0, read=45.0)
        )

    async def close(self):
        await self.client.aclose()

    async def create_task(
        self,
        prompt: str,
        image_bytes: Optional[bytes] = None,
        category: str = "General"
    ) -> str:
        """Submit generation task to /api/generate with imageModel='qwen-image-3.0-pro'. Returns runId."""
        import base64
        import io
        from PIL import Image

        if image_bytes:
            try:
                im = Image.open(io.BytesIO(image_bytes))
                buf = io.BytesIO()
                im.convert("RGB").save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                data_url = f"data:image/png;base64,{b64}"
            except Exception as e:
                logger.warning(f"Image processing failed for Qwen Image: {e}")
                b64 = base64.b64encode(image_bytes).decode("utf-8")
                data_url = f"data:image/png;base64,{b64}"
        else:
            # Clean neutral white canvas
            im = Image.new("RGB", (512, 512), color=(255, 255, 255))
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            data_url = f"data:image/png;base64,{b64}"

        clean_prompt = prompt.strip()
        payload = {
            "productImage": {
                "name": "product.png",
                "dataUrl": data_url
            },
            "productName": clean_prompt[:60],
            "category": category,
            "sellingPoints": clean_prompt,
            "targetAudience": "General audience",
            "imageModel": "qwen-image-3.0-pro",
            "textModel": "qwen-max"
        }

        resp = await self.client.post(
            f"{self.base_url}/api/generate",
            json=payload
        )

        if resp.status_code != 200:
            try:
                err = resp.json().get("error", resp.text)
            except Exception:
                err = resp.text
            raise RuntimeError(f"Ошибка Qwen Image: {err}")

        data = resp.json()
        run_id = data.get("runId")
        if not run_id:
            raise RuntimeError("Сервер Qwen Image не вернул runId задачи")
        return run_id

    async def get_task(self, run_id: str) -> Dict[str, Any]:
        """Fetch task status from /api/run-status?runId={runId}."""
        resp = await self.client.get(f"{self.base_url}/api/run-status?runId={run_id}")
        if resp.status_code != 200:
            raise RuntimeError(f"Ошибка проверки статуса Qwen Image ({resp.status_code})")

        data = resp.json()
        status = data.get("status", "running")
        posters = data.get("posters", [])
        completed_posters = [p for p in posters if p.get("imageUrl")]

        if len(completed_posters) >= 1:
            norm_status = "succeeded"
            image_url = completed_posters[0]["imageUrl"]
        elif status in ("failed", "error"):
            norm_status = "failed"
            image_url = None
        else:
            norm_status = "processing"
            image_url = None

        return {
            "id": run_id,
            "status": norm_status,
            "stage": f"Qwen Image ({len(completed_posters)}/9 готово)" if completed_posters else (data.get("current") or f"Qwen {status}"),
            "imageUrl": image_url,
            "all_posters": [p["imageUrl"] for p in completed_posters],
            "error": data.get("error"),
        }

    def get_full_url(self, image_path: str) -> str:
        if image_path.startswith("http://") or image_path.startswith("https://"):
            return image_path
        return f"{self.base_url}/{image_path.lstrip('/')}" if image_path else self.base_url

    async def download_image(self, image_path: str) -> bytes:
        """Download PNG image from Qwen server."""
        url = self.get_full_url(image_path)
        async with httpx.AsyncClient(verify=False, timeout=httpx.Timeout(60.0, connect=10.0, read=45.0)) as dl_client:
            resp = await dl_client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"Не удалось скачать изображение Qwen ({resp.status_code})")
            return resp.content


# Промпт предобработки, как в запросе с сайта (ставит позу и кадр). Меняется здесь.
MOTION_PREPROCESS_PROMPT = (
    "Use the uploaded user image as the main identity reference. Preserve the user's facial features, "
    "hairstyle, body proportions, clothing identity, and overall visual realism. Keep the original "
    "environment, lighting style, atmosphere, and scene aesthetics from the user image intact. "
    "Maintain cinematic realism, realistic anatomy, and coherent perspective."
)


class DaVinciClient:
    """Unified Client for DaVinci AI Studio (api-dev.davinci.ai):
    - Video models: Seedance 2.5, Seedance 2.0, Seedance 2.0 Fast, Seedance 2.0 Mini, Seedance 1.5 Pro,
      Kling 4.0, Kling 4.0 Flash, Flux 3, Flux 3 Max, LTX 2.5 Pro, Gemini Omni Flash 1.2
    - Image models: Nano Banana 2.1, Nano Banana Pro, Nano Banana, Flux 3 Image, Flux 3 Klein, Qwen Image 3.0
    - Voice models: ElevenLabs TTS V3 & Voice Changer
    """

    def __init__(
        self,
        base_url: str = DAVINCI_API_BASE_URL,
        token: str = DAVINCI_TOKEN,
        refresh_token: str = DAVINCI_REFRESH_TOKEN,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.refresh_token = refresh_token
        self.uid = DAVINCI_DEFAULT_UID
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=15.0, read=45.0)
        )
        self._load_tokens_from_disk()
        self._extract_uid_from_token()

    def _load_tokens_from_disk(self):
        if DAVINCI_TOKEN_FILE.exists():
            try:
                saved = DAVINCI_TOKEN_FILE.read_text(encoding="utf-8").strip()
                if saved:
                    self.token = saved
            except Exception as e:
                logger.warning(f"Failed to read .davinci_token: {e}")
        if DAVINCI_REFRESH_FILE.exists():
            try:
                saved_ref = DAVINCI_REFRESH_FILE.read_text(encoding="utf-8").strip()
                if saved_ref:
                    self.refresh_token = saved_ref
            except Exception as e:
                logger.warning(f"Failed to read .davinci_refresh_token: {e}")

    def set_token(self, new_token: str, new_refresh: Optional[str] = None):
        self.token = new_token.strip()
        try:
            DAVINCI_TOKEN_FILE.write_text(self.token, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not save .davinci_token: {e}")
        if new_refresh:
            self.refresh_token = new_refresh.strip()
            try:
                DAVINCI_REFRESH_FILE.write_text(self.refresh_token, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not save .davinci_refresh_token: {e}")
        self._extract_uid_from_token()

    def _extract_uid_from_token(self):
        try:
            parts = self.token.split(".")
            if len(parts) >= 2:
                pad = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = json.loads(base64.urlsafe_b64decode(pad).decode("utf-8"))
                uid = payload.get("user_id") or payload.get("sub")
                if uid:
                    self.uid = uid
        except Exception:
            pass

    def _is_token_expiring(self) -> bool:
        try:
            parts = self.token.split(".")
            if len(parts) >= 2:
                pad = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = json.loads(base64.urlsafe_b64decode(pad).decode("utf-8"))
                exp = int(payload.get("exp", 0))
                if exp and time.time() > (exp - 120):
                    return True
        except Exception:
            pass
        return False

    async def ensure_valid_token(self, force_refresh: bool = False):
        self._load_tokens_from_disk()
        if (force_refresh or self._is_token_expiring()) and self.refresh_token:
            try:
                resp = await self.client.post(
                    f"https://securetoken.googleapis.com/v1/token?key={DAVINCI_FIREBASE_API_KEY}",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self.refresh_token,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    new_id_tok = data.get("id_token")
                    new_ref_tok = data.get("refresh_token")
                    if new_id_tok:
                        self.set_token(new_id_tok, new_ref_tok)
                        logger.info("Successfully refreshed DaVinci Firebase ID token.")
            except Exception as e:
                logger.warning(f"DaVinci token refresh failed: {e}")

    def _headers(self) -> Dict[str, str]:
        return {
            "accept": "application/json",
            "content-type": "application/json",
            "origin": DAVINCI_ORIGIN,
            "referer": f"{DAVINCI_ORIGIN}/",
            "x-platform": "web",
            "x-token": self.token,
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36",
        }

    async def close(self):
        await self.client.aclose()

    async def upload_media(
        self,
        media_bytes: bytes,
        ext: str = ".jpg",
        content_type: str = "image/jpeg"
    ) -> str:
        """Upload reference image/audio/video to Firebase Storage and return bucketPath."""
        await self.ensure_valid_token()
        if not ext.startswith("."):
            ext = f".{ext}"
        bucket_path = f"user-inputs/{self.uid}/{uuid.uuid4()}{ext}"
        encoded_name = urllib.parse.quote(bucket_path, safe="")
        upload_url = (
            f"https://firebasestorage.googleapis.com/v0/b/{DAVINCI_STORAGE_BUCKET}/o"
            f"?uploadType=media&name={encoded_name}"
        )
        headers = {
            "Authorization": f"Firebase {self.token}",
            "Content-Type": content_type,
            "Origin": DAVINCI_ORIGIN,
            "Referer": f"{DAVINCI_ORIGIN}/",
        }
        resp = await self.client.post(upload_url, content=media_bytes, headers=headers)
        if resp.status_code in (401, 403) and self.refresh_token:
            await self.ensure_valid_token(force_refresh=True)
            headers["Authorization"] = f"Firebase {self.token}"
            resp = await self.client.post(upload_url, content=media_bytes, headers=headers)

        if resp.status_code != 200:
            raise RuntimeError(f"Ошибка загрузки референса в облако ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        final_path = data.get("name") or bucket_path

        # Best-effort asset registration
        try:
            await self.client.post(
                f"{self.base_url}/uploaded-assets",
                json={"path": final_path},
                headers=self._headers(),
            )
        except Exception:
            pass

        return final_path

    async def create_motion_control_task(
        self,
        image_bytes: bytes,
        video_bytes: bytes,
        resolution: str = "720p",
        keep_sound: bool = True,
    ) -> str:
        """Kling Motion Control 3.0: фото персонажа + видео с движением → processId."""
        await self.ensure_valid_token()
        image_path = await self.upload_media(image_bytes, ext=".jpg", content_type="image/jpeg")
        video_path = await self.upload_media(video_bytes, ext=".mp4", content_type="video/mp4")
        res = resolution if resolution in ("720p", "1080p") else "720p"
        payload: Dict[str, Any] = {
            "modelId": "klingMotionControl3",
            "generationMode": "workflow",
            "imagePath": image_path,
            "inputVideos": [video_path],
            "characterOrientation": "video",
            "generateAudio": False,
            "keepOriginalSound": bool(keep_sound),
            "resolution": res,
            "preprocessPrompt": MOTION_PREPROCESS_PROMPT,
        }
        logger.info(f"[motion/process] resolution={res} image={image_path} video={video_path}")
        resp = await self.client.post(f"{self.base_url}/video/process", json=payload, headers=self._headers())
        if resp.status_code == 401 and self.refresh_token:
            await self.ensure_valid_token(force_refresh=True)
            resp = await self.client.post(f"{self.base_url}/video/process", json=payload, headers=self._headers())
        if resp.status_code not in (200, 201):
            try:
                err = resp.json()
                err_msg = err.get("data") or err.get("message") or err.get("error") or resp.text
            except Exception:
                err_msg = resp.text
            raise RuntimeError(f"Ошибка генерации Motion Control ({resp.status_code}): {err_msg}")
        data = resp.json().get("data")
        process_id = data[0] if isinstance(data, list) and data else str(data or "")
        if not process_id:
            raise RuntimeError("Сервер не вернул id задачи Motion Control")
        return process_id

    async def _trim_video_for_ref(self, video_bytes: bytes, max_seconds: float = 15.0) -> bytes:
        """Trim reference video cleanly to max_seconds only if its duration exceeds the provider limit."""
        if not video_bytes or len(video_bytes) < 1024 or max_seconds <= 0:
            return video_bytes
        ffprobe_bin = shutil.which("ffprobe")
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffprobe_bin or not ffmpeg_bin:
            return video_bytes
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                in_path = Path(tmpdir) / "in.mp4"
                in_path.write_bytes(video_bytes)

                async def _probe(p: Path) -> Optional[float]:
                    proc = await asyncio.create_subprocess_exec(
                        ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", str(p),
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    )
                    out, _ = await asyncio.wait_for(proc.communicate(), timeout=20.0)
                    txt = out.decode("utf-8", "ignore").strip()
                    return float(txt) if txt and txt != "N/A" else None

                orig_dur = await _probe(in_path)
                if orig_dur is None or orig_dur <= max_seconds + 0.25:
                    return video_bytes

                out_copy = Path(tmpdir) / "out_copy.mp4"
                proc = await asyncio.create_subprocess_exec(
                    ffmpeg_bin, "-y", "-i", str(in_path), "-t", f"{max_seconds:.2f}",
                    "-c", "copy", "-movflags", "+faststart", str(out_copy),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=30.0)
                if out_copy.exists() and out_copy.stat().st_size > 1024:
                    copied_dur = await _probe(out_copy)
                    if copied_dur is not None and copied_dur <= max_seconds + 0.5:
                        logger.info(f"[video/process] Trimmed reference video {orig_dur:.2f}s -> {copied_dur:.2f}s (stream copy)")
                        return out_copy.read_bytes()

                out_re = Path(tmpdir) / "out_re.mp4"
                proc2 = await asyncio.create_subprocess_exec(
                    ffmpeg_bin, "-y", "-i", str(in_path), "-t", f"{max_seconds:.2f}",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                    "-c:a", "aac", "-movflags", "+faststart", str(out_re),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc2.communicate(), timeout=60.0)
                if out_re.exists() and out_re.stat().st_size > 1024:
                    logger.info(f"[video/process] Trimmed reference video {orig_dur:.2f}s -> {max_seconds:.2f}s (re-encode)")
                    return out_re.read_bytes()
        except Exception as trim_err:
            logger.warning(f"[video/process] Reference video duration check/trim skipped: {trim_err}")
        return video_bytes

    async def create_video_task(
        self,
        model_id: str,
        prompt: str,
        duration: int,
        resolution: str,
        ratio: str,
        generate_audio: bool = True,
        ref_images: Optional[List[bytes]] = None,
        ref_mode: str = "ref",
        ref_video: Optional[bytes] = None,
        audio_bytes: Optional[bytes] = None,
    ) -> str:
        """Submit video generation task to POST /video/process. Returns processId."""
        await self.ensure_valid_token()

        # Route Seedance video-reference jobs to Enterprise v2 Fast (seedance25 / seedance2 upstream
        # rejects video_edit unpredictably, whereas seedance2Fast succeeds consistently).
        effective_model_id = model_id
        if ref_video and model_id in ("seedance25", "seedance2", "seedance"):
            logger.info(
                f"[video/process] Routing video-ref {model_id} -> seedance2Fast "
                "(reliable Seedance enterprise reference-to-video engine)"
            )
            effective_model_id = "seedance2Fast"

        video_bucket_path: Optional[str] = None
        if ref_video:
            max_vid_sec = 15.0
            if effective_model_id in ("minimaxH3", "geminiOmniFlash11"):
                max_vid_sec = 10.0
            elif effective_model_id == "kling4Flash":
                max_vid_sec = 20.0
            elif effective_model_id in ("seedance25", "kling4"):
                max_vid_sec = 30.0
            trimmed_ref_video = await self._trim_video_for_ref(ref_video, max_seconds=max_vid_sec)
            video_bucket_path = await self.upload_media(trimmed_ref_video, ext=".mp4", content_type="video/mp4")

        seedance_or_wan_ref = effective_model_id in (
            "seedance25", "seedance2", "seedance2Fast", "seedance2Mini", "seedance", "wan30", "wan30Prime"
        )
        audio_bucket_path: Optional[str] = None
        if audio_bytes and not (video_bucket_path and seedance_or_wan_ref):
            audio_bucket_path = await self.upload_media(audio_bytes, ext=".mp3", content_type="audio/mpeg")

        bucket_paths: List[str] = []
        if ref_images:
            for img_b in ref_images:
                if img_b:
                    bp = await self.upload_media(img_b, ext=".jpg", content_type="image/jpeg")
                    bucket_paths.append(bp)

        # Normalize duration per effective model for the upstream API call
        dur = max(1, min(60, duration if duration > 0 else 5))
        api_dur = dur
        if effective_model_id == "seedance25":
            api_dur = max(4, min(30, api_dur))
        elif effective_model_id in ("seedance2", "seedance2Fast", "seedance2Mini", "seedance"):
            api_dur = max(4, min(15, api_dur))
        elif effective_model_id in ("wan30",):
            api_dur = max(2, min(15 if video_bucket_path else 30, api_dur))
        elif effective_model_id in ("kling4", "kling4Flash"):
            if api_dur < 3:
                api_dur = 3
        elif effective_model_id in ("ltx25Pro", "ltx25Fast"):
            if api_dur <= 6:
                api_dur = 6
            elif api_dur <= 8:
                api_dur = 8
            else:
                api_dur = 10
        elif effective_model_id == "pika22":
            api_dur = 5 if api_dur <= 5 else 10
        elif effective_model_id == "minimax-hailuo-2-3":
            api_dur = 5 if api_dur <= 5 else (6 if api_dur <= 6 else 10)
        elif effective_model_id in (
            "wan26",
            "wan30Prime",
            "minimaxH3",
            "grok",
            "flux3",
            "flux3Max",
            "geminiOmniFlash11",
            "luma-dream-machine",
            "luma-ray-3-2",
        ):
            # These accept 1, 2, 3, 4, 5... directly without minimum clamping
            api_dur = dur

        # Normalize resolution per effective model
        res: Optional[str] = resolution
        if effective_model_id in ("kling4Flash", "ltx25Pro", "ltx25Fast"):
            res = None
        elif effective_model_id == "minimaxH3":
            res = "2K" if str(res).lower() in ("1080p", "2k", "4k") else "768P"
        elif effective_model_id in ("seedance2Fast", "seedance2Mini", "wan30", "wan30Prime", "wan26", "grok"):
            if res not in ("480p", "720p"):
                res = "720p"
        elif effective_model_id in ("kling4", "flux3", "flux3Max", "pixversev6", "minimax-hailuo-2-3", "pika22", "luma-dream-machine", "luma-ray-3-2"):
            if res not in ("720p", "1080p"):
                res = "720p"
        elif effective_model_id in ("geminiOmniFlash12", "geminiOmniFlash11"):
            if res not in ("360p", "720p", "1080p", "4k"):
                res = "720p"
        else:
            if res not in ("480p", "720p", "1080p", "4k"):
                res = "720p"

        # Normalize dimension (aspect ratio) per effective model
        dim = ratio if ratio in ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "auto") else "16:9"
        if effective_model_id in ("ltx25Pro", "ltx25Fast", "geminiOmniFlash12", "geminiOmniFlash11") and dim not in ("16:9", "9:16"):
            dim = "16:9"
        elif effective_model_id in ("kling4", "kling4Flash") and dim not in ("16:9", "9:16", "1:1", "21:9"):
            dim = "16:9"

        # Audio support per effective model
        models_without_audio = (
            "kling4",
            "geminiOmniFlash12",
            "geminiOmniFlash11",
            "minimaxH3",
            "minimax-hailuo-2-3",
            "pika22",
        )
        audio_enabled = False if effective_model_id in models_without_audio else bool(generate_audio)

        # Reference images vs startFrame
        multi_ref_models = (
            "seedance25",
            "seedance2",
            "seedance2Fast",
            "seedance2Mini",
            "kling4",
            "kling4Flash",
            "geminiOmniFlash12",
            "geminiOmniFlash11",
            "minimaxH3",
            "wan30",
            "wan30Prime",
            "wan26",
            "grok",
            "runway-aleph",
            "luma-dream-machine",
            "luma-ray-3-2",
        )
        start_frame: Optional[str] = None
        reference_images_payload: Optional[List[str]] = None

        if bucket_paths:
            if effective_model_id in multi_ref_models:
                if ref_mode == "start" and len(bucket_paths) == 1 and not video_bucket_path:
                    start_frame = bucket_paths[0]
                else:
                    reference_images_payload = bucket_paths
            else:
                start_frame = bucket_paths[0]

        clean_prompt = (prompt or "").strip() or "Animate this scene with smooth cinematic motion"
        if video_bucket_path and effective_model_id in ("seedance25", "seedance2", "seedance2Fast", "seedance2Mini", "seedance", "wan30", "wan30Prime"):
            has_vid_tag = "@video1" in clean_prompt.lower()
            has_img_tag = "@image1" in clean_prompt.lower()
            if reference_images_payload:
                img_tags = " ".join(f"@Image{i + 1}" for i in range(len(reference_images_payload)))
                if not has_vid_tag and not has_img_tag:
                    clean_prompt = (
                        f"@Video1 точно повтори все движения, мимику, ракурс и динамику из видео 1. "
                        f"{img_tags} замени персонажа на видео 1 на персонажа с фото, полностью сохранив его внешность, лицо, прическу, одежду и стиль. "
                        f"Дополнительные детали: {clean_prompt}"
                    )
                elif not has_vid_tag:
                    clean_prompt = f"@Video1 точно следуй движениям и динамике из видео 1. {clean_prompt}"
                elif not has_img_tag:
                    clean_prompt = f"{img_tags} используй внешность персонажа с фото. {clean_prompt}"
            elif not has_vid_tag:
                clean_prompt = f"@Video1 следуй видео-референсу @Video1. {clean_prompt}"

        payload: Dict[str, Any] = {
            "modelId": effective_model_id,
            "prompt": clean_prompt,
            "duration": api_dur,
            "dimension": dim,
            "generateAudio": audio_enabled,
        }
        if res is not None:
            payload["resolution"] = res
        if start_frame is not None:
            payload["startFrame"] = start_frame
        if reference_images_payload is not None:
            payload["referenceImages"] = reference_images_payload
        if video_bucket_path:
            payload["inputVideos"] = [video_bucket_path]

        if audio_bucket_path:
            payload["audio"] = audio_bucket_path
            payload["referenceAudios"] = [audio_bucket_path]

        logger.info(
            f"[video/process] model={effective_model_id} (req={model_id}) payload keys={sorted(payload.keys())} "
            f"images={len(reference_images_payload or [])} video={'yes' if video_bucket_path else 'no'} "
            f"res={res} dur={api_dur}"
        )
        resp = await self.client.post(
            f"{self.base_url}/video/process",
            json=payload,
            headers=self._headers(),
        )
        if resp.status_code == 401 and self.refresh_token:
            await self.ensure_valid_token(force_refresh=True)
            resp = await self.client.post(
                f"{self.base_url}/video/process",
                json=payload,
                headers=self._headers(),
            )

        if resp.status_code not in (200, 201) and model_id in ("runway-aleph", "runwayAlpha"):
            logger.info("Runway Aleph not yet active on DaVinci server, falling back to Wan 2.6")
            payload["modelId"] = "wan26"
            resp = await self.client.post(
                f"{self.base_url}/video/process",
                json=payload,
                headers=self._headers(),
            )

        if resp.status_code not in (200, 201) and ("audio" in payload or "referenceAudios" in payload):
            logger.warning(
                f"DaVinci server rejected task with audio fields ({resp.status_code}). "
                f"Retrying without server-side audio payload (audio will be overlaid locally by FFmpeg)..."
            )
            payload.pop("audio", None)
            payload.pop("referenceAudios", None)
            resp = await self.client.post(
                f"{self.base_url}/video/process",
                json=payload,
                headers=self._headers(),
            )

        if resp.status_code not in (200, 201):
            try:
                err_data = resp.json()
                err_msg = err_data.get("data") or err_data.get("message") or err_data.get("error") or resp.text
            except Exception:
                err_msg = resp.text
            raise RuntimeError(f"Ошибка генерации видео ({resp.status_code}): {err_msg}")

        data = resp.json().get("data")
        process_id = data[0] if isinstance(data, list) and data else str(data or "")
        if not process_id:
            raise RuntimeError("Сервер DaVinci не вернул processId видео-задачи")
        return process_id

    async def create_image_task(
        self,
        model_key: str,
        prompt: str,
        resolution: str = "1K",
        ratio: str = "1:1",
        ref_images: Optional[List[bytes]] = None,
    ) -> str:
        """Submit image generation task to POST /process/txt-image. Returns processId."""
        await self.ensure_valid_token()

        bucket_paths: List[str] = []
        if ref_images:
            for img_b in ref_images:
                if img_b:
                    bp = await self.upload_media(img_b, ext=".jpg", content_type="image/jpeg")
                    bucket_paths.append(bp)

        dim = ratio if ratio in ("1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "auto") else "1:1"
        clean_prompt = (prompt or "").strip() or "High quality detailed studio photograph"

        payload: Dict[str, Any] = {
            "prompt": clean_prompt,
            "model": model_key,
            "dimension": dim,
            "imageCount": 1,
        }

        if model_key != "NANO_BANANA":
            res = resolution if resolution in ("1K", "2K", "4K") else "1K"
            if model_key in ("QWEN_IMAGE_3", "GPT_IMAGE_2_6_SUNBURST", "GPT_IMAGE_2_6_FLARE") and res == "4K":
                res = "2K"
            payload["resolution"] = res

        if bucket_paths:
            payload["imagePath"] = bucket_paths

        resp = await self.client.post(
            f"{self.base_url}/process/txt-image",
            json=payload,
            headers=self._headers(),
        )
        if resp.status_code == 401 and self.refresh_token:
            await self.ensure_valid_token(force_refresh=True)
            resp = await self.client.post(
                f"{self.base_url}/process/txt-image",
                json=payload,
                headers=self._headers(),
            )

        if resp.status_code not in (200, 201):
            try:
                err_data = resp.json()
                err_msg = err_data.get("data") or err_data.get("message") or err_data.get("error") or resp.text
            except Exception:
                err_msg = resp.text
            raise RuntimeError(f"Ошибка DaVinci Image ({resp.status_code}): {err_msg}")

        data = resp.json().get("data")
        process_id = data[0] if isinstance(data, list) and data else str(data or "")
        if not process_id:
            raise RuntimeError("Сервер DaVinci не вернул processId фото-задачи")
        return process_id

    async def create_voice_task(
        self,
        prompt: str,
        voice_id: str = "UGTtbzgh3HObxRjWaSpr",
        audio_bytes: Optional[bytes] = None,
    ) -> str:
        """Submit voiceover or voice-changer task to POST /voice/process. Returns processId."""
        await self.ensure_valid_token()

        if audio_bytes:
            audio_bp = await self.upload_media(audio_bytes, ext=".mp3", content_type="audio/mpeg")
            payload: Dict[str, Any] = {
                "type": "voice-changer",
                "modelKey": "voice-changer",
                "voice": voice_id,
                "audio": audio_bp,
                "removeBackgroundNoise": True,
            }
        else:
            clean_text = (prompt or "").strip() or "Привет! Это тестовая озвучка в боте Poco AI."
            # Язык по тексту: раньше всегда стоял "en", из-за чего русский звучал странно
            lang = "ru" if any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in clean_text) else "en"
            payload = {
                "modelKey": "eleven-v3",
                "text": clean_text,
                "voice": voice_id,
                "languageCode": lang,
                "stability": 0.5,
            }

        resp = await self.client.post(
            f"{self.base_url}/voice/process",
            json=payload,
            headers=self._headers(),
        )
        if resp.status_code == 401 and self.refresh_token:
            await self.ensure_valid_token(force_refresh=True)
            resp = await self.client.post(
                f"{self.base_url}/voice/process",
                json=payload,
                headers=self._headers(),
            )

        if resp.status_code not in (200, 201):
            try:
                err_data = resp.json()
                err_msg = err_data.get("data") or err_data.get("message") or err_data.get("error") or resp.text
            except Exception:
                err_msg = resp.text
            raise RuntimeError(f"Ошибка ElevenLabs ({resp.status_code}): {err_msg}")

        data = resp.json().get("data")
        process_id = data[0] if isinstance(data, list) and data else str(data or "")
        if not process_id:
            raise RuntimeError("Сервер ElevenLabs не вернул processId задачи")
        return process_id

    async def get_task(self, process_id: str) -> Dict[str, Any]:
        """Poll task status from GET /generations?page=1&limit=50 with cache-busting."""
        await self.ensure_valid_token()
        headers = self._headers()
        headers["cache-control"] = "no-cache"
        headers["pragma"] = "no-cache"
        url = f"{self.base_url}/generations?page=1&limit=50&_t={int(time.time() * 1000)}"
        resp = await self.client.get(
            url,
            headers=headers,
            timeout=20.0,
        )
        if resp.status_code == 401 and self.refresh_token:
            await self.ensure_valid_token(force_refresh=True)
            headers = self._headers()
            headers["cache-control"] = "no-cache"
            resp = await self.client.get(
                url,
                headers=headers,
                timeout=20.0,
            )

        if resp.status_code != 200:
            raise RuntimeError(f"Ошибка опроса статуса DaVinci ({resp.status_code})")

        groups = resp.json().get("data", [])
        for grp in groups:
            for item in grp.get("items", []):
                if process_id in (
                    item.get("processId"),
                    item.get("batchProcessId"),
                    item.get("analyticsProcessId"),
                    item.get("providerProcessId"),
                    grp.get("creationGroupId"),
                    item.get("_id"),
                ):
                    raw_status = (item.get("status") or "PROCESSING").upper()
                    media_type = (item.get("mediaType") or "VIDEO").upper()
                    if media_type == "VIDEO":
                        media_url = item.get("url")
                    else:
                        media_url = item.get("url") or item.get("originalImageUrl") or item.get("previewImageUrl")

                    if raw_status in ("COMPLETED", "SUCCEEDED", "SUCCESS", "DONE") and media_url:
                        return {
                            "id": process_id,
                            "status": "succeeded",
                            "stage": "Готово!",
                            "videoUrl": media_url,
                            "imageUrl": media_url,
                            "audioUrl": media_url,
                        }
                    if raw_status in ("FAILED", "ERROR", "CANCELLED", "REJECTED"):
                        err = (
                            item.get("errorMessage")
                            or item.get("error")
                            or "Запрос отклонен сервером или модерацией нейросети"
                        )
                        return {
                            "id": process_id,
                            "status": "failed",
                            "stage": "Ошибка",
                            "error": err,
                        }
                    return {
                        "id": process_id,
                        "status": "processing",
                        "stage": f"Рендеринг в облаке ({raw_status})...",
                    }

        # If not yet visible in /generations list, it is still initializing/processing
        return {
            "id": process_id,
            "status": "processing",
            "stage": "Задача обрабатывается на GPU-кластере...",
        }

    async def get_latest_completed(self, count: int = 1) -> List[Dict[str, Any]]:
        """Fetch the most recent completed generations from DaVinci."""
        await self.ensure_valid_token()
        headers = self._headers()
        headers["cache-control"] = "no-cache"
        resp = await self.client.get(
            f"{self.base_url}/generations?page=1&limit=25&_t={int(time.time() * 1000)}",
            headers=headers,
            timeout=20.0,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Ошибка получения списка генераций ({resp.status_code})")

        results: List[Dict[str, Any]] = []
        for grp in resp.json().get("data", []):
            for item in grp.get("items", []):
                raw_status = (item.get("status") or "").upper()
                media_type = (item.get("mediaType") or "VIDEO").upper()
                media_url = (
                    item.get("url")
                    if media_type == "VIDEO"
                    else (item.get("url") or item.get("originalImageUrl") or item.get("previewImageUrl"))
                )
                if raw_status in ("COMPLETED", "SUCCEEDED", "SUCCESS", "DONE") and media_url:
                    adv = item.get("advancedSettings") or {}
                    ctx = item.get("analyticsContext") or {}
                    results.append({
                        "processId": item.get("processId"),
                        "mediaType": media_type,
                        "url": media_url,
                        "prompt": item.get("prompt") or "",
                        "model_name": ctx.get("model_name") or adv.get("createdModel") or "DaVinci AI",
                        "duration": adv.get("duration") or 5,
                        "resolution": adv.get("resolution") or "720p",
                        "dimension": adv.get("dimension") or "16:9",
                    })
                    if len(results) >= count:
                        return results
        return results

    async def get_account_balance(self) -> Dict[str, Any]:
        """Fetch live account credit balance, plan tier, and generation stats directly from Firestore REST API."""
        await self.ensure_valid_token()
        headers = {
            "Authorization": f"Bearer {self.token}",
        }
        url = f"https://firestore.googleapis.com/v1/projects/davinci-web-dev/databases/(default)/documents/users/{self.uid}"
        resp = await self.client.get(url, headers=headers, timeout=15.0)
        if resp.status_code == 401 and self.refresh_token:
            await self.ensure_valid_token(force_refresh=True)
            headers["Authorization"] = f"Bearer {self.token}"
            resp = await self.client.get(url, headers=headers, timeout=15.0)

        if resp.status_code != 200:
            raise RuntimeError(f"Не удалось получить баланс с сервера DaVinci ({resp.status_code})")

        fields = resp.json().get("fields", {})
        consumable = int(fields.get("consumableCredit", {}).get("integerValue", 0))
        plan = int(fields.get("planCredit", {}).get("integerValue", 0))
        non_consumable = int(fields.get("nonConsumableCredit", {}).get("integerValue", 0))
        total = consumable + plan + non_consumable
        tier = fields.get("tierName", {}).get("stringValue", "Premium")
        renewal = fields.get("subscriptionRenewalDate", {}).get("stringValue", "Не указана")
        gen_count = int(fields.get("generationCount", {}).get("integerValue", 0))
        is_auto_refill = fields.get("isAutoRefillActive", {}).get("booleanValue", False)

        return {
            "total_credits": total,
            "consumable_credits": consumable,
            "plan_credits": plan,
            "tier_name": tier,
            "renewal_date": renewal,
            "generation_count": gen_count,
            "auto_refill": is_auto_refill,
        }

    def get_full_url(self, media_url: str) -> str:
        return media_url

    async def download_video(self, media_url: str) -> bytes:
        async with httpx.AsyncClient(verify=False, timeout=httpx.Timeout(120.0, connect=15.0, read=90.0)) as dl_client:
            resp = await dl_client.get(media_url)
            if resp.status_code != 200:
                raise RuntimeError(f"Не удалось скачать медиафайл ({resp.status_code})")
            return resp.content

    async def download_image(self, media_url: str) -> bytes:
        return await self.download_video(media_url)

    async def download_audio(self, media_url: str) -> bytes:
        return await self.download_video(media_url)
