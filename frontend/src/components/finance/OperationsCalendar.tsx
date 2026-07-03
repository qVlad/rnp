/**
 * Календарь операций (DEV-093, как TS «Операции → Календарь»): месячные
 * сетки, на каждый день — остаток на счетах + поступления/списания.
 * Данные — /api/cashflow-calendar (баланс от Σ initial_balance счетов).
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

type Day = {
  date: string; income: number; expense: number; balance: number;
  obligation_receivable: number; obligation_payable: number;
};

export default function OperationsCalendar({ from, to }: { from: string; to: string }) {
  const q = useQuery({
    queryKey: ["cashflow-calendar", from, to],
    queryFn: () => api.cashflowCalendar(from, to),
  });
  const days = q.data?.data ?? [];
  if (q.isLoading) return <div className="card text-sm text-muted">Загрузка…</div>;
  if (!days.length) return <div className="card text-sm text-muted">Нет данных за период.</div>;

  // Разбивка по месяцам.
  const byMonth = new Map<string, Day[]>();
  for (const d of days) {
    const key = d.date.slice(0, 7);
    if (!byMonth.has(key)) byMonth.set(key, []);
    byMonth.get(key)!.push(d);
  }

  return (
    <div className="flex flex-col gap-6">
      {[...byMonth.entries()].map(([month, mdays]) => (
        <MonthGrid key={month} month={month} days={mdays} />
      ))}
    </div>
  );
}

function MonthGrid({ month, days }: { month: string; days: Day[] }) {
  const [y, m] = month.split("-").map(Number);
  const first = new Date(y, m - 1, 1);
  const lead = (first.getDay() + 6) % 7; // Пн=0
  const byDate = new Map(days.map((d) => [d.date, d]));
  const daysInMonth = new Date(y, m, 0).getDate();
  const todayIso = new Date().toISOString().slice(0, 10); // маркер «Сегодня» (TS-parity, DEV-094)
  const cells: Array<Day | null> = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  for (let day = 1; day <= daysInMonth; day++) {
    const iso = `${month}-${String(day).padStart(2, "0")}`;
    cells.push(byDate.get(iso) ?? null);
  }

  return (
    <div>
      <h3 className="font-medium mb-2">{MONTHS[m - 1]} {y}</h3>
      <div className="card p-0 overflow-x-auto">
        <div className="grid grid-cols-7 min-w-[840px]">
          {WEEKDAYS.map((w) => (
            <div key={w} className="p-2 text-xs text-muted text-center border-b border-border">{w}</div>
          ))}
          {cells.map((d, i) => {
            const dayNum = i - lead + 1;
            const inMonth = dayNum >= 1 && dayNum <= daysInMonth;
            const iso = `${month}-${String(dayNum).padStart(2, "0")}`;
            const isToday = inMonth && iso === todayIso;
            return (
              <div
                key={i}
                className={`min-h-[76px] p-1.5 border-b border-r border-border/50 text-right ${
                  inMonth && d && (d.income || d.expense) ? "bg-success/5" : ""
                } ${isToday ? "ring-2 ring-accent ring-inset rounded-sm" : ""}`}
                title={isToday ? "Сегодня" : undefined}
              >
                {inMonth && (
                  <>
                    <div className={`text-xs ${isToday ? "text-accent font-semibold" : "text-muted"}`}>
                      {dayNum}{isToday ? " · сегодня" : ""}
                    </div>
                    {d && (
                      <>
                        <div className="text-[11px] font-mono" title="Остаток на конец дня">
                          {fmtRub(d.balance)}
                        </div>
                        {d.income > 0 && (
                          <div className="text-[11px] font-mono text-success">+{fmtRub(d.income)}</div>
                        )}
                        {d.expense > 0 && (
                          <div className="text-[11px] font-mono text-danger">−{fmtRub(d.expense)}</div>
                        )}
                        {(d.obligation_receivable > 0 || d.obligation_payable > 0) && (
                          <div className="text-[10px] text-warn" title="Плановые обязательства">
                            план {d.obligation_receivable > 0 ? `+${fmtRub(d.obligation_receivable)}` : ""}
                            {d.obligation_payable > 0 ? ` −${fmtRub(d.obligation_payable)}` : ""}
                          </div>
                        )}
                      </>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
