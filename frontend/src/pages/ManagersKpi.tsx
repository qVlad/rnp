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
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";

const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];

const today = new Date();

type Mode = "preliminary" | "final" | "hybrid";

export default function ManagersKpi() {
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [mode, setMode] = useState<Mode>("hybrid");

  const q = useQuery({
    queryKey: ["managers-kpi", year, month, mode],
    queryFn: () => api.managersKpi(year, month, mode),
  });

  const items = q.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">KPI менеджеров</h1>
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
      </div>

      <div className="card text-sm text-muted leading-relaxed">
        Сводка по менеджерам за {MONTHS[month - 1]} {year}. Каждая строка —
        менеджер и KPI по всем его брендам (из назначений в разделе «Бренды»).
        Сортировка — по убыванию чистой выручки. Менеджеры без назначений
        внизу с пометкой «нет брендов».
      </div>

      {q.isLoading && <div className="text-muted">Загрузка…</div>}
      {q.isError && (
        <div className="card text-red-400 text-sm">
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
              <tr className="text-xs text-muted border-b border-border">
                <th className="text-left py-2 pr-3">Менеджер</th>
                <th className="text-left py-2 pr-3">Бренды</th>
                <th className="text-right py-2 pr-3" title="Чистая выручка после WB-комиссии (revenue_net)">
                  Выручка
                </th>
                <th className="text-right py-2 pr-3" title="Маржинальная прибыль = revenue_net − COGS − ad_cost">
                  Маржа ₽
                </th>
                <th className="text-right py-2 pr-3" title="Маржа в % от revenue_net. Норма 5-25%">
                  Маржа %
                </th>
                <th className="text-right py-2 pr-3" title="Доля рекламных расходов от gross-выручки заказов">
                  ДРР
                </th>
                <th className="text-right py-2 pr-3" title="% выкупа за период">
                  Выкуп
                </th>
                <th className="text-right py-2 pr-3">Заказы</th>
                <th className="text-right py-2 pr-3" title="Расходы на рекламу WB + внеш. маркетинг">
                  Реклама
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
                        ? "text-red-400"
                        : "text-muted";
                return (
                  <tr
                    key={m.user_id}
                    className={`border-b border-border/40 ${
                      m.no_brands ? "opacity-60" : ""
                    }`}
                  >
                    <td className="py-2 pr-3">
                      <div className="font-medium">
                        {m.full_name || m.username}
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
                    <td className="py-2 pr-3 text-right">
                      {fmtRub(m.revenue_net_rub)}
                    </td>
                    <td className="py-2 pr-3 text-right">
                      {fmtRub(m.margin_rub)}
                    </td>
                    <td className={`py-2 pr-3 text-right ${marginColor}`}>
                      {fmtPct(m.margin_pct)}
                    </td>
                    <td className="py-2 pr-3 text-right">
                      {fmtPct(m.drr_pct)}
                    </td>
                    <td className="py-2 pr-3 text-right">
                      {fmtPct(m.buyout_pct)}
                    </td>
                    <td className="py-2 pr-3 text-right">
                      {fmtNum(m.orders)}
                    </td>
                    <td className="py-2 pr-3 text-right">
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
        Бренд без назначения = менеджер не виден здесь, но видим в Brands.
      </div>
    </div>
  );
}
