#!/usr/bin/env python3
"""
CS2 Match Predictor — Main Entry Point.

Usage:
    python run.py              — Start web server
    python run.py seed         — Seed database with sample data
    python run.py train        — Train the ML model (stacking ensemble)
    python run.py tune         — Train with Optuna hyperparameter tuning
    python run.py collect      — Collect data from HLTV + PandaScore + Liquipedia
    python run.py reset        — Full reset: clear DB, rebuild from real data only
    python run.py predict      — Quick CLI prediction
    python run.py evaluate     — Full model evaluation (reliability + tier breakdown)
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


def cmd_train(use_optuna=False):
    """Train the prediction model."""
    from data.database import init_db
    from models.predictor import CSPredictor
    init_db()
    predictor = CSPredictor()
    result = predictor.train(use_optuna=use_optuna)
    if result:
        logger.info("Training complete!")
        logger.info("Temporal CV Accuracy: %.1f%%", result["temporal_cv_accuracy"] * 100)
        logger.info("Temporal CV Brier Score: %.4f", result["temporal_cv_brier"])
        if "calibrated_brier" in result:
            logger.info("Calibrated Brier Score: %.4f", result["calibrated_brier"])
        logger.info("Samples: %d | Features: %d | Base Models: %d",
                     result["n_samples"], result["n_features"], result["n_base_models"])
        if result.get("has_lgbm"):
            logger.info("LightGBM: enabled")
        if result.get("has_optuna"):
            logger.info("Optuna tuning: enabled")
        logger.info("Fold details:")
        for fold in result["fold_results"]:
            logger.info("  Fold %d: acc=%.1f%% brier=%.4f (n=%d)",
                        fold["fold"], fold["accuracy"] * 100, fold["brier"], fold["test_size"])
        logger.info("Feature importance (top 15):")
        for feat, imp in sorted(result["feature_importance"].items(), key=lambda x: -x[1])[:15]:
            logger.info("  %-35s %.4f", feat, imp)
    else:
        logger.warning("Training failed — not enough data.")


def cmd_collect():
    """Collect data from all sources (HLTV + PandaScore + Liquipedia)."""
    from data.collector import collect_all
    from models.rating_systems import recalculate_all_ratings
    collect_all()
    recalculate_all_ratings()
    logger.info("Data collection and rating recalculation complete.")


def cmd_reset():
    """Clear synthetic matches, keep team rankings, collect real match data only."""
    from data.database import init_db, get_connection
    from scripts.seed_data import seed_teams, seed_players
    from models.rating_systems import recalculate_all_ratings
    from config.settings import MODEL_PATH, FEATURE_COLUMNS_PATH, CALIBRATOR_PATH

    init_db()
    conn = get_connection()

    # Clear matches, ratings, predictions — but keep teams and players
    for table in ["predictions", "team_map_ratings", "team_ratings",
                   "map_stats", "matches"]:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()

    # Ensure teams with HLTV rankings exist
    team_count = conn.execute("SELECT COUNT(*) as c FROM teams").fetchone()["c"]
    if team_count == 0:
        seed_teams(conn)
        seed_players(conn)
        logger.info("Seeded %d teams with HLTV rankings", team_count)
    conn.close()

    # Delete old trained model
    for path in [MODEL_PATH, FEATURE_COLUMNS_PATH, CALIBRATOR_PATH]:
        if os.path.exists(path):
            os.remove(path)
            logger.info("Removed old model: %s", path)

    # Try HLTV for live rankings update
    try:
        from data.hltv import collect_hltv_rankings
        logger.info("=== Step 1: Updating rankings from HLTV ===")
        collect_hltv_rankings()
    except Exception as e:
        logger.info("HLTV unavailable (Cloudflare) — using seed rankings: %s", e)

    # Collect real match data from PandaScore
    logger.info("=== Step 2: Fetching PandaScore match history ===")
    from data.collector import fetch_results, store_results, fetch_matches
    results = fetch_results()
    if results:
        store_results(results)

    # Liquipedia: tournament results
    try:
        from data.liquipedia import collect_liquipedia
        logger.info("=== Step 3: Fetching Liquipedia results ===")
        collect_liquipedia()
    except Exception as e:
        logger.warning("Liquipedia collection skipped: %s", e)

    # Recalculate ratings from real matches only
    logger.info("=== Step 4: Recalculating ratings ===")
    recalculate_all_ratings()

    # Summary
    conn = get_connection()
    team_count = conn.execute("SELECT COUNT(*) as c FROM teams").fetchone()["c"]
    match_count = conn.execute("SELECT COUNT(*) as c FROM matches").fetchone()["c"]
    ranked = conn.execute("SELECT COUNT(*) as c FROM teams WHERE world_ranking IS NOT NULL").fetchone()["c"]
    conn.close()

    logger.info("=== Reset complete ===")
    logger.info("  Teams: %d (%d with HLTV ranking)", team_count, ranked)
    logger.info("  Matches: %d (all real data, zero synthetic)", match_count)


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
        map_name = input("Map (empty=any): ").strip() or None
        bo = int(input("Best of (1/3/5, default 3): ").strip() or "3")
    except (ValueError, EOFError):
        print("Invalid input.")
        return

    predictor = get_predictor()
    result = predictor.predict(t1, t2, map_name=map_name, best_of=bo)

    print(f"\n{'='*50}")
    print(f" {result['team1']['name']} vs {result['team2']['name']}")
    print(f"{'='*50}")
    print(f" {result['team1']['name']}: {result['team1']['win_prob']*100:.1f}%")
    print(f" {result['team2']['name']}: {result['team2']['win_prob']*100:.1f}%")
    print(f"\n Predicted Winner: {result['predicted_winner']}")
    print(f" Confidence: {result['confidence_label']} ({result['confidence']*100:.1f}%)")
    print(f" Method: {result['method']}")

    if result.get("series_simulation"):
        sim = result["series_simulation"]
        print(f"\n --- BO{bo} Series Simulation ({sim['n_simulations']} runs) ---")
        print(f" {result['team1']['name']} wins series: {sim['team1_series_win_prob']*100:.1f}%")
        print(f" {result['team2']['name']} wins series: {sim['team2_series_win_prob']*100:.1f}%")
        print(f" Score probabilities:")
        for score, prob in sim['score_probabilities'].items():
            print(f"   {score}: {prob*100:.1f}%")
        print(f" Map probabilities ({result['team1']['name']}):")
        for map_n, prob in sim['map_probabilities'].items():
            print(f"   {map_n}: {prob*100:.1f}%")

    if result.get("model_probabilities"):
        mp = result["model_probabilities"]
        print(f"\n Model breakdown:")
        for model, prob in mp.items():
            if model != "agreement":
                print(f"   {model:25s}: {prob*100:.1f}%")
        print(f"   {'agreement':25s}: {mp.get('agreement', 0)*100:.0f}%")

    print(f"\n Analysis:")
    for point in result['analysis']:
        print(f"   - {point}")
    print()


def cmd_evaluate():
    """Full model evaluation: reliability diagram + tier breakdown."""
    from data.database import init_db
    from models.predictor import get_predictor
    init_db()

    predictor = get_predictor()
    result = predictor.evaluate()

    if not result:
        logger.error("Not enough data for evaluation.")
        return

    overall = result["overall"]
    logger.info("=" * 55)
    logger.info("  MODEL EVALUATION RESULTS")
    logger.info("=" * 55)
    logger.info("  Overall Accuracy: %.1f%%", overall["accuracy"] * 100)
    logger.info("  Brier Score:      %.4f", overall["brier"])
    logger.info("  Log Loss:         %.4f", overall["log_loss"])
    logger.info("  Samples:          %d", overall["n_samples"])

    logger.info("\n  Tier Breakdown:")
    for tier, info in result["tier_breakdown"].items():
        label = tier.replace("_", " ").title()
        brier_str = f" brier={info['brier']:.4f}" if "brier" in info else ""
        logger.info("    %-25s acc=%.1f%%%s (n=%d)", label, info["accuracy"] * 100, brier_str, info["count"])

    logger.info("\n  Reliability Diagram:")
    logger.info("    %-10s %-12s %-12s %s", "Bin", "Predicted", "Actual", "Count")
    for b in result["reliability_diagram"]:
        gap = abs(b["mean_predicted"] - b["mean_actual"])
        marker = "  OK" if gap < 0.05 else " ~" if gap < 0.10 else " !!"
        logger.info("    %-10s %-12.1f%% %-12.1f%% %d%s",
                     f"{b['bin_center']*100:.0f}%",
                     b["mean_predicted"] * 100,
                     b["mean_actual"] * 100,
                     b["count"], marker)
    logger.info("=" * 55)


def main():
    if len(sys.argv) < 2:
        cmd_serve()
        return

    command = sys.argv[1].lower()
    commands = {
        "serve": cmd_serve,
        "seed": cmd_seed,
        "train": cmd_train,
        "tune": lambda: cmd_train(use_optuna=True),
        "collect": cmd_collect,
        "reset": cmd_reset,
        "predict": cmd_predict,
        "evaluate": cmd_evaluate,
    }

    if command in commands:
        commands[command]()
    else:
        print(f"Unknown command: {command}")
        print(f"Available commands: {', '.join(commands.keys())}")
        sys.exit(1)


if __name__ == "__main__":
    main()
