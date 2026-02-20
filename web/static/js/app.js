/* ═══════════════════════════════════════════
   CS2 PREDICTOR — Frontend Logic
   ═══════════════════════════════════════════ */

// ─── API Helpers ───

async function apiGet(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
}

async function apiPost(url, data = {}) {
    const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.error || err.message || `HTTP ${resp.status}`);
    }
    return resp.json();
}

// ─── Toast ───

function showToast(message, type = "success") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(100%)";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ─── Team Search Autocomplete ───

function setupTeamSearch(inputId, dropdownId, hiddenId, selectedId) {
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    const hidden = document.getElementById(hiddenId);
    const selected = document.getElementById(selectedId);

    if (!input) return;

    let debounce = null;

    input.addEventListener("input", () => {
        clearTimeout(debounce);
        debounce = setTimeout(async () => {
            const q = input.value.trim();
            if (q.length < 1) {
                dropdown.classList.remove("show");
                return;
            }
            try {
                const teams = await apiGet(`/api/teams/search?q=${encodeURIComponent(q)}`);
                dropdown.innerHTML = "";
                if (teams.length === 0) {
                    dropdown.classList.remove("show");
                    return;
                }
                teams.forEach(t => {
                    const item = document.createElement("div");
                    item.className = "dropdown-item";
                    item.textContent = t.name + (t.world_ranking ? ` (#${t.world_ranking})` : "");
                    item.addEventListener("click", () => {
                        hidden.value = t.id;
                        selected.textContent = t.name;
                        input.value = t.name;
                        dropdown.classList.remove("show");
                    });
                    dropdown.appendChild(item);
                });
                dropdown.classList.add("show");
            } catch (e) {
                console.error("Search failed:", e);
            }
        }, 250);
    });

    document.addEventListener("click", (e) => {
        if (!dropdown.contains(e.target) && e.target !== input) {
            dropdown.classList.remove("show");
        }
    });
}

// ─── Dashboard Init ───

document.addEventListener("DOMContentLoaded", () => {
    // Only init dashboard elements if we're on the dashboard page
    if (document.querySelector(".dashboard")) {
        initDashboard();
    }

    // Refresh button (all pages)
    const refreshBtn = document.getElementById("btn-refresh");
    if (refreshBtn) {
        refreshBtn.addEventListener("click", refreshData);
    }
});

async function initDashboard() {
    // Setup team search
    setupTeamSearch("team1-search", "team1-dropdown", "team1-id", "team1-selected");
    setupTeamSearch("team2-search", "team2-dropdown", "team2-id", "team2-selected");

    // Predict button
    const predictBtn = document.getElementById("btn-predict");
    if (predictBtn) {
        predictBtn.addEventListener("click", makePrediction);
    }

    // Load data
    loadOverview();
    loadRecentMatches();
}

async function loadOverview() {
    try {
        const data = await apiGet("/api/stats/overview");
        document.getElementById("stat-matches").textContent = data.total_matches;
        document.getElementById("stat-teams").textContent = data.total_teams;
        document.getElementById("stat-predictions").textContent = data.total_predictions;
        document.getElementById("stat-accuracy").textContent =
            data.accuracy ? data.accuracy.toFixed(1) + "%" : "N/A";

        // Top teams
        const topTeams = document.getElementById("top-teams");
        if (topTeams && data.top_teams && data.top_teams.length) {
            topTeams.innerHTML = data.top_teams.map((t, i) => `
                <div class="top-team-item">
                    <span class="top-team-rank ${i < 3 ? 'gold' : ''}">${i + 1}</span>
                    <span class="top-team-name">${t.name}</span>
                    <span class="top-team-elo">${t.elo.toFixed(0)}</span>
                </div>
            `).join("");
        }
    } catch (e) {
        console.error("Failed to load overview:", e);
    }
}

async function loadRecentMatches() {
    try {
        const data = await apiGet("/api/matches/recent?limit=20");
        const tbody = document.querySelector("#recent-matches tbody");
        if (!tbody) return;
        tbody.innerHTML = "";
        data.forEach(m => {
            const row = document.createElement("tr");
            const date = m.match_date ? new Date(m.match_date).toLocaleDateString("ru-RU") : "-";
            const t1Class = m.winner_name === m.team1_name ? "winner" : "";
            const t2Class = m.winner_name === m.team2_name ? "winner" : "";
            row.innerHTML = `
                <td>${date}</td>
                <td class="${t1Class}">${m.team1_name}</td>
                <td>${m.team1_score ?? "-"} : ${m.team2_score ?? "-"}</td>
                <td class="${t2Class}">${m.team2_name}</td>
                <td>${m.event_name || "-"}</td>
            `;
            tbody.appendChild(row);
        });
    } catch (e) {
        console.error("Failed to load matches:", e);
    }
}

// ─── Prediction ───

async function makePrediction() {
    const team1Id = document.getElementById("team1-id").value;
    const team2Id = document.getElementById("team2-id").value;

    if (!team1Id || !team2Id) {
        showToast("Please select both teams", "warning");
        return;
    }
    if (team1Id === team2Id) {
        showToast("Please select different teams", "warning");
        return;
    }

    const mapName = document.getElementById("map-select").value || null;
    const isLan = document.getElementById("is-lan").checked;
    const isPlayoff = document.getElementById("is-playoff").checked;
    const bestOf = parseInt(document.getElementById("best-of").value) || 1;
    const eventName = document.getElementById("event-name").value || "";
    const oddsT1 = parseFloat(document.getElementById("odds-t1").value) || null;
    const oddsT2 = parseFloat(document.getElementById("odds-t2").value) || null;

    const btn = document.getElementById("btn-predict");
    btn.disabled = true;
    btn.textContent = "Predicting...";

    try {
        const result = await apiPost("/api/predict", {
            team1_id: parseInt(team1Id),
            team2_id: parseInt(team2Id),
            map_name: mapName,
            is_lan: isLan,
            is_playoff: isPlayoff,
            best_of: bestOf,
            event_name: eventName,
            bookmaker_odds_team1: oddsT1,
            bookmaker_odds_team2: oddsT2,
        });

        displayPrediction(result);
        showToast("Prediction complete!", "success");
    } catch (e) {
        showToast("Prediction failed: " + e.message, "error");
    }

    btn.disabled = false;
    btn.textContent = "Predict";
}

function displayPrediction(result) {
    const container = document.getElementById("prediction-result");
    container.classList.remove("hidden");

    // Confidence badge
    const confBadge = document.getElementById("result-confidence");
    confBadge.textContent = `${result.confidence_label} confidence (${(result.confidence * 100).toFixed(1)}%)`;
    confBadge.className = `confidence-badge confidence-${result.confidence_label}`;

    // Team 1
    const t1 = document.getElementById("result-team1");
    const isT1Winner = result.team1.win_prob > result.team2.win_prob;
    t1.className = `result-team ${isT1Winner ? "winner" : ""}`;
    t1.querySelector(".team-name").textContent = result.team1.name;
    t1.querySelector(".win-prob").textContent = (result.team1.win_prob * 100).toFixed(1) + "%";
    t1.querySelector(".prob-fill").style.width = (result.team1.win_prob * 100) + "%";

    // Team 2
    const t2 = document.getElementById("result-team2");
    t2.className = `result-team ${!isT1Winner ? "winner" : ""}`;
    t2.querySelector(".team-name").textContent = result.team2.name;
    t2.querySelector(".win-prob").textContent = (result.team2.win_prob * 100).toFixed(1) + "%";
    t2.querySelector(".prob-fill").style.width = (result.team2.win_prob * 100) + "%";

    // Winner
    document.getElementById("result-winner").textContent =
        `Predicted Winner: ${result.predicted_winner}`;

    // Method
    const methodNames = {
        "stacking_ensemble": "Stacking Ensemble (XGB + GBT + LGBM + LR)",
        "ensemble": "Ensemble (XGB + GBT + LR)",
        "heuristic": "Heuristic (Weighted Ratings)",
    };
    document.getElementById("result-method").textContent =
        `Method: ${methodNames[result.method] || result.method}`;

    // BO3/BO5 Series Simulation
    const seriesDiv = document.getElementById("result-series");
    if (result.series_simulation) {
        seriesDiv.classList.remove("hidden");
        const sim = result.series_simulation;

        // Overview
        document.getElementById("series-overview").innerHTML = `
            <div class="series-probs">
                <div class="series-prob-item">
                    <span class="name">${result.team1.name} wins series</span>
                    <span class="value ${sim.team1_series_win_prob > 0.5 ? 'positive' : ''}">${(sim.team1_series_win_prob * 100).toFixed(1)}%</span>
                </div>
                <div class="series-prob-item">
                    <span class="name">${result.team2.name} wins series</span>
                    <span class="value ${sim.team2_series_win_prob > 0.5 ? 'positive' : ''}">${(sim.team2_series_win_prob * 100).toFixed(1)}%</span>
                </div>
            </div>
        `;

        // Score probabilities
        const scores = sim.score_probabilities;
        document.getElementById("series-scores").innerHTML = `
            <div class="series-score-grid">
                ${Object.entries(scores).map(([score, prob]) => `
                    <div class="score-item">
                        <span class="score-label">${score}</span>
                        <div class="score-bar-wrap">
                            <div class="score-bar" style="width: ${prob * 100 * 2.5}%"></div>
                        </div>
                        <span class="score-prob">${(prob * 100).toFixed(1)}%</span>
                    </div>
                `).join("")}
            </div>
        `;

        // Map probabilities
        const maps = sim.map_probabilities;
        document.getElementById("series-maps").innerHTML = `
            <div class="series-map-grid">
                ${Object.entries(maps).map(([mapName, prob]) => `
                    <div class="feature-item">
                        <span class="name">${mapName}</span>
                        <span class="value ${prob > 0.5 ? 'positive' : 'negative'}">${result.team1.name}: ${(prob * 100).toFixed(1)}%</span>
                    </div>
                `).join("")}
            </div>
        `;
    } else {
        seriesDiv.classList.add("hidden");
    }

    // Analysis
    const points = document.getElementById("analysis-points");
    points.innerHTML = result.analysis.map(p => `<li>${p}</li>`).join("");

    // Model agreement (ensemble only)
    const modelsDiv = document.getElementById("result-models");
    if (result.model_probabilities) {
        modelsDiv.classList.remove("hidden");
        const mg = document.getElementById("models-grid");
        const mp = result.model_probabilities;
        let html = `
            <div class="feature-item"><span class="name">XGBoost</span><span class="value">${(mp.xgboost * 100).toFixed(1)}%</span></div>
            <div class="feature-item"><span class="name">Gradient Boosting</span><span class="value">${(mp.gradient_boosting * 100).toFixed(1)}%</span></div>
            <div class="feature-item"><span class="name">Logistic Regression</span><span class="value">${(mp.logistic_regression * 100).toFixed(1)}%</span></div>
        `;
        if (mp.lightgbm !== undefined) {
            html += `<div class="feature-item"><span class="name">LightGBM</span><span class="value">${(mp.lightgbm * 100).toFixed(1)}%</span></div>`;
        }
        html += `<div class="feature-item"><span class="name">Agreement</span><span class="value ${mp.agreement > 0.7 ? 'positive' : mp.agreement < 0.4 ? 'negative' : ''}">${(mp.agreement * 100).toFixed(0)}%</span></div>`;
        mg.innerHTML = html;
    } else {
        modelsDiv.classList.add("hidden");
    }

    // Value bet
    const vbDiv = document.getElementById("result-value-bet");
    if (result.value_bet) {
        vbDiv.classList.remove("hidden");
        const vb = result.value_bet;
        let html = `<div class="features-grid">
            <div class="feature-item"><span class="name">${result.team1.name} implied</span><span class="value">${(vb.team1_implied_prob * 100).toFixed(1)}%</span></div>
            <div class="feature-item"><span class="name">${result.team2.name} implied</span><span class="value">${(vb.team2_implied_prob * 100).toFixed(1)}%</span></div>
            <div class="feature-item"><span class="name">${result.team1.name} edge</span><span class="value ${vb.team1_edge > 0 ? 'positive' : 'negative'}">${(vb.team1_edge * 100).toFixed(1)}%</span></div>
            <div class="feature-item"><span class="name">${result.team2.name} edge</span><span class="value ${vb.team2_edge > 0 ? 'positive' : 'negative'}">${(vb.team2_edge * 100).toFixed(1)}%</span></div>
        </div>`;
        if (vb.recommendation) {
            const r = vb.recommendation;
            html += `<div class="value-bet-rec ${r.rating}">
                VALUE BET: <strong>${r.team}</strong> @ ${r.odds} (edge: ${r.edge}%, EV: +${(r.ev_per_unit * 100).toFixed(1)}% per unit) [${r.rating.toUpperCase()}]
            </div>`;
        }
        document.getElementById("value-bet-content").innerHTML = html;
    } else {
        vbDiv.classList.add("hidden");
    }

    // Features
    const grid = document.getElementById("features-grid");
    grid.innerHTML = Object.entries(result.features).map(([k, v]) => {
        const cls = v > 0 ? "positive" : v < 0 ? "negative" : "";
        const label = k.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
        return `<div class="feature-item">
            <span class="name">${label}</span>
            <span class="value ${cls}">${typeof v === "number" ? v.toFixed(3) : v}</span>
        </div>`;
    }).join("");

    // Scroll to result
    container.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ─── Data Refresh ───

async function refreshData() {
    const btn = document.getElementById("btn-refresh");
    btn.disabled = true;
    btn.innerHTML = "&#8987; Loading...";

    try {
        const res = await apiPost("/api/data/refresh");
        showToast(`Data updated! ${res.upcoming_matches || 0} upcoming matches found.`, "success");
        // Reload page data
        if (document.querySelector(".dashboard")) {
            loadOverview();
            loadRecentMatches();
        }
    } catch (e) {
        showToast("Data refresh failed: " + e.message, "error");
    }

    btn.disabled = false;
    btn.innerHTML = "&#8635; Update";
}
