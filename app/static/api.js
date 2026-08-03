const DEFAULT_TIMEOUT_MS = 30_000;

export class ApiError extends Error {
  constructor(message, {status = 0, detail = null} = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function validationMessage(detail) {
  if (!Array.isArray(detail)) return "";

  return detail
    .map(item => {
      const location = Array.isArray(item.loc)
        ? item.loc.filter(part => part !== "body").join(" → ")
        : "request";
      return `${location || "request"}: ${item.msg || "invalid value"}`;
    })
    .join("; ");
}

async function requestJson(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    options.timeoutMs || DEFAULT_TIMEOUT_MS
  );

  if (options.signal) {
    options.signal.addEventListener("abort", () => controller.abort(), {once: true});
  }

  try {
    const response = await fetch(path, {
      ...options,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(options.body ? {"Content-Type": "application/json"} : {}),
        ...options.headers
      }
    });

    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }

    if (!response.ok) {
      const message = validationMessage(body?.detail)
        || (typeof body?.detail === "string" ? body.detail : "")
        || (typeof body?.detail?.message === "string" ? body.detail.message : "")
        || `Request failed with status ${response.status}.`;
      throw new ApiError(message, {status: response.status, detail: body?.detail});
    }

    return body;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new ApiError("The request timed out before the investigation completed.");
    }
    if (error instanceof ApiError) throw error;
    throw new ApiError("LineageShield could not reach the backend service.");
  } finally {
    window.clearTimeout(timeout);
  }
}

export function getHealth() {
  return requestJson("/api/health", {timeoutMs: 8_000});
}

export function analyzeChange(payload) {
  return requestJson("/api/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
    timeoutMs: 80_000
  });
}

export function previewWriteback(analysisId) {
  return requestJson("/api/writeback/preview", {
    method: "POST",
    body: JSON.stringify({analysis_id: analysisId}),
    timeoutMs: 20_000
  });
}

export function applyWriteback(analysisId) {
  return requestJson("/api/writeback/apply", {
    method: "POST",
    body: JSON.stringify({
      analysis_id: analysisId,
      confirmation: "RECORD_IN_DATAHUB"
    }),
    timeoutMs: 30_000
  });
}
