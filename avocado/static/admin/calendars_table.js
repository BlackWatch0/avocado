export const renderCalendars = ({ state, calendarBody, calendars, t, toDisplayValue, escapeHtml }) => {
  state.latestCalendars = calendars || [];
  calendarBody.innerHTML = "";

  if (!state.latestCalendars.length) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan='3'>${t("empty.calendars")}</td>`;
    calendarBody.appendChild(row);
    return;
  }

  state.latestCalendars.forEach((cal) => {
    const row = document.createElement("tr");
    row.dataset.calendarId = cal.calendar_id || "";
    const name = toDisplayValue(cal.name || "(Unnamed)");
    const calendarId = toDisplayValue(cal.calendar_id);
    const isManaged = !!(cal.is_stack || cal.is_user || cal.is_new);
    const tags = [];
    if (cal.is_stack) tags.push(t("tag.stack"));
    if (cal.is_user) tags.push(t("tag.user"));
    if (cal.is_new) tags.push(t("tag.new"));
    if (cal.managed_duplicate && cal.managed_duplicate_role === "user") tags.push(t("tag.duplicate_user"));
    if (cal.managed_duplicate && cal.managed_duplicate_role === "stack") tags.push(t("tag.duplicate_stack"));
    if (cal.managed_duplicate && cal.managed_duplicate_role === "new") tags.push(t("tag.duplicate_new"));
    const roleText = tags.length ? tags.join(", ") : "-";

    row.innerHTML = `
      <td>
        <div><strong>${escapeHtml(name)}</strong></div>
        <div class="muted" title="${escapeHtml(calendarId)}">${escapeHtml(calendarId)}</div>
      </td>
      <td>${escapeHtml(roleText)}</td>
      <td><input type="checkbox" data-role="locked-source" ${cal.source_locked ? "checked" : ""} ${isManaged ? "disabled" : ""}></td>
    `;

    calendarBody.appendChild(row);
  });
};

export const readLockedSourceCalendarIds = (calendarBody) => {
  const ids = [];
  const rows = calendarBody.querySelectorAll("tr[data-calendar-id]");
  rows.forEach((row) => {
    const calendarId = String(row.dataset.calendarId || "").trim();
    if (!calendarId) return;
    const checkbox = row.querySelector("input[data-role='locked-source']");
    if (checkbox?.checked) ids.push(calendarId);
  });
  return ids;
};
