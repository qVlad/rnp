import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";
import { DateRangePicker } from "@/components/DateRangePicker";

const today = () => new Date().toISOString().slice(0, 10);
const startOfMonth = () => {
  const d = new Date();
  d.setDate(1);
  return d.toISOString().slice(0, 10);
};

const SECTION_META: Record<string, { color: string; hint: string }> = {
  operating: {
    color: "border-emerald-700/40",
    hint: "Поступления и оттоки от ежедневных операций: продажи, расходы МП, маркетинг, COGS, ОПЕР-OPEX",
  },
  investing: {
    color: "border-blue-700/40",
    hint: "Покупки оборудования, инвест.вложения, выходы из инвестиций",
  },
  financing: {
    color: "border-yellow-700/40",
    hint: "Кредиты получаемые/погашаемые, дивиденды, вложения учредителей",
  },
};

export default function CashFlow() {
  const [from, setFrom] = useState(startOfMonth());
  const [to, setTo] = useState(today());

  const q = useQuery({
    queryKey: ["cash-flow", from, to],
    queryFn: () => api.cashFlow(from, to),
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">ДДС — Движение денежных средств</h1>
        <div className="flex items-end gap-3 flex-wrap">
          <div className="flex flex-col text-xs text-muted">
            Период
            <DateRangePicker
              from={from}
              to={to}
              onChange={(r) => { setFrom(r.from); setTo(r.to); }}
            />
          </div>
        </div>
      </div>

      <div className="card text-sm text-muted leading-relaxed">
        Отчёт построен на принципе «деньги по факту движения», не по начислению. Знак:
        <span className="text-emerald-400"> +</span> — поступление,
        <span className="text-red-400"> −</span> — выбытие.
        Принадлежность OPEX-категорий к секциям настраивается на странице{" "}
        <a className="text-accent" href="/opex">OPEX</a>.
      </div>

      {/* Top-line summary */}
      {q.data && (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
          {q.data.sections.map((s) => (
            <div
              key={s.name}
              className={`card border-l-4 ${SECTION_META[s.name]?.color ?? ""}`}
            >
              <div className="text-xs text-muted uppercase tracking-wide">
                {s.title}
              </div>
              <div
                className={`text-lg font-semibold mt-1 ${
                  s.total >= 0 ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {fmtRub(s.total)}
              </div>
              <div className="text-xs text-muted mt-2">
                <div>Поступления: <span className="font-mono">{fmtRub(s.inflows_total)}</span></div>
                <div>Оттоки: <span className="font-mono">{fmtRub(s.outflows_total)}</span></div>
              </div>
            </div>
          ))}
          <div className="card border-l-4 border-accent">
            <div className="text-xs text-muted uppercase tracking-wide">
              Чистый денежный поток
            </div>
            <div
              className={`text-2xl font-semibold mt-1 ${
                q.data.net_cash_flow >= 0 ? "text-emerald-400" : "text-red-400"
              }`}
            >
              {fmtRub(q.data.net_cash_flow)}
            </div>
            <div className="text-xs text-muted mt-2">
              {q.data.period.from} … {q.data.period.to}
            </div>
            {q.data.context?.pnl_cash_flow !== undefined && (
              <div
                className="text-xs mt-2"
                title="ДДС считается через P&L как единый источник правды (final WB-логика, hybrid storage, НДС, налог). При расхождении — баг."
              >
                <span className="text-muted">Сверка с P&L:</span>{" "}
                <span className="font-mono">
                  {fmtRub(q.data.context.pnl_cash_flow)}
                </span>
                {Math.abs(q.data.context.pnl_cash_flow - q.data.net_cash_flow) > 1 && (
                  <span className="ml-2 text-red-400">
                    Δ {fmtRub(q.data.net_cash_flow - q.data.context.pnl_cash_flow)}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {q.isLoading && <div className="card text-muted">Загрузка…</div>}

      {q.data &&
        q.data.sections.map((s) => (
          <section key={s.name} className={`card border-l-4 ${SECTION_META[s.name]?.color ?? ""}`}>
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="font-medium">{s.title}</h2>
              <span
                className={`font-mono text-lg ${
                  s.total >= 0 ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {fmtRub(s.total)}
              </span>
            </div>
            <div className="text-xs text-muted mb-3">
              {SECTION_META[s.name]?.hint}
            </div>
            {s.lines.length === 0 && (
              <div className="text-muted text-sm">Нет операций в этой секции.</div>
            )}
            {s.lines.length > 0 && (
              <table className="w-full text-sm">
                <tbody>
                  {s.lines.map((l, i) => (
                    <tr key={i} className="border-t border-border">
                      <td className="p-2">{l.label}</td>
                      <td
                        className={`p-2 text-right font-mono ${
                          l.amount > 0
                            ? "text-emerald-400"
                            : l.amount < 0
                            ? "text-red-400"
                            : "text-muted"
                        }`}
                      >
                        {l.amount > 0 ? "+" : ""}
                        {fmtRub(l.amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        ))}
    </div>
  );
}
