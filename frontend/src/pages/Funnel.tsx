/**
 * Funnel views → cart → order → buyout per-SKU (TASK-LEAD-025).
 *
 * Закрывает дыру vs MPump «Воронка продаж и Конверсии». У нас раньше был
 * только скаляр buyout_pct — не видно где SKU теряет покупателя.
 *
 * Источник — реклама (`wb_ad_stats_daily`): views/atbs/orders + выкупы
 * из wb_report_detail. Органика не учитывается (WB не отдаёт через API).
 *
 * UI: таблица с 4 шагами + conv-rates + «слабая ступень» (где SKU больше
 * всего теряет). Сортировка по показу или по слабой ступени.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtNum, fmtPct } from "@/lib/format";
import { useTagFilter } from "@/lib/useTagFilter";
import TagFilterDropdown from "@/components/TagFilterDropdown";

type SortKey =
  | "views"
  | "ctr_pct"
  | "cart_rate_pct"
  | "buyout_rate_pct"
  | "buyouts";

const WEAKEST_LABEL: Record<string, string> = {
  "views→cart": "Показ → корзина",
  "cart→order": "Корзина → заказ",
  "order→buyout": "Заказ → выкуп",
};

const WEAKEST_COLOR: Record<string, string> = {
  "views→cart": "bg-danger-subtle text-danger",
  "cart→order": "bg-warning/10 text-warning",
  "order→buyout": "bg-accent/10 text-accent",
};

function rateColor(pct: number): string {
  if (pct >= 10) return "text-success";
  if (pct >= 3) return "text-warning";
  return "text-danger";
}

export default function Funnel() {
  const [days, setDays] = useState(14);
  const [sortKey, setSortKey] = useState<SortKey>("views");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const q = useQuery({
    queryKey: ["funnel-by-sku", days],
    queryFn: () => api.funnelBySku(days),
  });

  const { matchTag } = useTagFilter("funnel.tag-filter.v1");

  const items = useMemo(() => {
    const arr = (q.data?.items ?? []).filter((it) => matchTag(it.nm_id));
    arr.sort((a, b) => {
      const av = Number((a as any)[sortKey] ?? 0);
      const bv = Number((b as any)[sortKey] ?? 0);
      return sortDir === "desc" ? bv - av : av - bv;
    });
    return arr;
  }, [q.data, sortKey, sortDir, matchTag]);

  const totals = q.data?.totals;

  const onSort = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    else { setSortKey(k); setSortDir("desc"); }
  };
  const sortIndicator = (k: SortKey) =>
    sortKey === k ? (sortDir === "desc" ? " ▼" : " ▲") : "";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold">Воронка продаж — per SKU</h1>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-muted">Период:</span>
          {[7, 14, 30].map((n) => (
            <button
              key={n}
              type="button"
              className={`btn text-xs ${days === n ? "border-accent text-accent" : ""}`}
              onClick={() => setDays(n)}
            >
              {n} дн
            </button>
          ))}
          <TagFilterDropdown storageKey="funnel.tag-filter.v1" />
        </div>
      </div>

      <div className="card text-sm text-muted leading-relaxed">
        4 шага: <strong>показ</strong> (реклама) → <strong>корзина</strong> (atbs)
        → <strong>заказ</strong> → <strong>выкуп</strong>. Conv-rate низкий
        (&lt; 3%) — красный, 3-10% — жёлтый, &gt; 10% — зелёный. «Слабая ступень» —
        где SKU теряет больше всего покупателей (самый низкий из 3 rate'ов).
        Только трафик из <strong>рекламы</strong> — органика не учитывается.
      </div>

      {totals && (
        <div className="card grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
          <div>
            <div className="text-xs text-muted">Показы</div>
            <div className="text-lg font-semibold">{fmtNum(totals.views)}</div>
          </div>
          <div>
            <div className="text-xs text-muted">Корзина (CTR)</div>
            <div className={`text-lg font-semibold ${rateColor(totals.ctr_pct)}`}>
              {fmtPct(totals.ctr_pct)}
            </div>
            <div className="text-[10px] text-muted">{fmtNum(totals.atbs)}</div>
          </div>
          <div>
            <div className="text-xs text-muted">Корзина→Заказ</div>
            <div className={`text-lg font-semibold ${rateColor(totals.cart_rate_pct)}`}>
              {fmtPct(totals.cart_rate_pct)}
            </div>
            <div className="text-[10px] text-muted">{fmtNum(totals.orders)}</div>
          </div>
          <div>
            <div className="text-xs text-muted">Заказ→Выкуп</div>
            <div className={`text-lg font-semibold ${rateColor(totals.buyout_rate_pct)}`}>
              {fmtPct(totals.buyout_rate_pct)}
            </div>
            <div className="text-[10px] text-muted">{fmtNum(totals.buyouts)}</div>
          </div>
          <div>
            <div className="text-xs text-muted">Сквозная конверсия</div>
            <div className={`text-lg font-semibold ${rateColor(totals.overall_conv_pct)}`}>
              {fmtPct(totals.overall_conv_pct)}
            </div>
            <div className="text-[10px] text-muted">показ → выкуп</div>
          </div>
        </div>
      )}

      {q.isLoading && <div className="text-muted">Загрузка…</div>}
      {q.isError && (
        <div className="card text-danger text-sm">
          Ошибка: {(q.error as Error).message}
        </div>
      )}
      {q.data && items.length === 0 && (
        <div className="card text-muted text-sm">
          Нет SKU с рекламой за выбранный период. Если запустили рекламу
          недавно — подождите следующего sync (4 раза в день).
        </div>
      )}

      {items.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted border-b border-border">
                <th className="text-left p-2">nm_id</th>
                <th className="text-left p-2">Артикул / предмет</th>
                <th className="text-left p-2">Бренд</th>
                <th
                  className="text-right p-2 cursor-pointer hover:text-fg"
                  onClick={() => onSort("views")}
                >
                  Показы{sortIndicator("views")}
                </th>
                <th
                  className="text-right p-2 cursor-pointer hover:text-fg"
                  onClick={() => onSort("ctr_pct")}
                  title="Conv views → atbs (CTR-показ к корзине)"
                >
                  CTR{sortIndicator("ctr_pct")}
                </th>
                <th
                  className="text-right p-2 cursor-pointer hover:text-fg"
                  onClick={() => onSort("cart_rate_pct")}
                  title="Conv atbs → orders"
                >
                  Корзина→Заказ{sortIndicator("cart_rate_pct")}
                </th>
                <th
                  className="text-right p-2 cursor-pointer hover:text-fg"
                  onClick={() => onSort("buyout_rate_pct")}
                  title="Conv orders → выкуп (из report_detail)"
                >
                  Заказ→Выкуп{sortIndicator("buyout_rate_pct")}
                </th>
                <th
                  className="text-right p-2 cursor-pointer hover:text-fg"
                  onClick={() => onSort("buyouts")}
                >
                  Выкуплено{sortIndicator("buyouts")}
                </th>
                <th className="text-left p-2">Слабое звено</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.nm_id} className="border-b border-border/40">
                  <td className="p-2 font-mono text-xs">{it.nm_id}</td>
                  <td className="p-2 text-xs">
                    <div>{it.vendor_code ?? "—"}</div>
                    <div className="text-[10px] text-muted">{it.subject ?? "—"}</div>
                  </td>
                  <td className="p-2 text-xs">{it.brand ?? "—"}</td>
                  <td className="p-2 text-right font-mono">{fmtNum(it.views)}</td>
                  <td className={`p-2 text-right ${rateColor(it.ctr_pct)}`}>
                    {fmtPct(it.ctr_pct)}
                  </td>
                  <td className={`p-2 text-right ${rateColor(it.cart_rate_pct)}`}>
                    {fmtPct(it.cart_rate_pct)}
                  </td>
                  <td className={`p-2 text-right ${rateColor(it.buyout_rate_pct)}`}>
                    {fmtPct(it.buyout_rate_pct)}
                  </td>
                  <td className="p-2 text-right font-mono">{fmtNum(it.buyouts)}</td>
                  <td className="p-2">
                    <span
                      className={`px-2 py-0.5 rounded text-xs ${
                        WEAKEST_COLOR[it.weakest_step] ?? ""
                      }`}
                    >
                      {WEAKEST_LABEL[it.weakest_step] ?? it.weakest_step}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
