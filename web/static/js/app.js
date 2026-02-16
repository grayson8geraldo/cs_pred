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

    const btn = document.getElementById("btn-predict");
    btn.disabled = true;
    btn.textContent = "Predicting...";

    try {
        const result = await apiPost("/api/predict", {
            team1_id: parseInt(team1Id),
            team2_id: parseInt(team2Id),
            map_name: mapName,
            is_lan: isLan,
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
    document.getElementById("result-method").textContent =
        `Method: ${result.method === "xgboost" ? "XGBoost ML Model" : "Heuristic (Weighted Ratings)"}`;

    // Analysis
    const points = document.getElementById("analysis-points");
    points.innerHTML = result.analysis.map(p => `<li>${p}</li>`).join("");

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
