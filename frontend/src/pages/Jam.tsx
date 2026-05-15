/**
 * Джем — поисковая аналитика по кластерам (10X-методика).
 *
 * Реальная имплементация:
 *  - Источник данных: jam_queries (наполняется через Excel-импорт юзером
 *    выгрузкой ТОП-30 запросов из «Аналитики сравнения карточек» WB-кабинета).
 *  - Кластеризация: на лету в backend (jam-сервис) — по общему слову.
 *  - Цветовая разметка: красный = CPC > MAX_CPC, жёлтый 70-100%, зелёный < 70%.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";

const STATUS_COLORS: Record<string, string> = {
  red: "text-danger",
  yellow: "text-warn",
  green: "text-success",
  ok: "text-muted",
};
const STATUS_BG: Record<string, string> = {
  red: "bg-danger/15",
  yellow: "bg-warn/15",
  green: "bg-success/10",
  ok: "",
};

export default function Jam() {
  const [nmId, setNmId] = useState<number | null>(null);
  const [organicPct, setOrganicPct] = useState(0);
  const [targetMargin, setTargetMargin] = useState(0);
  const [days, setDays] = useState(30);

  const status = useQuery({
    queryKey: ["jam-status"],
    queryFn: () => api.jamStatus(),
  });

  const skus = useQuery({
    queryKey: ["jam-skus"],
    queryFn: () => api.jamSkus(),
  });

  const clusters = useQuery({
    queryKey: ["jam-clusters", nmId, days, organicPct, targetMargin],
    queryFn: () =>
      api.jamClusters(nmId!, { days_back: days, organic_pct: organicPct, target_margin_pct: targetMargin }),
    enabled: nmId != null,
  });

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold">Джем — поисковая аналитика</h1>
        <div className="text-xs text-muted mt-1">
          Кластеры поисковых запросов с MAX-границами рекламы (10X-методика).
          Источник: jam_queries. Загрузка через Excel из «Аналитики сравнения карточек» WB.
        </div>
      </div>

      {status.data?.status === "empty" && (
        <div className="card border-warn/40 bg-warn/5">
          <div className="font-medium text-warn mb-2">📥 Нет загруженных запросов</div>
          <div className="text-sm leading-relaxed">{status.data.message}</div>
          <div className="mt-3 text-xs space-y-1">
            <div>
              <strong>Шаги загрузки:</strong>
            </div>
            <ol className="list-decimal list-inside space-y-1 text-muted">
              <li>
                Открыть в WB-кабинете{" "}
                <a
                  href={status.data.docs_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-accent underline"
                >
                  Аналитика сравнения карточек
                </a>
                .
              </li>
              <li>
                Скачать ТОП-30 запросов по своим SKU (xlsx).
              </li>
              <li>
                Преобразовать в формат: <code>nm_id, query, period_start,
                period_end, orders, clicks, views, ad_spent</code>.
              </li>
              <li>
                Загрузить в /settings → Excel I/O → <strong>jam_queries</strong> → Импорт.
              </li>
            </ol>
          </div>
        </div>
      )}

      {status.data?.status === "configured" && (
        <div className="card text-xs text-muted">
          ✅ {status.data.message}
        </div>
      )}

      <section className="card">
        <h2 className="font-medium mb-3">Кластеры по SKU</h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
          <Field label="SKU">
            <select
              className="bg-surface border border-border rounded-md p-1.5 text-sm text-white w-full"
              value={nmId ?? ""}
              onChange={(e) => setNmId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">— выберите —</option>
              {(skus.data?.items ?? []).map((s: any) => (
                <option key={s.nm_id} value={s.nm_id}>
                  {s.nm_id} ({s.queries} зап.)
                </option>
              ))}
            </select>
          </Field>
          <Field label="Период (дней)">
            <select
              className="bg-surface border border-border rounded-md p-1.5 text-sm text-white w-full"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              {[7, 14, 30, 60, 90].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Органика %">
            <input
              type="number"
              className="bg-surface border border-border rounded-md p-1.5 text-sm text-white w-full"
              value={organicPct}
              onChange={(e) => setOrganicPct(Number(e.target.value) || 0)}
              min="0"
              max="100"
              step="5"
            />
          </Field>
          <Field label="Целевая маржа %">
            <input
              type="number"
              className="bg-surface border border-border rounded-md p-1.5 text-sm text-white w-full"
              value={targetMargin}
              onChange={(e) => setTargetMargin(Number(e.target.value) || 0)}
              min="0"
              step="0.5"
            />
          </Field>
        </div>

        {nmId == null && (
          <div className="text-muted text-sm">Выберите SKU из списка выше.</div>
        )}

        {clusters.data?.unit_economics && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs mb-3">
            <Mini label="Цена SKU" value={fmtRub(clusters.data.unit_economics.price)} />
            <Mini label="COGS" value={fmtRub(clusters.data.unit_economics.cogs)} />
            <Mini label="Комиссия %" value={`${clusters.data.unit_economics.commission_pct}%`} />
            <Mini label="Логистика" value={fmtRub(clusters.data.unit_economics.logistics_per_unit)} />
          </div>
        )}

        {clusters.data?.message && (
          <div className="text-warn text-sm py-2">{clusters.data.message}</div>
        )}

        {clusters.data && clusters.data.clusters.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-muted text-xs uppercase">
                <tr>
                  <th className="text-left p-2">Кластер</th>
                  <th className="text-right p-2">Заказов</th>
                  <th className="text-right p-2">Кликов</th>
                  <th className="text-right p-2">CTR</th>
                  <th className="text-right p-2">Корзина%</th>
                  <th className="text-right p-2">Расход</th>
                  <th className="text-right p-2">CPC</th>
                  <th className="text-right p-2">MAX CPC</th>
                  <th className="text-right p-2">ДРР</th>
                  <th className="text-left p-2">Запросы</th>
                </tr>
              </thead>
              <tbody>
                {clusters.data.clusters.map((c: any, i: number) => (
                  <tr
                    key={i}
                    className={`border-t border-border ${STATUS_BG[c.status] ?? ""}`}
                  >
                    <td className="p-2">
                      <span className={STATUS_COLORS[c.status]}>●</span>{" "}
                      <span className="font-medium">{c.cluster}</span>
                      <div className="text-xs text-muted">
                        {c.queries_count} запросов
                      </div>
                    </td>
                    <td className="p-2 text-right">{c.orders}</td>
                    <td className="p-2 text-right">{c.clicks}</td>
                    <td className="p-2 text-right">{c.ctr}%</td>
                    <td className="p-2 text-right">{c.cart_conv_pct}%</td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(c.ad_spent)}
                    </td>
                    <td
                      className={`p-2 text-right font-mono ${
                        c.status === "red" ? "text-danger font-bold" : ""
                      }`}
                    >
                      {fmtRub(c.cpc)}
                    </td>
                    <td className="p-2 text-right font-mono text-muted">
                      {c.max_cpc > 0 ? fmtRub(c.max_cpc) : "—"}
                    </td>
                    <td className="p-2 text-right">{c.drr}%</td>
                    <td className="p-2 text-xs text-muted max-w-xs">
                      {c.queries_sample.join(", ")}
                      {c.queries_count > c.queries_sample.length && (
                        <span> и ещё {c.queries_count - c.queries_sample.length}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {clusters.data.totals && (
              <div className="mt-3 text-xs text-muted">
                Итого: <strong>{clusters.data.totals.clusters_total}</strong>{" "}
                кластеров /{" "}
                <strong>{clusters.data.totals.queries_total}</strong> запросов /{" "}
                <strong>{clusters.data.totals.orders_total}</strong> заказов.
                {clusters.data.totals.red_clusters > 0 && (
                  <>
                    {" "}
                    <span className="text-danger">
                      🔴 {clusters.data.totals.red_clusters} кластеров с CPC выше MAX (убыток).
                    </span>
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </section>

      <div className="card text-xs text-muted leading-relaxed">
        <strong>Как читать:</strong>
        <ul className="list-disc list-inside space-y-1 mt-1">
          <li>
            <span className="text-danger">🔴 Красный</span> — CPC выше MAX (вы
            теряете на этом кластере).
          </li>
          <li>
            <span className="text-warn">🟡 Жёлтый</span> — CPC 70-100% от MAX
            (баланс на грани, маржа минимальная).
          </li>
          <li>
            <span className="text-success">🟢 Зелёный</span> — CPC меньше 70%
            от MAX (есть запас по марже).
          </li>
          <li>
            MAX-метрики считаются из текущей юнит-экономики SKU + ваших
            параметров органики и целевой маржи.
          </li>
        </ul>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: any }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      {children}
    </label>
  );
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-bg/40 rounded p-2">
      <div className="text-muted">{label}</div>
      <div className="font-mono text-white">{value}</div>
    </div>
  );
}
