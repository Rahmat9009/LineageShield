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
  "Running Agent Context tools",
  "Generating safeguards"
];

const byId = id => document.getElementById(id);

const elements = {
  shell: byId("main-content"),
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
  headerChange: byId("header-change"),
  headerRootAsset: byId("header-root-asset"),
  headerChangeDetail: byId("header-change-detail"),
  headerMutationStatus: byId("header-mutation-status"),
  downloadJson: byId("download-json"),
  reviewSpine: byId("review-spine"),
  reviewSpineToggle: byId("review-spine-toggle"),
  reviewSpineToggleSummary: byId("review-spine-toggle-summary"),
  reviewSpineDetails: byId("review-spine-details"),
  reviewSpineTitle: byId("review-spine-title"),
  reviewSpinePlatform: byId("review-spine-platform"),
  reviewDiffBefore: byId("review-diff-before"),
  reviewDiffAfter: byId("review-diff-after"),
  reviewChangeType: byId("review-change-type"),
  reviewChangeReason: byId("review-change-reason"),
  reviewViewSelect: byId("review-view-select"),
  reviewTabs: [...document.querySelectorAll(".review-tab")],
  reviewPanels: [...document.querySelectorAll(".review-panel")],
  reviewCountLineage: byId("review-count-lineage"),
  reviewCountAssets: byId("review-count-assets"),
  reviewCountRisk: byId("review-count-risk"),
  reviewCountAgent: byId("review-count-agent"),
  reviewCountSafeguards: byId("review-count-safeguards"),
  decisionPanel: byId("review-panel-overview"),
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
  metadataMetric: byId("metadata-metric"),
  overviewRawScore: byId("overview-raw-score"),
  overviewFactors: byId("overview-factors"),
  overviewQualityEvidence: byId("overview-quality-evidence"),
  overviewDatahubAuthority: byId("overview-datahub-authority"),
  overviewCalculationAuthority: byId("overview-calculation-authority"),
  overviewAgentAuthority: byId("overview-agent-authority"),
  agentStatus: byId("agent-status"),
  agentEvidenceCount: byId("agent-evidence-count"),
  agentAuthoritativeResult: byId("agent-authoritative-result"),
  agentNarrativeSource: byId("agent-narrative-source"),
  agentModelState: byId("agent-model-state"),
  agentNarrative: byId("agent-narrative"),
  agentToolkit: byId("agent-toolkit"),
  agentDuration: byId("agent-duration"),
  agentFallback: byId("agent-fallback"),
  agentToolSummary: byId("agent-tool-summary"),
  agentExecutions: byId("agent-executions"),
  agentFallbackReason: byId("agent-fallback-reason"),
  agentEvidenceReferences: byId("agent-evidence-references"),
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
  reviewView: "overview",
  proposalExpanded: false,
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
  elements.form.classList.toggle("is-hidden", view === "result");
  elements.reviewSpine.classList.toggle("is-hidden", view !== "result");
  elements.headerChange.classList.toggle("is-hidden", view !== "result");
  elements.downloadJson.disabled = view !== "result";
  elements.shell.dataset.viewState = view;
}

function sentenceCase(value) {
  const text = String(value || "").toLowerCase();
  return text ? `${text[0].toUpperCase()}${text.slice(1)}` : "";
}

function decisionLabel(decision) {
  return {
    ALLOW: "Merge allowed",
    REVIEW: "Review required",
    BLOCK: "Merge blocked"
  }[decision] || "Decision unavailable";
}

function changeTypeLabel(changeType) {
  return {
    rename: "Rename column",
    type_change: "Change data type",
    add: "Add column",
    drop: "Drop column"
  }[changeType] || "Schema change";
}

function schemaDiff(payload) {
  const column = payload?.column || "Column unavailable";
  const newValue = payload?.new_value || "Removed";

  if (payload?.change_type === "add") {
    return {before: "Not present", after: `${column} · ${newValue}`};
  }
  if (payload?.change_type === "type_change") {
    return {before: column, after: `${column} · ${newValue}`};
  }
  if (payload?.change_type === "drop") {
    return {before: column, after: "Removed"};
  }
  return {before: column, after: newValue};
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
  const delays = [700, 1400, 2100, 2800, 3500];
  delays.forEach((delay, index) => {
    const target = index + 1;
    state.progressTimers.push(window.setTimeout(() => {
      elements.progressStages.forEach((stage, stageIndex) => {
        stage.classList.toggle("is-complete", stageIndex < target);
        stage.classList.toggle("is-active", stageIndex === target);
      });
      elements.loadingTitle.textContent = PROGRESS_LABELS[target];
      elements.progressFill.style.width = `${16 + target * 15}%`;
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

function updateReviewSpineExpansion() {
  elements.reviewSpine.classList.toggle("is-proposal-expanded", state.proposalExpanded);
  elements.reviewSpineToggle.setAttribute("aria-expanded", String(state.proposalExpanded));
}

function selectReviewView(view, {focusTab = false} = {}) {
  const tab = elements.reviewTabs.find(item => item.dataset.reviewView === view);
  const panel = elements.reviewPanels.find(item => item.dataset.reviewView === view);
  if (!tab || !panel) return;

  state.reviewView = view;
  elements.reviewTabs.forEach(item => {
    const active = item === tab;
    item.classList.toggle("is-active", active);
    item.setAttribute("aria-selected", String(active));
    item.tabIndex = active ? 0 : -1;
  });
  elements.reviewPanels.forEach(item => {
    item.hidden = item !== panel;
  });
  elements.reviewViewSelect.value = view;
  if (focusTab) tab.focus({preventScroll: true});
}

function updateReviewSelectOption(view, label, count = null) {
  const option = [...elements.reviewViewSelect.options]
    .find(item => item.value === view);
  if (!option) return;
  option.textContent = count === null ? label : `${label} · ${count}`;
}

function renderReviewWorkspace(result) {
  const rootAsset = normalizeRootAsset(result);
  const payload = state.lastPayload || {};
  const diff = schemaDiff(payload);
  const trace = result.agent_trace || {};
  const executionCount = Array.isArray(trace.executions) ? trace.executions.length : 0;
  const affectedCount = result.affected_assets.length;
  const factorCount = result.factors.length;
  const safeguardCount = Object.keys(result.artifacts || {}).length;

  elements.headerRootAsset.textContent = rootAsset.name || readableNameFromUrn(rootAsset.urn);
  elements.headerChangeDetail.textContent = payload.change_type === "rename"
    ? `${payload.column || "Column"} → ${payload.new_value || "New name"}`
    : `${changeTypeLabel(payload.change_type)} · ${payload.column || "Column"}`;

  elements.reviewSpineTitle.textContent = rootAsset.name || readableNameFromUrn(rootAsset.urn);
  elements.reviewSpinePlatform.textContent = `${rootAsset.platform || "Unknown platform"} · ${assetTypeLabel(rootAsset.asset_type)}`;
  elements.reviewDiffBefore.textContent = diff.before;
  elements.reviewDiffAfter.textContent = diff.after;
  elements.reviewChangeType.textContent = changeTypeLabel(payload.change_type);
  elements.reviewChangeReason.textContent = payload.reason || "No rationale provided.";
  elements.reviewSpineToggleSummary.textContent = payload.change_type === "rename"
    ? `${diff.before} → ${diff.after}`
    : `${changeTypeLabel(payload.change_type)} · ${payload.column || "Column"}`;

  elements.reviewCountLineage.textContent = String(affectedCount);
  elements.reviewCountAssets.textContent = String(affectedCount);
  elements.reviewCountRisk.textContent = String(factorCount);
  elements.reviewCountAgent.textContent = String(executionCount);
  elements.reviewCountSafeguards.textContent = String(safeguardCount);
  updateReviewSelectOption("lineage", "Lineage", affectedCount);
  updateReviewSelectOption("assets", "Affected assets", affectedCount);
  updateReviewSelectOption("risk", "Risk evidence", factorCount);
  updateReviewSelectOption("agent", "Agent Context", executionCount);
  updateReviewSelectOption("safeguards", "Safeguards", safeguardCount);

  state.proposalExpanded = false;
  updateReviewSpineExpansion();
  selectReviewView("overview");
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
    elements.decisionPanel.focus({preventScroll: true});
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
  const metadataSummary = result.metadata_summary || {};
  const enriched = Number(metadataSummary.datahub_entities_enriched || 0);
  const totalMetadataAssets = Number(metadataSummary.total_assets || 0);

  elements.decisionPanel.dataset.decision = result.decision;
  elements.decision.textContent = decisionLabel(result.decision);
  elements.riskLevel.textContent = `${sentenceCase(result.risk_level)} risk`;
  elements.explanation.textContent = result.explanation;
  appendTextWithSuffix(elements.riskScore, result.risk_score, "/100");
  elements.scoreMeterFill.style.width = `${Math.min(100, result.risk_score)}%`;
  elements.assetMetric.textContent = String(result.affected_assets.length);
  elements.platformMetric.textContent = String(platforms.length);
  elements.platformSummary.textContent = displayPlatformList(platforms);
  elements.approvalMetric.textContent = String(approvals.length);
  elements.metadataMetric.textContent = totalMetadataAssets
    ? `${enriched}/${totalMetadataAssets}`
    : "Unavailable";
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

function renderOverview(result) {
  const rawScore = result.raw_risk_score
    ?? result.factors.reduce((sum, factor) => sum + factor.points, 0);
  const factorRows = result.factors.map(factor => {
    const row = document.createElement("article");
    row.className = "overview-factor-row";
    const points = document.createElement("strong");
    points.textContent = `+${factor.points}`;
    const copy = document.createElement("span");
    const label = document.createElement("b");
    label.textContent = factor.label;
    const evidence = document.createElement("small");
    evidence.textContent = factor.evidence;
    copy.append(label, evidence);
    row.append(points, copy);
    return row;
  });
  elements.overviewRawScore.textContent = `${rawScore} point${rawScore === 1 ? "" : "s"}`;
  elements.overviewFactors.replaceChildren(...factorRows);

  const rootAsset = normalizeRootAsset(result);
  const qualityFailure = [rootAsset, ...result.affected_assets].find(asset =>
    asset.quality_status === "failing"
      && asset.metadata_sources?.quality === "datahub"
  );
  elements.overviewQualityEvidence.textContent = qualityFailure
    ? `${qualityFailure.name || readableNameFromUrn(qualityFailure.urn)} — ${qualityFailure.quality_evidence || "DataHub reports a failing quality test."}`
    : "No identifiable failing DataHub quality evidence returned.";
  elements.overviewQualityEvidence.dataset.state = qualityFailure ? "failing" : "none";

  const metadataSummary = result.metadata_summary || {};
  const enriched = Number(metadataSummary.datahub_entities_enriched || 0);
  const totalMetadataAssets = Number(metadataSummary.total_assets || 0);
  elements.overviewDatahubAuthority.textContent = result.provider === "datahub"
    ? `${result.affected_assets.length} downstream assets · ${totalMetadataAssets ? `${enriched}/${totalMetadataAssets} entities enriched` : "metadata coverage unavailable"}`
    : `Unavailable — analysis used the ${result.provider || "unknown"} provider`;
  elements.overviewCalculationAuthority.textContent = `${result.decision} · ${result.risk_score}/100 · deterministic and authoritative`;

  const trace = result.agent_trace || {};
  const requested = Array.isArray(trace.tools_requested) ? trace.tools_requested.length : 0;
  const succeeded = Array.isArray(trace.tools_succeeded) ? trace.tools_succeeded.length : 0;
  elements.overviewAgentAuthority.textContent = trace.executed
    ? `${agentStatusLabel(trace.status)} · ${succeeded}/${requested} read operations · supplemental`
    : "Unavailable · supplemental only";
}

function agentStatusLabel(status) {
  return {
    completed: "Completed",
    degraded: "Degraded",
    unavailable: "Unavailable"
  }[status] || "Unavailable";
}

function agentNarrativeSourceLabel(source) {
  return {
    deterministic_orchestration: "Deterministic orchestration",
    optional_model: "Optional model output",
    unavailable: "Unavailable"
  }[source] || "Unavailable";
}

function evidenceTypeLabel(type) {
  return {
    root_entity: "Root entity",
    column_lineage: "Column lineage",
    dataset_lineage: "Dataset lineage fallback"
  }[type] || "DataHub context";
}

function renderAgentInvestigation(result) {
  const trace = result.agent_trace || {
    status: "unavailable",
    executed: false,
    tools_requested: [],
    tools_succeeded: [],
    tool_failures: [],
    executions: [],
    context_evidence_references: [],
    fallback_occurred: true,
    fallback_reason: "This response did not include an Agent Context Kit trace.",
    duration_ms: 0,
    narrative_source: "unavailable",
    narrative: "Agent Context Kit did not execute for this investigation.",
    llm_used: false
  };
  const requested = Array.isArray(trace.tools_requested) ? trace.tools_requested : [];
  const succeeded = Array.isArray(trace.tools_succeeded) ? trace.tools_succeeded : [];
  const executions = Array.isArray(trace.executions) ? trace.executions : [];
  const references = Array.isArray(trace.context_evidence_references)
    ? trace.context_evidence_references
    : [];

  elements.agentStatus.dataset.state = trace.status || "unavailable";
  elements.agentStatus.textContent = agentStatusLabel(trace.status);
  elements.agentEvidenceCount.textContent = `${references.length} reference${references.length === 1 ? "" : "s"}`;
  elements.agentAuthoritativeResult.textContent = `${result.decision} · ${result.risk_score}/100`;
  elements.agentNarrativeSource.textContent = agentNarrativeSourceLabel(trace.narrative_source);
  elements.agentModelState.textContent = trace.llm_used ? "Optional model used" : "No model called";
  elements.agentNarrative.textContent = trace.narrative || "No agent narrative was available.";
  elements.agentToolkit.textContent = trace.toolkit_version
    ? `${trace.toolkit || "datahub-agent-context"} ${trace.toolkit_version}`
    : (trace.toolkit || "datahub-agent-context");
  elements.agentDuration.textContent = `${Number(trace.duration_ms || 0).toLocaleString()} ms`;
  elements.agentFallback.textContent = trace.fallback_occurred ? "Used · recorded" : "Not used";
  elements.agentToolSummary.textContent = `${requested.length} requested · ${succeeded.length} succeeded`;

  const executionItems = executions.map(execution => {
    const item = document.createElement("li");
    item.className = "agent-execution";
    item.dataset.state = execution.status || "failure";
    const heading = document.createElement("div");
    const operation = document.createElement("strong");
    operation.textContent = execution.operation || execution.tool || "Context operation";
    const status = document.createElement("span");
    status.textContent = execution.status || "unknown";
    heading.append(operation, status);
    const summary = document.createElement("p");
    summary.textContent = execution.result_summary || "No operation summary was returned.";
    const duration = document.createElement("small");
    duration.textContent = `${Number(execution.duration_ms || 0).toLocaleString()} ms · ${execution.tool || "tool"}`;
    item.append(heading, summary, duration);
    return item;
  });
  if (!executionItems.length) {
    const empty = document.createElement("li");
    empty.className = "agent-execution is-empty";
    empty.textContent = "No Agent Context Kit tool execution was reported.";
    executionItems.push(empty);
  }
  elements.agentExecutions.replaceChildren(...executionItems);

  elements.agentFallbackReason.textContent = trace.fallback_reason || "";
  elements.agentFallbackReason.classList.toggle("is-hidden", !trace.fallback_reason);

  const referenceItems = references.map(reference => {
    const item = document.createElement("li");
    const identity = document.createElement("span");
    const label = document.createElement("strong");
    label.textContent = reference.label || readableNameFromUrn(reference.urn);
    const type = document.createElement("small");
    type.textContent = evidenceTypeLabel(reference.evidence_type);
    identity.append(label, type);
    const urn = document.createElement("code");
    urn.textContent = reference.urn || "Reference unavailable";
    item.append(identity, urn);
    return item;
  });
  if (!referenceItems.length) {
    const empty = document.createElement("li");
    empty.className = "agent-evidence-empty";
    empty.textContent = "No Agent Context Kit evidence references were available.";
    referenceItems.push(empty);
  }
  elements.agentEvidenceReferences.replaceChildren(...referenceItems);
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

  elements.inspectorType.textContent = `${isSource ? "Source · " : ""}${assetTypeLabel(asset.asset_type)}`;
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
  renderOverview(result);
  renderAgentInvestigation(result);
  renderLineageSection(result);
  populatePlatformFilter(result.affected_assets);
  renderAssetList();
  renderRisk(result);
  selectArtifactTab(byId("tab-migration"));
  renderReviewWorkspace(result);
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
  elements.headerMutationStatus.dataset.state = status;
  elements.headerMutationStatus.textContent = status === "enabled"
    ? "Mutations on"
    : (status === "unavailable" || status === "unsupported"
      ? "Write-back unavailable"
      : "Mutations off");
  elements.headerMutationStatus.title = message;
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

function editProposal() {
  setView("empty");
  elements.assetUrn.focus();
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
byId("edit-proposal").addEventListener("click", editProposal);
byId("edit-review-proposal").addEventListener("click", editProposal);

elements.reviewSpineToggle.addEventListener("click", () => {
  state.proposalExpanded = !state.proposalExpanded;
  updateReviewSpineExpansion();
});

elements.reviewViewSelect.addEventListener("change", () => {
  selectReviewView(elements.reviewViewSelect.value);
});

elements.reviewTabs.forEach(button => {
  button.addEventListener("click", () => selectReviewView(button.dataset.reviewView));
  button.addEventListener("keydown", event => {
    if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = elements.reviewTabs.indexOf(button);
    let target = index;
    if (event.key === "ArrowUp") target = (index - 1 + elements.reviewTabs.length) % elements.reviewTabs.length;
    if (event.key === "ArrowDown") target = (index + 1) % elements.reviewTabs.length;
    if (event.key === "Home") target = 0;
    if (event.key === "End") target = elements.reviewTabs.length - 1;
    selectReviewView(elements.reviewTabs[target].dataset.reviewView, {focusTab: true});
  });
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
setView("empty");
updateConnectionStatus();
