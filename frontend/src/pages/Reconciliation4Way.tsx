/**
 * 4-way Reconciliation страница — Stratege ставка #2 MVP.
 *
 * Уникальная для рынка: 4 источника данных side-by-side для каждой недели:
 *   • Наш P&L
 *   • WB Cabinet (отчёт реализации)
 *   • WB Documents API (выкупы + акты взаимозачёта)
 *   • Бухгалтер XLSX (placeholder в MVP)
 *
 * Цель — позиционирование «единственный сервис где WB + бухгалтер + наши
 * цифры сходятся копейка в копейку». Сегмент CFO/бухгалтер 5-30М ₽/мес.
 *
 * Доступ: director + head_of_sales (защищено DirectorOrHead в App.tsx).
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";

function diffColor(pct: number): string {
  const a = Math.abs(pct);
  if (a < 0.5) return "text-success";
  if (a < 2) return "text-warning";
  return "text-red-400";
}

export default function Reconciliation4Way() {
  const [weeks, setWeeks] = useState(8);
  const q = useQuery({
    queryKey: ["reconciliation-4way", weeks],
    queryFn: () => api.reconciliation4way(weeks),
  });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold">4-way Сверка</h1>
          <div className="text-xs text-muted mt-1">
            Уникально для РНП — 4 источника данных side-by-side. Дифференциатор
            vs Eggheads / TrueStats / MPump.
          </div>
        </div>
        <div className="flex gap-1">
          {[4, 8, 12, 24].map((w) => (
            <button
              key={w}
              className={`btn text-xs ${weeks === w ? "border-accent text-accent" : ""}`}
              onClick={() => setWeeks(w)}
            >
              {w} нед.
            </button>
          ))}
        </div>
      </div>

      <div className="card text-xs text-muted leading-relaxed">
        Источники: <strong className="text-fg">Наш P&L</strong> (services/pnl_builder)
        / <strong className="text-fg">WB Cabinet</strong> (wb_report_detail)
        / <strong className="text-fg">WB Documents</strong> (уведомления о выкупе
        + акты взаимозачёта)
        / <strong className="text-fg">Бухгалтер</strong> (импорт XLSX —{" "}
        <em>пока не реализован, planned</em>).
        Зелёное = расхождение &lt;0.5%, жёлтое 0.5-2%, красное &gt;2%.
      </div>

      {q.isLoading && <div className="text-muted">Загрузка…</div>}
      {q.isError && (
        <div className="card text-red-400 text-sm">
          Ошибка: {(q.error as Error).message}
        </div>
      )}

      {q.data && q.data.periods.length === 0 && (
        <div className="card text-muted text-sm">
          За последние {weeks} недель закрытых отчётов реализации нет.
        </div>
      )}

      {q.data && q.data.periods.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted border-b border-border">
                <th rowSpan={2} className="text-left p-2 sticky left-0 bg-surface">
                  Неделя
                </th>
                <th colSpan={2} className="text-center p-2 border-l border-border bg-accent/5">
                  Наш P&L
                </th>
                <th colSpan={3} className="text-center p-2 border-l border-border bg-surface-2/40">
                  WB Cabinet
                </th>
                <th colSpan={3} className="text-center p-2 border-l border-border bg-success/5">
                  WB Documents
                </th>
                <th colSpan={2} className="text-center p-2 border-l border-border bg-warning/5">
                  Бухгалтер
                </th>
              </tr>
              <tr className="text-[10px] text-muted border-b border-border">
                {/* Ours */}
                <th className="text-right p-1 border-l border-border">Выручка ₽</th>
                <th className="text-right p-1">Δ vs WB</th>
                {/* WB Cabinet */}
                <th className="text-right p-1 border-l border-border">Выручка ₽</th>
                <th className="text-right p-1">Комис.</th>
                <th className="text-right p-1">К выпл.</th>
                {/* WB Docs */}
                <th className="text-right p-1 border-l border-border">Выкупы ₽</th>
                <th className="text-right p-1">Акты ₽</th>
                <th className="text-right p-1">Всего</th>
                {/* Bookkeeper */}
                <th className="text-right p-1 border-l border-border">Выручка</th>
                <th className="text-right p-1">Комис.</th>
              </tr>
            </thead>
            <tbody>
              {q.data.periods.map((p) => (
                <tr
                  key={`${p.period_from}_${p.period_to}`}
                  className="border-b border-border/40"
                >
                  <td className="p-2 sticky left-0 bg-surface text-xs whitespace-nowrap">
                    {p.period_from} … {p.period_to}
                  </td>
                  {/* Наш P&L */}
                  <td className="p-2 text-right border-l border-border">
                    {fmtRub(p.ours.revenue_gross)}
                  </td>
                  <td
                    className={`p-2 text-right font-mono ${diffColor(p.ours.diff_vs_wb_pct)}`}
                  >
                    {p.ours.diff_vs_wb_pct > 0 ? "+" : ""}
                    {fmtPct(p.ours.diff_vs_wb_pct)}
                  </td>
                  {/* WB Cabinet */}
                  <td className="p-2 text-right border-l border-border">
                    {fmtRub(p.wb_cabinet.revenue_gross)}
                  </td>
                  <td className="p-2 text-right text-muted">
                    {fmtRub(p.wb_cabinet.commission)}
                  </td>
                  <td className="p-2 text-right text-muted">
                    {fmtRub(p.wb_cabinet.payout)}
                  </td>
                  {/* WB Documents */}
                  <td className="p-2 text-right border-l border-border">
                    {fmtRub(p.wb_documents.redeem_total_rub)}
                    {p.wb_documents.redeem_count > 0 && (
                      <span className="text-[10px] text-muted ml-1">
                        ({p.wb_documents.redeem_count})
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-right">
                    {fmtRub(p.wb_documents.offset_total_rub)}
                    {p.wb_documents.offset_count > 0 && (
                      <span className="text-[10px] text-muted ml-1">
                        ({p.wb_documents.offset_count})
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-right font-medium">
                    {fmtRub(p.wb_documents.total_rub)}
                  </td>
                  {/* Бухгалтер — placeholder */}
                  <td className="p-2 text-right border-l border-border text-muted text-xs">
                    {p.bookkeeper.available
                      ? fmtRub(p.bookkeeper.revenue_gross || 0)
                      : "—"}
                  </td>
                  <td className="p-2 text-right text-muted text-xs">
                    {p.bookkeeper.available
                      ? fmtRub(p.bookkeeper.commission || 0)
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card text-xs text-muted leading-relaxed">
        <strong className="text-fg">Coming soon:</strong> импорт XLSX от
        бухгалтера. Бухгалтер выгружает 1С → загружает XLSX → 4-я колонка
        заполняется и подсвечивается дельта с нашим P&L и WB-кабинетом.
        Это закроет последний gap для CFO-сегмента: «вы единственные, у кого
        WB + наш расчёт + бух сводятся копейка в копейку».
      </div>
    </div>
  );
}
