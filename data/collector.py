"""Data collector: fetches CS2 match data from PandaScore API and stores in database."""

import time
import logging
import requests
from datetime import datetime

from data.database import get_connection, init_db
from config.settings import PANDASCORE_BASE, PANDASCORE_TOKEN

logger = logging.getLogger(__name__)


def _api_get(endpoint, params=None, retries=3, delay=2, filter_cs2=True):
    """Make a GET request to the PandaScore API with retries."""
    if not PANDASCORE_TOKEN:
        logger.error(
            "PANDASCORE_TOKEN not set. "
            "Register at https://pandascore.co and set the env var: "
            "export PANDASCORE_TOKEN=your_token_here"
        )
        return None

    url = f"{PANDASCORE_BASE}{endpoint}"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {PANDASCORE_TOKEN}",
    }
    if params is None:
        params = {}
    # Filter to CS2 only where supported (matches, not teams)
    if filter_cs2:
        params.setdefault("filter[videogame_title]", "cs-2")

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401:
                logger.error("PandaScore auth failed — check PANDASCORE_TOKEN")
                return None
            if resp.status_code == 429:
                logger.warning("Rate limited, waiting %ds...", delay * (attempt + 2))
                time.sleep(delay * (attempt + 2))
                continue
            logger.warning("API %s returned %d", url, resp.status_code)
        except requests.RequestException as e:
            logger.warning("API request failed (attempt %d): %s", attempt + 1, e)
        time.sleep(delay * (attempt + 1))
    return None


def _get_or_create_team(conn, name, pandascore_id=None):
    """Get team ID by name, or create if doesn't exist."""
    row = conn.execute(
        "SELECT id FROM teams WHERE name = ?", (name,)
    ).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO teams (name, hltv_id) VALUES (?, ?)",
        (name, pandascore_id),
    )
    conn.commit()
    return cursor.lastrowid


def _parse_opponents(match):
    """Extract team1 and team2 names and IDs from PandaScore match data."""
    opponents = match.get("opponents", [])
    if len(opponents) < 2:
        return None, None, None, None
    t1 = opponents[0].get("opponent", {})
    t2 = opponents[1].get("opponent", {})
    return t1.get("name"), t1.get("id"), t2.get("name"), t2.get("id")


def _parse_scores(match):
    """Extract team scores from PandaScore results array."""
    results = match.get("results", [])
    if len(results) >= 2:
        return results[0].get("score", 0), results[1].get("score", 0)
    return 0, 0


def fetch_results(page_size=100, pages=15):
    """Fetch recent finished CS2 matches from PandaScore.

    Default: 15 pages x 100 = up to 1500 matches.
    PandaScore free tier allows 1000 requests/hour, so this is safe.
    """
    all_matches = []
    for page in range(1, pages + 1):
        logger.info("Fetching PandaScore results page %d/%d...", page, pages)
        data = _api_get("/csgo/matches/past", params={
            "page[size]": page_size,
            "page[number]": page,
            "sort": "-begin_at",
        })
        if not data:
            break
        all_matches.extend(data)
        if len(data) < page_size:
            break
        # Small delay to be polite to API
        time.sleep(0.3)
    logger.info("Fetched %d finished matches from PandaScore", len(all_matches))
    return all_matches


def fetch_matches():
    """Fetch upcoming CS2 matches from PandaScore."""
    data = _api_get("/csgo/matches/upcoming", params={
        "page[size]": 50,
        "sort": "begin_at",
    })
    if not data:
        logger.error("Failed to fetch upcoming matches")
        return []
    logger.info("Fetched %d upcoming matches from PandaScore", len(data))
    return data


def fetch_top_teams():
    """Fetch CS2 teams from PandaScore, sorted to approximate rankings."""
    all_teams = []
    for page in range(1, 3):
        data = _api_get("/csgo/teams", params={
            "page[size]": 50,
            "page[number]": page,
        }, filter_cs2=False)
        if not data:
            break
        all_teams.extend(data)
        if len(data) < 50:
            break
    logger.info("Fetched %d teams from PandaScore", len(all_teams))
    return all_teams


def store_results(results):
    """Parse and store PandaScore match results in the database."""
    conn = get_connection()
    stored = 0
    for match in results:
        try:
            team1_name, t1_ps_id, team2_name, t2_ps_id = _parse_opponents(match)
            if not team1_name or not team2_name:
                continue

            team1_id = _get_or_create_team(conn, team1_name, t1_ps_id)
            team2_id = _get_or_create_team(conn, team2_name, t2_ps_id)

            team1_score, team2_score = _parse_scores(match)

            # Determine winner
            winner_ps_id = match.get("winner_id")
            winner = match.get("winner") or {}
            if winner_ps_id and winner_ps_id == t1_ps_id:
                winner_id = team1_id
            elif winner_ps_id and winner_ps_id == t2_ps_id:
                winner_id = team2_id
            elif team1_score > team2_score:
                winner_id = team1_id
            elif team2_score > team1_score:
                winner_id = team2_id
            else:
                winner_id = None

            # Match date (ISO-8601)
            match_date = match.get("begin_at") or match.get("scheduled_at")
            if not match_date:
                match_date = datetime.utcnow().isoformat()

            # Event / tournament info
            tournament = match.get("tournament") or {}
            league = match.get("league") or {}
            event_name = tournament.get("name") or league.get("name") or ""
            if league.get("name") and tournament.get("name"):
                event_name = f"{league['name']}: {tournament['name']}"

            # Best-of format
            best_of = match.get("number_of_games", 1) or 1

            # Map info from games
            map_name = None
            games = match.get("games") or []
            if len(games) == 1 and games[0].get("map", {}).get("name"):
                map_name = games[0]["map"]["name"]

            ps_match_id = match.get("id")

            conn.execute("""
                INSERT OR IGNORE INTO matches
                    (hltv_id, team1_id, team2_id, team1_score, team2_score,
                     winner_id, event_name, match_date, best_of, map_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ps_match_id, team1_id, team2_id, team1_score, team2_score,
                  winner_id, event_name, match_date, best_of, map_name))
            stored += 1
        except Exception as e:
            logger.error("Error storing match: %s", e)
            continue

    conn.commit()
    conn.close()
    logger.info("Stored %d match results", stored)
    return stored


def store_rankings(teams):
    """Store team metadata from PandaScore (logo, country).

    NOTE: Does NOT overwrite world_ranking if it already exists,
    since PandaScore rankings are approximated and less accurate
    than HLTV rankings (set by seed_data or HLTV collector).
    """
    conn = get_connection()
    for entry in teams:
        try:
            team_name = entry.get("name")
            if not team_name:
                continue
            ps_id = entry.get("id")
            location = entry.get("location")
            image_url = entry.get("image_url")

            team_id = _get_or_create_team(conn, team_name, ps_id)

            updates = ["updated_at = CURRENT_TIMESTAMP"]
            params = []

            if location:
                updates.append("country = COALESCE(country, ?)")
                params.append(location)
            if image_url:
                updates.append("logo_url = ?")
                params.append(image_url)

            # Only set ranking if team has none (don't overwrite HLTV data)
            # PandaScore order is NOT the same as HLTV world ranking
            params.append(team_id)

            conn.execute(
                f"UPDATE teams SET {', '.join(updates)} WHERE id = ?",
                params,
            )
        except Exception as e:
            logger.error("Error storing team: %s", e)
    conn.commit()
    conn.close()


def collect_all():
    """Run full data collection: HLTV (optional) + PandaScore + Liquipedia."""
    init_db()

    # 1. Try HLTV for live rankings (may fail due to Cloudflare)
    try:
        from data.hltv import collect_hltv_rankings, collect_hltv_results
        logger.info("=== HLTV: Fetching real world rankings ===")
        collect_hltv_rankings()

        logger.info("=== HLTV: Fetching recent match results ===")
        collect_hltv_results(days=7, max_results=50)
    except Exception as e:
        logger.info("HLTV unavailable — using existing rankings: %s", e)

    # 2. PandaScore: match results (large historical dataset — main source)
    logger.info("=== PandaScore: Fetching match history ===")
    results = fetch_results()
    if results:
        store_results(results)

    # 3. Liquipedia: additional match history
    try:
        from data.liquipedia import collect_liquipedia
        logger.info("=== Liquipedia: Fetching tournament results ===")
        collect_liquipedia()
    except Exception as e:
        logger.warning("Liquipedia collection failed (non-critical): %s", e)

    # 4. Upcoming matches (PandaScore — structured data)
    upcoming = fetch_matches()
    logger.info("Found %d upcoming matches from PandaScore", len(upcoming))

    return upcoming


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collect_all()
