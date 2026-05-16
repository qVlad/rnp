import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";
import {
  ColumnVisibilityButton,
  useColumnVisibility,
} from "@/components/ColumnVisibility";
import { DateRangePicker } from "@/components/DateRangePicker";

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

type LineKind = "section" | "data" | "subtotal";
type Line = {
  key?: string;
  label: string;
  kind?: LineKind;
  emphasize?: boolean;
  hint?: string;
  /** Для subtotal: имя поля с %-маржой (показывается в скобках справа от ₽). */
  marginKey?: string;
};

// ── ОПиУ-структура ───────────────────────────────────────────────────────
// Revenue → COGS → Валовая прибыль → Коммерческие → Прибыль от продаж →
// Управленческие → Операционная прибыль (EBIT) / EBITDA → Налог → Чистая прибыль.
// Маржа % считается к revenue_after_vat — это база, на которой компания
// реально получает деньги после НДС.
const lines: Line[] = [
  { kind: "section", label: "Выручка (FBO / основной канал)" },
  { key: "revenue_gross", label: "Выручка (gross)" },
  { key: "revenue_returns", label: "Возвраты" },

  { kind: "section", label: "Сторонний канал доставки (DBS / rFBS)" },
  {
    key: "dbs_revenue",
    label: "Выручка через свою логистику",
    hint:
      "Реальные продажи через свою логистику (Delivery by Seller / realFBS). WB не показывает их в /supplier/sales — добавлены вручную через «Корректировки выручки». Эта выручка добавляется к gross в чистую выручку.",
  },

  { kind: "section", label: "Корректировки выручки (артефакты)" },
  {
    key: "selfbuy_adjustment",
    label: "Самовыкупы / самозаказы / раздачи",
    hint:
      "Фиктивные продажи (накрутка рейтинга, бартер, инфлюенсеры). Сумма вычитается из чистой выручки, чтобы P&L отражал только реальные деньги.",
  },

  { key: "revenue_net", label: "Чистая выручка", emphasize: true },
  { key: "vat", label: "НДС (исходящий)" },
  {
    kind: "subtotal",
    key: "revenue_after_vat",
    label: "Выручка после НДС",
    hint:
      "Чистая выручка − НДС. База для расчёта всех %-маржей в ОПиУ.",
  },

  { kind: "section", label: "Себестоимость продаж" },
  { key: "cogs", label: "Себестоимость (COGS)" },
  {
    kind: "subtotal",
    key: "gross_profit",
    label: "Валовая прибыль (Gross Profit)",
    marginKey: "gross_margin_pct",
    hint:
      "Выручка после НДС − COGS. Показывает маржинальность продукта в чистом виде, без учёта расходов на продажу и управление.",
  },

  { kind: "section", label: "Коммерческие расходы (расходы продаж)" },
  { key: "commission", label: "Комиссия WB" },
  { key: "delivery", label: "Логистика WB" },
  { key: "storage", label: "Хранение WB" },
  { key: "penalty", label: "Штрафы" },
  { key: "deduction", label: "Удержания" },
  { key: "acquiring", label: "Эквайринг" },
  { key: "ad_cost", label: "Реклама WB" },
  { key: "external_ad_cost", label: "Внешний маркетинг (блогеры/инфографика)" },
  { key: "contractor_fees", label: "Услуги подрядчиков (самовыкуп/DBS)" },
  {
    kind: "subtotal",
    key: "profit_from_sales",
    label: "Прибыль от продаж",
    marginKey: "profit_from_sales_margin_pct",
    hint: "Валовая прибыль − коммерческие расходы.",
  },

  { kind: "section", label: "Управленческие расходы" },
  { key: "opex_operating", label: "OPEX (постоянные/переменные)" },
  { key: "other_costs", label: "Прочие фикс.расходы (legacy)" },
  {
    kind: "subtotal",
    key: "operating_profit",
    label: "Операционная прибыль (EBIT)",
    marginKey: "operating_margin_pct",
    emphasize: true,
    hint:
      "Прибыль от продаж − управленческие. Главный показатель эффективности операций — сколько бизнес зарабатывает до налогов и финансовых статей.",
  },
  {
    kind: "subtotal",
    key: "ebitda",
    label: "EBITDA",
    marginKey: "ebitda_margin_pct",
    hint:
      "EBIT + амортизация. Сейчас амортизация в модели не выделена отдельно — EBITDA = EBIT. Когда заведёшь категорию «Амортизация» в OPEX (in_operating=true, cf_section=investing), цифра отделится.",
  },

  { kind: "section", label: "Налоги" },
  { key: "tax", label: "Налог (управленческий, retail_amt × ставка)" },
  { key: "tax_for_fns", label: "Налог по бух-методу (для 1С, retail_amt − УПД − COGS)" },

  {
    key: "profit",
    label: "Чистая прибыль",
    emphasize: true,
    kind: "subtotal",
    marginKey: "net_margin_pct",
  },

  { kind: "section", label: "Cash flow" },
  { key: "opex_cashflow_only", label: "Не-операционные оттоки (тело кредита, дивиденды и пр.)" },
  { key: "cash_flow", label: "Денежный поток (cash flow)", emphasize: true },
];

function deltaCell(curr: number | undefined, prev: number | undefined): {
  abs: string;
  pct: string;
  cls: string;
} {
  const c = Number(curr ?? 0);
  const p = Number(prev ?? 0);
  const abs = c - p;
  const pctVal = p === 0 ? null : (abs / Math.abs(p)) * 100;
  const cls =
    abs > 0
      ? "text-success"
      : abs < 0
      ? "text-red-400"
      : "text-muted";
  return {
    abs: (abs > 0 ? "+" : "") + fmtRub(abs),
    pct: pctVal === null ? "—" : `${pctVal > 0 ? "+" : ""}${pctVal.toFixed(1)}%`,
    cls,
  };
}

export default function PnL() {
  const [from, setFrom] = useState(daysAgo(29));
  const [to, setTo] = useState(today());
  const [granularity, setGranularity] = useState<"day" | "week" | "month">("day");
  const [compare, setCompare] = useState(false);
  const { isHidden: rowHidden } = useColumnVisibility("pnl.rows.hidden.v1");

  const q = useQuery({
    queryKey: ["pnl", from, to, granularity, compare],
    queryFn: () =>
      api.pnl(from, to, granularity, compare) as Promise<any>,
  });

  const isBrandsScope = q.data?.scope === "brands";
  const prevTotals = q.data?.previous?.totals;

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
        <h1 className="text-xl font-semibold">P&L — Отчёт о прибылях и убытках</h1>
        <div className="flex items-end gap-3 flex-wrap">
          <div className="flex flex-col text-xs text-muted">
            Период
            <DateRangePicker
              from={from}
              to={to}
              onChange={(r) => { setFrom(r.from); setTo(r.to); }}
            />
          </div>
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
          <label
            className={`btn cursor-pointer ${compare ? "border-accent text-accent" : ""}`}
            title="Сравнить с предыдущим периодом такой же длины"
          >
            <input
              type="checkbox"
              checked={compare}
              onChange={(e) => setCompare(e.target.checked)}
              className="mr-1.5 align-middle"
            />
            Сравнить с прошлым
          </label>
          <ColumnVisibilityButton
            storageKey="pnl.rows.hidden.v1"
            columns={lines
              .filter((l) => l.kind !== "section" && l.key)
              .map((l) => ({ key: l.key as string, label: l.label }))}
            buttonLabel="Строки"
          />
        </div>
      </div>

      <div className="card overflow-x-auto">
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.data && (
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface-2 z-10 shadow-[0_1px_0_var(--border)]">
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
                {compare && prevTotals && (
                  <>
                    <th
                      className="text-right p-2 whitespace-nowrap text-muted"
                      title={`${q.data.previous.from} … ${q.data.previous.to}`}
                    >
                      Прошл.
                    </th>
                    <th className="text-right p-2 whitespace-nowrap">Δ</th>
                    <th className="text-right p-2 whitespace-nowrap">Δ %</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {lines.filter((line) => !rowHidden(line.key || "")).map((line, idx) => {
                if (line.kind === "section") {
                  const colSpan =
                    (q.data.rows?.length ?? 0) +
                    2 +
                    (compare && prevTotals ? 3 : 0);
                  return (
                    <tr key={`s-${idx}`} className="border-t border-border bg-surface-2/40">
                      <td
                        className="p-2 sticky left-0 bg-surface text-xs uppercase tracking-wide text-muted font-semibold"
                        colSpan={colSpan}
                      >
                        {line.label}
                      </td>
                    </tr>
                  );
                }
                const k = line.key as string;
                const isSubtotal = line.kind === "subtotal";
                const rowCls = isSubtotal
                  ? "border-t-2 border-accent/50 bg-surface-2/60 font-semibold"
                  : line.emphasize
                  ? "border-t border-border bg-surface-2/50 font-semibold"
                  : "border-t border-border";
                const total = q.data.totals?.[k];
                const margin = line.marginKey
                  ? q.data.totals?.[line.marginKey]
                  : undefined;
                return (
                  <tr key={k} className={rowCls}>
                    <td
                      className="p-2 sticky left-0 bg-surface"
                      title={line.hint || undefined}
                    >
                      {line.label}
                      {line.hint && (
                        <span
                          className="ml-1 text-muted text-[10px] cursor-help"
                          aria-label="что это?"
                        >
                          ⓘ
                        </span>
                      )}
                    </td>
                    {q.data.rows.map((r: any) => (
                      <td key={r.period_start} className="text-right p-2 font-mono">
                        {fmtRub(r[k])}
                      </td>
                    ))}
                    <td className="text-right p-2 font-mono">
                      {fmtRub(total)}
                      {margin !== undefined && (
                        <span
                          className={`ml-1 text-[11px] ${
                            margin >= 0 ? "text-muted" : "text-red-400"
                          }`}
                        >
                          ({margin >= 0 ? "" : ""}
                          {Number(margin).toFixed(1)}%)
                        </span>
                      )}
                    </td>
                    {compare && prevTotals && (() => {
                      const prev = prevTotals[k];
                      const d = deltaCell(total, prev);
                      return (
                        <>
                          <td className="text-right p-2 font-mono text-muted">
                            {fmtRub(prev)}
                          </td>
                          <td className={`text-right p-2 font-mono ${d.cls}`}>
                            {d.abs}
                          </td>
                          <td className={`text-right p-2 font-mono ${d.cls}`}>
                            {d.pct}
                          </td>
                        </>
                      );
                    })()}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="text-xs text-muted leading-relaxed">
        Источник истины — отчёт WB <code>report_detail</code> (final-логика по{" "}
        <code>supplier_oper_name</code>, задержка 1–2 дня). Реклама и COGS сводятся
        по дате операции. <strong>Маржа %</strong> считается к выручке после НДС.
        EBITDA = EBIT, пока амортизация не вынесена в отдельную OPEX-категорию.
      </div>
    </div>
  );
}
