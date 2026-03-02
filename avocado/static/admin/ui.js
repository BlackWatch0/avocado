export const setStatus = (state, statusEl, t, type, key, vars = {}) => {
  state.statusKey = key;
  state.statusVars = vars || {};
  statusEl.className = `status ${type}`;
  statusEl.textContent = t(key, vars);
};

export const retranslateStatus = (state, statusEl, t) => {
  if (!state.statusKey) return;
  statusEl.textContent = t(state.statusKey, state.statusVars || {});
};

export const setActiveTab = (dom, panel) => {
  dom.panelEls.forEach((el) => {
    el.style.display = el.getAttribute("data-panel") === panel ? "" : "none";
  });
  [dom.tabConfigBtn, dom.tabCalendarsBtn, dom.tabLogsBtn].forEach((btn) => btn.classList.remove("active"));
  if (panel === "config") dom.tabConfigBtn.classList.add("active");
  if (panel === "calendars") dom.tabCalendarsBtn.classList.add("active");
  if (panel === "logs") dom.tabLogsBtn.classList.add("active");
};

export const withPending = (el, pending) => {
  if (!el) return;
  if (el.tagName === "BUTTON") {
    el.disabled = pending;
    return;
  }
  if (el.tagName === "A") {
    el.setAttribute("aria-disabled", pending ? "true" : "false");
  }
};
