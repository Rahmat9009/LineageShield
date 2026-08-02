const demo = {
  asset_urn: "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)",
  column: "ORDER_ID",
  change_type: "rename",
  new_value: "PURCHASE_ID",
  reason: "Standardize order identifiers across warehouse and BI assets"
};

const el = id => document.getElementById(id);
const form = el("change-form");
const emptyState = el("empty-state");
const loading = el("loading");
const resultView = el("result");
let currentResult = null;
let currentTab = "migration";

function loadDemo() {
  el("asset-urn").value = demo.asset_urn;
  el("column").value = demo.column;
  el("change-type").value = demo.change_type;
  el("new-value").value = demo.new_value;
  el("reason").value = demo.reason;
}

function setView(view) {
  emptyState.classList.toggle("hidden", view !== "empty");
  loading.classList.toggle("hidden", view !== "loading");
  resultView.classList.toggle("hidden", view !== "result");
}

function artifactText(result, tab) {
  const artifacts = result.artifacts;
  if (tab === "migration") return artifacts.migration_sql;
  if (tab === "compatibility") return artifacts.compatibility_sql;
  if (tab === "tests") return artifacts.data_tests_yaml;
  return artifacts.pull_request_summary;
}

function renderArtifacts() {
  if (currentResult) {
    el("artifact-code").textContent = artifactText(
      currentResult,
      currentTab
    );
  }
}

function assetIcon(type) {
  return {
    dashboard: "▥",
    pipeline: "⌁",
    feature_table: "ƒ",
    ml_model: "M",
    dataset: "D"
  }[type] || "•";
}

function render(data) {
  currentResult = data;
  el("decision").textContent = data.decision;
  el("risk-score").textContent = `${data.risk_score}/100`;
  el("risk-level").textContent = data.risk_level;
  el("meter-fill").style.width = `${data.risk_score}%`;
  el("explanation").textContent = data.explanation;
  el("asset-count").textContent =
    `${data.affected_assets.length} downstream assets`;

  el("decision").style.background =
    data.decision === "ALLOW"
      ? "var(--green)"
      : data.decision === "REVIEW"
        ? "var(--yellow)"
        : "var(--red)";

  el("assets").innerHTML = data.affected_assets.map(asset => `
    <div class="asset">
      <div class="asset-icon">${assetIcon(asset.asset_type)}</div>
      <div class="asset-body">
        <div class="asset-name">${asset.name}</div>
        <div class="asset-meta">
          ${asset.platform} ·
          ${asset.asset_type.replace("_", " ")} ·
          ${asset.owners.join(", ") || "owner not loaded yet"}
        </div>
      </div>
      <div class="asset-risk">${asset.criticality.toUpperCase()}</div>
    </div>
  `).join("");

  el("factors").innerHTML = data.factors.map(factor => `
    <div class="factor">
      <div class="factor-body">
        <div class="factor-label">${factor.label}</div>
        <div class="factor-evidence">${factor.evidence}</div>
      </div>
      <div class="factor-points">+${factor.points}</div>
    </div>
  `).join("");

  el("approvals").innerHTML = data.required_approvals.length
    ? data.required_approvals
        .map(owner => `<span class="chip">${owner}</span>`)
        .join("")
    : `<span class="chip">Owner enrichment is the next milestone</span>`;

  renderArtifacts();
  setView("result");
}

async function analyze(event) {
  event.preventDefault();

  const payload = {
    asset_urn: el("asset-urn").value.trim(),
    column: el("column").value.trim(),
    change_type: el("change-type").value,
    new_value: el("new-value").value.trim() || null,
    reason: el("reason").value.trim()
  };

  setView("loading");

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    });

    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.detail || "Analysis failed");
    }

    render(body);
  } catch (error) {
    setView("empty");
    alert(error.message);
  }
}

async function updateConnectionStatus() {
  const status = document.querySelector(".status");

  try {
    const response = await fetch("/api/health");
    const body = await response.json();

    status.innerHTML =
      `<span></span> ${
        body.context_provider === "datahub"
          ? "Live DataHub connected"
          : "Demo context connected"
      }`;
  } catch {
    status.textContent = "Backend unavailable";
  }
}

form.addEventListener("submit", analyze);
el("load-demo").addEventListener("click", loadDemo);

document.querySelectorAll(".tab").forEach(button => {
  button.addEventListener("click", () => {
    document
      .querySelectorAll(".tab")
      .forEach(item => item.classList.remove("active"));

    button.classList.add("active");
    currentTab = button.dataset.tab;
    renderArtifacts();
  });
});

el("download-json").addEventListener("click", () => {
  if (!currentResult) return;

  const blob = new Blob(
    [JSON.stringify(currentResult, null, 2)],
    {type: "application/json"}
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = `lineageshield-${currentResult.analysis_id}.json`;
  link.click();
  URL.revokeObjectURL(url);
});

loadDemo();
updateConnectionStatus();
