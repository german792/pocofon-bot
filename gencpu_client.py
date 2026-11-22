import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

GENCPU_BASE_URL = os.getenv("GENCPU_BASE_URL", "https://160.30.161.35").rstrip("/")
GENCPU_TOKEN = (os.getenv("GENCPU_TOKEN") or "").strip()
GENCPU_EMAIL = (os.getenv("GENCPU_EMAIL") or "").strip()
GENCPU_PASSWORD = (os.getenv("GENCPU_PASSWORD") or "").strip()


class GenCPUClient:
    """Async client for free models on 160.30.161.35 (Veo 3 Free & Gencpu Free)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.base_url = (base_url or GENCPU_BASE_URL).rstrip("/")
        self.token = (token if token is not None else GENCPU_TOKEN).strip()
        self.email = (email if email is not None else GENCPU_EMAIL).strip()
        self.password = (password if password is not None else GENCPU_PASSWORD).strip()

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h: Dict[str, str] = {
            "Accept": "application/json",
            "X-GenCPU-Client": "web",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
            h["X-Api-Key"] = self.token
        if extra:
            h.update(extra)
        return h

    def get_full_url(self, url_or_path: str) -> str:
        raw = str(url_or_path or "").strip()
        if not raw:
            return ""
        if raw.startswith(("http://", "https://")):
            return raw
        return f"{self.base_url}/{raw.lstrip('/')}"

    async def _ensure_auth(self) -> None:
        if self.token:
            return
        if self.email and self.password:
            async with httpx.AsyncClient(verify=False, timeout=20.0) as client:
                resp = await client.post(
                    f"{self.base_url}/api/auth/login",
                    headers=self._headers({"Content-Type": "application/json"}),
                    json={"email": self.email, "username": self.email, "password": self.password},
                )
                if resp.status_code < 400:
                    data = resp.json()
                    user = data.get("user") or {}
                    tok = user.get("webToken") or user.get("apiKey") or data.get("token") or ""
                    if tok:
                        self.token = str(tok).strip()
                        return
        raise RuntimeError("Требуется токен доступа (GENCPU_TOKEN или GENCPU_EMAIL/GENCPU_PASSWORD)")

    async def upload_image(self, image_bytes: bytes, filename: str = "ref.jpg") -> str:
        """Upload a reference image to /api/assets/upload and return its asset ID."""
        await self._ensure_auth()
        async with httpx.AsyncClient(verify=False, timeout=45.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/assets/upload",
                headers=self._headers(),
                files={"file": (filename, image_bytes, "image/jpeg")},
            )
            if resp.status_code == 401:
                raise RuntimeError("Сессия истекла (GENCPU_TOKEN)")
            if resp.status_code >= 400:
                raise RuntimeError(f"Ошибка загрузки референса ({resp.status_code}): {resp.text[:200]}")
            data = resp.json()
            asset = data.get("asset") or data
            asset_id = str(asset.get("id") or data.get("id") or data.get("assetId") or "")
            if not asset_id:
                raise RuntimeError("Сервер не вернул ID загруженного референса")
            return asset_id

    async def create_batch_task(
        self,
        model_info: Dict[str, Any],
        prompt: str,
        duration: int = 8,
        resolution: str = "720p",
        ratio: str = "16:9",
        ref_images: Optional[List[bytes]] = None,
    ) -> str:
        """Submit a free generation job to POST /api/batches."""
        await self._ensure_auth()
        server_engine = str(model_info.get("server_engine") or "server11")
        sv7_mode = model_info.get("sv7_mode")
        is_image = model_info.get("category") == "image"

        asset_ids: List[str] = []
        if not (is_image and not ref_images):
            for idx, img in enumerate(ref_images or [], start=1):
                if img:
                    asset_ids.append(await self.upload_image(img, filename=f"ref_{idx}.jpg"))

        if is_image:
            op = "i2v" if asset_ids else "t2v"
            sv7_mode = "gencpu_img_edit" if asset_ids else "gencpu_t2i"
        else:
            op = "i2v" if asset_ids else "t2v"

        payload: Dict[str, Any] = {
            "prompts": [(prompt or "").strip()],
            "model": str(model_info.get("api_id") or "Veo 3.1 Fast"),
            "serverEngine": server_engine,
            "engine": server_engine,
            "cookieSource": server_engine,
            "op": op,
            "i2vMode": "all-1",
            "imageAssetIds": asset_ids,
            "refVidAssetIds": [],
            "refAudioAssetIds": [],
            "duration": int(duration or 8),
            "aspectRatio": ratio or ("1:1" if is_image else "16:9"),
            "resolution": str(resolution or "720p"),
        }
        if sv7_mode:
            payload["sv7Mode"] = sv7_mode

        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/batches",
                headers=self._headers({"Content-Type": "application/json"}),
                json=payload,
            )
            if resp.status_code == 401:
                raise RuntimeError("Требуется авторизация (GENCPU_TOKEN)")
            if resp.status_code >= 400:
                msg = ""
                try:
                    msg = resp.json().get("error") or resp.json().get("message") or ""
                except Exception:
                    msg = resp.text[:250]
                raise RuntimeError(f"Ошибка запуска генерации ({resp.status_code}): {msg}")

            data = resp.json()
            jobs = data.get("jobs") or []
            if jobs and isinstance(jobs[0], dict):
                return str(jobs[0].get("id") or "")
            job_ids = data.get("jobIds") or []
            if job_ids:
                return str(job_ids[0])
            batch_id = str(data.get("batchId") or data.get("id") or "")
            if not batch_id:
                raise RuntimeError("Сервер не вернул ID задачи генерации")
            return batch_id

    async def get_task(self, job_id: str) -> Dict[str, Any]:
        """Poll GET /api/state to check job completion status."""
        await self._ensure_auth()
        async with httpx.AsyncClient(verify=False, timeout=20.0) as client:
            resp = await client.get(f"{self.base_url}/api/state", headers=self._headers())
            if resp.status_code >= 400:
                return {"status": "PROCESSING", "progress": 0.2}
            data = resp.json()
            for j in data.get("myJobs") or []:
                if str(j.get("id")) == str(job_id) or str(j.get("batchId")) == str(job_id):
                    return self._normalize_job(j)
            return {"status": "PROCESSING", "progress": 0.25}

    def _normalize_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        st = str(job.get("status") or "pending").lower()
        if st in ("done", "completed", "ready", "success"):
            media = (
                job.get("videoUrl")
                or job.get("resultUrl")
                or job.get("mediaUrl")
                or job.get("imageUrl")
                or f"/api/v1/media/{job.get('id')}.mp4?download=1"
            )
            full = self.get_full_url(media)
            return {"status": "COMPLETED", "video_url": full, "image_url": full, "progress": 1.0}
        if st in ("error", "failed", "cancelled"):
            err = job.get("error") or job.get("errorMessage") or "Генерация завершилась с ошибкой"
            return {"status": "FAILED", "error": str(err)}
        prog = job.get("progress")
        return {
            "status": "PROCESSING",
            "progress": float(prog) / 100.0 if isinstance(prog, (int, float)) and prog > 1 else (
                float(prog) if isinstance(prog, (int, float)) else 0.4
            ),
        }

    async def download_video(self, url_or_path: str) -> bytes:
        await self._ensure_auth()
        full_url = self.get_full_url(url_or_path)
        async with httpx.AsyncClient(verify=False, timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(full_url, headers=self._headers())
            resp.raise_for_status()
            return resp.content

    async def download_image(self, url_or_path: str) -> bytes:
        return await self.download_video(url_or_path)
