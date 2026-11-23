import base64
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

ARK_BASE_URL = os.getenv("ARK_BASE_URL", "https://ark.ap-southeast.bytepluses.com/api/v3").rstrip("/")
ARK_API_KEY = (os.getenv("ARK_API_KEY") or "").strip()

IMAGE_RATIO_SIZES = {
    "1:1": "1024x1024",
    "16:9": "1280x720",
    "9:16": "720x1280",
    "4:3": "1152x864",
    "3:4": "864x1152",
}


def _clean_ark_error(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        err = data.get("error") or {}
        code = str(err.get("code") or "")
        msg = str(err.get("message") or data.get("message") or "")
        if code == "ModelNotOpen" or "has not activated the model" in msg:
            return "Эта модель пока не активирована на аккаунте API."
        if code == "AuthenticationError" or resp.status_code == 401:
            return "Неверный или просроченный API-ключ."
        if "quota" in msg.lower() or "rate limit" in msg.lower() or resp.status_code == 429:
            return "Превышен лимит запросов для этой модели. Попробуйте позже."
        if msg:
            return msg.split("Request id:")[0].strip()
    except Exception:
        pass
    return f"Ошибка сервера ({resp.status_code})"


class ArkClient:
    """Async client for video, image, and text models via OpenAI/Ark-compatible v3 API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.base_url = (base_url or os.getenv("ARK_BASE_URL") or ARK_BASE_URL).rstrip("/")
        self.api_key = (api_key if api_key is not None else (os.getenv("ARK_API_KEY") or ARK_API_KEY)).strip()

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise RuntimeError("Не задан API-ключ (ARK_API_KEY).")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_full_url(self, url: str) -> str:
        return str(url or "").strip()

    async def create_video_task(
        self,
        model_info: Dict[str, Any],
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        ratio: str = "16:9",
        generate_audio: bool = True,
        ref_images: Optional[List[bytes]] = None,
        ref_mode: str = "omni",
    ) -> str:
        """Create an async video generation task via POST /contents/generations/tasks."""
        model_id = str(model_info.get("api_id") or "")
        content: List[Dict[str, Any]] = [{"type": "text", "text": (prompt or "").strip()}]

        imgs = [b for b in (ref_images or []) if b]
        for idx, img_bytes in enumerate(imgs[:4]):
            b64 = base64.b64encode(img_bytes).decode("ascii")
            item: Dict[str, Any] = {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            }
            if ref_mode == "frames" and len(imgs) >= 2:
                item["role"] = "first_frame" if idx == 0 else "last_frame"
            elif idx == 0 and len(imgs) == 1:
                item["role"] = "first_frame"
            content.append(item)

        payload: Dict[str, Any] = {
            "model": model_id,
            "content": content,
            "ratio": ratio or "16:9",
            "duration": max(2, int(duration or 5)),
            "resolution": str(resolution or "720p"),
        }
        if model_info.get("has_audio"):
            payload["generate_audio"] = bool(generate_audio)

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"{self.base_url}/contents/generations/tasks",
                headers=self._headers(),
                json=payload,
            )
            if resp.status_code >= 400:
                raise RuntimeError(_clean_ark_error(resp))
            data = resp.json()
            task_id = str(data.get("id") or data.get("task_id") or "")
            if not task_id:
                raise RuntimeError("Сервер не вернул ID задачи генерации видео.")
            return task_id

    async def get_task(self, task_id: str) -> Dict[str, Any]:
        """Poll GET /contents/generations/tasks/{task_id}."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"{self.base_url}/contents/generations/tasks/{task_id}",
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                return {"status": "PROCESSING", "progress": 0.2}
            data = resp.json()
            status = str(data.get("status") or "running").lower()
            if status in ("succeeded", "completed", "done"):
                content = data.get("content") or {}
                vurl = content.get("video_url") or data.get("video_url") or ""
                return {"status": "COMPLETED", "video_url": vurl, "progress": 1.0}
            if status in ("failed", "cancelled", "expired"):
                err = data.get("error") or {}
                msg = err.get("message") if isinstance(err, dict) else str(err)
                return {"status": "FAILED", "error": msg or "Генерация завершилась с ошибкой."}
            return {"status": "PROCESSING", "progress": 0.4}

    async def create_image_url(
        self,
        model_info: Dict[str, Any],
        prompt: str,
        ratio: str = "1:1",
        ref_images: Optional[List[bytes]] = None,
    ) -> str:
        """Generate an image synchronously via POST /images/generations and return its URL."""
        model_id = str(model_info.get("api_id") or "")
        payload: Dict[str, Any] = {
            "model": model_id,
            "prompt": (prompt or "").strip(),
            "size": IMAGE_RATIO_SIZES.get(ratio or "1:1", "1024x1024"),
            "response_format": "url",
            "watermark": False,
        }
        imgs = [b for b in (ref_images or []) if b]
        if imgs:
            b64 = base64.b64encode(imgs[0]).decode("ascii")
            payload["image"] = f"data:image/jpeg;base64,{b64}"

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{self.base_url}/images/generations",
                headers=self._headers(),
                json=payload,
            )
            if resp.status_code >= 400:
                raise RuntimeError(_clean_ark_error(resp))
            data = resp.json()
            items = data.get("data") or []
            if items and isinstance(items[0], dict):
                url = items[0].get("url") or ""
                if url:
                    return url
            raise RuntimeError("Сервер не вернул ссылку на сгенерированное изображение.")

    async def create_chat_completion(
        self,
        model_info: Dict[str, Any],
        prompt: str,
        ref_images: Optional[List[bytes]] = None,
    ) -> str:
        """Generate a text response via POST /chat/completions."""
        model_id = str(model_info.get("api_id") or "")
        imgs = [b for b in (ref_images or []) if b]
        if imgs:
            user_content: Any = [{"type": "text", "text": (prompt or "").strip()}]
            for img_bytes in imgs[:2]:
                b64 = base64.b64encode(img_bytes).decode("ascii")
                user_content.append(
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                )
        else:
            user_content = (prompt or "").strip()

        payload: Dict[str, Any] = {
            "model": model_id,
            "messages": [{"role": "user", "content": user_content}],
            "max_tokens": 2048,
        }
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            if resp.status_code >= 400:
                raise RuntimeError(_clean_ark_error(resp))
            data = resp.json()
            choices = data.get("choices") or []
            if choices and isinstance(choices[0], dict):
                msg = choices[0].get("message") or {}
                text = str(msg.get("content") or "").strip()
                if text:
                    return text
            raise RuntimeError("Модель вернула пустой ответ.")

    async def download_video(self, url: str) -> bytes:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    async def download_image(self, url: str) -> bytes:
        return await self.download_video(url)
