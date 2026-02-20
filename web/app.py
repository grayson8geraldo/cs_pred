"""Flask web application for CS2 Match Predictor."""

import json
import logging
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify
from data.database import get_connection, init_db
from data.collector import collect_all
from models.predictor import get_predictor, CSPredictor
from models.rating_systems import recalculate_all_ratings
from models.features import get_feature_names
from config.settings import DATA_REFRESH_INTERVAL, PREDICTION_CACHE_TTL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)
app.config["SECRET_KEY"] = "cs-pred-dev"

# Simple in-memory prediction cache
_pred_cache = {}
_pred_cache_ts = {}


# ──────────────────────── Pages ────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/predictions")
def predictions_page():
    return render_template("predictions.html")


@app.route("/teams")
def teams_page():
    return render_template("teams.html")


@app.route("/stats")
def stats_page():
    return render_template("stats.html")


# ──────────────────────── API ────────────────────────

@app.route("/api/predict", methods=["POST"])
def api_predict():
    """Make a prediction for a match."""
    data = request.json
    team1_id = data.get("team1_id")
    team2_id = data.get("team2_id")
    map_name = data.get("map_name")
    is_lan = data.get("is_lan", False)
    best_of = data.get("best_of", 1)
    event_name = data.get("event_name", "")
    is_playoff = data.get("is_playoff", False)
    odds_t1 = data.get("bookmaker_odds_team1")
    odds_t2 = data.get("bookmaker_odds_team2")

    if not team1_id or not team2_id:
        return jsonify({"error": "team1_id and team2_id are required"}), 400

    # Check prediction cache
    cache_key = f"{team1_id}:{team2_id}:{map_name}:{best_of}:{is_lan}:{event_name}"
    now = time.time()
    if cache_key in _pred_cache and (now - _pred_cache_ts.get(cache_key, 0)) < PREDICTION_CACHE_TTL:
        result = _pred_cache[cache_key]
    else:
        predictor = get_predictor()
        result = predictor.predict(
            int(team1_id), int(team2_id), map_name=map_name, is_lan=is_lan,
            best_of=int(best_of), event_name=event_name, is_playoff=is_playoff,
            bookmaker_odds_t1=float(odds_t1) if odds_t1 else None,
            bookmaker_odds_t2=float(odds_t2) if odds_t2 else None,
        )
        _pred_cache[cache_key] = result
        _pred_cache_ts[cache_key] = now

    # Store prediction
    conn = get_connection()
    conn.execute("""
        INSERT INTO predictions (team1_id, team2_id, team1_win_prob, team2_win_prob,
                                 predicted_winner_id, confidence, confidence_label,
                                 method, features_json, analysis_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        team1_id, team2_id,
        result["team1"]["win_prob"], result["team2"]["win_prob"],
        result["predicted_winner_id"], result["confidence"],
        result["confidence_label"], result["method"],
        json.dumps(result["features"]), json.dumps(result["analysis"]),
    ))
    conn.commit()
    conn.close()

    return jsonify(result)


@app.route("/api/teams")
def api_teams():
    """Get all teams."""
    conn = get_connection()
    teams = conn.execute("""
        SELECT t.id, t.name, t.world_ranking,
               COALESCE(tr.rating, 1500) as elo_rating
        FROM teams t
        LEFT JOIN team_ratings tr ON t.id = tr.team_id AND tr.rating_type = 'elo'
        ORDER BY
            CASE WHEN t.world_ranking IS NOT NULL THEN t.world_ranking ELSE 9999 END,
            tr.rating DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(t) for t in teams])


@app.route("/api/teams/search")
def api_teams_search():
    """Search teams by name."""
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify([])
    conn = get_connection()
    teams = conn.execute(
        "SELECT id, name, world_ranking FROM teams WHERE name LIKE ? LIMIT 20",
        (f"%{q}%",),
    ).fetchall()
    conn.close()
    return jsonify([dict(t) for t in teams])


@app.route("/api/matches/recent")
def api_recent_matches():
    """Get recent match results."""
    limit = request.args.get("limit", 50, type=int)
    conn = get_connection()
    matches = conn.execute("""
        SELECT m.id, m.match_date, m.team1_score, m.team2_score,
               m.event_name, m.map_name,
               t1.name as team1_name, t2.name as team2_name,
               tw.name as winner_name
        FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        LEFT JOIN teams tw ON m.winner_id = tw.id
        ORDER BY m.match_date DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return jsonify([dict(m) for m in matches])


@app.route("/api/predictions/history")
def api_prediction_history():
    """Get prediction history."""
    limit = request.args.get("limit", 50, type=int)
    conn = get_connection()
    preds = conn.execute("""
        SELECT p.id, p.created_at,
               p.team1_win_prob, p.team2_win_prob,
               p.confidence, p.confidence_label, p.method,
               t1.name as team1_name, t2.name as team2_name,
               tw.name as predicted_winner
        FROM predictions p
        JOIN teams t1 ON p.team1_id = t1.id
        JOIN teams t2 ON p.team2_id = t2.id
        LEFT JOIN teams tw ON p.predicted_winner_id = tw.id
        ORDER BY p.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return jsonify([dict(p) for p in preds])


@app.route("/api/stats/overview")
def api_stats_overview():
    """Get overview statistics."""
    conn = get_connection()

    total_matches = conn.execute("SELECT COUNT(*) as c FROM matches").fetchone()["c"]
    total_teams = conn.execute("SELECT COUNT(*) as c FROM teams").fetchone()["c"]
    total_predictions = conn.execute("SELECT COUNT(*) as c FROM predictions").fetchone()["c"]

    correct = conn.execute("""
        SELECT COUNT(*) as c FROM predictions
        WHERE actual_winner_id IS NOT NULL AND predicted_winner_id = actual_winner_id
    """).fetchone()["c"]
    verified = conn.execute("""
        SELECT COUNT(*) as c FROM predictions WHERE actual_winner_id IS NOT NULL
    """).fetchone()["c"]

    accuracy = (correct / verified * 100) if verified > 0 else None

    top_teams = conn.execute("""
        SELECT t.name, tr.rating
        FROM team_ratings tr
        JOIN teams t ON tr.team_id = t.id
        WHERE tr.rating_type = 'elo'
        ORDER BY tr.rating DESC
        LIMIT 10
    """).fetchall()

    conn.close()

    return jsonify({
        "total_matches": total_matches,
        "total_teams": total_teams,
        "total_predictions": total_predictions,
        "verified_predictions": verified,
        "correct_predictions": correct,
        "accuracy": round(accuracy, 1) if accuracy else None,
        "top_teams": [{"name": t["name"], "elo": round(t["rating"], 1)} for t in top_teams],
    })


@app.route("/api/evaluate", methods=["POST"])
def api_evaluate():
    """Run full model evaluation with reliability diagram and tier breakdown."""
    try:
        predictor = get_predictor()
        result = predictor.evaluate()
        if result:
            return jsonify({"status": "ok", **result})
        return jsonify({"status": "error", "message": "Not enough data for evaluation"}), 400
    except Exception as e:
        logger.error("Evaluation failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/data/refresh", methods=["POST"])
def api_refresh_data():
    """Trigger data refresh from PandaScore."""
    try:
        upcoming = collect_all()
        recalculate_all_ratings()
        # Clear prediction cache after data refresh
        _pred_cache.clear()
        _pred_cache_ts.clear()
        return jsonify({
            "status": "ok",
            "upcoming_matches": len(upcoming) if upcoming else 0,
        })
    except Exception as e:
        logger.error("Data refresh failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/model/train", methods=["POST"])
def api_train_model():
    """Trigger model training."""
    try:
        use_optuna = request.json.get("use_optuna", False) if request.json else False
        predictor = get_predictor()
        result = predictor.train(use_optuna=use_optuna)
        if result:
            # Clear prediction cache after retraining
            _pred_cache.clear()
            _pred_cache_ts.clear()
            return jsonify({"status": "ok", **result})
        return jsonify({"status": "error", "message": "Not enough data to train"}), 400
    except Exception as e:
        logger.error("Training failed: %s", e)
        return jsonify({"error": str(e)}), 500


# ──────────────────────── Auto-refresh scheduler ────────────────────────

def setup_scheduler(app):
    """Set up background data refresh scheduler."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler()

        def scheduled_refresh():
            with app.app_context():
                try:
                    collect_all()
                    recalculate_all_ratings()
                    _pred_cache.clear()
                    _pred_cache_ts.clear()
                    logger.info("Scheduled data refresh complete")
                except Exception as e:
                    logger.error("Scheduled refresh failed: %s", e)

        scheduler.add_job(
            scheduled_refresh, 'interval',
            seconds=DATA_REFRESH_INTERVAL,
            id='data_refresh',
        )
        scheduler.start()
        logger.info("Auto-refresh scheduler started (interval: %ds)", DATA_REFRESH_INTERVAL)
    except ImportError:
        logger.info("APScheduler not available — auto-refresh disabled")
    except Exception as e:
        logger.warning("Scheduler setup failed: %s", e)


# ──────────────────────── Init ────────────────────────

def create_app():
    init_db()
    setup_scheduler(app)
    return app


if __name__ == "__main__":
    create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
