/**
 * PeriodCompareCalendar (TASK-DEV-060) — пикер двух периодов (основной + сравнение),
 * как в TrueStats: два месяца-календаря, переключатель цели (основной/сравнение),
 * пресеты (Вчера/7/30/90 дней/Текущий месяц) и выпадашка WB-недель.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/Icon";

export type Range = { from: string; to: string };

const MONTHS_RU = ["январь","февраль","март","апрель","май","июнь","июль","август","сентябрь","октябрь","ноябрь","декабрь"];
const DOW = ["пн","вт","ср","чт","пт","сб","вс"];

function d2iso(d: Date) { return d.toISOString().slice(0, 10); }
function parse(s: string) { return new Date(s + "T00:00:00Z"); }
function addDays(d: Date, n: number) { return new Date(d.getTime() + n * 86400000); }
function todayUTC() { const t = new Date(); return new Date(Date.UTC(t.getFullYear(), t.getMonth(), t.getDate())); }
function fmt(s: string) { const [y, m, dd] = s.split("-"); return `${dd}.${m}.${y}`; }
function lenDays(r: Range) { return Math.round((parse(r.to).getTime() - parse(r.from).getTime()) / 86400000) + 1; }
function prevOf(r: Range): Range { const n = lenDays(r); const pe = addDays(parse(r.from), -1); const ps = addDays(pe, -(n - 1)); return { from: d2iso(ps), to: d2iso(pe) }; }
function monday(d: Date) { const wd = (d.getUTCDay() + 6) % 7; return addDays(d, -wd); }
function isoWeek(d: Date) {
  const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const dn = (t.getUTCDay() + 6) % 7; t.setUTCDate(t.getUTCDate() - dn + 3);
  const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
  return 1 + Math.round(((t.getTime() - y0.getTime()) / 86400000 - 3 + ((y0.getUTCDay() + 6) % 7)) / 7);
}
function monthGrid(view: Date): (Date | null)[] {
  const first = new Date(Date.UTC(view.getUTCFullYear(), view.getUTCMonth(), 1));
  const lead = (first.getUTCDay() + 6) % 7;
  const dim = new Date(Date.UTC(view.getUTCFullYear(), view.getUTCMonth() + 1, 0)).getUTCDate();
  const cells: (Date | null)[] = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  for (let dd = 1; dd <= dim; dd++) cells.push(new Date(Date.UTC(view.getUTCFullYear(), view.getUTCMonth(), dd)));
  return cells;
}

export function PeriodCompareCalendar({
  main, compare, onApply,
}: {
  main: Range;
  compare: Range;
  onApply: (main: Range, compare: Range) => void;
}) {
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<"main" | "compare">("main");
  const [dMain, setDMain] = useState<Range>(main);
  const [dCmp, setDCmp] = useState<Range>(compare);
  const [anchor, setAnchor] = useState<string | null>(null);
  const [view, setView] = useState<Date>(() => { const d = parse(main.from); return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - 1, 1)); });
  const wrap = useRef<HTMLDivElement>(null);

  useEffect(() => { setDMain(main); setDCmp(compare); }, [main, compare, open]);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc); document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const cur = target === "main" ? dMain : dCmp;
  const setCur = (r: Range) => {
    if (target === "main") { setDMain(r); setDCmp(prevOf(r)); }
    else setDCmp(r);
  };

  const onDay = (iso: string) => {
    if (!anchor) { setAnchor(iso); return; }
    const [f, t] = iso < anchor ? [iso, anchor] : [anchor, iso];
    setCur({ from: f, to: t });
    setAnchor(null);
  };

  const presets: { label: string; r: () => Range }[] = [
    { label: "Вчера", r: () => { const y = addDays(todayUTC(), -1); return { from: d2iso(y), to: d2iso(y) }; } },
    { label: "7 дней", r: () => ({ from: d2iso(addDays(todayUTC(), -6)), to: d2iso(todayUTC()) }) },
    { label: "30 дней", r: () => ({ from: d2iso(addDays(todayUTC(), -29)), to: d2iso(todayUTC()) }) },
    { label: "Текущий месяц", r: () => { const t = todayUTC(); return { from: d2iso(new Date(Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), 1))), to: d2iso(t) }; } },
    { label: "90 дней", r: () => ({ from: d2iso(addDays(todayUTC(), -89)), to: d2iso(todayUTC()) }) },
  ];

  const weeks = useMemo(() => {
    const out: { label: string; r: Range }[] = [];
    let m = monday(todayUTC());
    for (let i = 0; i < 12; i++) {
      const f = m, t = addDays(m, 6);
      out.push({ label: `${isoWeek(f)} (${fmt(d2iso(f))} - ${fmt(d2iso(t))})`, r: { from: d2iso(f), to: d2iso(t) } });
      m = addDays(m, -7);
    }
    return out;
  }, []);

  const months = [view, new Date(Date.UTC(view.getUTCFullYear(), view.getUTCMonth() + 1, 1))];

  return (
    <div ref={wrap} className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)} className="input flex items-center gap-2">
        <Icon name="calendar" size={12} className="text-muted" />
        <span className="tabular-nums">{fmt(main.from)} — {fmt(main.to)}</span>
        <span className="text-muted text-xs">↔ {fmt(compare.from)} — {fmt(compare.to)}</span>
      </button>

      {open && (
        <div className="absolute z-50 mt-1 bg-surface border border-border rounded-lg shadow-xl p-4 text-sm w-[640px] max-w-[95vw]">
          <div className="flex gap-3 mb-3">
            {(["main", "compare"] as const).map((tg) => {
              const r = tg === "main" ? dMain : dCmp;
              return (
                <button key={tg} type="button" onClick={() => setTarget(tg)}
                  className={`flex-1 text-left px-3 py-2 rounded-lg border ${target === tg ? "border-accent bg-accent/10" : "border-border"}`}>
                  <div className="flex items-center gap-2 text-xs text-muted mb-1">
                    <span className={`inline-block w-2.5 h-2.5 rounded-full ${target === tg ? "bg-accent" : "border border-muted"}`} />
                    {tg === "main" ? "Основной период" : "Период сравнения"}
                  </div>
                  <div className="tabular-nums">{fmt(r.from)} — {fmt(r.to)}</div>
                  <div className="text-[11px] text-muted">Интервал: {lenDays(r)} дн.</div>
                </button>
              );
            })}
          </div>

          <div className="flex gap-4">
            <div className="flex gap-3">
              {months.map((mv, mi) => (
                <div key={mi} className="w-[200px] shrink-0">
                  <div className="flex items-center justify-between mb-2">
                    {mi === 0 ? <button onClick={() => setView(new Date(Date.UTC(view.getUTCFullYear(), view.getUTCMonth() - 1, 1)))} className="px-2 text-muted hover:text-white">‹</button> : <span className="w-6" />}
                    <div className="font-medium text-[13px]">{MONTHS_RU[mv.getUTCMonth()]} {mv.getUTCFullYear()}</div>
                    {mi === 1 ? <button onClick={() => setView(new Date(Date.UTC(view.getUTCFullYear(), view.getUTCMonth() + 1, 1)))} className="px-2 text-muted hover:text-white">›</button> : <span className="w-6" />}
                  </div>
                  <div className="grid grid-cols-7 gap-0.5">
                    {DOW.map((d) => <div key={d} className="text-center text-[10px] text-muted py-1">{d}</div>)}
                    {monthGrid(mv).map((d, i) => {
                      if (!d) return <div key={i} />;
                      const iso = d2iso(d);
                      const lo = cur.from <= cur.to ? cur.from : cur.to, hi = cur.from <= cur.to ? cur.to : cur.from;
                      const inMain = iso >= dMain.from && iso <= dMain.to;
                      const inCmp = iso >= dCmp.from && iso <= dCmp.to;
                      const inRange = iso >= lo && iso <= hi;
                      const edge = iso === lo || iso === hi;
                      const cls = [
                        "text-center py-1 rounded cursor-pointer tabular-nums text-[12px]",
                        edge ? "bg-accent text-white font-semibold"
                          : inRange ? "bg-accent/40 text-white"
                          : inMain ? "bg-accent/20" : inCmp ? "bg-muted/20" : "hover:bg-surface-2",
                      ].join(" ");
                      return <div key={i} className={cls} onClick={() => onDay(iso)}>{d.getUTCDate()}</div>;
                    })}
                  </div>
                </div>
              ))}
            </div>

            <div className="flex flex-col gap-1.5 w-[180px] shrink-0 border-l border-border/40 pl-4">
              {presets.map((p) => (
                <button key={p.label} type="button" onClick={() => setCur(p.r())}
                  className="px-3 py-1.5 rounded border border-border text-xs whitespace-nowrap text-left hover:bg-surface-2">{p.label}</button>
              ))}
              <div className="text-xs text-muted mt-2">Неделя</div>
              <select className="input text-xs w-full" value=""
                onChange={(e) => { const w = weeks.find((x) => x.label === e.target.value); if (w) setCur(w.r); }}>
                <option value="">— выбрать —</option>
                {weeks.map((w) => <option key={w.label} value={w.label}>{w.label}</option>)}
              </select>
              <div className="text-[11px] text-muted mt-1">
                {anchor ? `${fmt(anchor)} → вторую дату` : "Кликни диапазон"}
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-2 mt-4">
            <button type="button" onClick={() => { setDMain(main); setDCmp(compare); setAnchor(null); }}
              className="px-4 py-1.5 rounded border border-border text-sm hover:bg-surface-2">Сбросить</button>
            <button type="button" onClick={() => { onApply(dMain, dCmp); setOpen(false); }}
              className="px-4 py-1.5 rounded bg-accent text-white text-sm">Готово</button>
          </div>
        </div>
      )}
    </div>
  );
}
