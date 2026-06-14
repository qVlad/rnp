/**
 * Джем — поисковая аналитика по кластерам (10X-методика).
 *
 * Реальная имплементация:
 *  - Источник данных: jam_queries (наполняется через Excel-импорт юзером
 *    выгрузкой ТОП-30 запросов из «Аналитики сравнения карточек» WB-кабинета).
 *  - Кластеризация: на лету в backend (jam-сервис) — по общему слову.
 *  - Цветовая разметка: красный = CPC > MAX_CPC, жёлтый 70-100%, зелёный < 70%.
 */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";
import { useAuth } from "@/contexts/AuthContext";
import { Icon } from "../components/Icon";
import PageHeader from "@/components/PageHeader";

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
  const { user } = useAuth();
  const isDirector = user?.role === "director";
  const qc = useQueryClient();
  const [nmId, setNmId] = useState<number | null>(null);
  const [organicPct, setOrganicPct] = useState(0);
  const [targetMargin, setTargetMargin] = useState(0);
  const [days, setDays] = useState(30);
  const [syncResult, setSyncResult] = useState<any>(null);
  const [urlInput, setUrlInput] = useState("");

  const status = useQuery({
    queryKey: ["jam-status"],
    queryFn: () => api.jamStatus(),
  });

  const urlQ = useQuery({
    queryKey: ["jam-url"],
    queryFn: () => api.jamGetUrl(),
    enabled: isDirector,
  });
  useEffect(() => {
    if (urlQ.data) setUrlInput(urlQ.data.wb_jam_url || "");
  }, [urlQ.data]);

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

  // DEV-085 — динамика позиций (из расширения, abtest_position_snapshot).
  const positions = useQuery({
    queryKey: ["jam-positions", days],
    queryFn: () => api.jamPositions(days),
  });

  const syncMut = useMutation({
    mutationFn: () => api.jamSyncNow(days),
    onSuccess: (data) => {
      setSyncResult(data);
      qc.invalidateQueries({ queryKey: ["jam-status"] });
      qc.invalidateQueries({ queryKey: ["jam-skus"] });
      qc.invalidateQueries({ queryKey: ["jam-clusters"] });
    },
    onError: (err: any) => {
      setSyncResult({ error: String(err?.message || err) });
    },
  });

  const urlMut = useMutation({
    mutationFn: () => api.jamSetUrl(urlInput.trim()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jam-url"] });
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Джем — поисковая аналитика"
        subtitle="Кластеры поисковых запросов с MAX-границами рекламы (10X-методика). Источник: jam_queries. Загрузка через Excel из «Аналитики сравнения карточек» WB."
      />

      {status.data?.status === "empty" && (
        <div className="card border-warn/40 bg-warn/5">
          <div className="font-medium text-warn mb-2"><Icon name="download" size={12} /> Нет загруженных запросов</div>
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
          <Icon name="check" size={12} /> {status.data.message}
        </div>
      )}

      {isDirector && (
        <section className="card">
          <h2 className="font-medium mb-3">
            Подключение WB Jam (синхронизация по API)
          </h2>

          {/* TASK-DEV-008: краткая инструкция как найти endpoint самостоятельно.
              Все 3 наших дефолтных кандидата отдают 404 (WB не публикует path),
              но юзер сам может найти его за 30 секунд в DevTools. */}
          <details className="text-xs text-muted mb-3">
            <summary className="cursor-pointer text-accent hover:underline">
              Как найти точный URL endpoint (если дефолтные кандидаты 404)
            </summary>
            <ol className="list-decimal list-inside space-y-1 mt-2 leading-relaxed">
              <li>
                Открой в браузере{" "}
                <a
                  href="https://seller.wildberries.ru"
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent underline"
                >
                  seller.wildberries.ru
                </a>{" "}
                и залогинься.
              </li>
              <li>
                Открой <strong>F12</strong> → вкладка <strong>Network</strong>{" "}
                → фильтр <code>search-report</code>.
              </li>
              <li>
                Перейди в раздел{" "}
                <em>«Аналитика → Сравнение карточек»</em> и выбери любой
                свой SKU.
              </li>
              <li>
                В Network появится один или несколько запросов к{" "}
                <code>seller-analytics-api.wildberries.ru</code> — клик по
                первому 200-ответу.
              </li>
              <li>
                Скопируй <strong>Request URL</strong>, удали схему/хост, оставь
                только path и любые query-параметры (например{" "}
                <code>/api/v2/search-report/products?nmId=...</code>).
              </li>
              <li>
                Вставь в поле ниже → «Сохранить URL» → «Синхронизировать».
              </li>
            </ol>
            <div className="mt-2 text-warn">
              <Icon name="warning" size={12} /> Этот endpoint WB не публикует официально. Может поменяться
              без предупреждения — если перестанет работать, повтори поиск.
            </div>
          </details>

          <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-3 mb-3">
            <Field label="WB Jam URL (опционально, оставьте пусто для авто)">
              <input
                className="bg-surface border border-border rounded-md p-1.5 text-sm text-white w-full font-mono"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                placeholder="/api/v2/search-report/products?nmId=..."
              />
              <div className="text-[11px] text-muted mt-1 leading-snug">
                Оставьте пустым — система попробует дефолтные кандидаты
                (<code>/api/v2/search-report/products</code> и др.). Если
                знаете точный путь — впишите. Хост подставится автоматически
                (<code>seller-analytics-api.wildberries.ru</code>).
              </div>
            </Field>
            <div className="flex items-end gap-2">
              <button
                className="btn"
                onClick={() => urlMut.mutate()}
                disabled={urlMut.isPending || urlInput === (urlQ.data?.wb_jam_url ?? "")}
              >
                {urlMut.isPending ? "Сохраняю…" : "Сохранить URL"}
              </button>
              <button
                className="btn-primary"
                onClick={() => syncMut.mutate()}
                disabled={syncMut.isPending}
                title="Запустить синхронизацию WB Jam прямо сейчас (длится ~10 мин)"
              >
                {syncMut.isPending ? "Sync…" : "Sync now"}
              </button>
            </div>
          </div>
          {syncResult && (
            <div
              className={`text-xs p-2 rounded ${
                syncResult.error || (syncResult.errors && syncResult.errors.length > 0)
                  ? "bg-danger/10 text-danger"
                  : "bg-success/10 text-success"
              }`}
            >
              {syncResult.error ? (
                <>Ошибка: {syncResult.error}</>
              ) : syncResult.skipped ? (
                <>Пропущено: {syncResult.reason}</>
              ) : (
                <>
                  Готово: обработано {syncResult.skus_processed ?? 0} SKU,
                  upsert {syncResult.queries_upserted ?? 0} запросов.
                  {syncResult.errors && syncResult.errors.length > 0 && (
                    <div className="mt-1">
                      Ошибки ({syncResult.errors.length}):
                      <ul className="list-disc list-inside">
                        {syncResult.errors.slice(0, 3).map((e: string, i: number) => (
                          <li key={i}>{e}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
          <div className="text-xs text-muted mt-2 leading-relaxed">
            WB Jam — платная подписка. Точный endpoint в публичных API-доках
            не зафиксирован; система пробует кандидаты из своего списка. Если
            sync даёт 404 на всех — впишите точный URL вручную (его можно
            подсмотреть в DevTools-сетевых запросах WB-кабинета на странице
            «Аналитика сравнения карточек»). Альтернатива — Excel-импорт через
            /settings → jam_queries.
          </div>
        </section>
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
                    <td className="p-2 text-right font-mono">{c.cart_conv_pct}%</td>
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

      {/* DEV-085 — динамика позиций наших карточек в поиске */}
      <section className="card">
        <h2 className="font-medium mb-1">Динамика позиций в поиске</h2>
        <p className="text-xs text-muted mb-3">
          Позиции наших карточек по запросам — собирает Chrome-расширение при
          заходе на www.wildberries.ru. Конкурентов пока не отслеживаем.
        </p>
        {positions.isLoading && <div className="text-muted text-sm">Загрузка…</div>}
        {!positions.isLoading && (positions.data?.count ?? 0) === 0 && (
          <div className="text-muted text-sm">
            Нет данных по позициям за период. Установите Chrome-расширение РНП и
            зайдите на поиск WB — позиции начнут собираться.
          </div>
        )}
        {(positions.data?.count ?? 0) > 0 && (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">SKU</th>
                <th className="text-left p-2">Запрос</th>
                <th className="text-right p-2">Позиция</th>
                <th className="text-right p-2">Стр.</th>
                <th className="text-right p-2">Δ к началу</th>
                <th className="text-right p-2">Лучшая / Худшая</th>
                <th className="text-right p-2">Замеров</th>
              </tr>
            </thead>
            <tbody>
              {positions.data!.items.map((p) => (
                <tr key={`${p.nm_id}-${p.query}`} className="border-t border-border">
                  <td className="p-2 font-mono text-xs">
                    #{p.nm_id}
                    {p.vendor_code && (
                      <div className="text-muted">{p.vendor_code}</div>
                    )}
                  </td>
                  <td className="p-2 text-xs">{p.query}</td>
                  <td className="p-2 text-right font-mono">{p.current_position}</td>
                  <td className="p-2 text-right font-mono">{p.current_page}</td>
                  <td
                    className={`p-2 text-right font-mono ${
                      p.delta > 0
                        ? "text-success"
                        : p.delta < 0
                          ? "text-danger"
                          : "text-muted"
                    }`}
                    title="Изменение позиции за период (положительное = поднялись выше)"
                  >
                    {p.delta > 0 ? `↑${p.delta}` : p.delta < 0 ? `↓${-p.delta}` : "—"}
                  </td>
                  <td className="p-2 text-right font-mono text-xs">
                    {p.best} / {p.worst}
                  </td>
                  <td className="p-2 text-right font-mono text-muted">{p.samples}</td>
                </tr>
              ))}
            </tbody>
          </table>
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
    <div className="bg-surface-2/50 rounded p-2">
      <div className="text-muted">{label}</div>
      <div className="font-mono text-white">{value}</div>
    </div>
  );
}
