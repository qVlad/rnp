import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { DateRangePicker } from "@/components/DateRangePicker";
import { fmtNum, fmtPct, fmtRub } from "@/lib/format";
import { usePeriod } from "@/contexts/PeriodContext";
import PageHeader from "@/components/PageHeader";
import { useFilters, filterKey } from "@/contexts/FilterContext";
import { GlobalFilterBar } from "@/components/GlobalFilterBar";

type Metric =
  | "drr"
  | "spent"
  | "orders"
  | "clicks"
  | "revenue"
  | "cpl"
  | "cps"
  | "basket_conv"
  | "order_conv";

const metricLabel: Record<Metric, string> = {
  drr: "ДРР %",
  spent: "Расход ₽",
  revenue: "Выручка ₽",
  orders: "Заказы шт",
  clicks: "Клики шт",
  cpl: "CPL ₽",
  cps: "CPS ₽",
  basket_conv: "Корз. конв. %",
  order_conv: "Зак. конв. %",
};

const metricHelp: Record<Metric, string> = {
  drr: "Доля рекламных расходов = sum_spent / sum_price × 100. Зелёный — низкий ДРР (хорошо), красный — высокий (слив).",
  spent: "Сумма списанная с рекламного баланса за день.",
  revenue: "Выручка от кликов по этому объявлению (`sum_price`).",
  orders: "Количество заказов с этого объявления.",
  clicks: "Количество кликов.",
  cpl: "Стоимость клика (Cost Per Lead) = расход / клики. ₽ за клик. Чем ниже — тем дешевле трафик.",
  cps: "Стоимость заказа (Cost Per Sale) = расход / заказы. ₽ за заказ. Сравнивай со средним чеком — должно быть в разы меньше.",
  basket_conv: "Конверсия в корзину = atbs / клики × 100. % людей, которые после клика добавили товар в корзину. Норма 5-20%.",
  order_conv: "Конверсия в заказ = заказы / клики × 100. % людей, которые после клика оформили заказ. Норма 1-5%.",
};

// Является ли метрика процентной (для форматирования в ячейках)
function isPercentMetric(m: Metric): boolean {
  return m === "drr" || m === "basket_conv" || m === "order_conv";
}

// Является ли метрика рублёвой
function isRubMetric(m: Metric): boolean {
  return m === "spent" || m === "revenue" || m === "cpl" || m === "cps";
}

// Форматирование значения произвольной метрики для tooltip (для 2-й метрики).
function fmtTitle2(m: Metric, val: number): string {
  if (m === "drr") return fmtPct(val);
  if (m === "basket_conv" || m === "order_conv") return fmtPct(val, 1);
  if (isRubMetric(m)) return fmtRub(val);
  return fmtNum(val);
}

function cellColor(metric: Metric, val: number | null): string {
  if (val == null || val <= 0) return "bg-bg text-muted/60";
  if (metric === "drr") {
    // ДРР: <5 насыщ. зелёный, 5-15 зелёный, 15-30 жёлтый, 30-50 оранжевый, >50 красный
    if (val < 5) return "bg-success/40 text-fg";
    if (val < 15) return "bg-success-subtle";
    if (val < 30) return "bg-warn-subtle";
    if (val < 50) return "bg-warn/30";
    return "bg-danger/40 text-fg";
  }
  if (metric === "basket_conv") {
    // Корзина-конверсия: чем выше — тем лучше (зелёный)
    if (val >= 20) return "bg-success/40 text-fg";
    if (val >= 10) return "bg-success-subtle";
    if (val >= 5) return "bg-warn-subtle";
    return "bg-danger/30";
  }
  if (metric === "order_conv") {
    // Order-конверсия: норма 1-5%, выше — отлично
    if (val >= 5) return "bg-success/40 text-fg";
    if (val >= 2) return "bg-success-subtle";
    if (val >= 1) return "bg-warn-subtle";
    return "bg-danger/30";
  }
  // Для остальных метрик — accent с opacity (см. intensityStyle ниже)
  return "bg-accent-subtle";
}

export default function AdsHeatmap() {
  // TASK-UI-005: глобальный период.
  const { range, setPeriod } = usePeriod();
  const from = range.from;
  const to = range.to;
  const [metric, setMetric] = useState<Metric>("drr");
  // DEV-080 (TS-parity): двойная метрика — цвет = metric, размер ячейки = sizeMetric.
  const [sizeMetric, setSizeMetric] = useState<Metric | "none">("none");
  const { filters, toParams } = useFilters();

  const q = useQuery<any>({
    queryKey: ["ads-heatmap", from, to, metric, filterKey(filters)],
    queryFn: () => api.adsHeatmap(from, to, metric, toParams()),
  });
  // Вторая метрика — отдельный запрос (API отдаёт по одной метрике за раз).
  // Кампании/дни совпадают (тот же период/фильтры) → выравниваем по advert_id.
  const sizeQ = useQuery<any>({
    queryKey: ["ads-heatmap-size", from, to, sizeMetric, filterKey(filters)],
    queryFn: () => api.adsHeatmap(from, to, sizeMetric as Metric, toParams()),
    enabled: sizeMetric !== "none",
  });
  const d: any = q.data;
  const days: string[] = d?.days || [];
  const campaigns: any[] = d?.campaigns || [];
  const totals = d?.totals;

  // Для метрик с opacity-расцветкой считаем max. drr/basket_conv/order_conv
  // имеют свою дискретную палитру (cellColor), max не нужен.
  const maxVal = useMemo(() => {
    if (metric === "drr" || metric === "basket_conv" || metric === "order_conv")
      return null;
    let m = 0;
    for (const c of campaigns) for (const v of c.cells) if (v != null && v > m) m = v;
    return m || 1;
  }, [campaigns, metric]);

  // Карта advert_id → cells второй метрики + её max (для масштаба размера).
  const sizeByAdvert = useMemo(() => {
    const map: Record<string, (number | null)[]> = {};
    let mx = 0;
    if (sizeMetric !== "none" && sizeQ.data?.campaigns) {
      for (const c of sizeQ.data.campaigns) {
        map[String(c.advert_id)] = c.cells;
        for (const v of c.cells) if (v != null && v > mx) mx = v;
      }
    }
    return { map, max: mx || 1 };
  }, [sizeQ.data, sizeMetric]);

  // Масштаб 0.3..1.0 по площади (sqrt) для значения второй метрики.
  const sizeScale = (advertId: number | string, i: number): number => {
    if (sizeMetric === "none") return 1;
    const cells = sizeByAdvert.map[String(advertId)];
    const v = cells?.[i];
    if (v == null || v <= 0) return 0.22;
    return Math.max(0.3, Math.min(1, Math.sqrt(v / sizeByAdvert.max)));
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Тепловая карта рекламы"
        subtitle={metricHelp[metric]}
      />

      {/* DEV-062 — глобальные фильтры. */}
      <GlobalFilterBar />

      <section className="card flex flex-wrap gap-4 items-end">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Период</span>
          <DateRangePicker
            from={from}
            to={to}
            onChange={(r) =>
              setPeriod({ kind: "custom", from: r.from, to: r.to })
            }
          />
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Метрика</span>
          <select
            className="input"
            value={metric}
            onChange={(e) => setMetric(e.target.value as Metric)}
            title={metricHelp[metric]}
          >
            <optgroup label="Финансы">
              {(["drr", "spent", "revenue"] as Metric[]).map((m) => (
                <option key={m} value={m}>
                  {metricLabel[m]}
                </option>
              ))}
            </optgroup>
            <optgroup label="Воронка">
              {(["orders", "clicks"] as Metric[]).map((m) => (
                <option key={m} value={m}>
                  {metricLabel[m]}
                </option>
              ))}
            </optgroup>
            <optgroup label="Стоимость / Конверсия (TASK-LEAD-033)">
              {(["cpl", "cps", "basket_conv", "order_conv"] as Metric[]).map((m) => (
                <option key={m} value={m}>
                  {metricLabel[m]}
                </option>
              ))}
            </optgroup>
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Размер ячейки</span>
          <select
            className="input"
            value={sizeMetric}
            onChange={(e) => setSizeMetric(e.target.value as Metric | "none")}
            title="Вторая метрика: размер ячейки ∝ её значению (цвет — основная метрика). Как в TrueStats."
          >
            <option value="none">— нет (одна метрика) —</option>
            {(
              [
                "spent",
                "revenue",
                "orders",
                "clicks",
                "cpl",
                "cps",
              ] as Metric[]
            ).map((m) => (
              <option key={m} value={m} disabled={m === metric}>
                {metricLabel[m]}
              </option>
            ))}
          </select>
        </div>
        {totals && (
          <div className="ml-auto text-xs text-muted">
            <div>Расход: <span className="text-fg font-mono">{fmtRub(totals.spent)}</span></div>
            <div>Выручка: <span className="text-fg font-mono">{fmtRub(totals.revenue)}</span></div>
            <div>
              ДРР итого:{" "}
              <span className="text-fg font-mono">
                {totals.drr != null ? fmtPct(totals.drr) : "—"}
              </span>
            </div>
            <div>
              CPL / CPS:{" "}
              <span className="text-fg font-mono">
                {totals.cpl != null ? fmtRub(totals.cpl) : "—"} /{" "}
                {totals.cps != null ? fmtRub(totals.cps) : "—"}
              </span>
            </div>
            <div>
              Корз. / Зак.:{" "}
              <span className="text-fg font-mono">
                {totals.basket_conv != null ? `${fmtPct(totals.basket_conv, 1)}` : "—"} /{" "}
                {totals.order_conv != null ? `${fmtPct(totals.order_conv, 1)}` : "—"}
              </span>
            </div>
          </div>
        )}
      </section>

      <section className="card overflow-x-auto">
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {q.error && <div className="text-danger">Ошибка: {String((q.error as any).message)}</div>}
        {!q.isLoading && campaigns.length === 0 && (
          <div className="text-muted">Нет рекламных данных за период. Проверь что синк `/adv/v3/fullstats` отработал.</div>
        )}
        {campaigns.length > 0 && (
          <table className="text-xs border-collapse">
            <thead>
              <tr className="border-b border-border">
                <th className="p-1 text-left sticky left-0 bg-bg z-10 min-w-[200px]">
                  Кампания
                </th>
                <th className="p-1 text-right">Расход</th>
                <th className="p-1 text-right">ДРР %</th>
                {days.map((d) => (
                  <th key={d} className="p-1 text-center font-normal text-muted text-[10px] min-w-[30px]">
                    {d.slice(5)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c: any) => (
                <tr key={c.advert_id} className="border-b border-border/40">
                  <td className="p-1 sticky left-0 bg-bg z-10">
                    <div className="font-mono text-[11px] truncate max-w-[200px]" title={c.name}>
                      {c.name}
                    </div>
                    <div className="text-muted text-[10px]">
                      #{c.advert_id} · {c.status || "—"}
                    </div>
                  </td>
                  <td className="p-1 text-right font-mono">{fmtRub(c.spent)}</td>
                  <td className="p-1 text-right font-mono">
                    {c.drr_total != null ? (
                      <span
                        className={
                          c.drr_total < 15
                            ? "text-success"
                            : c.drr_total < 30
                            ? "text-warning"
                            : "text-danger"
                        }
                      >
                        {fmtPct(c.drr_total)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  {c.cells.map((v: number | null, i: number) => {
                    const cls = cellColor(metric, v);
                    // Для drr и conv-метрик расцветка уже задана в cellColor —
                    // не накладываем opacity (иначе зелёный/красный размывается).
                    const useOpacity =
                      metric !== "drr" &&
                      metric !== "basket_conv" &&
                      metric !== "order_conv";
                    const intensityStyle =
                      useOpacity && v != null && maxVal
                        ? { opacity: Math.max(0.2, Math.min(1, v / maxVal)) }
                        : undefined;
                    // math: conditional digits per metric — drr 0 digits, others 1
                    const fmtCell = (val: number) => {
                      if (isPercentMetric(metric)) return `${val.toFixed(metric === "drr" ? 0 : 1)}`;
                      if (isRubMetric(metric))
                        return val >= 1000
                          ? `${Math.round(val / 100) / 10}k`
                          : metric === "cpl" || metric === "cps"
                          ? val.toFixed(val < 10 ? 1 : 0)
                          : Math.round(val);
                      return Math.round(val);
                    };
                    const fmtTitle = (val: number) => {
                      if (metric === "drr") return fmtPct(val);
                      if (metric === "basket_conv" || metric === "order_conv")
                        return `${fmtPct(val, 1)}`;
                      if (isRubMetric(metric)) return fmtRub(val);
                      return fmtNum(val);
                    };
                    // Двойная метрика: цвет ячейки несёт metric, а размер
                    // внутреннего блока ∝ значению sizeMetric (DEV-080).
                    if (sizeMetric !== "none") {
                      const scale = sizeScale(c.advert_id, i);
                      const sizeCells = sizeByAdvert.map[String(c.advert_id)];
                      const sizeVal = sizeCells?.[i];
                      const pct = `${Math.round(scale * 100)}%`;
                      return (
                        <td
                          key={i}
                          className="p-0.5 text-center align-middle min-w-[30px] h-[26px]"
                          title={`${days[i]}: ${metricLabel[metric]} ${
                            v != null ? fmtTitle(v) : "—"
                          } · ${metricLabel[sizeMetric as Metric]} ${
                            sizeVal != null ? fmtTitle2(sizeMetric as Metric, sizeVal) : "—"
                          }`}
                        >
                          <div className="w-full h-full flex items-center justify-center">
                            <div
                              className={`rounded-sm ${cls}`}
                              style={{ width: pct, height: pct, ...intensityStyle }}
                            />
                          </div>
                        </td>
                      );
                    }
                    return (
                      <td
                        key={i}
                        className={`p-1 text-center text-[10px] font-mono ${cls}`}
                        style={intensityStyle}
                        title={`${days[i]}: ${v != null ? fmtTitle(v) : "—"}`}
                      >
                        {v != null ? fmtCell(v) : ""}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
