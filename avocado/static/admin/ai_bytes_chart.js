export const renderAiBytesChart = ({ canvas, records, t, formatShortTime }) => {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const ratio = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth || 900;
  const cssHeight = canvas.clientHeight || 260;
  canvas.width = Math.max(1, Math.floor(cssWidth * ratio));
  canvas.height = Math.max(1, Math.floor(cssHeight * ratio));

  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, cssWidth, cssHeight);

  const points = (records || [])
    .map((item) => {
      if (Object.prototype.hasOwnProperty.call(item || {}, "request_tokens")) {
        return {
          time: item.created_at || "",
          tokens: Number(item.request_tokens || 0),
          flexUsed: !!item.flex_used,
        };
      }
      return {
        time: item?.created_at || "",
        tokens: Number(item?.details?.total_tokens || 0),
        flexUsed: String(item?.details?.service_tier || "").toLowerCase() === "flex",
      };
    })
    .filter((item) => Number.isFinite(item.tokens) && item.tokens >= 0)
    .sort((a, b) => (a.time < b.time ? -1 : 1))
    .slice(-120);

  const padLeft = 56;
  const padRight = 20;
  const padTop = 18;
  const padBottom = 34;
  const plotW = Math.max(10, cssWidth - padLeft - padRight);
  const plotH = Math.max(10, cssHeight - padTop - padBottom);

  ctx.strokeStyle = "#cbd5e1";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padLeft, padTop);
  ctx.lineTo(padLeft, cssHeight - padBottom);
  ctx.lineTo(cssWidth - padRight, cssHeight - padBottom);
  ctx.stroke();

  if (!points.length) {
    ctx.fillStyle = "#64748b";
    ctx.font = "13px Segoe UI";
    ctx.fillText(t("chart.no_data"), padLeft + 10, padTop + 24);
    return;
  }

  const maxTokens = Math.max(...points.map((p) => p.tokens));
  const yMax = maxTokens <= 1 ? 1 : Math.ceil(maxTokens * 1.1);
  const xStep = points.length === 1 ? 0 : plotW / (points.length - 1);
  const yBase = cssHeight - padBottom;
  const coords = points.map((p, idx) => ({
    x: padLeft + idx * xStep,
    y: padTop + plotH - (p.tokens / yMax) * plotH,
  }));

  const successFlexIndexes = points
    .map((p, idx) => (p.flexUsed && p.tokens > 0 ? idx : -1))
    .filter((idx) => idx >= 0);
  const greenSegments = Array(Math.max(0, points.length - 1)).fill(false);
  const greenPointIndexes = new Set();
  const greenSpans = [];
  for (let i = 1; i < successFlexIndexes.length; i += 1) {
    const start = successFlexIndexes[i - 1];
    const end = successFlexIndexes[i];
    let onlyZeroInBetween = true;
    for (let k = start + 1; k < end; k += 1) {
      if ((points[k]?.tokens || 0) > 0) {
        onlyZeroInBetween = false;
        break;
      }
    }
    if (!onlyZeroInBetween) continue;
    for (let seg = start + 1; seg <= end; seg += 1) {
      greenSegments[seg - 1] = true;
    }
    for (let idx = start; idx <= end; idx += 1) {
      greenPointIndexes.add(idx);
    }
    greenSpans.push([start, end]);
  }

  if (successFlexIndexes.length > 0) {
    const lastFlex = successFlexIndexes[successFlexIndexes.length - 1];
    let trailingAllZero = true;
    for (let k = lastFlex + 1; k < points.length; k += 1) {
      if ((points[k]?.tokens || 0) > 0) {
        trailingAllZero = false;
        break;
      }
    }
    if (trailingAllZero && lastFlex < points.length - 1) {
      for (let seg = lastFlex + 1; seg < points.length; seg += 1) {
        greenSegments[seg - 1] = true;
      }
      for (let idx = lastFlex; idx < points.length; idx += 1) {
        greenPointIndexes.add(idx);
      }
      greenSpans.push([lastFlex, points.length - 1]);
    }
  }

  ctx.strokeStyle = "#93c5fd";
  ctx.lineWidth = 1;
  for (let i = 1; i <= 4; i += 1) {
    const y = padTop + (plotH * i) / 4;
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(cssWidth - padRight, y);
    ctx.stroke();
  }

  if (points.length === 1) {
    const x = coords[0].x;
    const y = coords[0].y;
    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 0.001, y);
    ctx.stroke();
  } else {
    greenSpans.forEach(([start, end]) => {
      if (end <= start) return;
      ctx.fillStyle = "rgba(22, 163, 74, 0.24)";
      ctx.beginPath();
      ctx.moveTo(coords[start].x, yBase);
      for (let idx = start; idx <= end; idx += 1) {
        ctx.lineTo(coords[idx].x, coords[idx].y);
      }
      ctx.lineTo(coords[end].x, yBase);
      ctx.closePath();
      ctx.fill();
    });

    for (let i = 1; i < points.length; i += 1) {
      const x1 = coords[i - 1].x;
      const y1 = coords[i - 1].y;
      const x2 = coords[i].x;
      const y2 = coords[i].y;
      ctx.strokeStyle = greenSegments[i - 1] ? "#16a34a" : "#2563eb";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
  }

  points.forEach((p, idx) => {
    const x = coords[idx].x;
    const y = coords[idx].y;
    const pointInFlexSpan = greenPointIndexes.has(idx);
    const successFlex = !!p.flexUsed && p.tokens > 0;
    ctx.fillStyle = successFlex || pointInFlexSpan ? "#16a34a" : "#1d4ed8";
    ctx.beginPath();
    ctx.arc(x, y, 2.4, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.fillStyle = "#334155";
  ctx.font = "11px Segoe UI";
  ctx.fillText("0", 20, cssHeight - padBottom + 4);
  ctx.fillText(`${yMax} ${t("chart.tokens_unit")}`, 8, padTop + 4);
  ctx.fillText(formatShortTime(points[0].time), padLeft, cssHeight - 10);
  ctx.fillText(formatShortTime(points[points.length - 1].time), cssWidth - padRight - 86, cssHeight - 10);
};
