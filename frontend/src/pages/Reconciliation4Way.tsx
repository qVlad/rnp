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
import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";
import { Icon } from "../components/Icon";
import PageHeader from "@/components/PageHeader";

function diffColor(pct: number | null | undefined): string {
  if (pct == null) return "text-muted";
  const a = Math.abs(pct);
  if (a < 0.5) return "text-success";
  if (a < 2) return "text-warning";
  return "text-danger";
}

export default function Reconciliation4Way() {
  const qc = useQueryClient();
  const [weeks, setWeeks] = useState(8);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importResult, setImportResult] = useState<{
    imported: number;
    errors: string[];
    sheet_name?: string;
    header_row?: number;
    filename?: string;
  } | null>(null);

  const q = useQuery({
    queryKey: ["reconciliation-4way", weeks],
    queryFn: () => api.reconciliation4way(weeks),
  });

  const importMut = useMutation({
    mutationFn: (file: File) => api.reconciliationImport(file, "bookkeeper"),
    onSuccess: (data) => {
      setImportResult(data);
      qc.invalidateQueries({ queryKey: ["reconciliation-4way"] });
    },
    onError: (err: any) => {
      setImportResult({
        imported: 0,
        errors: [err?.message || String(err)],
      });
    },
  });

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) importMut.mutate(f);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="4-way Сверка"
        subtitle="Уникально для SellerFriends — 4 источника данных side-by-side. Дифференциатор vs Eggheads / TrueStats / MPump."
        actions={
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
        }
      />

      <div className="card text-xs text-muted leading-relaxed">
        Источники: <strong className="text-fg">Наш P&L</strong> (services/pnl_builder)
        / <strong className="text-fg">WB Cabinet</strong> (wb_report_detail)
        / <strong className="text-fg">WB Documents</strong> (уведомления о выкупе
        + акты взаимозачёта)
        / <strong className="text-fg">Бухгалтер</strong> (импорт XLSX из 1С/учёта).
        Зелёное = расхождение &lt;0.5%, жёлтое 0.5-2%, красное &gt;2%.
      </div>

      {/* Bookkeeper XLSX upload */}
      <div className="card flex items-center justify-between flex-wrap gap-3">
        <div className="text-sm">
          <div className="font-medium">Импорт от бухгалтера</div>
          <div className="text-xs text-muted mt-0.5 leading-relaxed">
            XLSX с колонками: Период с / Период по / Выручка / Возвраты /
            Комиссия / К выплате. Re-upload того же периода обновит значения.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx"
            onChange={handleFile}
            className="hidden"
          />
          <button
            type="button"
            className="btn-primary text-xs"
            onClick={() => fileInputRef.current?.click()}
            disabled={importMut.isPending}
          >
            {importMut.isPending ? (
              "Импортирую…"
            ) : (
              <><Icon name="upload" size={12} /> Загрузить XLSX</>
            )}
          </button>
        </div>
      </div>

      {importResult && (
        <div
          className={`card text-xs ${
            importResult.imported > 0
              ? "border-success/30 bg-success/5"
              : "border-danger bg-danger-subtle"
          }`}
        >
          {importResult.imported > 0 ? (
            <div className="text-success font-medium">
              <Icon name="check" size={12} /> Импортировано строк: {importResult.imported}
              {importResult.filename && (
                <span className="text-muted ml-2 font-normal">
                  ({importResult.filename}, лист «{importResult.sheet_name}»,
                  заголовок в строке {importResult.header_row})
                </span>
              )}
            </div>
          ) : (
            <div className="text-danger font-medium">
              <Icon name="close" size={12} /> Не удалось импортировать
            </div>
          )}
          {importResult.errors.length > 0 && (
            <ul className="mt-1 list-disc list-inside text-muted">
              {importResult.errors.slice(0, 5).map((e, i) => (
                <li key={i}>{e}</li>
              ))}
              {importResult.errors.length > 5 && (
                <li>… и ещё {importResult.errors.length - 5} ошибок</li>
              )}
            </ul>
          )}
        </div>
      )}

      {q.isLoading && <div className="text-muted">Загрузка…</div>}
      {q.isError && (
        <div className="card text-danger text-sm">
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
                <th colSpan={3} className="text-center p-2 border-l border-border bg-warning/5">
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
                <th className="text-right p-1 border-l border-border">Выручка ₽</th>
                <th className="text-right p-1">Комис.</th>
                <th className="text-right p-1">Δ vs WB</th>
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
                  <td className="p-2 text-right border-l border-border font-mono">
                    {fmtRub(p.ours.revenue_gross)}
                  </td>
                  <td
                    className={`p-2 text-right font-mono ${diffColor(p.ours.diff_vs_wb_pct)}`}
                  >
                    {p.ours.diff_vs_wb_pct > 0 ? "+" : ""}
                    {fmtPct(p.ours.diff_vs_wb_pct)}
                  </td>
                  {/* WB Cabinet */}
                  <td className="p-2 text-right border-l border-border font-mono">
                    {fmtRub(p.wb_cabinet.revenue_gross)}
                  </td>
                  <td className="p-2 text-right text-muted font-mono">
                    {fmtRub(p.wb_cabinet.commission)}
                  </td>
                  <td className="p-2 text-right text-muted font-mono">
                    {fmtRub(p.wb_cabinet.payout)}
                  </td>
                  {/* WB Documents */}
                  <td className="p-2 text-right border-l border-border font-mono">
                    {fmtRub(p.wb_documents.redeem_total_rub)}
                    {p.wb_documents.redeem_count > 0 && (
                      <span className="text-[10px] text-muted ml-1">
                        ({p.wb_documents.redeem_count})
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-right font-mono">
                    {fmtRub(p.wb_documents.offset_total_rub)}
                    {p.wb_documents.offset_count > 0 && (
                      <span className="text-[10px] text-muted ml-1">
                        ({p.wb_documents.offset_count})
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-right font-medium font-mono">
                    {fmtRub(p.wb_documents.total_rub)}
                  </td>
                  {/* Бухгалтер */}
                  <td className="p-2 text-right border-l border-border text-xs font-mono">
                    {p.bookkeeper.available
                      ? fmtRub(p.bookkeeper.revenue_gross || 0)
                      : <span className="text-muted">—</span>}
                  </td>
                  <td className="p-2 text-right text-xs font-mono">
                    {p.bookkeeper.available
                      ? fmtRub(p.bookkeeper.commission || 0)
                      : <span className="text-muted">—</span>}
                  </td>
                  <td
                    className={`p-2 text-right text-xs font-mono ${diffColor(p.bookkeeper.diff_vs_wb_pct)}`}
                    title={
                      p.bookkeeper.imported_at
                        ? `Импортировано ${p.bookkeeper.imported_at.slice(0, 16)}`
                        : "Нет импорта за этот период"
                    }
                  >
                    {p.bookkeeper.available && p.bookkeeper.diff_vs_wb_pct != null
                      ? `${p.bookkeeper.diff_vs_wb_pct > 0 ? "+" : ""}${fmtPct(p.bookkeeper.diff_vs_wb_pct)}`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card text-xs text-muted leading-relaxed">
        Импорт от бухгалтера активен ✓. Если 4-я колонка не заполнена за
        неделю — значит за этот период XLSX ещё не загружен. Один файл может
        содержать любое количество строк (недель/месяцев) — UPSERT по (период,
        источник) дедуплицирует повторные загрузки.
      </div>
    </div>
  );
}
