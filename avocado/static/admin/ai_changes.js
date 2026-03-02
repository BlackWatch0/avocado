import { formatEventRange } from "./utils.js";

export const hideAllKebabMenus = () => {
  document.querySelectorAll(".kebab-menu.show").forEach((menu) => menu.classList.remove("show"));
};

export const renderAiChanges = ({
  state,
  aiChangesList,
  changes,
  t,
  escapeHtml,
  shortText,
  onUndo,
  onRevise,
  onError,
}) => {
  state.latestAiChanges = changes || [];
  if (!aiChangesList) return;
  aiChangesList.innerHTML = "";
  if (!state.latestAiChanges.length) {
    aiChangesList.innerHTML = `<div class="muted">${t("empty.ai_changes")}</div>`;
    return;
  }

  state.latestAiChanges.forEach((item) => {
    const patchLines = Array.isArray(item.patch) ? item.patch : [];
    const visiblePatchLines = patchLines.filter((line) => {
      const beforeText = String(line?.before || "");
      const afterText = String(line?.after || "");
      return beforeText !== afterText;
    });
    const patchHtml = visiblePatchLines.length
      ? visiblePatchLines
          .map(
            (line) =>
              `<div class="ai-change-patch-line"><strong>${escapeHtml(line.field || "")}</strong>: ${escapeHtml(
                shortText(line.before || "", 80)
              )} -> ${escapeHtml(shortText(line.after || "", 80))}</div>`
          )
          .join("")
      : `<div class="ai-change-patch-line">-</div>`;

    const wrapper = document.createElement("article");
    wrapper.className = "ai-change-item";
    wrapper.innerHTML = `
      <div class="ai-change-head">
        <div>
          <p class="ai-change-title">${escapeHtml(item.title || "(Untitled)")}</p>
          <div class="ai-change-meta">${escapeHtml(formatEventRange(item.start, item.end, t("ai.legacy_time")))}</div>
          <div class="ai-change-meta">${escapeHtml(t("ai.identity_prefix"))}${escapeHtml(
            `${item.calendar_id || "-"} / ${item.uid || "-"}`
          )}</div>
          <div class="ai-change-meta">${escapeHtml(item.created_at || "")}</div>
        </div>
        <div class="kebab-wrap">
          <button class="kebab-btn" type="button" aria-label="menu">...</button>
          <div class="kebab-menu">
            <button type="button" data-action="undo">${escapeHtml(t("ai.menu.undo"))}</button>
            <button type="button" data-action="revise">${escapeHtml(t("ai.menu.revise"))}</button>
          </div>
        </div>
      </div>
      <p class="ai-change-reason">${escapeHtml(t("ai.reason_prefix"))}${escapeHtml(item.reason || "-")}</p>
      <div class="ai-change-patch">${patchHtml}</div>
    `;
    const kebabBtn = wrapper.querySelector(".kebab-btn");
    const menu = wrapper.querySelector(".kebab-menu");
    kebabBtn?.addEventListener("click", (event) => {
      event.stopPropagation();
      const visible = menu?.classList.contains("show");
      hideAllKebabMenus();
      if (!visible) menu?.classList.add("show");
    });
    wrapper.querySelector("button[data-action='undo']")?.addEventListener("click", async () => {
      hideAllKebabMenus();
      try {
        await onUndo(item.audit_id);
      } catch (err) {
        onError(err);
      }
    });
    wrapper.querySelector("button[data-action='revise']")?.addEventListener("click", async () => {
      hideAllKebabMenus();
      const instruction = window.prompt(t("ai.revise_prompt"), "");
      if (instruction === null) return;
      const text = instruction.trim();
      if (!text) {
        onError(new Error(t("error.revise_instruction_required")));
        return;
      }
      try {
        await onRevise(item.audit_id, text);
      } catch (err) {
        onError(err);
      }
    });
    aiChangesList.appendChild(wrapper);
  });
};
