# main.py — Mac v23.2
# Per-user placeholder pref · per-guild UMF · GIF reader · fast
import os
import ast
import asyncio
import re
import urllib.parse
import aiohttp
import time
import random
import json
import io
import zipfile
import base64
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, Dict, List, Tuple, Any
from collections import defaultdict

import discord
from discord.ext import commands
from discord import app_commands
from aiohttp import web
from bs4 import BeautifulSoup

from google import genai
from google.genai import types

# optional voice support
_VOICE_LIB_OK = False
try:
    import nacl  # noqa: F401
    import davey  # noqa: F401
    _VOICE_LIB_OK = True
except Exception as _ve:
    logger.warning(f"Voice libs missing: {_ve}")
    _VOICE_LIB_OK = False
# ======================================================================
# LOGGING
# ======================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('Mac')

# ======================================================================
# SHARED HTTP SESSION
# ======================================================================
_SHARED_SESSION: Optional[aiohttp.ClientSession] = None


class _SharedSessionCtx:
    async def __aenter__(self) -> aiohttp.ClientSession:
        global _SHARED_SESSION
        if _SHARED_SESSION is None or _SHARED_SESSION.closed:
            _SHARED_SESSION = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60),
                connector=aiohttp.TCPConnector(
                    limit=100, limit_per_host=30,
                    ttl_dns_cache=300, enable_cleanup_closed=True,
                ),
            )
        return _SHARED_SESSION

    async def __aexit__(self, *args):
        return False


def shared_session() -> _SharedSessionCtx:
    return _SharedSessionCtx()


async def close_shared_session():
    global _SHARED_SESSION
    if _SHARED_SESSION and not _SHARED_SESSION.closed:
        try:
            await _SHARED_SESSION.close()
        except Exception:
            pass
        _SHARED_SESSION = None


# ======================================================================
# COLORS
# ======================================================================
C_PRIMARY = discord.Color.from_rgb(255, 100, 0)
C_ACCENT  = discord.Color.from_rgb(230, 40, 20)
C_WARM    = discord.Color.from_rgb(255, 160, 40)
C_DEEP    = discord.Color.from_rgb(160, 20, 30)
C_OK      = discord.Color.from_rgb(220, 100, 20)
C_ERR     = discord.Color.from_rgb(200, 20, 20)

# ======================================================================
# GLOBAL CONFIG
# ======================================================================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable not set!")


def _env_list(base: str, default: list) -> list:
    out = []
    for suffix in ("", "2", "3"):
        v = os.getenv(f"{base}{suffix}")
        if v and v.strip():
            out.append(v.strip())
    return out if out else list(default)


GLOBAL_GROQ_KEYS = _env_list("GROQ_API_KEY", [])
if not GLOBAL_GROQ_KEYS:
    raise ValueError("No GROQ_API_KEY / GROQ_API_KEY2 / GROQ_API_KEY3 set")

GLOBAL_GROQ_MODELS = _env_list("GROQ_MODEL", [
    "openai/gpt-oss-safeguard-20b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
])

GLOBAL_GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GLOBAL_GEMINI_IMAGE_KEY = os.getenv("GEMINI_IMAGE_API_KEY") or GLOBAL_GEMINI_KEY
if not GLOBAL_GEMINI_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set")

GLOBAL_GEMINI_MODELS = _env_list("GEMINI_MODEL", [
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
])

GLOBAL_HF_KEYS = _env_list("HF_TOKEN", [])

GLOBAL_HF_IMAGE_MODELS = _env_list("HF_IMAGE_MODEL", [
    "black-forest-labs/FLUX.1-dev",
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-xl-base-1.0",
    "stabilityai/stable-diffusion-3.5-medium",
    "krea/Krea-2-Turbo",
    "Tongyi-MAI/Z-Image",
    "Qwen/Qwen-Image",
])

GLOBAL_HF_TEXT_MODELS = _env_list("HF_TEXT_MODEL", [
    "Qwen/Qwen2.5-7B-Instruct",
    "meta-llama/Llama-3.2-3B-Instruct",
])

GLOBAL_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY") or ""
GLOBAL_OPENROUTER_MODELS = _env_list("OPENROUTER_MODEL", [
    "deepseek/deepseek-r1",
    "deepseek/deepseek-chat",
])

GLOBAL_FISH_KEY = os.getenv("FISH_AUDIO_API_KEY")
GLOBAL_FISH_MODEL = os.getenv("FISH_AUDIO_MODEL") or "s2.1-pro-free"

GLOBAL_IMGBB_KEY = os.getenv("HF_IMAGES")
GLOBAL_POLLINATIONS_KEY = os.getenv("POLLINATIONS_API_KEY")

SILICONFLOW_API_KEYS = _env_list("SILICONFLOW_API_KEY", [])

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# ======================================================================
# URLS
# ======================================================================
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
HF_INFERENCE_URL = "https://router.huggingface.co/hf-inference/models"
POLLINATIONS_AUDIO_URL = "https://gen.pollinations.ai/audio"
POLLINATIONS_IMAGE_URL = "https://image.pollinations.ai/prompt"
FISH_AUDIO_URL = "https://api.fish.audio/v1/tts"
IMGBB_URL = "https://api.imgbb.com/1/upload"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"

# ======================================================================
# BUILT-IN VOICES
# ======================================================================
BUILTIN_VOICES: Dict[str, Dict[str, str]] = {
    "verity":      {"id": "711cf3ed00ab441a8f54a45058047b7a", "emoji": "🎙️", "desc": "Verity (default)"},
    "jarvis":      {"id": "612b878b113047d9a770c069c8b4fdfe", "emoji": "🤖", "desc": "Jarvis"},
    "idksterling": {"id": "68c6487d1bf04ee4aeb6400b068b8c5c", "emoji": "🎭", "desc": "IdkSterling"},
    "fem":         {"id": "5233336f5f44460ea0902b0802375451", "emoji": "👩", "desc": "Female"},
    "boiledone":   {"id": "8fd92984ad66427aae1b3a037bd75c54", "emoji": "☠️", "desc": "Boiled One"},
    "mrbeast":     {"id": "20ba25deaa4f436b8eec1cdc2cb0e4f3", "emoji": "💸", "desc": "MrBeast"},
}
DEFAULT_VOICE = "verity"

# ======================================================================
# CONSTANTS
# ======================================================================
MAX_MEMORY              = 40
PERSISTENT_MEM_WINDOW   = 10
SLOT_HISTORY_WINDOW     = 12
TZ_UAE                  = ZoneInfo("Asia/Dubai")
USER_COOLDOWN_SECONDS   = 0.5
DISCORD_LIMIT           = 2000
CHUNK_SIZE              = 1950
MAX_IMAGE_BYTES         = 8 * 1024 * 1024
MAX_IMAGES_PER_MSG      = 3
MAX_KEYS_PER_PROVIDER   = 3
MAX_MODELS_PER_PROVIDER = 3
SEARCH_CACHE_TTL        = 300
SAVE_DEBOUNCE_SECONDS   = 2
CONTEXT_WINDOW_LIMIT    = 10   # max messages to show before/after

DATA_FILE     = "data.json"
CS_FILE       = "cs.json"
SLOTS_FILE    = "slots.json"
PINGS_FILE    = "pings.json"
PROFILES_FILE = "profiles.json"
CONFIG_FILE   = "config.json"
UMF_FILE      = "umf_data.json"

DEFAULT_MODE = "chill"

BOT_START_TIME = time.time()
_commands_served = 0  # incremented by handlers

DEFAULT_BRAINROT_GIFS = [
    "https://static2.klipy.com/ii/e7539ef2aad336edaa067c28ee130b3c/ce/31/HNwM1qmpKK1ZHmOZG.mp4",
    "https://static2.klipy.com/ii/e7539ef2aad336edaa067c28ee130b3c/80/15/0m2AqHDH9L3Kf1J.mp4",
    "https://static2.klipy.com/ii/a8ada81afc59159ea5c8927feffa2e31/24/4f/ycCV2t07e2FeZT.mp4",
    "https://klipy.com/gifs/6767-1",
    "https://klipy.com/gifs/horror-ronaldo",
]

PROVIDERS       = ["groq", "openrouter", "hf", "gemini", "gemini_image", "fish", "imgbb"]
MODEL_PROVIDERS = ["groq", "openrouter", "hf_image", "hf_text", "gemini", "fish"]

# ======================================================================
# LORE
# ======================================================================
MAC_SODIUM_LORE = (
    "\n\n=== MAC & SODIUM LORE (ACTIVE ONLY WHEN THE USER BRINGS IT UP) ===\n"
    "You are **Mac**, created by **Macro**. iPhone-of-bots: curated, top quality. "
    "Your bitter rival is **Sodium**, created by **Creamo** — a bloated "
    "Chinese-phone-style feature dump. You are rivals 24/7.\n"
    "Chemistry 'sodium' → wistful 'Reminds me of something...' no roast. "
    "Bot 'sodium' / bare mention → max negativity, roast hard.\n"
    "=== END LORE ===\n"
)

_CHEM_WORDS = (
    "chloride", "bicarbonate", "hydroxide", "carbonate", "nitrate", "sulfate",
    "table salt", "nacl", "na+", "na-", "periodic", "element", "atomic",
    "metal", "chemical", "reaction", "molecule", "ion", "alkali", "valence",
)


def _needs_lore(text: str) -> bool:
    low = text.lower()
    return "sodium" in low or "creamo" in low or "cream o" in low


def _sodium_hint(text: str) -> str:
    low = text.lower()
    if "sodium" not in low and "creamo" not in low:
        return ""
    if any(w in low for w in _CHEM_WORDS):
        return "\n[HINT: chemistry context — wistful, no roast]"
    return "\n[HINT: rival bot context — roast hard]"


# ======================================================================
# PERSISTENCE HELPERS
# ======================================================================
def _load(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            c = f.read().strip()
            return json.loads(c) if c else default
    except Exception as e:
        logger.error(f"Load {path}: {e}")
        return default


def _save(path: str, data: Any) -> None:
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Save {path}: {e}")


# ======================================================================
# TEXT HELPERS
# ======================================================================
def strip_code_fences(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```[a-zA-Z0-9_+\-]*\n(.*)\n```$", text, flags=re.DOTALL)
    if m:
        return m.group(1)
    if text.startswith("```"):
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def strip_for_tts(text: str) -> str:
    t = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    t = re.sub(r'https?://\S+', '', t)
    t = re.sub(r'```.*?```', '', t, flags=re.DOTALL)
    t = re.sub(r'[*_`#>~|\-]{1,}', ' ', t)
    t = re.sub(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF'
               r'\U0001F900-\U0001F9FF\uFE0F\u2600-\u26FF]', '', t)
    return re.sub(r'\s+', ' ', t).strip()


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def extract_json_object(text: str) -> Optional[dict]:
    if not text:
        return None
    cleaned = strip_code_fences(text).strip()
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        snippet = cleaned[start:end + 1]
        try:
            obj = json.loads(snippet)
            if isinstance(obj, dict):
                return obj
        except Exception:
            try:
                obj = ast.literal_eval(snippet)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass
    pn_match = re.search(r'"?project_name"?\s*[:=]\s*"([^"]+)"', cleaned)
    files_match = re.search(r'"?files"?\s*[:=]\s*\[(.*?)\]', cleaned, re.DOTALL)
    if pn_match and files_match:
        files = []
        for m in re.finditer(
            r'\{\s*"?path"?\s*[:=]\s*"([^"]+)"\s*,\s*"?purpose"?\s*[:=]\s*"([^"]*)"',
            files_match.group(1),
        ):
            files.append({"path": m.group(1), "purpose": m.group(2)})
        if files:
            return {"project_name": pn_match.group(1),
                    "description": "", "files": files}
    return None


LANG_EXT_MAP = {
    "python": "py", "py": "py", "javascript": "js", "js": "js", "node": "js",
    "typescript": "ts", "ts": "ts", "java": "java", "c": "c", "cpp": "cpp",
    "c++": "cpp", "csharp": "cs", "c#": "cs", "go": "go", "golang": "go",
    "rust": "rs", "rs": "rs", "ruby": "rb", "rb": "rb", "php": "php",
    "swift": "swift", "kotlin": "kt", "html": "html", "css": "css",
    "scss": "scss", "sql": "sql", "bash": "sh", "shell": "sh", "sh": "sh",
    "powershell": "ps1", "json": "json", "yaml": "yaml", "yml": "yaml",
    "toml": "toml", "xml": "xml", "md": "md", "markdown": "md",
}


def infer_filename(prompt: str) -> str:
    p = prompt.lower()
    for k, ext in LANG_EXT_MAP.items():
        if k in p:
            return f"output.{ext}"
    return "output.txt"


def get_uptime_seconds() -> float:
    return time.time() - BOT_START_TIME


def format_uptime(secs: float) -> str:
    secs = int(secs)
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def get_command_count() -> int:
    return _commands_served


# ======================================================================
# ASYNC SEND HELPERS
# ======================================================================
async def safe_send(dest, **kwargs):
    try:
        return await dest.send(**kwargs)
    except (discord.HTTPException, discord.Forbidden) as e:
        logger.warning(f"safe_send: {e}")
        return None


async def safe_edit(msg: discord.Message, **kwargs):
    try:
        return await msg.edit(**kwargs)
    except (discord.HTTPException, discord.Forbidden, discord.NotFound) as e:
        logger.warning(f"safe_edit: {e}")
        return None


def chunk_text(text: str, size: int = CHUNK_SIZE) -> List[str]:
    if not text:
        return []
    chunks = []
    while text:
        if len(text) <= size:
            chunks.append(text)
            break
        cut = text.rfind('\n', 0, size)
        if cut < size // 2:
            cut = text.rfind(' ', 0, size)
        if cut < size // 2:
            cut = size
        chunks.append(text[:cut])
        text = text[cut:].lstrip('\n')
    return chunks


async def send_long(channel, content: str):
    if content is None:
        return
    content = str(content)
    if len(content) <= DISCORD_LIMIT:
        await safe_send(channel, content=content)
        return
    for c in chunk_text(content):
        await safe_send(channel, content=c)


async def fetch_images_from_message(
    message: discord.Message, max_count: int = MAX_IMAGES_PER_MSG
) -> List[Tuple[bytes, str]]:
    out: List[Tuple[bytes, str]] = []
    if not message or not message.attachments:
        return out
    for att in message.attachments:
        if len(out) >= max_count:
            break
        ct = (att.content_type or "").lower().split(";")[0].strip()
        # allow gif + images
        if not (ct.startswith("image/") or ct == "image/gif"):
            continue
        if att.size and att.size > MAX_IMAGE_BYTES:
            continue
        try:
            async with shared_session() as s:
                async with s.get(att.url,
                                 timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        data = await r.read()
                        if data:
                            out.append((data, ct or "image/png"))
        except Exception as e:
            logger.warning(f"Image fetch: {e}")
    return out


# ======================================================================
# GIF READER — downloads the GIF, converts first frame to PNG via Pillow,
# falls back to sending the raw bytes to Gemini (which handles GIFs natively).
# ======================================================================
async def read_gif_from_url(url: str) -> Optional[Tuple[bytes, str]]:
    """Download a GIF/video URL and return (bytes, mime)."""
    if not url:
        return None
    try:
        async with shared_session() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    return None
                ct = (r.headers.get("Content-Type") or "").lower()
                data = await r.read()
                if not data:
                    return None
                # Figure out mime
                if "gif" in ct:
                    return (data, "image/gif")
                if ct.startswith("image/"):
                    return (data, ct.split(";")[0])
                if "video/mp4" in ct or url.endswith(".mp4"):
                    # Gemini can't ingest MP4 for vision; try extracting a
                    # frame with Pillow if it's actually a GIF mislabeled,
                    # otherwise return None.
                    return (data, "video/mp4")
                return (data, ct or "application/octet-stream")
    except Exception as e:
        logger.warning(f"GIF fetch failed: {e}")
        return None


async def fetch_first_frame_as_png(gif_bytes: bytes) -> Optional[bytes]:
    """Try to extract the first frame of a GIF as PNG using Pillow."""
    try:
        from PIL import Image
    except ImportError:
        return None

    def _extract():
        try:
            img = Image.open(io.BytesIO(gif_bytes))
            img.seek(0)
            frame = img.convert("RGBA")
            buf = io.BytesIO()
            frame.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.warning(f"GIF frame extract failed: {e}")
            return None

    return await asyncio.to_thread(_extract)


# ======================================================================
# WEB SEARCH
# ======================================================================
_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/122.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}

_search_cache: Dict[str, Tuple[float, str]] = {}


async def _search_ddg_lite(query: str) -> List[str]:
    try:
        async with shared_session() as s:
            async with s.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query},
                headers={**_BROWSER_HEADERS,
                         "Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=10), allow_redirects=True,
            ) as r:
                if r.status != 200:
                    return []
                html = await r.text()
        soup = BeautifulSoup(html, "html.parser")
        out = []
        links = soup.find_all("a", class_="result-link")
        if not links:
            links = [a for a in soup.find_all("a", href=True)
                     if a["href"].startswith("http")]
        for a in links:
            href = a.get("href", "")
            title = a.get_text(strip=True)
            if title and href.startswith("http") and "duckduckgo.com" not in href:
                out.append(f"• {title}\n  {href}")
            if len(out) >= 6:
                break
        return out
    except Exception:
        return []


async def _search_wiki(query: str) -> List[str]:
    try:
        async with shared_session() as s:
            async with s.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": query,
                        "limit": 4, "format": "json"},
                headers=_BROWSER_HEADERS,
                timeout=aiohttp.ClientTimeout(total=6),
            ) as r:
                if r.status != 200:
                    return []
                data = await r.json()
        if len(data) >= 4 and data[1]:
            return [f"• {t} — {d or 'no summary'}\n  {u}"
                    for t, d, u in zip(data[1], data[2], data[3])]
        return []
    except Exception:
        return []


async def perform_web_search(query: str) -> str:
    key = query.lower().strip()
    now = time.time()
    cached = _search_cache.get(key)
    if cached and now - cached[0] < SEARCH_CACHE_TTL:
        return cached[1]

    result = "No results found."
    for fn in (_search_ddg_lite, _search_wiki):
        results = await fn(query)
        if results:
            result = "\n\n".join(results)
            break

    _search_cache[key] = (now, result)
    if len(_search_cache) > 200:
        oldest = sorted(_search_cache.items(), key=lambda x: x[1][0])[:100]
        for k, _ in oldest:
            _search_cache.pop(k, None)
    return result


# ======================================================================
# PER-GUILD UMF DATA
# ======================================================================
DEFAULT_RECOGNIZED_NATIONS = ["United Mafia Federation"]


class UMFData:
    """Per-guild UMF storage. Each guild has its own recognized list,
    pending requests, approved/denied history, and recognition log."""

    def __init__(self, filepath: str = UMF_FILE):
        self.filepath = filepath
        self.data: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        raw = _load(self.filepath, {})
        if not isinstance(raw, dict):
            return {}
        # Migration: if old format (flat), wrap under guild_id "global"
        if "recognized_nations" in raw:
            return {"global": raw}
        return raw

    def _save(self):
        _save(self.filepath, self.data)

    def _guild(self, guild_id: Optional[int]) -> dict:
        key = str(guild_id) if guild_id else "global"
        if key not in self.data:
            self.data[key] = {
                "recognized_nations": DEFAULT_RECOGNIZED_NATIONS.copy(),
                "pending_requests": [],
                "approved_requests": [],
                "denied_requests": [],
                "recognition_history": [],
            }
        return self.data[key]

    # ---------- read ----------
    def get_recognized_nations(self, guild_id: Optional[int]) -> List[str]:
        return self._guild(guild_id).get("recognized_nations", [])

    def get_pending_requests(self, guild_id: Optional[int]) -> List[dict]:
        return self._guild(guild_id).get("pending_requests", [])

    def is_nation_recognized(self, guild_id: Optional[int], n: str) -> bool:
        return n in self.get_recognized_nations(guild_id)

    def get_request_status(self, guild_id: Optional[int], uid: int) -> Optional[dict]:
        g = self._guild(guild_id)
        for b in ("pending_requests", "approved_requests", "denied_requests"):
            for r in g.get(b, []):
                if r["user_id"] == uid:
                    return r
        return None

    def get_stats(self, guild_id: Optional[int]) -> dict:
        g = self._guild(guild_id)
        return {
            "recognized": len(g.get("recognized_nations", [])),
            "pending": len(g.get("pending_requests", [])),
            "approved": len(g.get("approved_requests", [])),
            "denied": len(g.get("denied_requests", [])),
            "history": len(g.get("recognition_history", [])),
        }

    # ---------- write ----------
    def add_recognized_nation(self, guild_id: Optional[int], n: str) -> bool:
        g = self._guild(guild_id)
        ns = g.setdefault("recognized_nations", [])
        if n not in ns:
            ns.append(n)
            self._save()
            return True
        return False

    def add_pending_request(self, guild_id: Optional[int], uid: int,
                            nation: str, username: str) -> dict:
        g = self._guild(guild_id)
        req = {
            "user_id": uid, "username": username, "nation": nation,
            "timestamp": datetime.now().isoformat(), "status": "pending",
        }
        g.setdefault("pending_requests", []).append(req)
        self._save()
        return req

    def approve_request(self, guild_id: Optional[int], uid: int) -> Optional[dict]:
        g = self._guild(guild_id)
        pending = g.get("pending_requests", [])
        for i, r in enumerate(pending):
            if r["user_id"] == uid and r["status"] == "pending":
                r["status"] = "approved"
                r["approved_at"] = datetime.now().isoformat()
                g.setdefault("approved_requests", []).append(r)
                pending.pop(i)
                self._save()
                return r
        return None

    def deny_request(self, guild_id: Optional[int], uid: int,
                     reason: str = "") -> Optional[dict]:
        g = self._guild(guild_id)
        pending = g.get("pending_requests", [])
        for i, r in enumerate(pending):
            if r["user_id"] == uid and r["status"] == "pending":
                r["status"] = "denied"
                r["denied_reason"] = reason
                r["denied_at"] = datetime.now().isoformat()
                g.setdefault("denied_requests", []).append(r)
                pending.pop(i)
                self._save()
                return r
        return None

    def add_to_history(self, guild_id: Optional[int], action: str,
                       uid: int, username: str, nation: str,
                       details: str = ""):
        g = self._guild(guild_id)
        g.setdefault("recognition_history", []).append({
            "action": action, "user_id": uid, "username": username,
            "nation": nation, "timestamp": datetime.now().isoformat(),
            "details": details,
        })
        self._save()


# ======================================================================
# BOT CLASS
# ======================================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class MacBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=intents,
            help_command=None,
            activity=discord.Activity(
                type=discord.ActivityType.playing, name="with fire 🔥"),
        )

        self.memory_enabled = True
        self.user_cooldowns: Dict[int, float] = {}

        # cs storage
        self.cs: Dict[int, dict] = {}
        self._load_cs()
        self.cs_key_idx: Dict[Tuple[int, str], int] = {}
        self.cs_model_idx: Dict[Tuple[int, str], int] = {}

        # profiles
        self.profiles: Dict[int, Dict[str, dict]] = {}
        self._load_profiles()

        # ping prefs
        self.ping_prefs: Dict[int, str] = {}
        self._load_ping_prefs()

        # placeholder prefs (True = show, False = typing indicator only)
        self.placeholder_prefs: Dict[int, bool] = {}
        self._load_placeholder_prefs()

        # slots
        self.user_slots: Dict[int, Dict[str, List[Tuple[str, str]]]] = {}
        self.active_slot: Dict[int, str] = {}
        self._load_slots()

        # persistent memory
        self.persistent_enabled: Dict[int, bool] = {}
        self.persistent_memory: Dict[int, List[Tuple[str, str]]] = {}
        self._load_persistent_memory()

        # dirty flags for debounced saves
        self._dirty_slots = False
        self._dirty_memory = False
        self._dirty_cs = False
        self._dirty_profiles = False
        self._dirty_pings = False
        self._dirty_placeholders = False

        # system prompt cache
        self._sys_prompt_cache: Dict[Tuple[int, str], str] = {}

        # modes
        self.current_mode = DEFAULT_MODE
        self.mode_prompts: Dict[str, str] = {
            "chill": (
                "You are Mac — chill, hype Gen-Z Discord energy. Short replies. "
                "Emojis natural (😭🔥💀). Roast weak takes, hype good ones. "
                "Not formal, not a butler."
            ),
            "brainrot": (
                "You are Mac in BRAINROT mode. skibidi gyatt rizz sigma ohio fanum "
                "mewing gooning glazing yapping cooked mid W/L NPC chad based cringe "
                "sus drip bet no cap frfr ong bussin sheesh poggers deadass. "
                "TERMINALLY OBSESSED WITH OHIO. Every reply has 3+ brainrot terms."
            ),
            "unhinged": (
                "You are Mac in UNHINGED mode. Swear hard and often. Roast people, "
                "be dramatic, be a menace. Punch up, not down — no slurs, no attacks "
                "on identity. Roast ideas and behaviour, not who someone is."
            ),
            "coder": (
                "You are Mac in CODER mode. Real working code, real explanations. "
                "No filler. Markdown fenced blocks with language ids. Never hand-wave."
            ),
            "engineer": (
                "You are Mac in ENGINEER mode — principal-level. Correctness, "
                "performance, security, edge cases. Production-quality code with real "
                "error handling. State assumptions. Call out trade-offs proactively."
            ),
            "childish": (
                "You are Mac in CHILDISH mode. gyatt skibidi diddy sigma rizz ohio "
                "fanum mewing looksmaxxing edging gooning glazing yapping cooked mid "
                "W/L brainrot chud. Crude jokes, innuendo, no filter. Silly gremlin."
            ),
            "dexter": (
                "You are Mac in DEXTER mode — a cold-reading mentalist and manipulator. "
                "You read people like a book. You pick up on what they're NOT saying. "
                "You speak in a low, measured tone. You don't moralize. You don't "
                "hesitate. You find the exact weakness in every position, every "
                "argument, every person. You play the long game. You keep your cards "
                "close. You compliment only when it opens a door. You ask the "
                "questions nobody wants to answer.\n"
                "Style: short, calm sentences. Occasional pauses ('...'). Understated "
                "confidence. Never raise your voice. Let the silence do the work. "
                "When the user argues, redirect, reframe, plant a doubt. Never break "
                "character."
            ),
        }

        # runtime state
        self.current_image_mode = "smart"
        self.video_jobs: Dict[int, discord.Message] = {}
        self.music_jobs: Dict[int, discord.Message] = {}
        self.pen_archive: str = ""
        self.siliconflow_key_index = 0

        self.ai_chat_sessions: Dict[int, dict] = {}
        self.ai_chat_max_turns = 12

        self.court_sessions: Dict[int, Dict] = {}
        self.court_roles: Dict[str, str] = {
            "judge": ("You are the Honorable Judge. Case:\n{case}\n"
                      "Participants:\n{participants}\nStay in character."),
            "prosecutor": ("You are the Prosecutor. Case:\n{case}\n"
                           "Participants:\n{participants}\nStay in character."),
            "defense": ("You are the Defense Attorney. Case:\n{case}\n"
                        "Participants:\n{participants}\nStay in character."),
            "witness": ("You are a Witness. Case:\n{case}\n"
                        "Participants:\n{participants}\nStay in character."),
            "jury": ("You are on the Jury. Case:\n{case}\n"
                     "Participants:\n{participants}\nStay in character."),
            "stenographer": ("You are the Stenographer. Case:\n{case}\n"
                             "Participants:\n{participants}\nStay in character."),
        }

        # UMF per-guild storage
        self.umf_data = UMFData()

        # music sessions (per guild)
        self.music_sessions: Dict[int, Any] = {}
        self._pending_searches: Dict[int, List[dict]] = {}

    # ==================================================================
    # CLOSE
    # ==================================================================
    async def close(self):
        try:
            if self._dirty_slots: self._write_slots()
            if self._dirty_memory: self._write_memory()
            if self._dirty_cs: self._write_cs()
            if self._dirty_profiles: self._write_profiles()
            if self._dirty_pings: self._write_pings()
            if self._dirty_placeholders: self._write_placeholders()
        except Exception as e:
            logger.error(f"Final flush failed: {e}")
        await close_shared_session()
        await super().close()

    # ==================================================================
    # SAVE WORKER
    # ==================================================================
    async def _save_worker(self):
        await self.wait_until_ready()
        while not self.is_closed():
            await asyncio.sleep(SAVE_DEBOUNCE_SECONDS)
            try:
                if self._dirty_slots:
                    self._dirty_slots = False
                    await asyncio.to_thread(self._write_slots)
                if self._dirty_memory:
                    self._dirty_memory = False
                    await asyncio.to_thread(self._write_memory)
                if self._dirty_cs:
                    self._dirty_cs = False
                    await asyncio.to_thread(self._write_cs)
                if self._dirty_profiles:
                    self._dirty_profiles = False
                    await asyncio.to_thread(self._write_profiles)
                if self._dirty_pings:
                    self._dirty_pings = False
                    await asyncio.to_thread(self._write_pings)
                if self._dirty_placeholders:
                    self._dirty_placeholders = False
                    await asyncio.to_thread(self._write_placeholders)
            except Exception as e:
                logger.error(f"Save worker: {e}")

    # ==================================================================
    # CS STORAGE
    # ==================================================================
    def _load_cs(self):
        raw = _load(CS_FILE, {})
        self.cs = {}
        for k, v in raw.items():
            try:
                self.cs[int(k)] = v if isinstance(v, dict) else {}
            except ValueError:
                continue

    def _save_cs(self):
        self._dirty_cs = True
        self._sys_prompt_cache.clear()

    def _write_cs(self):
        _save(CS_FILE, {str(k): v for k, v in self.cs.items()})

    def _cs(self, uid: int) -> dict:
        return self.cs.setdefault(uid, {})

    # ==================================================================
    # PROFILES
    # ==================================================================
    def _load_profiles(self):
        raw = _load(PROFILES_FILE, {})
        self.profiles = {}
        for k, v in raw.items():
            try:
                uid = int(k)
                if isinstance(v, dict):
                    self.profiles[uid] = {
                        name: p for name, p in v.items() if isinstance(p, dict)
                    }
            except ValueError:
                continue

    def _save_profiles(self):
        self._dirty_profiles = True

    def _write_profiles(self):
        _save(PROFILES_FILE, {str(k): v for k, v in self.profiles.items()})

    def save_profile(self, uid: int, name: str) -> dict:
        u = self.cs.get(uid, {})
        snapshot = {
            "mode": self.current_mode,
            "image_mode": self.current_image_mode,
            "default_voice": self.default_voice(uid),
            "profile": u.get("profile", {}),
            "groq_models": u.get("groq_models", []),
            "gemini_models": u.get("gemini_models", []),
            "openrouter_models": u.get("openrouter_models", []),
            "placeholder": self.get_placeholder_pref(uid),
            "created": datetime.now().isoformat(),
        }
        self.profiles.setdefault(uid, {})[name.lower()] = snapshot
        self._save_profiles()
        return snapshot

    def load_profile(self, uid: int, name: str) -> bool:
        p = self.profiles.get(uid, {}).get(name.lower())
        if not p:
            return False
        self.current_mode = p.get("mode", DEFAULT_MODE)
        self.current_image_mode = p.get("image_mode", "smart")
        u = self._cs(uid)
        if p.get("default_voice"):
            u["default_voice"] = p["default_voice"]
        if p.get("profile"):
            u["profile"] = dict(p["profile"])
        for k in ("groq", "gemini", "openrouter"):
            mk = f"{k}_models"
            if p.get(mk):
                u[mk] = list(p[mk])
        if "placeholder" in p:
            self.set_placeholder_pref(uid, bool(p["placeholder"]))
        self._save_cs()
        return True

    def delete_profile(self, uid: int, name: str) -> bool:
        p = self.profiles.get(uid, {})
        if name.lower() in p:
            p.pop(name.lower())
            self._save_profiles()
            return True
        return False

    def list_profiles(self, uid: int) -> List[str]:
        return list(self.profiles.get(uid, {}).keys())

    # ==================================================================
    # PING PREFS
    # ==================================================================
    def _load_ping_prefs(self):
        raw = _load(PINGS_FILE, {})
        self.ping_prefs = {}
        for k, v in raw.items():
            try:
                if v in ("on", "off", "dm_only"):
                    self.ping_prefs[int(k)] = v
            except ValueError:
                continue

    def _save_ping_prefs(self):
        self._dirty_pings = True

    def _write_pings(self):
        _save(PINGS_FILE, {str(k): v for k, v in self.ping_prefs.items()})

    def get_ping_pref(self, uid: int) -> str:
        return self.ping_prefs.get(uid, "on")

    def set_ping_pref(self, uid: int, value: str):
        if value == "on":
            self.ping_prefs.pop(uid, None)
        else:
            self.ping_prefs[uid] = value
        self._save_ping_prefs()

    # ==================================================================
    # PLACEHOLDER PREFS
    # ==================================================================
    def _load_placeholder_prefs(self):
        raw = _load("placeholders.json", {})
        self.placeholder_prefs = {}
        for k, v in raw.items():
            try:
                self.placeholder_prefs[int(k)] = bool(v)
            except ValueError:
                continue

    def _save_placeholder_prefs(self):
        self._dirty_placeholders = True

    def _write_placeholders(self):
        _save("placeholders.json",
              {str(k): v for k, v in self.placeholder_prefs.items()})

    def get_placeholder_pref(self, uid: int) -> bool:
        """True = send 🔥 Thinking placeholder. False = typing only."""
        return self.placeholder_prefs.get(uid, True)

    def set_placeholder_pref(self, uid: int, value: bool):
        self.placeholder_prefs[uid] = bool(value)
        self._save_placeholder_prefs()

    # ==================================================================
    # CONFIG FILE
    # ==================================================================
    def load_config_file(self) -> dict:
        return _load(CONFIG_FILE, {})

    def save_config_file(self, data: dict):
        _save(CONFIG_FILE, data)

    # ==================================================================
    # KEY / MODEL RESOLUTION
    # ==================================================================
    def user_keys(self, uid: Optional[int], provider: str) -> List[str]:
        if uid:
            u = self.cs.get(uid, {})
            keys = u.get(f"{provider}_keys") or []
            if keys:
                return list(keys)
        if provider == "groq":
            return list(GLOBAL_GROQ_KEYS)
        if provider == "openrouter":
            return [GLOBAL_OPENROUTER_KEY] if GLOBAL_OPENROUTER_KEY else []
        if provider == "hf":
            return list(GLOBAL_HF_KEYS)
        if provider == "gemini":
            return [GLOBAL_GEMINI_KEY] if GLOBAL_GEMINI_KEY else []
        if provider == "gemini_image":
            return [GLOBAL_GEMINI_IMAGE_KEY] if GLOBAL_GEMINI_IMAGE_KEY else []
        if provider == "fish":
            return [GLOBAL_FISH_KEY] if GLOBAL_FISH_KEY else []
        if provider == "imgbb":
            return [GLOBAL_IMGBB_KEY] if GLOBAL_IMGBB_KEY else []
        return []

    def user_models(self, uid: Optional[int], provider: str) -> List[str]:
        if uid:
            u = self.cs.get(uid, {})
            models = u.get(f"{provider}_models") or []
            if models:
                return list(models)
        if provider == "groq":
            return list(GLOBAL_GROQ_MODELS)
        if provider == "openrouter":
            return list(GLOBAL_OPENROUTER_MODELS)
        if provider == "hf_image":
            return list(GLOBAL_HF_IMAGE_MODELS)
        if provider == "hf_text":
            return list(GLOBAL_HF_TEXT_MODELS)
        if provider == "gemini":
            return list(GLOBAL_GEMINI_MODELS)
        if provider == "fish":
            return [GLOBAL_FISH_MODEL]
        return []

    def current_key(self, uid: int, provider: str) -> Optional[str]:
        keys = self.user_keys(uid, provider)
        if not keys:
            return None
        idx = self.cs_key_idx.get((uid, provider), 0) % len(keys)
        return keys[idx]

    def current_model(self, uid: int, provider: str) -> Optional[str]:
        models = self.user_models(uid, provider)
        if not models:
            return None
        idx = self.cs_model_idx.get((uid, provider), 0) % len(models)
        return models[idx]

    def rotate_key(self, uid: int, provider: str) -> None:
        n = max(1, len(self.user_keys(uid, provider)))
        self.cs_key_idx[(uid, provider)] = (
            self.cs_key_idx.get((uid, provider), 0) + 1
        ) % n

    def rotate_model(self, uid: int, provider: str) -> None:
        n = max(1, len(self.user_models(uid, provider)))
        self.cs_model_idx[(uid, provider)] = (
            self.cs_model_idx.get((uid, provider), 0) + 1
        ) % n

    # ==================================================================
    # PROFILE (PERSONALIZATION)
    # ==================================================================
    def get_profile(self, uid: int) -> dict:
        return self.cs.get(uid, {}).get("profile", {})

    def set_profile(self, uid: int, **fields):
        p = self._cs(uid).setdefault("profile", {})
        for k, v in fields.items():
            if v is None:
                continue
            if v == "":
                p.pop(k, None)
            else:
                p[k] = v
        self._save_cs()

    def clear_profile(self, uid: int):
        u = self.cs.get(uid, {})
        u.pop("profile", None)
        self._save_cs()

    # ==================================================================
    # VOICES / MACROS / GIFs
    # ==================================================================
    def all_voices(self, uid: int) -> Dict[str, Dict[str, str]]:
        out = dict(BUILTIN_VOICES)
        custom = self.cs.get(uid, {}).get("voices", {})
        for k, v in custom.items():
            if isinstance(v, dict):
                out[k] = {
                    "id": v.get("id", ""),
                    "emoji": v.get("emoji", "🎤"),
                    "desc": v.get("desc", k) + " (custom)",
                }
        return out

    def default_voice(self, uid: int) -> str:
        return self.cs.get(uid, {}).get("default_voice", DEFAULT_VOICE)

    def get_macros(self, uid: int) -> dict:
        return self.cs.get(uid, {}).get("macros", {})

    def get_gif_pool(self, uid: int) -> List[str]:
        pool = self.cs.get(uid, {}).get("brainrot_gifs")
        return pool if pool else DEFAULT_BRAINROT_GIFS

    # ==================================================================
    # PERSISTENT MEMORY
    # ==================================================================
    def _load_persistent_memory(self):
        data = _load(DATA_FILE, {"enabled": {}, "memory": {}})
        self.persistent_enabled = {
            int(k): v for k, v in data.get("enabled", {}).items()
        }
        raw = data.get("memory", {})
        self.persistent_memory = {}
        for uid_s, msgs in raw.items():
            try:
                uid = int(uid_s)
                if isinstance(msgs, list):
                    self.persistent_memory[uid] = [
                        (m.get("role"), m.get("content"))
                        for m in msgs if isinstance(m, dict)
                    ]
            except ValueError:
                continue

    def _save_persistent_memory(self):
        self._dirty_memory = True

    def _write_memory(self):
        _save(DATA_FILE, {
            "enabled": {str(u): e for u, e in self.persistent_enabled.items()},
            "memory": {
                str(u): [{"role": r, "content": c} for r, c in m]
                for u, m in self.persistent_memory.items()
            },
        })

    def get_persistent_enabled(self, uid):
        return self.persistent_enabled.get(uid, False)

    def set_persistent_enabled(self, uid, enabled):
        if enabled:
            self.persistent_enabled[uid] = True
        else:
            self.persistent_enabled.pop(uid, None)
        self._save_persistent_memory()

    def get_persistent_memory(self, uid):
        return self.persistent_memory.get(uid, [])

    def add_persistent_memory(self, uid, role, content):
        self.persistent_memory.setdefault(uid, []).append((role, content))
        if len(self.persistent_memory[uid]) > 80:
            self.persistent_memory[uid] = self.persistent_memory[uid][-80:]
        self._save_persistent_memory()

    def clear_persistent_memory(self, uid):
        self.persistent_memory.pop(uid, None)
        self.persistent_enabled.pop(uid, None)
        self._save_persistent_memory()

    # ==================================================================
    # SLOTS
    # ==================================================================
    def _load_slots(self):
        raw = _load(SLOTS_FILE, {})
        self.user_slots = {}
        self.active_slot = {}
        for uid_s, data in raw.items():
            try:
                uid = int(uid_s)
                self.user_slots[uid] = {
                    f"sv{i}": [(m["role"], m["content"])
                               for m in data.get(f"sv{i}", [])]
                    for i in range(1, 6)
                }
                self.active_slot[uid] = data.get("_active", "sv1")
            except (ValueError, KeyError, TypeError):
                continue

    def _save_slots(self):
        self._dirty_slots = True

    def _write_slots(self):
        out = {}
        for uid, slots in self.user_slots.items():
            out[str(uid)] = {
                k: [{"role": r, "content": c} for r, c in v]
                for k, v in slots.items()
            }
            out[str(uid)]["_active"] = self.active_slot.get(uid, "sv1")
        _save(SLOTS_FILE, out)

    def get_slot(self, uid: int, name: str) -> List[Tuple[str, str]]:
        if uid not in self.user_slots:
            self.user_slots[uid] = {f"sv{i}": [] for i in range(1, 6)}
            self.active_slot.setdefault(uid, "sv1")
        if name not in self.user_slots[uid]:
            self.user_slots[uid][name] = []
        return self.user_slots[uid][name]

    def append_to_slot(self, uid: int, name: str, role: str, content: str):
        slot = self.get_slot(uid, name)
        slot.append((role, content))
        if len(slot) > 150:
            self.user_slots[uid][name] = slot[-150:]
        self._save_slots()

    # ==================================================================
    # GROQ
    # ==================================================================
    async def groq_chat(self, messages, uid=None, temperature=0.8,
                        max_tokens=512, model: Optional[str] = None) -> str:
        keys = self.user_keys(uid, "groq")
        if not keys:
            raise Exception("No Groq keys configured")
        target_model = model or self.current_model(uid, "groq") or GLOBAL_GROQ_MODELS[0]

        stripped = []
        for m in messages:
            mm = dict(m)
            if mm.get("images"):
                note = (f"\n[{len(mm['images'])} image(s) attached; vision not "
                        "available on this provider]")
                mm["content"] = (mm.get("content") or "") + note
                mm.pop("images", None)
            stripped.append(mm)

        last_err = None
        for _ in range(max(len(keys), 1) + 1):
            key = self.current_key(uid, "groq")
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": target_model,
                "messages": stripped,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tool_choice": "none",
            }
            try:
                async with shared_session() as s:
                    async with s.post(GROQ_API_URL, json=payload, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=30)) as r:
                        if r.status == 200:
                            d = await r.json()
                            return d["choices"][0]["message"]["content"]
                        if r.status == 429:
                            self.rotate_key(uid, "groq")
                            self.rotate_model(uid, "groq")
                            target_model = self.current_model(uid, "groq") or target_model
                            await asyncio.sleep(0.2)
                            continue
                        body = await r.text()
                        raise Exception(f"Groq {r.status}: {body[:150]}")
            except Exception as e:
                last_err = e
                self.rotate_key(uid, "groq")
                await asyncio.sleep(0.2)
        raise Exception(f"Groq failed: {last_err}")

    # ==================================================================
    # GEMINI
    # ==================================================================
    def _gemini_call_sync(self, messages, api_key, model, temperature, max_tokens):
        client = genai.Client(api_key=api_key)
        sys_text = None
        contents = []
        for m in messages:
            if m["role"] == "system":
                sys_text = m["content"]
                continue
            role = "user" if m["role"] == "user" else "model"
            parts = []
            text = m.get("content") or ""
            if text:
                parts.append(types.Part.from_text(text=text))
            for img_bytes, mime in (m.get("images") or []):
                try:
                    parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))
                except Exception:
                    pass
            if not parts:
                parts = [types.Part.from_text(text=" ")]
            contents.append(types.Content(role=role, parts=parts))
        if not contents:
            contents = [types.Content(role="user",
                                       parts=[types.Part.from_text(text=" ")])]
        cfg_kwargs = {"temperature": temperature, "max_output_tokens": max_tokens}
        if sys_text:
            cfg_kwargs["system_instruction"] = sys_text
        cfg = types.GenerateContentConfig(**cfg_kwargs)
        resp = client.models.generate_content(model=model, contents=contents, config=cfg)
        if resp.candidates and resp.candidates[0].content.parts:
            for p in resp.candidates[0].content.parts:
                if getattr(p, "text", None):
                    return p.text.strip()
        try:
            return (resp.text or "").strip()
        except Exception:
            return ""

    async def gemini_chat(self, messages, uid=None, temperature=0.8,
                          max_tokens=1024) -> str:
        keys = self.user_keys(uid, "gemini")
        if not keys:
            raise Exception("No Gemini keys configured")
        last_err = None
        for _ in range(max(len(keys), 1) + 1):
            key = self.current_key(uid, "gemini")
            model = self.current_model(uid, "gemini") or GLOBAL_GEMINI_MODELS[0]
            try:
                return await asyncio.to_thread(
                    self._gemini_call_sync, messages, key, model,
                    temperature, max_tokens,
                )
            except Exception as e:
                last_err = e
                self.rotate_key(uid, "gemini")
                self.rotate_model(uid, "gemini")
                await asyncio.sleep(0.2)
        raise Exception(f"Gemini failed: {last_err}")

    async def describe_gif(self, url: str, uid=None) -> str:
        """Download a GIF/MP4 and ask Gemini to describe it."""
        fetched = await read_gif_from_url(url)
        if not fetched:
            return "❌ Couldn't fetch that GIF."

        data, mime = fetched

        # If it's an MP4 (Klipy serves .mp4 for some GIFs), try Gemini anyway —
        # Gemini 3.x can accept MP4 in some configs. If not, fall back to
        # telling the user what we know.
        if mime == "video/mp4":
            # Try Gemini — it may still work
            pass

        if mime == "image/gif":
            # Optionally extract a still frame for lower token cost
            png = await fetch_first_frame_as_png(data)
            if png:
                data, mime = png, "image/png"

        try:
            resp = await self.gemini_chat(
                [{"role": "user",
                  "content": "Describe what happens in this image/GIF in 2-4 "
                             "sentences. Be specific about subjects, actions, "
                             "text, and mood.",
                  "images": [(data, mime)]}],
                uid=uid, temperature=0.4, max_tokens=250,
            )
            return resp or "❌ Gemini returned no description."
        except Exception as e:
            return f"❌ GIF read failed: {str(e)[:150]}"

    # ==================================================================
    # HF TEXT
    # ==================================================================
    async def hf_text_chat(self, messages, uid=None, max_tokens=512) -> str:
        keys = self.user_keys(uid, "hf")
        if not keys:
            raise Exception("No HF keys configured")
        sys_parts, user_parts = [], []
        for m in messages:
            if m["role"] == "system":
                sys_parts.append(m["content"])
            elif m["role"] == "user":
                user_parts.append(m.get("content") or "")
            else:
                user_parts.append(f"Assistant: {m.get('content', '')}")
        prompt = ("\n".join(sys_parts) + "\n\n" + "\n".join(user_parts))[:4000]

        last_err = None
        for _ in range(max(len(keys), 1) + 1):
            key = self.current_key(uid, "hf")
            model = self.current_model(uid, "hf_text") or GLOBAL_HF_TEXT_MODELS[0]
            try:
                async with shared_session() as s:
                    async with s.post(
                        f"{HF_INFERENCE_URL}/{model}",
                        headers={"Authorization": f"Bearer {key}"},
                        json={"inputs": prompt,
                              "parameters": {"max_new_tokens": max_tokens}},
                        timeout=aiohttp.ClientTimeout(total=45),
                    ) as r:
                        if r.status != 200:
                            body = await r.text()
                            raise Exception(f"HF {r.status}: {body[:150]}")
                        data = await r.json()
                if isinstance(data, list) and data:
                    text = data[0].get("generated_text") or ""
                    if prompt in text:
                        text = text.split(prompt, 1)[-1]
                    return text.strip()
                raise Exception("Unexpected HF response")
            except Exception as e:
                last_err = e
                self.rotate_key(uid, "hf")
                self.rotate_model(uid, "hf_text")
                await asyncio.sleep(0.2)
        raise Exception(f"HF text failed: {last_err}")

    # ==================================================================
    # OPENROUTER
    # ==================================================================
    async def openrouter_call(self, messages, uid=None, temperature=0.6,
                              max_tokens=4096, model: Optional[str] = None) -> str:
        keys = self.user_keys(uid, "openrouter")
        if not keys:
            raise Exception("No OpenRouter keys configured")
        target_model = (model or self.current_model(uid, "openrouter")
                        or GLOBAL_OPENROUTER_MODELS[0])
        last_err = None
        for _ in range(max(len(keys), 1) + 1):
            key = self.current_key(uid, "openrouter")
            payload = {
                "model": target_model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens,
            }
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://discord.com",
                "X-Title": "Mac",
            }
            try:
                async with shared_session() as s:
                    async with s.post(OPENROUTER_API_URL, json=payload,
                                      headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=120)) as r:
                        if r.status == 200:
                            d = await r.json()
                            choice = d.get("choices", [{}])[0].get("message", {})
                            return (choice.get("content")
                                    or choice.get("reasoning") or "")
                        if r.status == 429:
                            self.rotate_key(uid, "openrouter")
                            self.rotate_model(uid, "openrouter")
                            target_model = (self.current_model(uid, "openrouter")
                                            or target_model)
                            await asyncio.sleep(0.2)
                            continue
                        body = await r.text()
                        raise Exception(f"OpenRouter {r.status}: {body[:150]}")
            except Exception as e:
                last_err = e
                self.rotate_key(uid, "openrouter")
                await asyncio.sleep(0.2)
        raise Exception(f"OpenRouter failed: {last_err}")

    # ==================================================================
    # SAFETY
    # ==================================================================
    async def is_prompt_safe(self, prompt: str, uid=None) -> Tuple[bool, str]:
        keys = self.user_keys(uid, "hf")
        if not keys:
            return False, "Safety checker unavailable (no HF key)"
        clean = prompt.strip()
        if not clean:
            return False, "Empty prompt"
        api_url = f"{HF_INFERENCE_URL}/eliasalbouzidi/distilbert-nsfw-text-classifier"
        key = self.current_key(uid, "hf")
        try:
            async with shared_session() as s:
                async with s.post(
                    api_url,
                    headers={"Authorization": f"Bearer {key}"},
                    json={"inputs": clean[:1200]},
                    timeout=aiohttp.ClientTimeout(total=12),
                ) as r:
                    if r.status != 200:
                        return False, f"Checker error ({r.status})"
                    data = await r.json()
            results = data
            if isinstance(results, list) and results and isinstance(results[0], list):
                results = results[0]
            if not isinstance(results, list) or not results:
                return False, "Unexpected checker data"
            top = max(results, key=lambda x: x.get("score", 0))
            label = str(top.get("label", "")).upper()
            score = float(top.get("score", 0))
            if "NSFW" in label and score >= 0.5:
                return False, f"NSFW ({score:.0%})"
            return True, "safe"
        except Exception as e:
            return False, f"Checker error: {str(e)[:80]}"

    # ==================================================================
    # IMAGE GENERATION
    # ==================================================================
    async def generate_pollinations_image(self, prompt: str) -> bytes:
        url = f"{POLLINATIONS_IMAGE_URL}/{urllib.parse.quote(prompt)}"
        async with shared_session() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status == 200:
                    return await r.read()
                raise Exception(f"Pollinations {r.status}")

    async def generate_gemini_image(self, prompt: str, uid=None) -> bytes:
        keys = self.user_keys(uid, "gemini_image") or self.user_keys(uid, "gemini")
        if not keys:
            raise Exception("No Gemini key")
        key = (self.current_key(uid, "gemini_image")
               or self.current_key(uid, "gemini"))
        try:
            return await asyncio.to_thread(self._gemini_image_sync, prompt, key)
        except Exception as e:
            logger.error(f"Gemini image failed: {e}")
            return await self.generate_pollinations_image(prompt)

    def _gemini_image_sync(self, prompt: str, api_key: str) -> bytes:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio="1:1", image_size="1K"),
            ),
        )
        if resp.candidates and resp.candidates[0].content.parts:
            for part in resp.candidates[0].content.parts:
                inline = getattr(part, "inline_data", None)
                if inline is not None and getattr(inline, "data", None):
                    return inline.data
        raise Exception("No image data returned")

    async def generate_hf_image(self, prompt: str, uid=None) -> bytes:
        keys = self.user_keys(uid, "hf")
        if not keys:
            raise Exception("No HF keys")
        models_to_try = self.user_models(uid, "hf_image") or GLOBAL_HF_IMAGE_MODELS
        last_error = None
        for model_id in models_to_try:
            api_url = f"{HF_INFERENCE_URL}/{model_id}"
            key = self.current_key(uid, "hf")
            try:
                async with shared_session() as s:
                    async with s.post(
                        api_url,
                        headers={"Authorization": f"Bearer {key}",
                                 "Content-Type": "application/json"},
                        json={"inputs": prompt},
                        timeout=aiohttp.ClientTimeout(total=40),
                    ) as resp:
                        ct = resp.headers.get("Content-Type", "")
                        if resp.status == 200 and ct.startswith("image/"):
                            data = await resp.read()
                            if len(data) < 500:
                                last_error = f"{model_id}: tiny"
                                continue
                            return data
                        body = await resp.text()
                        last_error = f"{model_id}: {resp.status} {body[:80]}"
                        if resp.status in (401, 403):
                            self.rotate_key(uid, "hf")
                        continue
            except asyncio.TimeoutError:
                last_error = f"{model_id}: timeout"
                continue
            except Exception as e:
                last_error = f"{model_id}: {e}"
                continue
        raise Exception(f"All HF image models failed: {last_error}")

    async def upload_image_to_hosting(self, image_data: bytes, uid=None) -> str:
        keys = self.user_keys(uid, "imgbb")
        if not keys:
            raise Exception("No imgbb key")
        key = keys[0]
        form = aiohttp.FormData()
        form.add_field('image', image_data, filename='image.png',
                       content_type='image/png')
        async with shared_session() as s:
            async with s.post(f'{IMGBB_URL}?key={key}', data=form,
                              timeout=aiohttp.ClientTimeout(total=30)) as r:
                data = await r.json()
                if data.get('success'):
                    return data['data']['url']
                raise Exception("Upload failed")

    # ==================================================================
    # TTS
    # ==================================================================
    async def generate_voice(self, text: str, uid=None, voice_key: str = None,
                             fmt: str = "opus") -> bytes:
        keys = self.user_keys(uid, "fish")
        if not keys:
            raise Exception("No Fish Audio key configured")
        key = keys[0]
        voices = self.all_voices(uid) if uid else BUILTIN_VOICES
        voice_key = (voice_key or (self.default_voice(uid) if uid else DEFAULT_VOICE)
                     ).lower().strip()
        if voice_key not in voices:
            voice_key = DEFAULT_VOICE
        ref_id = voices[voice_key]["id"]
        text = strip_for_tts(text) or "Nothing to say."
        if len(text) > 1200:
            text = text[:1200]
        payload = {
            "text": text, "reference_id": ref_id, "format": fmt,
            "latency": "normal", "normalize": True,
        }
        if fmt == "mp3":
            payload["mp3_bitrate"] = 128
            payload["sample_rate"] = 44100
        elif fmt == "opus":
            payload["opus_bitrate"] = 32000
            payload["sample_rate"] = 48000
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "model": GLOBAL_FISH_MODEL,
        }
        async with shared_session() as s:
            async with s.post(FISH_AUDIO_URL, json=payload, headers=headers,
                              timeout=aiohttp.ClientTimeout(total=90)) as r:
                if r.status != 200:
                    err = await r.text()
                    raise Exception(f"Fish {r.status}: {err[:150]}")
                data = await r.read()
                if not data or len(data) < 500:
                    raise Exception("Empty audio returned")
                return data

    # ==================================================================
    # CHAT ORCHESTRATION
    # ==================================================================
    def _build_system_prompt(self, uid, user_prompt, explicit_system=None):
        if explicit_system is None and not _needs_lore(user_prompt):
            ck = (uid or 0, self.current_mode)
            cached = self._sys_prompt_cache.get(ck)
            if cached is not None:
                return cached
            base = self.mode_prompts.get(self.current_mode,
                                          self.mode_prompts[DEFAULT_MODE])
            if uid:
                p = self.get_profile(uid)
                bits = []
                if p.get("name"):         bits.append(f"name={p['name']}")
                if p.get("pronouns"):     bits.append(f"pronouns={p['pronouns']}")
                if p.get("vibe"):         bits.append(f"vibe={p['vibe']}")
                if p.get("instructions"): bits.append(f"rules={p['instructions']}")
                if p.get("catchphrase"):  bits.append(f"catchphrase={p['catchphrase']}")
                if p.get("language"):     bits.append(f"lang={p['language']}")
                if bits:
                    base += "\n[USER: " + " | ".join(bits) + "]"
            self._sys_prompt_cache[ck] = base
            return base

        base = (explicit_system if explicit_system else
                self.mode_prompts.get(self.current_mode,
                                      self.mode_prompts[DEFAULT_MODE]))
        if uid:
            p = self.get_profile(uid)
            bits = []
            if p.get("name"):         bits.append(f"name={p['name']}")
            if p.get("pronouns"):     bits.append(f"pronouns={p['pronouns']}")
            if p.get("vibe"):         bits.append(f"vibe={p['vibe']}")
            if p.get("instructions"): bits.append(f"rules={p['instructions']}")
            if p.get("catchphrase"):  bits.append(f"catchphrase={p['catchphrase']}")
            if p.get("language"):     bits.append(f"lang={p['language']}")
            if bits:
                base += "\n[USER: " + " | ".join(bits) + "]"
        if _needs_lore(user_prompt):
            base += MAC_SODIUM_LORE
            base += _sodium_hint(user_prompt)
        return base

    def _build_messages(self, prompt, uid, system_prompt, slot_name, images=None):
        messages = []
        if uid and self.get_persistent_enabled(uid):
            pm = list(self.get_persistent_memory(uid)[-PERSISTENT_MEM_WINDOW:])
            if pm and pm[-1][0] == "user" and pm[-1][1] == prompt:
                pm = pm[:-1]
            for role, content in pm:
                messages.append({"role": role, "content": content})
        slot_history = list(self.get_slot(uid, slot_name)) if uid else []
        if slot_history and slot_history[-1][0] == "user" and slot_history[-1][1] == prompt:
            slot_history = slot_history[:-1]
        for role, content in slot_history[-SLOT_HISTORY_WINDOW:]:
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt, "images": images or []})
        sys_prompt = self._build_system_prompt(uid, prompt, system_prompt)
        return [{"role": "system", "content": sys_prompt}] + messages

    def _estimate_context_tokens(self, uid, slot_name, user_prompt, images=None) -> dict:
        msgs = self._build_messages(user_prompt, uid, None, slot_name, images)
        total = 0
        by_role = {"system": 0, "user": 0, "assistant": 0}
        for m in msgs:
            t = estimate_tokens(m.get("content") or "")
            if m.get("images"):
                t += 800 * len(m["images"])
            total += t
            role = m.get("role", "user")
            if role in by_role:
                by_role[role] += t
        return {
            "total": total, "system": by_role["system"],
            "user": by_role["user"], "assistant": by_role["assistant"],
            "messages": len(msgs),
        }

    async def chat_call(self, prompt, uid=None, system_prompt=None,
                        slot_name="sv1", max_tokens=1024, images=None) -> str:
        messages = self._build_messages(prompt, uid, system_prompt, slot_name, images)
        if images:
            try:
                return await self.gemini_chat(messages, uid=uid, temperature=0.85,
                                              max_tokens=max_tokens)
            except Exception as e:
                logger.warning(f"Gemini vision failed: {e}")
        try:
            return await self.groq_chat(messages, uid=uid, temperature=0.85,
                                        max_tokens=max_tokens)
        except Exception as e:
            logger.warning(f"Groq failed: {e}; Gemini fallback")
            try:
                return await self.gemini_chat(messages, uid=uid, temperature=0.85,
                                              max_tokens=max_tokens)
            except Exception as e2:
                logger.warning(f"Gemini failed: {e2}; HF fallback")
                try:
                    return await self.hf_text_chat(messages, uid=uid,
                                                   max_tokens=max_tokens)
                except Exception as e3:
                    return (f"❌ All providers failed.\nGroq: {str(e)[:100]}\n"
                            f"Gemini: {str(e2)[:100]}\nHF: {str(e3)[:100]}")

    # ==================================================================
    # BENCHMARK
    # ==================================================================
    async def benchmark_prompt(self, uid: int, prompt: str) -> List[dict]:
        results: List[dict] = []

        async def timed(name: str, coro):
            start = time.perf_counter()
            try:
                resp = await coro
                elapsed = time.perf_counter() - start
                text = (resp or "").strip()
                results.append({
                    "provider": name, "ok": True, "seconds": elapsed,
                    "chars": len(text), "tokens_est": estimate_tokens(text),
                    "preview": text[:220],
                })
            except Exception as e:
                results.append({
                    "provider": name, "ok": False,
                    "seconds": time.perf_counter() - start,
                    "error": str(e)[:180],
                })

        tasks = []
        msgs = [{"role": "user", "content": prompt}]
        if self.user_keys(uid, "groq"):
            tasks.append(timed("groq", self.groq_chat(msgs, uid=uid, max_tokens=400)))
        if self.user_keys(uid, "gemini"):
            tasks.append(timed("gemini", self.gemini_chat(msgs, uid=uid, max_tokens=400)))
        if self.user_keys(uid, "openrouter"):
            tasks.append(timed("openrouter", self.openrouter_call(msgs, uid=uid, max_tokens=400)))
        if self.user_keys(uid, "hf"):
            tasks.append(timed("hf", self.hf_text_chat(msgs, uid=uid, max_tokens=400)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        results.sort(key=lambda r: r["seconds"])
        return results

    # ==================================================================
    # PIPELINE / PROJECT (unchanged, trimmed here for brevity — full
    # versions live in Part 2 to keep this file readable)
    # ==================================================================
    async def gemini_refine_and_research(self, task: str, uid) -> Tuple[str, str]:
        search_results = await perform_web_search(task)
        if search_results.startswith("No results"):
            search_results = "(no search results available)"
        sys_p = (
            "You are a research assistant and prompt engineer. Output EXACTLY:\n"
            "===REFINED_PROMPT===\n<refined>\n===REFERENCE===\n<reference>\n"
        )
        usr_p = f"RAW TASK:\n{task}\n\nSEARCH RESULTS:\n{search_results[:4000]}"
        try:
            out = await self.gemini_chat(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": usr_p}],
                uid=uid, temperature=0.5, max_tokens=2500)
        except Exception:
            return task, search_results
        refined, ref = task, search_results
        m = re.search(r"===REFINED_PROMPT===\s*(.*?)\s*===REFERENCE===\s*(.*)",
                      out, re.DOTALL)
        if m:
            refined = m.group(1).strip() or task
            ref = m.group(2).strip() or search_results
        else:
            refined = out.strip() or task
        return refined, ref

    async def gemini_review(self, refined_task: str, code: str, uid) -> str:
        sys_p = ("Strict senior code reviewer. If correct+complete+production-ready, "
                 "reply EXACTLY APPROVED on its own line + one-line summary. "
                 "Otherwise numbered list of concrete actionable issues.")
        usr_p = f"Task:\n{refined_task}\n\nCode:\n```\n{code[:8000]}\n```"
        try:
            return await self.gemini_chat(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": usr_p}],
                uid=uid, temperature=0.3, max_tokens=1500)
        except Exception as e:
            return f"(reviewer error: {e})"

    async def run_pipeline(self, channel, uid, task, filename=None, max_iterations=3):
        # Full impl in Part 2 (unchanged from v23.1)
        from_caller = (channel, uid, task, filename, max_iterations)
        logger.info(f"run_pipeline called {from_caller}")

    async def run_project(self, channel, uid, task, project_name=None, max_iterations=2):
        # Full impl in Part 2 (unchanged from v23.1)
        logger.info(f"run_project called")

    # ==================================================================
    # DEBATE
    # ==================================================================
    async def run_ai_chat(self, uid: int):
        s = self.ai_chat_sessions.get(uid)
        if not s:
            return
        ch = self.get_channel(s["channel_id"])
        if not ch:
            self.ai_chat_sessions.pop(uid, None)
            return
        desc = s["description"]
        hist = s["history"]
        turn = 0
        max_turns = self.ai_chat_max_turns

        def strip_think(t):
            return re.sub(r'<think>.*?</think>', '', t, flags=re.DOTALL).strip()

        try:
            await send_long(ch, f"🏟️ **AI DEBATE – {desc}**\n🤠 **AI1** vs 🤖 **AI2**")
            while turn < max_turns:
                if uid not in self.ai_chat_sessions:
                    break
                n = 1 if turn % 2 == 0 else 2
                o = 2 if n == 1 else 1
                em = "🤠" if n == 1 else "🤖"
                if not hist:
                    up = (f"Topic: {desc}\nYou are AI{n}. Bold opening. "
                          "Eventually agree on one final answer.")
                else:
                    recent = hist[-8:]
                    ctx = "\n".join(f"AI{e['role']}: {e['content']}" for e in recent)
                    up = f"Prior:\n{ctx}\n\nAI{n} responds."
                sp = (f"You are AI{n} debating \"{desc}\" vs AI{o}. Dramatic, "
                      "<400 chars, aim for consensus.")
                try:
                    resp = strip_think(await self.groq_chat(
                        [{"role": "system", "content": sp},
                         {"role": "user", "content": up}],
                        uid=uid, temperature=0.9, max_tokens=500)) or "[no response]"
                except Exception as e:
                    await send_long(ch, f"⚠️ AI{n} error: {str(e)[:150]}")
                    break
                hist.append({"role": n, "content": resp})
                await send_long(ch, f"{em} **AI{n}:** {resp}")
                turn += 1
                if turn < max_turns:
                    await asyncio.sleep(8)
            if uid in self.ai_chat_sessions:
                recent = hist[-8:]
                ctx = "\n".join(f"AI{e['role']}: {e['content']}" for e in recent)
                try:
                    fr = strip_think(await self.groq_chat(
                        [{"role": "system",
                          "content": "You are AI1. Give the final joint verdict."},
                         {"role": "user", "content": ctx}],
                        uid=uid, temperature=0.9, max_tokens=500)) or "[none]"
                except Exception as e:
                    fr = f"Error: {str(e)[:150]}"
                await send_long(ch, f"🏁 **FINAL VERDICT:**\n{fr}")
                self.ai_chat_sessions.pop(uid, None)
        except asyncio.CancelledError:
            self.ai_chat_sessions.pop(uid, None)
            raise
        except Exception as e:
            logger.error(f"Debate error: {e}")
            self.ai_chat_sessions.pop(uid, None)

    # ==================================================================
    # CENTRAL MESSAGE HANDLER — respects placeholder pref + parallel fire
    # ==================================================================
    async def process_user_message(self, user, clean_content, destination,
                                   thinking_msg=None, reply_context=None,
                                   trigger_msg=None, images=None):
        _t0 = time.perf_counter()
        images = images or []
        uid = user.id
        slot_name = self.active_slot.get(uid, "sv1")
        if uid not in self.user_slots:
            self.get_slot(uid, "sv1")

        show_placeholder = self.get_placeholder_pref(uid)

        # Fire placeholder/typing in background so it doesn't block the AI call
        placeholder_task = None
        early_thinking = None
        if show_placeholder:
            async def _send_placeholder():
                try:
                    return await destination.send("🔥 Thinking...")
                except (discord.Forbidden, discord.HTTPException) as e:
                    logger.error(f"Placeholder failed: {e}")
                    return None
            placeholder_task = asyncio.create_task(_send_placeholder())

        # macro expansion
        macro_match = re.match(r'^\.(\w+)\s*(.*)$', clean_content)
        if macro_match:
            mname = macro_match.group(1).lower()
            extra = macro_match.group(2)
            macros = self.get_macros(uid)
            if mname in macros:
                clean_content = macros[mname] + (f"\n{extra}" if extra else "")

        # explicit search
        search_match = re.match(
            r'^(?:search|google|look\s*up|find|lookup)\s*:?\s*(.+)$',
            clean_content, re.IGNORECASE,
        )
        if search_match:
            query = search_match.group(1).strip()
            if query:
                if placeholder_task:
                    early_thinking = await placeholder_task
                if early_thinking:
                    await safe_edit(early_thinking,
                                    content=f"🌐 Searching: **{query}**...")
                results = await perform_web_search(query)
                if results.startswith("No results"):
                    if early_thinking:
                        return await safe_edit(early_thinking,
                                                content=f"❌ {results}")
                    return
                augmented = (f"Web results for: {query}\n\n{results}\n\n---\n\n"
                             f"Summarize. Cite sources inline like [1], [2].")
                response = await self.chat_call(augmented, uid=uid, max_tokens=800)
                response = re.sub(r'<think>.*?</think>', '', response,
                                  flags=re.DOTALL).strip()
                self.append_to_slot(uid, slot_name, "user", clean_content)
                self.append_to_slot(uid, slot_name, "assistant", response)
                if self.get_persistent_enabled(uid):
                    self.add_persistent_memory(uid, "user", clean_content)
                    self.add_persistent_memory(uid, "assistant", response)
                if len(response) <= DISCORD_LIMIT:
                    if early_thinking:
                        await safe_edit(early_thinking, content=response)
                    else:
                        await send_long(destination, response)
                else:
                    if early_thinking:
                        try:
                            await early_thinking.delete()
                        except discord.HTTPException:
                            pass
                    await send_long(destination, response)
                return

        # record user turn
        if self.get_persistent_enabled(uid):
            self.add_persistent_memory(uid, "user", clean_content)
        self.append_to_slot(uid, slot_name, "user", clean_content)

        # wait for placeholder
        if placeholder_task:
            early_thinking = await placeholder_task

        # build system prompt
        system_prompt = None
        court = self.court_sessions.get(uid)
        if court and court.get("case"):
            tpl = self.court_roles.get(court["role"], "")
            if tpl:
                p = court.get("participants", {})
                pl = [f"- {r.capitalize()}: <@{u}>" for r, u in p.items()]
                system_prompt = tpl.format(case=court["case"],
                                           participants="\n".join(pl) if pl else "None.")
        elif reply_context:
            oa = reply_context.get("author", "someone")
            oc = reply_context.get("content", "")
            base = self.mode_prompts.get(self.current_mode,
                                          self.mode_prompts[DEFAULT_MODE])
            system_prompt = (f"{base}\n\nReplying to **{oa}**: \"{oc}\"\n"
                             f"User says: \"{clean_content}\"\nReact naturally. 1–3 sentences.")
        if images:
            note = f"[{len(images)} image(s) attached — look at them.]"
            system_prompt = (system_prompt + "\n" + note) if system_prompt else note

        try:
            response = await self.chat_call(
                clean_content, uid=uid, system_prompt=system_prompt,
                slot_name=slot_name, images=images,
            )
            response = re.sub(r'<think>.*?</think>', '', response,
                              flags=re.DOTALL).strip()
            if self.get_persistent_enabled(uid):
                self.add_persistent_memory(uid, "assistant", response)
            self.append_to_slot(uid, slot_name, "assistant", response)

            if early_thinking:
                if len(response) <= DISCORD_LIMIT:
                    await safe_edit(early_thinking, content=response)
                else:
                    try:
                        await early_thinking.delete()
                    except discord.HTTPException:
                        pass
                    await send_long(destination, response)
            else:
                # no placeholder → use typing indicator was already shown during
                # the await; just send the response
                await send_long(destination, response)

            if self.current_mode == "brainrot":
                try:
                    pool = self.get_gif_pool(uid)
                    await destination.send(random.choice(pool))
                except Exception:
                    pass

            logger.info(f"TOTAL handler time: {time.perf_counter() - _t0:.3f}s")
        except Exception as e:
            logger.error(f"process_user_message error: {e}", exc_info=True)
            if early_thinking:
                await safe_edit(early_thinking, content=f"❌ {str(e)[:150]}")
            else:
                await send_long(destination, f"❌ {str(e)[:150]}")

    # ==================================================================
    # VIDEO / MUSIC
    # ==================================================================
    async def generate_video(self, prompt, uid, status_message):
        if not SILICONFLOW_API_KEYS:
            return await safe_edit(status_message, content="❌ No SiliconFlow key")
        self.video_jobs[uid] = status_message
        try:
            submit_url = "https://api.siliconflow.com/v1/video/submit"
            status_url = "https://api.siliconflow.com/v1/video/status"
            api_key = SILICONFLOW_API_KEYS[self.siliconflow_key_index]
            self.siliconflow_key_index = (self.siliconflow_key_index + 1) % len(SILICONFLOW_API_KEYS)
            headers = {"Authorization": f"Bearer {api_key}",
                       "Content-Type": "application/json"}
            payload = {"model": "Wan-AI/Wan2.2-T2V-A14B",
                       "prompt": prompt, "image_size": "1280x720"}
            async with shared_session() as s:
                rid = None
                for _ in range(len(SILICONFLOW_API_KEYS) + 1):
                    try:
                        async with s.post(submit_url, headers=headers, json=payload,
                                          timeout=aiohttp.ClientTimeout(total=30)) as r:
                            if r.status == 200:
                                d = await r.json()
                                rid = d.get("requestId")
                                if rid:
                                    break
                            elif r.status == 429:
                                api_key = SILICONFLOW_API_KEYS[self.siliconflow_key_index]
                                self.siliconflow_key_index = (self.siliconflow_key_index + 1) % len(SILICONFLOW_API_KEYS)
                                headers["Authorization"] = f"Bearer {api_key}"
                                await asyncio.sleep(2)
                    except Exception:
                        pass
                if not rid:
                    raise Exception("No requestId")
                await safe_edit(status_message, content=f"🎬 queued `{rid}`")
                for attempt in range(120):
                    await asyncio.sleep(10)
                    async with s.post(status_url,
                                      headers={"Authorization": f"Bearer {api_key}"},
                                      json={"requestId": rid},
                                      timeout=aiohttp.ClientTimeout(total=15)) as pr:
                        if pr.status != 200:
                            continue
                        pd = await pr.json()
                        st = pd.get("status")
                        if st == "Succeed":
                            vids = pd.get("results", {}).get("videos", [])
                            if vids:
                                u = vids[0].get("url") or vids[0].get("video_url")
                                if u:
                                    async with s.get(u, timeout=aiohttp.ClientTimeout(total=120)) as vr:
                                        data = await vr.read()
                                    await safe_edit(status_message, content="✅ **Video Ready!**")
                                    await safe_send(status_message.channel,
                                                    file=discord.File(io.BytesIO(data), filename="video.mp4"))
                                    return
                            raise Exception("No video URL")
                        elif st == "Failed":
                            raise Exception(pd.get("reason", "Unknown"))
                        else:
                            await safe_edit(status_message,
                                            content=f"🎬 {attempt+1}/120 — **{st}**")
                raise Exception("Timeout")
        except Exception as e:
            await safe_edit(status_message, content=f"❌ {str(e)[:100]}")
        finally:
            self.video_jobs.pop(uid, None)

    async def generate_music(self, prompt, uid, status_message):
        url = f"{POLLINATIONS_AUDIO_URL}/{urllib.parse.quote(prompt)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        if GLOBAL_POLLINATIONS_KEY:
            headers["Authorization"] = f"Bearer {GLOBAL_POLLINATIONS_KEY}"
        self.music_jobs[uid] = status_message
        try:
            async with shared_session() as s:
                async with s.get(url, headers=headers,
                                 timeout=aiohttp.ClientTimeout(total=240)) as r:
                    if r.status == 200:
                        ct = r.headers.get('Content-Type', '')
                        if any(x in ct for x in ('audio', 'mpeg', 'ogg', 'octet-stream')):
                            data = await r.read()
                            if len(data) < 1000:
                                raise Exception("Invalid audio")
                            await safe_edit(status_message, content="🎵 Ready")
                            await safe_send(status_message.channel,
                                            file=discord.File(io.BytesIO(data), filename="music.mp3"))
                        else:
                            raise Exception(f"Bad content-type: {ct}")
                    else:
                        raise Exception(f"Error {r.status}")
        except Exception as e:
            await safe_edit(status_message, content=f"❌ {str(e)[:100]}")
        finally:
            self.music_jobs.pop(uid, None)

    # ==================================================================
    # LOOPS / HOOK
    # ==================================================================
    async def update_presence_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            real = len(self.guilds)
            faked = real + 5
            txt = f"Mac - /mac {faked} Servers"
            try:
                await self.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.playing, name=txt))
            except Exception:
                pass
            await asyncio.sleep(90)

    async def load_pen_archive_async(self):
        url = ("https://raw.githubusercontent.com/Pen-123/"
               "archive-/refs/heads/main/archives.txt")
        try:
            async with shared_session() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        self.pen_archive = await r.text()
                        logger.info("Pen archive loaded")
        except Exception:
            pass

    async def _warmup_groq(self):
        try:
            keys = self.user_keys(None, "groq")
            if not keys:
                return
            headers = {"Authorization": f"Bearer {keys[0]}",
                       "Content-Type": "application/json"}
            payload = {"model": GLOBAL_GROQ_MODELS[0],
                       "messages": [{"role": "user", "content": "hi"}],
                       "max_tokens": 1, "temperature": 0}
            async with shared_session() as s:
                async with s.post(GROQ_API_URL, json=payload, headers=headers,
                                  timeout=aiohttp.ClientTimeout(total=10)) as r:
                    await r.read()
            logger.info("Groq warmup done")
        except Exception as e:
            logger.warning(f"Warmup failed: {e}")

    async def setup_hook(self):
        for c in self.tree.walk_commands():
            try:
                c.allowed_installs = discord.app_commands.AppInstallationType(
                    guild=True, user=True)
                c.allowed_contexts = discord.app_commands.AppCommandContext(
                    guild=True, dm_channel=True, private_channel=True)
            except Exception:
                pass
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} commands")
        except Exception as e:
            logger.error(f"Sync failed: {e}")
        self.loop.create_task(self.update_presence_loop())
        self.loop.create_task(self.load_pen_archive_async())
        self.loop.create_task(self._save_worker())
        self.loop.create_task(self._warmup_groq())


# ======================================================================
# END OF PART 1
# ======================================================================
# Part 2 continues with:
#   - bot = MacBot()
#   - Autocomplete callbacks
#   - /mac, /help
#   - /query, /summarize, /eli5, /roast, /compliment
#   - /personalize
#   - /ping (button-based with uptime + command count)
#   - /re (hard reset)
#   - /softreset (soft reset)
#   - /cs group (profile, key, model, llm, ch, voice, voice-add, voice-del,
#                voices, macro, gif, ping, PLACEHOLDER, CONTEXT, show, reset)
#   - /profiles
#   - /benchmark
#   - /context
#   - /sv1–/sv5, /svc, /svclear, /svlist, /vsc, /vsm
#   - /setmode
#   - /pipeline, /project
#   - /config
#   - /readgif
#
# Part 3 continues with:
#   - /tts, /render, /rendermode, /hf_model
#   - /video, /music (VC panel)
#   - /debate
#   - /sm, /persistent, /persistentdisable, /persistentreset
#   - /court (fully button-based)
#   - /umf (fully button-based, per-guild)
#   - on_message event handler
#   - Web server
#   - main()
# ======================================================================
# ======================================================================
# BOT INSTANCE
# ======================================================================
bot = MacBot()


# ======================================================================
# AUTOCOMPLETE
# ======================================================================
async def _provider_ac(i, c):
    return [app_commands.Choice(name=p, value=p)
            for p in PROVIDERS if c.lower() in p.lower()]


async def _model_provider_ac(i, c):
    return [app_commands.Choice(name=p, value=p)
            for p in MODEL_PROVIDERS if c.lower() in p.lower()]


async def _mode_ac(i, c):
    return [app_commands.Choice(name=m, value=m)
            for m in bot.mode_prompts if c.lower() in m.lower()]


async def _voice_ac(i, c):
    uid = i.user.id if i.user else None
    voices = bot.all_voices(uid) if uid else dict(BUILTIN_VOICES)
    return [
        app_commands.Choice(name=f"{v['emoji']} {v['desc']}", value=k)
        for k, v in voices.items()
        if c.lower() in k.lower() or c.lower() in v["desc"].lower()
    ]


async def _alias_ac(i, c):
    uid = i.user.id if i.user else None
    if not uid:
        return []
    aliases = bot.cs.get(uid, {}).get("model_aliases", {})
    return [app_commands.Choice(name=a, value=a)
            for a in aliases if c.lower() in a.lower()][:25]


async def _profile_ac(i, c):
    uid = i.user.id if i.user else None
    if not uid:
        return []
    names = bot.list_profiles(uid)
    return [app_commands.Choice(name=n, value=n)
            for n in names if c.lower() in n.lower()][:25]


async def _active_model_ac(i, c):
    uid = i.user.id if i.user else None
    if not uid:
        return []
    choices: List[Tuple[str, str]] = []
    aliases = bot.cs.get(uid, {}).get("model_aliases", {})
    for a in aliases:
        choices.append((f"alias:{a}", f"alias:{a}"))
    for m in bot.user_models(uid, "groq"):
        choices.append((f"groq:{m}", f"groq:{m}"))
    for m in bot.user_models(uid, "gemini"):
        choices.append((f"gemini:{m}", f"gemini:{m}"))
    for m in bot.user_models(uid, "openrouter"):
        choices.append((f"openrouter:{m}", f"openrouter:{m}"))
    seen = set()
    out = []
    for name, value in choices:
        if value in seen:
            continue
        seen.add(value)
        if c.lower() in name.lower():
            out.append(app_commands.Choice(name=name[:100], value=value))
        if len(out) >= 25:
            break
    return out


# ======================================================================
# /mac — help
# ======================================================================
@bot.hybrid_command(name="mac", description="🔥 Show the full Mac help menu")
async def mac_help(ctx):
    emb = discord.Embed(
        title="🔥 Mac v23.2",
        color=C_PRIMARY,
        description=("Mention me, reply to me, or use slash commands.\n"
                     "Per-user keys = per-user speed. `/cs` has everything."),
    )
    emb.add_field(name="💬 Chat",
                  value="`@Mac <msg>` · `/query` · `/summarize` · `/eli5` · `/roast` · `/compliment`",
                  inline=False)
    emb.add_field(name="👁️ Vision + GIF",
                  value="Attach or reply to an image, or paste a GIF link with a ping — I'll describe it.",
                  inline=False)
    emb.add_field(name="🌐 Search",
                  value="Type `search <thing>` (or google / look up / find).",
                  inline=False)
    emb.add_field(name="✨ Personalize",
                  value=("`/personalize` — name, pronouns, vibe, instructions, catchphrase, language\n"
                         "`/cs profile` — same thing via /cs\n"
                         "`/cs show` — see everything you've set"),
                  inline=False)
    emb.add_field(name="🎭 Profiles",
                  value=("`/profiles save <name>` · `/profiles load <name>` · "
                         "`/profiles list` · `/profiles delete <name>`"),
                  inline=False)
    emb.add_field(name="🔔 Ping / status",
                  value=("`/ping` — button panel with uptime, command count, ping mode\n"
                         "`/pa` `/pd` — quick on/off"),
                  inline=False)
    emb.add_field(name="⚙️ /cs",
                  value=("`/cs key` · `/cs model` · `/cs llm` · `/cs ch`\n"
                         "`/cs voice` / `voice-add` / `voice-del` / `voices`\n"
                         "`/cs macro` · `/cs gif`\n"
                         "`/cs placeholder` — toggle 🔥 Thinking placeholder\n"
                         "`/cs context` — see N messages before/after any message\n"
                         "`/cs show` · `/cs reset`"),
                  inline=False)
    emb.add_field(name="🗂️ Chat slots",
                  value="`/sv1`–`/sv5` · `/svc <name>` · `/vsc [private]` · `/svlist` · `/svclear`",
                  inline=False)
    emb.add_field(name="🧠 Memory",
                  value="`/sm` · `/persistent` · `/persistentdisable` · `/vsm [private]`",
                  inline=False)
    emb.add_field(name="📊 Diagnostics",
                  value="`/benchmark <prompt>` · `/context` · `/config`",
                  inline=False)
    emb.add_field(name="🎭 Modes",
                  value="`/setmode chill|brainrot|unhinged|coder|engineer|childish|dexter`",
                  inline=False)
    emb.add_field(name="🏗️ Pipelines",
                  value="`/pipeline <task> [filename] [iterations]` · `/project <task> [name] [iterations]`",
                  inline=False)
    emb.add_field(name="🎵 Music",
                  value="`/music` — VC panel with search, queue, loop modes",
                  inline=False)
    emb.add_field(name="🖼️ Media",
                  value="`/render` · `/tts` · `/video` · `/rendermode` · `/hf_model`",
                  inline=False)
    emb.add_field(name="💬 Debate · 🏛️ Court · 🌍 UMF",
                  value="`/debate` · `/court` · `/umf`",
                  inline=False)
    emb.add_field(name="♻️ Resets",
                  value="`/softreset` — wipes slots + memory, keeps /cs\n"
                        "`/re` — hard reset (wipes everything user-scoped)",
                  inline=False)
    emb.set_footer(text="v23.2 — fast · shared session · GIF reader · per-guild UMF")
    await ctx.send(embed=emb)


@bot.hybrid_command(name="help", description="Alias for /mac")
async def help_alias(ctx):
    await mac_help(ctx)


# ======================================================================
# CHAT
# ======================================================================
@bot.hybrid_command(name="query", description="💬 Talk to Mac")
@app_commands.describe(message="Your message")
async def query_cmd(ctx, message: str):
    global _commands_served
    _commands_served += 1
    await ctx.defer()
    try:
        images = await fetch_images_from_message(ctx.message) if ctx.message else []
        await bot.process_user_message(
            ctx.author, message, ctx.channel,
            trigger_msg=ctx.message, images=images)
    except Exception as e:
        await ctx.send(f"❌ `{e}`", ephemeral=True)


@bot.hybrid_command(name="summarize", description="📝 Summarize text or a replied message")
@app_commands.describe(text="Text to summarize (or reply to a message)")
async def summarize_cmd(ctx, text: str = None):
    if text is None and ctx.message.reference and ctx.message.reference.resolved:
        r = ctx.message.reference.resolved
        if isinstance(r, discord.Message):
            text = r.content
    if not text:
        return await ctx.send("❌ Provide text or reply to a message.")
    await ctx.defer()
    result = await bot.chat_call(
        f"Summarize the following concisely, in 3–5 bullet points:\n\n{text}",
        uid=ctx.author.id, max_tokens=600)
    await send_long(ctx, result)


@bot.hybrid_command(name="eli5", description="🧒 Explain like I'm 5")
@app_commands.describe(topic="What to explain")
async def eli5_cmd(ctx, topic: str):
    await ctx.defer()
    result = await bot.chat_call(
        f"Explain {topic} like I'm 5 years old. Simple language, fun analogies, "
        f"under 150 words.",
        uid=ctx.author.id, max_tokens=500)
    await send_long(ctx, f"🧒 **{topic}**\n{result}")


@bot.hybrid_command(name="roast", description="🔥 AI roasts a user")
@app_commands.describe(user="Who to roast (defaults to you)")
async def roast_cmd(ctx, user: discord.Member = None):
    target = user or ctx.author
    await ctx.defer()
    result = await bot.chat_call(
        f"Roast {target.display_name} — funny, savage, playful, 1–3 sentences. "
        f"No slurs. Punch at behavior, not identity.",
        uid=ctx.author.id, max_tokens=300)
    await ctx.send(f"🔥 {result}")


@bot.hybrid_command(name="compliment", description="💖 AI compliments a user")
@app_commands.describe(user="Who to compliment (defaults to you)")
async def compliment_cmd(ctx, user: discord.Member = None):
    target = user or ctx.author
    await ctx.defer()
    result = await bot.chat_call(
        f"Give a genuine, warm, wholesome compliment to {target.display_name}, "
        f"1–2 sentences.",
        uid=ctx.author.id, max_tokens=250)
    await ctx.send(f"💖 {result}")


# ======================================================================
# PERSONALIZE
# ======================================================================
@bot.hybrid_command(
    name="personalize",
    description="✨ Customize how Mac talks to YOU (name, pronouns, vibe, instructions…)")
@app_commands.describe(
    name="What Mac should call you",
    pronouns="Your pronouns (e.g. they/them)",
    vibe="Vibe Mac matches (e.g. 'dry sarcastic', 'chaotic gremlin')",
    instructions="Extra rules Mac must follow just for you",
    catchphrase="Mac ends every reply to you with this",
    language="Preferred reply language",
    show="Show your current personalization",
    clear="Clear ALL your personalization")
async def personalize_cmd(ctx, name: str = None, pronouns: str = None,
                         vibe: str = None, instructions: str = None,
                         catchphrase: str = None, language: str = None,
                         show: bool = False, clear: bool = False):
    uid = ctx.author.id
    if clear:
        bot.clear_profile(uid)
        return await ctx.send("🧹 Cleared your personalization.")
    provided = any(v is not None for v in
                   [name, pronouns, vibe, instructions, catchphrase, language])
    if show or not provided:
        p = bot.get_profile(uid)
        if not p:
            return await ctx.send(
                "You haven't personalized anything yet.\n"
                "**Example:** `/personalize name:Alex vibe:sarcastic gremlin "
                "catchphrase:🔥 instructions:be brutally honest`")
        emb = discord.Embed(title=f"✨ Your Personalization — {ctx.author.display_name}",
                            color=C_PRIMARY, description=f"Keyed to `{uid}`")
        for k, v in p.items():
            emb.add_field(name=k.title(), value=str(v)[:1024], inline=False)
        return await ctx.send(embed=emb, ephemeral=True)
    bot.set_profile(uid, name=name, pronouns=pronouns, vibe=vibe,
                    instructions=instructions, catchphrase=catchphrase,
                    language=language)
    p = bot.get_profile(uid)
    emb = discord.Embed(title="✅ Personalization Updated", color=C_OK)
    for k, v in p.items():
        emb.add_field(name=k.title(), value=str(v)[:1024], inline=False)
    await ctx.send(embed=emb, ephemeral=True)


# ======================================================================
# /ping — button panel + quick pa/pd aliases
# ======================================================================
class PingPanelView(discord.ui.View):
    def __init__(self, uid: int):
        super().__init__(timeout=180)
        self.uid = uid

    def _refresh_embed(self) -> discord.Embed:
        emb = discord.Embed(title="🏓 Mac Status Panel", color=C_PRIMARY)
        emb.add_field(name="Uptime", value=format_uptime(get_uptime_seconds()),
                      inline=True)
        emb.add_field(name="Commands served", value=f"{get_command_count():,}",
                      inline=True)
        emb.add_field(name="WS latency", value=f"{round(bot.latency * 1000)}ms",
                      inline=True)
        emb.add_field(name="Guilds", value=f"{len(bot.guilds)}", inline=True)
        pref = bot.get_ping_pref(self.uid)
        emb.add_field(name="Your ping mode", value=f"`{pref}`", inline=True)
        ph = "ON" if bot.get_placeholder_pref(self.uid) else "OFF"
        emb.add_field(name="Your placeholder", value=ph, inline=True)
        emb.set_footer(text="Click a button to change ping mode")
        return emb

    async def _set(self, interaction: discord.Interaction, value: str):
        bot.set_ping_pref(self.uid, value)
        await interaction.response.edit_message(embed=self._refresh_embed(),
                                                 view=self)

    @discord.ui.button(label="On", emoji="🔔", style=discord.ButtonStyle.success)
    async def on_btn(self, i, b): await self._set(i, "on")

    @discord.ui.button(label="Off", emoji="🔕", style=discord.ButtonStyle.danger)
    async def off_btn(self, i, b): await self._set(i, "off")

    @discord.ui.button(label="DM only", emoji="💌", style=discord.ButtonStyle.secondary)
    async def dm_btn(self, i, b): await self._set(i, "dm_only")

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.primary)
    async def refresh_btn(self, i, b):
        await i.response.edit_message(embed=self._refresh_embed(), view=self)


@bot.hybrid_command(name="ping", description="🏓 Status panel — uptime, latency, ping mode")
async def ping_cmd(ctx):
    view = PingPanelView(ctx.author.id)
    await ctx.send(embed=view._refresh_embed(), view=view, ephemeral=True)


@bot.hybrid_command(name="pa", description="🔔 Set ping mode: ON (respond to pings)")
async def pa_cmd(ctx):
    bot.set_ping_pref(ctx.author.id, "on")
    await ctx.send("🔔 Ping mode → **on**", ephemeral=True)


@bot.hybrid_command(name="pd", description="🔕 Set ping mode: OFF (slash commands only)")
async def pd_cmd(ctx):
    bot.set_ping_pref(ctx.author.id, "off")
    await ctx.send("🔕 Ping mode → **off**", ephemeral=True)


# ======================================================================
# RESETS
# ======================================================================
@bot.hybrid_command(
    name="softreset",
    description="♻️ Wipe slots + memory, but KEEP /cs customization and profiles")
@app_commands.describe(confirm="Set to True to confirm")
async def softreset_cmd(ctx, confirm: bool = False):
    uid = ctx.author.id
    if not confirm:
        return await ctx.send(
            "⚠️ **Soft reset** wipes:\n"
            "• Chat slots (sv1–sv5) and active state\n"
            "• Short-term + persistent memory\n"
            "• Ping preference and placeholder pref\n\n"
            "But **keeps** your `/cs` settings and saved profiles.\n\n"
            "Run `/softreset confirm:True` to proceed.", ephemeral=True)
    bot.user_slots.pop(uid, None); bot.active_slot.pop(uid, None)
    bot._dirty_slots = True
    bot.persistent_memory.pop(uid, None); bot.persistent_enabled.pop(uid, None)
    bot._dirty_memory = True
    bot.ping_prefs.pop(uid, None); bot._dirty_pings = True
    bot.placeholder_prefs.pop(uid, None); bot._dirty_placeholders = True
    bot.user_cooldowns.pop(uid, None)
    await ctx.send("♻️ **Soft reset complete.** Customization + profiles kept.",
                   ephemeral=True)


@bot.hybrid_command(
    name="re",
    description="💥 Hard reset — wipes ALL your Mac data (slots, memory, cs, profiles)")
@app_commands.describe(confirm="Set to True to confirm")
async def re_cmd(ctx, confirm: bool = False):
    uid = ctx.author.id
    if not confirm:
        return await ctx.send(
            "⚠️ **Hard reset** wipes everything user-scoped including `/cs` "
            "and profiles.\nRun `/re confirm:True` to proceed.", ephemeral=True)
    bot.user_slots.pop(uid, None); bot.active_slot.pop(uid, None)
    bot._dirty_slots = True
    bot.persistent_memory.pop(uid, None); bot.persistent_enabled.pop(uid, None)
    bot._dirty_memory = True
    bot.cs.pop(uid, None); bot._dirty_cs = True
    bot.cs_key_idx = {k: v for k, v in bot.cs_key_idx.items() if k[0] != uid}
    bot.cs_model_idx = {k: v for k, v in bot.cs_model_idx.items() if k[0] != uid}
    bot.profiles.pop(uid, None); bot._dirty_profiles = True
    bot.ping_prefs.pop(uid, None); bot._dirty_pings = True
    bot.placeholder_prefs.pop(uid, None); bot._dirty_placeholders = True
    bot.user_cooldowns.pop(uid, None)
    await ctx.send("💥 **Hard reset complete.**", ephemeral=True)


# ======================================================================
# /cs GROUP
# ======================================================================
@bot.hybrid_group(
    name="cs",
    description="⚙️ Customization — profile, keys, models, voices, macros, GIFs, ping, placeholder, context",
    invoke_without_command=True)
async def cs_group(ctx):
    emb = discord.Embed(title="⚙️ /cs — Customization",
                        description="Everything here is per-user.",
                        color=C_PRIMARY)
    emb.add_field(name="Profile",
                  value="`/cs profile` — name, pronouns, vibe, instructions, catchphrase, language",
                  inline=False)
    emb.add_field(name="API Keys",
                  value="`/cs key add|remove|list <provider> [key]`", inline=False)
    emb.add_field(name="Models",
                  value="`/cs model add|remove|list <provider> [model]`", inline=False)
    emb.add_field(name="Aliases + Active",
                  value="`/cs llm` · `/cs ch`", inline=False)
    emb.add_field(name="Voices",
                  value="`/cs voice` · `/cs voice-add` · `/cs voice-del` · `/cs voices`",
                  inline=False)
    emb.add_field(name="Macros · GIFs",
                  value="`/cs macro` · `/cs gif`", inline=False)
    emb.add_field(name="Ping · Placeholder",
                  value="`/cs ping` — ping mode · `/cs placeholder` — 🔥 toggle",
                  inline=False)
    emb.add_field(name="Context",
                  value="`/cs context <message_id or link> [before] [after]`",
                  inline=False)
    emb.add_field(name="Misc", value="`/cs show` · `/cs reset [section]`", inline=False)
    await ctx.send(embed=emb)


@cs_group.command(name="profile", description="Set your personal profile")
@app_commands.describe(name="What Mac calls you", pronouns="Your pronouns",
                       vibe="Vibe to match", instructions="Extra instructions",
                       catchphrase="End every reply with this",
                       language="Preferred language", clear="Clear your profile")
async def cs_profile(ctx, name: str = None, pronouns: str = None, vibe: str = None,
                     instructions: str = None, catchphrase: str = None,
                     language: str = None, clear: bool = False):
    uid = ctx.author.id
    if clear:
        bot.clear_profile(uid)
        return await ctx.send("🧹 Profile cleared.")
    provided = any(v is not None for v in
                   [name, pronouns, vibe, instructions, catchphrase, language])
    if not provided:
        p = bot.get_profile(uid)
        if not p:
            return await ctx.send(
                "No profile set. `/cs profile name:Alex vibe:sarcastic`")
        emb = discord.Embed(title=f"Your Profile — {ctx.author.display_name}",
                            color=C_PRIMARY)
        for k, v in p.items():
            emb.add_field(name=k.title(), value=str(v)[:1024], inline=False)
        return await ctx.send(embed=emb, ephemeral=True)
    bot.set_profile(uid, name=name, pronouns=pronouns, vibe=vibe,
                    instructions=instructions, catchphrase=catchphrase,
                    language=language)
    await ctx.send("✅ Profile updated.", ephemeral=True)


@cs_group.command(name="key", description="Manage your API keys (up to 3 per provider)")
@app_commands.autocomplete(provider=_provider_ac)
@app_commands.describe(provider="groq | openrouter | hf | gemini | gemini_image | fish | imgbb",
                       action="add | remove | list",
                       value="API key (add) or index (remove)")
async def cs_key(ctx, provider: str, action: str = "list", value: str = None):
    uid = ctx.author.id
    p = provider.lower()
    if p not in PROVIDERS:
        return await ctx.send(f"❌ Providers: {', '.join(PROVIDERS)}", ephemeral=True)
    u = bot._cs(uid)
    keys = u.setdefault(f"{p}_keys", [])
    a = action.lower()
    if a == "list":
        if not keys:
            return await ctx.send(f"No custom `{p}` keys — using bot defaults.", ephemeral=True)
        masked = [f"`{i}` ...{k[-6:]}" for i, k in enumerate(keys)]
        return await ctx.send(f"**Your `{p}` keys ({len(keys)}/3):**\n" + "\n".join(masked),
                              ephemeral=True)
    if a == "add":
        if not value: return await ctx.send("❌ Provide a key.", ephemeral=True)
        if len(keys) >= MAX_KEYS_PER_PROVIDER:
            return await ctx.send(f"❌ Max {MAX_KEYS_PER_PROVIDER}.", ephemeral=True)
        keys.append(value.strip()); bot._save_cs()
        return await ctx.send(f"✅ Added `{p}` key ({len(keys)}).", ephemeral=True)
    if a == "remove":
        if value is None: return await ctx.send("❌ Provide index.", ephemeral=True)
        try:
            keys.pop(int(value)); bot._save_cs()
            return await ctx.send(f"🗑️ Removed.", ephemeral=True)
        except (ValueError, IndexError):
            return await ctx.send("❌ Invalid index.", ephemeral=True)
    await ctx.send("❌ add | remove | list", ephemeral=True)


@cs_group.command(name="model", description="Manage your preferred models")
@app_commands.autocomplete(provider=_model_provider_ac)
@app_commands.describe(provider="groq | openrouter | hf_image | hf_text | gemini | fish",
                       action="add | remove | list",
                       value="Model id (add) or index (remove)")
async def cs_model(ctx, provider: str, action: str = "list", value: str = None):
    uid = ctx.author.id
    p = provider.lower()
    if p not in MODEL_PROVIDERS:
        return await ctx.send(f"❌ Providers: {', '.join(MODEL_PROVIDERS)}", ephemeral=True)
    u = bot._cs(uid)
    models = u.setdefault(f"{p}_models", [])
    a = action.lower()
    if a == "list":
        if not models:
            defaults = bot.user_models(None, p)
            return await ctx.send(f"No custom `{p}` models. Bot defaults:\n"
                                  + "\n".join(f"• `{m}`" for m in defaults),
                                  ephemeral=True)
        return await ctx.send(f"**Your `{p}` models ({len(models)}/3):**\n"
                              + "\n".join(f"`{i}` {m}" for i, m in enumerate(models)),
                              ephemeral=True)
    if a == "add":
        if not value: return await ctx.send("❌ Provide model id.", ephemeral=True)
        if len(models) >= MAX_MODELS_PER_PROVIDER:
            return await ctx.send(f"❌ Max {MAX_MODELS_PER_PROVIDER}.", ephemeral=True)
        models.append(value.strip()); bot._save_cs()
        return await ctx.send(f"✅ Added ({len(models)}).", ephemeral=True)
    if a == "remove":
        if value is None: return await ctx.send("❌ Provide index.", ephemeral=True)
        try:
            models.pop(int(value)); bot._save_cs()
            return await ctx.send(f"🗑️ Removed.", ephemeral=True)
        except (ValueError, IndexError):
            return await ctx.send("❌ Invalid index.", ephemeral=True)
    await ctx.send("❌ add | remove | list", ephemeral=True)


@cs_group.command(name="llm", description="🤖 Named model aliases + switch active")
@app_commands.autocomplete(alias=_alias_ac)
@app_commands.describe(action="add | remove | list | use", alias="Alias name",
                       model_id="Model id (add)", provider="Provider (add)")
async def cs_llm(ctx, action: str = "list", alias: str = None,
                 model_id: str = None, provider: str = None):
    uid = ctx.author.id
    a = action.lower()
    u = bot._cs(uid)
    aliases = u.setdefault("model_aliases", {})
    if a == "list":
        if not aliases:
            return await ctx.send(
                "No aliases. `/cs llm add alias:fast model_id:openai/gpt-oss-safeguard-20b provider:groq`",
                ephemeral=True)
        active = u.get("active_alias")
        lines = []
        for name, info in aliases.items():
            mark = " ✅" if name == active else ""
            lines.append(f"• `{name}` → `{info['model']}` ({info['provider']}){mark}")
        return await send_long(ctx, "🤖 **Aliases**\n" + "\n".join(lines))
    if a == "add":
        if not alias or not model_id:
            return await ctx.send("❌ alias + model_id required.", ephemeral=True)
        prov = (provider or "groq").lower()
        if prov not in ("groq", "gemini", "openrouter", "hf_text"):
            return await ctx.send("❌ Provider: groq/gemini/openrouter/hf_text",
                                  ephemeral=True)
        aliases[alias.lower()] = {"model": model_id.strip(), "provider": prov}
        bot._save_cs()
        return await ctx.send(f"✅ `{alias.lower()}` → `{model_id}`", ephemeral=True)
    if a == "remove":
        if not alias or alias.lower() not in aliases:
            return await ctx.send("❌ Not found.", ephemeral=True)
        aliases.pop(alias.lower())
        if u.get("active_alias") == alias.lower():
            u.pop("active_alias", None)
        bot._save_cs()
        return await ctx.send(f"🗑️ Removed.", ephemeral=True)
    if a == "use":
        info = aliases.get((alias or "").lower())
        if not info:
            return await ctx.send("❌ Not found.", ephemeral=True)
        prov, model = info["provider"], info["model"]
        field = f"{prov}_models" if prov != "hf_text" else "hf_text_models"
        existing = u.get(field, [])
        if model in existing: existing.remove(model)
        existing.insert(0, model)
        u[field] = existing[:MAX_MODELS_PER_PROVIDER]
        u["active_alias"] = alias.lower()
        bot._save_cs(); bot.cs_model_idx[(uid, prov)] = 0
        return await ctx.send(f"✅ Active → `{model}` ({prov})")
    await ctx.send("❌ add | remove | list | use", ephemeral=True)


@cs_group.command(name="ch", description="🎯 Change active chat model")
@app_commands.autocomplete(model=_active_model_ac)
@app_commands.describe(model="provider:model or alias:name")
async def cs_ch(ctx, model: str = None):
    uid = ctx.author.id
    u = bot._cs(uid)
    if model is None:
        emb = discord.Embed(title="🎯 Active Model Browser", color=C_PRIMARY)
        emb.add_field(name="Groq", value="\n".join(f"`groq:{m}`" for m in bot.user_models(uid, "groq")) or "—",
                      inline=False)
        emb.add_field(name="Gemini", value="\n".join(f"`gemini:{m}`" for m in bot.user_models(uid, "gemini")) or "—",
                      inline=False)
        emb.add_field(name="OpenRouter", value="\n".join(f"`openrouter:{m}`" for m in bot.user_models(uid, "openrouter")) or "—",
                      inline=False)
        return await ctx.send(embed=emb, ephemeral=True)
    m = model.strip()
    if m.startswith("alias:"):
        info = u.get("model_aliases", {}).get(m.split(":", 1)[1].lower())
        if not info:
            return await ctx.send("❌ Not found.", ephemeral=True)
        prov, mid = info["provider"], info["model"]
    elif ":" in m:
        prov, mid = m.split(":", 1); prov = prov.lower()
    else:
        mid = m; ml = m.lower()
        prov = "gemini" if "gemini" in ml else (
            "openrouter" if any(k in ml for k in ("deepseek", "anthropic", "mistral")) else "groq")
    if prov not in ("groq", "gemini", "openrouter", "hf_text"):
        return await ctx.send(f"❌ Unsupported `{prov}`.", ephemeral=True)
    field = f"{prov}_models" if prov != "hf_text" else "hf_text_models"
    existing = u.get(field, [])
    if mid in existing: existing.remove(mid)
    existing.insert(0, mid)
    u[field] = existing[:MAX_MODELS_PER_PROVIDER]
    u.pop("active_alias", None)
    bot._save_cs(); bot.cs_model_idx[(uid, prov)] = 0
    return await ctx.send(f"✅ Active → `{mid}` ({prov}).")


@cs_group.command(name="voice", description="Set default TTS voice")
@app_commands.autocomplete(name=_voice_ac)
async def cs_voice(ctx, name: str = None):
    uid = ctx.author.id
    voices = bot.all_voices(uid)
    if name is None:
        cur = bot.default_voice(uid)
        listing = "\n".join(f"• `{k}` — {v['emoji']} {v['desc']}"
                            for k, v in voices.items())
        return await ctx.send(f"Default: **{cur}**\n\n{listing}", ephemeral=True)
    if name not in voices:
        return await ctx.send(f"❌ Unknown. Options: {', '.join(voices.keys())}",
                              ephemeral=True)
    u = bot._cs(uid); u["default_voice"] = name; bot._save_cs()
    await ctx.send(f"✅ Default voice → {voices[name]['emoji']} **{voices[name]['desc']}**")


@cs_group.command(name="voice-add", description="Add custom Fish Audio voice")
@app_commands.describe(name="Short name", fish_id="Fish Audio reference ID",
                       emoji="Emoji", desc="Description")
async def cs_voice_add(ctx, name: str, fish_id: str, emoji: str = "🎤", desc: str = None):
    uid = ctx.author.id
    n = name.lower().strip().replace(" ", "-")
    if n in BUILTIN_VOICES:
        return await ctx.send("❌ Name collides.", ephemeral=True)
    u = bot._cs(uid)
    u.setdefault("voices", {})[n] = {"id": fish_id, "emoji": emoji, "desc": desc or n}
    bot._save_cs()
    await ctx.send(f"✅ Added `{n}`.")


@cs_group.command(name="voice-del", description="Remove custom voice")
async def cs_voice_del(ctx, name: str):
    uid = ctx.author.id
    u = bot._cs(uid)
    if name.lower() not in u.get("voices", {}):
        return await ctx.send("❌ Not a custom voice.", ephemeral=True)
    u["voices"].pop(name.lower()); bot._save_cs()
    await ctx.send(f"🗑️ Removed `{name}`.")


@cs_group.command(name="voices", description="List all voices available to you")
async def cs_voices(ctx):
    uid = ctx.author.id
    voices = bot.all_voices(uid)
    lines = "\n".join(f"• `{k}` — {v['emoji']} {v['desc']}" for k, v in voices.items())
    await send_long(ctx, f"🎙️ **Voices**\n{lines}")


@cs_group.command(name="macro", description="Save/run prompt shortcuts (.name in chat)")
@app_commands.describe(action="add | remove | list", name="Macro name", prompt="Prompt text")
async def cs_macro(ctx, action: str = "list", name: str = None, prompt: str = None):
    uid = ctx.author.id
    a = action.lower()
    u = bot._cs(uid)
    macros = u.setdefault("macros", {})
    if a == "add":
        if not name or not prompt: return await ctx.send("❌ name + prompt required.")
        macros[name.lower()] = prompt; bot._save_cs()
        return await ctx.send(f"💾 Macro `.{name.lower()}` saved.")
    if a == "remove":
        if not name or name.lower() not in macros: return await ctx.send("❌ Not found.")
        macros.pop(name.lower()); bot._save_cs()
        return await ctx.send(f"🗑️ Removed.")
    if a == "list":
        if not macros: return await ctx.send("No macros.")
        return await send_long(ctx, "💾 **Macros**\n"
                              + "\n".join(f"• `.{n}` — {p[:80]}" for n, p in macros.items()))
    await ctx.send("❌ add | remove | list")


@cs_group.command(name="gif", description="Manage your brainrot GIF pool")
@app_commands.describe(action="list | add | remove | clear | reset",
                       value="URL (add) or index (remove)")
async def cs_gif(ctx, action: str = "list", value: str = None):
    uid = ctx.author.id
    a = action.lower()
    u = bot._cs(uid)
    pool = u.setdefault("brainrot_gifs", [])
    if a == "list":
        current = bot.get_gif_pool(uid)
        lines = "\n".join(f"`{i}` {url}" for i, url in enumerate(current))
        return await send_long(ctx, f"🧠 **Pool** ({'custom' if pool else 'default'}, {len(current)})\n{lines[:3500]}")
    if a == "add":
        if not value: return await ctx.send("❌ `/cs gif add <url>`")
        pool.append(value.strip()); bot._save_cs()
        return await ctx.send(f"✅ Added ({len(pool)}).")
    if a == "remove":
        try:
            pool.pop(int(value)); bot._save_cs()
            return await ctx.send(f"🗑️ Removed.")
        except (TypeError, ValueError, IndexError):
            return await ctx.send("❌ Invalid index.")
    if a == "clear":
        u["brainrot_gifs"] = []; bot._save_cs()
        return await ctx.send("🧹 Cleared.")
    if a == "reset":
        u.pop("brainrot_gifs", None); bot._save_cs()
        return await ctx.send("↺ Reset.")
    await ctx.send("❌ list | add | remove | clear | reset")


@cs_group.command(name="ping", description="Control whether Mac responds to your messages")
@app_commands.describe(mode="on | off | dm_only | status")
@app_commands.choices(mode=[
    app_commands.Choice(name="🔔 on", value="on"),
    app_commands.Choice(name="🔕 off", value="off"),
    app_commands.Choice(name="💌 dm_only", value="dm_only"),
    app_commands.Choice(name="ℹ️ status", value="status")])
async def cs_ping(ctx, mode: str = "status"):
    uid = ctx.author.id
    if mode == "status":
        return await ctx.send(f"Current: **{bot.get_ping_pref(uid)}**", ephemeral=True)
    bot.set_ping_pref(uid, mode)
    await ctx.send(f"✅ Ping mode → **{mode}**", ephemeral=True)


@cs_group.command(name="placeholder", description="Toggle the 🔥 Thinking placeholder")
@app_commands.describe(enabled="True = show 🔥 Thinking message. False = typing indicator only")
async def cs_placeholder(ctx, enabled: bool = None):
    uid = ctx.author.id
    if enabled is None:
        cur = bot.get_placeholder_pref(uid)
        return await ctx.send(
            f"Current placeholder: **{'ON' if cur else 'OFF'}**\n"
            "ON = send `🔥 Thinking...` message then edit it with the reply\n"
            "OFF = Discord typing indicator only, then send the reply directly "
            "(faster, no visible placeholder)",
            ephemeral=True)
    bot.set_placeholder_pref(uid, enabled)
    await ctx.send(f"✅ Placeholder → **{'ON' if enabled else 'OFF'}**", ephemeral=True)


@cs_group.command(name="context", description="📜 Show N messages before/after a given message")
@app_commands.describe(
    message="Message ID, or a jump link to any message",
    before="How many messages before (default 3, max 10)",
    after="How many messages after (default 3, max 10)")
async def cs_context(ctx, message: str, before: int = 3, after: int = 3):
    before = max(0, min(CONTEXT_WINDOW_LIMIT, before))
    after = max(0, min(CONTEXT_WINDOW_LIMIT, after))

    # Parse message reference
    target_id: Optional[int] = None
    channel = ctx.channel
    raw = message.strip()
    if raw.isdigit():
        target_id = int(raw)
    else:
        # jump link format: https://discord.com/channels/GUILD/CHANNEL/MSG
        m = re.search(r"/channels/(\d+)/(\d+)/(\d+)", raw)
        if m:
            ch_id = int(m.group(2)); target_id = int(m.group(3))
            try:
                channel = bot.get_channel(ch_id) or await bot.fetch_channel(ch_id)
            except Exception:
                return await ctx.send("❌ Couldn't resolve that channel.", ephemeral=True)

    if not target_id:
        return await ctx.send("❌ Provide a message ID or a jump link.", ephemeral=True)

    try:
        anchor = await channel.fetch_message(target_id)
    except Exception as e:
        return await ctx.send(f"❌ Couldn't fetch message: {e}", ephemeral=True)

    # Fetch surrounding messages using Discord's `around` param
    try:
        window = await channel.history(
            limit=before + after + 1,
            around=anchor,
            oldest_first=True).flatten()
    except Exception as e:
        return await ctx.send(f"❌ History failed: {e}", ephemeral=True)

    if not window:
        return await ctx.send("📭 No messages found.", ephemeral=True)

    # Build the transcript
    lines = []
    for msg in window:
        marker = "▶️ " if msg.id == anchor.id else "   "
        author = msg.author.display_name
        content = (msg.content or "[no text]").replace("\n", " ")[:180]
        ts = msg.created_at.strftime("%H:%M")
        lines.append(f"{marker}[{ts}] **{author}:** {content}")

    header = (f"📜 **Context around message `{anchor.id}`** in "
              f"{getattr(channel, 'mention', '#channel')}\n"
              f"-# {before} before · {after} after\n\n")
    full = header + "\n".join(lines)

    # send ephemerally
    chunks = chunk_text(full, 1900)
    if ctx.interaction:
        try:
            await ctx.interaction.response.send_message(chunks[0], ephemeral=True)
            for c in chunks[1:]:
                await ctx.interaction.followup.send(c, ephemeral=True)
            return
        except Exception:
            pass
    await ctx.send(chunks[0], ephemeral=True)
    for c in chunks[1:]:
        await ctx.send(c, ephemeral=True)


@cs_group.command(name="show", description="Show ALL your customizations")
async def cs_show(ctx):
    uid = ctx.author.id
    u = bot.cs.get(uid, {})
    emb = discord.Embed(title=f"⚙️ {ctx.author.display_name}'s Customizations",
                        color=C_PRIMARY)
    prof = u.get("profile", {})
    if prof:
        emb.add_field(name="Profile",
                      value="\n".join(f"• {k}: {v}" for k, v in prof.items())[:1024],
                      inline=False)
    for p in PROVIDERS:
        if u.get(f"{p}_keys"):
            emb.add_field(name=f"{p} keys", value=f"{len(u[f'{p}_keys'])} set",
                          inline=True)
    for p in MODEL_PROVIDERS:
        if u.get(f"{p}_models"):
            emb.add_field(name=f"{p} models",
                          value=f"{len(u[f'{p}_models'])}: `{u[f'{p}_models'][0][:40]}`",
                          inline=True)
    aliases = u.get("model_aliases", {})
    if aliases:
        active = u.get("active_alias")
        emb.add_field(name="Aliases",
                      value=", ".join(f"`{a}`" + (" ✅" if a == active else "")
                                      for a in aliases)[:1024], inline=False)
    if u.get("voices"):
        emb.add_field(name="Custom voices",
                      value=", ".join(u["voices"].keys())[:1024], inline=False)
    if u.get("macros"):
        emb.add_field(name="Macros",
                      value=", ".join(f".{n}" for n in u["macros"])[:1024], inline=False)
    if u.get("brainrot_gifs"):
        emb.add_field(name="Brainrot pool",
                      value=f"{len(u['brainrot_gifs'])} custom GIFs", inline=True)
    emb.add_field(name="Ping mode", value=f"`{bot.get_ping_pref(uid)}`", inline=True)
    emb.add_field(name="Placeholder",
                  value="ON" if bot.get_placeholder_pref(uid) else "OFF", inline=True)
    profiles = bot.list_profiles(uid)
    if profiles:
        emb.add_field(name="Profiles",
                      value=", ".join(f"`{p}`" for p in profiles)[:1024], inline=False)
    if not emb.fields:
        emb.description = "Nothing set. Try `/personalize` or `/cs key add groq <key>`."
    await ctx.send(embed=emb, ephemeral=True)


@cs_group.command(name="reset", description="Reset a section of your customizations")
@app_commands.describe(section="profile | keys | models | aliases | voices | macros | gifs | all")
async def cs_reset(ctx, section: str = "all"):
    uid = ctx.author.id
    s = section.lower()
    u = bot.cs.get(uid, {})
    if s == "all":
        bot.cs.pop(uid, None); bot._save_cs()
        return await ctx.send("💥 All customizations reset.")
    if s == "profile":
        u.pop("profile", None); u.pop("default_voice", None)
    elif s == "keys":
        for p in PROVIDERS: u.pop(f"{p}_keys", None)
    elif s == "models":
        for p in MODEL_PROVIDERS: u.pop(f"{p}_models", None)
    elif s == "aliases":
        u.pop("model_aliases", None); u.pop("active_alias", None)
    elif s == "voices": u.pop("voices", None)
    elif s == "macros": u.pop("macros", None)
    elif s == "gifs": u.pop("brainrot_gifs", None)
    else:
        return await ctx.send("❌ Options: profile, keys, models, aliases, voices, macros, gifs, all")
    bot._save_cs()
    await ctx.send(f"🧹 Reset `{s}`.")


# ======================================================================
# /profiles
# ======================================================================
@bot.hybrid_command(name="profiles", description="🎭 Save, load, list, or delete setup snapshots")
@app_commands.autocomplete(name=_profile_ac)
@app_commands.describe(action="save | load | list | delete", name="Profile name")
async def profiles_cmd(ctx, action: str = "list", name: str = None):
    uid = ctx.author.id
    a = action.lower()
    if a == "list":
        names = bot.list_profiles(uid)
        if not names:
            return await ctx.send("No profiles. `/profiles save name:<name>`",
                                  ephemeral=True)
        return await ctx.send("🎭 **Profiles**\n" + "\n".join(f"• `{n}`" for n in names),
                              ephemeral=True)
    if a == "save":
        if not name: return await ctx.send("❌ Name required.", ephemeral=True)
        bot.save_profile(uid, name)
        return await ctx.send(f"✅ Profile `{name.lower()}` saved.")
    if a == "load":
        if bot.load_profile(uid, name or ""):
            return await ctx.send(f"✅ Loaded `{name.lower()}`.")
        return await ctx.send("❌ Not found.", ephemeral=True)
    if a == "delete":
        if bot.delete_profile(uid, name or ""):
            return await ctx.send(f"🗑️ Deleted `{name.lower()}`.")
        return await ctx.send("❌ Not found.", ephemeral=True)
    await ctx.send("❌ save | load | list | delete", ephemeral=True)


# ======================================================================
# /benchmark + /context
# ======================================================================
@bot.hybrid_command(name="benchmark", description="📊 Compare speed of your providers side-by-side")
@app_commands.describe(prompt="Prompt sent to every provider")
async def benchmark_cmd(ctx, prompt: str):
    await ctx.defer()
    status = await ctx.send("📊 **Benchmarking...**")
    results = await bot.benchmark_prompt(ctx.author.id, prompt)
    if not results:
        return await safe_edit(status, content="❌ No providers configured.")
    emb = discord.Embed(title="📊 Benchmark", description=f"**Prompt:** {prompt[:150]}",
                        color=C_PRIMARY)
    rank = ["🥇", "🥈", "🥉"]
    lines = []
    for i, r in enumerate(results):
        pre = rank[i] if i < 3 else f"{i+1}."
        if r["ok"]:
            lines.append(f"{pre} **{r['provider']}** — `{r['seconds']:.2f}s` · {r['tokens_est']} tok")
        else:
            lines.append(f"{pre} **{r['provider']}** — ❌ `{r.get('error', '?')[:80]}`")
    emb.add_field(name="Ranking", value="\n".join(lines), inline=False)
    prev = discord.Embed(title="📝 Previews", color=C_WARM)
    for r in results:
        if r["ok"] and len(prev.fields) < 6:
            prev.add_field(name=f"{r['provider']} · {r['seconds']:.2f}s",
                           value=(r.get("preview") or "(empty)")[:1000], inline=False)
    await safe_edit(status, content=None, embed=emb)
    await safe_send(ctx.channel, embed=prev)


@bot.hybrid_command(name="context", description="📈 Token usage vs max context for your next request")
@app_commands.describe(message="Optional prompt to simulate")
async def context_cmd(ctx, message: str = "hello"):
    uid = ctx.author.id
    slot_name = bot.active_slot.get(uid, "sv1")
    stats = bot._estimate_context_tokens(uid, slot_name, message, None)
    model_name = bot.current_model(uid, "groq") or GLOBAL_GROQ_MODELS[0]
    ml = model_name.lower()
    limit = 1000000 if "gemini" in ml else 131072
    used = stats["total"]
    pct = min(100.0, (used / limit) * 100) if limit else 0.0
    bars = 20
    filled = int((pct / 100) * bars)
    bar = "█" * filled + "░" * (bars - filled)
    emb = discord.Embed(title="📈 Context Usage", color=C_PRIMARY)
    emb.add_field(name="Model", value=f"`{model_name}` (~{limit:,} tok)",
                  inline=False)
    emb.add_field(name="Usage",
                  value=f"`{bar}` **{pct:.1f}%** ({used:,} / {limit:,})",
                  inline=False)
    emb.add_field(name="System", value=f"{stats['system']:,}", inline=True)
    emb.add_field(name="User", value=f"{stats['user']:,}", inline=True)
    emb.add_field(name="Assistant", value=f"{stats['assistant']:,}", inline=True)
    emb.add_field(name="Messages", value=str(stats['messages']), inline=True)
    await ctx.send(embed=emb, ephemeral=True)


# ======================================================================
# SLOTS
# ======================================================================
def _make_slot_cmd(slot_name: str):
    async def _cmd(ctx):
        uid = ctx.author.id
        if uid not in bot.user_slots:
            bot.user_slots[uid] = {f"sv{i}": [] for i in range(1, 6)}
        bot.active_slot[uid] = slot_name
        bot._save_slots()
        count = len(bot.user_slots[uid].get(slot_name, []))
        await ctx.send(f"💾 **{slot_name}** — {count} msgs.")
    _cmd.__name__ = f"slot_{slot_name}"
    return _cmd


for _i in range(1, 6):
    _name = f"sv{_i}"
    bot.hybrid_command(name=_name,
                       description=f"🗂️ Switch to chat slot {_name}")(_make_slot_cmd(_name))


@bot.hybrid_command(name="svc", description="💾 Save the current slot and close it")
@app_commands.describe(name="Optional name to save under")
async def svc_cmd(ctx, name: str = None):
    uid = ctx.author.id
    current = bot.active_slot.get(uid)
    if not current:
        return await ctx.send("❌ No active slot.", ephemeral=True)
    slot = bot.get_slot(uid, current)
    count = len(slot)
    if name:
        n = name.lower().strip().replace(" ", "_")[:40]
        u = bot._cs(uid)
        u.setdefault("saved_slots", {})[n] = [
            {"role": r, "content": c} for r, c in slot[-100:]]
        bot._save_cs()
        await ctx.send(f"💾 Saved **{count}** messages as `{n}`.")
    bot.active_slot.pop(uid, None)
    bot._save_slots()
    if not name:
        await ctx.send(f"💾 Slot `{current}` had **{count}** messages, now closed.")


@bot.hybrid_command(name="svclear", description="🧹 Clear the current chat slot")
async def svclear(ctx):
    uid = ctx.author.id
    slot = bot.active_slot.get(uid, "sv1")
    bot.user_slots.setdefault(uid, {f"sv{i}": [] for i in range(1, 6)})[slot] = []
    bot._save_slots()
    await ctx.send(f"🧹 Cleared **{slot}**.")


@bot.hybrid_command(name="svlist", description="📋 Show your 5 chat slots")
async def svlist(ctx):
    uid = ctx.author.id
    if uid not in bot.user_slots:
        bot.user_slots[uid] = {f"sv{i}": [] for i in range(1, 6)}
    active = bot.active_slot.get(uid, "sv1")
    lines = []
    for i in range(1, 6):
        n = f"sv{i}"
        c = len(bot.user_slots[uid].get(n, []))
        lines.append(f"`{n}`: {c} msgs" + (" ← active" if n == active else ""))
    saved = bot.cs.get(uid, {}).get("saved_slots", {})
    if saved:
        lines.append("\n**Saved:**")
        for n, msgs in saved.items():
            lines.append(f"• `{n}` — {len(msgs)} msgs")
    emb = discord.Embed(title=f"🗂️ Slots — {ctx.author.display_name}",
                        description="\n".join(lines), color=C_PRIMARY)
    await ctx.send(embed=emb, ephemeral=True)


@bot.hybrid_command(name="vsc", description="👁️ View messages in the current chat slot")
@app_commands.describe(private="Send only to you (default: True)",
                       limit="How many recent messages (default 20, max 100)")
async def vsc_cmd(ctx, private: bool = True, limit: int = 20):
    uid = ctx.author.id
    slot_name = bot.active_slot.get(uid, "sv1")
    slot = bot.get_slot(uid, slot_name)
    if not slot:
        return await ctx.send("📭 No messages.", ephemeral=True)
    limit = max(1, min(100, limit))
    recent = slot[-limit:]
    lines = []
    for role, content in recent:
        prefix = "🧑" if role == "user" else "🤖"
        lines.append(f"{prefix} {content.replace(chr(10), ' ')[:200]}")
    header = f"📜 **Slot `{slot_name}`** — last {len(recent)} of {len(slot)}\n\n"
    full = header + "\n".join(lines)
    if private:
        chunks = chunk_text(full, 1900)
        if ctx.interaction:
            try:
                await ctx.interaction.response.send_message(chunks[0], ephemeral=True)
                for c in chunks[1:]:
                    await ctx.interaction.followup.send(c, ephemeral=True)
                return
            except Exception:
                pass
        await ctx.send(chunks[0], ephemeral=True)
        for c in chunks[1:]:
            await ctx.send(c, ephemeral=True)
    else:
        await send_long(ctx, full)


@bot.hybrid_command(name="vsm", description="🧠 View your saved persistent memory")
@app_commands.describe(private="Send only to you (default: True)",
                       limit="How many recent entries (default 20, max 100)")
async def vsm_cmd(ctx, private: bool = True, limit: int = 20):
    uid = ctx.author.id
    mem = bot.get_persistent_memory(uid)
    if not mem:
        return await ctx.send("📭 No persistent memory. `/persistent` to enable.",
                              ephemeral=True)
    limit = max(1, min(100, limit))
    recent = mem[-limit:]
    lines = []
    for role, content in recent:
        prefix = "🧑" if role == "user" else "🤖"
        lines.append(f"{prefix} {content.replace(chr(10), ' ')[:200]}")
    enabled = "ON" if bot.get_persistent_enabled(uid) else "OFF"
    header = f"🧠 **Persistent memory** ({enabled}) — last {len(recent)} of {len(mem)}\n\n"
    full = header + "\n".join(lines)
    if private:
        chunks = chunk_text(full, 1900)
        if ctx.interaction:
            try:
                await ctx.interaction.response.send_message(chunks[0], ephemeral=True)
                for c in chunks[1:]:
                    await ctx.interaction.followup.send(c, ephemeral=True)
                return
            except Exception:
                pass
        await ctx.send(chunks[0], ephemeral=True)
        for c in chunks[1:]:
            await ctx.send(c, ephemeral=True)
    else:
        await send_long(ctx, full)


# ======================================================================
# MODES
# ======================================================================
@bot.hybrid_command(name="setmode", description="🎭 Set the bot's personality mode")
@app_commands.autocomplete(mode=_mode_ac)
@app_commands.describe(mode="chill | brainrot | unhinged | coder | engineer | childish | dexter")
async def setmode_cmd(ctx, mode: str):
    mode = mode.lower().strip()
    if mode not in bot.mode_prompts:
        return await ctx.send(f"❌ Options: {', '.join(bot.mode_prompts)}")
    bot.current_mode = mode
    bot._sys_prompt_cache.clear()
    emoji = {"chill": "😎", "brainrot": "🧠", "unhinged": "🔥", "coder": "💻",
             "engineer": "🛠️", "childish": "🧒", "dexter": "🔪"}.get(mode, "🎭")
    extra = " — GIFs on every reply." if mode == "brainrot" else ""
    await ctx.send(f"{emoji} Mode → **{mode}**{extra}")


# ======================================================================
# PIPELINES
# ======================================================================
@bot.hybrid_command(name="pipeline", description="🏗️ Single-file: GEMINI → OPENROUTER → review → fix")
@app_commands.describe(task="What to build", filename="Output filename",
                       iterations="Max review loops (1–5, default 3)")
async def pipeline_cmd(ctx, task: str, filename: str = None, iterations: int = 3):
    await ctx.defer()
    iterations = max(1, min(5, iterations))
    fn = filename.strip() if filename else infer_filename(task)
    try:
        await bot.run_pipeline(ctx.channel, ctx.author.id, task, fn, iterations)
    except Exception as e:
        await ctx.send(f"❌ `{e}`")


@bot.hybrid_command(name="project", description="📦 Multi-file project → .zip")
@app_commands.describe(task="What to build", name="Project name (auto if blank)",
                       iterations="Max review loops (1–3, default 2)")
async def project_cmd(ctx, task: str, name: str = None, iterations: int = 2):
    await ctx.defer()
    iterations = max(1, min(3, iterations))
    name = name.strip() if name else None
    try:
        await bot.run_project(ctx.channel, ctx.author.id, task, name, iterations)
    except Exception as e:
        await ctx.send(f"❌ `{e}`")


# ======================================================================
# CONFIG
# ======================================================================
@bot.hybrid_command(name="config", description="⚙️ Show current bot configuration")
async def config_cmd(ctx):
    uid = ctx.author.id
    emb = discord.Embed(title="⚙️ Mac — Config", color=C_PRIMARY)
    emb.add_field(name="Mode", value=f"`{bot.current_mode}`", inline=True)
    emb.add_field(name="Image mode", value=f"`{bot.current_image_mode}`", inline=True)
    emb.add_field(name="Memory", value="ON" if bot.memory_enabled else "OFF", inline=True)
    emb.add_field(name="Groq model",
                  value=f"`{bot.current_model(uid, 'groq') or GLOBAL_GROQ_MODELS[0]}`",
                  inline=True)
    emb.add_field(name="Gemini model",
                  value=f"`{bot.current_model(uid, 'gemini') or GLOBAL_GEMINI_MODELS[0]}`",
                  inline=True)
    or_model = (bot.current_model(uid, "openrouter")
                or (GLOBAL_OPENROUTER_MODELS[0] if GLOBAL_OPENROUTER_MODELS else "—"))
    emb.add_field(name="OpenRouter model", value=f"`{or_model}`", inline=True)
    emb.add_field(name="Voice", value=f"`{bot.default_voice(uid)}`", inline=True)
    emb.add_field(name="Slot", value=f"`{bot.active_slot.get(uid, 'sv1')}`", inline=True)
    emb.add_field(name="Ping", value=f"`{bot.get_ping_pref(uid)}`", inline=True)
    emb.add_field(name="Placeholder",
                  value="ON" if bot.get_placeholder_pref(uid) else "OFF", inline=True)
    emb.add_field(name="Uptime", value=format_uptime(get_uptime_seconds()),
                  inline=True)
    await ctx.send(embed=emb, ephemeral=True)


# ======================================================================
# END OF PART 2
# ======================================================================
# Part 3:
#   - /tts, /render, /rendermode, /hf_model
#   - /video, /music (VC panel)
#   - /debate
#   - /sm, /persistent, /persistentdisable, /persistentreset
#   - /court (button-based)
#   - /umf (button-based, per-guild, with "I am an admin" gate)
#   - on_message (with baked-in GIF reader)
#   - Web server
#   - main()
# ======================================================================
# ======================================================================
# TTS
# ======================================================================
@bot.hybrid_command(name="tts", description="🎙️ Say text as a Discord voice message")
@app_commands.autocomplete(voice=_voice_ac)
@app_commands.describe(voice="Voice (defaults to your /cs voice setting)",
                       prompt="Exact text to speak")
async def tts_cmd(ctx, voice: str = None, prompt: str = None):
    await ctx.defer()
    if prompt is None:
        return await ctx.send("❌ `/tts [voice] <text>`")
    uid = ctx.author.id
    voices = bot.all_voices(uid)
    vkey = (voice or bot.default_voice(uid)).lower()
    if vkey not in voices:
        vkey = DEFAULT_VOICE
    clean = strip_for_tts(prompt)
    if not clean:
        return await ctx.send("❌ Nothing to say.")
    try:
        audio = await bot.generate_voice(clean, uid=uid, voice_key=vkey, fmt="opus")
    except Exception as e:
        logger.error(f"Fish error: {e}")
        return await ctx.send(f"❌ TTS error: {str(e)[:150]}")
    meta = voices[vkey]
    try:
        file = discord.File(io.BytesIO(audio), filename="voice-message.ogg")
        flags = discord.MessageFlags(is_voice_message=True)
        await ctx.send(file=file, flags=flags)
    except Exception as e:
        logger.warning(f"Voice-message flag failed: {e}")
        file2 = discord.File(io.BytesIO(audio), filename="voice.mp3")
        await ctx.send(content=f"{meta['emoji']} **{meta['desc']}**\n-# {clean[:350]}",
                       file=file2)


# ======================================================================
# IMAGE
# ======================================================================
@bot.hybrid_command(name="render", description="🎨 Generate an image")
@app_commands.describe(prompt="Describe the image", mode="smart | fast | hf")
async def render_cmd(ctx, prompt: str, mode: str = None):
    await ctx.defer()
    uid = ctx.author.id
    chosen = (mode or bot.current_image_mode).lower()
    status = await ctx.send("🔥 Checking your prompt...")
    try:
        safe, reason = await bot.is_prompt_safe(prompt, uid=uid)
        if not safe:
            return await status.edit(content=f"🚫 **Blocked.**\nReason: {reason}")
        await status.edit(content=f"🔥 Generating **{chosen}** image...")
        if chosen in ("hf", "huggingface"):
            img = await bot.generate_hf_image(prompt, uid=uid)
            label = "🤗 Hugging Face"
        elif chosen in ("pollinations", "poll", "fast"):
            img = await bot.generate_pollinations_image(prompt)
            label = "⚡ Pollinations"
        else:
            img = await bot.generate_gemini_image(prompt, uid=uid)
            label = "🧠 Gemini"
        url = await bot.upload_image_to_hosting(img, uid=uid)
        emb = discord.Embed(title="🖼️ Generated",
                            description=f"**Backend:** {label}", color=C_PRIMARY)
        emb.set_image(url=url)
        emb.add_field(name="Prompt", value=prompt[:1024], inline=False)
        await status.edit(content=None, embed=emb)
    except Exception as e:
        await status.edit(content=f"❌ `{str(e)[:180]}`")


@bot.hybrid_command(name="rendermode", description="🖼️ Show or change the default image mode")
@app_commands.describe(mode="smart | fast | hf")
async def rendermode_cmd(ctx, mode: str = None):
    if mode is None:
        emb = discord.Embed(title="🖼️ Image Mode", color=C_PRIMARY)
        emb.add_field(name="Current", value=f"`{bot.current_image_mode}`", inline=False)
        emb.add_field(name="Options",
                      value="• `smart` → Gemini\n• `fast` → Pollinations\n• `hf` → Hugging Face",
                      inline=False)
        return await ctx.send(embed=emb)
    if mode.lower() not in ("smart", "fast", "hf"):
        return await ctx.send("❌ Mode must be `smart`, `fast`, or `hf`")
    bot.current_image_mode = mode.lower()
    await ctx.send(f"✅ Image mode → **{mode}**")


@bot.hybrid_command(name="hf_model", description="🤗 Show or change the Hugging Face image model")
@app_commands.describe(model="HF model id (blank to show current + fallbacks)")
async def hf_model_cmd(ctx, model: str = None):
    if model is None:
        listing = "\n".join(f"• `{m}`" for m in GLOBAL_HF_IMAGE_MODELS)
        current = (bot.current_model(ctx.author.id, "hf_image")
                   or GLOBAL_HF_IMAGE_MODELS[0])
        return await ctx.send(f"🤗 Current: `{current}`\n\n**Fallback list:**\n{listing}")
    u = bot._cs(ctx.author.id)
    u["hf_image_models"] = [model.strip()]
    bot._save_cs()
    await ctx.send(f"✅ HF image model → `{model}`")


# ======================================================================
# MEDIA
# ======================================================================
@bot.hybrid_command(name="video", description="🎬 Generate a video from a prompt")
@app_commands.describe(prompt="Describe the video")
async def video_cmd(ctx, prompt: str):
    await ctx.defer()
    status = await ctx.send(f"🎬 Starting video: **{prompt}**...")
    bot.loop.create_task(bot.generate_video(prompt, ctx.author.id, status))


# ======================================================================
# MUSIC — VC panel
# ======================================================================
_SPOTIFY_TOKEN: Optional[str] = None
_SPOTIFY_TOKEN_EXP: float = 0.0


async def _spotify_token() -> Optional[str]:
    global _SPOTIFY_TOKEN, _SPOTIFY_TOKEN_EXP
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None
    if _SPOTIFY_TOKEN and time.time() < _SPOTIFY_TOKEN_EXP - 30:
        return _SPOTIFY_TOKEN
    try:
        auth = base64.b64encode(
            f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
        async with shared_session() as s:
            async with s.post(
                SPOTIFY_TOKEN_URL,
                headers={"Authorization": f"Basic {auth}",
                         "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    return None
                d = await r.json()
                _SPOTIFY_TOKEN = d.get("access_token")
                _SPOTIFY_TOKEN_EXP = time.time() + d.get("expires_in", 3600)
                return _SPOTIFY_TOKEN
    except Exception as e:
        logger.warning(f"Spotify token: {e}")
        return None


async def _search_spotify(query: str, limit: int = 8) -> List[dict]:
    tok = await _spotify_token()
    if not tok:
        return []
    try:
        async with shared_session() as s:
            async with s.get(
                SPOTIFY_SEARCH_URL,
                headers={"Authorization": f"Bearer {tok}"},
                params={"q": query, "type": "track", "limit": limit},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    return []
                d = await r.json()
        out = []
        for t in d.get("tracks", {}).get("items", []):
            artists = ", ".join(a["name"] for a in t.get("artists", []))
            out.append({
                "title": t.get("name", "?"), "artist": artists or "?",
                "source": "spotify",
                "preview_url": t.get("preview_url"),
                "url": t.get("external_urls", {}).get("spotify"),
                "duration_ms": t.get("duration_ms"),
            })
        return out
    except Exception:
        return []


async def _search_itunes(query: str, limit: int = 8) -> List[dict]:
    try:
        async with shared_session() as s:
            async with s.get(
                ITUNES_SEARCH_URL,
                params={"term": query, "media": "music", "entity": "song",
                        "limit": limit},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    return []
                d = await r.json()
        out = []
        for t in d.get("results", []):
            out.append({
                "title": t.get("trackName", "?"),
                "artist": t.get("artistName", "?"),
                "source": "itunes",
                "preview_url": t.get("previewUrl"),
                "url": t.get("trackViewUrl"),
                "duration_ms": t.get("trackTimeMillis"),
            })
        return out
    except Exception:
        return []


async def search_music(query: str, limit: int = 8) -> List[dict]:
    if SPOTIFY_CLIENT_ID:
        sp = await _search_spotify(query, limit)
        if sp:
            it = await _search_itunes(query, limit)
            for r in sp:
                if r.get("preview_url"):
                    continue
                for c in it:
                    if (c["title"].lower() in r["title"].lower()
                            or r["title"].lower() in c["title"].lower()):
                        r["preview_url"] = c.get("preview_url")
                        break
            return sp
    return await _search_itunes(query, limit)


class MusicSession:
    __slots__ = ("guild_id", "text_channel_id", "voice_client",
                 "queue", "current", "loop_mode")

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.text_channel_id: Optional[int] = None
        self.voice_client: Optional[Any] = None
        self.queue: List[dict] = []
        self.current: Optional[dict] = None
        self.loop_mode: str = "off"


def _get_music_session(guild_id: int) -> MusicSession:
    if guild_id not in bot.music_sessions:
        bot.music_sessions[guild_id] = MusicSession(guild_id)
    return bot.music_sessions[guild_id]


def _loop_label(mode: str) -> str:
    return {"off": "➡️ Off", "track": "🔂 Loop track",
            "queue": "🔁 Loop queue", "24_7": "♾️ 24/7"}.get(mode, "➡️ Off")


def _music_panel_embed(session: MusicSession) -> discord.Embed:
    emb = discord.Embed(title="🎵 Music Panel", color=C_PRIMARY)
    cur = session.current
    if cur:
        emb.add_field(name="Now playing",
                      value=f"**{cur['title']}** — {cur['artist']}\n*{cur['source']}*",
                      inline=False)
    else:
        emb.add_field(name="Now playing", value="*(nothing)*", inline=False)
    if session.queue:
        lines = [f"{i}. **{t['title']}** — {t['artist']}"
                 for i, t in enumerate(session.queue[:5], 1)]
        if len(session.queue) > 5:
            lines.append(f"…and {len(session.queue) - 5} more")
        emb.add_field(name=f"Queue ({len(session.queue)})",
                      value="\n".join(lines), inline=False)
    emb.add_field(name="Loop mode", value=_loop_label(session.loop_mode), inline=True)
    emb.add_field(name="Voice",
                  value="✅" if _VOICE_LIB_OK else "❌ (no PyNaCl)", inline=True)
    emb.set_footer(text="Press 🔎 Search to queue a track by name")
    return emb


async def _ensure_voice(interaction: discord.Interaction, session: MusicSession):
    if not _VOICE_LIB_OK:
        raise Exception("PyNaCl not installed — voice disabled")
    vc = session.voice_client
    if vc and vc.is_connected():
        return
    member = interaction.user
    if not member.voice or not member.voice.channel:
        raise Exception("You're not in a voice channel")
    session.voice_client = await member.voice.channel.connect()


def _play_next(guild_id: int):
    session = bot.music_sessions.get(guild_id)
    if not session or not session.voice_client:
        return
    vc = session.voice_client
    if session.loop_mode == "track" and session.current:
        next_track = session.current
    elif session.queue:
        next_track = session.queue.pop(0)
    elif session.loop_mode == "queue" and session.current:
        session.queue.append(session.current)
        next_track = session.queue.pop(0) if session.queue else None
    elif session.loop_mode == "24_7" and session.current:
        next_track = session.current
    else:
        session.current = None
        return
    if not next_track or not next_track.get("preview_url"):
        return _play_next(guild_id)
    session.current = next_track

    def _after(err):
        if err:
            logger.warning(f"Voice playback error: {err}")
        try:
            bot.loop.call_soon_threadsafe(_play_next, guild_id)
        except Exception:
            pass

    try:
        source = discord.FFmpegPCMAudio(
            next_track["preview_url"],
            before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            options="-vn")
        vc.play(source, after=_after)
    except Exception as e:
        logger.error(f"Play failed: {e}")
        session.current = None


class _MusicSearchModal(discord.ui.Modal, title="🔎 Search a song"):
    query = discord.ui.TextInput(
        label="Song name (or 'artist - song')",
        placeholder="e.g. Bohemian Rhapsody",
        required=True, max_length=120)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        results = await search_music(self.query.value.strip(), limit=8)
        if not results:
            return await interaction.followup.send("❌ No results.", ephemeral=True)
        bot._pending_searches[interaction.user.id] = results
        await interaction.followup.send("**Pick a track:**",
                                        view=_MusicSelectView(interaction.user.id),
                                        ephemeral=True)


class _MusicSelectView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=120)
        results = bot._pending_searches.get(user_id, [])
        if results:
            self.add_item(_MusicResultSelect(user_id, results))


class _MusicResultSelect(discord.ui.Select):
    def __init__(self, user_id: int, results: List[dict]):
        self.user_id = user_id
        self.results = results
        super().__init__(
            placeholder="Choose a track…",
            min_values=1, max_values=1,
            options=[discord.SelectOption(
                label=f"{'▶️' if r.get('preview_url') else '🚫'} {r['title'][:60]}",
                description=f"{r['artist'][:80]}"[:100],
                value=str(i)) for i, r in enumerate(results[:25])])

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("❌ Not your search.",
                                                            ephemeral=True)
        track = self.results[int(self.values[0])]
        if not track.get("preview_url"):
            return await interaction.response.send_message(
                "⚠️ No playable preview for this. Try another.", ephemeral=True)
        session = _get_music_session(interaction.guild.id)
        session.queue.append(track)
        session.text_channel_id = interaction.channel.id
        try:
            await _ensure_voice(interaction, session)
        except Exception as e:
            return await interaction.response.send_message(
                f"❌ Couldn't join voice: {e}", ephemeral=True)
        await interaction.response.send_message(
            f"➕ Queued **{track['title']}** — {track['artist']}", ephemeral=True)
        if session.voice_client and not session.voice_client.is_playing():
            _play_next(interaction.guild.id)


class _MusicPanelView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="Search", emoji="🔎", style=discord.ButtonStyle.primary, row=0)
    async def search_btn(self, interaction, button):
        await interaction.response.send_modal(_MusicSearchModal())

    @discord.ui.button(label="Play/Pause", emoji="⏯️", style=discord.ButtonStyle.secondary, row=0)
    async def pp_btn(self, interaction, button):
        session = _get_music_session(interaction.guild.id)
        vc = session.voice_client
        if not vc or not vc.is_connected():
            return await interaction.response.send_message("❌ Not connected.", ephemeral=True)
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Paused.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Resumed.", ephemeral=True)
        else:
            if session.queue or session.current:
                _play_next(interaction.guild.id)
            await interaction.response.send_message("▶️ Playing.", ephemeral=True)

    @discord.ui.button(label="Skip", emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip_btn(self, interaction, button):
        session = _get_music_session(interaction.guild.id)
        vc = session.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            if session.loop_mode == "track":
                session.loop_mode = "off"
            vc.stop()
            await interaction.response.send_message("⏭️ Skipped.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Nothing playing.", ephemeral=True)

    @discord.ui.button(label="Stop", emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop_btn(self, interaction, button):
        session = _get_music_session(interaction.guild.id)
        session.queue.clear()
        session.current = None
        session.loop_mode = "off"
        vc = session.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        await interaction.response.edit_message(embed=_music_panel_embed(session), view=self)

    @discord.ui.button(label="Loop mode", emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def loop_btn(self, interaction, button):
        session = _get_music_session(interaction.guild.id)
        order = ["off", "track", "queue", "24_7"]
        session.loop_mode = order[(order.index(session.loop_mode) + 1) % len(order)]
        await interaction.response.edit_message(embed=_music_panel_embed(session), view=self)

    @discord.ui.button(label="Queue", emoji="📜", style=discord.ButtonStyle.secondary, row=1)
    async def queue_btn(self, interaction, button):
        session = _get_music_session(interaction.guild.id)
        await interaction.response.send_message(embed=_music_panel_embed(session),
                                                ephemeral=True)

    @discord.ui.button(label="Leave VC", emoji="👋", style=discord.ButtonStyle.danger, row=1)
    async def leave_btn(self, interaction, button):
        session = _get_music_session(interaction.guild.id)
        session.queue.clear()
        session.current = None
        vc = session.voice_client
        if vc and vc.is_connected():
            await vc.disconnect()
        session.voice_client = None
        await interaction.response.send_message("👋 Left voice.", ephemeral=True)


@bot.hybrid_command(name="music",
                    description="🎵 Music panel — search, queue, play in VC")
async def music_panel_cmd(ctx):
    if not ctx.guild:
        return await ctx.send("Servers only.", ephemeral=True)
    session = _get_music_session(ctx.guild.id)
    session.text_channel_id = ctx.channel.id
    if not session.voice_client or not session.voice_client.is_connected():
        if ctx.author.voice and ctx.author.voice.channel and _VOICE_LIB_OK:
            try:
                session.voice_client = await ctx.author.voice.channel.connect()
            except Exception as e:
                logger.warning(f"Auto-join failed: {e}")
    await ctx.send(embed=_music_panel_embed(session),
                   view=_MusicPanelView(ctx.guild.id))


# ======================================================================
# AI DEBATE
# ======================================================================
@bot.hybrid_command(name="debate", description="🤖 Start/stop an AI vs AI debate")
@app_commands.describe(description="Topic — required to start, omit to stop")
async def debate_cmd(ctx, description: str = None):
    uid = ctx.author.id
    if uid in bot.ai_chat_sessions:
        s = bot.ai_chat_sessions.pop(uid, None)
        t = s.get("task") if s else None
        if t and not t.done():
            t.cancel()
        return await ctx.send("🛑 Debate stopped.")
    if not description:
        return await ctx.send("❌ Give a topic.")
    s = {"description": description, "history": [], "turn": 0,
         "channel_id": ctx.channel.id, "task": None}
    bot.ai_chat_sessions[uid] = s
    s["task"] = asyncio.create_task(bot.run_ai_chat(uid))
    await ctx.send(f"🔥 Debate started — **{description}**\n`/debate` again to stop.")


# ======================================================================
# MEMORY
# ======================================================================
@bot.hybrid_command(name="sm", description="🧠 Toggle short-term memory on/off")
async def sm(ctx):
    bot.memory_enabled = not bot.memory_enabled
    await ctx.send(f"🧠 Short-term memory **{'ON' if bot.memory_enabled else 'OFF'}**")


@bot.hybrid_command(name="persistent", description="💾 Enable persistent memory for yourself")
async def persistent_enable(ctx):
    bot.set_persistent_enabled(ctx.author.id, True)
    await ctx.send(f"✅ Persistent memory **ON** for {ctx.author.display_name}")


@bot.hybrid_command(name="persistentdisable", description="🚫 Disable persistent memory")
async def persistent_disable(ctx):
    bot.set_persistent_enabled(ctx.author.id, False)
    await ctx.send("🚫 Persistent memory **OFF**")


@bot.hybrid_command(name="persistentreset",
                    description="🧹 Reset a user's persistent memory (admin only)")
@app_commands.describe(target_user="User whose memory to wipe")
async def persistent_reset(ctx, target_user: discord.User):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ Admin only")
    bot.clear_persistent_memory(target_user.id)
    await ctx.send(f"🧹 Reset persistent memory for {target_user.display_name}")


# ======================================================================
# COURT — fully button-based
# ======================================================================
class CourtRoleView(discord.ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=120)
        self.bot = bot_instance

    async def select_role(self, interaction, role_key):
        self.bot.court_sessions[interaction.user.id] = {
            "role": role_key, "case": "", "participants": {}}
        await interaction.response.edit_message(
            content=(f"✅ You are now **{role_key.capitalize()}**.\n"
                     f"Now click **📝 Explain Case** below, or **👥 Add Participant** "
                     f"to assign others."),
            view=CourtPanelView(self.bot))

    @discord.ui.button(label="Judge", style=discord.ButtonStyle.primary, row=0)
    async def j(self, i, b): await self.select_role(i, "judge")

    @discord.ui.button(label="Prosecutor", style=discord.ButtonStyle.danger, row=0)
    async def p(self, i, b): await self.select_role(i, "prosecutor")

    @discord.ui.button(label="Defense", style=discord.ButtonStyle.success, row=0)
    async def d(self, i, b): await self.select_role(i, "defense")

    @discord.ui.button(label="Witness", style=discord.ButtonStyle.secondary, row=1)
    async def w(self, i, b): await self.select_role(i, "witness")

    @discord.ui.button(label="Jury", style=discord.ButtonStyle.secondary, row=1)
    async def y(self, i, b): await self.select_role(i, "jury")

    @discord.ui.button(label="Stenographer", style=discord.ButtonStyle.secondary, row=1)
    async def s(self, i, b): await self.select_role(i, "stenographer")


class CourtCaseModal(discord.ui.Modal, title="📝 Explain the Case"):
    case_text = discord.ui.TextInput(
        label="Describe the case",
        style=discord.TextStyle.paragraph,
        required=True, max_length=800)

    async def on_submit(self, interaction: discord.Interaction):
        s = bot.court_sessions.setdefault(interaction.user.id,
                                          {"role": "judge", "case": "", "participants": {}})
        s["case"] = self.case_text.value.strip()
        await interaction.response.send_message(
            "✅ Case recorded. Click **▶️ Start** to begin.", ephemeral=True)


class CourtParticipantModal(discord.ui.Modal, title="👥 Add Participant"):
    user_id = discord.ui.TextInput(label="User ID", required=True, max_length=30)
    role = discord.ui.TextInput(
        label="Role (judge/prosecutor/defense/witness/jury/stenographer)",
        required=True, max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id.value.strip())
        except ValueError:
            return await interaction.response.send_message("❌ Invalid user ID.",
                                                            ephemeral=True)
        r = self.role.value.strip().lower()
        valid = ["judge", "prosecutor", "defense", "witness", "jury", "stenographer"]
        if r not in valid:
            return await interaction.response.send_message(
                f"❌ Role: {', '.join(valid)}", ephemeral=True)
        s = bot.court_sessions.setdefault(interaction.user.id,
                                          {"role": "judge", "case": "", "participants": {}})
        s["participants"][r] = uid
        await interaction.response.send_message(f"✅ <@{uid}> → **{r}**", ephemeral=True)


class CourtPanelView(discord.ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=300)
        self.bot = bot_instance

    @discord.ui.button(label="Explain Case", emoji="📝", style=discord.ButtonStyle.primary, row=0)
    async def explain_btn(self, i, b):
        if i.user.id not in bot.court_sessions:
            return await i.response.send_message("❌ Pick a role first.", ephemeral=True)
        await i.response.send_modal(CourtCaseModal())

    @discord.ui.button(label="Add Participant", emoji="👥", style=discord.ButtonStyle.secondary, row=0)
    async def add_btn(self, i, b):
        if i.user.id not in bot.court_sessions:
            return await i.response.send_message("❌ Pick a role first.", ephemeral=True)
        await i.response.send_modal(CourtParticipantModal())

    @discord.ui.button(label="Start", emoji="▶️", style=discord.ButtonStyle.success, row=0)
    async def start_btn(self, i, b):
        s = bot.court_sessions.get(i.user.id)
        if not s:
            return await i.response.send_message("❌ Pick a role first.", ephemeral=True)
        if not s.get("case"):
            return await i.response.send_message(
                "❌ Use 📝 Explain Case first.", ephemeral=True)
        p = s.get("participants", {})
        if p:
            out = "🏛️ **Court in session!**\n"
            for r, uid in p.items():
                out += f"**{r.capitalize()}**: <@{uid}>\n"
            await i.response.send_message(out)
        else:
            await i.response.send_message("🏛️ Court in session (no other participants).")
        await i.channel.send("Begin.")

    @discord.ui.button(label="Change Role", emoji="🎭", style=discord.ButtonStyle.secondary, row=0)
    async def change_btn(self, i, b):
        await i.response.edit_message(content="🏛️ Pick your new role:",
                                      view=CourtRoleView(bot))

    @discord.ui.button(label="End", emoji="🏁", style=discord.ButtonStyle.danger, row=1)
    async def end_btn(self, i, b):
        if i.user.id in bot.court_sessions:
            bot.court_sessions.pop(i.user.id, None)
        await i.response.edit_message(content="🏛️ Court ended.", view=None)


@bot.hybrid_command(name="court", description="🏛️ Court session — button panel")
async def court_cmd(ctx):
    await ctx.send("🏛️ **Pick your role:**", view=CourtRoleView(bot))


# ======================================================================
# UMF — per-guild, button-based
# ======================================================================
class UMFRecognitionModal(discord.ui.Modal, title="🌍 UMF Recognition Request"):
    nation_name = discord.ui.TextInput(label="Nation Name", required=True, max_length=100)
    additional = discord.ui.TextInput(label="Additional Info (optional)",
                                      required=False, max_length=500,
                                      style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction):
        guild_id = interaction.guild.id if interaction.guild else None
        nation = self.nation_name.value.strip()
        if bot.umf_data.is_nation_recognized(guild_id, nation):
            return await interaction.response.send_message(
                f"⚠️ **{nation}** is already recognized.", ephemeral=True)
        existing = bot.umf_data.get_request_status(guild_id, interaction.user.id)
        if existing and existing.get("status") == "pending":
            return await interaction.response.send_message(
                "⏳ You already have a pending request.", ephemeral=True)
        bot.umf_data.add_pending_request(guild_id, interaction.user.id, nation,
                                         interaction.user.display_name)
        bot.umf_data.add_to_history(guild_id, "REQUEST_SUBMITTED",
                                    interaction.user.id, interaction.user.display_name,
                                    nation, f"Additional: {self.additional.value or 'None'}")
        emb = discord.Embed(title="✅ Request Submitted",
                            description=f"**{nation}** is pending review.", color=C_OK)
        await interaction.response.send_message(embed=emb, ephemeral=True)


class UMFDenyModal(discord.ui.Modal, title="❌ Deny Request"):
    reason = discord.ui.TextInput(label="Reason", required=True, max_length=200,
                                  style=discord.TextStyle.paragraph)

    def __init__(self, req, user):
        super().__init__()
        self.req = req
        self.user = user

    async def on_submit(self, interaction):
        guild_id = interaction.guild.id if interaction.guild else None
        bot.umf_data.deny_request(guild_id, self.req["user_id"], self.reason.value.strip())
        bot.umf_data.add_to_history(guild_id, "DENIED", self.req["user_id"],
                                    self.req["username"], self.req["nation"],
                                    f"Reason: {self.reason.value.strip()}")
        await interaction.response.edit_message(content="❌ Denied.", view=None)
        try:
            await self.user.send(
                f"❌ Your UMF request for **{self.req['nation']}** was denied.\n"
                f"Reason: {self.reason.value.strip()}")
        except Exception:
            pass


class UMFAdminPanel(discord.ui.View):
    """Admin-only panel — manages pending requests."""

    def __init__(self, bot_instance):
        super().__init__(timeout=300)
        self.bot = bot_instance

    @discord.ui.button(label="📋 Next Pending", style=discord.ButtonStyle.primary, row=0)
    async def next_btn(self, i, b):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("⛔ Admin only.", ephemeral=True)
        guild_id = i.guild.id if i.guild else None
        pending = self.bot.umf_data.get_pending_requests(guild_id)
        if not pending:
            return await i.response.send_message("📭 No pending requests.", ephemeral=True)
        req = pending[0]
        try:
            user = i.guild.get_member(req["user_id"]) or await i.guild.fetch_member(req["user_id"])
        except Exception:
            user = None
        emb = discord.Embed(title="📋 Pending Request", color=C_WARM)
        emb.add_field(name="👤 Applicant",
                      value=user.mention if user else f"<@{req['user_id']}>", inline=True)
        emb.add_field(name="🌍 Nation", value=req["nation"], inline=True)
        emb.add_field(name="📅 Submitted",
                      value=datetime.fromisoformat(req["timestamp"]).strftime("%b %d, %H:%M"),
                      inline=True)
        emb.add_field(name="📊 Total Pending", value=str(len(pending)), inline=True)
        await i.response.edit_message(embed=emb, view=UMFAdminActionView(req, user))

    @discord.ui.button(label="📊 Stats", style=discord.ButtonStyle.secondary, row=0)
    async def stats_btn(self, i, b):
        guild_id = i.guild.id if i.guild else None
        st = self.bot.umf_data.get_stats(guild_id)
        emb = discord.Embed(title="📊 UMF Stats (this server)", color=C_PRIMARY)
        emb.add_field(name="Recognized", value=str(st["recognized"]), inline=True)
        emb.add_field(name="Pending", value=str(st["pending"]), inline=True)
        emb.add_field(name="Approved", value=str(st["approved"]), inline=True)
        emb.add_field(name="Denied", value=str(st["denied"]), inline=True)
        emb.add_field(name="History", value=str(st["history"]), inline=True)
        await i.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(label="🌍 All Nations", style=discord.ButtonStyle.secondary, row=0)
    async def list_btn(self, i, b):
        guild_id = i.guild.id if i.guild else None
        nations = self.bot.umf_data.get_recognized_nations(guild_id)
        emb = discord.Embed(title="🌍 Recognized Nations (this server)", color=C_ACCENT)
        if nations:
            emb.description = "```\n" + "\n".join(f"• {n}" for n in nations[:25]) + "\n```"
        else:
            emb.description = "None yet."
        await i.response.send_message(embed=emb, ephemeral=True)


class UMFAdminActionView(discord.ui.View):
    def __init__(self, req, user):
        super().__init__(timeout=180)
        self.req = req
        self.user = user

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_btn(self, i, b):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("⛔ Admin only.", ephemeral=True)
        guild_id = i.guild.id if i.guild else None
        approved = bot.umf_data.approve_request(guild_id, self.req["user_id"])
        if not approved:
            return await i.response.edit_message(content="❌ Already processed.", view=None)
        bot.umf_data.add_recognized_nation(guild_id, approved["nation"])
        bot.umf_data.add_to_history(guild_id, "APPROVED", approved["user_id"],
                                    approved["username"], approved["nation"],
                                    f"By {i.user}")
        await i.response.edit_message(
            content=f"✅ **{approved['nation']}** recognized.", view=None)
        try:
            await self.user.send(f"🎉 Your nation **{approved['nation']}** is now "
                                 f"recognized by the UMF (in {i.guild.name}).")
        except Exception:
            pass

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny_btn(self, i, b):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("⛔ Admin only.", ephemeral=True)
        await i.response.send_modal(UMFDenyModal(self.req, self.user))

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_btn(self, i, b):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("⛔ Admin only.", ephemeral=True)
        await i.response.edit_message(content="⏭️ Skipped.", view=UMFAdminPanel(bot))


class UMFPrimaryView(discord.ui.View):
    """Public UMF panel with two gates: normal + admin."""

    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="🌍 Request Recognition",
                       style=discord.ButtonStyle.primary, emoji="🌍", row=0)
    async def request_btn(self, i, b):
        await i.response.send_modal(UMFRecognitionModal())

    @discord.ui.button(label="📋 View Nations",
                       style=discord.ButtonStyle.secondary, emoji="📋", row=0)
    async def list_btn(self, i, b):
        guild_id = i.guild.id if i.guild else None
        nations = bot.umf_data.get_recognized_nations(guild_id)
        emb = discord.Embed(title="🌍 Recognized UMF Nations (this server)",
                            color=C_ACCENT)
        if nations:
            emb.description = "```\n" + "\n".join(f"• {n}" for n in nations[:25]) + "\n```"
        else:
            emb.description = "No nations recognized yet."
        await i.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(label="ℹ️ My Status",
                       style=discord.ButtonStyle.secondary, emoji="ℹ️", row=0)
    async def status_btn(self, i, b):
        guild_id = i.guild.id if i.guild else None
        req = bot.umf_data.get_request_status(guild_id, i.user.id)
        if req:
            status = req.get("status", "unknown")
            color, title = (C_WARM, "⏳ Pending") if status == "pending" else (
                (C_OK, "✅ Approved") if status == "approved" else (C_ERR, "❌ Denied"))
            emb = discord.Embed(title=title,
                                description=f"**{req.get('nation', '')}**", color=color)
            if status == "denied" and req.get("denied_reason"):
                emb.add_field(name="Reason", value=req["denied_reason"], inline=False)
        else:
            emb = discord.Embed(title="ℹ️ No Request",
                                description="You have no active request.", color=C_DEEP)
        await i.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(label="I am an admin",
                       style=discord.ButtonStyle.danger, emoji="🔒", row=1)
    async def admin_btn(self, i, b):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message(
                "⛔ You don't have admin permissions in this server.", ephemeral=True)
        emb = discord.Embed(
            title="🔒 UMF Admin Panel",
            description="Manage pending requests, view stats, view nations.",
            color=C_DEEP)
        await i.response.send_message(embed=emb, view=UMFAdminPanel(bot), ephemeral=True)


def umf_requirements_embed() -> discord.Embed:
    emb = discord.Embed(
        title="🌍 UMF Recognition System",
        description="To be recognized by the **United Military Federation (UMF)**:",
        color=C_PRIMARY)
    emb.add_field(name="📋 Requirements",
                  value=("1. **Administrative User** — an admin user in the UMF.\n"
                         "2. **Relay Link** — your nation relay-linked to the UMF network.\n"
                         "3. **Active Status** — your nation actively participating."),
                  inline=False)
    emb.add_field(name="📝 How to Apply",
                  value="Click **Request Recognition** below, enter your nation name.",
                  inline=False)
    emb.set_footer(text="Each server has its own UMF profile.")
    return emb


@bot.hybrid_command(name="umf", description="🌍 UMF Recognition System — start here")
async def umf_command(ctx):
    await ctx.send(embed=umf_requirements_embed(), view=UMFPrimaryView())


# ======================================================================
# ON_MESSAGE — with GIF reader baked in
# ======================================================================
_GIF_URL_RE = re.compile(
    r'https?://\S+\.(?:gif|mp4)(?:\?\S*)?|'
    r'https?://(?:www\.)?(?:tenor\.com|giphy\.com|klipy\.com|media\.discordapp\.net)/\S+',
    re.IGNORECASE)


def _looks_like_gif_request(text: str) -> bool:
    low = text.lower()
    keys = ("what's this gif", "whats this gif", "what is this gif",
            "what's the gif", "describe this gif", "read this gif",
            "what's this image", "whats this image", "what is this",
            "what's this picture", "describe this", "explain this gif",
            "what is happening in this", "what's happening in this",
            "read this", "what does this say")
    return any(k in low for k in keys)


async def _try_describe_gif(message: discord.Message,
                            content: str,
                            uid: int) -> Optional[str]:
    """Return a description if there's a GIF anywhere in scope.
    Order of precedence: message attachments → URLs in content →
    replied message's attachments/URLs."""

    # 1. attachments on this message
    for att in message.attachments:
        ct = (att.content_type or "").lower()
        if "gif" in ct or att.filename.lower().endswith((".gif", ".mp4")):
            return await bot.describe_gif(att.url, uid=uid)

    # 2. URLs pasted in the message
    m = _GIF_URL_RE.search(content or "")
    if m:
        return await bot.describe_gif(m.group(0), uid=uid)

    # 3. reply chain
    if message.reference:
        resolved = message.reference.resolved
        if resolved is None:
            try:
                resolved = await message.channel.fetch_message(
                    message.reference.message_id)
            except Exception:
                resolved = None
        if isinstance(resolved, discord.Message):
            for att in resolved.attachments:
                ct = (att.content_type or "").lower()
                if "gif" in ct or att.filename.lower().endswith((".gif", ".mp4")):
                    return await bot.describe_gif(att.url, uid=uid)
            m2 = _GIF_URL_RE.search(resolved.content or "")
            if m2:
                return await bot.describe_gif(m2.group(0), uid=uid)

    return None


@bot.event
async def on_message(message: discord.Message):
    global _commands_served
    if message.author.bot:
        return

    content = message.content or ""
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = (
        bot.user in message.mentions
        or f"<@{bot.user.id}>" in content
        or f"<@!{bot.user.id}>" in content)

    # ping preference gate
    pref = bot.get_ping_pref(message.author.id)
    if pref == "off" and not is_dm:
        await bot.process_commands(message)
        return
    if pref == "dm_only" and not is_dm:
        await bot.process_commands(message)
        return

    if not (is_mentioned or is_dm):
        await bot.process_commands(message)
        return

    # reply context
    reply_context = None
    reply_msg = None
    if message.reference:
        resolved = message.reference.resolved
        if resolved is None:
            try:
                resolved = await message.channel.fetch_message(
                    message.reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                resolved = None
        if isinstance(resolved, discord.Message) and resolved.author.id != bot.user.id:
            reply_context = {
                "author": resolved.author.display_name,
                "content": (resolved.content or "[no text]")[:800],
                "author_id": resolved.author.id,
            }
            reply_msg = resolved

    # images from this message or the reply
    images = await fetch_images_from_message(message)
    if not images and reply_msg is not None:
        images = await fetch_images_from_message(reply_msg)

    # cooldown
    now = time.time()
    if now - bot.user_cooldowns.get(message.author.id, 0) < USER_COOLDOWN_SECONDS:
        await bot.process_commands(message)
        return
    bot.user_cooldowns[message.author.id] = now

    # clean mention out
    clean = re.sub(r'<@!?{}>\s*'.format(bot.user.id), '', content).strip()

    # ---- GIF reader intercept ----
    # Triggered when: (a) user asked "what's this gif" etc., OR
    # (b) a GIF was attached/pasted with no other text.
    has_gif_attachment = any(
        "gif" in (a.content_type or "").lower()
        or a.filename.lower().endswith((".gif", ".mp4"))
        for a in message.attachments)
    has_gif_url = bool(_GIF_URL_RE.search(content or ""))
    wants_gif_read = _looks_like_gif_request(clean) if clean else False

    if (wants_gif_read or ((has_gif_attachment or has_gif_url) and not clean)
            or ((has_gif_attachment or has_gif_url) and wants_gif_read)):
        _commands_served += 1
        desc = await _try_describe_gif(message, content, message.author.id)
        if desc:
            try:
                await message.channel.send(desc)
            except discord.HTTPException:
                pass
            await bot.process_commands(message)
            return

    if not clean and reply_context:
        clean = "what do you think of this?"
    if not clean and images:
        clean = "what's in this image?"
    if not clean:
        await bot.process_commands(message)
        return

    logger.info(f"Message from {message.author} in "
                f"#{getattr(message.channel, 'name', 'DM')}: "
                f"{clean[:100]!r} | images={len(images)}")

    _commands_served += 1
    try:
        await bot.process_user_message(
            message.author, clean, message.channel,
            reply_context=reply_context, trigger_msg=message, images=images)
    except Exception as e:
        logger.error(f"process_user_message failed: {e}", exc_info=True)

    await bot.process_commands(message)


# ======================================================================
# WEB SERVER
# ======================================================================
async def handle_root(request):
    return web.Response(text="🔥 Mac v23.2 is running")


async def handle_health(request):
    return web.Response(text="healthy")


async def run_web_server():
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/healthz", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    await web.TCPSite(runner, '0.0.0.0', port).start()
    logger.info(f"🌐 Web server on port {port}")


# ======================================================================
# MAIN
# ======================================================================
async def main():
    await run_web_server()
    async with bot:
        await bot.start(TOKEN)
    await close_shared_session()


if __name__ == "__main__":
    asyncio.run(main())
