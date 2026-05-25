import React, { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtPct, fmtRatio } from "@/lib/format";
import PageHeader from "@/components/PageHeader";
import ReportingModeBadge from "@/components/ReportingModeBadge";

// WB seller cabinet — раздел финансовых отчётов реализации.
// Прямого URL на конкретный realization_id у WB нет — селлер открывает
// общий список и фильтрует по ID.
const WB_FINANCE_REPORTS_URL =
  "https://seller.wildberries.ru/realization-reports/main";

export default function PnLReconciliation() {
  const [weeks, setWeeks] = useState(12);
  const [threshold, setThreshold] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["pnl-reconciliation", weeks, threshold],
    queryFn: () => api.pnlReconciliation(weeks, threshold),
  });

  const periods = q.data?.periods ?? [];
  const totals = q.data?.totals;
  const loadedWeeks = periods.length;
  const hasPartialHistory = !q.isLoading && loadedWeeks > 0 && loadedWeeks < weeks;

  // TASK-LEAD-063 — deep-link: `#period=YYYY-MM-DD_YYYY-MM-DD` от
  // ReconciliationHeroWidget. На load автоматически раскрываем wizard
  // соответствующей строки + скроллим к ней. Если hash пустой / не парсится
  // / неделя не в текущем окне — silent skip (обычное поведение).
  useEffect(() => {
    if (!periods.length) return;
    const hash = window.location.hash || "";
    const m = hash.match(/period=(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})/);
    if (!m) return;
    const [, from, to] = m;
    const match = periods.find(
      (p: any) => p.period_from === from && p.period_to === to,
    );
    if (!match) return;
    const key = `${match.period_from}-${match.period_to}`;
    setExpanded(key);
    // отложим scroll до того момента когда DOM перерисуется с раскрытой строкой
    requestAnimationFrame(() => {
      const el = document.getElementById(`recon-row-${key}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.data]);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={
          <span className="inline-flex items-center gap-3 flex-wrap">
            <span>Сверка с WB</span>
            <ReportingModeBadge />
          </span>
        }
        subtitle="сравнение нашей P&L с финальным отчётом WB по каждой неделе"
        actions={
          <a
            href="/docs/reconciliation"
            className="btn text-xs"
            title="Методика сверки P&L с WB (TASK-LEAD-095)"
          >
            📖 Методика
          </a>
        }
      />

      <div className="card text-xs text-muted leading-relaxed">
        <div className="font-medium text-white mb-1">Как пользоваться</div>
        Каждая строка — закрытая неделя WB (понедельник→воскресенье).
        В столбцах <span className="text-warn">WB:</span> — то что WB прислал в
        отчёте реализации, наша «истина в последней инстанции». В столбцах{" "}
        <span className="text-success">Наша:</span> — наш расчёт P&L за тот же
        период. Если <b>Δ Выручка</b> &gt; порога — строка подсвечена красным
        (несовпадение, копать в audit-log или backfill). <b>Доля выплаты</b>{" "}
        (Payout / gross) — какой % gross-выручки реально дошёл до селлера после
        WB-удержаний; норма 25-40 % для маркетплейса.
        <div className="mt-2 text-accent">
          <Icon name="info" size={12} /> <b>Кликни на строку</b> — откроется пошаговая сверка с прямой ссылкой
          в WB-кабинет: куда смотреть и какие поля сличать.
        </div>
        <span className="text-accent">
          Все термины → <a href="/glossary" className="underline">/glossary</a>
        </span>
      </div>

      <section className="card flex flex-wrap gap-4 items-end">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Глубина</span>
          <select
            className="input"
            value={weeks}
            onChange={(e: any) => setWeeks(Number(e.target.value))}
          >
            <option value={4}>4 недели</option>
            <option value={8}>8 недель</option>
            <option value={12}>12 недель</option>
            <option value={26}>26 недель</option>
            <option value={52}>52 недели</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Порог алерта, %</span>
          <input
            type="number"
            className="input"
            step="0.1"
            min="0"
            value={threshold}
            onChange={(e: any) => setThreshold(Number(e.target.value))}
          />
        </label>
        {q.data && (
          <div className="text-xs text-muted max-w-md">
            <div>
              Найдено <span className="text-white font-medium">{loadedWeeks}</span>{" "}
              закрытых WB-недель в окне{" "}
              <span className="text-white font-medium">{weeks}</span> недель.
            </div>
            {hasPartialHistory && (
              <div className="mt-1 text-warn">
                Пустые недели не рисуются: для них ещё нет загруженного отчёта
                реализации WB или период ещё не закрыт.
              </div>
            )}
          </div>
        )}
        {totals && (
          <div className="ml-auto text-sm flex gap-4">
            <Stat label="WB: Выручка (gross)" value={totals.wb_revenue_gross} />
            <Stat label="WB: К перечислению" value={totals.wb_payout} />
            <Stat label="Наша: Выручка (gross)" value={totals.ours_revenue_gross} />
            <Stat label="Наша: Чистая прибыль" value={totals.ours_profit} />
            <Stat
              label="Алертов"
              value={totals.alerts_count}
              danger={totals.alerts_count > 0}
              raw
            />
          </div>
        )}
      </section>

      {q.isLoading && <div className="text-muted text-sm">Загрузка…</div>}
      {q.isError && (
        <div className="card text-danger text-sm">
          Ошибка: {(q.error as Error).message}
        </div>
      )}

      {!q.isLoading && periods.length === 0 && (
        <div className="card text-muted text-sm">
          Нет данных — `wb_report_detail` пустой. Запустите синхронизацию
          «Отчёт реализации» в Настройках. Отчёт появляется в WB с задержкой
          1-2 дня после закрытия отчётной недели.
        </div>
      )}

      {periods.length > 0 && (
        <section className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2 sticky left-0 bg-surface">Период</th>
                <th
                  className="text-left p-2"
                  title="ID отчётов реализации WB за неделю (если их несколько — WB разбил период на части)"
                >
                  ID отчёта
                </th>
                <th className="text-right p-2 text-warn">WB: Выручка (gross)</th>
                <th className="text-right p-2 text-warn">WB: Возвраты</th>
                <th className="text-right p-2 text-warn">WB: Комиссия</th>
                <th className="text-right p-2 text-warn">WB: К перечислению</th>
                <th
                  className="text-right p-2"
                  title="WB удержания: логистика + хранение + штрафы + удержания + эквайринг − доплаты"
                >
                  WB удержания
                </th>
                <th className="text-right p-2 text-success">Наша: Выручка</th>
                <th className="text-right p-2 text-success">Наша: Чистая выручка</th>
                <th className="text-right p-2 text-success">Наша: Чистая прибыль</th>
                <th className="text-right p-2" title="Расхождение нашей gross-выручки с WB, в рублях">Δ Выручка, ₽</th>
                <th className="text-right p-2" title="Расхождение нашей gross-выручки с WB, в %">Δ Выручка, %</th>
                <th
                  className="text-right p-2"
                  title="Payout / gross — какой % gross-выручки реально дошёл до селлера после WB-удержаний"
                >
                  Доля выплаты
                </th>
              </tr>
            </thead>
            <tbody>
              {periods.map((p) => {
                const fees =
                  p.wb.delivery + p.wb.storage + p.wb.penalty +
                  p.wb.deduction + p.wb.acquiring - p.wb.additional;
                const key = `${p.period_from}-${p.period_to}`;
                const isOpen = expanded === key;
                return (
                  <React.Fragment key={key}>
                  <tr
                    id={`recon-row-${key}`}
                    className={`border-t border-border cursor-pointer hover:bg-surface-2/50 ${
                      p.diff.alert ? "bg-danger/10" : ""
                    }`}
                    onClick={() => setExpanded(isOpen ? null : key)}
                    title={isOpen ? "Свернуть детали" : "Открыть сверку шаг-за-шагом"}
                  >
                    <td className="p-2 sticky left-0 bg-surface whitespace-nowrap">
                      <span className="text-muted mr-1 inline-block w-3">
                        {isOpen ? "▾" : "▸"}
                      </span>
                      {p.period_from} — {p.period_to}
                    </td>
                    <td className="p-2 font-mono text-xs">
                      {p.realizations_count}
                      <div className="text-muted">{p.realization_ids}</div>
                    </td>
                    <td className="p-2 text-right font-mono">{fmtRub(p.wb.revenue_gross)}</td>
                    <td className="p-2 text-right text-muted font-mono">
                      {p.wb.revenue_returns ? fmtRub(p.wb.revenue_returns) : "—"}
                    </td>
                    <td className="p-2 text-right font-mono">{fmtRub(p.wb.commission)}</td>
                    <td className="p-2 text-right font-medium font-mono">
                      {fmtRub(p.wb.payout)}
                    </td>
                    <td className="p-2 text-right text-muted font-mono">{fmtRub(fees)}</td>
                    <td className="p-2 text-right font-mono">{fmtRub(p.ours.revenue_gross)}</td>
                    <td className="p-2 text-right font-mono">{fmtRub(p.ours.revenue_net)}</td>
                    <td
                      className={`p-2 text-right font-medium ${
                        p.ours.profit >= 0 ? "text-success" : "text-danger"
                      }`}
                    >
                      {fmtRub(p.ours.profit)}
                    </td>
                    <td
                      className={`p-2 text-right ${
                        Math.abs(p.diff.revenue_gross_abs) > 0.5
                          ? "text-danger"
                          : "text-muted"
                      }`}
                    >
                      {fmtRatio(p.diff.revenue_gross_abs, 2)}
                    </td>
                    <td
                      className={`p-2 text-right ${
                        p.diff.alert ? "text-danger font-bold" : "text-muted"
                      }`}
                    >
                      {fmtPct(p.diff.revenue_gross_pct, 2)}
                    </td>
                    <td
                      className={`p-2 text-right ${
                        p.diff.payout_to_gross_pct < 60
                          ? "text-warn"
                          : "text-muted"
                      }`}
                      title="Какая доля gross-выручки реально доходит до селлера после комиссий WB"
                    >
                      {fmtPct(p.diff.payout_to_gross_pct, 1)}
                    </td>
                  </tr>
                  {isOpen && <WizardRow p={p} fees={fees} />}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
          <div className="mt-3 text-xs text-muted">
            <strong>Δ gross</strong> — расхождение нашего <code>revenue_gross</code>{" "}
            с WB-сторонним sum по «Продажам». Норма ≈ 0 (один источник).
            Если &gt; порога — где-то потеряны строки или несинхронизированы
            doc_type регистры.{" "}
            <strong>Payout / gross</strong> — какая доля от gross-выручки
            реально доходит до селлера на счёт после удержаний WB
            (комиссия + логистика + хранение + штрафы + эквайринг). Чем выше %,
            тем больше остаётся селлеру. Подсветка жёлтым если &lt; 60%.
            +услуги = доставка+хранение+штрафы+удержания+эквайринг−доплаты.
          </div>
        </section>
      )}

      <style>{`.input { background: #13161d; border: 1px solid #262a35; border-radius: 6px; padding: 8px 10px; font-size: 14px; color: white; }`}</style>
    </div>
  );
}

function Stat({
  label,
  value,
  danger,
  raw,
}: {
  label: string;
  value: number;
  danger?: boolean;
  raw?: boolean;
}) {
  return (
    <div className="flex flex-col items-end">
      <span className="text-xs text-muted uppercase">{label}</span>
      <span className={`font-medium ${danger ? "text-danger" : ""}`}>
        {raw ? value : fmtRub(value)}
      </span>
    </div>
  );
}

// Wizard-row — раскрывается при клике на неделю. Шаг-за-шагом сверка
// с WB-кабинетом: какие поля сличать и что значит расхождение.
function WizardRow({ p, fees }: { p: any; fees: number }) {
  // ВАЖНО: формулы сторон должны быть симметричны (apples-to-apples).
  //
  // 1) Выручка net (Продажи − Возвраты): обе стороны — сумма retail_with_disc.
  //    WB: revenue_gross − revenue_returns (по report_date_to)
  //    Наша: revenue_gross − revenue_returns (по sale_dt) — НЕ revenue_net,
  //    т.к. revenue_net включает manual adjustments (dbs, selfbuy) которых
  //    в WB-данных нет — это дало бы фейковую дельту.
  //
  // 2) Комиссия + эквайринг: WB-side commission = revenue_net − ppvz_for_pay
  //    (т.к. WB уже вычел и комиссию, и эквайринг до ppvz_for_pay). Наша
  //    side хранит их раздельно: commission (без эквайринга) + acquiring.
  //    Сумма обоих = WB.commission.
  //
  // 3) Чистая выручка (ppvz_for_pay) — фактическое перечисление селлеру
  //    после WB-удержаний. Обе стороны: sum(ppvz_for_pay net Продажа−Возврат).
  //    Раньше тут сравнивали wb.payout vs ours.revenue_net — РАЗНЫЕ ПОНЯТИЯ.
  const checks: { label: string; wb: number; ours: number; tolerance?: number; note?: string }[] = [
    {
      label: "Выручка (Продажи − Возвраты)",
      wb: p.wb.revenue_gross - p.wb.revenue_returns,
      ours: (p.ours.revenue_gross || 0) - (p.ours.revenue_returns || 0),
      tolerance: 1.0,
      note: "В WB-кабинете это строка «Реализация» (Продажи − Возвраты).",
    },
    {
      label: "Комиссия WB и эквайринг",
      wb: p.wb.commission,
      ours: (p.ours.commission || 0) + (p.ours.acquiring || 0),
      tolerance: 1.0,
      note: "WB: revenue_net − ppvz_for_pay (включает эквайринг). Наша: commission + acquiring.",
    },
    {
      label: "Чистая выручка (ppvz_for_pay)",
      wb: p.wb.payout,
      ours: p.ours.ppvz_for_pay || 0,
      tolerance: 1.0,
      note: "Сумма ppvz_for_pay net (Продажа − Возврат) — то что WB реально перечисляет селлеру.",
    },
  ];
  // TASK-LEAD-043 — Explainer: если есть alert или unattributed > 0, показываем
  // summary блок что именно расходится. Не заменяет WizardRow ниже — дополняет.
  const hasAlert = p.diff?.alert;
  const unattributed = p.unattributed;
  const unattributedTotal = unattributed?.total ?? 0;
  const payoutToGrossPct = p.diff?.payout_to_gross_pct;
  const showExplainer =
    hasAlert ||
    unattributedTotal > 100 ||
    (payoutToGrossPct != null && (payoutToGrossPct < 85 || payoutToGrossPct > 105));

  return (
    <tr className="bg-bg/50 border-t border-border">
      <td colSpan={13} className="p-4">
        {/* TASK-LEAD-043 — Summary explainer для проблемных недель */}
        {showExplainer && (
          <div className="card mb-4 border border-warn/40">
            <div className="font-medium mb-2"><Icon name="warning" size={12} /> Что не сходится за эту неделю</div>
            <div className="grid md:grid-cols-3 gap-3 text-sm">
              {hasAlert && (
                <div>
                  <div className="text-xs text-muted uppercase">Δ revenue gross</div>
                  <div className="text-lg font-mono font-semibold text-danger mt-1">
                    {p.diff.revenue_gross_pct >= 0 ? "+" : ""}
                    {fmtPct(p.diff.revenue_gross_pct, 2)}
                  </div>
                  <div className="text-xs text-muted">
                    {p.diff.revenue_gross_abs >= 0 ? "+" : ""}
                    {fmtRub(p.diff.revenue_gross_abs)} абс. (WB − Наша)
                  </div>
                </div>
              )}
              {unattributedTotal > 100 && (
                <div>
                  <div className="text-xs text-muted uppercase">
                    WB-расходы без SKU ({unattributed.rows_count} строк)
                  </div>
                  <div className="text-lg font-mono font-semibold text-warn mt-1">
                    {fmtRub(unattributedTotal)}
                  </div>
                  <div className="text-xs text-muted">
                    Платная приёмка / бонусы / корректировки на категорию.
                    WB шлёт без nm_id — мы не учитываем в per-SKU аналитике.
                  </div>
                </div>
              )}
              {payoutToGrossPct != null && (
                <div>
                  <div className="text-xs text-muted uppercase">Payout / Gross</div>
                  <div
                    className={`text-lg font-mono font-semibold mt-1 ${
                      payoutToGrossPct >= 95 && payoutToGrossPct <= 105
                        ? "text-success"
                        : payoutToGrossPct < 85
                          ? "text-danger"
                          : "text-warn"
                    }`}
                  >
                    {fmtPct(payoutToGrossPct, 1)}
                  </div>
                  <div className="text-xs text-muted">
                    Норма 95-100%. &lt; 90% — WB активно «жмёт» удержаниями;
                    &gt; 105% — WB доплачивает за прошлые периоды.
                  </div>
                </div>
              )}
            </div>
            {unattributedTotal > 100 && (
              <div className="mt-3 text-xs">
                <span className="text-muted uppercase">Разбивка WB-расходов без SKU:</span>
                <div className="grid grid-cols-2 md:grid-cols-6 gap-2 mt-1 font-mono">
                  {unattributed.delivery > 0 && (
                    <div>Логистика: {fmtRub(unattributed.delivery)}</div>
                  )}
                  {unattributed.storage > 0 && (
                    <div>Хранение: {fmtRub(unattributed.storage)}</div>
                  )}
                  {unattributed.penalty > 0 && (
                    <div>Штрафы: {fmtRub(unattributed.penalty)}</div>
                  )}
                  {unattributed.deduction > 0 && (
                    <div>Удержания: {fmtRub(unattributed.deduction)}</div>
                  )}
                  {unattributed.acquiring > 0 && (
                    <div>Эквайринг: {fmtRub(unattributed.acquiring)}</div>
                  )}
                  {unattributed.additional > 0 && (
                    <div>Доплаты: −{fmtRub(unattributed.additional)}</div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
        <div className="grid lg:grid-cols-[1fr_1fr] gap-6">
          {/* Левая колонка: инструкция сверки */}
          <div className="text-sm flex flex-col gap-3">
            <div className="font-medium text-white">
              Шаги сверки за {p.period_from} — {p.period_to}
            </div>

            <ol className="list-decimal list-inside space-y-2 text-muted leading-relaxed">
              <li>
                <a
                  href={WB_FINANCE_REPORTS_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-accent underline hover:no-underline"
                >
                  Открыть WB-кабинет → Отчёты → Финансовые отчёты реализации
                </a>{" "}
                в новой вкладке.
              </li>
              <li>
                Найти отчёт с ID{" "}
                <code className="text-white">{p.realization_ids}</code> (
                {p.realizations_count}{" "}
                {p.realizations_count === 1 ? "отчёт" : "отчётов"} за неделю).
              </li>
              <li>
                Скачать xlsx (если ещё не скачан) — он 1:1 с тем что WB
                присылает по API. Ключевые поля для сверки:{" "}
                <b>цена продажи после скидки</b>,{" "}
                <b>сумма к перечислению селлеру</b>, <b>% комиссии WB</b>,{" "}
                <b>стоимость логистики</b>, <b>стоимость хранения</b>.
              </li>
              <li>
                Сравнить итоги по строкам справа. Если Δ &lt; ~1 ₽ — норма
                (округления). Если больше — проверь, докачался ли финансовый
                отчёт от WB (синхронизация раз в сутки, 04:15 МСК), или
                посмотри не прислал ли WB ретроспективную корректировку.
              </li>
            </ol>

            {p.diff.alert && (
              <div className="card border-danger/40 bg-danger/10 text-xs text-danger">
                <Icon name="warning" size={12} className="inline mr-1" />Δ Выручка {fmtPct(p.diff.revenue_gross_pct, 2)} превышает
                порог {`(`}
                {fmtRub(p.diff.revenue_gross_abs)}
                {`)`}. Возможные причины:
                <ul className="list-disc list-inside mt-1 space-y-0.5">
                  <li>
                    не дошла последняя синхронизация финансового отчёта от
                    WB — запустить вручную в разделе «Настройки →
                    Синхронизация» или подождать следующий запуск (04:15 МСК)
                  </li>
                  <li>
                    WB прислал ретроспективную корректировку (доплату или
                    дополнительное удержание) — найди этот номер отчёта в
                    журнале изменений (Audit log)
                  </li>
                  <li>
                    в нашей базе встретился отчёт с нетипичным «типом
                    операции» (например, «Продажа» с нестандартным регистром
                    букв) — сообщи в поддержку
                  </li>
                </ul>
              </div>
            )}
          </div>

          {/* Правая колонка: построчная таблица сверки */}
          <div className="flex flex-col gap-2">
            <div className="text-sm font-medium text-white">
              Сравнение ключевых полей
            </div>
            <table className="text-xs w-full">
              <thead className="text-muted">
                <tr>
                  <th className="text-left p-1">Поле</th>
                  <th className="text-right p-1 text-warn">WB</th>
                  <th className="text-right p-1 text-success">Наша</th>
                  <th className="text-right p-1">Δ</th>
                </tr>
              </thead>
              <tbody>
                {checks.map((c) => {
                  const diff = c.ours - c.wb;
                  const tol = c.tolerance ?? 1.0;
                  const bad = Math.abs(diff) > tol;
                  return (
                    <tr key={c.label} className="border-t border-border">
                      <td className="p-1" title={c.note}>
                        {c.label}
                      </td>
                      <td className="p-1 text-right font-mono">
                        {fmtRub(c.wb)}
                      </td>
                      <td className="p-1 text-right font-mono">
                        {fmtRub(c.ours)}
                      </td>
                      <td
                        className={`p-1 text-right font-mono ${
                          bad ? "text-danger font-bold" : "text-muted"
                        }`}
                      >
                        {fmtRatio(diff, 2)}
                      </td>
                    </tr>
                  );
                })}
                <tr className="border-t border-border">
                  <td className="p-1 text-muted">WB-удержания (сумма)</td>
                  <td className="p-1 text-right font-mono text-muted">
                    {fmtRub(fees)}
                  </td>
                  <td className="p-1 text-right font-mono text-muted">—</td>
                  <td className="p-1 text-right text-muted">—</td>
                </tr>
              </tbody>
            </table>
            <div className="text-xs text-muted leading-relaxed mt-2">
              «WB-удержания» = логистика {fmtRub(p.wb.delivery)} + хранение{" "}
              {fmtRub(p.wb.storage)} + штрафы {fmtRub(p.wb.penalty)} +
              удержания {fmtRub(p.wb.deduction)} + эквайринг{" "}
              {fmtRub(p.wb.acquiring)} − доплаты {fmtRub(p.wb.additional)}.
            </div>

            {p.unattributed && p.unattributed.rows_count > 0 && (
              <div className="card border-warn/30 bg-warn/5 mt-3 text-xs">
                <div className="font-medium text-warn mb-1">
                  «Нулевой SKU» — расходы без nm_id ({p.unattributed.rows_count} стр.)
                </div>
                <div className="text-muted leading-relaxed mb-2">
                  WB шлёт эти строки без привязки к товару: платная приёмка по складу,
                  бонусы, корректировки на категорию. В наш per-SKU P&L они не попадают —
                  показываем отдельно чтобы видеть «куда ушла дельта».
                </div>
                <table className="w-full">
                  <tbody>
                    {[
                      ["Логистика", p.unattributed.delivery],
                      ["Хранение", p.unattributed.storage],
                      ["Штрафы", p.unattributed.penalty],
                      ["Удержания", p.unattributed.deduction],
                      ["Эквайринг", p.unattributed.acquiring],
                      ["Доплаты (−)", -p.unattributed.additional],
                      ["ppvz_for_pay", p.unattributed.ppvz],
                    ]
                      .filter(([, v]) => (v as number) !== 0)
                      .map(([label, v]) => (
                        <tr key={String(label)}>
                          <td className="py-0.5 text-muted">{label}</td>
                          <td className="py-0.5 text-right font-mono">
                            {fmtRub(v as number)}
                          </td>
                        </tr>
                      ))}
                    <tr className="border-t border-border">
                      <td className="py-0.5 font-medium">Итого (сумма)</td>
                      <td className="py-0.5 text-right font-mono font-medium">
                        {fmtRub(p.unattributed.total)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </td>
    </tr>
  );
}
