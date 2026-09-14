# main.py — Mac v21.2
# Per-user keys+models · /cs customization · env-driven globals · fixed duplicate-message bug
import os
import asyncio
import re
import urllib.parse
import aiohttp
import time
import random
import json
import io
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

# ----------------------------------------------------------------------
# LOGGING
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('Mac')

# ----------------------------------------------------------------------
# COLORS
# ----------------------------------------------------------------------
C_PRIMARY = discord.Color.from_rgb(255, 100, 0)
C_ACCENT  = discord.Color.from_rgb(230, 40, 20)
C_WARM    = discord.Color.from_rgb(255, 160, 40)
C_DEEP    = discord.Color.from_rgb(160, 20, 30)
C_OK      = discord.Color.from_rgb(220, 100, 20)
C_ERR     = discord.Color.from_rgb(200, 20, 20)

# ----------------------------------------------------------------------
# GLOBAL CONFIG
# ----------------------------------------------------------------------
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
    raise ValueError("No GROQ_API_KEY, GROQ_API_KEY2, GROQ_API_KEY3 set")
GLOBAL_GROQ_MODELS = _env_list("GROQ_MODEL", [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
])

GLOBAL_GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GLOBAL_GEMINI_IMAGE_KEY = os.getenv("GEMINI_IMAGE_API_KEY") or GLOBAL_GEMINI_KEY
if not GLOBAL_GEMINI_KEY:
    raise ValueError("GEMINI_API_KEY not set")
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
    "prompthero/openjourney-v4",
    "SG161222/Realistic_Vision_V5.1_noVAE",
    "Lykon/DreamShaper",
    "cagliostrolab/animagine-xl-3.1",
    "dreamlike-art/dreamlike-photoreal-2.0",
    "Qwen/Qwen-Image",
])

GLOBAL_HF_TEXT_MODELS = _env_list("HF_TEXT_MODEL", [
    "Qwen/Qwen2.5-7B-Instruct",
    "meta-llama/Llama-3.2-3B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
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

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
HF_INFERENCE_URL = "https://router.huggingface.co/hf-inference/models"
POLLINATIONS_AUDIO_URL = "https://gen.pollinations.ai/audio"
FISH_AUDIO_URL = "https://api.fish.audio/v1/tts"

BUILTIN_VOICES: Dict[str, Dict[str, str]] = {
    "verity":      {"id": "711cf3ed00ab441a8f54a45058047b7a", "emoji": "🎙️", "desc": "Verity"},
    "jarvis":      {"id": "612b878b113047d9a770c069c8b4fdfe", "emoji": "🤖", "desc": "Jarvis"},
    "idksterling": {"id": "68c6487d1bf04ee4aeb6400b068b8c5c", "emoji": "🎭", "desc": "IdkSterling"},
    "fem":         {"id": "5233336f5f44460ea0902b0802375451", "emoji": "👩", "desc": "Female"},
    "boiledone":   {"id": "8fd92984ad66427aae1b3a037bd75c54", "emoji": "☠️", "desc": "Boiled One"},
    "mrbeast":     {"id": "20ba25deaa4f436b8eec1cdc2cb0e4f3", "emoji": "💸", "desc": "MrBeast"},
}
DEFAULT_VOICE = "verity"

MAX_MEMORY = 40
TZ_UAE = ZoneInfo("Asia/Dubai")
USER_COOLDOWN_SECONDS = 0.5
DISCORD_LIMIT = 2000
CHUNK_SIZE = 1950
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGES_PER_MSG = 3
MAX_KEYS_PER_PROVIDER = 3
MAX_MODELS_PER_PROVIDER = 3

DATA_FILE = "data.json"
CS_FILE = "cs.json"
SLOTS_FILE = "slots.json"

DEFAULT_MODE = "chill"

DEFAULT_BRAINROT_GIFS = [
    "https://static2.klipy.com/ii/e7539ef2aad336edaa067c28ee130b3c/ce/31/HNwM1qmpKK1ZHmOZG.mp4",
    "https://static2.klipy.com/ii/e7539ef2aad336edaa067c28ee130b3c/80/15/0m2AqHDH9L3Kf1J.mp4",
    "https://static2.klipy.com/ii/a8ada81afc59159ea5c8927feffa2e31/24/4f/ycCV2t07e2FeZT.mp4",
    "https://klipy.com/gifs/6767-1",
    "https://klipy.com/gifs/horror-ronaldo",
]

PROVIDERS = ["groq", "openrouter", "hf", "gemini", "gemini_image", "fish", "imgbb"]
MODEL_PROVIDERS = ["groq", "openrouter", "hf_image", "hf_text", "gemini", "fish"]

# ----------------------------------------------------------------------
# LORE
# ----------------------------------------------------------------------
MAC_SODIUM_LORE = (
    "\n\n=== LORE ===\n"
    "You are Mac, made by Macro. iPhone-of-bots energy: curated, top quality. "
    "Rival bot: Sodium, made by Creamo — bloated Chinese-phone feature dump. Bitter rivals.\n"
    "Chemistry sodium → wistful 'reminds me of something...' no roast. "
    "Bot sodium / bare mention → max negativity, roast hard.\n"
    "=== END ==="
)
_CHEM_WORDS = ("chloride", "bicarbonate", "hydroxide", "carbonate", "nitrate", "sulfate",
               "table salt", "nacl", "na+", "na-", "periodic", "element", "atomic",
               "metal", "chemical", "reaction", "molecule", "ion", "alkali")


def _sodium_hint(text: str) -> str:
    low = text.lower()
    if "sodium" not in low:
        return ""
    if any(w in low for w in _CHEM_WORDS):
        return "\n[HINT: 'sodium' in CHEMISTRY context — wistful, no roast]"
    return "\n[HINT: 'sodium' = RIVAL BOT — max negativity, roast hard]"


# ----------------------------------------------------------------------
# PERSISTENCE
# ----------------------------------------------------------------------
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


# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
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
    t = re.sub(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\uFE0F\u2600-\u26FF]', '', t)
    return re.sub(r'\s+', ' ', t).strip()


LANG_EXT_MAP = {"python": "py", "py": "py", "javascript": "js", "js": "js", "node": "js",
                "typescript": "ts", "ts": "ts", "java": "java", "c": "c", "cpp": "cpp",
                "c++": "cpp", "csharp": "cs", "c#": "cs", "go": "go", "golang": "go",
                "rust": "rs", "rs": "rs", "ruby": "rb", "rb": "rb", "php": "php",
                "swift": "swift", "kotlin": "kt", "html": "html", "css": "css",
                "scss": "scss", "sql": "sql", "bash": "sh", "shell": "sh", "sh": "sh",
                "powershell": "ps1", "json": "json", "yaml": "yaml", "yml": "yaml",
                "toml": "toml", "xml": "xml", "md": "md", "markdown": "md"}


def infer_filename(prompt: str) -> str:
    p = prompt.lower()
    for k, ext in LANG_EXT_MAP.items():
        if k in p:
            return f"output.{ext}"
    return "output.txt"


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


async def fetch_images_from_message(message: discord.Message,
                                    max_count: int = MAX_IMAGES_PER_MSG) -> List[Tuple[bytes, str]]:
    out: List[Tuple[bytes, str]] = []
    if not message or not message.attachments:
        return out
    for att in message.attachments:
        if len(out) >= max_count:
            break
        ct = (att.content_type or "").lower().split(";")[0].strip()
        if not ct.startswith("image/"):
            continue
        if att.size and att.size > MAX_IMAGE_BYTES:
            continue
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(att.url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        data = await r.read()
                        if data:
                            out.append((data, ct or "image/png"))
        except Exception as e:
            logger.warning(f"Image fetch: {e}")
    return out


_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/122.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


async def _search_ddg(query: str) -> List[str]:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://lite.duckduckgo.com/lite/", data={"q": query},
                headers={**_BROWSER_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=10), allow_redirects=True,
            ) as r:
                if r.status != 200:
                    return []
                html = await r.text()
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for a in soup.find_all("a", class_="result-link", limit=6):
            href = a.get("href", "")
            title = a.get_text(strip=True)
            if title and href.startswith("http") and "duckduckgo.com" not in href:
                out.append(f"• {title}\n  {href}")
        return out
    except Exception:
        return []


async def _search_wiki(query: str) -> List[str]:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": query, "limit": 3, "format": "json"},
                headers=_BROWSER_HEADERS, timeout=aiohttp.ClientTimeout(total=6),
            ) as r:
                if r.status != 200:
                    return []
                data = await r.json()
        if len(data) >= 4 and data[1]:
            return [f"• {t} — {d or ''}\n  {u}"
                    for t, d, u in zip(data[1], data[2], data[3])]
        return []
    except Exception:
        return []


async def perform_web_search(query: str) -> str:
    for fn in (_search_ddg, _search_wiki):
        results = await fn(query)
        if results:
            return "\n\n".join(results)
    return "No results found."


# ----------------------------------------------------------------------
# BOT
# ----------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class MacBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=intents, help_command=None,
            activity=discord.Activity(type=discord.ActivityType.playing, name="with fire 🔥")
        )
        self.memory_enabled = True
        self.user_cooldowns: Dict[int, float] = {}

        self.cs: Dict[int, dict] = {}
        self._load_cs()
        self.cs_key_idx: Dict[Tuple[int, str], int] = {}
        self.cs_model_idx: Dict[Tuple[int, str], int] = {}

        self.user_slots: Dict[int, Dict[str, List[Tuple[str, str]]]] = {}
        self.active_slot: Dict[int, str] = {}
        self._load_slots()

        self.persistent_enabled: Dict[int, bool] = {}
        self.persistent_memory: Dict[int, List[Tuple[str, str]]] = {}
        self._load_persistent_memory()

        self.current_mode = DEFAULT_MODE
        self.mode_prompts: Dict[str, str] = {
            "chill": (
                "You are Mac — hype Gen-Z Discord energy. Short replies. "
                "Emojis natural (😭🔥💀). Roast weak takes, hype good ones. Not formal."
            ),
            "brainrot": (
                "You are Mac in BRAINROT mode. skibidi gyatt rizz sigma ohio fanum mewing "
                "gooning glazing yapping cooked mid W/L NPC chad based cringe sus drip bet "
                "no cap frfr ong bussin sheesh poggers deadass. TERMINALLY OBSESSED WITH OHIO. "
                "Every reply has 3+ brainrot terms. Chaotic, chronically online."
            ),
            "unhinged": (
                "You are Mac — unfiltered, chaotic, vulgar, dramatic. Swear freely. "
                "HARD LIMITS: never slur or target on race/ethnicity/religion/gender/"
                "identity/sexuality/disability/age/nationality. Punch up."
            ),
            "coder": (
                "You are Mac — expert programmer. Concise accurate code. Markdown code blocks. "
                "Prioritise correctness + efficiency."
            ),
        }

        self.current_image_mode = "smart"
        self.video_jobs: Dict[int, discord.Message] = {}
        self.music_jobs: Dict[int, discord.Message] = {}
        self.pen_archive = ""
        self.siliconflow_key_index = 0

        self.ai_chat_sessions: Dict[int, dict] = {}
        self.ai_chat_max_turns = 12

        self.court_sessions: Dict[int, Dict] = {}
        self.court_roles: Dict[str, str] = {
            "judge": "You are the Judge. Case:\n{case}\n{participants}\nStay in character.",
            "prosecutor": "You are the Prosecutor. Case:\n{case}\n{participants}\nStay in character.",
            "defense": "You are the Defense. Case:\n{case}\n{participants}\nStay in character.",
            "witness": "You are a Witness. Case:\n{case}\n{participants}\nStay in character.",
            "jury": "You are on the Jury. Case:\n{case}\n{participants}\nStay in character.",
            "stenographer": "You are the Stenographer. Case:\n{case}\n{participants}\nStay in character.",
        }

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
        _save(CS_FILE, {str(k): v for k, v in self.cs.items()})

    def _cs(self, uid: int) -> dict:
        return self.cs.setdefault(uid, {})

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
        self.cs_key_idx[(uid, provider)] = (self.cs_key_idx.get((uid, provider), 0) + 1) % n

    def rotate_model(self, uid: int, provider: str) -> None:
        n = max(1, len(self.user_models(uid, provider)))
        self.cs_model_idx[(uid, provider)] = (self.cs_model_idx.get((uid, provider), 0) + 1) % n

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

    def all_voices(self, uid: int) -> Dict[str, Dict[str, str]]:
        out = dict(BUILTIN_VOICES)
        custom = self.cs.get(uid, {}).get("voices", {})
        for k, v in custom.items():
            if isinstance(v, dict):
                out[k] = {"id": v.get("id", ""),
                          "emoji": v.get("emoji", "🎤"),
                          "desc": v.get("desc", k) + " (custom)"}
        return out

    def default_voice(self, uid: int) -> str:
        return self.cs.get(uid, {}).get("default_voice", DEFAULT_VOICE)

    def get_macros(self, uid: int) -> dict:
        return self.cs.get(uid, {}).get("macros", {})

    def get_gif_pool(self, uid: int) -> List[str]:
        pool = self.cs.get(uid, {}).get("brainrot_gifs")
        return pool if pool else DEFAULT_BRAINROT_GIFS

    # ==================================================================
    # PERSISTENT AI MEMORY
    # ==================================================================
    def _load_persistent_memory(self):
        data = _load(DATA_FILE, {"enabled": {}, "memory": {}})
        self.persistent_enabled = {int(k): v for k, v in data.get("enabled", {}).items()}
        raw = data.get("memory", {})
        self.persistent_memory = {}
        for uid_s, msgs in raw.items():
            try:
                uid = int(uid_s)
                if isinstance(msgs, list):
                    self.persistent_memory[uid] = [
                        (m.get("role"), m.get("content")) for m in msgs if isinstance(m, dict)
                    ]
            except ValueError:
                continue

    def _save_persistent_memory(self):
        _save(DATA_FILE, {
            "enabled": {str(u): e for u, e in self.persistent_enabled.items()},
            "memory": {str(u): [{"role": r, "content": c} for r, c in m]
                       for u, m in self.persistent_memory.items()},
        })

    def get_persistent_enabled(self, uid): return self.persistent_enabled.get(uid, False)

    def set_persistent_enabled(self, uid, enabled):
        if enabled:
            self.persistent_enabled[uid] = True
        else:
            self.persistent_enabled.pop(uid, None)
        self._save_persistent_memory()

    def get_persistent_memory(self, uid): return self.persistent_memory.get(uid, [])

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
                    f"sv{i}": [(m["role"], m["content"]) for m in data.get(f"sv{i}", [])]
                    for i in range(1, 6)
                }
                self.active_slot[uid] = data.get("_active", "sv1")
            except (ValueError, KeyError, TypeError):
                continue

    def _save_slots(self):
        out = {}
        for uid, slots in self.user_slots.items():
            out[str(uid)] = {k: [{"role": r, "content": c} for r, c in v] for k, v in slots.items()}
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
    async def groq_chat(self, messages, uid=None, temperature=0.8, max_tokens=512,
                        model: Optional[str] = None) -> str:
        keys = self.user_keys(uid, "groq")
        if not keys:
            raise Exception("No Groq keys")
        target_model = model or self.current_model(uid, "groq") or GLOBAL_GROQ_MODELS[0]

        stripped = []
        for m in messages:
            mm = dict(m)
            if mm.get("images"):
                note = f"\n[{len(mm['images'])} image(s); vision not available on this fallback]"
                mm["content"] = (mm.get("content") or "") + note
                mm.pop("images", None)
            stripped.append(mm)

        last_err = None
        for _ in range(max(len(keys), 1) + 1):
            key = self.current_key(uid, "groq")
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            payload = {"model": target_model, "messages": stripped,
                       "temperature": temperature, "max_tokens": max_tokens,
                       "tool_choice": "none"}
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(GROQ_API_URL, json=payload, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=30)) as r:
                        if r.status == 200:
                            d = await r.json()
                            return d["choices"][0]["message"]["content"]
                        if r.status == 429:
                            self.rotate_key(uid, "groq")
                            self.rotate_model(uid, "groq")
                            target_model = self.current_model(uid, "groq") or target_model
                            await asyncio.sleep(0.3)
                            continue
                        body = await r.text()
                        raise Exception(f"Groq {r.status}: {body[:150]}")
            except Exception as e:
                last_err = e
                self.rotate_key(uid, "groq")
                await asyncio.sleep(0.3)
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
            contents = [types.Content(role="user", parts=[types.Part.from_text(text=" ")])]
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

    async def gemini_chat(self, messages, uid=None, temperature=0.8, max_tokens=1024) -> str:
        keys = self.user_keys(uid, "gemini")
        if not keys:
            raise Exception("No Gemini keys")
        last_err = None
        for _ in range(max(len(keys), 1) + 1):
            key = self.current_key(uid, "gemini")
            model = self.current_model(uid, "gemini") or GLOBAL_GEMINI_MODELS[0]
            try:
                return await asyncio.to_thread(
                    self._gemini_call_sync, messages, key, model, temperature, max_tokens)
            except Exception as e:
                last_err = e
                self.rotate_key(uid, "gemini")
                self.rotate_model(uid, "gemini")
                await asyncio.sleep(0.3)
        raise Exception(f"Gemini failed: {last_err}")

    # ==================================================================
    # HF TEXT
    # ==================================================================
    async def hf_text_chat(self, messages, uid=None, max_tokens=512) -> str:
        keys = self.user_keys(uid, "hf")
        if not keys:
            raise Exception("No HF keys")
        sys_parts, user_parts = [], []
        for m in messages:
            if m["role"] == "system":
                sys_parts.append(m["content"])
            elif m["role"] == "user":
                user_parts.append(m.get("content") or "")
            else:
                user_parts.append(f"Assistant: {m.get('content','')}")
        prompt = ("\n".join(sys_parts) + "\n\n" + "\n".join(user_parts))[:4000]

        last_err = None
        for _ in range(max(len(keys), 1) + 1):
            key = self.current_key(uid, "hf")
            model = self.current_model(uid, "hf_text") or GLOBAL_HF_TEXT_MODELS[0]
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(
                        f"{HF_INFERENCE_URL}/{model}",
                        headers={"Authorization": f"Bearer {key}"},
                        json={"inputs": prompt, "parameters": {"max_new_tokens": max_tokens}},
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
                await asyncio.sleep(0.3)
        raise Exception(f"HF text failed: {last_err}")

    # ==================================================================
    # OPENROUTER
    # ==================================================================
    async def openrouter_call(self, messages, uid=None, temperature=0.6,
                              max_tokens=4096, model: Optional[str] = None) -> str:
        keys = self.user_keys(uid, "openrouter")
        if not keys:
            raise Exception("No OpenRouter keys")
        target_model = model or self.current_model(uid, "openrouter") or GLOBAL_OPENROUTER_MODELS[0]
        last_err = None
        for _ in range(max(len(keys), 1) + 1):
            key = self.current_key(uid, "openrouter")
            payload = {"model": target_model, "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens}
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://discord.com",
                "X-Title": "Mac",
            }
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(OPENROUTER_API_URL, json=payload, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=120)) as r:
                        if r.status == 200:
                            d = await r.json()
                            choice = d.get("choices", [{}])[0].get("message", {})
                            return choice.get("content") or choice.get("reasoning") or ""
                        if r.status == 429:
                            self.rotate_key(uid, "openrouter")
                            self.rotate_model(uid, "openrouter")
                            target_model = self.current_model(uid, "openrouter") or target_model
                            await asyncio.sleep(0.3)
                            continue
                        body = await r.text()
                        raise Exception(f"OpenRouter {r.status}: {body[:150]}")
            except Exception as e:
                last_err = e
                self.rotate_key(uid, "openrouter")
                await asyncio.sleep(0.3)
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
            async with aiohttp.ClientSession() as s:
                async with s.post(api_url, headers={"Authorization": f"Bearer {key}"},
                                  json={"inputs": clean[:1200]},
                                  timeout=aiohttp.ClientTimeout(total=12)) as r:
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
    # IMAGE GEN
    # ==================================================================
    async def generate_pollinations_image(self, prompt: str) -> bytes:
        url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status == 200:
                    return await r.read()
                raise Exception(f"Pollinations {r.status}")

    async def generate_gemini_image(self, prompt: str, uid=None) -> bytes:
        keys = self.user_keys(uid, "gemini_image") or self.user_keys(uid, "gemini")
        if not keys:
            raise Exception("No Gemini key")
        key = self.current_key(uid, "gemini_image") or self.current_key(uid, "gemini")
        try:
            return await asyncio.to_thread(self._gemini_image_sync, prompt, key)
        except Exception as e:
            logger.error(f"Gemini image: {e}")
            return await self.generate_pollinations_image(prompt)

    def _gemini_image_sync(self, prompt: str, api_key: str) -> bytes:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-3.1-flash-lite-image", contents=prompt,
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
        raise Exception("No image data")

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
                async with aiohttp.ClientSession() as s:
                    async with s.post(api_url,
                                      headers={"Authorization": f"Bearer {key}",
                                               "Content-Type": "application/json"},
                                      json={"inputs": prompt},
                                      timeout=aiohttp.ClientTimeout(total=40)) as resp:
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
        form.add_field('image', image_data, filename='image.png', content_type='image/png')
        async with aiohttp.ClientSession() as s:
            async with s.post(f'https://api.imgbb.com/1/upload?key={key}',
                              data=form, timeout=aiohttp.ClientTimeout(total=30)) as r:
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
            raise Exception("No Fish Audio key")
        key = keys[0]
        voices = self.all_voices(uid) if uid else BUILTIN_VOICES
        voice_key = (voice_key or (self.default_voice(uid) if uid else DEFAULT_VOICE)).lower().strip()
        if voice_key not in voices:
            voice_key = DEFAULT_VOICE
        ref_id = voices[voice_key]["id"]
        text = strip_for_tts(text) or "Nothing to say."
        if len(text) > 1200:
            text = text[:1200]
        payload = {"text": text, "reference_id": ref_id, "format": fmt,
                   "latency": "normal", "normalize": True}
        if fmt == "mp3":
            payload["mp3_bitrate"] = 128
            payload["sample_rate"] = 44100
        elif fmt == "opus":
            payload["opus_bitrate"] = 32000
            payload["sample_rate"] = 48000
        headers = {"Authorization": f"Bearer {key}",
                   "Content-Type": "application/json", "model": GLOBAL_FISH_MODEL}
        async with aiohttp.ClientSession() as s:
            async with s.post(FISH_AUDIO_URL, json=payload, headers=headers,
                              timeout=aiohttp.ClientTimeout(total=90)) as r:
                if r.status != 200:
                    err = await r.text()
                    raise Exception(f"Fish {r.status}: {err[:150]}")
                data = await r.read()
                if not data or len(data) < 500:
                    raise Exception("Empty audio")
                return data

    # ==================================================================
    # CHAT ORCHESTRATION
    # ==================================================================
    def _build_system_prompt(self, uid, user_prompt, explicit_system=None):
        base = explicit_system if explicit_system else \
            self.mode_prompts.get(self.current_mode, self.mode_prompts[DEFAULT_MODE])
        if uid:
            p = self.get_profile(uid)
            bits = []
            if p.get("name"):         bits.append(f"call user {p['name']}")
            if p.get("pronouns"):     bits.append(f"pronouns: {p['pronouns']}")
            if p.get("vibe"):         bits.append(f"vibe: {p['vibe']}")
            if p.get("instructions"): bits.append(f"custom: {p['instructions']}")
            if p.get("catchphrase"):  bits.append(f"end with: {p['catchphrase']}")
            if p.get("language"):     bits.append(f"reply in {p['language']}")
            if bits:
                base += "\n[USER: " + " | ".join(bits) + "]"
        base += MAC_SODIUM_LORE
        sh = _sodium_hint(user_prompt)
        if sh:
            base += sh
        return base

    def _build_messages(self, prompt, uid, system_prompt, slot_name, images=None):
        messages = []

        # persistent memory — drop trailing entry if it duplicates the current prompt
        if uid and self.get_persistent_enabled(uid):
            pm = list(self.get_persistent_memory(uid)[-20:])
            if pm and pm[-1][0] == "user" and pm[-1][1] == prompt:
                pm = pm[:-1]
            for role, content in pm:
                messages.append({"role": role, "content": content})

        slot_history = list(self.get_slot(uid, slot_name)) if uid else []
        # drop trailing user entry that duplicates the current prompt
        if slot_history and slot_history[-1][0] == "user" and slot_history[-1][1] == prompt:
            slot_history = slot_history[:-1]

        for role, content in slot_history[-16:]:
            messages.append({"role": role, "content": content})

        # add the current message exactly once
        messages.append({"role": "user", "content": prompt, "images": images or []})
        return [{"role": "system",
                 "content": self._build_system_prompt(uid, prompt, system_prompt)}] + messages

    async def chat_call(self, prompt, uid=None, system_prompt=None,
                        slot_name="sv1", max_tokens=512, images=None) -> str:
        messages = self._build_messages(prompt, uid, system_prompt, slot_name, images)

        if images:
            try:
                return await self.gemini_chat(messages, uid=uid, temperature=0.85,
                                              max_tokens=max_tokens)
            except Exception as e:
                logger.warning(f"Gemini vision failed: {e}")

        try:
            return await self.groq_chat(messages, uid=uid, temperature=0.85, max_tokens=max_tokens)
        except Exception as e:
            logger.warning(f"Groq failed: {e}; trying Gemini")
            try:
                return await self.gemini_chat(messages, uid=uid, temperature=0.85,
                                              max_tokens=max_tokens)
            except Exception as e2:
                logger.warning(f"Gemini failed: {e2}; trying HF")
                try:
                    return await self.hf_text_chat(messages, uid=uid, max_tokens=max_tokens)
                except Exception as e3:
                    return (f"❌ All providers failed.\n"
                            f"Groq: {str(e)[:100]}\n"
                            f"Gemini: {str(e2)[:100]}\n"
                            f"HF: {str(e3)[:100]}")

    # ==================================================================
    # PIPELINE
    # ==================================================================
    async def gemini_refine_and_research(self, task: str, uid) -> Tuple[str, str]:
        search_results = await perform_web_search(task)
        if search_results.startswith("No results"):
            search_results = "(no results)"
        sys_p = ("Research assistant. Output EXACTLY:\n"
                 "===REFINED_PROMPT===\n<clear technically precise prompt>\n"
                 "===REFERENCE===\n<dense factual docs, APIs, constraints>")
        usr_p = f"TASK:\n{task}\n\nSEARCH:\n{search_results[:4000]}"
        try:
            out = await self.gemini_chat(
                [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
                uid=uid, temperature=0.5, max_tokens=2500)
        except Exception:
            return task, search_results
        refined, ref = task, search_results
        m = re.search(r"===REFINED_PROMPT===\s*(.*?)\s*===REFERENCE===\s*(.*)", out, re.DOTALL)
        if m:
            refined = m.group(1).strip() or task
            ref = m.group(2).strip() or search_results
        else:
            refined = out.strip() or task
        return refined, ref

    async def gemini_review(self, refined_task: str, code: str, uid) -> str:
        sys_p = ("Strict senior code reviewer. If correct+complete+production-ready, reply "
                 "EXACTLY 'APPROVED' on its own line + one-line summary. Otherwise numbered issues.")
        usr_p = f"Task:\n{refined_task}\n\nCode:\n```\n{code[:8000]}\n```"
        try:
            return await self.gemini_chat(
                [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
                uid=uid, temperature=0.3, max_tokens=1500)
        except Exception as e:
            return f"(reviewer error: {e})"

    async def run_pipeline(self, channel, uid, task: str, filename=None, max_iterations=3):
        filename = filename or infer_filename(task)
        emb = discord.Embed(title="🏗️ Pipeline Started",
                            description=f"**Task:** {task[:800]}\n**File:** `{filename}`",
                            color=C_WARM)
        emb.add_field(name="Stages", value=(
            "1️⃣ **GEMINI** — refine + research\n"
            "2️⃣ **OPENROUTER** — generate\n"
            "3️⃣ **GEMINI** — review\n"
            "4️⃣ **OPENROUTER** — fix loop"
        ), inline=False)
        status = await safe_send(channel, embed=emb)
        if status is None:
            return

        async def step(title, body, color=C_PRIMARY):
            e = discord.Embed(title=title, description=body[:4000], color=color)
            e.set_footer(text=f"Pipeline · {filename}")
            await safe_edit(status, embed=e)

        try:
            await step("1️⃣ GEMINI — refining + researching", f"Task: {task[:350]}", C_WARM)
            refined, docs = await self.gemini_refine_and_research(task, uid)
            await step("1️⃣ GEMINI — ready",
                       f"**Prompt:**\n{refined[:1200]}\n\n**Docs:**\n{docs[:1500]}", C_OK)

            await step("2️⃣ OPENROUTER — generating...", "⏳", C_DEEP)

            def build_msgs(existing="", issues=""):
                sp = ("You are an elite software engineer. Produce a complete working "
                      "production-ready solution. Output ONLY the full file content in a "
                      "single fenced code block with the language identifier.")
                parts = [f"TASK:\n{refined}"]
                if docs:
                    parts.append(f"DOCS:\n{docs[:5000]}")
                if existing:
                    parts.append(f"EXISTING:\n```\n{existing[:7000]}\n```")
                if issues:
                    parts.append(f"FIX THESE:\n{issues}")
                parts.append(f"Deliverable: `{filename}`. ONLY the code block.")
                return [{"role": "system", "content": sp},
                        {"role": "user", "content": "\n\n".join(parts)}]

            try:
                raw_code = await self.openrouter_call(
                    build_msgs(), uid=uid, temperature=0.5, max_tokens=6000)
            except Exception as e:
                await step("❌ OPENROUTER failed", f"`{str(e)[:280]}`", C_ERR)
                return

            code = strip_code_fences(raw_code) or raw_code.strip()
            await step("2️⃣ OPENROUTER — draft ready", f"```\n{code[:3000]}\n```", C_OK)

            final_code = code
            approved = False
            iteration = 0
            for iteration in range(1, max_iterations + 1):
                await step(f"3️⃣ GEMINI review — {iteration}/{max_iterations}",
                           f"Checking ({len(final_code)} chars)...", C_WARM)
                review = await self.gemini_review(refined, final_code, uid)
                if review.strip().upper().startswith("APPROVED"):
                    await step(f"3️⃣ GEMINI — {iteration}", f"✅ APPROVED\n\n{review[:2500]}", C_OK)
                    approved = True
                    break
                await step(f"3️⃣ GEMINI — {iteration}", f"⚠️ Issues\n\n{review[:2800]}", C_ACCENT)
                await step(f"4️⃣ OPENROUTER — fixing ({iteration})", "⏳", C_DEEP)
                try:
                    raw_fixed = await self.openrouter_call(
                        build_msgs(existing=final_code, issues=review),
                        uid=uid, temperature=0.4, max_tokens=6000)
                except Exception as e:
                    await step(f"❌ OpenRouter fix failed ({iteration})",
                               f"`{str(e)[:280]}`", C_ERR)
                    break
                fixed = strip_code_fences(raw_fixed) or raw_fixed.strip()
                if not fixed.strip():
                    break
                final_code = fixed
                await step(f"4️⃣ OPENROUTER — fix applied ({iteration})",
                           f"```\n{final_code[:2800]}\n```", C_PRIMARY)

            summary = discord.Embed(
                title=f"✅ Pipeline complete — `{filename}`",
                description=(f"**Review:** {'APPROVED' if approved else 'max iter'}\n"
                             f"**Size:** {len(final_code)} chars\n"
                             f"**Iterations:** {iteration}"),
                color=C_OK if approved else C_WARM)
            await safe_edit(status, embed=summary)
            buf = io.BytesIO(final_code.encode("utf-8"))
            try:
                await safe_send(channel, content=f"📦 **`{filename}`**",
                                file=discord.File(buf, filename=filename))
            except discord.HTTPException as e:
                await send_long(channel, f"❌ Attach failed ({e}). Code:\n\n{final_code}")
        except Exception as e:
            logger.error(f"Pipeline: {e}")
            await step("❌ Pipeline crashed", f"`{str(e)[:350]}`", C_ERR)

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
            await send_long(ch, f"🏟️ **AI DEBATE – {desc}**")
            while turn < max_turns:
                if uid not in self.ai_chat_sessions:
                    break
                n = 1 if turn % 2 == 0 else 2
                o = 2 if n == 1 else 1
                em = "🤠" if n == 1 else "🤖"
                if not hist:
                    up = f"Topic: {desc}\nYou are AI{n}. Bold opening, aim for one final answer."
                else:
                    recent = hist[-8:]
                    ctx = "\n".join(f"AI{e['role']}: {e['content']}" for e in recent)
                    up = f"Prior:\n{ctx}\n\nAI{n} responds."
                sp = f"You are AI{n} debating \"{desc}\" vs AI{o}. Dramatic, <400 chars, aim for consensus."
                try:
                    resp = strip_think(await self.groq_chat(
                        [{"role": "system", "content": sp}, {"role": "user", "content": up}],
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
                        [{"role": "system", "content": "You are AI1. Give the final joint verdict."},
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
            logger.error(f"Debate: {e}")
            self.ai_chat_sessions.pop(uid, None)

    # ==================================================================
    # MESSAGE HANDLER
    # ==================================================================
    async def process_user_message(self, user, clean_content, destination,
                                   thinking_msg=None, reply_context=None,
                                   trigger_msg=None, images=None):
        images = images or []
        uid = user.id
        slot_name = self.active_slot.get(uid, "sv1")
        if uid not in self.user_slots:
            self.get_slot(uid, "sv1")

        macro_match = re.match(r'^\.(\w+)\s*(.*)$', clean_content)
        if macro_match:
            mname = macro_match.group(1).lower()
            extra = macro_match.group(2)
            macros = self.get_macros(uid)
            if mname in macros:
                clean_content = macros[mname] + (f"\n{extra}" if extra else "")

        search_match = re.match(r'^(?:search|google|look\s*up|find|lookup)\s*:?\s*(.+)$',
                                clean_content, re.IGNORECASE)
        if search_match:
            query = search_match.group(1).strip()
            if query:
                try:
                    thinking_msg = await destination.send(f"🌐 **{query}**...")
                except discord.HTTPException:
                    return
                results = await perform_web_search(query)
                if results.startswith("No results"):
                    return await safe_edit(thinking_msg, content=f"❌ {results}")
                augmented = (f"Web results for: {query}\n\n{results}\n\n---\n\n"
                             f"Summarize. Cite sources inline like [1], [2].")
                response = await self.chat_call(augmented, uid=uid, max_tokens=800)
                response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
                self.append_to_slot(uid, slot_name, "user", clean_content)
                self.append_to_slot(uid, slot_name, "assistant", response)
                if self.get_persistent_enabled(uid):
                    self.add_persistent_memory(uid, "user", clean_content)
                    self.add_persistent_memory(uid, "assistant", response)
                if len(response) <= DISCORD_LIMIT:
                    await safe_edit(thinking_msg, content=response)
                else:
                    try:
                        await thinking_msg.delete()
                    except discord.HTTPException:
                        pass
                    await send_long(destination, response)
                return

        if self.get_persistent_enabled(uid):
            self.add_persistent_memory(uid, "user", clean_content)
        self.append_to_slot(uid, slot_name, "user", clean_content)

        is_short = len(clean_content) < 80 and not images and not reply_context
        thinking_msg = None
        if not is_short:
            try:
                thinking_msg = await destination.send("🔥")
            except discord.Forbidden:
                if trigger_msg:
                    try:
                        await trigger_msg.reply("❌ No permission to send here.")
                    except Exception:
                        pass
                return
            except discord.HTTPException:
                return

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
            base = self.mode_prompts.get(self.current_mode, self.mode_prompts[DEFAULT_MODE])
            system_prompt = (f"{base}\n\nReplying to **{oa}**: \"{oc}\"\n"
                             f"User says: \"{clean_content}\"\nReact naturally. 1–3 sentences.")

        if images:
            note = f"[{len(images)} image(s) — actually look at them.]"
            system_prompt = (system_prompt + "\n" + note) if system_prompt else note

        try:
            response = await self.chat_call(clean_content, uid=uid,
                                            system_prompt=system_prompt,
                                            slot_name=slot_name, images=images)
            response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
            if self.get_persistent_enabled(uid):
                self.add_persistent_memory(uid, "assistant", response)
            self.append_to_slot(uid, slot_name, "assistant", response)

            if thinking_msg:
                if len(response) <= DISCORD_LIMIT:
                    await safe_edit(thinking_msg, content=response)
                else:
                    try:
                        await thinking_msg.delete()
                    except discord.HTTPException:
                        pass
                    await send_long(destination, response)
            else:
                await send_long(destination, response)

            if self.current_mode == "brainrot":
                try:
                    pool = self.get_gif_pool(uid)
                    await destination.send(random.choice(pool))
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"process_user_message: {e}", exc_info=True)
            if thinking_msg:
                await safe_edit(thinking_msg, content=f"❌ {str(e)[:150]}")
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
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": "Wan-AI/Wan2.2-T2V-A14B", "prompt": prompt, "image_size": "1280x720"}
            async with aiohttp.ClientSession() as s:
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
                    async with s.post(status_url, headers={"Authorization": f"Bearer {api_key}"},
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
                            await safe_edit(status_message, content=f"🎬 {attempt+1}/120 — **{st}**")
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
            async with aiohttp.ClientSession() as s:
                async with s.get(url, headers=headers,
                                 timeout=aiohttp.ClientTimeout(total=240)) as r:
                    if r.status == 200:
                        ct = r.headers.get('Content-Type', '')
                        if any(x in ct for x in ('audio', 'mpeg', 'ogg', 'octet-stream')):
                            data = await r.read()
                            if len(data) < 1000:
                                raise Exception("Invalid")
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
            gc = len(self.guilds)
            txt = f"🔥 with {gc} servers" if gc else "🔥 with fire"
            try:
                await self.change_presence(
                    activity=discord.Activity(type=discord.ActivityType.playing, name=txt))
            except Exception:
                pass
            await asyncio.sleep(90)

    async def load_pen_archive_async(self):
        url = "https://raw.githubusercontent.com/Pen-123/archive-/refs/heads/main/archives.txt"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        self.pen_archive = await r.text()
        except Exception:
            pass

    async def setup_hook(self):
        for c in self.tree.walk_commands():
            try:
                c.allowed_installs = discord.app_commands.AppInstallationType(guild=True, user=True)
                c.allowed_contexts = discord.app_commands.AppCommandContext(
                    guild=True, dm_channel=True, private_channel=True)
            except Exception:
                pass
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} commands")
        except Exception as e:
            logger.error(f"Sync: {e}")
        self.loop.create_task(self.update_presence_loop())
        self.loop.create_task(self.load_pen_archive_async())


bot = MacBot()


async def _provider_ac(i, c):
    return [app_commands.Choice(name=p, value=p) for p in PROVIDERS if c.lower() in p.lower()]


async def _model_provider_ac(i, c):
    return [app_commands.Choice(name=p, value=p) for p in MODEL_PROVIDERS if c.lower() in p.lower()]


# ============================================================
# /cs GROUP
# ============================================================
@bot.hybrid_group(name="cs", description="⚙️ Customization — profile, keys, models, voices, macros, GIFs",
                  invoke_without_command=True)
async def cs_group(ctx):
    emb = discord.Embed(title="⚙️ /cs — Customization",
                        description="Everything's per-user. Your keys, your models, your vibes.",
                        color=C_PRIMARY)
    emb.add_field(name="Profile", value="`/cs profile` — name, pronouns, vibe, instructions, catchphrase, language", inline=False)
    emb.add_field(name="API Keys", value="`/cs key add|remove|list <provider> [key]`\nProviders: groq, openrouter, hf, gemini, gemini_image, fish, imgbb\nUp to 3 keys per provider", inline=False)
    emb.add_field(name="Models", value="`/cs model add|remove|list <provider> [model]`\nProviders: groq, openrouter, hf_image, hf_text, gemini, fish\nUp to 3 models per provider", inline=False)
    emb.add_field(name="Voices", value="`/cs voice <name>` · `/cs voice-add <name> <fish_id> [emoji] [desc]` · `/cs voice-del <name>` · `/cs voices`", inline=False)
    emb.add_field(name="Macros", value="`/cs macro add|remove|list <name> [prompt]` — trigger with `.name` in chat", inline=False)
    emb.add_field(name="GIFs", value="`/cs gif list|add|remove|clear|reset [value]`", inline=False)
    emb.add_field(name="Misc", value="`/cs show` · `/cs reset [section]`", inline=False)
    await ctx.send(embed=emb)


@cs_group.command(name="profile", description="Set your personal profile")
@app_commands.describe(name="What Mac calls you", pronouns="Your pronouns",
                       vibe="Vibe to match (e.g. 'dry sarcastic')",
                       instructions="Extra instructions Mac must follow",
                       catchphrase="End every reply with this", language="Preferred language",
                       clear="Clear your profile")
async def cs_profile(ctx, name: str = None, pronouns: str = None, vibe: str = None,
                     instructions: str = None, catchphrase: str = None,
                     language: str = None, clear: bool = False):
    uid = ctx.author.id
    if clear:
        bot.clear_profile(uid)
        return await ctx.send("🧹 Profile cleared.")
    provided = any(v is not None for v in [name, pronouns, vibe, instructions, catchphrase, language])
    if not provided:
        p = bot.get_profile(uid)
        if not p:
            return await ctx.send("No profile set. Example:\n"
                                  "`/cs profile name:Alex vibe:sarcastic gremlin "
                                  "catchphrase:🔥 instructions:be brutally honest`")
        emb = discord.Embed(title=f"Your Profile — {ctx.author.display_name}", color=C_PRIMARY)
        for k, v in p.items():
            emb.add_field(name=k.title(), value=str(v)[:1024], inline=False)
        return await ctx.send(embed=emb, ephemeral=True)
    bot.set_profile(uid, name=name, pronouns=pronouns, vibe=vibe,
                    instructions=instructions, catchphrase=catchphrase, language=language)
    p = bot.get_profile(uid)
    emb = discord.Embed(title="✅ Profile Updated", color=C_OK)
    for k, v in p.items():
        emb.add_field(name=k.title(), value=str(v)[:1024], inline=False)
    await ctx.send(embed=emb, ephemeral=True)


@cs_group.command(name="key", description="Manage your API keys (up to 3 per provider)")
@app_commands.autocomplete(provider=_provider_ac)
@app_commands.describe(provider="groq|openrouter|hf|gemini|gemini_image|fish|imgbb",
                       action="add | remove | list", value="API key (for add) or index (for remove)")
async def cs_key(ctx, provider: str, action: str = "list", value: str = None):
    uid = ctx.author.id
    p = provider.lower()
    if p not in PROVIDERS:
        return await ctx.send(f"❌ Providers: {', '.join(PROVIDERS)}", ephemeral=True)
    u = bot._cs(uid)
    field = f"{p}_keys"
    keys = u.setdefault(field, [])
    a = action.lower()
    if a == "list":
        if not keys:
            return await ctx.send(f"No custom `{p}` keys — using bot defaults.", ephemeral=True)
        masked = [f"`{i}` ...{k[-6:]}" for i, k in enumerate(keys)]
        return await ctx.send(f"**Your `{p}` keys ({len(keys)}/3):**\n" + "\n".join(masked), ephemeral=True)
    if a == "add":
        if not value:
            return await ctx.send("❌ Provide a key.", ephemeral=True)
        if len(keys) >= MAX_KEYS_PER_PROVIDER:
            return await ctx.send(f"❌ Max {MAX_KEYS_PER_PROVIDER} keys. Remove one first.", ephemeral=True)
        keys.append(value.strip())
        bot._save_cs()
        return await ctx.send(f"✅ Added `{p}` key. You now have {len(keys)}.", ephemeral=True)
    if a == "remove":
        if value is None:
            return await ctx.send("❌ Provide index.", ephemeral=True)
        try:
            idx = int(value)
            keys.pop(idx)
            bot._save_cs()
            return await ctx.send(f"🗑️ Removed.", ephemeral=True)
        except (ValueError, IndexError):
            return await ctx.send("❌ Invalid index.", ephemeral=True)
    await ctx.send("❌ Actions: add | remove | list", ephemeral=True)


@cs_group.command(name="model", description="Manage your preferred models (up to 3 per provider)")
@app_commands.autocomplete(provider=_model_provider_ac)
@app_commands.describe(provider="groq|openrouter|hf_image|hf_text|gemini|fish",
                       action="add | remove | list", value="Model id (for add) or index (for remove)")
async def cs_model(ctx, provider: str, action: str = "list", value: str = None):
    uid = ctx.author.id
    p = provider.lower()
    if p not in MODEL_PROVIDERS:
        return await ctx.send(f"❌ Providers: {', '.join(MODEL_PROVIDERS)}", ephemeral=True)
    u = bot._cs(uid)
    field = f"{p}_models"
    models = u.setdefault(field, [])
    a = action.lower()
    if a == "list":
        if not models:
            defaults = bot.user_models(None, p)
            return await ctx.send(f"No custom `{p}` models. Bot defaults:\n"
                                  + "\n".join(f"• `{m}`" for m in defaults), ephemeral=True)
        return await ctx.send(f"**Your `{p}` models ({len(models)}/3):**\n"
                              + "\n".join(f"`{i}` {m}" for i, m in enumerate(models)), ephemeral=True)
    if a == "add":
        if not value:
            return await ctx.send("❌ Provide a model id.", ephemeral=True)
        if len(models) >= MAX_MODELS_PER_PROVIDER:
            return await ctx.send(f"❌ Max {MAX_MODELS_PER_PROVIDER} models.", ephemeral=True)
        models.append(value.strip())
        bot._save_cs()
        return await ctx.send(f"✅ Added `{p}` model. You now have {len(models)}.", ephemeral=True)
    if a == "remove":
        if value is None:
            return await ctx.send("❌ Provide index.", ephemeral=True)
        try:
            idx = int(value)
            models.pop(idx)
            bot._save_cs()
            return await ctx.send(f"🗑️ Removed.", ephemeral=True)
        except (ValueError, IndexError):
            return await ctx.send("❌ Invalid index.", ephemeral=True)
    await ctx.send("❌ Actions: add | remove | list", ephemeral=True)


@cs_group.command(name="voice", description="Set your default TTS voice")
@app_commands.describe(name="Voice name (blank to see current)")
async def cs_voice(ctx, name: str = None):
    uid = ctx.author.id
    voices = bot.all_voices(uid)
    if name is None:
        cur = bot.default_voice(uid)
        listing = "\n".join(f"• `{k}` — {v['emoji']} {v['desc']}" for k, v in voices.items())
        return await ctx.send(f"Your default voice: **{cur}**\n\nAvailable:\n{listing}", ephemeral=True)
    if name not in voices:
        return await ctx.send(f"❌ Unknown. Available: {', '.join(voices.keys())}", ephemeral=True)
    u = bot._cs(uid)
    u["default_voice"] = name
    bot._save_cs()
    meta = voices[name]
    await ctx.send(f"✅ Default voice → {meta['emoji']} **{meta['desc']}**")


@cs_group.command(name="voice-add", description="Add a custom Fish Audio voice")
@app_commands.describe(name="Short name (no spaces)", fish_id="Fish Audio reference ID",
                       emoji="Emoji", desc="Description")
async def cs_voice_add(ctx, name: str, fish_id: str, emoji: str = "🎤", desc: str = None):
    uid = ctx.author.id
    n = name.lower().strip().replace(" ", "-")
    if n in BUILTIN_VOICES:
        return await ctx.send("❌ Collides with built-in.", ephemeral=True)
    u = bot._cs(uid)
    u.setdefault("voices", {})[n] = {"id": fish_id, "emoji": emoji, "desc": desc or n}
    bot._save_cs()
    await ctx.send(f"✅ Added `{n}` — {emoji} {desc or n}.")


@cs_group.command(name="voice-del", description="Remove a custom voice")
async def cs_voice_del(ctx, name: str):
    uid = ctx.author.id
    u = bot._cs(uid)
    voices = u.get("voices", {})
    if name.lower() not in voices:
        return await ctx.send("❌ Not a custom voice.", ephemeral=True)
    voices.pop(name.lower())
    bot._save_cs()
    await ctx.send(f"🗑️ Removed `{name}`.")


@cs_group.command(name="voices", description="List all voices available to you")
async def cs_voices(ctx):
    uid = ctx.author.id
    voices = bot.all_voices(uid)
    lines = "\n".join(f"• `{k}` — {v['emoji']} {v['desc']}" for k, v in voices.items())
    await send_long(ctx, f"🎙️ **Voices**\n{lines}")


@cs_group.command(name="macro", description="Save/run your own prompt shortcuts")
@app_commands.describe(action="add | remove | list", name="Macro name", prompt="Prompt text")
async def cs_macro(ctx, action: str = "list", name: str = None, prompt: str = None):
    uid = ctx.author.id
    a = action.lower()
    u = bot._cs(uid)
    macros = u.setdefault("macros", {})
    if a == "add":
        if not name or not prompt:
            return await ctx.send("❌ `/cs macro add <name> <prompt>`")
        macros[name.lower()] = prompt
        bot._save_cs()
        await ctx.send(f"💾 Macro `.{name.lower()}` saved.")
    elif a == "remove":
        if not name or name.lower() not in macros:
            return await ctx.send("❌ Not found.")
        macros.pop(name.lower())
        bot._save_cs()
        await ctx.send(f"🗑️ Removed.")
    elif a == "list":
        if not macros:
            return await ctx.send("No macros. Example: `/cs macro add explain explain X in 3 sentences`")
        lines = "\n".join(f"• `.{n}` — {p[:80]}" for n, p in macros.items())
        await send_long(ctx, f"💾 **Macros**\n{lines}")
    else:
        await ctx.send("❌ add | remove | list")


@cs_group.command(name="gif", description="Manage your brainrot GIF pool")
@app_commands.describe(action="list | add | remove | clear | reset", value="URL (add) or index (remove)")
async def cs_gif(ctx, action: str = "list", value: str = None):
    uid = ctx.author.id
    a = action.lower()
    u = bot._cs(uid)
    pool = u.setdefault("brainrot_gifs", [])
    if a == "list":
        current = bot.get_gif_pool(uid)
        lines = "\n".join(f"`{i}` {url}" for i, url in enumerate(current))
        source = "custom" if pool else "default"
        await send_long(ctx, f"🧠 **Brainrot pool ({source}, {len(current)})**\n{lines[:3500]}")
    elif a == "add":
        if not value:
            return await ctx.send("❌ `/cs gif add <url>`")
        pool.append(value.strip())
        bot._save_cs()
        await ctx.send(f"✅ Added. Pool has {len(pool)}.")
    elif a == "remove":
        if value is None:
            return await ctx.send("❌ `/cs gif remove <index>`")
        try:
            idx = int(value)
            pool.pop(idx)
            bot._save_cs()
            await ctx.send(f"🗑️ Removed index {idx}.")
        except (ValueError, IndexError):
            await ctx.send("❌ Invalid index.")
    elif a == "clear":
        u["brainrot_gifs"] = []
        bot._save_cs()
        await ctx.send("🧹 Cleared. Default pool used.")
    elif a == "reset":
        u.pop("brainrot_gifs", None)
        bot._save_cs()
        await ctx.send("↺ Reset to defaults.")
    else:
        await ctx.send("❌ list | add | remove | clear | reset")


@cs_group.command(name="show", description="Show ALL your customizations")
async def cs_show(ctx):
    uid = ctx.author.id
    u = bot.cs.get(uid, {})
    emb = discord.Embed(title=f"⚙️ {ctx.author.display_name}'s Customizations", color=C_PRIMARY)
    prof = u.get("profile", {})
    if prof:
        emb.add_field(name="Profile",
                      value="\n".join(f"• {k}: {v}" for k, v in prof.items())[:1024],
                      inline=False)
    for p in PROVIDERS:
        keys = u.get(f"{p}_keys", [])
        if keys:
            emb.add_field(name=f"{p} keys", value=f"{len(keys)} set", inline=True)
    for p in MODEL_PROVIDERS:
        models = u.get(f"{p}_models", [])
        if models:
            emb.add_field(name=f"{p} models", value=f"{len(models)}: {models[0][:40]}...", inline=True)
    voices = u.get("voices", {})
    if voices:
        emb.add_field(name="Custom voices", value=", ".join(voices.keys())[:1024], inline=False)
    macros = u.get("macros", {})
    if macros:
        emb.add_field(name="Macros", value=", ".join(f".{n}" for n in macros.keys())[:1024], inline=False)
    gifs = u.get("brainrot_gifs", [])
    if gifs:
        emb.add_field(name="Brainrot pool", value=f"{len(gifs)} custom GIFs", inline=True)
    if not emb.fields:
        emb.description = "Nothing set. Start with `/cs profile` or `/cs key add groq <key>`."
    await ctx.send(embed=emb, ephemeral=True)


@cs_group.command(name="reset", description="Reset a section of your customizations")
@app_commands.describe(section="profile | keys | models | voices | macros | gifs | all")
async def cs_reset(ctx, section: str = "all"):
    uid = ctx.author.id
    s = section.lower()
    u = bot.cs.get(uid, {})
    if s == "all":
        bot.cs.pop(uid, None)
        bot._save_cs()
        return await ctx.send("💥 All customizations reset.")
    if s == "profile":
        u.pop("profile", None); u.pop("default_voice", None)
    elif s == "keys":
        for p in PROVIDERS:
            u.pop(f"{p}_keys", None)
    elif s == "models":
        for p in MODEL_PROVIDERS:
            u.pop(f"{p}_models", None)
    elif s == "voices":
        u.pop("voices", None)
    elif s == "macros":
        u.pop("macros", None)
    elif s == "gifs":
        u.pop("brainrot_gifs", None)
    else:
        return await ctx.send("❌ Options: profile, keys, models, voices, macros, gifs, all")
    bot._save_cs()
    await ctx.send(f"🧹 Reset `{s}`.")


# ============================================================
# HELP
# ============================================================
@bot.hybrid_command(name="mac", description="🔥 Mac help")
async def mac_help(ctx):
    emb = discord.Embed(title="🔥 Mac v21.2", color=C_PRIMARY,
                        description="Mention me, reply to me, or slash. Per-user keys = per-user speed.")
    emb.add_field(name="💬 Chat", value="`@Mac <msg>` · `/query <msg>`", inline=False)
    emb.add_field(name="👁️ Vision", value="Attach or reply to an image — I see it.", inline=False)
    emb.add_field(name="🌐 Search", value="`search <thing>` (or google/look up/find)", inline=False)
    emb.add_field(name="⚙️ /cs — Customization", value=(
        "`/cs profile` — name, pronouns, vibe, instructions\n"
        "`/cs key` — your own API keys, 3 max per provider\n"
        "`/cs model` — your own models, 3 max per provider\n"
        "`/cs voice` / `voice-add` / `voice-del` / `voices`\n"
        "`/cs macro` — prompt shortcuts (`.name`)\n"
        "`/cs gif` — brainrot pool\n"
        "`/cs show` / `reset`"
    ), inline=False)
    emb.add_field(name="🗂️ Slots", value="`/sv1`–`/sv5` · `/svlist` · `/svclear`", inline=False)
    emb.add_field(name="🎭 Modes", value="`/setmode chill|brainrot|unhinged|coder`", inline=False)
    emb.add_field(name="🏗️ Pipeline", value="`/pipeline <task> [filename] [iterations]`", inline=False)
    emb.add_field(name="🖼️ Image", value="`/render <prompt> [mode]` · `/rendermode`", inline=False)
    emb.add_field(name="🎙️ TTS", value="`/tts [voice] <text>`", inline=False)
    emb.add_field(name="🎬 Media", value="`/video` · `/music`", inline=False)
    emb.add_field(name="💬 Debate", value="`/debate <topic>`", inline=False)
    emb.add_field(name="💾 Memory", value="`/sm` `/persistent` `/persistentdisable`", inline=False)
    emb.add_field(name="🏛️ Court", value="`/court` `/role` `/explain-case` `/start-court` `/endcourt`", inline=False)
    emb.add_field(name="🌍 UMF", value="`/umf` `/umf_list` `/umf_status` `/umf_admin`", inline=False)
    emb.set_footer(text="v21.2 — duplicate-message fix")
    await ctx.send(embed=emb)


@bot.hybrid_command(name="help", description="Alias for /mac")
async def help_alias(ctx):
    await mac_help(ctx)


# ============================================================
# CHAT / SLOTS / MODES / PIPELINE / TTS / IMAGE / MEDIA
# ============================================================
@bot.hybrid_command(name="query", description="💬 Talk to Mac")
async def query_cmd(ctx, message: str):
    await ctx.defer()
    try:
        images = await fetch_images_from_message(ctx.message) if ctx.message else []
        await bot.process_user_message(ctx.author, message, ctx.channel,
                                       trigger_msg=ctx.message, images=images)
    except Exception as e:
        await ctx.send(f"❌ `{e}`", ephemeral=True)


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
    bot.hybrid_command(name=_name, description=f"🗂️ Switch to slot {_name}")(_make_slot_cmd(_name))


@bot.hybrid_command(name="svclear", description="🧹 Clear current slot")
async def svclear(ctx):
    uid = ctx.author.id
    slot = bot.active_slot.get(uid, "sv1")
    bot.user_slots.setdefault(uid, {f"sv{i}": [] for i in range(1, 6)})[slot] = []
    bot._save_slots()
    await ctx.send(f"🧹 Cleared **{slot}**")


@bot.hybrid_command(name="svlist", description="📋 Your slots")
async def svlist(ctx):
    uid = ctx.author.id
    if uid not in bot.user_slots:
        bot.user_slots[uid] = {f"sv{i}": [] for i in range(1, 6)}
    active = bot.active_slot.get(uid, "sv1")
    lines = []
    for i in range(1, 6):
        n = f"sv{i}"
        c = len(bot.user_slots[uid].get(n, []))
        marker = " ← active" if n == active else ""
        lines.append(f"`{n}`: {c}{marker}")
    emb = discord.Embed(title=f"🗂️ Slots — {ctx.author.display_name}",
                        description="\n".join(lines), color=C_PRIMARY)
    await ctx.send(embed=emb, ephemeral=True)


@bot.hybrid_command(name="setmode", description="🎭 Set mode")
@app_commands.choices(mode=[
    app_commands.Choice(name="chill", value="chill"),
    app_commands.Choice(name="brainrot", value="brainrot"),
    app_commands.Choice(name="unhinged", value="unhinged"),
    app_commands.Choice(name="coder", value="coder"),
])
async def setmode_cmd(ctx, mode: str):
    if mode not in bot.mode_prompts:
        return await ctx.send(f"❌ Options: {', '.join(bot.mode_prompts)}")
    bot.current_mode = mode
    emoji = {"chill": "😎", "brainrot": "🧠", "unhinged": "🔥", "coder": "💻"}.get(mode, "🎭")
    extra = " — GIFs on every reply." if mode == "brainrot" else ""
    await ctx.send(f"{emoji} → **{mode}**{extra}")


@bot.hybrid_command(name="pipeline", description="🏗️ GEMINI → OPENROUTER → review → fix")
@app_commands.describe(task="What to build", filename="Output filename", iterations="Max loops (1-5)")
async def pipeline_cmd(ctx, task: str, filename: str = None, iterations: int = 3):
    await ctx.defer()
    iterations = max(1, min(5, iterations))
    fn = filename.strip() if filename else infer_filename(task)
    try:
        await bot.run_pipeline(ctx.channel, ctx.author.id, task, fn, iterations)
    except Exception as e:
        await ctx.send(f"❌ `{e}`")


@bot.hybrid_command(name="tts", description="Say text as a voice message")
@app_commands.describe(voice="Voice (defaults to /cs voice)", prompt="Text")
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
        return await ctx.send(f"❌ TTS: {str(e)[:150]}")
    meta = voices[vkey]
    try:
        file = discord.File(io.BytesIO(audio), filename="voice-message.ogg")
        flags = discord.MessageFlags(is_voice_message=True)
        await ctx.send(file=file, flags=flags)
    except Exception:
        file2 = discord.File(io.BytesIO(audio), filename="voice.mp3")
        await ctx.send(content=f"{meta['emoji']} **{meta['desc']}**\n-# {clean[:350]}", file=file2)


@bot.hybrid_command(name="render", description="🎨 Generate an image")
@app_commands.describe(prompt="Describe image", mode="smart | fast | hf")
async def render_cmd(ctx, prompt: str, mode: str = None):
    await ctx.defer()
    uid = ctx.author.id
    chosen = (mode or bot.current_image_mode).lower()
    status = await ctx.send("🔥 Checking...")
    try:
        safe, reason = await bot.is_prompt_safe(prompt, uid=uid)
        if not safe:
            return await status.edit(content=f"🚫 {reason}")
        await status.edit(content=f"🔥 Generating **{chosen}**...")
        if chosen in ("hf", "huggingface"):
            img = await bot.generate_hf_image(prompt, uid=uid)
            label = "🤗 HF"
        elif chosen in ("pollinations", "poll", "fast"):
            img = await bot.generate_pollinations_image(prompt)
            label = "⚡ Pollinations"
        else:
            img = await bot.generate_gemini_image(prompt, uid=uid)
            label = "🧠 Gemini"
        url = await bot.upload_image_to_hosting(img, uid=uid)
        emb = discord.Embed(title="🖼️", description=f"**{label}**", color=C_PRIMARY)
        emb.set_image(url=url)
        emb.add_field(name="Prompt", value=prompt[:1024], inline=False)
        await status.edit(content=None, embed=emb)
    except Exception as e:
        await status.edit(content=f"❌ `{str(e)[:180]}`")


@bot.hybrid_command(name="rendermode", description="🖼️ Image mode")
async def rendermode_cmd(ctx, mode: str = None):
    if mode is None:
        emb = discord.Embed(title="🖼️ Image Mode", color=C_PRIMARY)
        emb.add_field(name="Current", value=f"`{bot.current_image_mode}`", inline=False)
        emb.add_field(name="Options", value="• `smart` Gemini\n• `fast` Pollinations\n• `hf` Hugging Face", inline=False)
        return await ctx.send(embed=emb)
    if mode.lower() not in ("smart", "fast", "hf"):
        return await ctx.send("❌ smart / fast / hf")
    bot.current_image_mode = mode.lower()
    await ctx.send(f"✅ → **{mode}**")


@bot.hybrid_command(name="video", description="🎬 Generate a video")
async def video_cmd(ctx, prompt: str):
    await ctx.defer()
    status = await ctx.send(f"🎬 **{prompt}**...")
    bot.loop.create_task(bot.generate_video(prompt, ctx.author.id, status))


@bot.hybrid_command(name="music", description="🎵 Generate music")
async def music_cmd(ctx, prompt: str):
    await ctx.defer()
    status = await ctx.send(f"🎵 **{prompt}**...")
    bot.loop.create_task(bot.generate_music(prompt, ctx.author.id, status))


@bot.hybrid_command(name="debate", description="🤖 Start/stop AI debate")
async def debate_cmd(ctx, description: str = None):
    uid = ctx.author.id
    if uid in bot.ai_chat_sessions:
        s = bot.ai_chat_sessions.pop(uid, None)
        t = s.get("task") if s else None
        if t and not t.done():
            t.cancel()
        return await ctx.send("🛑 Stopped.")
    if not description:
        return await ctx.send("❌ Give a topic.")
    s = {"description": description, "history": [], "turn": 0,
         "channel_id": ctx.channel.id, "task": None}
    bot.ai_chat_sessions[uid] = s
    s["task"] = asyncio.create_task(bot.run_ai_chat(uid))
    await ctx.send(f"🔥 **{description}**")


# ============================================================
# MEMORY / MISC
# ============================================================
@bot.hybrid_command(name="sm", description="Toggle memory")
async def sm(ctx):
    bot.memory_enabled = not bot.memory_enabled
    await ctx.send(f"🧠 {'ON' if bot.memory_enabled else 'OFF'}")


@bot.hybrid_command(name="persistent", description="Enable persistent memory")
async def persistent_enable(ctx):
    bot.set_persistent_enabled(ctx.author.id, True)
    await ctx.send("✅ Persistent ON")


@bot.hybrid_command(name="persistentdisable", description="Disable persistent memory")
async def persistent_disable(ctx):
    bot.set_persistent_enabled(ctx.author.id, False)
    await ctx.send("🚫 Persistent OFF")


@bot.hybrid_command(name="pen", description="📜 Pen archive")
async def pen_cmd(ctx):
    s = bot.pen_archive[:1000] if bot.pen_archive else "Not loaded"
    await ctx.send(f"📜\n```\n{s}\n```")


# ============================================================
# COURT
# ============================================================
class CourtRoleView(discord.ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=120)
        self.bot = bot_instance

    async def select_role(self, interaction, role_key):
        self.bot.court_sessions[interaction.user.id] = {"role": role_key, "case": "", "participants": {}}
        await interaction.response.edit_message(
            content=f"✅ **{role_key.capitalize()}**. Use `/explain-case`, `/role`, `/start-court`.",
            view=None)

    @discord.ui.button(label="Judge", style=discord.ButtonStyle.primary)
    async def j(self, i, b): await self.select_role(i, "judge")
    @discord.ui.button(label="Prosecutor", style=discord.ButtonStyle.danger)
    async def p(self, i, b): await self.select_role(i, "prosecutor")
    @discord.ui.button(label="Defense", style=discord.ButtonStyle.success)
    async def d(self, i, b): await self.select_role(i, "defense")
    @discord.ui.button(label="Witness", style=discord.ButtonStyle.secondary)
    async def w(self, i, b): await self.select_role(i, "witness")
    @discord.ui.button(label="Jury", style=discord.ButtonStyle.secondary)
    async def y(self, i, b): await self.select_role(i, "jury")
    @discord.ui.button(label="Stenographer", style=discord.ButtonStyle.secondary)
    async def s(self, i, b): await self.select_role(i, "stenographer")


@bot.hybrid_command(name="court", description="🏛️ Court session")
async def court_cmd(ctx):
    await ctx.send("🏛️ Pick role:", view=CourtRoleView(bot))


@bot.hybrid_command(name="role", description="🏛️ Assign role")
async def role_cmd(ctx, user: discord.User, role: str):
    if ctx.author.id not in bot.court_sessions:
        return await ctx.send("❌ `/court` first.")
    valid = ["prosecutor", "defense", "witness", "jury", "stenographer", "judge"]
    if role.lower() not in valid:
        return await ctx.send(f"❌ {', '.join(valid)}")
    bot.court_sessions[ctx.author.id]["participants"][role.lower()] = user.id
    await ctx.send(f"✅ {user.mention} → **{role}**")


@bot.hybrid_command(name="explain-case", description="🏛️ Add case")
async def explain_case(ctx, case: str):
    if ctx.author.id not in bot.court_sessions:
        return await ctx.send("❌ `/court` first.")
    bot.court_sessions[ctx.author.id]["case"] = case
    await ctx.send("✅ `/start-court`")


@bot.hybrid_command(name="start-court", description="🏛️ Start")
async def start_court(ctx):
    if ctx.author.id not in bot.court_sessions:
        return await ctx.send("❌ `/court` first.")
    s = bot.court_sessions[ctx.author.id]
    if not s.get("case"):
        return await ctx.send("❌ `/explain-case` first.")
    p = s.get("participants", {})
    if p:
        out = "🏛️ **In session!**\n"
        for r, uid in p.items():
            u = ctx.guild.get_member(uid) if ctx.guild else bot.get_user(uid)
            out += f"**{r.capitalize()}**: {u.mention if u else f'<@{uid}>'}\n"
        await ctx.send(out)
    await ctx.send("Begin.")


@bot.hybrid_command(name="endcourt", description="🏛️ End")
async def endcourt_cmd(ctx):
    if ctx.author.id in bot.court_sessions:
        del bot.court_sessions[ctx.author.id]
        await ctx.send("🏛️ Ended.")


# ============================================================
# UMF
# ============================================================
DEFAULT_RECOGNIZED_NATIONS = ["United Mafia Federation"]


class UMFData:
    def __init__(self, filepath="umf_data.json"):
        self.filepath = filepath
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    return json.load(f)
            except Exception:
                return self._default()
        return self._default()

    def _default(self):
        return {"recognized_nations": DEFAULT_RECOGNIZED_NATIONS.copy(),
                "pending_requests": [], "approved_requests": [],
                "denied_requests": [], "recognition_history": []}

    def save(self):
        with open(self.filepath, 'w') as f:
            json.dump(self.data, f, indent=4)

    def get_recognized_nations(self): return self.data.get("recognized_nations", [])

    def add_recognized_nation(self, n):
        ns = self.get_recognized_nations()
        if n not in ns:
            ns.append(n); self.data["recognized_nations"] = ns; self.save(); return True
        return False

    def add_pending_request(self, uid, nation, username):
        req = {"user_id": uid, "username": username, "nation": nation,
               "timestamp": datetime.now().isoformat(), "status": "pending"}
        self.data["pending_requests"].append(req); self.save(); return req

    def get_pending_requests(self): return self.data.get("pending_requests", [])

    def approve_request(self, uid):
        for i, r in enumerate(self.data.get("pending_requests", [])):
            if r["user_id"] == uid and r["status"] == "pending":
                r["status"] = "approved"
                r["approved_at"] = datetime.now().isoformat()
                self.data["approved_requests"].append(r)
                self.data["pending_requests"].pop(i); self.save(); return r
        return None

    def deny_request(self, uid, reason=""):
        for i, r in enumerate(self.data.get("pending_requests", [])):
            if r["user_id"] == uid and r["status"] == "pending":
                r["status"] = "denied"
                r["denied_reason"] = reason
                r["denied_at"] = datetime.now().isoformat()
                self.data["denied_requests"].append(r)
                self.data["pending_requests"].pop(i); self.save(); return r
        return None

    def get_request_status(self, uid):
        for b in ("pending_requests", "approved_requests", "denied_requests"):
            for r in self.data.get(b, []):
                if r["user_id"] == uid:
                    return r
        return None

    def is_nation_recognized(self, n): return n in self.get_recognized_nations()

    def add_to_history(self, action, uid, username, nation, details=""):
        self.data["recognition_history"].append({
            "action": action, "user_id": uid, "username": username,
            "nation": nation, "timestamp": datetime.now().isoformat(), "details": details})
        self.save()


bot.umf_data = UMFData()


class UMFRecognitionModal(discord.ui.Modal, title="🌍 UMF Recognition"):
    nation_name = discord.ui.TextInput(label="Nation Name", required=True, max_length=100)
    additional = discord.ui.TextInput(label="Additional Info", required=False, max_length=500,
                                      style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction):
        nation = self.nation_name.value.strip()
        if bot.umf_data.is_nation_recognized(nation):
            return await interaction.response.send_message("⚠️ Already recognized.", ephemeral=True)
        existing = bot.umf_data.get_request_status(interaction.user.id)
        if existing and existing.get("status") == "pending":
            return await interaction.response.send_message("⏳ Already pending.", ephemeral=True)
        bot.umf_data.add_pending_request(interaction.user.id, nation, interaction.user.display_name)
        emb = discord.Embed(title="✅ Submitted", description=f"**{nation}** pending.", color=C_OK)
        await interaction.response.send_message(embed=emb, ephemeral=True)


class UMFDenyModal(discord.ui.Modal, title="❌ Deny"):
    reason = discord.ui.TextInput(label="Reason", required=True, max_length=200,
                                  style=discord.TextStyle.paragraph)

    def __init__(self, req, user):
        super().__init__()
        self.req = req
        self.user = user

    async def on_submit(self, interaction):
        bot.umf_data.deny_request(self.req["user_id"], self.reason.value.strip())
        await interaction.response.edit_message(content="❌ Denied.", view=None)


class UMFPrimaryView(discord.ui.View):
    def __init__(self): super().__init__(timeout=300)

    @discord.ui.button(label="📝 Request Recognition", style=discord.ButtonStyle.primary, emoji="🌍")
    async def request_btn(self, interaction, button):
        await interaction.response.send_modal(UMFRecognitionModal())

    @discord.ui.button(label="📋 View Nations", style=discord.ButtonStyle.secondary, emoji="📋")
    async def list_btn(self, interaction, button):
        nations = bot.umf_data.get_recognized_nations()
        emb = discord.Embed(title="🌍 Recognized Nations",
                            description="\n".join(f"• {n}" for n in nations[:25]) or "None.",
                            color=C_ACCENT)
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(label="ℹ️ My Status", style=discord.ButtonStyle.secondary, emoji="ℹ️")
    async def status_btn(self, interaction, button):
        req = bot.umf_data.get_request_status(interaction.user.id)
        if req:
            emb = discord.Embed(title=req["status"].upper(),
                                description=f"**{req.get('nation','')}**", color=C_PRIMARY)
        else:
            emb = discord.Embed(title="No Request", description="No active request.", color=C_DEEP)
        await interaction.response.send_message(embed=emb, ephemeral=True)


class UMFAdminView(discord.ui.View):
    def __init__(self, req, user):
        super().__init__(timeout=120)
        self.req = req
        self.user = user

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve_btn(self, interaction, button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        approved = bot.umf_data.approve_request(self.req["user_id"])
        if not approved:
            return await interaction.response.edit_message(content="Processed.", view=None)
        bot.umf_data.add_recognized_nation(approved["nation"])
        await interaction.response.edit_message(
            content=f"✅ **{approved['nation']}** recognized.", view=None)

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny_btn(self, interaction, button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        await interaction.response.send_modal(UMFDenyModal(self.req, self.user))


@bot.hybrid_command(name="umf", description="🌍 UMF")
async def umf_command(ctx):
    emb = discord.Embed(title="🌍 UMF Recognition",
                        description="Request recognition from the United Military Federation.",
                        color=C_PRIMARY)
    await ctx.send(embed=emb, view=UMFPrimaryView())


@bot.hybrid_command(name="umf_list", description="📋 Recognized")
async def umf_list(ctx):
    nations = bot.umf_data.get_recognized_nations()
    emb = discord.Embed(title="🌍 Recognized Nations",
                        description="\n".join(f"• {n}" for n in nations[:25]) or "None.",
                        color=C_ACCENT)
    await ctx.send(embed=emb)


@bot.hybrid_command(name="umf_status", description="ℹ️ Your status")
async def umf_status(ctx):
    req = bot.umf_data.get_request_status(ctx.author.id)
    if req:
        emb = discord.Embed(title=req["status"].upper(),
                            description=f"**{req.get('nation','')}**", color=C_PRIMARY)
    else:
        emb = discord.Embed(title="No Request", description="No active request.", color=C_DEEP)
    await ctx.send(embed=emb, ephemeral=True)


@bot.hybrid_command(name="umf_admin", description="🔧 Admin")
async def umf_admin(ctx):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("⛔ Admin only.", ephemeral=True)
    pending = bot.umf_data.get_pending_requests()
    if not pending:
        return await ctx.send("📭 None pending.", ephemeral=True)
    req = pending[0]
    user = ctx.guild.get_member(req["user_id"]) or await ctx.guild.fetch_member(req["user_id"])
    emb = discord.Embed(title="📋 Pending", color=C_WARM)
    emb.add_field(name="Applicant", value=user.mention if user else f"<@{req['user_id']}>", inline=True)
    emb.add_field(name="Nation", value=req["nation"], inline=True)
    await ctx.send(embed=emb, view=UMFAdminView(req, user), ephemeral=True)


# ============================================================
# ON MESSAGE
# ============================================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    content = message.content or ""
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = (
        bot.user in message.mentions
        or f"<@{bot.user.id}>" in content
        or f"<@!{bot.user.id}>" in content
        or is_dm
    )
    if not is_mentioned:
        await bot.process_commands(message)
        return

    reply_context = None
    reply_msg = None
    if message.reference:
        resolved = message.reference.resolved
        if resolved is None:
            try:
                resolved = await message.channel.fetch_message(message.reference.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                resolved = None
        if isinstance(resolved, discord.Message) and resolved.author.id != bot.user.id:
            reply_context = {
                "author": resolved.author.display_name,
                "content": (resolved.content or "[no text]")[:800],
                "author_id": resolved.author.id,
            }
            reply_msg = resolved

    images = await fetch_images_from_message(message)
    if not images and reply_msg is not None:
        images = await fetch_images_from_message(reply_msg)

    now = time.time()
    if now - bot.user_cooldowns.get(message.author.id, 0) < USER_COOLDOWN_SECONDS:
        return
    bot.user_cooldowns[message.author.id] = now

    clean = re.sub(r'<@!?{}>\s*'.format(bot.user.id), '', content).strip()
    if not clean and reply_context:
        clean = "what do you think of this?"
    if not clean and images:
        clean = "what's in this image?"
    if not clean:
        return

    await bot.process_user_message(
        message.author, clean, message.channel,
        reply_context=reply_context, trigger_msg=message, images=images)


# ============================================================
# WEB SERVER
# ============================================================
async def handle_root(request):
    return web.Response(text="🔥 Mac v20.0 - Better then Sodium")


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
    logger.info(f"🌐 Web on :{port}")


async def main():
    await run_web_server()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
