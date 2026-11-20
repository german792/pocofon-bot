import asyncio
import json
import logging
import subprocess
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from config import BASE_DIR, PROMPTWISE_BASE_URL, PROMPTWISE_COOKIE

logger = logging.getLogger(__name__)

PROMPTWISE_COOKIE_FILE = BASE_DIR / ".promptwise_cookie"


def _probe_video_duration_and_size(video_bytes: bytes) -> Dict[str, Any]:
    """Probe duration/width/height via ffprobe (best-effort)."""
    if not video_bytes:
        return {}
    tmp_dir = Path(tempfile.mkdtemp(prefix="pw_probe_"))
    try:
        vp = tmp_dir / "in.mp4"
        vp.write_bytes(video_bytes)
        res = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "stream=width,height,codec_type",
                "-show_entries", "format=duration",
                "-of", "json",
                str(vp),
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
        if res.returncode != 0:
            return {}
        data = json.loads(res.stdout.decode("utf-8", "ignore") or "{}")
        out: Dict[str, Any] = {}
        dur = (data.get("format") or {}).get("duration")
        if dur is not None:
            try:
                out["durationSeconds"] = round(float(dur), 2)
            except Exception:
                pass
        for st in data.get("streams") or []:
            if st.get("codec_type") == "video":
                if st.get("width"):
                    out["width"] = int(st["width"])
                if st.get("height"):
                    out["height"] = int(st["height"])
                break
        return out
    except Exception:
        return {}
    finally:
        for p in tmp_dir.glob("*"):
            p.unlink(missing_ok=True)
        tmp_dir.rmdir()


def _detect_image_mime_and_ext(img_bytes: bytes) -> tuple[str, str]:
    if img_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if img_bytes[:4] == b"RIFF" and img_bytes[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return "image/jpeg", ".jpg"


class PromptWiseClient:
    """Unified async client for staging.promptwise.com (Video, Motion Control, Image, Voice, Music, SFX)."""

    def __init__(
        self,
        base_url: str = PROMPTWISE_BASE_URL,
        cookie: str = PROMPTWISE_COOKIE,
    ):
        self.base_url = (base_url or "https://staging.promptwise.com").rstrip("/")
        self.cookie_value = (cookie or "").strip()
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(90.0, connect=15.0, read=60.0),
            follow_redirects=True,
        )
        self._load_cookie_from_disk()

    def _load_cookie_from_disk(self) -> None:
        if not self.cookie_value and PROMPTWISE_COOKIE_FILE.exists():
            try:
                saved = PROMPTWISE_COOKIE_FILE.read_text(encoding="utf-8").strip()
                if saved:
                    self.cookie_value = saved
            except Exception as exc:
                logger.warning(f"Failed to read .promptwise_cookie: {exc}")

    def set_cookie(self, new_cookie: str) -> None:
        cleaned = (new_cookie or "").strip()
        if cleaned.lower().startswith("cookie:"):
            cleaned = cleaned[7:].strip()
        self.cookie_value = cleaned
        try:
            PROMPTWISE_COOKIE_FILE.write_text(self.cookie_value + "\n", encoding="utf-8")
        except Exception as exc:
            logger.warning(f"Could not save .promptwise_cookie: {exc}")

    # Compatibility alias for existing /token handler
    def set_token(self, new_token: str, new_refresh: Optional[str] = None) -> None:
        self.set_cookie(new_token)

    @property
    def token(self) -> str:
        return self.cookie_value

    @property
    def cookie(self) -> str:
        return self.cookie_value

    def _cookie_header(self) -> str:
        val = (self.cookie_value or "").strip()
        if not val:
            return ""
        if "=" in val and ("session_token" in val or ";" in val):
            return val
        return f"__Secure-better-auth.session_token={val}"

    def _headers(self, json_body: bool = True) -> Dict[str, str]:
        h: Dict[str, str] = {
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/studio/unified",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        if json_body:
            h["Content-Type"] = "application/json"
        ck = self._cookie_header()
        if ck:
            h["Cookie"] = ck
        return h

    def _abs_url(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return f"{self.base_url}/{url.lstrip('/')}"

    def get_full_url(self, media_url: str) -> str:
        return self._abs_url(media_url)

    async def close(self) -> None:
        await self.client.aclose()

    def _extract_error(self, resp: httpx.Response) -> str:
        try:
            data = resp.json()
            if isinstance(data, dict):
                return str(data.get("error") or data.get("message") or data.get("detail") or resp.text[:300])
        except Exception:
            pass
        return resp.text[:300]

    async def upload_asset(
        self,
        data: bytes,
        kind: str,
        mime_type: str,
        file_name: str,
        purpose: str = "generation-reference",
        width: Optional[int] = None,
        height: Optional[int] = None,
        duration_seconds: Optional[float] = None,
    ) -> Dict[str, str]:
        """Upload image/video/audio via presigned upload -> PUT -> complete. Returns {file_id, url}."""
        r1 = await self.client.post(
            f"{self.base_url}/api/assets/presigned-upload",
            headers=self._headers(),
            json={
                "kind": kind,
                "mimeType": mime_type,
                "purpose": purpose,
                "sizeBytes": len(data),
                "fileName": file_name,
            },
        )
        if r1.status_code not in (200, 201):
            raise RuntimeError(f"Ошибка загрузки {kind} ({r1.status_code}): {self._extract_error(r1)}")

        up = r1.json()
        presigned_url = up.get("presignedUrl")
        asset_id = up.get("assetId")
        put_headers = dict(up.get("headers") or {})
        if "Content-Type" not in put_headers and "content-type" not in put_headers:
            put_headers["Content-Type"] = mime_type

        if not presigned_url or not asset_id:
            raise RuntimeError("Сервер не вернул presignedUrl/assetId для загрузки медиа")

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0, read=90.0)) as put_client:
            r2 = await put_client.put(presigned_url, content=data, headers=put_headers)
            if r2.status_code not in (200, 201, 204):
                raise RuntimeError(f"Ошибка прямой загрузки {kind} ({r2.status_code})")

        complete_body: Dict[str, Any] = {"sizeBytes": len(data)}
        if width is not None:
            complete_body["width"] = int(width)
        if height is not None:
            complete_body["height"] = int(height)
        if duration_seconds is not None:
            complete_body["durationSeconds"] = float(duration_seconds)

        r3 = await self.client.post(
            f"{self.base_url}/api/assets/{urllib.parse.quote(str(asset_id), safe='')}/complete",
            headers=self._headers(),
            json=complete_body,
        )
        if r3.status_code not in (200, 201):
            raise RuntimeError(f"Ошибка подтверждения загрузки {kind} ({r3.status_code}): {self._extract_error(r3)}")

        comp = r3.json()
        file_id = str(comp.get("fileId") or comp.get("id") or asset_id)
        url = self._abs_url(str(comp.get("url") or ""))
        return {"file_id": file_id, "url": url}

    async def create_video_task(
        self,
        model_info: Dict[str, Any],
        prompt: str,
        duration: int = 5,
        resolution: str = "720p",
        ratio: str = "16:9",
        generate_audio: bool = True,
        ref_images: Optional[List[bytes]] = None,
        ref_mode: str = "ref",
        ref_video: Optional[bytes] = None,
        audio_bytes: Optional[bytes] = None,
    ) -> str:
        """Submit video generation to POST /api/v1/generate-video/<api_id>."""
        api_id = model_info["api_id"]
        route = f"{self.base_url}/api/v1/generate-video/{api_id}"

        model_durs = [int(d) for d in (model_info.get("durations") or [5])]
        dur = duration if duration in model_durs else min(model_durs, key=lambda x: (abs(x - duration), x))

        options: Dict[str, Any] = {"duration": int(dur)}

        res_vals = list(model_info.get("resolutions") or [])
        if res_vals:
            res_map = {v.lower(): v for v in res_vals}
            chosen_res = res_map.get((resolution or "").lower(), res_vals[0])
            options["resolution"] = chosen_res

        ratio_vals = list(model_info.get("ratios") or [])
        if ratio_vals:
            chosen_ratio = ratio if ratio in ratio_vals else ("16:9" if "16:9" in ratio_vals else ratio_vals[0])
            options["aspectRatio"] = chosen_ratio

        audio_key = model_info.get("audio_option_key")
        if audio_key:
            options[audio_key] = True if model_info.get("audio_locked") else bool(generate_audio)

        omni_max_refs = int(model_info.get("omni_max_refs") or 0)
        has_omni_video = bool(model_info.get("video_ref"))
        has_omni_audio = bool(model_info.get("audio_ref"))
        supports_frames = model_info.get("supports_frames") or []
        imgs = [b for b in (ref_images or []) if b]

        use_omni = False
        if omni_max_refs > 0:
            if (ref_video and has_omni_video) or (audio_bytes and has_omni_audio):
                use_omni = True
            elif imgs and ref_mode != "start" and (len(imgs) > 1 or not supports_frames):
                use_omni = True
            elif imgs and ref_mode == "ref" and not supports_frames:
                use_omni = True

        input_obj: Dict[str, Any] = {
            "prompt": (prompt or "").strip() or "Cinematic realistic scene with smooth motion",
            "options": options,
        }

        if use_omni:
            refs_obj: Dict[str, Any] = {}
            if imgs:
                uploaded_imgs = []
                for idx, ib in enumerate(imgs[:omni_max_refs]):
                    mime, ext = _detect_image_mime_and_ext(ib)
                    uploaded_imgs.append(
                        await self.upload_asset(
                            ib,
                            kind="image",
                            mime_type=mime,
                            file_name=f"ref_{idx}{ext}",
                            purpose="temporary-omni-reference",
                        )
                    )
                if uploaded_imgs:
                    refs_obj["images"] = uploaded_imgs
            if ref_video and has_omni_video:
                vmeta = await asyncio.to_thread(_probe_video_duration_and_size, ref_video)
                up_vid = await self.upload_asset(
                    ref_video,
                    kind="video",
                    mime_type="video/mp4",
                    file_name="ref_video.mp4",
                    purpose="temporary-omni-reference",
                    width=vmeta.get("width"),
                    height=vmeta.get("height"),
                    duration_seconds=vmeta.get("durationSeconds"),
                )
                refs_obj["videos"] = [up_vid]
            if audio_bytes and has_omni_audio:
                up_aud = await self.upload_asset(
                    audio_bytes,
                    kind="audio",
                    mime_type="audio/mpeg",
                    file_name="ref_audio.mp3",
                    purpose="temporary-omni-reference",
                )
                refs_obj["audio"] = [up_aud]
            if refs_obj:
                input_obj["references"] = refs_obj
        elif imgs and "start" in supports_frames:
            mime0, ext0 = _detect_image_mime_and_ext(imgs[0])
            input_obj["start_frame"] = await self.upload_asset(
                imgs[0],
                kind="image",
                mime_type=mime0,
                file_name=f"start{ext0}",
                purpose="generation-reference",
            )
            if len(imgs) >= 2 and "end" in supports_frames:
                mime1, ext1 = _detect_image_mime_and_ext(imgs[1])
                input_obj["end_frame"] = await self.upload_asset(
                    imgs[1],
                    kind="image",
                    mime_type=mime1,
                    file_name=f"end{ext1}",
                    purpose="generation-reference",
                )

        has_start_or_end = bool(input_obj.get("start_frame") or input_obj.get("end_frame"))
        has_omni_vid = bool((input_obj.get("references") or {}).get("videos"))
        if api_id in ("seedance-2.5", "seedance-2.5-flash") and (has_start_or_end or has_omni_vid):
            options["aspectRatio"] = "adaptive"
        elif has_start_or_end and api_id in (
            "kling-4.0",
            "kling-3.0-std", "kling-3.0-pro", "kling-3.0-4k",
            "kling-3.0-turbo-std", "kling-3.0-turbo-pro",
            "kling-v3-omni-std", "kling-v3-omni-pro", "kling-v3-omni-4k",
            "minimax-h3", "hailuo-pro", "grok-video",
        ):
            options.pop("aspectRatio", None)

        payload = {
            "context": {"source": "studio"},
            "input": input_obj,
        }
        logger.info(f"[promptwise/video] model={api_id} options={options} omni={use_omni} imgs={len(imgs)} vid={bool(ref_video)}")
        resp = await self.client.post(route, headers=self._headers(), json=payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Ошибка генерации видео ({resp.status_code}): {self._extract_error(resp)}")

        gen_id = str(resp.json().get("generationId") or "")
        if not gen_id:
            raise RuntimeError("Сервер не вернул generationId видео-задачи")
        return gen_id

    async def create_motion_control_task(
        self,
        image_bytes: bytes,
        video_bytes: bytes,
        prompt: str = "",
        resolution: str = "720p",
        character_orientation: str = "image",
        model_id: str = "kling-3.0-motion-control",
    ) -> str:
        """Submit Kling 3.0 Motion Control to POST /api/v1/generate-video/kling-3.0-motion-control."""
        mime, ext = _detect_image_mime_and_ext(image_bytes)
        char_up = await self.upload_asset(
            image_bytes,
            kind="image",
            mime_type=mime,
            file_name=f"character{ext}",
            purpose="kling-motion-control-reference",
        )
        vmeta = await asyncio.to_thread(_probe_video_duration_and_size, video_bytes)
        vid_up = await self.upload_asset(
            video_bytes,
            kind="video",
            mime_type="video/mp4",
            file_name="motion.mp4",
            purpose="kling-motion-control-reference",
            width=vmeta.get("width"),
            height=vmeta.get("height"),
            duration_seconds=vmeta.get("durationSeconds"),
        )
        res = resolution if resolution in ("720p", "1080p") else "720p"
        orient = character_orientation if character_orientation in ("image", "video") else "image"
        payload = {
            "context": {"source": "studio"},
            "input": {
                "prompt": (prompt or "").strip(),
                "options": {"resolution": res},
                "motion_control": {
                    "character_image": {"file_id": char_up["file_id"]},
                    "motion_video": {"file_id": vid_up["file_id"]},
                    "character_orientation": orient,
                },
            },
        }
        route = f"{self.base_url}/api/v1/generate-video/{model_id}"
        resp = await self.client.post(route, headers=self._headers(), json=payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Ошибка Motion Control ({resp.status_code}): {self._extract_error(resp)}")
        gen_id = str(resp.json().get("generationId") or "")
        if not gen_id:
            raise RuntimeError("Сервер не вернул generationId для Motion Control")
        return gen_id

    async def create_image_task(
        self,
        model_info: Dict[str, Any],
        prompt: str,
        resolution: str = "1K",
        ratio: str = "1:1",
        ref_images: Optional[List[bytes]] = None,
    ) -> str:
        """Submit image generation to POST /api/generate-image."""
        api_id = model_info["api_id"]
        payload: Dict[str, Any] = {
            "prompt": (prompt or "").strip() or "Photorealistic studio quality image",
            "model": api_id,
        }
        for k, v in (model_info.get("default_opts") or {}).items():
            payload[k] = v

        ratio_vals = list(model_info.get("ratios") or ["1:1"])
        payload["aspect_ratio"] = ratio if ratio in ratio_vals else ratio_vals[0]

        res_axis = model_info.get("res_axis")
        res_vals = list(model_info.get("resolutions") or [])
        if res_axis and res_vals:
            rmap = {v.lower(): v.lower() for v in res_vals}
            chosen = rmap.get((resolution or "").lower(), res_vals[0].lower())
            payload[res_axis] = chosen

        ref_limit = int(model_info.get("ref_limit") or 0)
        imgs = [b for b in (ref_images or []) if b][:ref_limit] if ref_limit > 0 else []
        if imgs:
            uploaded = []
            for idx, ib in enumerate(imgs):
                mime, ext = _detect_image_mime_and_ext(ib)
                uploaded.append(
                    await self.upload_asset(
                        ib,
                        kind="image",
                        mime_type=mime,
                        file_name=f"imgref_{idx}{ext}",
                        purpose="generation-reference",
                    )
                )
            urls = [u["url"] for u in uploaded]
            refs = [{"fileId": u["file_id"], "url": u["url"]} for u in uploaded]
            payload["image_urls"] = urls
            payload["image_url"] = urls[0]
            payload["image_refs"] = refs
            payload["image_ref"] = refs[0]

        logger.info(f"[promptwise/image] model={api_id} ratio={payload['aspect_ratio']} res_axis={res_axis} refs={len(imgs)}")
        resp = await self.client.post(f"{self.base_url}/api/generate-image", headers=self._headers(), json=payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Ошибка генерации фото ({resp.status_code}): {self._extract_error(resp)}")

        data = resp.json()
        gens = data.get("generations") or []
        gen_id = str((gens[0].get("generationId") if gens and isinstance(gens[0], dict) else None) or data.get("generationId") or "")
        if not gen_id:
            raise RuntimeError("Сервер не вернул generationId фото-задачи")
        return gen_id

    async def create_audio_task(
        self,
        model_info: Dict[str, Any],
        prompt: str,
        voice_id: Optional[str] = None,
        duration_seconds: Optional[int] = None,
    ) -> str:
        """Submit Voice (TTS), Music, or SFX task to POST /api/generate-audio."""
        api_id = model_info["api_id"]
        audio_type = model_info.get("audio_type", "tts")
        clean_text = (prompt or "").strip() or "Привет! Это тестовая генерация в боте Poco AI."

        payload: Dict[str, Any] = {
            "type": audio_type,
            "text": clean_text,
            "model_id": api_id,
        }
        if audio_type == "tts":
            if model_info.get("provider") == "elevenlabs":
                payload["voice_id"] = voice_id or "LxN8dyndjhJGesWKq1RH"
                payload["stability"] = 0.5
                payload["similarity_boost"] = 0.75
                if not model_info.get("fixed_speed"):
                    payload["speed"] = 1.0
        else:
            durs = [int(d) for d in (model_info.get("durations") or [30])]
            dur = int(duration_seconds) if duration_seconds else durs[0]
            dur = max(min(durs), min(max(durs), dur))
            payload["duration_seconds"] = dur

        logger.info(f"[promptwise/audio] type={audio_type} model={api_id} dur={payload.get('duration_seconds')}")
        resp = await self.client.post(f"{self.base_url}/api/generate-audio", headers=self._headers(), json=payload)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Ошибка генерации аудио ({resp.status_code}): {self._extract_error(resp)}")

        gen_id = str(resp.json().get("generationId") or "")
        if not gen_id:
            raise RuntimeError("Сервер не вернул generationId аудио-задачи")
        return gen_id

    async def get_task(self, generation_id: str) -> Dict[str, Any]:
        """Poll task status via POST /api/generations/batch-status (with fallback to GET /api/generations/{id})."""
        info: Optional[Dict[str, Any]] = None
        try:
            r = await self.client.post(
                f"{self.base_url}/api/generations/batch-status",
                headers=self._headers(),
                json={"ids": [generation_id]},
                timeout=20.0,
            )
            if r.status_code == 200:
                info = (r.json().get("generations") or {}).get(generation_id)
        except Exception as exc:
            logger.warning(f"batch-status warning for {generation_id}: {exc}")

        if info is None:
            r2 = await self.client.get(
                f"{self.base_url}/api/generations/{urllib.parse.quote(generation_id, safe='')}",
                headers=self._headers(json_body=False),
                timeout=20.0,
            )
            if r2.status_code == 200:
                info = r2.json()
            elif r2.status_code == 401:
                raise RuntimeError("Сессия PromptWise истекла (401). Обновите cookie через /token.")

        if not info:
            return {"id": generation_id, "status": "processing", "stage": "Задача в очереди на сервере..."}

        raw_status = str(info.get("status") or "PROCESSING").upper()
        raw_url = str(info.get("fileUrl") or info.get("url") or "").strip()
        full_url = self._abs_url(raw_url) if raw_url else ""

        if raw_status in ("COMPLETED", "SUCCEEDED", "SUCCESS", "DONE") and full_url:
            return {
                "id": generation_id,
                "status": "succeeded",
                "stage": "Готово!",
                "videoUrl": full_url,
                "imageUrl": full_url,
                "audioUrl": full_url,
            }
        if raw_status in ("FAILED", "ERROR", "CANCELLED", "CANCELED", "REJECTED"):
            return {
                "id": generation_id,
                "status": "failed",
                "stage": "Ошибка",
                "error": str(info.get("error") or info.get("reason") or "Запрос отклонён сервером"),
            }
        return {
            "id": generation_id,
            "status": "processing",
            "stage": f"Обработка на сервере ({raw_status})...",
        }

    async def get_account_balance(self) -> Dict[str, Any]:
        """Fetch live credit balance from PromptWise tRPC credits.getBalance."""
        url = f"{self.base_url}/api/trpc/credits.getBalance?batch=1&input=%7B%220%22%3A%7B%22json%22%3Anull%7D%7D"
        resp = await self.client.get(url, headers=self._headers(json_body=False), timeout=15.0)
        if resp.status_code != 200:
            raise RuntimeError(f"Не удалось получить баланс PromptWise ({resp.status_code})")
        arr = resp.json()
        data = (arr[0].get("result") or {}).get("data") if isinstance(arr, list) and arr else {}
        return {
            "total_credits": int(data.get("spendableCredits") or 0),
            "plan_credits": int(data.get("allowanceRemaining") or 0),
            "consumable_credits": int(data.get("walletBalance") or 0),
            "tier_name": str(data.get("entitlementLabel") or "PromptWise"),
            "renewal_date": str(data.get("allowanceResetAt") or "Не указана"),
            "generation_count": int(data.get("heldCredits") or 0),
            "auto_refill": bool(data.get("isPaidSubscription")),
        }

    async def get_latest_completed(self, count: int = 1) -> List[Dict[str, Any]]:
        """Compatibility stub for /last command."""
        return []

    async def download_media(self, media_url: str) -> bytes:
        full_url = self._abs_url(media_url)
        headers: Dict[str, str] = {"User-Agent": "Mozilla/5.0"}
        if full_url.startswith(self.base_url):
            ck = self._cookie_header()
            if ck:
                headers["Cookie"] = ck
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=15.0, read=90.0),
            follow_redirects=True,
        ) as dl:
            resp = await dl.get(full_url, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(f"Не удалось скачать медиафайл ({resp.status_code})")
            return resp.content

    async def download_video(self, media_url: str) -> bytes:
        return await self.download_media(media_url)

    async def download_image(self, media_url: str) -> bytes:
        return await self.download_media(media_url)

    async def download_audio(self, media_url: str) -> bytes:
        return await self.download_media(media_url)
