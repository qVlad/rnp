import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";
import { chartTheme } from "@/lib/chartTheme";

export default function PaymentCalendar() {
  const [daysForward, setDaysForward] = useState(30);
  const [payOffset, setPayOffset] = useState(14);
  const [initBalance, setInitBalance] = useState<string>("");

  const q = useQuery<any>({
    queryKey: ["payment-calendar", daysForward, payOffset, initBalance],
    queryFn: () =>
      api.paymentCalendar({
        days_forward: daysForward,
        pay_offset_days: payOffset,
        initial_balance: initBalance === "" ? undefined : Number(initBalance),
      }),
  });
  const d: any = q.data;

  const chartData = useMemo(() => {
    if (!d) return [];
    return d.days.map((row: any) => ({
      date: row.date.slice(5), // MM-DD
      balance: row.balance,
      incoming: row.incoming,
      outgoing: -row.outgoing,
    }));
  }, [d]);

  // today в локальной TZ как YYYY-MM-DD (для сравнения с row.date)
  const todayIso = useMemo(() => {
    const t = new Date();
    const y = t.getFullYear();
    const m = String(t.getMonth() + 1).padStart(2, "0");
    const dd = String(t.getDate()).padStart(2, "0");
    return `${y}-${m}-${dd}`;
  }, []);

  // если today попадает в видимый период — формат MM-DD для XAxis-tick
  const todayInView = useMemo(() => {
    if (!d || !d.days?.length) return null as string | null;
    const hit = d.days.find((r: any) => r.date === todayIso);
    return hit ? hit.date.slice(5) : null;
  }, [d, todayIso]);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold mb-1">Платёжный календарь</h1>
        <p className="text-sm text-muted">
          Прогноз банковского остатка: ожидаемые выплаты WB (по неоплаченным отчётам)
          + запланированные OPEX. Алерт показывается если в горизонте ожидается кассовый разрыв.
        </p>
      </div>

      <section className="card flex flex-wrap gap-4 items-end">
        <label className="flex flex-col gap-1">
          <span className="text-xs uppercase text-muted">Горизонт, дн</span>
          <input
            type="number"
            min={1}
            max={180}
            className="input w-24"
            value={daysForward}
            onChange={(e) => setDaysForward(Number(e.target.value) || 30)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span
            className="text-xs uppercase text-muted"
            title="Лаг WB-выплат от report_date_to. Обычно 14 дн, на каникулах до 20."
          >
            Pay offset, дн
          </span>
          <input
            type="number"
            min={0}
            max={60}
            className="input w-24"
            value={payOffset}
            onChange={(e) => setPayOffset(Number(e.target.value) || 14)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span
            className="text-xs uppercase text-muted"
            title="Начальный остаток на расчётном счёте. Если пусто — 0."
          >
            Начальный остаток, ₽
          </span>
          <input
            type="number"
            className="input w-36"
            value={initBalance}
            placeholder="0"
            onChange={(e) => setInitBalance(e.target.value)}
          />
        </label>
        {d && (
          <div className="ml-auto text-xs text-muted">
            <div>
              Приход за период:{" "}
              <span className="text-success font-mono">+{fmtRub(d.total_incoming)}</span>
            </div>
            <div>
              Расход:{" "}
              <span className="text-danger font-mono">−{fmtRub(d.total_outgoing)}</span>
            </div>
            <div>
              Финальный остаток:{" "}
              <span
                className={`font-mono font-medium ${
                  d.final_balance < 0
                    ? "text-danger"
                    : d.final_balance < d.initial_balance * 0.2
                    ? "text-warning"
                    : "text-success"
                }`}
              >
                {fmtRub(d.final_balance)}
              </span>
            </div>
          </div>
        )}
      </section>

      {d?.alerts?.length > 0 && (
        <section className="space-y-2">
          {d.alerts.map((a: any, i: number) => (
            <div
              key={i}
              className={`card border-l-4 ${
                a.severity === "danger"
                  ? "border-l-danger text-danger"
                  : "border-l-warning text-warning"
              }`}
            >
              {a.message}
            </div>
          ))}
        </section>
      )}

      <section className="card">
        <div className="font-medium mb-3">Кривая остатка</div>
        {chartData.length > 0 && (
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData} margin={{ top: 5, right: 16, left: 16, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid} />
              <XAxis dataKey="date" stroke={chartTheme.axis} fontSize={11} />
              <YAxis stroke={chartTheme.axis} fontSize={11} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
              <Tooltip
                formatter={(v: any) => fmtRub(Number(v))}
                contentStyle={chartTheme.tooltipStyle}
              />
              <Line type="monotone" dataKey="balance" stroke={chartTheme.primary} dot={false} strokeWidth={2} />
              {todayInView && (
                <ReferenceLine
                  x={todayInView}
                  stroke={chartTheme.warn}
                  strokeDasharray="4 4"
                  strokeWidth={2}
                  label={{
                    value: "Сегодня",
                    position: "top",
                    fill: chartTheme.warn,
                    fontSize: 11,
                  }}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        )}
      </section>

      <section className="card overflow-x-auto">
        <div className="font-medium mb-3">Расписание по дням</div>
        {d && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs uppercase text-muted">
                <th className="text-left p-2">Дата</th>
                <th className="text-right p-2">Приход</th>
                <th className="text-right p-2">Расход</th>
                <th className="text-right p-2">Остаток</th>
              </tr>
            </thead>
            <tbody>
              {d.days.map((row: any) => {
                const hasMovement = row.incoming > 0 || row.outgoing > 0;
                const isToday = row.date === todayIso;
                const isPast = row.date < todayIso;
                const rowClass = isToday
                  ? "border-t-2 border-warning bg-warning/5 font-medium"
                  : `border-t border-border/40 ${
                      hasMovement ? (isPast ? "" : "text-muted") : "text-muted/60"
                    }`;
                const dateExtra = isToday
                  ? ""
                  : isPast
                  ? ""
                  : " border-l border-dashed border-border";
                return (
                  <tr key={row.date} className={rowClass}>
                    <td className={`p-2 font-mono${dateExtra}`}>
                      {row.date}
                      {isToday && (
                        <span className="ml-2 text-xs uppercase text-warning">сегодня</span>
                      )}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {row.incoming > 0 ? (
                        <span className={isPast ? "text-success" : "text-success/70"}>
                          +{fmtRub(row.incoming)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {row.outgoing > 0 ? (
                        <span className={isPast ? "text-danger" : "text-danger/70"}>
                          −{fmtRub(row.outgoing)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td
                      className={`p-2 text-right font-mono ${
                        row.balance < 0 ? "text-danger font-medium" : ""
                      }`}
                    >
                      {fmtRub(row.balance)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {d?.events?.length > 0 && (
        <section className="card">
          <div className="font-medium mb-3">События</div>
          <ul className="text-sm space-y-1">
            {d.events.map((e: any, i: number) => (
              <li key={i} className="flex items-baseline gap-2">
                <span className="font-mono text-xs text-muted w-20">{e.date}</span>
                <span
                  className={`font-mono w-28 text-right ${
                    e.amount >= 0 ? "text-success" : "text-danger"
                  }`}
                >
                  {e.amount >= 0 ? "+" : ""}
                  {fmtRub(e.amount)}
                </span>
                <span className="text-xs">{e.description}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
