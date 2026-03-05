import { formatEventRange, formatShortTime } from "./utils.js";

export const hideAllKebabMenus = () => {
  document.querySelectorAll(".kebab-menu.show").forEach((menu) => menu.classList.remove("show"));
};

export const renderAiChanges = ({
  state,
  aiChangesList,
  changes,
  groups,
  t,
  escapeHtml,
  shortText,
  onUndo,
  onRevise,
  onError,
}) => {
  const normalizedGroups = Array.isArray(groups) ? groups : [];
  state.latestAiChanges = changes || [];
  if (!aiChangesList) return;
  aiChangesList.innerHTML = "";
  if (!state.latestAiChanges.length && !normalizedGroups.length) {
    aiChangesList.innerHTML = `<div class="muted">${t("empty.ai_changes")}</div>`;
    return;
  }

  const DEFAULT_EXPANDED_GROUPS = 2;
  const DEFAULT_EXPANDED_ITEMS_PER_GROUP = 2;

  const formatPatchValue = (value, field) => {
    const raw = String(value ?? "").trim();
    if (!raw || raw === "-") return "-";
    const normalizedField = String(field || "").toLowerCase();
    if (normalizedField === "start" || normalizedField === "end" || normalizedField === "time_range") {
      return formatShortTime(raw);
    }
    if (raw.includes("T") && !Number.isNaN(new Date(raw).getTime())) {
      return formatShortTime(raw);
    }
    return shortText(raw, 80);
  };

  const renderItem = (item, { expanded = false } = {}) => {
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
                formatPatchValue(line.before || "", line.field || "")
              )} -> ${escapeHtml(formatPatchValue(line.after || "", line.field || ""))}</div>`
          )
          .join("")
      : `<div class="ai-change-patch-line">-</div>`;
    const isCreate = String(item.item_type || "") === "create";
    const typeBadge = isCreate
      ? `<span class="ai-change-type-badge ai-change-type-create">${escapeHtml(t("ai.type.create"))}</span>`
      : `<span class="ai-change-type-badge ai-change-type-update">${escapeHtml(t("ai.type.update"))}</span>`;

    const wrapper = document.createElement("details");
    wrapper.className = `ai-change-item ai-change-item-details ${isCreate ? "ai-change-item-create" : "ai-change-item-update"}`;
    if (expanded) wrapper.open = true;
    const menuHtml =
      item.can_undo || item.can_revise
        ? `
        <div class="kebab-wrap">
          <button class="kebab-btn" type="button" aria-label="menu">...</button>
          <div class="kebab-menu">
            ${item.can_undo ? `<button type="button" data-action="undo">${escapeHtml(t("ai.menu.undo"))}</button>` : ""}
            ${item.can_revise ? `<button type="button" data-action="revise">${escapeHtml(t("ai.menu.revise"))}</button>` : ""}
          </div>
        </div>
      `
        : "";
    wrapper.innerHTML = `
      <summary class="ai-change-item-summary">
        <span class="ai-change-item-summary-main">${typeBadge}${escapeHtml(item.title || "(Untitled)")}</span>
        <span class="ai-change-item-summary-time">${escapeHtml(formatEventRange(item.start, item.end, t("ai.legacy_time")))}</span>
      </summary>
      <div class="ai-change-item-content">
        <div class="ai-change-head">
          <div>
            <div class="ai-change-meta">${escapeHtml(t("ai.identity_prefix"))}${escapeHtml(
              `${item.calendar_id || "-"} / ${item.uid || "-"}`
            )}</div>
            <div class="ai-change-meta">${escapeHtml(item.created_at || "")}</div>
          </div>
          ${menuHtml}
        </div>
        <p class="ai-change-reason">${escapeHtml(t("ai.reason_prefix"))}${escapeHtml(item.reason || "-")}</p>
        <div class="ai-change-patch">${patchHtml}</div>
      </div>
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
    return wrapper;
  };

  if (normalizedGroups.length) {
    normalizedGroups.forEach((group, groupIndex) => {
      const box = document.createElement("details");
      box.className = "ai-change-group";
      if (groupIndex < DEFAULT_EXPANDED_GROUPS) box.open = true;
      const groupItems = Array.isArray(group.items) ? group.items : [];
      const updatedCount = Number(group.updated_count || 0);
      const createdCount = Number(group.created_count || 0);
      const tierText = String(group.service_tier || "").trim();
      const modelText = String(group.model || "").trim();
      box.innerHTML = `
        <summary class="ai-change-group-head ai-change-group-summary">
          <div>
            <p class="ai-change-group-title">${escapeHtml(t("ai.group.title"))} #${escapeHtml(String(group.run_id || "-"))}</p>
            <div class="ai-change-group-counts">
              <span class="ai-change-group-count ai-change-group-count-update">${escapeHtml(t("ai.group.updated_prefix"))}${escapeHtml(String(updatedCount))}${escapeHtml(t("ai.group.items_suffix"))}</span>
              <span class="ai-change-group-count ai-change-group-count-create">${escapeHtml(t("ai.group.created_prefix"))}${escapeHtml(String(createdCount))}${escapeHtml(t("ai.group.items_suffix"))}</span>
            </div>
            <div class="ai-change-group-meta">${escapeHtml(t("ai.group.model_prefix"))}${escapeHtml(modelText || "-")} | ${escapeHtml(t("ai.group.tier_prefix"))}${escapeHtml(tierText || "-")}</div>
            <div class="ai-change-group-meta">${escapeHtml(t("ai.group.requested_at_prefix"))}${escapeHtml(group.requested_at || "-")}</div>
          </div>
        </summary>
        <div class="ai-change-group-items"></div>
      `;
      const itemsWrap = box.querySelector(".ai-change-group-items");
      groupItems.forEach((item, itemIndex) => {
        const expanded = groupIndex < DEFAULT_EXPANDED_GROUPS && itemIndex < DEFAULT_EXPANDED_ITEMS_PER_GROUP;
        itemsWrap?.appendChild(renderItem(item, { expanded }));
      });
      aiChangesList.appendChild(box);
    });
    return;
  }

  state.latestAiChanges.forEach((item, index) => {
    aiChangesList.appendChild(renderItem(item, { expanded: index < DEFAULT_EXPANDED_ITEMS_PER_GROUP }));
  });
};
