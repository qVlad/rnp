export const fmtRub = (v: number | null | undefined) =>
  v == null
    ? "—"
    : new Intl.NumberFormat("ru-RU", {
        maximumFractionDigits: 0,
      }).format(v) + " ₽";

export const fmtNum = (v: number | null | undefined) =>
  v == null ? "—" : new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(v);

export const fmtPct = (v: number | null | undefined, digits = 1) =>
  v == null ? "—" : `${v.toFixed(digits)}%`;

export const fmtChange = (v: number | null) => {
  if (v == null) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
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

