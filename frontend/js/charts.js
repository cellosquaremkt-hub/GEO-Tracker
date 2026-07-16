// Position Tracking 라인 차트 — GET /trends 데이터를 SVG로 그린다.
// prototype/index.html의 renderChart() 로직을 기반으로 하되, sov가 null인 주(그 배치가 아직
// 없었던 주)는 점을 찍지 않고 선을 끊는다 — 0으로 잘못 표시하면 "노출이 0%였다"는 의미가 되어
// "그 주는 측정 자체가 없었다"는 사실과 달라진다(docs/metrics.md null 의미 참조).
import { escapeHtml, toNumber } from "./format.js";

const BASE_PALETTE = ["#0c8f7b", "#65b96e", "#d04f2f", "#2f6fed", "#d99a19", "#7a5fcd", "#5f6f7a"];

// 브랜드 수가 팔레트보다 많아지면(7개 초과) HSL 회전으로 자동 생성한다 — 작업 지시 4번.
export function generatePalette(count) {
  const colors = [...BASE_PALETTE];
  let i = colors.length;
  while (colors.length < count) {
    const hue = (i * 47) % 360; // 47은 황금각에 가까운 값 — 이웃한 색끼리 너무 비슷해지지 않게 함
    colors.push(`hsl(${hue}, 62%, 46%)`);
    i += 1;
  }
  return colors.slice(0, count);
}

function trendPointsFor(points, width, height, padding, min, max) {
  const usableWidth = width - padding.left - padding.right;
  const usableHeight = height - padding.top - padding.bottom;
  const denom = Math.max(1, points.length - 1);
  return points.map((point, index) => {
    const value = toNumber(point.sov);
    if (value === null) return { x: null, y: null, value: null, week: point.week };
    const x = padding.left + (index * usableWidth) / denom;
    const y = padding.top + ((max - value) * usableHeight) / (max - min || 1);
    return { x, y, value, week: point.week };
  });
}

// null로 끊긴 지점을 기준으로 연속 구간(segment)만 path로 그린다.
function segmentsFromPoints(points) {
  const segments = [];
  let current = [];
  for (const point of points) {
    if (point.value === null) {
      if (current.length) segments.push(current);
      current = [];
    } else {
      current.push(point);
    }
  }
  if (current.length) segments.push(current);
  return segments;
}

function pathFromPoints(points) {
  return points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
}

export function renderTrendChart(els, trendsData) {
  const { weeks, series } = trendsData;
  const width = 760;
  const height = 210;
  const padding = { top: 18, right: 18, bottom: 24, left: 32 };

  if (!series.length || !weeks.length) {
    els.trendGraph.innerHTML = "";
    els.chartLabels.innerHTML = "";
    els.trendLegend.innerHTML = "";
    return;
  }

  const allValues = series.flatMap((s) => s.points.map((p) => toNumber(p.sov)).filter((v) => v !== null));
  const max = Math.max(10, ...(allValues.length ? allValues : [10])) * 1.15;
  const min = 0;

  const palette = generatePalette(series.length);
  const gridLines = 4;
  const grid = Array.from({ length: gridLines }, (_, i) => {
    const value = (max / (gridLines - 1)) * i;
    const y = padding.top + ((max - value) * (height - padding.top - padding.bottom)) / (max - min || 1);
    return `<line x1="${padding.left}" x2="${width - padding.right}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="#e7ebf0" stroke-width="1" />`;
  }).join("");

  const lines = series
    .map((brand, brandIndex) => {
      const points = trendPointsFor(brand.points, width, height, padding, min, max);
      const color = palette[brandIndex];
      const segments = segmentsFromPoints(points);
      const isPrimary = brandIndex < 2;

      const pathEls = segments
        .map(
          (segment) =>
            `<path class="trend-line ${isPrimary ? "" : "secondary"}" d="${pathFromPoints(segment)}" stroke="${color}" />`
        )
        .join("");

      const pointNodes = points
        .filter((p) => p.value !== null)
        .map(
          (p) => `
        <circle class="trend-point" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${isPrimary ? 4.2 : 3.4}" fill="${color}">
          <title>${escapeHtml(brand.brand_name)} · ${p.week} · ${p.value.toFixed(1)}%</title>
        </circle>
      `
        )
        .join("");

      const lastPoint = [...points].reverse().find((p) => p.value !== null);
      const label =
        isPrimary && lastPoint
          ? `<text class="trend-value" x="${Math.min(width - padding.right - 38, lastPoint.x + 7).toFixed(1)}" y="${(lastPoint.y + 3).toFixed(1)}">${lastPoint.value.toFixed(1)}%</text>`
          : "";

      return `${pathEls}${pointNodes}${label}`;
    })
    .join("");

  els.trendGraph.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="브랜드별 주차 SOV 추이">
      ${grid}
      ${lines}
    </svg>
  `;
  els.chartLabels.innerHTML = weeks.map((week) => `<span>${week}</span>`).join("");
  els.trendLegend.innerHTML = series
    .map(
      (brand, index) =>
        `<span><i class="key" style="background:${palette[index]}"></i>${escapeHtml(brand.brand_name)}</span>`
    )
    .join("");
}
