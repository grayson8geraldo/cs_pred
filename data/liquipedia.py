"""
Liquipedia data collector for CS2 match results.

Uses the Liquipedia API (MediaWiki Cargo queries) to fetch historical
match results from major tournaments. This supplements PandaScore data
with deeper tournament history.

Liquipedia API docs: https://liquipedia.net/commons/Liquipedia:API_Usage_Guidelines
Rate limit: 1 request per 2 seconds (we use 2.5s to be safe).
"""

import time
import logging
import requests
from datetime import datetime

from data.database import get_connection

logger = logging.getLogger(__name__)

LIQUIPEDIA_API = "https://liquipedia.net/counterstrike/api.php"
USER_AGENT = "CS2MatchPredictor/1.0 (educational project)"

# Rate limit: max 1 request per 2 seconds per Liquipedia guidelines
REQUEST_DELAY = 2.5


def _lp_cargo_query(tables, fields, where="", order="", limit=100, offset=0):
    """Execute a Cargo query against the Liquipedia API."""
    params = {
        "action": "cargoquery",
        "format": "json",
        "tables": tables,
        "fields": fields,
        "limit": limit,
        "offset": offset,
    }
    if where:
        params["where"] = where
    if order:
        params["order_by"] = order

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    try:
        resp = requests.get(LIQUIPEDIA_API, params=params, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("cargoquery", [])
            return [r.get("title", {}) for r in results]
        logger.warning("Liquipedia API returned %d: %s", resp.status_code, resp.text[:200])
    except requests.RequestException as e:
        logger.warning("Liquipedia request failed: %s", e)
    return []


def _get_or_create_team(conn, name):
    """Get team ID by name, or create if doesn't exist."""
    if not name or name.strip() == "":
        return None
    name = name.strip()
    row = conn.execute("SELECT id FROM teams WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO teams (name, updated_at) VALUES (?, CURRENT_TIMESTAMP)", (name,)
    )
    conn.commit()
    return cursor.lastrowid


def fetch_liquipedia_matches(limit=500):
    """Fetch CS2 match results from Liquipedia Cargo tables.

    Queries the MatchSchedule table for completed CS2 matches
    with known results.
    """
    all_results = []
    offset = 0
    batch_size = 100

    while offset < limit:
        logger.info("Fetching Liquipedia matches (offset %d)...", offset)

        rows = _lp_cargo_query(
            tables="MatchSchedule",
            fields=(
                "Team1, Team2, Winner, Team1Score, Team2Score, "
                "BestOf, DateTime_UTC, MatchPage, Tournament, "
                "Team1Score__exact, Team2Score__exact"
            ),
            where=(
                "Winner IS NOT NULL AND Winner != '' "
                "AND Team1 IS NOT NULL AND Team1 != '' "
                "AND Team2 IS NOT NULL AND Team2 != '' "
                "AND DateTime_UTC >= '2024-01-01'"
            ),
            order="DateTime_UTC DESC",
            limit=batch_size,
            offset=offset,
        )

        if not rows:
            break
        all_results.extend(rows)
        offset += batch_size

        if len(rows) < batch_size:
            break
        time.sleep(REQUEST_DELAY)

    logger.info("Fetched %d matches from Liquipedia", len(all_results))
    return all_results


def store_liquipedia_matches(matches):
    """Store Liquipedia match results in the database."""
    conn = get_connection()
    stored = 0
    skipped = 0

    for match in matches:
        try:
            team1_name = match.get("Team1", "").strip()
            team2_name = match.get("Team2", "").strip()
            winner_name = match.get("Winner", "").strip()

            if not team1_name or not team2_name or not winner_name:
                skipped += 1
                continue

            team1_id = _get_or_create_team(conn, team1_name)
            team2_id = _get_or_create_team(conn, team2_name)
            if not team1_id or not team2_id:
                skipped += 1
                continue

            # Determine winner
            if winner_name == team1_name:
                winner_id = team1_id
            elif winner_name == team2_name:
                winner_id = team2_id
            else:
                # Winner name might be slightly different, try matching
                winner_id = _get_or_create_team(conn, winner_name)

            # Scores
            try:
                team1_score = int(match.get("Team1Score", 0) or 0)
                team2_score = int(match.get("Team2Score", 0) or 0)
            except (ValueError, TypeError):
                team1_score, team2_score = 0, 0

            # Match date
            match_date = match.get("DateTime UTC", "") or match.get("DateTime_UTC", "")
            if not match_date:
                continue

            # Best-of
            try:
                best_of = int(match.get("BestOf", 1) or 1)
            except (ValueError, TypeError):
                best_of = 1

            # Event name
            event_name = match.get("Tournament", "") or ""

            # Use MatchPage as unique ID to avoid duplicates
            match_page = match.get("MatchPage", "")
            lp_id = f"lp_{match_page}" if match_page else f"lp_{team1_name}_{team2_name}_{match_date}"

            conn.execute("""
                INSERT OR IGNORE INTO matches
                    (hltv_id, team1_id, team2_id, team1_score, team2_score,
                     winner_id, event_name, match_date, best_of)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (lp_id, team1_id, team2_id, team1_score, team2_score,
                  winner_id, event_name, match_date, best_of))
            stored += 1

        except Exception as e:
            logger.error("Error storing Liquipedia match: %s", e)
            skipped += 1
            continue

    conn.commit()
    conn.close()
    logger.info("Stored %d Liquipedia matches (%d skipped)", stored, skipped)
    return stored


def collect_liquipedia():
    """Run Liquipedia data collection."""
    logger.info("Collecting match data from Liquipedia...")
    matches = fetch_liquipedia_matches(limit=500)
    if matches:
        stored = store_liquipedia_matches(matches)
        return stored
    return 0
