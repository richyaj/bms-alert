"""
BookMyShow IMAX Alert System
Uses multiple detection strategies to find IMAX bookings.
    "movie_name": "Dhurandhar The Revenge",
BookMyShow IMAX Alert System
Detection priority:
  1. Jina AI reader (free, unlimited) — renders JS pages, bypasses BMS bot detection
  2. SerpApi (250/month free) — fallback if Jina finds nothing
Sends push notification via ntfy.sh.
"""

import os
import json
import hashlib
import logging
import requests
from datetime import datetime, UTC
from bs4 import BeautifulSoup

CONFIG = {
    "movie_name": "Dhurandhar The Revenge",
    "city": "chennai",
    "city_code": "CHEN",
    "show_type": "IMAX",
    "ntfy_topic": os.environ.get("NTFY_TOPIC", ""),
    "serpapi_key": os.environ.get("SERPAPI_KEY", ""),
    "state_file": "alert_state.json",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)

# ─── State ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(CONFIG["state_file"]):
        with open(CONFIG["state_file"], "r") as f:
            return json.load(f)
    return {"alerted_hashes": [], "last_check": None}

def save_state(state: dict):
    state["last_check"] = datetime.now(UTC).isoformat()
    with open(CONFIG["state_file"], "w") as f:
        json.dump(state, f, indent=2)
    log.info("State saved.")

def make_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

# ─── Strategy 1: Jina AI Reader (free, unlimited) ──────────────────────────────

def strategy_jina(movie_name: str) -> list[dict]:
    """
    Jina AI's reader (r.jina.ai) renders JavaScript pages server-side and returns
    clean markdown/text. Free, no account, no rate limits.
    We use it to fetch the BMS Chennai movies page — bypasses bot detection.
    """
    found = []
    try:
        # Jina renders the page and returns clean text/markdown
        # Replace the jina_url line with:
        jina_url = f"https://r.jina.ai/https://in.bookmyshow.com/explore/imax-2d-movies-{CONFIG['city']}"
        resp = requests.get(
            jina_url,
            headers={
                "Accept": "text/plain",
                "X-Return-Format": "text",        # Get plain text back
                "X-With-Links-Summary": "true",   # Include all links at bottom
            },
            timeout=30,
        )
        log.info("[Jina] Status: %d, Length: %d", resp.status_code, len(resp.text))

        if resp.status_code == 200:
            text = resp.text
            movie_lower = movie_name.lower()

            # Check if the movie is even mentioned
            if movie_lower not in text.lower():
                log.info("[Jina] Movie not found in page text")
                return found

            log.info("[Jina] Movie mentioned on BMS page!")

            # Extract all URLs from the text — Jina includes a links section
            import re
            # Catch both bare URLs and markdown-style [text](url)
            urls = re.findall(r'https?://[^\s\)\"\'>\]]+', text)
            markdown_urls = re.findall(r'\]\((https?://[^\)]+)\)', text)
            urls = list(set(urls + markdown_urls))
            # DEBUG — remove after testing
            buyticket_lines = [line for line in text.split('\n') if 'buyticket' in line.lower() or 'book' in line.lower()]
            log.info("[Jina DEBUG] Lines with 'buyticket/book': %s", buyticket_lines[:5])
            for url in urls:
                url = url.rstrip('.,)')
                if "bookmyshow.com" in url and "buytickets" in url:
                    if movie_lower.replace(" ", "-") in url.lower() or movie_lower.replace(" ", "") in url.lower():
                        found.append({
                            "source": "jina",
                            "title": movie_name,
                            "url": url,
                            "imax": "imax" in url.lower() or "imax" in text[max(0, text.lower().find(url.split("/")[-1]))-200:].lower(),
                        })
                        log.info("[Jina] Found booking URL: %s", url)

            # Also try Jina on the IMAX-specific BMS page
            if not found:
                imax_url = f"https://r.jina.ai/https://in.bookmyshow.com/explore/imax-2d-movies-{CONFIG['city']}"
                resp2 = requests.get(imax_url, headers={"Accept": "text/plain", "X-With-Links-Summary": "true"}, timeout=30)
                log.info("[Jina IMAX page] Status: %d", resp2.status_code)
                if resp2.status_code == 200 and movie_lower in resp2.text.lower():
                    log.info("[Jina IMAX page] Movie found on IMAX page!")
                    urls2 = re.findall(r'https?://[^\s\)\"\']+', resp2.text)
                    for url in urls2:
                        url = url.rstrip('.,)')
                        if "bookmyshow.com" in url and "buytickets" in url:
                            found.append({
                                "source": "jina_imax",
                                "title": movie_name,
                                "url": url,
                                "imax": True,
                            })
                            log.info("[Jina IMAX page] Found: %s", url)

    except Exception as e:
        log.error("[Jina] Failed: %s", e)
    return found

# ─── Strategy 2: SerpApi (250/month free — emergency fallback) ─────────────────

def strategy_serpapi(movie_name: str) -> list[dict]:
    """Use SerpApi to Google search for BMS booking links. Costs 1 credit per run."""
    found = []
    api_key = CONFIG["serpapi_key"]
    if not api_key:
        log.warning("[SerpApi] SERPAPI_KEY not set, skipping")
        return found
    try:
        resp = requests.get(
            "https://serpapi.com/search",
            params={
                "q": f"{movie_name} IMAX Chennai bookmyshow buytickets",
                "engine": "google",
                "gl": "in",
                "hl": "en",
                "api_key": api_key,
            },
            timeout=15,
        )
        data = resp.json()
        for result in data.get("organic_results", []):
            url = result.get("link", "")
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            log.info("[SerpApi] Result: %s", url[:80])
            if "bookmyshow.com" in url and "buytickets" in url:
                found.append({
                    "source": "serpapi",
                    "title": title or movie_name,
                    "url": url,
                    "imax": "imax" in (url + snippet).lower(),
                })
                log.info("[SerpApi] Found: %s", url)
    except Exception as e:
        log.error("[SerpApi] Failed: %s", e)
    return found

# ─── Main Detection ────────────────────────────────────────────────────────────

def check_bms_for_movie() -> list[dict]:
    movie = CONFIG["movie_name"]
    all_found = []

    # Try Jina first — free and unlimited
    log.info("Trying: Jina AI Reader (free)")
    jina_results = strategy_jina(movie)
    if jina_results:
        log.info("Jina found %d result(s)", len(jina_results))
        all_found.extend(jina_results)
    else:
        # Only use SerpApi if Jina finds nothing — saves credits
        log.info("Jina found nothing. Trying: SerpApi (uses 1 credit)")
        serp_results = strategy_serpapi(movie)
        if serp_results:
            log.info("SerpApi found %d result(s)", len(serp_results))
            all_found.extend(serp_results)

    # Deduplicate by URL
    seen, deduped = set(), []
    for r in all_found:
        if r["url"] not in seen:
            seen.add(r["url"])
            deduped.append(r)
    return deduped

# ─── Ntfy Notification ─────────────────────────────────────────────────────────

def send_ntfy_alert(results: list[dict]):
    topic = CONFIG["ntfy_topic"]
    movie = CONFIG["movie_name"]
    if not topic:
        log.warning("NTFY_TOPIC not set — would have sent alert:")
        for r in results:
            log.info("  %s | %s", r.get("title"), r.get("url"))
        return False

    best = next((r for r in results if r.get("imax")), results[0])
    booking_url = best.get("url", "https://in.bookmyshow.com/chennai/movies")

    try:
        resp = requests.post(
            f"https://ntfy.sh/{topic}",
            headers={
                "Title": f"{movie} - IMAX Tickets Live!",
                "Priority": "urgent",
                "Tags": "movie_camera,rotating_light",
                "Click": booking_url,
            },
            data=(
                f"Booking is OPEN in Chennai!\n"
                f"Format: {CONFIG['show_type']}\n"
                f"Link: {booking_url}\n"
                f"Detected: {datetime.now(UTC).strftime('%d %b %Y %H:%M UTC')}"
            ).encode("utf-8"),
            timeout=10,
        )
        resp.raise_for_status()
        log.info("Ntfy alert sent to topic '%s'!", topic)
        return True
    except requests.RequestException as e:
        log.error("Failed to send ntfy alert: %s", e)
        return False

def send_ntfy_heartbeat():
    topic = CONFIG["ntfy_topic"]
    if not topic or datetime.now(UTC).hour != 9:
        return
    try:
        requests.post(
            f"https://ntfy.sh/{topic}",
            headers={"Title": "BMS Alert Bot - Still Running", "Priority": "low", "Tags": "white_check_mark"},
            data=f"Monitoring: {CONFIG['movie_name']} ({CONFIG['show_type']}) in Chennai\n{datetime.now(UTC).strftime('%d %b %Y %H:%M UTC')}".encode(),
            timeout=10,
        )
    except Exception:
        pass

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("BMS IMAX Alert Check — %s", datetime.now(UTC).isoformat())
    log.info("Movie: %s | Format: %s | City: Chennai", CONFIG["movie_name"], CONFIG["show_type"])
    log.info("=" * 60)

    state = load_state()
    already_alerted = set(state.get("alerted_hashes", []))

    results = check_bms_for_movie()
    log.info("Total unique booking results found: %d", len(results))

    if not results:
        log.info("No bookings found yet. Will check again later.")
        send_ntfy_heartbeat()
        save_state(state)
        return

    new_results = []
    for r in results:
        h = make_hash(r.get("url", r.get("title", "")))
        if h not in already_alerted:
            r["_hash"] = h
            new_results.append(r)

    if not new_results:
        log.info("Bookings found but already alerted. No duplicate sent.")
        save_state(state)
        return

    log.info("NEW bookings detected: %d", len(new_results))
    sent = send_ntfy_alert(new_results)

    if sent:
        for r in new_results:
            already_alerted.add(r["_hash"])
        state["alerted_hashes"] = list(already_alerted)

    save_state(state)
    log.info("Done.")

if __name__ == "__main__":
    main()
