"""
POCO AI Web Studio — Modern Web Interface for POCOFON AI
Supports Video AI (Seedance 2.5, Kling 4, Flux 3 Max, Grok, MiniMax),
Image AI (Nano Banana 2.1, Flux 3 Image, Qwen Image), and ElevenLabs Voice.
"""

import os
import sys
import time
import uuid
import asyncio
import logging
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any

import secrets
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import config
import image_utils
import watermark_utils
import access_manager
import history_manager
from api_client import (
    DaVinciClient,
    SeedanceAPIClient,
    SeedanceV2Client,
    GrokVideoClient,
    MiniMaxClient,
    QwenImageClient,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("web_studio")

BASE_DIR = Path(__file__).resolve().parent
VIDEOS_DIR = BASE_DIR / "videos"
OUTPUTS_DIR = BASE_DIR / "outputs"
STATIC_DIR = BASE_DIR / "static"

VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="POCO AI Web Studio", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Clients
davinci_client = DaVinciClient()
api_client = SeedanceAPIClient()
v2_client = SeedanceV2Client()
grok_client = GrokVideoClient()
minimax_client = MiniMaxClient()
qwen_client = QwenImageClient()

# Active in-memory tasks and sessions
active_tasks: Dict[str, Dict[str, Any]] = {}
admin_sessions: set = set()

def check_admin_token(token: Optional[str]) -> bool:
    return bool(token and token in admin_sessions)

def get_auth_context(request: Request) -> Dict[str, Any]:
    admin_token = request.headers.get("x-admin-token") or request.query_params.get("admin_token")
    if check_admin_token(admin_token):
        return {"authenticated": True, "role": "admin", "user_id": "GermanUstinf", "note": "Создатель"}

    access_key = request.headers.get("x-access-key") or request.query_params.get("access_key")
    if access_key:
        key_info = access_manager.verify_key(access_key)
        if key_info:
            return {
                "authenticated": True,
                "role": "user",
                "user_id": key_info["key"],
                "note": key_info.get("note", ""),
            }

    return {"authenticated": False, "role": "guest", "user_id": None, "note": None}

def get_client_for_backend(backend: str):
    if backend in ("davinci", "davinci_image", "davinci_voice"):
        return davinci_client
    elif backend == "v2":
        return v2_client
    elif backend == "grok":
        return grok_client
    elif backend == "minimax":
        return minimax_client
    elif backend == "qwen_image":
        return qwen_client
    return api_client

def calculate_progress(elapsed: int, est_duration: int = 45, server_progress: Optional[float] = None) -> int:
    if server_progress is not None and server_progress > 0:
        return min(96, max(10, int(server_progress * 100)))
    if elapsed <= 0:
        return 10
    if elapsed >= est_duration * 2:
        return 94
    if elapsed <= est_duration:
        return int(15 + (elapsed / est_duration) * 65)
    extra = elapsed - est_duration
    return min(94, int(80 + (extra / est_duration) * 14))


async def process_web_generation(
    task_id: str,
    model_key: str,
    prompt: str,
    duration: int,
    resolution: str,
    ratio: str,
    generate_audio: bool,
    ref_mode: str,
    has_grid: bool,
    ref_images: List[bytes],
    ref_video: Optional[bytes] = None,
    audio_bytes: Optional[bytes] = None,
):
    task = active_tasks[task_id]
    model_info = config.MODELS.get(model_key, config.MODELS[config.DEFAULT_MODEL])
    backend = model_info.get("backend", "davinci")
    category = model_info.get("category", "video")

    logger.info(f"Starting web task {task_id}: model={model_key} backend={backend} refs={len(ref_images)}")

    try:
        task["status"] = "processing"
        task["stage"] = "Подготовка референсов..."
        task["progress"] = 10

        history_manager.log_task_start(
            task_id=task_id,
            source="web",
            user_id=task.get("user_id", "web_visitor"),
            username=task.get("user_note", ""),
            model_key=model_key,
            model_name=model_info["name"],
            category=category,
            prompt=prompt,
            duration=duration,
            resolution=resolution,
            ratio=ratio,
            has_audio=generate_audio,
        )

        # Apply grid if requested
        prepared_images = list(ref_images)
        if has_grid and prepared_images:
            task["stage"] = "Наложение сетки 3×3 на референсы..."
            prepared_images = [
                image_utils.overlay_grid(b, rows=3, cols=3, thickness_mode="thick", color="contrast")
                for b in prepared_images if b
            ]

        # Submit task
        task["stage"] = f"Отправка задачи в нейросеть ({model_info['name']})..."
        task["progress"] = 20

        sub_task_id = None
        if backend == "davinci":
            prepared_refs = [
                image_utils.prepare_user_image(b, ratio) for b in prepared_images if b
            ]
            sub_task_id = await davinci_client.create_video_task(
                model_id=model_info["api_id"],
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                ratio=ratio,
                generate_audio=generate_audio,
                ref_images=prepared_refs,
                ref_mode=ref_mode,
                ref_video=ref_video if model_info.get("video_ref") else None,
            )
        elif backend == "davinci_image":
            prepared_refs = [
                image_utils.prepare_user_image(b, ratio) for b in prepared_images if b
            ]
            sub_task_id = await davinci_client.create_image_task(
                model_key=model_info["api_id"],
                prompt=prompt,
                resolution=resolution,
                ratio=ratio,
                ref_images=prepared_refs,
            )
        elif backend == "davinci_voice":
            sub_task_id = await davinci_client.create_voice_task(
                prompt=prompt,
                audio_bytes=audio_bytes,
            )
        elif backend == "v2":
            img = image_utils.prepare_user_image(prepared_images[0], ratio) if prepared_images else None
            sub_task_id = await v2_client.create_task(
                model_api_id=model_info["api_id"],
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                ratio=ratio,
                image_bytes=img,
            )
        elif backend == "grok":
            img = image_utils.prepare_user_image(prepared_images[0], ratio) if prepared_images else None
            sub_task_id = await grok_client.create_task(
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                ratio=ratio,
                channel=model_info.get("channel", "auto"),
                image_bytes=img,
            )
        elif backend == "minimax":
            img = image_utils.prepare_user_image(prepared_images[0], ratio) if prepared_images else None
            sub_task_id = await minimax_client.create_task(
                prompt=prompt,
                duration=15,
                resolution=resolution,
                ratio=ratio,
                style=model_info.get("style", "minimalist-hero"),
                image_bytes=img,
            )
        elif backend == "qwen_image":
            img = prepared_images[0] if prepared_images else None
            sub_task_id = await qwen_client.create_task(
                prompt=prompt,
                image_bytes=img,
            )
        else:
            img = (
                image_utils.prepare_user_image(prepared_images[0], ratio)
                if prepared_images
                else image_utils.generate_text_seed_image(ratio)
            )
            sub_task_id = await api_client.create_task(
                prompt=prompt,
                duration=duration,
                resolution=resolution,
                ratio=ratio,
                generate_audio=generate_audio,
                image_bytes=img,
            )

        task["sub_task_id"] = sub_task_id
        task["stage"] = f"Генерация {model_info['name']}..."
        task["progress"] = 30
        logger.info(f"Web task {task_id} backend task ID: {sub_task_id}")

        # Polling loop
        client = get_client_for_backend(backend)
        start_time = asyncio.get_event_loop().time()
        media_url = None
        poll_sleep = 3 if backend in ("grok", "minimax", "qwen_image", "davinci_image", "davinci_voice") else 5
        est_duration = 35 if category == "image" else (duration * 6 if duration > 0 else 45)

        while True:
            await asyncio.sleep(poll_sleep)
            elapsed = int(asyncio.get_event_loop().time() - start_time)
            task["elapsed"] = elapsed

            try:
                task_info = await asyncio.wait_for(client.get_task(sub_task_id), timeout=25.0)
            except Exception as poll_exc:
                logger.warning(f"Web task {task_id} polling warning: {poll_exc}")
                continue

            status = task_info.get("status")
            srv_progress = task_info.get("progress")
            task["progress"] = calculate_progress(elapsed, est_duration, srv_progress)
            task["stage"] = f"Генерация {model_info['name']} ({elapsed} сек)..."
            history_manager.update_task_progress(task_id, task["progress"], task["stage"])

            if status == "succeeded":
                if backend in ("qwen_image", "davinci_image"):
                    media_url = task_info.get("imageUrl") or task_info.get("videoUrl")
                elif backend == "davinci_voice":
                    media_url = task_info.get("audioUrl") or task_info.get("videoUrl")
                else:
                    media_url = task_info.get("videoUrl")
                break
            elif status == "failed":
                err_msg = str(task_info.get("error", "Неизвестная ошибка сервера"))
                raise RuntimeError(err_msg)

            if elapsed > 1800:
                raise RuntimeError("Превышено максимальное время генерации (30 минут)")

        # Download & Watermark
        task["stage"] = "Загрузка и обработка результата..."
        task["progress"] = 92
        ts = int(time.time())

        if category == "image":
            out_filename = f"web_{task_id}.jpg"
            out_path = OUTPUTS_DIR / out_filename
            img_bytes = await client.download_image(media_url)
            out_path.write_bytes(img_bytes)
            task["media_url"] = f"/api/media/{out_filename}"
            task["media_type"] = "image"
        elif backend == "davinci_voice":
            out_filename = f"web_{task_id}.mp3"
            out_path = OUTPUTS_DIR / out_filename
            audio_data = await davinci_client.download_audio(media_url)
            out_path.write_bytes(audio_data)
            task["media_url"] = f"/api/media/{out_filename}"
            task["media_type"] = "audio"
        else:
            # Video
            out_filename = f"web_{task_id}.mp4"
            raw_filename = f"raw_web_{task_id}.mp4"
            raw_path = VIDEOS_DIR / raw_filename
            out_path = VIDEOS_DIR / out_filename

            vid_bytes = await client.download_video(media_url)
            raw_path.write_bytes(vid_bytes)

            # Apply cyclic corner watermark
            task["stage"] = "Наложение фирменного водяного знака Poco AI..."
            task["progress"] = 96
            wm_ok = await watermark_utils.apply_watermark(raw_path, out_path)
            if not wm_ok or not out_path.exists() or out_path.stat().st_size == 0:
                raw_path.replace(out_path)
            else:
                raw_path.unlink(missing_ok=True)

            task["media_url"] = f"/api/media/{out_filename}"
            task["media_type"] = "video"

        task["status"] = "completed"
        task["progress"] = 100
        task["stage"] = "Готово!"
        history_manager.complete_task(
            task_id=task_id,
            media_url=task["media_url"],
            media_type=task["media_type"],
            elapsed=task.get("elapsed", 0),
        )
        logger.info(f"Web task {task_id} completed successfully -> {task['media_url']}")

    except Exception as e:
        logger.error(f"Web task {task_id} failed: {e}", exc_info=True)
        task["status"] = "failed"
        task["error"] = str(e)
        task["stage"] = f"Ошибка: {e}"
        history_manager.fail_task(
            task_id=task_id,
            error=str(e),
            elapsed=task.get("elapsed", 0),
        )


@app.get("/api/models")
async def get_models():
    """Return all models structured for UI."""
    video_models = []
    image_models = []
    voice_models = []

    for key, m in config.MODELS.items():
        cat = m.get("category", "video")
        item = {
            "key": key,
            "name": m.get("name"),
            "short": m.get("short"),
            "category": cat,
            "desc": m.get("desc", ""),
            "multi_ref": m.get("multi_ref", False),
            "ref_limit": m.get("ref_limit", 1),
            "has_audio": m.get("has_audio", False),
            "video_ref": m.get("video_ref", False),
            "durations": m.get("durations", config.DURATION_OPTIONS if cat == "video" else [1]),
            "resolutions": config.RESOLUTION_OPTIONS if cat == "video" else config.IMAGE_RESOLUTION_OPTIONS,
            "ratios": config.RATIO_OPTIONS if cat == "video" else config.IMAGE_RATIO_OPTIONS,
        }
        if cat == "image":
            image_models.append(item)
        elif m.get("backend") == "davinci_voice":
            voice_models.append(item)
        else:
            video_models.append(item)

    return {
        "video_models": video_models,
        "image_models": image_models,
        "voice_models": voice_models,
        "default_video": config.DEFAULT_MODEL,
        "default_image": config.DEFAULT_IMAGE_MODEL,
        "default_duration": config.DEFAULT_DURATION,
        "default_resolution": config.DEFAULT_RESOLUTION,
        "default_ratio": config.DEFAULT_RATIO,
    }


@app.get("/api/cost")
async def get_generation_cost(model_key: str, duration: int = 5, resolution: str = "720p"):
    """Calculate exact credit cost for model and parameters."""
    cost = config.calculate_credit_cost(model_key, duration, resolution)
    return {"cost": cost}


@app.get("/api/status")
async def get_system_status():
    """Return system readiness & stats."""
    return {
        "online": True,
        "davinci_auth": bool(davinci_client.token),
        "active_tasks_count": sum(1 for t in active_tasks.values() if t["status"] in ("pending", "processing")),
        "completed_count": sum(1 for t in active_tasks.values() if t["status"] == "succeeded"),
    }


@app.post("/api/auth/verify-key")
async def api_verify_key(payload: Dict[str, Any]):
    key = str(payload.get("key", "")).strip().upper()
    info = access_manager.verify_key(key)
    if not info:
        raise HTTPException(
            status_code=401,
            detail="Неверный или отозванный ключ доступа. Напишите создателю: @GermanUstinf"
        )
    return {
        "valid": True,
        "key": info["key"],
        "note": info.get("note", ""),
        "created_at": info.get("created_at"),
    }


@app.post("/api/auth/admin-login")
async def api_admin_login(payload: Dict[str, Any]):
    pwd = str(payload.get("password", "")).strip()
    if not access_manager.verify_admin_password(pwd):
        raise HTTPException(status_code=401, detail="Неверный пароль администратора/создателя")

    token = secrets.token_hex(24)
    admin_sessions.add(token)
    return {
        "valid": True,
        "token": token,
        "role": "admin",
        "username": "GermanUstinf"
    }


@app.get("/api/auth/check")
async def api_auth_check(request: Request):
    return get_auth_context(request)


@app.get("/api/admin/history")
async def api_admin_history(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    search: Optional[str] = None,
    status: Optional[str] = None,
):
    ctx = get_auth_context(request)
    if ctx.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Требуется вход администратора")
    items = history_manager.get_history(limit=limit, offset=offset, search=search, status=status)
    stats = history_manager.get_history_stats()
    return {"history": items, "stats": stats}


@app.get("/api/admin/stats")
async def api_admin_stats(request: Request):
    ctx = get_auth_context(request)
    if ctx.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Требуется вход администратора")
    return history_manager.get_history_stats()


@app.get("/api/admin/keys")
async def api_admin_keys(request: Request):
    ctx = get_auth_context(request)
    if ctx.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Требуется вход администратора")
    return {"keys": access_manager.get_all_keys()}


@app.post("/api/admin/keys/generate")
async def api_admin_generate_key(request: Request, payload: Dict[str, Any]):
    ctx = get_auth_context(request)
    if ctx.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Требуется вход администратора")
    note = str(payload.get("note", "")).strip()
    key = access_manager.generate_key(note=note, created_by="Admin Panel (@GermanUstinf)")
    return {"success": True, "key": key}


@app.post("/api/admin/keys/revoke")
async def api_admin_revoke_key(request: Request, payload: Dict[str, Any]):
    ctx = get_auth_context(request)
    if ctx.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Требуется вход администратора")
    key = str(payload.get("key", "")).strip()
    ok = access_manager.revoke_key(key)
    return {"success": ok}


@app.post("/api/admin/keys/activate")
async def api_admin_activate_key(request: Request, payload: Dict[str, Any]):
    ctx = get_auth_context(request)
    if ctx.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Требуется вход администратора")
    key = str(payload.get("key", "")).strip()
    ok = access_manager.activate_key(key)
    return {"success": ok}


@app.post("/api/admin/keys/delete")
async def api_admin_delete_key(request: Request, payload: Dict[str, Any]):
    ctx = get_auth_context(request)
    if ctx.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Требуется вход администратора")
    key = str(payload.get("key", "")).strip()
    ok = access_manager.delete_key(key)
    return {"success": ok}


@app.post("/api/generate")
async def create_generation(
    request: Request,
    background_tasks: BackgroundTasks,
    model_key: str = Form(...),
    prompt: str = Form(...),
    duration: int = Form(5),
    resolution: str = Form("720p"),
    ratio: str = Form("16:9"),
    audio: bool = Form(True),
    ref_mode: str = Form("ref"),
    has_grid: bool = Form(False),
    ref_images: List[UploadFile] = File(default=[]),
    ref_video: Optional[UploadFile] = File(default=None),
    audio_ref: Optional[UploadFile] = File(default=None),
):
    auth_ctx = get_auth_context(request)
    if not auth_ctx.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail="Доступ закрыт. Для генерации введите действующий персональный ключ доступа или запросите его у создателя: @GermanUstinf"
        )

    if model_key not in config.MODELS:
        raise HTTPException(status_code=400, detail="Неверная модель")

    model_info = config.MODELS[model_key]
    clean_prompt = prompt.strip()
    if not clean_prompt:
        clean_prompt = "Cinematic dramatic scene, photorealistic, 8k"

    # Read uploaded images
    image_bytes_list: List[bytes] = []
    for upload in ref_images:
        content = await upload.read()
        if content:
            image_bytes_list.append(content)

    # Read video reference if provided
    video_bytes: Optional[bytes] = None
    if ref_video:
        content = await ref_video.read()
        if content:
            video_bytes = content

    # Read audio reference if provided
    audio_bytes_data: Optional[bytes] = None
    if audio_ref:
        content = await audio_ref.read()
        if content:
            audio_bytes_data = content

    # Check multi_ref and limits
    ref_limit = model_info.get("ref_limit", 1)
    if not model_info.get("multi_ref"):
        image_bytes_list = image_bytes_list[:1]
    else:
        image_bytes_list = image_bytes_list[:ref_limit]

    task_id = str(uuid.uuid4())[:8]
    active_tasks[task_id] = {
        "id": task_id,
        "status": "pending",
        "progress": 5,
        "stage": "Инициализация задачи...",
        "prompt": clean_prompt,
        "model_key": model_key,
        "model_name": model_info["name"],
        "category": model_info.get("category", "video"),
        "user_id": auth_ctx.get("user_id", "web_visitor"),
        "user_note": auth_ctx.get("note", ""),
        "role": auth_ctx.get("role", "user"),
        "created_at": time.time(),
        "elapsed": 0,
        "media_url": None,
        "media_type": "video" if model_info.get("category") == "video" else "image",
        "error": None,
    }

    background_tasks.add_task(
        process_web_generation,
        task_id=task_id,
        model_key=model_key,
        prompt=clean_prompt,
        duration=duration,
        resolution=resolution,
        ratio=ratio,
        generate_audio=audio,
        ref_mode=ref_mode,
        has_grid=has_grid,
        ref_images=image_bytes_list,
        ref_video=video_bytes,
        audio_bytes=audio_bytes_data,
    )

    return {"task_id": task_id, "status": "pending"}


@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in active_tasks:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return active_tasks[task_id]


@app.get("/api/media/{filename}")
async def get_media_file(filename: str):
    # Security check: filename must not contain directory traversals
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if filename.endswith(".mp4"):
        file_path = VIDEOS_DIR / filename
        media_type = "video/mp4"
    elif filename.endswith((".jpg", ".jpeg")):
        file_path = OUTPUTS_DIR / filename
        media_type = "image/jpeg"
    elif filename.endswith(".png"):
        file_path = OUTPUTS_DIR / filename
        media_type = "image/png"
    elif filename.endswith(".mp3"):
        file_path = OUTPUTS_DIR / filename
        media_type = "audio/mpeg"
    else:
        raise HTTPException(status_code=400, detail="Unsupported media format")

    if not file_path.exists():
        # Check in outputs dir if not in videos dir
        if (OUTPUTS_DIR / filename).exists():
            file_path = OUTPUTS_DIR / filename
        elif (VIDEOS_DIR / filename).exists():
            file_path = VIDEOS_DIR / filename
        else:
            raise HTTPException(status_code=404, detail="Media file not found")

    return FileResponse(file_path, media_type=media_type)


@app.get("/api/gallery")
async def get_gallery():
    """Return all generated items for display in the gallery."""
    items = []
    # Collect videos
    for p in sorted(VIDEOS_DIR.glob("*.mp4"), key=os.path.getmtime, reverse=True):
        if p.name.startswith("raw_"):
            continue
        items.append({
            "filename": p.name,
            "url": f"/api/media/{p.name}",
            "type": "video",
            "size": p.stat().st_size,
            "mtime": p.stat().st_mtime,
        })
    # Collect images
    for p in sorted(OUTPUTS_DIR.glob("*.*"), key=os.path.getmtime, reverse=True):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            items.append({
                "filename": p.name,
                "url": f"/api/media/{p.name}",
                "type": "image",
                "size": p.stat().st_size,
                "mtime": p.stat().st_mtime,
            })
        elif p.suffix.lower() == ".mp3":
            items.append({
                "filename": p.name,
                "url": f"/api/media/{p.name}",
                "type": "audio",
                "size": p.stat().st_size,
                "mtime": p.stat().st_mtime,
            })
    return {"items": items[:30]}


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>POCO AI Studio loading...</h1>")

# Mount static folder
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def main():
    parser = argparse.ArgumentParser(description="Run POCO AI Web Studio")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=7860, help="Port to bind")
    args = parser.parse_args()

    print(f"\n==================================================")
    print(f"✨ POCO AI Web Studio started!")
    print(f"🌐 Website available at: http://localhost:{args.port}")
    print(f"🤖 Telegram Bot integration: @POCOFONAIbot")
    print(f"==================================================\n")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
