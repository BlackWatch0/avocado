import { apiGetJson, apiPost, apiPut } from "./api.js";
import { renderAiChanges, hideAllKebabMenus } from "./ai_changes.js";
import { renderAiBytesChart } from "./ai_bytes_chart.js";
import { renderCalendars, readLockedSourceCalendarIds } from "./calendars_table.js";
import { bindConfig, readPayload } from "./config_form.js";
import { dom } from "./dom.js";
import { I18N } from "./i18n.js";
import { renderAuditLogs } from "./logs_audit.js";
import { renderSyncLogs } from "./logs_sync.js";
import { AI_BYTES_CACHE_KEY, AI_BYTES_DAYS_KEY, LANG_PREF_KEY, state } from "./state.js";
import { retranslateStatus, setActiveTab, setStatus, withPending } from "./ui.js";
import {
  ensureSelectOption,
  escapeHtml,
  formatShortTime,
  shortText,
  splitByComma,
  statusBadgeClass,
  summarizeDetails,
  toDisplayValue,
  toPrettyJson,
  joinList,
} from "./utils.js";

const template = (text, vars = {}) =>
  String(text || "").replace(/\{([a-zA-Z0-9_]+)\}/g, (_, key) => String(vars[key] ?? ""));

const detectBrowserLang = () => {
  const source = (navigator.languages && navigator.languages[0]) || navigator.language || "en";
  return source.toLowerCase().startsWith("zh") ? "zh" : "en";
};

const resolveLanguage = (pref) => {
  if (pref === "zh" || pref === "en") return pref;
  return detectBrowserLang();
};

const t = (key, vars = {}) => {
  const langPack = I18N[state.currentLang] || I18N.en;
  const fallback = I18N.en[key] || key;
  return template(langPack[key] || fallback, vars);
};

const rerenderAll = () => {
  renderCalendars({
    state,
    calendarBody: dom.calendarBody,
    calendars: state.latestCalendars,
    t,
    toDisplayValue,
    escapeHtml,
  });
  renderSyncLogs({
    state,
    syncLogsBody: dom.syncLogsBody,
    runs: state.latestSyncRuns,
    t,
    toDisplayValue,
    escapeHtml,
    statusBadgeClass,
    onSelectRun: async (runId) => {
      state.selectedAuditRunId = runId;
      if (dom.auditRunIdInput) {
        dom.auditRunIdInput.value = state.selectedAuditRunId ? String(state.selectedAuditRunId) : "";
      }
      await loadAuditLogs();
    },
  });
  renderAuditLogs({
    state,
    auditLogsBody: dom.auditLogsBody,
    events: state.latestAuditEvents,
    t,
    toDisplayValue,
    summarizeDetails,
    toPrettyJson,
    escapeHtml,
  });
  renderAiChanges({
    state,
    aiChangesList: dom.aiChangesList,
    changes: state.latestAiChanges,
    t,
    escapeHtml,
    shortText,
    onUndo: undoAiChange,
    onRevise: reviseAiChange,
    onError: (err) => setStatus(state, dom.statusEl, t, "error", "status.error", { detail: err.message || "" }),
  });
  renderAiBytesChart({
    canvas: dom.aiBytesChartCanvas,
    records: state.latestAiRequestMetrics,
    t,
    formatShortTime,
  });
};

const applyLanguage = (pref) => {
  state.languagePref = pref;
  state.currentLang = resolveLanguage(pref);
  document.documentElement.lang = state.currentLang === "zh" ? "zh-CN" : "en";

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    el.textContent = t(key);
  });

  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    el.setAttribute("placeholder", t(key));
  });

  if (dom.langSelect) {
    const autoOpt = dom.langSelect.querySelector("option[value='auto']");
    const enOpt = dom.langSelect.querySelector("option[value='en']");
    const zhOpt = dom.langSelect.querySelector("option[value='zh']");
    if (autoOpt) autoOpt.textContent = t("lang.auto");
    if (enOpt) enOpt.textContent = "English";
    if (zhOpt) zhOpt.textContent = "中文";
  }

  document.title = t("page.title");
  rerenderAll();
  retranslateStatus(state, dom.statusEl, t);
};

const initLanguage = () => {
  let pref = "auto";
  try {
    pref = localStorage.getItem(LANG_PREF_KEY) || "auto";
  } catch (_err) {
    pref = "auto";
  }
  if (!["auto", "en", "zh"].includes(pref)) {
    pref = "auto";
  }
  if (dom.langSelect) {
    dom.langSelect.value = pref;
    dom.langSelect.addEventListener("change", () => {
      const next = ["auto", "en", "zh"].includes(dom.langSelect.value) ? dom.langSelect.value : "auto";
      try {
        localStorage.setItem(LANG_PREF_KEY, next);
      } catch (_err) {
        // ignore storage errors
      }
      applyLanguage(next);
    });
  }
  applyLanguage(pref);
};

const getAiBytesDays = () => {
  const value = Number(dom.aiBytesDaysInput?.value || "90");
  if (!Number.isFinite(value) || value < 1) return 90;
  return Math.min(3650, Math.floor(value));
};

const persistAiBytesDays = (days) => {
  try {
    localStorage.setItem(AI_BYTES_DAYS_KEY, String(days));
  } catch (_err) {
    // ignore storage errors
  }
};

const loadAiBytesDaysPref = () => {
  let days = 90;
  try {
    const raw = localStorage.getItem(AI_BYTES_DAYS_KEY);
    if (raw) {
      const parsed = Number(raw);
      if (Number.isFinite(parsed) && parsed >= 1) days = Math.min(3650, Math.floor(parsed));
    }
  } catch (_err) {
    // ignore storage errors
  }
  if (dom.aiBytesDaysInput) dom.aiBytesDaysInput.value = String(days);
  return days;
};

const loadConfig = async () => {
  setStatus(state, dom.statusEl, t, "info", "status.loading_config");
  const data = await apiGetJson("/api/config/raw", t("error.load_config_failed"));
  bindConfig({ cfg: data.config || {}, t, ensureSelectOption, joinList });
  await loadSystemTimezone({ silent: true });
  setStatus(state, dom.statusEl, t, "success", "status.config_loaded");
};

const loadSystemTimezone = async ({ silent = false } = {}) => {
  try {
    const data = await apiGetJson("/api/system/timezone", t("error.load_system_timezone_failed"));
    if (dom.hostTimezoneCode) {
      dom.hostTimezoneCode.textContent = String(data.host_timezone || "UTC");
    }
    if (dom.effectiveTimezoneCode) {
      dom.effectiveTimezoneCode.textContent = String(data.effective_timezone || "UTC");
    }
    if (dom.timezoneSourceSelect && dom.timezoneSelect) {
      dom.timezoneSourceSelect.value = data.timezone_source === "manual" ? "manual" : "host";
      dom.timezoneSelect.disabled = dom.timezoneSourceSelect.value !== "manual";
    }
  } catch (err) {
    if (!silent) {
      setStatus(state, dom.statusEl, t, "error", "status.error", {
        detail: err.message || t("error.load_system_timezone_failed"),
      });
    }
  }
};

const loadCalendars = async () => {
  const data = await apiGetJson("/api/calendars", t("error.load_calendars_failed"));
  renderCalendars({
    state,
    calendarBody: dom.calendarBody,
    calendars: data.calendars || [],
    t,
    toDisplayValue,
    escapeHtml,
  });
};

const loadSyncLogs = async () => {
  const data = await apiGetJson("/api/sync/status?limit=50", t("error.load_sync_logs_failed"));
  renderSyncLogs({
    state,
    syncLogsBody: dom.syncLogsBody,
    runs: data.runs || [],
    t,
    toDisplayValue,
    escapeHtml,
    statusBadgeClass,
    onSelectRun: async (runId) => {
      state.selectedAuditRunId = runId;
      if (dom.auditRunIdInput) {
        dom.auditRunIdInput.value = state.selectedAuditRunId ? String(state.selectedAuditRunId) : "";
      }
      await loadAuditLogs();
    },
  });
};

const loadAuditLogs = async () => {
  const qs = new URLSearchParams({ limit: "300" });
  if (state.selectedAuditRunId) qs.set("run_id", String(state.selectedAuditRunId));
  const data = await apiGetJson(`/api/audit/events?${qs.toString()}`, t("error.load_audit_logs_failed"));
  renderAuditLogs({
    state,
    auditLogsBody: dom.auditLogsBody,
    events: data.events || [],
    t,
    toDisplayValue,
    summarizeDetails,
    toPrettyJson,
    escapeHtml,
  });
};

const loadAiChanges = async () => {
  const data = await apiGetJson("/api/ai/changes?limit=15", t("error.load_ai_changes_failed"));
  renderAiChanges({
    state,
    aiChangesList: dom.aiChangesList,
    changes: data.changes || [],
    t,
    escapeHtml,
    shortText,
    onUndo: undoAiChange,
    onRevise: reviseAiChange,
    onError: (err) => setStatus(state, dom.statusEl, t, "error", "status.error", { detail: err.message || "" }),
  });
};

const loadAiRequestMetrics = async ({ silent = false } = {}) => {
  const days = getAiBytesDays();
  persistAiBytesDays(days);
  if (!silent) setStatus(state, dom.statusEl, t, "info", "status.refreshing_ai_bytes");
  try {
    const data = await apiGetJson(
      `/api/metrics/ai-request-bytes?days=${encodeURIComponent(days)}&limit=20000`,
      t("error.load_ai_bytes_failed")
    );
    state.latestAiRequestMetrics = data.points || [];
    renderAiBytesChart({ canvas: dom.aiBytesChartCanvas, records: state.latestAiRequestMetrics, t, formatShortTime });
    try {
      localStorage.setItem(
        AI_BYTES_CACHE_KEY,
        JSON.stringify({ days, points: state.latestAiRequestMetrics, cached_at: new Date().toISOString() })
      );
    } catch (_err) {
      // ignore storage errors
    }
    if (!silent) setStatus(state, dom.statusEl, t, "success", "status.ai_bytes_refreshed");
  } catch (err) {
    if (state.latestAiRequestMetrics.length === 0) {
      try {
        const cached = JSON.parse(localStorage.getItem(AI_BYTES_CACHE_KEY) || "{}");
        if (Array.isArray(cached.points) && cached.points.length) {
          state.latestAiRequestMetrics = cached.points;
          renderAiBytesChart({ canvas: dom.aiBytesChartCanvas, records: state.latestAiRequestMetrics, t, formatShortTime });
        }
      } catch (_cacheErr) {
        // ignore cache parse errors
      }
    }
    if (!silent) {
      setStatus(state, dom.statusEl, t, "error", "status.error", { detail: err.message || t("error.load_ai_bytes_failed") });
    }
  }
};

const undoAiChange = async (auditId) => {
  setStatus(state, dom.statusEl, t, "info", "status.undoing_ai_change");
  await apiPost("/api/ai/changes/undo", t("error.undo_ai_change_failed"), { audit_id: Number(auditId) });
  await loadAiChanges();
  await loadAuditLogs();
  await loadSyncLogs();
  setStatus(state, dom.statusEl, t, "success", "status.ai_change_undone");
};

const reviseAiChange = async (auditId, instruction) => {
  setStatus(state, dom.statusEl, t, "info", "status.requesting_ai_revise");
  await apiPost("/api/ai/changes/revise", t("error.revise_ai_change_failed"), {
    audit_id: Number(auditId),
    instruction,
  });
  await loadAiChanges();
  await loadAuditLogs();
  await loadSyncLogs();
  setStatus(state, dom.statusEl, t, "success", "status.ai_revise_requested");
};

const saveConfig = async () => {
  withPending(dom.saveBtn, true);
  try {
    const payload = readPayload({ t, splitByComma, readLockedSourceCalendarIds: () => readLockedSourceCalendarIds(dom.calendarBody) });
    setStatus(state, dom.statusEl, t, "info", "status.saving_config");
    await apiPut("/api/config", t("error.save_failed"), { payload });
    await loadConfig();
    await loadCalendars();
    await loadAiChanges();
    await loadSystemTimezone({ silent: true });
    await loadAiRequestMetrics({ silent: true });
    setStatus(state, dom.statusEl, t, "success", "status.config_saved");
  } catch (err) {
    setStatus(state, dom.statusEl, t, "error", "status.error", { detail: err.message || t("error.save_failed") });
  } finally {
    withPending(dom.saveBtn, false);
  }
};

const runSync = async () => {
  withPending(dom.syncBtn, true);
  try {
    setStatus(state, dom.statusEl, t, "info", "status.triggering_sync");
    await apiPost("/api/sync/run", t("error.sync_trigger_failed"));
    await loadCalendars();
    await loadSyncLogs();
    await loadAuditLogs();
    await loadAiChanges();
    await loadAiRequestMetrics({ silent: true });
    setStatus(state, dom.statusEl, t, "success", "status.sync_triggered_refreshed");
  } catch (err) {
    setStatus(state, dom.statusEl, t, "error", "status.error", { detail: err.message || t("error.sync_trigger_failed") });
  } finally {
    withPending(dom.syncBtn, false);
  }
};

const runCustomRangeSync = async () => {
  withPending(dom.customSyncBtn, true);
  try {
    const startValue = document.getElementById("sync-custom-start").value;
    const endValue = document.getElementById("sync-custom-end").value;
    if (!startValue || !endValue) {
      throw new Error(t("error.custom_sync_missing"));
    }
    const startDate = new Date(startValue);
    const endDate = new Date(endValue);
    if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
      throw new Error(t("error.custom_sync_missing"));
    }
    if (endDate < startDate) {
      throw new Error(t("error.custom_sync_range"));
    }

    setStatus(state, dom.statusEl, t, "info", "status.triggering_custom_sync");
    await apiPost("/api/sync/run-window", t("error.sync_trigger_failed"), {
      start: startDate.toISOString(),
      end: endDate.toISOString(),
    });
    await loadCalendars();
    await loadSyncLogs();
    await loadAuditLogs();
    await loadAiChanges();
    await loadAiRequestMetrics({ silent: true });
    setStatus(state, dom.statusEl, t, "success", "status.custom_sync_triggered_refreshed");
  } catch (err) {
    setStatus(state, dom.statusEl, t, "error", "status.error", { detail: err.message || t("error.sync_trigger_failed") });
  } finally {
    withPending(dom.customSyncBtn, false);
  }
};

const refreshCalendars = async () => {
  withPending(dom.refreshCalendarsBtn, true);
  try {
    setStatus(state, dom.statusEl, t, "info", "status.refreshing_calendars");
    await loadCalendars();
    setStatus(state, dom.statusEl, t, "success", "status.calendars_refreshed");
  } catch (err) {
    setStatus(state, dom.statusEl, t, "error", "status.error", { detail: err.message || t("error.refresh_calendars_failed") });
  } finally {
    withPending(dom.refreshCalendarsBtn, false);
  }
};

const replaceAiModelOptions = (modelEl, models, preferredModel = "") => {
  if (!modelEl) return;
  const normalized = Array.isArray(models)
    ? [...new Set(models.map((x) => String(x || "").trim()).filter(Boolean))]
    : [];
  const selected = String(preferredModel || modelEl.value || "").trim();

  modelEl.innerHTML = "";
  const emptyOption = document.createElement("option");
  emptyOption.value = "";
  emptyOption.textContent = "-";
  modelEl.appendChild(emptyOption);

  normalized.forEach((modelId) => {
    const option = document.createElement("option");
    option.value = modelId;
    option.textContent = modelId;
    modelEl.appendChild(option);
  });

  if (selected && normalized.includes(selected)) {
    modelEl.value = selected;
  } else if (normalized.length) {
    modelEl.value = normalized[0];
  } else {
    modelEl.value = "";
  }
};

const testAiConnectivity = async () => {
  withPending(dom.aiTestLink, true);
  try {
    setStatus(state, dom.statusEl, t, "info", "status.testing_ai");
    const data = await apiPost("/api/ai/test", t("error.ai_test_failed"));
    const message = (data.message || "").trim();
    const modelEl = document.getElementById("ai-model");
    const currentModel = modelEl?.value || "";
    const models = Array.isArray(data.models) ? data.models : [];
    replaceAiModelOptions(modelEl, models, currentModel);
    if (data.ok) {
      setStatus(state, dom.statusEl, t, "success", "status.ai_ok", { message });
    } else {
      setStatus(state, dom.statusEl, t, "error", "status.ai_failed", { message });
    }
  } catch (err) {
    setStatus(state, dom.statusEl, t, "error", "status.error", { detail: err.message || t("error.ai_test_failed") });
  } finally {
    withPending(dom.aiTestLink, false);
  }
};

const refreshSyncLogs = async () => {
  withPending(dom.refreshSyncLogsBtn, true);
  try {
    setStatus(state, dom.statusEl, t, "info", "status.refreshing_sync_logs");
    await loadSyncLogs();
    setStatus(state, dom.statusEl, t, "success", "status.sync_logs_refreshed");
  } catch (err) {
    setStatus(state, dom.statusEl, t, "error", "status.error", { detail: err.message || t("error.refresh_sync_logs_failed") });
  } finally {
    withPending(dom.refreshSyncLogsBtn, false);
  }
};

const refreshAuditLogs = async () => {
  withPending(dom.refreshAuditLogsBtn, true);
  try {
    setStatus(state, dom.statusEl, t, "info", "status.refreshing_audit_logs");
    await loadAuditLogs();
    setStatus(state, dom.statusEl, t, "success", "status.audit_logs_refreshed");
  } catch (err) {
    setStatus(state, dom.statusEl, t, "error", "status.error", { detail: err.message || t("error.refresh_audit_logs_failed") });
  } finally {
    withPending(dom.refreshAuditLogsBtn, false);
  }
};

const applyAuditRunFilter = async () => {
  const runId = Number((dom.auditRunIdInput?.value || "").trim());
  state.selectedAuditRunId = Number.isFinite(runId) && runId > 0 ? runId : null;
  await loadAuditLogs();
};

const clearAuditRunFilter = async () => {
  state.selectedAuditRunId = null;
  if (dom.auditRunIdInput) dom.auditRunIdInput.value = "";
  await loadAuditLogs();
};

const refreshAiChanges = async () => {
  withPending(dom.refreshAiChangesBtn, true);
  try {
    setStatus(state, dom.statusEl, t, "info", "status.refreshing_ai_changes");
    await loadAiChanges();
    setStatus(state, dom.statusEl, t, "success", "status.ai_changes_refreshed");
  } catch (err) {
    setStatus(state, dom.statusEl, t, "error", "status.error", { detail: err.message || t("error.refresh_ai_changes_failed") });
  } finally {
    withPending(dom.refreshAiChangesBtn, false);
  }
};

const refreshAiBytes = async () => {
  withPending(dom.refreshAiBytesBtn, true);
  try {
    await loadAiRequestMetrics({ silent: false });
  } finally {
    withPending(dom.refreshAiBytesBtn, false);
  }
};

dom.saveBtn.addEventListener("click", saveConfig);
dom.syncBtn.addEventListener("click", runSync);
dom.customSyncBtn.addEventListener("click", runCustomRangeSync);
dom.refreshCalendarsBtn.addEventListener("click", refreshCalendars);
dom.aiTestLink.addEventListener("click", (event) => {
  event.preventDefault();
  if (dom.aiTestLink.getAttribute("aria-disabled") === "true") return;
  void testAiConnectivity();
});
dom.refreshSyncLogsBtn.addEventListener("click", refreshSyncLogs);
dom.refreshAuditLogsBtn.addEventListener("click", refreshAuditLogs);
if (dom.applyAuditRunFilterBtn) dom.applyAuditRunFilterBtn.addEventListener("click", () => void applyAuditRunFilter());
if (dom.clearAuditRunFilterBtn) dom.clearAuditRunFilterBtn.addEventListener("click", () => void clearAuditRunFilter());
dom.refreshAiChangesBtn.addEventListener("click", refreshAiChanges);
dom.refreshAiBytesBtn.addEventListener("click", refreshAiBytes);
dom.tabConfigBtn.addEventListener("click", () => setActiveTab(dom, "config"));
dom.tabCalendarsBtn.addEventListener("click", () => setActiveTab(dom, "calendars"));
dom.tabLogsBtn.addEventListener("click", () => setActiveTab(dom, "logs"));
if (dom.timezoneSourceSelect && dom.timezoneSelect) {
  dom.timezoneSourceSelect.addEventListener("change", () => {
    dom.timezoneSelect.disabled = dom.timezoneSourceSelect.value !== "manual";
  });
}
window.addEventListener("resize", () =>
  renderAiBytesChart({ canvas: dom.aiBytesChartCanvas, records: state.latestAiRequestMetrics, t, formatShortTime })
);
document.addEventListener("click", () => hideAllKebabMenus());

(async () => {
  try {
    initLanguage();
    loadAiBytesDaysPref();
    setActiveTab(dom, "config");
    await loadConfig();
    await loadCalendars();
    await loadSyncLogs();
    await loadAuditLogs();
    await loadAiChanges();
    await loadAiRequestMetrics({ silent: true });
    state.aiBytesAutoRefreshTimer = window.setInterval(() => {
      void loadAiRequestMetrics({ silent: true });
    }, 30000);
  } catch (err) {
    setStatus(state, dom.statusEl, t, "error", "status.initialization_failed", { detail: err.message || "" });
  }
})();
