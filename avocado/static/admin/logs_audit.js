export const renderAuditLogs = ({ state, auditLogsBody, events, t, toDisplayValue, summarizeDetails, toPrettyJson, escapeHtml }) => {
  state.latestAuditEvents = events || [];
  auditLogsBody.innerHTML = "";
  if (!state.latestAuditEvents.length) {
    auditLogsBody.innerHTML = `<tr><td colspan='5'>${t("empty.audit_logs")}</td></tr>`;
    return;
  }
  state.latestAuditEvents.forEach((event) => {
    const createdAt = toDisplayValue(event.created_at);
    const action = toDisplayValue(event.action);
    const calendarId = toDisplayValue(event.calendar_id);
    const uid = toDisplayValue(event.uid);
    const summary = summarizeDetails(event.details) || t("details.empty");
    const prettyJson = toPrettyJson(event.details);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="cell-compact" title="${escapeHtml(createdAt)}">${escapeHtml(createdAt)}</td>
      <td class="cell-compact" title="${escapeHtml(action)}">${escapeHtml(action)}</td>
      <td class="cell-compact" title="${escapeHtml(calendarId)}">${escapeHtml(calendarId)}</td>
      <td class="cell-compact" title="${escapeHtml(uid)}">${escapeHtml(uid)}</td>
      <td>
        <details class="log-details">
          <summary title="${escapeHtml(summary)}">${escapeHtml(`${t("details.view")}: ${summary}`)}</summary>
          <pre>${escapeHtml(prettyJson)}</pre>
        </details>
      </td>
    `;
    auditLogsBody.appendChild(tr);
  });
};
