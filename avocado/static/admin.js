const statusEl = document.getElementById("status");
const saveBtn = document.getElementById("save-btn");
const syncBtn = document.getElementById("sync-btn");
const refreshCalendarsBtn = document.getElementById("refresh-calendars-btn");
const aiTestLink = document.getElementById("ai-test-link");
const refreshSyncLogsBtn = document.getElementById("refresh-sync-logs-btn");
const refreshAuditLogsBtn = document.getElementById("refresh-audit-logs-btn");
const tabConfigBtn = document.getElementById("tab-config");
const tabCalendarsBtn = document.getElementById("tab-calendars");
const tabLogsBtn = document.getElementById("tab-logs");
const langSelect = document.getElementById("lang-select");
const calendarBody = document.getElementById("calendar-behaviors-body");
const syncLogsBody = document.getElementById("sync-logs-body");
const auditLogsBody = document.getElementById("audit-logs-body");
const panelEls = [...document.querySelectorAll("[data-panel]")];

const LANG_PREF_KEY = "avocado_admin_lang_pref";

const I18N = {
  en: {
    "page.title": "Avocado Admin",
    "lang.label": "Language",
    "lang.auto": "Auto",
    "lang.en": "English",
    "lang.zh": "Chinese",
    "tab.config": "Config",
    "tab.calendars": "Calendars",
    "tab.logs": "Logs",
    "action.run_sync": "Run Sync",
    "action.refresh_calendars": "Refresh Calendars",
    "action.save_config": "Save Config",
    "action.refresh_sync_logs": "Refresh Sync Logs",
    "action.refresh_audit_logs": "Refresh Audit Logs",
    "section.caldav": "CalDAV",
    "section.ai": "AI",
    "section.sync": "Sync",
    "section.calendar_rules": "Calendar Rules",
    "section.task_defaults": "Task Defaults",
    "section.calendars": "Calendars (from CalDAV)",
    "section.logs": "Run Logs",
    "field.base_url": "Base URL",
    "field.username": "Username",
    "field.password": "Password",
    "field.api_key": "API Key",
    "field.model": "Model",
    "field.timeout_seconds": "Timeout Seconds",
    "field.system_prompt": "System Prompt",
    "field.window_days": "Window Days",
    "field.interval_seconds": "Interval Seconds",
    "field.timezone": "Timezone",
    "field.immutable_keywords": "Immutable Keywords (comma separated)",
    "field.immutable_calendar_ids": "Immutable Calendar IDs (auto-filled from calendar table)",
    "field.staging_calendar_id": "Staging Calendar ID",
    "field.staging_calendar_name": "Staging Calendar Name",
    "field.user_calendar_id": "User Calendar ID",
    "field.user_calendar_name": "User Calendar Name",
    "field.locked": "Locked",
    "field.mandatory": "Mandatory",
    "field.editable_fields": "Editable Fields (comma separated)",
    "placeholder.keep_secret": "Leave empty to keep current",
    "ai.test_link": "Test AI API connectivity",
    "hint.refresh_calendars": "Click Sync or Refresh Calendars to load latest list from server.",
    "table.name": "Name",
    "table.immutable": "Immutable",
    "table.default_locked": "Default Locked",
    "table.default_mandatory": "Default Mandatory",
    "table.run_at": "Run At",
    "table.status": "Status",
    "table.trigger": "Trigger",
    "table.changes": "Changes",
    "table.conflicts": "Conflicts",
    "table.message": "Message",
    "table.created_at": "Created At",
    "table.action": "Action",
    "table.calendar": "Calendar",
    "table.uid": "UID",
    "table.details": "Details",
    "status.loading_config": "Loading config...",
    "status.config_loaded": "Config loaded.",
    "status.saving_config": "Saving config...",
    "status.config_saved": "Config saved.",
    "status.triggering_sync": "Triggering sync...",
    "status.sync_triggered_refreshed": "Sync triggered and calendars/logs refreshed.",
    "status.refreshing_calendars": "Refreshing calendars...",
    "status.calendars_refreshed": "Calendars refreshed.",
    "status.testing_ai": "Testing AI connectivity...",
    "status.ai_ok": "AI connectivity OK. {message}",
    "status.ai_failed": "AI connectivity failed. {message}",
    "status.refreshing_sync_logs": "Refreshing sync logs...",
    "status.sync_logs_refreshed": "Sync logs refreshed.",
    "status.refreshing_audit_logs": "Refreshing audit logs...",
    "status.audit_logs_refreshed": "Audit logs refreshed.",
    "status.initialization_failed": "Failed to initialize: {detail}",
    "status.error": "{detail}",
    "error.window_days": "window_days must be >= 1",
    "error.interval_seconds": "interval_seconds must be >= 30",
    "error.timeout_seconds": "timeout_seconds must be >= 1",
    "error.load_config_failed": "Failed to load config",
    "error.load_calendars_failed": "Failed to load calendars",
    "error.load_sync_logs_failed": "Failed to load sync logs",
    "error.load_audit_logs_failed": "Failed to load audit logs",
    "error.save_failed": "Save failed",
    "error.sync_trigger_failed": "Sync trigger failed",
    "error.refresh_calendars_failed": "Refresh calendars failed",
    "error.ai_test_failed": "AI connectivity test failed",
    "error.refresh_sync_logs_failed": "Refresh sync logs failed",
    "error.refresh_audit_logs_failed": "Refresh audit logs failed",
    "empty.calendars": "No calendars loaded.",
    "empty.sync_logs": "No sync logs.",
    "empty.audit_logs": "No audit logs.",
    "tag.stage": "stage",
    "tag.user_layer": "user-layer",
    "tag.duplicate_user": "duplicate-user",
    "tag.duplicate_staging": "duplicate-stage",
    "common.custom": "custom"
  },
  zh: {
    "page.title": "Avocado 管理后台",
    "lang.label": "语言",
    "lang.auto": "自动",
    "lang.en": "English",
    "lang.zh": "中文",
    "tab.config": "配置",
    "tab.calendars": "日历",
    "tab.logs": "日志",
    "action.run_sync": "执行同步",
    "action.refresh_calendars": "刷新日历",
    "action.save_config": "保存配置",
    "action.refresh_sync_logs": "刷新同步日志",
    "action.refresh_audit_logs": "刷新审计日志",
    "section.caldav": "CalDAV",
    "section.ai": "AI",
    "section.sync": "同步",
    "section.calendar_rules": "日历规则",
    "section.task_defaults": "任务默认值",
    "section.calendars": "日历列表（来自 CalDAV）",
    "section.logs": "运行日志",
    "field.base_url": "Base URL",
    "field.username": "用户名",
    "field.password": "密码",
    "field.api_key": "API Key",
    "field.model": "模型",
    "field.timeout_seconds": "超时时间（秒）",
    "field.system_prompt": "系统提示词",
    "field.window_days": "窗口天数",
    "field.interval_seconds": "轮询间隔（秒）",
    "field.timezone": "时区",
    "field.immutable_keywords": "不可变关键字（逗号分隔）",
    "field.immutable_calendar_ids": "不可变日历 ID（由日历表自动填充）",
    "field.staging_calendar_id": "Stage 日历 ID",
    "field.staging_calendar_name": "Stage 日历名称",
    "field.user_calendar_id": "用户层日历 ID",
    "field.user_calendar_name": "用户层日历名称",
    "field.locked": "锁定",
    "field.mandatory": "强制",
    "field.editable_fields": "可编辑字段（逗号分隔）",
    "placeholder.keep_secret": "留空则保持当前值",
    "ai.test_link": "测试 AI API 连通性",
    "hint.refresh_calendars": "点击“执行同步”或“刷新日历”以加载服务器最新列表。",
    "table.name": "名称",
    "table.immutable": "不可变",
    "table.default_locked": "默认锁定",
    "table.default_mandatory": "默认强制",
    "table.run_at": "运行时间",
    "table.status": "状态",
    "table.trigger": "触发方式",
    "table.changes": "变更数",
    "table.conflicts": "冲突数",
    "table.message": "消息",
    "table.created_at": "创建时间",
    "table.action": "动作",
    "table.calendar": "日历",
    "table.uid": "UID",
    "table.details": "详情",
    "status.loading_config": "正在加载配置...",
    "status.config_loaded": "配置已加载。",
    "status.saving_config": "正在保存配置...",
    "status.config_saved": "配置已保存。",
    "status.triggering_sync": "正在触发同步...",
    "status.sync_triggered_refreshed": "已触发同步并刷新日历/日志。",
    "status.refreshing_calendars": "正在刷新日历...",
    "status.calendars_refreshed": "日历已刷新。",
    "status.testing_ai": "正在测试 AI 连通性...",
    "status.ai_ok": "AI 连通性正常。{message}",
    "status.ai_failed": "AI 连通性失败。{message}",
    "status.refreshing_sync_logs": "正在刷新同步日志...",
    "status.sync_logs_refreshed": "同步日志已刷新。",
    "status.refreshing_audit_logs": "正在刷新审计日志...",
    "status.audit_logs_refreshed": "审计日志已刷新。",
    "status.initialization_failed": "初始化失败：{detail}",
    "status.error": "{detail}",
    "error.window_days": "window_days 必须 >= 1",
    "error.interval_seconds": "interval_seconds 必须 >= 30",
    "error.timeout_seconds": "timeout_seconds 必须 >= 1",
    "error.load_config_failed": "加载配置失败",
    "error.load_calendars_failed": "加载日历失败",
    "error.load_sync_logs_failed": "加载同步日志失败",
    "error.load_audit_logs_failed": "加载审计日志失败",
    "error.save_failed": "保存失败",
    "error.sync_trigger_failed": "触发同步失败",
    "error.refresh_calendars_failed": "刷新日历失败",
    "error.ai_test_failed": "AI 连通性测试失败",
    "error.refresh_sync_logs_failed": "刷新同步日志失败",
    "error.refresh_audit_logs_failed": "刷新审计日志失败",
    "empty.calendars": "暂无日历数据。",
    "empty.sync_logs": "暂无同步日志。",
    "empty.audit_logs": "暂无审计日志。",
    "tag.stage": "stage",
    "tag.user_layer": "用户层",
    "tag.duplicate_user": "重复用户层",
    "tag.duplicate_staging": "重复stage",
    "common.custom": "自定义"
  }
};

let languagePref = "auto";
let currentLang = "en";
let latestCalendars = [];
let latestSyncRuns = [];
let latestAuditEvents = [];

const joinList = (items) => (items || []).join(", ");
const splitByComma = (text) =>
  (text || "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);

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
  const langPack = I18N[currentLang] || I18N.en;
  const fallback = I18N.en[key] || key;
  return template(langPack[key] || fallback, vars);
};

const setStatus = (type, key, vars = {}) => {
  statusEl.className = `status ${type}`;
  statusEl.dataset.i18nStatusKey = key;
  statusEl.dataset.i18nStatusVars = JSON.stringify(vars || {});
  statusEl.textContent = t(key, vars);
};

const retranslateStatus = () => {
  const key = statusEl.dataset.i18nStatusKey;
  if (!key) return;
  let vars = {};
  try {
    vars = JSON.parse(statusEl.dataset.i18nStatusVars || "{}");
  } catch (_err) {
    vars = {};
  }
  statusEl.textContent = t(key, vars);
};

const setActiveTab = (panel) => {
  panelEls.forEach((el) => {
    el.style.display = el.getAttribute("data-panel") === panel ? "" : "none";
  });
  [tabConfigBtn, tabCalendarsBtn, tabLogsBtn].forEach((btn) => btn.classList.remove("active"));
  if (panel === "config") tabConfigBtn.classList.add("active");
  if (panel === "calendars") tabCalendarsBtn.classList.add("active");
  if (panel === "logs") tabLogsBtn.classList.add("active");
};

const applyLanguage = (pref) => {
  languagePref = pref;
  currentLang = resolveLanguage(pref);
  document.documentElement.lang = currentLang === "zh" ? "zh-CN" : "en";

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    el.textContent = t(key);
  });

  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    el.setAttribute("placeholder", t(key));
  });

  if (langSelect) {
    const autoOpt = langSelect.querySelector("option[value='auto']");
    const enOpt = langSelect.querySelector("option[value='en']");
    const zhOpt = langSelect.querySelector("option[value='zh']");
    if (autoOpt) autoOpt.textContent = t("lang.auto");
    if (enOpt) enOpt.textContent = "English";
    if (zhOpt) zhOpt.textContent = "中文";
  }

  document.title = t("page.title");
  renderCalendars(latestCalendars);
  renderSyncLogs(latestSyncRuns);
  renderAuditLogs(latestAuditEvents);
  retranslateStatus();
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
  if (langSelect) {
    langSelect.value = pref;
    langSelect.addEventListener("change", () => {
      const next = ["auto", "en", "zh"].includes(langSelect.value) ? langSelect.value : "auto";
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

const bindConfig = (cfg) => {
  document.getElementById("caldav-base-url").value = cfg.caldav?.base_url || "";
  document.getElementById("caldav-username").value = cfg.caldav?.username || "";
  document.getElementById("caldav-password").value = "";

  document.getElementById("ai-base-url").value = cfg.ai?.base_url || "";
  document.getElementById("ai-api-key").value = "";
  document.getElementById("ai-model").value = cfg.ai?.model || "";
  document.getElementById("ai-timeout-seconds").value = cfg.ai?.timeout_seconds ?? 90;
  document.getElementById("ai-system-prompt").value = cfg.ai?.system_prompt || "";

  document.getElementById("sync-window-days").value = cfg.sync?.window_days ?? 7;
  document.getElementById("sync-interval-seconds").value = cfg.sync?.interval_seconds ?? 300;
  const timezoneEl = document.getElementById("sync-timezone");
  const tzValue = cfg.sync?.timezone || "UTC";
  if (![...timezoneEl.options].some((opt) => opt.value === tzValue)) {
    const customOption = document.createElement("option");
    customOption.value = tzValue;
    customOption.textContent = `${tzValue} (${t("common.custom")})`;
    timezoneEl.appendChild(customOption);
  }
  timezoneEl.value = tzValue;

  document.getElementById("rules-immutable-keywords").value = joinList(
    cfg.calendar_rules?.immutable_keywords || []
  );
  document.getElementById("rules-immutable-calendar-ids").value = (
    cfg.calendar_rules?.immutable_calendar_ids || []
  ).join("\n");
  document.getElementById("rules-staging-calendar-id").value =
    cfg.calendar_rules?.staging_calendar_id || "";
  document.getElementById("rules-staging-calendar-name").value =
    cfg.calendar_rules?.staging_calendar_name || "";
  document.getElementById("rules-user-calendar-id").value =
    cfg.calendar_rules?.user_calendar_id || "";
  document.getElementById("rules-user-calendar-name").value =
    cfg.calendar_rules?.user_calendar_name || "";

  document.getElementById("task-locked").checked = !!cfg.task_defaults?.locked;
  document.getElementById("task-mandatory").checked = !!cfg.task_defaults?.mandatory;
  document.getElementById("task-editable-fields").value = joinList(
    cfg.task_defaults?.editable_fields || []
  );
};

const syncImmutableIdsTextarea = () => {
  const ids = [];
  const rows = calendarBody.querySelectorAll("tr[data-calendar-id]");
  rows.forEach((row) => {
    const immutableCheckbox = row.querySelector("input[data-role='immutable']");
    if (immutableCheckbox?.checked) {
      ids.push(row.dataset.calendarId);
    }
  });
  document.getElementById("rules-immutable-calendar-ids").value = ids.join("\n");
};

const renderCalendars = (calendars) => {
  latestCalendars = calendars || [];
  calendarBody.innerHTML = "";

  if (!latestCalendars.length) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan='4'>${t("empty.calendars")}</td>`;
    calendarBody.appendChild(row);
    syncImmutableIdsTextarea();
    return;
  }

  latestCalendars.forEach((cal) => {
    const row = document.createElement("tr");
    row.dataset.calendarId = cal.calendar_id;

    const immutableChecked = !!cal.immutable_selected;
    const lockedChecked = !!cal.default_locked;
    const mandatoryChecked = !!cal.default_mandatory;
    const tags = [];
    if (cal.is_staging) tags.push(t("tag.stage"));
    if (cal.is_user) tags.push(t("tag.user_layer"));
    if (cal.managed_duplicate && cal.managed_duplicate_role === "user") tags.push(t("tag.duplicate_user"));
    if (cal.managed_duplicate && cal.managed_duplicate_role === "staging") tags.push(t("tag.duplicate_staging"));

    row.innerHTML = `
      <td>
        <div><strong>${cal.name || "(Unnamed)"}</strong></div>
        <div class="muted">${cal.calendar_id}${tags.length ? ` [${tags.join(", ")}]` : ""}</div>
      </td>
      <td><input type="checkbox" data-role="immutable" ${immutableChecked ? "checked" : ""}></td>
      <td><input type="checkbox" data-role="locked" ${lockedChecked ? "checked" : ""}></td>
      <td><input type="checkbox" data-role="mandatory" ${mandatoryChecked ? "checked" : ""}></td>
    `;

    const immutableInput = row.querySelector("input[data-role='immutable']");
    immutableInput?.addEventListener("change", () => syncImmutableIdsTextarea());

    calendarBody.appendChild(row);
  });

  syncImmutableIdsTextarea();
};

const renderSyncLogs = (runs) => {
  latestSyncRuns = runs || [];
  syncLogsBody.innerHTML = "";
  if (!latestSyncRuns.length) {
    syncLogsBody.innerHTML = `<tr><td colspan='6'>${t("empty.sync_logs")}</td></tr>`;
    return;
  }
  latestSyncRuns.forEach((run) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${run.run_at || ""}</td>
      <td>${run.status || ""}</td>
      <td>${run.trigger || ""}</td>
      <td>${run.changes_applied ?? ""}</td>
      <td>${run.conflicts ?? ""}</td>
      <td>${run.message || ""}</td>
    `;
    syncLogsBody.appendChild(tr);
  });
};

const renderAuditLogs = (events) => {
  latestAuditEvents = events || [];
  auditLogsBody.innerHTML = "";
  if (!latestAuditEvents.length) {
    auditLogsBody.innerHTML = `<tr><td colspan='5'>${t("empty.audit_logs")}</td></tr>`;
    return;
  }
  latestAuditEvents.forEach((event) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${event.created_at || ""}</td>
      <td>${event.action || ""}</td>
      <td>${event.calendar_id || ""}</td>
      <td>${event.uid || ""}</td>
      <td><code>${JSON.stringify(event.details || {})}</code></td>
    `;
    auditLogsBody.appendChild(tr);
  });
};

const readCalendarBehavior = () => {
  const immutableCalendarIds = [];
  const perCalendarDefaults = {};

  const rows = calendarBody.querySelectorAll("tr[data-calendar-id]");
  rows.forEach((row) => {
    const calendarId = row.dataset.calendarId;
    if (!calendarId) return;

    const immutable = !!row.querySelector("input[data-role='immutable']")?.checked;
    const locked = !!row.querySelector("input[data-role='locked']")?.checked;
    const mandatory = !!row.querySelector("input[data-role='mandatory']")?.checked;

    if (immutable) immutableCalendarIds.push(calendarId);
    perCalendarDefaults[calendarId] = {
      mode: immutable ? "immutable" : "editable",
      locked,
      mandatory,
    };
  });

  return { immutableCalendarIds, perCalendarDefaults };
};

const readPayload = () => {
  const windowDays = Number(document.getElementById("sync-window-days").value || "0");
  const intervalSeconds = Number(document.getElementById("sync-interval-seconds").value || "0");
  const timeoutSeconds = Number(document.getElementById("ai-timeout-seconds").value || "0");
  if (windowDays < 1) throw new Error(t("error.window_days"));
  if (intervalSeconds < 30) throw new Error(t("error.interval_seconds"));
  if (timeoutSeconds < 1) throw new Error(t("error.timeout_seconds"));

  const { immutableCalendarIds, perCalendarDefaults } = readCalendarBehavior();

  return {
    caldav: {
      base_url: document.getElementById("caldav-base-url").value.trim(),
      username: document.getElementById("caldav-username").value.trim(),
      password: document.getElementById("caldav-password").value,
    },
    ai: {
      base_url: document.getElementById("ai-base-url").value.trim(),
      api_key: document.getElementById("ai-api-key").value,
      model: document.getElementById("ai-model").value.trim(),
      timeout_seconds: timeoutSeconds,
      system_prompt: document.getElementById("ai-system-prompt").value.trim(),
    },
    sync: {
      window_days: windowDays,
      interval_seconds: intervalSeconds,
      timezone: document.getElementById("sync-timezone").value.trim(),
    },
    calendar_rules: {
      immutable_keywords: splitByComma(document.getElementById("rules-immutable-keywords").value),
      immutable_calendar_ids: immutableCalendarIds,
      staging_calendar_id: document.getElementById("rules-staging-calendar-id").value.trim(),
      staging_calendar_name: document.getElementById("rules-staging-calendar-name").value.trim(),
      user_calendar_id: document.getElementById("rules-user-calendar-id").value.trim(),
      user_calendar_name: document.getElementById("rules-user-calendar-name").value.trim(),
      per_calendar_defaults: perCalendarDefaults,
    },
    task_defaults: {
      locked: document.getElementById("task-locked").checked,
      mandatory: document.getElementById("task-mandatory").checked,
      editable_fields: splitByComma(document.getElementById("task-editable-fields").value),
    },
  };
};

const withPending = (el, pending) => {
  if (!el) return;
  if (el.tagName === "BUTTON") {
    el.disabled = pending;
    return;
  }
  if (el.tagName === "A") {
    el.setAttribute("aria-disabled", pending ? "true" : "false");
  }
};

const loadConfig = async () => {
  setStatus("info", "status.loading_config");
  const res = await fetch("/api/config/raw");
  if (!res.ok) throw new Error(`${t("error.load_config_failed")}: ${res.status}`);
  const data = await res.json();
  bindConfig(data.config || {});
  setStatus("success", "status.config_loaded");
};

const loadCalendars = async () => {
  const res = await fetch("/api/calendars");
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`${t("error.load_calendars_failed")}: ${res.status} ${errorText}`);
  }
  const data = await res.json();
  renderCalendars(data.calendars || []);
};

const loadSyncLogs = async () => {
  const res = await fetch("/api/sync/status?limit=50");
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`${t("error.load_sync_logs_failed")}: ${res.status} ${errorText}`);
  }
  const data = await res.json();
  renderSyncLogs(data.runs || []);
};

const loadAuditLogs = async () => {
  const res = await fetch("/api/audit/events?limit=100");
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`${t("error.load_audit_logs_failed")}: ${res.status} ${errorText}`);
  }
  const data = await res.json();
  renderAuditLogs(data.events || []);
};

const saveConfig = async () => {
  withPending(saveBtn, true);
  try {
    const payload = readPayload();
    setStatus("info", "status.saving_config");
    const res = await fetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ payload }),
    });
    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`${t("error.save_failed")}: ${res.status} ${errorText}`);
    }
    await loadConfig();
    await loadCalendars();
    setStatus("success", "status.config_saved");
  } catch (err) {
    setStatus("error", "status.error", { detail: err.message || t("error.save_failed") });
  } finally {
    withPending(saveBtn, false);
  }
};

const runSync = async () => {
  withPending(syncBtn, true);
  try {
    setStatus("info", "status.triggering_sync");
    const res = await fetch("/api/sync/run", { method: "POST" });
    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`${t("error.sync_trigger_failed")}: ${res.status} ${errorText}`);
    }
    await loadCalendars();
    await loadSyncLogs();
    await loadAuditLogs();
    setStatus("success", "status.sync_triggered_refreshed");
  } catch (err) {
    setStatus("error", "status.error", { detail: err.message || t("error.sync_trigger_failed") });
  } finally {
    withPending(syncBtn, false);
  }
};

const refreshCalendars = async () => {
  withPending(refreshCalendarsBtn, true);
  try {
    setStatus("info", "status.refreshing_calendars");
    await loadCalendars();
    setStatus("success", "status.calendars_refreshed");
  } catch (err) {
    setStatus("error", "status.error", { detail: err.message || t("error.refresh_calendars_failed") });
  } finally {
    withPending(refreshCalendarsBtn, false);
  }
};

const testAiConnectivity = async () => {
  withPending(aiTestLink, true);
  try {
    setStatus("info", "status.testing_ai");
    const res = await fetch("/api/ai/test", { method: "POST" });
    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`${t("error.ai_test_failed")}: ${res.status} ${errorText}`);
    }
    const data = await res.json();
    const message = (data.message || "").trim();
    if (data.ok) {
      setStatus("success", "status.ai_ok", { message });
    } else {
      setStatus("error", "status.ai_failed", { message });
    }
  } catch (err) {
    setStatus("error", "status.error", { detail: err.message || t("error.ai_test_failed") });
  } finally {
    withPending(aiTestLink, false);
  }
};

const refreshSyncLogs = async () => {
  withPending(refreshSyncLogsBtn, true);
  try {
    setStatus("info", "status.refreshing_sync_logs");
    await loadSyncLogs();
    setStatus("success", "status.sync_logs_refreshed");
  } catch (err) {
    setStatus("error", "status.error", { detail: err.message || t("error.refresh_sync_logs_failed") });
  } finally {
    withPending(refreshSyncLogsBtn, false);
  }
};

const refreshAuditLogs = async () => {
  withPending(refreshAuditLogsBtn, true);
  try {
    setStatus("info", "status.refreshing_audit_logs");
    await loadAuditLogs();
    setStatus("success", "status.audit_logs_refreshed");
  } catch (err) {
    setStatus("error", "status.error", { detail: err.message || t("error.refresh_audit_logs_failed") });
  } finally {
    withPending(refreshAuditLogsBtn, false);
  }
};

saveBtn.addEventListener("click", saveConfig);
syncBtn.addEventListener("click", runSync);
refreshCalendarsBtn.addEventListener("click", refreshCalendars);
aiTestLink.addEventListener("click", (event) => {
  event.preventDefault();
  if (aiTestLink.getAttribute("aria-disabled") === "true") return;
  void testAiConnectivity();
});
refreshSyncLogsBtn.addEventListener("click", refreshSyncLogs);
refreshAuditLogsBtn.addEventListener("click", refreshAuditLogs);
tabConfigBtn.addEventListener("click", () => setActiveTab("config"));
tabCalendarsBtn.addEventListener("click", () => setActiveTab("calendars"));
tabLogsBtn.addEventListener("click", () => setActiveTab("logs"));

(async () => {
  try {
    initLanguage();
    setActiveTab("config");
    await loadConfig();
    await loadCalendars();
    await loadSyncLogs();
    await loadAuditLogs();
  } catch (err) {
    setStatus("error", "status.initialization_failed", { detail: err.message || "" });
  }
})();
