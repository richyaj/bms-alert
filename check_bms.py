"""
BookMyShow IMAX Alert System
Checks for IMAX bookings for a specific movie in Chennai and sends Telegram alerts.
"""

import os
import json
import time
import hashlib
import logging
import requests
from datetime import datetime
from typing import Optional

# ─── Configuration ────────────────────────────────────────────────────────────

CONFIG = {
    "movie_name": "Project Hail Mary",
    "city_code": "CHEN",          # Chennai BMS city code
    "city_name": "Chennai",
    "show_type": "IMAX",          # Alert keyword to look for
    "ntfy_topic": os.environ.get("NTFY_TOPIC", "bms-imax-alert-chennai"),
    # State file path — in GitHub Actions use a gist or artifact; locally just a file
    "state_file": "alert_state.json",
    # BMS API endpoints (public, no auth required)
    "bms_search_url": "https://in.bookmyshow.com/api/explore/v1/discover/movies",
    "bms_event_url": "https://in.bookmyshow.com/buytickets/{event_code}/movie-{city}-{date}/",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://in.bookmyshow.com/",
    "X-Region-Code": "CHEN",
    "X-Region-Slug": "chennai",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── State Management (prevent duplicate alerts) ───────────────────────────────

def load_state() -> dict:
    """Load persisted state (which alerts have already been sent)."""
    # GitHub Actions: read from environment variable set by gist-based state
    state_json = os.environ.get("ALERT_STATE_JSON", "")
    if state_json:
        try:
            return json.loads(state_json)
        except json.JSONDecodeError:
            pass

    if os.path.exists(CONFIG["state_file"]):
        with open(CONFIG["state_file"], "r") as f:
            return json.load(f)

    return {"alerted_shows": [], "last_check": None}


def save_state(state: dict):
    """Save state to local file (GitHub Actions artifact handles persistence)."""
    state["last_check"] = datetime.utcnow().isoformat()
    with open(CONFIG["state_file"], "w") as f:
        json.dump(state, f, indent=2)
    log.info("State saved to %s", CONFIG["state_FILE"] if False else CONFIG["state_file"])
    # Also print for GitHub Actions to capture as output
    print(f"::set-output name=alert_state::{json.dumps(state)}")


def make_show_id(show: dict) -> str:
    """Create a unique ID for a show to track duplicates."""
    key = f"{show.get('EventCode','')}-{show.get('ShowType','')}-{show.get('Date','')}"
    return hashlib.md5(key.encode()).hexdigest()

# ─── BookMyShow API Calls ──────────────────────────────────────────────────────

def search_movie(movie_name: str, city_code: str) -> Optional[dict]:
    """Search for a movie by name in a city using BMS's internal API."""
    url = "https://in.bookmyshow.com/api/explore/v1/discover/movies"
    params = {
        "appCode": "MOBAND2",
        "appVersion": "14.3.4",
        "language": "en",
        "region": city_code,
        "regionCode": city_code,
        "subRegion": city_code,
        "bmsId": "1.21.1",
        "token": "",
        "lat": "13.0827",
        "lon": "80.2707",
        "page": "1",
        "limit": "10",
    }

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        movies = (
            data.get("BookMyShow", {})
                .get("arrEvents", [])
        )

        for movie in movies:
            name = movie.get("EventTitle", "")
            if movie_name.lower() in name.lower():
                log.info("Found movie: %s (Code: %s)", name, movie.get("EventCode"))
                return movie

        log.info("Movie '%s' not found in current listings.", movie_name)
        return None

    except requests.RequestException as e:
        log.error("Error searching for movie: %s", e)
        return None


def get_movie_shows(event_code: str, city_code: str) -> list[dict]:
    """Get show listings for a specific movie event code."""
    today = datetime.now().strftime("%Y%m%d")
    url = f"https://in.bookmyshow.com/api/movies-data/showtimes-by-event"

    params = {
        "appCode": "MOBAND2",
        "appVersion": "14.3.4",
        "language": "en",
        "bmsId": "1.21.1",
        "region": city_code,
        "regionCode": city_code,
        "eventCode": event_code,
        "ShowDate": today,
        "pageCount": "1",
        "token": "",
    }

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        shows = data.get("ShowDetails", [])
        log.info("Retrieved %d venue/show groups", len(shows))
        return shows

    except requests.RequestException as e:
        log.error("Error fetching showtimes: %s", e)
        return []


def find_imax_shows(shows: list[dict], show_type_keyword: str) -> list[dict]:
    """Filter shows to only IMAX (or whichever format specified)."""
    imax_shows = []

    for venue_group in shows:
        venue_name = venue_group.get("VenueName", "Unknown Venue")
        venue_code = venue_group.get("VenueCode", "")

        for show_time_group in venue_group.get("ShowTimeList", []):
            for show in show_time_group.get("ShowTimes", []):
                show_name = (
                    show.get("ShowType", "")
                    + " " + show.get("ShowExperience", "")
                    + " " + show.get("ScreenName", "")
                ).upper()

                if show_type_keyword.upper() in show_name:
                    # Check booking is actually open
                    booking_open = show.get("IsAvailable", False) or \
                                   show.get("ShowStatus", "") in ("OPEN", "BOOK")

                    imax_shows.append({
                        "VenueName": venue_name,
                        "VenueCode": venue_code,
                        "ShowType": show.get("ShowType", ""),
                        "ShowExperience": show.get("ShowExperience", ""),
                        "ShowTime": show.get("ShowTime", ""),
                        "Date": show.get("ShowDate", datetime.now().strftime("%Y%m%d")),
                        "BookingOpen": booking_open,
                        "ShowId": show.get("ShowId", ""),
                        "EventCode": show.get("EventCode", ""),
                    })

    return imax_shows

# ─── BMS HTML Fallback Scraper ─────────────────────────────────────────────────

def scrape_bms_page_fallback(movie_name: str, city: str, show_type: str) -> list[dict]:
    """
    Fallback: directly scrape the BMS search page if API fails.
    Returns mock-structured data for IMAX show detection.
    """
    try:
        from bs4 import BeautifulSoup

        search_url = f"https://in.bookmyshow.com/{city.lower()}/movies"
        resp = requests.get(search_url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")

        found = []
        # Look for movie cards containing the movie name and IMAX badge
        for card in soup.select("[class*='movie-card'], [class*='__name'], a[href*='buytickets']"):
            text = card.get_text(" ", strip=True)
            href = card.get("href", "")
            if movie_name.lower() in text.lower() and show_type.upper() in text.upper():
                found.append({
                    "VenueName": "See booking link",
                    "ShowType": show_type,
                    "ShowTime": "Check link",
                    "Date": datetime.now().strftime("%Y%m%d"),
                    "BookingOpen": True,
                    "BookingURL": f"https://in.bookmyshow.com{href}" if href.startswith("/") else href,
                })

        return found

    except Exception as e:
        log.error("HTML fallback scraper failed: %s", e)
        return []

# ─── Telegram Notifications ────────────────────────────────────────────────────

def send_ntfy_alert(shows: list[dict], movie_name: str):
    topic = CONFIG["ntfy_topic"]
    venue_list = ", ".join(s.get("VenueName", "Theatre") for s in shows[:3])
    
    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        headers={
            "Title": f"🎬 IMAX Booking Open — {movie_name}!",
            "Priority": "urgent",
            "Tags": "movie_camera,rotating_light",
            "Click": "https://in.bookmyshow.com/chennai/movies",
        },
        data=f"IMAX shows now bookable in Chennai!\nVenues: {venue_list}\nBook at: https://in.bookmyshow.com/chennai/movies".encode("utf-8"),
        timeout=10,
    )
    return resp.status_code == 200


def send_telegram_heartbeat():
    """Optional: send a daily heartbeat so you know the bot is running."""
    token = CONFIG["telegram_bot_token"]
    chat_id = CONFIG["telegram_chat_id"]
    if not token or not chat_id:
        return

    hour = datetime.utcnow().hour
    # Only send heartbeat once per day around 09:00 UTC (14:30 IST)
    if hour != 9:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": (
            f"🤖 BMS Alert Bot is running\n"
            f"Monitoring: *{CONFIG['movie_name']}* ({CONFIG['show_type']}) in {CONFIG['city_name']}\n"
            f"Time: {datetime.utcnow().strftime('%d %b %Y %H:%M UTC')}"
        ),
        "parse_mode": "Markdown",
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass

# ─── Main Logic ────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("BookMyShow IMAX Alert — %s", datetime.utcnow().isoformat())
    log.info("Movie: %s | City: %s | Format: %s",
             CONFIG["movie_name"], CONFIG["city_name"], CONFIG["show_type"])
    log.info("=" * 60)

    state = load_state()
    already_alerted = set(state.get("alerted_shows", []))

    # ── Step 1: Search for the movie ──
    movie = search_movie(CONFIG["movie_name"], CONFIG["city_code"])

    imax_shows = []

    if movie:
        event_code = movie.get("EventCode", "")
        log.info("Event code: %s", event_code)

        # ── Step 2: Fetch showtimes ──
        shows = get_movie_shows(event_code, CONFIG["city_code"])

        # ── Step 3: Filter for IMAX ──
        imax_shows = find_imax_shows(shows, CONFIG["show_type"])
        log.info("IMAX shows found via API: %d", len(imax_shows))
    else:
        log.info("Movie not in API listings yet. Trying HTML fallback...")
        imax_shows = scrape_bms_page_fallback(
            CONFIG["movie_name"], CONFIG["city_name"], CONFIG["show_type"]
        )
        log.info("IMAX shows found via HTML fallback: %d", len(imax_shows))

    if not imax_shows:
        log.info("No IMAX shows found. Booking not open yet. Will check again later.")
        send_telegram_heartbeat()
        save_state(state)
        return

    # ── Step 4: Filter out already-alerted shows ──
    new_shows = []
    for show in imax_shows:
        show_id = make_show_id(show)
        if show_id not in already_alerted:
            show["_id"] = show_id
            new_shows.append(show)

    if not new_shows:
        log.info("IMAX shows found but already alerted. No duplicate notification sent.")
        save_state(state)
        return

    log.info("🚨 NEW IMAX shows detected: %d", len(new_shows))

    # ── Step 5: Send alert ──
    sent = send_ntfy_alert(new_shows, CONFIG["movie_name"])

    if sent:
        # Mark these shows as alerted
        for show in new_shows:
            already_alerted.add(show["_id"])
        state["alerted_shows"] = list(already_alerted)

    save_state(state)
    log.info("Done.")


if __name__ == "__main__":
    main()
