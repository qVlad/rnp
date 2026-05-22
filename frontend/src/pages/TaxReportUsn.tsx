import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { DateRangePicker } from "@/components/DateRangePicker";
import PaymentOrdersTable from "@/components/PaymentOrdersTable";
import { fmtRub } from "@/lib/format";
import { usePeriod } from "@/contexts/PeriodContext";
import PageHeader from "@/components/PageHeader";

function isoDate(d: Date) {
  return d.toISOString().slice(0, 10);
}

/**
 * Универсальная страница УСН-Доходы с опциональным невозвратным НДС.
 * Один экспорт-default — обычная УСН-6% без НДС.
 * `TaxReportUsnVat5` / `TaxReportUsnVat7` — с НДС 5/7%.
 */
function UsnPage({ vatRate, title }: { vatRate: number; title: string }) {
  const today = useMemo(() => new Date(), []);
  const defaultTo = useMemo(() => isoDate(today), [today]);
  const defaultFrom = useMemo(() => {
    const d = new Date(today.getFullYear(), today.getMonth() - 5, 1);
    return isoDate(d);
  }, [today]);

  // TASK-UI-005: глобальный период.
  const { range, setPeriod } = usePeriod();
  const from = range.from;
  const to = range.to;
  void defaultFrom;
  void defaultTo;
  const [taxRate, setTaxRate] = useState<string>("6");
  const [showPaymentOrders, setShowPaymentOrders] = useState(false);

  const q = useQuery<any>({
    queryKey: ["tax-report-usn", from, to, taxRate, vatRate],
    queryFn: () =>
      api.taxReportUsn(from, to, taxRate === "" ? undefined : Number(taxRate), vatRate),
  });
  const d: any = q.data;
  const totals = d?.totals;

  const ordersQ = useQuery<any>({
    queryKey: ["payment-orders", from, to],
    queryFn: () => api.paymentOrdersList(from, to),
    enabled: showPaymentOrders,
  });

  const hasVat = vatRate > 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title={title}
        subtitle={
          <>
            Налоговый отчёт по методике бухгалтера: cash-basis для выкупных
            отчётов, accrual (по дате реализации) для основных отчётов.
            {hasVat && (
              <>
                {" "}Невозвратный НДС {vatRate}% выделяется ИЗ цены, УСН
                считается с net (gross − НДС). Общая нагрузка = УСН + НДС.
              </>
            )}
          </>
        }
      />

      <section className="card text-xs text-muted">
        <strong className="text-fg">Формула:</strong>{" "}
        <code>
          База_gross = Отчёты_реализации (G) + Тов_компенсация (Y) +
          Банк_выкупы (T) + УПД_доставки (Z) + Возвраты_выкупы (AA)
        </code>
        {hasVat ? (
          <>
            <br />
            <strong className="text-fg">НДС:</strong>{" "}
            <code>База_gross × {vatRate} / (100 + {vatRate})</code>
            <br />
            <strong className="text-fg">УСН-база:</strong>{" "}
            <code>База_gross − НДС</code>
            <br />
            <strong className="text-fg">УСН:</strong>{" "}
            <code>УСН-база × ставка</code> (по умолчанию 6%)
            <br />
            <strong className="text-fg">Итого:</strong>{" "}
            <code>УСН + НДС</code> (общая налоговая нагрузка)
          </>
        ) : (
          <>
            <br />
            <strong className="text-fg">Налог:</strong> База × ставка (по умолчанию 6%).
          </>
        )}
        <br />
        <span>
          Источник данных: <code>wb_report_detail</code> (для G, Y) +{" "}
          <code>wb_payment_order</code> (для T, Z, AA — импорт XLSX).
        </span>
      </section>

      <section className="card flex flex-wrap gap-4 items-end">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Период</span>
          <DateRangePicker
            from={from}
            to={to}
            onChange={(r) =>
              setPeriod({ kind: "custom", from: r.from, to: r.to })
            }
          />
        </div>
        <label className="flex flex-col gap-1">
          <span
            className="text-xs text-muted uppercase"
            title="Ставка УСН-Доходы. Default 6%. Можно сменить если у тебя пониженная региональная ставка."
          >
            Ставка УСН, %
          </span>
          <input
            type="number"
            min={0}
            max={20}
            step={0.1}
            className="input w-24"
            value={taxRate}
            onChange={(e) => setTaxRate(e.target.value)}
          />
        </label>
        {hasVat && (
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted uppercase">Ставка НДС</span>
            <div className="input w-24 cursor-not-allowed text-muted">{vatRate}%</div>
          </div>
        )}
        {totals && (
          <div className="ml-auto text-xs text-muted">
            <div>
              База gross:{" "}
              <span className="font-mono text-fg">{fmtRub(totals.base_gross)}</span>
            </div>
            {hasVat && (
              <>
                <div>
                  НДС ({vatRate}%):{" "}
                  <span className="font-mono text-warn">{fmtRub(totals.vat)}</span>
                </div>
                <div>
                  База УСН (net):{" "}
                  <span className="font-mono text-fg">{fmtRub(totals.base)}</span>
                </div>
              </>
            )}
            <div>
              УСН ({totals.tax_rate || taxRate}%):{" "}
              <span className="font-mono text-fg">{fmtRub(totals.tax)}</span>
            </div>
            {hasVat && (
              <div className="mt-1 pt-1 border-t border-border">
                Итого налог:{" "}
                <span className="font-mono text-fg font-medium">
                  {fmtRub(totals.total_tax)}
                </span>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="card overflow-x-auto">
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.error && (
          <div className="text-danger">Ошибка: {String((q.error as any).message)}</div>
        )}
        {d && (
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-muted">
              <tr>
                <th className="text-left p-2">Месяц</th>
                <th className="text-right p-2" title="Сумма retail_amount net для «Основной» отчётов по period_end">
                  Отчёты реализации (G)
                </th>
                <th className="text-right p-2" title="Добровольная компенсация при возврате (ppvz)">
                  Тов. комп. (Y)
                </th>
                <th className="text-right p-2" title="Итого к оплате для «По выкупам» по paid_dt">
                  Банк выкупы (T)
                </th>
                <th className="text-right p-2" title="УПД доставки для «По выкупам» по period_start">
                  УПД (Z)
                </th>
                <th className="text-right p-2" title="Возвраты выкупы по period_start">
                  Возвр. (AA)
                </th>
                <th className="text-right p-2 font-semibold">
                  База {hasVat ? "gross" : ""}
                </th>
                {hasVat && (
                  <>
                    <th className="text-right p-2 text-warn">НДС</th>
                    <th className="text-right p-2 font-semibold">База нетто</th>
                  </>
                )}
                <th className="text-right p-2 font-semibold">УСН</th>
                {hasVat && (
                  <th className="text-right p-2 font-semibold">Итого</th>
                )}
              </tr>
            </thead>
            <tbody>
              {d.monthly.map((row: any) => (
                <tr key={row.month} className="border-t border-border">
                  <td className="p-2 font-mono">{row.month}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(row.sale_realization)}</td>
                  <td className="p-2 text-right font-mono">
                    {row.tovar_compensation > 0 ? fmtRub(row.tovar_compensation) : <span className="text-muted">—</span>}
                  </td>
                  <td className="p-2 text-right font-mono">{fmtRub(row.bank_buyout)}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(row.upd_delivery)}</td>
                  <td className="p-2 text-right font-mono">
                    {row.buyout_returns > 0 ? fmtRub(row.buyout_returns) : <span className="text-muted">—</span>}
                  </td>
                  <td className="p-2 text-right font-mono font-semibold">
                    {fmtRub(hasVat ? row.base_gross : row.base)}
                  </td>
                  {hasVat && (
                    <>
                      <td className="p-2 text-right font-mono text-warn">{fmtRub(row.vat)}</td>
                      <td className="p-2 text-right font-mono font-semibold">{fmtRub(row.base)}</td>
                    </>
                  )}
                  <td className="p-2 text-right font-mono font-semibold">{fmtRub(row.tax)}</td>
                  {hasVat && (
                    <td className="p-2 text-right font-mono font-semibold text-accent">
                      {fmtRub(row.total_tax)}
                    </td>
                  )}
                </tr>
              ))}
              {d.totals && (
                <tr className="border-t-2 border-border bg-surface-2/40 font-semibold">
                  <td className="p-2">Итого</td>
                  <td className="p-2 text-right font-mono">{fmtRub(d.totals.sale_realization)}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(d.totals.tovar_compensation)}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(d.totals.bank_buyout)}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(d.totals.upd_delivery)}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(d.totals.buyout_returns)}</td>
                  <td className="p-2 text-right font-mono">
                    {fmtRub(hasVat ? d.totals.base_gross : d.totals.base)}
                  </td>
                  {hasVat && (
                    <>
                      <td className="p-2 text-right font-mono text-warn">{fmtRub(d.totals.vat)}</td>
                      <td className="p-2 text-right font-mono">{fmtRub(d.totals.base)}</td>
                    </>
                  )}
                  <td className="p-2 text-right font-mono">{fmtRub(d.totals.tax)}</td>
                  {hasVat && (
                    <td className="p-2 text-right font-mono text-accent">
                      {fmtRub(d.totals.total_tax)}
                    </td>
                  )}
                </tr>
              )}
            </tbody>
          </table>
        )}
      </section>

      <section className="card text-xs text-muted">
        <div>
          <strong className="text-fg">Сравни с другими режимами:</strong>{" "}
          <a className="text-accent underline" href="/tax-report-ausn">АУСН 8%</a>
          {" · "}
          <a className="text-accent underline" href="/tax-report-usn">УСН 6% без НДС</a>
          {" · "}
          <a className="text-accent underline" href="/tax-report-usn-vat5">УСН 6% + НДС 5%</a>
          {" · "}
          <a className="text-accent underline" href="/tax-report-usn-vat7">УСН 6% + НДС 7%</a>
        </div>
        <div className="mt-2">
          <strong className="text-fg">Что нужно загрузить:</strong> XLSX в формате «Стас Разметка банка»
          с колонками <code>№ отчёта, Дата конца, Тип отчёта, Дата оплаты, Итого к оплате, УПД доставки, Возвраты выкупы</code>.
          Импорт — через страницу <a href="/tax-report-ausn" className="text-accent underline">АУСН-Доходы 8%</a>.
        </div>
        {hasVat && (
          <div className="mt-2">
            <strong className="text-fg">О режиме:</strong> УСН с невозвратным НДС
            действует с 2025 года (176-ФЗ от 12.07.2024) для селлеров с оборотом
            более 60 млн ₽/год. Ставки НДС: 5% (при доходах 60–250M) или 7%
            (при 250–450M); ставку выбирает налогоплательщик в течение 3 лет.
            «Невозвратный» = нельзя вычесть входящий НДС, только начислить выходящий.
          </div>
        )}
      </section>

      <section className="card">
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={showPaymentOrders}
            onChange={(e) => setShowPaymentOrders(e.target.checked)}
          />
          <span>Показать заявки WB (для ручного исключения из базы)</span>
        </label>
      </section>

      {showPaymentOrders && (
        <section className="card overflow-auto">
          <div className="text-xs text-muted mb-3">
            Флаг «Исключить из УСН» действует на всех УСН-страницах сразу (с НДС и без).
            Наведи курсор на заголовок столбца — подсказка.
          </div>
          <PaymentOrdersTable
            items={ordersQ.data?.items ?? []}
            scope="usn"
            showExtendedColumns
          />
          {(ordersQ.data?.items ?? []).length === 0 && (
            <div className="text-center text-muted py-4">
              Заявок за выбранный период нет — загрузите XLSX на странице АУСН.
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export default function TaxReportUsn() {
  return <UsnPage vatRate={0} title="УСН-Доходы 6% (без НДС)" />;
}

export function TaxReportUsnVat5() {
  return <UsnPage vatRate={5} title="УСН-Доходы 6% + невозвратный НДС 5%" />;
}

export function TaxReportUsnVat7() {
  return <UsnPage vatRate={7} title="УСН-Доходы 6% + невозвратный НДС 7%" />;
}
