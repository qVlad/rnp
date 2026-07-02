/**
 * ДДС (TASK-DEV-093, стиль TrueStats) — матрица «статьи × месяцы» из
 * банковских/ручных операций + вкладки «По статьям / По виду деятельности /
 * По контрагентам». Старый управленческий ДДС (WB+OPEX из P&L) сохранён
 * последней вкладкой — это другой взгляд (по начислению WB-строк), данные
 * не теряем.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type CashFlowMatrix } from "@/api/client";
import { fmtRub } from "@/lib/format";
import { DateRangePicker } from "@/components/DateRangePicker";
import { usePeriod } from "@/contexts/PeriodContext";
import PageHeader from "@/components/PageHeader";
import { Skeleton } from "@/components/states";

const SECTION_META: Record<string, { color: string; hint: string }> = {
  operating: {
    color: "border-success/40",
    hint: "Поступления и оттоки от ежедневных операций: продажи, расходы МП, маркетинг, COGS, ОПЕР-OPEX",
  },
  investing: {
    color: "border-accent",
    hint: "Покупки оборудования, инвест.вложения, выходы из инвестиций",
  },
  financing: {
    color: "border-warn/40",
    hint: "Кредиты получаемые/погашаемые, дивиденды, вложения учредителей",
  },
};

function monthLabel(m: string): string {
  const [y, mm] = m.split("-");
  const names = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  return `${names[Number(mm) - 1] ?? mm} ${y}`;
}

// ── Матрица операций (как TS «Отчет ДДС») ───────────────────────────────────

function MatrixTab({ groupBy }: { groupBy: "article" | "activity" | "counterparty" }) {
  const { range, setPeriod } = usePeriod();
  const [includePlanned, setIncludePlanned] = useState(false);
  const [accSel, setAccSel] = useState<number[]>([]);
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({ income: true, expense: true });
  const [balOpen, setBalOpen] = useState(false);

  const accountsQ = useQuery({ queryKey: ["finance-accounts"], queryFn: () => api.financeAccounts() });
  const q = useQuery({
    queryKey: ["cf-matrix", range.from, range.to, groupBy, includePlanned, accSel.join(",")],
    queryFn: () =>
      api.cashFlowMatrix(range.from, range.to, {
        group_by: groupBy,
        include_planned: includePlanned,
        accounts: accSel.length ? accSel.join(",") : undefined,
      }),
  });
  const d = q.data;

  const sections = useMemo(() => {
    if (!d) return [];
    return (["income", "expense"] as const).map((sec) => ({
      section: sec,
      title: sec === "income" ? "Доход" : "Расход",
      rows: d.rows.filter((r) => r.section === sec),
      undistributed: d.undistributed[sec],
      monthTotals: d.months.map((m) => {
        let sum = d.rows.filter((r) => r.section === sec).reduce(
          (s, r) => s + (r.cells.find((c) => c.month === m)?.amount ?? 0), 0);
        sum += d.undistributed[sec]?.cells.find((c) => c.month === m)?.amount ?? 0;
        return sum;
      }),
    }));
  }, [d]);

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <DateRangePicker from={range.from} to={range.to}
          onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })} />
        {/* Остаток на счетах с per-счёт дропдауном (как TS) */}
        {d && (
          <div className="relative">
            <button className="input flex items-center gap-2 text-sm" onClick={() => setBalOpen((o) => !o)}>
              <span className="text-muted">Остаток на счетах:</span>
              <b>{fmtRub(d.accounts_balance.total)}</b> <span className="text-muted">▾</span>
            </button>
            {balOpen && (
              <div className="absolute z-40 mt-1 w-72 bg-surface border border-border rounded-lg shadow-xl p-2">
                {d.accounts_balance.per_account.map((a) => (
                  <div key={a.id} className="flex justify-between text-sm py-1 px-1">
                    <span className="truncate">{a.name}</span>
                    <span className="font-mono">{fmtRub(a.balance)}</span>
                  </div>
                ))}
                {d.accounts_balance.per_account.length === 0 && (
                  <div className="text-xs text-muted p-1">
                    Счетов нет — добавьте в <Link className="text-accent" to="/finance-extras">Дополнительно</Link>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        {/* Фильтр по счетам */}
        {(accountsQ.data?.items ?? []).length > 0 && (
          <select
            className="input text-sm"
            value={accSel[0] ?? ""}
            onChange={(e) => setAccSel(e.target.value ? [Number(e.target.value)] : [])}
          >
            <option value="">Все счета</option>
            {(accountsQ.data?.items ?? []).filter((a) => !a.archived).map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        )}
        <label className="flex items-center gap-1.5 text-sm">
          <input type="checkbox" checked={includePlanned} onChange={(e) => setIncludePlanned(e.target.checked)} />
          Учитывать плановые операции
        </label>
        {d && d.counters.ops_without_article > 0 && (
          <Link to="/operations?no_article=1" className="text-sm text-accent hover:underline">
            {d.counters.ops_without_article} операций без статей
          </Link>
        )}
        {d && d.counters.import_errors > 0 && (
          <Link to="/operations?tab=imports" className="text-sm text-danger hover:underline">
            {d.counters.import_errors} ошибка импорта
          </Link>
        )}
      </div>

      {q.isLoading && <Skeleton variant="table" rows={8} />}
      {d && d.months.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="text-left text-muted border-b border-border">
                <th className="p-2 sticky left-0 bg-surface min-w-[220px]">Статья</th>
                <th className="p-2 text-right">Итого</th>
                {d.months.map((m) => (
                  <th key={m} className="p-2 text-right" colSpan={2}>{monthLabel(m)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sections.map((sec) => (
                <SectionRows
                  key={sec.section}
                  sec={sec}
                  months={d.months}
                  open={openSections[sec.section] ?? true}
                  onToggle={() =>
                    setOpenSections((s) => ({ ...s, [sec.section]: !(s[sec.section] ?? true) }))
                  }
                />
              ))}
              {/* Перевод */}
              {d.transfer.cells.some((c) => c.amount !== 0) && (
                <tr className="border-t border-border font-medium">
                  <td className="p-2 sticky left-0 bg-surface">Перевод</td>
                  <td className="p-2 text-right font-mono text-muted">
                    {fmtRub(d.transfer.cells.reduce((s, c) => s + c.amount, 0))}
                  </td>
                  {d.transfer.cells.map((c) => (
                    <td key={c.month} className="p-2 text-right font-mono text-muted" colSpan={2}>
                      {c.amount ? fmtRub(c.amount) : "0,00 ₽"}
                    </td>
                  ))}
                </tr>
              )}
              {/* Итого (Сальдо) */}
              <tr className="border-t-2 border-border font-semibold">
                <td className="p-2 sticky left-0 bg-surface">Итого (Сальдо)</td>
                <td className="p-2 text-right font-mono">
                  <Amount v={d.saldo.reduce((s, c) => s + c.amount, 0)} signed />
                </td>
                {d.saldo.map((c) => (
                  <td key={c.month} className="p-2 text-right font-mono" colSpan={2}>
                    <Amount v={c.amount} signed />
                  </td>
                ))}
              </tr>
              {/* Итого (накопленный остаток) */}
              <tr className="border-t border-border font-semibold">
                <td className="p-2 sticky left-0 bg-surface" title="Остаток денег на конец месяца (Σ начальных балансов счетов + сальдо с начала времён)">
                  Итого
                </td>
                <td className="p-2 text-right font-mono text-muted">—</td>
                {d.cumulative.map((c) => (
                  <td key={c.month} className="p-2 text-right font-mono" colSpan={2}>
                    <Amount v={c.amount} signed />
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
      {d && d.rows.length === 0 && !d.undistributed.income && !d.undistributed.expense && (
        <div className="card text-sm text-muted">
          Операций за период нет. Добавьте вручную на странице{" "}
          <Link className="text-accent" to="/operations">Операции</Link> или загрузите банковскую
          выписку (кнопка «Импорт» там же).
        </div>
      )}
    </>
  );
}

function Amount({ v, signed }: { v: number; signed?: boolean }) {
  const cls = v > 0 ? "text-success" : v < 0 ? "text-danger" : "text-muted";
  return <span className={cls}>{signed && v > 0 ? "+" : ""}{fmtRub(v)}</span>;
}

function SectionRows({
  sec, months, open, onToggle,
}: {
  sec: {
    section: "income" | "expense";
    title: string;
    rows: CashFlowMatrix["rows"];
    undistributed?: { cells: Array<{ month: string; amount: number; pct: number }>; total: number };
    monthTotals: number[];
  };
  months: string[];
  open: boolean;
  onToggle: () => void;
}) {
  const sign = sec.section === "income" ? 1 : -1;
  return (
    <>
      <tr className="border-t border-border font-semibold cursor-pointer hover:bg-soft/40" onClick={onToggle}>
        <td className="p-2 sticky left-0 bg-surface">
          <span className="text-muted mr-1">{open ? "▾" : "▸"}</span>{sec.title}
        </td>
        <td className="p-2 text-right font-mono">
          <Amount v={sign * (sec.rows.reduce((s, r) => s + r.total, 0) + (sec.undistributed?.total ?? 0))} signed />
        </td>
        {months.map((m, i) => (
          <td key={m} className="p-2 text-right font-mono" colSpan={2}>
            <Amount v={sign * sec.monthTotals[i]} signed />
          </td>
        ))}
      </tr>
      {open && sec.rows.map((r) => (
        <tr key={`${r.section}-${String(r.key)}`} className="border-t border-border/50 hover:bg-soft/40">
          <td className="p-2 pl-7 sticky left-0 bg-surface truncate max-w-[260px]">{r.label}</td>
          <td className="p-2 text-right font-mono"><Amount v={sign * r.total} signed /></td>
          {r.cells.map((c) => (
            <MonthCell key={c.month} amount={sign * c.amount} pct={c.pct} />
          ))}
        </tr>
      ))}
      {open && sec.undistributed && sec.undistributed.total !== 0 && (
        <tr className="border-t border-border/50 text-muted">
          <td className="p-2 pl-4 sticky left-0 bg-surface">
            Нераспределённый {sec.section === "income" ? "доход" : "расход"}
          </td>
          <td className="p-2 text-right font-mono"><Amount v={sign * sec.undistributed.total} signed /></td>
          {sec.undistributed.cells.map((c) => (
            <MonthCell key={c.month} amount={sign * c.amount} pct={c.pct} />
          ))}
        </tr>
      )}
    </>
  );
}

function MonthCell({ amount, pct }: { amount: number; pct: number }) {
  return (
    <>
      <td className="p-2 text-right font-mono">
        {amount !== 0 ? <Amount v={amount} signed /> : <span className="text-muted/50">0,00 ₽</span>}
      </td>
      <td className="p-1 pr-2 text-right text-[11px] text-muted w-10">
        {pct ? `${pct}%` : ""}
      </td>
    </>
  );
}

// ── Старый управленческий ДДС (WB+OPEX через P&L) — сохранён как вкладка ────

function ManagementCashFlow() {
  const { range, setPeriod } = usePeriod();
  const from = range.from;
  const to = range.to;

  const q = useQuery({
    queryKey: ["cash-flow", from, to],
    queryFn: () => api.cashFlow(from, to),
  });

  return (
    <>
      <div className="flex flex-col text-xs text-muted w-fit">
        Период
        <DateRangePicker
          from={from}
          to={to}
          onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })}
        />
      </div>

      <div className="card text-sm text-muted leading-relaxed">
        Управленческий взгляд: строится из WB-данных (P&L) + OPEX-категорий, а не из
        банковских операций. Знак:
        <span className="text-success"> +</span> — поступление,
        <span className="text-danger"> −</span> — выбытие.
        Принадлежность OPEX-категорий к секциям настраивается на странице{" "}
        <a className="text-accent" href="/opex">OPEX</a>.
      </div>

      {q.data && (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
          {q.data.sections.map((s) => (
            <div key={s.name} className={`card border-l-4 ${SECTION_META[s.name]?.color ?? ""}`}>
              <div className="text-xs text-muted uppercase tracking-wide">{s.title}</div>
              <div className={`text-lg font-semibold mt-1 ${s.total >= 0 ? "text-success" : "text-danger"}`}>
                {fmtRub(s.total)}
              </div>
              <div className="text-xs text-muted mt-2">
                <div>Поступления: <span className="font-mono">{fmtRub(s.inflows_total)}</span></div>
                <div>Оттоки: <span className="font-mono">{fmtRub(s.outflows_total)}</span></div>
              </div>
            </div>
          ))}
          <div className="card border-l-4 border-accent">
            <div className="text-xs text-muted uppercase tracking-wide">Чистый денежный поток</div>
            <div className={`text-2xl font-semibold mt-1 ${q.data.net_cash_flow >= 0 ? "text-success" : "text-danger"}`}>
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
                <span className="font-mono">{fmtRub(q.data.context.pnl_cash_flow)}</span>
                {Math.abs(q.data.context.pnl_cash_flow - q.data.net_cash_flow) > 1 && (
                  <span className="ml-2 text-danger">
                    Δ {fmtRub(q.data.net_cash_flow - q.data.context.pnl_cash_flow)}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {q.isLoading && <Skeleton variant="table" rows={6} />}

      {q.data &&
        q.data.sections.map((s) => (
          <section key={s.name} className={`card border-l-4 ${SECTION_META[s.name]?.color ?? ""}`}>
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="font-medium">{s.title}</h2>
              <span className={`font-mono text-lg ${s.total >= 0 ? "text-success" : "text-danger"}`}>
                {fmtRub(s.total)}
              </span>
            </div>
            <div className="text-xs text-muted mb-3">{SECTION_META[s.name]?.hint}</div>
            {s.lines.length === 0 && (
              <div className="text-muted text-sm">Нет операций в этой секции.</div>
            )}
            {s.lines.length > 0 && (
              <table className="w-full text-sm">
                <tbody>
                  {s.lines.map((l, i) => (
                    <tr key={i} className="border-t border-border">
                      <td className="p-2">{l.label}</td>
                      <td className={`p-2 text-right font-mono ${l.amount > 0 ? "text-success" : l.amount < 0 ? "text-danger" : "text-muted"}`}>
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
    </>
  );
}

// ── Страница ────────────────────────────────────────────────────────────────

const TABS = [
  { key: "article", label: "По статьям" },
  { key: "activity", label: "По виду деятельности" },
  { key: "counterparty", label: "По контрагентам" },
  { key: "management", label: "Управленческий (WB+OPEX)" },
] as const;

export default function CashFlow() {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("article");
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Отчет ДДС"
        subtitle="Движение денежных средств по операциям (банк/ручные) — как в TrueStats. Управленческий взгляд (WB+OPEX) — последняя вкладка."
      />
      <div className="inline-flex rounded-lg bg-soft p-1 text-sm w-fit flex-wrap">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`px-3 py-1.5 rounded-md ${tab === t.key ? "bg-white shadow-sm font-medium" : "text-muted"}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "management" ? (
        <ManagementCashFlow />
      ) : (
        <MatrixTab groupBy={tab} />
      )}
    </div>
  );
}
