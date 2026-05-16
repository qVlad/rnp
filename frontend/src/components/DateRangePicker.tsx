import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/Icon";

export type DateRange = { from: string; to: string };

type Preset = { label: string; range: () => DateRange };

const DEFAULT_PRESETS: Preset[] = [
  { label: "Сегодня", range: () => ({ from: iso(today()), to: iso(today()) }) },
  {
    label: "7 дней",
    range: () => ({ from: iso(addDays(today(), -6)), to: iso(today()) }),
  },
  {
    label: "30 дней",
    range: () => ({ from: iso(addDays(today(), -29)), to: iso(today()) }),
  },
  {
    label: "С начала месяца",
    range: () => ({
      from: iso(monthStart(today())),
      to: iso(today()),
    }),
  },
  {
    label: "Прошлый месяц",
    range: () => {
      const t = today();
      const lm = new Date(t.getFullYear(), t.getMonth() - 1, 1);
      const end = new Date(t.getFullYear(), t.getMonth(), 0);
      return { from: iso(lm), to: iso(end) };
    },
  },
  {
    label: "С начала года",
    range: () => ({
      from: `${today().getFullYear()}-01-01`,
      to: iso(today()),
    }),
  },
];

const MONTHS_RU = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];
const DAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

export function DateRangePicker({
  from,
  to,
  onChange,
  presets,
  className,
  compact,
}: {
  from: string;
  to: string;
  onChange: (r: DateRange) => void;
  presets?: Preset[];
  className?: string;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [viewMonth, setViewMonth] = useState<Date>(() => parseISO(from) || today());
  const [draftFrom, setDraftFrom] = useState<string | null>(null);
  const [hoverDay, setHoverDay] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Close on outside click / Esc
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
        setDraftFrom(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        setDraftFrom(null);
      }
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // When opening — sync viewMonth to current `from`
  useEffect(() => {
    if (open) {
      setViewMonth(parseISO(from) || today());
      setDraftFrom(null);
    }
  }, [open, from]);

  const handleDayClick = (day: string) => {
    if (!draftFrom) {
      setDraftFrom(day);
      setHoverDay(null);
    } else {
      const [f, t] = day < draftFrom ? [day, draftFrom] : [draftFrom, day];
      onChange({ from: f, to: t });
      setDraftFrom(null);
      setHoverDay(null);
      setOpen(false);
    }
  };

  const activePresets = presets ?? DEFAULT_PRESETS;

  return (
    <div ref={wrapRef} className={`relative ${className || ""}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`input flex items-center gap-2 ${compact ? "px-2 py-1" : ""}`}
        title="Выбрать период"
      >
        <Icon name="calendar" size={12} className="text-muted" />
        <span className="tabular-nums">
          {formatDisplay(from)} — {formatDisplay(to)}
        </span>
      </button>

      {open && (
        <div className="absolute z-50 mt-1 bg-surface border border-border rounded shadow-lg p-3 flex gap-3 text-xs">
          {/* Presets sidebar */}
          <div className="flex flex-col gap-1 min-w-[140px] border-r border-border/40 pr-3">
            {activePresets.map((p) => (
              <button
                key={p.label}
                type="button"
                className="text-left px-2 py-1 rounded hover:bg-surface-2/70 text-muted hover:text-white"
                onClick={() => {
                  onChange(p.range());
                  setOpen(false);
                  setDraftFrom(null);
                }}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Calendar */}
          <div>
            <CalendarHeader
              month={viewMonth}
              onPrev={() =>
                setViewMonth((m) => new Date(m.getFullYear(), m.getMonth() - 1, 1))
              }
              onNext={() =>
                setViewMonth((m) => new Date(m.getFullYear(), m.getMonth() + 1, 1))
              }
            />
            <CalendarGrid
              viewMonth={viewMonth}
              rangeFrom={draftFrom || from}
              rangeTo={draftFrom ? hoverDay || from : to}
              onDayClick={handleDayClick}
              onDayHover={setHoverDay}
            />
            <div className="mt-2 text-[10px] text-muted">
              {draftFrom
                ? `Выбрано: ${formatDisplay(draftFrom)} → … кликни вторую дату`
                : "Кликни первую дату диапазона"}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CalendarHeader({
  month,
  onPrev,
  onNext,
}: {
  month: Date;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="flex items-center justify-between mb-2">
      <button
        type="button"
        onClick={onPrev}
        className="px-2 py-1 rounded hover:bg-surface-2 text-muted"
        aria-label="Предыдущий месяц"
      >
        ←
      </button>
      <div className="font-medium text-white">
        {MONTHS_RU[month.getMonth()]} {month.getFullYear()}
      </div>
      <button
        type="button"
        onClick={onNext}
        className="px-2 py-1 rounded hover:bg-surface-2 text-muted"
        aria-label="Следующий месяц"
      >
        →
      </button>
    </div>
  );
}

function CalendarGrid({
  viewMonth,
  rangeFrom,
  rangeTo,
  onDayClick,
  onDayHover,
}: {
  viewMonth: Date;
  rangeFrom: string;
  rangeTo: string;
  onDayClick: (day: string) => void;
  onDayHover: (day: string | null) => void;
}) {
  const days = useMemo(() => buildMonthGrid(viewMonth), [viewMonth]);
  const [lo, hi] = rangeFrom <= rangeTo ? [rangeFrom, rangeTo] : [rangeTo, rangeFrom];

  return (
    <div className="grid grid-cols-7 gap-1 w-[15rem]">
      {DAYS_RU.map((d) => (
        <div key={d} className="text-center text-muted py-1">
          {d}
        </div>
      ))}
      {days.map((d, i) => {
        if (d === null) return <div key={i} />;
        const iso = formatISO(d);
        const inCurrentMonth = d.getMonth() === viewMonth.getMonth();
        const inRange = iso >= lo && iso <= hi;
        const isStart = iso === lo;
        const isEnd = iso === hi;
        const isToday = iso === formatISO(today());
        const cls = [
          "text-center py-1 rounded cursor-pointer tabular-nums",
          inCurrentMonth ? "text-white" : "text-muted/40",
          inRange ? "bg-accent/30" : "hover:bg-surface-2",
          (isStart || isEnd) ? "bg-accent text-white font-semibold" : "",
          isToday && !isStart && !isEnd ? "ring-1 ring-accent/50" : "",
        ].join(" ");
        return (
          <div
            key={i}
            className={cls}
            onClick={() => onDayClick(iso)}
            onMouseEnter={() => onDayHover(iso)}
            onMouseLeave={() => onDayHover(null)}
          >
            {d.getDate()}
          </div>
        );
      })}
    </div>
  );
}

// ── date utilities ──────────────────────────────────────────────────────

function today(): Date {
  const t = new Date();
  return new Date(t.getFullYear(), t.getMonth(), t.getDate());
}

function iso(d: Date): string {
  return formatISO(d);
}

function formatISO(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function parseISO(s: string): Date | null {
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s);
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

function monthStart(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function buildMonthGrid(viewMonth: Date): (Date | null)[] {
  // Show 6 weeks × 7 days = 42 cells. Start from the Monday of week containing day 1.
  const first = new Date(viewMonth.getFullYear(), viewMonth.getMonth(), 1);
  // Monday = 0 в нашей сетке; getDay(): Sun=0..Sat=6.
  const weekdayMon0 = (first.getDay() + 6) % 7;
  const gridStart = addDays(first, -weekdayMon0);
  return Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
}

function formatDisplay(s: string): string {
  const d = parseISO(s);
  if (!d) return s;
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.${d.getFullYear()}`;
}
