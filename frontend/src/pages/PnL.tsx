import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

type LineKind = "section" | "data";
type Line = {
  key?: string;
  label: string;
  kind?: LineKind;
  emphasize?: boolean;
};

const lines: Line[] = [
  { kind: "section", label: "Выручка" },
  { key: "revenue_gross", label: "Выручка WB (gross)" },
  { key: "revenue_returns", label: "Возвраты" },
  { key: "dbs_revenue", label: "DBS / rFBS выручка" },
  { key: "selfbuy_adjustment", label: "Самовыкупы / раздачи (вычитаем)" },
  { key: "revenue_net", label: "Чистая выручка", emphasize: true },
  { key: "vat", label: "НДС (исходящий)" },

  { kind: "section", label: "Расходы маркетплейса" },
  { key: "commission", label: "Комиссия WB" },
  { key: "delivery", label: "Логистика" },
  { key: "storage", label: "Хранение" },
  { key: "penalty", label: "Штрафы" },
  { key: "deduction", label: "Удержания" },
  { key: "acquiring", label: "Эквайринг" },

  { kind: "section", label: "Маркетинг и подрядчики" },
  { key: "ad_cost", label: "Реклама WB" },
  { key: "external_ad_cost", label: "Внешний маркетинг (блогеры/инфографика)" },
  { key: "contractor_fees", label: "Услуги подрядчиков (самовыкуп/DBS)" },

  { kind: "section", label: "Себестоимость и OPEX" },
  { key: "cogs", label: "Себестоимость (COGS)" },
  { key: "opex_operating", label: "OPEX (постоянные/переменные)" },
  { key: "other_costs", label: "Прочие фикс.расходы (legacy)" },

  { kind: "section", label: "Налоги" },
  { key: "tax", label: "Налог" },

  { key: "profit", label: "Чистая (опер.) прибыль", emphasize: true },

  { kind: "section", label: "Cash flow" },
  { key: "opex_cashflow_only", label: "Не-операционные оттоки (тело кредита, дивиденды и пр.)" },
  { key: "cash_flow", label: "Денежный поток (cash flow)", emphasize: true },
];

export default function PnL() {
  const [from, setFrom] = useState(daysAgo(29));
  const [to, setTo] = useState(today());
  const [granularity, setGranularity] = useState<"day" | "week" | "month">("day");

  const q = useQuery({
    queryKey: ["pnl", from, to, granularity],
    queryFn: () => api.pnl(from, to, granularity) as Promise<any>,
  });

  const isBrandsScope = q.data?.scope === "brands";

  return (
    <div className="flex flex-col gap-4">
      {isBrandsScope && (
        <div className="card text-xs text-muted border-border bg-surface">
          Вы видите P&amp;L по своим брендам — contribution-margin вид (без OPEX,
          fixed-costs, налогов и НДС). Чтобы увидеть полный финансовый
          результат компании, попросите директора.
        </div>
      )}
      <div className="flex items-end justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">P&L</h1>
        <div className="flex items-end gap-3 flex-wrap">
          <label className="flex flex-col text-xs text-muted">
            С
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              className="bg-surface border border-border rounded-md p-1.5 text-sm text-white"
            />
          </label>
          <label className="flex flex-col text-xs text-muted">
            По
            <input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              className="bg-surface border border-border rounded-md p-1.5 text-sm text-white"
            />
          </label>
          <div className="flex gap-1">
            {(["day", "week", "month"] as const).map((g) => (
              <button
                key={g}
                className={`btn ${granularity === g ? "border-accent text-accent" : ""}`}
                onClick={() => setGranularity(g)}
              >
                {g === "day" ? "День" : g === "week" ? "Неделя" : "Месяц"}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="card overflow-x-auto">
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.data && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-muted text-xs uppercase">
                <th className="text-left p-2 sticky left-0 bg-surface">Статья</th>
                {q.data.rows.map((r: any) => (
                  <th key={r.period_start} className="text-right p-2 whitespace-nowrap">
                    {r.period_start === r.period_end
                      ? r.period_start
                      : `${r.period_start} … ${r.period_end}`}
                  </th>
                ))}
                <th className="text-right p-2 whitespace-nowrap font-semibold">Σ</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line, idx) => {
                if (line.kind === "section") {
                  return (
                    <tr key={`s-${idx}`} className="border-t border-border bg-bg/30">
                      <td
                        className="p-2 sticky left-0 bg-surface text-xs uppercase tracking-wide text-muted font-semibold"
                        colSpan={(q.data.rows?.length ?? 0) + 2}
                      >
                        {line.label}
                      </td>
                    </tr>
                  );
                }
                const k = line.key as string;
                return (
                  <tr
                    key={k}
                    className={`border-t border-border ${line.emphasize ? "bg-bg/40 font-semibold" : ""}`}
                  >
                    <td className="p-2 sticky left-0 bg-surface">{line.label}</td>
                    {q.data.rows.map((r: any) => (
                      <td key={r.period_start} className="text-right p-2 font-mono">
                        {fmtRub(r[k])}
                      </td>
                    ))}
                    <td className="text-right p-2 font-mono">
                      {fmtRub(q.data.totals?.[k])}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="text-xs text-muted">
        Источник истины — отчёт WB <code>/reportDetailByPeriod</code> (задержка 1–2 дня).
        Реклама и COGS сводятся по дате операции.
      </div>
    </div>
  );
}
