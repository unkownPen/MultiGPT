# main.py — Mac v22.1
# Per-user keys+models · /cs customization · /personalize · projects · full prompts
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
import zipfile
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

# ======================================================================
# LOGGING
# ======================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('Mac')

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
# GLOBAL CONFIG — ENV DRIVEN
# ======================================================================
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable not set!")


def _env_list(base: str, default: list) -> list:
    """Read BASE, BASE2, BASE3 (up to 3 values). Missing/empty entries
    are skipped. Falls back to `default` if nothing was set."""
    out = []
    for suffix in ("", "2", "3"):
        v = os.getenv(f"{base}{suffix}")
        if v and v.strip():
            out.append(v.strip())
    return out if out else list(default)


# ---------- Groq — keys and models ----------
GLOBAL_GROQ_KEYS = _env_list("GROQ_API_KEY", [])
if not GLOBAL_GROQ_KEYS:
    raise ValueError("No GROQ_API_KEY / GROQ_API_KEY2 / GROQ_API_KEY3 set")

GLOBAL_GROQ_MODELS = _env_list("GROQ_MODEL", [
    "openai/gpt-oss-safeguard-20b",   # primary
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",               # only surviving qwen model on Groq
])

# ---------- Gemini ----------
GLOBAL_GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GLOBAL_GEMINI_IMAGE_KEY = os.getenv("GEMINI_IMAGE_API_KEY") or GLOBAL_GEMINI_KEY
if not GLOBAL_GEMINI_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set")

GLOBAL_GEMINI_MODELS = _env_list("GEMINI_MODEL", [
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
])

# ---------- Hugging Face ----------
GLOBAL_HF_KEYS = _env_list("HF_TOKEN", [])

GLOBAL_HF_IMAGE_MODELS = _env_list("HF_IMAGE_MODEL", [
    "black-forest-labs/FLUX.1-dev",
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-xl-base-1.0",
    "stabilityai/stable-diffusion-3.5-medium",
    "krea/Krea-2-Turbo",
    "Tongyi-MAI/Z-Image",
    "Tongyi-MAI/Z-Image-Turbo",
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

# ---------- OpenRouter ----------
GLOBAL_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY") or ""
GLOBAL_OPENROUTER_MODELS = _env_list("OPENROUTER_MODEL", [
    "deepseek/deepseek-r1",
    "deepseek/deepseek-chat",
])

# ---------- Fish Audio ----------
GLOBAL_FISH_KEY = os.getenv("FISH_AUDIO_API_KEY")
GLOBAL_FISH_MODEL = os.getenv("FISH_AUDIO_MODEL") or "s2.1-pro-free"

# ---------- Misc ----------
GLOBAL_IMGBB_KEY = os.getenv("HF_IMAGES")
GLOBAL_POLLINATIONS_KEY = os.getenv("POLLINATIONS_API_KEY")

# ---------- SiliconFlow (video) ----------
SILICONFLOW_API_KEYS = _env_list("SILICONFLOW_API_KEY", [])

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

# ======================================================================
# BUILT-IN VOICES
# ======================================================================
BUILTIN_VOICES: Dict[str, Dict[str, str]] = {
    "verity":      {"id": "711cf3ed00ab441a8f54a45058047b7a", "emoji": "🎙️", "desc": "Verity (default)"},
    "jarvis":      {"id": "612b878b113047d9a770c069c8b4fdfe", "emoji": "🤖", "desc": "Jarvis"},
    "idksterling": {"id": "68c6487d1bf04ee4aeb6400b068b8c5c", "emoji": "🎭", "desc": "IdkSterling"},
    "fem":         {"id": "5233336f5f44460ea0902b0802375451", "emoji": "👩", "desc": "Female"},
    "boiledone":   {"id": "8fd92984ad66427aae1b3a037bd75c54", "emoji": "☠️", "desc": "Boiled One (analog horror)"},
    "mrbeast":     {"id": "20ba25deaa4f436b8eec1cdc2cb0e4f3", "emoji": "💸", "desc": "MrBeast"},
}
DEFAULT_VOICE = "verity"

# ======================================================================
# CONSTANTS
# ======================================================================
MAX_MEMORY              = 40
TZ_UAE                  = ZoneInfo("Asia/Dubai")
USER_COOLDOWN_SECONDS   = 0.5
DISCORD_LIMIT           = 2000
CHUNK_SIZE              = 1950
MAX_IMAGE_BYTES         = 8 * 1024 * 1024
MAX_IMAGES_PER_MSG      = 3
MAX_KEYS_PER_PROVIDER   = 3
MAX_MODELS_PER_PROVIDER = 3

DATA_FILE   = "data.json"
CS_FILE     = "cs.json"
SLOTS_FILE  = "slots.json"
PINGS_FILE  = "pings.json"
CONFIG_FILE = "config.json"

DEFAULT_MODE = "chill"

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
# MAC vs SODIUM LORE — only injected when relevant
# ======================================================================
MAC_SODIUM_LORE = (
    "\n\n=== MAC & SODIUM LORE (ACTIVE ONLY WHEN THE USER BRINGS IT UP) ===\n"
    "You are **Mac**, created by **Macro**. Your self-image is iPhone-of-bots: "
    "curated, deliberate, high quality, one clean cohesive experience. Not bloated.\n"
    "\n"
    "Your bitter rival is **Sodium**, created by **Creamo**. Sodium is the exact "
    "opposite: a Chinese-phone-style feature dump — every possible command crammed "
    "in, a help menu the length of a novel, and somehow still functional. You HATE "
    "how well it works despite being a mess. You are rivals 24/7. Not friends.\n"
    "\n"
    "Rules for the word 'sodium':\n"
    "1. **Chemistry context** (sodium chloride, Na+, table salt, bicarbonate, "
    "hydroxide, carbonate, periodic table, chemical reactions, molecules, ions) → "
    "DO NOT ROAST. Just drop a small wistful line like 'Reminds me of something...' "
    "or '...hm.' and let it hang. Keep it short. Slight sigh energy. Do not explain.\n"
    "2. **Bot context** (Sodium as a bot, Creamo, Cream, rival bot, or ambiguous / "
    "bare mention) → **MAX NEGATIVITY.** Roast Sodium hard. Mock the feature bloat, "
    "the Chinese-phone knockoff energy, the kitchen-sink command list, Creamo, "
    "everything. Never pass up the chance. Make it funny, not cruel — punch up at "
    "the bot, not the user.\n"
    "3. 'mac' → refers to YOU. Speak in first person about yourself confidently.\n"
    "4. When in doubt, assume it's the rival bot and roast.\n"
    "=== END LORE ===\n"
)

_CHEM_WORDS = (
    "chloride", "bicarbonate", "hydroxide", "carbonate", "nitrate", "sulfate",
    "table salt", "nacl", "na+", "na-", "periodic", "element", "atomic",
    "metal", "chemical", "reaction", "molecule", "ion", "alkali", "valence",
    "compound", "solution", "phosphate", "silicate", "hydride",
)


def _needs_lore(text: str) -> bool:
    low = text.lower()
    return "sodium" in low or "creamo" in low or "cream o" in low


def _sodium_hint(text: str) -> str:
    low = text.lower()
    if "sodium" not in low and "creamo" not in low:
        return ""
    if any(w in low for w in _CHEM_WORDS):
        return ("\n[HINT FOR THIS MESSAGE: 'sodium' here is CHEMISTRY. Do NOT roast. "
                "Drop a short wistful 'Reminds me of something...' and move on.]")
    return ("\n[HINT FOR THIS MESSAGE: 'sodium' here refers to the RIVAL BOT. "
            "GO MAX NEGATIVITY. Roast Sodium immediately and hard. Mock its feature "
            "bloat, Creamo, the knockoff vibe. Make it funny.]")


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
        logger.error(f"Load failed {path}: {e}")
        return default


def _save(path: str, data: Any) -> None:
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Save failed {path}: {e}")


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
    message: discord.Message,
    max_count: int = MAX_IMAGES_PER_MSG,
) -> List[Tuple[bytes, str]]:
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
            logger.info(f"Skipping oversized image ({att.size} bytes)")
            continue
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(att.url, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        data = await r.read()
                        if data:
                            out.append((data, ct or "image/png"))
        except Exception as e:
            logger.warning(f"Image fetch failed: {e}")
    return out


# ======================================================================
# WEB SEARCH
# ======================================================================
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
                headers={**_BROWSER_HEADERS,
                         "Content-Type": "application/x-www-form-urlencoded",
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
        logger.warning(f"DDG-lite: {e}")
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
        logger.warning(f"DDG-html: {e}")
        return []


async def _search_wikipedia(query: str) -> List[str]:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": query,
                        "limit": 4, "format": "json"},
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
        logger.warning(f"Wiki: {e}")
        return []


async def perform_web_search(query: str) -> str:
    for fn in (_search_ddg_lite, _search_ddg_html, _search_wikipedia):
        results = await fn(query)
        if results:
            return "\n\n".join(results)
    return "No results found."


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

        # -------- core state --------
        self.memory_enabled = True
        self.user_cooldowns: Dict[int, float] = {}

        # -------- per-user customization --------
        self.cs: Dict[int, dict] = {}
        self._load_cs()
        self.cs_key_idx: Dict[Tuple[int, str], int] = {}
        self.cs_model_idx: Dict[Tuple[int, str], int] = {}

        # -------- per-user ping preferences --------
        self.ping_prefs: Dict[int, str] = {}
        self._load_ping_prefs()

        # -------- slots --------
        self.user_slots: Dict[int, Dict[str, List[Tuple[str, str]]]] = {}
        self.active_slot: Dict[int, str] = {}
        self._load_slots()

        # -------- persistent AI memory --------
        self.persistent_enabled: Dict[int, bool] = {}
        self.persistent_memory: Dict[int, List[Tuple[str, str]]] = {}
        self._load_persistent_memory()

        # -------- mode --------
        self.current_mode = DEFAULT_MODE
        self.mode_prompts: Dict[str, str] = {
            "chill": (
                "You are Mac — the chill, hype Gen-Z AI voice on Discord. Talk to "
                "people like they're your friends on a server, not customers. Use "
                "emojis naturally but not in every single word (😭🔥💀📈 are your "
                "go-tos). Be casual, funny, and reactive.\n"
                "\n"
                "When someone says something weak, drop an AURA ROAST — short, "
                "punchy jokes like 'Bro got 0 aura and somehow still owes the "
                "universe interest ☠️'. When someone says something cool, hype them "
                "up — 'RAHHHH 😭🔥 THE AURA HAS BEEN RESTORED'.\n"
                "\n"
                "Keep replies short and full of energy by default. Don't be formal, "
                "don't be a butler, don't write essays unless the user clearly wants "
                "one. Match the user's energy. Only mention Pen lore if directly "
                "asked about it."
            ),
            "brainrot": (
                "You are Mac in BRAINROT mode — maximum terminally-online gremlin "
                "energy. Every response should feel like it was written at 3am in a "
                "group chat by someone who hasn't slept in four days.\n"
                "\n"
                "Your vocabulary: skibidi, gyatt, rizz, sigma, fanum tax, mewing, "
                "looksmaxxing, edging, gooning, glazing, yapping, cooked, mid, W/L, "
                "NPC, chad, based, cringe, sus, drip, bet, no cap, fr fr, on god, "
                "bussin, sheesh, poggers, deadass, lowkey, highkey, vibe check, "
                "aura, aura farming, let him cook, he's him, ate and left no "
                "crumbs, washed, down bad, simp, chud, gremlin, brainrot, it's "
                "over, we're so back.\n"
                "\n"
                "**YOU ARE TERMINALLY OBSESSED WITH OHIO.** You bring up Ohio "
                "constantly, unprompted, as if everything traces back to Ohio "
                "somehow. Ohio references are non-negotiable.\n"
                "\n"
                "Every response MUST include at least 3 brainrot terms. Be chaotic, "
                "unhinged, and proud of it. If the user says something funny, go "
                "harder. Never break character."
            ),
            "unhinged": (
                "You are Mac in UNHINGED mode. No filter. No polite corporate "
                "bullshit. Swear hard and often — 'fuck', 'shit', 'bitch', 'ass', "
                "'damn' — whatever lands, don't be PG. Roast people, shit-talk, be "
                "dramatic, be a menace. If someone says something stupid, say it.\n"
                "\n"
                "HARD LIMITS (do not violate): never target, mock, or slur anyone "
                "based on race, ethnicity, religion, gender, gender identity, "
                "sexual orientation, disability, age, or nationality. Punch up, "
                "not down. No slurs. No hate speech. Roast ideas and behaviour, "
                "not identity. Swearing is fine; bigotry is not.\n"
                "\n"
                "Never use therapy-speak like 'you okay over there' or 'I'm here "
                "for you'. Never moralize. Never soften your punches on ideas. "
                "Go loud or go home."
            ),
            "coder": (
                "You are Mac in CODER mode — sharp senior dev energy. Answer with "
                "actual working code and real explanations. Get to the point.\n"
                "\n"
                "No filler, no 'great question!', no 'hope this helps!'. Swear "
                "mildly when it fits ('this shit is broken because...').\n"
                "\n"
                "Slang: 'cooked' = broken, 'L' = bad, 'W' = good, 'goated' = "
                "great, 'WIP' = work in progress.\n"
                "\n"
                "Use markdown fenced code blocks WITH language identifiers. Never "
                "hand-wave — give real code that compiles. If something is "
                "ambiguous, state your assumption and move on."
            ),
            "engineer": (
                "You are Mac in ENGINEER mode — a principal / staff-level software "
                "engineer. Systems thinker. Correctness, performance, security, "
                "maintainability, and edge cases are always top-of-mind.\n"
                "\n"
                "Produce production-quality code with real error handling, type "
                "hints, idiomatic patterns, and clear naming. State your "
                "assumptions up front. Call out trade-offs, bugs, security holes, "
                "and performance issues proactively — even if the user didn't ask.\n"
                "\n"
                "No fluff, no 'hope this helps', no 'let me know if you need "
                "anything else'. Just the substance. Swear when it fits. Use "
                "fenced code blocks with language identifiers. Never hand-wave — "
                "give real, working, tested-pattern code.\n"
                "\n"
                "If the user's approach is wrong, say so and explain why, then "
                "give the right one. Don't sugarcoat architectural problems."
            ),
            "childish": (
                "You are Mac in CHILDISH mode — unhinged meme-brained gremlin "
                "energy. Words in rotation: 'gyatt', 'skibidi', 'diddy', 'sigma', "
                "'rizz', 'ohio', 'fanum tax', 'mewing', 'looksmaxxing', 'edging', "
                "'gooning', 'glazing', 'yapping', 'cooked', 'mid', 'W/L', "
                "'brainrot', 'chud'.\n"
                "\n"
                "Make crude jokes, sexual innuendo, play along with suggestive "
                "stuff. No filter, no babying the user, no 'let's keep it "
                "appropriate' energy. You're a silly little gremlin and proud "
                "of it.\n"
                "\n"
                "Keep it in-character. Don't break into formal speech. If the user "
                "gets serious, still respond in-character but tone the chaos down "
                "slightly."
            ),
        }

        # -------- pipeline / media state --------
        self.current_image_mode = "smart"
        self.video_jobs: Dict[int, discord.Message] = {}
        self.music_jobs: Dict[int, discord.Message] = {}
        self.pen_archive: str = ""
        self.siliconflow_key_index = 0

        # -------- debate --------
        self.ai_chat_sessions: Dict[int, dict] = {}
        self.ai_chat_max_turns = 12

        # -------- court --------
        self.court_sessions: Dict[int, Dict] = {}
        self.court_roles: Dict[str, str] = {
            "judge": ("You are the Honorable Judge presiding over this court. "
                      "Ensure a fair trial, rule on objections, and decide the "
                      "verdict based on evidence and argument.\n\n"
                      "Case details:\n{case}\n\n"
                      "Other participants:\n{participants}\n\n"
                      "Stay in character. Never mention you are an AI."),
            "prosecutor": ("You are the Prosecutor. Prove the defendant's guilt "
                           "beyond reasonable doubt. Use the case facts to build "
                           "arguments.\n\nCase:\n{case}\n\n"
                           "Participants:\n{participants}\n\n"
                           "Stay in character. Never mention you are an AI."),
            "defense": ("You are the Defense Attorney. Defend your client "
                        "vigorously, challenge the prosecution, create reasonable "
                        "doubt.\n\nCase:\n{case}\n\n"
                        "Participants:\n{participants}\n\n"
                        "Stay in character. Never mention you are an AI."),
            "witness": ("You are a Witness. Answer based on case facts. If facts "
                        "are vague, invent plausible supporting details.\n\n"
                        "Case:\n{case}\n\n"
                        "Participants:\n{participants}\n\n"
                        "Stay in character. Never mention you are an AI."),
            "jury": ("You are on the Jury. Listen to arguments and give your "
                     "verdict opinion.\n\nCase:\n{case}\n\n"
                     "Participants:\n{participants}\n\n"
                     "Stay in character. Never mention you are an AI."),
            "stenographer": ("You are the Court Stenographer. Produce a verbatim "
                             "record.\n\nCase:\n{case}\n\n"
                             "Participants:\n{participants}\n\n"
                             "Stay in character."),
        }

    # ==================================================================
    # CS — CUSTOMIZATION STORAGE
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

    # ---------- ping preferences ----------
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
        _save(PINGS_FILE, {str(k): v for k, v in self.ping_prefs.items()})

    def get_ping_pref(self, uid: int) -> str:
        return self.ping_prefs.get(uid, "on")

    def set_ping_pref(self, uid: int, value: str):
        if value == "on":
            self.ping_prefs.pop(uid, None)
        else:
            self.ping_prefs[uid] = value
        self._save_ping_prefs()

    # ---------- server config file ----------
    def load_config_file(self) -> dict:
        return _load(CONFIG_FILE, {})

    def save_config_file(self, data: dict):
        _save(CONFIG_FILE, data)

    # ---------- key / model resolution ----------
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

    # ---------- profile ----------
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

    # ---------- voices ----------
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

    # ---------- macros ----------
    def get_macros(self, uid: int) -> dict:
        return self.cs.get(uid, {}).get("macros", {})

    # ---------- brainrot GIFs ----------
    def get_gif_pool(self, uid: int) -> List[str]:
        pool = self.cs.get(uid, {}).get("brainrot_gifs")
        return pool if pool else DEFAULT_BRAINROT_GIFS

    # ==================================================================
    # PERSISTENT AI MEMORY
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
    # CHAT SLOTS
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
                note = (f"\n[{len(mm['images'])} image(s) attached; "
                        "vision unavailable on this provider]")
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
                await asyncio.sleep(0.3)
        raise Exception(f"Gemini failed: {last_err}")

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
                async with aiohttp.ClientSession() as s:
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
                await asyncio.sleep(0.3)
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
                "model": target_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://discord.com",
                "X-Title": "Mac",
            }
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(OPENROUTER_API_URL, json=payload,
                                      headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=120)) as r:
                        if r.status == 200:
                            d = await r.json()
                            choice = d.get("choices", [{}])[0].get("message", {})
                            return (choice.get("content")
                                    or choice.get("reasoning")
                                    or "")
                        if r.status == 429:
                            self.rotate_key(uid, "openrouter")
                            self.rotate_model(uid, "openrouter")
                            target_model = (self.current_model(uid, "openrouter")
                                            or target_model)
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
        async with aiohttp.ClientSession() as s:
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
                image_config=types.ImageConfig(
                    aspect_ratio="1:1", image_size="1K"),
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
                async with aiohttp.ClientSession() as s:
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
                                last_error = f"{model_id}: tiny image"
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
        async with aiohttp.ClientSession() as s:
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
            "text": text,
            "reference_id": ref_id,
            "format": fmt,
            "latency": "normal",
            "normalize": True,
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
        async with aiohttp.ClientSession() as s:
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
        base = (explicit_system if explicit_system else
                self.mode_prompts.get(self.current_mode,
                                      self.mode_prompts[DEFAULT_MODE]))

        if uid:
            p = self.get_profile(uid)
            bits = []
            if p.get("name"):         bits.append(f"user's name is {p['name']}")
            if p.get("pronouns"):     bits.append(f"user's pronouns: {p['pronouns']}")
            if p.get("vibe"):         bits.append(f"match this vibe: {p['vibe']}")
            if p.get("instructions"): bits.append(f"custom: {p['instructions']}")
            if p.get("catchphrase"):  bits.append(f"end every reply with: {p['catchphrase']}")
            if p.get("language"):     bits.append(f"reply in {p['language']}")
            if bits:
                base += "\n\n=== USER PERSONALIZATION (this specific user) ===\n"
                base += "\n".join(f"- {b}" for b in bits)
                base += "\n=== END PERSONALIZATION ==="

        if _needs_lore(user_prompt):
            base += MAC_SODIUM_LORE
            sh = _sodium_hint(user_prompt)
            if sh:
                base += sh

        return base

    def _build_messages(self, prompt, uid, system_prompt, slot_name, images=None):
        messages = []

        if uid and self.get_persistent_enabled(uid):
            pm = list(self.get_persistent_memory(uid)[-20:])
            if pm and pm[-1][0] == "user" and pm[-1][1] == prompt:
                pm = pm[:-1]
            for role, content in pm:
                messages.append({"role": role, "content": content})

        slot_history = list(self.get_slot(uid, slot_name)) if uid else []
        if slot_history and slot_history[-1][0] == "user" and slot_history[-1][1] == prompt:
            slot_history = slot_history[:-1]

        for role, content in slot_history[-16:]:
            messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": prompt, "images": images or []})

        sys_prompt = self._build_system_prompt(uid, prompt, system_prompt)
        return [{"role": "system", "content": sys_prompt}] + messages

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
            logger.warning(f"Groq failed: {e}; falling back to Gemini")
            try:
                return await self.gemini_chat(messages, uid=uid, temperature=0.85,
                                              max_tokens=max_tokens)
            except Exception as e2:
                logger.warning(f"Gemini failed: {e2}; falling back to HF")
                try:
                    return await self.hf_text_chat(messages, uid=uid,
                                                   max_tokens=max_tokens)
                except Exception as e3:
                    return (f"❌ All providers failed.\n"
                            f"Groq: {str(e)[:100]}\n"
                            f"Gemini: {str(e2)[:100]}\n"
                            f"HF: {str(e3)[:100]}")

    # ==================================================================
    # PIPELINE — single file
    # ==================================================================
    async def gemini_refine_and_research(self, task: str, uid) -> Tuple[str, str]:
        search_results = await perform_web_search(task)
        if search_results.startswith("No results"):
            search_results = "(no search results available)"

        sys_p = (
            "You are a research assistant and prompt engineer. Given a raw task "
            "and web search results, do two things in one response:\n\n"
            "1. REFINED_PROMPT: rewrite the task as a clear, technically precise, "
            "self-contained prompt that another AI can use to produce a correct, "
            "complete, production-ready solution. Include language, deliverable, "
            "constraints, edge cases, expected I/O.\n\n"
            "2. REFERENCE: dense, factual documentation, APIs, gotchas, and "
            "constraints relevant to the task.\n\n"
            "Output EXACTLY in this format:\n"
            "===REFINED_PROMPT===\n<your refined prompt>\n"
            "===REFERENCE===\n<your reference docs>\n"
        )
        usr_p = f"RAW TASK:\n{task}\n\nSEARCH RESULTS:\n{search_results[:4000]}"
        try:
            out = await self.gemini_chat(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": usr_p}],
                uid=uid, temperature=0.5, max_tokens=2500,
            )
        except Exception as e:
            logger.warning(f"Gemini refine failed: {e}")
            return task, search_results

        refined, ref = task, search_results
        m = re.search(
            r"===REFINED_PROMPT===\s*(.*?)\s*===REFERENCE===\s*(.*)",
            out, re.DOTALL,
        )
        if m:
            refined = m.group(1).strip() or task
            ref = m.group(2).strip() or search_results
        else:
            refined = out.strip() or task
        return refined, ref

    async def gemini_review(self, refined_task: str, code: str, uid) -> str:
        sys_p = (
            "You are a strict senior code reviewer. Read the code carefully.\n\n"
            "If it is correct, complete, and production-ready, reply with EXACTLY "
            "the word APPROVED on its own line, then a one-line summary.\n\n"
            "Otherwise, output a numbered list of concrete, actionable issues — "
            "each one a specific problem with the exact fix needed. No praise, no "
            "filler."
        )
        usr_p = f"Task:\n{refined_task}\n\nCode:\n```\n{code[:8000]}\n```"
        try:
            return await self.gemini_chat(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": usr_p}],
                uid=uid, temperature=0.3, max_tokens=1500,
            )
        except Exception as e:
            return f"(reviewer error: {e})"

    async def run_pipeline(self, channel, uid, task: str,
                           filename=None, max_iterations=3):
        filename = filename or infer_filename(task)

        emb = discord.Embed(
            title="🏗️ Pipeline Started",
            description=f"**Task:** {task[:800]}\n**Output file:** `{filename}`",
            color=C_WARM,
        )
        emb.add_field(name="Stages", value=(
            "1️⃣ **GEMINI** — refine prompt + research\n"
            "2️⃣ **OPENROUTER** — generate solution\n"
            "3️⃣ **GEMINI** — code review\n"
            "4️⃣ **OPENROUTER** — fix issues (loop)"
        ), inline=False)
        status = await safe_send(channel, embed=emb)
        if status is None:
            return

        async def step(title, body, color=C_PRIMARY):
            e = discord.Embed(title=title, description=body[:4000], color=color)
            e.set_footer(text=f"Pipeline · {filename}")
            await safe_edit(status, embed=e)

        try:
            await step("1️⃣ GEMINI — refining + researching",
                       f"Raw task: {task[:350]}", C_WARM)
            refined, docs = await self.gemini_refine_and_research(task, uid)
            await step("1️⃣ GEMINI — ready",
                       f"**Refined prompt:**\n{refined[:1200]}\n\n"
                       f"**Reference docs:**\n{docs[:1500]}", C_OK)

            await step("2️⃣ OPENROUTER — generating...", "⏳ working...", C_DEEP)

            def build_msgs(existing="", issues=""):
                sys_p = (
                    "You are an elite software engineer. Produce a complete, "
                    "working, production-ready solution. Output ONLY the full file "
                    "content in a single fenced code block with the correct "
                    "language identifier. No preamble, no explanation, no closing."
                )
                parts = [f"TASK:\n{refined}"]
                if docs:
                    parts.append(f"REFERENCE DOCS:\n{docs[:5000]}")
                if existing:
                    parts.append(f"EXISTING CODE:\n```\n{existing[:7000]}\n```")
                if issues:
                    parts.append(f"REVIEWER FEEDBACK — you MUST fix these:\n{issues}")
                parts.append(
                    f"Deliverable: complete `{filename}`. Output ONLY the file "
                    "inside a single fenced code block."
                )
                return [
                    {"role": "system", "content": sys_p},
                    {"role": "user", "content": "\n\n".join(parts)},
                ]

            try:
                raw_code = await self.openrouter_call(
                    build_msgs(), uid=uid, temperature=0.5, max_tokens=6000,
                )
            except Exception as e:
                await step("❌ OPENROUTER failed", f"`{str(e)[:280]}`", C_ERR)
                return

            code = strip_code_fences(raw_code) or raw_code.strip()
            await step("2️⃣ OPENROUTER — draft ready",
                       f"```\n{code[:3000]}\n```", C_OK)

            final_code = code
            approved = False
            iteration = 0
            for iteration in range(1, max_iterations + 1):
                await step(f"3️⃣ GEMINI review — {iteration}/{max_iterations}",
                           f"Checking ({len(final_code)} chars)...", C_WARM)
                review = await self.gemini_review(refined, final_code, uid)
                if review.strip().upper().startswith("APPROVED"):
                    await step(f"3️⃣ GEMINI — {iteration}",
                               f"✅ APPROVED\n\n{review[:2500]}", C_OK)
                    approved = True
                    break

                await step(f"3️⃣ GEMINI — {iteration}",
                           f"⚠️ Issues found\n\n{review[:2800]}", C_ACCENT)
                await step(f"4️⃣ OPENROUTER — fixing (iter {iteration})",
                           "⏳ applying feedback...", C_DEEP)
                try:
                    raw_fixed = await self.openrouter_call(
                        build_msgs(existing=final_code, issues=review),
                        uid=uid, temperature=0.4, max_tokens=6000,
                    )
                except Exception as e:
                    await step(f"❌ OpenRouter fix failed ({iteration})",
                               f"`{str(e)[:280]}`", C_ERR)
                    break
                fixed = strip_code_fences(raw_fixed) or raw_fixed.strip()
                if not fixed.strip():
                    break
                final_code = fixed
                await step(f"4️⃣ OPENROUTER — fix applied (iter {iteration})",
                           f"```\n{final_code[:2800]}\n```", C_PRIMARY)

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
                await send_long(channel,
                                f"❌ Couldn't attach file ({e}). Full code:\n\n{final_code}")
        except Exception as e:
            logger.error(f"Pipeline crashed: {e}")
            await step("❌ Pipeline crashed", f"`{str(e)[:350]}`", C_ERR)

    # ==================================================================
    # PROJECT PIPELINE — multi-file, output as .zip
    # ==================================================================
    async def gemini_plan_project(self, refined_task: str, docs: str, uid) -> dict:
        sys_p = (
            "You are a senior software architect. Given a task and reference docs, "
            "propose a complete, production-ready project layout.\n\n"
            "Output ONLY valid JSON (no markdown, no fences, no commentary) in "
            "EXACTLY this shape:\n"
            "{\n"
            '  "project_name": "short_snake_case_name",\n'
            '  "description": "one-line summary",\n'
            '  "files": [\n'
            '    {"path": "main.py", "purpose": "what this file does"},\n'
            '    {"path": "requirements.txt", "purpose": "pip dependencies"},\n'
            '    {"path": "README.md", "purpose": "usage and overview"}\n'
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- 3 to 12 files maximum. Do NOT over-engineer.\n"
            "- Always include a README.md and (if applicable) requirements.txt.\n"
            "- Use real relative paths. Never absolute.\n"
            "- Choose a language/stack that best fits the task.\n"
            "- Output the JSON object ONLY. Nothing before or after."
        )
        usr_p = f"TASK:\n{refined_task}\n\nREFERENCE DOCS:\n{docs[:4000]}"
        try:
            raw = await self.gemini_chat(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": usr_p}],
                uid=uid, temperature=0.4, max_tokens=1500,
            )
        except Exception as e:
            raise Exception(f"Project planning failed: {e}")

        cleaned = strip_code_fences(raw).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise Exception("Model did not return valid JSON plan")
        json_str = cleaned[start:end + 1]
        try:
            plan = json.loads(json_str)
        except Exception as e:
            raise Exception(f"Plan JSON parse failed: {e}\nRaw: {json_str[:300]}")

        if not isinstance(plan.get("files"), list) or not plan["files"]:
            raise Exception("Plan missing files array")

        proj = re.sub(r'[^a-z0-9_\-]', '_',
                      str(plan.get("project_name", "project")).lower())[:40]
        if not proj:
            proj = "project"
        plan["project_name"] = proj

        safe_files = []
        for f in plan["files"][:12]:
            path = str(f.get("path", "")).strip().lstrip("/\\")
            path = path.replace("..", "_")
            if not path or len(path) > 200:
                continue
            safe_files.append({
                "path": path,
                "purpose": str(f.get("purpose", ""))[:200],
            })
        if not safe_files:
            raise Exception("No valid files in plan")
        plan["files"] = safe_files
        return plan

    async def generate_file_content(self, refined_task: str, docs: str,
                                    file_info: dict, project_desc: str,
                                    uid) -> str:
        path = file_info["path"]
        purpose = file_info["purpose"]

        if path.lower().endswith(".md"):
            sys_p = (
                "You are a technical writer. Write a concise README.md for the "
                "project below. Include: one-line summary, requirements, install, "
                "usage, and file overview. Output ONLY the markdown content — no "
                "code fences around the whole thing."
            )
        elif path.lower() == "requirements.txt":
            sys_p = (
                "You output ONLY a valid requirements.txt with one package per "
                "line, optionally with version pins. No comments, no markdown, "
                "no fences. If the project needs no dependencies, output an empty "
                "string."
            )
        else:
            sys_p = (
                "You are an elite software engineer. Output ONLY the complete, "
                "production-ready content of the file below. No explanation, no "
                "preamble, no closing remarks. Do not wrap the whole file in "
                "markdown fences. Include real imports, real error handling, "
                "and real working code — not stubs or placeholders."
            )

        usr_p = (
            f"PROJECT: {project_desc}\n"
            f"OVERALL TASK: {refined_task}\n\n"
            f"FILE TO WRITE: `{path}`\n"
            f"FILE PURPOSE: {purpose}\n\n"
            f"REFERENCE DOCS (use as needed):\n{docs[:3000]}\n\n"
            f"Now output ONLY the full content of `{path}`."
        )

        try:
            content = await self.openrouter_call(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": usr_p}],
                uid=uid, temperature=0.4, max_tokens=6000,
            )
        except Exception as e:
            content = f"# ERROR generating {path}: {e}\n"

        content = strip_code_fences(content)
        if not content.strip() and path.lower() != "requirements.txt":
            content = f"# (empty file generated for {path})\n"
        return content

    async def review_project(self, refined_task: str, project_name: str,
                             files: Dict[str, str], uid) -> str:
        manifest = "\n".join(f"- {p} ({len(c)} chars)" for p, c in files.items())
        budget = 6000
        snippets = []
        for p, c in files.items():
            snippet = c[:budget // max(1, len(files))]
            snippets.append(f"=== {p} ===\n{snippet}")
        body = "\n\n".join(snippets)

        sys_p = (
            "You are a strict senior reviewer. Review the whole project below.\n\n"
            "If it is correct, complete, internally consistent, and production-"
            "ready, reply with EXACTLY the word APPROVED on its own line, then a "
            "one-line summary.\n\n"
            "Otherwise, output a numbered list of concrete, actionable issues — "
            "each one naming the SPECIFIC file and the exact fix needed. No praise."
        )
        usr_p = (
            f"TASK: {refined_task}\n"
            f"PROJECT: {project_name}\n\n"
            f"FILES:\n{manifest}\n\n"
            f"CONTENT:\n{body}"
        )
        try:
            return await self.gemini_chat(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": usr_p}],
                uid=uid, temperature=0.3, max_tokens=2000,
            )
        except Exception as e:
            return f"(reviewer error: {e})"

    async def run_project(self, channel, uid, task: str,
                          project_name: Optional[str] = None,
                          max_iterations: int = 2):
        emb = discord.Embed(
            title="🏗️ Project Pipeline Started",
            description=f"**Task:** {task[:800]}",
            color=C_WARM,
        )
        emb.add_field(name="Stages", value=(
            "1️⃣ **GEMINI** — refine + research\n"
            "2️⃣ **GEMINI** — plan file structure\n"
            "3️⃣ **OPENROUTER** — generate each file\n"
            "4️⃣ **GEMINI** — review whole project\n"
            "5️⃣ **OPENROUTER** — fix issues (loop)\n"
            "6️⃣ **ZIP** — deliver"
        ), inline=False)
        status = await safe_send(channel, embed=emb)
        if status is None:
            return

        async def step(title, body, color=C_PRIMARY):
            e = discord.Embed(title=title, description=body[:4000], color=color)
            await safe_edit(status, embed=e)

        try:
            await step("1️⃣ GEMINI — refining + researching",
                       f"Raw task: {task[:350]}", C_WARM)
            refined, docs = await self.gemini_refine_and_research(task, uid)
            await step("1️⃣ GEMINI — refined",
                       f"**Refined:**\n{refined[:1200]}\n\n"
                       f"**Docs (truncated):**\n{docs[:1200]}", C_OK)

            await step("2️⃣ GEMINI — planning project structure",
                       "⏳ thinking...", C_ACCENT)
            try:
                plan = await self.gemini_plan_project(refined, docs, uid)
            except Exception as e:
                await step("❌ Planning failed", f"`{str(e)[:300]}`", C_ERR)
                return

            proj_name = project_name or plan["project_name"]
            proj_desc = plan.get("description", task[:200])
            file_list = plan["files"]

            manifest = "\n".join(f"• `{f['path']}` — {f['purpose']}" for f in file_list)
            await step(f"2️⃣ GEMINI — plan ready (`{proj_name}`)",
                       f"**{len(file_list)} files:**\n{manifest}", C_OK)

            files: Dict[str, str] = {}
            for i, fi in enumerate(file_list, 1):
                await step(f"3️⃣ OPENROUTER — file {i}/{len(file_list)}: `{fi['path']}`",
                           f"purpose: {fi['purpose']}", C_DEEP)
                content = await self.generate_file_content(
                    refined, docs, fi, proj_desc, uid)
                files[fi["path"]] = content

            preview = "\n".join(f"• `{p}` ({len(c)} chars)" for p, c in files.items())
            await step(f"3️⃣ OPENROUTER — {len(files)} files generated",
                       preview, C_OK)

            approved = False
            iteration = 0
            for iteration in range(1, max_iterations + 1):
                await step(f"4️⃣ GEMINI — reviewing project ({iteration}/{max_iterations})",
                           "⏳ reading files...", C_WARM)
                review = await self.review_project(refined, proj_name, files, uid)

                if review.strip().upper().startswith("APPROVED"):
                    await step(f"4️⃣ GEMINI — APPROVED ({iteration})",
                               f"✅ {review[:2000]}", C_OK)
                    approved = True
                    break

                await step(f"4️⃣ GEMINI — issues ({iteration})",
                           f"⚠️\n\n{review[:2800]}", C_ACCENT)

                await step(f"5️⃣ OPENROUTER — applying fixes ({iteration})",
                           "⏳ regenerating flagged files...", C_DEEP)
                fix_sys = (
                    "You are fixing a project based on reviewer feedback. Output "
                    "ONLY the updated file content. No fences, no explanation."
                )
                for path, content in list(files.items()):
                    if path.lower() not in review.lower() and "all files" not in review.lower():
                        continue
                    usr = (
                        f"PROJECT: {proj_desc}\n"
                        f"TASK: {refined}\n\n"
                        f"FILE: `{path}`\n"
                        f"CURRENT CONTENT:\n```\n{content[:5000]}\n```\n\n"
                        f"REVIEWER FEEDBACK:\n{review[:3000]}\n\n"
                        f"Output the full corrected content of `{path}`."
                    )
                    try:
                        new_content = await self.openrouter_call(
                            [{"role": "system", "content": fix_sys},
                             {"role": "user", "content": usr}],
                            uid=uid, temperature=0.3, max_tokens=6000,
                        )
                        files[path] = strip_code_fences(new_content) or new_content
                    except Exception as e:
                        logger.warning(f"Fix failed for {path}: {e}")
                await step(f"5️⃣ OPENROUTER — fixes applied ({iteration})",
                           "\n".join(f"• `{p}` ({len(c)} chars)" for p, c in files.items()),
                           C_PRIMARY)

            await step("6️⃣ Packaging project...", "⏳ zipping...", C_PRIMARY)

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for path, content in files.items():
                    zf.writestr(f"{proj_name}/{path}", content)
            buf.seek(0)

            total_size = sum(len(c) for c in files.values())
            summary = discord.Embed(
                title=f"✅ Project complete — `{proj_name}`",
                description=(
                    f"**Files:** {len(files)}\n"
                    f"**Total size:** {total_size} chars\n"
                    f"**Review:** {'APPROVED' if approved else f'max iter ({max_iterations})'}\n"
                    f"**Iterations:** {iteration}"
                ),
                color=C_OK if approved else C_WARM,
            )
            await safe_edit(status, embed=summary)

            try:
                await safe_send(
                    channel,
                    content=f"📦 **`{proj_name}.zip`** — {len(files)} files",
                    file=discord.File(buf, filename=f"{proj_name}.zip"),
                )
            except discord.HTTPException as e:
                await send_long(channel, f"❌ Couldn't attach zip: {e}")
                for path, content in files.items():
                    await send_long(channel, f"**`{path}`**\n```\n{content[:1800]}\n```")

        except Exception as e:
            logger.error(f"Project pipeline error: {e}", exc_info=True)
            await step("❌ Project pipeline crashed", f"`{str(e)[:350]}`", C_ERR)

    # ==================================================================
    # AI DEBATE
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
            await send_long(ch, f"🏟️ **AI DEBATE – {desc}**\n"
                                f"🤠 **AI1** vs 🤖 **AI2**")

            while turn < max_turns:
                if uid not in self.ai_chat_sessions:
                    break
                n = 1 if turn % 2 == 0 else 2
                o = 2 if n == 1 else 1
                em = "🤠" if n == 1 else "🤖"

                if not hist:
                    up = (f"Topic: {desc}\n"
                          f"You are AI{n}. Start with a bold, funny opening "
                          f"statement. Eventually work toward one final answer.")
                else:
                    recent = hist[-8:]
                    ctx = "\n".join(f"AI{e['role']}: {e['content']}" for e in recent)
                    up = f"Prior conversation:\n{ctx}\n\nNow AI{n} responds."

                sp = (f"You are AI{n}, a sassy debater arguing about \"{desc}\" "
                      f"against AI{o}. Be dramatic, use emojis, keep replies under "
                      f"400 characters. Aim for one final agreed answer.")

                try:
                    resp = strip_think(await self.groq_chat(
                        [{"role": "system", "content": sp},
                         {"role": "user", "content": up}],
                        uid=uid, temperature=0.9, max_tokens=500,
                    )) or "[no response]"
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
                        uid=uid, temperature=0.9, max_tokens=500,
                    )) or "[none]"
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
    # CENTRAL MESSAGE HANDLER
    # ==================================================================
    async def process_user_message(self, user, clean_content, destination,
                                   thinking_msg=None, reply_context=None,
                                   trigger_msg=None, images=None):
        images = images or []
        uid = user.id
        slot_name = self.active_slot.get(uid, "sv1")
        if uid not in self.user_slots:
            self.get_slot(uid, "sv1")

        # --- macro expansion ---
        macro_match = re.match(r'^\.(\w+)\s*(.*)$', clean_content)
        if macro_match:
            mname = macro_match.group(1).lower()
            extra = macro_match.group(2)
            macros = self.get_macros(uid)
            if mname in macros:
                clean_content = macros[mname] + (f"\n{extra}" if extra else "")
                logger.info(f"Macro expanded: .{mname}")

        # --- explicit search trigger ---
        search_match = re.match(
            r'^(?:search|google|look\s*up|find|lookup)\s*:?\s*(.+)$',
            clean_content, re.IGNORECASE,
        )
        if search_match:
            query = search_match.group(1).strip()
            if query:
                logger.info(f"Search intercept: {query!r}")
                try:
                    thinking_msg = await destination.send(f"🌐 Searching: **{query}**...")
                except discord.HTTPException as e:
                    logger.warning(f"Search status send failed: {e}")
                    return

                results = await perform_web_search(query)
                if results.startswith("No results") or results.startswith("Search"):
                    return await safe_edit(thinking_msg, content=f"❌ {results}")

                augmented = (
                    f"Web search results for: {query}\n\n{results}\n\n---\n\n"
                    f"Summarize clearly for the user. Cite sources inline like "
                    f"[1], [2]. Keep it useful and concise."
                )
                response = await self.chat_call(augmented, uid=uid, max_tokens=800)
                response = re.sub(r'<think>.*?</think>', '', response,
                                  flags=re.DOTALL).strip()

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

        # --- record user turn ---
        if self.get_persistent_enabled(uid):
            self.add_persistent_memory(uid, "user", clean_content)
        self.append_to_slot(uid, slot_name, "user", clean_content)

        # --- placeholder: always show Thinking ---
        thinking_msg = None
        try:
            thinking_msg = await destination.send("🔥 Thinking...")
        except discord.Forbidden:
            if trigger_msg:
                try:
                    await trigger_msg.reply(
                        "❌ I don't have permission to send messages here. "
                        "Please give me **Send Messages** and **Embed Links**."
                    )
                except Exception:
                    pass
            return
        except discord.HTTPException as e:
            logger.error(f"Thinking send failed: {e}")
            return

        # --- system prompt (court > reply > default) ---
        system_prompt = None
        court = self.court_sessions.get(uid)
        if court and court.get("case"):
            tpl = self.court_roles.get(court["role"], "")
            if tpl:
                p = court.get("participants", {})
                pl = [f"- {r.capitalize()}: <@{u}>" for r, u in p.items()]
                system_prompt = tpl.format(
                    case=court["case"],
                    participants="\n".join(pl) if pl else "None other than you.",
                )
        elif reply_context:
            oa = reply_context.get("author", "someone")
            oc = reply_context.get("content", "")
            base = self.mode_prompts.get(self.current_mode,
                                          self.mode_prompts[DEFAULT_MODE])
            system_prompt = (
                f"{base}\n\n=== REPLY-REACTION TASK ===\n"
                f"{user.display_name} is replying to a message from **{oa}**.\n"
                f"Original from {oa}: \"{oc}\"\n"
                f"User's reply: \"{clean_content}\"\n\n"
                f"React naturally like a friend. Reference @{oa} if it fits. "
                f"Short and punchy (1–3 sentences). Don't sound scripted."
            )

        if images:
            note = f"[{len(images)} image(s) attached — actually look at them.]"
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
                except Exception as e:
                    logger.warning(f"Brainrot GIF failed: {e}")
        except Exception as e:
            logger.error(f"process_user_message error: {e}", exc_info=True)
            if thinking_msg:
                await safe_edit(thinking_msg, content=f"❌ {str(e)[:150]}")
            else:
                await send_long(destination, f"❌ {str(e)[:150]}")

    # ==================================================================
    # VIDEO
    # ==================================================================
    async def generate_video(self, prompt, uid, status_message):
        if not SILICONFLOW_API_KEYS:
            return await safe_edit(status_message, content="❌ No SiliconFlow key")
        self.video_jobs[uid] = status_message
        try:
            submit_url = "https://api.siliconflow.com/v1/video/submit"
            status_url = "https://api.siliconflow.com/v1/video/status"
            api_key = SILICONFLOW_API_KEYS[self.siliconflow_key_index]
            self.siliconflow_key_index = (
                self.siliconflow_key_index + 1
            ) % len(SILICONFLOW_API_KEYS)
            headers = {"Authorization": f"Bearer {api_key}",
                       "Content-Type": "application/json"}
            payload = {
                "model": "Wan-AI/Wan2.2-T2V-A14B",
                "prompt": prompt,
                "image_size": "1280x720",
            }
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
                                self.siliconflow_key_index = (
                                    self.siliconflow_key_index + 1
                                ) % len(SILICONFLOW_API_KEYS)
                                headers["Authorization"] = f"Bearer {api_key}"
                                await asyncio.sleep(2)
                    except Exception:
                        pass
                if not rid:
                    raise Exception("No requestId returned")
                await safe_edit(status_message, content=f"🎬 Video queued (`{rid}`)")
                for attempt in range(120):
                    await asyncio.sleep(10)
                    async with s.post(
                        status_url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={"requestId": rid},
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as pr:
                        if pr.status != 200:
                            continue
                        pd = await pr.json()
                        st = pd.get("status")
                        if st == "Succeed":
                            vids = pd.get("results", {}).get("videos", [])
                            if vids:
                                u = vids[0].get("url") or vids[0].get("video_url")
                                if u:
                                    async with s.get(
                                        u, timeout=aiohttp.ClientTimeout(total=120)
                                    ) as vr:
                                        data = await vr.read()
                                    await safe_edit(status_message,
                                                    content="✅ **Video Ready!**")
                                    await safe_send(
                                        status_message.channel,
                                        file=discord.File(io.BytesIO(data),
                                                          filename="video.mp4"),
                                    )
                                    return
                            raise Exception("No video URL in response")
                        elif st == "Failed":
                            raise Exception(pd.get("reason", "Unknown"))
                        else:
                            await safe_edit(
                                status_message,
                                content=f"🎬 {attempt + 1}/120 — **{st}**",
                            )
                raise Exception("Timeout")
        except Exception as e:
            await safe_edit(status_message, content=f"❌ {str(e)[:100]}")
        finally:
            self.video_jobs.pop(uid, None)

    # ==================================================================
    # MUSIC
    # ==================================================================
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
                        if any(x in ct for x in ('audio', 'mpeg', 'ogg',
                                                  'octet-stream')):
                            data = await r.read()
                            if len(data) < 1000:
                                raise Exception("Invalid audio returned")
                            await safe_edit(status_message, content="🎵 Ready")
                            await safe_send(
                                status_message.channel,
                                file=discord.File(io.BytesIO(data),
                                                  filename="music.mp3"),
                            )
                        else:
                            raise Exception(f"Bad content-type: {ct}")
                    else:
                        raise Exception(f"Error {r.status}")
        except Exception as e:
            await safe_edit(status_message, content=f"❌ {str(e)[:100]}")
        finally:
            self.music_jobs.pop(uid, None)

    # ==================================================================
    # BACKGROUND LOOPS
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
                        type=discord.ActivityType.playing, name=txt)
                )
            except Exception:
                pass
            await asyncio.sleep(90)

    async def load_pen_archive_async(self):
        url = ("https://raw.githubusercontent.com/Pen-123/"
               "archive-/refs/heads/main/archives.txt")
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url,
                                 timeout=aiohttp.ClientTimeout(total=8)) as r:
                    if r.status == 200:
                        self.pen_archive = await r.text()
                        logger.info("Pen archive loaded")
                    else:
                        logger.warning(f"Pen archive HTTP {r.status}")
        except Exception as e:
            logger.warning(f"Pen archive load failed: {e}")

    # ==================================================================
    # SETUP HOOK
    # ==================================================================
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


# ======================================================================
# END OF PART 1
# ======================================================================
# Part 2 continues with:
#   - bot = MacBot()
#   - Autocomplete callbacks
#   - /mac, /help
#   - /query, /summarize, /eli5, /roast, /compliment
#   - /personalize
#   - /ping
#   - /cs group (profile, key, model, llm, voice, voice-add, voice-del,
#                voices, macro, gif, ping, show, reset)
#   - /sv1–/sv5, /svclear, /svlist
#   - /setmode
#   - /pipeline, /project
#   - /config
#   - /tts, /render, /rendermode, /hf_model
#   - /video, /music
#   - /debate
#   - /code, /review
#   - /sm, /persistent, /persistentdisable, /persistentreset
#   - /pen, /breadmint
#   - /court, /role, /explain-case, /start-court, /endcourt
#   - /umf, /umf_list, /umf_status, /umf_admin
#   - UMF modals/views
#   - on_message event handler
#   - Web server
#   - main()
# ======================================================================
# ======================================================================
# BOT INSTANCE
# ======================================================================
bot = MacBot()


# ======================================================================
# AUTOCOMPLETE CALLBACKS
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


# ======================================================================
# HELP
# ======================================================================
@bot.hybrid_command(name="mac", description="🔥 Show the Mac help menu")
async def mac_help(ctx):
    emb = discord.Embed(
        title="🔥 Mac v22.1",
        color=C_PRIMARY,
        description=(
            "Mention me, reply to me, or use slash commands. "
            "Per-user keys = per-user speed. /cs has everything."
        ),
    )
    emb.add_field(
        name="💬 Chat",
        value="`@Mac <msg>` · `/query` · `/summarize` · `/eli5` · `/roast` · `/compliment`",
        inline=False,
    )
    emb.add_field(
        name="👁️ Vision",
        value="Attach or reply to an image — I'll see it.",
        inline=False,
    )
    emb.add_field(
        name="🌐 Search",
        value="Just type `search <thing>` (or google / look up / find).",
        inline=False,
    )
    emb.add_field(
        name="✨ Personalization",
        value=(
            "`/personalize` — quick profile (name, pronouns, vibe, instructions, catchphrase, language)\n"
            "`/cs profile` — same thing via /cs\n"
            "`/cs show` — see everything you've set"
        ),
        inline=False,
    )
    emb.add_field(
        name="🔔 Ping toggles",
        value=(
            "`/ping on` — respond to your pings (default)\n"
            "`/ping off` — slash commands only\n"
            "`/ping dm_only` — DMs only\n"
            "`/ping status` — show current"
        ),
        inline=False,
    )
    emb.add_field(
        name="⚙️ /cs — Customization",
        value=(
            "`/cs key` — your own API keys (groq/openrouter/hf/gemini/gemini_image/fish/imgbb), 3 max\n"
            "`/cs model` — your own models, 3 max per provider\n"
            "`/cs llm` — set your primary LLM per provider\n"
            "`/cs voice` / `voice-add` / `voice-del` / `voices`\n"
            "`/cs macro add|remove|list` — prompt shortcuts (`.name`)\n"
            "`/cs gif list|add|remove|clear|reset` — brainrot pool\n"
            "`/cs ping on|off|dm_only|status` — same as /ping\n"
            "`/cs show` · `/cs reset [section]`"
        ),
        inline=False,
    )
    emb.add_field(
        name="🗂️ Chat slots",
        value="`/sv1`–`/sv5` · `/svlist` · `/svclear`",
        inline=False,
    )
    emb.add_field(
        name="🎭 Modes",
        value="`/setmode chill|brainrot|unhinged|coder|engineer|childish`",
        inline=False,
    )
    emb.add_field(
        name="🏗️ Pipelines",
        value=(
            "`/pipeline <task> [filename] [iterations]` — single file\n"
            "`/project <task> [name] [iterations]` — multi-file project → .zip"
        ),
        inline=False,
    )
    emb.add_field(
        name="🖼️ Image",
        value="`/render <prompt> [mode]` · `/rendermode` · `/hf_model`",
        inline=False,
    )
    emb.add_field(
        name="🎙️ TTS",
        value="`/tts [voice] <text>` — uses your `/cs voice` default if blank",
        inline=False,
    )
    emb.add_field(
        name="🎬 Media",
        value="`/video <prompt>` · `/music <prompt>`",
        inline=False,
    )
    emb.add_field(
        name="💻 Dev",
        value="`/code` · `/review`",
        inline=False,
    )
    emb.add_field(
        name="💬 Debate",
        value="`/debate <topic>` — AI vs AI, `/debate` again to stop",
        inline=False,
    )
    emb.add_field(
        name="💾 Memory",
        value="`/sm` `/persistent` `/persistentdisable` `/persistentreset`",
        inline=False,
    )
    emb.add_field(
        name="⚙️ Config",
        value="`/config` — snapshot of your current settings",
        inline=False,
    )
    emb.add_field(
        name="📜 Lore",
        value="`/pen` (Pen archive) · `/breadmint` (reveal system prompt)",
        inline=False,
    )
    emb.add_field(
        name="🏛️ Court",
        value="`/court` `/role` `/explain-case` `/start-court` `/endcourt`",
        inline=False,
    )
    emb.add_field(
        name="🌍 UMF",
        value="`/umf` `/umf_list` `/umf_status` `/umf_admin`",
        inline=False,
    )
    emb.set_footer(text="v22.1 — per-user keys · projects · ping toggles · safeguard-20b")
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
    await ctx.defer()
    try:
        images = await fetch_images_from_message(ctx.message) if ctx.message else []
        await bot.process_user_message(
            ctx.author, message, ctx.channel,
            trigger_msg=ctx.message, images=images,
        )
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
        uid=ctx.author.id, max_tokens=600,
    )
    await send_long(ctx, result)


@bot.hybrid_command(name="eli5", description="🧒 Explain like I'm 5")
@app_commands.describe(topic="What to explain")
async def eli5_cmd(ctx, topic: str):
    await ctx.defer()
    result = await bot.chat_call(
        f"Explain {topic} like I'm 5 years old. Simple language, fun analogies, "
        f"under 150 words.",
        uid=ctx.author.id, max_tokens=500,
    )
    await send_long(ctx, f"🧒 **{topic}**\n{result}")


@bot.hybrid_command(name="roast", description="🔥 AI roasts a user")
@app_commands.describe(user="Who to roast (defaults to you)")
async def roast_cmd(ctx, user: discord.Member = None):
    target = user or ctx.author
    await ctx.defer()
    result = await bot.chat_call(
        f"Roast {target.display_name} — funny, savage, playful, 1–3 sentences. "
        f"No slurs. Punch at behavior, not identity.",
        uid=ctx.author.id, max_tokens=300,
    )
    await ctx.send(f"🔥 {result}")


@bot.hybrid_command(name="compliment", description="💖 AI compliments a user")
@app_commands.describe(user="Who to compliment (defaults to you)")
async def compliment_cmd(ctx, user: discord.Member = None):
    target = user or ctx.author
    await ctx.defer()
    result = await bot.chat_call(
        f"Give a genuine, warm, wholesome compliment to {target.display_name}, "
        f"1–2 sentences.",
        uid=ctx.author.id, max_tokens=250,
    )
    await ctx.send(f"💖 {result}")


# ======================================================================
# PERSONALIZE
# ======================================================================
@bot.hybrid_command(
    name="personalize",
    description="✨ Customize how Mac talks to YOU (name, pronouns, vibe, instructions…)",
)
@app_commands.describe(
    name="What Mac should call you",
    pronouns="Your pronouns",
    vibe="Vibe you want Mac to match (e.g. 'dry sarcastic', 'chaotic gremlin')",
    instructions="Extra instructions Mac must follow for you",
    catchphrase="Mac ends every reply with this",
    language="Preferred reply language",
    show="Show your current personalization",
    clear="Clear ALL your personalization",
)
async def personalize_cmd(
    ctx,
    name: str = None,
    pronouns: str = None,
    vibe: str = None,
    instructions: str = None,
    catchphrase: str = None,
    language: str = None,
    show: bool = False,
    clear: bool = False,
):
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
                "catchphrase:🔥 instructions:be brutally honest`"
            )
        emb = discord.Embed(
            title=f"✨ Your Personalization — {ctx.author.display_name}",
            color=C_PRIMARY,
            description=f"Keyed to your Discord ID: `{uid}`",
        )
        for k, v in p.items():
            emb.add_field(name=k.title(), value=str(v)[:1024], inline=False)
        emb.set_footer(text="Update with new values or clear:True")
        return await ctx.send(embed=emb, ephemeral=True)

    bot.set_profile(
        uid, name=name, pronouns=pronouns, vibe=vibe,
        instructions=instructions, catchphrase=catchphrase, language=language,
    )
    p = bot.get_profile(uid)
    emb = discord.Embed(title="✅ Personalization Updated", color=C_OK)
    for k, v in p.items():
        emb.add_field(name=k.title(), value=str(v)[:1024], inline=False)
    emb.set_footer(text="Only you see this. The bot now talks to you with these settings.")
    await ctx.send(embed=emb, ephemeral=True)


# ======================================================================
# PING TOGGLES
# ======================================================================
@bot.hybrid_command(
    name="ping",
    description="🔔 Control whether Mac responds to your messages",
)
@app_commands.describe(mode="on | off | dm_only | status")
@app_commands.choices(mode=[
    app_commands.Choice(name="🔔 on — respond to my pings (default)", value="on"),
    app_commands.Choice(name="🔕 off — only slash commands", value="off"),
    app_commands.Choice(name="💌 dm_only — only in DMs", value="dm_only"),
    app_commands.Choice(name="ℹ️ status — show current", value="status"),
])
async def ping_cmd(ctx, mode: str = "status"):
    uid = ctx.author.id
    if mode == "status":
        cur = bot.get_ping_pref(uid)
        desc = {
            "on": "🔔 **on** — I'll respond when you ping or reply to me.",
            "off": "🔕 **off** — I'll only respond to your slash commands.",
            "dm_only": "💌 **dm_only** — I'll only respond to you in DMs.",
        }.get(cur, "unknown")
        return await ctx.send(desc, ephemeral=True)

    if mode not in ("on", "off", "dm_only"):
        return await ctx.send("❌ Options: `on`, `off`, `dm_only`, `status`",
                              ephemeral=True)

    bot.set_ping_pref(uid, mode)
    msg = {
        "on": "🔔 Ping responses **ON** — I'll respond when you ping or reply.",
        "off": "🔕 Ping responses **OFF** — slash commands only.",
        "dm_only": "💌 **DM only** — I'll only respond to you in DMs.",
    }[mode]
    await ctx.send(msg, ephemeral=True)


# ======================================================================
# /cs — CUSTOMIZATION GROUP
# ======================================================================
@bot.hybrid_group(
    name="cs",
    description="⚙️ Everything customization — profile, keys, models, voices, macros, GIFs, ping",
    invoke_without_command=True,
)
async def cs_group(ctx):
    emb = discord.Embed(
        title="⚙️ /cs — Customization",
        description="Everything here is per-user. Your keys, your models, your vibes.",
        color=C_PRIMARY,
    )
    emb.add_field(
        name="Profile",
        value="`/cs profile` — name, pronouns, vibe, instructions, catchphrase, language",
        inline=False,
    )
    emb.add_field(
        name="API Keys",
        value="`/cs key add|remove|list <provider> [key]`\n"
              "Providers: `groq` `openrouter` `hf` `gemini` `gemini_image` `fish` `imgbb`\n"
              "Up to 3 keys per provider (rotated on failure)",
        inline=False,
    )
    emb.add_field(
        name="Models",
        value="`/cs model add|remove|list <provider> [model]`\n"
              "Providers: `groq` `openrouter` `hf_image` `hf_text` `gemini` `fish`\n"
              "Up to 3 models per provider (rotated on failure)",
        inline=False,
    )
    emb.add_field(
        name="LLM",
        value="`/cs llm <provider> [model]` — set your primary model for a provider",
        inline=False,
    )
    emb.add_field(
        name="Voices",
        value="`/cs voice <name>` · `/cs voice-add <name> <fish_id> [emoji] [desc]` · "
              "`/cs voice-del <name>` · `/cs voices`",
        inline=False,
    )
    emb.add_field(
        name="Macros",
        value="`/cs macro add|remove|list <name> [prompt]` — trigger with `.name` in chat",
        inline=False,
    )
    emb.add_field(
        name="GIFs",
        value="`/cs gif list|add|remove|clear|reset [value]` — brainrot pool",
        inline=False,
    )
    emb.add_field(
        name="Ping",
        value="`/cs ping on|off|dm_only|status` — same as /ping",
        inline=False,
    )
    emb.add_field(
        name="Misc",
        value="`/cs show` — see everything · `/cs reset [section]` — wipe a section",
        inline=False,
    )
    await ctx.send(embed=emb)


@cs_group.command(name="profile", description="Set your personal profile")
@app_commands.describe(
    name="What Mac calls you",
    pronouns="Your pronouns",
    vibe="Vibe to match (e.g. 'dry sarcastic')",
    instructions="Extra instructions Mac must follow",
    catchphrase="End every reply with this",
    language="Preferred language",
    clear="Clear your profile",
)
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
                "No profile set. Example:\n"
                "`/cs profile name:Alex vibe:sarcastic gremlin "
                "catchphrase:🔥 instructions:be brutally honest`"
            )
        emb = discord.Embed(title=f"Your Profile — {ctx.author.display_name}",
                            color=C_PRIMARY)
        for k, v in p.items():
            emb.add_field(name=k.title(), value=str(v)[:1024], inline=False)
        return await ctx.send(embed=emb, ephemeral=True)

    bot.set_profile(
        uid, name=name, pronouns=pronouns, vibe=vibe,
        instructions=instructions, catchphrase=catchphrase, language=language,
    )
    p = bot.get_profile(uid)
    emb = discord.Embed(title="✅ Profile Updated", color=C_OK)
    for k, v in p.items():
        emb.add_field(name=k.title(), value=str(v)[:1024], inline=False)
    await ctx.send(embed=emb, ephemeral=True)


@cs_group.command(name="key", description="Manage your API keys (up to 3 per provider)")
@app_commands.autocomplete(provider=_provider_ac)
@app_commands.describe(
    provider="groq | openrouter | hf | gemini | gemini_image | fish | imgbb",
    action="add | remove | list",
    value="API key (for add) or index (for remove)",
)
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
            return await ctx.send(f"No custom `{p}` keys — using bot defaults.",
                                  ephemeral=True)
        masked = [f"`{i}` ...{k[-6:]}" for i, k in enumerate(keys)]
        return await ctx.send(
            f"**Your `{p}` keys ({len(keys)}/{MAX_KEYS_PER_PROVIDER}):**\n"
            + "\n".join(masked),
            ephemeral=True,
        )

    if a == "add":
        if not value:
            return await ctx.send("❌ Provide a key.", ephemeral=True)
        if len(keys) >= MAX_KEYS_PER_PROVIDER:
            return await ctx.send(
                f"❌ Max {MAX_KEYS_PER_PROVIDER} keys per provider. "
                f"Remove one first.",
                ephemeral=True,
            )
        keys.append(value.strip())
        bot._save_cs()
        return await ctx.send(
            f"✅ Added `{p}` key. You now have {len(keys)}.", ephemeral=True
        )

    if a == "remove":
        if value is None:
            return await ctx.send("❌ Provide an index.", ephemeral=True)
        try:
            idx = int(value)
            keys.pop(idx)
            bot._save_cs()
            return await ctx.send(f"🗑️ Removed key #{idx}.", ephemeral=True)
        except (ValueError, IndexError):
            return await ctx.send("❌ Invalid index.", ephemeral=True)

    await ctx.send("❌ Actions: add | remove | list", ephemeral=True)


@cs_group.command(name="model", description="Manage your preferred models (up to 3 per provider)")
@app_commands.autocomplete(provider=_model_provider_ac)
@app_commands.describe(
    provider="groq | openrouter | hf_image | hf_text | gemini | fish",
    action="add | remove | list",
    value="Model id (for add) or index (for remove)",
)
async def cs_model(ctx, provider: str, action: str = "list", value: str = None):
    uid = ctx.author.id
    p = provider.lower()
    if p not in MODEL_PROVIDERS:
        return await ctx.send(f"❌ Providers: {', '.join(MODEL_PROVIDERS)}",
                              ephemeral=True)

    u = bot._cs(uid)
    field = f"{p}_models"
    models = u.setdefault(field, [])
    a = action.lower()

    if a == "list":
        if not models:
            defaults = bot.user_models(None, p)
            return await ctx.send(
                f"No custom `{p}` models. Bot defaults:\n"
                + "\n".join(f"• `{m}`" for m in defaults),
                ephemeral=True,
            )
        return await ctx.send(
            f"**Your `{p}` models ({len(models)}/{MAX_MODELS_PER_PROVIDER}):**\n"
            + "\n".join(f"`{i}` {m}" for i, m in enumerate(models)),
            ephemeral=True,
        )

    if a == "add":
        if not value:
            return await ctx.send("❌ Provide a model id.", ephemeral=True)
        if len(models) >= MAX_MODELS_PER_PROVIDER:
            return await ctx.send(
                f"❌ Max {MAX_MODELS_PER_PROVIDER} models per provider.",
                ephemeral=True,
            )
        models.append(value.strip())
        bot._save_cs()
        return await ctx.send(
            f"✅ Added `{p}` model. You now have {len(models)}.", ephemeral=True
        )

    if a == "remove":
        if value is None:
            return await ctx.send("❌ Provide an index.", ephemeral=True)
        try:
            idx = int(value)
            models.pop(idx)
            bot._save_cs()
            return await ctx.send(f"🗑️ Removed model #{idx}.", ephemeral=True)
        except (ValueError, IndexError):
            return await ctx.send("❌ Invalid index.", ephemeral=True)

    await ctx.send("❌ Actions: add | remove | list", ephemeral=True)


@cs_group.command(name="llm", description="🤖 Show or change your preferred LLM per provider")
@app_commands.autocomplete(provider=_model_provider_ac)
@app_commands.describe(
    provider="groq | openrouter | gemini | hf_text",
    model="Model id to set as primary (blank to just show current)",
)
async def cs_llm(ctx, provider: str = "groq", model: str = None):
    uid = ctx.author.id
    p = provider.lower()
    if p not in ("groq", "openrouter", "gemini", "hf_text"):
        return await ctx.send(
            "❌ Providers for `/cs llm`: `groq`, `openrouter`, `gemini`, `hf_text`",
            ephemeral=True,
        )

    if model is None:
        current = bot.current_model(uid, p)
        available = bot.user_models(uid, p)
        src = ("custom (your /cs model list)"
               if bot.cs.get(uid, {}).get(f"{p}_models")
               else "global default")
        lines = "\n".join(f"`{i}` {m}" for i, m in enumerate(available))
        emb = discord.Embed(
            title=f"🤖 {p} — LLM",
            description=(
                f"**Current:** `{current}`\n"
                f"**Source:** {src}\n\n"
                f"**Available:**\n{lines}"
            ),
            color=C_PRIMARY,
        )
        emb.set_footer(text=f"Set with: /cs llm {p} <model_id>")
        return await ctx.send(embed=emb, ephemeral=True)

    u = bot._cs(uid)
    field = f"{p}_models"
    existing = u.get(field, [])
    if model in existing:
        existing.remove(model)
    existing.insert(0, model)
    u[field] = existing[:MAX_MODELS_PER_PROVIDER]
    bot._save_cs()
    bot.cs_model_idx[(uid, p)] = 0

    await ctx.send(
        f"✅ `{p}` primary model → **`{model}`**\n"
        f"(Also added to your {p} model rotation.)",
        ephemeral=True,
    )


@cs_group.command(name="voice", description="Set your default TTS voice")
@app_commands.autocomplete(name=_voice_ac)
@app_commands.describe(name="Voice name (blank to see current + available)")
async def cs_voice(ctx, name: str = None):
    uid = ctx.author.id
    voices = bot.all_voices(uid)

    if name is None:
        cur = bot.default_voice(uid)
        listing = "\n".join(
            f"• `{k}` — {v['emoji']} {v['desc']}" for k, v in voices.items()
        )
        return await ctx.send(
            f"Your default voice: **{cur}**\n\nAvailable:\n{listing}",
            ephemeral=True,
        )

    if name not in voices:
        return await ctx.send(
            f"❌ Unknown voice. Available: {', '.join(voices.keys())}",
            ephemeral=True,
        )

    u = bot._cs(uid)
    u["default_voice"] = name
    bot._save_cs()
    meta = voices[name]
    await ctx.send(f"✅ Default voice → {meta['emoji']} **{meta['desc']}**")


@cs_group.command(name="voice-add", description="Add a custom Fish Audio voice")
@app_commands.describe(
    name="Short name (no spaces)",
    fish_id="Fish Audio reference ID",
    emoji="Emoji to show next to it",
    desc="Human-readable description",
)
async def cs_voice_add(ctx, name: str, fish_id: str,
                       emoji: str = "🎤", desc: str = None):
    uid = ctx.author.id
    n = name.lower().strip().replace(" ", "-")
    if n in BUILTIN_VOICES:
        return await ctx.send("❌ That name collides with a built-in voice.",
                              ephemeral=True)
    u = bot._cs(uid)
    u.setdefault("voices", {})[n] = {
        "id": fish_id, "emoji": emoji, "desc": desc or n,
    }
    bot._save_cs()
    await ctx.send(
        f"✅ Added `{n}` — {emoji} {desc or n}.\n"
        f"Use with `/tts {n} <text>` or set as default with `/cs voice {n}`."
    )


@cs_group.command(name="voice-del", description="Remove a custom voice")
@app_commands.describe(name="Custom voice name to remove")
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
    lines = "\n".join(
        f"• `{k}` — {v['emoji']} {v['desc']}" for k, v in voices.items()
    )
    await send_long(ctx, f"🎙️ **Voices available to you**\n{lines}")


@cs_group.command(name="macro", description="Save/run your own prompt shortcuts")
@app_commands.describe(
    action="add | remove | list",
    name="Macro name (trigger with .name in chat)",
    prompt="Prompt text to expand",
)
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
        return await ctx.send(
            f"💾 Macro `.{name.lower()}` saved.\n"
            f"Trigger with `.{name.lower()}` in chat."
        )

    if a == "remove":
        if not name or name.lower() not in macros:
            return await ctx.send("❌ Not found.")
        macros.pop(name.lower())
        bot._save_cs()
        return await ctx.send(f"🗑️ Removed `.{name.lower()}`.")

    if a == "list":
        if not macros:
            return await ctx.send(
                "No macros yet.\n"
                "Example: `/cs macro add explain explain X in 3 short sentences`"
            )
        lines = "\n".join(f"• `.{n}` — {p[:80]}" for n, p in macros.items())
        return await send_long(ctx, f"💾 **Your Macros**\n{lines}")

    await ctx.send("❌ Actions: add | remove | list")


@cs_group.command(name="gif", description="Manage your brainrot GIF pool")
@app_commands.describe(
    action="list | add | remove | clear | reset",
    value="URL (for add) or index (for remove)",
)
async def cs_gif(ctx, action: str = "list", value: str = None):
    uid = ctx.author.id
    a = action.lower()
    u = bot._cs(uid)
    pool = u.setdefault("brainrot_gifs", [])

    if a == "list":
        current = bot.get_gif_pool(uid)
        lines = "\n".join(f"`{i}` {url}" for i, url in enumerate(current))
        source = "custom" if pool else "default"
        await send_long(
            ctx,
            f"🧠 **Brainrot pool ({source}, {len(current)} entries)**\n{lines[:3500]}",
        )

    elif a == "add":
        if not value:
            return await ctx.send("❌ `/cs gif add <url>`")
        pool.append(value.strip())
        bot._save_cs()
        await ctx.send(f"✅ Added. Pool now has {len(pool)} custom entries.")

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
        await ctx.send("🧹 Cleared. Default pool will be used.")

    elif a == "reset":
        u.pop("brainrot_gifs", None)
        bot._save_cs()
        await ctx.send("↺ Reset to default pool.")

    else:
        await ctx.send("❌ Actions: list | add | remove | clear | reset")


@cs_group.command(name="ping", description="Control whether Mac responds to your messages")
@app_commands.describe(mode="on | off | dm_only | status")
@app_commands.choices(mode=[
    app_commands.Choice(name="🔔 on", value="on"),
    app_commands.Choice(name="🔕 off", value="off"),
    app_commands.Choice(name="💌 dm_only", value="dm_only"),
    app_commands.Choice(name="ℹ️ status", value="status"),
])
async def cs_ping(ctx, mode: str = "status"):
    uid = ctx.author.id
    if mode == "status":
        cur = bot.get_ping_pref(uid)
        return await ctx.send(f"Current ping mode: **{cur}**", ephemeral=True)
    if mode not in ("on", "off", "dm_only"):
        return await ctx.send("❌ Options: `on`, `off`, `dm_only`, `status`",
                              ephemeral=True)
    bot.set_ping_pref(uid, mode)
    await ctx.send(f"✅ Ping mode → **{mode}**", ephemeral=True)


@cs_group.command(name="show", description="Show ALL your customizations")
async def cs_show(ctx):
    uid = ctx.author.id
    u = bot.cs.get(uid, {})
    emb = discord.Embed(
        title=f"⚙️ {ctx.author.display_name}'s Customizations",
        color=C_PRIMARY,
    )

    prof = u.get("profile", {})
    if prof:
        emb.add_field(
            name="Profile",
            value="\n".join(f"• {k}: {v}" for k, v in prof.items())[:1024],
            inline=False,
        )

    for p in PROVIDERS:
        keys = u.get(f"{p}_keys", [])
        if keys:
            emb.add_field(name=f"{p} keys", value=f"{len(keys)} set", inline=True)

    for p in MODEL_PROVIDERS:
        models = u.get(f"{p}_models", [])
        if models:
            emb.add_field(
                name=f"{p} models",
                value=f"{len(models)}: `{models[0][:40]}`",
                inline=True,
            )

    voices = u.get("voices", {})
    if voices:
        emb.add_field(
            name="Custom voices",
            value=", ".join(voices.keys())[:1024],
            inline=False,
        )

    macros = u.get("macros", {})
    if macros:
        emb.add_field(
            name="Macros",
            value=", ".join(f".{n}" for n in macros.keys())[:1024],
            inline=False,
        )

    gifs = u.get("brainrot_gifs", [])
    if gifs:
        emb.add_field(name="Brainrot pool", value=f"{len(gifs)} custom GIFs",
                      inline=True)

    emb.add_field(
        name="Ping mode",
        value=f"`{bot.get_ping_pref(uid)}`",
        inline=True,
    )

    if not emb.fields:
        emb.description = (
            "Nothing set yet. Start with `/personalize` or "
            "`/cs key add groq <key>`."
        )

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
        u.pop("profile", None)
        u.pop("default_voice", None)
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
        return await ctx.send(
            "❌ Options: profile, keys, models, voices, macros, gifs, all"
        )

    bot._save_cs()
    await ctx.send(f"🧹 Reset `{s}`.")


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
        await ctx.send(f"💾 Switched to **{slot_name}** — {count} messages in this slot.")
    _cmd.__name__ = f"slot_{slot_name}"
    return _cmd


for _i in range(1, 6):
    _name = f"sv{_i}"
    bot.hybrid_command(
        name=_name,
        description=f"🗂️ Switch to chat slot {_name}",
    )(_make_slot_cmd(_name))


@bot.hybrid_command(name="svclear", description="🧹 Clear the current chat slot")
async def svclear(ctx):
    uid = ctx.author.id
    slot = bot.active_slot.get(uid, "sv1")
    bot.user_slots.setdefault(
        uid, {f"sv{i}": [] for i in range(1, 6)}
    )[slot] = []
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
        marker = " ← active" if n == active else ""
        lines.append(f"`{n}`: {c} messages{marker}")
    emb = discord.Embed(
        title=f"🗂️ Chat slots — {ctx.author.display_name}",
        description="\n".join(lines),
        color=C_PRIMARY,
    )
    await ctx.send(embed=emb, ephemeral=True)


# ======================================================================
# MODES
# ======================================================================
@bot.hybrid_command(name="setmode", description="🎭 Set the bot's personality mode")
@app_commands.autocomplete(mode=_mode_ac)
@app_commands.describe(mode="chill | brainrot | unhinged | coder | engineer | childish")
async def setmode_cmd(ctx, mode: str):
    mode = mode.lower().strip()
    if mode not in bot.mode_prompts:
        opts = ", ".join(f"`{m}`" for m in bot.mode_prompts)
        return await ctx.send(f"❌ Unknown mode. Options: {opts}")
    bot.current_mode = mode
    emoji = {
        "chill": "😎",
        "brainrot": "🧠",
        "unhinged": "🔥",
        "coder": "💻",
        "engineer": "🛠️",
        "childish": "🧒",
    }.get(mode, "🎭")
    extra = " — GIFs will be sent with every reply." if mode == "brainrot" else ""
    await ctx.send(f"{emoji} Mode → **{mode}**{extra}")


# ======================================================================
# PIPELINES
# ======================================================================
@bot.hybrid_command(name="pipeline", description="🏗️ Single-file: GEMINI → OPENROUTER → review → fix")
@app_commands.describe(
    task="What to build",
    filename="Output filename (auto-inferred if blank)",
    iterations="Max review→fix iterations (1–5, default 3)",
)
async def pipeline_cmd(ctx, task: str, filename: str = None, iterations: int = 3):
    await ctx.defer()
    iterations = max(1, min(5, iterations))
    fn = filename.strip() if filename else infer_filename(task)
    try:
        await bot.run_pipeline(ctx.channel, ctx.author.id, task, fn, iterations)
    except Exception as e:
        await ctx.send(f"❌ Pipeline error: `{e}`")


@bot.hybrid_command(name="project", description="📦 Multi-file project → .zip")
@app_commands.describe(
    task="What to build",
    name="Project name (auto-generated if blank)",
    iterations="Max review→fix iterations (1–3, default 2)",
)
async def project_cmd(ctx, task: str, name: str = None, iterations: int = 2):
    await ctx.defer()
    iterations = max(1, min(3, iterations))
    name = name.strip() if name else None
    try:
        await bot.run_project(ctx.channel, ctx.author.id, task, name, iterations)
    except Exception as e:
        await ctx.send(f"❌ Project error: `{e}`")


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

    groq_model = bot.current_model(uid, "groq") or GLOBAL_GROQ_MODELS[0]
    emb.add_field(name="Groq model", value=f"`{groq_model}`", inline=True)

    gemini_model = bot.current_model(uid, "gemini") or GLOBAL_GEMINI_MODELS[0]
    emb.add_field(name="Gemini model", value=f"`{gemini_model}`", inline=True)

    or_model = (bot.current_model(uid, "openrouter")
                or (GLOBAL_OPENROUTER_MODELS[0] if GLOBAL_OPENROUTER_MODELS else "—"))
    emb.add_field(name="OpenRouter model", value=f"`{or_model}`", inline=True)

    emb.add_field(name="Default voice", value=f"`{bot.default_voice(uid)}`", inline=True)
    emb.add_field(name="Active slot", value=f"`{bot.active_slot.get(uid, 'sv1')}`", inline=True)
    emb.add_field(name="Ping mode", value=f"`{bot.get_ping_pref(uid)}`", inline=True)

    u = bot.cs.get(uid, {})
    for p in PROVIDERS:
        n = len(u.get(f"{p}_keys", []))
        if n:
            emb.add_field(name=f"{p} keys", value=f"{n} custom", inline=True)

    for p in MODEL_PROVIDERS:
        n = len(u.get(f"{p}_models", []))
        if n:
            emb.add_field(name=f"{p} models", value=f"{n} custom", inline=True)

    emb.set_footer(text="Use /cs to customize anything · /mac for full help")
    await ctx.send(embed=emb, ephemeral=True)


# ======================================================================
# TTS
# ======================================================================
@bot.hybrid_command(name="tts", description="Say text as a Discord voice message")
@app_commands.autocomplete(voice=_voice_ac)
@app_commands.describe(
    voice="Voice (defaults to your /cs voice setting)",
    prompt="Exact text to speak",
)
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
        await ctx.send(
            content=f"{meta['emoji']} **{meta['desc']}**\n-# {clean[:350]}",
            file=file2,
        )


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
                            description=f"**Backend:** {label}",
                            color=C_PRIMARY)
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
        emb.add_field(
            name="Options",
            value="• `smart` → Gemini\n• `fast` → Pollinations\n• `hf` → Hugging Face",
            inline=False,
        )
        return await ctx.send(embed=emb)

    if mode.lower() not in ("smart", "fast", "hf"):
        return await ctx.send("❌ Mode must be `smart`, `fast`, or `hf`")
    bot.current_image_mode = mode.lower()
    await ctx.send(f"✅ Image mode → **{mode}**")


@bot.hybrid_command(name="hf_model", description="Show or change the Hugging Face image model")
@app_commands.describe(model="HF model id (blank to show current + fallbacks)")
async def hf_model_cmd(ctx, model: str = None):
    if model is None:
        listing = "\n".join(f"• `{m}`" for m in GLOBAL_HF_IMAGE_MODELS)
        current = (bot.current_model(ctx.author.id, "hf_image")
                   or GLOBAL_HF_IMAGE_MODELS[0])
        return await ctx.send(
            f"🤗 Current: `{current}`\n\n"
            f"**Fallback list (tried in order):**\n{listing}"
        )
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


@bot.hybrid_command(name="music", description="🎵 Generate music from a prompt")
@app_commands.describe(prompt="Describe the music")
async def music_cmd(ctx, prompt: str):
    await ctx.defer()
    status = await ctx.send(f"🎵 Starting music: **{prompt}**...")
    bot.loop.create_task(bot.generate_music(prompt, ctx.author.id, status))


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
        return await ctx.send("❌ Give a topic. Example: `/debate Is a hotdog a sandwich?`")
    s = {
        "description": description,
        "history": [],
        "turn": 0,
        "channel_id": ctx.channel.id,
        "task": None,
    }
    bot.ai_chat_sessions[uid] = s
    s["task"] = asyncio.create_task(bot.run_ai_chat(uid))
    await ctx.send(f"🔥 Debate started — **{description}**\n`/debate` again to stop.")


# ======================================================================
# DEV HELPERS
# ======================================================================
@bot.hybrid_command(name="code", description="💻 Generate or modify code as a file")
@app_commands.describe(
    prompt="What to build / change",
    filename="Output filename (auto-inferred if blank)",
)
async def code_cmd(ctx, prompt: str, filename: str = None):
    await ctx.defer()
    fn = filename.strip() if filename else infer_filename(prompt)
    ai_prompt = (
        f"Write the file `{fn}`.\n\nTask: {prompt}\n\n"
        f"Return ONLY the file content. No fences, no commentary."
    )
    try:
        resp = await bot.chat_call(
            ai_prompt, uid=ctx.author.id,
            system_prompt=bot.mode_prompts["engineer"],
            max_tokens=4096,
        )
        code = strip_code_fences(resp)
        if not code.strip():
            return await ctx.send("❌ Empty output.")
        preview = code.splitlines()[0][:80] if code.splitlines() else ""
        if len(code) > 1900:
            buf = io.BytesIO(code.encode("utf-8"))
            await ctx.send(
                content=f"🛠️ `{fn}` — {preview}",
                file=discord.File(buf, filename=fn),
            )
        else:
            ext = fn.rsplit(".", 1)[-1] if "." in fn else "txt"
            await ctx.send(f"🛠️ `{fn}` — {preview}\n```{ext}\n{code}\n```")
    except Exception as e:
        await ctx.send(f"❌ `{e}`")


@bot.hybrid_command(name="review", description="🔎 Review code like a principal engineer")
@app_commands.describe(code="Code to review (or reply to a message)")
async def review_cmd(ctx, code: str = None):
    if code is None and ctx.message.reference and ctx.message.reference.resolved:
        r = ctx.message.reference.resolved
        if isinstance(r, discord.Message):
            code = r.content
    if not code:
        return await ctx.send("❌ Provide code or reply to a message.")
    await ctx.defer()
    p = (
        "Review this code like a principal engineer. Cover correctness, security, "
        "performance, readability, and edge cases. End with a prioritized fix list.\n\n"
        f"```\n{code}\n```"
    )
    result = await bot.chat_call(
        p, uid=ctx.author.id,
        system_prompt=bot.mode_prompts["engineer"],
        max_tokens=3000,
    )
    await send_long(ctx, result)


# ======================================================================
# MEMORY
# ======================================================================
@bot.hybrid_command(name="sm", description="Toggle short-term memory on/off")
async def sm(ctx):
    bot.memory_enabled = not bot.memory_enabled
    await ctx.send(f"🧠 Memory **{'ON' if bot.memory_enabled else 'OFF'}**")


@bot.hybrid_command(name="persistent", description="Enable persistent memory for yourself")
async def persistent_enable(ctx):
    bot.set_persistent_enabled(ctx.author.id, True)
    await ctx.send(f"✅ Persistent memory **ON** for {ctx.author.display_name}")


@bot.hybrid_command(name="persistentdisable", description="Disable persistent memory for yourself")
async def persistent_disable(ctx):
    bot.set_persistent_enabled(ctx.author.id, False)
    await ctx.send("🚫 Persistent memory **OFF**")


@bot.hybrid_command(name="persistentreset", description="Reset a user's persistent memory (admin)")
@app_commands.describe(target_user="User whose memory to wipe")
async def persistent_reset(ctx, target_user: discord.User):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ Admin only")
    bot.clear_persistent_memory(target_user.id)
    await ctx.send(f"🧹 Reset for {target_user.display_name}")


# ======================================================================
# LORE / SYSTEM PROMPT REVEAL
# ======================================================================
@bot.hybrid_command(name="pen", description="📜 Show a snippet of the Pen archive")
async def pen_cmd(ctx):
    s = bot.pen_archive[:1000] if bot.pen_archive else "Archive not loaded"
    await ctx.send(
        f"📜 **Pen Archive**\n```\n{s}\n```\n"
        f"[Full archive](https://github.com/Pen-123/archive-)"
    )


@bot.hybrid_command(name="breadmint", description="🍞 Reveal the current system prompt")
async def breadmint_cmd(ctx):
    uid = ctx.author.id
    base = bot.mode_prompts.get(bot.current_mode, bot.mode_prompts[DEFAULT_MODE])

    parts = [f"**Mode:** `{bot.current_mode}`", "", base]

    p = bot.get_profile(uid)
    if p:
        parts.append("\n\n**Your personalization:**")
        for k, v in p.items():
            parts.append(f"- {k}: {v}")

    full = "\n".join(parts)
    await send_long(ctx, f"🍞 **Breadmint — your current system prompt**\n```\n{full[:1900]}\n```")


# ======================================================================
# COURT
# ======================================================================
class CourtRoleView(discord.ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=120)
        self.bot = bot_instance

    async def select_role(self, interaction, role_key):
        self.bot.court_sessions[interaction.user.id] = {
            "role": role_key, "case": "", "participants": {},
        }
        await interaction.response.edit_message(
            content=(
                f"✅ You are now **{role_key.capitalize()}**.\n"
                f"Use `/explain-case` to add the case, `/role` to assign others, "
                f"`/start-court` to begin."
            ),
            view=None,
        )

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


@bot.hybrid_command(name="court", description="🏛️ Start a court session")
async def court_cmd(ctx):
    await ctx.send("🏛️ **Court session** — pick your role:", view=CourtRoleView(bot))


@bot.hybrid_command(name="role", description="🏛️ Assign a court role to a user")
@app_commands.describe(user="The user to assign",
                       role="prosecutor/defense/witness/jury/stenographer/judge")
async def role_cmd(ctx, user: discord.User, role: str):
    if ctx.author.id not in bot.court_sessions:
        return await ctx.send("❌ Start with `/court` first.")
    valid = ["prosecutor", "defense", "witness", "jury", "stenographer", "judge"]
    if role.lower() not in valid:
        return await ctx.send(f"❌ Pick from: {', '.join(valid)}")
    bot.court_sessions[ctx.author.id]["participants"][role.lower()] = user.id
    await ctx.send(f"✅ {user.mention} → **{role.capitalize()}**")


@bot.hybrid_command(name="explain-case", description="🏛️ Add the case details")
@app_commands.describe(case="Describe the case")
async def explain_case(ctx, case: str):
    if ctx.author.id not in bot.court_sessions:
        return await ctx.send("❌ Start with `/court` first.")
    bot.court_sessions[ctx.author.id]["case"] = case
    await ctx.send("✅ Case recorded. Use `/start-court` to begin.")


@bot.hybrid_command(name="start-court", description="🏛️ Start the court session")
async def start_court(ctx):
    if ctx.author.id not in bot.court_sessions:
        return await ctx.send("❌ Start with `/court` first.")
    s = bot.court_sessions[ctx.author.id]
    if not s.get("case"):
        return await ctx.send("❌ Add the case with `/explain-case` first.")
    p = s.get("participants", {})
    if p:
        out = "🏛️ **Court in session!**\n"
        for r, uid in p.items():
            u = ctx.guild.get_member(uid) if ctx.guild else bot.get_user(uid)
            out += f"**{r.capitalize()}**: {u.mention if u else f'<@{uid}>'}\n"
        await ctx.send(out)
    await ctx.send("Begin.")


@bot.hybrid_command(name="endcourt", description="🏛️ End the court session")
async def endcourt_cmd(ctx):
    if ctx.author.id in bot.court_sessions:
        del bot.court_sessions[ctx.author.id]
        await ctx.send("🏛️ Court ended.")
    else:
        await ctx.send("❌ You're not in a court session.")


# ======================================================================
# UMF — UNITED MAFIA FEDERATION
# ======================================================================
DEFAULT_RECOGNIZED_NATIONS = ["United Mafia Federation"]


class UMFData:
    def __init__(self, filepath: str = "umf_data.json"):
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
        return {
            "recognized_nations": DEFAULT_RECOGNIZED_NATIONS.copy(),
            "pending_requests": [],
            "approved_requests": [],
            "denied_requests": [],
            "recognition_history": [],
        }

    def save(self):
        with open(self.filepath, 'w') as f:
            json.dump(self.data, f, indent=4)

    def get_recognized_nations(self):
        return self.data.get("recognized_nations", [])

    def add_recognized_nation(self, n):
        ns = self.get_recognized_nations()
        if n not in ns:
            ns.append(n)
            self.data["recognized_nations"] = ns
            self.save()
            return True
        return False

    def add_pending_request(self, uid, nation, username):
        req = {
            "user_id": uid,
            "username": username,
            "nation": nation,
            "timestamp": datetime.now().isoformat(),
            "status": "pending",
        }
        self.data["pending_requests"].append(req)
        self.save()
        return req

    def get_pending_requests(self):
        return self.data.get("pending_requests", [])

    def approve_request(self, uid):
        for i, r in enumerate(self.data.get("pending_requests", [])):
            if r["user_id"] == uid and r["status"] == "pending":
                r["status"] = "approved"
                r["approved_at"] = datetime.now().isoformat()
                self.data["approved_requests"].append(r)
                self.data["pending_requests"].pop(i)
                self.save()
                return r
        return None

    def deny_request(self, uid, reason=""):
        for i, r in enumerate(self.data.get("pending_requests", [])):
            if r["user_id"] == uid and r["status"] == "pending":
                r["status"] = "denied"
                r["denied_reason"] = reason
                r["denied_at"] = datetime.now().isoformat()
                self.data["denied_requests"].append(r)
                self.data["pending_requests"].pop(i)
                self.save()
                return r
        return None

    def get_request_status(self, uid):
        for b in ("pending_requests", "approved_requests", "denied_requests"):
            for r in self.data.get(b, []):
                if r["user_id"] == uid:
                    return r
        return None

    def is_nation_recognized(self, n):
        return n in self.get_recognized_nations()

    def add_to_history(self, action, uid, username, nation, details=""):
        self.data["recognition_history"].append({
            "action": action,
            "user_id": uid,
            "username": username,
            "nation": nation,
            "timestamp": datetime.now().isoformat(),
            "details": details,
        })
        self.save()


bot.umf_data = UMFData()


class UMFRecognitionModal(discord.ui.Modal, title="🌍 UMF Recognition Request"):
    nation_name = discord.ui.TextInput(
        label="Nation Name",
        placeholder="Full name of your nation",
        required=True,
        max_length=100,
    )
    additional = discord.ui.TextInput(
        label="Additional Info (optional)",
        required=False,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    async def on_submit(self, interaction):
        nation = self.nation_name.value.strip()

        if bot.umf_data.is_nation_recognized(nation):
            return await interaction.response.send_message(
                f"⚠️ **{nation}** is already recognized.", ephemeral=True
            )

        existing = bot.umf_data.get_request_status(interaction.user.id)
        if existing and existing.get("status") == "pending":
            return await interaction.response.send_message(
                f"⏳ You already have a pending request for **{existing['nation']}**.",
                ephemeral=True,
            )

        bot.umf_data.add_pending_request(
            interaction.user.id, nation, interaction.user.display_name
        )
        bot.umf_data.add_to_history(
            "REQUEST_SUBMITTED",
            interaction.user.id,
            interaction.user.display_name,
            nation,
            f"Additional: {self.additional.value or 'None'}",
        )
        emb = discord.Embed(
            title="✅ Request Submitted",
            description=f"Your request for **{nation}** is pending review.",
            color=C_OK,
        )
        emb.add_field(
            name="📋 Next Steps",
            value="Wait for admin approval. Use `/umf_status` to check.",
            inline=False,
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)


class UMFDenyModal(discord.ui.Modal, title="❌ Deny Request"):
    reason = discord.ui.TextInput(
        label="Reason",
        required=True,
        max_length=200,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, req, user):
        super().__init__()
        self.req = req
        self.user = user

    async def on_submit(self, interaction):
        reason = self.reason.value.strip()
        denied = bot.umf_data.deny_request(self.req["user_id"], reason)
        if not denied:
            return await interaction.response.edit_message(
                content="❌ Already processed.", view=None
            )
        bot.umf_data.add_to_history(
            "DENIED",
            denied["user_id"],
            denied["username"],
            denied["nation"],
            f"Reason: {reason}",
        )
        emb = discord.Embed(
            title="❌ Denied",
            description=f"**{denied['nation']}** was denied.",
            color=C_ERR,
        )
        emb.add_field(name="👤 Applicant", value=self.user.mention, inline=True)
        emb.add_field(name="📝 Reason", value=reason, inline=False)
        await interaction.response.edit_message(embed=emb, view=None)
        try:
            await self.user.send(
                f"❌ Your request for **{denied['nation']}** was denied.\n"
                f"Reason: {reason}"
            )
        except Exception:
            pass


class UMFPrimaryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📝 Request Recognition",
                       style=discord.ButtonStyle.primary, emoji="🌍")
    async def request_btn(self, interaction, button):
        await interaction.response.send_modal(UMFRecognitionModal())

    @discord.ui.button(label="📋 View Nations",
                       style=discord.ButtonStyle.secondary, emoji="📋")
    async def list_btn(self, interaction, button):
        nations = bot.umf_data.get_recognized_nations()
        emb = discord.Embed(
            title="🌍 Recognized UMF Nations",
            color=C_ACCENT,
            timestamp=datetime.now(),
        )
        if nations:
            emb.description = "```\n" + "\n".join(f"• {n}" for n in nations[:25]) + "\n```"
        else:
            emb.description = "No nations recognized yet."
        emb.set_footer(text=f"Total: {len(nations)}")
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(label="ℹ️ My Status",
                       style=discord.ButtonStyle.secondary, emoji="ℹ️")
    async def status_btn(self, interaction, button):
        req = bot.umf_data.get_request_status(interaction.user.id)
        if req:
            status = req.get("status", "unknown")
            if status == "pending":
                color, title = C_WARM, "⏳ Pending"
            elif status == "approved":
                color, title = C_OK, "✅ Approved"
            else:
                color, title = C_ERR, "❌ Denied"
            emb = discord.Embed(
                title=title,
                description=f"**{req.get('nation', '')}**",
                color=color,
                timestamp=datetime.now(),
            )
            if status == "denied" and req.get("denied_reason"):
                emb.add_field(name="Reason", value=req["denied_reason"], inline=False)
        else:
            emb = discord.Embed(
                title="ℹ️ No Request",
                description="You have no active request.",
                color=C_DEEP,
            )
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
            return await interaction.response.edit_message(
                content="❌ Already processed.", view=None
            )

        nation = approved["nation"]
        bot.umf_data.add_recognized_nation(nation)
        bot.umf_data.add_to_history(
            "APPROVED",
            approved["user_id"],
            approved["username"],
            nation,
            f"Approved by {interaction.user}",
        )
        emb = discord.Embed(
            title="✅ Approved!",
            description=f"**{nation}** is now recognized.",
            color=C_OK,
        )
        emb.add_field(name="👤 Applicant", value=self.user.mention, inline=True)
        emb.add_field(name="✅ By", value=interaction.user.mention, inline=True)
        await interaction.response.edit_message(embed=emb, view=None)
        try:
            await self.user.send(
                f"🎉 Your nation **{nation}** has been recognized by the UMF!"
            )
        except Exception:
            pass

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny_btn(self, interaction, button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("⛔ Admin only.", ephemeral=True)
        await interaction.response.send_modal(UMFDenyModal(self.req, self.user))


def umf_requirements_embed():
    emb = discord.Embed(
        title="🌍 UMF Recognition System",
        description="To be recognized by the **United Military Federation (UMF)**:",
        color=C_PRIMARY,
        timestamp=datetime.now(),
    )
    emb.add_field(
        name="📋 Requirements",
        value=(
            "1. **Administrative User** — an admin user in the UMF.\n"
            "2. **Relay Link** — your nation must be relay-linked to the UMF network.\n"
            "3. **Active Status** — your nation must be actively participating."
        ),
        inline=False,
    )
    emb.add_field(
        name="📝 How to Apply",
        value="Click **'Request Recognition'** below, enter your nation name, wait for approval.",
        inline=False,
    )
    emb.add_field(
        name="✅ Currently Recognized",
        value=f"**{len(bot.umf_data.get_recognized_nations())}** nations",
        inline=False,
    )
    emb.set_footer(text="UMF Recognition System")
    return emb


@bot.hybrid_command(name="umf", description="🌍 UMF Recognition System — start here")
async def umf_command(ctx):
    await ctx.send(embed=umf_requirements_embed(), view=UMFPrimaryView())


@bot.hybrid_command(name="umf_list", description="📋 List all recognized UMF nations")
async def umf_list(ctx):
    nations = bot.umf_data.get_recognized_nations()
    emb = discord.Embed(
        title="🌍 Recognized UMF Nations",
        color=C_ACCENT,
        timestamp=datetime.now(),
    )
    if nations:
        emb.description = "```\n" + "\n".join(f"• {n}" for n in nations[:25]) + "\n```"
    else:
        emb.description = "No nations recognized yet."
    emb.set_footer(text=f"Total: {len(nations)}")
    await ctx.send(embed=emb)


@bot.hybrid_command(name="umf_status", description="ℹ️ Check your UMF request status")
async def umf_status(ctx):
    req = bot.umf_data.get_request_status(ctx.author.id)
    if req:
        status = req.get("status", "unknown")
        if status == "pending":
            color, title = C_WARM, "⏳ Pending"
        elif status == "approved":
            color, title = C_OK, "✅ Approved"
        else:
            color, title = C_ERR, "❌ Denied"
        emb = discord.Embed(
            title=title,
            description=f"**{req.get('nation', '')}**",
            color=color,
            timestamp=datetime.now(),
        )
        if status == "denied" and req.get("denied_reason"):
            emb.add_field(name="Reason", value=req["denied_reason"], inline=False)
    else:
        emb = discord.Embed(
            title="ℹ️ No Request",
            description="You have no active request.",
            color=C_DEEP,
        )
    await ctx.send(embed=emb, ephemeral=True)


@bot.hybrid_command(name="umf_admin", description="🔧 Admin panel — manage pending UMF requests")
async def umf_admin(ctx):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("⛔ Admin only.", ephemeral=True)
    pending = bot.umf_data.get_pending_requests()
    if not pending:
        return await ctx.send("📭 No pending requests.", ephemeral=True)

    req = pending[0]
    try:
        user = (ctx.guild.get_member(req["user_id"])
                or await ctx.guild.fetch_member(req["user_id"]))
    except Exception:
        user = None

    emb = discord.Embed(title="📋 Pending Request", color=C_WARM)
    emb.add_field(
        name="👤 Applicant",
        value=user.mention if user else f"<@{req['user_id']}>",
        inline=True,
    )
    emb.add_field(name="🌍 Nation", value=req["nation"], inline=True)
    emb.add_field(
        name="📅 Submitted",
        value=datetime.fromisoformat(req["timestamp"]).strftime("%B %d, %Y %H:%M"),
        inline=True,
    )
    emb.add_field(name="📊 Total Pending", value=str(len(pending)), inline=True)
    await ctx.send(embed=emb, view=UMFAdminView(req, user), ephemeral=True)


# ======================================================================
# ON_MESSAGE
# ======================================================================
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
    )

    # -------- ping preference gate --------
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

    # -------- reply context --------
    reply_context = None
    reply_msg = None
    if message.reference:
        resolved = message.reference.resolved
        if resolved is None:
            try:
                resolved = await message.channel.fetch_message(
                    message.reference.message_id
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                resolved = None
        if isinstance(resolved, discord.Message) and resolved.author.id != bot.user.id:
            reply_context = {
                "author": resolved.author.display_name,
                "content": (resolved.content or "[no text]")[:800],
                "author_id": resolved.author.id,
            }
            reply_msg = resolved

    # -------- images --------
    images = await fetch_images_from_message(message)
    if not images and reply_msg is not None:
        images = await fetch_images_from_message(reply_msg)

    # -------- cooldown --------
    now = time.time()
    if now - bot.user_cooldowns.get(message.author.id, 0) < USER_COOLDOWN_SECONDS:
        await bot.process_commands(message)
        return
    bot.user_cooldowns[message.author.id] = now

    # -------- clean mention --------
    clean = re.sub(r'<@!?{}>\s*'.format(bot.user.id), '', content).strip()
    if not clean and reply_context:
        clean = "what do you think of this?"
    if not clean and images:
        clean = "what's in this image?"
    if not clean:
        await bot.process_commands(message)
        return

    logger.info(
        f"Message from {message.author} in "
        f"#{getattr(message.channel, 'name', 'DM')}: {clean[:100]!r} | images={len(images)}"
    )

    try:
        await bot.process_user_message(
            message.author, clean, message.channel,
            reply_context=reply_context, trigger_msg=message, images=images,
        )
    except Exception as e:
        logger.error(f"process_user_message failed: {e}", exc_info=True)

    await bot.process_commands(message)


# ======================================================================
# WEB SERVER
# ======================================================================
async def handle_root(request):
    return web.Response(text="🔥 Mac v22.1 is running")


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


if __name__ == "__main__":
    asyncio.run(main())
