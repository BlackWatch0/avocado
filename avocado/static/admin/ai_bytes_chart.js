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
        };
      }
      return {
        time: item?.created_at || "",
        tokens: Number(item?.details?.total_tokens || 0),
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

  ctx.strokeStyle = "#93c5fd";
  ctx.lineWidth = 1;
  for (let i = 1; i <= 4; i += 1) {
    const y = padTop + (plotH * i) / 4;
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(cssWidth - padRight, y);
    ctx.stroke();
  }

  ctx.strokeStyle = "#2563eb";
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((p, idx) => {
    const x = padLeft + idx * xStep;
    const y = padTop + plotH - (p.tokens / yMax) * plotH;
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = "#1d4ed8";
  points.forEach((p, idx) => {
    const x = padLeft + idx * xStep;
    const y = padTop + plotH - (p.tokens / yMax) * plotH;
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
