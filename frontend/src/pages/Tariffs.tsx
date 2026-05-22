/**
 * Страница «Тарифы WB» — timeline + сравнение изменений.
 *
 * Цель: дать селлеру быстро понять «как тарифы по моему складу/предмету
 * менялись за последние полгода, в какую сторону, на сколько». WB меняет
 * тарифы раз в неделю (объявление за 7-14 дней), без timeline планирование
 * закупок — слепое.
 *
 * Источник данных: миграция 0040 (wb_tariff_box / pallet / commission) +
 * Celery beat `sync.tariffs` ежедневно 08:00 MSK. SCD Type 2: каждое
 * изменение WB — новая запись с `effective_from = today`.
 *
 * 3 таба:
 *   - Box (FBO короб) — delivery + storage по выбранному складу
 *   - Pallet (FBO монопаллет) — то же + storage_expr (% коэффициент)
 *   - Commission — комиссии WB по subject_name (FBO/FBS/express)
 *
 * Чарт recharts LineChart с двумя линиями (например storage_base +
 * storage_liter) и таблица всех изменений с дельтами.
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type TariffTimelineRow } from "@/api/client";
import { fmtPct } from "@/lib/format";
import PageHeader from "@/components/PageHeader";
import { Skeleton } from "@/components/states";
import { GRID_PROPS, AXIS_PROPS, TOOLTIP_STYLE, LEGEND_STYLE } from "@/lib/chartTheme";

type Tab = "box" | "pallet" | "commission";

function fmtDate(s: string | null | undefined): string {
  if (!s) return "—";
  return new Date(s).toLocaleDateString("ru-RU");
}

function fmtNum(v: number | null | undefined, digits = 4): string {
  if (v == null) return "—";
  return v.toLocaleString("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function delta(curr: number | null | undefined, prev: number | null | undefined): {
  text: string;
  className: string;
} {
  if (curr == null || prev == null || prev === 0)
    return { text: "—", className: "text-muted" };
  const diff = curr - prev;
  if (Math.abs(diff) < 1e-9) return { text: "0", className: "text-muted" };
  const pct = (diff / prev) * 100;
  const arrow = diff > 0 ? "↑" : "↓";
  const cls = diff > 0 ? "text-warn" : "text-success";
  return {
    text: `${arrow} ${pct >= 0 ? "+" : ""}${fmtPct(pct, 1)}`,
    className: cls,
  };
}

export default function Tariffs() {
  const [tab, setTab] = useState<Tab>("box");

  return (
    <div className="space-y-4">
      <PageHeader
        title="Тарифы Wildberries"
        subtitle={
          <>
            История изменения тарифов хранения, логистики и комиссий по складам
            и предметам. Источник — WB Tariffs API (sync ежедневно в 08:00 MSK,
            таблицы <code className="px-1">wb_tariff_*</code>).
          </>
        }
      />

      <nav className="flex gap-1 border-b border-border">
        {(
          [
            { id: "box", label: "FBO короб" },
            { id: "pallet", label: "FBO монопаллет" },
            { id: "commission", label: "Комиссии WB" },
          ] as { id: Tab; label: string }[]
        ).map((t) => (
          <button
            key={t.id}
            type="button"
            className={`px-4 py-2 text-sm border-b-2 -mb-px transition-colors ${
              tab === t.id
                ? "border-primary text-fg"
                : "border-transparent text-muted hover:text-fg"
            }`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "box" && <WarehouseTab kind="box" key="box" />}
      {tab === "pallet" && <WarehouseTab kind="pallet" key="pallet" />}
      {tab === "commission" && <CommissionTab />}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Tab 1+2 — FBO короб / монопаллет, select по складу
// ─────────────────────────────────────────────────────────────────────────

function WarehouseTab({ kind }: { kind: "box" | "pallet" }) {
  const [warehouse, setWarehouse] = useState<string>("");

  const whQ = useQuery({
    queryKey: ["tariff-warehouses"],
    queryFn: () => api.tariffWarehouses(),
  });

  // При первой загрузке списка — выбираем «Краснодар» если есть, иначе первый.
  useEffect(() => {
    if (warehouse) return;
    const items = whQ.data?.items;
    if (!items?.length) return;
    const krasnodar = items.find((w) => w.toLowerCase().includes("краснод"));
    setWarehouse(krasnodar ?? items[0]);
  }, [whQ.data, warehouse]);

  const timelineQ = useQuery({
    queryKey: ["tariff-timeline", kind, warehouse],
    queryFn: () =>
      kind === "box"
        ? api.tariffBoxTimeline(warehouse)
        : api.tariffPalletTimeline(warehouse),
    enabled: !!warehouse,
  });

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-3">
        <label htmlFor="wh-select" className="text-sm">
          Склад:
        </label>
        <select
          id="wh-select"
          className="input min-w-[280px]"
          value={warehouse}
          onChange={(e) => setWarehouse(e.target.value)}
          disabled={whQ.isLoading}
        >
          {whQ.data?.items.map((w) => (
            <option key={w} value={w}>
              {w}
            </option>
          ))}
        </select>
        <span className="text-xs text-muted">
          Период: последние 180 дней + 30 дней вперёд (если WB уже опубликовал)
        </span>
      </div>

      {timelineQ.isLoading && <Skeleton variant="table" rows={6} />}
      {timelineQ.isError && (
        <div className="card text-warn text-sm">
          Не удалось загрузить timeline: {(timelineQ.error as Error).message}
        </div>
      )}
      {timelineQ.data && (
        <TimelineView rows={timelineQ.data.items} kind={kind} />
      )}
    </section>
  );
}

function TimelineView({
  rows,
  kind,
}: {
  rows: TariffTimelineRow[];
  kind: "box" | "pallet";
}) {
  if (rows.length === 0) {
    return (
      <div className="card text-muted text-sm">
        Нет данных за период. Проверь имя склада, либо запусти sync вручную:
        <code className="px-1">docker compose exec backend python -c "from app.sync.tasks_tariffs import sync_tariffs; sync_tariffs.delay()"</code>
      </div>
    );
  }

  // Готовим точки для чарта — точка на каждое изменение (effective_from = X).
  const chartData = rows.map((r) => ({
    label: fmtDate(r.effective_from),
    delivery_base: r.delivery_base,
    delivery_liter: r.delivery_liter,
    storage_base: r.storage_base,
    storage_liter: r.storage_liter,
    storage_expr: r.storage_expr,
  }));

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ChartCard
          title="Логистика (₽)"
          data={chartData}
          lines={[
            { key: "delivery_base", label: "Базовая ставка", color: "#3b82f6" },
            { key: "delivery_liter", label: "₽/литр", color: "#f59e0b" },
          ]}
        />
        <ChartCard
          title="Хранение (₽/день)"
          data={chartData}
          lines={[
            { key: "storage_base", label: "Базовая ставка", color: "#10b981" },
            { key: "storage_liter", label: "₽/литр/день", color: "#ef4444" },
            ...(kind === "pallet"
              ? [
                  {
                    key: "storage_expr" as const,
                    label: "Коэф. (%)",
                    color: "#8b5cf6",
                  },
                ]
              : []),
          ]}
        />
      </div>

      <ChangesTable rows={rows} kind={kind} />
    </div>
  );
}

function ChartCard<T extends Record<string, unknown>>({
  title,
  data,
  lines,
}: {
  title: string;
  data: T[];
  lines: { key: string; label: string; color: string }[];
}) {
  return (
    <div className="card p-3" style={{ height: 280 }}>
      <h3 className="text-sm font-medium mb-2">{title}</h3>
      <ResponsiveContainer width="100%" height="90%">
        <LineChart data={data}>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis {...AXIS_PROPS} dataKey="label" />
          <YAxis {...AXIS_PROPS} />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={LEGEND_STYLE} />
          {lines.map((l) => (
            <Line
              key={l.key}
              type="stepAfter"
              dataKey={l.key}
              stroke={l.color}
              strokeWidth={2}
              dot={{ r: 3 }}
              connectNulls
              name={l.label}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function ChangesTable({
  rows,
  kind,
}: {
  rows: TariffTimelineRow[];
  kind: "box" | "pallet";
}) {
  // Идём desc по дате — последние изменения сверху
  const sorted = useMemo(
    () =>
      [...rows].sort((a, b) =>
        a.effective_from < b.effective_from ? 1 : -1,
      ),
    [rows],
  );
  return (
    <div className="card overflow-x-auto p-0">
      <table className="min-w-full text-sm">
        <thead className="sticky-table-head text-muted text-xs uppercase">
          <tr>
            <th className="text-left p-2">С даты</th>
            <th className="text-right p-2">Δ Логистика база</th>
            <th className="text-right p-2">Δ Логистика литр</th>
            <th className="text-right p-2">Δ Хранение база</th>
            <th className="text-right p-2">Δ Хранение литр</th>
            {kind === "pallet" && (
              <th className="text-right p-2">Δ Коэф. (%)</th>
            )}
            <th className="text-right p-2">Загружено</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const next = sorted[i + 1] || null;
            return (
              <tr key={r.effective_from} className="border-t border-border">
                <td className="p-2">
                  {fmtDate(r.effective_from)}
                  {r.is_baseline && (
                    <span className="ml-2 text-xs text-muted">(baseline)</span>
                  )}
                </td>
                <DeltaCell curr={r.delivery_base} prev={next?.delivery_base} />
                <DeltaCell curr={r.delivery_liter} prev={next?.delivery_liter} />
                <DeltaCell
                  curr={r.storage_base}
                  prev={next?.storage_base}
                  digits={6}
                />
                <DeltaCell
                  curr={r.storage_liter}
                  prev={next?.storage_liter}
                  digits={6}
                />
                {kind === "pallet" && (
                  <DeltaCell
                    curr={r.storage_expr}
                    prev={next?.storage_expr}
                  />
                )}
                <td className="p-2 text-right text-muted text-xs">
                  {r.dt_next ? `WB next: ${fmtDate(r.dt_next)}` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DeltaCell({
  curr,
  prev,
  digits = 4,
}: {
  curr: number | null | undefined;
  prev: number | null | undefined;
  digits?: number;
}) {
  const d = delta(curr, prev);
  return (
    <td className="p-2 text-right font-mono">
      <div className="font-mono">{fmtNum(curr, digits)}</div>
      <div className={`text-xs ${d.className}`}>{d.text}</div>
    </td>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Tab 3 — комиссии по предмету
// ─────────────────────────────────────────────────────────────────────────

function CommissionTab() {
  const [search, setSearch] = useState("");
  const [subject, setSubject] = useState<string>("");

  const subjQ = useQuery({
    queryKey: ["tariff-subjects", search],
    queryFn: () => api.tariffSubjects(search || undefined, 500),
  });

  const timelineQ = useQuery({
    queryKey: ["tariff-comm-timeline", subject],
    queryFn: () => api.tariffCommissionTimeline(subject),
    enabled: !!subject,
  });

  // Авто-выбор первого предмета при загрузке списка.
  useEffect(() => {
    if (subject) return;
    const items = subjQ.data?.items;
    if (items?.length) setSubject(items[0].subject_name);
  }, [subjQ.data, subject]);

  const chartData = (timelineQ.data?.items || []).map((r) => ({
    label: fmtDate(r.effective_from),
    commission_fbo: r.commission_fbo,
    commission_fbs: r.commission_fbs,
    commission_express: r.commission_express,
  }));

  const sorted = useMemo(
    () =>
      [...(timelineQ.data?.items || [])].sort((a, b) =>
        a.effective_from < b.effective_from ? 1 : -1,
      ),
    [timelineQ.data],
  );

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-sm">Поиск предмета:</label>
        <input
          type="text"
          className="input min-w-[200px]"
          placeholder="например, куртка"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="input min-w-[280px]"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          disabled={subjQ.isLoading}
        >
          {subjQ.data?.items.map((s) => (
            <option key={s.subject_name} value={s.subject_name}>
              {s.subject_name}
              {s.subject_id ? ` (#${s.subject_id})` : ""}
            </option>
          ))}
        </select>
      </div>

      {timelineQ.isLoading && <Skeleton variant="table" rows={6} />}
      {timelineQ.data && timelineQ.data.items.length === 0 && (
        <div className="card text-muted text-sm">
          Нет изменений для предмета «{subject}» в последние 180 дней.
        </div>
      )}
      {chartData.length > 0 && (
        <ChartCard
          title={`Комиссии WB по предмету «${subject}» (%)`}
          data={chartData}
          lines={[
            { key: "commission_fbo", label: "FBO", color: "#3b82f6" },
            { key: "commission_fbs", label: "FBS", color: "#f59e0b" },
            {
              key: "commission_express",
              label: "Express",
              color: "#10b981",
            },
          ]}
        />
      )}
      {sorted.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <table className="min-w-full text-sm">
            <thead className="sticky-table-head text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">С даты</th>
                <th className="text-right p-2">Δ FBO, %</th>
                <th className="text-right p-2">Δ FBS, %</th>
                <th className="text-right p-2">Δ Express, %</th>
                <th className="text-right p-2">Платное хранение KGVP</th>
                <th className="text-right p-2">Возврат, ₽</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => {
                const next = sorted[i + 1] || null;
                return (
                  <tr key={r.effective_from} className="border-t border-border">
                    <td className="p-2">
                      {fmtDate(r.effective_from)}
                      {r.is_baseline && (
                        <span className="ml-2 text-xs text-muted">
                          (baseline)
                        </span>
                      )}
                    </td>
                    <DeltaCell
                      curr={r.commission_fbo}
                      prev={next?.commission_fbo}
                      digits={2}
                    />
                    <DeltaCell
                      curr={r.commission_fbs}
                      prev={next?.commission_fbs}
                      digits={2}
                    />
                    <DeltaCell
                      curr={r.commission_express}
                      prev={next?.commission_express}
                      digits={2}
                    />
                    <td className="p-2 text-right font-mono">
                      {fmtNum(r.paid_storage_kgvp, 2)}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtNum(r.return_cost, 2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
