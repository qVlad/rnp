export const fmtRub = (v: number | null | undefined) =>
  v == null
    ? "—"
    : new Intl.NumberFormat("ru-RU", {
        maximumFractionDigits: 0,
      }).format(v) + " ₽";

export const fmtNum = (v: number | null | undefined) =>
  v == null ? "—" : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(v);

export const fmtPct = (v: number | string | null | undefined, digits = 1) => {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? `${n.toFixed(digits)}%` : "—";
};

export const fmtChange = (v: number | string | null | undefined) => {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
};

export const formatValue = (value: number, unit: string) => {
  if (unit === "₽") return fmtRub(value);
  if (unit === "%") return fmtPct(value);
  return fmtNum(value);
};

/** Arrow для дельты: ▲ при росте, ▼ при падении, '' при нуле/null. */
export const arrowForDelta = (v: number | null | undefined): string => {
  if (v == null || v === 0) return "";
  return v > 0 ? "▲" : "▼";
};

/**
 * Компактный формат для axis-labels recharts: "1.2M" / "500k" / "42".
 * Без валюты, без знака — суффикс M/k только если значение того стоит.
 */
export const fmtCompact = (v: number | null | undefined, digits = 1): string => {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(digits)}M`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(digits === 1 ? 0 : digits)}k`;
  return n.toFixed(0);
};

/**
 * Форматирование коэффициента / курса с фиксированным числом цифр после запятой.
 * Используется для FX-rates (ЦБ РФ), коэффициентов сезонности и т.п.
 */
export const fmtRatio = (
  v: number | string | null | undefined,
  digits = 4,
): string => {
  if (v == null) return "—";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n.toFixed(digits) : "—";
};

/** ISO timestamp → "DD.MM HH:MM" в локальном TZ браузера. */
export const fmtLocalDt = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mn = String(d.getMinutes()).padStart(2, "0");
  return `${dd}.${mm} ${hh}:${mn}`;
};

/** ISO timestamp → "HH:MM" в локальном TZ браузера. */
export const fmtLocalTime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  const hh = String(d.getHours()).padStart(2, "0");
  const mn = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mn}`;
};

