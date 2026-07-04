/**
 * Аналитика РК (TASK-DEV-046 → DEV-096, как TS «РНП → Аналитика РК»):
 * вкладки «По зонам показа» (Поиск / Полки+Каталог / Единая) и «По кампаниям»
 * с воронкой корзины (добавления в корзину % / в заказ %), CPM/CPO/CPL/CPS,
 * ценами до/после СПП, остатками и drill «Показать по дням».
 */
import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, AdCampaignRow } from "@/api/client";
import { usePeriod } from "@/contexts/PeriodContext";
import { DateRangePicker } from "@/components/DateRangePicker";
import PageHeader from "@/components/PageHeader";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";
import { useFilters, filterKey } from "@/contexts/FilterContext";
import { GlobalFilterBar } from "@/components/GlobalFilterBar";

// Колонки таблицы кампаний: key → [label, formatter]. Порядок как в TS.
const CAMPAIGN_COLUMNS: [keyof AdCampaignRow, string, (v: number) => string][] = [
  ["spent", "Бюджет, ₽", fmtRub],
  ["views", "Показы", fmtNum],
  ["clicks", "Клики", fmtNum],
  ["ctr", "CTR, %", fmtPct],
  ["cpc", "CPC, ₽", fmtRub],
  ["cpm", "CPM, ₽", fmtRub],
  ["atbs", "Корзина, шт", fmtNum],
  ["atb_pct", "В корзину, %", fmtPct],
  ["orders", "Заказы, шт", fmtNum],
  ["revenue", "Заказы, ₽", fmtRub],
  ["order_pct", "В заказ, %", fmtPct],
  ["cr", "CR, %", fmtPct],
  ["cpo", "CPO, ₽", fmtRub],
  ["cpl", "CPL, ₽", fmtRub],
  ["cps", "CPS, ₽", fmtRub],
  ["drr", "ДРРз, %", fmtPct],
  ["price_before_spp", "Цена до СПП, ₽", fmtRub],
  ["price_after_spp", "Цена после СПП, ₽", fmtRub],
  ["spp_pct", "Скидка МП, %", fmtPct],
  ["stock_wh", "Остатки МП, шт", fmtNum],
];

const COLS_KEY = "adAnalytics.cols.v1";

export default function AdCampaignsAnalytics() {
  const { range, setPeriod } = usePeriod();
  const { filters: gFilters, toParams: gToParams } = useFilters();
  const gfk = filterKey(gFilters);
  const [tab, setTab] = useState<"zones" | "campaigns">("zones");
  const [openDaily, setOpenDaily] = useState<number | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(COLS_KEY) || "[]"));
    } catch {
      return new Set();
    }
  });
  const [drawer, setDrawer] = useState(false);

  const q = useQuery({
    queryKey: ["ad-analytics", range.from, range.to, gfk],
    queryFn: () => api.adCampaignsAnalytics(range.from, range.to, gToParams()),
  });
  const qd = useQuery({
    queryKey: ["ad-daily", openDaily, range.from, range.to],
    queryFn: () => api.adCampaignDaily(openDaily!, range.from, range.to),
    enabled: openDaily != null,
  });
  const t = q.data?.totals;
  const cols = useMemo(() => CAMPAIGN_COLUMNS.filter(([k]) => !hidden.has(k as string)), [hidden]);

  const toggleCol = (k: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      try {
        localStorage.setItem(COLS_KEY, JSON.stringify([...next]));
      } catch {}
      return next;
    });
  };

  const cell = (v: number | null | undefined, fmt: (v: number) => string) =>
    v == null ? "—" : fmt(v);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Аналитика РК"
        subtitle="Эффективность рекламы WB: зоны показа, воронка корзины, CPO/CPL/CPS, цены и остатки по кампаниям."
      />
      <div className="flex flex-wrap items-center gap-3">
        <DateRangePicker
          from={range.from}
          to={range.to}
          onChange={(r) => setPeriod({ kind: "custom", from: r.from, to: r.to })}
        />
        <GlobalFilterBar />
        <div className="ml-auto flex gap-1">
          {([["zones", "По зонам показа"], ["campaigns", "По кампаниям"]] as const).map(([k, label]) => (
            <button key={k} className={`btn text-xs ${tab === k ? "btn-primary" : ""}`} onClick={() => setTab(k)}>
              {label}
            </button>
          ))}
          {tab === "campaigns" && (
            <button className="btn text-xs" onClick={() => setDrawer(!drawer)}>⚙ Настройка таблицы</button>
          )}
        </div>
      </div>
      {drawer && tab === "campaigns" && (
        <div className="card p-3 grid grid-cols-2 md:grid-cols-5 gap-1 text-xs">
          {CAMPAIGN_COLUMNS.map(([k, label]) => (
            <label key={k as string} className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={!hidden.has(k as string)} onChange={() => toggleCol(k as string)} />
              {label}
            </label>
          ))}
        </div>
      )}
      {q.isLoading && <div className="text-muted text-sm">Загружаю…</div>}
      {q.isError && <div className="text-danger text-sm">Ошибка: {(q.error as Error)?.message}</div>}
      {q.data && (
        <>
          {t && (
            <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
              <div className="card p-3"><div className="text-xs text-muted">Расход</div><div className="text-lg font-semibold">{fmtRub(t.spent)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">Выручка с РК</div><div className="text-lg font-semibold">{fmtRub(t.revenue)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">ДРРз</div><div className="text-lg font-semibold">{fmtPct(t.drr)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">Заказы с РК</div><div className="text-lg font-semibold">{fmtNum(t.orders)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">Корзина</div><div className="text-lg font-semibold">{fmtNum(t.atbs)}</div></div>
              <div className="card p-3"><div className="text-xs text-muted">Клики</div><div className="text-lg font-semibold">{fmtNum(t.clicks)}</div></div>
            </div>
          )}

          {tab === "zones" && (
            <div className="card overflow-x-auto p-0">
              <table className="w-full text-sm whitespace-nowrap">
                <thead>
                  <tr className="text-left text-muted border-b border-border">
                    <th className="p-2">Зона показа</th>
                    <th className="p-2 text-right">Кампаний</th>
                    <th className="p-2 text-right">Бюджет, ₽</th>
                    <th className="p-2 text-right">Показы</th>
                    <th className="p-2 text-right">Клики</th>
                    <th className="p-2 text-right">CTR</th>
                    <th className="p-2 text-right">CPC</th>
                    <th className="p-2 text-right">CPM</th>
                    <th className="p-2 text-right">Корзина</th>
                    <th className="p-2 text-right">В корзину %</th>
                    <th className="p-2 text-right">Заказы</th>
                    <th className="p-2 text-right">Заказы ₽</th>
                    <th className="p-2 text-right">В заказ %</th>
                    <th className="p-2 text-right">CPO</th>
                    <th className="p-2 text-right">CPL</th>
                    <th className="p-2 text-right">CPS</th>
                    <th className="p-2 text-right">ДРРз</th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.zones.map((z) => (
                    <tr key={z.zone} className="border-b border-border/50 hover:bg-soft/40">
                      <td className="p-2 font-medium">{z.zone}</td>
                      <td className="p-2 text-right">{z.campaigns}</td>
                      <td className="p-2 text-right">{fmtRub(z.spent)}</td>
                      <td className="p-2 text-right">{fmtNum(z.views)}</td>
                      <td className="p-2 text-right">{fmtNum(z.clicks)}</td>
                      <td className="p-2 text-right">{fmtPct(z.ctr)}</td>
                      <td className="p-2 text-right">{fmtRub(z.cpc)}</td>
                      <td className="p-2 text-right">{fmtRub(z.cpm)}</td>
                      <td className="p-2 text-right">{fmtNum(z.atbs)}</td>
                      <td className="p-2 text-right">{fmtPct(z.atb_pct)}</td>
                      <td className="p-2 text-right">{fmtNum(z.orders)}</td>
                      <td className="p-2 text-right">{fmtRub(z.revenue)}</td>
                      <td className="p-2 text-right">{fmtPct(z.order_pct)}</td>
                      <td className="p-2 text-right">{fmtRub(z.cpo)}</td>
                      <td className="p-2 text-right">{fmtRub(z.cpl)}</td>
                      <td className="p-2 text-right">{fmtRub(z.cps)}</td>
                      <td className={`p-2 text-right ${z.drr > 20 ? "text-danger" : ""}`}>{fmtPct(z.drr)}</td>
                    </tr>
                  ))}
                  {q.data.zones.length === 0 && (
                    <tr><td colSpan={17} className="p-4 text-center text-muted">Нет данных за период.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {tab === "campaigns" && (
            <div className="card overflow-x-auto p-0">
              <table className="w-full text-sm whitespace-nowrap">
                <thead>
                  <tr className="text-left text-muted border-b border-border">
                    <th className="p-2 sticky left-0 bg-surface min-w-[220px]">Кампания</th>
                    <th className="p-2">Зона</th>
                    <th className="p-2">Статус</th>
                    {cols.map(([k, label]) => (
                      <th key={k as string} className="p-2 text-right">{label}</th>
                    ))}
                    <th className="p-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.items.map((x) => (
                    <Fragment key={x.advert_id}>
                      <tr className="border-b border-border/50 hover:bg-soft/40">
                        <td className="p-2 sticky left-0 bg-surface max-w-[260px] truncate" title={`${x.advert_id} · ${x.name}`}>
                          {x.name}
                        </td>
                        <td className="p-2 text-muted">{x.zone}</td>
                        <td className="p-2 text-muted">{x.status}</td>
                        {cols.map(([k, , fmt]) => (
                          <td key={k as string} className={`p-2 text-right ${k === "drr" && x.drr > 20 ? "text-danger" : ""}`}>
                            {cell(x[k] as number | null, fmt)}
                          </td>
                        ))}
                        <td className="p-2">
                          <button
                            className="btn text-xs"
                            onClick={() => setOpenDaily(openDaily === x.advert_id ? null : x.advert_id)}
                          >
                            {openDaily === x.advert_id ? "Скрыть дни" : "По дням"}
                          </button>
                        </td>
                      </tr>
                      {openDaily === x.advert_id && (
                        <tr className="border-b border-border/50">
                          <td colSpan={cols.length + 4} className="p-2 bg-soft/20">
                            {qd.isLoading && <div className="text-xs text-muted">Загружаю дни…</div>}
                            {qd.data && (
                              <table className="w-full text-xs">
                                <thead>
                                  <tr className="text-left text-muted">
                                    <th className="p-1">Дата</th>
                                    <th className="p-1 text-right">Бюджет</th>
                                    <th className="p-1 text-right">Показы</th>
                                    <th className="p-1 text-right">Клики</th>
                                    <th className="p-1 text-right">CTR</th>
                                    <th className="p-1 text-right">CPC</th>
                                    <th className="p-1 text-right">Корзина</th>
                                    <th className="p-1 text-right">Заказы</th>
                                    <th className="p-1 text-right">Заказы ₽</th>
                                    <th className="p-1 text-right">CPO</th>
                                    <th className="p-1 text-right">ДРРз</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {qd.data.days.map((d) => (
                                    <tr key={d.date} className="border-t border-border/30">
                                      <td className="p-1">{d.date}</td>
                                      <td className="p-1 text-right">{fmtRub(d.spent)}</td>
                                      <td className="p-1 text-right">{fmtNum(d.views)}</td>
                                      <td className="p-1 text-right">{fmtNum(d.clicks)}</td>
                                      <td className="p-1 text-right">{fmtPct(d.ctr)}</td>
                                      <td className="p-1 text-right">{fmtRub(d.cpc)}</td>
                                      <td className="p-1 text-right">{fmtNum(d.atbs)}</td>
                                      <td className="p-1 text-right">{fmtNum(d.orders)}</td>
                                      <td className="p-1 text-right">{fmtRub(d.revenue)}</td>
                                      <td className="p-1 text-right">{fmtRub(d.cpo)}</td>
                                      <td className="p-1 text-right">{fmtPct(d.drr)}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                  {q.data.items.length === 0 && (
                    <tr><td colSpan={cols.length + 4} className="p-4 text-center text-muted">Нет данных по кампаниям за период.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
          <div className="text-xs text-muted">
            Цены до/после СПП и остатки — усреднение/сумма по карточкам, крутившимся в кампании за период. Ассоциированные заказы WB в публичном API не отдаёт.
          </div>
        </>
      )}
    </div>
  );
}
