export const bindConfig = ({ cfg, t, ensureSelectOption, joinList }) => {
  document.getElementById("caldav-base-url").value = cfg.caldav?.base_url || "";
  document.getElementById("caldav-username").value = cfg.caldav?.username || "";
  document.getElementById("caldav-password").value = "";

  document.getElementById("ai-enabled").checked = cfg.ai?.enabled !== false;
  document.getElementById("ai-base-url").value = cfg.ai?.base_url || "";
  document.getElementById("ai-api-key").value = "";
  const modelEl = document.getElementById("ai-model");
  const modelValue = cfg.ai?.model || "";
  if (modelValue) {
    ensureSelectOption(modelEl, modelValue, modelValue, true);
  } else {
    modelEl.value = "";
  }
  document.getElementById("ai-high-load-model").value = cfg.ai?.high_load_model || "";
  document.getElementById("ai-high-load-event-threshold").value =
    cfg.ai?.high_load_event_threshold ?? 0;
  const highLoadAutoEnabledEl = document.getElementById("ai-high-load-auto-enabled");
  if (highLoadAutoEnabledEl) {
    highLoadAutoEnabledEl.checked = !!cfg.ai?.high_load_auto_enabled;
  }
  document.getElementById("ai-high-load-use-flex").checked = !!cfg.ai?.high_load_use_flex;
  document.getElementById("ai-high-load-flex-fallback-auto").checked =
    cfg.ai?.high_load_flex_fallback_to_auto !== false;
  document.getElementById("ai-timeout-seconds").value = cfg.ai?.timeout_seconds ?? 90;
  document.getElementById("ai-system-prompt").value = cfg.ai?.system_prompt || "";

  document.getElementById("sync-window-days").value = cfg.sync?.window_days ?? 7;
  document.getElementById("sync-interval-seconds").value = cfg.sync?.interval_seconds ?? 300;
  document.getElementById("sync-freeze-hours").value = cfg.sync?.freeze_hours ?? 0;
  const timezoneSourceEl = document.getElementById("sync-timezone-source");
  const timezoneSourceValue = cfg.sync?.timezone_source === "manual" ? "manual" : "host";
  if (timezoneSourceEl) {
    timezoneSourceEl.value = timezoneSourceValue;
  }
  const timezoneEl = document.getElementById("sync-timezone");
  const tzValue = cfg.sync?.timezone || "UTC";
  if (![...timezoneEl.options].some((opt) => opt.value === tzValue)) {
    const customOption = document.createElement("option");
    customOption.value = tzValue;
    customOption.textContent = `${tzValue} (${t("common.custom")})`;
    timezoneEl.appendChild(customOption);
  }
  timezoneEl.value = tzValue;
  timezoneEl.disabled = timezoneSourceValue !== "manual";

  document.getElementById("rules-stack-calendar-id").value =
    cfg.calendar_rules?.stack_calendar_id || "";
  document.getElementById("rules-stack-calendar-name").value =
    cfg.calendar_rules?.stack_calendar_name || "";
  document.getElementById("rules-user-calendar-id").value =
    cfg.calendar_rules?.user_calendar_id || "";
  document.getElementById("rules-user-calendar-name").value =
    cfg.calendar_rules?.user_calendar_name || "";
  document.getElementById("rules-new-calendar-id").value =
    cfg.calendar_rules?.new_calendar_id || "";
  document.getElementById("rules-new-calendar-name").value =
    cfg.calendar_rules?.new_calendar_name || "";

  document.getElementById("task-editable-fields").value = joinList(
    cfg.task_defaults?.editable_fields || []
  );
};

export const readPayload = ({ t, splitByComma, readLockedSourceCalendarIds }) => {
  const windowDays = Number(document.getElementById("sync-window-days").value || "0");
  const intervalSeconds = Number(document.getElementById("sync-interval-seconds").value || "0");
  const freezeHours = Number(document.getElementById("sync-freeze-hours").value || "0");
  const timeoutSeconds = Number(document.getElementById("ai-timeout-seconds").value || "0");
  const highLoadEventThreshold = Number(
    document.getElementById("ai-high-load-event-threshold").value || "0"
  );
  if (windowDays < 1) throw new Error(t("error.window_days"));
  if (intervalSeconds < 30) throw new Error(t("error.interval_seconds"));
  if (freezeHours < 0) throw new Error(t("error.freeze_hours"));
  if (timeoutSeconds < 1) throw new Error(t("error.timeout_seconds"));
  if (highLoadEventThreshold < 0) throw new Error(t("error.high_load_event_threshold"));

  return {
    caldav: {
      base_url: document.getElementById("caldav-base-url").value.trim(),
      username: document.getElementById("caldav-username").value.trim(),
      password: document.getElementById("caldav-password").value,
    },
    ai: {
      enabled: document.getElementById("ai-enabled").checked,
      base_url: document.getElementById("ai-base-url").value.trim(),
      api_key: document.getElementById("ai-api-key").value,
      model: document.getElementById("ai-model").value.trim(),
      high_load_model: document.getElementById("ai-high-load-model").value.trim(),
      high_load_event_threshold: highLoadEventThreshold,
      high_load_auto_enabled: !!document.getElementById("ai-high-load-auto-enabled")?.checked,
      high_load_use_flex: document.getElementById("ai-high-load-use-flex").checked,
      high_load_flex_fallback_to_auto: document.getElementById("ai-high-load-flex-fallback-auto").checked,
      timeout_seconds: timeoutSeconds,
      system_prompt: document.getElementById("ai-system-prompt").value.trim(),
    },
    sync: {
      window_days: windowDays,
      interval_seconds: intervalSeconds,
      freeze_hours: freezeHours,
      timezone_source: document.getElementById("sync-timezone-source")?.value || "host",
      timezone: document.getElementById("sync-timezone").value.trim(),
    },
    calendar_rules: {
      stack_calendar_id: document.getElementById("rules-stack-calendar-id").value.trim(),
      stack_calendar_name: document.getElementById("rules-stack-calendar-name").value.trim(),
      user_calendar_id: document.getElementById("rules-user-calendar-id").value.trim(),
      user_calendar_name: document.getElementById("rules-user-calendar-name").value.trim(),
      new_calendar_id: document.getElementById("rules-new-calendar-id").value.trim(),
      new_calendar_name: document.getElementById("rules-new-calendar-name").value.trim(),
      locked_calendar_ids: readLockedSourceCalendarIds(),
    },
    task_defaults: {
      locked: false,
      editable_fields: splitByComma(document.getElementById("task-editable-fields").value),
    },
  };
};
