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
args = parser.parse_args()

DRY_RUN = args.dry_run
RUN_ONCE = args.once
LOCAL_MODE = args.local

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
macro_event_cache: Dict[str, datetime] = {}

# Persistent storage file for processed hashes (survives restarts)
PROCESSED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed.json")


def load_processed_hashes() -> None:
    """Load previously processed hashes + story fingerprints from disk."""
    global processed_hashes, processed_stories
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
                    logger.info(f"{LOG_BOT} Loaded {len(processed_hashes)} hashes + {len(processed_stories)} stories from disk")
    except Exception as e:
        logger.warning(f"Could not load processed hashes: {e}")


def save_processed_hashes() -> None:
    """Save processed hashes + story fingerprints to disk."""
    try:
        with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "hashes": sorted(processed_hashes),
                "stories": [sorted(s) for s in processed_stories[-2000:]]
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
    
    # Generate Hinglish headline - Simple, natural Hinglish
    hinglish_map = {
        "ETF": "ETF approve hua - market khush!",
        "Regulation": "Sarkar ne naye rules banaye - crypto pe asar!",
        "Hack": "Bada hack hua - paise gayab, market dar gaya!",
        "Macro": "Fed ka decision aaya - crypto liquidity change hogi!",
        "Influencer": "Bade aadmi ne tweet kiya - market hil gaya!",
        "Whale": "Whale ne bada move kiya - price pe asar!",
        "Protocol": "Protocol upgrade hua - naye features aaye!",
    }
    
    headline = hinglish_map.get(detected_category, "Badi khabar - market pe asar!")
    if len(headline) > 60:
        headline = headline[:57] + "..."
    
    # Generate summary bullets - Simple Hinglish
    summary_templates = {
        "ETF": [
            "SEC ne Bitcoin ETF approve kiya - bade players aayenge",
            "Price discovery better hoga, volatility kam hogi",
            "Traditional finance ab crypto mein aa rahi hai"
        ],
        "Regulation": [
            "Naye rules se exchange compliance strict hoga",
            "Stablecoin reserve rules badh sakte hain",
            "DeFi projects ko registration karna pad sakta hai"
        ],
        "Hack": [
            "Attacker ne vulnerability use ki - $100M+ gayab",
            "Exchange ne withdrawals band kiye - users pareshan",
            "Chain analysis chal rahi - funds trace ho rahe hain"
        ],
        "Macro": [
            "Fed rate decision se USD strong/weak hua",
            "CPI data expectations se alag aaya",
            "Liquidity conditions crypto ke liye badlenge"
        ],
        "Influencer": [
            "High-profile tweet se sudden volume aaya",
            "Market sentiment ekdum badal gaya",
            "Traders apni positions adjust kar rahe hain"
        ],
        "Whale": [
            "Bade wallet ne exchange pe paise dale - sell pressure",
            "Institutional buyer ne kharida - bullish signal",
            "On-chain data se move track hua"
        ],
        "Protocol": [
            "Mainnet upgrade successfully activate hua",
            "Gas fees kam honge, speed badhegi",
            "Developers naye tools use kar sakte hain"
        ],
    }
    
    summary = summary_templates.get(detected_category, [
        "Market-moving event detect hua",
        "Traders apni positions review karein",
        "Volatility badhne ki sambhavna hai"
    ])
    
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
   Return ONLY this JSON structure:
   {
     "category": "ETF/Regulation/Hack/Macro/Whale/Protocol/Influencer",
     "headline": "Simple Hinglish headline (max 60 chars)",
     "summary": ["Point 1 in simple Hinglish", "Point 2 in simple Hinglish", "Point 3 in simple Hinglish"],
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


def fetch_rss_feed(feed_info: Dict[str, str]) -> List[Dict[str, Any]]:
    """Fetch and parse a single RSS feed. ONLY today's news (strict current-date filter)."""
    name = feed_info["name"]
    url = feed_info["url"]
    items = []
    skipped_old = 0
    
    # Current date (local) - only news published TODAY is accepted
    today = datetime.now().date()
    
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
            
            # STRICT CURRENT-DATE FILTER: skip anything not published today
            pub_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
            if pub_parsed:
                try:
                    pub_date = datetime(*pub_parsed[:6]).date()
                    if pub_date != today:
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
                "type": "crypto_news"
            })
        
        logger.info(f"{LOG_RSS} {name}: {len(items)} today, {skipped_old} old skipped")
        return items
        
    except Exception as e:
        logger.error(f"RSS fetch error for {name}: {e}")
        return []


def fetch_forex_factory_calendar() -> List[Dict[str, Any]]:
    """Fetch high-impact USD macro events from economic calendar."""
    items = []
    
    try:
        logger.debug(f"Fetching macro calendar: {FOREX_FACTORY_CALENDAR_URL}")
        response = requests.get(FOREX_FACTORY_CALENDAR_URL, timeout=15)
        response.raise_for_status()
        events = response.json()
        
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=6)  # Events from last 6 hours
        window_end = now + timedelta(hours=24)   # Upcoming 24 hours
        
        for event in events:
            try:
                # Parse event time
                event_time_str = event.get("date", "") + " " + event.get("time", "00:00")
                event_time = datetime.strptime(event_time_str, "%Y-%m-%d %H:%M")
                
                # Skip if outside our window
                if not (window_start <= event_time <= window_end):
                    continue
                
                # Filter: Only USD currency
                currency = event.get("currency", "").upper()
                if currency != "USD":
                    continue
                
                # Filter: Only High Impact
                impact = event.get("impact", "").lower()
                if impact != "high":
                    continue
                
                # Filter: Only our target event types
                event_name = event.get("event", "").strip()
                if not any(keyword.lower() in event_name.lower() for keyword in HIGH_IMPACT_USD_EVENTS):
                    continue
                
                # Create unique cache key
                cache_key = f"{event_name}_{event_time_str}"
                if cache_key in macro_event_cache:
                    continue  # Already sent this event
                
                # Build description
                actual = event.get("actual", "")
                forecast = event.get("forecast", "")
                previous = event.get("previous", "")
                
                desc_parts = [f"Event: {event_name}"]
                if actual:
                    desc_parts.append(f"Actual: {actual}")
                if forecast:
                    desc_parts.append(f"Forecast: {forecast}")
                if previous:
                    desc_parts.append(f"Previous: {previous}")
                
                # Determine if it's upcoming or past
                time_label = "UPCOMING" if event_time > now else "JUST RELEASED"
                
                items.append({
                    "title": f"[{time_label}] {event_name} - High Impact USD",
                    "description": " | ".join(desc_parts),
                    "url": f"https://www.forexfactory.com/calendar?day={event_time.strftime('%Y-%m-%d')}",
                    "source": "Forex Factory Calendar",
                    "published": event_time_str,
                    "type": "macro_event",
                    "cache_key": cache_key
                })
                
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping malformed calendar event: {e}")
                continue
        
        logger.info(f"{LOG_MACRO} Forex Factory: {len(items)} high-impact USD events")
        return items
        
    except requests.exceptions.Timeout:
        logger.warning("Forex Factory calendar timeout")
    except requests.exceptions.RequestException as e:
        logger.error(f"Forex Factory calendar error: {e}")
    except json.JSONDecodeError:
        logger.error("Invalid JSON from Forex Factory calendar")
    except Exception as e:
        logger.error(f"Macro calendar fetch error: {e}")
    
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

    # ============ OLLAMA (FREE, LOCAL, NO ACCOUNT) ============
    if LLM_PROVIDER == "ollama":
        return _analyze_with_ollama(user_content)
    
    # ============ GEMINI (FREE: 1500 req/day) ============
    elif LLM_PROVIDER == "gemini":
        return _analyze_with_gemini(user_content)
    
    # ============ GROQ (FREE: fast, generous) ============
    elif LLM_PROVIDER == "groq":
        return _analyze_with_groq(user_content)
    
    # ============ OPENROUTER (needs credits) ============
    elif LLM_PROVIDER == "openrouter":
        return _analyze_with_openrouter(user_content)
    
    else:
        logger.error(f"Unknown LLM_PROVIDER: {LLM_PROVIDER}")
        return None


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
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(TELEGRAM_API_URL, json=payload, timeout=15)
        response.raise_for_status()
        result = response.json()
        
        if result.get("ok"):
            logger.info(f"{LOG_SENT} Telegram message sent successfully")
            return True
        else:
            logger.error(f"Telegram API error: {result}")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Telegram send error: {e}")
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


def main():
    """Main event loop."""
    mode_str = "DRY-RUN" if DRY_RUN else ("LOCAL" if LOCAL_MODE else "LIVE")
    logger.info(f"{LOG_BOT} Crypto AI News Bot Starting... [{mode_str}]")
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
            
            if new_count > 0:
                logger.info(f"{LOG_RSS} Processed {len(news_items)} items, sent {new_count} alerts")
            elif DRY_RUN:
                logger.info(f"{LOG_RSS} Processed {len(news_items)} items, 0 alerts (all filtered by mock LLM)")
            
            # Periodic cleanup
            cleanup_old_data()
            
            # Save processed hashes to disk (survives restarts, prevents duplicates)
            save_processed_hashes()
            
        except KeyboardInterrupt:
            logger.info(f"\n{LOG_BOT} Bot stopped by user")
            save_processed_hashes()
            break
        except Exception as e:
            logger.error(f"{LOG_ERR} Unexpected error in main loop: {e}")
            consecutive_errors += 1
        
        if RUN_ONCE:
            logger.info(f"{LOG_BOT} Single cycle complete. Exiting.")
            break
        
        # Sleep before next poll
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()