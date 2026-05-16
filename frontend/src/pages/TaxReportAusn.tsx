import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";
import { DateRangePicker } from "@/components/DateRangePicker";
import PaymentOrdersTable from "@/components/PaymentOrdersTable";

function isoDate(d: Date) {
  return d.toISOString().slice(0, 10);
}

const MONTH_LABELS_RU: Record<string, string> = {
  "01": "Январь",
  "02": "Февраль",
  "03": "Март",
  "04": "Апрель",
  "05": "Май",
  "06": "Июнь",
  "07": "Июль",
  "08": "Август",
  "09": "Сентябрь",
  "10": "Октябрь",
  "11": "Ноябрь",
  "12": "Декабрь",
};

function monthLabel(yyyymm: string): string {
  if (yyyymm === "ИТОГО") return "ИТОГО";
  const [y, m] = yyyymm.split("-");
  return `${MONTH_LABELS_RU[m] ?? m} ${y}`;
}

export default function TaxReportAusn() {
  const today = useMemo(() => new Date(), []);
  const defaultTo = useMemo(() => isoDate(today), [today]);
  const defaultFrom = useMemo(() => {
    const d = new Date(today.getFullYear(), today.getMonth() - 5, 1);
    return isoDate(d);
  }, [today]);

  const [from, setFrom] = useState(defaultFrom);
  const [to, setTo] = useState(defaultTo);
  const [payOffsetDays, setPayOffsetDays] = useState(10);
  const [showDrillDown, setShowDrillDown] = useState(false);
  const [paySource, setPaySource] = useState<"auto" | "proxy" | "actual">(
    "auto",
  );
  const [showPaymentOrders, setShowPaymentOrders] = useState(false);
  const [importMsg, setImportMsg] = useState<string | null>(null);
  const [importErr, setImportErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["tax-report-ausn", from, to, payOffsetDays, paySource],
    queryFn: () => api.taxReportAusn(from, to, payOffsetDays, paySource),
  });

  const ordersQ = useQuery({
    queryKey: ["payment-orders", from, to],
    queryFn: () => api.paymentOrdersList(from, to),
  });

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setImportMsg(null);
    setImportErr(null);
    try {
      const r = await api.paymentOrdersImport(f);
      setImportMsg(
        `Загружено: ${r.rows_total} (новых ${r.rows_inserted}, обновлено ${r.rows_updated}` +
          (r.rows_skipped ? `, пропущено ${r.rows_skipped}` : "") +
          ")" +
          (r.errors?.length ? ` · ${r.errors.length} предупр.` : ""),
      );
      if (r.errors?.length) {
        setImportErr(r.errors.slice(0, 3).join(" · "));
      }
      qc.invalidateQueries({ queryKey: ["tax-report-ausn"] });
      qc.invalidateQueries({ queryKey: ["payment-orders"] });
    } catch (err: any) {
      setImportErr(err?.message || "Не удалось загрузить файл");
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function handleDelete(poid: string) {
    if (!confirm(`Удалить заявку ${poid}?`)) return;
    try {
      await api.paymentOrderDelete(poid);
      qc.invalidateQueries({ queryKey: ["tax-report-ausn"] });
      qc.invalidateQueries({ queryKey: ["payment-orders"] });
    } catch (e: any) {
      alert(e?.message || "Ошибка");
    }
  }

  const monthly = q.data?.monthly ?? [];
  const totals = q.data?.totals;
  const realizations = q.data?.realizations ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end gap-4">
        <h1 className="text-xl font-semibold">Налог АУСН «Доходы» (8 %)</h1>
        <span className="text-xs text-muted">
          Месячная свёртка по методике бухгалтера Стаса (xlsx «Разметка банка»)
        </span>
      </div>

      <div className="card text-xs text-muted leading-relaxed">
        <div className="font-medium text-white mb-1">Методика расчёта</div>
        <div>
          <code className="text-success">База месяца</code> ={" "}
          <code className="text-accent">Банк</code> +{" "}
          <code className="text-accent">ВЗЗ_отчёты</code> +{" "}
          <code className="text-accent">УПД_доставки</code>.{" "}
          <code className="text-warn">Налог = База × ставка</code> (АУСН-Доходы 8 %).
        </div>
        <ul className="list-disc ml-5 mt-2 space-y-1">
          <li>
            <b>Банк</b> — `ppvz_for_pay` net (Продажа − Возврат), привязан к
            месяцу по <i>дате зачисления денег WB → р/с</i>. Публичного API
            WB для реальных дат зачисления нет (страница «История платежей» в
            ЛК отдаётся private API), используется proxy:{" "}
            <code>report_date_to + N дней</code>. По умолчанию N = 10
            (типичный лаг между формированием заявки на оплату и фактическим
            переводом по данным «Истории платежей» в ЛК).
          </li>
          <li>
            <b>ВЗЗ отчёты</b> — для «Основных» отчётов: <code>retail_amount_net
            − ppvz_for_pay_net</code> = удержания WB (комиссия / логистика /
            хранение / штрафы), которые WB провёл взаимозачётом услуг. Для
            АУСН «Доходы» это тоже доход (встречная услуга = реализация).
            Привязка к месяцу — по <code>report_date_to</code>.
          </li>
          <li>
            <b>УПД доставки</b> — `wb_redeem_notification` (Уведомления о
            выкупе) с привязкой к месяцу по <code>notification_date</code>.
          </li>
          <li>
            <b>Возвраты Выкупы</b> — справочно, в базу налога <i>не входят</i>
            (АУСН-Доходы не уменьшает доход на возвраты в этой методике).
          </li>
        </ul>
        <div className="mt-2">
          Сумма <code>Банк + ВЗЗ ≈ retail_amount_gross</code> — то есть
          фактически налог берётся с полной выручки, разделение нужно только
          для документального подтверждения каждой части перед ФНС.
        </div>
      </div>

      <section className="card flex flex-wrap gap-4 items-end">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Период</span>
          <DateRangePicker
            from={from}
            to={to}
            onChange={(r) => { setFrom(r.from); setTo(r.to); }}
          />
        </div>
        <label className="flex flex-col gap-1">
          <span
            className="text-xs text-muted uppercase"
            title="Сколько дней прибавлять к report_date_to для proxy даты зачисления денег WB → р/с. По данным «Истории платежей» в ЛК WB типичный лаг 7-11 дней; default 10. На каникулах может растягиваться до 20 дней."
          >
            Pay offset (дни)
          </span>
          <input
            type="number"
            min={0}
            max={60}
            className="input w-24"
            value={payOffsetDays}
            onChange={(e) => setPayOffsetDays(Number(e.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span
            className="text-xs text-muted uppercase"
            title="auto: фактическая дата если есть импорт «Истории платежей», иначе proxy. proxy: всегда proxy. actual: только импорт (если нет — Банк = 0)."
          >
            Источник Банка
          </span>
          <select
            className="input"
            value={paySource}
            onChange={(e) => setPaySource(e.target.value as any)}
          >
            <option value="auto">Авто</option>
            <option value="proxy">Proxy (offset)</option>
            <option value="actual">Факт (XLSX)</option>
          </select>
        </label>
        <label className="flex items-center gap-2 ml-auto text-xs">
          <input
            type="checkbox"
            checked={showDrillDown}
            onChange={(e) => setShowDrillDown(e.target.checked)}
          />
          Показать отчёты (drill-down)
        </label>
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={showPaymentOrders}
            onChange={(e) => setShowPaymentOrders(e.target.checked)}
          />
          Показать «Историю платежей»
        </label>
        <div className="text-xs text-muted">
          {q.isLoading && "Загрузка…"}
          {!q.isLoading && q.data && `Месяцев: ${monthly.length}`}
        </div>
      </section>

      {q.data && (
        <section className="card flex flex-wrap items-center gap-4 text-xs">
          <div>
            <span className="text-muted uppercase mr-2">Сейчас Банк по:</span>
            <span
              className={
                q.data.pay_date_source_effective === "actual"
                  ? "text-success font-medium"
                  : "text-warn"
              }
            >
              {q.data.pay_date_source_effective === "actual"
                ? `факту (${q.data.payment_orders_paid_count} заявок)`
                : `proxy (+${q.data.pay_offset_days} дн)`}
            </span>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx,.xls"
              onChange={handleFile}
              className="text-xs"
            />
            <a
              className="text-accent underline"
              href="https://seller.wildberries.ru/payment-history/active"
              target="_blank"
              rel="noopener noreferrer"
              title="Откроется ЛК WB. Кнопка «Экспорт в Excel» в правом верхнем углу таблицы."
            >
              Открыть «Историю платежей» в ЛК WB
            </a>
          </div>
          {importMsg && (
            <div className="basis-full text-success">{importMsg}</div>
          )}
          {importErr && (
            <div className="basis-full text-error">{importErr}</div>
          )}
          <details className="basis-full text-muted leading-relaxed">
            <summary className="cursor-pointer">Как загрузить (формат файла)</summary>
            <div className="mt-2 ml-4">
              <ol className="list-decimal ml-5 space-y-1">
                <li>
                  В ЛК WB открой <b>Финансы → История платежей → Архив</b>{" "}
                  (или сразу <b>Активные</b>, если интересуют недавние).
                </li>
                <li>
                  Выбери период (можно за весь год — повторный импорт
                  идемпотентен по ID заявки).
                </li>
                <li>
                  Нажми <b>Экспорт в Excel</b> (кнопка в правом верхнем
                  углу таблицы) — скачается .xlsx.
                </li>
                <li>
                  Загрузи файл сюда. Парсер найдёт колонки по заголовку
                  (порядок неважен): <code>ID заявки на оплату</code>,{" "}
                  <code>Сумма</code>, <code>Валюта</code>,{" "}
                  <code>Дата создания</code>, <code>Статус оплаты</code>,{" "}
                  <code>Комментарий банка</code>.
                </li>
                <li>
                  Дата зачисления извлекается из «Статус оплаты»
                  (фрагмент <code>DD.MM.YYYY</code>). «Оплата
                  обрабатывается» сохраняется со статусом{" "}
                  <code>processing</code> и пустой <code>paid_dt</code>.
                </li>
                <li>
                  Когда загружены все месяцы периода — переключи{" "}
                  <b>Источник Банка → Факт (XLSX)</b> или оставь{" "}
                  <b>Авто</b> (само переключится, если данные за месяц
                  есть).
                </li>
              </ol>
            </div>
          </details>
        </section>
      )}

      {totals && (
        <section className="card grid grid-cols-2 md:grid-cols-5 gap-4">
          <KpiBlock label="Банк (итого)" value={totals.bank} color="text-muted" />
          <KpiBlock
            label="ВЗЗ отчёты (итого)"
            value={totals.vzz_reports}
            color="text-muted"
          />
          <KpiBlock
            label="УПД доставки (итого)"
            value={totals.upd_delivery}
            color="text-muted"
          />
          <KpiBlock label="База (итого)" value={totals.base} color="text-success" />
          <KpiBlock
            label="Налог к уплате"
            value={totals.tax}
            color="text-accent"
            big
          />
        </section>
      )}

      <section className="card overflow-auto">
        <h2 className="font-medium mb-3">Месячная свёртка</h2>
        <table className="min-w-full text-xs">
          <thead className="sticky top-0 bg-surface-2 border-b border-border z-10">
            <tr>
              <th className="text-left py-2 px-2">Месяц</th>
              <th className="text-right py-2 px-2 text-muted">Банк</th>
              <th className="text-right py-2 px-2 text-muted">ВЗЗ отчёты</th>
              <th className="text-right py-2 px-2 text-muted">УПД доставки</th>
              <th className="text-right py-2 px-2 text-success">База</th>
              <th className="text-right py-2 px-2">Ставка</th>
              <th className="text-right py-2 px-2 text-accent">Налог</th>
              <th
                className="text-right py-2 px-2 text-muted"
                title="Возвраты по выкупам — справочно, в базу не входят"
              >
                Возвраты (спр.)
              </th>
              <th
                className="text-right py-2 px-2 text-muted"
                title="Сколько отчётов реализации попало в Bank-агрегат за этот месяц"
              >
                Отч.
              </th>
            </tr>
          </thead>
          <tbody>
            {monthly.map((r) => (
              <tr key={r.month} className="border-b border-border/40 hover:bg-surface-2/60">
                <td className="py-2 px-2 font-medium">{monthLabel(r.month)}</td>
                <td className="py-2 px-2 text-right">{fmtRub(r.bank)}</td>
                <td className="py-2 px-2 text-right">{fmtRub(r.vzz_reports)}</td>
                <td className="py-2 px-2 text-right">{fmtRub(r.upd_delivery)}</td>
                <td className="py-2 px-2 text-right text-success font-medium">
                  {fmtRub(r.base)}
                </td>
                <td className="py-2 px-2 text-right text-muted">
                  {r.tax_rate.toFixed(1)}%
                </td>
                <td className="py-2 px-2 text-right text-accent font-medium">
                  {fmtRub(r.tax)}
                </td>
                <td className="py-2 px-2 text-right text-muted/60 italic">
                  {fmtRub(r.buyback_returns)}
                </td>
                <td className="py-2 px-2 text-right text-muted">
                  {r.realizations_count}
                </td>
              </tr>
            ))}
            {totals && (
              <tr className="border-t-2 border-border bg-surface-2/40 font-semibold">
                <td className="py-2 px-2">{monthLabel(totals.month)}</td>
                <td className="py-2 px-2 text-right">{fmtRub(totals.bank)}</td>
                <td className="py-2 px-2 text-right">
                  {fmtRub(totals.vzz_reports)}
                </td>
                <td className="py-2 px-2 text-right">
                  {fmtRub(totals.upd_delivery)}
                </td>
                <td className="py-2 px-2 text-right text-success">
                  {fmtRub(totals.base)}
                </td>
                <td className="py-2 px-2 text-right text-muted">—</td>
                <td className="py-2 px-2 text-right text-accent">
                  {fmtRub(totals.tax)}
                </td>
                <td className="py-2 px-2 text-right text-muted/60 italic">
                  {fmtRub(totals.buyback_returns)}
                </td>
                <td className="py-2 px-2 text-right text-muted">
                  {totals.realizations_count}
                </td>
              </tr>
            )}
            {!q.isLoading && monthly.length === 0 && (
              <tr>
                <td colSpan={9} className="text-center text-muted py-4">
                  Нет данных за выбранный период
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      {showDrillDown && realizations.length > 0 && (
        <section className="card overflow-auto">
          <h2 className="font-medium mb-3">
            По отчётам реализации ({realizations.length})
          </h2>
          <table className="min-w-full text-xs">
            <thead className="sticky top-0 bg-surface-2 border-b border-border z-10">
              <tr>
                <th className="text-left py-2 px-2">Отчёт WB</th>
                <th className="text-left py-2 px-2">Период</th>
                <th className="text-left py-2 px-2 text-muted">Тип</th>
                <th
                  className="text-left py-2 px-2 text-muted"
                  title="report_date_to + pay_offset_days — proxy даты зачисления денег WB → р/с"
                >
                  Pay date (proxy)
                </th>
                <th className="text-left py-2 px-2 text-muted">Месяц</th>
                <th
                  className="text-right py-2 px-2 text-muted"
                  title="retail_amount net (Продажа − Возврат)"
                >
                  Продажа
                </th>
                <th
                  className="text-right py-2 px-2"
                  title="ppvz_for_pay net = Итого к оплате"
                >
                  Банк
                </th>
                <th
                  className="text-right py-2 px-2 text-muted"
                  title="Продажа − Банк = удержания WB через взаимозачёт услуг"
                >
                  ВЗЗ
                </th>
              </tr>
            </thead>
            <tbody>
              {realizations.map((r) => (
                <tr
                  key={r.realization_id}
                  className="border-b border-border/40 hover:bg-surface-2/60"
                >
                  <td className="py-2 px-2 font-mono">#{r.realization_id}</td>
                  <td className="py-2 px-2 text-muted">
                    {r.report_date_from} … {r.report_date_to}
                  </td>
                  <td className="py-2 px-2 text-muted">{r.report_type}</td>
                  <td className="py-2 px-2 text-muted">{r.pay_date_proxy}</td>
                  <td className="py-2 px-2 text-muted">{monthLabel(r.month)}</td>
                  <td className="py-2 px-2 text-right text-muted">
                    {fmtRub(r.sale_gross)}
                  </td>
                  <td className="py-2 px-2 text-right">{fmtRub(r.bank_amount)}</td>
                  <td className="py-2 px-2 text-right text-muted">
                    {fmtRub(r.vzz_amount)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {showPaymentOrders && (
        <section className="card overflow-auto">
          <div className="flex items-center mb-3">
            <h2 className="font-medium">
              История платежей (импорт XLSX) ·{" "}
              {ordersQ.data?.totals.count ?? 0} заявок
            </h2>
            <div className="ml-auto text-xs text-muted">
              Зачислено:{" "}
              <span className="text-success">
                {fmtRub(ordersQ.data?.totals.paid_sum ?? 0)}
              </span>{" "}
              · В обработке:{" "}
              <span className="text-warn">
                {fmtRub(ordersQ.data?.totals.processing_sum ?? 0)}
              </span>
            </div>
          </div>
          <PaymentOrdersTable
            items={ordersQ.data?.items ?? []}
            scope="ausn"
            onDelete={handleDelete}
          />
          {(ordersQ.data?.items ?? []).length === 0 && (
            <div className="text-center text-muted py-4">
              Заявок за выбранный период нет — загрузите XLSX выше.
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function KpiBlock({
  label,
  value,
  color,
  big,
}: {
  label: string;
  value: number;
  color?: string;
  big?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <div className="text-xs text-muted uppercase">{label}</div>
      <div className={`${big ? "text-2xl" : "text-lg"} font-semibold ${color || ""}`}>
        {fmtRub(value)}
      </div>
    </div>
  );
}
