import {analyzeChange, applyWriteback, getHealth, previewWriteback} from "./api.js";
import {assetGroup, assetTypeLabel, renderLineage} from "./lineage.js";

const SAMPLE_SCENARIO = {
  asset_urn: "urn:li:dataset:(urn:li:dataPlatform:snowflake,b2fd91.order_entry_db.analytics.order_details,PROD)",
  column: "ORDER_ID",
  change_type: "rename",
  new_value: "PURCHASE_ID",
  reason: "Standardize order identifiers across warehouse and BI assets"
};

const CHANGE_COPY = {
  rename: {
    label: "New column name",
    help: "The replacement identifier downstream consumers must adopt.",
    warning: null
  },
  type_change: {
    label: "New data type",
    help: "Use the target warehouse type, for example NUMBER(38,0) or VARCHAR.",
    warning: {
      title: "Potentially breaking change",
      copy: "A type change can reject, truncate, or reinterpret values in downstream consumers.",
      risk: "breaking"
    }
  },
  add: {
    label: "Column data type",
    help: "Define the warehouse type for the new column.",
    warning: null
  },
  drop: {
    label: "New value",
    help: "Not required for a drop operation.",
    warning: {
      title: "Destructive change",
      copy: "Dropping a column requires every dependent consumer to migrate before removal.",
      risk: "destructive"
    }
  }
};

const ARTIFACTS = {
  migration: {key: "migration_sql", filename: "migration.sql"},
  compatibility: {key: "compatibility_sql", filename: "compatibility_view.sql"},
  tests: {key: "data_tests_yaml", filename: "schema_tests.yml"},
  rollback: {key: "rollback_plan", filename: "ROLLBACK.md"},
  pr: {key: "pull_request_summary", filename: "PULL_REQUEST.md"}
};

const PROGRESS_LABELS = [
  "Resolving source asset",
  "Traversing downstream lineage",
  "Classifying affected assets",
  "Calculating deterministic risk",
  "Generating safeguards"
];

const byId = id => document.getElementById(id);

const elements = {
  form: byId("change-form"),
  assetUrn: byId("asset-urn"),
  column: byId("column"),
  changeType: byId("change-type"),
  newValue: byId("new-value"),
  newValueField: byId("new-value-field"),
  newValueLabel: byId("new-value-label"),
  newValueHelp: byId("new-value-help"),
  reason: byId("reason"),
  changeWarning: byId("change-warning"),
  changeWarningTitle: byId("change-warning-title"),
  changeWarningCopy: byId("change-warning-copy"),
  formSummary: byId("form-error-summary"),
  analyzeButton: byId("analyze-button"),
  emptyState: byId("empty-state"),
  loadingState: byId("loading-state"),
  errorState: byId("error-state"),
  resultView: byId("result-view"),
  loadingTitle: byId("loading-title"),
  progressFill: byId("progress-fill"),
  progressStages: [...document.querySelectorAll("#progress-stages li")],
  errorTitle: byId("error-title"),
  errorMessage: byId("error-message"),
  systemState: byId("system-state"),
  connectionLabel: byId("connection-label"),
  connectionDetail: byId("connection-detail"),
  providerLabel: byId("provider-label"),
  retryHealth: byId("retry-health"),
  decisionPanel: byId("decision-panel"),
  decision: byId("decision"),
  riskLevel: byId("risk-level"),
  explanation: byId("explanation"),
  riskScore: byId("risk-score"),
  scoreMeterFill: byId("score-meter-fill"),
  assetMetric: byId("asset-metric"),
  platformMetric: byId("platform-metric"),
  platformSummary: byId("platform-summary"),
  approvalMetric: byId("approval-metric"),
  approvalSummary: byId("approval-summary"),
  lineageCanvas: byId("lineage-canvas"),
  lineageNote: byId("lineage-note"),
  inspectorType: byId("inspector-type"),
  inspectorTitle: byId("node-inspector-title"),
  inspectorDescription: byId("inspector-description"),
  inspectorMetadata: byId("inspector-metadata"),
  inspectorUrnBlock: byId("inspector-urn-block"),
  inspectorUrn: byId("inspector-urn"),
  assetSearch: byId("asset-search"),
  typeFilter: byId("asset-type-filter"),
  platformFilter: byId("platform-filter"),
  criticalityFilter: byId("criticality-filter"),
  assetCount: byId("asset-count"),
  assets: byId("assets"),
  assetsEmpty: byId("assets-empty"),
  rawScore: byId("raw-score"),
  scoreCapNote: byId("score-cap-note"),
  factors: byId("factors"),
  approvals: byId("approvals"),
  artifactPanel: byId("artifact-panel"),
  artifactFilename: byId("artifact-filename"),
  artifactCode: byId("artifact-code").querySelector("code"),
  copyStatus: byId("copy-status"),
  writebackStatus: byId("writeback-status"),
  writebackAvailability: byId("writeback-availability"),
  previewWriteback: byId("preview-writeback"),
  writebackFeedback: byId("writeback-feedback"),
  writebackPreview: byId("writeback-preview"),
  writebackTarget: byId("writeback-target"),
  writebackTargetUrn: byId("writeback-target-urn"),
  writebackDecision: byId("writeback-decision"),
  writebackRisk: byId("writeback-risk"),
  writebackIdempotency: byId("writeback-idempotency"),
  writebackManagedSection: byId("writeback-managed-section"),
  writebackResultingDescription: byId("writeback-resulting-description"),
  writebackWarnings: byId("writeback-warnings"),
  writebackConfirm: byId("writeback-confirm"),
  applyWriteback: byId("apply-writeback"),
  writebackReceipt: byId("writeback-receipt"),
  receiptTitle: byId("receipt-title"),
  receiptAnalysis: byId("receipt-analysis"),
  receiptAsset: byId("receipt-asset"),
  receiptOperation: byId("receipt-operation"),
  receiptTime: byId("receipt-time"),
  receiptMessage: byId("receipt-message")
};

const state = {
  result: null,
  lastPayload: null,
  selectedAsset: null,
  artifactTab: "migration",
  provider: null,
  mutationsEnabled: false,
  writebackPreview: null,
  writebackOutcomeUnknown: false,
  progressTimers: [],
  copyTimer: null
};

function setView(view) {
  elements.emptyState.classList.toggle("is-hidden", view !== "empty");
  elements.loadingState.classList.toggle("is-hidden", view !== "loading");
  elements.errorState.classList.toggle("is-hidden", view !== "error");
  elements.resultView.classList.toggle("is-hidden", view !== "result");
}

function appendTextWithSuffix(container, value, suffix) {
  const suffixNode = document.createElement("span");
  suffixNode.textContent = suffix;
  container.replaceChildren(document.createTextNode(String(value)), suffixNode);
}

function readableNameFromUrn(urn) {
  if (!urn) return "Unnamed asset";
  const inner = urn.includes("(") ? urn.slice(urn.indexOf("(") + 1, urn.lastIndexOf(")")) : urn;
  const parts = inner.split(",");
  const candidate = parts.length >= 2 ? parts[parts.length - 2] : parts.at(-1);
  const decoded = decodeURIComponent(candidate || urn).replace(/^urn:li:[^:]+:/, "");
  return decoded.replace(/[._-]+/g, " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

function setFieldError(input, message) {
  const error = byId(`${input.id}-error`);
  if (error) error.textContent = message;
  input.setAttribute("aria-invalid", message ? "true" : "false");
}

function validateInput(input) {
  let message = "";
  const value = input.value.trim();

  if (input === elements.assetUrn) {
    if (!value) message = "Enter a DataHub asset URN.";
    else if (!value.startsWith("urn:li:")) message = "The asset must be a valid DataHub URN beginning with urn:li:.";
  }

  if (input === elements.column && !value) {
    message = "Enter the column being changed.";
  }

  if (input === elements.newValue && !input.disabled) {
    if (!value) {
      message = `${CHANGE_COPY[elements.changeType.value].label} is required.`;
    } else if (elements.changeType.value === "rename" && value === elements.column.value.trim()) {
      message = "The new column name must differ from the current column.";
    }
  }

  setFieldError(input, message);
  return !message;
}

function validateForm() {
  const inputs = [elements.assetUrn, elements.column];
  if (!elements.newValue.disabled) inputs.push(elements.newValue);
  const valid = inputs.map(validateInput).every(Boolean);

  elements.formSummary.textContent = valid
    ? ""
    : "Resolve the highlighted fields before running the investigation.";
  elements.formSummary.classList.toggle("is-hidden", valid);

  if (!valid) inputs.find(input => input.getAttribute("aria-invalid") === "true")?.focus();
  return valid;
}

function updateChangeType() {
  const changeType = elements.changeType.value;
  const config = CHANGE_COPY[changeType];
  const isDrop = changeType === "drop";

  elements.newValueField.classList.toggle("is-hidden", isDrop);
  elements.newValue.disabled = isDrop;
  elements.newValue.required = !isDrop;
  elements.newValueLabel.replaceChildren(
    document.createTextNode(`${config.label} `),
    Object.assign(document.createElement("span"), {textContent: "*"})
  );
  elements.newValueLabel.lastElementChild.setAttribute("aria-hidden", "true");
  elements.newValueHelp.textContent = config.help;
  setFieldError(elements.newValue, "");

  elements.changeWarning.classList.toggle("is-hidden", !config.warning);
  elements.form.dataset.changeRisk = config.warning?.risk || "standard";
  if (config.warning) {
    elements.changeWarningTitle.textContent = config.warning.title;
    elements.changeWarningCopy.textContent = config.warning.copy;
  }
}

function loadSample({announce = true} = {}) {
  elements.assetUrn.value = SAMPLE_SCENARIO.asset_urn;
  elements.column.value = SAMPLE_SCENARIO.column;
  elements.changeType.value = SAMPLE_SCENARIO.change_type;
  elements.newValue.value = SAMPLE_SCENARIO.new_value;
  elements.reason.value = SAMPLE_SCENARIO.reason;
  updateChangeType();
  [elements.assetUrn, elements.column, elements.newValue].forEach(input => setFieldError(input, ""));
  elements.formSummary.classList.add("is-hidden");
  if (announce) {
    elements.formSummary.textContent = "Sample scenario loaded. Review the proposal, then run the investigation.";
    elements.formSummary.classList.remove("is-hidden");
    elements.formSummary.style.borderLeftColor = "var(--accent)";
    window.setTimeout(() => {
      elements.formSummary.classList.add("is-hidden");
      elements.formSummary.style.removeProperty("border-left-color");
    }, 3500);
  }
}

async function updateConnectionStatus() {
  elements.systemState.dataset.state = "checking";
  elements.connectionLabel.textContent = "Checking connection";
  elements.connectionDetail.textContent = "Verifying backend and provider";
  elements.providerLabel.textContent = "—";
  elements.retryHealth.classList.add("is-hidden");

  try {
    const health = await getHealth();
    const provider = health.provider || health.context_provider || "unknown";
    const connected = health.connected !== false && health.status === "ok";
    state.provider = provider;
    state.mutationsEnabled = health.mutations_enabled === true;
    elements.providerLabel.textContent = provider;
    elements.systemState.dataset.state = connected ? "connected" : "unavailable";

    if (provider === "datahub") {
      elements.connectionLabel.textContent = connected ? "Live DataHub connected" : "DataHub unavailable";
      elements.connectionDetail.textContent = health.detail || (connected
        ? "Read-only lineage provider is ready"
        : "Start DataHub, then retry the check");
    } else {
      elements.connectionLabel.textContent = connected ? "Demo provider active" : "Provider unavailable";
      elements.connectionDetail.textContent = health.detail || "Analysis is not using live DataHub metadata";
    }
    elements.retryHealth.classList.toggle("is-hidden", connected);
    renderWritebackAvailability();
  } catch (error) {
    elements.systemState.dataset.state = "unavailable";
    elements.connectionLabel.textContent = "Backend unavailable";
    elements.connectionDetail.textContent = error.message;
    elements.providerLabel.textContent = "offline";
    elements.retryHealth.classList.remove("is-hidden");
    state.provider = null;
    state.mutationsEnabled = false;
    renderWritebackAvailability({connectionFailed: true});
  }
}

function resetProgress() {
  state.progressTimers.forEach(timer => window.clearTimeout(timer));
  state.progressTimers = [];
  elements.progressStages.forEach(stage => stage.classList.remove("is-active", "is-complete"));
  elements.progressStages[0].classList.add("is-active");
  elements.loadingTitle.textContent = PROGRESS_LABELS[0];
  elements.progressFill.style.width = "10%";
}

function startProgress() {
  resetProgress();
  const delays = [800, 1650, 2500, 3350];
  delays.forEach((delay, index) => {
    const target = index + 1;
    state.progressTimers.push(window.setTimeout(() => {
      elements.progressStages.forEach((stage, stageIndex) => {
        stage.classList.toggle("is-complete", stageIndex < target);
        stage.classList.toggle("is-active", stageIndex === target);
      });
      elements.loadingTitle.textContent = PROGRESS_LABELS[target];
      elements.progressFill.style.width = `${18 + target * 18}%`;
    }, delay));
  });
}

function stopProgress() {
  state.progressTimers.forEach(timer => window.clearTimeout(timer));
  state.progressTimers = [];
}

function payloadFromForm() {
  return {
    asset_urn: elements.assetUrn.value.trim(),
    column: elements.column.value.trim(),
    change_type: elements.changeType.value,
    new_value: elements.changeType.value === "drop" ? null : elements.newValue.value.trim(),
    reason: elements.reason.value.trim()
  };
}

async function runInvestigation(payload) {
  state.lastPayload = payload;
  elements.analyzeButton.disabled = true;
  setView("loading");
  startProgress();

  try {
    const result = await analyzeChange(payload);
    stopProgress();
    renderResult(result);
    setView("result");
    elements.decisionPanel.scrollIntoView({behavior: "smooth", block: "start"});
  } catch (error) {
    stopProgress();
    elements.errorTitle.textContent = error.status === 503
      ? "DataHub could not complete the investigation"
      : "Investigation could not be completed";
    elements.errorMessage.textContent = error.message;
    setView("error");
  } finally {
    elements.analyzeButton.disabled = false;
  }
}

function normalizeRootAsset(result) {
  return result.root_asset || {
    urn: state.lastPayload?.asset_urn || "",
    name: readableNameFromUrn(state.lastPayload?.asset_urn),
    asset_type: "dataset",
    platform: "unknown",
    criticality: "high",
    criticality_source: "fallback",
    owners: [],
    tags: [],
    glossary_terms: [],
    fields: [],
    quality_status: "unknown",
    usage_score: 0,
    metadata_sources: {}
  };
}

function displayPlatformList(platforms) {
  if (!platforms.length) return "None identified";
  if (platforms.length <= 3) return platforms.join(", ");
  return `${platforms.slice(0, 2).join(", ")} +${platforms.length - 2}`;
}

function renderDecision(result) {
  const platforms = [...new Set(result.affected_assets.map(asset => asset.platform).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
  const approvals = result.required_approvals || [];

  elements.decisionPanel.dataset.decision = result.decision;
  elements.decision.textContent = result.decision;
  elements.riskLevel.textContent = `${result.risk_level} RISK`;
  elements.explanation.textContent = result.explanation;
  appendTextWithSuffix(elements.riskScore, result.risk_score, "/100");
  elements.scoreMeterFill.style.width = `${Math.min(100, result.risk_score)}%`;
  elements.assetMetric.textContent = String(result.affected_assets.length);
  elements.platformMetric.textContent = String(platforms.length);
  elements.platformSummary.textContent = displayPlatformList(platforms);
  elements.approvalMetric.textContent = String(approvals.length);
  const metadataSummary = result.metadata_summary || {};
  elements.approvalSummary.textContent = approvals.length
    ? `${approvals.length} owner${approvals.length === 1 ? "" : "s"} identified`
    : (result.provider === "datahub"
      ? (metadataSummary.datahub_entities_enriched > 0
        ? (metadataSummary.assets_with_owners > 0
          ? "No high-impact owner approval required"
          : "No owners returned by DataHub")
        : "Owner metadata unavailable")
      : "No owner approval required");
}

function metadataPair(label, value) {
  const term = document.createElement("dt");
  const description = document.createElement("dd");
  term.textContent = label;
  description.textContent = value;
  return [term, description];
}

function summarizeMetadataList(values, {empty = "None stored in DataHub", limit = 6} = {}) {
  if (!Array.isArray(values) || !values.length) return empty;
  if (values.length <= limit) return values.join(", ");
  return `${values.slice(0, limit).join(", ")} +${values.length - limit}`;
}

function metadataSourceLabel(source) {
  const labels = {
    datahub: "DataHub",
    lineage: "DataHub lineage",
    inferred: "inferred fallback",
    fallback: "URN fallback",
    unavailable: "unavailable",
    demo: "demo metadata"
  };
  return labels[source] || "source unknown";
}

function inspectAsset(asset) {
  state.selectedAsset = asset;
  const isSource = asset.urn === normalizeRootAsset(state.result).urn;
  const sources = asset.metadata_sources || {};
  const ownerDetails = Array.isArray(asset.owner_details) ? asset.owner_details : [];
  const owners = ownerDetails.length
    ? ownerDetails.map(owner => owner.ownership_type
      ? `${owner.label} — ${owner.ownership_type}`
      : owner.label).join(", ")
    : (Array.isArray(asset.owners) && asset.owners.length
      ? asset.owners.join(", ")
      : (sources.owners === "datahub" ? "None stored in DataHub" : "Unavailable"));
  const qualitySource = metadataSourceLabel(sources.quality);
  const usage = sources.usage === "datahub"
    ? `${asset.usage_score || 0}/100 · DataHub`
    : "Unavailable · score kept at 0";
  const fields = summarizeMetadataList(asset.fields, {
    empty: sources.fields === "datahub" ? "No schema fields stored" : "Unavailable",
    limit: 5
  });
  const structuredPropertyCount = Object.keys(asset.structured_properties || {}).length;

  elements.inspectorType.textContent = `${isSource ? "SOURCE · " : ""}${assetTypeLabel(asset.asset_type).toUpperCase()}`;
  elements.inspectorTitle.textContent = asset.name || readableNameFromUrn(asset.urn);
  elements.inspectorDescription.textContent = asset.description || (isSource
    ? "The proposed column change originates from this asset."
    : "This asset appears in the live downstream impact response.");
  elements.inspectorMetadata.replaceChildren(
    ...metadataPair("Platform", asset.platform || "Unknown"),
    ...metadataPair(
      "Criticality",
      `${asset.criticality || "Unknown"} · ${metadataSourceLabel(asset.criticality_source)}`
    ),
    ...metadataPair("Dependency", asset.dependency_type || (isSource ? "Source" : "Downstream")),
    ...metadataPair("Owners", owners),
    ...metadataPair("Tags", summarizeMetadataList(asset.tags)),
    ...metadataPair("Glossary terms", summarizeMetadataList(asset.glossary_terms)),
    ...metadataPair("Schema fields", fields),
    ...metadataPair(
      "Quality",
      `${asset.quality_status || "Unknown"} · ${qualitySource}`
    ),
    ...metadataPair("Usage", usage),
    ...metadataPair(
      "Structured properties",
      structuredPropertyCount
        ? `${structuredPropertyCount} from DataHub`
        : "None available"
    ),
    ...metadataPair(
      "Entity metadata",
      sources.entity === "datahub" ? "Retrieved directly from DataHub" : "Safe fallbacks only"
    )
  );
  elements.inspectorUrn.textContent = asset.urn;
  elements.inspectorUrnBlock.classList.remove("is-hidden");
}

function renderLineageSection(result) {
  const rootAsset = normalizeRootAsset(result);
  const edges = result.lineage_edges || result.edges || [];
  renderLineage(
    elements.lineageCanvas,
    {rootAsset, assets: result.affected_assets, edges},
    inspectAsset
  );
  const notes = Array.isArray(result.context_notes) ? result.context_notes : [];
  elements.lineageNote.textContent = notes.length
    ? notes.join(" · ")
    : "Lineage scope and metadata reflect the active provider response at investigation time.";
}

function svgIcon(group) {
  const paths = {
    dataset: "M5 4.5h14v6H5v-6Zm0 9h14v6H5v-6Z",
    pipeline: "M6 4v16m0-8h12m-3-3 3 3-3 3",
    reporting: "M4 19V10h4v9m4 0V5h4v14m4 0v-6",
    ml: "M12 4v4m0 8v4M4 12h4m8 0h4M9 9h6v6H9Z",
    other: "M5 5h14v14H5z"
  };
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", "20");
  svg.setAttribute("height", "20");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", paths[group] || paths.other);
  svg.append(path);
  return svg;
}

function assetRow(asset) {
  const group = assetGroup(asset.asset_type);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "asset-row";
  button.setAttribute("aria-label", `Inspect ${asset.name || readableNameFromUrn(asset.urn)}`);

  const identity = document.createElement("span");
  identity.className = "asset-identity";
  const icon = document.createElement("span");
  icon.className = `asset-icon ${group}`;
  icon.append(svgIcon(group));
  const title = document.createElement("span");
  title.className = "asset-title";
  const name = document.createElement("strong");
  name.textContent = asset.name || readableNameFromUrn(asset.urn);
  const dependency = document.createElement("small");
  dependency.textContent = asset.dependency_type || "Downstream dependency";
  title.append(name, dependency);
  identity.append(icon, title);

  const context = document.createElement("span");
  context.className = "asset-context";
  const platform = document.createElement("strong");
  platform.textContent = asset.platform || "Unknown platform";
  const type = document.createElement("small");
  type.textContent = assetTypeLabel(asset.asset_type);
  context.append(platform, type);

  const criticality = document.createElement("span");
  criticality.className = `criticality-badge ${asset.criticality || "medium"}`;
  criticality.textContent = asset.criticality || "unknown";
  criticality.title = `Criticality source: ${metadataSourceLabel(asset.criticality_source)}`;
  button.append(identity, context, criticality);
  button.addEventListener("click", () => inspectAsset(asset));
  return button;
}

function populatePlatformFilter(assets) {
  const previous = elements.platformFilter.value;
  const options = [document.createElement("option")];
  options[0].value = "all";
  options[0].textContent = "All platforms";

  [...new Set(assets.map(asset => asset.platform).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b))
    .forEach(platform => {
      const option = document.createElement("option");
      option.value = platform.toLowerCase();
      option.textContent = platform;
      options.push(option);
    });
  elements.platformFilter.replaceChildren(...options);
  if ([...elements.platformFilter.options].some(option => option.value === previous)) {
    elements.platformFilter.value = previous;
  }
}

function filteredAssets() {
  if (!state.result) return [];
  const query = elements.assetSearch.value.trim().toLowerCase();
  const selectedType = elements.typeFilter.value;
  const platform = elements.platformFilter.value;
  const criticality = elements.criticalityFilter.value;

  return state.result.affected_assets.filter(asset => {
    const text = `${asset.name || ""} ${asset.platform || ""} ${asset.asset_type || ""}`.toLowerCase();
    return (!query || text.includes(query))
      && (selectedType === "all" || assetGroup(asset.asset_type) === selectedType)
      && (platform === "all" || String(asset.platform || "").toLowerCase() === platform)
      && (criticality === "all" || asset.criticality === criticality);
  });
}

function renderAssetList() {
  const assets = filteredAssets();
  elements.assets.replaceChildren(...assets.map(assetRow));
  elements.assetCount.textContent = `${assets.length} result${assets.length === 1 ? "" : "s"}`;
  elements.assetsEmpty.classList.toggle("is-hidden", assets.length > 0);
}

function renderRisk(result) {
  const rawScore = result.raw_risk_score
    ?? result.factors.reduce((sum, factor) => sum + factor.points, 0);
  elements.rawScore.textContent = `${rawScore} point${rawScore === 1 ? "" : "s"}`;
  elements.scoreCapNote.textContent = rawScore > 100
    ? `${rawScore} raw points are capped at 100.`
    : "Final score uses the factor total shown.";

  const factorRows = result.factors.map(factor => {
    const row = document.createElement("article");
    row.className = "factor-row";
    const label = document.createElement("strong");
    label.className = "factor-label";
    label.textContent = factor.label;
    const evidence = document.createElement("span");
    evidence.className = "factor-evidence";
    evidence.textContent = factor.evidence;
    const points = document.createElement("span");
    points.className = "factor-points";
    points.textContent = `+${factor.points}`;
    row.append(label, evidence, points);
    return row;
  });
  elements.factors.replaceChildren(...factorRows);

  const approvals = result.required_approvals || [];
  if (approvals.length) {
    elements.approvals.replaceChildren(...approvals.map(owner => {
      const chip = document.createElement("span");
      chip.className = "approval-chip";
      chip.textContent = owner;
      return chip;
    }));
  } else {
    const empty = document.createElement("span");
    empty.className = "approval-empty";
    empty.textContent = result.provider === "datahub"
      ? "No approvals identified from loaded owner metadata"
      : "No owner approval required by current evidence";
    elements.approvals.replaceChildren(empty);
  }
}

function artifactText(result, tab) {
  const value = result.artifacts?.[ARTIFACTS[tab].key];
  if (Array.isArray(value)) {
    return value.map((step, index) => `${index + 1}. ${step}`).join("\n");
  }
  return value || "No artifact was generated.";
}

function renderArtifact() {
  if (!state.result) return;
  const config = ARTIFACTS[state.artifactTab];
  elements.artifactFilename.textContent = config.filename;
  elements.artifactCode.textContent = artifactText(state.result, state.artifactTab);
  const activeTab = byId(`tab-${state.artifactTab}`);
  elements.artifactPanel.setAttribute("aria-labelledby", activeTab.id);
}

function selectArtifactTab(button, {focus = false} = {}) {
  document.querySelectorAll(".artifact-tab").forEach(tab => {
    const active = tab === button;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  state.artifactTab = button.dataset.tab;
  renderArtifact();
  if (focus) button.focus();
}

async function copyText(value) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const textArea = document.createElement("textarea");
  textArea.value = value;
  textArea.style.position = "fixed";
  textArea.style.opacity = "0";
  document.body.append(textArea);
  textArea.select();
  document.execCommand("copy");
  textArea.remove();
}

function announceCopy(message) {
  window.clearTimeout(state.copyTimer);
  elements.copyStatus.textContent = message;
  state.copyTimer = window.setTimeout(() => {
    elements.copyStatus.textContent = "";
  }, 2500);
}

function downloadBlob(contents, filename, type) {
  const blob = new Blob([contents], {type});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function renderResult(result) {
  state.result = result;
  state.artifactTab = "migration";
  resetWriteback();
  renderDecision(result);
  renderLineageSection(result);
  populatePlatformFilter(result.affected_assets);
  renderAssetList();
  renderRisk(result);
  selectArtifactTab(byId("tab-migration"));
}

function renderWritebackAvailability({connectionFailed = false} = {}) {
  const provider = state.result?.provider || state.provider;
  const datahubAnalysis = provider === "datahub";
  let status = "disabled";
  let label = "Mutations disabled";
  let message = "Preview is available for live DataHub analyses; applying requires DATAHUB_MUTATIONS_ENABLED=true.";

  if (connectionFailed) {
    status = "unavailable";
    label = "Configuration unavailable";
    message = "Reconnect to the backend before previewing a DataHub record.";
  } else if (!datahubAnalysis) {
    status = "unsupported";
    label = "Live DataHub required";
    message = "Complete this investigation with the live DataHub provider to create a write-back preview.";
  } else if (state.mutationsEnabled) {
    status = "enabled";
    label = "Mutations enabled";
    message = "Preview is read-only. Apply remains locked until the exact patch is reviewed and confirmed.";
  }

  elements.writebackStatus.dataset.state = status;
  elements.writebackStatus.textContent = label;
  elements.writebackAvailability.textContent = message;
  elements.previewWriteback.disabled = !state.result || !datahubAnalysis || connectionFailed;
  updateApplyAvailability();
}

function resetWriteback() {
  state.writebackPreview = null;
  state.writebackOutcomeUnknown = false;
  elements.writebackConfirm.checked = false;
  elements.writebackPreview.classList.add("is-hidden");
  elements.writebackReceipt.classList.add("is-hidden");
  elements.writebackFeedback.classList.add("is-hidden");
  elements.writebackFeedback.textContent = "";
  elements.previewWriteback.disabled = false;
  elements.previewWriteback.textContent = "Preview DataHub record";
  renderWritebackAvailability();
}

function setWritebackFeedback(message, stateName = "info") {
  elements.writebackFeedback.textContent = message;
  elements.writebackFeedback.dataset.state = stateName;
  elements.writebackFeedback.setAttribute("role", stateName === "error" ? "alert" : "status");
  elements.writebackFeedback.classList.toggle("is-hidden", !message);
}

function updateApplyAvailability() {
  elements.applyWriteback.disabled = !state.writebackPreview
    || !state.mutationsEnabled
    || state.writebackOutcomeUnknown
    || !elements.writebackConfirm.checked;
}

function renderWritebackPreview(preview) {
  state.writebackPreview = preview;
  state.writebackOutcomeUnknown = false;
  state.mutationsEnabled = preview.mutations_enabled === true;
  const {record, mutation} = preview;
  elements.writebackTarget.textContent = record.root_asset.name || "Unnamed asset";
  elements.writebackTargetUrn.textContent = record.root_asset.urn;
  elements.writebackDecision.textContent = record.decision;
  elements.writebackRisk.textContent = `${record.risk_score}/100 · ${record.risk_level}`;
  elements.writebackIdempotency.textContent = mutation.already_applied
    ? "Already present · no-op on apply"
    : "New managed record";
  elements.writebackManagedSection.textContent = mutation.managed_section;
  elements.writebackResultingDescription.textContent = mutation.resulting_description;
  elements.writebackWarnings.replaceChildren(...(preview.warnings || []).map(warning => {
    const item = document.createElement("li");
    item.textContent = warning;
    return item;
  }));
  elements.writebackConfirm.checked = false;
  elements.writebackPreview.classList.remove("is-hidden");
  elements.writebackReceipt.classList.add("is-hidden");
  renderWritebackAvailability();
  updateApplyAvailability();
}

function renderWritebackReceipt(receipt) {
  elements.receiptTitle.textContent = receipt.status === "already_applied"
    ? "Record already confirmed"
    : "Record confirmed";
  elements.receiptAnalysis.textContent = receipt.analysis_id;
  elements.receiptAsset.textContent = `${receipt.asset.name} · ${receipt.asset.urn}`;
  elements.receiptOperation.textContent = "Patched editable dataset description";
  elements.receiptTime.textContent = new Date(receipt.applied_at).toLocaleString();
  elements.receiptMessage.textContent = receipt.message;
  elements.writebackPreview.classList.add("is-hidden");
  elements.writebackReceipt.classList.remove("is-hidden");
}

elements.form.addEventListener("submit", event => {
  event.preventDefault();
  if (validateForm()) runInvestigation(payloadFromForm());
});

elements.changeType.addEventListener("change", updateChangeType);
byId("load-demo").addEventListener("click", () => loadSample());
elements.retryHealth.addEventListener("click", updateConnectionStatus);
byId("retry-analysis").addEventListener("click", () => {
  if (state.lastPayload) runInvestigation(state.lastPayload);
});
byId("edit-proposal").addEventListener("click", () => {
  setView("empty");
  elements.assetUrn.focus();
});

[elements.assetUrn, elements.column, elements.newValue].forEach(input => {
  input.addEventListener("blur", () => validateInput(input));
  input.addEventListener("input", () => {
    if (input.getAttribute("aria-invalid") === "true") validateInput(input);
  });
});

[elements.assetSearch, elements.typeFilter, elements.platformFilter, elements.criticalityFilter]
  .forEach(control => control.addEventListener(control === elements.assetSearch ? "input" : "change", renderAssetList));

byId("clear-filters").addEventListener("click", () => {
  elements.assetSearch.value = "";
  elements.typeFilter.value = "all";
  elements.platformFilter.value = "all";
  elements.criticalityFilter.value = "all";
  renderAssetList();
  elements.assetSearch.focus();
});

document.querySelectorAll(".artifact-tab").forEach(button => {
  button.addEventListener("click", () => selectArtifactTab(button));
  button.addEventListener("keydown", event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...document.querySelectorAll(".artifact-tab")];
    const index = tabs.indexOf(button);
    let target = index;
    if (event.key === "ArrowLeft") target = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
    if (event.key === "Home") target = 0;
    if (event.key === "End") target = tabs.length - 1;
    selectArtifactTab(tabs[target], {focus: true});
  });
});

byId("copy-urn").addEventListener("click", async () => {
  if (!state.selectedAsset) return;
  try {
    await copyText(state.selectedAsset.urn);
    announceCopy("DataHub URN copied.");
  } catch {
    announceCopy("The URN could not be copied. Select it manually from the details panel.");
  }
});

byId("copy-artifact").addEventListener("click", async () => {
  if (!state.result) return;
  try {
    await copyText(artifactText(state.result, state.artifactTab));
    announceCopy(`${ARTIFACTS[state.artifactTab].filename} copied.`);
  } catch {
    announceCopy("The artifact could not be copied. Select it manually from the code panel.");
  }
});

byId("download-artifact").addEventListener("click", () => {
  if (!state.result) return;
  const config = ARTIFACTS[state.artifactTab];
  downloadBlob(artifactText(state.result, state.artifactTab), config.filename, "text/plain;charset=utf-8");
});

byId("download-json").addEventListener("click", () => {
  if (!state.result) return;
  downloadBlob(
    JSON.stringify(state.result, null, 2),
    `lineageshield-${state.result.analysis_id}.json`,
    "application/json;charset=utf-8"
  );
});

elements.previewWriteback.addEventListener("click", async () => {
  if (!state.result) return;
  elements.previewWriteback.disabled = true;
  elements.previewWriteback.textContent = "Loading preview…";
  setWritebackFeedback("Reading the current root documentation. No mutation is being performed.");
  try {
    const preview = await previewWriteback(state.result.analysis_id);
    renderWritebackPreview(preview);
    setWritebackFeedback(
      preview.mutation.already_applied
        ? "This exact analysis record is already present. Apply will be an idempotent no-op."
        : "Preview ready. Review the exact managed section before confirming."
    );
  } catch (error) {
    setWritebackFeedback(error.message, "error");
  } finally {
    elements.previewWriteback.textContent = "Preview DataHub record";
    renderWritebackAvailability();
  }
});

elements.writebackConfirm.addEventListener("change", updateApplyAvailability);

elements.applyWriteback.addEventListener("click", async () => {
  if (!state.result || !elements.writebackConfirm.checked) return;
  elements.applyWriteback.disabled = true;
  elements.applyWriteback.textContent = "Applying metadata patch…";
  setWritebackFeedback("Patching the reviewed root asset only. No migration SQL is being executed.");
  try {
    const receipt = await applyWriteback(state.result.analysis_id);
    renderWritebackReceipt(receipt);
    setWritebackFeedback("");
  } catch (error) {
    const unknownOutcome = error.detail?.mutation_state === "unknown";
    state.writebackOutcomeUnknown = unknownOutcome;
    setWritebackFeedback(
      unknownOutcome
        ? `${error.message} Do not retry until you inspect the root asset in DataHub.`
        : error.message,
      "error"
    );
  } finally {
    elements.applyWriteback.textContent = "Apply to root asset";
    updateApplyAvailability();
  }
});

loadSample({announce: false});
updateChangeType();
updateConnectionStatus();
