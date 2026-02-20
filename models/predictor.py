"""
Advanced ensemble CS2 match predictor.
- 4 base models: XGBoost + GradientBoosting + LightGBM + LogisticRegression
- Stacking meta-learner (replaces fixed weights)
- Isotonic probability calibration
- Optuna hyperparameter tuning
- BO3/BO5 Monte Carlo map simulation
- Reliability diagram + tier-breakdown evaluation
"""

import json
import os
import logging
import math
import pickle
import time
from datetime import datetime
from collections import defaultdict

import numpy as np
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
from sklearn.isotonic import IsotonicRegression

try:
    import lightgbm as lgbm
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False

from models.features import compute_features, compute_map_features, get_feature_names, get_team_map_pool
from data.database import get_connection
from config.settings import (
    MODEL_PATH, MODELS_DIR, FEATURE_COLUMNS_PATH, CALIBRATOR_PATH,
    STACKING_META_PATH, OPTUNA_N_TRIALS, OPTUNA_TIMEOUT,
    OPTUNA_BEST_PARAMS_PATH, MONTE_CARLO_SIMULATIONS, CS2_MAPS,
)

logger = logging.getLogger(__name__)


class CSPredictor:
    """Advanced ensemble CS2 match outcome predictor."""

    def __init__(self):
        self.model = None
        self.scaler = None
        self.meta_learner = None
        self.calibrator = None
        self.feature_names = get_feature_names()
        self._prediction_cache = {}
        self._cache_timestamps = {}
        self._load_model()

    def _load_model(self):
        if os.path.exists(MODEL_PATH):
            with open(MODEL_PATH, "rb") as f:
                saved = pickle.load(f)
            self.model = saved["model"]
            self.scaler = saved.get("scaler")
            self.meta_learner = saved.get("meta_learner")
            # Load feature names from saved model if available
            if "feature_names" in saved:
                self.feature_names = saved["feature_names"]
            logger.info("Ensemble model loaded from %s", MODEL_PATH)
        else:
            logger.info("No trained model found, will use heuristic predictor")

        if os.path.exists(CALIBRATOR_PATH):
            with open(CALIBRATOR_PATH, "rb") as f:
                self.calibrator = pickle.load(f)
            logger.info("Probability calibrator loaded")

    # ═══════════════════════════════════════════════════════
    #  TRAINING
    # ═══════════════════════════════════════════════════════

    def train(self, use_optuna=False):
        """Train stacking ensemble with temporal CV, 4 base models, calibration."""
        conn = get_connection()
        matches = conn.execute("""
            SELECT id, team1_id, team2_id, winner_id, map_name, is_lan,
                   best_of, event_name, is_playoff, match_date
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
            match_date = None
            if match["match_date"]:
                try:
                    match_date = datetime.fromisoformat(str(match["match_date"]))
                except (ValueError, TypeError):
                    pass
            features = compute_features(
                match["team1_id"], match["team2_id"],
                map_name=match["map_name"],
                is_lan=bool(match["is_lan"]),
                best_of=match["best_of"] or 1,
                event_name=match["event_name"] or "",
                is_playoff=bool(match["is_playoff"]),
                as_of=match_date,
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

        # Get hyperparameters (Optuna or defaults)
        if use_optuna and HAS_OPTUNA:
            logger.info("Running Optuna hyperparameter search...")
            best_params = self._optuna_search(X, X_scaled, y)
        elif os.path.exists(OPTUNA_BEST_PARAMS_PATH):
            with open(OPTUNA_BEST_PARAMS_PATH) as f:
                best_params = json.load(f)
            logger.info("Using saved Optuna params from %s", OPTUNA_BEST_PARAMS_PATH)
        else:
            best_params = self._default_params()

        # Build base models
        xgb_model, gbt_model, lgbm_model, lr_model = self._build_models(best_params)

        # Temporal CV with stacking
        n_splits = min(5, max(2, len(y) // 50))
        tscv = TimeSeriesSplit(n_splits=n_splits)

        fold_results = []
        oof_preds = np.zeros((len(y), self._n_base_models()))
        oof_mask = np.zeros(len(y), dtype=bool)

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

            base_preds = [p_xgb, p_gbt, p_lr]

            if lgbm_model is not None:
                lgbm_model.fit(X_tr, y_tr)
                p_lgbm = lgbm_model.predict_proba(X_te)[:, 1]
                base_preds.append(p_lgbm)

            stacked = np.column_stack(base_preds)
            oof_preds[test_idx, :len(base_preds)] = stacked
            oof_mask[test_idx] = True

            # Temporary ensemble for CV metrics (simple average before meta-learner)
            p_ens = np.mean(stacked, axis=1)
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

        # Train stacking meta-learner on OOF predictions
        oof_X = oof_preds[oof_mask]
        oof_y = y[oof_mask]
        self.meta_learner = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs")
        self.meta_learner.fit(oof_X, oof_y)
        logger.info("Stacking meta-learner trained on %d OOF samples", len(oof_y))

        # Train isotonic calibrator on OOF stacked predictions
        meta_probs = self.meta_learner.predict_proba(oof_X)[:, 1]
        self.calibrator = IsotonicRegression(y_min=0.02, y_max=0.98, out_of_bounds="clip")
        self.calibrator.fit(meta_probs, oof_y)
        logger.info("Isotonic calibrator trained")

        # Evaluate calibrated predictions on OOF
        calibrated_probs = self.calibrator.predict(meta_probs)
        cal_brier = brier_score_loss(oof_y, calibrated_probs)
        cal_acc = accuracy_score(oof_y, (calibrated_probs >= 0.5).astype(int))
        logger.info("Calibrated OOF: acc=%.3f brier=%.4f (improvement: %.4f)",
                     cal_acc, cal_brier, avg_brier - cal_brier)

        # Final train on all data
        xgb_model.fit(X, y)
        gbt_model.fit(X, y)
        lr_model.fit(X_scaled, y)
        models_dict = {"xgb": xgb_model, "gbt": gbt_model, "lr": lr_model}
        if lgbm_model is not None:
            lgbm_model.fit(X, y)
            models_dict["lgbm"] = lgbm_model

        # Save everything
        os.makedirs(MODELS_DIR, exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({
                "model": models_dict,
                "scaler": self.scaler,
                "meta_learner": self.meta_learner,
                "feature_names": self.feature_names,
                "trained_at": datetime.utcnow().isoformat(),
            }, f)

        with open(CALIBRATOR_PATH, "wb") as f:
            pickle.dump(self.calibrator, f)

        self.model = models_dict

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
            "calibrated_brier": float(cal_brier),
            "fold_results": fold_results,
            "n_samples": len(y),
            "n_features": len(self.feature_names),
            "n_base_models": self._n_base_models(),
            "feature_importance": importance,
            "has_lgbm": HAS_LGBM,
            "has_optuna": use_optuna and HAS_OPTUNA,
        }

    def _n_base_models(self):
        return 4 if HAS_LGBM else 3

    def _default_params(self):
        return {
            "xgb": {
                "n_estimators": 300, "max_depth": 4, "learning_rate": 0.03,
                "subsample": 0.75, "colsample_bytree": 0.6, "min_child_weight": 10,
                "reg_alpha": 1.0, "reg_lambda": 5.0, "gamma": 0.3,
                "max_delta_step": 1,
            },
            "gbt": {
                "n_estimators": 200, "max_depth": 3, "learning_rate": 0.05,
                "subsample": 0.75, "min_samples_leaf": 15, "max_features": 0.6,
            },
            "lgbm": {
                "n_estimators": 300, "max_depth": 4, "learning_rate": 0.03,
                "subsample": 0.75, "colsample_bytree": 0.6,
                "min_child_samples": 15, "reg_alpha": 1.0, "reg_lambda": 5.0,
                "num_leaves": 31,
            },
            "lr": {"C": 0.5},
        }

    def _build_models(self, params):
        xgb_model = xgb.XGBClassifier(
            **params["xgb"],
            eval_metric="logloss", random_state=42,
        )
        gbt_model = GradientBoostingClassifier(
            **params["gbt"],
            random_state=42,
        )
        lr_model = LogisticRegression(
            C=params["lr"]["C"], max_iter=1000, solver="lbfgs", random_state=42,
        )
        lgbm_model = None
        if HAS_LGBM:
            lgbm_model = lgbm.LGBMClassifier(
                **params["lgbm"],
                random_state=42, verbose=-1,
            )
        return xgb_model, gbt_model, lgbm_model, lr_model

    # ═══════════════════════════════════════════════════════
    #  OPTUNA HYPERPARAMETER TUNING
    # ═══════════════════════════════════════════════════════

    def _optuna_search(self, X, X_scaled, y):
        """Run Optuna hyperparameter search for all base models."""
        n_splits = min(3, max(2, len(y) // 100))
        tscv = TimeSeriesSplit(n_splits=n_splits)

        best = {}

        # XGBoost
        def xgb_objective(trial):
            params = {
                "n_estimators": trial.suggest_int("n_estimators", 100, 500),
                "max_depth": trial.suggest_int("max_depth", 2, 6),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
                "subsample": trial.suggest_float("subsample", 0.6, 0.9),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.4, 0.8),
                "min_child_weight": trial.suggest_int("min_child_weight", 5, 30),
                "reg_alpha": trial.suggest_float("reg_alpha", 0.1, 5.0, log=True),
                "reg_lambda": trial.suggest_float("reg_lambda", 0.5, 10.0, log=True),
                "gamma": trial.suggest_float("gamma", 0.0, 1.0),
                "max_delta_step": trial.suggest_int("max_delta_step", 0, 3),
            }
            briers = []
            for train_idx, test_idx in tscv.split(X):
                m = xgb.XGBClassifier(**params, eval_metric="logloss", random_state=42)
                m.fit(X[train_idx], y[train_idx])
                p = m.predict_proba(X[test_idx])[:, 1]
                briers.append(brier_score_loss(y[test_idx], p))
            return np.mean(briers)

        study = optuna.create_study(direction="minimize")
        study.optimize(xgb_objective, n_trials=OPTUNA_N_TRIALS, timeout=OPTUNA_TIMEOUT)
        best["xgb"] = study.best_params
        logger.info("XGBoost best Brier: %.4f", study.best_value)

        # GradientBoosting
        def gbt_objective(trial):
            params = {
                "n_estimators": trial.suggest_int("n_estimators", 100, 400),
                "max_depth": trial.suggest_int("max_depth", 2, 5),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
                "subsample": trial.suggest_float("subsample", 0.6, 0.9),
                "min_samples_leaf": trial.suggest_int("min_samples_leaf", 5, 30),
                "max_features": trial.suggest_float("max_features", 0.3, 0.8),
            }
            briers = []
            for train_idx, test_idx in tscv.split(X):
                m = GradientBoostingClassifier(**params, random_state=42)
                m.fit(X[train_idx], y[train_idx])
                p = m.predict_proba(X[test_idx])[:, 1]
                briers.append(brier_score_loss(y[test_idx], p))
            return np.mean(briers)

        study = optuna.create_study(direction="minimize")
        study.optimize(gbt_objective, n_trials=OPTUNA_N_TRIALS, timeout=OPTUNA_TIMEOUT)
        best["gbt"] = study.best_params
        logger.info("GBT best Brier: %.4f", study.best_value)

        # LightGBM
        if HAS_LGBM:
            def lgbm_objective(trial):
                params = {
                    "n_estimators": trial.suggest_int("n_estimators", 100, 500),
                    "max_depth": trial.suggest_int("max_depth", 2, 6),
                    "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
                    "subsample": trial.suggest_float("subsample", 0.6, 0.9),
                    "colsample_bytree": trial.suggest_float("colsample_bytree", 0.4, 0.8),
                    "min_child_samples": trial.suggest_int("min_child_samples", 5, 30),
                    "reg_alpha": trial.suggest_float("reg_alpha", 0.1, 5.0, log=True),
                    "reg_lambda": trial.suggest_float("reg_lambda", 0.5, 10.0, log=True),
                    "num_leaves": trial.suggest_int("num_leaves", 15, 63),
                }
                briers = []
                for train_idx, test_idx in tscv.split(X):
                    m = lgbm.LGBMClassifier(**params, random_state=42, verbose=-1)
                    m.fit(X[train_idx], y[train_idx])
                    p = m.predict_proba(X[test_idx])[:, 1]
                    briers.append(brier_score_loss(y[test_idx], p))
                return np.mean(briers)

            study = optuna.create_study(direction="minimize")
            study.optimize(lgbm_objective, n_trials=OPTUNA_N_TRIALS, timeout=OPTUNA_TIMEOUT)
            best["lgbm"] = study.best_params
            logger.info("LightGBM best Brier: %.4f", study.best_value)
        else:
            best["lgbm"] = self._default_params()["lgbm"]

        # Logistic Regression
        def lr_objective(trial):
            C = trial.suggest_float("C", 0.01, 10.0, log=True)
            briers = []
            for train_idx, test_idx in tscv.split(X):
                m = LogisticRegression(C=C, max_iter=1000, solver="lbfgs", random_state=42)
                m.fit(X_scaled[train_idx], y[train_idx])
                p = m.predict_proba(X_scaled[test_idx])[:, 1]
                briers.append(brier_score_loss(y[test_idx], p))
            return np.mean(briers)

        study = optuna.create_study(direction="minimize")
        study.optimize(lr_objective, n_trials=20, timeout=60)
        best["lr"] = study.best_params
        logger.info("LR best Brier: %.4f", study.best_value)

        # Save best params
        os.makedirs(MODELS_DIR, exist_ok=True)
        with open(OPTUNA_BEST_PARAMS_PATH, "w") as f:
            json.dump(best, f, indent=2)
        logger.info("Best params saved to %s", OPTUNA_BEST_PARAMS_PATH)

        return best

    # ═══════════════════════════════════════════════════════
    #  PREDICTION
    # ═══════════════════════════════════════════════════════

    def predict(self, team1_id, team2_id, map_name=None, is_lan=False,
                best_of=1, event_name="", is_playoff=False,
                bookmaker_odds_t1=None, bookmaker_odds_t2=None):
        """Predict with stacking ensemble + calibration + BO3/BO5 simulation."""
        features = compute_features(
            team1_id, team2_id, map_name=map_name, is_lan=is_lan,
            best_of=best_of, event_name=event_name, is_playoff=is_playoff,
        )
        fv = np.array(
            [features[f] for f in self.feature_names], dtype=np.float64
        ).reshape(1, -1)
        fv = np.nan_to_num(fv, nan=0.0, posinf=1e6, neginf=-1e6)

        model_probs = {}
        if self.model is not None and isinstance(self.model, dict):
            p_xgb = float(self.model["xgb"].predict_proba(fv)[0][1])
            p_gbt = float(self.model["gbt"].predict_proba(fv)[0][1])
            fv_s = self.scaler.transform(fv) if self.scaler else fv
            p_lr = float(self.model["lr"].predict_proba(fv_s)[0][1])

            model_probs = {"xgboost": p_xgb, "gradient_boosting": p_gbt, "logistic_regression": p_lr}
            base_preds = [p_xgb, p_gbt, p_lr]

            if "lgbm" in self.model:
                p_lgbm = float(self.model["lgbm"].predict_proba(fv)[0][1])
                model_probs["lightgbm"] = p_lgbm
                base_preds.append(p_lgbm)

            # Stacking meta-learner
            if self.meta_learner is not None:
                stacked = np.array(base_preds).reshape(1, -1)
                team1_prob = float(self.meta_learner.predict_proba(stacked)[0][1])
            else:
                # Fallback to simple average
                team1_prob = np.mean(base_preds)

            # Isotonic calibration
            if self.calibrator is not None:
                team1_prob = float(self.calibrator.predict(np.array([team1_prob]))[0])

            team1_prob = max(0.02, min(0.98, team1_prob))
            team2_prob = 1.0 - team1_prob
            method = "stacking_ensemble"
            model_agreement = self._model_agreement(list(model_probs.values()))
            model_probs["agreement"] = round(model_agreement, 4)
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

        if model_probs:
            result["model_probabilities"] = {k: round(v, 4) for k, v in model_probs.items()}

        # BO3/BO5 Monte Carlo simulation
        if best_of >= 3 and self.model is not None:
            series_result = self.simulate_series(
                team1_id, team2_id, best_of=best_of,
                is_lan=is_lan, event_name=event_name, is_playoff=is_playoff,
            )
            result["series_simulation"] = series_result

        return result

    # ═══════════════════════════════════════════════════════
    #  BO3/BO5 MONTE CARLO SIMULATION
    # ═══════════════════════════════════════════════════════

    def simulate_series(self, team1_id, team2_id, best_of=3,
                        is_lan=False, event_name="", is_playoff=False):
        """Monte Carlo simulation of a BO3/BO5 series with map veto modeling."""
        maps_needed = (best_of + 1) // 2  # 2 for BO3, 3 for BO5

        # Get each team's map pool preferences
        pool1 = get_team_map_pool(team1_id)
        pool2 = get_team_map_pool(team2_id)

        # Simulate veto: each team bans worst maps, picks best
        available_maps = [m for m in CS2_MAPS if m in pool1 or m in pool2]
        if not available_maps:
            available_maps = CS2_MAPS[:7]

        # Simplified veto: team1 picks best map, team2 picks best map, rest random
        veto_maps = self._simulate_veto(pool1, pool2, available_maps, maps_needed)

        # Get per-map win probabilities
        map_probs = {}
        for map_name in veto_maps:
            prob = self._predict_map_prob(
                team1_id, team2_id, map_name,
                is_lan=is_lan, event_name=event_name, is_playoff=is_playoff,
            )
            map_probs[map_name] = prob

        # Monte Carlo simulation
        n_sims = MONTE_CARLO_SIMULATIONS
        score_counts = defaultdict(int)
        t1_series_wins = 0

        rng = np.random.default_rng(42)
        for _ in range(n_sims):
            t1_score, t2_score = 0, 0
            map_order = list(veto_maps)
            rng.shuffle(map_order)

            for map_name in map_order:
                if rng.random() < map_probs[map_name]:
                    t1_score += 1
                else:
                    t2_score += 1
                if t1_score == maps_needed or t2_score == maps_needed:
                    break

            score_key = f"{t1_score}-{t2_score}"
            score_counts[score_key] += 1
            if t1_score > t2_score:
                t1_series_wins += 1

        # Normalize to probabilities
        total = sum(score_counts.values())
        score_probs = {k: round(v / total, 4) for k, v in sorted(score_counts.items())}

        return {
            "team1_series_win_prob": round(t1_series_wins / n_sims, 4),
            "team2_series_win_prob": round(1 - t1_series_wins / n_sims, 4),
            "score_probabilities": score_probs,
            "map_probabilities": {k: round(v, 4) for k, v in map_probs.items()},
            "simulated_maps": veto_maps,
            "n_simulations": n_sims,
        }

    def _simulate_veto(self, pool1, pool2, available, n_maps):
        """Simplified map veto simulation."""
        result = []
        used = set()

        # Team1 picks their best available map
        for m in pool1:
            if m in available and m not in used:
                result.append(m)
                used.add(m)
                break

        # Team2 picks their best available map
        for m in pool2:
            if m in available and m not in used:
                result.append(m)
                used.add(m)
                break

        # Fill remaining with random available maps
        for m in available:
            if len(result) >= n_maps:
                break
            if m not in used:
                result.append(m)
                used.add(m)

        # Ensure we have enough maps
        while len(result) < n_maps:
            for m in CS2_MAPS:
                if m not in used:
                    result.append(m)
                    used.add(m)
                    if len(result) >= n_maps:
                        break

        return result[:n_maps]

    def _predict_map_prob(self, team1_id, team2_id, map_name,
                          is_lan=False, event_name="", is_playoff=False):
        """Get team1 win probability on a specific map."""
        features = compute_map_features(
            team1_id, team2_id, map_name,
            is_lan=is_lan, event_name=event_name, is_playoff=is_playoff,
        )
        fv = np.array(
            [features[f] for f in self.feature_names], dtype=np.float64
        ).reshape(1, -1)
        fv = np.nan_to_num(fv, nan=0.0, posinf=1e6, neginf=-1e6)

        if self.model is not None and isinstance(self.model, dict):
            base_preds = [
                float(self.model["xgb"].predict_proba(fv)[0][1]),
                float(self.model["gbt"].predict_proba(fv)[0][1]),
                float(self.model["lr"].predict_proba(
                    self.scaler.transform(fv) if self.scaler else fv
                )[0][1]),
            ]
            if "lgbm" in self.model:
                base_preds.append(float(self.model["lgbm"].predict_proba(fv)[0][1]))

            if self.meta_learner is not None:
                stacked = np.array(base_preds).reshape(1, -1)
                prob = float(self.meta_learner.predict_proba(stacked)[0][1])
            else:
                prob = np.mean(base_preds)

            if self.calibrator is not None:
                prob = float(self.calibrator.predict(np.array([prob]))[0])

            return max(0.02, min(0.98, prob))
        else:
            p1, _ = self._heuristic_predict(features)
            return p1

    # ═══════════════════════════════════════════════════════
    #  EVALUATION & DIAGNOSTICS
    # ═══════════════════════════════════════════════════════

    def evaluate(self):
        """Full evaluation: reliability diagram data, tier breakdown, and metrics."""
        conn = get_connection()
        matches = conn.execute("""
            SELECT id, team1_id, team2_id, winner_id, map_name, is_lan,
                   best_of, event_name, is_playoff, match_date
            FROM matches WHERE winner_id IS NOT NULL
            ORDER BY match_date ASC
        """).fetchall()
        conn.close()

        if len(matches) < 30:
            return None

        X, y, meta = [], [], []
        for match in matches:
            match_date = None
            if match["match_date"]:
                try:
                    match_date = datetime.fromisoformat(str(match["match_date"]))
                except (ValueError, TypeError):
                    pass
            features = compute_features(
                match["team1_id"], match["team2_id"],
                map_name=match["map_name"],
                is_lan=bool(match["is_lan"]),
                best_of=match["best_of"] or 1,
                event_name=match["event_name"] or "",
                is_playoff=bool(match["is_playoff"]),
                as_of=match_date,
            )
            fv = [features[f] for f in self.feature_names]
            label = 1 if match["winner_id"] == match["team1_id"] else 0
            X.append(fv)
            y.append(label)

            # Collect team ranking info for tier breakdown
            r1 = features.get("ranking_diff", 0)
            meta.append({
                "ranking_diff_abs": abs(r1),
                "event_tier": features.get("event_tier", 0.2),
                "is_lan": features.get("is_lan", 0),
            })

        X = np.array(X, dtype=np.float64)
        y = np.array(y)
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

        # Temporal CV predictions
        n_splits = min(5, max(2, len(y) // 50))
        tscv = TimeSeriesSplit(n_splits=n_splits)
        all_probs = np.zeros(len(y))
        all_mask = np.zeros(len(y), dtype=bool)

        if self.model is not None:
            X_scaled = self.scaler.transform(X) if self.scaler else X
            params = self._default_params()
            xgb_m, gbt_m, lgbm_m, lr_m = self._build_models(params)

            for train_idx, test_idx in tscv.split(X):
                xgb_m.fit(X[train_idx], y[train_idx])
                gbt_m.fit(X[train_idx], y[train_idx])
                lr_m.fit(X_scaled[train_idx], y[train_idx])
                preds = [
                    xgb_m.predict_proba(X[test_idx])[:, 1],
                    gbt_m.predict_proba(X[test_idx])[:, 1],
                    lr_m.predict_proba(X_scaled[test_idx])[:, 1],
                ]
                if lgbm_m is not None:
                    lgbm_m.fit(X[train_idx], y[train_idx])
                    preds.append(lgbm_m.predict_proba(X[test_idx])[:, 1])
                all_probs[test_idx] = np.mean(preds, axis=0)
                all_mask[test_idx] = True

        probs = all_probs[all_mask]
        labels = y[all_mask]
        meta_filtered = [meta[i] for i in range(len(meta)) if all_mask[i]]

        # Reliability diagram data (10 bins)
        reliability = self._compute_reliability_diagram(probs, labels)

        # Tier breakdown
        tier_results = self._compute_tier_breakdown(probs, labels, meta_filtered)

        return {
            "overall": {
                "accuracy": float(accuracy_score(labels, (probs >= 0.5).astype(int))),
                "brier": float(brier_score_loss(labels, probs)),
                "log_loss": float(log_loss(labels, np.clip(probs, 1e-7, 1 - 1e-7))),
                "n_samples": int(len(labels)),
            },
            "reliability_diagram": reliability,
            "tier_breakdown": tier_results,
        }

    def _compute_reliability_diagram(self, probs, labels, n_bins=10):
        """Compute reliability diagram data for calibration visualization."""
        bins = np.linspace(0, 1, n_bins + 1)
        result = []
        for i in range(n_bins):
            mask = (probs >= bins[i]) & (probs < bins[i + 1])
            if mask.sum() == 0:
                continue
            bin_probs = probs[mask]
            bin_labels = labels[mask]
            result.append({
                "bin_center": round((bins[i] + bins[i + 1]) / 2, 2),
                "mean_predicted": round(float(bin_probs.mean()), 4),
                "mean_actual": round(float(bin_labels.mean()), 4),
                "count": int(mask.sum()),
            })
        return result

    def _compute_tier_breakdown(self, probs, labels, meta_list):
        """Accuracy breakdown by match tier (close vs easy)."""
        results = {}

        # By ranking difference
        for tier_name, condition in [
            ("top10_vs_top10", lambda m: m["ranking_diff_abs"] <= 10),
            ("top10_vs_rest", lambda m: 10 < m["ranking_diff_abs"] <= 30),
            ("easy_matches", lambda m: m["ranking_diff_abs"] > 30),
        ]:
            mask = [condition(m) for m in meta_list]
            mask = np.array(mask)
            if mask.sum() > 0:
                t_probs = probs[mask]
                t_labels = labels[mask]
                results[tier_name] = {
                    "accuracy": round(float(accuracy_score(t_labels, (t_probs >= 0.5).astype(int))), 4),
                    "brier": round(float(brier_score_loss(t_labels, t_probs)), 4),
                    "count": int(mask.sum()),
                }

        # LAN vs Online
        lan_mask = np.array([m["is_lan"] > 0 for m in meta_list])
        if lan_mask.sum() > 0:
            results["lan"] = {
                "accuracy": round(float(accuracy_score(labels[lan_mask], (probs[lan_mask] >= 0.5).astype(int))), 4),
                "count": int(lan_mask.sum()),
            }
        online_mask = ~lan_mask
        if online_mask.sum() > 0:
            results["online"] = {
                "accuracy": round(float(accuracy_score(labels[online_mask], (probs[online_mask] >= 0.5).astype(int))), 4),
                "count": int(online_mask.sum()),
            }

        return results

    # ═══════════════════════════════════════════════════════
    #  INTERNAL HELPERS
    # ═══════════════════════════════════════════════════════

    def _model_agreement(self, probs):
        winners = [p > 0.5 for p in probs]
        spread = max(probs) - min(probs)
        if all(winners) or not any(winners):
            return max(0, 1.0 - spread * 2)
        std = float(np.std(probs))
        return max(0.1, 1.0 - std * 6)

    def _compute_confidence(self, prob_spread, model_agreement, features):
        base = 1.0 / (1.0 + math.exp(-8 * (prob_spread - 0.15)))
        agreement_factor = 0.7 + 0.3 * model_agreement
        h2h_data = features.get("h2h_matches", 0)
        data_factor = 0.8 + 0.2 * min(h2h_data, 1.0)
        return min(base * agreement_factor * data_factor, 1.0)

    def _heuristic_predict(self, features):
        weights = {
            "elo_diff": 0.16, "glicko2_diff": 0.14, "ranking_diff": 0.08,
            "win_rate_30d_diff": 0.10, "win_rate_90d_diff": 0.06,
            "recent_form_5_diff": 0.07, "h2h_advantage": 0.06,
            "map_wr_diff": 0.05, "player_rating_diff": 0.05,
            "streak_diff": 0.03, "vs_top10_diff": 0.04, "star_player_diff": 0.03,
            "rest_diff": 0.02, "roster_stability_diff": 0.02,
            "close_map_resilience_diff": 0.02,
            "sos_win_rate_diff": 0.04, "ct_wr_diff": 0.02, "pistol_wr_diff": 0.01,
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
        is_lan = features.get("is_lan", 0)
        is_playoff = features.get("is_playoff", 0)
        if is_lan:
            score *= 1.05
        if is_playoff:
            score *= 1.08
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

        sos = features.get("sos_win_rate_diff", 0)
        if abs(sos) > 0.1:
            b = team1_name if sos > 0 else team2_name
            points.append(f"{b} has a better strength-of-schedule adjusted record")

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

        ct_diff = features.get("ct_wr_diff", 0)
        if abs(ct_diff) > 0.1:
            b = team1_name if ct_diff > 0 else team2_name
            points.append(f"{b} has better CT-side execution")

        pistol = features.get("pistol_wr_diff", 0)
        if abs(pistol) > 0.1:
            b = team1_name if pistol > 0 else team2_name
            points.append(f"{b} wins more pistol rounds")

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

        tm = features.get("tournament_momentum_diff", 0)
        if abs(tm) > 0.15:
            b = team1_name if tm > 0 else team2_name
            points.append(f"{b} has stronger tournament momentum")

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
