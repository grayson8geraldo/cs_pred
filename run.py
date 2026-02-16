#!/usr/bin/env python3
"""
CS2 Match Predictor — Main Entry Point.

Usage:
    python run.py              — Start web server
    python run.py seed         — Seed database with sample data
    python run.py train        — Train the ML model
    python run.py collect      — Collect data from HLTV API
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
    app = create_app()
    logger.info("Starting CS2 Predictor web server on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)


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
        logger.info("CV Accuracy: %.1f%% (+/- %.1f%%)", result["cv_accuracy"] * 100, result["cv_std"] * 100)
        logger.info("Samples: %d", result["n_samples"])
        logger.info("Feature importance:")
        for feat, imp in sorted(result["feature_importance"].items(), key=lambda x: -x[1]):
            logger.info("  %-25s %.4f", feat, imp)
    else:
        logger.warning("Training failed — not enough data.")


def cmd_collect():
    """Collect data from HLTV API."""
    from data.collector import collect_all
    from models.rating_systems import recalculate_all_ratings
    collect_all()
    recalculate_all_ratings()
    logger.info("Data collection and rating recalculation complete.")


def cmd_predict():
    """Interactive CLI prediction."""
    from data.database import init_db, get_connection
    from models.predictor import get_predictor
    init_db()

    conn = get_connection()
    teams = conn.execute(
        "SELECT id, name, world_ranking FROM teams ORDER BY world_ranking ASC NULLS LAST LIMIT 30"
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
