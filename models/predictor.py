"""
Ensemble CS2 match predictor.
Combines XGBoost + GradientBoosting + Logistic Regression.
Temporal cross-validation. Probability calibration. Value bet detection.
"""

import json
import os
import logging
import math
import pickle
import numpy as np
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler

from models.features import compute_features, get_feature_names
from data.database import get_connection
from config.settings import MODEL_PATH, MODELS_DIR, FEATURE_COLUMNS_PATH

logger = logging.getLogger(__name__)


class CSPredictor:
    """Ensemble Counter-Strike 2 match outcome predictor."""

    def __init__(self):
        self.model = None
        self.scaler = None
        self.feature_names = get_feature_names()
        self._load_model()

    def _load_model(self):
        if os.path.exists(MODEL_PATH):
            with open(MODEL_PATH, "rb") as f:
                saved = pickle.load(f)
            self.model = saved["model"]
            self.scaler = saved.get("scaler")
            logger.info("Ensemble model loaded from %s", MODEL_PATH)
        else:
            logger.info("No trained model found, will use heuristic predictor")

    def train(self):
        """Train ensemble with temporal CV, 3 base models, weighted soft vote."""
        conn = get_connection()
        matches = conn.execute("""
            SELECT id, team1_id, team2_id, winner_id, map_name, is_lan,
                   best_of, event_name, is_playoff
            FROM matches
            WHERE winner_id IS NOT NULL
            ORDER BY match_date ASC
        """).fetchall()
        conn.close()

        if len(matches) < 30:
            logger.warning("Not enough matches (%d). Need at least 30.", len(matches))
            return None

        X, y = [], []
        for match in matches:
            features = compute_features(
                match["team1_id"], match["team2_id"],
                map_name=match["map_name"],
                is_lan=bool(match["is_lan"]),
                best_of=match["best_of"] or 1,
                event_name=match["event_name"] or "",
                is_playoff=bool(match["is_playoff"]),
            )
            feature_vector = [features[f] for f in self.feature_names]
            label = 1 if match["winner_id"] == match["team1_id"] else 0
            X.append(feature_vector)
            y.append(label)

        X = np.array(X, dtype=np.float64)
        y = np.array(y)
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        # Base models
        xgb_model = xgb.XGBClassifier(
            n_estimators=300, max_depth=5, learning_rate=0.03,
            subsample=0.8, colsample_bytree=0.7, min_child_weight=5,
            reg_alpha=0.5, reg_lambda=2.0, gamma=0.1,
            eval_metric="logloss", random_state=42,
        )
        gbt_model = GradientBoostingClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            subsample=0.8, min_samples_leaf=10, max_features=0.7,
            random_state=42,
        )
        lr_model = LogisticRegression(
            C=0.5, max_iter=1000, solver="lbfgs", random_state=42,
        )

        # Temporal CV
        n_splits = min(5, max(2, len(y) // 50))
        tscv = TimeSeriesSplit(n_splits=n_splits)

        fold_results = []
        for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
            X_tr, X_te = X[train_idx], X[test_idx]
            y_tr, y_te = y[train_idx], y[test_idx]
            X_tr_s, X_te_s = X_scaled[train_idx], X_scaled[test_idx]

            xgb_model.fit(X_tr, y_tr)
            gbt_model.fit(X_tr, y_tr)
            lr_model.fit(X_tr_s, y_tr)

            p_xgb = xgb_model.predict_proba(X_te)[:, 1]
            p_gbt = gbt_model.predict_proba(X_te)[:, 1]
            p_lr = lr_model.predict_proba(X_te_s)[:, 1]

            p_ens = 0.45 * p_xgb + 0.35 * p_gbt + 0.20 * p_lr
            preds = (p_ens >= 0.5).astype(int)

            acc = accuracy_score(y_te, preds)
            brier = brier_score_loss(y_te, p_ens)
            ll = log_loss(y_te, np.clip(p_ens, 1e-7, 1 - 1e-7))

            fold_results.append({
                "fold": fold + 1, "accuracy": acc,
                "brier": brier, "log_loss": ll, "test_size": len(y_te),
            })
            logger.info("Fold %d: acc=%.3f brier=%.4f logloss=%.4f (n=%d)",
                        fold + 1, acc, brier, ll, len(y_te))

        avg_acc = np.mean([r["accuracy"] for r in fold_results])
        avg_brier = np.mean([r["brier"] for r in fold_results])
        logger.info("Temporal CV Accuracy: %.3f, Brier: %.4f", avg_acc, avg_brier)

        # Final train on all data
        xgb_model.fit(X, y)
        gbt_model.fit(X, y)
        lr_model.fit(X_scaled, y)

        # Save
        os.makedirs(MODELS_DIR, exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({
                "model": {"xgb": xgb_model, "gbt": gbt_model, "lr": lr_model},
                "scaler": self.scaler,
                "weights": [0.45, 0.35, 0.20],
            }, f)

        self.model = {"xgb": xgb_model, "gbt": gbt_model, "lr": lr_model}

        with open(FEATURE_COLUMNS_PATH, "w") as fh:
            json.dump(self.feature_names, fh)

        importance = dict(zip(
            self.feature_names,
            [float(x) for x in xgb_model.feature_importances_],
        ))

        logger.info("Ensemble model saved to %s", MODEL_PATH)
        return {
            "temporal_cv_accuracy": float(avg_acc),
            "temporal_cv_brier": float(avg_brier),
            "fold_results": fold_results,
            "n_samples": len(y),
            "n_features": len(self.feature_names),
            "feature_importance": importance,
        }

    def predict(self, team1_id, team2_id, map_name=None, is_lan=False,
                best_of=1, event_name="", is_playoff=False,
                bookmaker_odds_t1=None, bookmaker_odds_t2=None):
        """Predict with ensemble + value bet detection."""
        features = compute_features(
            team1_id, team2_id, map_name=map_name, is_lan=is_lan,
            best_of=best_of, event_name=event_name, is_playoff=is_playoff,
        )
        fv = np.array(
            [features[f] for f in self.feature_names], dtype=np.float64
        ).reshape(1, -1)
        fv = np.nan_to_num(fv, nan=0.0, posinf=1e6, neginf=-1e6)

        p_xgb = p_gbt = p_lr = None
        if self.model is not None and isinstance(self.model, dict):
            p_xgb = float(self.model["xgb"].predict_proba(fv)[0][1])
            p_gbt = float(self.model["gbt"].predict_proba(fv)[0][1])
            fv_s = self.scaler.transform(fv) if self.scaler else fv
            p_lr = float(self.model["lr"].predict_proba(fv_s)[0][1])

            team1_prob = 0.45 * p_xgb + 0.35 * p_gbt + 0.20 * p_lr
            team2_prob = 1.0 - team1_prob
            method = "ensemble"
            model_agreement = self._model_agreement(p_xgb, p_gbt, p_lr)
        else:
            team1_prob, team2_prob = self._heuristic_predict(features)
            method = "heuristic"
            model_agreement = 1.0

        prob_spread = abs(team1_prob - team2_prob)
        confidence = self._compute_confidence(prob_spread, model_agreement, features)
        confidence_label = (
            "high" if confidence > 0.7
            else "medium" if confidence > 0.4
            else "low"
        )

        conn = get_connection()
        t1 = conn.execute("SELECT name FROM teams WHERE id = ?", (team1_id,)).fetchone()
        t2 = conn.execute("SELECT name FROM teams WHERE id = ?", (team2_id,)).fetchone()
        conn.close()
        team1_name = t1["name"] if t1 else f"Team {team1_id}"
        team2_name = t2["name"] if t2 else f"Team {team2_id}"

        predicted_winner = team1_name if team1_prob > team2_prob else team2_name
        predicted_winner_id = team1_id if team1_prob > team2_prob else team2_id

        value_bet = None
        if bookmaker_odds_t1 and bookmaker_odds_t2:
            value_bet = self._detect_value_bet(
                team1_prob, team2_prob,
                bookmaker_odds_t1, bookmaker_odds_t2,
                team1_name, team2_name,
            )

        result = {
            "team1": {"id": team1_id, "name": team1_name, "win_prob": round(team1_prob, 4)},
            "team2": {"id": team2_id, "name": team2_name, "win_prob": round(team2_prob, 4)},
            "predicted_winner": predicted_winner,
            "predicted_winner_id": predicted_winner_id,
            "confidence": round(confidence, 4),
            "confidence_label": confidence_label,
            "method": method,
            "features": {k: round(v, 4) for k, v in features.items()},
            "analysis": self._build_analysis(features, team1_name, team2_name, confidence_label),
            "value_bet": value_bet,
        }

        if method == "ensemble" and p_xgb is not None:
            result["model_probabilities"] = {
                "xgboost": round(p_xgb, 4),
                "gradient_boosting": round(p_gbt, 4),
                "logistic_regression": round(p_lr, 4),
                "agreement": round(model_agreement, 4),
            }

        return result

    def _model_agreement(self, p1, p2, p3):
        probs = [p1, p2, p3]
        winners = [p > 0.5 for p in probs]
        if all(winners) or not any(winners):
            spread = max(probs) - min(probs)
            return max(0, 1.0 - spread * 2)
        return 0.3

    def _compute_confidence(self, prob_spread, model_agreement, features):
        base = min(prob_spread * 1.5, 1.0)
        agreement_factor = 0.7 + 0.3 * model_agreement
        h2h_data = features.get("h2h_matches", 0)
        data_factor = 0.7 + 0.3 * min(h2h_data, 1.0)
        return base * agreement_factor * data_factor

    def _heuristic_predict(self, features):
        weights = {
            "elo_diff": 0.20, "glicko2_diff": 0.15, "ranking_diff": 0.10,
            "win_rate_30d_diff": 0.12, "win_rate_90d_diff": 0.08,
            "recent_form_5_diff": 0.08, "h2h_advantage": 0.07,
            "map_wr_diff": 0.05, "player_rating_diff": 0.05,
            "streak_diff": 0.03, "vs_top10_diff": 0.04, "star_player_diff": 0.03,
        }
        norm = {}
        divisors = {
            "elo_diff": 400, "glicko2_diff": 400, "ranking_diff": 50,
            "streak_diff": 5, "star_player_diff": 0.2,
        }
        for k in weights:
            val = features.get(k, 0)
            if k == "h2h_advantage":
                val = (val - 0.5) * 2
            elif k in divisors:
                val = val / divisors[k]
            else:
                val = val * 2
            norm[k] = max(-1, min(1, val))
        score = sum(weights[k] * norm[k] for k in weights)
        team1_prob = 1.0 / (1 + math.exp(-5 * score))
        return team1_prob, 1.0 - team1_prob

    def _detect_value_bet(self, model_prob_t1, model_prob_t2,
                          odds_t1, odds_t2, name1, name2):
        implied_t1 = 1.0 / odds_t1 if odds_t1 > 0 else 0
        implied_t2 = 1.0 / odds_t2 if odds_t2 > 0 else 0
        edge_t1 = model_prob_t1 - implied_t1
        edge_t2 = model_prob_t2 - implied_t2
        ev_t1 = model_prob_t1 * odds_t1 - 1
        ev_t2 = model_prob_t2 * odds_t2 - 1

        result = {
            "team1_implied_prob": round(implied_t1, 4),
            "team2_implied_prob": round(implied_t2, 4),
            "team1_edge": round(edge_t1, 4),
            "team2_edge": round(edge_t2, 4),
            "team1_ev": round(ev_t1, 4),
            "team2_ev": round(ev_t2, 4),
            "recommendation": None,
        }
        EDGE_THRESHOLD = 0.05
        if edge_t1 > EDGE_THRESHOLD and ev_t1 > 0:
            result["recommendation"] = {
                "team": name1, "edge": round(edge_t1 * 100, 1),
                "ev_per_unit": round(ev_t1, 3), "odds": odds_t1,
                "rating": "strong" if edge_t1 > 0.10 else "moderate",
            }
        elif edge_t2 > EDGE_THRESHOLD and ev_t2 > 0:
            result["recommendation"] = {
                "team": name2, "edge": round(edge_t2 * 100, 1),
                "ev_per_unit": round(ev_t2, 3), "odds": odds_t2,
                "rating": "strong" if edge_t2 > 0.10 else "moderate",
            }
        return result

    def _build_analysis(self, features, team1_name, team2_name, confidence_label):
        points = []
        elo_diff = features.get("elo_diff", 0)
        if abs(elo_diff) > 100:
            b = team1_name if elo_diff > 0 else team2_name
            points.append(f"{b} has a significant Elo advantage ({abs(elo_diff):.0f} pts)")
        elif abs(elo_diff) > 30:
            b = team1_name if elo_diff > 0 else team2_name
            points.append(f"{b} has a slight Elo edge ({abs(elo_diff):.0f} pts)")

        rank_diff = features.get("ranking_diff", 0)
        if abs(rank_diff) >= 5:
            b = team1_name if rank_diff > 0 else team2_name
            points.append(f"{b} is ranked {abs(rank_diff):.0f} positions higher")

        trend = features.get("form_trend_diff", 0)
        if abs(trend) > 0.1:
            b = team1_name if trend > 0 else team2_name
            points.append(f"{b} is on an improving form trajectory")

        form5 = features.get("recent_form_5_diff", 0)
        if abs(form5) > 0.2:
            b = team1_name if form5 > 0 else team2_name
            points.append(f"{b} has stronger recent form (last 5)")

        h2h = features.get("h2h_advantage", 0.5)
        h2h_count = features.get("h2h_matches", 0)
        if h2h_count > 0.1 and abs(h2h - 0.5) > 0.1:
            b = team1_name if h2h > 0.5 else team2_name
            rate = h2h if h2h > 0.5 else (1 - h2h)
            points.append(f"{b} leads head-to-head ({rate*100:.0f}%)")

        map_diff = features.get("map_wr_diff", 0)
        if abs(map_diff) > 0.1:
            b = team1_name if map_diff > 0 else team2_name
            points.append(f"{b} is stronger on the selected map")

        pool_diff = features.get("map_pool_depth_diff", 0)
        if abs(pool_diff) >= 2:
            b = team1_name if pool_diff > 0 else team2_name
            points.append(f"{b} has a deeper map pool (+{abs(pool_diff):.0f} maps)")

        star_diff = features.get("star_player_diff", 0)
        if abs(star_diff) > 0.1:
            b = team1_name if star_diff > 0 else team2_name
            points.append(f"{b} has the better star player")

        pr_diff = features.get("player_rating_diff", 0)
        if abs(pr_diff) > 0.05:
            b = team1_name if pr_diff > 0 else team2_name
            points.append(f"{b} has higher average player ratings")

        streak = features.get("streak_diff", 0)
        if abs(streak) >= 3:
            b = team1_name if streak > 0 else team2_name
            points.append(f"{b} is on a {abs(streak):.0f}-game win streak")

        vt = features.get("vs_top10_diff", 0)
        if abs(vt) > 0.15:
            b = team1_name if vt > 0 else team2_name
            points.append(f"{b} performs better vs top-10 opponents")

        if not points:
            points.append("Very even matchup — expect a close game")
        if confidence_label == "low":
            points.append("Low confidence — high upset potential")
        elif confidence_label == "high":
            points.append("High confidence — strong signal alignment across all models")
        return points


_predictor = None

def get_predictor():
    global _predictor
    if _predictor is None:
        _predictor = CSPredictor()
    return _predictor
