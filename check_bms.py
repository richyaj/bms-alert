"""
BookMyShow IMAX Alert System
Scrapes BMS Chennai page for Project Hail Mary IMAX bookings.
Sends push notification via ntfy.sh when booking opens.
"""

import os
import json
import hashlib
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup

# ─── Configuration ─────────────────────────────────────────────────────────────

CONFIG = {
    "movie_name": "Project Hail Mary",
    "city": "chennai",
    "show_type": "IMAX",
    "ntfy_topic": os.environ.get("NTFY_TOPIC", ""),
    "state_file": "alert_state.json",
    "bms_url": "https://in.bookmyshow.com/chennai/movies",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── State Management ──────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(CONFIG["state_file"]):
        with open(CONFIG["state_file"], "r") as f:
            return json.load(f)
    return {"alerted_hashes": [], "last_check": None}


def save_state(state: dict):
    state["last_check"] = datetime.utcnow().isoformat()
    with open(CONFIG["state_file"], "w") as f:
        json.dump(state, f, indent=2)
    log.info("State saved.")


def make_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

# ─── Scraper ───────────────────────────────────────────────────────────────────

def check_bms_for_movie() -> list[dict]:
    found = []

    # Try 1: BMS Chennai movies listing page
    try:
        log.info("Fetching BMS Chennai movies page...")
        resp = requests.get(CONFIG["bms_url"], headers=HEADERS, timeout=20)
        log.info("Response status: %d", resp.status_code)
        soup = BeautifulSoup(resp.text, "lxml")
        movie_name_lower = CONFIG["movie_name"].lower()

        for tag in soup.find_all(["a", "div", "span", "h2", "h3", "p"]):
            text = tag.get_text(" ", strip=True)
            if movie_name_lower in text.lower():
                href = tag.get("href", "")
                if "buytickets" in href or "book-tickets" in href.lower():
                    url = href if href.startswith("http") else f"https://in.bookmyshow.com{href}"
                    found.append({
                        "source": "bms_listing",
                        "title": text[:80],
                        "url": url,
                        "imax": CONFIG["show_type"].lower() in text.lower(),
                    })
                    log.info("Found booking link: %s", url)
                else:
                    log.info("Movie mentioned (no booking link yet): %s", text[:80])

    except Exception as e:
        log.error("BMS listing scrape failed: %s", e)

    # Try 2: BMS search page
    if not found:
        try:
            search_url = "https://in.bookmyshow.com/search"
            params = {"q": CONFIG["movie_name"], "city": CONFIG["city"]}
            resp = requests.get(search_url, headers=HEADERS, params=params, timeout=20)
            soup = BeautifulSoup(resp.text, "lxml")

            for tag in soup.find_all("a", href=True):
                href = tag["href"]
                text = tag.get_text(" ", strip=True)
                if "buytickets" in href and CONFIG["movie_name"].lower() in (href + text).lower():
                    url = href if href.startswith("http") else f"https://in.bookmyshow.com{href}"
                    found.append({
                        "source": "bms_search",
                        "title": text[:80] or CONFIG["movie_name"],
                        "url": url,
                        "imax": CONFIG["show_type"].lower() in (href + text).lower(),
                    })

        except Exception as e:
            log.error("BMS search scrape failed: %s", e)

    # Try 3: Google search fallback
    if not found:
        try:
            log.info("Trying Google search fallback...")
            query = f"{CONFIG['movie_name']} IMAX Chennai bookmyshow book tickets"
            google_url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
            g_headers = {**HEADERS, "Referer": "https://www.google.com/"}
            resp = requests.get(google_url, headers=g_headers, timeout=20)
            soup = BeautifulSoup(resp.text, "lxml")

            for tag in soup.find_all("a", href=True):
                href = tag["href"]
                if "bookmyshow.com" in href and "buytickets" in href:
                    if href.startswith("/url?q="):
                        href = href.split("/url?q=")[1].split("&")[0]
                    found.append({
                        "source": "google",
                        "title": CONFIG["movie_name"],
                        "url": href,
                        "imax": True,
                    })
                    log.info("Found via Google: %s", href)

        except Exception as e:
            log.error("Google fallback failed: %s", e)

    return found

# ─── Ntfy Notification ─────────────────────────────────────────────────────────

def send_ntfy_alert(results: list[dict]):
    topic = CONFIG["ntfy_topic"]
    movie = CONFIG["movie_name"]

    if not topic:
        log.warning("NTFY_TOPIC not set — would have sent alert:")
        for r in results:
            log.info("  %s | %s", r.get("title"), r.get("url"))
        return False

    imax_results = [r for r in results if r.get("imax")]
    best = imax_results[0] if imax_results else results[0]
    booking_url = best.get("url", "https://in.bookmyshow.com/chennai/movies")

    body = (
        f"Booking is OPEN in Chennai!\n"
        f"Format: {CONFIG['show_type']}\n"
        f"Detected: {datetime.utcnow().strftime('%d %b %Y %H:%M UTC')}"
    )

    try:
        resp = requests.post(
            f"https://ntfy.sh/{topic}",
            headers={
                "Title": f"🎬 {movie} — IMAX Tickets Live!",
                "Priority": "urgent",
                "Tags": "movie_camera,rotating_light",
                "Click": booking_url,
            },
            data=body.encode("utf-8"),
            timeout=10,
        )
        resp.raise_for_status()
        log.info("✅ Ntfy alert sent to topic '%s'!", topic)
        return True
    except requests.RequestException as e:
        log.error("Failed to send ntfy alert: %s", e)
        return False


def send_ntfy_heartbeat():
    topic = CONFIG["ntfy_topic"]
    if not topic or datetime.utcnow().hour != 9:
        return
    try:
        requests.post(
            f"https://ntfy.sh/{topic}",
            headers={
                "Title": "🤖 BMS Alert Bot — Still Running",
                "Priority": "low",
                "Tags": "white_check_mark",
            },
            data=(
                f"Monitoring: {CONFIG['movie_name']} ({CONFIG['show_type']}) in Chennai\n"
                f"{datetime.utcnow().strftime('%d %b %Y %H:%M UTC')}"
            ).encode("utf-8"),
            timeout=10,
        )
    except Exception:
        pass

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("BMS IMAX Alert Check — %s", datetime.utcnow().isoformat())
    log.info("Movie: %s | Format: %s | City: Chennai", CONFIG["movie_name"], CONFIG["show_type"])
    log.info("=" * 60)

    state = load_state()
    already_alerted = set(state.get("alerted_hashes", []))

    results = check_bms_for_movie()
    log.info("Total booking results found: %d", len(results))

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

    log.info("🚨 NEW bookings detected: %d", len(new_results))
    sent = send_ntfy_alert(new_results)

    if sent:
        for r in new_results:
            already_alerted.add(r["_hash"])
        state["alerted_hashes"] = list(already_alerted)

    save_state(state)
    log.info("Done.")


if __name__ == "__main__":
    main()
