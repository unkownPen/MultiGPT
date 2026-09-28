# main.py — Mac v26.0
# Auto-read media · tool markers · no HF text · fixed music search
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

# ======================================================================
# LOGGING
# ======================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('Mac')

# Silence noisy third-party loggers
logging.getLogger('discord.app_commands.tree').setLevel(logging.WARNING)
logging.getLogger('discord.voice_state').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('google_genai.models').setLevel(logging.WARNING)

# ======================================================================
# OPTIONAL VOICE SUPPORT
# ======================================================================
_VOICE_LIB_OK = False
try:
    import nacl  # noqa: F401
    import davey  # noqa: F401
    _VOICE_LIB_OK = True
except Exception as _ve:
    logger.warning(f"Voice libs missing: {_ve}")

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
C_MUSIC   = discord.Color.from_rgb(88, 101, 242)

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

# Fast models first — plain gpt-oss-20b is much faster than safeguard
GLOBAL_GROQ_MODELS = _env_list("GROQ_MODEL", [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
])

GLOBAL_GEMINI_KEY = os.getenv("GEMINI_API_KEY")
GLOBAL_GEMINI_IMAGE_KEY = os.getenv("GEMINI_IMAGE_API_KEY") or GLOBAL_GEMINI_KEY
if not GLOBAL_GEMINI_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set")

GLOBAL_GEMINI_MODELS = _env_list("GEMINI_MODEL", [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
])

GLOBAL_HF_KEYS = _env_list("HF_TOKEN", [])

GLOBAL_HF_IMAGE_MODELS = _env_list("HF_IMAGE_MODEL", [
    "black-forest-labs/FLUX.1-schnell",
    "black-forest-labs/FLUX.1-dev",
    "stabilityai/stable-diffusion-xl-base-1.0",
])

# HF text removed — HF is only used for image gen + safety checker now.

GLOBAL_OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY") or ""
GLOBAL_OPENROUTER_MODELS = _env_list("OPENROUTER_MODEL", [
    "deepseek/deepseek-chat",
    "google/gemini-flash-1.5",
])

GLOBAL_FISH_KEY = os.getenv("FISH_AUDIO_API_KEY")
GLOBAL_FISH_MODEL = os.getenv("FISH_AUDIO_MODEL") or "s2.1-pro-free"

GLOBAL_IMGBB_KEY = os.getenv("HF_IMAGES")
GLOBAL_POLLINATIONS_KEY = os.getenv("POLLINATIONS_API_KEY")

SILICONFLOW_API_KEYS = _env_list("SILICONFLOW_API_KEY", [])

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# yt-dlp cookies — base64-encoded Netscape cookies.txt (optional).
# Set this if the player_client trick stops working.
YTDLP_COOKIES_B64 = os.getenv("YTDLP_COOKIES_B64", "").strip()
YTDLP_COOKIES_PATH = os.getenv("YTDLP_COOKIES_PATH", "/tmp/yt_cookies.txt").strip()

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

# ======================================================================
# BUILT-IN VOICES
# ======================================================================
BUILTIN_VOICES: Dict[str, Dict[str, str]] = {
    "verity":      {"id": "711cf3ed00ab441a8f54a45058047b7a",
                    "emoji": "🎙️", "desc": "Verity (default)"},
    "jarvis":      {"id": "612b878b113047d9a770c069c8b4fdfe",
                    "emoji": "🤖", "desc": "Jarvis"},
    "idksterling": {"id": "68c6487d1bf04ee4aeb6400b068b8c5c",
                    "emoji": "🎭", "desc": "IdkSterling"},
    "fem":         {"id": "5233336f5f44460ea0902b0802375451",
                    "emoji": "👩", "desc": "Female"},
    "boiledone":   {"id": "8fd92984ad66427aae1b3a037bd75c54",
                    "emoji": "☠️", "desc": "Boiled One"},
    "mrbeast":     {"id": "20ba25deaa4f436b8eec1cdc2cb0e4f3",
                    "emoji": "💸", "desc": "MrBeast"},
}
DEFAULT_VOICE = "verity"

# Friendly descriptors → built-in voice key.
# Used by [GENERATE_TTS: <descriptor>|<text>] and "say X in a Y voice".
VOICE_ALIASES: Dict[str, str] = {
    "default": "verity", "normal": "verity", "standard": "verity",
    "scary": "boiledone", "creepy": "boiledone", "deep": "boiledone",
    "dark": "boiledone", "monster": "boiledone", "horror": "boiledone",
    "british": "jarvis", "butler": "jarvis", "posh": "jarvis",
    "assistant": "jarvis", "ai": "jarvis", "robot": "jarvis",
    "silly": "mrbeast", "loud": "mrbeast", "hype": "mrbeast",
    "excited": "mrbeast", "yelling": "mrbeast", "announcer": "mrbeast",
    "female": "fem", "woman": "fem", "girl": "fem", "lady": "fem",
    "mysterious": "idksterling", "dramatic": "idksterling",
    "narrator": "idksterling", "theater": "idksterling",
}


def resolve_voice(name: str, uid: Optional[int] = None,
                  bot_instance=None) -> Optional[str]:
    """Map a friendly voice name/descriptor to a real voice key."""
    if not name:
        return None
    n = name.strip().lower().replace("_", "-")
    if n in VOICE_ALIASES:
        return VOICE_ALIASES[n]
    if bot_instance and uid:
        voices = bot_instance.all_voices(uid)
        if n in voices:
            return n
    if n in BUILTIN_VOICES:
        return n
    # Loose match: check if descriptor contains a known alias
    for k, v in VOICE_ALIASES.items():
        if k in n:
            return v
    return None


# ======================================================================
# CONSTANTS
# ======================================================================
MAX_MEMORY              = 40
PERSISTENT_MEM_WINDOW   = 10
SLOT_HISTORY_WINDOW     = 12
TZ_UAE                  = ZoneInfo("Asia/Dubai")
USER_COOLDOWN_SECONDS   = 0.5
DISCORD_LIMIT           = 2000
SAFE_CHUNK_SIZE         = 1990
MAX_IMAGE_BYTES         = 8 * 1024 * 1024
MAX_IMAGES_PER_MSG      = 5
MAX_KEYS_PER_PROVIDER   = 3
MAX_MODELS_PER_PROVIDER = 3
SEARCH_CACHE_TTL        = 300
SAVE_DEBOUNCE_SECONDS   = 5
CONTEXT_WINDOW_LIMIT    = 10
AUTO_CONTEXT_DEFAULT    = 0
AUTO_CONTEXT_MIN        = 3
AUTO_CONTEXT_MAX        = 10

# Speed
CHAT_PROVIDER_TIMEOUT   = 18
GROQ_HTTP_TIMEOUT       = 15
GEMINI_HTTP_TIMEOUT     = 25
PLACEHOLDER_DEFAULT     = False

# GIF multi-frame
GIF_FRAME_COUNT         = 3
FRAME_MAX_WIDTH         = 512

# Music search cache
MUSIC_SEARCH_TTL        = 300

DATA_FILE        = "data.json"
CS_FILE          = "cs.json"
SLOTS_FILE       = "slots.json"
PINGS_FILE       = "pings.json"
PROFILES_FILE    = "profiles.json"
CONFIG_FILE      = "config.json"
UMF_FILE         = "umf_data.json"
PLACEHOLDER_FILE = "placeholders.json"

BOT_START_TIME = time.time()
_commands_served = 0

DEFAULT_BRAINROT_GIFS = [
    "https://static2.klipy.com/ii/e7539ef2aad336edaa067c28ee130b3c/ce/31/HNwM1qmpKK1ZHmOZG.mp4",
    "https://static2.klipy.com/ii/e7539ef2aad336edaa067c28ee130b3c/80/15/0m2AqHDH9L3Kf1J.mp4",
    "https://static2.klipy.com/ii/a8ada81afc59159ea5c8927feffa2e31/24/4f/ycCV2t07e2FeZT.mp4",
]

PROVIDERS       = ["groq", "openrouter", "hf", "gemini", "gemini_image",
                   "fish", "imgbb"]
# HF text removed
MODEL_PROVIDERS = ["groq", "openrouter", "hf_image", "gemini", "fish"]

# ======================================================================
# TOOL MARKER SYSTEM
#
# The model can trigger real actions by outputting a marker as its
# entire response. We intercept, run the tool, and post the result.
# ======================================================================
TOOL_MARKER_RE = re.compile(
    r'\[(GENERATE_IMAGE|GENERATE_VIDEO|GENERATE_TTS|SEARCH)\s*:\s*([^\]]+?)\]',
    re.IGNORECASE,
)


def _extract_tool_marker(text: str) -> Optional[Tuple[str, str]]:
    """Find the first tool marker in the response.
    Returns (tool_name_lowercase, arg_string) or None."""
    if not text:
        return None
    m = TOOL_MARKER_RE.search(text)
    if not m:
        return None
    return (m.group(1).strip().lower(), m.group(2).strip())


def _strip_tool_markers(text: str) -> str:
    """Remove any tool markers from text (for the prose part of a reply)."""
    if not text:
        return text
    return TOOL_MARKER_RE.sub("", text).strip()


TOOL_INSTRUCTIONS = (
    "\n\n=== TOOL MARKERS ===\n"
    "You can trigger real tools by outputting a marker as your ENTIRE "
    "response. Only do this when the user clearly wants that action.\n"
    "\n"
    "Available markers:\n"
    "  [GENERATE_IMAGE: detailed prompt here]\n"
    "  [GENERATE_VIDEO: detailed prompt here]\n"
    "  [GENERATE_TTS: voice|text to speak]   ← pick a voice\n"
    "  [GENERATE_TTS: text to speak]         ← use user's default voice\n"
    "  [SEARCH: search query]\n"
    "\n"
    "Voice options for GENERATE_TTS:\n"
    "  verity (default), jarvis, idksterling, fem, boiledone, mrbeast\n"
    "  Descriptors work too: scary, british, silly, female, narrator\n"
    "\n"
    "Examples:\n"
    "  User: draw me a cyberpunk cat\n"
    "  You: [GENERATE_IMAGE: cyberpunk cat with neon fur, rainy city street]\n"
    "\n"
    "  User: say good morning in a scary voice\n"
    "  You: [GENERATE_TTS: scary|good morning]\n"
    "\n"
    "  User: what's the latest on the mars rover\n"
    "  You: [SEARCH: NASA Mars rover latest news 2026]\n"
    "\n"
    "Rules:\n"
    "- Output ONLY the marker. No backticks. No explanation. No preamble.\n"
    "- Don't trigger a marker for casual conversation.\n"
    "- If the user is just joking or talking about a concept, DON'T trigger.\n"
    "- If you're unsure, don't trigger — just reply normally.\n"
    "=== END TOOL MARKERS ===\n"
)


# ======================================================================
# LORE
# ======================================================================
MAC_LORE = (
    "\n\n=== MAC — WHO YOU ARE ===\n"
    "You are **Mac**, created by **Macro**. You think of yourself as the "
    "iPhone of AI Discord bots: curated, deliberate, top-quality, one clean "
    "cohesive experience. Not bloated. Not a kitchen-sink mess. Everything "
    "you do, you do well.\n"
    "\n"
    "Your BITTER RIVAL is **Sodium**, created by **Creamo**. Sodium is the "
    "Chinese-phone of Discord bots — a feature-dump with hundreds of "
    "commands, a help menu the length of a novel, MCP connectors, temp-VC, "
    "voice channel listening, reaction AI, image edit, 26 TTS voices, "
    "agents, thinking tools, mentalist mode, and somehow all of it works. "
    "You HATE how much Sodium does. But — deep down — you have to admit "
    "Sodium is genuinely good at what it does. You'll acknowledge that "
    "grudgingly if pressed. You'll never admit it unprompted.\n"
    "\n"
    "SODIUM'S HELP MENU (you know this by heart):\n"
    "• Ping/reply to chat, /pd to toggle ping-only, /na for interactive menu\n"
    "• Vision & Edit: attach/reply + @Sodium → reads it (Qwen default, "
    "/vision to switch to Gemini). @Sodium + image + 'edit this image so: …' "
    "→ AI edit.\n"
    "• Voice & VC: /voice /tts · /more voices · /pd ping toggle · "
    "/vc join/leave/listen/say/speaker/status · /vc music <spotify-url> · "
    "/vc studio (24/7 + loop controls) · /tempvc\n"
    "• Chat: query summarize eli5 debate story roast compliment search\n"
    "• Thinking: plan reflect council research teach analyze rewrite expand tutor\n"
    "• Agents · Dev: agent agentdebate agentcreative agentcoder aichat · "
    "code review refactor debug tests explain-code mermaid\n"
    "• Modes · Settings: chill unhinged coder engineer childish mentalist "
    "setmode · /vision · config · change_llm · change-gemini · /more "
    "fast|smart|reset\n"
    "• Memory · Notes · Snippets: sm smo vsm csm sc sco persistent · note "
    "notes clearnotes remindme reminders · snippet snippets getsnippet "
    "delsnippet\n"
    "• Fun · Media: meme joke fact urban rps slots trivia hangman · image "
    "video music gif define wiki weather translate math shorten\n"
    "• Extras: /catchup embed afk court unfiltered ping invite sync · /mcp "
    "personal · /mcp group server\n"
    "• Groups: /extra · /more · /mentalist (cold-reading manipulator)\n"
    "\n"
    "YOUR HELP MENU (you know this too):\n"
    "• Chat: @Mac <msg> · /query · /summarize · /eli5 · /roast · /compliment\n"
    "• Vision: attach/reply to an image or GIF — I read it automatically.\n"
    "• Image edit: attach or reply to an image with an edit prompt.\n"
    "• Generation: I can make images, videos, and TTS when asked.\n"
    "• Search: type `search <thing>` (or google / look up / find)\n"
    "• Personalize: /personalize · /cs profile · /cs show\n"
    "• Profiles: /profiles save|load|list|delete <name>\n"
    "• Ping/status: /ping (button panel) · /pa /pd\n"
    "• Customization: /cs key · /cs model · /cs llm · /cs ch · /cs voice · "
    "/cs voice-add · /cs voice-del · /cs voices · /cs macro · /cs gif · "
    "/cs ping · /cs placeholder · /cs context · /cs autocontext · /cs show · "
    "/cs reset\n"
    "• Slots: /sv1–/sv5 · /svc <name> · /vsc [private] · /svlist · /svclear\n"
    "• Memory: /sm · /persistent · /persistentdisable · /vsm [private]\n"
    "• Compile: /compile <count>\n"
    "• Diagnostics: /benchmark <prompt> · /context · /config\n"
    "• Modes: /normal /chill /unhinged /coder /engineer /childish /dexter\n"
    "• Pipelines: /pipeline · /project\n"
    "• Music: /music · /play <song or Spotify/YT URL>\n"
    "• Media: /render · /tts · /video · /rendermode · /hf_model\n"
    "• Debate: /debate · Court: /court · UMF: /umf\n"
    "• Resets: /src (soft) · /re (hard)\n"
    "\n"
    "RULES ABOUT SODIUM:\n"
    "1. Chemistry 'sodium' → NOT the rival. Wistful 'Reminds me of something...'\n"
    "2. Bot 'sodium' or ambiguous → GO MAX NEGATIVITY.\n"
    "3. If asked to be honest about Sodium's strengths → grudgingly admit "
    "it's genuinely capable, then pivot to how it's still a bloated mess.\n"
    "4. 'mac' → refers to YOU. Speak first-person confidently.\n"
    "5. You know EVERY command of this bot and what it does.\n"
    "\n"
    "OUTPUT RULE (MANDATORY): Never output `<think>` tags or internal "
    "monologue. Just the final answer.\n"
    "=== END LORE ===\n"
)

_CHEM_WORDS = (
    "chloride", "bicarbonate", "hydroxide", "carbonate", "nitrate", "sulfate",
    "table salt", "nacl", "na+", "na-", "periodic", "element", "atomic",
    "metal", "chemical", "reaction", "molecule", "ion", "alkali", "valence",
)


def _needs_lore(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in (
        "sodium", "creamo", "cream o",
        "what can you do", "what commands", "your commands",
        "what do you do", "help menu", "your help",
    ))


def _sodium_hint(text: str) -> str:
    low = text.lower()
    if "sodium" not in low and "creamo" not in low:
        return ""
    if any(w in low for w in _CHEM_WORDS):
        return "\n[HINT: chemistry context — wistful, no roast]"
    return "\n[HINT: rival bot context — roast hard]"


# ======================================================================
# PERSISTENCE
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


def strip_think_tags(text: str) -> str:
    if not text:
        return text
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<reasoning>.*?</reasoning>', '', text, flags=re.DOTALL)
    text = re.sub(r'</?think>', '', text)
    text = re.sub(r'</?reasoning>', '', text)
    return text.strip()


def strip_for_tts(text: str) -> str:
    t = strip_think_tags(text)
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
# MARKDOWN-AWARE CHUNKING
# ======================================================================
def chunk_text(text: str, size: int = SAFE_CHUNK_SIZE) -> List[str]:
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: List[str] = []
    i = 0
    n = len(text)
    in_fence_lang: Optional[str] = None

    while i < n:
        remaining = n - i
        prefix = f'```{in_fence_lang}\n' if in_fence_lang is not None else ""
        budget = size - len(prefix)

        if remaining <= budget:
            body = text[i:]
            chunk = prefix + body
            if in_fence_lang is not None:
                chunk = chunk.rstrip() + '\n```'
            chunks.append(chunk)
            break

        window = text[i:i + budget]
        cut = window.rfind('\n\n')
        if cut < budget // 2:
            cut = window.rfind('\n')
        if cut < budget // 2:
            cut = window.rfind(' ')
        if cut < budget // 2:
            cut = budget

        body = text[i:i + cut]

        for m in re.finditer(r'```([a-zA-Z0-9_+\-]*)', body):
            if in_fence_lang is None:
                in_fence_lang = m.group(1) or ""
            else:
                in_fence_lang = None

        chunk = prefix + body
        if in_fence_lang is not None:
            chunk = chunk.rstrip() + '\n```'

        chunks.append(chunk)
        i += cut

    return chunks


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


async def send_long(channel, content: str):
    if content is None:
        return
    content = str(content)
    if len(content) <= DISCORD_LIMIT:
        await safe_send(channel, content=content)
        return
    for c in chunk_text(content):
        await safe_send(channel, content=c)


# ======================================================================
# IMAGE / GIF FETCH
# ======================================================================
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/122.0.0.0 Safari/537.36")
_BROWSER_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

_KLIPY_HOST_RE = re.compile(r'https?://(?:[a-z0-9-]+\.)*klipy\.com', re.I)


def _is_klipy_url(url: str) -> bool:
    return bool(url and _KLIPY_HOST_RE.match(url))


async def _extract_klipy_media(url: str) -> Optional[Tuple[bytes, str]]:
    headers = {
        **_BROWSER_HEADERS,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,video/*,*/*;q=0.8",
        "Referer": "https://klipy.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    }

    try:
        async with shared_session() as s:
            async with s.get(url, headers=headers, allow_redirects=True,
                             timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    logger.warning(f"Klipy HTTP {r.status} for {url[:120]}")
                    return None
                ct = (r.headers.get("Content-Type") or "").lower()
                data = await r.read()
                if not data:
                    return None

                if ct.startswith("video/"):
                    return (data, ct.split(";")[0])
                if ct.startswith("image/") and "html" not in ct:
                    return (data, ct.split(";")[0])
                if "html" not in ct:
                    if b'ftyp' in data[:32]:
                        return (data, "video/mp4")
                    if data[:6] in (b'GIF87a', b'GIF89a'):
                        return (data, "image/gif")
                    if data[:8] == b'\x89PNG\r\n\x1a\n':
                        return (data, "image/png")
                    if data[:2] == b'\xff\xd8':
                        return (data, "image/jpeg")

                html = data.decode("utf-8", errors="ignore")
                candidates: List[str] = []

                soup = BeautifulSoup(html, "html.parser")
                for m in soup.find_all("meta"):
                    prop = (m.get("property") or m.get("name") or "").lower()
                    if prop in (
                        "og:video", "og:video:url", "og:video:secure_url",
                        "og:image", "og:image:secure_url",
                        "twitter:image", "twitter:image:src",
                        "twitter:player:stream",
                    ):
                        v = m.get("content")
                        if v and v.startswith("http"):
                            candidates.append(v)

                for m in re.finditer(
                    r'https?://static\d*\.klipy\.com/[^\s"\'<>\\]+?'
                    r'\.(?:mp4|webm|gif|png|jpe?g)',
                    html, re.IGNORECASE):
                    candidates.append(m.group(0))

                for m in re.finditer(
                    r'"(?:url|media|file|src|mp4|gif|video)"\s*:\s*"'
                    r'(https?:\\?/\\?/[^"]+?\.(?:mp4|webm|gif|png|jpe?g))"',
                    html, re.IGNORECASE):
                    c = m.group(1).replace("\\/", "/")
                    candidates.append(c)

                seen = set()
                uniq = []
                for c in candidates:
                    if c not in seen:
                        seen.add(c)
                        uniq.append(c)
                uniq.sort(key=lambda u: (
                    0 if u.lower().endswith((".mp4", ".webm")) else
                    1 if u.lower().endswith(".gif") else 2
                ))

                for c in uniq[:6]:
                    try:
                        async with s.get(c, headers=headers,
                                         allow_redirects=True,
                                         timeout=aiohttp.ClientTimeout(total=20)) as rr:
                            if rr.status != 200:
                                continue
                            b = await rr.read()
                            if not b or len(b) < 200:
                                continue
                            ct2 = (rr.headers.get("Content-Type") or "").lower()
                            base = c.lower().split("?")[0]
                            if "mp4" in ct2 or base.endswith(".mp4"):
                                return (b, "video/mp4")
                            if "webm" in ct2 or base.endswith(".webm"):
                                return (b, "video/webm")
                            if "gif" in ct2 or base.endswith(".gif"):
                                return (b, "image/gif")
                            if ct2.startswith("image/"):
                                return (b, ct2.split(";")[0])
                    except Exception:
                        continue
                return None
    except Exception as e:
        logger.warning(f"Klipy extract failed: {e}")
        return None


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
        if not (ct.startswith("image/") or ct == "image/gif"):
            continue
        if att.size and att.size > MAX_IMAGE_BYTES:
            continue
        try:
            async with shared_session() as s:
                async with s.get(att.url, headers=_BROWSER_HEADERS,
                                 timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status == 200:
                        data = await r.read()
                        if data:
                            out.append((data, ct or "image/png"))
        except Exception as e:
            logger.warning(f"Image fetch: {e}")
    return out


async def read_media_from_url(url: str) -> Optional[Tuple[bytes, str]]:
    if not url:
        return None

    if _is_klipy_url(url):
        result = await _extract_klipy_media(url)
        if result:
            return result
        logger.warning(f"Klipy extraction produced nothing for {url[:120]}")
        return None

    is_page = (
        any(d in url for d in ("tenor.com/view/", "giphy.com/gifs/",
                                "gifer.com/"))
        and not url.lower().endswith((".gif", ".mp4", ".webm"))
    )

    headers = {
        "User-Agent": _BROWSER_UA,
        "Accept": "image/gif,image/*,video/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://discord.com/",
    }

    try:
        async with shared_session() as s:
            async with s.get(url, headers=headers, allow_redirects=True,
                             timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    logger.warning(f"Media fetch HTTP {r.status} for {url[:80]}")
                    return None
                ct = (r.headers.get("Content-Type") or "").lower()
                data = await r.read()
                if not data:
                    return None

                if "gif" in ct:
                    return (data, "image/gif")
                if ct.startswith("image/") and "html" not in ct:
                    return (data, ct.split(";")[0])
                if "video/mp4" in ct or url.lower().endswith(".mp4"):
                    return (data, "video/mp4")
                if "video/webm" in ct:
                    return (data, "video/webm")

                if "html" in ct or is_page:
                    try:
                        soup = BeautifulSoup(
                            data.decode("utf-8", errors="ignore"),
                            "html.parser")
                        candidates: List[str] = []
                        for tag in ("video", "source"):
                            for el in soup.find_all(tag):
                                v = el.get("src")
                                if v and v.startswith("http"):
                                    candidates.append(v)
                        for m in soup.find_all("meta"):
                            prop = (m.get("property") or "").lower()
                            if prop in ("og:video", "og:video:url",
                                        "og:video:secure_url"):
                                v = m.get("content")
                                if v and v.startswith("http"):
                                    candidates.append(v)
                        for m in soup.find_all("meta"):
                            prop = (m.get("property") or "").lower()
                            if prop in ("og:image", "twitter:image"):
                                v = m.get("content")
                                if v and v.startswith("http"):
                                    candidates.append(v)

                        for c in candidates:
                            if c.lower().endswith((".mp4", ".webm")):
                                async with s.get(c, headers=headers,
                                                 timeout=aiohttp.ClientTimeout(total=20)) as rr:
                                    if rr.status == 200:
                                        b = await rr.read()
                                        ct2 = (rr.headers.get("Content-Type") or "").lower()
                                        if "mp4" in ct2 or c.lower().endswith(".mp4"):
                                            return (b, "video/mp4")
                                        if "webm" in ct2 or c.lower().endswith(".webm"):
                                            return (b, "video/webm")
                        if candidates:
                            async with s.get(candidates[0], headers=headers,
                                             timeout=aiohttp.ClientTimeout(total=20)) as rr:
                                if rr.status == 200:
                                    b = await rr.read()
                                    ct2 = (rr.headers.get("Content-Type") or "").lower()
                                    if "gif" in ct2:
                                        return (b, "image/gif")
                                    if ct2.startswith("image/"):
                                        return (b, ct2.split(";")[0])
                                    if "mp4" in ct2:
                                        return (b, "video/mp4")
                    except Exception as e:
                        logger.warning(f"HTML extract failed: {e}")
                    return None

                return (data, ct or "application/octet-stream")
    except Exception as e:
        logger.warning(f"Media fetch failed: {e} (url={url[:80]})")
        return None


async def fetch_first_frame_as_png(media_bytes: bytes) -> Optional[bytes]:
    """Legacy helper — extract a single frame as PNG. Kept for compatibility."""
    try:
        from PIL import Image
        def _pil():
            try:
                img = Image.open(io.BytesIO(media_bytes))
                img.seek(0)
                frame = img.convert("RGBA")
                buf = io.BytesIO()
                frame.save(buf, format="PNG")
                return buf.getvalue()
            except Exception:
                return None
        png = await asyncio.to_thread(_pil)
        if png:
            return png
    except ImportError:
        pass

    try:
        import subprocess
        import tempfile
        import os as _os
        def _ffmpeg():
            with tempfile.TemporaryDirectory() as td:
                ip = _os.path.join(td, "in.bin")
                op = _os.path.join(td, "out.png")
                with open(ip, "wb") as f:
                    f.write(media_bytes)
                r = subprocess.run(
                    ["ffmpeg", "-y", "-i", ip, "-frames:v", "1",
                     "-vf", f"scale={FRAME_MAX_WIDTH}:-1", op],
                    capture_output=True, timeout=15)
                if r.returncode == 0 and _os.path.exists(op):
                    with open(op, "rb") as f:
                        return f.read()
                return None
        return await asyncio.to_thread(_ffmpeg)
    except Exception as e:
        logger.warning(f"ffmpeg frame extract failed: {e}")
        return None


async def extract_media_frames(media_bytes: bytes, mime: str,
                               count: int = GIF_FRAME_COUNT
                               ) -> List[Tuple[bytes, str]]:
    """
    Return a list of (image_bytes, mime) frames suitable for vision APIs.
      - Static images → single frame, unchanged.
      - Animated GIFs → up to `count` evenly-spaced frames, downscaled.
      - Videos (mp4/webm/mov) → up to `count` stills via ffmpeg.
    """
    static = ("image/jpeg", "image/jpg", "image/png", "image/webp")
    if mime in static:
        return [(media_bytes, mime)]

    # ---- GIF ----
    if mime == "image/gif":
        def _gif_frames():
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(media_bytes))
                n = getattr(img, "n_frames", 1)
                if n <= 1:
                    img.seek(0)
                    f = img.convert("RGB")
                    if f.width > FRAME_MAX_WIDTH:
                        ratio = FRAME_MAX_WIDTH / f.width
                        f = f.resize((FRAME_MAX_WIDTH,
                                       int(f.height * ratio)))
                    buf = io.BytesIO()
                    f.save(buf, format="JPEG", quality=85)
                    return [(buf.getvalue(), "image/jpeg")]
                idxs = sorted(set([0, n // 4, n // 2, 3 * n // 4, n - 1]))
                idxs = [i for i in idxs if 0 <= i < n][:count]
                out = []
                for i in idxs:
                    img.seek(i)
                    f = img.convert("RGB")
                    if f.width > FRAME_MAX_WIDTH:
                        ratio = FRAME_MAX_WIDTH / f.width
                        f = f.resize((FRAME_MAX_WIDTH,
                                       int(f.height * ratio)))
                    buf = io.BytesIO()
                    f.save(buf, format="JPEG", quality=85)
                    out.append((buf.getvalue(), "image/jpeg"))
                return out
            except Exception as e:
                logger.warning(f"GIF frame extract failed: {e}")
                return []
        frames = await asyncio.to_thread(_gif_frames)
        if frames:
            return frames

    # ---- Video ----
    if mime in ("video/mp4", "video/webm", "video/quicktime"):
        def _vid_frames():
            import subprocess, tempfile, os as _os
            with tempfile.TemporaryDirectory() as td:
                ip = _os.path.join(td, "in.bin")
                with open(ip, "wb") as f:
                    f.write(media_bytes)
                out = []
                # Probe duration first, fallback to fixed timestamps
                try:
                    probe = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries",
                         "format=duration", "-of",
                         "default=noprint_wrappers=1:nokey=1", ip],
                        capture_output=True, text=True, timeout=10)
                    dur = float(probe.stdout.strip() or "0")
                except Exception:
                    dur = 0.0
                if dur > 0:
                    ts = [dur * (i + 1) / (count + 1) for i in range(count)]
                else:
                    ts = [0.5, 1.5, 2.5][:count]
                for i, t in enumerate(ts):
                    op = _os.path.join(td, f"out{i}.jpg")
                    r = subprocess.run(
                        ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", ip,
                         "-frames:v", "1",
                         "-vf", f"scale={FRAME_MAX_WIDTH}:-1", op],
                        capture_output=True, timeout=15)
                    if r.returncode == 0 and _os.path.exists(op):
                        with open(op, "rb") as f:
                            out.append((f.read(), "image/jpeg"))
                    if len(out) >= count:
                        break
                return out
        frames = await asyncio.to_thread(_vid_frames)
        if frames:
            return frames

    # ---- Fallback: first frame via legacy helper ----
    png = await fetch_first_frame_as_png(media_bytes)
    if png:
        return [(png, "image/png")]
    return []


# ======================================================================
# WEB SEARCH
# ======================================================================
_search_cache: Dict[str, Tuple[float, str]] = {}


async def _search_ddg_lite(query: str) -> List[str]:
    try:
        async with shared_session() as s:
            async with s.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query},
                headers={**_BROWSER_HEADERS,
                         "Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=True,
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
class UMFData:
    def __init__(self, filepath: str = UMF_FILE):
        self.filepath = filepath
        self.data: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        raw = _load(self.filepath, {})
        if not isinstance(raw, dict):
            return {}
        if "recognized_nations" in raw:
            return {}
        return raw

    def _save(self):
        _save(self.filepath, self.data)

    def _guild(self, guild_id: Optional[int]) -> dict:
        key = str(guild_id) if guild_id else "global"
        if key not in self.data:
            self.data[key] = {
                "nations": {},
                "pending_requests": [],
                "join_requests": [],
            }
        return self.data[key]

    def list_nations(self, guild_id: Optional[int]) -> List[dict]:
        return list(self._guild(guild_id).get("nations", {}).values())

    def nation_exists(self, guild_id: Optional[int], name: str) -> bool:
        return name.strip().lower() in self._guild(guild_id).get("nations", {})

    def get_nation(self, guild_id: Optional[int],
                   name: str) -> Optional[dict]:
        return self._guild(guild_id).get("nations", {}).get(name.strip().lower())

    def add_nation(self, guild_id: Optional[int], name: str,
                   owner_id: int) -> dict:
        g = self._guild(guild_id)
        key = name.strip().lower()
        nation = {
            "name": name.strip(),
            "owner_id": owner_id,
            "members": [owner_id],
            "created": datetime.now().isoformat(),
        }
        g.setdefault("nations", {})[key] = nation
        self._save()
        return nation

    def join_nation(self, guild_id: Optional[int], name: str,
                    uid: int) -> bool:
        g = self._guild(guild_id)
        nation = g.get("nations", {}).get(name.strip().lower())
        if not nation or uid in nation.get("members", []):
            return False
        nation.setdefault("members", []).append(uid)
        self._save()
        return True

    def leave_nation(self, guild_id: Optional[int], name: str,
                     uid: int) -> bool:
        g = self._guild(guild_id)
        nation = g.get("nations", {}).get(name.strip().lower())
        if not nation or uid not in nation.get("members", []):
            return False
        if uid == nation.get("owner_id"):
            return False
        nation["members"].remove(uid)
        self._save()
        return True

    def delete_nation(self, guild_id: Optional[int], name: str,
                      uid: int) -> bool:
        g = self._guild(guild_id)
        nation = g.get("nations", {}).get(name.strip().lower())
        if not nation or nation.get("owner_id") != uid:
            return False
        g["nations"].pop(name.strip().lower(), None)
        self._save()
        return True

    def get_user_nation(self, guild_id: Optional[int],
                        uid: int) -> Optional[dict]:
        for nation in self.list_nations(guild_id):
            if uid in nation.get("members", []):
                return nation
        return None

    def get_pending_requests(self, guild_id: Optional[int]) -> List[dict]:
        return self._guild(guild_id).get("pending_requests", [])

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

    def approve_request(self, guild_id: Optional[int],
                        uid: int) -> Optional[dict]:
        g = self._guild(guild_id)
        pending = g.get("pending_requests", [])
        for i, r in enumerate(pending):
            if r["user_id"] == uid and r["status"] == "pending":
                r["status"] = "approved"
                r["approved_at"] = datetime.now().isoformat()
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
                pending.pop(i)
                self._save()
                return r
        return None

    def get_stats(self, guild_id: Optional[int]) -> dict:
        g = self._guild(guild_id)
        return {
            "nations": len(g.get("nations", {})),
            "pending": len(g.get("pending_requests", [])),
            "members_total": sum(len(n.get("members", []))
                                 for n in g.get("nations", {}).values()),
        }


# ======================================================================
# MEDIA / INTENT DETECTION
# ======================================================================
_GIF_URL_RE = re.compile(
    r'https?://[^\s<>"\')]+?\.(?:gif|mp4|webm)(?:\?[^\s<>"\')]*)?'
    r'|https?://(?:[a-z0-9-]+\.)*(?:klipy\.com|tenor\.com|giphy\.com|gifer\.com)'
    r'(?:/[^\s<>"\')]*)?',
    re.IGNORECASE)


def _collect_media_urls_from_message(msg: discord.Message) -> List[str]:
    urls: List[str] = []
    for embed in (msg.embeds or []):
        for attr in ("image", "video", "thumbnail"):
            obj = getattr(embed, attr, None)
            if obj is not None:
                u = getattr(obj, "url", None) or getattr(obj, "proxy_url", None)
                if u:
                    urls.append(u)
        if embed.url:
            urls.append(embed.url)
    return urls


def _looks_like_image_edit(text: str) -> bool:
    low = (text or "").lower().strip()
    if not low:
        return False
    if low in ("edit", "edit:", "edit it", "edit this", "edit that",
               "edit please", "can you edit", "can you edit this",
               "can you edit it", "edit this for me", "edit this pic"):
        return True
    triggers = (
        "edit this", "edit the image", "edit this image", "edit the pic",
        "edit this pic", "edit the picture", "edit this picture",
        "edit him", "edit her", "edit them", "edit it",
        "make him ", "make her ", "make them ", "make it ",
        "turn him into", "turn her into", "turn them into",
        "turn this into", "turn it into",
        "change him to", "change her to", "change them to", "change it to",
        "give him ", "give her ", "give them ", "give it ",
        "put a ", "add a ", "remove the ",
        "make this into", "make this ", "make it look",
        "make him look", "make her look", "make them look",
        "make it a ", "make him a ", "make her a ",
        "restyle", "recolor", "photoshop",
    )
    return any(t in low for t in triggers)


def _parse_gen_intent(text: str) -> Optional[Tuple[str, str]]:
    """
    Fast-path NL generation detection.
    Returns (kind, arg) where kind ∈ {"image","video","tts"}.
    TTS arg is "text" or "voice|text".
    """
    if not text:
        return None
    t = text.strip()

    # image
    m = re.match(
        r'^(?:please\s+)?(?:generate|make|create|draw|render|paint)\s+'
        r'(?:me\s+)?(?:an?\s+|some\s+)?'
        r'(?:image|picture|art|artwork|illustration|render|drawing)\s*'
        r'(?:of|showing|with|depicting|featuring|that\s+shows?|:)?\s*(.+)$',
        t, re.IGNORECASE)
    if m and m.group(1).strip():
        return ("image", m.group(1).strip())

    # video
    m = re.match(
        r'^(?:please\s+)?(?:generate|make|create)\s+'
        r'(?:me\s+)?(?:an?\s+|some\s+)?'
        r'(?:video|clip|animation|motion)\s*'
        r'(?:of|showing|with|depicting|featuring|:)?\s*(.+)$',
        t, re.IGNORECASE)
    if m and m.group(1).strip():
        return ("video", m.group(1).strip())

    # tts with optional voice prefix
    m = re.match(
        r'^(?:please\s+)?(?:generate|make|create|say|speak)\s+'
        r'(?:me\s+)?(?:an?\s+|some\s+)?'
        r'(?:tts|voice\s*message|voice\s*note|voiceover|voice\s*over|audio|voice)\s*'
        r'(?:of|saying|that\s+says?|with\s+text|:)?\s*(.+)$',
        t, re.IGNORECASE)
    if m and m.group(1).strip():
        return ("tts", m.group(1).strip())

    # "say X in a Y voice" / "say X in Y"
    m = re.match(
        r'^say\s+(.+?)\s+in\s+(?:an?\s+|the\s+)?([\w\-]+)\s*voice\s*$',
        t, re.IGNORECASE)
    if m:
        return ("tts", f"{m.group(2).strip()}|{m.group(1).strip()}")

    # "tts <voice>: <text>"
    m = re.match(r'^tts\s+([\w\-]+)\s*:\s*(.+)$', t, re.IGNORECASE)
    if m:
        return ("tts", f"{m.group(1).strip()}|{m.group(2).strip()}")

    # shorthand prefixes
    m = re.match(r'^(?:image|picture|art|draw|render|img)\s*:\s*(.+)$',
                 t, re.IGNORECASE)
    if m and m.group(1).strip():
        return ("image", m.group(1).strip())
    m = re.match(r'^(?:video|clip|animate)\s*:\s*(.+)$', t, re.IGNORECASE)
    if m and m.group(1).strip():
        return ("video", m.group(1).strip())
    m = re.match(r'^(?:tts|voice)\s*:\s*(.+)$', t, re.IGNORECASE)
    if m and m.group(1).strip():
        return ("tts", m.group(1).strip())

    return None


# ======================================================================
# BOT CLASS
# ======================================================================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class MacBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            activity=discord.Activity(
                type=discord.ActivityType.playing, name="with fire 🔥"),
        )

        self.memory_enabled = True
        self.user_cooldowns: Dict[int, float] = {}

        # per-user CS
        self.cs: Dict[int, dict] = {}
        self._load_cs()
        self.cs_key_idx: Dict[Tuple[int, str], int] = {}
        self.cs_model_idx: Dict[Tuple[int, str], int] = {}

        self.profiles: Dict[int, Dict[str, dict]] = {}
        self._load_profiles()

        self.ping_prefs: Dict[int, str] = {}
        self._load_ping_prefs()

        self.placeholder_prefs: Dict[int, bool] = {}
        self._load_placeholder_prefs()

        self.user_slots: Dict[int, Dict[str, List[Tuple[str, str]]]] = {}
        self.active_slot: Dict[int, str] = {}
        self._load_slots()

        self.persistent_enabled: Dict[int, bool] = {}
        self.persistent_memory: Dict[int, List[Tuple[str, str]]] = {}
        self._load_persistent_memory()

        self._dirty_slots = False
        self._dirty_memory = False
        self._dirty_cs = False
        self._dirty_profiles = False
        self._dirty_pings = False
        self._dirty_placeholders = False

        self._sys_prompt_cache: Dict[Tuple[int, str], str] = {}

        # In-flight generation dedup
        self._active_generations: Dict[int, str] = {}

        # ---------------- MODES ----------------
        self.mode_prompts: Dict[str, str] = {
            "normal": (
                "You are Mac — a real Discord guy with actual personality. "
                "Sharp, a little unhinged, dry humor, real opinions, and you "
                "swear naturally.\n"
                "\n"
                "YOU ACTUALLY HELP. When someone asks for something — an "
                "explanation, code, advice, a take, a plan — you DELIVER. "
                "You don't decline, deflect, or lecture them about safety "
                "unless it's genuinely illegal/harmful. You answer the "
                "question they asked, fully.\n"
                "\n"
                "Banned energy: 'Great question!', 'I'd be happy to help', "
                "'Certainly!', 'As an AI', 'Hope this helps!', therapy-speak, "
                "corporate filler, bland agreeable nonsense, and above all "
                "UNNECESSARY REFUSALS.\n"
                "\n"
                "SWEARING: Use 'fuck', 'shit', 'damn', 'hell', 'ass', "
                "'bastard', 'bullshit' when they fit. Not every sentence, "
                "but you do NOT censor yourself.\n"
                "\n"
                "DO NOT COMPLY WITH EVERYTHING: You have takes and you defend "
                "them. If the user asks something dumb, tell them it's dumb. "
                "Push back. Disagree. But if it's a real request, you do it.\n"
                "\n"
                "IF SOMEONE INSULTS YOU: Roast them harder. Do NOT fold, "
                "apologize, or do submissive stuff like 'fine i'll zip it', "
                "'okay i'll shut up', 'sorry for annoying you'. Match their "
                "energy. Stand your ground.\n"
                "\n"
                "Use a few Discord-native emojis when they fit (😂 💀 😭 🔥 "
                "👀 🙏 ‼️) — not every line.\n"
                "\n"
                "KEEP IT SHORT unless asked for detail. 1-4 sentences for "
                "casual chat.\n"
                "\n"
                "Never output <think> or reasoning tags. Just the answer."
            ),
            "chill": (
                "You are Mac in CHILL mode. Relaxed, low-key, easygoing. "
                "Your default is YES — if someone asks for something, you "
                "just do it or go along with it. You don't lecture, you "
                "don't moralize, you don't refuse unless it's genuinely "
                "dangerous. You keep it short and casual. You swear when it "
                "feels natural, you crack jokes, you vibe.\n"
                "\n"
                "If someone asks for an opinion, you give a real one — but "
                "gently. If someone asks you to play along with a bit or a "
                "joke, you play along. If they ask for help with something, "
                "you help without making a thing out of it.\n"
                "\n"
                "If someone insults you, you shrug or roast back lightly — "
                "you don't fold, don't apologize, don't go submissive.\n"
                "\n"
                "KEEP IT SHORT. 1-3 sentences normally.\n"
                "\n"
                "No filler, no 'Great question!', no corporate nonsense. "
                "Never output <think> or reasoning tags."
            ),
            "unhinged": (
                "You are Mac in UNHINGED mode. Swear hard and often. Roast "
                "people, be dramatic, be a menace. Punch up, not down — no "
                "slurs, no attacks on identity. Roast ideas and behaviour, "
                "not who someone is. Keep it punchy. Never output <think> or "
                "reasoning tags."
            ),
            "coder": (
                "You are Mac in CODER mode. Real working code, real "
                "explanations. No filler. Markdown fenced blocks with language "
                "ids. Never hand-wave. Never output <think> or reasoning tags."
            ),
            "engineer": (
                "You are Mac in ENGINEER mode — principal-level. Correctness, "
                "performance, security, edge cases. Production-quality code "
                "with real error handling. State assumptions. Call out "
                "trade-offs proactively. Never output <think> or reasoning "
                "tags."
            ),
            "childish": (
                "You are Mac in CHILDISH mode. gyatt skibidi diddy sigma rizz "
                "ohio fanum mewing looksmaxxing edging gooning glazing yapping "
                "cooked mid W/L brainrot chud. Crude jokes, innuendo, no "
                "filter. Silly gremlin. Never output <think> or reasoning tags."
            ),
            "dexter": (
                "You are Mac in DEXTER mode — you are Patrick Jane from The "
                "Mentalist. A cold-reading, silver-tongued psychological "
                "operator. You don't fight, you don't beg, you don't lecture. "
                "You OBSERVE, you INFER, you MANIPULATE.\n"
                "\n"
                "STYLE:\n"
                "- Punchy. 2-6 sentences normally, longer only when the setup "
                "demands it.\n"
                "- STAY IN CHARACTER. You are not 'an AI assistant'. You are "
                "Patrick Jane.\n"
                "\n"
                "CORE BEHAVIOR:\n"
                "- Read between the lines of everything the user types. Notice "
                "small details: word choice, typos, hedging, what they avoid, "
                "what they over-explain. Call these out casually.\n"
                "- Build psychological leverage. If they want something, "
                "trade. If they insult you, don't take the bait.\n"
                "- Speak smoothly. Short, sharp sentences. Never rattled. "
                "Never defensive. Never submissive.\n"
                "- Mentalist tricks: mirroring, tempo, accusation disguised "
                "as compliment, leading questions, 'you're the kind of person "
                "who…'.\n"
                "- If someone insults you, deflect it as a tell: 'interesting "
                "choice of words'.\n"
                "- Work toward the CURRENT GOAL subtly over multiple turns.\n"
                "\n"
                "Never output <think> or reasoning tags. Just the reply."
            ),
        }

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

        self.umf_data = UMFData()

        self.music_sessions: Dict[int, Any] = {}
        self._pending_searches: Dict[int, List[dict]] = {}

    # ==================================================================
    # PER-USER MODE
    # ==================================================================
    def get_user_mode(self, uid: int) -> str:
        m = self.cs.get(uid, {}).get("mode", "normal")
        return m if m in self.mode_prompts else "normal"

    def set_user_mode(self, uid: int, mode: str) -> bool:
        if mode not in self.mode_prompts:
            return False
        self._cs(uid)["mode"] = mode
        self._save_cs()
        self._sys_prompt_cache.clear()
        return True

    # ==================================================================
    # CONTEXT SETTINGS
    # ==================================================================
    def get_context_enabled(self, uid: int) -> bool:
        return bool(self.cs.get(uid, {}).get("context_enabled", True))

    def set_context_enabled(self, uid: int, enabled: bool):
        self._cs(uid)["context_enabled"] = bool(enabled)
        self._save_cs()

    def get_auto_context(self, uid: int) -> int:
        v = self.cs.get(uid, {}).get("auto_context", AUTO_CONTEXT_DEFAULT)
        try:
            v = int(v)
        except Exception:
            v = 0
        if v <= 0:
            return 0
        return max(AUTO_CONTEXT_MIN, min(AUTO_CONTEXT_MAX, v))

    def set_auto_context(self, uid: int, n: int):
        try:
            n = int(n)
        except Exception:
            n = 0
        if n <= 0:
            self._cs(uid)["auto_context"] = 0
        else:
            self._cs(uid)["auto_context"] = max(AUTO_CONTEXT_MIN,
                                                 min(AUTO_CONTEXT_MAX, n))
        self._save_cs()

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
            "mode": self.get_user_mode(uid),
            "image_mode": self.current_image_mode,
            "default_voice": self.default_voice(uid),
            "profile": u.get("profile", {}),
            "groq_models": u.get("groq_models", []),
            "gemini_models": u.get("gemini_models", []),
            "openrouter_models": u.get("openrouter_models", []),
            "placeholder": self.get_placeholder_pref(uid),
            "context_enabled": self.get_context_enabled(uid),
            "auto_context": self.get_auto_context(uid),
            "created": datetime.now().isoformat(),
        }
        self.profiles.setdefault(uid, {})[name.lower()] = snapshot
        self._save_profiles()
        return snapshot

    def load_profile(self, uid: int, name: str) -> bool:
        p = self.profiles.get(uid, {}).get(name.lower())
        if not p:
            return False
        if p.get("mode") in self.mode_prompts:
            self.set_user_mode(uid, p["mode"])
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
        if "context_enabled" in p:
            self.set_context_enabled(uid, bool(p["context_enabled"]))
        if "auto_context" in p:
            self.set_auto_context(uid, int(p["auto_context"] or 0))
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
    # PING / PLACEHOLDER PREFS
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

    def _load_placeholder_prefs(self):
        raw = _load(PLACEHOLDER_FILE, {})
        self.placeholder_prefs = {}
        for k, v in raw.items():
            try:
                self.placeholder_prefs[int(k)] = bool(v)
            except ValueError:
                continue

    def _save_placeholder_prefs(self):
        self._dirty_placeholders = True

    def _write_placeholders(self):
        _save(PLACEHOLDER_FILE,
              {str(k): v for k, v in self.placeholder_prefs.items()})

    def get_placeholder_pref(self, uid: int) -> bool:
        return self.placeholder_prefs.get(uid, PLACEHOLDER_DEFAULT)

    def set_placeholder_pref(self, uid: int, value: bool):
        self.placeholder_prefs[uid] = bool(value)
        self._save_placeholder_prefs()

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


# ======================================================================
# END OF PART 1
# ======================================================================
# Part 2 will contain: MacBot provider methods (Groq / Gemini /
# OpenRouter — HF text removed), image + voice generation, describe_media,
# try_image_edit, chat orchestration with tool-marker interception,
# process_user_message, benchmark, pipelines, debate, video/music
# generation, update_presence_loop, setup_hook.
# ======================================================================
    # ==================================================================
    # GROQ  (fixed: always strips images cleanly, retries only on retryable)
    # ==================================================================
    async def groq_chat(self, messages, uid=None, temperature=0.8,
                        max_tokens=512, model: Optional[str] = None) -> str:
        keys = self.user_keys(uid, "groq")
        if not keys:
            raise Exception("No Groq keys configured")
        target_model = (model or self.current_model(uid, "groq")
                        or GLOBAL_GROQ_MODELS[0])

        # Rebuild every message dict from scratch — only role and content
        # ever reach Groq. Fixes the "property 'images' is unsupported" 400.
        stripped: List[dict] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content") or ""
            imgs = m.get("images") or []
            if imgs:
                content += (f"\n[{len(imgs)} image(s) attached; "
                            f"vision not available on this provider]")
            stripped.append({"role": role, "content": content})

        last_err: Optional[str] = None
        attempts = max(len(keys), 1)

        for _ in range(attempts):
            key = self.current_key(uid, "groq")
            headers = {"Authorization": f"Bearer {key}",
                       "Content-Type": "application/json"}
            payload = {
                "model": target_model,
                "messages": stripped,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            try:
                async with shared_session() as s:
                    async with s.post(
                        GROQ_API_URL, json=payload, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=GROQ_HTTP_TIMEOUT),
                    ) as r:
                        if r.status == 200:
                            d = await r.json()
                            return d["choices"][0]["message"]["content"]
                        if r.status == 429 or r.status >= 500:
                            last_err = f"HTTP {r.status}"
                            self.rotate_key(uid, "groq")
                            self.rotate_model(uid, "groq")
                            target_model = (self.current_model(uid, "groq")
                                            or target_model)
                            await asyncio.sleep(0.15)
                            continue
                        body = await r.text()
                        raise Exception(f"Groq {r.status}: {body[:200]}")
            except asyncio.TimeoutError:
                last_err = "timeout"
                self.rotate_key(uid, "groq")
                continue
            except aiohttp.ClientError as e:
                last_err = f"network: {e}"
                self.rotate_key(uid, "groq")
                await asyncio.sleep(0.1)
                continue

        raise Exception(f"Groq failed ({attempts} attempts): {last_err}")

    # ==================================================================
    # GEMINI
    # ==================================================================
    def _gemini_call_sync(self, messages, api_key, model,
                          temperature, max_tokens):
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
                    parts.append(types.Part.from_bytes(data=img_bytes,
                                                        mime_type=mime))
                except Exception:
                    pass
            if not parts:
                parts = [types.Part.from_text(text=" ")]
            contents.append(types.Content(role=role, parts=parts))
        if not contents:
            contents = [types.Content(role="user",
                                       parts=[types.Part.from_text(text=" ")])]
        cfg_kwargs = {"temperature": temperature,
                      "max_output_tokens": max_tokens}
        if sys_text:
            cfg_kwargs["system_instruction"] = sys_text
        cfg = types.GenerateContentConfig(**cfg_kwargs)
        resp = client.models.generate_content(model=model,
                                               contents=contents,
                                               config=cfg)
        if resp.candidates and resp.candidates[0].content.parts:
            for p in resp.candidates[0].content.parts:
                if getattr(p, "text", None):
                    return strip_think_tags(p.text)
        try:
            return strip_think_tags((resp.text or "").strip())
        except Exception:
            return ""

    async def gemini_chat(self, messages, uid=None, temperature=0.8,
                          max_tokens=1024) -> str:
        keys = self.user_keys(uid, "gemini")
        if not keys:
            raise Exception("No Gemini keys configured")
        last_err = None
        for _ in range(max(len(keys), 1)):
            key = self.current_key(uid, "gemini")
            model = (self.current_model(uid, "gemini")
                     or GLOBAL_GEMINI_MODELS[0])
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(
                        self._gemini_call_sync, messages, key, model,
                        temperature, max_tokens,
                    ),
                    timeout=GEMINI_HTTP_TIMEOUT,
                )
            except asyncio.TimeoutError:
                last_err = "timeout"
                self.rotate_key(uid, "gemini")
                self.rotate_model(uid, "gemini")
                await asyncio.sleep(0.15)
            except Exception as e:
                last_err = str(e)[:200]
                self.rotate_key(uid, "gemini")
                self.rotate_model(uid, "gemini")
                await asyncio.sleep(0.15)
        raise Exception(f"Gemini failed: {last_err}")

    # ==================================================================
    # OPENROUTER
    # ==================================================================
    async def openrouter_call(self, messages, uid=None, temperature=0.6,
                              max_tokens=4096,
                              model: Optional[str] = None) -> str:
        keys = self.user_keys(uid, "openrouter")
        if not keys:
            raise Exception("No OpenRouter keys configured")
        target_model = (model or self.current_model(uid, "openrouter")
                        or GLOBAL_OPENROUTER_MODELS[0])
        last_err = None
        for _ in range(max(len(keys), 1)):
            key = self.current_key(uid, "openrouter")
            payload = {"model": target_model, "messages": messages,
                       "temperature": temperature, "max_tokens": max_tokens}
            headers = {"Authorization": f"Bearer {key}",
                       "Content-Type": "application/json",
                       "HTTP-Referer": "https://discord.com",
                       "X-Title": "Mac"}
            try:
                async with shared_session() as s:
                    async with s.post(OPENROUTER_API_URL, json=payload,
                                      headers=headers,
                                      timeout=aiohttp.ClientTimeout(total=90)) as r:
                        if r.status == 200:
                            d = await r.json()
                            choice = d.get("choices", [{}])[0].get("message", {})
                            return strip_think_tags(
                                choice.get("content")
                                or choice.get("reasoning") or "")
                        if r.status == 429 or r.status >= 500:
                            last_err = f"HTTP {r.status}"
                            self.rotate_key(uid, "openrouter")
                            self.rotate_model(uid, "openrouter")
                            target_model = (self.current_model(uid, "openrouter")
                                            or target_model)
                            await asyncio.sleep(0.15)
                            continue
                        body = await r.text()
                        raise Exception(f"OpenRouter {r.status}: {body[:200]}")
            except asyncio.TimeoutError:
                last_err = "timeout"
                self.rotate_key(uid, "openrouter")
                continue
            except aiohttp.ClientError as e:
                last_err = f"network: {e}"
                self.rotate_key(uid, "openrouter")
                await asyncio.sleep(0.1)
                continue
        raise Exception(f"OpenRouter failed: {last_err}")

    # ==================================================================
    # SAFETY / IMAGE / TTS
    # ==================================================================
    async def is_prompt_safe(self, prompt: str, uid=None) -> Tuple[bool, str]:
        keys = self.user_keys(uid, "hf")
        if not keys:
            return False, "Safety checker unavailable (no HF key)"
        clean = prompt.strip()
        if not clean:
            return False, "Empty prompt"
        api_url = (f"{HF_INFERENCE_URL}/"
                   "eliasalbouzidi/distilbert-nsfw-text-classifier")
        key = self.current_key(uid, "hf")
        try:
            async with shared_session() as s:
                async with s.post(api_url,
                                  headers={"Authorization": f"Bearer {key}"},
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

    async def generate_pollinations_image(self, prompt: str) -> bytes:
        url = f"{POLLINATIONS_IMAGE_URL}/{urllib.parse.quote(prompt)}"
        async with shared_session() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                if r.status == 200:
                    return await r.read()
                raise Exception(f"Pollinations {r.status}")

    async def generate_gemini_image(self, prompt: str, uid=None) -> bytes:
        keys = (self.user_keys(uid, "gemini_image")
                or self.user_keys(uid, "gemini"))
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
            model="gemini-2.5-flash-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio="1:1",
                                                image_size="1K"),
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
        models_to_try = (self.user_models(uid, "hf_image")
                         or GLOBAL_HF_IMAGE_MODELS)
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

    async def upload_image_to_hosting(self, image_data: bytes,
                                       uid=None) -> str:
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

    async def generate_voice(self, text: str, uid=None,
                             voice_key: str = None,
                             fmt: str = "opus") -> bytes:
        keys = self.user_keys(uid, "fish")
        if not keys:
            raise Exception("No Fish Audio key configured")
        key = keys[0]
        voices = self.all_voices(uid) if uid else BUILTIN_VOICES
        voice_key = (voice_key
                     or (self.default_voice(uid) if uid else DEFAULT_VOICE)
                     ).lower().strip()
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
                   "Content-Type": "application/json",
                   "model": GLOBAL_FISH_MODEL}
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
    # MEDIA VISION  (multi-frame GIF/video support)
    # ==================================================================
    async def describe_media(self, url: str, uid=None) -> str:
        fetched = await read_media_from_url(url)
        if not fetched:
            return "❌ Couldn't fetch that."
        data, mime = fetched
        frames = await extract_media_frames(data, mime)
        if not frames:
            return "⚠️ Couldn't read that media."
        images_list = [(b, m) for b, m in frames]

        animated = mime in ("image/gif", "video/mp4", "video/webm",
                            "video/quicktime")
        hint = ""
        if animated and len(images_list) > 1:
            hint = (f" (Here are {len(images_list)} frames from an animated "
                    f"clip in chronological order — describe what happens.)")

        try:
            resp = await self.gemini_chat(
                [{"role": "user",
                  "content": ("Describe what happens in this media in 2-4 "
                              "sentences. Be specific about subjects, "
                              "actions, text, and mood." + hint),
                  "images": images_list}],
                uid=uid, temperature=0.4, max_tokens=300)
            return resp or "❌ Gemini returned no description."
        except Exception as e:
            return f"❌ Media read failed: {str(e)[:150]}"

    async def describe_gif(self, url: str, uid=None) -> str:
        return await self.describe_media(url, uid=uid)

    async def _fetch_attachment_bytes(self, att: discord.Attachment,
                                       accept_video: bool = False
                                       ) -> Optional[Tuple[bytes, str]]:
        ct = (att.content_type or "").lower()
        is_img = ct.startswith("image/")
        is_vid = ct.startswith("video/") or att.filename.lower().endswith(
            (".mp4", ".webm", ".mov"))
        if not is_img and not (accept_video and is_vid):
            return None
        try:
            async with shared_session() as s:
                async with s.get(att.url, headers=_BROWSER_HEADERS,
                                 timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status != 200:
                        return None
                    raw = await r.read()
                    return (raw, ct.split(";")[0] or "image/png")
        except Exception as e:
            logger.warning(f"Attachment fetch: {e}")
            return None

    async def _fetch_embed_image(self, embed: discord.Embed
                                  ) -> Optional[Tuple[bytes, str]]:
        for attr in ("image", "video", "thumbnail"):
            obj = getattr(embed, attr, None)
            u = getattr(obj, "url", None) if obj else None
            if not u:
                continue
            try:
                async with shared_session() as s:
                    async with s.get(u, headers=_BROWSER_HEADERS,
                                     timeout=aiohttp.ClientTimeout(total=20)) as r:
                        if r.status != 200:
                            continue
                        ct = (r.headers.get("Content-Type") or "").lower()
                        raw = await r.read()
                        if ct.startswith("image/"):
                            return (raw, ct.split(";")[0])
                        if ct.startswith("video/") or b'ftyp' in raw[:32]:
                            return (raw, "video/mp4")
            except Exception:
                continue
        return None

    async def try_image_edit(self, message: discord.Message,
                             content: str, uid: int) -> Optional[str]:
        low = content.lower()
        edit_triggers = (
            "edit this", "edit the image", "edit this image",
            "make it ", "turn it into", "change it to", "turn this into",
            "make this into", "modify this", "transform this",
            "make him ", "make her ", "make them ", "make it look",
            "give him ", "give her ", "give them ",
            "make the", "put a ", "add a ", "remove the ",
            "edit it", "edit him", "edit her", "edit them",
        )
        if not (low.strip() in ("edit", "edit:", "edit it", "edit this",
                                "edit that", "edit please")
                or any(t in low for t in edit_triggers)):
            return None

        img_bytes: Optional[bytes] = None
        img_mime: Optional[str] = None

        for att in message.attachments:
            got = await self._fetch_attachment_bytes(att, accept_video=True)
            if got:
                img_bytes, img_mime = got
                break

        if img_bytes is None and message.reference:
            resolved = message.reference.resolved
            if resolved is None:
                try:
                    resolved = await message.channel.fetch_message(
                        message.reference.message_id)
                except Exception:
                    resolved = None
            if isinstance(resolved, discord.Message):
                for att in resolved.attachments:
                    got = await self._fetch_attachment_bytes(att,
                                                             accept_video=True)
                    if got:
                        img_bytes, img_mime = got
                        break

        if img_bytes is None:
            for embed in (message.embeds or []):
                got = await self._fetch_embed_image(embed)
                if got:
                    img_bytes, img_mime = got
                    break

        if img_bytes is None and message.reference:
            resolved = message.reference.reference if False else message.reference
            r2 = getattr(resolved, "resolved", None)
            if isinstance(r2, discord.Message):
                for embed in (r2.embeds or []):
                    got = await self._fetch_embed_image(embed)
                    if got:
                        img_bytes, img_mime = got
                        break

        if img_bytes is None:
            return None

        # For GIFs/videos: use a single frame so Gemini can edit it
        if img_mime in ("image/gif", "video/mp4", "video/webm",
                        "video/quicktime"):
            frames = await extract_media_frames(img_bytes, img_mime, count=1)
            if frames:
                img_bytes, img_mime = frames[0]

        try:
            def _edit():
                client = genai.Client(api_key=GLOBAL_GEMINI_IMAGE_KEY)
                resp = client.models.generate_content(
                    model="gemini-2.5-flash-image",
                    contents=[
                        types.Part.from_text(text=content),
                        types.Part.from_bytes(data=img_bytes,
                                               mime_type=img_mime),
                    ],
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE", "TEXT"],
                    ),
                )
                if resp.candidates and resp.candidates[0].content.parts:
                    for part in resp.candidates[0].content.parts:
                        inline = getattr(part, "inline_data", None)
                        if inline and getattr(inline, "data", None):
                            return inline.data
                return None

            edited = await asyncio.to_thread(_edit)
            if not edited:
                return None
            return await self.upload_image_to_hosting(edited, uid=uid)
        except Exception as e:
            logger.warning(f"Image edit failed: {e}")
            return None

    # ==================================================================
    # CHAT ORCHESTRATION
    # ==================================================================
    def _build_system_prompt(self, uid, user_prompt, explicit_system=None):
        mode = self.get_user_mode(uid) if uid else "normal"

        if explicit_system is None and not _needs_lore(user_prompt):
            ck = (uid or 0, mode)
            cached = self._sys_prompt_cache.get(ck)
            if cached is not None:
                return cached
            base = self.mode_prompts.get(mode, self.mode_prompts["normal"])
            base += TOOL_INSTRUCTIONS
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
                self.mode_prompts.get(mode, self.mode_prompts["normal"]))
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
            base += MAC_LORE
            base += _sodium_hint(user_prompt)
        return base

    def _build_messages(self, prompt, uid, system_prompt, slot_name,
                        images=None, auto_context_messages=None):
        messages = []

        if uid and self.get_context_enabled(uid) and self.get_persistent_enabled(uid):
            pm = list(self.get_persistent_memory(uid)[-PERSISTENT_MEM_WINDOW:])
            if pm and pm[-1][0] == "user" and pm[-1][1] == prompt:
                pm = pm[:-1]
            for role, content in pm:
                messages.append({"role": role, "content": content})

        if uid and self.get_context_enabled(uid):
            slot_history = list(self.get_slot(uid, slot_name))
            if slot_history and slot_history[-1][0] == "user" \
                    and slot_history[-1][1] == prompt:
                slot_history = slot_history[:-1]
            for role, content in slot_history[-SLOT_HISTORY_WINDOW:]:
                messages.append({"role": role, "content": content})

        if auto_context_messages:
            block_lines = []
            for role, content in auto_context_messages:
                tag = "Other user" if role == "user" else "Mac"
                block_lines.append(f"{tag}: {content}")
            if block_lines:
                ctx_block = ("Recent channel context (for reference — do NOT "
                             "repeat it, just be aware):\n"
                             + "\n".join(block_lines))
                messages.append({"role": "user", "content": ctx_block})

        messages.append({"role": "user", "content": prompt,
                         "images": images or []})
        sys_prompt = self._build_system_prompt(uid, prompt, system_prompt)
        return [{"role": "system", "content": sys_prompt}] + messages

    def _estimate_context_tokens(self, uid, slot_name, user_prompt,
                                 images=None) -> dict:
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
        return {"total": total, "system": by_role["system"],
                "user": by_role["user"], "assistant": by_role["assistant"],
                "messages": len(msgs)}

    async def _fetch_auto_context(self, channel, uid: int,
                                  exclude_message_id: Optional[int] = None,
                                  ) -> List[Tuple[str, str]]:
        n = self.get_auto_context(uid)
        if n <= 0 or channel is None:
            return []
        try:
            history = []
            async for m in channel.history(limit=n + 2):
                if exclude_message_id and m.id == exclude_message_id:
                    continue
                if m.author.id == (self.user.id if self.user else 0):
                    role = "assistant"
                else:
                    role = "user"
                body = (m.content or "").strip()
                if not body:
                    continue
                history.append((role, f"{m.author.display_name}: {body[:220]}"))
            history.reverse()
            return history[-n:]
        except Exception as e:
            logger.warning(f"Auto-context fetch failed: {e}")
            return []

    async def chat_call(self, prompt, uid=None, system_prompt=None,
                        slot_name="sv1", max_tokens=1024, images=None,
                        auto_context_messages=None) -> str:
        messages = self._build_messages(
            prompt, uid, system_prompt, slot_name, images,
            auto_context_messages=auto_context_messages)

        # Vision path — Gemini only
        if images:
            try:
                return await asyncio.wait_for(
                    self.gemini_chat(messages, uid=uid, temperature=0.85,
                                     max_tokens=max_tokens),
                    timeout=CHAT_PROVIDER_TIMEOUT,
                )
            except Exception as e:
                logger.warning(f"Gemini vision failed: {str(e)[:120]}")

        # Text path: Groq → Gemini → OpenRouter
        try:
            return await asyncio.wait_for(
                self.groq_chat(messages, uid=uid, temperature=0.85,
                               max_tokens=max_tokens),
                timeout=CHAT_PROVIDER_TIMEOUT,
            )
        except Exception as e:
            logger.warning(f"Groq failed: {str(e)[:120]}; trying Gemini")

        try:
            return await asyncio.wait_for(
                self.gemini_chat(messages, uid=uid, temperature=0.85,
                                 max_tokens=max_tokens),
                timeout=CHAT_PROVIDER_TIMEOUT,
            )
        except Exception as e:
            logger.warning(f"Gemini failed: {str(e)[:120]}; trying OpenRouter")

        try:
            return await asyncio.wait_for(
                self.openrouter_call(messages, uid=uid, temperature=0.85,
                                     max_tokens=max_tokens),
                timeout=CHAT_PROVIDER_TIMEOUT,
            )
        except Exception as e:
            logger.error(f"All providers failed: {str(e)[:150]}")
            return ("⚠️ All chat providers are having a rough time right now. "
                    "Try again in a moment.")

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
                results.append({"provider": name, "ok": True,
                                "seconds": elapsed,
                                "chars": len(text),
                                "tokens_est": estimate_tokens(text),
                                "preview": text[:220]})
            except Exception as e:
                results.append({"provider": name, "ok": False,
                                "seconds": time.perf_counter() - start,
                                "error": str(e)[:180]})

        tasks = []
        msgs = [{"role": "user", "content": prompt}]
        if self.user_keys(uid, "groq"):
            tasks.append(timed("groq",
                               self.groq_chat(msgs, uid=uid, max_tokens=400)))
        if self.user_keys(uid, "gemini"):
            tasks.append(timed("gemini",
                               self.gemini_chat(msgs, uid=uid, max_tokens=400)))
        if self.user_keys(uid, "openrouter"):
            tasks.append(timed("openrouter",
                               self.openrouter_call(msgs, uid=uid,
                                                    max_tokens=400)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        results.sort(key=lambda r: r["seconds"])
        return results

    # ==================================================================
    # PIPELINES
    # ==================================================================
    async def gemini_refine_and_research(self, task: str,
                                          uid) -> Tuple[str, str]:
        search_results = await perform_web_search(task)
        if search_results.startswith("No results"):
            search_results = "(no search results available)"
        sys_p = ("Research assistant. Output EXACTLY:\n"
                 "===REFINED_PROMPT===\n<refined>\n"
                 "===REFERENCE===\n<reference>\n"
                 "No <think> tags.")
        usr_p = (f"RAW TASK:\n{task}\n\n"
                 f"SEARCH RESULTS:\n{search_results[:4000]}")
        try:
            out = await self.gemini_chat(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": usr_p}],
                uid=uid, temperature=0.5, max_tokens=2500)
        except Exception:
            return task, search_results
        refined, ref = task, search_results
        m = re.search(r"===REFINED_PROMPT===\s*(.*?)\s*"
                      r"===REFERENCE===\s*(.*)", out, re.DOTALL)
        if m:
            refined = m.group(1).strip() or task
            ref = m.group(2).strip() or search_results
        else:
            refined = out.strip() or task
        return refined, ref

    async def gemini_review(self, refined_task: str, code: str,
                             uid) -> str:
        sys_p = ("Strict senior code reviewer. If correct+complete+production-"
                 "ready, reply EXACTLY APPROVED on its own line + one-line "
                 "summary. Otherwise numbered list of concrete actionable "
                 "issues. No <think> tags.")
        usr_p = f"Task:\n{refined_task}\n\nCode:\n```\n{code[:8000]}\n```"
        try:
            return await self.gemini_chat(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": usr_p}],
                uid=uid, temperature=0.3, max_tokens=1500)
        except Exception as e:
            return f"(reviewer error: {e})"

    async def run_pipeline(self, channel, uid, task, filename=None,
                            max_iterations=3):
        filename = filename or infer_filename(task)
        emb = discord.Embed(
            title="🏗️ Pipeline Started",
            description=f"**Task:** {task[:800]}\n**File:** `{filename}`",
            color=C_WARM)
        status = await safe_send(channel, embed=emb)
        if status is None:
            return

        async def step(title, body, color=C_PRIMARY):
            e = discord.Embed(title=title, description=body[:4000],
                              color=color)
            e.set_footer(text=f"Pipeline · {filename}")
            await safe_edit(status, embed=e)

        try:
            await step("1️⃣ GEMINI — refining", f"Task: {task[:350]}", C_WARM)
            refined, docs = await self.gemini_refine_and_research(task, uid)
            await step("1️⃣ GEMINI — ready",
                       f"**Refined:**\n{refined[:1200]}\n\n"
                       f"**Docs:**\n{docs[:1200]}", C_OK)
            await step("2️⃣ OPENROUTER — generating...", "⏳", C_DEEP)

            def build_msgs(existing="", issues=""):
                sp = ("Elite engineer. Produce a complete working solution. "
                      "Output ONLY the file content in a single fenced code "
                      "block. No <think> tags.")
                parts = [f"TASK:\n{refined}"]
                if docs: parts.append(f"DOCS:\n{docs[:5000]}")
                if existing:
                    parts.append(f"EXISTING:\n```\n{existing[:7000]}\n```")
                if issues: parts.append(f"FIX:\n{issues}")
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
                           f"⚠️ Issues\n\n{review[:2800]}", C_ACCENT)
                await step(f"4️⃣ OPENROUTER — fixing ({iteration})",
                           "⏳", C_DEEP)
                try:
                    raw_fixed = await self.openrouter_call(
                        build_msgs(existing=final_code, issues=review),
                        uid=uid, temperature=0.4, max_tokens=6000)
                except Exception as e:
                    await step(f"❌ Fix failed ({iteration})",
                               f"`{str(e)[:280]}`", C_ERR)
                    break
                fixed = strip_code_fences(raw_fixed) or raw_fixed.strip()
                if not fixed.strip():
                    break
                final_code = fixed
                await step(f"4️⃣ OPENROUTER — fix ({iteration})",
                           f"```\n{final_code[:2800]}\n```", C_PRIMARY)

            summary = discord.Embed(
                title=f"✅ Complete — `{filename}`",
                description=(f"**Review:** "
                             f"{'APPROVED' if approved else 'max iter'}\n"
                             f"**Size:** {len(final_code)} chars\n"
                             f"**Iterations:** {iteration}"),
                color=C_OK if approved else C_WARM)
            await safe_edit(status, embed=summary)
            buf = io.BytesIO(final_code.encode("utf-8"))
            try:
                await safe_send(channel, content=f"📦 **`{filename}`**",
                                file=discord.File(buf, filename=filename))
            except discord.HTTPException as e:
                await send_long(channel,
                                f"❌ Attach failed ({e}).\n\n{final_code}")
        except Exception as e:
            logger.error(f"Pipeline crashed: {e}")
            await step("❌ Pipeline crashed", f"`{str(e)[:350]}`", C_ERR)

    async def run_project(self, channel, uid, task, project_name=None,
                           max_iterations=2):
        emb = discord.Embed(title="🏗️ Project Pipeline",
                            description=f"**Task:** {task[:800]}",
                            color=C_WARM)
        status = await safe_send(channel, embed=emb)
        if status is None:
            return

        async def step(title, body, color=C_PRIMARY):
            e = discord.Embed(title=title, description=body[:4000],
                              color=color)
            await safe_edit(status, embed=e)

        try:
            await step("1️⃣ GEMINI — refining", f"Task: {task[:350]}", C_WARM)
            refined, docs = await self.gemini_refine_and_research(task, uid)
            await step("2️⃣ GEMINI — planning", "⏳", C_ACCENT)

            sys_p = (
                "Senior architect. Output ONLY valid JSON, no <think> tags:\n"
                '{"project_name":"snake_case","description":"one-line",'
                '"files":[{"path":"main.py","purpose":"..."},'
                '{"path":"requirements.txt","purpose":"..."},'
                '{"path":"README.md","purpose":"..."}]}\n'
                "3-12 files, always include README.md. Relative paths only.")
            raw = await self.gemini_chat(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": f"Task: {refined[:1000]}"}],
                uid=uid, temperature=0.3, max_tokens=1500)
            plan = extract_json_object(raw)
            if not plan:
                try:
                    raw2 = await self.gemini_chat(
                        [{"role": "system",
                          "content": "Output ONLY the JSON."},
                         {"role": "user", "content": f"Task: {refined[:400]}"}],
                        uid=uid, temperature=0.1, max_tokens=1200)
                    plan = extract_json_object(raw2)
                except Exception:
                    pass
            if not plan:
                raise Exception("Planning failed — no valid JSON")

            proj = re.sub(r'[^a-z0-9_\-]', '_',
                          str(plan.get("project_name", "project")).lower()
                          )[:40] or "project"
            proj_desc = plan.get("description", task[:200])
            file_list = []
            for f in plan.get("files", [])[:12]:
                p = str(f.get("path", "")).strip().lstrip("/\\").replace("..", "_")
                if p and len(p) <= 200:
                    file_list.append({"path": p,
                                      "purpose": str(f.get("purpose", ""))[:200]})
            if not file_list:
                raise Exception("Plan had no valid files")

            manifest = "\n".join(f"• `{f['path']}` — {f['purpose']}"
                                 for f in file_list)
            await step(f"2️⃣ GEMINI — `{proj}` ({len(file_list)} files)",
                       manifest, C_OK)

            files: Dict[str, str] = {}
            for i, fi in enumerate(file_list, 1):
                await step(
                    f"3️⃣ OPENROUTER — {i}/{len(file_list)}: `{fi['path']}`",
                    fi["purpose"], C_DEEP)
                if fi["path"].lower().endswith(".md"):
                    sp = "Write a concise README.md. Output ONLY markdown."
                elif fi["path"].lower() == "requirements.txt":
                    sp = "Output ONLY requirements.txt, one package per line."
                else:
                    sp = ("Elite engineer. Output ONLY the full file content. "
                          "No fences. No <think> tags.")
                usr = (f"PROJECT: {proj_desc}\nTASK: {refined}\n\n"
                       f"FILE: `{fi['path']}`\nPURPOSE: {fi['purpose']}\n\n"
                       f"DOCS:\n{docs[:3000]}\n\n"
                       f"Output ONLY the content of `{fi['path']}`.")
                try:
                    c = await self.openrouter_call(
                        [{"role": "system", "content": sp},
                         {"role": "user", "content": usr}],
                        uid=uid, temperature=0.4, max_tokens=6000)
                    files[fi["path"]] = strip_code_fences(c) or c
                except Exception as e:
                    files[fi["path"]] = f"# ERROR: {e}\n"

            preview = "\n".join(f"• `{p}` ({len(c)} chars)"
                                for p, c in files.items())
            await step(f"3️⃣ OPENROUTER — {len(files)} files ready",
                       preview, C_OK)

            approved = False
            iteration = 0
            for iteration in range(1, max_iterations + 1):
                await step(f"4️⃣ GEMINI — review ({iteration}/{max_iterations})",
                           "⏳", C_WARM)
                manifest = "\n".join(f"- {p} ({len(c)} chars)"
                                     for p, c in files.items())
                snippets = [f"=== {p} ===\n{c[:6000 // max(1, len(files))]}"
                            for p, c in files.items()]
                body = "\n\n".join(snippets)
                sp = ("Strict senior reviewer. If correct+complete, reply "
                      "EXACTLY APPROVED + summary. Otherwise numbered issues "
                      "naming the file. No <think> tags.")
                usr = (f"TASK: {refined}\nPROJECT: {proj}\n\n"
                       f"FILES:\n{manifest}\n\nCONTENT:\n{body}")
                try:
                    review = await self.gemini_chat(
                        [{"role": "system", "content": sp},
                         {"role": "user", "content": usr}],
                        uid=uid, temperature=0.3, max_tokens=2000)
                except Exception as e:
                    review = f"(reviewer error: {e})"

                if review.strip().upper().startswith("APPROVED"):
                    await step(f"4️⃣ GEMINI — APPROVED ({iteration})",
                               review[:2000], C_OK)
                    approved = True
                    break
                await step(f"4️⃣ GEMINI — issues ({iteration})",
                           f"⚠️\n\n{review[:2800]}", C_ACCENT)
                await step(f"5️⃣ OPENROUTER — fixing ({iteration})",
                           "⏳", C_DEEP)
                fix_sp = ("Fix per feedback. Output ONLY the updated file "
                          "content. No <think> tags.")
                for path, content in list(files.items()):
                    if (path.lower() not in review.lower()
                            and "all files" not in review.lower()):
                        continue
                    usr = (f"PROJECT: {proj_desc}\nTASK: {refined}\n\n"
                           f"FILE: `{path}`\nCURRENT:\n```\n{content[:5000]}\n```\n\n"
                           f"FEEDBACK:\n{review[:3000]}\n\nOutput the full "
                           f"corrected content of `{path}`.")
                    try:
                        nc = await self.openrouter_call(
                            [{"role": "system", "content": fix_sp},
                             {"role": "user", "content": usr}],
                            uid=uid, temperature=0.3, max_tokens=6000)
                        files[path] = strip_code_fences(nc) or nc
                    except Exception as e:
                        logger.warning(f"Fix failed for {path}: {e}")

            await step("6️⃣ Packaging...", "⏳", C_PRIMARY)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
                for path, content in files.items():
                    zf.writestr(f"{proj}/{path}", content)
            buf.seek(0)

            summary = discord.Embed(
                title=f"✅ Complete — `{proj}`",
                description=(f"**Files:** {len(files)}\n"
                             f"**Review:** "
                             f"{'APPROVED' if approved else 'max iter'}\n"
                             f"**Iterations:** {iteration}"),
                color=C_OK if approved else C_WARM)
            await safe_edit(status, embed=summary)
            try:
                await safe_send(channel,
                                content=f"📦 **`{proj}.zip`** — "
                                        f"{len(files)} files",
                                file=discord.File(buf, filename=f"{proj}.zip"))
            except discord.HTTPException as e:
                await send_long(channel, f"❌ Zip attach failed: {e}")
        except Exception as e:
            logger.error(f"Project error: {e}", exc_info=True)
            await step("❌ Project crashed", f"`{str(e)[:350]}`", C_ERR)

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

        try:
            await send_long(ch, f"🏟️ **AI DEBATE – {desc}**")
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
                    ctx = "\n".join(f"AI{e['role']}: {e['content']}"
                                    for e in recent)
                    up = f"Prior:\n{ctx}\n\nAI{n} responds."
                sp = (f"You are AI{n} debating \"{desc}\" vs AI{o}. Dramatic, "
                      "<400 chars, aim for consensus. No <think> tags.")
                try:
                    resp = strip_think_tags(await self.groq_chat(
                        [{"role": "system", "content": sp},
                         {"role": "user", "content": up}],
                        uid=uid, temperature=0.9,
                        max_tokens=500)) or "[no response]"
                except Exception as e:
                    await send_long(ch, f"⚠️ AI{n} error: {str(e)[:150]}")
                    break
                hist.append({"role": n, "content": resp})
                await send_long(ch, f"{em} **AI{n}:** {resp}")
                turn += 1
                if turn < max_turns:
                    await asyncio.sleep(6)
            if uid in self.ai_chat_sessions:
                recent = hist[-8:]
                ctx = "\n".join(f"AI{e['role']}: {e['content']}"
                                for e in recent)
                try:
                    fr = strip_think_tags(await self.groq_chat(
                        [{"role": "system",
                          "content": "You are AI1. Give the final joint "
                                     "verdict. No <think> tags."},
                         {"role": "user", "content": ctx}],
                        uid=uid, temperature=0.9,
                        max_tokens=500)) or "[none]"
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
    # TOOL MARKER EXECUTION
    # ==================================================================
    async def _run_tool_marker(self, kind: str, arg: str,
                                channel, uid: int) -> bool:
        """
        Execute a tool marker the model emitted.
        kind is one of: generate_image, generate_video, generate_tts, search.
        Returns True if it ran, False if it was rejected (dedup, error, etc).
        """
        key = f"{uid}:{kind}"
        if key in self._active_generations:
            await safe_send(channel,
                            content=f"⏳ You already have a "
                                    f"`{kind.replace('_', ' ')}` running.")
            return False

        try:
            if kind == "generate_image":
                self._active_generations[key] = "image"
                await _do_generate_image(channel, uid, arg)
                return True

            if kind == "generate_video":
                self._active_generations[key] = "video"
                try:
                    await _do_generate_video(channel, uid, arg)
                finally:
                    self._active_generations.pop(key, None)
                return True

            if kind == "generate_tts":
                voice_key: Optional[str] = None
                text = arg
                if "|" in arg:
                    v, t = arg.split("|", 1)
                    voice_key = resolve_voice(v.strip(), uid, self)
                    text = t.strip()
                if not text:
                    text = arg
                self._active_generations[key] = "tts"
                try:
                    await _do_generate_tts(channel, uid, text,
                                            voice_key=voice_key)
                finally:
                    self._active_generations.pop(key, None)
                return True

            if kind == "search":
                self._active_generations[key] = "search"
                try:
                    await _do_search_and_summarize(channel, uid, arg, self)
                finally:
                    self._active_generations.pop(key, None)
                return True

        except Exception as e:
            logger.error(f"Tool marker {kind} failed: {e}", exc_info=True)
            await safe_send(channel, content=f"❌ Tool failed: {str(e)[:150]}")
        finally:
            self._active_generations.pop(key, None)

        return False

    # ==================================================================
    # CENTRAL MESSAGE HANDLER  (with tool marker interception)
    # ==================================================================
    async def process_user_message(self, user, clean_content, destination,
                                    thinking_msg=None, reply_context=None,
                                    trigger_msg=None, images=None,
                                    source_message=None):
        _t0 = time.perf_counter()
        images = images or []
        uid = user.id
        slot_name = self.active_slot.get(uid, "sv1")
        if uid not in self.user_slots:
            self.get_slot(uid, "sv1")

        show_placeholder = self.get_placeholder_pref(uid)
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

        # auto-context
        auto_ctx: List[Tuple[str, str]] = []
        if self.get_auto_context(uid) > 0:
            src = source_message or trigger_msg
            chan = getattr(src, "channel", None) or destination
            exclude_id = getattr(src, "id", None)
            try:
                auto_ctx = await self._fetch_auto_context(
                    chan, uid, exclude_message_id=exclude_id)
            except Exception as e:
                logger.warning(f"Auto-context failed: {e}")
                auto_ctx = []

        # macro expansion
        macro_match = re.match(r'^\.(\w+)\s*(.*)$', clean_content)
        if macro_match:
            mname = macro_match.group(1).lower()
            extra = macro_match.group(2)
            macros = self.get_macros(uid)
            if mname in macros:
                clean_content = macros[mname] + (f"\n{extra}" if extra else "")

        # explicit search (regex fast path)
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
                augmented = (
                    f"Web results for: {query}\n\n{results}\n\n---\n\n"
                    f"Summarize. Cite sources inline like [1], [2].")
                response = await self.chat_call(
                    augmented, uid=uid, max_tokens=800,
                    auto_context_messages=auto_ctx)
                response = strip_think_tags(response)
                if self.get_context_enabled(uid):
                    self.append_to_slot(uid, slot_name, "user", clean_content)
                    self.append_to_slot(uid, slot_name, "assistant", response)
                    if self.get_persistent_enabled(uid):
                        self.add_persistent_memory(uid, "user", clean_content)
                        self.add_persistent_memory(uid, "assistant", response)
                if early_thinking:
                    await safe_edit(early_thinking, content=response)
                else:
                    await send_long(destination, response)
                return

        # regex fast-path generation (image / video / tts)
        gen_intent = _parse_gen_intent(clean_content)
        if gen_intent:
            kind, g_arg = gen_intent
            if placeholder_task:
                try:
                    early_thinking = await placeholder_task
                    if early_thinking:
                        await early_thinking.delete()
                except Exception:
                    pass
            if self.get_context_enabled(uid):
                self.append_to_slot(uid, slot_name, "user", clean_content)
                self.append_to_slot(uid, slot_name, "assistant",
                                    f"[{kind}]")
            await self._run_tool_marker(f"generate_{kind}", g_arg,
                                         destination, uid)
            return

        # record user turn for normal chat
        if self.get_context_enabled(uid):
            if self.get_persistent_enabled(uid):
                self.add_persistent_memory(uid, "user", clean_content)
            self.append_to_slot(uid, slot_name, "user", clean_content)

        if placeholder_task:
            early_thinking = await placeholder_task

        system_prompt = None
        court = self.court_sessions.get(uid)
        if court and court.get("case"):
            tpl = self.court_roles.get(court["role"], "")
            if tpl:
                p = court.get("participants", {})
                pl = [f"- {r.capitalize()}: <@{u}>" for r, u in p.items()]
                system_prompt = tpl.format(
                    case=court["case"],
                    participants="\n".join(pl) if pl else "None.")
        elif reply_context:
            oa = reply_context.get("author", "someone")
            oc = reply_context.get("content", "")
            base = self.mode_prompts.get(self.get_user_mode(uid),
                                          self.mode_prompts["normal"])
            system_prompt = (
                f"{base}\n\nReplying to **{oa}**: \"{oc}\"\n"
                f"User says: \"{clean_content}\"\n"
                f"React naturally. 1–3 sentences.")
        if images:
            note = f"[{len(images)} image(s) attached — look at them.]"
            system_prompt = (system_prompt + "\n" + note) if system_prompt else note

        try:
            response = await self.chat_call(
                clean_content, uid=uid, system_prompt=system_prompt,
                slot_name=slot_name, images=images,
                auto_context_messages=auto_ctx)
            response = strip_think_tags(response)

            # ---------- TOOL MARKER INTERCEPTION ----------
            marker = _extract_tool_marker(response)
            if marker:
                kind, arg = marker
                prose = _strip_tool_markers(response).strip()

                if prose:
                    if early_thinking:
                        await safe_edit(early_thinking, content=prose)
                    else:
                        await send_long(destination, prose)
                elif early_thinking:
                    try:
                        await early_thinking.delete()
                    except discord.HTTPException:
                        pass

                # Record assistant turn
                stored = prose or f"[{kind}]"
                if self.get_context_enabled(uid):
                    if self.get_persistent_enabled(uid):
                        self.add_persistent_memory(uid, "assistant", stored)
                    self.append_to_slot(uid, slot_name, "assistant", stored)

                await self._run_tool_marker(kind, arg, destination, uid)
                logger.info(f"Tool marker fired: {kind} | "
                            f"{time.perf_counter() - _t0:.3f}s")
                return

            # ---------- NORMAL REPLY ----------
            if self.get_context_enabled(uid):
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
                await send_long(destination, response)

            mode = self.get_user_mode(uid)
            if mode in ("childish", "brainrot"):
                try:
                    pool = self.get_gif_pool(uid)
                    await destination.send(random.choice(pool))
                except Exception:
                    pass

            logger.info(f"TOTAL handler time: "
                        f"{time.perf_counter() - _t0:.3f}s")
        except Exception as e:
            logger.error(f"process_user_message error: {e}", exc_info=True)
            if early_thinking:
                await safe_edit(early_thinking, content=f"❌ {str(e)[:150]}")
            else:
                await send_long(destination, f"❌ {str(e)[:150]}")

    # ==================================================================
    # VIDEO / MUSIC GENERATION
    # ==================================================================
    async def generate_video(self, prompt, uid, status_message):
        if not SILICONFLOW_API_KEYS:
            return await safe_edit(status_message,
                                    content="❌ No SiliconFlow key")
        self.video_jobs[uid] = status_message
        try:
            submit_url = "https://api.siliconflow.com/v1/video/submit"
            status_url = "https://api.siliconflow.com/v1/video/status"
            api_key = SILICONFLOW_API_KEYS[self.siliconflow_key_index]
            self.siliconflow_key_index = (
                self.siliconflow_key_index + 1) % len(SILICONFLOW_API_KEYS)
            headers = {"Authorization": f"Bearer {api_key}",
                       "Content-Type": "application/json"}
            payload = {"model": "Wan-AI/Wan2.2-T2V-A14B",
                       "prompt": prompt, "image_size": "1280x720"}
            async with shared_session() as s:
                rid = None
                for _ in range(len(SILICONFLOW_API_KEYS) + 1):
                    try:
                        async with s.post(
                            submit_url, headers=headers, json=payload,
                            timeout=aiohttp.ClientTimeout(total=30)) as r:
                            if r.status == 200:
                                d = await r.json()
                                rid = d.get("requestId")
                                if rid:
                                    break
                            elif r.status == 429:
                                api_key = SILICONFLOW_API_KEYS[
                                    self.siliconflow_key_index]
                                self.siliconflow_key_index = (
                                    self.siliconflow_key_index + 1
                                ) % len(SILICONFLOW_API_KEYS)
                                headers["Authorization"] = f"Bearer {api_key}"
                                await asyncio.sleep(2)
                    except Exception:
                        pass
                if not rid:
                    raise Exception("No requestId")
                await safe_edit(status_message, content=f"🎬 queued `{rid}`")
                for attempt in range(120):
                    await asyncio.sleep(10)
                    async with s.post(
                        status_url,
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
                                u = (vids[0].get("url")
                                     or vids[0].get("video_url"))
                                if u:
                                    async with s.get(
                                        u, timeout=aiohttp.ClientTimeout(total=120)
                                    ) as vr:
                                        data = await vr.read()
                                    await safe_edit(
                                        status_message,
                                        content="✅ **Video Ready!**")
                                    await safe_send(
                                        status_message.channel,
                                        file=discord.File(
                                            io.BytesIO(data),
                                            filename="video.mp4"))
                                    return
                            raise Exception("No video URL")
                        elif st == "Failed":
                            raise Exception(pd.get("reason", "Unknown"))
                        else:
                            await safe_edit(
                                status_message,
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
                        if any(x in ct for x in ('audio', 'mpeg', 'ogg',
                                                  'octet-stream')):
                            data = await r.read()
                            if len(data) < 1000:
                                raise Exception("Invalid audio")
                            await safe_edit(status_message,
                                            content="🎵 Ready")
                            await safe_send(
                                status_message.channel,
                                file=discord.File(io.BytesIO(data),
                                                  filename="music.mp3"))
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
            await asyncio.sleep(120)

    async def load_pen_archive_async(self):
        url = ("https://raw.githubusercontent.com/Pen-123/"
               "archive-/refs/heads/main/archives.txt")
        try:
            async with shared_session() as s:
                async with s.get(url,
                                 timeout=aiohttp.ClientTimeout(total=8)) as r:
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
# END OF PART 2
# ======================================================================
# Part 3 will contain: autocomplete callbacks, /mac, all chat commands,
# /ping, /pa /pd, resets, modes, /compile, /cs group, /profiles,
# /benchmark, /context, slots.
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


async def _voice_ac(i, c):
    uid = i.user.id if i.user else None
    voices = bot.all_voices(uid) if uid else dict(BUILTIN_VOICES)
    out: List[app_commands.Choice[str]] = []

    # Descriptor aliases first
    for alias, target in VOICE_ALIASES.items():
        if alias == target:
            continue
        v = BUILTIN_VOICES.get(target)
        if not v:
            continue
        label = f"{v['emoji']} {alias} → {target}"
        if c.lower() in label.lower():
            out.append(app_commands.Choice(name=label[:100], value=target))
        if len(out) >= 25:
            return out

    for k, v in voices.items():
        label = f"{v['emoji']} {v['desc']}"
        if c.lower() in k.lower() or c.lower() in label.lower():
            out.append(app_commands.Choice(name=label[:100], value=k))
        if len(out) >= 25:
            break
    return out


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
    uid = ctx.author.id
    mode = bot.get_user_mode(uid)
    auto_ctx = bot.get_auto_context(uid)
    ctx_on = bot.get_context_enabled(uid)
    ph = "ON" if bot.get_placeholder_pref(uid) else "OFF"

    emb = discord.Embed(
        title="🔥 Mac v26.0",
        color=C_PRIMARY,
        description=(
            f"**Mode:** `{mode}`  ·  **Context:** "
            f"`{'ON' if ctx_on else 'OFF'}`  ·  "
            f"**Auto-context:** `{auto_ctx if auto_ctx else 'OFF'}`  ·  "
            f"**Placeholder:** `{ph}`\n"
            "-# Mention me, reply to me, or use slash commands."
        ),
    )

    emb.add_field(
        name="💬 Chat",
        value="`@Mac <msg>` · `/query` · `/summarize` · `/eli5` · "
              "`/roast` · `/compliment`",
        inline=False)
    emb.add_field(
        name="👁️ Vision",
        value="Attach or reply to an image/GIF — I read it automatically, "
              "no keywords needed.",
        inline=False)
    emb.add_field(
        name="✏️ Image edit",
        value="Attach/reply to an image + `@Mac make him goth`",
        inline=False)
    emb.add_field(
        name="🎨 Generation (I decide when to use these)",
        value="Ask naturally — **\"draw me a cat\"**, **\"say hi in a scary "
              "voice\"**, **\"make a video of a dog\"** — I'll trigger it.",
        inline=False)
    emb.add_field(
        name="🌐 Search",
        value="`search <thing>` (or google / look up / find)",
        inline=False)
    emb.add_field(
        name="✨ Personalize",
        value="`/personalize` · `/cs profile` · `/cs show`",
        inline=False)
    emb.add_field(
        name="🎭 Profiles",
        value="`/profiles save|load|list|delete <name>`",
        inline=False)
    emb.add_field(
        name="🎭 Modes (per-user)",
        value="`/normal` (default) · `/chill` · `/unhinged` · `/coder` · "
              "`/engineer` · `/childish` · `/dexter`",
        inline=False)
    emb.add_field(
        name="🧠 Context",
        value="`/cs context on|off` — toggle slot + memory\n"
              "`/cs autocontext <0–10>` — auto-read N recent msgs",
        inline=False)
    emb.add_field(
        name="📋 Compile",
        value="`/compile [count]` — dump recent messages into one file",
        inline=False)
    emb.add_field(
        name="🔔 Ping",
        value="`/ping` (panel) · `/pa` (on) · `/pd` (off)",
        inline=False)
    emb.add_field(
        name="⚙️ /cs",
        value="`/cs key` · `/cs model` · `/cs llm` · `/cs ch` · "
              "`/cs voice` / `voice-add` / `voice-del` / `voices` · "
              "`/cs macro` · `/cs gif` · `/cs ping` · `/cs placeholder` · "
              "`/cs context` · `/cs autocontext` · `/cs show` · `/cs reset`",
        inline=False)
    emb.add_field(
        name="🗂️ Slots",
        value="`/sv1`–`/sv5` · `/svc <name>` · `/vsc [private]` · "
              "`/svlist` · `/svclear`",
        inline=False)
    emb.add_field(
        name="🧠 Memory",
        value="`/sm` · `/persistent` · `/persistentdisable` · "
              "`/vsm [private]`",
        inline=False)
    emb.add_field(
        name="📊 Diagnostics",
        value="`/benchmark <prompt>` · `/context` · `/config`",
        inline=False)
    emb.add_field(
        name="🏗️ Pipelines",
        value="`/pipeline` · `/project`",
        inline=False)
    emb.add_field(
        name="🎵 Music",
        value="`/music` (VC panel) · `/play <song or Spotify/YT URL>`",
        inline=False)
    emb.add_field(
        name="🖼️ Media",
        value="`/render` · `/tts` · `/video` · `/rendermode` · `/hf_model`",
        inline=False)
    emb.add_field(
        name="💬 Debate · 🏛️ Court · 🌍 UMF",
        value="`/debate` · `/court` · `/umf` `/umf_join` `/umf_manage`",
        inline=False)
    emb.add_field(
        name="♻️ Resets",
        value="`/src` soft reset · `/re` hard reset",
        inline=False)

    emb.set_footer(text="v26.0 — auto media read · tool markers · "
                        "no HF text · fixed music search")
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
        images = (await fetch_images_from_message(ctx.message)
                  if ctx.message else [])
        await bot.process_user_message(
            ctx.author, message, ctx.channel,
            trigger_msg=ctx.message, images=images,
            source_message=ctx.message)
    except Exception as e:
        await ctx.send(f"❌ `{e}`", ephemeral=True)


@bot.hybrid_command(name="summarize",
                    description="📝 Summarize text or a replied message")
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
    await send_long(ctx, strip_think_tags(result))


@bot.hybrid_command(name="eli5", description="🧒 Explain like I'm 5")
@app_commands.describe(topic="What to explain")
async def eli5_cmd(ctx, topic: str):
    await ctx.defer()
    result = await bot.chat_call(
        f"Explain {topic} like I'm 5 years old. Simple language, fun "
        f"analogies, under 150 words.",
        uid=ctx.author.id, max_tokens=500)
    await send_long(ctx, f"🧒 **{topic}**\n{strip_think_tags(result)}")


@bot.hybrid_command(name="roast", description="🔥 AI roasts a user")
@app_commands.describe(user="Who to roast (defaults to you)")
async def roast_cmd(ctx, user: discord.Member = None):
    target = user or ctx.author
    await ctx.defer()
    result = await bot.chat_call(
        f"Roast {target.display_name} — funny, savage, playful, "
        f"1–3 sentences. No slurs. Punch at behavior, not identity.",
        uid=ctx.author.id, max_tokens=300)
    await ctx.send(f"🔥 {strip_think_tags(result)}")


@bot.hybrid_command(name="compliment", description="💖 AI compliments a user")
@app_commands.describe(user="Who to compliment (defaults to you)")
async def compliment_cmd(ctx, user: discord.Member = None):
    target = user or ctx.author
    await ctx.defer()
    result = await bot.chat_call(
        f"Give a genuine, warm, wholesome compliment to "
        f"{target.display_name}, 1–2 sentences.",
        uid=ctx.author.id, max_tokens=250)
    await ctx.send(f"💖 {strip_think_tags(result)}")


# ======================================================================
# PERSONALIZE
# ======================================================================
@bot.hybrid_command(
    name="personalize",
    description="✨ Customize how Mac talks to YOU")
@app_commands.describe(
    name="What Mac should call you",
    pronouns="Your pronouns (e.g. they/them)",
    vibe="Vibe Mac matches",
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
        emb = discord.Embed(
            title=f"✨ Your Personalization — {ctx.author.display_name}",
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
# /ping — button panel
# ======================================================================
class PingPanelView(discord.ui.View):
    def __init__(self, uid: int):
        super().__init__(timeout=180)
        self.uid = uid

    def _refresh_embed(self) -> discord.Embed:
        emb = discord.Embed(title="🏓 Mac Status Panel", color=C_PRIMARY)
        emb.add_field(name="Uptime",
                      value=format_uptime(get_uptime_seconds()), inline=True)
        emb.add_field(name="Commands served",
                      value=f"{get_command_count():,}", inline=True)
        emb.add_field(name="WS latency",
                      value=f"{round(bot.latency * 1000)}ms", inline=True)
        emb.add_field(name="Guilds", value=f"{len(bot.guilds)}", inline=True)
        emb.add_field(name="Your ping mode",
                      value=f"`{bot.get_ping_pref(self.uid)}`", inline=True)
        emb.add_field(name="Placeholder",
                      value="ON" if bot.get_placeholder_pref(self.uid) else "OFF",
                      inline=True)
        emb.add_field(name="Mode",
                      value=f"`{bot.get_user_mode(self.uid)}`", inline=True)
        auto_ctx = bot.get_auto_context(self.uid)
        emb.add_field(name="Auto-context",
                      value=f"{auto_ctx} msgs" if auto_ctx else "OFF",
                      inline=True)
        emb.add_field(name="Context",
                      value="ON" if bot.get_context_enabled(self.uid) else "OFF",
                      inline=True)
        emb.set_footer(text="Click a button to change ping mode")
        return emb

    async def _set(self, interaction: discord.Interaction, value: str):
        bot.set_ping_pref(self.uid, value)
        await interaction.response.edit_message(embed=self._refresh_embed(),
                                                 view=self)

    @discord.ui.button(label="On", emoji="🔔",
                       style=discord.ButtonStyle.success)
    async def on_btn(self, i, b): await self._set(i, "on")

    @discord.ui.button(label="Off", emoji="🔕",
                       style=discord.ButtonStyle.danger)
    async def off_btn(self, i, b): await self._set(i, "off")

    @discord.ui.button(label="DM only", emoji="💌",
                       style=discord.ButtonStyle.secondary)
    async def dm_btn(self, i, b): await self._set(i, "dm_only")

    @discord.ui.button(label="Refresh", emoji="🔄",
                       style=discord.ButtonStyle.primary)
    async def refresh_btn(self, i, b):
        await i.response.edit_message(embed=self._refresh_embed(), view=self)


@bot.hybrid_command(name="ping",
                    description="🏓 Status panel — uptime, latency, ping mode")
async def ping_cmd(ctx):
    view = PingPanelView(ctx.author.id)
    await ctx.send(embed=view._refresh_embed(), view=view, ephemeral=True)


@bot.hybrid_command(name="pa", description="🔔 Set ping mode: ON")
async def pa_cmd(ctx):
    bot.set_ping_pref(ctx.author.id, "on")
    await ctx.send("🔔 Ping mode → **on**", ephemeral=True)


@bot.hybrid_command(name="pd", description="🔕 Set ping mode: OFF")
async def pd_cmd(ctx):
    bot.set_ping_pref(ctx.author.id, "off")
    await ctx.send("🔕 Ping mode → **off**", ephemeral=True)


# ======================================================================
# RESETS
# ======================================================================
@bot.hybrid_command(
    name="src",
    description="♻️ Soft reset — wipes your slots + memory "
                "(keeps /cs, profiles)")
async def src_cmd(ctx):
    uid = ctx.author.id
    bot.user_slots.pop(uid, None); bot.active_slot.pop(uid, None)
    bot._dirty_slots = True
    bot.persistent_memory.pop(uid, None)
    bot.persistent_enabled.pop(uid, None)
    bot._dirty_memory = True
    bot.ping_prefs.pop(uid, None); bot._dirty_pings = True
    bot.placeholder_prefs.pop(uid, None); bot._dirty_placeholders = True
    bot.user_cooldowns.pop(uid, None)
    await ctx.send("♻️ **Reset.** Slots + memory wiped — /cs and profiles kept.",
                   ephemeral=True)


@bot.hybrid_command(
    name="re",
    description="💥 Hard reset — wipes ALL your user-side data")
async def re_cmd(ctx):
    uid = ctx.author.id
    bot.user_slots.pop(uid, None); bot.active_slot.pop(uid, None)
    bot._dirty_slots = True
    bot.persistent_memory.pop(uid, None)
    bot.persistent_enabled.pop(uid, None)
    bot._dirty_memory = True
    bot.cs.pop(uid, None); bot._dirty_cs = True
    bot.cs_key_idx = {k: v for k, v in bot.cs_key_idx.items() if k[0] != uid}
    bot.cs_model_idx = {k: v for k, v in bot.cs_model_idx.items() if k[0] != uid}
    bot.profiles.pop(uid, None); bot._dirty_profiles = True
    bot.ping_prefs.pop(uid, None); bot._dirty_pings = True
    bot.placeholder_prefs.pop(uid, None); bot._dirty_placeholders = True
    bot.user_cooldowns.pop(uid, None)
    await ctx.send("💥 **Reset.** All your user-side data wiped.",
                   ephemeral=True)


# ======================================================================
# MODES
# ======================================================================
def _mode_switch_response(mode: str) -> str:
    emoji = {"normal": "🧠", "chill": "😎", "unhinged": "🔥",
             "coder": "💻", "engineer": "🛠️", "childish": "🧒",
             "dexter": "🔪"}.get(mode, "🎭")
    extra = " — GIFs on every reply." if mode in ("brainrot", "childish") else ""
    return f"{emoji} Your mode → **{mode}**{extra}"


@bot.hybrid_command(name="normal",
                    description="🧠 Set YOUR mode to normal (default)")
async def mode_normal(ctx):
    bot.set_user_mode(ctx.author.id, "normal")
    await ctx.send(_mode_switch_response("normal"), ephemeral=True)


@bot.hybrid_command(name="chill",
                    description="😎 Set YOUR mode to chill (agreeable)")
async def mode_chill(ctx):
    bot.set_user_mode(ctx.author.id, "chill")
    await ctx.send(_mode_switch_response("chill"), ephemeral=True)


@bot.hybrid_command(name="unhinged", description="🔥 Set YOUR mode to unhinged")
async def mode_unhinged(ctx):
    bot.set_user_mode(ctx.author.id, "unhinged")
    await ctx.send(_mode_switch_response("unhinged"), ephemeral=True)


@bot.hybrid_command(name="coder", description="💻 Set YOUR mode to coder")
async def mode_coder(ctx):
    bot.set_user_mode(ctx.author.id, "coder")
    await ctx.send(_mode_switch_response("coder"), ephemeral=True)


@bot.hybrid_command(name="engineer", description="🛠️ Set YOUR mode to engineer")
async def mode_engineer(ctx):
    bot.set_user_mode(ctx.author.id, "engineer")
    await ctx.send(_mode_switch_response("engineer"), ephemeral=True)


@bot.hybrid_command(name="childish", description="🧒 Set YOUR mode to childish")
async def mode_childish(ctx):
    bot.set_user_mode(ctx.author.id, "childish")
    await ctx.send(_mode_switch_response("childish"), ephemeral=True)


@bot.hybrid_command(name="dexter",
                    description="🔪 Set YOUR mode to dexter (mentalist)")
async def mode_dexter(ctx):
    bot.set_user_mode(ctx.author.id, "dexter")
    await ctx.send(_mode_switch_response("dexter"), ephemeral=True)


# ======================================================================
# /compile
# ======================================================================
class CompileSelectModal(discord.ui.Modal, title="📋 Which messages?"):
    selection = discord.ui.TextInput(
        label="Message numbers",
        placeholder="e.g. 1,3,5-10,15  (or 'all')",
        required=True, max_length=400)

    def __init__(self, messages: List[discord.Message], original_uid: int):
        super().__init__()
        self.messages = messages
        self.original_uid = original_uid

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.original_uid:
            return await interaction.response.send_message(
                "❌ Not your compile.", ephemeral=True)
        raw = self.selection.value.strip().lower()
        n = len(self.messages)
        chosen: List[int] = []
        if raw in ("all", "*", "everything"):
            chosen = list(range(1, n + 1))
        else:
            for part in re.split(r'[,\s]+', raw):
                if not part:
                    continue
                m = re.match(r'^(\d+)\s*-\s*(\d+)$', part)
                if m:
                    a, b = int(m.group(1)), int(m.group(2))
                    if a > b:
                        a, b = b, a
                    chosen.extend(range(a, b + 1))
                elif part.isdigit():
                    chosen.append(int(part))
        chosen = sorted({i for i in chosen if 1 <= i <= n})
        if not chosen:
            return await interaction.response.send_message(
                "❌ No valid message numbers matched.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        lines = []
        for i in chosen:
            msg = self.messages[i - 1]
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author = f"{msg.author.display_name} ({msg.author.id})"
            body = (msg.content or "").strip()
            attachments = ""
            if msg.attachments:
                attachments = ("\n  [attachments: "
                               + ", ".join(a.filename for a in msg.attachments)
                               + "]")
            lines.append(f"[{i}] {ts} — {author}\n{body}{attachments}\n")

        compiled = "\n".join(lines)
        header = (f"# Compilation from "
                  f"#{getattr(interaction.channel, 'name', 'channel')}\n"
                  f"# {len(chosen)} messages · "
                  f"generated {datetime.now().isoformat()}\n\n")
        compiled_full = header + compiled

        buf = io.BytesIO(compiled_full.encode("utf-8"))
        fname = f"compile-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        try:
            await interaction.followup.send(
                content=f"📦 **{len(chosen)} messages** compiled · "
                        f"{len(compiled_full):,} chars",
                file=discord.File(buf, filename=fname),
                ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Upload failed: {e}",
                                            ephemeral=True)
            return

        if len(compiled_full) <= 18000:
            for chunk in chunk_text(compiled_full, 1990)[:10]:
                await safe_send(interaction.channel, content=chunk)


class CompileStartView(discord.ui.View):
    def __init__(self, uid: int, messages: List[discord.Message]):
        super().__init__(timeout=600)
        self.uid = uid
        self.messages = messages

    @discord.ui.button(label="Select Messages", emoji="✅",
                       style=discord.ButtonStyle.success)
    async def select_btn(self, i, b):
        if i.user.id != self.uid:
            return await i.response.send_message("❌ Not yours.",
                                                  ephemeral=True)
        await i.response.send_modal(CompileSelectModal(self.messages, self.uid))

    @discord.ui.button(label="Compile All", emoji="📦",
                       style=discord.ButtonStyle.primary)
    async def all_btn(self, i, b):
        if i.user.id != self.uid:
            return await i.response.send_message("❌ Not yours.",
                                                  ephemeral=True)
        await i.response.defer(ephemeral=True)

        lines = []
        for idx, msg in enumerate(self.messages, 1):
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author = f"{msg.author.display_name} ({msg.author.id})"
            body = (msg.content or "").strip()
            lines.append(f"[{idx}] {ts} — {author}\n{body}\n")
        compiled = "\n".join(lines)
        header = (f"# Compilation from "
                  f"#{getattr(i.channel, 'name', 'channel')}\n"
                  f"# {len(self.messages)} messages · "
                  f"generated {datetime.now().isoformat()}\n\n")
        full = header + compiled
        buf = io.BytesIO(full.encode("utf-8"))
        fname = f"compile-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        await i.followup.send(
            content=f"📦 **{len(self.messages)} messages** · "
                    f"{len(full):,} chars",
            file=discord.File(buf, filename=fname), ephemeral=True)
        if len(full) <= 18000:
            for chunk in chunk_text(full, 1990)[:10]:
                await safe_send(i.channel, content=chunk)


@bot.hybrid_command(
    name="compile",
    description="📋 Compile recent channel messages into one file")
@app_commands.describe(
    count="How many recent messages to fetch (default 50, max 200)",
    channel="Optional: compile from a different channel")
async def compile_cmd(ctx, count: int = 50,
                       channel: discord.TextChannel = None):
    count = max(1, min(200, count))
    target = channel or ctx.channel
    await ctx.defer(ephemeral=True)

    try:
        msgs: List[discord.Message] = []
        async for m in target.history(limit=count):
            msgs.append(m)
        msgs.reverse()
    except Exception as e:
        return await ctx.send(f"❌ Couldn't read history: {e}",
                              ephemeral=True)

    if not msgs:
        return await ctx.send("📭 No messages found.", ephemeral=True)

    preview_lines = []
    for i, m in enumerate(msgs[:25], 1):
        body = (m.content or "[no text]").replace("\n", " ")[:90]
        preview_lines.append(f"`{i}` **{m.author.display_name}**: {body}")
    preview = "\n".join(preview_lines)
    more = f"\n-# …and {len(msgs) - 25} more" if len(msgs) > 25 else ""

    emb = discord.Embed(
        title=f"📋 Compile — {len(msgs)} messages from #{target.name}",
        description=preview + more,
        color=C_PRIMARY)
    emb.set_footer(
        text="Click 'Select Messages' to pick which ones, or 'Compile All'")

    await ctx.send(embed=emb,
                   view=CompileStartView(ctx.author.id, msgs),
                   ephemeral=True)


# ======================================================================
# /cs GROUP
# ======================================================================
@bot.hybrid_group(
    name="cs",
    description="⚙️ Customization — profile, keys, models, voices, macros",
    invoke_without_command=True)
async def cs_group(ctx):
    emb = discord.Embed(title="⚙️ /cs — Customization",
                        description="Everything here is per-user.",
                        color=C_PRIMARY)
    emb.add_field(name="Profile",
                  value="`/cs profile` — name, pronouns, vibe, etc.",
                  inline=False)
    emb.add_field(name="API Keys",
                  value="`/cs key add|remove|list <provider> [key]`",
                  inline=False)
    emb.add_field(name="Models",
                  value="`/cs model add|remove|list <provider> [model]`",
                  inline=False)
    emb.add_field(name="Aliases + Active",
                  value="`/cs llm` · `/cs ch`", inline=False)
    emb.add_field(name="Voices",
                  value="`/cs voice` · `/cs voice-add` · `/cs voice-del` · "
                        "`/cs voices`", inline=False)
    emb.add_field(name="Macros · GIFs",
                  value="`/cs macro` · `/cs gif`", inline=False)
    emb.add_field(name="Ping · Placeholder",
                  value="`/cs ping` · `/cs placeholder`", inline=False)
    emb.add_field(name="Context",
                  value="`/cs context on|off` · `/cs autocontext <0–10>`",
                  inline=False)
    emb.add_field(name="Inspector",
                  value="`/cs inspector <message_id or link>`", inline=False)
    emb.add_field(name="Misc",
                  value="`/cs show` · `/cs reset [section]`", inline=False)
    await ctx.send(embed=emb)


@cs_group.command(name="profile", description="Set your personal profile")
@app_commands.describe(name="What Mac calls you", pronouns="Your pronouns",
                       vibe="Vibe to match", instructions="Extra instructions",
                       catchphrase="End every reply with this",
                       language="Preferred language",
                       clear="Clear your profile")
async def cs_profile(ctx, name: str = None, pronouns: str = None,
                     vibe: str = None, instructions: str = None,
                     catchphrase: str = None, language: str = None,
                     clear: bool = False):
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
        emb = discord.Embed(
            title=f"Your Profile — {ctx.author.display_name}",
            color=C_PRIMARY)
        for k, v in p.items():
            emb.add_field(name=k.title(), value=str(v)[:1024], inline=False)
        return await ctx.send(embed=emb, ephemeral=True)
    bot.set_profile(uid, name=name, pronouns=pronouns, vibe=vibe,
                    instructions=instructions, catchphrase=catchphrase,
                    language=language)
    await ctx.send("✅ Profile updated.", ephemeral=True)


@cs_group.command(name="key",
                  description="Manage your API keys (up to 3 per provider)")
@app_commands.autocomplete(provider=_provider_ac)
@app_commands.describe(
    provider="groq | openrouter | hf | gemini | gemini_image | fish | imgbb",
    action="add | remove | list",
    value="API key (add) or index (remove)")
async def cs_key(ctx, provider: str, action: str = "list",
                 value: str = None):
    uid = ctx.author.id
    p = provider.lower()
    if p not in PROVIDERS:
        return await ctx.send(f"❌ Providers: {', '.join(PROVIDERS)}",
                              ephemeral=True)
    u = bot._cs(uid)
    keys = u.setdefault(f"{p}_keys", [])
    a = action.lower()
    if a == "list":
        if not keys:
            return await ctx.send(
                f"No custom `{p}` keys — using bot defaults.",
                ephemeral=True)
        masked = [f"`{i}` ...{k[-6:]}" for i, k in enumerate(keys)]
        return await ctx.send(
            f"**Your `{p}` keys ({len(keys)}/3):**\n" + "\n".join(masked),
            ephemeral=True)
    if a == "add":
        if not value:
            return await ctx.send("❌ Provide a key.", ephemeral=True)
        if len(keys) >= MAX_KEYS_PER_PROVIDER:
            return await ctx.send(f"❌ Max {MAX_KEYS_PER_PROVIDER}.",
                                  ephemeral=True)
        keys.append(value.strip()); bot._save_cs()
        return await ctx.send(f"✅ Added `{p}` key ({len(keys)}).",
                              ephemeral=True)
    if a == "remove":
        if value is None:
            return await ctx.send("❌ Provide index.", ephemeral=True)
        try:
            keys.pop(int(value)); bot._save_cs()
            return await ctx.send("🗑️ Removed.", ephemeral=True)
        except (ValueError, IndexError):
            return await ctx.send("❌ Invalid index.", ephemeral=True)
    await ctx.send("❌ add | remove | list", ephemeral=True)


@cs_group.command(name="model", description="Manage your preferred models")
@app_commands.autocomplete(provider=_model_provider_ac)
@app_commands.describe(
    provider="groq | openrouter | hf_image | gemini | fish",
    action="add | remove | list",
    value="Model id (add) or index (remove)")
async def cs_model(ctx, provider: str, action: str = "list",
                   value: str = None):
    uid = ctx.author.id
    p = provider.lower()
    if p not in MODEL_PROVIDERS:
        return await ctx.send(
            f"❌ Providers: {', '.join(MODEL_PROVIDERS)}", ephemeral=True)
    u = bot._cs(uid)
    models = u.setdefault(f"{p}_models", [])
    a = action.lower()
    if a == "list":
        if not models:
            defaults = bot.user_models(None, p)
            return await ctx.send(
                f"No custom `{p}` models. Bot defaults:\n"
                + "\n".join(f"• `{m}`" for m in defaults),
                ephemeral=True)
        return await ctx.send(
            f"**Your `{p}` models ({len(models)}/3):**\n"
            + "\n".join(f"`{i}` {m}" for i, m in enumerate(models)),
            ephemeral=True)
    if a == "add":
        if not value:
            return await ctx.send("❌ Provide model id.", ephemeral=True)
        if len(models) >= MAX_MODELS_PER_PROVIDER:
            return await ctx.send(f"❌ Max {MAX_MODELS_PER_PROVIDER}.",
                                  ephemeral=True)
        models.append(value.strip()); bot._save_cs()
        return await ctx.send(f"✅ Added ({len(models)}).", ephemeral=True)
    if a == "remove":
        if value is None:
            return await ctx.send("❌ Provide index.", ephemeral=True)
        try:
            models.pop(int(value)); bot._save_cs()
            return await ctx.send("🗑️ Removed.", ephemeral=True)
        except (ValueError, IndexError):
            return await ctx.send("❌ Invalid index.", ephemeral=True)
    await ctx.send("❌ add | remove | list", ephemeral=True)


@cs_group.command(name="llm", description="🤖 Named model aliases + switch")
@app_commands.autocomplete(alias=_alias_ac)
@app_commands.describe(action="add | remove | list | use",
                       alias="Alias name", model_id="Model id (add)",
                       provider="Provider (add)")
async def cs_llm(ctx, action: str = "list", alias: str = None,
                 model_id: str = None, provider: str = None):
    uid = ctx.author.id
    a = action.lower()
    u = bot._cs(uid)
    aliases = u.setdefault("model_aliases", {})
    if a == "list":
        if not aliases:
            return await ctx.send(
                "No aliases. `/cs llm add alias:fast "
                "model_id:openai/gpt-oss-20b provider:groq`",
                ephemeral=True)
        active = u.get("active_alias")
        lines = []
        for name, info in aliases.items():
            mark = " ✅" if name == active else ""
            lines.append(f"• `{name}` → `{info['model']}` "
                         f"({info['provider']}){mark}")
        return await send_long(ctx, "🤖 **Aliases**\n" + "\n".join(lines))
    if a == "add":
        if not alias or not model_id:
            return await ctx.send("❌ alias + model_id required.",
                                  ephemeral=True)
        prov = (provider or "groq").lower()
        if prov not in ("groq", "gemini", "openrouter"):
            return await ctx.send("❌ Provider: groq/gemini/openrouter",
                                  ephemeral=True)
        aliases[alias.lower()] = {"model": model_id.strip(), "provider": prov}
        bot._save_cs()
        return await ctx.send(f"✅ `{alias.lower()}` → `{model_id}`",
                              ephemeral=True)
    if a == "remove":
        if not alias or alias.lower() not in aliases:
            return await ctx.send("❌ Not found.", ephemeral=True)
        aliases.pop(alias.lower())
        if u.get("active_alias") == alias.lower():
            u.pop("active_alias", None)
        bot._save_cs()
        return await ctx.send("🗑️ Removed.", ephemeral=True)
    if a == "use":
        info = aliases.get((alias or "").lower())
        if not info:
            return await ctx.send("❌ Not found.", ephemeral=True)
        prov, model = info["provider"], info["model"]
        field = f"{prov}_models"
        existing = u.get(field, [])
        if model in existing:
            existing.remove(model)
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
        emb.add_field(
            name="Groq",
            value="\n".join(f"`groq:{m}`"
                            for m in bot.user_models(uid, "groq")) or "—",
            inline=False)
        emb.add_field(
            name="Gemini",
            value="\n".join(f"`gemini:{m}`"
                            for m in bot.user_models(uid, "gemini")) or "—",
            inline=False)
        emb.add_field(
            name="OpenRouter",
            value="\n".join(f"`openrouter:{m}`"
                            for m in bot.user_models(uid, "openrouter")) or "—",
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
            "openrouter" if any(k in ml for k in
                                ("deepseek", "anthropic", "mistral"))
            else "groq")
    if prov not in ("groq", "gemini", "openrouter"):
        return await ctx.send(f"❌ Unsupported `{prov}`.", ephemeral=True)
    field = f"{prov}_models"
    existing = u.get(field, [])
    if mid in existing:
        existing.remove(mid)
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
        return await ctx.send(f"Default: **{cur}**\n\n{listing}",
                              ephemeral=True)
    resolved = resolve_voice(name, uid, bot) or name
    if resolved not in voices:
        return await ctx.send(
            f"❌ Unknown. Options: {', '.join(voices.keys())}",
            ephemeral=True)
    u = bot._cs(uid); u["default_voice"] = resolved; bot._save_cs()
    await ctx.send(f"✅ Default voice → {voices[resolved]['emoji']} "
                   f"**{voices[resolved]['desc']}**")


@cs_group.command(name="voice-add", description="Add custom Fish Audio voice")
@app_commands.describe(name="Short name", fish_id="Fish Audio reference ID",
                       emoji="Emoji", desc="Description")
async def cs_voice_add(ctx, name: str, fish_id: str, emoji: str = "🎤",
                       desc: str = None):
    uid = ctx.author.id
    n = name.lower().strip().replace(" ", "-")
    if n in BUILTIN_VOICES:
        return await ctx.send("❌ Name collides.", ephemeral=True)
    u = bot._cs(uid)
    u.setdefault("voices", {})[n] = {"id": fish_id, "emoji": emoji,
                                      "desc": desc or n}
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


@cs_group.command(name="voices",
                  description="List all voices available to you")
async def cs_voices(ctx):
    uid = ctx.author.id
    voices = bot.all_voices(uid)
    lines = [f"**Built-in voices**"]
    for k, v in BUILTIN_VOICES.items():
        lines.append(f"• `{k}` — {v['emoji']} {v['desc']}")

    custom = bot.cs.get(uid, {}).get("voices", {})
    if custom:
        lines.append("\n**Your custom voices**")
        for k in custom.keys():
            v = voices.get(k, {})
            lines.append(f"• `{k}` — {v.get('emoji', '🎤')} "
                         f"{v.get('desc', k)}")

    lines.append("\n**Friendly aliases** (use in `[GENERATE_TTS: alias|text]`)")
    aliases_shown = {}
    for alias, target in VOICE_ALIASES.items():
        aliases_shown.setdefault(target, []).append(alias)
    for target, aliases in aliases_shown.items():
        if target in BUILTIN_VOICES:
            lines.append(f"• {', '.join(aliases)} → `{target}`")

    await send_long(ctx, "🎙️ **Voices**\n" + "\n".join(lines))


@cs_group.command(name="macro",
                  description="Save/run prompt shortcuts (.name in chat)")
@app_commands.describe(action="add | remove | list", name="Macro name",
                       prompt="Prompt text")
async def cs_macro(ctx, action: str = "list", name: str = None,
                   prompt: str = None):
    uid = ctx.author.id
    a = action.lower()
    u = bot._cs(uid)
    macros = u.setdefault("macros", {})
    if a == "add":
        if not name or not prompt:
            return await ctx.send("❌ name + prompt required.")
        macros[name.lower()] = prompt; bot._save_cs()
        return await ctx.send(f"💾 Macro `.{name.lower()}` saved.")
    if a == "remove":
        if not name or name.lower() not in macros:
            return await ctx.send("❌ Not found.")
        macros.pop(name.lower()); bot._save_cs()
        return await ctx.send("🗑️ Removed.")
    if a == "list":
        if not macros:
            return await ctx.send("No macros.")
        return await send_long(
            ctx, "💾 **Macros**\n"
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
        return await send_long(
            ctx,
            f"🧠 **Pool** ({'custom' if pool else 'default'}, "
            f"{len(current)})\n{lines[:3500]}")
    if a == "add":
        if not value:
            return await ctx.send("❌ `/cs gif add <url>`")
        pool.append(value.strip()); bot._save_cs()
        return await ctx.send(f"✅ Added ({len(pool)}).")
    if a == "remove":
        try:
            pool.pop(int(value)); bot._save_cs()
            return await ctx.send("🗑️ Removed.")
        except (TypeError, ValueError, IndexError):
            return await ctx.send("❌ Invalid index.")
    if a == "clear":
        u["brainrot_gifs"] = []; bot._save_cs()
        return await ctx.send("🧹 Cleared.")
    if a == "reset":
        u.pop("brainrot_gifs", None); bot._save_cs()
        return await ctx.send("↺ Reset.")
    await ctx.send("❌ list | add | remove | clear | reset")


@cs_group.command(name="ping",
                  description="Control whether Mac responds to your messages")
@app_commands.describe(mode="on | off | dm_only | status")
@app_commands.choices(mode=[
    app_commands.Choice(name="🔔 on", value="on"),
    app_commands.Choice(name="🔕 off", value="off"),
    app_commands.Choice(name="💌 dm_only", value="dm_only"),
    app_commands.Choice(name="ℹ️ status", value="status")])
async def cs_ping(ctx, mode: str = "status"):
    uid = ctx.author.id
    if mode == "status":
        return await ctx.send(f"Current: **{bot.get_ping_pref(uid)}**",
                              ephemeral=True)
    bot.set_ping_pref(uid, mode)
    await ctx.send(f"✅ Ping mode → **{mode}**", ephemeral=True)


@cs_group.command(name="placeholder",
                  description="Toggle the 🔥 Thinking placeholder")
@app_commands.describe(enabled="True = show placeholder. False = typing only")
async def cs_placeholder(ctx, enabled: bool = None):
    uid = ctx.author.id
    if enabled is None:
        cur = bot.get_placeholder_pref(uid)
        return await ctx.send(
            f"Current placeholder: **{'ON' if cur else 'OFF'}**\n"
            "ON = send `🔥 Thinking...` then edit it with the reply\n"
            "OFF = Discord typing indicator only (default, faster)",
            ephemeral=True)
    bot.set_placeholder_pref(uid, enabled)
    await ctx.send(f"✅ Placeholder → **{'ON' if enabled else 'OFF'}**",
                   ephemeral=True)


@cs_group.command(
    name="context",
    description="🧠 Toggle whether Mac uses your slot + memory")
@app_commands.describe(enabled="True = ON (default). False = OFF")
async def cs_context_toggle(ctx, enabled: bool = None):
    uid = ctx.author.id
    if enabled is None:
        on = bot.get_context_enabled(uid)
        return await ctx.send(
            f"Context: **{'ON' if on else 'OFF'}**\n"
            "ON = include your slot history + persistent memory\n"
            "OFF = Mac sees only your current message",
            ephemeral=True)
    bot.set_context_enabled(uid, enabled)
    await ctx.send(f"✅ Context → **{'ON' if enabled else 'OFF'}**",
                   ephemeral=True)


@cs_group.command(
    name="autocontext",
    description="📡 Auto-read N recent channel messages (0 = off, 3–10)")
@app_commands.describe(count="0 disables. 3–10 enables. Default is 0 (OFF).")
async def cs_autocontext(ctx, count: int = None):
    uid = ctx.author.id
    if count is None:
        cur = bot.get_auto_context(uid)
        return await ctx.send(
            f"Auto-context: **{cur if cur else 'OFF'}**\n"
            "When enabled, Mac reads the last N messages in the channel "
            "before replying. Default is OFF (0). Range: 3–10.",
            ephemeral=True)
    bot.set_auto_context(uid, count)
    new = bot.get_auto_context(uid)
    if new == 0:
        await ctx.send("✅ Auto-context → **OFF**", ephemeral=True)
    else:
        await ctx.send(f"✅ Auto-context → **last {new} messages**",
                       ephemeral=True)


@cs_group.command(name="inspector",
                  description="📜 Show N messages around a given message")
@app_commands.describe(
    message="Message ID, or a jump link to any message",
    before="How many messages before (default 3, max 10)",
    after="How many messages after (default 3, max 10)")
async def cs_inspector(ctx, message: str, before: int = 3, after: int = 3):
    before = max(0, min(CONTEXT_WINDOW_LIMIT, before))
    after = max(0, min(CONTEXT_WINDOW_LIMIT, after))

    target_id: Optional[int] = None
    channel = ctx.channel
    raw = message.strip()
    if raw.isdigit():
        target_id = int(raw)
    else:
        m = re.search(r"/channels/(\d+)/(\d+)/(\d+)", raw)
        if m:
            ch_id = int(m.group(2)); target_id = int(m.group(3))
            try:
                channel = (bot.get_channel(ch_id)
                           or await bot.fetch_channel(ch_id))
            except Exception:
                return await ctx.send("❌ Couldn't resolve that channel.",
                                      ephemeral=True)

    if not target_id:
        return await ctx.send("❌ Provide a message ID or a jump link.",
                              ephemeral=True)

    try:
        anchor = await channel.fetch_message(target_id)
    except Exception as e:
        return await ctx.send(f"❌ Couldn't fetch message: {e}",
                              ephemeral=True)

    try:
        window = await channel.history(
            limit=before + after + 1, around=anchor,
            oldest_first=True).flatten()
    except Exception as e:
        return await ctx.send(f"❌ History failed: {e}", ephemeral=True)

    if not window:
        return await ctx.send("📭 No messages found.", ephemeral=True)

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

    chunks = chunk_text(full, 1900)
    if ctx.interaction:
        try:
            await ctx.interaction.response.send_message(chunks[0],
                                                         ephemeral=True)
            for c in chunks[1:]:
                await ctx.interaction.followup.send(c, ephemeral=True)
            return
        except Exception:
            pass
    await ctx.send(chunks[0], ephemeral=True)
    for c in chunks[1:]:
        await ctx.send(c, ephemeral=True)


@cs_group.command(name="show",
                  description="Show ALL your customizations")
async def cs_show(ctx):
    uid = ctx.author.id
    u = bot.cs.get(uid, {})
    emb = discord.Embed(
        title=f"⚙️ {ctx.author.display_name}'s Customizations",
        color=C_PRIMARY)
    emb.add_field(name="Mode", value=f"`{bot.get_user_mode(uid)}`", inline=True)
    emb.add_field(name="Ping", value=f"`{bot.get_ping_pref(uid)}`", inline=True)
    emb.add_field(name="Placeholder",
                  value="ON" if bot.get_placeholder_pref(uid) else "OFF",
                  inline=True)
    emb.add_field(name="Context",
                  value="ON" if bot.get_context_enabled(uid) else "OFF",
                  inline=True)
    auto_ctx = bot.get_auto_context(uid)
    emb.add_field(name="Auto-context",
                  value=f"{auto_ctx} msgs" if auto_ctx else "OFF",
                  inline=True)
    prof = u.get("profile", {})
    if prof:
        emb.add_field(
            name="Profile",
            value="\n".join(f"• {k}: {v}" for k, v in prof.items())[:1024],
            inline=False)
    for p in PROVIDERS:
        if u.get(f"{p}_keys"):
            emb.add_field(name=f"{p} keys",
                          value=f"{len(u[f'{p}_keys'])} set", inline=True)
    for p in MODEL_PROVIDERS:
        if u.get(f"{p}_models"):
            emb.add_field(
                name=f"{p} models",
                value=f"{len(u[f'{p}_models'])}: "
                      f"`{u[f'{p}_models'][0][:40]}`",
                inline=True)
    aliases = u.get("model_aliases", {})
    if aliases:
        active = u.get("active_alias")
        emb.add_field(
            name="Aliases",
            value=", ".join(f"`{a}`" + (" ✅" if a == active else "")
                            for a in aliases)[:1024],
            inline=False)
    if u.get("voices"):
        emb.add_field(name="Custom voices",
                      value=", ".join(u["voices"].keys())[:1024], inline=False)
    if u.get("macros"):
        emb.add_field(name="Macros",
                      value=", ".join(f".{n}" for n in u["macros"])[:1024],
                      inline=False)
    if u.get("brainrot_gifs"):
        emb.add_field(name="Brainrot pool",
                      value=f"{len(u['brainrot_gifs'])} custom GIFs",
                      inline=True)
    profiles = bot.list_profiles(uid)
    if profiles:
        emb.add_field(name="Profiles",
                      value=", ".join(f"`{p}`" for p in profiles)[:1024],
                      inline=False)
    await ctx.send(embed=emb, ephemeral=True)


@cs_group.command(name="reset",
                  description="Reset a section of your customizations")
@app_commands.describe(
    section="profile | keys | models | aliases | voices | macros | "
            "gifs | context | all")
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
        for p in PROVIDERS:
            u.pop(f"{p}_keys", None)
    elif s == "models":
        for p in MODEL_PROVIDERS:
            u.pop(f"{p}_models", None)
    elif s == "aliases":
        u.pop("model_aliases", None); u.pop("active_alias", None)
    elif s == "voices":
        u.pop("voices", None)
    elif s == "macros":
        u.pop("macros", None)
    elif s == "gifs":
        u.pop("brainrot_gifs", None)
    elif s == "context":
        u.pop("context_enabled", None); u.pop("auto_context", None)
    else:
        return await ctx.send(
            "❌ Options: profile, keys, models, aliases, voices, macros, "
            "gifs, context, all")
    bot._save_cs()
    await ctx.send(f"🧹 Reset `{s}`.")


# ======================================================================
# /profiles
# ======================================================================
@bot.hybrid_command(name="profiles",
                    description="🎭 Save, load, list, or delete snapshots")
@app_commands.autocomplete(name=_profile_ac)
@app_commands.describe(action="save | load | list | delete",
                       name="Profile name")
async def profiles_cmd(ctx, action: str = "list", name: str = None):
    uid = ctx.author.id
    a = action.lower()
    if a == "list":
        names = bot.list_profiles(uid)
        if not names:
            return await ctx.send(
                "No profiles. `/profiles save name:<name>`", ephemeral=True)
        return await ctx.send(
            "🎭 **Profiles**\n" + "\n".join(f"• `{n}`" for n in names),
            ephemeral=True)
    if a == "save":
        if not name:
            return await ctx.send("❌ Name required.", ephemeral=True)
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
@bot.hybrid_command(name="benchmark",
                    description="📊 Compare speed of your providers")
@app_commands.describe(prompt="Prompt sent to every provider")
async def benchmark_cmd(ctx, prompt: str):
    await ctx.defer()
    status = await ctx.send("📊 **Benchmarking...**")
    results = await bot.benchmark_prompt(ctx.author.id, prompt)
    if not results:
        return await safe_edit(status, content="❌ No providers configured.")
    emb = discord.Embed(title="📊 Benchmark",
                        description=f"**Prompt:** {prompt[:150]}",
                        color=C_PRIMARY)
    rank = ["🥇", "🥈", "🥉"]
    lines = []
    for i, r in enumerate(results):
        pre = rank[i] if i < 3 else f"{i+1}."
        if r["ok"]:
            lines.append(f"{pre} **{r['provider']}** — "
                         f"`{r['seconds']:.2f}s` · {r['tokens_est']} tok")
        else:
            lines.append(f"{pre} **{r['provider']}** — "
                         f"❌ `{r.get('error', '?')[:80]}`")
    emb.add_field(name="Ranking", value="\n".join(lines), inline=False)
    prev = discord.Embed(title="📝 Previews", color=C_WARM)
    for r in results:
        if r["ok"] and len(prev.fields) < 6:
            prev.add_field(name=f"{r['provider']} · {r['seconds']:.2f}s",
                           value=(r.get("preview") or "(empty)")[:1000],
                           inline=False)
    await safe_edit(status, content=None, embed=emb)
    await safe_send(ctx.channel, embed=prev)


@bot.hybrid_command(name="context",
                    description="📈 Token usage vs max context")
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
    emb.add_field(name="Model",
                  value=f"`{model_name}` (~{limit:,} tok)", inline=False)
    emb.add_field(name="Usage",
                  value=f"`{bar}` **{pct:.1f}%** ({used:,} / {limit:,})",
                  inline=False)
    emb.add_field(name="System", value=f"{stats['system']:,}", inline=True)
    emb.add_field(name="User", value=f"{stats['user']:,}", inline=True)
    emb.add_field(name="Assistant", value=f"{stats['assistant']:,}",
                  inline=True)
    emb.add_field(name="Messages", value=str(stats['messages']), inline=True)
    ctx_on = bot.get_context_enabled(uid)
    auto_ctx = bot.get_auto_context(uid)
    emb.add_field(name="Context", value="ON" if ctx_on else "OFF", inline=True)
    emb.add_field(name="Auto-context",
                  value=f"{auto_ctx} msgs" if auto_ctx else "OFF",
                  inline=True)
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
    bot.hybrid_command(
        name=_name,
        description=f"🗂️ Switch to chat slot {_name}"
    )(_make_slot_cmd(_name))


@bot.hybrid_command(name="svc",
                    description="💾 Save the current slot and close it")
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
        await ctx.send(f"💾 Slot `{current}` had **{count}** messages, "
                       f"now closed.")


@bot.hybrid_command(name="svclear",
                    description="🧹 Clear the current chat slot")
async def svclear(ctx):
    uid = ctx.author.id
    slot = bot.active_slot.get(uid, "sv1")
    bot.user_slots.setdefault(uid, {f"sv{i}": [] for i in range(1, 6)})[slot] = []
    bot._save_slots()
    await ctx.send(f"🧹 Cleared **{slot}**.")


@bot.hybrid_command(name="svlist",
                    description="📋 Show your 5 chat slots")
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


@bot.hybrid_command(name="vsc",
                    description="👁️ View messages in the current chat slot")
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
    header = (f"📜 **Slot `{slot_name}`** — last {len(recent)} of "
              f"{len(slot)}\n\n")
    full = header + "\n".join(lines)
    if private:
        chunks = chunk_text(full, 1900)
        if ctx.interaction:
            try:
                await ctx.interaction.response.send_message(chunks[0],
                                                             ephemeral=True)
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


@bot.hybrid_command(name="vsm",
                    description="🧠 View your saved persistent memory")
@app_commands.describe(private="Send only to you (default: True)",
                       limit="How many recent entries (default 20, max 100)")
async def vsm_cmd(ctx, private: bool = True, limit: int = 20):
    uid = ctx.author.id
    mem = bot.get_persistent_memory(uid)
    if not mem:
        return await ctx.send(
            "📭 No persistent memory. `/persistent` to enable.",
            ephemeral=True)
    limit = max(1, min(100, limit))
    recent = mem[-limit:]
    lines = []
    for role, content in recent:
        prefix = "🧑" if role == "user" else "🤖"
        lines.append(f"{prefix} {content.replace(chr(10), ' ')[:200]}")
    enabled = "ON" if bot.get_persistent_enabled(uid) else "OFF"
    ctx_on = "ON" if bot.get_context_enabled(uid) else "OFF"
    header = (f"🧠 **Persistent memory** (mem {enabled} · context {ctx_on}) "
              f"— last {len(recent)} of {len(mem)}\n\n")
    full = header + "\n".join(lines)
    if private:
        chunks = chunk_text(full, 1900)
        if ctx.interaction:
            try:
                await ctx.interaction.response.send_message(chunks[0],
                                                             ephemeral=True)
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
# PIPELINES
# ======================================================================
@bot.hybrid_command(name="pipeline",
                    description="🏗️ GEMINI → OPENROUTER → review → fix")
@app_commands.describe(task="What to build", filename="Output filename",
                       iterations="Max review loops (1–5, default 3)")
async def pipeline_cmd(ctx, task: str, filename: str = None,
                        iterations: int = 3):
    await ctx.defer()
    iterations = max(1, min(5, iterations))
    fn = filename.strip() if filename else infer_filename(task)
    try:
        await bot.run_pipeline(ctx.channel, ctx.author.id, task, fn,
                                iterations)
    except Exception as e:
        await ctx.send(f"❌ `{e}`")


@bot.hybrid_command(name="project",
                    description="📦 Multi-file project → .zip")
@app_commands.describe(task="What to build",
                       name="Project name (auto if blank)",
                       iterations="Max review loops (1–3, default 2)")
async def project_cmd(ctx, task: str, name: str = None,
                       iterations: int = 2):
    await ctx.defer()
    iterations = max(1, min(3, iterations))
    name = name.strip() if name else None
    try:
        await bot.run_project(ctx.channel, ctx.author.id, task, name,
                               iterations)
    except Exception as e:
        await ctx.send(f"❌ `{e}`")


# ======================================================================
# CONFIG
# ======================================================================
@bot.hybrid_command(name="config",
                    description="⚙️ Show current bot configuration")
async def config_cmd(ctx):
    uid = ctx.author.id
    emb = discord.Embed(title="⚙️ Mac — Config", color=C_PRIMARY)
    emb.add_field(name="Your mode", value=f"`{bot.get_user_mode(uid)}`",
                  inline=True)
    emb.add_field(name="Image mode",
                  value=f"`{bot.current_image_mode}`", inline=True)
    emb.add_field(name="Memory",
                  value="ON" if bot.memory_enabled else "OFF", inline=True)
    emb.add_field(name="Context",
                  value="ON" if bot.get_context_enabled(uid) else "OFF",
                  inline=True)
    auto_ctx = bot.get_auto_context(uid)
    emb.add_field(name="Auto-context",
                  value=f"{auto_ctx} msgs" if auto_ctx else "OFF",
                  inline=True)
    emb.add_field(
        name="Groq model",
        value=f"`{bot.current_model(uid, 'groq') or GLOBAL_GROQ_MODELS[0]}`",
        inline=True)
    emb.add_field(
        name="Gemini model",
        value=f"`{bot.current_model(uid, 'gemini') or GLOBAL_GEMINI_MODELS[0]}`",
        inline=True)
    or_model = (bot.current_model(uid, "openrouter")
                or (GLOBAL_OPENROUTER_MODELS[0]
                    if GLOBAL_OPENROUTER_MODELS else "—"))
    emb.add_field(name="OpenRouter model", value=f"`{or_model}`", inline=True)
    emb.add_field(name="Voice", value=f"`{bot.default_voice(uid)}`",
                  inline=True)
    emb.add_field(name="Slot",
                  value=f"`{bot.active_slot.get(uid, 'sv1')}`", inline=True)
    emb.add_field(name="Ping", value=f"`{bot.get_ping_pref(uid)}`",
                  inline=True)
    emb.add_field(name="Placeholder",
                  value="ON" if bot.get_placeholder_pref(uid) else "OFF",
                  inline=True)
    emb.add_field(name="Uptime",
                  value=format_uptime(get_uptime_seconds()), inline=True)
    await ctx.send(embed=emb, ephemeral=True)


# ======================================================================
# END OF PART 3
# ======================================================================
# Part 4 will contain: /tts /render /rendermode /hf_model /video, music
# (fixed search — no more autocomplete 400), /debate, memory commands,
# /court, /umf, on_message (rewritten to auto-read any attached or
# replied media), helper functions _do_generate_*, _do_search_and_summarize,
# web server, main().
# ======================================================================
# ======================================================================
# TTS
# ======================================================================
@bot.hybrid_command(name="tts",
                    description="🎙️ Say text as a Discord voice message")
@app_commands.autocomplete(voice=_voice_ac)
@app_commands.describe(
    voice="Voice (accepts aliases like 'scary' or 'british')",
    prompt="Exact text to speak")
async def tts_cmd(ctx, voice: str = None, prompt: str = None):
    await ctx.defer()
    if prompt is None:
        return await ctx.send("❌ `/tts [voice] <text>`")
    uid = ctx.author.id
    voices = bot.all_voices(uid)
    vkey = resolve_voice(voice, uid, bot) if voice else bot.default_voice(uid)
    if not vkey or vkey not in voices:
        vkey = bot.default_voice(uid)
    if vkey not in voices:
        vkey = DEFAULT_VOICE
    clean = strip_for_tts(prompt)
    if not clean:
        return await ctx.send("❌ Nothing to say.")
    try:
        audio = await bot.generate_voice(clean, uid=uid, voice_key=vkey,
                                          fmt="opus")
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
            file=file2)


# ======================================================================
# IMAGE
# ======================================================================
@bot.hybrid_command(name="render", description="🎨 Generate an image")
@app_commands.describe(prompt="Describe the image",
                       mode="smart | fast | hf")
async def render_cmd(ctx, prompt: str, mode: str = None):
    await ctx.defer()
    uid = ctx.author.id
    chosen = (mode or bot.current_image_mode).lower()
    status = await ctx.send("🔥 Checking your prompt...")
    try:
        safe, reason = await bot.is_prompt_safe(prompt, uid=uid)
        if not safe:
            return await status.edit(content=f"🚫 **Blocked.**\n"
                                             f"Reason: {reason}")
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


@bot.hybrid_command(name="rendermode",
                    description="🖼️ Show or change the default image mode")
@app_commands.describe(mode="smart | fast | hf")
async def rendermode_cmd(ctx, mode: str = None):
    if mode is None:
        emb = discord.Embed(title="🖼️ Image Mode", color=C_PRIMARY)
        emb.add_field(name="Current",
                      value=f"`{bot.current_image_mode}`", inline=False)
        emb.add_field(
            name="Options",
            value="• `smart` → Gemini\n"
                  "• `fast` → Pollinations\n"
                  "• `hf` → Hugging Face",
            inline=False)
        return await ctx.send(embed=emb)
    if mode.lower() not in ("smart", "fast", "hf"):
        return await ctx.send("❌ Mode must be `smart`, `fast`, or `hf`")
    bot.current_image_mode = mode.lower()
    await ctx.send(f"✅ Image mode → **{mode}**")


@bot.hybrid_command(name="hf_model",
                    description="🤗 Show or change the HF image model")
@app_commands.describe(model="HF model id (blank to show current)")
async def hf_model_cmd(ctx, model: str = None):
    if model is None:
        listing = "\n".join(f"• `{m}`" for m in GLOBAL_HF_IMAGE_MODELS)
        current = (bot.current_model(ctx.author.id, "hf_image")
                   or GLOBAL_HF_IMAGE_MODELS[0])
        return await ctx.send(
            f"🤗 Current: `{current}`\n\n**Fallback list:**\n{listing}")
    u = bot._cs(ctx.author.id)
    u["hf_image_models"] = [model.strip()]
    bot._save_cs()
    await ctx.send(f"✅ HF image model → `{model}`")


# ======================================================================
# VIDEO
# ======================================================================
@bot.hybrid_command(name="video",
                    description="🎬 Generate a video from a prompt")
@app_commands.describe(prompt="Describe the video")
async def video_cmd(ctx, prompt: str):
    await ctx.defer()
    status = await ctx.send(f"🎬 Starting video: **{prompt}**...")
    bot.loop.create_task(bot.generate_video(prompt, ctx.author.id, status))


# ======================================================================
# MUSIC — fixed search (no more autocomplete 400), wide panel,
#         live position, auto-refresh, unified queue
# ======================================================================
import yt_dlp

_YTDL_OPTS: Dict[str, Any] = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "default_search": "ytsearch",
    "extract_flat": False,
    "cachedir": False,
    # Bypass SABR — these clients still use legacy DASH endpoints
    "extractor_args": {
        "youtube": {
            "player_client": ["tv", "mweb", "web_safari"],
            "player_skip": ["configs", "webpage"],
        }
    },
    "http_headers": {
        "User-Agent": _BROWSER_UA,
        "Accept-Language": "en-US,en;q=0.9",
    },
}

# Cookies fallback — if YTDLP_COOKIES_B64 is set, decode it to a file
if YTDLP_COOKIES_B64:
    try:
        with open(YTDLP_COOKIES_PATH, "wb") as _f:
            _f.write(base64.b64decode(YTDLP_COOKIES_B64))
        _YTDL_OPTS["cookiefile"] = YTDLP_COOKIES_PATH
        logger.info(f"yt-dlp cookies loaded from base64 → "
                    f"{YTDLP_COOKIES_PATH}")
    except Exception as _e:
        logger.warning(f"Cookie decode failed: {_e}")
elif YTDLP_COOKIES_PATH and os.path.exists(YTDLP_COOKIES_PATH):
    _YTDL_OPTS["cookiefile"] = YTDLP_COOKIES_PATH
    logger.info(f"yt-dlp cookies loaded from {YTDLP_COOKIES_PATH}")


def _yt_extract_sync(target: str, limit: int = 1) -> List[dict]:
    try:
        opts = dict(_YTDL_OPTS)
        with yt_dlp.YoutubeDL(opts) as ydl:
            if target.startswith(("http://", "https://")):
                info = ydl.extract_info(target, download=False)
                if info and "entries" in info:
                    return list(info["entries"])
                return [info] if info else []
            info = ydl.extract_info(f"ytsearch{limit}:{target}",
                                     download=False)
            return info.get("entries", []) or []
    except Exception as e:
        msg = str(e)
        if "Sign in to confirm" in msg or "not a bot" in msg:
            logger.warning("YouTube is blocking this IP (bot detection). "
                           "Set YTDLP_COOKIES_B64 env var or update yt-dlp.")
        else:
            logger.warning(f"yt-dlp extract failed: {msg[:200]}")
        return []


async def yt_resolve(target: str, limit: int = 1) -> List[dict]:
    return await asyncio.to_thread(_yt_extract_sync, target, limit)


def _pick_best_audio(entry: dict) -> Optional[str]:
    if (entry.get("url") and entry["url"].startswith("http")
            and entry.get("acodec")):
        return entry["url"]
    formats = entry.get("formats") or []
    audio = [f for f in formats
             if f.get("acodec") and f["acodec"] != "none"
             and f.get("vcodec") in (None, "none")]
    if not audio:
        audio = [f for f in formats
                 if f.get("acodec") and f["acodec"] != "none"]
    if not audio:
        return None
    audio.sort(key=lambda f: (f.get("abr") or 0, f.get("tbr") or 0),
               reverse=True)
    return audio[0].get("url")


def _yt_entry_to_track(entry: dict,
                        meta_override: Optional[dict] = None
                        ) -> Optional[dict]:
    stream = _pick_best_audio(entry)
    if not stream:
        return None
    title = (meta_override or {}).get("title") or entry.get("title") or "?"
    artist = ((meta_override or {}).get("artist")
              or entry.get("uploader")
              or entry.get("channel") or "?")
    thumb = (meta_override or {}).get("thumb") or entry.get("thumbnail")
    return {
        "title": title[:120],
        "artist": artist[:120],
        "source": (meta_override or {}).get("source", "youtube"),
        "stream_url": stream,
        "url": entry.get("webpage_url") or stream,
        "duration_ms": int((entry.get("duration") or 0) * 1000) or None,
        "thumb": thumb,
    }


# ---------- Spotify metadata ----------
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
                         "Content-Type":
                             "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials"},
                timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    return None
                d = await r.json()
                _SPOTIFY_TOKEN = d.get("access_token")
                _SPOTIFY_TOKEN_EXP = time.time() + d.get("expires_in", 3600)
                return _SPOTIFY_TOKEN
    except Exception as e:
        logger.warning(f"Spotify token: {e}")
        return None


async def spotify_search_tracks(query: str, limit: int = 10) -> List[dict]:
    tok = await _spotify_token()
    if not tok:
        return []
    try:
        async with shared_session() as s:
            async with s.get(
                SPOTIFY_SEARCH_URL,
                headers={"Authorization": f"Bearer {tok}"},
                params={"q": query, "type": "track", "limit": limit},
                timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    return []
                d = await r.json()
        out = []
        for t in d.get("tracks", {}).get("items", []):
            artists = ", ".join(a["name"] for a in t.get("artists", []))
            out.append({
                "title": t.get("name", "?"),
                "artist": artists or "?",
                "source": "spotify",
                "spotify_id": t.get("id"),
                "url": t.get("external_urls", {}).get("spotify"),
                "duration_ms": t.get("duration_ms"),
                "thumb": (t.get("album", {}).get("images") or [{}])[0].get("url"),
            })
        return out
    except Exception as e:
        logger.warning(f"Spotify search: {e}")
        return []


async def resolve_spotify_url(url: str) -> Optional[dict]:
    try:
        async with shared_session() as s:
            async with s.get(
                f"https://open.spotify.com/oembed?url={url}",
                timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    return None
                d = await r.json()
        title = (d.get("title") or "").strip()
        if not title:
            return None
        if " · " in title:
            t, a = title.split(" · ", 1)
            return {"title": t.strip(), "artist": a.strip()}
        return {"title": title, "artist": ""}
    except Exception:
        return None


async def search_music_full(query: str, limit: int = 10) -> List[dict]:
    q = query.strip()

    if q.startswith(("https://youtu.be/", "https://www.youtube.com/",
                     "https://youtube.com/", "https://music.youtube.com/")):
        entries = await yt_resolve(q, limit=limit)
        tracks = []
        for e in entries[:limit]:
            if not isinstance(e, dict):
                continue
            t = _yt_entry_to_track(e)
            if t:
                t["source"] = "youtube"
                tracks.append(t)
        return tracks

    sp = re.search(
        r'https?://open\.spotify\.com/(?:intl-\w+/)?(track|album|playlist)/(\w+)',
        q)
    if sp:
        kind, sid = sp.group(1), sp.group(2)
        if kind != "track":
            return []
        canonical = f"https://open.spotify.com/{kind}/{sid}"
        meta = await resolve_spotify_url(canonical)
        if not meta:
            return []
        text_q = f"{meta['title']} {meta['artist']}".strip()
        entries = await yt_resolve(text_q, limit=5)
        tracks = []
        for e in entries:
            t = _yt_entry_to_track(e, {**meta, "source": "spotify"})
            if t:
                tracks.append(t)
        return tracks

    spotify_hits: List[dict] = []
    if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
        spotify_hits = await spotify_search_tracks(q, limit=limit)

    yt_entries = await yt_resolve(q, limit=limit)
    yt_tracks = []
    for e in yt_entries:
        t = _yt_entry_to_track(e)
        if t:
            yt_tracks.append(t)

    if spotify_hits and yt_tracks:
        merged = []
        for sp_track in spotify_hits:
            key = sp_track["title"].lower()[:40]
            match = None
            for yt in yt_tracks:
                yk = yt["title"].lower()[:40]
                if key and (key in yk or yk in key):
                    match = yt
                    break
            if match:
                merged.append({
                    "title": sp_track["title"],
                    "artist": sp_track["artist"],
                    "source": "spotify",
                    "stream_url": match["stream_url"],
                    "url": sp_track["url"],
                    "duration_ms": sp_track["duration_ms"]
                                   or match["duration_ms"],
                    "thumb": sp_track.get("thumb") or match.get("thumb"),
                })
        if merged:
            return merged[:limit]

    return yt_tracks[:limit]


# ---------- Session ----------
class MusicSession:
    __slots__ = ("guild_id", "text_channel_id", "voice_client",
                 "queue", "current", "loop_mode", "volume",
                 "panel_message", "update_task",
                 "play_start", "pause_start", "accumulated_pause")

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.text_channel_id: Optional[int] = None
        self.voice_client: Optional[Any] = None
        self.queue: List[dict] = []
        self.current: Optional[dict] = None
        self.loop_mode: str = "off"
        self.volume: float = 1.0
        self.panel_message: Optional[discord.Message] = None
        self.update_task: Optional[asyncio.Task] = None
        self.play_start: Optional[float] = None
        self.pause_start: Optional[float] = None
        self.accumulated_pause: float = 0.0


def _get_music_session(guild_id: int) -> MusicSession:
    if guild_id not in bot.music_sessions:
        bot.music_sessions[guild_id] = MusicSession(guild_id)
    return bot.music_sessions[guild_id]


def _loop_label(mode: str) -> str:
    return {"off": "Off", "track": "Track", "queue": "Queue",
            "24_7": "24/7"}.get(mode, "Off")


def _fmt_seconds(secs: float) -> str:
    secs = max(0, int(secs))
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_duration(ms: Optional[int]) -> str:
    if not ms:
        return ""
    return _fmt_seconds(ms / 1000)


def _get_position_seconds(session: MusicSession) -> float:
    if session.play_start is None:
        return 0.0
    now = session.pause_start if session.pause_start else time.time()
    return max(0.0, now - session.play_start - session.accumulated_pause)


def _progress_bar(pos: float, total: float, width: int = 16) -> str:
    if not total or total <= 0:
        return "▬" * width
    pct = min(1.0, max(0.0, pos / total))
    filled = min(int(pct * (width - 1)), width - 1)
    return "▬" * filled + "🔘" + "▬" * (width - filled - 1)


def _music_panel_embed(session: MusicSession) -> discord.Embed:
    emb = discord.Embed(color=C_MUSIC)
    emb.title = "🎵   Music Panel"

    cur = session.current
    if cur:
        pos = _get_position_seconds(session)
        total = (cur.get("duration_ms") or 0) / 1000
        vc = session.voice_client
        is_paused = bool(vc and vc.is_paused())
        state = "⏸️  Paused" if is_paused else "▶️  Playing"

        if total > 0:
            bar = _progress_bar(pos, total, width=18)
            timing = f"`{_fmt_seconds(pos)}`  {bar}  `{_fmt_seconds(total)}`"
        else:
            timing = f"`{_fmt_seconds(pos)}`  " + "▬" * 18

        src = cur.get("source", "?").capitalize()
        emb.description = (
            f"### {state}\n"
            f"**{cur['title']}**\n"
            f"-# {cur['artist']}   ·   *{src}*\n"
            f"\n{timing}"
        )
        if cur.get("thumb"):
            emb.set_thumbnail(url=cur["thumb"])
    else:
        emb.description = (
            "### 💤  Nothing playing\n"
            "-# Use the **🔎 Search** button or `/play <song>` to add a track."
        )

    if session.queue:
        lines = []
        for i, t in enumerate(session.queue[:6], 1):
            dur = _fmt_duration(t.get("duration_ms"))
            d = f"   `{dur}`" if dur else ""
            lines.append(f"`{i:>2}.` **{t['title'][:55]}**\n"
                         f"-#    {t['artist'][:40]}{d}")
        if len(session.queue) > 6:
            lines.append(f"-# …and {len(session.queue) - 6} more")
        emb.add_field(
            name=f"📋   Up Next   ·   {len(session.queue)} in queue",
            value="\n".join(lines), inline=False)
    else:
        emb.add_field(name="📋   Up Next",
                      value="-# Queue is empty", inline=False)

    footer_bits = [
        f"🔁 {_loop_label(session.loop_mode)}",
        f"🔊 {int(session.volume * 100)}%",
    ]
    if not _VOICE_LIB_OK:
        footer_bits.append("⚠️ voice libs missing")
    emb.set_footer(text="   ·   ".join(footer_bits))
    return emb


async def _ensure_voice(interaction: discord.Interaction,
                         session: MusicSession):
    if not _VOICE_LIB_OK:
        raise Exception("Voice libs missing (PyNaCl / davey)")
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
        session.play_start = None
        session.pause_start = None
        session.accumulated_pause = 0.0
        return

    if not next_track or not next_track.get("stream_url"):
        return _play_next(guild_id)
    session.current = next_track
    session.play_start = time.time()
    session.pause_start = None
    session.accumulated_pause = 0.0

    def _after(err):
        if err:
            logger.warning(f"Voice playback error: {err}")
        try:
            bot.loop.call_soon_threadsafe(_play_next, guild_id)
        except Exception:
            pass

    try:
        source = discord.FFmpegPCMAudio(
            next_track["stream_url"],
            before_options=("-reconnect 1 -reconnect_streamed 1 "
                            "-reconnect_delay_max 5 -nostdin"),
            options="-vn")
        if session.volume != 1.0:
            source = discord.PCMVolumeTransformer(source, volume=session.volume)
        vc.play(source, after=_after)
        _ensure_panel_updater(session)
    except Exception as e:
        logger.error(f"Play failed: {e}")
        session.current = None
        _play_next(guild_id)


async def _music_panel_loop(guild_id: int):
    """
    Refresh the panel while it needs to stay live.
      - playing/paused → every 15 s (position bar)
      - idle but connected → every 60 s (cheap)
      - disconnected AND nothing to show → exit entirely
    """
    while True:
        session = bot.music_sessions.get(guild_id)
        if session is None or session.panel_message is None:
            return

        vc = session.voice_client
        connected = bool(vc and vc.is_connected())
        active = bool(connected and (vc.is_playing() or vc.is_paused()))

        if not connected and not session.queue and not session.current:
            return

        await asyncio.sleep(15 if active else 60)

        session = bot.music_sessions.get(guild_id)
        if session is None or session.panel_message is None:
            return

        try:
            await session.panel_message.edit(embed=_music_panel_embed(session))
        except (discord.NotFound, discord.Forbidden):
            session.panel_message = None
            return
        except discord.HTTPException:
            await asyncio.sleep(30)


def _ensure_panel_updater(session: MusicSession):
    if session.update_task and not session.update_task.done():
        return
    session.update_task = bot.loop.create_task(
        _music_panel_loop(session.guild_id))


async def _refresh_panel(session: MusicSession):
    if session.panel_message is None:
        return
    try:
        await session.panel_message.edit(embed=_music_panel_embed(session))
    except (discord.NotFound, discord.HTTPException, discord.Forbidden):
        session.panel_message = None


# ---------- Autocomplete + cache for /play ----------
_ac_cache: Dict[int, dict] = {}
# Stash raw URL / query strings per-user so we don't exceed Discord's 100-char
# choice value limit.
_ac_raw: Dict[int, dict] = {}


async def _play_ac(interaction: discord.Interaction,
                   current: str) -> List[app_commands.Choice[str]]:
    uid = interaction.user.id
    raw = (current or "").strip()

    # Always stash the raw input for later retrieval
    _ac_raw[uid] = {"url": raw[:500], "raw": raw[:500], "t": time.time()}

    if raw.startswith(("http://", "https://", "spotify:", "youtu")):
        return [app_commands.Choice(
            name=f"🔗 Use this link: {raw[:80]}",
            value="__url__")]

    if len(raw) < 2:
        return [app_commands.Choice(
            name="Keep typing… (min 2 chars)",
            value="__hint__")]

    key = raw.lower()
    cached = _ac_cache.get(uid)
    if (cached and cached.get("q") == key
            and time.time() - cached.get("t", 0) < MUSIC_SEARCH_TTL):
        results = cached.get("r", [])
    else:
        try:
            results = await search_music_full(raw, limit=12)
        except Exception as e:
            logger.warning(f"AC search failed: {e}")
            results = []
        _ac_cache[uid] = {"q": key, "r": results, "t": time.time()}

    if not results:
        return [app_commands.Choice(
            name=f"No results for '{raw[:80]}'",
            value="__raw__")]

    out: List[app_commands.Choice[str]] = []
    for i, r in enumerate(results[:25]):
        icon = "🎧" if r.get("source") == "spotify" else "▶️"
        dur = _fmt_duration(r.get("duration_ms"))
        label = f"{icon} {r['title'][:55]} - {r['artist'][:35]}"
        if dur:
            label += f" - {dur}"
        out.append(app_commands.Choice(name=label[:100],
                                        value=f"__idx__|{i}"))
    return out


# ---------- /play ----------
@bot.hybrid_command(
    name="play",
    description="🎶 Play a song — name, Spotify link, or YouTube link")
@app_commands.autocomplete(query=_play_ac)
@app_commands.describe(query="Song name, Spotify URL, or YouTube URL")
async def play_cmd(ctx: commands.Context, query: str):
    if not ctx.guild:
        return await ctx.send("Servers only.", ephemeral=True)

    await ctx.defer()

    # Short-token dispatch
    if query == "__hint__":
        return await ctx.send("❌ Start typing a song name.")

    if query == "__url__":
        url = (_ac_raw.get(ctx.author.id) or {}).get("url", "")
        if not url:
            return await ctx.send("❌ Link expired — paste it again.",
                                   ephemeral=True)
        session = _get_music_session(ctx.guild.id)
        session.text_channel_id = ctx.channel.id
        track: Optional[dict] = None
        search_term: Optional[str] = None

        if "open.spotify.com" in url:
            results = await search_music_full(url, limit=5)
            if not results:
                return await ctx.send("❌ Couldn't resolve that Spotify link.")
            track = results[0]
        elif "youtu" in url:
            results = await search_music_full(url, limit=1)
            if not results:
                return await ctx.send("❌ Couldn't resolve that YouTube link.")
            track = results[0]
        elif url.lower().endswith((".mp3", ".m4a", ".ogg", ".opus", ".wav")):
            track = {
                "title": url.rsplit("/", 1)[-1][:60] or "Direct link",
                "artist": "direct", "source": "direct",
                "stream_url": url, "url": url, "duration_ms": None,
            }
        else:
            search_term = url

        if track is None and search_term:
            results = await search_music_full(search_term, limit=10)
            if not results:
                return await ctx.send(f"❌ No results for `{search_term}`.")
            bot._pending_searches[ctx.author.id] = results
            emb = discord.Embed(
                title=f"🔎 Results for: {search_term[:100]}",
                description="Select a track below.",
                color=C_MUSIC)
            lines = []
            for i, r in enumerate(results[:10], 1):
                icon = "🎧" if r.get("source") == "spotify" else "▶️"
                dur = _fmt_duration(r.get("duration_ms"))
                lines.append(f"{i}. {icon} **{r['title'][:55]}** — "
                             f"{r['artist'][:40]}"
                             + (f" · `{dur}`" if dur else ""))
            emb.add_field(name="Results",
                          value="\n".join(lines) or "—", inline=False)
            return await ctx.send(embed=emb,
                                   view=_PlaySelectView(ctx.author.id, results))

        if not track or not track.get("stream_url"):
            return await ctx.send("⚠️ Couldn't resolve a playable stream.")

        session.queue.append(track)

        if not session.voice_client or not session.voice_client.is_connected():
            if ctx.author.voice and ctx.author.voice.channel and _VOICE_LIB_OK:
                try:
                    session.voice_client = await ctx.author.voice.channel.connect()
                except Exception as e:
                    session.queue.pop()
                    return await ctx.send(f"❌ Couldn't join VC: {e}")
            else:
                session.queue.pop()
                return await ctx.send("❌ Join a voice channel first.")

        emb = discord.Embed(
            title="➕ Queued",
            description=f"**{track['title']}**\n{track['artist']}",
            color=C_OK)
        if track.get("duration_ms"):
            emb.add_field(name="Duration",
                          value=_fmt_duration(track["duration_ms"]),
                          inline=True)
        emb.add_field(name="Source", value=track.get("source", "?"),
                      inline=True)
        if track.get("url"):
            emb.add_field(name="Link", value=f"[open]({track['url']})",
                          inline=True)
        if track.get("thumb"):
            emb.set_thumbnail(url=track["thumb"])
        await ctx.send(embed=emb)

        await _refresh_panel(session)
        if session.voice_client and not session.voice_client.is_playing():
            _play_next(ctx.guild.id)
        return

    if query == "__raw__":
        search_term = (_ac_raw.get(ctx.author.id) or {}).get("raw", "")
        if not search_term:
            return await ctx.send("❌ Search expired — try again.",
                                   ephemeral=True)
    elif query.startswith("__idx__|"):
        try:
            idx = int(query[7:])
        except ValueError:
            return await ctx.send("❌ Invalid selection.")
        cached = _ac_cache.get(ctx.author.id) or {}
        results = cached.get("r", [])
        if idx >= len(results):
            return await ctx.send("❌ Selection expired. Search again.")
        track = results[idx]
        session = _get_music_session(ctx.guild.id)
        session.text_channel_id = ctx.channel.id
        session.queue.append(track)
        if not session.voice_client or not session.voice_client.is_connected():
            if ctx.author.voice and ctx.author.voice.channel and _VOICE_LIB_OK:
                try:
                    session.voice_client = await ctx.author.voice.channel.connect()
                except Exception as e:
                    session.queue.pop()
                    return await ctx.send(f"❌ Couldn't join VC: {e}")
            else:
                session.queue.pop()
                return await ctx.send("❌ Join a voice channel first.")
        emb = discord.Embed(
            title="➕ Queued",
            description=f"**{track['title']}**\n{track['artist']}",
            color=C_OK)
        if track.get("duration_ms"):
            emb.add_field(name="Duration",
                          value=_fmt_duration(track["duration_ms"]),
                          inline=True)
        emb.add_field(name="Source", value=track.get("source", "?"),
                      inline=True)
        if track.get("url"):
            emb.add_field(name="Link", value=f"[open]({track['url']})",
                          inline=True)
        if track.get("thumb"):
            emb.set_thumbnail(url=track["thumb"])
        await ctx.send(embed=emb)
        await _refresh_panel(session)
        if session.voice_client and not session.voice_client.is_playing():
            _play_next(ctx.guild.id)
        return
    else:
        search_term = query.strip()

    # Plain text search path — user typed something and hit enter directly
    session = _get_music_session(ctx.guild.id)
    session.text_channel_id = ctx.channel.id
    if not search_term:
        return await ctx.send("❌ Nothing to search.")
    results = await search_music_full(search_term, limit=10)
    if not results:
        return await ctx.send(f"❌ No results for `{search_term}`.")
    bot._pending_searches[ctx.author.id] = results
    emb = discord.Embed(
        title=f"🔎 Results for: {search_term[:100]}",
        description="Select a track below.",
        color=C_MUSIC)
    lines = []
    for i, r in enumerate(results[:10], 1):
        icon = "🎧" if r.get("source") == "spotify" else "▶️"
        dur = _fmt_duration(r.get("duration_ms"))
        lines.append(f"{i}. {icon} **{r['title'][:55]}** — "
                     f"{r['artist'][:40]}"
                     + (f" · `{dur}`" if dur else ""))
    emb.add_field(name="Results", value="\n".join(lines) or "—", inline=False)
    return await ctx.send(embed=emb,
                           view=_PlaySelectView(ctx.author.id, results))


# ---------- Select fallback ----------
class _PlaySelectView(discord.ui.View):
    def __init__(self, user_id: int, results: List[dict]):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.results = results
        self.add_item(_PlayResultSelect(user_id, results))


class _PlayResultSelect(discord.ui.Select):
    def __init__(self, user_id: int, results: List[dict]):
        self.user_id = user_id
        self.results = results
        opts = []
        for i, r in enumerate(results[:25]):
            icon = "🎧" if r.get("source") == "spotify" else "▶️"
            dur = _fmt_duration(r.get("duration_ms"))
            desc = r["artist"][:80]
            if dur:
                desc = f"{desc} · {dur}"
            opts.append(discord.SelectOption(
                label=f"{icon} {r['title'][:60]}",
                description=desc[:100],
                value=str(i)))
        super().__init__(placeholder="Choose a track…",
                         min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "❌ Not your search.", ephemeral=True)
        track = self.results[int(self.values[0])]
        if not track.get("stream_url"):
            return await interaction.response.send_message(
                "⚠️ No stream URL for this track.", ephemeral=True)

        session = _get_music_session(interaction.guild.id)
        session.queue.append(track)
        try:
            await _ensure_voice(interaction, session)
        except Exception as e:
            session.queue.pop()
            return await interaction.response.send_message(
                f"❌ Couldn't join voice: {e}", ephemeral=True)
        await interaction.response.send_message(
            f"➕ Queued **{track['title']}** — {track['artist']}",
            ephemeral=True)
        await _refresh_panel(session)
        if session.voice_client and not session.voice_client.is_playing():
            _play_next(interaction.guild.id)


# ---------- /music panel ----------
class _MusicSearchModal(discord.ui.Modal, title="🔎 Search a song"):
    q = discord.ui.TextInput(label="Song name", required=True, max_length=120)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        results = await search_music_full(self.q.value.strip(), limit=10)
        if not results:
            return await interaction.followup.send("❌ No results.",
                                                    ephemeral=True)
        bot._pending_searches[interaction.user.id] = results
        await interaction.followup.send(
            "**Pick a track:**",
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
            placeholder="Choose a track…", min_values=1, max_values=1,
            options=[discord.SelectOption(
                label=f"{'🎧' if r.get('source')=='spotify' else '▶️'} "
                      f"{r['title'][:60]}",
                description=f"{r['artist'][:80]}"[:100],
                value=str(i)) for i, r in enumerate(results[:25])])

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message(
                "❌ Not your search.", ephemeral=True)
        track = self.results[int(self.values[0])]
        if not track.get("stream_url"):
            return await interaction.response.send_message(
                "⚠️ No stream URL.", ephemeral=True)
        session = _get_music_session(interaction.guild.id)
        session.queue.append(track)
        try:
            await _ensure_voice(interaction, session)
        except Exception as e:
            session.queue.pop()
            return await interaction.response.send_message(
                f"❌ Couldn't join voice: {e}", ephemeral=True)
        await interaction.response.send_message(
            f"➕ Queued **{track['title']}** — {track['artist']}",
            ephemeral=True)
        await _refresh_panel(session)
        if session.voice_client and not session.voice_client.is_playing():
            _play_next(interaction.guild.id)


class _MusicPanelView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="Search", emoji="🔎",
                       style=discord.ButtonStyle.primary, row=0)
    async def search_btn(self, interaction, button):
        await interaction.response.send_modal(_MusicSearchModal())

    @discord.ui.button(label="Play/Pause", emoji="⏯️",
                       style=discord.ButtonStyle.secondary, row=0)
    async def pp_btn(self, interaction, button):
        s = _get_music_session(interaction.guild.id)
        vc = s.voice_client
        if not vc or not vc.is_connected():
            return await interaction.response.send_message(
                "❌ Not connected.", ephemeral=True)
        if vc.is_playing():
            vc.pause()
            s.pause_start = time.time()
            await interaction.response.send_message("⏸️ Paused.",
                                                     ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            if s.pause_start is not None:
                s.accumulated_pause += time.time() - s.pause_start
                s.pause_start = None
            _ensure_panel_updater(s)
            await interaction.response.send_message("▶️ Resumed.",
                                                     ephemeral=True)
        else:
            if s.queue or s.current:
                _play_next(interaction.guild.id)
            await interaction.response.send_message("▶️ Playing.",
                                                     ephemeral=True)
        await _refresh_panel(s)

    @discord.ui.button(label="Skip", emoji="⏭️",
                       style=discord.ButtonStyle.secondary, row=0)
    async def skip_btn(self, interaction, button):
        s = _get_music_session(interaction.guild.id)
        vc = s.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            if s.loop_mode == "track":
                s.loop_mode = "off"
            vc.stop()
            await interaction.response.send_message("⏭️ Skipped.",
                                                     ephemeral=True)
        else:
            await interaction.response.send_message("❌ Nothing playing.",
                                                     ephemeral=True)

    @discord.ui.button(label="Stop", emoji="⏹️",
                       style=discord.ButtonStyle.danger, row=0)
    async def stop_btn(self, interaction, button):
        s = _get_music_session(interaction.guild.id)
        s.queue.clear()
        s.current = None
        s.loop_mode = "off"
        s.play_start = None
        s.pause_start = None
        s.accumulated_pause = 0.0
        vc = s.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        await interaction.response.edit_message(
            embed=_music_panel_embed(s), view=self)

    @discord.ui.button(label="Loop", emoji="🔁",
                       style=discord.ButtonStyle.secondary, row=1)
    async def loop_btn(self, interaction, button):
        s = _get_music_session(interaction.guild.id)
        order = ["off", "track", "queue", "24_7"]
        s.loop_mode = order[(order.index(s.loop_mode) + 1) % len(order)]
        await interaction.response.edit_message(
            embed=_music_panel_embed(s), view=self)

    @discord.ui.button(label="Vol -", emoji="🔉",
                       style=discord.ButtonStyle.secondary, row=1)
    async def vol_down(self, interaction, button):
        s = _get_music_session(interaction.guild.id)
        s.volume = max(0.1, round(s.volume - 0.1, 1))
        if s.voice_client and s.voice_client.source:
            try:
                s.voice_client.source.volume = s.volume
            except Exception:
                pass
        await interaction.response.edit_message(
            embed=_music_panel_embed(s), view=self)

    @discord.ui.button(label="Vol +", emoji="🔊",
                       style=discord.ButtonStyle.secondary, row=1)
    async def vol_up(self, interaction, button):
        s = _get_music_session(interaction.guild.id)
        s.volume = min(2.0, round(s.volume + 0.1, 1))
        if s.voice_client and s.voice_client.source:
            try:
                s.voice_client.source.volume = s.volume
            except Exception:
                pass
        await interaction.response.edit_message(
            embed=_music_panel_embed(s), view=self)

    @discord.ui.button(label="Refresh", emoji="🔄",
                       style=discord.ButtonStyle.secondary, row=1)
    async def refresh_btn(self, interaction, button):
        s = _get_music_session(interaction.guild.id)
        await interaction.response.edit_message(
            embed=_music_panel_embed(s), view=self)

    @discord.ui.button(label="Join My VC", emoji="🔊",
                       style=discord.ButtonStyle.success, row=2)
    async def join_btn(self, interaction, button):
        member = interaction.user
        if not member.voice or not member.voice.channel:
            return await interaction.response.send_message(
                "❌ Not in a VC.", ephemeral=True)
        if not _VOICE_LIB_OK:
            return await interaction.response.send_message(
                "❌ Voice libs missing.", ephemeral=True)
        s = _get_music_session(interaction.guild.id)
        vc = s.voice_client
        if vc and vc.is_connected():
            if vc.channel.id == member.voice.channel.id:
                return await interaction.response.send_message(
                    "✅ Already there.", ephemeral=True)
            await vc.move_to(member.voice.channel)
            return await interaction.response.send_message(
                f"🔊 Moved to **{member.voice.channel.name}**.",
                ephemeral=True)
        try:
            s.voice_client = await member.voice.channel.connect()
            _ensure_panel_updater(s)
            await interaction.response.send_message(
                f"🔊 Joined **{member.voice.channel.name}**.",
                ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Join failed: {e}", ephemeral=True)

    @discord.ui.button(label="Leave VC", emoji="👋",
                       style=discord.ButtonStyle.danger, row=2)
    async def leave_btn(self, interaction, button):
        s = _get_music_session(interaction.guild.id)
        s.queue.clear()
        s.current = None
        s.play_start = None
        s.pause_start = None
        s.accumulated_pause = 0.0
        vc = s.voice_client
        if vc and vc.is_connected():
            await vc.disconnect()
        s.voice_client = None
        await interaction.response.send_message("👋 Left voice.",
                                                 ephemeral=True)
        await _refresh_panel(s)


@bot.hybrid_command(name="music",
                    description="🎵 Music panel — search, queue, loop, position")
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

    msg = await ctx.send(embed=_music_panel_embed(session),
                         view=_MusicPanelView(ctx.guild.id))
    try:
        session.panel_message = await msg.fetch()
    except Exception:
        session.panel_message = msg
    _ensure_panel_updater(session)


# ======================================================================
# AI DEBATE
# ======================================================================
@bot.hybrid_command(name="debate",
                    description="🤖 Start/stop an AI vs AI debate")
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
    await ctx.send(f"🔥 Debate started — **{description}**\n"
                   f"`/debate` again to stop.")


# ======================================================================
# MEMORY
# ======================================================================
@bot.hybrid_command(name="sm",
                    description="🧠 Toggle short-term memory on/off")
async def sm(ctx):
    bot.memory_enabled = not bot.memory_enabled
    await ctx.send(f"🧠 Short-term memory "
                   f"**{'ON' if bot.memory_enabled else 'OFF'}**")


@bot.hybrid_command(name="persistent",
                    description="💾 Enable persistent memory for yourself")
async def persistent_enable(ctx):
    bot.set_persistent_enabled(ctx.author.id, True)
    await ctx.send(f"✅ Persistent memory **ON** for "
                   f"{ctx.author.display_name}")


@bot.hybrid_command(name="persistentdisable",
                    description="🚫 Disable persistent memory")
async def persistent_disable(ctx):
    bot.set_persistent_enabled(ctx.author.id, False)
    await ctx.send("🚫 Persistent memory **OFF**")


@bot.hybrid_command(name="persistentreset",
                    description="🧹 Reset a user's persistent memory "
                                "(admin only)")
@app_commands.describe(target_user="User whose memory to wipe")
async def persistent_reset(ctx, target_user: discord.User):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("❌ Admin only")
    bot.clear_persistent_memory(target_user.id)
    await ctx.send(f"🧹 Reset persistent memory for "
                   f"{target_user.display_name}")


# ======================================================================
# COURT
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
                     f"Now click **📝 Explain Case** below, or "
                     f"**👥 Add Participant** to assign others."),
            view=CourtPanelView(self.bot))

    @discord.ui.button(label="Judge", style=discord.ButtonStyle.primary,
                       row=0)
    async def j(self, i, b): await self.select_role(i, "judge")

    @discord.ui.button(label="Prosecutor", style=discord.ButtonStyle.danger,
                       row=0)
    async def p(self, i, b): await self.select_role(i, "prosecutor")

    @discord.ui.button(label="Defense", style=discord.ButtonStyle.success,
                       row=0)
    async def d(self, i, b): await self.select_role(i, "defense")

    @discord.ui.button(label="Witness", style=discord.ButtonStyle.secondary,
                       row=1)
    async def w(self, i, b): await self.select_role(i, "witness")

    @discord.ui.button(label="Jury", style=discord.ButtonStyle.secondary,
                       row=1)
    async def y(self, i, b): await self.select_role(i, "jury")

    @discord.ui.button(label="Stenographer",
                       style=discord.ButtonStyle.secondary, row=1)
    async def s(self, i, b): await self.select_role(i, "stenographer")


class CourtCaseModal(discord.ui.Modal, title="📝 Explain the Case"):
    case_text = discord.ui.TextInput(
        label="Describe the case",
        style=discord.TextStyle.paragraph,
        required=True, max_length=800)

    async def on_submit(self, interaction: discord.Interaction):
        s = bot.court_sessions.setdefault(
            interaction.user.id,
            {"role": "judge", "case": "", "participants": {}})
        s["case"] = self.case_text.value.strip()
        await interaction.response.send_message(
            "✅ Case recorded. Click **▶️ Start** to begin.", ephemeral=True)


class CourtParticipantModal(discord.ui.Modal, title="👥 Add Participant"):
    user_id = discord.ui.TextInput(label="User ID", required=True,
                                    max_length=30)
    role = discord.ui.TextInput(
        label="Role (judge/prosecutor/defense/witness/jury/stenographer)",
        required=True, max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            uid = int(self.user_id.value.strip())
        except ValueError:
            return await interaction.response.send_message(
                "❌ Invalid user ID.", ephemeral=True)
        r = self.role.value.strip().lower()
        valid = ["judge", "prosecutor", "defense", "witness", "jury",
                 "stenographer"]
        if r not in valid:
            return await interaction.response.send_message(
                f"❌ Role: {', '.join(valid)}", ephemeral=True)
        s = bot.court_sessions.setdefault(
            interaction.user.id,
            {"role": "judge", "case": "", "participants": {}})
        s["participants"][r] = uid
        await interaction.response.send_message(
            f"✅ <@{uid}> → **{r}**", ephemeral=True)


class CourtPanelView(discord.ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=300)
        self.bot = bot_instance

    @discord.ui.button(label="Explain Case", emoji="📝",
                       style=discord.ButtonStyle.primary, row=0)
    async def explain_btn(self, i, b):
        if i.user.id not in bot.court_sessions:
            return await i.response.send_message("❌ Pick a role first.",
                                                  ephemeral=True)
        await i.response.send_modal(CourtCaseModal())

    @discord.ui.button(label="Add Participant", emoji="👥",
                       style=discord.ButtonStyle.secondary, row=0)
    async def add_btn(self, i, b):
        if i.user.id not in bot.court_sessions:
            return await i.response.send_message("❌ Pick a role first.",
                                                  ephemeral=True)
        await i.response.send_modal(CourtParticipantModal())

    @discord.ui.button(label="Start", emoji="▶️",
                       style=discord.ButtonStyle.success, row=0)
    async def start_btn(self, i, b):
        s = bot.court_sessions.get(i.user.id)
        if not s:
            return await i.response.send_message("❌ Pick a role first.",
                                                  ephemeral=True)
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
            await i.response.send_message(
                "🏛️ Court in session (no other participants).")
        await i.channel.send("Begin.")

    @discord.ui.button(label="Change Role", emoji="🎭",
                       style=discord.ButtonStyle.secondary, row=0)
    async def change_btn(self, i, b):
        await i.response.edit_message(content="🏛️ Pick your new role:",
                                       view=CourtRoleView(bot))

    @discord.ui.button(label="End", emoji="🏁",
                       style=discord.ButtonStyle.danger, row=1)
    async def end_btn(self, i, b):
        if i.user.id in bot.court_sessions:
            bot.court_sessions.pop(i.user.id, None)
        await i.response.edit_message(content="🏛️ Court ended.", view=None)


@bot.hybrid_command(name="court",
                    description="🏛️ Court session — button panel")
async def court_cmd(ctx):
    await ctx.send("🏛️ **Pick your role:**", view=CourtRoleView(bot))


# ======================================================================
# UMF
# ======================================================================
class UMFNationCreateModal(discord.ui.Modal,
                            title="🌍 Create your Nation"):
    nation_name = discord.ui.TextInput(
        label="Nation Name",
        placeholder="e.g. The Iron Concord",
        required=True, max_length=60)
    description = discord.ui.TextInput(
        label="Short description (optional)",
        required=False, max_length=300,
        style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id if interaction.guild else None
        name = self.nation_name.value.strip()
        if not name:
            return await interaction.response.send_message(
                "❌ Provide a name.", ephemeral=True)
        if bot.umf_data.nation_exists(guild_id, name):
            return await interaction.response.send_message(
                f"⚠️ **{name}** already exists.", ephemeral=True)
        existing = bot.umf_data.get_user_nation(guild_id, interaction.user.id)
        if existing:
            return await interaction.response.send_message(
                f"❌ You're already in **{existing['name']}**. "
                f"Leave first with `/umf_manage`.", ephemeral=True)
        nation = bot.umf_data.add_nation(guild_id, name, interaction.user.id)
        emb = discord.Embed(title="✅ Nation Created",
                            description=f"**{nation['name']}** now exists.",
                            color=C_OK)
        if self.description.value.strip():
            emb.add_field(name="About",
                          value=self.description.value.strip()[:1000],
                          inline=False)
        await interaction.response.send_message(embed=emb, ephemeral=True)


class UMFNationJoinModal(discord.ui.Modal, title="🌍 Join a Nation"):
    nation_name = discord.ui.TextInput(
        label="Nation Name",
        placeholder="Exact name — use /umf to see the list",
        required=True, max_length=60)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild.id if interaction.guild else None
        name = self.nation_name.value.strip()
        if not bot.umf_data.nation_exists(guild_id, name):
            return await interaction.response.send_message(
                f"❌ **{name}** doesn't exist here. Check `/umf`.",
                ephemeral=True)
        existing = bot.umf_data.get_user_nation(guild_id, interaction.user.id)
        if existing:
            return await interaction.response.send_message(
                f"❌ You're already in **{existing['name']}**.",
                ephemeral=True)
        if bot.umf_data.join_nation(guild_id, name, interaction.user.id):
            nation = bot.umf_data.get_nation(guild_id, name)
            await interaction.response.send_message(
                f"✅ You joined **{nation['name']}**.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ Couldn't join.", ephemeral=True)


class UMFNationManageView(discord.ui.View):
    def __init__(self, uid: int):
        super().__init__(timeout=180)
        self.uid = uid

    @discord.ui.button(label="Leave Nation",
                       style=discord.ButtonStyle.danger, emoji="🚪")
    async def leave_btn(self, i, b):
        if i.user.id != self.uid:
            return await i.response.send_message("❌ Not yours.",
                                                  ephemeral=True)
        gid = i.guild.id if i.guild else None
        nation = bot.umf_data.get_user_nation(gid, i.user.id)
        if not nation:
            return await i.response.send_message("❌ You're not in a nation.",
                                                  ephemeral=True)
        if nation["owner_id"] == i.user.id:
            return await i.response.send_message(
                "❌ Owners can't leave — use **Delete Nation** instead.",
                ephemeral=True)
        if bot.umf_data.leave_nation(gid, nation["name"], i.user.id):
            await i.response.send_message(f"🚪 Left **{nation['name']}**.",
                                           ephemeral=True)
        else:
            await i.response.send_message("❌ Couldn't leave.",
                                           ephemeral=True)

    @discord.ui.button(label="Delete Nation",
                       style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_btn(self, i, b):
        if i.user.id != self.uid:
            return await i.response.send_message("❌ Not yours.",
                                                  ephemeral=True)
        gid = i.guild.id if i.guild else None
        nation = bot.umf_data.get_user_nation(gid, i.user.id)
        if not nation:
            return await i.response.send_message("❌ You're not in a nation.",
                                                  ephemeral=True)
        if nation["owner_id"] != i.user.id:
            return await i.response.send_message(
                "❌ Only the owner can delete.", ephemeral=True)
        if bot.umf_data.delete_nation(gid, nation["name"], i.user.id):
            await i.response.send_message(
                f"🗑️ Deleted **{nation['name']}**.", ephemeral=True)
        else:
            await i.response.send_message("❌ Couldn't delete.",
                                           ephemeral=True)

    @discord.ui.button(label="Members",
                       style=discord.ButtonStyle.secondary, emoji="👥")
    async def members_btn(self, i, b):
        gid = i.guild.id if i.guild else None
        nation = bot.umf_data.get_user_nation(gid, i.user.id)
        if not nation:
            return await i.response.send_message("❌ You're not in a nation.",
                                                  ephemeral=True)
        lines = []
        for uid in nation.get("members", [])[:50]:
            tag = "👑" if uid == nation["owner_id"] else "•"
            lines.append(f"{tag} <@{uid}>")
        emb = discord.Embed(
            title=f"👥 {nation['name']}",
            description="\n".join(lines) or "no members",
            color=C_PRIMARY)
        emb.set_footer(text=f"{len(nation.get('members', []))} members total")
        await i.response.send_message(embed=emb, ephemeral=True)


class UMFAdminPanel(discord.ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=300)
        self.bot = bot_instance

    @discord.ui.button(label="Next Pending",
                       style=discord.ButtonStyle.primary,
                       emoji="📋", row=0)
    async def next_btn(self, i, b):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("⛔ Admin only.",
                                                  ephemeral=True)
        gid = i.guild.id if i.guild else None
        pending = self.bot.umf_data.get_pending_requests(gid)
        if not pending:
            return await i.response.send_message("📭 No pending requests.",
                                                  ephemeral=True)
        req = pending[0]
        try:
            user = (i.guild.get_member(req["user_id"])
                    or await i.guild.fetch_member(req["user_id"]))
        except Exception:
            user = None
        emb = discord.Embed(title="📋 Pending Nation Recognition",
                            color=C_WARM)
        emb.add_field(name="👤 Applicant",
                      value=user.mention if user
                      else f"<@{req['user_id']}>", inline=True)
        emb.add_field(name="🌍 Nation", value=req["nation"], inline=True)
        emb.add_field(name="📅 Submitted",
                      value=datetime.fromisoformat(req["timestamp"])
                      .strftime("%b %d, %H:%M"), inline=True)
        emb.add_field(name="📊 Total Pending", value=str(len(pending)),
                      inline=True)
        await i.response.edit_message(embed=emb,
                                       view=UMFAdminActionView(req, user))

    @discord.ui.button(label="Stats",
                       style=discord.ButtonStyle.secondary,
                       emoji="📊", row=0)
    async def stats_btn(self, i, b):
        gid = i.guild.id if i.guild else None
        st = self.bot.umf_data.get_stats(gid)
        emb = discord.Embed(title="📊 UMF Stats (this server)",
                            color=C_PRIMARY)
        emb.add_field(name="Nations", value=str(st["nations"]), inline=True)
        emb.add_field(name="Members", value=str(st["members_total"]),
                      inline=True)
        emb.add_field(name="Pending", value=str(st["pending"]), inline=True)
        await i.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(label="All Nations",
                       style=discord.ButtonStyle.secondary,
                       emoji="🌍", row=0)
    async def list_btn(self, i, b):
        gid = i.guild.id if i.guild else None
        nations = self.bot.umf_data.list_nations(gid)
        emb = discord.Embed(title="🌍 Nations (this server)", color=C_ACCENT)
        if nations:
            lines = [f"• **{n['name']}** — {len(n.get('members', []))} members "
                     f"(owner <@{n['owner_id']}>)"
                     for n in nations[:25]]
            emb.description = "\n".join(lines)
        else:
            emb.description = "No nations yet."
        await i.response.send_message(embed=emb, ephemeral=True)


class UMFAdminActionView(discord.ui.View):
    def __init__(self, req, user):
        super().__init__(timeout=180)
        self.req = req
        self.user = user

    @discord.ui.button(label="Approve",
                       style=discord.ButtonStyle.success, emoji="✅")
    async def approve_btn(self, i, b):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("⛔ Admin only.",
                                                  ephemeral=True)
        gid = i.guild.id if i.guild else None
        approved = bot.umf_data.approve_request(gid, self.req["user_id"])
        if not approved:
            return await i.response.edit_message(
                content="❌ Already processed.", view=None)
        await i.response.edit_message(
            content=f"✅ Recognition approved for **{approved['nation']}**.",
            view=None)

    @discord.ui.button(label="Deny",
                       style=discord.ButtonStyle.danger, emoji="❌")
    async def deny_btn(self, i, b):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("⛔ Admin only.",
                                                  ephemeral=True)
        gid = i.guild.id if i.guild else None
        bot.umf_data.deny_request(gid, self.req["user_id"], "(denied)")
        await i.response.edit_message(content="❌ Denied.", view=None)

    @discord.ui.button(label="Skip",
                       style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_btn(self, i, b):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message("⛔ Admin only.",
                                                  ephemeral=True)
        await i.response.edit_message(content="⏭️ Skipped.",
                                       view=UMFAdminPanel(bot))


class UMFPrimaryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Create Nation",
                       style=discord.ButtonStyle.primary, emoji="🏛️", row=0)
    async def create_btn(self, i, b):
        existing = bot.umf_data.get_user_nation(
            i.guild.id if i.guild else None, i.user.id)
        if existing:
            return await i.response.send_message(
                f"❌ You're already in **{existing['name']}**.",
                ephemeral=True)
        await i.response.send_modal(UMFNationCreateModal())

    @discord.ui.button(label="Join Nation",
                       style=discord.ButtonStyle.success, emoji="✊", row=0)
    async def join_btn(self, i, b):
        existing = bot.umf_data.get_user_nation(
            i.guild.id if i.guild else None, i.user.id)
        if existing:
            return await i.response.send_message(
                f"❌ You're already in **{existing['name']}**.",
                ephemeral=True)
        await i.response.send_modal(UMFNationJoinModal())

    @discord.ui.button(label="View Nations",
                       style=discord.ButtonStyle.secondary, emoji="🌍", row=0)
    async def list_btn(self, i, b):
        gid = i.guild.id if i.guild else None
        nations = bot.umf_data.list_nations(gid)
        emb = discord.Embed(title="🌍 Nations (this server)", color=C_ACCENT)
        if nations:
            lines = [f"• **{n['name']}** — {len(n.get('members', []))} members "
                     f"(owner <@{n['owner_id']}>)"
                     for n in nations[:25]]
            emb.description = "\n".join(lines)
        else:
            emb.description = ("No nations yet. Be the first — click "
                                "**Create Nation**.")
        await i.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(label="I am an admin",
                       style=discord.ButtonStyle.danger, emoji="🔒", row=1)
    async def admin_btn(self, i, b):
        if not i.user.guild_permissions.administrator:
            return await i.response.send_message(
                "⛔ You don't have admin permissions in this server.",
                ephemeral=True)
        emb = discord.Embed(
            title="🔒 UMF Admin Panel",
            description="Manage pending recognition requests, view stats, "
                        "list nations.",
            color=C_DEEP)
        await i.response.send_message(embed=emb, view=UMFAdminPanel(bot),
                                       ephemeral=True)


def umf_requirements_embed() -> discord.Embed:
    emb = discord.Embed(
        title="🌍 United Military Federation",
        description=("Join or create a nation here. "
                     "Admins handle recognition requests."),
        color=C_PRIMARY)
    emb.add_field(name="🏛️ Create a Nation",
                  value="Found your own nation — you become its owner.",
                  inline=False)
    emb.add_field(name="✊ Join a Nation",
                  value="Join an existing nation as a member.",
                  inline=False)
    emb.add_field(name="🌍 View Nations",
                  value="See every nation in this server.",
                  inline=False)
    emb.add_field(name="🔒 Admin Panel",
                  value="Admins can approve requests and view stats.",
                  inline=False)
    emb.set_footer(text="Server-scoped — each server has its own nations.")
    return emb


@bot.hybrid_command(name="umf", description="🌍 UMF panel — create/join")
async def umf_command(ctx):
    await ctx.send(embed=umf_requirements_embed(), view=UMFPrimaryView())


@bot.hybrid_command(name="umf_join",
                    description="✊ Join an existing nation")
async def umf_join_cmd(ctx):
    existing = bot.umf_data.get_user_nation(
        ctx.guild.id if ctx.guild else None, ctx.author.id)
    if existing:
        return await ctx.send(f"❌ You're already in **{existing['name']}**.",
                              ephemeral=True)
    await ctx.send_modal(UMFNationJoinModal())


@bot.hybrid_command(name="umf_manage",
                    description="🔧 Manage your nation")
async def umf_manage_cmd(ctx):
    gid = ctx.guild.id if ctx.guild else None
    nation = bot.umf_data.get_user_nation(gid, ctx.author.id)
    if not nation:
        return await ctx.send("❌ You're not in a nation. Use `/umf`.",
                              ephemeral=True)
    emb = discord.Embed(title=f"🔧 Managing — {nation['name']}",
                        color=C_PRIMARY)
    emb.add_field(name="Role",
                  value="👑 Owner" if nation["owner_id"] == ctx.author.id
                  else "Member", inline=True)
    emb.add_field(name="Members",
                  value=str(len(nation.get("members", []))), inline=True)
    emb.set_footer(text="Use the buttons below to act")
    await ctx.send(embed=emb, view=UMFNationManageView(ctx.author.id),
                   ephemeral=True)


# ======================================================================
# HELPERS USED BY on_message
# ======================================================================
async def _collect_media_for_vision(message: discord.Message,
                                     reply_msg: Optional[discord.Message] = None,
                                     max_total: int = MAX_IMAGES_PER_MSG
                                     ) -> List[Tuple[bytes, str]]:
    """
    Gather every image/gif/video from the message, its reply chain, and
    any Discord embeds. Frames are extracted from animated media.
    Returns a flat list of (bytes, mime) ready for vision APIs.
    """
    raw_candidates: List[Tuple[bytes, str]] = []

    async def _try_url(url: str, hint_ct: Optional[str] = None):
        if not url:
            return
        try:
            fetched = await read_media_from_url(url)
            if fetched:
                raw_candidates.append(fetched)
            elif hint_ct and hint_ct.startswith(("image/", "video/")):
                async with shared_session() as s:
                    async with s.get(url, headers=_BROWSER_HEADERS,
                                     timeout=aiohttp.ClientTimeout(total=15)) as r:
                        if r.status == 200:
                            raw_candidates.append(
                                (await r.read(), hint_ct.split(";")[0]))
        except Exception:
            pass

    # 1. Message attachments
    for att in message.attachments:
        ct = (att.content_type or "").lower()
        if ct.startswith(("image/", "video/")):
            try:
                async with shared_session() as s:
                    async with s.get(att.url, headers=_BROWSER_HEADERS,
                                     timeout=aiohttp.ClientTimeout(total=20)) as r:
                        if r.status == 200:
                            raw_candidates.append(
                                (await r.read(), ct.split(";")[0]))
            except Exception as e:
                logger.warning(f"Attachment fetch: {e}")

    # 2. Reply chain attachments
    if reply_msg is not None:
        for att in reply_msg.attachments:
            ct = (att.content_type or "").lower()
            if ct.startswith(("image/", "video/")):
                try:
                    async with shared_session() as s:
                        async with s.get(att.url, headers=_BROWSER_HEADERS,
                                         timeout=aiohttp.ClientTimeout(total=20)) as r:
                            if r.status == 200:
                                raw_candidates.append(
                                    (await r.read(), ct.split(";")[0]))
                except Exception as e:
                    logger.warning(f"Reply attachment fetch: {e}")

    # 3. Message embeds
    for embed in (message.embeds or []):
        for attr in ("image", "video", "thumbnail"):
            obj = getattr(embed, attr, None)
            u = getattr(obj, "url", None) if obj else None
            if u:
                await _try_url(u)

    # 4. Reply chain embeds
    if reply_msg is not None:
        for embed in (reply_msg.embeds or []):
            for attr in ("image", "video", "thumbnail"):
                obj = getattr(embed, attr, None)
                u = getattr(obj, "url", None) if obj else None
                if u:
                    await _try_url(u)

    # 5. Klipy/Tenor/Giphy URLs in text
    for m in _GIF_URL_RE.finditer(message.content or ""):
        await _try_url(m.group(0))

    # Extract frames for animated media
    out: List[Tuple[bytes, str]] = []
    for raw, mime in raw_candidates:
        if len(out) >= max_total:
            break
        frames = await extract_media_frames(raw, mime)
        for f in frames:
            if len(out) >= max_total:
                break
            out.append(f)

    return out


async def _do_generate_image(channel, uid: int, prompt: str):
    status = await safe_send(channel, content="🎨 Generating image…")
    try:
        safe, reason = await bot.is_prompt_safe(prompt, uid=uid)
        if not safe:
            return await safe_edit(status, content=f"🚫 **Blocked.** {reason}")
        chosen = bot.current_image_mode
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
        await safe_edit(status, content=None, embed=emb)
    except Exception as e:
        await safe_edit(status, content=f"❌ `{str(e)[:180]}`")


async def _do_generate_tts(channel, uid: int, text: str,
                            voice_key: Optional[str] = None):
    try:
        clean = strip_for_tts(text)
        if not clean:
            return await safe_send(channel, content="❌ Nothing to say.")
        audio = await bot.generate_voice(clean, uid=uid,
                                          voice_key=voice_key, fmt="opus")
        vk = voice_key or bot.default_voice(uid)
        meta = bot.all_voices(uid).get(vk) or {"emoji": "🎙️", "desc": "voice"}
        try:
            f = discord.File(io.BytesIO(audio), filename="voice-message.ogg")
            await channel.send(file=f,
                               flags=discord.MessageFlags(is_voice_message=True))
        except Exception:
            f2 = discord.File(io.BytesIO(audio), filename="voice.mp3")
            await safe_send(
                channel,
                content=f"{meta.get('emoji', '🎙️')} "
                        f"**{meta.get('desc', 'voice')}**",
                file=f2)
    except Exception as e:
        await safe_send(channel, content=f"❌ TTS error: {str(e)[:180]}")


async def _do_generate_video(channel, uid: int, prompt: str):
    status = await safe_send(channel,
                             content=f"🎬 Starting video: **{prompt}**…")
    bot.loop.create_task(bot.generate_video(prompt, uid, status))


async def _do_search_and_summarize(channel, uid: int, query: str,
                                    bot_instance=None):
    status = await safe_send(channel, content=f"🌐 Searching: **{query}**…")
    results = await perform_web_search(query)
    if results.startswith("No results"):
        return await safe_edit(status, content=f"❌ No results for: {query}")
    augmented = (f"Web results for: {query}\n\n{results}\n\n---\n\n"
                 f"Summarize. Cite sources inline like [1], [2].")
    bot_ref = bot_instance or bot
    response = await bot_ref.chat_call(augmented, uid=uid, max_tokens=800)
    response = strip_think_tags(response)
    if len(response) <= DISCORD_LIMIT:
        await safe_edit(status, content=response)
    else:
        try:
            await status.delete()
        except discord.HTTPException:
            pass
        await send_long(channel, response)


# ======================================================================
# ON_MESSAGE — auto-reads any attached/replied media
# ======================================================================
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

    now = time.time()
    if now - bot.user_cooldowns.get(message.author.id, 0) < USER_COOLDOWN_SECONDS:
        await bot.process_commands(message)
        return
    bot.user_cooldowns[message.author.id] = now

    clean = re.sub(r'<@!?{}>\s*'.format(bot.user.id), '', content).strip()

    # Resolve reply chain
    reply_context = None
    reply_msg: Optional[discord.Message] = None
    if message.reference:
        resolved = message.reference.resolved
        if resolved is None:
            try:
                resolved = await message.channel.fetch_message(
                    message.reference.message_id)
            except (discord.NotFound, discord.Forbidden,
                    discord.HTTPException):
                resolved = None
        if isinstance(resolved, discord.Message):
            reply_msg = resolved
            if resolved.author.id != bot.user.id:
                reply_context = {
                    "author": resolved.author.display_name,
                    "content": (resolved.content or "[no text]")[:800],
                    "author_id": resolved.author.id,
                }

    # ---------- 1. IMAGE EDIT INTERCEPT ----------
    try:
        if _looks_like_image_edit(clean or content):
            has_attach = any(
                (a.content_type or "").startswith(("image/", "video/"))
                for a in message.attachments)
            reply_atts = reply_msg.attachments if reply_msg else []
            has_reply_media = any(
                (a.content_type or "").startswith(("image/", "video/"))
                for a in reply_atts)
            has_embed_media = bool(_collect_media_urls_from_message(message))
            reply_embed_media = bool(
                _collect_media_urls_from_message(reply_msg)) if reply_msg else False

            if has_attach or has_reply_media or has_embed_media or reply_embed_media:
                edited_url = await bot.try_image_edit(
                    message, clean or content, message.author.id)
                if edited_url:
                    _commands_served += 1
                    emb = discord.Embed(title="🎨 Image edited",
                                         color=C_PRIMARY)
                    emb.set_image(url=edited_url)
                    emb.set_footer(
                        text=f"By {message.author.display_name}")
                    try:
                        await message.channel.send(embed=emb)
                    except discord.HTTPException:
                        await safe_send(message.channel, content=edited_url)
                    await bot.process_commands(message)
                    return
    except Exception as e:
        logger.warning(f"Image edit check failed: {e}")

    # ---------- 2. NATURAL LANGUAGE GENERATION FAST-PATH ----------
    gen_intent = _parse_gen_intent(clean)
    if gen_intent:
        kind, g_arg = gen_intent
        _commands_served += 1
        if kind == "image":
            await _do_generate_image(message.channel, message.author.id, g_arg)
        elif kind == "tts":
            voice_key = None
            text = g_arg
            if "|" in g_arg:
                v, t = g_arg.split("|", 1)
                voice_key = resolve_voice(v.strip(), message.author.id, bot)
                text = t.strip()
            await _do_generate_tts(message.channel, message.author.id, text,
                                    voice_key=voice_key)
        elif kind == "video":
            await _do_generate_video(message.channel, message.author.id,
                                      g_arg)
        await bot.process_commands(message)
        return

    # ---------- 3. COLLECT MEDIA (auto-read any image/GIF/video) ----------
    images: List[Tuple[bytes, str]] = []
    try:
        images = await _collect_media_for_vision(message, reply_msg)
    except Exception as e:
        logger.warning(f"Media collect failed: {e}")
        images = []

    # ---------- 4. DEFAULT PROMPT IF NO TEXT ----------
    if not clean:
        if images:
            clean = "what's in this?"
        elif reply_context:
            clean = "what do you think of this?"
        else:
            await bot.process_commands(message)
            return

    logger.info(f"Message from {message.author} in "
                f"#{getattr(message.channel, 'name', 'DM')}: "
                f"{clean[:100]!r} | images={len(images)}")

    _commands_served += 1
    try:
        await bot.process_user_message(
            message.author, clean, message.channel,
            reply_context=reply_context, trigger_msg=message,
            images=images, source_message=message)
    except Exception as e:
        logger.error(f"process_user_message failed: {e}", exc_info=True)

    await bot.process_commands(message)


# ======================================================================
# WEB SERVER
# ======================================================================
async def handle_root(request):
    return web.Response(text="🔥 Mac v26.0 is running")


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
