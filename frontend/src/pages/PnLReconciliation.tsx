import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";

export default function PnLReconciliation() {
  const [weeks, setWeeks] = useState(12);
  const [threshold, setThreshold] = useState(1);
  const q = useQuery({
    queryKey: ["pnl-reconciliation", weeks, threshold],
    queryFn: () => api.pnlReconciliation(weeks, threshold),
  });

  const periods = q.data?.periods ?? [];
  const totals = q.data?.totals;
  const loadedWeeks = periods.length;
  const hasPartialHistory = !q.isLoading && loadedWeeks > 0 && loadedWeeks < weeks;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end gap-4">
        <h1 className="text-xl font-semibold">Сверка с WB</h1>
        <span className="text-xs text-muted">
          сравнение нашей P&L с финальным отчётом WB по каждой неделе
        </span>
      </div>

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
        <span className="text-accent ml-2">
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
                return (
                  <tr
                    key={`${p.period_from}-${p.period_to}`}
                    className={`border-t border-border ${
                      p.diff.alert ? "bg-danger/10" : ""
                    }`}
                  >
                    <td className="p-2 sticky left-0 bg-surface whitespace-nowrap">
                      {p.period_from} — {p.period_to}
                    </td>
                    <td className="p-2 font-mono text-xs">
                      {p.realizations_count}
                      <div className="text-muted">{p.realization_ids}</div>
                    </td>
                    <td className="p-2 text-right">{fmtRub(p.wb.revenue_gross)}</td>
                    <td className="p-2 text-right text-muted">
                      {p.wb.revenue_returns ? fmtRub(p.wb.revenue_returns) : "—"}
                    </td>
                    <td className="p-2 text-right">{fmtRub(p.wb.commission)}</td>
                    <td className="p-2 text-right font-medium">
                      {fmtRub(p.wb.payout)}
                    </td>
                    <td className="p-2 text-right text-muted">{fmtRub(fees)}</td>
                    <td className="p-2 text-right">{fmtRub(p.ours.revenue_gross)}</td>
                    <td className="p-2 text-right">{fmtRub(p.ours.revenue_net)}</td>
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
                      {p.diff.revenue_gross_abs.toFixed(2)}
                    </td>
                    <td
                      className={`p-2 text-right ${
                        p.diff.alert ? "text-danger font-bold" : "text-muted"
                      }`}
                    >
                      {p.diff.revenue_gross_pct.toFixed(2)}%
                    </td>
                    <td
                      className={`p-2 text-right ${
                        p.diff.payout_to_gross_pct < 60
                          ? "text-warn"
                          : "text-muted"
                      }`}
                      title="Какая доля gross-выручки реально доходит до селлера после комиссий WB"
                    >
                      {p.diff.payout_to_gross_pct.toFixed(1)}%
                    </td>
                  </tr>
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
