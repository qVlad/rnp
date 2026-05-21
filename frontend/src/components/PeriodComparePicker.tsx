/**
 * PeriodComparePicker — два DateRangePicker'а + кнопка «Сравнить».
 *
 * TASK-LEAD-029: гибкое сравнение 2 произвольных периодов на Dashboard.
 * Изолированный компонент — НЕ наследует ничего у DateRangePicker, просто его
 * использует. Других страниц не ломает.
 */
import { useState } from "react";
import { DateRangePicker, type DateRange } from "@/components/DateRangePicker";

export type ComparePeriods = { a: DateRange; b: DateRange };

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

export default function PeriodComparePicker({
  initialA,
  initialB,
  onCompare,
}: {
  initialA?: DateRange;
  initialB?: DateRange;
  onCompare: (periods: ComparePeriods) => void;
}) {
  const [a, setA] = useState<DateRange>(
    initialA ?? { from: daysAgo(6), to: today() },
  );
  const [b, setB] = useState<DateRange>(
    initialB ?? { from: daysAgo(13), to: daysAgo(7) },
  );

  const valid =
    a.from && a.to && b.from && b.to && a.from <= a.to && b.from <= b.to;

  return (
    <div className="flex items-center gap-2 flex-wrap text-xs">
      <span className="text-muted">A:</span>
      <DateRangePicker from={a.from} to={a.to} onChange={setA} />
      <span className="text-muted">vs B:</span>
      <DateRangePicker from={b.from} to={b.to} onChange={setB} />
      <button
        className="btn text-xs border-accent text-accent"
        disabled={!valid}
        onClick={() => valid && onCompare({ a, b })}
        title="Применить и пересчитать KPI с дельтами"
      >
        Сравнить
      </button>
    </div>
  );
}
