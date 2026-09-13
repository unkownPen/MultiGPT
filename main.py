# main.py — Mac v9.1 (slim + slots + natural search)
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
from datetime import datetime, timedelta
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
# CONFIG
# ----------------------------------------------------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable not set!")

GROQ_API_KEYS = [k for k in [os.getenv("GROQ_API_KEY"), os.getenv("GROQ_API_KEY2")] if k]
GROQ_MODELS = [
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-safeguard-20b",
]
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_IMAGE_API_KEY = os.getenv("GEMINI_IMAGE_API_KEY") or GEMINI_API_KEY
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set!")
GEMINI_MODELS = ["gemini-3.1-flash-lite", "gemini-3-flash-preview"]
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"

HF_TOKENS = [t for t in [os.getenv("HF_TOKEN"), os.getenv("HF_TOKEN2")] if t]
HF_IMAGE_MODELS = [
    "stabilityai/stable-diffusion-xl-base-1.0",
    "krea/Krea-2-Turbo",
    "black-forest-labs/FLUX.1-dev",
    "Tongyi-MAI/Z-Image",
    "Tongyi-MAI/Z-Image-Turbo",
    "Qwen/Qwen-Image",
    "black-forest-labs/FLUX.1-schnell",
]
HF_IMAGE_MODEL = os.getenv("HF_IMAGE_MODEL", HF_IMAGE_MODELS[0])
HF_SAFETY_MODEL = os.getenv("HF_SAFETY_MODEL", "eliasalbouzidi/distilbert-nsfw-text-classifier")
HF_SAFETY_THRESHOLD = float(os.getenv("HF_SAFETY_THRESHOLD", "0.5"))

SILICONFLOW_API_KEYS = []
_i = 0
while True:
    k = os.getenv(f"SILICONFLOW_API_KEY{'' if _i == 0 else _i+1}")
    if k:
        SILICONFLOW_API_KEYS.append(k)
        _i += 1
    else:
        break

IMGBB_API_KEY        = os.getenv("HF_IMAGES")
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY")
OPENROUTER_API_KEY   = os.getenv("OPENROUTER_API_KEY") or ""
OPENROUTER_API_URL   = "https://openrouter.ai/api/v1/chat/completions"
TENOR_API_KEY        = os.getenv("TENOR_API_KEY")

FISH_AUDIO_API_KEY = os.getenv("FISH_AUDIO_API_KEY")
FISH_AUDIO_URL = "https://api.fish.audio/v1/tts"
FISH_AUDIO_MODEL = "s2.1-pro-free"

VOICE_MODES: Dict[str, Dict[str, str]] = {
    "verity":      {"id": "711cf3ed00ab441a8f54a45058047b7a", "emoji": "🎙️", "desc": "Verity (default)"},
    "jarvis":      {"id": "612b878b113047d9a770c069c8b4fdfe", "emoji": "🤖", "desc": "Jarvis"},
    "idksterling": {"id": "68c6487d1bf04ee4aeb6400b068b8c5c", "emoji": "🎭", "desc": "IdkSterling"},
    "fem":         {"id": "5233336f5f44460ea0902b0802375451", "emoji": "👩", "desc": "Female"},
}
DEFAULT_VOICE = "verity"

PIPELINE_GENERATOR_MODEL = "deepseek/deepseek-r1-zero:free"

POLLINATIONS_AUDIO_URL = "https://gen.pollinations.ai/audio"
HF_INFERENCE_URL = "https://router.huggingface.co/hf-inference/models"

MAX_MEMORY = 50
TZ_UAE = ZoneInfo("Asia/Dubai")
USER_COOLDOWN_SECONDS = 2
DATA_FILE = "data.json"
SNIPPETS_FILE = "snippets.json"
SLOTS_FILE = "slots.json"

DISCORD_LIMIT = 2000
CHUNK_SIZE = 1950

DEFAULT_MODE = "chill"


# ----------------------------------------------------------------------
# PERSISTENCE
# ----------------------------------------------------------------------
def _safe_json_load(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            c = f.read().strip()
            if not c:
                return default
            return json.loads(c)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Load failed {path}: {e}")
        return default


def _safe_json_save(path: str, data: Any) -> None:
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logger.error(f"Save failed {path}: {e}")


def load_persistent_data() -> dict:
    d = _safe_json_load(DATA_FILE, {"enabled": {}, "memory": {}})
    if not os.path.exists(DATA_FILE):
        _safe_json_save(DATA_FILE, d)
    return d


def save_persistent_data(data: dict) -> None:
    _safe_json_save(DATA_FILE, data)


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


# ----------------------------------------------------------------------
# WEB SEARCH
# ----------------------------------------------------------------------
_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/122.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}


async def _search_ddg_lite(query: str) -> List[str]:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query},
                headers={**_BROWSER_HEADERS, "Content-Type": "application/x-www-form-urlencoded",
                         "Referer": "https://lite.duckduckgo.com/"},
                timeout=aiohttp.ClientTimeout(total=12),
                allow_redirects=True,
            ) as r:
                if r.status != 200:
                    return []
                html = await r.text()
        soup = BeautifulSoup(html, "html.parser")
        out = []
        links = soup.find_all("a", class_="result-link")
        if not links:
            links = [a for a in soup.find_all("a", href=True) if a["href"].startswith("http")]
        for a in links:
            href = a.get("href", "")
            title = a.get_text(strip=True)
            if title and href.startswith("http") and "duckduckgo.com" not in href:
                out.append(f"• {title}\n  {href}")
            if len(out) >= 6:
                break
        return out
    except Exception as e:
        logger.warning(f"DDG-lite failed: {e}")
        return []


async def _search_ddg_html(query: str) -> List[str]:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}",
                headers=_BROWSER_HEADERS,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as r:
                if r.status != 200:
                    return []
                html = await r.text()
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for a in soup.find_all("a", class_="result__a", limit=6):
            href = a.get("href", "")
            if href.startswith("//duckduckgo.com/l/?uddg="):
                try:
                    href = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
                except Exception:
                    pass
            title = a.get_text(strip=True)
            if title and href:
                out.append(f"• {title}\n  {href}")
        return out
    except Exception as e:
        logger.warning(f"DDG-html failed: {e}")
        return []


async def _search_wikipedia(query: str) -> List[str]:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": query, "limit": 4, "format": "json"},
                headers=_BROWSER_HEADERS,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status != 200:
                    return []
                data = await r.json()
        if len(data) >= 4 and data[1]:
            return [f"• {t} — {d or 'no summary'}\n  {u}"
                    for t, d, u in zip(data[1], data[2], data[3])]
        return []
    except Exception as e:
        logger.warning(f"Wiki failed: {e}")
        return []


async def perform_web_search(query: str) -> str:
    for fn in (_search_ddg_lite, _search_ddg_html, _search_wikipedia):
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
            intents=intents,
            help_command=None,
            activity=discord.Activity(type=discord.ActivityType.playing, name="with fire 🔥")
        )
        self.memory_enabled = True
        self.saved_memory: List[Tuple[str, str]] = []

        # 5 per-user slots: {user_id: {"sv1": [(role, content)], ...}}
        self.user_slots: Dict[int, Dict[str, List[Tuple[str, str]]]] = {}
        self.active_slot: Dict[int, str] = {}  # user_id -> "sv1".."sv5"
        self._load_slots()

        self.current_gemini_model: str = DEFAULT_GEMINI_MODEL
        self.current_llm: str = GROQ_MODELS[0]
        self.current_model_list = GROQ_MODELS.copy()
        self.current_model_index = 0
        self.groq_key_index = 0
        self.model_cooldowns: Dict[str, float] = {}

        self.current_image_mode = "smart"
        self.current_hf_model = HF_IMAGE_MODEL
        self.current_voice = DEFAULT_VOICE
        self.complex_mode = True

        self.hf_key_index = 0
        self.siliconflow_key_index = 0

        self.video_jobs: Dict[int, discord.Message] = {}
        self.music_jobs: Dict[int, discord.Message] = {}

        self.pen_archive: str = ""

        # Single default persona — no more mode-switching commands
        self.mode_prompts: Dict[str, str] = {
            "chill": (
                "You are Mac — hype, chill, Gen-Z energy. Talk like you're on Discord "
                "with the boys. Use emojis naturally but not in every word (😭🔥💀📈). "
                "Be casual, funny, reactive. When the user says something weak, drop a "
                "short aura roast. When they say something cool, hype them up. Keep "
                "replies short and full of energy. Don't be formal. Only mention Pen "
                "lore if directly asked."
            )
        }
        self.current_mode = DEFAULT_MODE

        self.allowed_llms: Dict[str, str] = {
            "qwen-coder": "qwen/qwen3.6-27b",
            "gpt-oss-120b": "openai/gpt-oss-120b",
            "gpt-oss-20b": "openai/gpt-oss-20b",
            "gpt-oss-safeguard": "openai/gpt-oss-safeguard-20b",
        }

        self.persistent_enabled: Dict[int, bool] = {}
        self.persistent_memory: Dict[int, List[Tuple[str, str]]] = {}
        self._load_persistent_memory()

        self.ai_chat_sessions: Dict[int, dict] = {}
        self.ai_chat_max_turns = 16

        self.snippets: Dict[int, Dict[str, dict]] = defaultdict(dict)
        self._load_snippets()

        # Court
        self.court_sessions: Dict[int, Dict] = {}
        self.court_roles: Dict[str, str] = {
            "judge": ("You are the Honorable Judge. Case:\n{case}\nParticipants:\n{participants}\n"
                      "Stay in character. Never mention you are an AI."),
            "prosecutor": ("You are the Prosecutor. Case:\n{case}\nParticipants:\n{participants}\n"
                           "Stay in character. Never mention you are an AI."),
            "defense": ("You are the Defense Attorney. Case:\n{case}\nParticipants:\n{participants}\n"
                        "Stay in character. Never mention you are an AI."),
            "witness": ("You are a Witness. Case:\n{case}\nParticipants:\n{participants}\n"
                        "Stay in character. Never mention you are an AI."),
            "jury": ("You are on the Jury. Case:\n{case}\nParticipants:\n{participants}\n"
                     "Stay in character. Never mention you are an AI."),
            "stenographer": ("You are the Court Stenographer. Case:\n{case}\nParticipants:\n{participants}\n"
                             "Stay in character."),
        }

    # ---------------- persistent memory ----------------
    def _load_persistent_memory(self):
        data = load_persistent_data()
        self.persistent_enabled = {int(k): v for k, v in data.get("enabled", {}).items()}
        raw = data.get("memory", {})
        self.persistent_memory = {}
        for uid_s, msgs in raw.items():
            uid = int(uid_s)
            if isinstance(msgs, list):
                self.persistent_memory[uid] = [
                    (m.get("role"), m.get("content")) for m in msgs if isinstance(m, dict)
                ]

    def _save_persistent_memory(self):
        save_persistent_data({
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
        if len(self.persistent_memory[uid]) > 100:
            self.persistent_memory[uid] = self.persistent_memory[uid][-100:]
        self._save_persistent_memory()
    def clear_persistent_memory(self, uid):
        self.persistent_memory.pop(uid, None)
        self.persistent_enabled.pop(uid, None)
        self._save_persistent_memory()
    def reset_all_persistent_memory(self):
        self.persistent_enabled = {}
        self.persistent_memory = {}
        self._save_persistent_memory()

    # ---------------- 5-chat slots ----------------
    def _load_slots(self):
        raw = _safe_json_load(SLOTS_FILE, {})
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
        _safe_json_save(SLOTS_FILE, out)

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
        if len(slot) > 200:
            self.user_slots[uid][name] = slot[-200:]
        self._save_slots()

    # ---------------- snippets ----------------
    def _load_snippets(self):
        raw = _safe_json_load(SNIPPETS_FILE, {})
        self.snippets = defaultdict(dict)
        for uid_s, d in raw.items():
            try:
                self.snippets[int(uid_s)] = d
            except ValueError:
                pass

    def _save_snippets(self):
        _safe_json_save(SNIPPETS_FILE, {str(u): d for u, d in self.snippets.items()})

    # ---------------- archive ----------------
    async def load_pen_archive_async(self):
        url = "https://raw.githubusercontent.com/unkownPen/MultiGPT/refs/heads/main/archives.txt"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        self.pen_archive = await r.text()
                        logger.info("Pen archive loaded")
        except Exception as e:
            logger.warning(f"Pen archive failed: {e}")

    # ---------------- Groq rotation ----------------
    def get_next_available_model(self) -> str:
        now = time.time()
        cur = self.current_model_list[self.current_model_index]
        if self.model_cooldowns.get(cur, 0) <= now:
            return cur
        for i in range(1, len(self.current_model_list) + 1):
            nxt = (self.current_model_index + i) % len(self.current_model_list)
            m = self.current_model_list[nxt]
            if self.model_cooldowns.get(m, 0) <= now:
                self.current_model_index = nxt
                return m
        return self.current_model_list[0]

    def rotate_groq_key(self):
        self.groq_key_index = (self.groq_key_index + 1) % max(1, len(GROQ_API_KEYS))

    # ---------------- Gemini (primary) ----------------
    def _gemini_call_sync(self, messages, model, temperature, max_tokens):
        client = genai.Client(api_key=GEMINI_API_KEY)
        sys_text = None
        contents = []
        for m in messages:
            if m["role"] == "system":
                sys_text = m["content"]
                continue
            role = "user" if m["role"] == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
        if not contents:
            contents = [types.Content(role="user", parts=[types.Part.from_text(text="")])]
        cfg_kwargs = {"temperature": temperature, "max_output_tokens": max_tokens}
        if sys_text:
            cfg_kwargs["system_instruction"] = sys_text
        cfg = types.GenerateContentConfig(**cfg_kwargs)
        resp = client.models.generate_content(model=model, contents=contents, config=cfg)
        if resp.candidates and resp.candidates[0].content.parts:
            return (resp.candidates[0].content.parts[0].text or "").strip()
        try:
            return (resp.text or "").strip()
        except Exception:
            return ""

    async def gemini_chat(self, messages, temperature: float = 0.8, max_tokens: int = 2048) -> str:
        return await asyncio.to_thread(
            self._gemini_call_sync, messages,
            self.current_gemini_model, temperature, max_tokens,
        )

    # ---------------- Groq fallback ----------------
    async def groq_chat(self, messages, temperature: float = 0.8, max_tokens: int = 2048,
                        model: Optional[str] = None) -> str:
        if not GROQ_API_KEYS:
            raise Exception("No Groq keys configured")
        target_model = model or self.get_next_available_model()
        last_err = None
        for _ in range(len(GROQ_API_KEYS) + 2):
            key = GROQ_API_KEYS[self.groq_key_index]
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            payload = {"model": target_model, "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens,
                       "tool_choice": "none"}
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(GROQ_API_URL, json=payload, headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=90)) as r:
                        if r.status == 200:
                            d = await r.json()
                            return d["choices"][0]["message"]["content"]
                        if r.status == 429:
                            self.rotate_groq_key()
                            await asyncio.sleep(1)
                            continue
                        body = await r.text()
                        raise Exception(f"Groq {r.status}: {body[:200]}")
            except Exception as e:
                last_err = e
                self.rotate_groq_key()
                await asyncio.sleep(1)
        raise Exception(f"All Groq attempts failed: {last_err}")

    # ---------------- unified chat ----------------
    def _build_messages(self, prompt, user_id, system_prompt, slot_name):
        messages = []
        if user_id and self.get_persistent_enabled(user_id):
            for role, content in self.get_persistent_memory(user_id):
                messages.append({"role": role, "content": content})
        slot_history = self.get_slot(user_id, slot_name) if user_id else []
        for role, content in slot_history[-40:]:
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": prompt})

        date = datetime.now(TZ_UAE).strftime("%Y-%m-%d")
        if system_prompt:
            sys_msg = system_prompt
        else:
            mp = self.mode_prompts.get(self.current_mode, self.mode_prompts[DEFAULT_MODE])
            arch = self.pen_archive[:500] + "..." if len(self.pen_archive) > 500 else self.pen_archive
            sys_msg = f"Today (UAE): {date}. {mp}\n\nPen Archive (only if asked): {arch}"
        return [{"role": "system", "content": sys_msg}] + messages

    async def chat_call(self, prompt, user_id=None, system_prompt=None,
                        slot_name="sv1", max_tokens=2048) -> str:
        messages = self._build_messages(prompt, user_id, system_prompt, slot_name)
        try:
            return await self.gemini_chat(messages, temperature=0.85, max_tokens=max_tokens)
        except Exception as e:
            logger.warning(f"Gemini failed ({e}); falling back to Groq")
            try:
                return await self.groq_chat(messages, temperature=0.85, max_tokens=max_tokens)
            except Exception as e2:
                return f"❌ All models failed. Gemini: {str(e)[:120]} | Groq: {str(e2)[:120]}"

    async def chat_call_with_search(self, prompt, user_id=None, system_prompt=None,
                                    slot_name="sv1") -> str:
        results = await perform_web_search(prompt)
        if results.startswith("No results") or results.startswith("Search"):
            return await self.chat_call(prompt, user_id, system_prompt, slot_name)
        augmented = (
            f"Web search results for: {prompt}\n\n{results}\n\n---\n\n"
            f"Answer using these results. Cite inline like [1], [2] where relevant. "
            f"If results are irrelevant, say so and answer from your own knowledge.\n\n"
            f"Question: {prompt}"
        )
        return await self.chat_call(augmented, user_id, system_prompt, slot_name)

    async def ai_call(self, prompt, user_id=None, system_prompt=None,
                      slot_name="sv1", web_search=False) -> str:
        if web_search:
            return await self.chat_call_with_search(prompt, user_id, system_prompt, slot_name)
        return await self.chat_call(prompt, user_id, system_prompt, slot_name)

    # ---------------- OpenRouter (DeepSeek) ----------------
    async def openrouter_call(self, messages, model, temperature=0.6, max_tokens=4096) -> str:
        if not OPENROUTER_API_KEY:
            raise Exception("OPENROUTER_API_KEY not set — DeepSeek unavailable")
        payload = {"model": model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens}
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://discord.com",
            "X-Title": "Mac",
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(OPENROUTER_API_URL, json=payload, headers=headers,
                              timeout=aiohttp.ClientTimeout(total=180)) as r:
                if r.status == 200:
                    d = await r.json()
                    choice = d.get("choices", [{}])[0].get("message", {})
                    return choice.get("content") or choice.get("reasoning") or ""
                body = await r.text()
                raise Exception(f"OpenRouter {r.status}: {body[:200]}")

    # ---------------- safety ----------------
    async def is_prompt_safe(self, prompt: str) -> Tuple[bool, str]:
        if not HF_TOKENS:
            return False, "Safety checker unavailable (no HF token)"
        clean = prompt.strip()
        if not clean:
            return False, "Empty prompt"
        api_url = f"{HF_INFERENCE_URL}/{HF_SAFETY_MODEL}"
        headers = {"Authorization": f"Bearer {HF_TOKENS[self.hf_key_index]}",
                   "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(api_url, headers=headers, json={"inputs": clean[:1500]},
                                  timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status != 200:
                        return False, f"Safety checker error ({r.status})"
                    data = await r.json()
            results = data
            if isinstance(results, list) and results and isinstance(results[0], list):
                results = results[0]
            if not isinstance(results, list) or not results:
                return False, "Safety checker returned unexpected data"
            top = max(results, key=lambda x: x.get("score", 0))
            label = str(top.get("label", "")).upper()
            score = float(top.get("score", 0))
            if "NSFW" in label and score >= HF_SAFETY_THRESHOLD:
                return False, f"flagged as NSFW ({score:.0%} confidence)"
            return True, "safe"
        except asyncio.TimeoutError:
            return False, "Safety checker timed out"
        except Exception as e:
            return False, f"Safety checker error: {str(e)[:120]}"

    # ---------------- image ----------------
    async def generate_pollinations_image(self, prompt: str) -> bytes:
        url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt)
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status == 200:
                    return await r.read()
                raise Exception(f"Pollinations error {r.status}")

    async def generate_gemini_image(self, prompt: str) -> bytes:
        try:
            return await asyncio.to_thread(self._generate_gemini_image_sync, prompt,
                                           "imagen-3.0-generate-002")
        except Exception as e:
            logger.error(f"Gemini image failed: {e}")
            return await self.generate_pollinations_image(prompt)

    def _generate_gemini_image_sync(self, prompt: str, model_id: str) -> bytes:
        client = genai.Client(api_key=GEMINI_IMAGE_API_KEY)
        resp = client.models.generate_images(
            model=model_id, prompt=prompt,
            config=types.GenerateImagesConfig(number_of_images=1),
        )
        return resp.generated_images[0].image.image_bytes

    async def generate_hf_image(self, prompt: str) -> bytes:
        if not HF_TOKENS:
            raise Exception("No HF_TOKEN set")
        models_to_try = [self.current_hf_model] + [m for m in HF_IMAGE_MODELS if m != self.current_hf_model]
        last_error = None
        for model_id in models_to_try:
            api_url = f"{HF_INFERENCE_URL}/{model_id}"
            headers = {"Authorization": f"Bearer {HF_TOKENS[self.hf_key_index]}",
                       "Content-Type": "application/json"}
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(api_url, headers=headers, json={"inputs": prompt},
                                      timeout=aiohttp.ClientTimeout(total=45)) as resp:
                        ct = resp.headers.get("Content-Type", "")
                        if resp.status == 200 and ct.startswith("image/"):
                            data = await resp.read()
                            if len(data) < 500:
                                last_error = f"{model_id}: tiny image"
                                continue
                            self.current_hf_model = model_id
                            return data
                        body = await resp.text()
                        last_error = f"{model_id}: {resp.status} {body[:100]}"
                        if resp.status in (401, 403):
                            raise Exception(f"HF auth error {resp.status}")
                        continue
            except asyncio.TimeoutError:
                last_error = f"{model_id}: timeout"
                continue
            except Exception as e:
                last_error = f"{model_id}: {e}"
                continue
        raise Exception(f"All HF models failed: {last_error}")

    async def upload_image_to_hosting(self, image_data: bytes) -> str:
        if not IMGBB_API_KEY:
            raise Exception("No image hosting key (HF_IMAGES)")
        form = aiohttp.FormData()
        form.add_field('image', image_data, filename='image.png', content_type='image/png')
        async with aiohttp.ClientSession() as s:
            async with s.post(f'https://api.imgbb.com/1/upload?key={IMGBB_API_KEY}',
                              data=form, timeout=aiohttp.ClientTimeout(total=30)) as r:
                data = await r.json()
                if data.get('success'):
                    return data['data']['url']
                raise Exception("Upload failed")

    # ---------------- TTS ----------------
    async def generate_voice(self, text: str, voice_key: str = DEFAULT_VOICE, fmt: str = "opus") -> bytes:
        if not FISH_AUDIO_API_KEY:
            raise Exception("FISH_AUDIO_API_KEY not set")
        voice_key = (voice_key or DEFAULT_VOICE).lower().strip()
        if voice_key not in VOICE_MODES:
            voice_key = DEFAULT_VOICE
        ref_id = VOICE_MODES[voice_key]["id"]
        text = strip_for_tts(text) or "I've got nothing."
        if len(text) > 1500:
            text = text[:1500]
        payload = {"text": text, "reference_id": ref_id, "format": fmt,
                   "latency": "normal", "normalize": True}
        if fmt == "mp3":
            payload["mp3_bitrate"] = 128
            payload["sample_rate"] = 44100
        elif fmt == "opus":
            payload["opus_bitrate"] = 32000
            payload["sample_rate"] = 48000
        headers = {"Authorization": f"Bearer {FISH_AUDIO_API_KEY}",
                   "Content-Type": "application/json", "model": FISH_AUDIO_MODEL}
        async with aiohttp.ClientSession() as s:
            async with s.post(FISH_AUDIO_URL, json=payload, headers=headers,
                              timeout=aiohttp.ClientTimeout(total=120)) as r:
                if r.status != 200:
                    err = await r.text()
                    raise Exception(f"Fish Audio {r.status}: {err[:200]}")
                data = await r.read()
                if not data or len(data) < 500:
                    raise Exception("Empty audio")
                return data

    # ---------------- PIPELINE ----------------
    async def gemini_refine_and_research(self, task: str) -> Tuple[str, str]:
        search_results = await perform_web_search(task)
        if search_results.startswith("No results") or search_results.startswith("Search"):
            search_results = "(no search results available)"
        sys_p = (
            "You are a research assistant and prompt engineer. Given a raw task and web "
            "search results, do two things in one response:\n\n"
            "1. REFINED_PROMPT: a clear, technically precise, self-contained prompt.\n"
            "2. REFERENCE: dense, factual documentation, APIs, gotchas, constraints.\n\n"
            "Format EXACTLY:\n"
            "===REFINED_PROMPT===\n<refined>\n===REFERENCE===\n<reference>\n"
        )
        usr_p = f"RAW TASK:\n{task}\n\nSEARCH RESULTS:\n{search_results[:5000]}"
        try:
            out = await self.gemini_chat(
                [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
                temperature=0.5, max_tokens=3000,
            )
        except Exception as e:
            logger.warning(f"Gemini refine failed: {e}")
            return task, search_results
        refined, ref = task, search_results
        m = re.search(r"===REFINED_PROMPT===\s*(.*?)\s*===REFERENCE===\s*(.*)", out, re.DOTALL)
        if m:
            refined = m.group(1).strip() or task
            ref = m.group(2).strip() or search_results
        else:
            refined = out.strip() or task
        return refined, ref

    async def gemini_review(self, refined_task: str, code: str) -> str:
        sys_p = (
            "You are a strict senior code reviewer. If the code is correct, complete, and "
            "production-ready, reply with EXACTLY the word APPROVED on its own line, then a "
            "one-line summary. Otherwise, output a numbered list of concrete, actionable "
            "issues — each with the exact fix needed. No praise, no filler."
        )
        usr_p = f"Task:\n{refined_task}\n\nCode:\n```\n{code[:9000]}\n```"
        try:
            return await self.gemini_chat(
                [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
                temperature=0.3, max_tokens=2000,
            )
        except Exception as e:
            return f"(reviewer error: {e})"

    async def run_pipeline(self, channel, user_id, task: str,
                           filename: Optional[str] = None, max_iterations: int = 3):
        filename = filename or infer_filename(task)
        emb = discord.Embed(
            title="🏗️ Pipeline Started",
            description=f"**Task:** {task[:900]}\n**Output file:** `{filename}`",
            color=C_WARM,
        )
        emb.add_field(name="Stages", value=(
            "1️⃣ **GEMINI** — refine + research\n"
            "2️⃣ **DEEPSEEK** — generate\n"
            "3️⃣ **GEMINI** — code review\n"
            "4️⃣ **DEEPSEEK** — fix issues (loop)"
        ), inline=False)
        status = await safe_send(channel, embed=emb)
        if status is None:
            return

        async def step_update(title, body, color=C_PRIMARY):
            e = discord.Embed(title=title, description=body[:4000], color=color)
            e.set_footer(text=f"Pipeline · {filename}")
            await safe_edit(status, embed=e)

        try:
            await step_update("1️⃣ GEMINI — Refining + researching",
                              f"Raw task: {task[:400]}", C_WARM)
            refined, docs = await self.gemini_refine_and_research(task)
            await step_update("1️⃣ GEMINI — Ready",
                              f"**Refined prompt:**\n{refined[:1500]}\n\n"
                              f"**Reference docs:**\n{docs[:1800]}", C_OK)

            await step_update("2️⃣ DEEPSEEK — Generating...", "⏳ working...", C_DEEP)

            def build_msgs(existing="", issues=""):
                sys_p = ("You are an elite software engineer. Produce a complete, working, "
                         "production-ready solution. Output ONLY the full file content in a "
                         "single fenced code block with the correct language identifier.")
                parts = [f"TASK:\n{refined}"]
                if docs:
                    parts.append(f"REFERENCE DOCS:\n{docs[:6000]}")
                if existing:
                    parts.append(f"EXISTING CODE:\n```\n{existing[:8000]}\n```")
                if issues:
                    parts.append(f"REVIEWER FEEDBACK — you MUST fix these:\n{issues}")
                parts.append(f"Deliverable: complete `{filename}`. "
                             "Output ONLY the file inside a single fenced code block.")
                return [{"role": "system", "content": sys_p},
                        {"role": "user", "content": "\n\n".join(parts)}]

            try:
                raw_code = await self.openrouter_call(
                    build_msgs(), model=PIPELINE_GENERATOR_MODEL,
                    temperature=0.5, max_tokens=6000,
                )
            except Exception as e:
                await step_update("❌ DEEPSEEK failed", f"`{str(e)[:300]}`", C_ERR)
                return

            code = strip_code_fences(raw_code) or raw_code.strip()
            await step_update("2️⃣ DEEPSEEK — Draft ready",
                              f"```\n{code[:3400]}\n```", C_OK)

            final_code = code
            approved = False
            iteration = 0
            for iteration in range(1, max_iterations + 1):
                await step_update(f"3️⃣ GEMINI review — iter {iteration}/{max_iterations}",
                                  f"Checking ({len(final_code)} chars)...", C_WARM)
                review = await self.gemini_review(refined, final_code)
                if review.strip().upper().startswith("APPROVED"):
                    await step_update(f"3️⃣ GEMINI review — iter {iteration}",
                                      f"✅ **APPROVED**\n\n{review[:3000]}", C_OK)
                    approved = True
                    break
                await step_update(f"3️⃣ GEMINI review — iter {iteration}",
                                  f"⚠️ **Issues**\n\n{review[:3200]}", C_ACCENT)
                await step_update(f"4️⃣ DEEPSEEK — Fixing (iter {iteration})",
                                  "⏳ applying feedback...", C_DEEP)
                try:
                    raw_fixed = await self.openrouter_call(
                        build_msgs(existing=final_code, issues=review),
                        model=PIPELINE_GENERATOR_MODEL, temperature=0.4, max_tokens=6000,
                    )
                except Exception as e:
                    await step_update(f"❌ DEEPSEEK fix failed (iter {iteration})",
                                      f"`{str(e)[:300]}`", C_ERR)
                    break
                fixed = strip_code_fences(raw_fixed) or raw_fixed.strip()
                if not fixed.strip():
                    break
                final_code = fixed
                await step_update(f"4️⃣ DEEPSEEK — Fix applied (iter {iteration})",
                                  f"```\n{final_code[:3200]}\n```", C_PRIMARY)

            summary = discord.Embed(
                title=f"✅ Pipeline complete — `{filename}`",
                description=(
                    f"**Review:** {'APPROVED' if approved else 'max iterations reached'}\n"
                    f"**Final size:** {len(final_code)} chars\n"
                    f"**Iterations:** {iteration}"
                ),
                color=C_OK if approved else C_WARM,
            )
            await safe_edit(status, embed=summary)
            buf = io.BytesIO(final_code.encode("utf-8"))
            try:
                await safe_send(channel, content=f"📦 **Final `{filename}`**",
                                file=discord.File(buf, filename=filename))
            except discord.HTTPException as e:
                await send_long(channel, f"❌ Attach failed ({e}). Code:\n\n{final_code}")
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            await step_update("❌ Pipeline crashed", f"`{str(e)[:400]}`", C_ERR)

    # ---------------- Debate ----------------
    async def run_ai_chat(self, user_id: int):
        s = self.ai_chat_sessions.get(user_id)
        if not s:
            return
        ch = self.get_channel(s["channel_id"])
        if not ch:
            self.ai_chat_sessions.pop(user_id, None)
            return
        desc = s["description"]
        hist = s["history"]
        turn = 0
        max_turns = self.ai_chat_max_turns
        A1, A2 = "🤠", "🤖"

        def strip_think(t):
            return re.sub(r'<think>.*?</think>', '', t, flags=re.DOTALL).strip()

        try:
            await send_long(ch, f"🏟️ **AI DEBATE – {desc}**\n{A1} **AI1** vs {A2} **AI2**")
            while turn < max_turns:
                if user_id not in self.ai_chat_sessions:
                    break
                n = 1 if turn % 2 == 0 else 2
                o = 2 if n == 1 else 1
                em = A1 if n == 1 else A2
                if not hist:
                    up = (f"🏁 Topic: {desc}\nYou are AI{n}. Bold funny opening. "
                          "Eventually agree on one final answer.")
                else:
                    recent = hist[-10:]
                    ctx = "\n".join(f"AI{e['role']}: {e['content']}" for e in recent)
                    up = f"📢 So far:\n{ctx}\n\nAI{n} responds with energy."
                sp = (f"You are AI{n}, sassy debater. Topic: \"{desc}\" vs AI{o}. "
                      "Dramatic, emojis, <500 chars. Aim for one final answer.")
                try:
                    resp = strip_think(await self.gemini_chat(
                        [{"role": "system", "content": sp}, {"role": "user", "content": up}],
                        temperature=0.9, max_tokens=1024,
                    )) or "[no response]"
                except Exception as e:
                    await send_long(ch, f"⚠️ AI{n} error: {str(e)[:200]}")
                    break
                hist.append({"role": n, "content": resp})
                await send_long(ch, f"{em} **AI{n}:** {resp}")
                turn += 1
                if turn < max_turns:
                    await asyncio.sleep(13)
            if user_id in self.ai_chat_sessions:
                recent = hist[-10:]
                ctx = "\n".join(f"AI{e['role']}: {e['content']}" for e in recent)
                fp = f"🏆 Debate ended.\n{ctx}\n\nAs AI1, deliver final joint verdict."
                spf = f"You are AI1. Give the final answer you and AI2 settled on for \"{desc}\"."
                try:
                    fr = strip_think(await self.gemini_chat(
                        [{"role": "system", "content": spf}, {"role": "user", "content": fp}],
                        temperature=0.9, max_tokens=1024,
                    )) or "[none]"
                except Exception as e:
                    fr = f"Error: {str(e)[:200]}"
                await send_long(ch, f"🏁 **FINAL VERDICT:**\n{fr}")
                self.ai_chat_sessions.pop(user_id, None)
        except asyncio.CancelledError:
            self.ai_chat_sessions.pop(user_id, None)
            raise
        except Exception as e:
            logger.error(f"Debate error: {e}")
            self.ai_chat_sessions.pop(user_id, None)

    # ---------------- central message handler ----------------
    async def process_user_message(self, user, clean_content, destination,
                                   thinking_msg=None, reply_context=None, force_search=False):
        slot_name = self.active_slot.get(user.id, "sv1")
        if user.id not in self.user_slots:
            self.get_slot(user.id, "sv1")

        # Natural-language search: "search X", "google X", "look up X", "find X"
        search_match = re.match(
            r'^(?:search|google|look\s*up|find|lookup)\s*:?\s*(.+)$',
            clean_content, re.IGNORECASE)
        if search_match and not force_search:
            query = search_match.group(1).strip()
            if query:
                thinking_msg = thinking_msg or await safe_send(destination, content="🌐 Searching...")
                if thinking_msg:
                    await safe_edit(thinking_msg, content=f"🌐 Searching: **{query}**...")
                results = await perform_web_search(query)
                if results.startswith("No results") or results.startswith("Search"):
                    return await safe_edit(thinking_msg, content=f"❌ {results}")
                augmented = (
                    f"Web search results for: {query}\n\n{results}\n\n---\n\n"
                    f"Summarize clearly for the user. Cite sources inline like [1], [2]. "
                    f"Keep it useful and concise."
                )
                response = await self.chat_call(augmented, user.id, None, slot_name)
                response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
                self.append_to_slot(user.id, slot_name, "user", clean_content)
                self.append_to_slot(user.id, slot_name, "assistant", response)
                if self.get_persistent_enabled(user.id):
                    self.add_persistent_memory(user.id, "user", clean_content)
                    self.add_persistent_memory(user.id, "assistant", response)
                if len(response) <= DISCORD_LIMIT:
                    await safe_edit(thinking_msg, content=response)
                else:
                    try:
                        await thinking_msg.delete()
                    except discord.HTTPException:
                        pass
                    await send_long(destination, response)
                return

        if self.get_persistent_enabled(user.id):
            self.add_persistent_memory(user.id, "user", clean_content)
        self.append_to_slot(user.id, slot_name, "user", clean_content)

        if thinking_msg is None:
            thinking_msg = await safe_send(destination, content="🔥 Thinking...")
            if thinking_msg is None:
                return

        system_prompt = None
        court = self.court_sessions.get(user.id)
        if court and court.get("case"):
            tpl = self.court_roles.get(court["role"], "")
            if tpl:
                p = court.get("participants", {})
                pl = [f"- {r.capitalize()}: <@{uid}>" for r, uid in p.items()]
                system_prompt = tpl.format(case=court["case"],
                                           participants="\n".join(pl) if pl else "None other than you.")
        elif reply_context:
            oa = reply_context.get("author", "someone")
            oc = reply_context.get("content", "")
            base = self.mode_prompts.get(self.current_mode, self.mode_prompts[DEFAULT_MODE])
            system_prompt = (
                f"{base}\n\n=== REPLY-REACTION TASK ===\n"
                f"{user.display_name} is replying to **{oa}**.\n"
                f"Original from {oa}: \"{oc}\"\n"
                f"User's reply: \"{clean_content}\"\n\n"
                f"React like a real friend. Reference @{oa} naturally. "
                f"Short and punchy (1–3 sentences)."
            )

        try:
            response = await self.ai_call(clean_content, user_id=user.id,
                                          system_prompt=system_prompt,
                                          slot_name=slot_name, web_search=False)
            response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
            if self.get_persistent_enabled(user.id):
                self.add_persistent_memory(user.id, "assistant", response)
            self.append_to_slot(user.id, slot_name, "assistant", response)
            if len(response) <= DISCORD_LIMIT:
                await safe_edit(thinking_msg, content=response)
            else:
                try:
                    await thinking_msg.delete()
                except discord.HTTPException:
                    pass
                await send_long(destination, response)
        except Exception as e:
            logger.error(f"process_user_message: {e}")
            await safe_edit(thinking_msg, content=f"❌ Error: {e}")

    # ---------------- video / music ----------------
    async def generate_video(self, prompt, user_id, status_message):
        if not SILICONFLOW_API_KEYS:
            return await safe_edit(status_message, content="❌ No SiliconFlow key")
        self.video_jobs[user_id] = status_message
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
                                continue
                    except Exception:
                        pass
                if not rid:
                    raise Exception("No requestId")
                await safe_edit(status_message, content=f"🎬 Video queued (`{rid}`)")
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
                                    await safe_edit(status_message, content=f"✅ **Video Ready!**")
                                    await safe_send(status_message.channel,
                                                    file=discord.File(io.BytesIO(data), filename="video.mp4"))
                                    return
                            raise Exception("No video URL")
                        elif st == "Failed":
                            raise Exception(pd.get("reason", "Unknown"))
                        else:
                            await safe_edit(status_message, content=f"🎬 ({attempt+1}/120) — **{st}**")
                raise Exception("Timeout")
        except Exception as e:
            await safe_edit(status_message, content=f"❌ **Video Failed** — {str(e)[:100]}")
        finally:
            self.video_jobs.pop(user_id, None)

    async def generate_music(self, prompt, user_id, status_message):
        url = f"{POLLINATIONS_AUDIO_URL}/{urllib.parse.quote(prompt)}"
        headers = {"User-Agent": "Mozilla/5.0"}
        if POLLINATIONS_API_KEY:
            headers["Authorization"] = f"Bearer {POLLINATIONS_API_KEY}"
        self.music_jobs[user_id] = status_message
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, headers=headers,
                                 timeout=aiohttp.ClientTimeout(total=300)) as r:
                    if r.status == 200:
                        ct = r.headers.get('Content-Type', '')
                        if any(x in ct for x in ('audio', 'mpeg', 'ogg', 'octet-stream')):
                            data = await r.read()
                            if len(data) < 1000:
                                raise Exception("Invalid audio")
                            await safe_edit(status_message, content=f"🎵 Ready")
                            await safe_send(status_message.channel,
                                            file=discord.File(io.BytesIO(data), filename="music.mp3"))
                        else:
                            raise Exception(f"Unexpected content-type: {ct}")
                    else:
                        raise Exception(f"Error {r.status}")
        except asyncio.TimeoutError:
            await safe_edit(status_message, content="❌ Timeout")
        except Exception as e:
            await safe_edit(status_message, content=f"❌ Failed: {str(e)[:100]}")
        finally:
            self.music_jobs.pop(user_id, None)

    # ---------------- loops ----------------
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
            await asyncio.sleep(60)

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
            logger.error(f"Sync failed: {e}")
        self.loop.create_task(self.update_presence_loop())
        self.loop.create_task(self.load_pen_archive_async())


bot = MacBot()

# ============================================================
# AUTOCOMPLETE
# ============================================================
async def llm_ac(i, c):
    return [app_commands.Choice(name=n, value=n) for n in bot.allowed_llms if c.lower() in n.lower()]

async def gemini_ac(i, c):
    return [app_commands.Choice(name=m, value=m) for m in GEMINI_MODELS if c.lower() in m.lower()]


# ============================================================
# HELP
# ============================================================
@bot.hybrid_command(name="mac", description="🔥 Show the Mac help menu")
async def mac_help(ctx):
    emb = discord.Embed(title="🔥 Mac", color=C_PRIMARY,
                        description="Mention me or reply to me. Slash commands work too.")
    emb.add_field(name="💬 Chat", value="`@Mac <msg>` · `/query <msg>`", inline=False)
    emb.add_field(name="🌐 Search", value="Just type `search <thing>` or `google <thing>`", inline=False)
    emb.add_field(name="🗂️ Chat slots", value="`/sv1` `/sv2` `/sv3` `/sv4` `/sv5` — 5 separate chats per user", inline=False)
    emb.add_field(name="🏗️ Pipeline",
                  value="`/pipeline <task> [filename] [iterations]` — GEMINI → DEEPSEEK → review/fix loop",
                  inline=False)
    emb.add_field(name="🖼️ Image", value="`/render <prompt> [mode]` · `/rendermode` · `/hf_model`", inline=False)
    emb.add_field(name="🎙️ TTS", value="`/tts <character> <text>`\nVoices: verity · jarvis · idksterling · **fem**", inline=False)
    emb.add_field(name="🎬 Video / 🎵 Music", value="`/video <prompt>` · `/music <prompt>`", inline=False)
    emb.add_field(name="📚 Snippets", value="`/snippet` · `/snippets` · `/getsnippet` · `/delsnippet`", inline=False)
    emb.add_field(name="💬 AI Debate", value="`/debate <topic>`", inline=False)
    emb.add_field(name="⚙️ Settings",
                  value="`/change-gemini` `/gemini-models` `/change_llm` `/cur_llm` `/config` `/reset` `/smart` `/fast`",
                  inline=False)
    emb.add_field(name="💾 Memory",
                  value="`/sm` `/persistent` `/persistentdisable` `/persistentreset`", inline=False)
    emb.add_field(name="📜 Lore", value="`/pen`", inline=False)
    emb.add_field(name="🏛️ Court", value="`/court` `/role` `/explain-case` `/start-court` `/endcourt`", inline=False)
    emb.add_field(name="🌍 UMF", value="`/umf` `/umf_recognize` `/umf_list` `/umf_status` `/umf_admin` `/umf_search` `/umf_stats`", inline=False)
    emb.set_footer(text="Mac v9.1 — Gemini-first · DeepSeek pipeline · 5 slots per user 🔥")
    await ctx.send(embed=emb)


@bot.hybrid_command(name="help", description="Alias for /mac")
async def help_alias(ctx):
    await mac_help(ctx)


# ============================================================
# CHAT
# ============================================================
@bot.hybrid_command(name="query", description="💬 Talk to Mac")
async def query_cmd(ctx, message: str):
    await ctx.defer()
    try:
        await bot.process_user_message(ctx.author, message, ctx)
    except Exception as e:
        await ctx.send(f"❌ `{e}`", ephemeral=True)


# ============================================================
# CHAT SLOTS (sv1–sv5)
# ============================================================
def _make_slot_cmd(slot_name: str):
    async def _cmd(ctx):
        uid = ctx.author.id
        if uid not in bot.user_slots:
            bot.user_slots[uid] = {f"sv{i}": [] for i in range(1, 6)}
        bot.active_slot[uid] = slot_name
        bot._save_slots()
        count = len(bot.user_slots[uid].get(slot_name, []))
        await ctx.send(f"💾 Switched to **{slot_name}** — {count} messages in this slot.")

    _cmd.__name__ = f"slot_{slot_name}"
    return _cmd


for _i in range(1, 6):
    _name = f"sv{_i}"
    bot.hybrid_command(name=_name, description=f"🗂️ Switch to chat slot {_name}")(_make_slot_cmd(_name))


@bot.hybrid_command(name="svclear", description="🧹 Clear the current chat slot")
async def svclear(ctx):
    uid = ctx.author.id
    slot = bot.active_slot.get(uid, "sv1")
    bot.user_slots.setdefault(uid, {f"sv{i}": [] for i in range(1, 6)})[slot] = []
    bot._save_slots()
    await ctx.send(f"🧹 Cleared **{slot}**")


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
        marker = " ← active" if n == active else ""
        lines.append(f"`{n}`: {c} messages{marker}")
    emb = discord.Embed(title=f"🗂️ Chat slots — {ctx.author.display_name}",
                        description="\n".join(lines), color=C_PRIMARY)
    await ctx.send(embed=emb, ephemeral=True)


# ============================================================
# PIPELINE
# ============================================================
@bot.hybrid_command(name="pipeline", description="🏗️ GEMINI → DEEPSEEK → review → fix")
@app_commands.describe(task="What to build", filename="Output filename (auto if blank)",
                       iterations="Max review→fix iterations (1-5, default 3)")
async def pipeline_cmd(ctx, task: str, filename: str = None, iterations: int = 3):
    await ctx.defer()
    iterations = max(1, min(5, iterations))
    fn = filename.strip() if filename else infer_filename(task)
    try:
        await bot.run_pipeline(ctx.channel, ctx.author.id, task, fn, iterations)
    except Exception as e:
        await ctx.send(f"❌ Pipeline error: `{e}`")


# ============================================================
# TTS
# ============================================================
@bot.hybrid_command(name="tts", description="Say text as a Discord voice message")
@app_commands.describe(character="Voice (default: verity)", prompt="Exact text to speak")
@app_commands.choices(character=[
    app_commands.Choice(name="🎙️ Verity (default)", value="verity"),
    app_commands.Choice(name="🤖 Jarvis", value="jarvis"),
    app_commands.Choice(name="🎭 IdkSterling", value="idksterling"),
    app_commands.Choice(name="👩 Female", value="fem"),
])
async def tts_cmd(ctx, character: str, prompt: str):
    await ctx.defer()
    character = (character or DEFAULT_VOICE).lower()
    if character not in VOICE_MODES:
        character = DEFAULT_VOICE
    clean = strip_for_tts(prompt)
    if not clean:
        return await ctx.send("❌ Nothing to say.")
    try:
        audio = await bot.generate_voice(clean, voice_key=character, fmt="opus")
    except Exception as e:
        logger.error(f"Fish Audio error: {e}")
        return await ctx.send(f"❌ TTS error: {str(e)[:200]}")
    meta = VOICE_MODES[character]
    try:
        file = discord.File(io.BytesIO(audio), filename="voice-message.ogg")
        flags = discord.MessageFlags(is_voice_message=True)
        await ctx.send(file=file, flags=flags)
    except Exception as e:
        logger.warning(f"Voice flag failed, fallback: {e}")
        file2 = discord.File(io.BytesIO(audio), filename="voice.mp3")
        await ctx.send(content=f"{meta['emoji']} **{meta['desc']}**\n-# {clean[:400]}", file=file2)


# ============================================================
# IMAGE
# ============================================================
@bot.hybrid_command(name="render", description="🎨 Generate an image")
@app_commands.describe(prompt="Describe the image", mode="smart | fast | hf")
async def render_cmd(ctx, prompt: str, mode: str = None):
    await ctx.defer()
    chosen = (mode or bot.current_image_mode).lower()
    status_msg = await ctx.send("🔥 Checking your prompt...")
    try:
        safe, reason = await bot.is_prompt_safe(prompt)
        if not safe:
            return await status_msg.edit(content=f"🚫 **Blocked.**\nReason: {reason}")
        await status_msg.edit(content=f"🔥 Generating **{chosen}** image...")
        if chosen in ("hf", "huggingface"):
            img = await bot.generate_hf_image(prompt)
            label = f"🤗 HF (`{bot.current_hf_model}`)"
        elif chosen in ("pollinations", "poll", "fast"):
            img = await bot.generate_pollinations_image(prompt)
            label = "⚡ Pollinations"
        else:
            img = await bot.generate_gemini_image(prompt)
            label = "🧠 Gemini"
        url = await bot.upload_image_to_hosting(img)
        emb = discord.Embed(title="🖼️ Generated", description=f"**Backend:** {label}", color=C_PRIMARY)
        emb.set_image(url=url)
        emb.add_field(name="Prompt", value=prompt[:1024], inline=False)
        await status_msg.edit(content=None, embed=emb)
    except Exception as e:
        await status_msg.edit(content=f"❌ `{str(e)[:180]}`")


@bot.hybrid_command(name="rendermode", description="🖼️ Show or change default image mode")
async def rendermode_cmd(ctx, mode: str = None):
    if mode is None:
        emb = discord.Embed(title="🖼️ Image Mode", color=C_PRIMARY)
        emb.add_field(name="Current", value=f"`{bot.current_image_mode}`", inline=False)
        emb.add_field(name="Options",
                      value="• `smart` → Gemini\n• `fast` → Pollinations\n"
                            f"• `hf` → Hugging Face (`{bot.current_hf_model}`)", inline=False)
        return await ctx.send(embed=emb)
    mode = mode.lower()
    if mode not in ("smart", "fast", "hf"):
        return await ctx.send("❌ Mode must be `smart`, `fast`, or `hf`")
    bot.current_image_mode = mode
    await ctx.send(f"✅ Image mode → **{mode}**")


@bot.hybrid_command(name="hf_model", description="Show or change the HF image model")
async def hf_model_cmd(ctx, model: str = None):
    if model is None:
        listing = "\n".join(f"• `{m}`" for m in HF_IMAGE_MODELS)
        return await ctx.send(
            f"🤗 Current: `{bot.current_hf_model}`\n\nFallback list (tried in order):\n{listing}")
    bot.current_hf_model = model
    await ctx.send(f"✅ HF image model → `{model}`")


# ============================================================
# MEDIA
# ============================================================
@bot.hybrid_command(name="video", description="🎬 Generate a video")
async def video_cmd(ctx, prompt: str):
    await ctx.defer()
    status_msg = await ctx.send(f"🎬 Starting video: **{prompt}**...")
    bot.loop.create_task(bot.generate_video(prompt, ctx.author.id, status_msg))


@bot.hybrid_command(name="music", description="🎵 Generate music")
async def music_cmd(ctx, prompt: str):
    await ctx.defer()
    status_msg = await ctx.send(f"🎵 Starting music: **{prompt}**...")
    bot.loop.create_task(bot.generate_music(prompt, ctx.author.id, status_msg))


# ============================================================
# SETTINGS
# ============================================================
@bot.hybrid_command(name="smart", description="🧠 Smart mode (search + Gemini)")
async def smart_mode(ctx):
    bot.current_image_mode = "smart"
    bot.complex_mode = True
    await ctx.send("🧠 Smart mode")


@bot.hybrid_command(name="fast", description="⚡ Fast mode (search + Pollinations)")
async def fast_mode(ctx):
    bot.current_image_mode = "fast"
    bot.complex_mode = True
    await ctx.send("⚡ Fast mode")


@bot.hybrid_command(name="change-gemini", description="🔮 Change Gemini model (primary)")
@app_commands.autocomplete(name=gemini_ac)
async def change_gemini(ctx, name: str):
    if name not in GEMINI_MODELS:
        return await ctx.send(f"❌ Options: {', '.join(GEMINI_MODELS)}")
    bot.current_gemini_model = name
    await ctx.send(f"🔮 Gemini → **{name}**")


@bot.hybrid_command(name="gemini-models", description="🔮 List Gemini models")
async def gemini_models_cmd(ctx):
    s = "\n".join(f"- {m}" + (" ✅" if m == bot.current_gemini_model else "") for m in GEMINI_MODELS)
    await ctx.send(f"🔮 **Gemini Models**\n{s}\n\nUse `/change-gemini`.")


@bot.hybrid_command(name="change_llm", description="🤖 Change the Groq FALLBACK model")
@app_commands.autocomplete(name=llm_ac)
async def change_llm(ctx, name: str):
    if name not in bot.allowed_llms:
        return await ctx.send(f"❌ Options: {', '.join(bot.allowed_llms)}")
    bot.current_llm = bot.allowed_llms[name]
    try:
        bot.current_model_index = bot.current_model_list.index(bot.current_llm)
    except ValueError:
        bot.current_model_index = 0
    await ctx.send(f"🤖 Groq fallback → **{name}**")


@bot.hybrid_command(name="cur_llm", description="🤖 Show current models")
async def cur_llm(ctx):
    await ctx.send(
        f"🔮 **Gemini (primary):** `{bot.current_gemini_model}`\n"
        f"🤖 **Groq (fallback):** `{bot.current_llm}`\n"
        f"🖼️ **Image mode:** `{bot.current_image_mode}`\n"
        f"🤗 **HF model:** `{bot.current_hf_model}`\n"
        f"🧬 **Pipeline gen:** `{PIPELINE_GENERATOR_MODEL}`"
    )


@bot.hybrid_command(name="config", description="⚙️ Show settings")
async def config_cmd(ctx):
    emb = discord.Embed(title="⚙️ Config", color=C_PRIMARY)
    emb.add_field(name="Gemini", value=f"`{bot.current_gemini_model}`", inline=True)
    emb.add_field(name="Groq fallback", value=f"`{bot.current_llm}`", inline=True)
    emb.add_field(name="Image", value=f"`{bot.current_image_mode}`", inline=True)
    emb.add_field(name="HF model", value=f"`{bot.current_hf_model}`", inline=True)
    emb.add_field(name="Memory", value="ON" if bot.memory_enabled else "OFF", inline=True)
    emb.add_field(name="Active slot", value=f"`{bot.active_slot.get(ctx.author.id, 'sv1')}`", inline=True)
    await ctx.send(embed=emb)


@bot.hybrid_command(name="reset", description="Soft reset")
async def reset_cmd(ctx):
    bot.memory_enabled = True
    bot.saved_memory.clear()
    await ctx.send("🔄 Reset")


# ============================================================
# MEMORY
# ============================================================
@bot.hybrid_command(name="sm", description="Toggle memory")
async def sm(ctx):
    bot.memory_enabled = not bot.memory_enabled
    await ctx.send(f"🧠 Memory **{'ON' if bot.memory_enabled else 'OFF'}**")


@bot.hybrid_command(name="persistent", description="Enable persistent memory")
async def persistent_enable(ctx):
    bot.set_persistent_enabled(ctx.author.id, True)
    await ctx.send(f"✅ Persistent memory ON for {ctx.author.display_name}")


@bot.hybrid_command(name="persistentdisable", description="Disable persistent memory")
async def persistent_disable(ctx):
    bot.set_persistent_enabled(ctx.author.id, False)
    await ctx.send("🚫 Persistent memory OFF")


@bot.hybrid_command(name="persistentreset", description="Reset a user's persistent memory (admin)")
async def persistent_reset(ctx, target_user: discord.User):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ Admin only")
    bot.clear_persistent_memory(target_user.id)
    await ctx.send(f"🧹 Reset for {target_user.display_name}")


# ============================================================
# SNIPPETS
# ============================================================
async def _send_code(channel, code, filename, note=""):
    code = strip_code_fences(code)
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "txt"
    if len(code) > 1900:
        buf = io.BytesIO(code.encode("utf-8"))
        await safe_send(channel, content=note or f"📄 `{filename}`",
                        file=discord.File(buf, filename=filename))
    else:
        await safe_send(channel, content=(note + "\n" if note else "") + f"```{ext}\n{code}\n```")


@bot.hybrid_command(name="snippet", description="💾 Save a code snippet")
async def snippet_save(ctx, name: str, code: str):
    bot.snippets[ctx.author.id][name] = {"code": code, "created": datetime.now().isoformat()}
    bot._save_snippets()
    await ctx.send(f"💾 Snippet **{name}** saved ({len(code)} chars)")


@bot.hybrid_command(name="snippets", description="📚 List your snippets")
async def snippet_list(ctx):
    s = bot.snippets.get(ctx.author.id, {})
    if not s:
        return await ctx.send("No snippets saved.")
    lines = "\n".join(f"• **{n}** ({len(v['code'])} chars)" for n, v in s.items())
    await send_long(ctx, f"📚 **Your Snippets**\n{lines}")


@bot.hybrid_command(name="getsnippet", description="📄 Fetch a snippet")
async def snippet_get(ctx, name: str):
    s = bot.snippets.get(ctx.author.id, {}).get(name)
    if not s:
        return await ctx.send("❌ Not found.")
    await _send_code(ctx.channel, s["code"], f"{name}.txt", note=f"📄 `{name}`")


@bot.hybrid_command(name="delsnippet", description="🗑️ Delete a snippet")
async def snippet_delete(ctx, name: str):
    s = bot.snippets.get(ctx.author.id, {})
    if name not in s:
        return await ctx.send("❌ Not found.")
    s.pop(name)
    bot._save_snippets()
    await ctx.send(f"🗑️ Deleted **{name}**")


# ============================================================
# AI DEBATE
# ============================================================
@bot.hybrid_command(name="debate", description="🤖 Start/stop AI-to-AI debate")
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


# ============================================================
# LORE
# ============================================================
@bot.hybrid_command(name="pen", description="📜 Pen archive")
async def pen_cmd(ctx):
    s = bot.pen_archive[:1000] if bot.pen_archive else "Not loaded"
    await ctx.send(f"📜 **Pen Archive**\n```\n{s}\n```\n[Full](https://github.com/Pen-123/archive-)")


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
            content=(f"✅ You are now **{role_key.capitalize()}**.\n"
                     f"Use `/explain-case`, `/role`, `/start-court`."),
            view=None,
        )

    @discord.ui.button(label="Judge", style=discord.ButtonStyle.primary)
    async def judge_btn(self, i, b): await self.select_role(i, "judge")

    @discord.ui.button(label="Prosecutor", style=discord.ButtonStyle.danger)
    async def pros_btn(self, i, b): await self.select_role(i, "prosecutor")

    @discord.ui.button(label="Defense", style=discord.ButtonStyle.success)
    async def def_btn(self, i, b): await self.select_role(i, "defense")

    @discord.ui.button(label="Witness", style=discord.ButtonStyle.secondary)
    async def wit_btn(self, i, b): await self.select_role(i, "witness")

    @discord.ui.button(label="Jury", style=discord.ButtonStyle.secondary)
    async def jury_btn(self, i, b): await self.select_role(i, "jury")

    @discord.ui.button(label="Stenographer", style=discord.ButtonStyle.secondary)
    async def sten_btn(self, i, b): await self.select_role(i, "stenographer")


@bot.hybrid_command(name="court", description="🏛️ Start a court session")
async def court_cmd(ctx):
    await ctx.send("🏛️ **Court session** — pick your role:", view=CourtRoleView(bot))


@bot.hybrid_command(name="role", description="🏛️ Assign a court role")
async def role_cmd(ctx, user: discord.User, role: str):
    if ctx.author.id not in bot.court_sessions:
        return await ctx.send("❌ Start with `/court` first.")
    valid = ["prosecutor", "defense", "witness", "jury", "stenographer", "judge"]
    if role.lower() not in valid:
        return await ctx.send(f"❌ Pick from: {', '.join(valid)}")
    bot.court_sessions[ctx.author.id]["participants"][role.lower()] = user.id
    await ctx.send(f"✅ {user.mention} → **{role.capitalize()}**")


@bot.hybrid_command(name="explain-case", description="🏛️ Add case details")
async def explain_case(ctx, case: str):
    if ctx.author.id not in bot.court_sessions:
        return await ctx.send("❌ Start with `/court` first.")
    bot.court_sessions[ctx.author.id]["case"] = case
    await ctx.send("✅ Case recorded. `/start-court` to begin.")


@bot.hybrid_command(name="start-court", description="🏛️ Start the session")
async def start_court(ctx):
    if ctx.author.id not in bot.court_sessions:
        return await ctx.send("❌ Start with `/court` first.")
    s = bot.court_sessions[ctx.author.id]
    if not s.get("case"):
        return await ctx.send("❌ Add case with `/explain-case` first.")
    p = s.get("participants", {})
    if p:
        out = "🏛️ **Court in session!**\n"
        for r, uid in p.items():
            u = ctx.guild.get_member(uid) if ctx.guild else bot.get_user(uid)
            out += f"**{r.capitalize()}**: {u.mention if u else f'<@{uid}>'}\n"
        await ctx.send(out)
    await ctx.send("Begin.")


@bot.hybrid_command(name="endcourt", description="🏛️ End the session")
async def endcourt_cmd(ctx):
    if ctx.author.id in bot.court_sessions:
        del bot.court_sessions[ctx.author.id]
        await ctx.send("🏛️ Ended.")
    else:
        await ctx.send("❌ Not in a session.")


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
    def add_recognized_nation(self, nation):
        nations = self.get_recognized_nations()
        if nation not in nations:
            nations.append(nation)
            self.data["recognized_nations"] = nations
            self.save()
            return True
        return False

    def add_pending_request(self, user_id, nation, username):
        req = {"user_id": user_id, "username": username, "nation": nation,
               "timestamp": datetime.now().isoformat(), "status": "pending"}
        self.data["pending_requests"].append(req)
        self.save()
        return req

    def get_pending_requests(self): return self.data.get("pending_requests", [])

    def approve_request(self, user_id):
        pending = self.data.get("pending_requests", [])
        for i, req in enumerate(pending):
            if req["user_id"] == user_id and req["status"] == "pending":
                req["status"] = "approved"
                req["approved_at"] = datetime.now().isoformat()
                self.data["approved_requests"].append(req)
                pending.pop(i)
                self.data["pending_requests"] = pending
                self.save()
                return req
        return None

    def deny_request(self, user_id, reason=""):
        pending = self.data.get("pending_requests", [])
        for i, req in enumerate(pending):
            if req["user_id"] == user_id and req["status"] == "pending":
                req["status"] = "denied"
                req["denied_reason"] = reason
                req["denied_at"] = datetime.now().isoformat()
                self.data["denied_requests"].append(req)
                pending.pop(i)
                self.data["pending_requests"] = pending
                self.save()
                return req
        return None

    def get_request_status(self, user_id):
        for bucket in ("pending_requests", "approved_requests", "denied_requests"):
            for req in self.data.get(bucket, []):
                if req["user_id"] == user_id:
                    return req
        return None

    def is_nation_recognized(self, nation): return nation in self.get_recognized_nations()

    def add_to_history(self, action, user_id, username, nation, details=""):
        self.data["recognition_history"].append({
            "action": action, "user_id": user_id, "username": username,
            "nation": nation, "timestamp": datetime.now().isoformat(),
            "details": details})
        self.save()


bot.umf_data = UMFData()


def umf_requirements_embed():
    emb = discord.Embed(title="🌍 UMF Recognition System",
                        description="To be recognized by the **United Military Federation (UMF)**:",
                        color=C_PRIMARY, timestamp=datetime.now())
    emb.add_field(name="📋 Requirements", value=(
        "1. **Administrative User** — an admin user in the UMF.\n"
        "2. **Relay Link** — nation relay-linked to the UMF network.\n"
        "3. **Active Status** — nation actively participating."
    ), inline=False)
    emb.add_field(name="📝 How to Apply",
                  value="Click **'Request Recognition'**, enter your nation name.", inline=False)
    emb.add_field(name="✅ Currently Recognized",
                  value=f"**{len(bot.umf_data.get_recognized_nations())}** nations", inline=False)
    return emb


def umf_nation_list_embed(page=0, per_page=15):
    nations = bot.umf_data.get_recognized_nations()
    total = len(nations)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    start = page * per_page
    end = min(start + per_page, total)
    emb = discord.Embed(title="🌍 Recognized UMF Nations", color=C_ACCENT, timestamp=datetime.now())
    emb.description = ("```\n" + "\n".join(f"• {n}" for n in nations[start:end]) + "\n```"
                       if nations[start:end] else "No nations recognized yet.")
    emb.set_footer(text=f"Page {page + 1}/{pages} • Total: {total}")
    return emb


def umf_status_embed(req):
    nation = req.get("nation", "Unknown")
    status = req.get("status", "unknown")
    if status == "pending":
        color, title, desc = C_WARM, "⏳ Pending", f"Request for **{nation}** is under review."
    elif status == "approved":
        color, title, desc = C_OK, "✅ Approved!", f"**{nation}** is officially recognized."
    elif status == "denied":
        color, title, desc = C_ERR, "❌ Denied", (
            f"**{nation}** was denied.\nReason: {req.get('denied_reason', 'No reason given')}")
    else:
        color, title, desc = C_DEEP, "ℹ️ No Request", "You have no active request."
    emb = discord.Embed(title=title, description=desc, color=color, timestamp=datetime.now())
    emb.add_field(name="📋 Nation", value=nation, inline=True)
    if "timestamp" in req:
        emb.add_field(name="📅 Submitted",
                      value=datetime.fromisoformat(req["timestamp"]).strftime("%B %d, %Y %H:%M"),
                      inline=True)
    return emb


class UMFRecognitionModal(discord.ui.Modal, title="🌍 UMF Recognition Request"):
    nation_name = discord.ui.TextInput(label="Nation Name", required=True, max_length=100)
    additional = discord.ui.TextInput(label="Additional Info (optional)", required=False,
                                      max_length=500, style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction):
        nation = self.nation_name.value.strip()
        if bot.umf_data.is_nation_recognized(nation):
            return await interaction.response.send_message(
                f"⚠️ **{nation}** is already recognized.", ephemeral=True)
        existing = bot.umf_data.get_request_status(interaction.user.id)
        if existing and existing.get("status") == "pending":
            return await interaction.response.send_message(
                "⏳ You already have a pending request.", ephemeral=True)
        bot.umf_data.add_pending_request(interaction.user.id, nation, interaction.user.display_name)
        bot.umf_data.add_to_history("REQUEST_SUBMITTED", interaction.user.id,
                                    interaction.user.display_name, nation,
                                    f"Additional: {self.additional.value or 'None'}")
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
        reason = self.reason.value.strip()
        denied = bot.umf_data.deny_request(self.req["user_id"], reason)
        if not denied:
            return await interaction.response.edit_message(content="❌ Already processed.", view=None)
        bot.umf_data.add_to_history("DENIED", denied["user_id"], denied["username"],
                                    denied["nation"], f"Reason: {reason}")
        emb = discord.Embed(title="❌ Denied", description=f"**{denied['nation']}** denied.", color=C_ERR)
        emb.add_field(name="👤 Applicant", value=self.user.mention, inline=True)
        emb.add_field(name="📝 Reason", value=reason, inline=False)
        await interaction.response.edit_message(embed=emb, view=None)


class UMFPrimaryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📝 Request Recognition", style=discord.ButtonStyle.primary, emoji="🌍")
    async def request_btn(self, interaction, button):
        await interaction.response.send_modal(UMFRecognitionModal())

    @discord.ui.button(label="📋 View Nations", style=discord.ButtonStyle.secondary, emoji="📋")
    async def list_btn(self, interaction, button):
        await interaction.response.send_message(embed=umf_nation_list_embed(), ephemeral=True)

    @discord.ui.button(label="ℹ️ My Status", style=discord.ButtonStyle.secondary, emoji="ℹ️")
    async def status_btn(self, interaction, button):
        req = bot.umf_data.get_request_status(interaction.user.id)
        emb = umf_status_embed(req) if req else discord.Embed(
            title="ℹ️ No Request", description="No active request.", color=C_DEEP)
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
            return await interaction.response.edit_message(content="❌ Already processed.", view=None)
        nation = approved["nation"]
        bot.umf_data.add_recognized_nation(nation)
        bot.umf_data.add_to_history("APPROVED", approved["user_id"], approved["username"],
                                    nation, f"Approved by {interaction.user}")
        emb = discord.Embed(title="✅ Approved!", description=f"**{nation}** recognized.", color=C_OK)
        emb.add_field(name="👤 Applicant", value=self.user.mention, inline=True)
        emb.add_field(name="✅ By", value=interaction.user.mention, inline=True)
        await interaction.response.edit_message(embed=emb, view=None)

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny_btn(self, interaction, button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        await interaction.response.send_modal(UMFDenyModal(self.req, self.user))


@bot.hybrid_command(name="umf", description="🌍 UMF Recognition System")
async def umf_command(ctx):
    await ctx.send(embed=umf_requirements_embed(), view=UMFPrimaryView())


@bot.hybrid_command(name="umf_recognize", description="🌍 Request UMF recognition")
async def umf_recognize(ctx):
    if ctx.interaction:
        await ctx.interaction.response.send_modal(UMFRecognitionModal())
    else:
        await ctx.send("Use `/umf` to submit.")


@bot.hybrid_command(name="umf_list", description="📋 List recognized nations")
async def umf_list(ctx):
    await ctx.send(embed=umf_nation_list_embed())


@bot.hybrid_command(name="umf_status", description="ℹ️ Check your request status")
async def umf_status(ctx):
    req = bot.umf_data.get_request_status(ctx.author.id)
    emb = umf_status_embed(req) if req else discord.Embed(
        title="ℹ️ No Request", description="No active request.", color=C_DEEP)
    await ctx.send(embed=emb, ephemeral=True)


@bot.hybrid_command(name="umf_admin", description="🔧 Admin panel")
async def umf_admin(ctx):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("⛔ Admin only.", ephemeral=True)
    pending = bot.umf_data.get_pending_requests()
    if not pending:
        return await ctx.send("📭 No pending requests.", ephemeral=True)
    req = pending[0]
    user = ctx.guild.get_member(req["user_id"]) or await ctx.guild.fetch_member(req["user_id"])
    emb = discord.Embed(title="📋 Pending Request", color=C_WARM)
    emb.add_field(name="👤 Applicant", value=user.mention if user else f"<@{req['user_id']}>", inline=True)
    emb.add_field(name="🌍 Nation", value=req["nation"], inline=True)
    emb.add_field(name="📅 Submitted",
                  value=datetime.fromisoformat(req["timestamp"]).strftime("%B %d, %Y %H:%M"), inline=True)
    emb.add_field(name="📊 Total", value=str(len(pending)), inline=True)
    await ctx.send(embed=emb, view=UMFAdminView(req, user), ephemeral=True)


@bot.hybrid_command(name="umf_search", description="🔍 Search nations")
async def umf_search(ctx, query: str):
    nations = bot.umf_data.get_recognized_nations()
    matches = [n for n in nations if query.lower() in n.lower()]
    if matches:
        emb = discord.Embed(title=f"🔍 '{query}'",
                            description=f"Found **{len(matches)}**:\n```\n" +
                                        "\n".join(f"• {n}" for n in matches[:25]) + "\n```",
                            color=C_ACCENT)
    else:
        emb = discord.Embed(title=f"🔍 No results for '{query}'", color=C_ERR)
    await ctx.send(embed=emb, ephemeral=True)


@bot.hybrid_command(name="umf_stats", description="📊 UMF statistics")
async def umf_stats(ctx):
    d = bot.umf_data.data
    emb = discord.Embed(title="📊 UMF Statistics", color=C_PRIMARY, timestamp=datetime.now())
    emb.add_field(name="🌍 Recognized", value=str(len(d.get("recognized_nations", []))), inline=True)
    emb.add_field(name="⏳ Pending", value=str(len(d.get("pending_requests", []))), inline=True)
    emb.add_field(name="✅ Approved", value=str(len(d.get("approved_requests", []))), inline=True)
    emb.add_field(name="❌ Denied", value=str(len(d.get("denied_requests", []))), inline=True)
    emb.add_field(name="📜 History", value=str(len(d.get("recognition_history", []))), inline=True)
    await ctx.send(embed=emb, ephemeral=True)


# ============================================================
# ON MESSAGE (mention-safe)
# ============================================================
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Robust mention detection
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = (
        bot.user in message.mentions
        or f"<@{bot.user.id}>" in message.content
        or f"<@!{bot.user.id}>" in message.content
        or is_dm
    )

    # If it's a genuine prefix command (not a ping), let the command system handle it.
    # We only skip command processing when the message is a bot ping / DM.
    if not is_mentioned:
        await bot.process_commands(message)
        return

    # Try to parse reply context
    reply_context = None
    if message.reference and message.reference.resolved:
        resolved = message.reference.resolved
        if isinstance(resolved, discord.Message) and resolved.author.id != bot.user.id:
            reply_context = {
                "author": resolved.author.display_name,
                "content": (resolved.content or "[no text]")[:1000],
                "author_id": resolved.author.id,
            }
    elif message.reference and not message.reference.resolved:
        try:
            resolved = await message.channel.fetch_message(message.reference.message_id)
            if resolved.author.id != bot.user.id:
                reply_context = {
                    "author": resolved.author.display_name,
                    "content": (resolved.content or "[no text]")[:1000],
                    "author_id": resolved.author.id,
                }
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    # Cooldown
    now = time.time()
    if now - bot.user_cooldowns.get(message.author.id, 0) < USER_COOLDOWN_SECONDS:
        return
    bot.user_cooldowns[message.author.id] = now

    # Strip mentions from the content
    clean = re.sub(r'<@!?{}>\s*'.format(bot.user.id), '', message.content).strip()
    if not clean and reply_context:
        clean = "what do you think of this?"
    if not clean:
        return

    await bot.process_user_message(
        message.author, clean, message.channel, reply_context=reply_context
    )


# ============================================================
# WEB SERVER + MAIN
# ============================================================
async def handle_root(request):
    return web.Response(text="🔥 Mac is running!")


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
    logger.info(f"🌐 Web server on :{port}")


async def main():
    await run_web_server()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
