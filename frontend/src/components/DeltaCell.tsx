/**
 * TASK-UI-017 — Условная окраска значений + ▲/▼ inline для таблиц.
 *
 * Унифицированный компонент для отображения дельты (WoW / план vs факт /
 * прошлый период) с цветной подсветкой и стрелкой направления.
 *
 * Использование:
 *   <DeltaCell value={5.2} />         → "▲ +5.2%" (зелёное, рост = хорошо)
 *   <DeltaCell value={-3.1} lowerIsBetter />  → "▼ -3.1%" (зелёное, падение = хорошо)
 *   <DeltaCell value={null} />        → "—" (muted)
 *
 * Семантика: LOWER_IS_BETTER метрики (DRR, returns, commission, logistics,
 * storage, penalty, deduction) — рост = красное, падение = зелёное.
 *
 * Альтернатива абсолютным значениям: пара props `before`/`after` для
 * автоматического расчёта delta_pct.
 */
import { arrowForDelta, fmtPct } from "@/lib/format";

interface Props {
  /** Готовая дельта в процентах (например WoW%). Или используй before/after для авто-расчёта. */
  value?: number | null | undefined;
  /** Альтернатива: пара значений, дельта считается автоматически. */
  before?: number | null;
  after?: number | null;
  /** Метрики где рост = плохо (DRR, returns, commission, etc). */
  lowerIsBetter?: boolean;
  /** Сколько знаков после запятой (default 1). */
  digits?: number;
  /** Показать значок ▲/▼ перед числом (default true). */
  showArrow?: boolean;
  /** Дополнительные CSS-классы. */
  className?: string;
}

function computeDelta(before: number | null, after: number | null): number | null {
  if (before == null || after == null || !Number.isFinite(before) || !Number.isFinite(after)) {
    return null;
  }
  if (before === 0) return null;
  return ((after - before) / Math.abs(before)) * 100;
}

export default function DeltaCell({
  value,
  before,
  after,
  lowerIsBetter = false,
  digits = 1,
  showArrow = true,
  className = "",
}: Props) {
  let delta: number | null | undefined = value;
  if (delta == null && before !== undefined && after !== undefined) {
    delta = computeDelta(before ?? null, after ?? null);
  }

  if (delta == null || !Number.isFinite(delta)) {
    return <span className={`text-muted font-mono ${className}`}>—</span>;
  }

  const isUp = delta > 0;
  const isZero = delta === 0;
  // Хорошо когда: (рост и lowerIsBetter=false) или (падение и lowerIsBetter=true)
  const isGood = isZero ? false : (isUp ? !lowerIsBetter : lowerIsBetter);
  const cls = isZero
    ? "text-muted"
    : isGood
      ? "text-success"
      : "text-danger";
  const arrow = showArrow ? arrowForDelta(delta) : "";
  const sign = delta >= 0 ? "+" : "";

  return (
    <span className={`font-mono ${cls} ${className}`}>
      {arrow && <span className="mr-0.5">{arrow}</span>}
      {sign}
      {fmtPct(delta, digits).replace("%", "")}%
    </span>
  );
}
