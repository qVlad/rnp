/**
 * Аудит-артефакт «найдено N₽» (TASK-LEAD-140, таксономия TASK-LEAD-142).
 *
 * Три ЧЕСТНЫХ итога вместо одной кучи:
 *   1. 💰 НАЙДЕНО — вернуть (оспоримые удержания/штрафы) + дёшево остановить
 *      (минусовые проданные SKU, переплата логистики из-за перемеров).
 *   2. 📦 ЗАМОРОЖЕНО / ПОД РИСКОМ — дохлый сток: хранение капает + капитал
 *      заморожен в товаре. НЕ чистая экономия (вывоз/распродажа стоит денег).
 *   3. 📉 УЖЕ ПОТЕРЯНО — убыточные акции постфактум, вернуть нельзя (урок).
 *
 * Печатный/PDF-вид: «Печать / PDF» → window.print(); scoped print-CSS прячет
 * сайдбар (<aside>) и контролы. Backend: GET /api/leak-report.
 *
 * Тип ответа — `LeakReport` / `LeakBreakdownItem` в api/client.ts (единый
 * источник правды; тех-долг TASK-LEAD-142 закрыт — раньше тип жил локально,
 * пока client.ts держал чужой WIP).
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type LeakBreakdownItem, type LeakGroup } from "@/api/client";
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

const KIND_CHIP: Record<string, { label: string; cls: string }> = {
  recover: { label: "вернуть", cls: "bg-emerald-100 text-emerald-700" },
  stop: { label: "остановить", cls: "bg-amber-100 text-amber-700" },
  review: { label: "разобрать", cls: "bg-violet-100 text-violet-700" },
  frozen: { label: "заморожено", cls: "bg-sky-100 text-sky-700" },
  lost: { label: "потеряно", cls: "bg-rose-100 text-rose-700" },
  info: { label: "сервисы WB", cls: "bg-gray-100 text-gray-600" },
};

function LeakCard({ item }: { item: LeakBreakdownItem }) {
  const [open, setOpen] = useState(false);
  const empty = item.amount <= 0 && item.count === 0;
  const chip = KIND_CHIP[item.kind] ?? { label: item.kind, cls: "bg-gray-100 text-gray-600" };
  return (
    <div className={`lr-card card p-4 ${empty ? "opacity-60" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-lg">{item.icon}</span>
            <span className="font-medium">{item.label}</span>
            <span className={`text-tiny px-1.5 py-0.5 rounded ${chip.cls}`}>
              {chip.label}
            </span>
          </div>
          <p className="text-tiny text-muted mt-1">{item.hint}</p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-h3 font-semibold tabular-nums">{fmtRub(item.amount)}</div>
          <div className="text-tiny text-muted">{fmtNum(item.count)} SKU/строк</div>
          {item.frozen_capital != null && item.frozen_capital > 0 && (
            <div className="text-tiny text-sky-700 mt-0.5">
              заморожено в товаре: {fmtRub(item.frozen_capital)}
            </div>
          )}
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

// Чарджбэк-блоки отдают details по категориям ({category,label,amount,count}),
// а не по SKU — рисуем другую таблицу.
const CHARGEBACK_LEAK_TYPES = new Set(["disputable_chargebacks", "review_deductions"]);

function DetailTable({ item }: { item: LeakBreakdownItem }) {
  const rows = item.details;
  if (CHARGEBACK_LEAK_TYPES.has(item.leak_type)) {
    return (
      <table className="w-full text-tiny">
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-border/50">
              <td className="py-1">{String(r.label)}</td>
              <td className="py-1 text-right text-muted">{fmtNum(Number(r.count))} шт</td>
              <td className="py-1 text-right tabular-nums">{fmtRub(Number(r.amount))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  return (
    <table className="w-full text-tiny">
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-t border-border/50">
            <td className="py-1 w-8">
              {r.photo_url ? (
                <img src={String(r.photo_url)} alt="" className="w-6 h-6 rounded object-cover" />
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
      return `сток ${fmtNum(r.stock)} · заморожено ${fmtRub(Number(r.frozen_capital ?? 0))}`;
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
  const byGroup = useMemo(() => {
    const g: Record<LeakGroup, LeakBreakdownItem[]> = { found: [], review: [], frozen: [], lost: [], info: [] };
    if (data) for (const it of data.breakdown) g[it.group]?.push(it);
    for (const k of Object.keys(g) as LeakGroup[]) g[k].sort((a, b) => b.amount - a.amount);
    return g;
  }, [data]);

  return (
    <div className="max-w-4xl">
      <style>{PRINT_CSS}</style>
      <PageHeader
        title="Аудит кабинета — найдено ₽"
        subtitle={`Период ${range.from} → ${range.to}`}
        actions={
          <div className="lr-no-print flex items-end gap-2">
            <DateRangePicker from={range.from} to={range.to} onChange={setRange} compact />
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
      {q.isError && <div className="text-danger">Ошибка: {(q.error as Error).message}</div>}

      {data && (
        <>
          {/* Hero — НАЙДЕНО (вернуть + дёшево остановить) */}
          <div className="card p-6 mb-3 text-center">
            <div className="text-tiny text-muted uppercase tracking-wide">
              Найдено за период · можно вернуть или дёшево остановить
            </div>
            <div className="text-[40px] leading-none font-bold tabular-nums my-2">
              {fmtRub(data.totals.found_rub)}
            </div>
            {badge?.available && (
              <div className="text-tiny text-muted mt-2">
                ✅ Сверено с WB-кабинетом: {badge.weeks_matched}/{badge.weeks_total} недель
                совпали до 1% (макс. расхождение {fmtPct(badge.max_diff_pct)})
              </div>
            )}
          </div>

          {/* Вторичные итоги — НЕ входят в «найдено» */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
            <div className="card p-4">
              <div className="flex items-center gap-2">
                <span className="text-lg">🔍</span>
                <span className="font-medium">Разобрать</span>
              </div>
              <div className="text-h3 font-semibold tabular-nums mt-1">
                {fmtRub(data.totals.review_rub)}
              </div>
              <div className="text-tiny text-muted">
                удержания WB (приёмка, хранение с низким ИЛ) — в массе легитимны,
                проверить спорные. Не возвратные.
              </div>
            </div>
            <div className="card p-4">
              <div className="flex items-center gap-2">
                <span className="text-lg">📦</span>
                <span className="font-medium">Заморожено / под риском</span>
              </div>
              <div className="text-h3 font-semibold tabular-nums mt-1">
                {fmtRub(data.totals.frozen_capital_rub)}
              </div>
              <div className="text-tiny text-muted">
                капитал в дохлом стоке · хранение капает {fmtRub(data.totals.frozen_rub)}/период.
                Прекратить стоит денег (вывоз/распродажа) — не чистая экономия.
              </div>
            </div>
            <div className="card p-4">
              <div className="flex items-center gap-2">
                <span className="text-lg">📉</span>
                <span className="font-medium">Уже потеряно</span>
              </div>
              <div className="text-h3 font-semibold tabular-nums mt-1">
                {fmtRub(data.totals.lost_rub)}
              </div>
              <div className="text-tiny text-muted">
                убыточные акции постфактум — вернуть нельзя, урок на будущее.
              </div>
            </div>
          </div>

          {/* Breakdown по группам */}
          {(
            [
              ["found", "💰 Найдено — вернуть и остановить"],
              ["review", "🔍 Разобрать — удержания WB"],
              ["frozen", "📦 Заморожено / под риском"],
              ["lost", "📉 Уже потеряно"],
              ["info", "💼 Расходы на сервисы WB (справочно)"],
            ] as [LeakGroup, string][]
          ).map(([group, title]) =>
            byGroup[group].length === 0 ? null : (
              <div key={group} className="mb-4">
                <h2 className="text-tiny text-muted uppercase tracking-wide mb-2">{title}</h2>
                <div className="grid grid-cols-1 gap-3">
                  {byGroup[group].map((item) => (
                    <LeakCard key={item.leak_type} item={item} />
                  ))}
                </div>
              </div>
            ),
          )}

          <p className="text-tiny text-muted mt-4">
            Отчёт сформирован {new Date(data.generated_at).toLocaleString("ru-RU")}. «Найдено» =
            возврат (оспоримые штрафы/коррекции) + дёшево остановить. «Разобрать», «заморожено»
            и «потеряно» в эту сумму НЕ входят: удержания в массе легитимны, дохлый сток требует
            затрат на вывоз/распродажу, акции уже потрачены.
          </p>
        </>
      )}
    </div>
  );
}
