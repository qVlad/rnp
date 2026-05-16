import { formatValue } from "@/lib/format";

export interface CompositionSegment {
  key: string;
  label: string;
  value: number;
  color: string; // any CSS color, eg. "#34d399" or "var(--success)"
}

interface Props {
  /** Сегменты. Знак ИГНОРИРУЕТСЯ — composition bar показывает абсолютные
   * доли расходов/составляющих. Если нужно показать negatives — передавай
   * Math.abs() заранее. */
  segments: CompositionSegment[];
  /** Если задано — % считается к этому total. Иначе — к sum(|values|).
   * Используй когда часть compositions суммируется в другую метрику (eg.
   * COGS+TAX вместе из revenue_after_vat). */
  totalOverride?: number;
  /** Формат значений в подписях. По умолчанию rub. */
  unit?: string;
  className?: string;
  /** Сжатый режим: только полоска, без подписей-легенды. */
  compact?: boolean;
}

export default function CompositionBar({
  segments,
  totalOverride,
  unit = "rub",
  className = "",
  compact = false,
}: Props) {
  const usable = segments.filter((s) => s.value && !Number.isNaN(s.value));
  const absSum = usable.reduce((s, x) => s + Math.abs(x.value), 0);
  const base = totalOverride && totalOverride > 0 ? totalOverride : absSum;
  if (base === 0 || usable.length === 0) {
    return null;
  }

  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <div className="h-2 w-full rounded-full overflow-hidden bg-bg flex">
        {usable.map((s) => {
          const pct = (Math.abs(s.value) / base) * 100;
          return (
            <div
              key={s.key}
              style={{ width: `${pct}%`, background: s.color }}
              title={`${s.label}: ${formatValue(s.value, unit)} (${pct.toFixed(1)}%)`}
            />
          );
        })}
      </div>
      {!compact && (
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[10px] mt-0.5">
          {usable.map((s) => {
            const pct = (Math.abs(s.value) / base) * 100;
            return (
              <div
                key={s.key}
                className="flex items-center gap-1.5 min-w-0"
                title={`${s.label}: ${formatValue(s.value, unit)} (${pct.toFixed(1)}%)`}
              >
                <span
                  className="inline-block w-2 h-2 rounded-sm flex-shrink-0"
                  style={{ background: s.color }}
                />
                <span className="text-muted truncate flex-1">{s.label}</span>
                <span className="font-mono tabular-nums text-fg/80">
                  {pct.toFixed(0)}%
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
