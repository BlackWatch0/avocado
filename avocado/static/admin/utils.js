export const joinList = (items) => (items || []).join(", ");
export const splitByComma = (text) =>
  (text || "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);

export const escapeHtml = (value) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

export const shortText = (value, limit = 120) => {
  const compact = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!compact) return "";
  if (compact.length <= limit) return compact;
  return `${compact.slice(0, limit)}...`;
};

export const toDisplayValue = (value) => (value === null || value === undefined || value === "" ? "-" : String(value));

export const toPrettyJson = (value) => {
  if (value === null || value === undefined) return "{}";
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return "{}";
    try {
      return JSON.stringify(JSON.parse(trimmed), null, 2);
    } catch (_err) {
      return trimmed;
    }
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch (_err) {
    return String(value);
  }
};

export const ensureSelectOption = (selectEl, value, label = "", makeSelected = false) => {
  if (!selectEl) return;
  const text = label || value || "-";
  let option = [...selectEl.options].find((opt) => opt.value === value);
  if (!option) {
    option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    selectEl.appendChild(option);
  } else if (label) {
    option.textContent = text;
  }
  if (makeSelected) {
    selectEl.value = value;
  }
};

export const summarizeDetails = (value) => {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return shortText(value, 150);
  if (typeof value === "object") {
    const entries = Object.entries(value);
    if (!entries.length) return "";
    return shortText(
      entries
        .slice(0, 4)
        .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
        .join(" | "),
      150
    );
  }
  return shortText(value, 150);
};

export const statusBadgeClass = (status) => {
  const value = String(status || "").toLowerCase();
  if (["ok", "success", "done", "completed"].includes(value)) return "status-ok";
  if (["error", "failed", "fail"].includes(value)) return "status-error";
  if (["running", "queued", "in_progress"].includes(value)) return "status-running";
  return "status-default";
};

export const formatShortTime = (isoText) => {
  if (!isoText) return "-";
  const dt = new Date(isoText);
  if (Number.isNaN(dt.getTime())) return isoText;
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  const d = String(dt.getDate()).padStart(2, "0");
  const h = String(dt.getHours()).padStart(2, "0");
  const mi = String(dt.getMinutes()).padStart(2, "0");
  return `${m}-${d} ${h}:${mi}`;
};

export const formatEventRange = (start, end, fallbackText) => {
  const startText = String(start || "").trim();
  const endText = String(end || "").trim();
  if (!startText && !endText) return fallbackText;
  const left = startText ? formatShortTime(startText) : "-";
  const right = endText ? formatShortTime(endText) : "-";
  return `${left} -> ${right}`;
};
