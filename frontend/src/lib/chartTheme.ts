/**
 * Единая тема для recharts (P3.12 из UI_UX_AUDIT.md, DESIGN_SYSTEM.md §8).
 *
 * Все цвета через CSS-vars → автоматом подхватываются при смене палитры.
 * 8-цветная chart-палитра — из DESIGN_SYSTEM §3.4 (матовый регистр,
 * семантическая привязка: revenue-emerald, ad-violet, errors-red и т.д.).
 *
 * Использование:
 *   import { chartTheme, GRID_PROPS, AXIS_PROPS, TOOLTIP_STYLE, CHART_COLORS } from "@/lib/chartTheme";
 *   <CartesianGrid {...GRID_PROPS} />
 *   <XAxis {...AXIS_PROPS} dataKey="date" />
 *   <Tooltip contentStyle={TOOLTIP_STYLE} />
 *   <Line stroke={CHART_COLORS[0]} />  // или chartTheme.primary
 */
function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "";
}

export const chartTheme = {
  get primary() {
    return cssVar("--accent") || "#8b6eff";
  },
  get primarySoft() {
    return "rgba(139, 110, 255, 0.2)";
  },
  get positive() {
    return cssVar("--success") || "#34d399";
  },
  get negative() {
    return cssVar("--danger") || "#f87171";
  },
  get warn() {
    return cssVar("--warn") || "#fbbf24";
  },
  get grid() {
    return cssVar("--border") || "#252a36";
  },
  get axis() {
    return cssVar("--muted") || "#8b93a3";
  },
  get bg() {
    return cssVar("--bg") || "#0a0c10";
  },
  get surface() {
    return cssVar("--surface") || "#11141b";
  },
  get tooltipStyle() {
    return {
      background: cssVar("--surface-2") || "#171b24",
      border: `1px solid ${cssVar("--border") || "#252a36"}`,
      borderRadius: "6px",
      fontSize: "12px",
      color: cssVar("--fg") || "#e8eaef",
    } as const;
  },
  get fontFamily() {
    return '"Inter Variable", "Inter", system-ui, sans-serif';
  },
};

/**
 * 8-цветная палитра графиков (DESIGN_SYSTEM §3.4).
 * Семантическая привязка:
 *   [0] revenue / положительная серия — emerald-400
 *   [1] orders / count — amber-500
 *   [2] ad cost / маркетинг — violet-400
 *   [3] profit / cyan серия — cyan-400
 *   [4] commission / WB удержания — red-400
 *   [5] logistics — orange-400
 *   [6] storage — amber-400
 *   [7] OPEX / прочее — slate-500
 */
export const CHART_COLORS = [
  "#34d399", // revenue (emerald-400)
  "#f59e0b", // orders (amber-500)
  "#a78bfa", // ad cost (violet-400)
  "#22d3ee", // profit (cyan-400)
  "#f87171", // commission (red-400)
  "#fb923c", // logistics (orange-400)
  "#fbbf24", // storage (amber-400)
  "#64748b", // OPEX (slate-500)
] as const;

/**
 * Sparkline default (нейтральная одиночная линия) — blue-400.
 */
export const SPARKLINE_COLOR = "#60a5fa";

/**
 * Стандартные props для <CartesianGrid />.
 * vertical={false} — горизонтальные линии достаточны для bar/line чартов.
 */
export const GRID_PROPS = {
  get stroke() {
    return chartTheme.grid;
  },
  strokeDasharray: "3 3",
  vertical: false,
} as const;

/**
 * Стандартные props для <XAxis /> / <YAxis />.
 * axisLine={false} + tickLine={false} — minimalist стиль DESIGN_SYSTEM §8.
 */
export const AXIS_PROPS = {
  get stroke() {
    return chartTheme.axis;
  },
  get tick() {
    return { fontSize: 11, fill: chartTheme.axis };
  },
  axisLine: false,
  tickLine: false,
} as const;

/**
 * Стандартный стиль для <Tooltip contentStyle={...} />.
 * Используется напрямую как `contentStyle`.
 */
export const TOOLTIP_STYLE = chartTheme.tooltipStyle;

/**
 * Стандартный wrapperStyle для <Legend />.
 */
export const LEGEND_STYLE = {
  get color() {
    return chartTheme.axis;
  },
  fontSize: 12,
} as const;
