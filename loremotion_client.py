import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

LOREMOTION_BASE_URL = os.getenv("LOREMOTION_BASE_URL", "https://loremotion.com").rstrip("/")
LOREMOTION_AUTH_URL = os.getenv("LOREMOTION_AUTH_URL", "https://auth.loremotion.com").rstrip("/")
LOREMOTION_ANON_KEY = os.getenv(
    "LOREMOTION_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZpbWtnZ2NodGp6dWR0YXJmcWFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzcyMjMwNjMsImV4cCI6MjA5Mjc5OTA2M30.3ixvgKDf85HVSBYA-53iqoFibihV6F-QlYcNeIG3APM",
).strip()
LOREMOTION_TOKEN = (os.getenv("LOREMOTION_TOKEN") or "").strip()
LOREMOTION_REFRESH_TOKEN = (os.getenv("LOREMOTION_REFRESH_TOKEN") or "").strip()
LOREMOTION_COOKIE = (os.getenv("LOREMOTION_COOKIE") or "").strip()


class LoreMotionClient:
    """Async client for free video and image models on loremotion.com."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        cookie: Optional[str] = None,
        token: Optional[str] = None,
        refresh_token: Optional[str] = None,
    ):
        self.base_url = (base_url or LOREMOTION_BASE_URL).rstrip("/")
        self.cookie = (cookie if cookie is not None else LOREMOTION_COOKIE).strip()
        self.token = (token if token is not None else LOREMOTION_TOKEN).strip()
        self.refresh_token = (refresh_token if refresh_token is not None else LOREMOTION_REFRESH_TOKEN).strip()

        # Allow pasting full sb-*-auth-token JSON or JWT directly into LOREMOTION_TOKEN or LOREMOTION_COOKIE
        for raw_val in (self.token, self.cookie):
            if raw_val.startswith("{"):
                try:
                    parsed = json.loads(raw_val)
                    if isinstance(parsed, dict):
                        if parsed.get("access_token") and not self.token.startswith("eyJ"):
                            self.token = str(parsed["access_token"]).strip()
                        if parsed.get("refresh_token") and not self.refresh_token:
                            self.refresh_token = str(parsed["refresh_token"]).strip()
                except Exception:
                    pass
            elif raw_val.startswith("Bearer "):
                self.token = raw_val[7:].strip()
            elif raw_val.startswith("eyJ") and not self.token:
                self.token = raw_val

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h: Dict[str, str] = {
            "Accept": "application/json",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/generate/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        elif self.cookie and not self.cookie.startswith("{"):
            h["Cookie"] = self.cookie
        if extra:
            h.update(extra)
        return h

    async def _refresh_access_token(self) -> bool:
        if not self.refresh_token:
            return False
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{LOREMOTION_AUTH_URL}/auth/v1/token?grant_type=refresh_token",
                    headers={
                        "apikey": LOREMOTION_ANON_KEY,
                        "Content-Type": "application/json",
                    },
                    json={"refresh_token": self.refresh_token},
                )
                if resp.status_code < 400:
                    data = resp.json()
                    if data.get("access_token"):
                        self.token = str(data["access_token"]).strip()
                    if data.get("refresh_token"):
                        self.refresh_token = str(data["refresh_token"]).strip()
                    return bool(self.token)
        except Exception as e:
            logger.warning(f"Failed to refresh LoreMotion token: {e}")
        return False

    def get_full_url(self, url_or_path: str) -> str:
        raw = str(url_or_path or "").strip()
        if not raw:
            return ""
        if raw.startswith(("http://", "https://")):
            return raw
        return f"{self.base_url}/{raw.lstrip('/')}"

    async def upload_image(self, image_bytes: bytes, filename: str = "ref.jpg") -> str:
        """Upload a reference image and return its hosted URL."""
        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            resp = await client.post(
                f"{self.base_url}/api/upload/image",
                headers=self._headers(),
                files={"file": (filename, image_bytes, "image/jpeg")},
            )
            if resp.status_code == 401:
                raise RuntimeError("Требуется авторизация (LOREMOTION_COOKIE) для загрузки референсов")
            if resp.status_code >= 400:
                raise RuntimeError(f"Ошибка загрузки референса ({resp.status_code}): {resp.text[:200]}")
            data = resp.json()
            url = data.get("url") or data.get("image_url") or ""
            if not url:
                raise RuntimeError("Сервер не вернул ссылку на загруженный референс")
            return self.get_full_url(url)

    async def create_render_task(
        self,
        model_info: Dict[str, Any],
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        ratio: str = "16:9",
        ref_images: Optional[List[bytes]] = None,
        ref_mode: str = "omni",
    ) -> str:
        """Submit a free video or image render job to POST /api/renders."""
        model_id = str(model_info.get("api_id") or "ltx-2.3")
        is_image = model_info.get("category") == "image"

        uploaded_urls: List[str] = []
        for idx, img in enumerate(ref_images or [], start=1):
            if img:
                uploaded_urls.append(await self.upload_image(img, filename=f"ref_{idx}.jpg"))

        if is_image:
            mode = "i2i" if (uploaded_urls or model_id == "krea-2-identity-edit") else "t2i"
            res_int = 1024
            dur_val = 1
        else:
            mode = "i2v" if uploaded_urls else "t2v"
            res_digits = re.sub(r"\D+", "", str(resolution or "720p"))
            res_int = int(res_digits) if res_digits in ("480", "720", "1080") else 720
            dur_val = max(1, int(duration or 5))

        ref_first = uploaded_urls[0] if uploaded_urls else None
        ref_last = (
            uploaded_urls[1]
            if (not is_image and ref_mode == "frames" and len(uploaded_urls) >= 2 and model_info.get("supports_frames"))
            else None
        )

        payload: Dict[str, Any] = {
            "prompt": (prompt or "").strip(),
            "negative_prompt": None,
            "mode": mode,
            "ref_image_url": ref_first,
            "last_ref_image_url": ref_last,
            "ref_video_url": None,
            "resolution": res_int,
            "aspect_ratio": ratio or ("1:1" if is_image else "16:9"),
            "duration": dur_val,
            "model": model_id,
            "user_email": None,
        }
        if uploaded_urls:
            payload["ref_image_urls"] = uploaded_urls

        if not self.token and self.refresh_token:
            await self._refresh_access_token()

        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            resp = await client.post(
                f"{self.base_url}/api/jobs",
                headers=self._headers({"Content-Type": "application/json"}),
                json=payload,
            )
            if resp.status_code == 401 and await self._refresh_access_token():
                resp = await client.post(
                    f"{self.base_url}/api/jobs",
                    headers=self._headers({"Content-Type": "application/json"}),
                    json=payload,
                )
            if resp.status_code == 401:
                raise RuntimeError("Требуется авторизация (LOREMOTION_TOKEN / LOREMOTION_REFRESH_TOKEN) для запуска генерации")
            if resp.status_code >= 400:
                msg = ""
                try:
                    msg = resp.json().get("error") or resp.json().get("message") or ""
                except Exception:
                    msg = resp.text[:250]
                raise RuntimeError(f"Ошибка запуска генерации ({resp.status_code}): {msg}")

            data = resp.json()
            job_id = str(data.get("id") or data.get("job_id") or data.get("jobId") or "")
            if not job_id:
                raise RuntimeError("Сервер не вернул ID задачи генерации")
            return job_id

    async def get_task(self, job_id: str) -> Dict[str, Any]:
        """Poll GET /api/jobs/{job_id} and normalize status."""
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(
                f"{self.base_url}/api/jobs/{job_id}",
                headers=self._headers(),
            )
            if resp.status_code == 401 and await self._refresh_access_token():
                resp = await client.get(
                    f"{self.base_url}/api/jobs/{job_id}",
                    headers=self._headers(),
                )
            if resp.status_code >= 400:
                return {"status": "PROCESSING", "progress": 0.1}
            return self._normalize_job(resp.json())

    def _normalize_job(self, data: Dict[str, Any]) -> Dict[str, Any]:
        raw_status = str(data.get("status") or "pending").lower()
        if raw_status in ("done", "completed", "succeeded", "ready"):
            media = (
                data.get("video_url")
                or data.get("image_url")
                or data.get("output_url")
                or data.get("url")
                or ""
            )
            return {
                "status": "COMPLETED",
                "video_url": self.get_full_url(media),
                "image_url": self.get_full_url(media),
                "progress": 1.0,
            }
        if raw_status in ("failed", "error", "cancelled", "rejected"):
            err = data.get("error") or data.get("failure_reason") or "Генерация завершилась с ошибкой"
            return {"status": "FAILED", "error": str(err)}
        prog = data.get("progress")
        return {
            "status": "PROCESSING",
            "progress": float(prog) if isinstance(prog, (int, float)) else 0.35,
        }

    async def download_video(self, url_or_path: str) -> bytes:
        full_url = self.get_full_url(url_or_path)
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(full_url, headers=self._headers())
            resp.raise_for_status()
            return resp.content

    async def download_image(self, url_or_path: str) -> bytes:
        return await self.download_video(url_or_path)
