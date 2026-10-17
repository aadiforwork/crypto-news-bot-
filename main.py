#!/usr/bin/env python3
"""
Crypto AI News Bot - Event-driven Telegram bot that monitors Crypto RSS feeds + Forex Factory Macro Calendar,
filters via FREE LLM (Gemini / Groq / OpenRouter), and sends Hinglish alerts to Telegram.

Usage:
    python main.py              # Normal mode (requires LLM_API_KEY)
    python main.py --dry-run    # Test mode (no API keys needed, prints to console)
    python main.py --once       # Run one cycle and exit (good for cron)

FREE LLM Providers (no credit card needed):
    1. Google Gemini API (gemini-3.5-flash-lite) - FREE tier
       Get key: https://aistudio.google.com/apikey
    
    2. Groq API (openai/gpt-oss-20b) - FREE tier, very fast
       Get key: https://console.groq.com/keys
    
    3. OpenRouter (meta/muse-spark-1.3) - Needs credits but extremely cheap
       Get key: https://openrouter.ai/keys

Set LLM_PROVIDER in .env: gemini | groq | openrouter
"""

import os
import sys
import time
import json
import logging
import requests
import feedparser
import hashlib
import argparse
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Set, List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Parse command line arguments
parser = argparse.ArgumentParser(description="Crypto AI News Bot")
parser.add_argument("--dry-run", action="store_true", help="Test mode: fetch + analyze + print (no API keys needed)")
parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit")
parser.add_argument("--local", action="store_true", help="Local mode: keyword-based Hinglish analysis + REAL Telegram sending (no LLM API needed)")
parser.add_argument("--digest", action="store_true", help="Digest mode: post BIG HEADLINE of last 24h (runs once daily)")
args = parser.parse_args()

DRY_RUN = args.dry_run
RUN_ONCE = args.once
LOCAL_MODE = args.local
DIGEST_MODE = args.digest

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# LLM Provider Selection: ollama | gemini | groq | openrouter
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()

# API Keys (set the one for your chosen provider)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Ollama Configuration (FREE, LOCAL, NO ACCOUNT NEEDED)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

# Model selection per provider
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "meta/muse-spark-1.3")

# API Endpoints
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage" if TELEGRAM_BOT_TOKEN else ""
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# WhatsApp Alerts (FREE via CallMeBot - optional, Telegram stays primary)
# Setup: phone me CallMeBot number save karo, usko WhatsApp pe
# "I allow callmebot to send me messages" bhejo, apikey milega.
WHATSAPP_ENABLED = os.getenv("WHATSAPP_ENABLED", "false").lower() in ("1", "true", "yes")
WHATSAPP_PHONE = os.getenv("WHATSAPP_PHONE", "")      # e.g. 919876543210 (country code + number, bina + ke)
# Provider: "callmebot" (free, aasaan) ya "cloudapi" (official Meta API)
WHATSAPP_PROVIDER = os.getenv("WHATSAPP_PROVIDER", "callmebot").lower()
WHATSAPP_APIKEY = os.getenv("WHATSAPP_APIKEY", "")    # CallMeBot se mila apikey
# Official Meta WhatsApp Cloud API (developers.facebook.com se):
WHATSAPP_CLOUD_TOKEN = os.getenv("WHATSAPP_CLOUD_TOKEN", "")        # access token
WHATSAPP_CLOUD_PHONE_ID = os.getenv("WHATSAPP_CLOUD_PHONE_ID", "")  # test number ka Phone Number ID

# Instant phone push via ntfy.sh (FREE, no signup, no stranger numbers, no business account)
# Sirf app install + topic subscribe. Telegram jaisa instant notification phone pe.
NTFY_ENABLED = os.getenv("NTFY_ENABLED", "false").lower() in ("1", "true", "yes")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")  # secret sa topic naam, e.g. crypto-aadi-x7k2p9

# RSS Feed Sources - ONLY top-tier genuine outlets (no clickbait / spam feeds)
CRYPTO_RSS_FEEDS = [
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss"},
    {"name": "CoinTelegraph", "url": "https://cointelegraph.com/rss"},
    {"name": "The Block", "url": "https://www.theblock.co/rss.xml"},
    {"name": "Decrypt", "url": "https://decrypt.co/feed"},
    {"name": "BitcoinMag", "url": "https://bitcoinmagazine.com/feed"},
    {"name": "CryptoBriefing", "url": "https://cryptobriefing.com/feed/"},
    {"name": "BitcoinCom", "url": "https://news.bitcoin.com/feed/"},
]

# Forex Factory Economic Calendar (High-Impact USD events only)
# Using a reliable public calendar feed - Forex Factory doesn't have official RSS,
# so we use a trusted alternative: investing.com or similar public calendar
FOREX_FACTORY_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# High-Impact USD Event Keywords (strict filtering)
HIGH_IMPACT_USD_EVENTS = [
    "FOMC", "Federal Reserve", "Fed Rate", "Interest Rate Decision",
    "CPI", "Core CPI", "Inflation Rate",
    "Non-Farm Payrolls", "NFP", "Unemployment Rate", "Employment Change",
    "GDP", "Gross Domestic Product",
    "PCE Price Index", "Core PCE",
    "Retail Sales", "Core Retail Sales",
    "ISM Manufacturing", "ISM Services", "PMI",
    "Consumer Confidence", "Michigan Sentiment",
    "Durable Goods Orders",
    "Trade Balance",
    "Initial Jobless Claims",
    "JOLTS", "Job Openings",
]

# Model Configuration - Read from .env, with defaults
# Options:
#   FREE (but slow/unreliable): 
#     - liquid/lfm-2.5-2.6b:free
#     - nvidia/nemotron-3.5-lightning:free
#     - nvidia/nemotron-3-ultra:free
#   PAID (cheap, reliable, excellent Hinglish):
#     - meta/muse-spark-1.3          (~$0.001/1M tokens) ← RECOMMENDED for Hinglish
#     - meta/muse-glimmer-30b        (~$0.0003/1M tokens)
#     - openai/gpt-4o-mini           (~$0.15/1M tokens)
#     - google/gemini-2.5-flash      (~$0.30/1M tokens)
#     - nvidia/nemotron-3-ultra      (~$0.60/1M tokens)
MODEL_NAME = os.getenv("OPENROUTER_MODEL", "meta/muse-spark-1.3")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "120"))  # seconds (2 minutes - respectful to free RSS feeds)

# Logging setup - ASCII-safe for Windows console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# File logging - ALWAYS active (Task Scheduler / pythonw has no console, so
# without this all logs would vanish and deaths would leave zero trace).
try:
    _LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "bot.log")
    os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
    _file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    _file_handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logging.getLogger().addHandler(_file_handler)
except Exception as _log_err:
    logger.warning(f"Could not set up file logging: {_log_err}")

# ASCII-safe log prefixes
LOG_BOT = "[BOT]"
LOG_RSS = "[RSS]"
LOG_MACRO = "[MACRO]"
LOG_AI = "[AI]"
LOG_SKIP = "[SKIP]"
LOG_SENT = "[SENT]"
LOG_CLEAN = "[CLEAN]"
LOG_ERR = "[ERR]"
LOG_WARN = "[WARN]"

# In-memory set for processed item hashes (URL-based deduplication)
processed_hashes: Set[str] = set()

# Story fingerprints already alerted (same story from different feeds = send once)
processed_stories: List[frozenset] = []

# Cache for macro events to avoid re-sending same calendar events
# (persisted to processed.json so restarts don't cause duplicate macro alerts)
macro_event_cache: Dict[str, datetime] = {}

# Throttle for calendar HTTP downloads (faireconomy rate-limits aggressive polling -> 429).
# Raw JSON is cached here; the time-window filter is re-applied on every cycle.
_MACRO_HTTP_CACHE: Dict[str, Any] = {"at": None, "events": []}
MACRO_FETCH_INTERVAL = int(os.getenv("MACRO_FETCH_INTERVAL", "3600"))  # seconds between calendar downloads

# Persistent storage file for processed hashes (survives restarts)
PROCESSED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed.json")

# Last date (IST) on which the daily digest was posted (prevents double-posts)
LAST_DIGEST = ""


def load_processed_hashes() -> None:
    """Load previously processed hashes + story fingerprints from disk."""
    global processed_hashes, processed_stories, LAST_DIGEST, macro_event_cache
    try:
        if os.path.exists(PROCESSED_FILE):
            with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # Old format: plain hash list
                    processed_hashes = set(data)
                    logger.info(f"{LOG_BOT} Loaded {len(processed_hashes)} processed hashes from disk")
                elif isinstance(data, dict):
                    # New format: hashes + story fingerprints
                    processed_hashes = set(data.get("hashes", []))
                    processed_stories = [frozenset(s) for s in data.get("stories", [])]
                    LAST_DIGEST = data.get("last_digest", "")
                    # Macro cache (ISO timestamps) - survives restarts, prevents duplicate macro alerts
                    macro_event_cache = {}
                    for k, v in (data.get("macro_cache", {}) or {}).items():
                        try:
                            dt = datetime.fromisoformat(v)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            macro_event_cache[k] = dt
                        except (ValueError, TypeError):
                            continue
                    logger.info(f"{LOG_BOT} Loaded {len(processed_hashes)} hashes + {len(processed_stories)} stories + {len(macro_event_cache)} macro events from disk")
    except Exception as e:
        logger.warning(f"Could not load processed hashes: {e}")


def save_processed_hashes() -> None:
    """Save processed hashes + story fingerprints to disk."""
    try:
        with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "hashes": sorted(processed_hashes),
                "stories": [sorted(s) for s in processed_stories[-2000:]],
                "last_digest": LAST_DIGEST,
                "macro_cache": {k: v.isoformat() for k, v in macro_event_cache.items()}
            }, f)
    except Exception as e:
        logger.warning(f"Could not save processed hashes: {e}")


def is_duplicate_story(fp: frozenset) -> bool:
    """Check if this headline covers an already-alerted story (any feed)."""
    for old_fp in processed_stories:
        if same_story(fp, old_fp):
            return True
    return False


# ==================== MOCK LLM (for --dry-run) ====================
def _word_match(text: str, keyword: str) -> bool:
    """Match keyword with word boundaries (avoids 'act' matching 'impact', 'bill' matching 'billion')."""
    import re
    pattern = r"\b" + re.escape(keyword.strip()) + r"\b"
    return re.search(pattern, text) is not None


# Words proving the news is actually about crypto (not AI/politics/sports).
# Non-Macro alerts MUST contain at least one of these, else SKIP.
# Includes coins, companies AND crypto people (so "Trump won't pardon SBF" passes,
# but "Trump declares energy ceasefire" is still blocked).
CRYPTO_GATE_WORDS = [
    "bitcoin", "btc", "crypto", "cryptocurrency", "cryptocurrencies",
    "ethereum", "eth", "blockchain", "defi", "nft", "nfts", "web3",
    "stablecoin", "stablecoins", "token", "tokens", "tokenized",
    "digital asset", "digital assets", "coinbase", "binance", "kraken",
    "xrp", "ripple", "solana", "sol", "dogecoin", "doge", "cardano", "ada",
    "zcash", "zec", "bnb", "chainlink", "link", "avalanche", "avax",
    "polkadot", "dot", "polygon", "matic", "arbitrum", "arb", "optimism",
    "near", "aptos", "apt", "sui", "tron", "trx", "litecoin", "ltc",
    "altcoin", "altcoins", "satoshi", "mining", "miner", "miners",
    "wallet", "wallets", "ledger", "memecoin", "memecoins",
    "on-chain", "onchain", "tether", "usdt", "usdc", "etf", "celsius",
    "saylor", "sbf", "bankman-fried", "cz", "zhao", "vitalik", "buterin",
    "musk", "hoskinson", "armstrong", "garlinghouse",
]

# Common noise words ignored when comparing two headlines for same-story detection.
TITLE_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "as", "at", "by", "from", "is", "are", "was", "be", "has", "have",
    "says", "say", "new", "over", "after", "ahead", "amid", "vs",
}


def title_fingerprint(title: str) -> frozenset:
    """Extract significant words from a headline for same-story detection."""
    import re
    words = re.findall(r"[a-z0-9]+", title.lower())
    return frozenset(w for w in words if len(w) >= 4 and w not in TITLE_STOPWORDS)


def same_story(fp1: frozenset, fp2: frozenset) -> bool:
    """Two headlines cover the same story if they share enough significant words."""
    if not fp1 or not fp2:
        return False
    overlap = len(fp1 & fp2)
    smaller = min(len(fp1), len(fp2))
    return overlap >= 4 and (overlap / smaller) >= 0.4


def mock_analyze_with_llm(title: str, description: str, source: str) -> Optional[Dict[str, Any]]:
    """
    Simulated LLM analysis for dry-run mode.
    Uses STRICT word-boundary keyword matching to simulate filtering logic.
    Only genuine high-impact events pass.
    """
    text = f"{title} {description}".lower()
    title_text = title.lower()
    
    # SKIP rules - minor/junk content
    # NOTE: bare "to $" removed (it false-matched "tied to $14 billion").
    # Price targets are caught by PRICE_TARGET_RE below instead.
    skip_keywords = [
        "price prediction", "price forecast", "price target", "technical analysis", "price analysis",
        "hodl",
        "partnership", "collaboration", "webinar",
        "conference", "summit", "sponsored", "promo", "giveaway",
        "listing", "delisting", "airdrop", "presale",
        "mining difficulty", "hashrate", "governance proposal",
        "educational", "tutorial", "how to", "what is",
        "opinion piece", "op-ed", "editorial", "hackathon", "meetup", "workshop",
        "job opening", "hiring", "career", "funding round",
        "seed round", "series a", "series b", "raises $", "sweepstakes",
        # Roundups & sentiment commentary (not breaking events)
        "what happened", "roundup", "recap", "digest",
        "fear and greed", "fear & greed", "greed index",
        "week ahead", "week in crypto", "today in crypto",
        "morning minute", "market watch",
        # Testnet launches are not market-moving
        "testnet",
        # Interviews, videos & podcasts are commentary, not breaking events
        "interview", "podcast",
    ]
    
    # Single common words needing word-boundaries
    # (avoids "ama" matching "Cayman", "moon" matching "MoonPay",
    #  "guide" matching "guidance", "ico" matching "icon")
    skip_words_strict = ["ama", "ico", "moon", "guide"]
    
    # Price-target headlines like "Bitcoin to $100k", "takes it to $1M"
    # (not "tied to $14 billion" - spelled-out amounts don't match)
    import re as _re
    PRICE_TARGET_RE = _re.compile(r"\bto \$\d[\d,.]*[kmb]\b")
    
    if any(kw in text for kw in skip_keywords):
        return None  # SKIP
    if any(_word_match(text, w) for w in skip_words_strict):
        return None  # SKIP
    if PRICE_TARGET_RE.search(text):
        return None  # SKIP - price target clickbait
    
    # HIGH IMPACT detection - STRICT word-boundary matching
    # (prevents "act" matching "impact", "bill" matching "billion", etc.)
    high_impact = {
        "ETF": ["etf", "etfs", "exchange traded fund"],
        "Hack": ["hack", "hacked", "hacker", "hackers", "attack", "exploit", "exploited",
                 "drained", "drain", "stolen", "theft", "heist", "vulnerability",
                 "breach", "phishing", "unauthorized",
                 "insolvency", "insolvent", "bankruptcy", "bankrupt",
                 "halt withdrawals", "suspend withdrawals", "frozen funds",
                 "ransom", "laundering", "laundered"],
        "Regulation": ["sec", "cftc", "regulation", "regulator", "regulators", "regulatory",
                       "legislation", "bill", "act", "mica", "lawmaker", "lawmakers",
                       "senate", "congress", "parliament",
                       "lawsuit", "sued", "sues", "sue", "settlement", "enforcement",
                       "crackdown", "sanction", "sanctions", "freeze", "freezes", "frozen",
                       "indictment", "charged", "charges", "guilty", "jailed", "prison",
                       "fraud", "scam", "scams", "celsius",
                       "ban", "banned", "bans", "seize", "seized", "seizure",
                       "license", "licensed", "licence",
                       "tax", "taxes", "taxation", "stablecoin", "stablecoins",
                       "attorney"],
        "Macro": ["fomc", "federal reserve", "fed rate", "interest rate", "rate cut", "rate hike",
                  "cpi", "inflation", "non-farm", "nfp", "payrolls", "unemployment",
                  "gdp", "pce", "retail sales", "ism", "pmi", "jobless claims", "jolts",
                  "tariff", "tariffs", "powell"],
        "Influencer": ["trump", "white house", "elon musk", "musk", "gensler", "sbf", "bankman-fried",
                       "cz", "zhao", "vitalik", "buterin", "saylor", "yellen", "bessent"],
        "Whale": ["whale", "whales", "microstrategy", "strategy", "tesla", "blackrock",
                  "etf inflow", "etf inflows", "etf outflow", "etf outflows",
                  "record inflow", "record outflows", "accumulate", "accumulation"],
        "Protocol": ["upgrade", "upgraded", "fork", "hard fork", "merge", "mainnet",
                     "bug", "bugs", "patch", "patched",
                     "shapella", "dencun", "pectra", "halving", "eip-"],
    }
    
    # TITLE-FIRST detection: title is the concise signal, description is fallback.
    # This prevents description noise from miscategorizing the news.
    detected_category = None
    for cat, keywords in high_impact.items():
        if any(_word_match(title_text, kw) for kw in keywords):
            detected_category = cat
            break
    
    # Fallback to full text only if title gives no signal
    if not detected_category:
        for cat, keywords in high_impact.items():
            if any(_word_match(text, kw) for kw in keywords):
                detected_category = cat
                break
    
    if not detected_category:
        return None  # SKIP - not high impact
    
    # CRYPTO-RELEVANCE GATE: non-Macro news must actually be about crypto.
    # (Blocks AI/politics/sports stories that happen to contain regulation words.)
    if detected_category != "Macro":
        if not any(_word_match(text, kw) for kw in CRYPTO_GATE_WORDS):
            return None  # SKIP - not crypto-related
    
    # Generate Hinglish headline - NEWS-SPECIFIC (never fixed template).
    # Each alert must be distinguishable: headline is derived from THIS title.
    CATEGORY_ACTION = {
        "ETF": "ETF update!",
        "Regulation": "regulation update!",
        "Hack": "hack alert!",
        "Macro": "macro update!",
        "Influencer": "bada bayan!",
        "Whale": "whale move!",
        "Protocol": "upgrade update!",
    }
    action = CATEGORY_ACTION.get(detected_category, "badi khabar!")
    # Core = first clause of the real title (keeps entity names like ENS / Sberbank)
    core = title.split(" - ")[0].split(" | ")[0].split(":")[0].strip()
    if len(core) > 40:
        core = core[:37].rsplit(" ", 1)[0]  # cut at word boundary
    headline = f"{core} - {action}"
    if len(headline) > 60:
        headline = headline[:57] + "..."

    # Generate summary bullets - NEWS-SPECIFIC (from THIS title + description).
    # Bullet 1 = what happened (title), Bullet 2 = key detail (description),
    # Bullet 3 = market impact tied to this story. Never generic fixed lines.
    import re as _re2
    clean_desc = _re.sub(r"\s+", " ", description).strip()
    # First 1-2 meaningful sentences from the actual description
    sentences = [s.strip() for s in _re2.split(r"(?<=[.!?])\s+", clean_desc) if len(s.strip()) > 25]
    detail = " ".join(sentences[:2]).strip()
    if len(detail) > 180:
        detail = detail[:177].rsplit(" ", 1)[0] + "..."
    title_short = title.strip()
    if len(title_short) > 140:
        title_short = title_short[:137].rsplit(" ", 1)[0] + "..."

    CATEGORY_IMPACT_LINE = {
        "ETF": "Isse liquidity/inflows badh sakte hain - price pe nazar rakho",
        "Regulation": "Isse compliance/market access badlega - traders savdhaan rahein",
        "Hack": "Isse panic selling ho sakti hai - apni holdings check karo",
        "Macro": "Isse USD liquidity badlegi - crypto volatility badhegi",
        "Influencer": "Isse sentiment jaldi badal sakta hai - volatility ready rakho",
        "Whale": "Isse short-term price pressure aayega - levels dekho",
        "Protocol": "Isse network use/fees badlenge - related coin pe asar",
    }
    impact_line = CATEGORY_IMPACT_LINE.get(detected_category, "Volatility badh sakti hai - positions review karo")

    if detail:
        summary = [
            f"Kya hua: {title_short}",
            f"Detail: {detail} ({source} ne report kiya)",
            f"Asar: {impact_line}",
        ]
    else:
        summary = [
            f"Kya hua: {title_short}",
            f"Source: {source} ne report kiya - details aa rahi hain",
            f"Asar: {impact_line}",
        ]
    
    impact = "HIGH" if detected_category in ["ETF", "Regulation", "Hack", "Macro", "Influencer"] else "MEDIUM"
    
    return {
        "category": detected_category,
        "headline": headline,
        "summary": summary,
        "impact": impact,
        "source_name": source
    }


# ==================== LLM SYSTEM PROMPT ====================
SYSTEM_PROMPT = """You are a Crypto Market Intelligence Analyst. Your job is to filter noise and identify ONLY high-impact, market-moving crypto news.

STRICT FILTERING RULES:
1. CRYPTO-ONLY: Accept ONLY news directly related to:
   - Cryptocurrency, Web3, Blockchain, DeFi, NFTs
   - Macro economics impacting Bitcoin/Crypto (Fed rates, inflation, USD)
   - Crypto Regulation (SEC, CFTC, Global regulators)
   - US crypto politics (Congress bills, White House crypto orders/policy)
   - Indian govt crypto moves (RBI, Finance Ministry, FIU-IND, crypto tax, CBDC)
   - Major Exchange news (Binance, Coinbase, Kraken, etc.)

2. HIGH-IMPACT ONLY: Accept ONLY events that MOVE MARKETS:
   ✅ ETF approvals/rejections/flows
   ✅ Exchange hacks, insolvency, major outages
   ✅ Government regulation/legislation (MiCA, US bills, CBDC)
   ✅ US Congress crypto bills, White House crypto policy/orders
   ✅ Indian govt: RBI digital rupee/CBDC, crypto tax changes, FIU/exchange action
   ✅ Fed rate decisions, CPI, major macro data
   ✅ High-profile tweets: Trump, Musk, SEC Chair, Powell, SBF, CZ, Vitalik
   ✅ Trump / White House / Fed statements WITH market mechanism
      (tariffs, rate pressure, dollar, crypto policy, BTC reserve, taxes on crypto).
      Pure election-campaign promises with NO market mechanism (rally speeches,
      vote appeals, "pocket me paise" claims) = SKIP.
   ✅ Major protocol upgrades/forks/exploits ($100M+)
   ✅ Whale movements ($50M+), institutional adoption
   ✅ Stablecoin depegs, major liquidations

3. REJECT (reply with exactly this JSON and nothing else: {"response": "SKIP"}):
   ❌ Price predictions, technical analysis, "Bitcoin to $100k"
   ❌ Minor altcoin pumps/dumps (< $50M volume)
   ❌ Routine exchange listings/delistings
   ❌ Generic "adoption" articles, partnerships
   ❌ Opinion pieces, educational content
   ❌ Conference announcements, AMAs
   ❌ Promo/sponsored content
   ❌ Mining difficulty adjustments
   ❌ Minor governance proposals

4. OUTPUT FORMAT (if valid):
   Write in SIMPLE, NATURAL ROMAN HINGLISH (Hindi in English script, easy to read on mobile).
   Use simple words like: "sarkar" not "government", "paise" not "funds", "bada" not "major", "market" not "marketplace".
   Example style: "ETF approve hua - market khush!", "Sarkar ne naye rules banaye - crypto pe asar!"
   CRITICAL: headline + summary MUST be specific to THIS news (names, numbers, coin, company from Title/Description). NEVER reuse fixed generic lines for a category. Two different news MUST get different summaries.
   BAD (generic template - NEVER do this): Title Solana Alpenglow Oct 21 150ms -> headline Protocol upgrade hua - naye features aaye = REJECT. GOOD: headline names Solana/Alpenglow/150ms/Oct 21.
   BAD (copy-paste - NEVER do this): Coins.ph central-bank action and SkyAI SOL-dollar100 SEC risk must NOT share identical headline and bullets. Each names its own entity.
   Return ONLY this JSON structure:
   {
     "category": "ETF/Regulation/Hack/Macro/Whale/Protocol/Influencer",
     "headline": "News-specific Hinglish headline (max 60 chars, include key entity from title)",
     "summary": ["Point 1: kya hua in THIS news (names/numbers)", "Point 2: key detail from THIS description", "Point 3: is khabar ka market pe asar"],
     "impact": "HIGH" or "MEDIUM",
     "source_name": "Source name from input"
   }

Be ruthless. If unsure, reply {"response": "SKIP"}."""


def validate_env() -> bool:
    """Validate all required environment variables are set."""
    if DRY_RUN:
        logger.info(f"{LOG_BOT} DRY-RUN MODE: Skipping API key validation")
        return True
    
    if LOCAL_MODE:
        logger.info(f"{LOG_BOT} LOCAL MODE: Using keyword-based analysis (no LLM API needed)")
        required_telegram = {
            "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
            "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID
        }
        missing = [k for k, v in required_telegram.items() if not v]
        if missing:
            logger.error(f"Missing environment variables: {', '.join(missing)}")
            return False
        return True
    
    # Check Telegram keys (always required)
    required_telegram = {
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID
    }
    
    # Check LLM provider key
    llm_keys = {
        "gemini": ("GEMINI_API_KEY", GEMINI_API_KEY),
        "groq": ("GROQ_API_KEY", GROQ_API_KEY),
        "openrouter": ("OPENROUTER_API_KEY", OPENROUTER_API_KEY)
    }
    
    missing = [k for k, v in required_telegram.items() if not v]
    
    llm_key_name, llm_key_value = llm_keys.get(LLM_PROVIDER, (None, None))
    if not llm_key_value:
        missing.append(f"{llm_key_name} (for {LLM_PROVIDER})")
    
    if missing:
        logger.error(f"Missing environment variables: {', '.join(missing)}")
        logger.error(f"LLM Provider: {LLM_PROVIDER}")
        return False
    return True


def generate_item_hash(title: str, url: str) -> str:
    """Generate unique hash for deduplication based on title + URL."""
    content = f"{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.md5(content.encode()).hexdigest()[:16]


def fetch_rss_feed(feed_info: Dict[str, str], since_hours: Optional[float] = None) -> List[Dict[str, Any]]:
    """Fetch and parse a single RSS feed. ONLY today's news (strict current-date filter).
    If since_hours is set, accept items published within the last N hours instead."""
    name = feed_info["name"]
    url = feed_info["url"]
    items = []
    skipped_old = 0

    # Current date (local) - only news published TODAY is accepted
    today = datetime.now().date()
    cutoff = None
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    
    try:
        logger.debug(f"Fetching RSS: {name} - {url}")
        feed = feedparser.parse(url)
        
        if feed.bozo and feed.bozo_exception:
            logger.warning(f"RSS parse warning for {name}: {feed.bozo_exception}")
        
        for entry in feed.entries[:20]:  # Limit to latest 20 per feed
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = entry.get("summary", "") or entry.get("description", "") or ""
            published = entry.get("published", "") or entry.get("updated", "")
            
            if not title or not link:
                continue
            
            # DATE FILTER: last-N-hours window (digest) or strict today-only (normal)
            pub_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
            pub_dt_utc = None
            if pub_parsed:
                try:
                    # published_parsed is UTC when feed gives timezone-aware dates
                    pub_dt_utc = datetime(*pub_parsed[:6], tzinfo=timezone.utc)
                    if cutoff is not None:
                        if pub_dt_utc < cutoff:
                            skipped_old += 1
                            continue
                    elif pub_dt_utc.date() != today:
                        skipped_old += 1
                        continue  # Not today's news - skip (no kal/parson/month purani)
                except Exception:
                    pass  # If date unparseable, allow it through
            
            # Clean HTML from summary
            import re
            summary = re.sub(r'<[^>]+>', '', summary)
            summary = re.sub(r'\s+', ' ', summary).strip()[:500]
            
            items.append({
                "title": title,
                "description": summary,
                "url": link,
                "source": name,
                "published": published,
                "published_ts": pub_dt_utc.timestamp() if pub_dt_utc else 0,
                "type": "crypto_news"
            })
        
        logger.info(f"{LOG_RSS} {name}: {len(items)} today, {skipped_old} old skipped")
        return items
        
    except Exception as e:
        logger.error(f"RSS fetch error for {name}: {e}")
        return []


def _parse_calendar_time(event: Dict[str, Any]) -> Optional[datetime]:
    """Parse an event time from either calendar schema. Always returns an
    aware UTC datetime, or None if unparseable.

    Real faireconomy schema: {"date": "2026-10-14T12:30:00-04:00", ...} (ISO-8601 with offset).
    Legacy schema: {"date": "2026-10-14", "time": "12:30"} (no tz -> treated as UTC).
    """
    raw = (event.get("date") or "").strip()
    if not raw:
        return None
    try:
        t = (event.get("time") or "").strip()
        if t and "T" not in raw:
            dt = datetime.strptime(f"{raw} {t[:5]}", "%Y-%m-%d %H:%M")
            return dt.replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _macro_event_matches(event: Dict[str, Any]) -> Optional[str]:
    """Return the normalized event title if this is a tracked high-impact USD
    event, else None. Handles both schemas (title/country AND event/currency)."""
    country = (event.get("country") or event.get("currency") or "").strip().upper()
    if country != "USD":
        return None
    if (event.get("impact") or "").strip().lower() != "high":
        return None
    title = (event.get("title") or event.get("event") or "").strip()
    if not title:
        return None
    if not any(keyword.lower() in title.lower() for keyword in HIGH_IMPACT_USD_EVENTS):
        return None
    return title


def _download_calendar() -> List[Dict[str, Any]]:
    """Download raw calendar JSON (throttled). NEVER raises: on 429/timeout/bad
    JSON it logs a warning and returns the last cached download (possibly [])."""
    global _MACRO_HTTP_CACHE
    now = datetime.now(timezone.utc)
    last = _MACRO_HTTP_CACHE.get("at")
    cached = _MACRO_HTTP_CACHE.get("events") or []
    if last is not None and (now - last).total_seconds() < MACRO_FETCH_INTERVAL and cached:
        return cached
    try:
        response = requests.get(FOREX_FACTORY_CALENDAR_URL, timeout=15)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            logger.warning(f"{LOG_WARN} Macro calendar returned non-list JSON, using cached data")
            return cached
        _MACRO_HTTP_CACHE = {"at": now, "events": data}
        return data
    except requests.exceptions.HTTPError as e:
        status = getattr(getattr(e, "response", None), "status_code", "?")
        logger.warning(f"{LOG_WARN} Macro calendar HTTP {status} (rate-limited?) - using cached data")
    except requests.exceptions.Timeout:
        logger.warning(f"{LOG_WARN} Forex Factory calendar timeout - using cached data")
    except requests.exceptions.RequestException as e:
        logger.error(f"{LOG_ERR} Forex Factory calendar error: {e} - using cached data")
    except (json.JSONDecodeError, ValueError):
        logger.error(f"{LOG_ERR} Invalid JSON from Forex Factory calendar - using cached data")
    except Exception as e:
        logger.error(f"{LOG_ERR} Macro calendar fetch error: {e} - using cached data")
    return cached


def fetch_forex_factory_calendar() -> List[Dict[str, Any]]:
    """Filter cached/downloaded calendar down to high-impact USD macro events
    inside the alert window (last 6h -> next 24h). Timezone-safe."""
    items = []

    try:
        events = _download_calendar()

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=6)  # Events from last 6 hours
        window_end = now + timedelta(hours=24)   # Upcoming 24 hours

        for event in events:
            try:
                title = _macro_event_matches(event)
                if not title:
                    continue

                event_time = _parse_calendar_time(event)
                if event_time is None:
                    continue

                # Skip if outside our window (both sides are aware datetimes now)
                if not (window_start <= event_time <= window_end):
                    continue

                # Create unique cache key
                cache_key = f"{title}_{event_time.isoformat()}"
                if cache_key in macro_event_cache:
                    continue  # Already sent this event

                # Build description
                actual = event.get("actual", "") or ""
                forecast = event.get("forecast", "") or ""
                previous = event.get("previous", "") or ""

                desc_parts = [f"Event: {title}"]
                if actual:
                    desc_parts.append(f"Actual: {actual}")
                if forecast:
                    desc_parts.append(f"Forecast: {forecast}")
                if previous:
                    desc_parts.append(f"Previous: {previous}")

                # Determine if it's upcoming or past
                time_label = "UPCOMING" if event_time > now else "JUST RELEASED"

                items.append({
                    "title": f"[{time_label}] {title} - High Impact USD",
                    "description": " | ".join(desc_parts),
                    "url": f"https://www.forexfactory.com/calendar?day={event_time.strftime('%Y-%m-%d')}",
                    "source": "Forex Factory Calendar",
                    "published": event_time.isoformat(),
                    "type": "macro_event",
                    "cache_key": cache_key
                })

            except Exception as e:
                logger.debug(f"Skipping malformed calendar event: {e}")
                continue

        logger.info(f"{LOG_MACRO} Forex Factory: {len(items)} high-impact USD events")
        return items

    except Exception as e:
        logger.error(f"{LOG_ERR} Macro calendar filter error: {e}")
        return []


def fetch_all_news() -> List[Dict[str, Any]]:
    """Fetch from all RSS feeds + macro calendar."""
    all_items = []
    
    # Fetch crypto RSS feeds
    for feed in CRYPTO_RSS_FEEDS:
        items = fetch_rss_feed(feed)
        all_items.extend(items)
    
    # Fetch macro calendar events
    macro_items = fetch_forex_factory_calendar()
    all_items.extend(macro_items)
    
    return all_items


def analyze_with_llm(title: str, description: str, source: str) -> Optional[Dict[str, Any]]:
    """Send news to FREE LLM (Gemini/Groq/OpenRouter) for analysis."""

    # DRY-RUN or LOCAL: Use mock analysis (perfect Hinglish, no API needed)
    if DRY_RUN or LOCAL_MODE:
        return mock_analyze_with_llm(title, description, source)

    user_content = f"""Title: {title}
Description: {description}
Source: {source}

Analyze this crypto news item."""

    result: Optional[Dict[str, Any]] = None

    # ============ OLLAMA (FREE, LOCAL, NO ACCOUNT) ============
    if LLM_PROVIDER == "ollama":
        result = _analyze_with_ollama(user_content)

    # ============ GEMINI (FREE: 1500 req/day) ============
    elif LLM_PROVIDER == "gemini":
        result = _analyze_with_gemini(user_content)

    # ============ GROQ (FREE, fast, generous) ============
    elif LLM_PROVIDER == "groq":
        result = _analyze_with_groq(user_content)

    # ============ OPENROUTER (needs credits) ============
    elif LLM_PROVIDER == "openrouter":
        result = _analyze_with_openrouter(user_content)

    else:
        logger.error(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")
        return None

    # Specificity guard: small/cheap models often return the same template
    # for a whole category (e.g. identical Regulation bullets for Coins.ph
    # and SkyAI). Fall back to the deterministic specific builder instead
    # of spamming a generic alert.
    if isinstance(result, dict) and not result.get("__api_error__"):
        if is_generic_analysis(result, title, description):
            logger.warning(f"{LOG_WARN} Generic LLM output rejected, using specific fallback: {title[:70]}...")
            return mock_analyze_with_llm(title, description, source)

    return result


def _analyze_with_gemini(user_content: str) -> Optional[Dict[str, Any]]:
    """Analyze using Google Gemini API (FREE tier: 1500 req/day)."""
    payload = {
        "contents": [{
            "parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_content}]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 500,
            "responseMimeType": "application/json"
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }
    
    try:
        response = requests.post(GEMINI_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        content = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
        
        return _parse_llm_response(content)
        
    except requests.exceptions.Timeout:
        logger.warning("Gemini API timeout")
    except requests.exceptions.RequestException as e:
        logger.error(f"Gemini API error: {e}")
    except Exception as e:
        logger.error(f"Gemini analysis error: {e}")
    
    return None


def _analyze_with_groq(user_content: str) -> Optional[Dict[str, Any]]:
    """Analyze using Groq API (FREE tier, very fast)."""
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.1,
        "max_tokens": 1000,
        "response_format": {"type": "json_object"}
    }
    
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        last_err = None
        for attempt in range(2):  # Retry once: Groq sometimes fails JSON validation transiently
            try:
                response = requests.post(GROQ_URL, json=payload, headers=headers, timeout=30)
                response.raise_for_status()
                result = response.json()

                content = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

                try:
                    return _parse_llm_response(content)
                except (ValueError, KeyError, AttributeError) as e:
                    # Model answered but output unusable - burn it, don't retry forever
                    logger.warning("Groq bad response structure, skipping: %s", e)
                    return None

            except requests.exceptions.Timeout:
                last_err = "timeout"
                logger.warning("Groq API timeout (attempt %d)", attempt + 1)
            except requests.exceptions.RequestException as e:
                last_err = str(e)
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status == 429 and attempt == 0:
                    logger.warning("Groq rate-limited, cooling down 30s before retry")
                    time.sleep(30)
                else:
                    logger.warning("Groq API error (attempt %d): %s", attempt + 1, e)
        logger.error("Groq failed after 2 attempts: %s", last_err)
        return {"__api_error__": True}  # Transport failure, NOT a verdict - caller must retry later
    except Exception as e:
        logger.error(f"Groq analysis error: {e}")

    return {"__api_error__": True}


def _analyze_with_openrouter(user_content: str) -> Optional[Dict[str, Any]]:
    """Analyze using OpenRouter API (needs credits)."""
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.1,
        "max_tokens": 500,
        "response_format": {"type": "json_object"}
    }
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/crypto-news-bot",
        "X-Title": "Crypto AI News Bot"
    }
    
    try:
        response = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        
        return _parse_llm_response(content)
        
    except requests.exceptions.Timeout:
        logger.warning("OpenRouter API timeout")
    except requests.exceptions.RequestException as e:
        logger.error(f"OpenRouter API error: {e}")
    except Exception as e:
        logger.error(f"OpenRouter analysis error: {e}")
    
    return None


def _analyze_with_ollama(user_content: str) -> Optional[Dict[str, Any]]:
    """Analyze using local Ollama (FREE, LOCAL, NO ACCOUNT NEEDED)."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.1,
        "max_tokens": 500,
        "format": "json",
        "stream": False
    }
    
    try:
        response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        
        content = result.get("message", {}).get("content", "").strip()
        
        return _parse_llm_response(content)
        
    except requests.exceptions.Timeout:
        logger.warning("Ollama API timeout (model may be loading)")
    except requests.exceptions.ConnectionError:
        logger.error(f"Ollama connection failed. Is Ollama running at {OLLAMA_URL}?")
    except requests.exceptions.RequestException as e:
        logger.error(f"Ollama API error: {e}")
    except Exception as e:
        logger.error(f"Ollama analysis error: {e}")
    
    return None


def _parse_llm_response(content: str) -> Optional[Dict[str, Any]]:
    """Parse and validate LLM response."""
    if content is None:
        content = ""
    content = content.strip()
    
    # Handle different response formats
    # Format 1: Direct "SKIP"
    if content == "SKIP":
        return None
    
    # Format 2: JSON with response field: {"response": "SKIP"}
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            if parsed.get("response") == "SKIP":
                return None
            content = json.dumps(parsed)  # Re-serialize for parsing below
    except json.JSONDecodeError:
        pass  # Not JSON, use as-is
    
    # Parse JSON response
    analysis = json.loads(content)
    
    # Validate required fields
    required_fields = ["category", "headline", "summary", "impact", "source_name"]
    if all(field in analysis for field in required_fields):
        return analysis
    else:
        logger.warning(f"Invalid response structure from LLM: {content}")
        return None


# Phrases seen in the wild from small/cheap LLMs ignoring the "be specific"
# instruction and returning the same template for every alert in a category.
# If any of these appear, the response is generic and must be rejected.
GENERIC_BANNED_SUBSTRINGS = [
    "naye features aaye",
    "gas fees kam honge",
    "speed badhegi",
    "developers naye tools",
    "naye rules se exchange compliance",
    "stablecoin reserve rules",
    "defi projects ko registration",
    "sarkar ne naye rules banaye - crypto pe asar",
    "protocol upgrade hua",
    "mainnet upgrade successfully",
]


def is_generic_analysis(analysis: Dict[str, Any], title: str, description: str) -> bool:
    """Reject template/generic LLM output that ignores the THIS-news rule.

    Returns True when the headline+summary look copy-pasted instead of
    derived from this specific title/description.
    """
    headline = str(analysis.get("headline", "") or "")
    summary = analysis.get("summary", []) or []
    blob = f"{headline} {' '.join(str(s) for s in summary)}".lower()

    # 1. Known template phrases -> instantly generic.
    for banned in GENERIC_BANNED_SUBSTRINGS:
        if banned in blob:
            return True

    # 2. Two different stories must not produce byte-identical summaries.
    #    (Checked implicitly: identical template bullets hit rule 1, but also
    #    catch any 3-bullet output with zero title-specific words.)
    fp = title_fingerprint(title or "")
    if not fp:
        return False  # Can't judge very short titles; let it through.
    blob_words = set(__import__("re").findall(r"[a-z0-9]+", blob))
    overlap = len(fp & blob_words)
    # Require at least 2 significant title words (or 1 if title is very short)
    # to appear somewhere in headline+summary. Solana/Alpenglow/Coins.ph/SkyAI
    # style entities must be echoed, otherwise the LLM wrote a template.
    required = 1 if len(fp) <= 3 else 2
    if overlap < required:
        return True

    # 3. All 3 bullets identical to each other (degenerate output).
    normed = [str(s).strip().lower() for s in summary if str(s).strip()]
    if len(normed) >= 2 and len(set(normed)) == 1:
        return True

    return False


def format_telegram_message(analysis: Dict[str, Any], original_url: str, original_title: str = "") -> str:
    """Format analysis into Telegram Markdown message in Hinglish."""
    
    category = analysis.get("category", "NEWS")
    headline = analysis.get("headline", "Breaking News")
    summary = analysis.get("summary", [])
    impact = analysis.get("impact", "MEDIUM")
    source_name = analysis.get("source_name", "Unknown")
    
    # Impact emoji
    impact_emoji = "🔥" if impact == "HIGH" else "⚡"
    
    # Build summary bullets
    summary_text = "\n".join([f"• {point}" for point in summary[:3]])  # Max 3 points
    
    # Original headline (so each alert is distinguishable)
    original_line = ""
    if original_title:
        short_title = original_title.strip()
        if len(short_title) > 120:
            short_title = short_title[:117] + "..."
        original_line = f"📰 _{short_title}_\n"
    
    message = (
        f"🚨 *[{category}]*\n"
        f"{original_line}"
        f"📌 *Headline:* {headline}\n"
        f"💡 *Key Summary:*\n{summary_text}\n"
        f"📊 *Impact Level:* {impact_emoji} {impact}\n"
        f"🔗 *Source:* [{source_name}]({original_url})"
    )
    
    return message


def send_telegram_message(text: str) -> bool:
    """Send formatted message to Telegram."""
    
    # DRY-RUN: Print to console instead of sending
    if DRY_RUN:
        try:
            print("\n" + "=" * 60)
            print("[TG] TELEGRAM MESSAGE (DRY-RUN):")
            print("=" * 60)
            # Replace emojis for Windows console compatibility
            safe_text = (text.replace("🚨", "[ALERT]").replace("🔥", "[FIRE]").replace("⚡", "[BOLT]")
                         .replace("📌", "[PIN]").replace("💡", "[IDEA]").replace("📊", "[CHART]")
                         .replace("🔗", "[LINK]").replace("📰", "[NEWS]").replace("•", "-"))
            print(safe_text.encode("ascii", errors="replace").decode("ascii"))
            print("=" * 60 + "\n")
        except Exception:
            pass  # Ignore console encoding issues
        return True
    
    # TELEGRAM_CHAT_ID can hold multiple targets, comma-separated, e.g.
    #   "-5597836192,919135909"   (group + private)
    # Each target gets the same message. Sending to every target is best-effort:
    # one bad id won't stop the others, and we still report overall success.
    targets = [t.strip() for t in str(TELEGRAM_CHAT_ID).split(",") if t.strip()]
    if not targets:
        logger.error("Telegram send skipped: no TELEGRAM_CHAT_ID configured")
        return False

    all_ok = True
    for chat_id in targets:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        try:
            response = requests.post(TELEGRAM_API_URL, json=payload, timeout=15)
            response.raise_for_status()
            result = response.json()

            if result.get("ok"):
                logger.info(f"{LOG_SENT} Telegram message sent to {chat_id}")
            else:
                logger.error(f"Telegram API error for {chat_id}: {result}")
                all_ok = False

        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram send error for {chat_id}: {e}")
            all_ok = False

    return all_ok


def format_whatsapp_message(analysis: Dict[str, Any], original_url: str, original_title: str = "") -> str:
    """Format analysis into plain-text WhatsApp message (no Markdown - WhatsApp
    only supports *bold* / _italic_, so keep it simple). Links are raw URLs so
    WhatsApp shows a preview."""

    category = analysis.get("category", "NEWS")
    headline = analysis.get("headline", "Breaking News")
    summary = analysis.get("summary", [])
    impact = analysis.get("impact", "MEDIUM")
    source_name = analysis.get("source_name", "Unknown")

    impact_emoji = "🔥" if impact == "HIGH" else "⚡"

    lines = [f"🚨 [{category}]"]
    if original_title:
        short_title = original_title.strip()
        if len(short_title) > 120:
            short_title = short_title[:117] + "..."
        lines.append(f"📰 {short_title}")
    lines.append(f"Headline: {headline}")
    for point in summary[:3]:  # Max 3 points
        lines.append(f"• {point}")
    lines.append(f"Impact: {impact_emoji} {impact}")
    lines.append(f"Source: {source_name} - {original_url}")

    return "\n".join(lines)


def _send_whatsapp_cloudapi(text: str) -> bool:
    """Send via official Meta WhatsApp Cloud API. Never raises."""
    if not WHATSAPP_CLOUD_TOKEN or not WHATSAPP_CLOUD_PHONE_ID:
        logger.warning(f"{LOG_WARN} Cloud API selected but WHATSAPP_CLOUD_TOKEN/PHONE_ID missing - skipping")
        return False
    if not WHATSAPP_PHONE:
        logger.warning(f"{LOG_WARN} WHATSAPP_PHONE (receiver number) missing - skipping")
        return False
    try:
        response = requests.post(
            f"https://graph.facebook.com/v22.0/{WHATSAPP_CLOUD_PHONE_ID}/messages",
            headers={
                "Authorization": f"Bearer {WHATSAPP_CLOUD_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": WHATSAPP_PHONE,
                "type": "text",
                "text": {"preview_url": True, "body": text[:4000]},
            },
            timeout=20,
        )
        if response.status_code == 200:
            logger.info(f"{LOG_SENT} WhatsApp (Cloud API) message sent successfully")
            return True
        logger.warning(f"{LOG_WARN} WhatsApp Cloud API failed: HTTP {response.status_code}: {response.text[:300]}")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"{LOG_WARN} WhatsApp Cloud API error: {e}")
        return False


def send_whatsapp_message(text: str) -> bool:
    """Send alert to WhatsApp. Provider picked by WHATSAPP_PROVIDER env:
    "callmebot" (FREE, easy) or "cloudapi" (official Meta API).
    Best-effort: never raises, returns False on any failure (Telegram remains primary)."""

    if not WHATSAPP_ENABLED:
        return False

    # DRY-RUN: Print to console instead of sending
    if DRY_RUN:
        try:
            print("\n" + "=" * 60)
            print("[WA] WHATSAPP MESSAGE (DRY-RUN):")
            print("=" * 60)
            print(text[:1500])
            print("=" * 60 + "\n")
        except Exception:
            pass  # Ignore console encoding issues
        return True

    if WHATSAPP_PROVIDER == "cloudapi":
        return _send_whatsapp_cloudapi(text)

    if not WHATSAPP_PHONE or not WHATSAPP_APIKEY:
        logger.warning(f"{LOG_WARN} WhatsApp enabled but WHATSAPP_PHONE/WHATSAPP_APIKEY missing - skipping")
        return False

    try:
        # CallMeBot free API: GET with phone (country code + number, no +), text, apikey
        response = requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={"phone": WHATSAPP_PHONE, "text": text[:3000], "apikey": WHATSAPP_APIKEY},
            timeout=20,
        )
        if response.status_code == 200:
            logger.info(f"{LOG_SENT} WhatsApp message sent successfully")
            return True
        logger.warning(f"{LOG_WARN} WhatsApp send failed: HTTP {response.status_code}: {response.text[:200]}")
        return False

    except requests.exceptions.RequestException as e:
        logger.warning(f"{LOG_WARN} WhatsApp send error: {e}")
        return False


def send_ntfy_push(text: str) -> bool:
    """Instant phone notification via ntfy.sh (FREE, no account, no signup).
    Best-effort: never raises, returns False on any failure (Telegram stays primary)."""
    if not NTFY_ENABLED:
        return False

    # DRY-RUN: Print to console instead of sending
    if DRY_RUN:
        try:
            print("\n" + "=" * 60)
            print("[NTFY] PUSH MESSAGE (DRY-RUN):")
            print("=" * 60)
            print(text[:800])
            print("=" * 60 + "\n")
        except Exception:
            pass  # Ignore console encoding issues
        return True

    if not NTFY_TOPIC:
        logger.warning(f"{LOG_WARN} ntfy enabled but NTFY_TOPIC missing - skipping")
        return False

    try:
        response = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=text[:3500].encode("utf-8"),
            headers={"Title": "Crypto Alert", "Priority": "high", "Tags": "chart_with_upwards_trend"},
            timeout=15,
        )
        if response.status_code == 200:
            logger.info(f"{LOG_SENT} ntfy push sent successfully")
            return True
        logger.warning(f"{LOG_WARN} ntfy send failed: HTTP {response.status_code}: {response.text[:200]}")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"{LOG_WARN} ntfy send error: {e}")
        return False


def process_news_item(item: Dict[str, Any]) -> bool:
    """Process a single news item: analyze and send if valid."""
    item_hash = generate_item_hash(item["title"], item["url"])
    
    # Skip if already processed
    if item_hash in processed_hashes:
        return False
    
    title = item.get("title", "").strip()
    description = item.get("description", "").strip()
    source = item.get("source", "Unknown")
    url = item.get("url", "")
    item_type = item.get("type", "crypto_news")
    
    if not title:
        return False
    
    # SKIP videos/podcasts by URL - never breaking news
    url_lower = url.lower()
    if "/videos/" in url_lower or "/video/" in url_lower or "/podcast" in url_lower:
        logger.info(f"{LOG_SKIP} Skipped (video/podcast content)")
        processed_hashes.add(item_hash)
        return False
    
    # STORY-LEVEL DEDUP: same story from another feed already alerted? Send once only.
    if item_type == "crypto_news":
        fp = title_fingerprint(title)
        if is_duplicate_story(fp):
            logger.info(f"{LOG_SKIP} Duplicate story (already alerted from another feed): {title[:70]}...")
            processed_hashes.add(item_hash)
            return False
    
    logger.info(f"{LOG_AI} Analyzing [{item_type}]: {title[:80]}...")
    
    # Analyze with LLM
    analysis = analyze_with_llm(title, description, source)

    # API transport failure (NOT a verdict): retry next cycle, do NOT burn the hash
    if isinstance(analysis, dict) and analysis.get("__api_error__"):
        logger.warning(f"{LOG_WARN} LLM API failed, will retry next cycle: {title[:70]}...")
        return False

    if analysis is None:
        logger.info(f"{LOG_SKIP} Skipped (filtered by LLM)")
        processed_hashes.add(item_hash)
        # Cache macro events
        if item_type == "macro_event" and "cache_key" in item:
            macro_event_cache[item["cache_key"]] = datetime.now(timezone.utc)
        return False
    
    # Format and send (with original title so each alert is distinguishable)
    message = format_telegram_message(analysis, url, original_title=title)
    success = send_telegram_message(message)

    # Mirror the same alert to WhatsApp (best-effort, Telegram stays primary)
    if success and WHATSAPP_ENABLED:
        wa_message = format_whatsapp_message(analysis, url, original_title=title)
        if not send_whatsapp_message(wa_message):
            logger.warning(f"{LOG_WARN} Telegram sent but WhatsApp failed: {title[:70]}...")

    # Mirror the same alert as instant phone push via ntfy (best-effort)
    if success and NTFY_ENABLED:
        ntfy_message = format_whatsapp_message(analysis, url, original_title=title)
        if not send_ntfy_push(ntfy_message):
            logger.warning(f"{LOG_WARN} Telegram sent but ntfy push failed: {title[:70]}...")

    if success:
        processed_hashes.add(item_hash)
        # Remember story fingerprint so other feeds' copies are skipped
        if item_type == "crypto_news":
            processed_stories.append(title_fingerprint(title))
        # Cache macro events
        if item_type == "macro_event" and "cache_key" in item:
            macro_event_cache[item["cache_key"]] = datetime.now(timezone.utc)
        logger.info(f"{LOG_SENT} Alert sent: {analysis['category']} - {impact_emoji(analysis['impact'])}")
        return True
    
    return False


def impact_emoji(impact: str) -> str:
    return "🔥" if impact == "HIGH" else "⚡"


def cleanup_old_data(max_hashes: int = 5000, max_cache_age_hours: int = 48):
    """Prevent memory bloat by limiting processed hashes and macro cache."""
    global processed_hashes, processed_stories, macro_event_cache
    
    # Cleanup processed hashes
    if len(processed_hashes) > max_hashes:
        processed_hashes = set(list(processed_hashes)[-max_hashes//2:])
        logger.info(f"{LOG_CLEAN} Cleaned up processed hashes, kept {len(processed_hashes)}")
    
    # Cleanup old story fingerprints (keep latest 2000)
    if len(processed_stories) > 2000:
        processed_stories = processed_stories[-2000:]
        logger.info(f"{LOG_CLEAN} Cleaned up story fingerprints, kept {len(processed_stories)}")
    
    # Cleanup old macro cache entries
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_cache_age_hours)
    old_keys = [k for k, v in macro_event_cache.items() if v < cutoff]
    for k in old_keys:
        del macro_event_cache[k]
    if old_keys:
        logger.info(f"{LOG_CLEAN} Cleaned up {len(old_keys)} old macro cache entries")


def format_digest_message(top: Dict[str, Any], runners_up: List[Dict[str, Any]]) -> str:
    """Format the daily BIG HEADLINE digest message in Hinglish."""
    analysis = top["analysis"]
    category = analysis.get("category", "NEWS")
    headline = analysis.get("headline", "Breaking News")
    summary = analysis.get("summary", [])
    impact = analysis.get("impact", "HIGH")
    source_name = analysis.get("source_name", top["item"].get("source", "Unknown"))
    url = top["item"].get("url", "")
    original_title = top["item"].get("title", "")

    impact_emoji = "🔥" if impact == "HIGH" else "⚡"
    summary_text = "\n".join([f"• {point}" for point in summary[:3]])
    outlets = top["outlets"]
    outlet_line = f"({outlets} outlets ne cover kiya)" if outlets > 1 else ""

    short_title = original_title.strip()
    if len(short_title) > 120:
        short_title = short_title[:117] + "..."

    message = (
        f"🔥 *BIG HEADLINE — LAST 24 HOURS* {outlet_line}\n"
        f"📰 _{short_title}_\n"
        f"📌 *Headline:* {headline}\n"
        f"💡 *Key Summary:*\n{summary_text}\n"
        f"📊 *Impact Level:* {impact_emoji} {impact} | *[{category}]*\n"
        f"🔗 *Source:* [{source_name}]({url})"
    )

    if runners_up:
        lines = []
        for r in runners_up[:2]:
            t = r["item"].get("title", "").strip()
            if len(t) > 90:
                t = t[:87] + "..."
            lines.append(f"➕ {t}")
        message += "\n\n*Also big:*\n" + "\n".join(lines)

    return message


def run_digest() -> bool:
    """Post the single biggest crypto story of the last 24h. Returns True if posted."""
    global LAST_DIGEST

    # IST day (bot's audience timezone)
    now_utc = datetime.now(timezone.utc)
    today_ist = (now_utc + timedelta(hours=5, minutes=30)).date().isoformat()

    if LAST_DIGEST == today_ist:
        logger.info(f"{LOG_BOT} Digest already posted for {today_ist}, skipping")
        return False

    logger.info(f"{LOG_BOT} Building 24h digest...")

    # Fetch last-24h items from all feeds (no dedup marking here)
    all_items: List[Dict[str, Any]] = []
    for feed in CRYPTO_RSS_FEEDS:
        all_items.extend(fetch_rss_feed(feed, since_hours=24))

    # Skip video/podcast URLs (never headline material)
    candidates = []
    for item in all_items:
        url_lower = item.get("url", "").lower()
        if "/videos/" in url_lower or "/video/" in url_lower or "/podcast" in url_lower:
            continue
        if item.get("title", "").strip():
            candidates.append(item)

    logger.info(f"{LOG_BOT} Digest: {len(candidates)} candidates from last 24h")

    # STAGE 1 (free, local): cluster same story across outlets + rank clusters.
    # Multi-outlet coverage = bigger story. Only top clusters go to the LLM.
    DIGEST_KEYWORDS = {
        "etf", "hack", "hacked", "exploit", "sec", "cftc", "lawsuit", "sued",
        "fraud", "ban", "banned", "crackdown", "sanction", "tariff", "fomc",
        "federal reserve", "rate cut", "rate hike", "cpi", "inflation", "powell",
        "trump", "musk", "white house", "whale", "blackrock", "microstrategy",
        "saylor", "liquidat", "depeg", "bankrupt", "insolven", "seize", "raid",
        "halving", "mainnet", "upgrade", "fork", "congress", "senate", "bill",
        "rbi", "fiu", "tax", "cbdc",
    }

    pre_clusters: List[List[Dict[str, Any]]] = []
    for item in candidates:
        fp = title_fingerprint(item.get("title", ""))
        placed = False
        for c in pre_clusters:
            if same_story(fp, title_fingerprint(c[0].get("title", ""))):
                c.append(item)
                placed = True
                break
        if not placed:
            pre_clusters.append([item])

    def pre_score(c: List[Dict[str, Any]]):
        outlets = len({x.get("source", "?") for x in c})
        text = " ".join(x.get("title", "") for x in c).lower()
        kw = sum(1 for k in DIGEST_KEYWORDS if k in text)
        fresh = 1 if any((now_utc.timestamp() - x.get("published_ts", 0)) < 6 * 3600
                         and x.get("published_ts", 0) > 0 for x in c) else 0
        return (outlets * 10 + min(kw, 10) + fresh, max(x.get("published_ts", 0) for x in c))

    pre_clusters.sort(key=pre_score, reverse=True)

    # Take items from top clusters, max 30 LLM calls
    shortlisted: List[Dict[str, Any]] = []
    for c in pre_clusters:
        for item in c:
            if len(shortlisted) >= 30:
                break
            shortlisted.append(item)
        if len(shortlisted) >= 30:
            break

    logger.info(f"{LOG_BOT} Digest: shortlisted {len(shortlisted)} items for AI review")

    # STAGE 2 (AI): analyze shortlisted only (polite pacing for free-tier limits)
    scored: List[Dict[str, Any]] = []
    for i, item in enumerate(shortlisted):
        analysis = analyze_with_llm(
            item.get("title", ""), item.get("description", ""), item.get("source", "Unknown")
        )
        if isinstance(analysis, dict) and analysis.get("__api_error__"):
            logger.warning(f"{LOG_WARN} Digest: LLM failed for item, skipping")
            continue
        if analysis is None:
            continue  # Not high-impact
        scored.append({
            "item": item,
            "analysis": analysis,
            "fp": title_fingerprint(item.get("title", "")),
        })
        if i < len(shortlisted) - 1:
            time.sleep(5)

    if not scored:
        logger.warning(f"{LOG_WARN} Digest: no high-impact story found in last 24h")
        return False

    # Prefer HIGH impact; fall back to MEDIUM
    highs = [s for s in scored if s["analysis"].get("impact") == "HIGH"]
    pool = highs if highs else scored

    # Cluster same story (multi-outlet coverage = bigger story)
    clusters: List[List[Dict[str, Any]]] = []
    for s in pool:
        placed = False
        for c in clusters:
            if same_story(s["fp"], c[0]["fp"]):
                c.append(s)
                placed = True
                break
        if not placed:
            clusters.append([s])

    def cluster_key(c: List[Dict[str, Any]]):
        latest = max(x["item"].get("published_ts", 0) for x in c)
        return (len(c), latest)

    clusters.sort(key=cluster_key, reverse=True)

    top_cluster = clusters[0]
    # Representative: HIGH impact + latest within cluster
    top_cluster.sort(
        key=lambda x: (1 if x["analysis"].get("impact") == "HIGH" else 0,
                       x["item"].get("published_ts", 0)),
        reverse=True,
    )
    top = {
        "item": top_cluster[0]["item"],
        "analysis": top_cluster[0]["analysis"],
        "outlets": len({x["item"].get("source", "?") for x in top_cluster}),
    }
    runners_up = [
        {"item": c[0]["item"], "analysis": c[0]["analysis"], "outlets": len(c)}
        for c in clusters[1:3]
    ]

    message = format_digest_message(top, runners_up)
    if send_telegram_message(message):
        if WHATSAPP_ENABLED or NTFY_ENABLED:
            wa_top = top["item"]
            wa_text = format_whatsapp_message(top["analysis"], wa_top.get("url", ""), wa_top.get("title", ""))
            if runners_up:
                extra = []
                for r in runners_up[:2]:
                    t = r["item"].get("title", "").strip()
                    if len(t) > 90:
                        t = t[:87] + "..."
                    extra.append(f"+ {t}")
                wa_text += "\n\nAlso big:\n" + "\n".join(extra)
            wa_text = "BIG HEADLINE - LAST 24 HOURS\n" + wa_text
            if WHATSAPP_ENABLED and not send_whatsapp_message(wa_text):
                logger.warning(f"{LOG_WARN} Digest sent to Telegram but WhatsApp failed")
            if NTFY_ENABLED and not send_ntfy_push(wa_text):
                logger.warning(f"{LOG_WARN} Digest sent to Telegram but ntfy push failed")
        LAST_DIGEST = today_ist
        save_processed_hashes()
        logger.info(f"{LOG_SENT} Digest posted for {today_ist}")
        return True
    return False


def main():
    """Main event loop."""
    mode_str = "DRY-RUN" if DRY_RUN else ("LOCAL" if LOCAL_MODE else "LIVE")
    logger.info(f"{LOG_BOT} Crypto AI News Bot Starting... [{mode_str}]")
    logger.info(f"{LOG_BOT} pid={os.getpid()} wa_enabled={WHATSAPP_ENABLED}")
    logger.info(f"{LOG_BOT} Polling interval: {POLL_INTERVAL}s")
    if LOCAL_MODE or DRY_RUN:
        logger.info(f"{LOG_BOT} Analyzer: local keyword filter (Hinglish templates, no API)")
    else:
        logger.info(f"{LOG_BOT} Model: {MODEL_NAME}")
    logger.info(f"{LOG_RSS} RSS Feeds: {len(CRYPTO_RSS_FEEDS)} sources")
    logger.info(f"{LOG_MACRO} Macro Calendar: Forex Factory (High-Impact USD)")
    if RUN_ONCE:
        logger.info(f"{LOG_BOT} RUN_ONCE mode: Single cycle then exit")
    logger.info("=" * 60)
    
    if not validate_env():
        logger.error(f"{LOG_ERR} Environment validation failed. Check .env file.")
        return
    
    # Load previously processed items from disk (prevents duplicates after restart)
    load_processed_hashes()

    # Digest mode: post BIG HEADLINE of last 24h once, then exit
    if DIGEST_MODE:
        run_digest()
        return
    
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            # Fetch news from all sources
            news_items = fetch_all_news()
            
            if not news_items:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(f"{LOG_ERR} Too many consecutive errors ({consecutive_errors}). Sleeping longer...")
                    time.sleep(300)  # 5 min backoff
                if RUN_ONCE:
                    break
                continue
            
            consecutive_errors = 0  # Reset on success
            
            # Process each new item
            new_count = 0
            for item in news_items:
                if process_news_item(item):
                    new_count += 1
            
            # Heartbeat EVERY cycle (even with 0 alerts) - proves the bot is alive.
            # If these lines stop appearing in the log, the process was killed externally.
            logger.info(f"{LOG_RSS} Heartbeat: scanned {len(news_items)} items, sent {new_count} new alerts")
            
            # Periodic cleanup
            cleanup_old_data()
            
            # Save processed hashes to disk (survives restarts, prevents duplicates)
            save_processed_hashes()
            
        except KeyboardInterrupt:
            logger.info(f"\n{LOG_BOT} Bot stopped by user")
            save_processed_hashes()
            break
        except Exception as e:
            logger.exception(f"{LOG_ERR} Unexpected error in main loop: {e}")
            consecutive_errors += 1
        
        if RUN_ONCE:
            logger.info(f"{LOG_BOT} Single cycle complete. Exiting.")
            break
        
        # Sleep before next poll
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()