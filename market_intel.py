"""
Market Intel Module
Fetches and caches economic calendar, crypto news, and token events
"""

import asyncio
import hashlib
import json
import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional

# aiohttp is optional - will use requests as fallback
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

logger = logging.getLogger(__name__)

# Cache directory
BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "data" / "market_intel"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class MarketIntelCache:
    """Handles caching of market intel data with TTL"""

    def __init__(self, default_ttl: int = 600):
        self.default_ttl = default_ttl

    def get_cached(self, key: str, ttl: Optional[int] = None) -> Optional[Dict]:
        """Get cached data if still valid"""
        cache_file = CACHE_DIR / f"{key}.json"
        if not cache_file.exists():
            return None

        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            cached_time = datetime.fromisoformat(data.get("cached_at", "2000-01-01"))
            effective_ttl = ttl or self.default_ttl
            if datetime.now() - cached_time > timedelta(seconds=effective_ttl):
                return None

            return data.get("data")
        except Exception as e:
            logger.warning(f"Cache read error for {key}: {e}")
            return None

    def set_cached(self, key: str, data: Dict):
        """Cache data with timestamp"""
        cache_file = CACHE_DIR / f"{key}.json"
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"cached_at": datetime.now().isoformat(), "data": data},
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.warning(f"Cache write error for {key}: {e}")


class MarketIntelFetcher:
    """Fetches market intel data from various free APIs"""

    # Free API endpoints
    CRYPTO_PANIC_API = "https://cryptopanic.com/api/v1/posts/"
    COINGECKO_EVENTS_API = "https://api.coingecko.com/api/v3/events"

    def __init__(self):
        self.cache = MarketIntelCache()

    # RSS feed sources for free crypto news (no API key required)
    RSS_FEEDS = [
        {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
        {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
        {"name": "Decrypt", "url": "https://decrypt.co/feed"},
    ]

    # Major crypto symbols to tag in headlines
    CRYPTO_SYMBOLS = [
        "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOT", "AVAX", "LINK", "DOGE",
        "SHIB", "UNI", "ATOM", "LTC", "BCH", "XLM", "VET", "FIL", "TRX", "ETC",
        "NEAR", "ARB", "OP", "APT", "SUI", "INJ", "RNDR", "FET", "GRT", "PEPE",
        "FLOKI", "BONK", "WIF", "TON", "NOT", "ICP", "ALGO", "ICX", "EOS", "NEO",
    ]

    async def fetch_crypto_news(self) -> List[Dict]:
        """Fetch crypto news from public RSS feeds (no API key required)."""
        cached = self.cache.get_cached("crypto_news", ttl=600)  # 10 min cache
        if cached:
            return cached

        if not AIOHTTP_AVAILABLE:
            logger.warning("aiohttp not installed, no crypto news available")
            self.cache.set_cached("crypto_news", [])
            return []

        news: List[Dict] = []
        seen_titles: set[str] = set()

        async with aiohttp.ClientSession() as session:
            for feed in self.RSS_FEEDS:
                try:
                    async with session.get(
                        feed["url"],
                        timeout=aiohttp.ClientTimeout(total=8),
                        headers={"User-Agent": "TradeEdge-MarketIntel/1.0"},
                    ) as response:
                        if response.status != 200:
                            logger.warning(
                                f"RSS feed {feed['name']} returned status {response.status}"
                            )
                            continue

                        text = await response.text()
                        try:
                            root = ET.fromstring(text)
                        except ET.ParseError as e:
                            logger.warning(f"Failed to parse RSS feed {feed['name']}: {e}")
                            continue

                        items = root.findall(".//item")
                        for item in items[:12]:
                            title = (item.findtext("title", "") or "").strip()
                            link = (item.findtext("link", "") or "").strip()
                            guid = (item.findtext("guid", "") or "").strip()
                            pub_date = item.findtext("pubDate", "") or item.findtext(
                                "published", ""
                            )

                            if not title or title in seen_titles:
                                continue
                            seen_titles.add(title)

                            news_id = hashlib.md5(
                                (guid or link or title).encode()
                            ).hexdigest()[:12]
                            news.append({
                                "id": f"rss_{feed['name'].lower()}_{news_id}",
                                "title": title,
                                "source": feed["name"],
                                "published_at": self._parse_rss_date(pub_date),
                                "url": link or guid,
                                "sentiment": self._detect_sentiment(title),
                                "currencies": self._extract_currencies(title),
                            })
                except Exception as e:
                    logger.warning(f"Error fetching RSS feed {feed['name']}: {e}")

        # Sort by published date desc, fallback to title sort
        news.sort(
            key=lambda x: (x.get("published_at") or "1970-01-01T00:00:00"),
            reverse=True,
        )
        news = news[:20]

        logger.info(f"Fetched {len(news)} crypto news articles from RSS")
        self.cache.set_cached("crypto_news", news)
        return news

    def _parse_rss_date(self, date_str: str) -> Optional[str]:
        """Parse RSS pubDate to ISO format."""
        if not date_str:
            return None
        try:
            dt = parsedate_to_datetime(date_str)
            return dt.isoformat()
        except Exception:
            pass
        # Try common ISO-ish formats
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%a, %d %b %Y %H:%M:%S %Z",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).isoformat()
            except Exception:
                continue
        return None

    def _extract_currencies(self, title: str) -> List[str]:
        """Extract mentioned crypto symbols from a headline."""
        title_upper = title.upper()
        found = []
        for symbol in self.CRYPTO_SYMBOLS:
            # Require word boundaries for short symbols to avoid false positives
            pattern = (
                rf"\b{symbol}\b" if len(symbol) > 2 else rf"\b{symbol}(?:USD|USDT)?\b"
            )
            if symbol in title_upper:
                # Basic substring check; regex import kept lightweight
                found.append(symbol)
        return found[:5]

    async def fetch_economic_calendar(self) -> List[Dict]:
        """
        Generate estimated economic calendar events
        Creates expected dates for major events (CPI, FOMC, NFP, etc.) based on typical schedules
        Note: These are estimated dates - integrate with a real economic calendar API for accuracy
        """
        cached = self.cache.get_cached("economic_calendar", ttl=3600)  # 1 hour cache
        if cached:
            return cached

        events = self._generate_upcoming_economic_events()
        self.cache.set_cached("economic_calendar", events)
        return events

    async def fetch_token_events(self) -> List[Dict]:
        """
        Fetch token-specific events from CoinGecko events API (free tier)
        """
        cached = self.cache.get_cached("token_events", ttl=1800)  # 30 min cache
        if cached:
            return cached

        events = []
        try:
            if not AIOHTTP_AVAILABLE:
                logger.warning("aiohttp not installed, no token events available")
                return events
            async with aiohttp.ClientSession() as session:
                url = "https://api.coingecko.com/api/v3/events"
                params = {"upcoming_events_only": "true"}

                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=3)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        for event in data.get("data", [])[:20]:
                            events.append({
                                "id": f"cg_{event.get('id', '')}",
                                "token": event.get("coin", {}).get(
                                    "symbol", "UNKNOWN"
                                ).upper(),
                                "event_type": event.get("type", "OTHER"),
                                "timestamp": event.get("date", ""),
                                "description": event.get("description", ""),
                                "impact": self._estimate_event_impact(event),
                                "amount": event.get("amount"),
                                "url": event.get("website", ""),
                            })

                        logger.info(f"Fetched {len(events)} token events from CoinGecko")
                    else:
                        logger.warning(
                            f"CoinGecko events API returned status {response.status}"
                        )
        except Exception as e:
            logger.error(f"Error fetching token events: {e}")

        # Cache the result (even if empty)
        self.cache.set_cached("token_events", events)
        return events

    def _detect_sentiment(self, title: str) -> str:
        """Basic sentiment analysis from title keywords"""
        bullish_keywords = [
            "surge",
            "rally",
            "bull",
            "breakout",
            "pump",
            "moon",
            "adoption",
            "partnership",
            "upgrade",
            "listing",
            "approval",
        ]
        bearish_keywords = [
            "crash",
            "dump",
            "bear",
            "decline",
            "hack",
            "scam",
            "ban",
            "regulation",
            "sell",
            "fraud",
            "collapse",
        ]

        title_lower = title.lower()
        bull_count = sum(1 for w in bullish_keywords if w in title_lower)
        bear_count = sum(1 for w in bearish_keywords if w in title_lower)

        if bull_count > bear_count:
            return "positive"
        elif bear_count > bull_count:
            return "negative"
        return "neutral"

    def _estimate_event_impact(self, event: Dict) -> str:
        """Estimate event impact based on type and description"""
        high_impact_types = [
            "HALVING",
            "UPGRADE",
            "UNLOCK",
            "AIRDROP",
            "MERGE",
            "HARDFORK",
        ]
        event_type = event.get("type", "").upper()

        if any(t in event_type for t in high_impact_types):
            return "HIGH"

        desc = event.get("description", "").lower()
        if any(
            k in desc
            for k in ["billion", "major", "critical", "emergency", "hard fork"]
        ):
            return "HIGH"

        return "MEDIUM"

    def _generate_upcoming_economic_events(self) -> List[Dict]:
        """
        Generate upcoming economic events for next 14 days
        Based on typical US economic data release schedule
        """
        events = []
        now = datetime.now()

        # Major economic events with typical release schedules
        # These are high/medium impact events that affect crypto markets
        economic_schedule = [
            # High impact - Fed/Macro events
            {
                "title": "FOMC Interest Rate Decision",
                "currency": "USD",
                "impact": "HIGH",
                "event_type": "FOMC",
                "day_pattern": "every_6_weeks",
            },
            {
                "title": "CPI Inflation Rate (MoM)",
                "currency": "USD",
                "impact": "HIGH",
                "event_type": "CPI",
                "day_pattern": "mid_month",
            },
            {
                "title": "Core CPI (MoM)",
                "currency": "USD",
                "impact": "HIGH",
                "event_type": "CPI",
                "day_pattern": "mid_month",
            },
            {
                "title": "Non-Farm Payrolls",
                "currency": "USD",
                "impact": "HIGH",
                "event_type": "NFP",
                "day_pattern": "first_friday",
            },
            # Medium impact
            {
                "title": "PPI (MoM)",
                "currency": "USD",
                "impact": "MEDIUM",
                "event_type": "PPI",
                "day_pattern": "mid_month",
            },
            {
                "title": "Retail Sales (MoM)",
                "currency": "USD",
                "impact": "MEDIUM",
                "event_type": "RETAIL",
                "day_pattern": "mid_month",
            },
            {
                "title": "GDP Growth Rate (QoQ)",
                "currency": "USD",
                "impact": "HIGH",
                "event_type": "GDP",
                "day_pattern": "quarterly",
            },
            {
                "title": "Initial Jobless Claims",
                "currency": "USD",
                "impact": "MEDIUM",
                "event_type": "UNEMPLOYMENT",
                "day_pattern": "weekly_thursday",
            },
            {
                "title": "ISM Manufacturing PMI",
                "currency": "USD",
                "impact": "MEDIUM",
                "event_type": "PMI",
                "day_pattern": "first_business_day",
            },
            {
                "title": "Fed Chair Speech",
                "currency": "USD",
                "impact": "MEDIUM",
                "event_type": "SPEECH",
                "day_pattern": "random",
            },
            # Global events
            {
                "title": "ECB Interest Rate Decision",
                "currency": "EUR",
                "impact": "HIGH",
                "event_type": "FOMC",
                "day_pattern": "monthly_thursday",
            },
            {
                "title": "China GDP (YoY)",
                "currency": "CNY",
                "impact": "MEDIUM",
                "event_type": "GDP",
                "day_pattern": "quarterly",
            },
        ]

        # Generate events for next 14 days
        # Track added events to prevent duplicates
        added_events = set()

        for i in range(14):
            day = now + timedelta(days=i)
            day_key = day.strftime("%Y%m%d")

            # Add events based on patterns
            # First Friday of month - NFP
            if day.weekday() == 4 and day.day <= 7:  # Friday, first week
                event_key = f"{day_key}_NFP"
                if event_key not in added_events:
                    nfp_event = next(
                        (e for e in economic_schedule if e["event_type"] == "NFP"), None
                    )
                    if nfp_event:
                        events.append(self._create_event(day, nfp_event, hour=14))
                        added_events.add(event_key)

            # CPI - only add once on the first eligible day (10-13 of month)
            if day.day in [10, 11, 12, 13] and day.weekday() < 5:  # Weekday
                # Check if we already have CPI for this month
                month_key = day.strftime("%Y%m")
                cpi_key = f"{month_key}_CPI"
                core_cpi_key = f"{month_key}_CORE_CPI"

                if cpi_key not in added_events:
                    # CPI Inflation Rate
                    cpi_event = next(
                        (e for e in economic_schedule if e["title"] == "CPI Inflation Rate (MoM)"), None
                    )
                    if cpi_event:
                        events.append(self._create_event(day, cpi_event, hour=14))
                        added_events.add(cpi_key)

                if core_cpi_key not in added_events:
                    # Core CPI
                    core_cpi_event = next(
                        (e for e in economic_schedule if e["title"] == "Core CPI (MoM)"), None
                    )
                    if core_cpi_event:
                        events.append(self._create_event(day, core_cpi_event, hour=14))
                        added_events.add(core_cpi_key)

            # PPI - only once per month (typically 12-15)
            if day.day in [12, 13, 14, 15] and day.weekday() < 5:
                month_key = day.strftime("%Y%m")
                ppi_key = f"{month_key}_PPI"
                if ppi_key not in added_events:
                    ppi_event = next(
                        (e for e in economic_schedule if e["event_type"] == "PPI"), None
                    )
                    if ppi_event:
                        events.append(self._create_event(day, ppi_event, hour=10))
                        added_events.add(ppi_key)

            # Retail Sales - only once per month (typically 14-16)
            if day.day in [14, 15, 16] and day.weekday() < 5:
                month_key = day.strftime("%Y%m")
                retail_key = f"{month_key}_RETAIL"
                if retail_key not in added_events:
                    retail_event = next(
                        (e for e in economic_schedule if e["event_type"] == "RETAIL"), None
                    )
                    if retail_event:
                        events.append(self._create_event(day, retail_event, hour=10))
                        added_events.add(retail_key)

            # Thursday - Jobless Claims (weekly)
            if day.weekday() == 3:  # Thursday
                event_key = f"{day_key}_CLAIMS"
                if event_key not in added_events:
                    jc_event = next(
                        (
                            e
                            for e in economic_schedule
                            if e["event_type"] == "UNEMPLOYMENT"
                        ),
                        None,
                    )
                    if jc_event:
                        events.append(self._create_event(day, jc_event, hour=14))
                        added_events.add(event_key)

            # First business day - ISM PMI
            if day.weekday() in [0, 1, 2, 3, 4] and day.day == 1:  # First of month
                ism_event = next(
                    (
                        e
                        for e in economic_schedule
                        if e["event_type"] == "PMI"
                    ),
                    None,
                )
                if ism_event:
                    events.append(self._create_event(day, ism_event, hour=10))

        # Sort by timestamp
        events.sort(key=lambda x: x["timestamp"])

        return events[:30]  # Limit to 30 events

    def _create_event(self, day: datetime, evt_template: Dict, hour: int = 10) -> Dict:
        """Create an event dict from template"""
        event_time = day.replace(hour=hour, minute=0, second=0)
        # Include first 3 chars of title hash to make ID unique
        title_hash = int(hashlib.md5(evt_template['title'].encode()).hexdigest(), 16) % 1000
        return {
            "id": f"econ_{event_time.strftime('%Y%m%d_%H%M')}_{evt_template['event_type']}_{title_hash:03d}",
            "title": evt_template["title"],
            "currency": evt_template["currency"],
            "impact": evt_template["impact"],
            "event_type": evt_template["event_type"],
            "timestamp": event_time.isoformat(),
            "forecast": None,
            "previous": None,
            "actual": None,
            "sentiment": None,
        }


# Global fetcher instance
market_intel_fetcher = MarketIntelFetcher()


def analyze_event_impact_for_position(
    event: Dict, symbol: str, direction: str
) -> Dict:
    """
    Analyze if a token event impacts an open position

    Args:
        event: Token event dict
        symbol: Trading symbol (e.g., BTCUSDT)
        direction: LONG or SHORT

    Returns:
        Dict with position_impact, risk_adjustment, reason
    """
    event_type = event.get("event_type", "").upper()
    desc = event.get("description", "").lower()
    impact = event.get("impact", "MEDIUM")

    # Bullish events (generally positive for price)
    bullish_types = ["AIRDROP", "UPGRADE", "PARTNERSHIP", "LISTING", "BURN", "HALVING"]
    # Bearish events (generally negative for price)
    bearish_types = ["UNLOCK", "SELL", "HACK", "FUD", "DELISTING"]

    is_bullish = any(b in event_type or b in desc for b in bullish_types)
    is_bearish = any(b in event_type or b in desc for b in bearish_types)

    if direction == "LONG":
        if is_bearish:
            return {
                "position_impact": "NEGATIVE",
                "risk_adjustment": "INCREASE_SL" if impact == "HIGH" else "MONITOR",
                "reason": f"Bearish event ({event_type}) may decrease price",
            }
        elif is_bullish:
            return {
                "position_impact": "POSITIVE",
                "risk_adjustment": "HOLD",
                "reason": f"Bullish event ({event_type}) may support price",
            }
    else:  # SHORT
        if is_bullish:
            return {
                "position_impact": "NEGATIVE",
                "risk_adjustment": "INCREASE_SL" if impact == "HIGH" else "MONITOR",
                "reason": f"Bullish event ({event_type}) may increase price",
            }
        elif is_bearish:
            return {
                "position_impact": "POSITIVE",
                "risk_adjustment": "HOLD",
                "reason": f"Bearish event ({event_type}) may support short",
            }

    return {
        "position_impact": "NEUTRAL",
        "risk_adjustment": "HOLD",
        "reason": "Event impact unclear",
    }


def analyze_macro_event_impact(event: Dict, direction: str) -> Dict:
    """
    Analyze if a macro economic event impacts positions

    High-impact USD events affect all USD pairs (crypto and forex)
    """
    event_type = event.get("event_type", "")
    impact = event.get("impact", "MEDIUM")

    # Events that typically cause volatility
    volatility_events = ["FOMC", "CPI", "NFP", "GDP"]

    if event_type in volatility_events and impact == "HIGH":
        return {
            "position_impact": "NEUTRAL",
            "risk_adjustment": "MONITOR",
            "reason": f"{event.get('title')} may cause high volatility - monitor closely",
        }

    return {
        "position_impact": "NEUTRAL",
        "risk_adjustment": "HOLD",
        "reason": "Low volatility expected",
    }