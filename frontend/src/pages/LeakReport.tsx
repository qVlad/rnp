/**
 * Аудит-артефакт «найдено N₽» (TASK-LEAD-140).
 *
 * Одно число сверху — сколько денег у кабинета утекает или можно вернуть за
 * период — + breakdown по 5 источникам (оспоримые штрафы / минусовые SKU /
 * дохлый сток в хранении / переплата логистики из-за перемеров / убыточные
 * акции) + recon trust-badge «сверено с WB до рубля».
 *
 * Используется как ритуал входа в клуб (онбординг кабинета) и печатный
 * sales-артефакт: кнопка «Печать / PDF» → window.print(); scoped print-CSS
 * прячет сайдбар (<aside>) и контролы, оставляя только отчёт.
 *
 * Backend: GET /api/leak-report (services/leak_report.py).
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { LeakBreakdownItem } from "@/api/client";
import { api } from "@/api/client";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";
import PageHeader from "@/components/PageHeader";
import { DateRangePicker } from "@/components/DateRangePicker";

function iso(d: Date) {
  return d.toISOString().slice(0, 10);
}
function defaultRange() {
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - 29);
  return { from: iso(from), to: iso(to) };
}

const PRINT_CSS = `
@media print {
  aside { display: none !important; }
  main { padding: 0 !important; }
  .lr-no-print { display: none !important; }
  .lr-card { break-inside: avoid; }
  body { background: #fff !important; }
}
`;

/** Карточка одного источника утечки + раскрытие топ-SKU. */
function LeakCard({ item }: { item: LeakBreakdownItem }) {
  const [open, setOpen] = useState(false);
  const empty = item.amount <= 0 && item.count === 0;
  return (
    <div
      className={`lr-card card p-4 ${empty ? "opacity-60" : ""}`}
      data-kind={item.kind}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-lg">{item.icon}</span>
            <span className="font-medium">{item.label}</span>
            <span
              className={`text-tiny px-1.5 py-0.5 rounded ${
                item.kind === "recover"
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-amber-100 text-amber-700"
              }`}
            >
              {item.kind === "recover" ? "вернуть" : "прекратить"}
            </span>
          </div>
          <p className="text-tiny text-muted mt-1">{item.hint}</p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-h3 font-semibold tabular-nums">
            {fmtRub(item.amount)}
          </div>
          <div className="text-tiny text-muted">{fmtNum(item.count)} SKU/строк</div>
        </div>
      </div>

      {item.details.length > 0 && (
        <>
          <button
            type="button"
            className="lr-no-print text-tiny text-accent mt-3 hover:underline"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Свернуть" : `Показать детали (${item.details.length})`}
          </button>
          <div className={open ? "mt-2" : "mt-2 hidden print:block"}>
            <DetailTable item={item} />
          </div>
        </>
      )}
    </div>
  );
}

/** Таблица деталей — колонки зависят от типа источника. */
function DetailTable({ item }: { item: LeakBreakdownItem }) {
  const rows = item.details as Array<Record<string, any>>;
  if (item.leak_type === "recoverable_chargebacks") {
    return (
      <table className="w-full text-tiny">
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-border/50">
              <td className="py-1">{String(r.label)}</td>
              <td className="py-1 text-right text-muted">{fmtNum(r.count)} шт</td>
              <td className="py-1 text-right tabular-nums">{fmtRub(r.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  // SKU-таблицы (минус-маржа / дохлый сток / перемеры / акции)
  return (
    <table className="w-full text-tiny">
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-t border-border/50">
            <td className="py-1 w-8">
              {r.photo_url ? (
                <img
                  src={String(r.photo_url)}
                  alt=""
                  className="w-6 h-6 rounded object-cover"
                />
              ) : null}
            </td>
            <td className="py-1">
              <span className="font-mono">{String(r.nm_id)}</span>
              {r.vendor_code ? (
                <span className="text-muted"> · {String(r.vendor_code)}</span>
              ) : null}
            </td>
            <td className="py-1 text-right text-muted">{detailMeta(item.leak_type, r)}</td>
            <td className="py-1 text-right tabular-nums">
              {fmtRub(Number(r.loss ?? r.storage ?? r.overpay ?? 0))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function detailMeta(type: string, r: Record<string, any>): string {
  switch (type) {
    case "negative_margin_skus":
      return `${fmtPct(Number(r.margin_pct))} · ${fmtNum(r.units_sold)} шт`;
    case "dead_stock_storage":
      return `сток ${fmtNum(r.stock)}`;
    case "remeasure_logistics":
      return `${Number(r.prev_volume_l)}→${Number(r.volume_l)} л · ${fmtNum(r.units_sold)} шт`;
    case "loss_making_promos":
      return `${fmtNum(r.promo_units)} шт на акции`;
    default:
      return "";
  }
}

export default function LeakReport() {
  const [range, setRange] = useState(defaultRange);

  const q = useQuery({
    queryKey: ["leak-report", range.from, range.to],
    queryFn: () => api.leakReport({ from: range.from, to: range.to }),
  });

  const data = q.data;
  const badge = data?.trust_badge;
  const sorted = useMemo(
    () => (data ? [...data.breakdown].sort((a, b) => b.amount - a.amount) : []),
    [data],
  );

  return (
    <div className="max-w-4xl">
      <style>{PRINT_CSS}</style>
      <PageHeader
        title="Аудит кабинета — найдено ₽"
        subtitle={`Период ${range.from} → ${range.to}`}
        actions={
          <div className="lr-no-print flex items-end gap-2">
            <DateRangePicker
              from={range.from}
              to={range.to}
              onChange={setRange}
              compact
            />
            <button
              type="button"
              className="btn"
              onClick={() => window.print()}
              disabled={!data}
            >
              Печать / PDF
            </button>
          </div>
        }
      />

      {q.isLoading && <div className="text-muted">Считаем утечки…</div>}
      {q.isError && (
        <div className="text-danger">Ошибка: {(q.error as Error).message}</div>
      )}

      {data && (
        <>
          {/* Hero — одно число */}
          <div className="card p-6 mb-4 text-center">
            <div className="text-tiny text-muted uppercase tracking-wide">
              Найдено за период
            </div>
            <div className="text-[40px] leading-none font-bold tabular-nums my-2">
              {fmtRub(data.total_found_rub)}
            </div>
            <div className="flex justify-center gap-6 text-tiny mt-3">
              <span className="text-emerald-700">
                💰 Можно вернуть: <b>{fmtRub(data.total_recover_rub)}</b>
              </span>
              <span className="text-amber-700">
                🩹 Можно прекратить: <b>{fmtRub(data.total_prevent_rub)}</b>
              </span>
            </div>
            {badge?.available && (
              <div className="text-tiny text-muted mt-3">
                ✅ Сверено с WB-кабинетом: {badge.weeks_matched}/{badge.weeks_total}{" "}
                недель совпали до 1% (макс. расхождение {fmtPct(badge.max_diff_pct)})
              </div>
            )}
          </div>

          {/* Breakdown */}
          <div className="grid grid-cols-1 gap-3">
            {sorted.map((item) => (
              <LeakCard key={item.leak_type} item={item} />
            ))}
          </div>

          <p className="text-tiny text-muted mt-4">
            Отчёт сформирован {new Date(data.generated_at).toLocaleString("ru-RU")}.
            Суммы — оценка по данным кабинета; «вернуть» = претензии в WB, «прекратить»
            = управленческие решения по SKU.
          </p>
        </>
      )}
    </div>
  );
}
