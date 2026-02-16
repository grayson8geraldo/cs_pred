"""Data collector: fetches match data from HLTV API and stores in database."""

import time
import logging
import requests
from datetime import datetime, timedelta

from data.database import get_connection, init_db
from config.settings import HLTV_API_BASE

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _api_get(endpoint, retries=3, delay=2):
    """Make a GET request to the HLTV API with retries."""
    url = f"{HLTV_API_BASE}{endpoint}"
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("API %s returned %d", url, resp.status_code)
        except requests.RequestException as e:
            logger.warning("API request failed (attempt %d): %s", attempt + 1, e)
        time.sleep(delay * (attempt + 1))
    return None


def _get_or_create_team(conn, name, hltv_id=None):
    """Get team ID by name, or create if doesn't exist."""
    row = conn.execute(
        "SELECT id FROM teams WHERE name = ?", (name,)
    ).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO teams (name, hltv_id) VALUES (?, ?)",
        (name, hltv_id),
    )
    conn.commit()
    return cursor.lastrowid


def fetch_results():
    """Fetch recent match results from HLTV API."""
    data = _api_get("/api/results")
    if not data:
        logger.error("Failed to fetch results")
        return []
    return data


def fetch_matches():
    """Fetch upcoming matches from HLTV API."""
    data = _api_get("/api/matches")
    if not data:
        logger.error("Failed to fetch upcoming matches")
        return []
    return data


def fetch_top_teams():
    """Fetch HLTV top teams ranking."""
    data = _api_get("/api/ranking")
    if not data:
        logger.error("Failed to fetch top teams")
        return []
    return data


def store_results(results):
    """Parse and store match results in the database."""
    conn = get_connection()
    stored = 0
    for match in results:
        try:
            team1_name = match.get("team1", {}).get("name") if isinstance(match.get("team1"), dict) else match.get("team1")
            team2_name = match.get("team2", {}).get("name") if isinstance(match.get("team2"), dict) else match.get("team2")
            if not team1_name or not team2_name:
                continue

            team1_id = _get_or_create_team(conn, team1_name)
            team2_id = _get_or_create_team(conn, team2_name)

            # Parse scores
            result_text = match.get("result", "")
            team1_score, team2_score = 0, 0
            if isinstance(result_text, str) and " - " in result_text:
                parts = result_text.split(" - ")
                try:
                    team1_score = int(parts[0].strip())
                    team2_score = int(parts[1].strip())
                except (ValueError, IndexError):
                    pass

            winner_id = team1_id if team1_score > team2_score else team2_id

            # Match date
            match_date = match.get("date")
            if isinstance(match_date, (int, float)):
                match_date = datetime.fromtimestamp(match_date / 1000).isoformat()
            elif not match_date:
                match_date = datetime.utcnow().isoformat()

            event_name = match.get("event", {}).get("name") if isinstance(match.get("event"), dict) else match.get("event", "")

            hltv_id = match.get("matchId") or match.get("id")

            # Insert match
            conn.execute("""
                INSERT OR IGNORE INTO matches
                    (hltv_id, team1_id, team2_id, team1_score, team2_score,
                     winner_id, event_name, match_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (hltv_id, team1_id, team2_id, team1_score, team2_score,
                  winner_id, event_name, match_date))
            stored += 1
        except Exception as e:
            logger.error("Error storing match: %s", e)
            continue

    conn.commit()
    conn.close()
    logger.info("Stored %d match results", stored)
    return stored


def store_rankings(rankings):
    """Store team rankings in the database."""
    conn = get_connection()
    for entry in rankings:
        try:
            team_name = entry.get("team", {}).get("name") if isinstance(entry.get("team"), dict) else entry.get("team")
            if not team_name:
                continue
            rank = entry.get("ranking") or entry.get("rank") or entry.get("position")
            team_id = _get_or_create_team(conn, team_name)
            conn.execute(
                "UPDATE teams SET world_ranking = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (rank, team_id),
            )
        except Exception as e:
            logger.error("Error storing ranking: %s", e)
    conn.commit()
    conn.close()


def collect_all():
    """Run full data collection cycle."""
    init_db()
    logger.info("Starting data collection...")

    results = fetch_results()
    if results:
        store_results(results)

    rankings = fetch_top_teams()
    if rankings:
        store_rankings(rankings)

    upcoming = fetch_matches()
    logger.info("Found %d upcoming matches", len(upcoming))
    return upcoming


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collect_all()
