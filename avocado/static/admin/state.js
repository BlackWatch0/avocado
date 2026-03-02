export const LANG_PREF_KEY = "avocado_admin_lang_pref";
export const AI_BYTES_DAYS_KEY = "avocado_ai_bytes_days";
export const AI_BYTES_CACHE_KEY = "avocado_ai_bytes_cache";

export const state = {
  languagePref: "auto",
  currentLang: "en",
  latestCalendars: [],
  latestSyncRuns: [],
  latestAuditEvents: [],
  latestAiChanges: [],
  latestAiRequestMetrics: [],
  aiBytesAutoRefreshTimer: null,
  selectedAuditRunId: null,
  statusKey: "",
  statusVars: {},
};
