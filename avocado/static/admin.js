const statusEl = document.getElementById("status");
const saveBtn = document.getElementById("save-btn");
const syncBtn = document.getElementById("sync-btn");
const refreshCalendarsBtn = document.getElementById("refresh-calendars-btn");
const testAiBtn = document.getElementById("test-ai-btn");
const calendarBody = document.getElementById("calendar-behaviors-body");

const setStatus = (type, message) => {
  statusEl.className = `status ${type}`;
  statusEl.textContent = message;
};

const joinList = (items) => (items || []).join(", ");
const splitByComma = (text) =>
  (text || "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);

let latestCalendars = [];

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
    customOption.textContent = `${tzValue} (custom)`;
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
    row.innerHTML = "<td colspan='4'>No calendars loaded.</td>";
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

    row.innerHTML = `
      <td>
        <div><strong>${cal.name || "(Unnamed)"}</strong></div>
        <div class="muted">${cal.calendar_id}${cal.is_staging ? " (staging)" : ""}</div>
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
  if (windowDays < 1) throw new Error("window_days must be >= 1");
  if (intervalSeconds < 30) throw new Error("interval_seconds must be >= 30");
  if (timeoutSeconds < 1) throw new Error("timeout_seconds must be >= 1");

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
      per_calendar_defaults: perCalendarDefaults,
    },
    task_defaults: {
      locked: document.getElementById("task-locked").checked,
      mandatory: document.getElementById("task-mandatory").checked,
      editable_fields: splitByComma(document.getElementById("task-editable-fields").value),
    },
  };
};

const withPending = (btn, pending) => {
  btn.disabled = pending;
};

const loadConfig = async () => {
  setStatus("info", "Loading config...");
  const res = await fetch("/api/config/raw");
  if (!res.ok) throw new Error(`Failed to load config: ${res.status}`);
  const data = await res.json();
  bindConfig(data.config || {});
  setStatus("success", "Config loaded.");
};

const loadCalendars = async () => {
  const res = await fetch("/api/calendars");
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Failed to load calendars: ${res.status} ${errorText}`);
  }
  const data = await res.json();
  renderCalendars(data.calendars || []);
};

const saveConfig = async () => {
  withPending(saveBtn, true);
  try {
    const payload = readPayload();
    setStatus("info", "Saving config...");
    const res = await fetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ payload }),
    });
    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`Save failed: ${res.status} ${errorText}`);
    }
    await loadConfig();
    await loadCalendars();
    setStatus("success", "Config saved.");
  } catch (err) {
    setStatus("error", err.message || "Save failed");
  } finally {
    withPending(saveBtn, false);
  }
};

const runSync = async () => {
  withPending(syncBtn, true);
  try {
    setStatus("info", "Triggering sync...");
    const res = await fetch("/api/sync/run", { method: "POST" });
    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`Sync trigger failed: ${res.status} ${errorText}`);
    }
    await loadCalendars();
    setStatus("success", "Sync triggered and calendars refreshed.");
  } catch (err) {
    setStatus("error", err.message || "Sync trigger failed");
  } finally {
    withPending(syncBtn, false);
  }
};

const refreshCalendars = async () => {
  withPending(refreshCalendarsBtn, true);
  try {
    setStatus("info", "Refreshing calendars...");
    await loadCalendars();
    setStatus("success", "Calendars refreshed.");
  } catch (err) {
    setStatus("error", err.message || "Refresh calendars failed");
  } finally {
    withPending(refreshCalendarsBtn, false);
  }
};

const testAiConnectivity = async () => {
  withPending(testAiBtn, true);
  try {
    setStatus("info", "Testing AI connectivity...");
    const res = await fetch("/api/ai/test", { method: "POST" });
    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`AI test failed: ${res.status} ${errorText}`);
    }
    const data = await res.json();
    if (data.ok) {
      setStatus("success", `AI connectivity OK. ${data.message || ""}`.trim());
    } else {
      setStatus("error", `AI connectivity failed. ${data.message || ""}`.trim());
    }
  } catch (err) {
    setStatus("error", err.message || "AI connectivity test failed");
  } finally {
    withPending(testAiBtn, false);
  }
};

saveBtn.addEventListener("click", saveConfig);
syncBtn.addEventListener("click", runSync);
refreshCalendarsBtn.addEventListener("click", refreshCalendars);
testAiBtn.addEventListener("click", testAiConnectivity);

(async () => {
  try {
    await loadConfig();
    await loadCalendars();
  } catch (err) {
    setStatus("error", err.message || "Failed to initialize");
  }
})();
