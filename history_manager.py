"""
POCO AI Studio — Generation History Manager
Stores persistent generation history in SQLite database (data/history.db)
for admin audit, viewing, downloading, and statistics.
"""

import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import config

DATA_DIR = config.BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "history.db"


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS generations (
                id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                source TEXT NOT NULL,
                user_id TEXT,
                username TEXT,
                model_key TEXT NOT NULL,
                model_name TEXT NOT NULL,
                category TEXT NOT NULL,
                prompt TEXT NOT NULL,
                duration INTEGER DEFAULT 5,
                resolution TEXT DEFAULT '720p',
                ratio TEXT DEFAULT '16:9',
                has_audio INTEGER DEFAULT 1,
                status TEXT NOT NULL,
                stage TEXT,
                progress INTEGER DEFAULT 0,
                media_url TEXT,
                media_type TEXT,
                elapsed REAL DEFAULT 0,
                error TEXT
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gen_created_at ON generations(created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gen_status ON generations(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gen_model ON generations(model_key);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_gen_source ON generations(source);")
        conn.commit()


# Initialize on import
init_db()


def log_task_start(
    task_id: str,
    source: str = "web",
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    model_key: str = "s2_5",
    model_name: str = "Seedance 2.5",
    category: str = "video",
    prompt: str = "",
    duration: int = 5,
    resolution: str = "720p",
    ratio: str = "16:9",
    has_audio: bool = True,
    status: str = "pending",
    stage: str = "Инициализация...",
    progress: int = 5,
) -> None:
    """Record task inception in history."""
    now = time.time()
    try:
        with _get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO generations (
                    id, created_at, source, user_id, username,
                    model_key, model_name, category, prompt,
                    duration, resolution, ratio, has_audio,
                    status, stage, progress, media_url, media_type,
                    elapsed, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    now,
                    source,
                    user_id or "web_user",
                    username or "",
                    model_key,
                    model_name,
                    category,
                    prompt,
                    duration,
                    resolution,
                    ratio,
                    1 if has_audio else 0,
                    status,
                    stage,
                    progress,
                    None,
                    category,
                    0.0,
                    None,
                ),
            )
            conn.commit()
    except Exception as e:
        print(f"[history_manager] Error logging task start: {e}")


def update_task_progress(task_id: str, progress: int, stage: str, status: str = "processing") -> None:
    """Update task progress during generation."""
    try:
        with _get_connection() as conn:
            conn.execute(
                """
                UPDATE generations 
                SET progress = ?, stage = ?, status = ?
                WHERE id = ?
                """,
                (progress, stage, status, task_id),
            )
            conn.commit()
    except Exception as e:
        print(f"[history_manager] Error updating task progress: {e}")


def complete_task(
    task_id: str,
    media_url: str,
    media_type: str = "video",
    elapsed: float = 0.0,
) -> None:
    """Mark task as successfully completed with resulting media URL."""
    try:
        with _get_connection() as conn:
            conn.execute(
                """
                UPDATE generations 
                SET status = 'completed', stage = 'Готово!', progress = 100,
                    media_url = ?, media_type = ?, elapsed = ?
                WHERE id = ?
                """,
                (media_url, media_type, round(elapsed, 1), task_id),
            )
            conn.commit()
    except Exception as e:
        print(f"[history_manager] Error completing task: {e}")


def fail_task(task_id: str, error: str, elapsed: float = 0.0) -> None:
    """Mark task as failed with error explanation."""
    try:
        with _get_connection() as conn:
            conn.execute(
                """
                UPDATE generations 
                SET status = 'failed', stage = ?, progress = 0,
                    error = ?, elapsed = ?
                WHERE id = ?
                """,
                (f"Ошибка: {error}", error, round(elapsed, 1), task_id),
            )
            conn.commit()
    except Exception as e:
        print(f"[history_manager] Error failing task: {e}")


def get_history(
    limit: int = 50,
    offset: int = 0,
    source: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve filtered generation history for admin panel."""
    query = "SELECT * FROM generations WHERE 1=1"
    params: List[Any] = []

    if source:
        query += " AND source = ?"
        params.append(source)
    if status:
        query += " AND status = ?"
        params.append(status)
    if search:
        query += " AND (prompt LIKE ? OR model_name LIKE ? OR user_id LIKE ?)"
        wild = f"%{search}%"
        params.extend([wild, wild, wild])

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    try:
        with _get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[history_manager] Error fetching history: {e}")
        return []


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Get single task by ID."""
    try:
        with _get_connection() as conn:
            row = conn.execute("SELECT * FROM generations WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None
    except Exception as e:
        print(f"[history_manager] Error fetching task {task_id}: {e}")
        return None


def get_history_stats() -> Dict[str, Any]:
    """Calculate overall statistics for admin dashboard."""
    try:
        with _get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0]
            completed = conn.execute("SELECT COUNT(*) FROM generations WHERE status = 'completed'").fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM generations WHERE status = 'failed'").fetchone()[0]
            
            # Count by category
            videos = conn.execute("SELECT COUNT(*) FROM generations WHERE category = 'video'").fetchone()[0]
            images = conn.execute("SELECT COUNT(*) FROM generations WHERE category = 'image'").fetchone()[0]
            voices = conn.execute("SELECT COUNT(*) FROM generations WHERE category = 'voice'").fetchone()[0]

            # Top models
            top_rows = conn.execute(
                """
                SELECT model_name, COUNT(*) as cnt 
                FROM generations 
                GROUP BY model_name 
                ORDER BY cnt DESC LIMIT 5
                """
            ).fetchall()
            top_models = [{"model": r["model_name"], "count": r["cnt"]} for r in top_rows]

            return {
                "total": total,
                "completed": completed,
                "failed": failed,
                "videos": videos,
                "images": images,
                "voices": voices,
                "top_models": top_models,
            }
    except Exception as e:
        print(f"[history_manager] Error fetching stats: {e}")
        return {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "videos": 0,
            "images": 0,
            "voices": 0,
            "top_models": [],
        }
