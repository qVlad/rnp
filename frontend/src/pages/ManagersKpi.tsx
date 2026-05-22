/**
 * KPI каждого менеджера за выбранный месяц (TASK-DEV-001).
 *
 * Главная боль РОПа из ревью c8f6609 — нет одного экрана где видно
 * как отрабатывают менеджеры. Раньше приходилось ходить по бренду в
 * Dashboard для каждого и сводить руками. Здесь — таблица с одной
 * строкой на менеджера: бренды, выручка, маржа, ДРР, заказы, реклама.
 *
 * Доступ: director + head_of_sales. Защищено DirectorOrHead-обёрткой
 * в App.tsx и `directorOrHead: true` в Layout.tsx (пункт меню).
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { LineChart, Line, YAxis } from "recharts";
import { api } from "@/api/client";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";
import PageHeader from "@/components/PageHeader";

const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

const today = new Date();

type Mode = "preliminary" | "final" | "hybrid";

// Поля по которым можно сортировать (TASK-DEV-009 — клик по <th>).
type SortField =
  | "full_name"
  | "revenue_net_rub"
  | "margin_rub"
  | "margin_pct"
  | "delta_revenue_pct"
  | "drr_pct"
  | "buyout_pct"
  | "orders"
  | "ad_cost_rub";

const SORT_KEY = "managers-kpi.sort.v1";

function _loadSort(): { field: SortField; dir: "asc" | "desc" } {
  try {
    const raw = localStorage.getItem(SORT_KEY);
    if (raw) {
      const v = JSON.parse(raw);
      if (v && typeof v.field === "string" && (v.dir === "asc" || v.dir === "desc")) {
        return v;
      }
    }
  } catch {}
  return { field: "revenue_net_rub", dir: "desc" };
}

export default function ManagersKpi() {
  const navigate = useNavigate();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [mode, setMode] = useState<Mode>("hybrid");
  const [sort, setSort] = useState(_loadSort);

  // TASK-DEV-018 — drill-down: клик по строке → /pnl с фильтром брендов менеджера.
  const openDrilldown = (m: any) => {
    if (m.no_brands || !m.brands?.length) return;
    const brands = encodeURIComponent(m.brands.join(","));
    const label = encodeURIComponent(m.full_name || m.username);
    navigate(`/pnl?brands=${brands}&label=${label}`);
  };

  const q = useQuery({
    queryKey: ["managers-kpi", year, month, mode],
    queryFn: () => api.managersKpi(year, month, mode),
  });

  const rawItems = q.data?.items ?? [];

  // Сортировка: no_brands всегда внизу, остальное — по выбранному полю.
  const items = useMemo(() => {
    const withBrands: any[] = [];
    const noBrands: any[] = [];
    for (const it of rawItems) (it.no_brands ? noBrands : withBrands).push(it);
    const cmp = (a: any, b: any): number => {
      const av = a[sort.field];
      const bv = b[sort.field];
      // null/undefined в хвост (например, delta_revenue_pct=null если prev=0)
      const aNull = av == null;
      const bNull = bv == null;
      if (aNull && bNull) return 0;
      if (aNull) return 1;
      if (bNull) return -1;
      let d: number;
      if (typeof av === "string" || typeof bv === "string") {
        d = String(av).localeCompare(String(bv), "ru");
      } else {
        d = Number(av) - Number(bv);
      }
      return sort.dir === "asc" ? d : -d;
    };
    withBrands.sort(cmp);
    return [...withBrands, ...noBrands];
  }, [rawItems, sort]);

  const onSortClick = (field: SortField) => {
    setSort((prev) => {
      const next =
        prev.field === field
          ? { field, dir: prev.dir === "asc" ? "desc" : "asc" }
          : { field, dir: "desc" as const };
      try {
        localStorage.setItem(SORT_KEY, JSON.stringify(next));
      } catch {}
      return next as { field: SortField; dir: "asc" | "desc" };
    });
  };

  const sortArrow = (field: SortField) =>
    sort.field === field ? (sort.dir === "asc" ? " ↑" : " ↓") : "";

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="KPI менеджеров"
        actions={
          <div className="flex items-end gap-3 flex-wrap">
            <label className="flex flex-col text-xs text-muted">
              Месяц
              <select
                className="input"
                value={month}
                onChange={(e: any) => setMonth(Number(e.target.value))}
              >
                {MONTHS.map((m, i) => (
                  <option key={i} value={i + 1}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col text-xs text-muted">
              Год
              <input
                type="number"
                min={2020}
                max={2100}
                className="input"
                value={year}
                onChange={(e: any) =>
                  setYear(Number(e.target.value) || today.getFullYear())
                }
              />
            </label>
            <label className="flex flex-col text-xs text-muted">
              Режим
              <select
                className="input"
                value={mode}
                onChange={(e: any) => setMode(e.target.value as Mode)}
                title={
                  "Гибрид (рекоменд.) — финальные за закрытые недели + черновые за свежие. " +
                  "Финальные — только wb_report_detail (лаг ~14 дн). " +
                  "Предварительные — wb_orders/wb_sales (свежие, но шумят)."
                }
              >
                <option value="hybrid">Гибрид</option>
                <option value="final">Финальные</option>
                <option value="preliminary">Предварительные</option>
              </select>
            </label>
          </div>
        }
      />

      <div className="card text-sm text-muted leading-relaxed">
        Сводка по менеджерам за {MONTHS[month - 1]} {year}. Каждая строка —
        менеджер и KPI по всем его брендам (из назначений в разделе «Бренды»).
        Клик по заголовку колонки — сортировка (по умолчанию выручка ↓).
        Колонка «Δ м/м» и sparkline — сравнение с прошлым месяцем (всегда
        финальные цифры за прошлый, чтобы preliminary-шум не давал ложную
        просадку). Менеджеры без назначений — внизу.
      </div>

      {q.isLoading && <div className="text-muted">Загрузка…</div>}
      {q.isError && (
        <div className="card text-danger text-sm">
          Ошибка: {(q.error as Error).message}
        </div>
      )}
      {q.data && items.length === 0 && (
        <div className="card text-muted text-sm">
          В тенанте нет активных менеджеров. Создайте пользователя с ролью{" "}
          <code>manager</code> в разделе «Пользователи» и назначьте ему бренды.
        </div>
      )}

      {items.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted border-b border-border select-none">
                <th
                  className="text-left py-2 pr-3 cursor-pointer hover:text-accent"
                  onClick={() => onSortClick("full_name")}
                >
                  Менеджер{sortArrow("full_name")}
                </th>
                <th className="text-left py-2 pr-3">Бренды</th>
                <th
                  className="text-right py-2 pr-3 cursor-pointer hover:text-accent"
                  title="Чистая выручка после WB-комиссии (revenue_net)"
                  onClick={() => onSortClick("revenue_net_rub")}
                >
                  Выручка{sortArrow("revenue_net_rub")}
                </th>
                <th
                  className="text-right py-2 pr-3 cursor-pointer hover:text-accent"
                  title="Δ выручки к прошлому месяцу (всегда финальные цифры за прошлый месяц, чтобы не было ложной просадки)"
                  onClick={() => onSortClick("delta_revenue_pct")}
                >
                  Δ м/м{sortArrow("delta_revenue_pct")}
                </th>
                <th className="text-center py-2 pr-3" title="Выручка по месяцам за последние 6 (sparkline, oldest first)">
                  6 мес
                </th>
                <th
                  className="text-right py-2 pr-3 cursor-pointer hover:text-accent"
                  title="Маржинальная прибыль = revenue_net − COGS − ad_cost"
                  onClick={() => onSortClick("margin_rub")}
                >
                  Маржа ₽{sortArrow("margin_rub")}
                </th>
                <th
                  className="text-right py-2 pr-3 cursor-pointer hover:text-accent"
                  title="Маржа в % от revenue_net. Норма 5-25%"
                  onClick={() => onSortClick("margin_pct")}
                >
                  Маржа %{sortArrow("margin_pct")}
                </th>
                <th
                  className="text-right py-2 pr-3 cursor-pointer hover:text-accent"
                  title="Доля рекламных расходов от gross-выручки заказов"
                  onClick={() => onSortClick("drr_pct")}
                >
                  ДРР{sortArrow("drr_pct")}
                </th>
                <th
                  className="text-right py-2 pr-3 cursor-pointer hover:text-accent"
                  title="% выкупа за период"
                  onClick={() => onSortClick("buyout_pct")}
                >
                  Выкуп{sortArrow("buyout_pct")}
                </th>
                <th
                  className="text-right py-2 pr-3 cursor-pointer hover:text-accent"
                  onClick={() => onSortClick("orders")}
                >
                  Заказы{sortArrow("orders")}
                </th>
                <th
                  className="text-right py-2 pr-3 cursor-pointer hover:text-accent"
                  title="Расходы на рекламу WB + внеш. маркетинг"
                  onClick={() => onSortClick("ad_cost_rub")}
                >
                  Реклама{sortArrow("ad_cost_rub")}
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((m) => {
                const marginPct = Number(m.margin_pct);
                const marginColor =
                  marginPct >= 15
                    ? "text-success"
                    : marginPct >= 5
                      ? "text-warning"
                      : marginPct < 0
                        ? "text-danger"
                        : "text-muted";
                // Δ-цвет: |Δ|<3% — шум, серый. >+3 — зелёный. <-3 — красный.
                const dRev = m.delta_revenue_pct;
                const deltaColor =
                  dRev == null || Math.abs(Number(dRev)) < 3
                    ? "text-muted"
                    : Number(dRev) > 0
                      ? "text-success"
                      : "text-danger";
                const deltaLabel =
                  dRev == null
                    ? "—"
                    : `${Number(dRev) > 0 ? "+" : ""}${Number(dRev).toFixed(1)}%`;
                const sparkData = (m.sparkline_revenue ?? []).map(
                  (v: number, i: number) => ({ i, v: Number(v) || 0 }),
                );
                const sparkAllZero = sparkData.every((p: any) => p.v === 0);
                return (
                  <tr
                    key={m.user_id}
                    className={`border-b border-border/40 transition-colors ${
                      m.no_brands
                        ? "opacity-60"
                        : "cursor-pointer hover:bg-surface-2/40"
                    }`}
                    onClick={() => openDrilldown(m)}
                    title={
                      m.no_brands
                        ? undefined
                        : `Открыть P&L с фильтром по брендам ${m.brands.join(", ")}`
                    }
                  >
                    <td className="py-2 pr-3">
                      <div className="font-medium flex items-center gap-1.5">
                        {m.full_name || m.username}
                        {!m.no_brands && (
                          <span
                            className="text-muted text-[10px]"
                            aria-hidden
                          >
                            →
                          </span>
                        )}
                      </div>
                      {m.full_name && (
                        <div className="text-xs text-muted">{m.username}</div>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-xs">
                      {m.no_brands ? (
                        <span className="text-warning">
                          нет назначений
                        </span>
                      ) : (
                        <span className="text-muted">
                          {m.brands.join(", ")}
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono">
                      {fmtRub(m.revenue_net_rub)}
                    </td>
                    <td
                      className={`py-2 pr-3 text-right ${deltaColor}`}
                      title={
                        dRev == null
                          ? "Прошлый месяц был нулевым — Δ не считается"
                          : `Прошлый месяц: ${fmtRub(m.prev_revenue_net_rub ?? 0)}`
                      }
                    >
                      {m.no_brands ? "—" : deltaLabel}
                    </td>
                    <td className="py-2 pr-3 text-center">
                      {m.no_brands || sparkAllZero ? (
                        <span className="text-muted text-xs">—</span>
                      ) : (
                        <div
                          className={
                            Number(dRev ?? 0) >= 0 ? "text-success" : "text-danger"
                          }
                        >
                          <LineChart width={80} height={24} data={sparkData}>
                            <YAxis hide domain={["dataMin", "dataMax"]} />
                            <Line
                              type="monotone"
                              dataKey="v"
                              stroke="currentColor"
                              strokeWidth={1.5}
                              dot={false}
                              isAnimationActive={false}
                            />
                          </LineChart>
                        </div>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono">
                      {fmtRub(m.margin_rub)}
                    </td>
                    <td className={`py-2 pr-3 text-right ${marginColor}`}>
                      {fmtPct(m.margin_pct)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono">
                      {fmtPct(m.drr_pct)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono">
                      {fmtPct(m.buyout_pct)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono">
                      {fmtNum(m.orders)}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono">
                      {fmtRub(m.ad_cost_rub)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="text-xs text-muted">
        Подсказка: маржа &lt; 5% — красное, 5-15% — жёлтое, &gt;15% — зелёное.
        Δ м/м: |Δ| &lt; 3% — серое (шум), &gt; +3% зелёное, &lt; −3% красное.
        Бренд без назначения = менеджер не виден здесь, но видим в Brands.
      </div>
    </div>
  );
}
