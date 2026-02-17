#!/usr/bin/env python3
"""
CS2 Match Predictor — Main Entry Point.

Usage:
    python run.py              — Start web server
    python run.py seed         — Seed database with sample data
    python run.py train        — Train the ML model
    python run.py collect      — Collect data from PandaScore API
    python run.py reset        — Clear matches, keep teams/rankings, collect real data
    python run.py predict      — Quick CLI prediction
"""

import sys
import os
import logging

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def cmd_serve():
    """Start the web server."""
    from web.app import create_app
    from config.settings import FLASK_HOST, FLASK_PORT
    app = create_app()
    logger.info("Starting CS2 Predictor web server on http://%s:%d", FLASK_HOST, FLASK_PORT)
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True)


def cmd_seed():
    """Seed the database with sample data."""
    from scripts.seed_data import run_seed
    run_seed()


def cmd_train():
    """Train the prediction model."""
    from data.database import init_db
    from models.predictor import CSPredictor
    init_db()
    predictor = CSPredictor()
    result = predictor.train()
    if result:
        logger.info("Training complete!")
        logger.info("Temporal CV Accuracy: %.1f%%", result["temporal_cv_accuracy"] * 100)
        logger.info("Temporal CV Brier Score: %.4f", result["temporal_cv_brier"])
        logger.info("Samples: %d | Features: %d", result["n_samples"], result["n_features"])
        logger.info("Fold details:")
        for fold in result["fold_results"]:
            logger.info("  Fold %d: acc=%.1f%% brier=%.4f (n=%d)",
                        fold["fold"], fold["accuracy"] * 100, fold["brier"], fold["test_size"])
        logger.info("Feature importance (top 15):")
        for feat, imp in sorted(result["feature_importance"].items(), key=lambda x: -x[1])[:15]:
            logger.info("  %-30s %.4f", feat, imp)
    else:
        logger.warning("Training failed — not enough data.")


def cmd_collect():
    """Collect data from PandaScore API."""
    from data.collector import collect_all
    from models.rating_systems import recalculate_all_ratings
    collect_all()
    recalculate_all_ratings()
    logger.info("Data collection and rating recalculation complete.")


def cmd_reset():
    """Clear synthetic matches but keep team data (rankings, players), then collect real matches."""
    from data.database import init_db, get_connection
    from scripts.seed_data import seed_teams, seed_players, seed_map_stats
    from data.collector import fetch_results, store_results, fetch_matches
    from models.rating_systems import recalculate_all_ratings

    init_db()
    conn = get_connection()

    # Clear matches, ratings, predictions — but keep teams and players
    for table in ["predictions", "team_map_ratings", "team_ratings",
                   "map_stats", "matches"]:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()

    # Re-seed teams and players if empty (preserves HLTV rankings)
    team_count = conn.execute("SELECT COUNT(*) as c FROM teams").fetchone()["c"]
    if team_count == 0:
        seed_teams(conn)
        seed_players(conn)

    conn.close()
    logger.info("Matches cleared. Collecting real match data...")

    # Collect real data only (no seed matches)
    results = fetch_results()
    if results:
        store_results(results)

    # Liquipedia
    try:
        from data.liquipedia import collect_liquipedia
        collect_liquipedia()
    except Exception as e:
        logger.warning("Liquipedia collection skipped: %s", e)

    # Recalculate ratings from real matches
    recalculate_all_ratings()

    # Fetch upcoming matches
    upcoming = fetch_matches()
    logger.info("Found %d upcoming matches", len(upcoming))
    logger.info("Reset complete — real matches only, team rankings preserved.")


def cmd_predict():
    """Interactive CLI prediction."""
    from data.database import init_db, get_connection
    from models.predictor import get_predictor
    init_db()

    conn = get_connection()
    teams = conn.execute(
        "SELECT id, name, world_ranking FROM teams ORDER BY world_ranking ASC NULLS LAST LIMIT 65"
    ).fetchall()
    conn.close()

    if not teams:
        logger.error("No teams in database. Run 'python run.py seed' first.")
        return

    print("\nAvailable teams:")
    for t in teams:
        rank = f"#{t['world_ranking']}" if t['world_ranking'] else "N/R"
        print(f"  [{t['id']:3d}] {t['name']:<25s} ({rank})")

    try:
        t1 = int(input("\nTeam 1 ID: "))
        t2 = int(input("Team 2 ID: "))
    except (ValueError, EOFError):
        print("Invalid input.")
        return

    predictor = get_predictor()
    result = predictor.predict(t1, t2)

    print(f"\n{'='*50}")
    print(f" {result['team1']['name']} vs {result['team2']['name']}")
    print(f"{'='*50}")
    print(f" {result['team1']['name']}: {result['team1']['win_prob']*100:.1f}%")
    print(f" {result['team2']['name']}: {result['team2']['win_prob']*100:.1f}%")
    print(f"\n Predicted Winner: {result['predicted_winner']}")
    print(f" Confidence: {result['confidence_label']} ({result['confidence']*100:.1f}%)")
    print(f" Method: {result['method']}")
    print(f"\n Analysis:")
    for point in result['analysis']:
        print(f"   - {point}")
    print()


def main():
    if len(sys.argv) < 2:
        cmd_serve()
        return

    command = sys.argv[1].lower()
    commands = {
        "serve": cmd_serve,
        "seed": cmd_seed,
        "train": cmd_train,
        "collect": cmd_collect,
        "reset": cmd_reset,
        "predict": cmd_predict,
    }

    if command in commands:
        commands[command]()
    else:
        print(f"Unknown command: {command}")
        print(f"Available commands: {', '.join(commands.keys())}")
        sys.exit(1)


if __name__ == "__main__":
    main()
