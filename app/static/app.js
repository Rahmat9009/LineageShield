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
  migration: {key: "migration_sql", filename: "migration.sql", language: "SQL"},
  compatibility: {key: "compatibility_sql", filename: "compatibility.sql", language: "SQL"},
  tests: {key: "data_tests_yaml", filename: "schema-tests.yml", language: "YAML"},
  rollback: {key: "rollback_plan", filename: "rollback-steps.md", language: "Review steps"},
  pr: {key: "pull_request_summary", filename: "pr-summary.md", language: "Markdown"}
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
  agentRequestedCount: byId("agent-requested-count"),
  agentSucceededCount: byId("agent-succeeded-count"),
  agentFailedCount: byId("agent-failed-count"),
  agentFallback: byId("agent-fallback"),
  agentToolSummary: byId("agent-tool-summary"),
  agentExecutions: byId("agent-executions"),
  agentFallbackReason: byId("agent-fallback-reason"),
  agentReferenceSummary: byId("agent-reference-summary"),
  agentEvidenceDetails: document.querySelector(".agent-evidence-details"),
  agentEvidenceReferences: byId("agent-evidence-references"),
  lineageSurface: byId("lineage-surface"),
  lineageGraphRegion: byId("lineage-graph-region"),
  lineageCanvas: byId("lineage-canvas"),
  lineageAssetList: byId("lineage-asset-list"),
  lineageLegend: byId("lineage-legend"),
  fitLineage: byId("fit-lineage"),
  resetLineageSelection: byId("reset-lineage-selection"),
  toggleLineageList: byId("toggle-lineage-list"),
  lineageScopeFallback: byId("lineage-scope-fallback"),
  lineageScopeCount: byId("lineage-scope-count"),
  lineageScopeHops: byId("lineage-scope-hops"),
  lineageScopeLimit: byId("lineage-scope-limit"),
  lineageNote: byId("lineage-note"),
  assetInspector: byId("asset-inspector"),
  assetInspectorBackdrop: byId("asset-inspector-backdrop"),
  closeAssetInspector: byId("close-asset-inspector"),
  inspectorType: byId("inspector-type"),
  inspectorTitle: byId("node-inspector-title"),
  inspectorPlatformType: byId("inspector-platform-type"),
  inspectorDescription: byId("inspector-description"),
  inspectorDescriptionNote: byId("inspector-description-note"),
  inspectorFullDescription: byId("inspector-full-description"),
  inspectorDescriptionFull: byId("inspector-description-full"),
  inspectorMetadata: byId("inspector-metadata"),
  inspectorDependency: byId("inspector-dependency"),
  inspectorCriticality: byId("inspector-criticality"),
  inspectorCriticalitySource: byId("inspector-criticality-source"),
  inspectorQuality: byId("inspector-quality"),
  inspectorQualitySource: byId("inspector-quality-source"),
  inspectorUsage: byId("inspector-usage"),
  inspectorOwners: byId("inspector-owners"),
  inspectorTags: byId("inspector-tags"),
  inspectorGlossary: byId("inspector-glossary"),
  inspectorFields: byId("inspector-fields"),
  inspectorProperties: byId("inspector-properties"),
  inspectorUrnBlock: byId("inspector-urn-block"),
  inspectorUrn: byId("inspector-urn"),
  inspectorCopyStatus: byId("inspector-copy-status"),
  assetSearch: byId("asset-search"),
  typeFilter: byId("asset-type-filter"),
  platformFilter: byId("platform-filter"),
  criticalityFilter: byId("criticality-filter"),
  failingQualityFilter: byId("failing-quality-filter"),
  failingQualityCount: byId("failing-quality-count"),
  assetCount: byId("asset-count"),
  assets: byId("assets"),
  assetsEmpty: byId("assets-empty"),
  rawScore: byId("raw-score"),
  riskFinalScore: byId("risk-final-score"),
  riskDisposition: byId("risk-disposition"),
  riskLedgerDisposition: document.querySelector(".risk-ledger-disposition"),
  riskAuthoritySummary: byId("risk-authority-summary"),
  riskFactorTotal: byId("risk-factor-total"),
  scoreCapNote: byId("score-cap-note"),
  factors: byId("factors"),
  approvals: byId("approvals"),
  artifactPanel: byId("artifact-panel"),
  artifactFileSelect: byId("artifact-file-select"),
  artifactFilename: byId("artifact-filename"),
  artifactLanguage: byId("artifact-language"),
  artifactProvenance: byId("artifact-provenance"),
  artifactCode: byId("artifact-code").querySelector("code"),
  copyStatus: byId("copy-status"),
  writebackWorkflow: byId("review-panel-writeback"),
  writebackStatus: byId("writeback-status"),
  writebackModeState: byId("writeback-mode-state"),
  writebackStateTitle: byId("writeback-state-title"),
  writebackAvailability: byId("writeback-availability"),
  previewWriteback: byId("preview-writeback"),
  writebackFeedback: byId("writeback-feedback"),
  writebackPreview: byId("writeback-preview"),
  writebackTarget: byId("writeback-target"),
  writebackTargetUrn: byId("writeback-target-urn"),
  writebackAnalysisId: byId("writeback-analysis-id"),
  writebackPreservation: byId("writeback-preservation"),
  writebackDecision: byId("writeback-decision"),
  writebackRisk: byId("writeback-risk"),
  writebackIdempotency: byId("writeback-idempotency"),
  writebackManagedSection: byId("writeback-managed-section"),
  writebackResultingDetails: byId("writeback-resulting-details"),
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
  inspectorOpen: false,
  inspectorTrigger: null,
  lineageController: null,
  lineageDisplay: "graph",
  lineageDisplayPreference: null,
  qualityFailureOnly: false,
  reviewView: "overview",
  proposalExpanded: false,
  artifactTab: "migration",
  provider: null,
  mutationsEnabled: false,
  writebackPreview: null,
  writebackPreviewError: false,
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
  elements.resultView.dataset.activeReviewView = view;
  if (view === "lineage" && state.lineageDisplayPreference === null) {
    setLineageDisplay(prefersLineageList() ? "list" : "graph");
  }
  updateInspectorVisibility();
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

function executionReferenceCount(execution, references) {
  const explicitCount = Number(
    execution.reference_count
      ?? execution.evidence_count
      ?? execution.result_count
  );
  if (Number.isFinite(explicitCount)) return explicitCount;

  const evidenceType = {
    "get_entities.root": "root_entity",
    "get_lineage.column_downstream": "column_lineage",
    "get_lineage.dataset_downstream": "dataset_lineage"
  }[execution.operation];
  return evidenceType
    ? references.filter(reference => reference.evidence_type === evidenceType).length
    : 0;
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
  const failures = Array.isArray(trace.tool_failures) ? trace.tool_failures : [];
  const references = Array.isArray(trace.context_evidence_references)
    ? trace.context_evidence_references
    : [];

  elements.agentStatus.dataset.state = trace.status || "unavailable";
  elements.agentStatus.textContent = agentStatusLabel(trace.status);
  elements.agentEvidenceCount.textContent = `${references.length} reference${references.length === 1 ? "" : "s"}`;
  elements.agentAuthoritativeResult.textContent = `${result.decision} · ${result.risk_score}/100`;
  elements.agentNarrativeSource.textContent = agentNarrativeSourceLabel(trace.narrative_source);
  elements.agentModelState.textContent = String(trace.llm_used === true);
  elements.agentNarrative.textContent = trace.narrative || "No agent narrative was available.";
  elements.agentToolkit.textContent = trace.toolkit_version
    ? `${trace.toolkit || "datahub-agent-context"} ${trace.toolkit_version}`
    : (trace.toolkit || "datahub-agent-context");
  elements.agentDuration.textContent = `${Number(trace.duration_ms || 0).toLocaleString()} ms`;
  elements.agentFallback.textContent = trace.fallback_occurred ? "Used · recorded" : "Not used";
  elements.agentRequestedCount.textContent = String(requested.length);
  elements.agentSucceededCount.textContent = String(succeeded.length);
  elements.agentFailedCount.textContent = String(failures.length);
  elements.agentFailedCount.dataset.state = failures.length ? "failure" : "none";
  elements.agentToolSummary.textContent = `${requested.length} requested · ${succeeded.length} succeeded · ${failures.length} failed`;
  elements.agentReferenceSummary.textContent = `${references.length} total`;
  elements.agentEvidenceDetails.open = false;

  const executionItems = executions.map(execution => {
    const item = document.createElement("li");
    item.className = "agent-execution";
    item.dataset.state = execution.status || "failure";
    const operation = document.createElement("div");
    operation.className = "agent-operation";
    operation.dataset.label = "Operation";
    const operationCode = document.createElement("code");
    operationCode.textContent = execution.operation || execution.tool || "Context operation";
    operation.append(operationCode);

    const status = document.createElement("div");
    status.className = "agent-operation-status";
    status.dataset.label = "Status";
    const statusText = document.createElement("span");
    statusText.textContent = sentenceCase(execution.status || "unknown");
    status.append(statusText);

    const duration = document.createElement("div");
    duration.className = "agent-operation-duration";
    duration.dataset.label = "Duration";
    const durationCode = document.createElement("code");
    durationCode.textContent = `${Number(execution.duration_ms || 0).toLocaleString()} ms`;
    duration.append(durationCode);

    const referenceCount = document.createElement("div");
    referenceCount.className = "agent-operation-references";
    referenceCount.dataset.label = "References";
    const count = executionReferenceCount(execution, references);
    const countCode = document.createElement("code");
    countCode.textContent = String(count);
    referenceCount.append(countCode);

    const summary = document.createElement("p");
    summary.textContent = execution.result_summary || "No operation summary was returned.";
    item.append(operation, status, duration, referenceCount, summary);
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

function explicitSourceLabel(source) {
  return {
    datahub: "Explicit DataHub metadata",
    lineage: "DataHub lineage evidence",
    inferred: "Inferred by LineageShield",
    fallback: "Derived from the asset URN",
    unavailable: "Unavailable",
    demo: "Demo metadata"
  }[source] || "Source unavailable";
}

function normalizedDescription(description) {
  const text = String(description || "").trim();
  const managedPattern = /<!--\s*LINEAGESHIELD:BEGIN[^>]*-->[\s\S]*?<!--\s*LINEAGESHIELD:END[^>]*-->/gi;
  const managedBlocks = text.match(managedPattern) || [];
  const withoutManaged = text.replace(managedPattern, " ").replace(/\s+/g, " ").trim();
  const normalized = withoutManaged || (text ? "Only managed LineageShield documentation is present." : "No description is available.");
  const preview = normalized.length > 240 ? `${normalized.slice(0, 239).trimEnd()}…` : normalized;
  return {text, preview, managedCount: managedBlocks.length};
}

function renderOwnerDetails(asset, sources) {
  const ownerDetails = Array.isArray(asset.owner_details) ? asset.owner_details : [];
  const owners = Array.isArray(asset.owners) ? asset.owners : [];
  const items = ownerDetails.length
    ? ownerDetails.map(owner => ({label: owner.label, role: owner.ownership_type || "Role unavailable"}))
    : owners.map(owner => ({label: owner, role: "Role unavailable"}));

  if (!items.length) {
    const empty = document.createElement("li");
    empty.textContent = sources.owners === "datahub"
      ? "No owners stored in DataHub."
      : "Owner metadata unavailable.";
    elements.inspectorOwners.replaceChildren(empty);
    return;
  }

  elements.inspectorOwners.replaceChildren(...items.map(owner => {
    const item = document.createElement("li");
    const label = document.createElement("strong");
    const role = document.createElement("span");
    label.textContent = owner.label || "Unnamed owner";
    role.textContent = owner.role;
    item.append(label, role);
    return item;
  }));
}

function renderFieldSummary(asset, sources) {
  const fields = Array.isArray(asset.fields) ? asset.fields : [];
  if (!fields.length) {
    elements.inspectorFields.textContent = sources.fields === "datahub"
      ? "No schema fields stored in DataHub."
      : "Schema fields unavailable.";
    return;
  }

  const count = document.createElement("strong");
  count.textContent = `${fields.length} field${fields.length === 1 ? "" : "s"}`;
  const separator = document.createTextNode(" · ");
  const preview = document.createElement("span");
  fields.slice(0, 6).forEach((field, index) => {
    if (index) preview.append(document.createTextNode(", "));
    const code = document.createElement("code");
    code.textContent = field;
    preview.append(code);
  });
  if (fields.length > 6) preview.append(document.createTextNode(` +${fields.length - 6}`));
  elements.inspectorFields.replaceChildren(count, separator, preview);
}

function structuredPropertyName(urn) {
  return String(urn || "Property").split(":").at(-1)
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[._-]+/g, " ");
}

function structuredPropertyValue(value) {
  const values = Array.isArray(value) ? value : [value];
  return values.map(item => typeof item === "object" ? JSON.stringify(item) : String(item)).join(", ");
}

function renderStructuredProperties(asset, sources) {
  const entries = Object.entries(asset.structured_properties || {});
  if (!entries.length) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = "Properties";
    description.textContent = sources.structured_properties === "datahub"
      ? "None stored in DataHub"
      : "Unavailable";
    row.append(term, description);
    elements.inspectorProperties.replaceChildren(row);
    return;
  }

  elements.inspectorProperties.replaceChildren(...entries.map(([key, value]) => {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const code = document.createElement("code");
    const description = document.createElement("dd");
    code.textContent = structuredPropertyName(key);
    description.textContent = structuredPropertyValue(value);
    term.append(code);
    row.append(term, description);
    return row;
  }));
}

function isInspectorDialogMode() {
  return typeof window.matchMedia === "function"
    && window.matchMedia("(max-width: 1100px)").matches;
}

function updateInspectorMode() {
  const dialog = isInspectorDialogMode();
  elements.assetInspector.setAttribute("role", dialog ? "dialog" : "complementary");
  if (dialog) elements.assetInspector.setAttribute("aria-modal", "true");
  else elements.assetInspector.removeAttribute("aria-modal");
  return dialog;
}

function updateInspectorVisibility({focus = false} = {}) {
  const evidenceView = state.reviewView === "lineage"
    || state.reviewView === "assets"
    || state.reviewView === "risk";
  const visible = Boolean(state.selectedAsset && state.inspectorOpen && evidenceView);
  const dialog = updateInspectorMode();
  elements.assetInspector.hidden = !visible;
  elements.assetInspectorBackdrop.hidden = !(visible && dialog);
  elements.resultView.classList.toggle("is-inspector-open", visible);
  document.body.classList.toggle("is-inspector-dialog-open", visible && dialog);
  if (visible && dialog && focus) {
    const focusInspector = () => elements.assetInspector.focus({preventScroll: true});
    if (typeof window.requestAnimationFrame === "function") window.requestAnimationFrame(focusInspector);
    else focusInspector();
  }
}

function closeAssetInspector({returnFocus = true} = {}) {
  const trigger = state.inspectorTrigger;
  state.inspectorOpen = false;
  updateInspectorVisibility();
  if (!returnFocus) return;
  if (trigger && typeof trigger.focus === "function" && trigger.isConnected !== false) {
    trigger.focus({preventScroll: true});
  } else {
    const panel = elements.reviewPanels.find(item => item.dataset.reviewView === state.reviewView);
    panel?.focus({preventScroll: true});
  }
}

function syncSelectedAssetUI() {
  const selectedUrn = state.selectedAsset?.urn || "";
  document.querySelectorAll(".asset-row, .lineage-list-row").forEach(row => {
    const selected = row.dataset.assetUrn === selectedUrn;
    row.classList.toggle("is-selected", selected);
    row.setAttribute("aria-selected", String(selected));
  });
  document.querySelectorAll(".factor-asset-link").forEach(button => {
    const selected = button.dataset.assetUrn === selectedUrn;
    button.classList.toggle("is-selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
  if (selectedUrn) state.lineageController?.selectUrn(selectedUrn, {notify: false});
}

function renderAssetInspector(asset) {
  const isSource = asset.urn === normalizeRootAsset(state.result).urn;
  const sources = asset.metadata_sources || {};
  const description = normalizedDescription(asset.description);
  const criticalitySource = asset.criticality_source || sources.criticality;
  const dependency = asset.dependency_type || (isSource ? "Source asset" : "Downstream dependency");
  const hops = Number(asset.hops || 0);

  elements.inspectorType.textContent = `${isSource ? "Source · " : ""}${assetTypeLabel(asset.asset_type)}`;
  elements.inspectorTitle.textContent = asset.name || readableNameFromUrn(asset.urn);
  elements.inspectorPlatformType.textContent = `${asset.platform || "Unknown platform"} · ${assetTypeLabel(asset.asset_type)}`;
  elements.inspectorDependency.textContent = `${dependency} · ${hops} hop${hops === 1 ? "" : "s"}`;
  elements.inspectorCriticality.textContent = sentenceCase(asset.criticality || "unknown");
  elements.inspectorCriticality.dataset.state = asset.criticality || "unknown";
  elements.inspectorCriticalitySource.textContent = criticalitySource === "datahub"
    ? "Explicit DataHub metadata"
    : `${explicitSourceLabel(criticalitySource)}${asset.criticality_evidence ? ` — ${asset.criticality_evidence}` : ""}`;

  const qualityIsDataHub = sources.quality === "datahub";
  elements.inspectorQuality.textContent = qualityIsDataHub
    ? sentenceCase(asset.quality_status || "unknown")
    : "Unavailable";
  elements.inspectorQuality.dataset.state = qualityIsDataHub ? (asset.quality_status || "unknown") : "unknown";
  elements.inspectorQualitySource.textContent = qualityIsDataHub
    ? `DataHub evidence — ${asset.quality_evidence || "No quality detail returned."}`
    : (asset.quality_evidence || "No identifiable DataHub quality result was returned.");
  elements.inspectorUsage.textContent = sources.usage === "datahub"
    ? `${asset.usage_score || 0}/100 · DataHub normalized score`
    : "Unavailable · score retained at 0";

  renderOwnerDetails(asset, sources);
  elements.inspectorTags.textContent = `${summarizeMetadataList(asset.tags, {
    empty: sources.tags === "datahub" ? "None stored in DataHub" : "Unavailable"
  })} · ${explicitSourceLabel(sources.tags)}`;
  elements.inspectorGlossary.textContent = `${summarizeMetadataList(asset.glossary_terms, {
    empty: sources.glossary_terms === "datahub" ? "None stored in DataHub" : "Unavailable"
  })} · ${explicitSourceLabel(sources.glossary_terms)}`;
  renderFieldSummary(asset, sources);
  renderStructuredProperties(asset, sources);

  elements.inspectorDescription.textContent = description.preview;
  elements.inspectorDescriptionFull.textContent = description.text || "No description is available.";
  elements.inspectorFullDescription.open = false;
  elements.inspectorFullDescription.classList.toggle("is-hidden", !description.text);
  elements.inspectorDescriptionNote.classList.toggle("is-hidden", description.managedCount === 0);
  elements.inspectorDescriptionNote.textContent = description.managedCount
    ? `${description.managedCount} managed LineageShield documentation block${description.managedCount === 1 ? " was" : "s were"} omitted from this preview.`
    : "";
  elements.inspectorUrn.textContent = asset.urn;
  elements.inspectorCopyStatus.textContent = "";
}

function inspectAsset(asset, {trigger = null, focusInspector = true} = {}) {
  state.selectedAsset = asset;
  state.inspectorOpen = true;
  if (trigger) state.inspectorTrigger = trigger;
  renderAssetInspector(asset);
  syncSelectedAssetUI();
  updateInspectorVisibility({focus: focusInspector});
}

function prefersLineageList() {
  return typeof window.matchMedia === "function"
    && window.matchMedia("(max-width: 820px)").matches;
}

function setLineageDisplay(display, {user = false} = {}) {
  const showList = display === "list";
  state.lineageDisplay = showList ? "list" : "graph";
  if (user) state.lineageDisplayPreference = state.lineageDisplay;
  elements.lineageSurface.dataset.display = state.lineageDisplay;
  elements.lineageGraphRegion.hidden = showList;
  elements.lineageAssetList.hidden = !showList;
  elements.lineageLegend.hidden = showList;
  elements.fitLineage.disabled = showList;
  elements.toggleLineageList.setAttribute("aria-pressed", String(showList));
  elements.toggleLineageList.textContent = showList ? "View graph" : "View as asset list";
  if (showList) syncSelectedAssetUI();
}

function focusAdjacentAssetRow(container, current, direction) {
  const rows = [...container.querySelectorAll("button")];
  const index = rows.indexOf(current);
  if (index < 0) return;
  const target = Math.min(rows.length - 1, Math.max(0, index + direction));
  rows[target]?.focus({preventScroll: true});
}

function lineageListRow(asset, {source = false} = {}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "lineage-list-row";
  button.dataset.assetUrn = asset.urn;
  button.setAttribute("role", "option");
  button.setAttribute("aria-selected", String(state.selectedAsset?.urn === asset.urn));
  button.setAttribute("aria-label", `Inspect ${source ? "source asset" : "downstream asset"} ${asset.name || readableNameFromUrn(asset.urn)}`);

  const identity = document.createElement("span");
  const name = document.createElement("strong");
  const context = document.createElement("small");
  const dependency = document.createElement("span");
  const selected = document.createElement("span");
  name.textContent = asset.name || readableNameFromUrn(asset.urn);
  context.textContent = `${asset.platform || "Unknown platform"} · ${assetTypeLabel(asset.asset_type)}`;
  dependency.textContent = source
    ? "Source asset"
    : `${asset.dependency_type || "Downstream dependency"} · ${Number(asset.hops || 0)} hop${Number(asset.hops || 0) === 1 ? "" : "s"}`;
  selected.className = "asset-selected-label";
  selected.textContent = "Selected";
  identity.append(name, context);
  button.append(identity, dependency, selected);
  button.classList.toggle("is-selected", state.selectedAsset?.urn === asset.urn);
  button.addEventListener("click", () => inspectAsset(asset, {trigger: button}));
  button.addEventListener("keydown", event => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      focusAdjacentAssetRow(elements.lineageAssetList, button, event.key === "ArrowDown" ? 1 : -1);
    }
  });
  return button;
}

function renderLineageAssetList(rootAsset, assets) {
  elements.lineageAssetList.replaceChildren(
    lineageListRow(rootAsset, {source: true}),
    ...assets.map(asset => lineageListRow(asset))
  );
}

function renderLineageSection(result) {
  const rootAsset = normalizeRootAsset(result);
  const edges = result.lineage_edges || result.edges || [];
  const allAssets = [rootAsset, ...result.affected_assets];
  const selectedAsset = allAssets.find(asset => asset.urn === state.selectedAsset?.urn) || rootAsset;
  state.selectedAsset = selectedAsset;
  state.lineageController = renderLineage(
    elements.lineageCanvas,
    {rootAsset, assets: result.affected_assets, edges, selectedUrn: selectedAsset.urn},
    (asset, trigger) => inspectAsset(asset, {trigger})
  );
  renderLineageAssetList(rootAsset, result.affected_assets);

  const notes = Array.isArray(result.context_notes) ? result.context_notes : [];
  const fallbackUsed = notes.some(note => /entity-level lineage/i.test(note))
    || result.affected_assets.some(asset => /entity-level/i.test(asset.dependency_type || ""));
  elements.lineageScopeFallback.textContent = fallbackUsed
    ? "Entity-level fallback used"
    : "Column-level lineage";
  elements.lineageScopeCount.textContent = String(result.affected_assets.length);
  elements.lineageScopeHops.textContent = "2 downstream hops";
  elements.lineageScopeLimit.textContent = "60 assets";
  elements.lineageNote.textContent = notes.length
    ? notes.join(" · ")
    : "Lineage scope and metadata reflect the active provider response at investigation time.";

  state.lineageDisplayPreference = null;
  setLineageDisplay(prefersLineageList() ? "list" : "graph");
  renderAssetInspector(selectedAsset);
  state.inspectorTrigger = state.lineageController?.getNode(selectedAsset.urn) || null;
  state.inspectorOpen = !isInspectorDialogMode();
  syncSelectedAssetUI();
  updateInspectorVisibility();
}

function assetRow(asset) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "asset-row";
  button.dataset.assetUrn = asset.urn;
  button.setAttribute("role", "option");
  button.setAttribute("aria-selected", String(state.selectedAsset?.urn === asset.urn));
  button.setAttribute("aria-label", `Inspect ${asset.name || readableNameFromUrn(asset.urn)} on ${asset.platform || "unknown platform"}`);
  button.classList.toggle("is-selected", state.selectedAsset?.urn === asset.urn);

  const identity = document.createElement("span");
  identity.className = "asset-identity";
  const name = document.createElement("strong");
  name.textContent = asset.name || readableNameFromUrn(asset.urn);
  const selected = document.createElement("small");
  selected.className = "asset-selected-label";
  selected.textContent = "Selected";
  identity.append(name, selected);

  const context = document.createElement("span");
  context.className = "asset-context";
  context.dataset.label = "Platform / type";
  const platform = document.createElement("strong");
  platform.textContent = asset.platform || "Unknown platform";
  const type = document.createElement("small");
  type.textContent = assetTypeLabel(asset.asset_type);
  context.append(platform, type);

  const dependency = document.createElement("span");
  dependency.className = "asset-dependency";
  dependency.dataset.label = "Dependency evidence";
  const dependencyType = document.createElement("strong");
  const dependencyHops = document.createElement("small");
  dependencyType.textContent = asset.dependency_type || "Downstream dependency";
  dependencyHops.textContent = `${Number(asset.hops || 0)} hop${Number(asset.hops || 0) === 1 ? "" : "s"}`;
  dependency.append(dependencyType, dependencyHops);

  const criticality = document.createElement("span");
  criticality.className = "asset-criticality";
  criticality.dataset.label = "Criticality";
  const criticalityValue = document.createElement("strong");
  const criticalitySource = document.createElement("small");
  criticalityValue.textContent = sentenceCase(asset.criticality || "unknown");
  criticalitySource.textContent = asset.criticality_source === "datahub" ? "DataHub" : metadataSourceLabel(asset.criticality_source);
  criticality.append(criticalityValue, criticalitySource);

  const quality = document.createElement("span");
  quality.className = "asset-quality";
  quality.dataset.label = "Quality";
  quality.dataset.state = asset.metadata_sources?.quality === "datahub"
    ? (asset.quality_status || "unknown")
    : "unknown";
  const qualityValue = document.createElement("strong");
  const qualitySource = document.createElement("small");
  qualityValue.textContent = asset.metadata_sources?.quality === "datahub"
    ? sentenceCase(asset.quality_status || "unknown")
    : "Unknown";
  qualitySource.textContent = asset.metadata_sources?.quality === "datahub" ? "DataHub" : "Unavailable";
  quality.append(qualityValue, qualitySource);

  const owner = document.createElement("span");
  owner.className = "asset-owner";
  owner.dataset.label = "Owner";
  const ownerDetails = Array.isArray(asset.owner_details) ? asset.owner_details : [];
  const owners = (ownerDetails.length ? ownerDetails.map(item => item.label) : (asset.owners || []))
    .filter(Boolean);
  const ownerValue = document.createElement("strong");
  const ownerSource = document.createElement("small");
  ownerValue.textContent = owners.length
    ? `${owners[0]}${owners.length > 1 ? ` +${owners.length - 1}` : ""}`
    : "No owner";
  ownerSource.textContent = asset.metadata_sources?.owners === "datahub" ? "DataHub" : "Unavailable";
  owner.append(ownerValue, ownerSource);

  button.append(identity, context, dependency, criticality, quality, owner);
  button.addEventListener("click", () => inspectAsset(asset, {trigger: button}));
  button.addEventListener("keydown", event => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      focusAdjacentAssetRow(elements.assets, button, event.key === "ArrowDown" ? 1 : -1);
    }
  });
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
    const ownerText = [
      ...(asset.owners || []),
      ...(asset.owner_details || []).map(owner => `${owner.label || ""} ${owner.ownership_type || ""}`)
    ].join(" ");
    const text = `${asset.name || ""} ${asset.platform || ""} ${asset.asset_type || ""} ${asset.dependency_type || ""} ${asset.quality_status || ""} ${asset.quality_evidence || ""} ${ownerText}`.toLowerCase();
    return (!query || text.includes(query))
      && (selectedType === "all" || assetGroup(asset.asset_type) === selectedType)
      && (platform === "all" || String(asset.platform || "").toLowerCase() === platform)
      && (criticality === "all" || asset.criticality === criticality)
      && (!state.qualityFailureOnly || (
        asset.quality_status === "failing"
        && asset.metadata_sources?.quality === "datahub"
      ));
  });
}

function renderAssetList() {
  const assets = filteredAssets();
  elements.assets.replaceChildren(...assets.map(assetRow));
  elements.assetCount.textContent = `${assets.length} result${assets.length === 1 ? "" : "s"}`;
  elements.assetsEmpty.classList.toggle("is-hidden", assets.length > 0);
  const failingCount = state.result?.affected_assets.filter(asset =>
    asset.quality_status === "failing"
      && asset.metadata_sources?.quality === "datahub"
  ).length || 0;
  elements.failingQualityCount.textContent = String(failingCount);
  elements.failingQualityFilter.setAttribute("aria-pressed", String(state.qualityFailureOnly));
  elements.failingQualityFilter.classList.toggle("is-active", state.qualityFailureOnly);
  syncSelectedAssetUI();
}

function referencedAssetsForFactor(factor, result) {
  const evidence = String(factor.evidence || "").toLowerCase();
  const qualityFactor = String(factor.label || "").toLowerCase().includes("quality");
  const candidates = [normalizeRootAsset(result), ...result.affected_assets];
  const seen = new Set();
  return candidates.filter(asset => {
    const name = String(asset.name || "").trim();
    const explicitFailure = asset.quality_status === "failing"
      && asset.metadata_sources?.quality === "datahub";
    if (name.length < 3
      || !evidence.includes(name.toLowerCase())
      || seen.has(asset.urn)
      || (qualityFactor && !explicitFailure)) {
      return false;
    }
    seen.add(asset.urn);
    return true;
  });
}

function riskFactorAuthority(factor, referencedAssets, result) {
  const label = String(factor.label || "").toLowerCase();
  const providerLabel = result.provider === "datahub" ? "DataHub" : sentenceCase(result.provider || "provider");

  if (label.includes("quality")) {
    const explicitQuality = referencedAssets.some(asset => asset.metadata_sources?.quality === "datahub");
    return explicitQuality ? "Explicit DataHub quality evidence" : `${providerLabel} evidence · deterministic rule`;
  }
  if (label.includes("business-critical") || label.includes("criticality")) {
    return "LineageShield deterministic inference";
  }
  if (label.includes("cross-team") || label.includes("coordination")) {
    return `${providerLabel} ownership · deterministic rule`;
  }
  if (label.includes("downstream") || label.includes("blast radius")) {
    return `${providerLabel} lineage · deterministic rule`;
  }
  return "Change proposal · deterministic rule";
}

function factorEvidenceCell(factor, referencedAssets) {
  const cell = document.createElement("div");
  cell.className = "factor-evidence";
  cell.setAttribute("role", "cell");
  const evidence = document.createElement("span");
  evidence.textContent = factor.evidence;
  cell.append(evidence);

  if (!referencedAssets.length) return cell;
  const references = document.createElement("span");
  references.className = "factor-asset-references";
  referencedAssets.slice(0, 3).forEach(asset => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "factor-asset-link";
    button.dataset.assetUrn = asset.urn;
    button.setAttribute("aria-pressed", String(state.selectedAsset?.urn === asset.urn));
    button.textContent = `Inspect ${asset.name || readableNameFromUrn(asset.urn)} · ${asset.platform || "Unknown platform"}`;
    button.addEventListener("click", () => inspectAsset(asset, {trigger: button}));
    references.append(button);
  });
  if (referencedAssets.length > 3) {
    const remainder = document.createElement("span");
    remainder.textContent = `+${referencedAssets.length - 3} more referenced`;
    references.append(remainder);
  }
  cell.append(references);
  return cell;
}

function renderRisk(result) {
  const rawScore = result.raw_risk_score
    ?? result.factors.reduce((sum, factor) => sum + factor.points, 0);
  elements.riskDisposition.textContent = decisionLabel(result.decision);
  elements.riskLedgerDisposition.dataset.decision = result.decision;
  elements.riskFinalScore.textContent = `${result.risk_score}/100`;
  elements.rawScore.textContent = `${rawScore} point${rawScore === 1 ? "" : "s"}`;
  elements.riskFactorTotal.textContent = String(rawScore);
  elements.scoreCapNote.textContent = rawScore > 100
    ? `${rawScore} raw points capped to ${result.risk_score}.`
    : `Raw and capped score both equal ${result.risk_score}.`;
  elements.riskAuthoritySummary.textContent = `${result.decision} at ${result.risk_score}/100 is the authoritative deterministic result. Agent Context supplies supplemental narrative only and cannot change this ledger.`;

  const factorRows = result.factors.map(factor => {
    const referencedAssets = referencedAssetsForFactor(factor, result);
    const row = document.createElement("div");
    row.className = "factor-row";
    row.setAttribute("role", "row");
    const label = document.createElement("div");
    label.className = "factor-label";
    label.setAttribute("role", "cell");
    label.textContent = factor.label;
    const evidence = factorEvidenceCell(factor, referencedAssets);
    const authority = document.createElement("div");
    authority.className = "factor-authority";
    authority.setAttribute("role", "cell");
    authority.textContent = riskFactorAuthority(factor, referencedAssets, result);
    const points = document.createElement("div");
    points.className = "factor-points";
    points.setAttribute("role", "cell");
    points.textContent = `+${factor.points}`;
    row.append(label, evidence, authority, points);
    return row;
  });
  elements.factors.replaceChildren(...factorRows);

  const approvals = result.required_approvals || [];
  if (approvals.length) {
    elements.approvals.replaceChildren(...approvals.map(owner => {
      const row = document.createElement("li");
      row.className = "approval-row";
      const name = document.createElement("strong");
      name.textContent = owner;
      const requirement = document.createElement("span");
      requirement.textContent = "Required approval";
      row.append(name, requirement);
      return row;
    }));
  } else {
    const empty = document.createElement("li");
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
  elements.artifactLanguage.textContent = `${config.language} · generated review artifact`;
  elements.artifactProvenance.textContent = state.artifactTab === "rollback"
    ? "Generated deterministically by LineageShield as human-readable rollback steps; this is not presented as executable SQL."
    : "Generated deterministically by LineageShield for human review. No artifact was executed.";
  elements.artifactFileSelect.value = state.artifactTab;
  elements.artifactCode.parentElement.dataset.language = config.language.toLowerCase().replaceAll(" ", "-");
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

function announceInspectorCopy(message) {
  window.clearTimeout(state.copyTimer);
  elements.inspectorCopyStatus.textContent = message;
  state.copyTimer = window.setTimeout(() => {
    elements.inspectorCopyStatus.textContent = "";
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
  state.selectedAsset = null;
  state.inspectorOpen = false;
  state.inspectorTrigger = null;
  state.lineageController = null;
  state.lineageDisplayPreference = null;
  state.qualityFailureOnly = false;
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
  elements.writebackModeState.textContent = status === "enabled"
    ? "On · apply requires confirmation"
    : (status === "disabled" ? "Off · read-only default" : label);
  if (state.writebackPreviewError) {
    elements.writebackWorkflow.dataset.writebackState = "preview-error";
    elements.writebackStateTitle.textContent = "Preview unavailable";
  } else if (!state.writebackPreview && elements.writebackReceipt.classList.contains("is-hidden")) {
    const previewAvailable = Boolean(state.result && datahubAnalysis && !connectionFailed);
    elements.writebackWorkflow.dataset.writebackState = previewAvailable ? "awaiting-preview" : "unavailable";
    elements.writebackStateTitle.textContent = previewAvailable ? "Preview available" : "Preview unavailable";
  }
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
  state.writebackPreviewError = false;
  state.writebackOutcomeUnknown = false;
  elements.writebackConfirm.checked = false;
  elements.writebackResultingDetails.open = false;
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
    || state.writebackPreviewError
    || state.writebackOutcomeUnknown
    || !elements.writebackConfirm.checked;
  if (state.writebackPreview && !state.writebackPreviewError && !state.writebackOutcomeUnknown) {
    elements.writebackWorkflow.dataset.writebackState = elements.writebackConfirm.checked
      ? "confirmation-complete"
      : "confirmation-required";
    elements.writebackStateTitle.textContent = elements.writebackConfirm.checked
      ? "Confirmation recorded"
      : "Confirmation required";
  }
}

function renderWritebackPreview(preview) {
  state.writebackPreview = preview;
  state.writebackPreviewError = false;
  state.writebackOutcomeUnknown = false;
  state.mutationsEnabled = preview.mutations_enabled === true;
  const {record, mutation} = preview;
  elements.writebackTarget.textContent = record.root_asset.name || "Unnamed asset";
  elements.writebackTargetUrn.textContent = record.root_asset.urn;
  elements.writebackAnalysisId.textContent = record.analysis_id || state.result?.analysis_id || "Unavailable";
  elements.writebackPreservation.textContent = mutation.preserves_existing_description
    ? "Preserved around the managed block"
    : "No existing documentation was returned";
  elements.writebackDecision.textContent = record.decision;
  elements.writebackRisk.textContent = `${record.risk_score}/100 · ${record.risk_level}`;
  elements.writebackIdempotency.textContent = mutation.already_applied
    ? "Already present · no-op on apply"
    : "New managed record";
  elements.writebackManagedSection.textContent = mutation.managed_section;
  elements.writebackResultingDescription.textContent = mutation.resulting_description;
  elements.writebackResultingDetails.open = false;
  elements.writebackWarnings.replaceChildren(...(preview.warnings || []).map(warning => {
    const item = document.createElement("li");
    item.textContent = warning;
    return item;
  }));
  elements.writebackConfirm.checked = false;
  elements.writebackPreview.classList.remove("is-hidden");
  elements.writebackReceipt.classList.add("is-hidden");
  elements.writebackWorkflow.dataset.writebackState = mutation.already_applied
    ? "already-present"
    : "preview-ready";
  elements.writebackStateTitle.textContent = mutation.already_applied
    ? "Preview ready · record already present"
    : "Preview ready";
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
  elements.writebackWorkflow.dataset.writebackState = receipt.status === "already_applied"
    ? "already-applied"
    : "applied";
  elements.writebackStateTitle.textContent = receipt.status === "already_applied"
    ? "Already applied"
    : "Applied";
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

elements.failingQualityFilter.addEventListener("click", () => {
  state.qualityFailureOnly = !state.qualityFailureOnly;
  renderAssetList();
  elements.failingQualityFilter.focus({preventScroll: true});
});

byId("clear-filters").addEventListener("click", () => {
  elements.assetSearch.value = "";
  elements.typeFilter.value = "all";
  elements.platformFilter.value = "all";
  elements.criticalityFilter.value = "all";
  state.qualityFailureOnly = false;
  renderAssetList();
  elements.assetSearch.focus();
});

elements.fitLineage.addEventListener("click", () => {
  state.lineageController?.fit();
  elements.lineageCanvas.focus({preventScroll: true});
});

elements.resetLineageSelection.addEventListener("click", () => {
  state.selectedAsset = null;
  state.inspectorOpen = false;
  state.inspectorTrigger = null;
  state.lineageController?.resetSelection();
  syncSelectedAssetUI();
  updateInspectorVisibility();
  elements.lineageCanvas.focus({preventScroll: true});
});

elements.toggleLineageList.addEventListener("click", () => {
  setLineageDisplay(state.lineageDisplay === "graph" ? "list" : "graph", {user: true});
  const target = state.lineageDisplay === "list"
    ? (elements.lineageAssetList.querySelector(".is-selected") || elements.lineageAssetList.querySelector("button"))
    : elements.lineageCanvas;
  target.focus({preventScroll: true});
});

elements.closeAssetInspector.addEventListener("click", () => closeAssetInspector());
elements.assetInspectorBackdrop.addEventListener("click", () => closeAssetInspector());
elements.assetInspector.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    event.preventDefault();
    closeAssetInspector();
    return;
  }
  if (event.key !== "Tab" || !isInspectorDialogMode()) return;
  const focusable = [...elements.assetInspector.querySelectorAll(
    "button:not([disabled]), summary, a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"
  )].filter(item => !item.hidden);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable.at(-1);
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});

window.addEventListener("resize", () => {
  if (state.lineageDisplayPreference === null && state.result) {
    setLineageDisplay(prefersLineageList() ? "list" : "graph");
  }
  updateInspectorVisibility();
});

document.querySelectorAll(".artifact-tab").forEach(button => {
  button.addEventListener("click", () => selectArtifactTab(button));
  button.addEventListener("keydown", event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...document.querySelectorAll(".artifact-tab")];
    const index = tabs.indexOf(button);
    let target = index;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") target = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") target = (index + 1) % tabs.length;
    if (event.key === "Home") target = 0;
    if (event.key === "End") target = tabs.length - 1;
    selectArtifactTab(tabs[target], {focus: true});
  });
});

elements.artifactFileSelect.addEventListener("change", () => {
  const button = byId(`tab-${elements.artifactFileSelect.value}`);
  if (button) selectArtifactTab(button);
});

byId("copy-urn").addEventListener("click", async () => {
  if (!state.selectedAsset) return;
  try {
    await copyText(state.selectedAsset.urn);
    announceInspectorCopy("DataHub URN copied.");
  } catch {
    announceInspectorCopy("The URN could not be copied. Select it manually from this panel.");
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
  announceCopy(`${config.filename} downloaded.`);
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
  state.writebackPreviewError = false;
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
    state.writebackPreviewError = true;
    elements.writebackWorkflow.dataset.writebackState = "preview-error";
    elements.writebackStateTitle.textContent = "Preview unavailable";
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
    if (unknownOutcome) {
      elements.writebackWorkflow.dataset.writebackState = "unknown";
      elements.writebackStateTitle.textContent = "Outcome unknown · inspect DataHub before retrying";
    }
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
updateInspectorMode();
updateConnectionStatus();
