/**
 * Единая тема для recharts (P3.12 из UI_UX_AUDIT.md).
 *
 * Все цвета через CSS-vars → автоматом подхватываются при смене палитры.
 *
 * Использование:
 *   import { chartTheme } from "@/lib/chartTheme";
 *   <CartesianGrid stroke={chartTheme.grid} />
 *   <Line stroke={chartTheme.primary} />
 *   <Tooltip contentStyle={chartTheme.tooltipStyle} />
 */
function cssVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "";
}

export const chartTheme = {
  get primary() {
    return cssVar("--accent") || "#8b6eff";
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
