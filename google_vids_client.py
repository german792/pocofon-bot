import asyncio
import base64
import json
import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from config import (
    BASE_DIR,
    GOOGLE_VIDS_CHROME_PATH,
    GOOGLE_VIDS_HEADLESS,
    GOOGLE_VIDS_PROFILES,
    GOOGLE_VIDS_TIMEOUT_SEC,
    GOOGLE_VIDS_URL,
)

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, str], Awaitable[None]]]

PROFILES_JSON_PATH = BASE_DIR / "data" / "google_vids_profiles.json"
DEFAULT_PROFILES_ROOT = BASE_DIR / "data" / "chrome_profiles"
VIDEOS_DIR = BASE_DIR / "videos"
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

QUOTA_PATTERNS = (
    "quota",
    "limit reached",
    "daily limit",
    "usage limit",
    "rate limit",
    "too many requests",
    "out of credits",
    "insufficient credits",
    "try again later",
    "квот",
    "лимит",
    "превышен",
    "попробуйте позже",
)

UNSUPPORTED_PATTERNS = (
    "not available",
    "not supported",
    "not eligible",
    "feature is unavailable",
    "access denied",
    "request access",
    "sign in",
    "unsupported",
    "недоступ",
    "не поддерживается",
    "нет доступа",
    "войдите в аккаунт",
)

POLICY_PATTERNS = (
    "safety",
    "policy",
    "guidelines",
    "violates",
    "blocked",
    "prohibited",
    "inappropriate",
    "правил",
    "безопасност",
)


class GoogleVidsProfileError(RuntimeError):
    """Profile-level error that allows falling back to a backup Chrome profile."""


class ProfileQuotaError(GoogleVidsProfileError):
    """Raised when the active Chrome profile has exhausted its Google Vids quota."""


class ProfileUnsupportedError(GoogleVidsProfileError):
    """Raised when the active Chrome profile is not logged in or cannot run the request."""


class GoogleVidsFatalError(RuntimeError):
    """Raised on non-profile errors (e.g. policy block or missing Playwright)."""


@dataclass
class ChromeProfile:
    """Isolated Chrome profile configuration for Google Vids."""

    name: str
    user_data_dir: Path
    profile_directory: str = "Default"
    cooldown_until: float = 0.0
    last_error: str = ""
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def key(self) -> str:
        return f"{self.user_data_dir}::{self.profile_directory}"

    def is_in_cooldown(self, now: Optional[float] = None) -> bool:
        ts = time.time() if now is None else now
        return self.cooldown_until > ts


def _detect_chrome_executable() -> Optional[str]:
    """Find a local Google Chrome executable if explicitly configured or on standard paths."""
    if GOOGLE_VIDS_CHROME_PATH and Path(GOOGLE_VIDS_CHROME_PATH).exists():
        return GOOGLE_VIDS_CHROME_PATH

    candidates = [
        shutil.which("google-chrome"),
        shutil.which("chrome"),
        shutil.which("chromium"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for cand in candidates:
        if cand and Path(cand).exists():
            return str(cand)
    return None


def _parse_profile_spec(raw: str, idx: int) -> Optional[ChromeProfile]:
    """Parse a single profile specification from env string."""
    item = (raw or "").strip()
    if not item:
        return None

    name = ""
    if "=" in item:
        left, right = item.split("=", 1)
        if left.strip() and right.strip():
            name = left.strip()
            item = right.strip()

    profile_dir = "Default"
    if "|" in item:
        path_part, prof_part = item.split("|", 1)
        item = path_part.strip()
        if prof_part.strip():
            profile_dir = prof_part.strip()

    p = Path(item)
    if not p.is_absolute():
        p = BASE_DIR / p
    return ChromeProfile(
        name=name or p.name or f"profile_{idx}",
        user_data_dir=p,
        profile_directory=profile_dir,
    )


def load_chrome_profiles() -> List[ChromeProfile]:
    """Load primary and backup Chrome profiles from JSON, env, or data/chrome_profiles/."""
    profiles: List[ChromeProfile] = []
    seen_keys = set()

    if PROFILES_JSON_PATH.exists():
        try:
            raw_list = json.loads(PROFILES_JSON_PATH.read_text(encoding="utf-8"))
            if isinstance(raw_list, list):
                for idx, entry in enumerate(raw_list, start=1):
                    if not isinstance(entry, dict) or not entry.get("user_data_dir"):
                        continue
                    if entry.get("enabled", True) is False:
                        continue
                    p = Path(str(entry["user_data_dir"]))
                    if not p.is_absolute():
                        p = BASE_DIR / p
                    prof = ChromeProfile(
                        name=str(entry.get("name") or p.name or f"profile_{idx}"),
                        user_data_dir=p,
                        profile_directory=str(entry.get("profile_directory") or "Default"),
                    )
                    if prof.key not in seen_keys:
                        seen_keys.add(prof.key)
                        profiles.append(prof)
        except Exception as e:
            logger.warning(f"Failed to read {PROFILES_JSON_PATH}: {e}")

    if GOOGLE_VIDS_PROFILES:
        for idx, token in enumerate(re.split(r"[;,]", GOOGLE_VIDS_PROFILES), start=1):
            prof = _parse_profile_spec(token, idx)
            if prof and prof.key not in seen_keys:
                seen_keys.add(prof.key)
                profiles.append(prof)

    if not profiles and DEFAULT_PROFILES_ROOT.exists():
        for sub in sorted(DEFAULT_PROFILES_ROOT.iterdir()):
            if sub.is_dir():
                prof = ChromeProfile(name=sub.name, user_data_dir=sub)
                if prof.key not in seen_keys:
                    seen_keys.add(prof.key)
                    profiles.append(prof)

    if not profiles:
        default_dir = DEFAULT_PROFILES_ROOT / "profile_1"
        default_dir.mkdir(parents=True, exist_ok=True)
        profiles.append(ChromeProfile(name="profile_1", user_data_dir=default_dir))

    return profiles


def _classify_page_error(text: str) -> Optional[Exception]:
    """Inspect visible error/banner text and map it to a profile or fatal exception."""
    low = (text or "").strip().lower()
    if not low:
        return None
    if any(tok in low for tok in QUOTA_PATTERNS):
        return ProfileQuotaError(text.strip())
    if any(tok in low for tok in UNSUPPORTED_PATTERNS):
        return ProfileUnsupportedError(text.strip())
    if any(tok in low for tok in POLICY_PATTERNS):
        return GoogleVidsFatalError(text.strip())
    return None


class GoogleVidsClient:
    """Automates Google Vids Omni video generation in isolated Chrome profiles."""

    def __init__(
        self,
        profiles: Optional[Sequence[ChromeProfile]] = None,
        vids_url: Optional[str] = None,
        headless: Optional[bool] = None,
        timeout_sec: Optional[int] = None,
        quota_cooldown_sec: int = 1800,
    ):
        self.profiles: List[ChromeProfile] = list(profiles) if profiles is not None else load_chrome_profiles()
        self.vids_url = (vids_url or GOOGLE_VIDS_URL).strip()
        self.headless = GOOGLE_VIDS_HEADLESS if headless is None else bool(headless)
        self.timeout_sec = max(60, int(timeout_sec or GOOGLE_VIDS_TIMEOUT_SEC))
        self.quota_cooldown_sec = max(60, int(quota_cooldown_sec))

    def get_full_url(self, path_or_url: str) -> str:
        """Return a normalized path/URL string compatible with queue_worker."""
        return str(path_or_url or "")

    async def download_video(self, path_or_url: str) -> bytes:
        """Read a locally downloaded Google Vids MP4 clip from disk."""
        raw = str(path_or_url or "")
        if raw.startswith("file://"):
            raw = raw[7:]
        p = Path(raw)
        if not p.exists() or p.stat().st_size == 0:
            raise FileNotFoundError(f"Google Vids clip not found: {p}")
        return p.read_bytes()

    def _ordered_profiles(self) -> List[ChromeProfile]:
        """Order profiles: ready + unlocked first, then unlocked in cooldown, then locked."""
        now = time.time()
        ready = [p for p in self.profiles if not p.is_in_cooldown(now) and not p.lock.locked()]
        cooled = sorted(
            [p for p in self.profiles if p.is_in_cooldown(now) and not p.lock.locked()],
            key=lambda p: p.cooldown_until,
        )
        busy = [p for p in self.profiles if p.lock.locked()]
        return ready + cooled + busy

    async def _emit(self, cb: ProgressCallback, pct: int, stage: str) -> None:
        if cb is None:
            return
        try:
            await cb(max(1, min(98, int(pct))), stage)
        except Exception as e:
            logger.debug(f"Progress callback error: {e}")

    async def generate_video(
        self,
        prompt: str,
        duration: int = 8,
        resolution: str = "720p",
        ratio: str = "16:9",
        generate_audio: bool = True,
        ref_images: Optional[List[bytes]] = None,
        ref_mode: str = "omni",
        ref_video: Optional[bytes] = None,
        on_progress: ProgressCallback = None,
    ) -> Path:
        """Generate a video via Google Vids trying primary and backup Chrome profiles."""
        if not self.profiles:
            self.profiles = load_chrome_profiles()

        ordered = self._ordered_profiles()
        errors: List[str] = []

        for idx, profile in enumerate(ordered, start=1):
            if idx > 1:
                await self._emit(
                    on_progress,
                    5,
                    f"Переключаюсь на резервный профиль Chrome ({profile.name})...",
                )
            try:
                async with profile.lock:
                    clip_path = await self._generate_with_profile(
                        profile=profile,
                        prompt=prompt,
                        duration=duration,
                        resolution=resolution,
                        ratio=ratio,
                        generate_audio=generate_audio,
                        ref_images=ref_images or [],
                        ref_mode=ref_mode,
                        ref_video=ref_video,
                        on_progress=on_progress,
                    )
                profile.cooldown_until = 0.0
                profile.last_error = ""
                return clip_path
            except ProfileQuotaError as qe:
                profile.cooldown_until = time.time() + self.quota_cooldown_sec
                profile.last_error = str(qe)
                logger.warning(f"[google_vids] Quota exhausted on profile '{profile.name}': {qe}")
                errors.append(f"{profile.name}: квота исчерпана")
            except ProfileUnsupportedError as ue:
                profile.last_error = str(ue)
                logger.warning(f"[google_vids] Profile '{profile.name}' unsupported: {ue}")
                errors.append(f"{profile.name}: {ue}")
            except GoogleVidsFatalError:
                raise

        summary = "; ".join(errors) if errors else "нет доступных профилей"
        raise RuntimeError(f"Ни один профиль Chrome для Google Vids не смог выполнить запрос ({summary})")

    async def _generate_with_profile(
        self,
        profile: ChromeProfile,
        prompt: str,
        duration: int,
        resolution: str,
        ratio: str,
        generate_audio: bool,
        ref_images: List[bytes],
        ref_mode: str,
        ref_video: Optional[bytes],
        on_progress: ProgressCallback,
    ) -> Path:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise GoogleVidsFatalError(
                "Не установлен playwright. Выполните: pip install playwright && playwright install chromium"
            ) from exc

        profile.user_data_dir.mkdir(parents=True, exist_ok=True)
        chrome_exe = _detect_chrome_executable()

        await self._emit(on_progress, 7, f"Открываю Google Vids в профиле {profile.name}...")

        pw = await async_playwright().start()
        context = None
        try:
            launch_kwargs: Dict[str, object] = {
                "user_data_dir": str(profile.user_data_dir),
                "headless": self.headless,
                "accept_downloads": True,
                "viewport": {"width": 1440, "height": 900},
                "args": [
                    f"--profile-directory={profile.profile_directory}",
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            }
            if chrome_exe:
                launch_kwargs["executable_path"] = chrome_exe
            else:
                launch_kwargs["channel"] = "chrome"

            context = await pw.chromium.launch_persistent_context(**launch_kwargs)
            page = context.pages[0] if context.pages else await context.new_page()
            page.set_default_timeout(20000)

            await page.goto(self.vids_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(2.0)

            await self._emit(on_progress, 14, f"Проверяю доступ и квоту ({profile.name})...")
            await self._ensure_profile_supported(page)

            await self._emit(on_progress, 22, "Открываю панель генерации Omni в Google Vids...")
            await self._open_omni_generator(page)
            await self._ensure_profile_supported(page)

            with tempfile.TemporaryDirectory(prefix="gvids_refs_") as tmp_dir:
                tmp_path = Path(tmp_dir)
                if ref_images or ref_video:
                    ref_total = len(ref_images) + (1 if ref_video else 0)
                    await self._emit(on_progress, 34, f"Загружаю референсы ({ref_total} шт.)...")
                    await self._upload_references(page, ref_images, ref_video, tmp_path)

                await self._emit(
                    on_progress,
                    46,
                    f"Выставляю параметры Omni ({ratio}, {duration}с, {resolution})...",
                )
                await self._configure_omni_options(
                    page=page,
                    ratio=ratio,
                    duration=duration,
                    resolution=resolution,
                    generate_audio=generate_audio,
                    ref_mode=ref_mode,
                )

                await self._emit(on_progress, 54, "Ввожу промпт и запускаю генерацию...")
                await self._enter_prompt_and_submit(page, prompt)

                await self._poll_generation(
                    page=page,
                    duration=duration,
                    profile_name=profile.name,
                    on_progress=on_progress,
                )

                await self._emit(on_progress, 93, "Скачиваю готовый клип из Google Vids...")
                out_file = VIDEOS_DIR / f"gvids_{int(time.time())}_{os.getpid()}.mp4"
                await self._download_clip(page, context, out_file)
                return out_file
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            try:
                await pw.stop()
            except Exception:
                pass

    async def _read_visible_banner_text(self, page) -> str:
        """Collect alert/toast/dialog text for quota or compatibility detection."""
        try:
            texts = await page.evaluate(
                """() => {
                    const els = document.querySelectorAll(
                        '[role="alert"], [role="status"], [aria-live="assertive"], ' +
                        '.docs-butterbar-container, [data-error], [role="dialog"]'
                    );
                    return Array.from(els)
                        .map(el => (el.innerText || '').trim())
                        .filter(Boolean)
                        .slice(0, 6);
                }"""
            )
            return " | ".join(texts) if isinstance(texts, list) else ""
        except Exception:
            return ""

    async def _ensure_profile_supported(self, page) -> None:
        url = (page.url or "").lower()
        if "accounts.google.com" in url or "servicelogin" in url:
            raise ProfileUnsupportedError("профиль не авторизован в Google")

        banner = await self._read_visible_banner_text(page)
        err = _classify_page_error(banner)
        if err is not None:
            raise err

    async def _click_first_visible(self, page, selectors: Sequence[str], timeout_ms: int = 3500) -> bool:
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=timeout_ms)
                    return True
            except Exception:
                continue
        return False

    async def _open_omni_generator(self, page) -> None:
        """Open a new Google Vids document/AI generation drawer if not already open."""
        prompt_already = await self._find_prompt_input(page)
        if prompt_already is not None:
            return

        # Step A: on Google Vids home, click New / Blank / Help me create
        await self._click_first_visible(
            page,
            [
                'button:has-text("Help me create")',
                'button:has-text("Create a video")',
                'button:has-text("Generate video")',
                'button:has-text("Создать видео")',
                'button:has-text("Помочь создать")',
                '[aria-label*="Create new" i]',
                '[aria-label*="Blank" i]',
                '[aria-label*="Создать" i]',
                'div[role="button"]:has-text("Blank")',
            ],
        )
        await asyncio.sleep(2.0)

        if await self._find_prompt_input(page) is not None:
            return

        # Step B: inside editor, open the AI / Generate Video / Veo / Omni side panel
        opened = await self._click_first_visible(
            page,
            [
                'button:has-text("Generate video")',
                'button:has-text("Veo")',
                'button:has-text("Omni")',
                'button:has-text("Сгенерировать видео")',
                '[aria-label*="Generate video" i]',
                '[aria-label*="Video generation" i]',
                '[aria-label*="Сгенерировать видео" i]',
                '[data-tooltip*="Generate video" i]',
            ],
        )
        await asyncio.sleep(1.5)

        if not opened and await self._find_prompt_input(page) is None:
            banner = await self._read_visible_banner_text(page)
            classified = _classify_page_error(banner)
            if classified is not None:
                raise classified
            raise ProfileUnsupportedError("генератор видео Google Vids не найден в этом профиле")

    async def _find_prompt_input(self, page):
        selectors = [
            'textarea[aria-label*="prompt" i]',
            'textarea[placeholder*="Describe" i]',
            'textarea[placeholder*="prompt" i]',
            'textarea[placeholder*="Опишите" i]',
            'div[contenteditable="true"][aria-label*="prompt" i]',
            'div[contenteditable="true"][role="textbox"]',
            "textarea",
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

    async def _upload_references(
        self,
        page,
        ref_images: List[bytes],
        ref_video: Optional[bytes],
        tmp_dir: Path,
    ) -> None:
        files_to_upload: List[str] = []
        for idx, img_bytes in enumerate(ref_images[:10], start=1):
            if not img_bytes:
                continue
            p = tmp_dir / f"ref_{idx}.jpg"
            p.write_bytes(img_bytes)
            files_to_upload.append(str(p))

        if ref_video:
            vp = tmp_dir / "ref_video.mp4"
            vp.write_bytes(ref_video)
            files_to_upload.append(str(vp))

        if not files_to_upload:
            return

        file_input = page.locator('input[type="file"]').first
        if await file_input.count() > 0:
            await file_input.set_input_files(files_to_upload)
            await asyncio.sleep(1.5)
            return

        upload_btn_selectors = [
            'button:has-text("Add reference")',
            'button:has-text("Upload")',
            'button:has-text("Добавить референс")',
            '[aria-label*="reference" i]',
            '[aria-label*="Upload" i]',
            '[aria-label*="Attach" i]',
            '[aria-label*="Прикрепить" i]',
        ]
        for sel in upload_btn_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    async with page.expect_file_chooser(timeout=5000) as fc_info:
                        await btn.click()
                    chooser = await fc_info.value
                    await chooser.set_files(files_to_upload)
                    await asyncio.sleep(1.5)
                    return
            except Exception:
                continue

        raise ProfileUnsupportedError("профиль не поддерживает загрузку референсов")

    async def _configure_omni_options(
        self,
        page,
        ratio: str,
        duration: int,
        resolution: str,
        generate_audio: bool,
        ref_mode: str,
    ) -> None:
        """Select Omni mode, aspect ratio, duration, resolution, and audio in Google Vids."""
        # Switch to Omni mode if available
        await self._click_first_visible(
            page,
            [
                'button:has-text("Omni")',
                '[role="tab"]:has-text("Omni")',
                '[role="option"]:has-text("Omni")',
            ],
            timeout_ms=2000,
        )

        # Aspect ratio (16:9 / 9:16 / 1:1)
        if ratio:
            await self._click_first_visible(
                page,
                [
                    f'button:has-text("{ratio}")',
                    f'[role="radio"]:has-text("{ratio}")',
                    f'[role="option"]:has-text("{ratio}")',
                    f'[aria-label*="{ratio}"]',
                ],
                timeout_ms=2000,
            )

        # Duration (e.g. 5s, 8s, 10s, 15s)
        if duration and duration > 0:
            await self._click_first_visible(
                page,
                [
                    f'button:has-text("{duration}s")',
                    f'button:has-text("{duration} с")',
                    f'[role="option"]:has-text("{duration}s")',
                ],
                timeout_ms=2000,
            )

        # Resolution (720p / 1080p)
        if resolution:
            await self._click_first_visible(
                page,
                [
                    f'button:has-text("{resolution}")',
                    f'[role="option"]:has-text("{resolution}")',
                ],
                timeout_ms=2000,
            )

        # Audio toggle if present
        try:
            audio_toggle = page.locator(
                '[role="switch"][aria-label*="Audio" i], [role="switch"][aria-label*="Звук" i]'
            ).first
            if await audio_toggle.count() > 0 and await audio_toggle.is_visible():
                checked = (await audio_toggle.get_attribute("aria-checked") or "").lower() == "true"
                if checked != bool(generate_audio):
                    await audio_toggle.click(timeout=2000)
        except Exception:
            pass

        # Frame mode hint if user picked frames instead of omni
        if ref_mode == "frames":
            await self._click_first_visible(
                page,
                [
                    'button:has-text("Frames")',
                    'button:has-text("Start & End")',
                    '[role="tab"]:has-text("Frames")',
                ],
                timeout_ms=1500,
            )

    async def _enter_prompt_and_submit(self, page, prompt: str) -> None:
        prompt_loc = await self._find_prompt_input(page)
        if prompt_loc is None:
            raise ProfileUnsupportedError("поле ввода промпта недоступно в этом профиле")

        await prompt_loc.click()
        await prompt_loc.fill(prompt)
        await asyncio.sleep(0.4)

        submitted = await self._click_first_visible(
            page,
            [
                'button:has-text("Generate"):not([disabled])',
                'button:has-text("Create"):not([disabled])',
                'button:has-text("Создать"):not([disabled])',
                'button:has-text("Сгенерировать"):not([disabled])',
                '[aria-label*="Generate" i]:not([disabled])',
            ],
            timeout_ms=4000,
        )
        if not submitted:
            await prompt_loc.press("Enter")

        await asyncio.sleep(1.5)
        banner = await self._read_visible_banner_text(page)
        err = _classify_page_error(banner)
        if err is not None:
            raise err

    async def _poll_generation(
        self,
        page,
        duration: int,
        profile_name: str,
        on_progress: ProgressCallback,
    ) -> None:
        """Poll Google Vids until the video clip is ready or an error occurs."""
        start_ts = time.time()
        est_total = max(35.0, float(duration or 8) * 6.0)
        last_pct = 58

        while True:
            elapsed = time.time() - start_ts
            if elapsed > self.timeout_sec:
                raise TimeoutError("Превышено время ожидания генерации в Google Vids")

            banner = await self._read_visible_banner_text(page)
            err = _classify_page_error(banner)
            if err is not None:
                raise err

            # Check if download button or generated <video> is ready
            ready = await page.evaluate(
                """() => {
                    const dl = document.querySelector(
                        'button[aria-label*="Download" i], button[aria-label*="Export" i], ' +
                        'a[download], button[aria-label*="Скачать" i]'
                    );
                    if (dl && !dl.disabled) return true;
                    const vid = document.querySelector('video[src], video source[src]');
                    if (vid) {
                        const s = vid.getAttribute('src') || '';
                        if (s.startsWith('blob:') || s.startsWith('http')) return true;
                    }
                    return false;
                }"""
            )
            if ready:
                await self._emit(on_progress, 92, "Клип готов, подготавливаю скачивание...")
                return

            # Try reading numeric progress from DOM (e.g. "64%"), fallback to smooth estimate
            dom_pct = await page.evaluate(
                """() => {
                    const pb = document.querySelector('[role="progressbar"][aria-valuenow]');
                    if (pb) {
                        const v = Number(pb.getAttribute('aria-valuenow'));
                        if (!Number.isNaN(v)) return v;
                    }
                    return null;
                }"""
            )
            if isinstance(dom_pct, (int, float)) and 0 < dom_pct < 100:
                pct = max(last_pct, min(91, int(58 + dom_pct * 0.33)))
            else:
                ratio_done = min(0.95, elapsed / est_total)
                pct = max(last_pct, min(91, int(58 + ratio_done * 33)))

            if pct > last_pct or int(elapsed) % 6 == 0:
                last_pct = pct
                await self._emit(
                    on_progress,
                    pct,
                    f"Генерация в Google Vids ({profile_name})...",
                )

            await asyncio.sleep(2.5)

    async def _download_clip(self, page, context, output_path: Path) -> None:
        """Download the finished video clip from Google Vids to output_path."""
        dl_selectors = [
            'button[aria-label*="Download" i]',
            'button:has-text("Download")',
            'button:has-text("Скачать")',
            'button[aria-label*="Export" i]',
            'a[download]',
        ]
        for sel in dl_selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    async with page.expect_download(timeout=30000) as dl_info:
                        await loc.click()
                    download = await dl_info.value
                    await download.save_as(str(output_path))
                    if output_path.exists() and output_path.stat().st_size > 0:
                        return
            except Exception:
                continue

        # Fallback: extract <video src> (blob: or https://) directly
        src = await page.evaluate(
            """() => {
                const v = document.querySelector('video[src]') || document.querySelector('video source[src]');
                return v ? (v.currentSrc || v.getAttribute('src') || '') : '';
            }"""
        )
        if not src:
            raise RuntimeError("Не удалось найти готовый клип для скачивания в Google Vids")

        if src.startswith("blob:"):
            b64_data = await page.evaluate(
                """async (blobUrl) => {
                    const resp = await fetch(blobUrl);
                    const buf = await resp.arrayBuffer();
                    const bytes = new Uint8Array(buf);
                    let bin = '';
                    const chunk = 0x8000;
                    for (let i = 0; i < bytes.length; i += chunk) {
                        bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
                    }
                    return btoa(bin);
                }""",
                src,
            )
            output_path.write_bytes(base64.b64decode(b64_data))
        else:
            resp = await context.request.get(src, timeout=60000)
            if not resp.ok:
                raise RuntimeError(f"Ошибка скачивания клипа ({resp.status})")
            output_path.write_bytes(await resp.body())

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("Скачанный файл клипа оказался пустым")
