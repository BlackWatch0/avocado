export const renderSyncLogs = ({ state, syncLogsBody, runs, t, toDisplayValue, escapeHtml, statusBadgeClass, onSelectRun }) => {
  state.latestSyncRuns = runs || [];
  syncLogsBody.innerHTML = "";
  if (!state.latestSyncRuns.length) {
    syncLogsBody.innerHTML = `<tr><td colspan='7'>${t("empty.sync_logs")}</td></tr>`;
    return;
  }
  state.latestSyncRuns.forEach((run) => {
    const runId = Number(run.id || 0);
    const runAt = toDisplayValue(run.run_at);
    const status = toDisplayValue(run.status);
    const trigger = toDisplayValue(run.trigger);
    const changes = toDisplayValue(run.changes_applied);
    const conflicts = toDisplayValue(run.conflicts);
    const message = toDisplayValue(run.message);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="cell-compact"><button type="button" class="link-btn run-filter-btn" data-run-id="${runId}">#${runId}</button></td>
      <td class="cell-compact" title="${escapeHtml(runAt)}">${escapeHtml(runAt)}</td>
      <td><span class="status-badge ${statusBadgeClass(status)}">${escapeHtml(status)}</span></td>
      <td class="cell-compact" title="${escapeHtml(trigger)}">${escapeHtml(trigger)}</td>
      <td class="cell-compact">${escapeHtml(changes)}</td>
      <td class="cell-compact">${escapeHtml(conflicts)}</td>
      <td class="cell-compact cell-message" title="${escapeHtml(message)}">${escapeHtml(message)}</td>
    `;
    const filterBtn = tr.querySelector(".run-filter-btn");
    if (filterBtn) {
      filterBtn.addEventListener("click", async () => {
        await onSelectRun(runId > 0 ? runId : null);
      });
    }
    syncLogsBody.appendChild(tr);
  });
};
