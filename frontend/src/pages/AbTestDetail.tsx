/**
 * Детали одного A/B теста: метаданные, варианты с фото-uploader'ом,
 * последние ротации, alerts, результат (значимость + графики).
 */
import { useState } from "react";
import StopDialog from "@/components/abtest/StopDialog";
import { Link, useParams } from "react-router-dom";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  abtestApi,
  AbTestStatus,
  AbTestVariant,
} from "@/api/abtest";
import { VariantPhotoGrid } from "@/components/abtest/VariantPhotoGrid";
import { Icon } from "../components/Icon";

const STATUS_BADGE: Record<AbTestStatus | string, string> = {
  draft: "bg-surface-2 text-muted",
  running: "bg-success-bg text-success",
  paused: "bg-warn-bg text-warn",
  completed: "bg-info-bg text-info",
  stopped: "bg-surface-2 text-muted",
  cancelled: "bg-surface-2 text-muted", // legacy alias
};

function fmtDate(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleString("ru-RU");
}

// Метки top/bottom метрик зависят от сценария (port wbab M-матрицы).
function scenarioLabels(testMode: string, trafficSource: string): {
  top: string;
  bottom: string;
} {
  if (testMode === "PHOTO") {
    // ADV_ONLY+PHOTO: показ → клик
    return { top: "Показ → Клик, %", bottom: "Клик → Заказ, %" };
  }
  // FUNNEL
  if (trafficSource === "ADV_ONLY") {
    return { top: "Клик → В корзину, %", bottom: "В корзину → Заказ, %" };
  }
  // ANY_FUNNEL / BOTH_FUNNEL
  return { top: "Открытие → В корзину, %", bottom: "В корзину → Заказ, %" };
}

const EVENT_LABELS: Record<string, string> = {
  variant_eliminated: "✕ Вариант отсеян",
  variant_returned: "↩ Вариант возвращён",
  winner_applied: "🏆 Применён победитель",
  test_stopped: "⏹ Тест остановлен",
};

function TimelineSection({
  abtestId,
  variants,
  rotations,
}: {
  abtestId: number;
  variants: AbTestVariant[];
  rotations: Array<{
    id: number;
    variant_id: number;
    applied_at: string;
    success: boolean;
    error: string | null;
  }>;
}) {
  const eventsQ = useQuery({
    queryKey: ["abtest-events", abtestId],
    queryFn: () => abtestApi.getEvents(abtestId),
  });
  const events = eventsQ.data?.items || [];
  // Merge rotations + events into one sorted-desc timeline.
  type Row = {
    key: string;
    at: string;
    kind: "rotation" | "event";
    rotation?: (typeof rotations)[number];
    event?: (typeof events)[number];
  };
  const rows: Row[] = [
    ...rotations.map((r) => ({
      key: `r${r.id}`,
      at: r.applied_at,
      kind: "rotation" as const,
      rotation: r,
    })),
    ...events.map((e) => ({
      key: `e${e.id}`,
      at: e.created_at,
      kind: "event" as const,
      event: e,
    })),
  ].sort((a, b) => (a.at < b.at ? 1 : -1));

  if (rows.length === 0) {
    return (
      <section>
        <h2 className="text-lg font-medium mb-2">История</h2>
        <div className="card text-muted">Событий ещё не было.</div>
      </section>
    );
  }
  return (
    <section>
      <h2 className="text-lg font-medium mb-2">История</h2>
      <div className="card overflow-x-auto p-0">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-2 text-muted text-xs uppercase">
            <tr>
              <th className="text-left p-2">Время</th>
              <th className="text-left p-2">Тип</th>
              <th className="text-left p-2">Вариант</th>
              <th className="text-left p-2">Статус/Источник</th>
              <th className="text-left p-2">Детали</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              if (row.kind === "rotation") {
                const r = row.rotation!;
                const v = variants.find((x) => x.id === r.variant_id);
                return (
                  <tr key={row.key} className="border-t border-border">
                    <td className="p-2 text-muted">{fmtDate(r.applied_at)}</td>
                    <td className="p-2">Ротация</td>
                    <td className="p-2">{v?.label || `#${r.variant_id}`}</td>
                    <td
                      className={`p-2 ${r.success ? "text-success" : "text-warn"}`}
                    >
                      {r.success ? "✓ OK" : "✕ FAIL"}
                    </td>
                    <td className="p-2 text-muted text-xs">{r.error || "—"}</td>
                  </tr>
                );
              }
              const e = row.event!;
              const v = e.variant_id
                ? variants.find((x) => x.id === e.variant_id)
                : null;
              return (
                <tr key={row.key} className="border-t border-border">
                  <td className="p-2 text-muted">{fmtDate(e.created_at)}</td>
                  <td className="p-2">{EVENT_LABELS[e.kind] || e.kind}</td>
                  <td className="p-2">{v?.label || (e.variant_id ? `#${e.variant_id}` : "—")}</td>
                  <td className="p-2 text-muted">
                    {e.source === "auto" ? "🤖 auto" : "👤 manual"}
                  </td>
                  <td className="p-2 text-muted text-xs">
                    {e.event_metadata
                      ? Object.entries(e.event_metadata)
                          .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                          .join(" · ")
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}


/**
 * Снимки позиций карточки теста в выдаче WB.
 *
 * Источник данных — Chrome-расширение (`extension/src/content/wb-search.ts`)
 * при заходе юзера на www.wildberries.ru. Данные накапливаются за время
 * активности теста.
 *
 * Показываем:
 *   • сводку — сколько снимков, сколько уникальных запросов, период
 *   • timeline-чарт — позиция во времени, по линии на каждый запрос
 *     (только если есть данные за >=2 момента времени, иначе пусто)
 *   • таблицу последних 50 снимков для гранулярной диагностики
 *
 * При status=draft (тест не запущен) — скрыта.
 */
function PositionsSection({ abtestId }: { abtestId: number }) {
  const q = useQuery({
    queryKey: ["abtest-positions", abtestId],
    queryFn: () => abtestApi.getPositions(abtestId, 2000),
  });

  if (q.isLoading) {
    return (
      <section>
        <h2 className="text-lg font-medium mb-2">Позиции в выдаче WB</h2>
        <div className="card text-muted">Загрузка…</div>
      </section>
    );
  }
  if (q.isError) {
    return (
      <section>
        <h2 className="text-lg font-medium mb-2">Позиции в выдаче WB</h2>
        <div className="card text-warn text-sm">
          Не удалось загрузить позиции: {(q.error as Error).message}
        </div>
      </section>
    );
  }
  const items = q.data?.items || [];
  const summary = q.data?.summary;

  if (items.length === 0) {
    return (
      <section>
        <h2 className="text-lg font-medium mb-2">Позиции в выдаче WB</h2>
        <div className="card text-muted text-sm space-y-1">
          <div>Снимков позиций ещё нет.</div>
          <div className="text-xs">
            Данные собирает Chrome-расширение РНП при заходе на
            <code className="px-1">www.wildberries.ru</code> с включённой
            опцией <em>«Трекинг позиций»</em> (по умолчанию включена). Когда
            кто-то откроет каталог/поиск со SKU вашего теста — позиции
            начнут накапливаться здесь.
          </div>
        </div>
      </section>
    );
  }

  // Группируем по query → массив точек {ts, position}.
  // Берём топ-5 запросов по числу снимков чтобы chart не превращался в кашу.
  const byQuery = new Map<string, Array<{ ts: number; position: number }>>();
  for (const it of items) {
    const arr = byQuery.get(it.query) || [];
    arr.push({ ts: new Date(it.collected_at).getTime(), position: it.position });
    byQuery.set(it.query, arr);
  }
  const topQueries = Array.from(byQuery.entries())
    .sort((a, b) => b[1].length - a[1].length)
    .slice(0, 5);

  // Все timestamp'ы в единой шкале X — берём union, сортируем asc.
  const allTs = new Set<number>();
  for (const [, pts] of topQueries) {
    for (const p of pts) allTs.add(p.ts);
  }
  const xs = Array.from(allTs).sort((a, b) => a - b);

  // Для каждого X — собираем точку по каждому запросу (или null).
  const chartData = xs.map((ts) => {
    const row: Record<string, number | string | null> = {
      ts,
      label: new Date(ts).toLocaleString("ru-RU", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }),
    };
    for (const [query, pts] of topQueries) {
      const match = pts.find((p) => p.ts === ts);
      row[query] = match ? match.position : null;
    }
    return row;
  });

  // Палитра recharts для линий — теми же оттенками что и daily-stats бары.
  const COLORS = ["#3b82f6", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"];

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-medium">Позиции в выдаче WB</h2>

      {summary && (
        <div className="flex gap-6 text-sm">
          <div>
            <span className="text-muted">Снимков: </span>
            <strong>{summary.total_snapshots}</strong>
          </div>
          <div>
            <span className="text-muted">Уникальных запросов: </span>
            <strong>{summary.distinct_queries}</strong>
          </div>
          <div>
            <span className="text-muted">Первый: </span>
            <strong>{fmtDate(summary.first_seen)}</strong>
          </div>
          <div>
            <span className="text-muted">Последний: </span>
            <strong>{fmtDate(summary.last_seen)}</strong>
          </div>
        </div>
      )}

      {chartData.length >= 2 && (
        <div className="card p-3" style={{ height: 320 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              {/*
                Y-ось перевёрнута: лучшая позиция = 1 (вверху), 100+ внизу.
                Это конвенция SEO-отчётов.
              */}
              <YAxis
                tick={{ fontSize: 11 }}
                reversed
                domain={[1, "dataMax"]}
                allowDecimals={false}
                label={{
                  value: "Позиция",
                  angle: -90,
                  position: "insideLeft",
                  fontSize: 12,
                }}
              />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {topQueries.map(([query], idx) => (
                <Line
                  key={query}
                  type="monotone"
                  dataKey={query}
                  stroke={COLORS[idx % COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
          <p className="text-xs text-muted mt-1">
            Показаны топ-5 запросов по числу снимков. Лучшая позиция (1)
            — вверху графика; чем выше линия, тем лучше карточка ранжируется.
          </p>
        </div>
      )}

      <div className="card overflow-x-auto p-0">
        <table className="min-w-full text-sm">
          <thead className="bg-surface-2 text-muted text-xs uppercase">
            <tr>
              <th className="text-left p-2">Время</th>
              <th className="text-left p-2">Запрос</th>
              <th className="text-right p-2">Позиция</th>
              <th className="text-right p-2">Страница</th>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, 50).map((it) => (
              <tr key={it.id} className="border-t border-border">
                <td className="p-2 text-muted">{fmtDate(it.collected_at)}</td>
                <td
                  className="p-2 max-w-md truncate"
                  title={it.query}
                >
                  {it.query}
                </td>
                <td className="p-2 text-right font-mono">{it.position}</td>
                <td className="p-2 text-right text-muted">{it.page}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {items.length > 50 && (
          <div className="p-2 text-xs text-muted text-center border-t border-border">
            Показаны последние 50 из {items.length}.
          </div>
        )}
      </div>
    </section>
  );
}


function VariantCard({
  abtestId,
  variant,
  testStatus,
  onChange,
}: {
  abtestId: number;
  variant: AbTestVariant;
  testStatus: AbTestStatus;
  onChange: () => void;
}) {
  const qc = useQueryClient();
  const canEdit = testStatus === "draft" || testStatus === "paused";

  const uploadOne = async (order: number, file: File) => {
    await abtestApi.uploadPhoto(abtestId, variant.id, order, file);
    onChange();
    await qc.invalidateQueries({ queryKey: ["abtest", abtestId] });
  };

  const deleteOne = async (photoId: number) => {
    await abtestApi.deletePhoto(abtestId, variant.id, photoId);
    onChange();
    await qc.invalidateQueries({ queryKey: ["abtest", abtestId] });
  };

  const eliminateMut = useMutation({
    mutationFn: () =>
      variant.eliminated_at
        ? abtestApi.unEliminateVariant(abtestId, variant.id)
        : abtestApi.eliminateVariant(abtestId, variant.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["abtest", abtestId] }),
  });

  return (
    <div className="card space-y-3">
      <div className="flex items-baseline justify-between">
        <div>
          {variant.eliminated_at && (
            <span className="text-warn text-xs">
              отсеян {fmtDate(variant.eliminated_at)}
            </span>
          )}
        </div>
        <button
          className="btn-link text-xs"
          onClick={() => eliminateMut.mutate()}
          disabled={eliminateMut.isPending}
        >
          {variant.eliminated_at ? "↩ Вернуть" : "✕ Отсеять"}
        </button>
      </div>

      <VariantPhotoGrid
        label={variant.label}
        abtestId={abtestId}
        variantId={variant.id}
        canEdit={canEdit}
        existingPhotos={variant.photos}
        onUploadLive={uploadOne}
        onDeleteLive={deleteOne}
      />
    </div>
  );
}

export default function AbTestDetail() {
  const { id: idStr } = useParams<{ id: string }>();
  const id = Number(idStr);
  const qc = useQueryClient();
  const [stopOpen, setStopOpen] = useState(false);

  const q = useQuery({
    queryKey: ["abtest", id],
    queryFn: () => abtestApi.get(id),
    enabled: Number.isFinite(id),
  });

  const resQ = useQuery({
    queryKey: ["abtest-result", id],
    queryFn: () => abtestApi.getResult(id),
    enabled: Number.isFinite(id),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["abtest", id] });
    qc.invalidateQueries({ queryKey: ["abtest-result", id] });
  };

  const action = (fn: () => Promise<unknown>) =>
    fn().then(invalidate).catch((e) => alert(`Ошибка: ${e.message}`));

  // Auto-label: следующий неиспользованный из A/B/C/D/E. Пользователь не
  // должен вводить «C» вручную — система знает что уже занято.
  const ALL_LABELS = ["A", "B", "C", "D", "E", "F", "G", "H"] as const;
  const nextLabel = (used: string[]): string | null => {
    const taken = new Set(used);
    return ALL_LABELS.find((l) => !taken.has(l)) ?? null;
  };

  const addVariantMut = useMutation({
    mutationFn: (label: string) => abtestApi.addVariant(id, label),
    onSuccess: invalidate,
  });

  if (q.isLoading) return <div className="text-muted">Загрузка…</div>;
  if (q.error)
    return <div className="card text-warn">{(q.error as Error).message}</div>;
  if (!q.data) return null;

  const { test, variants, recent_rotations, alerts } = q.data;
  const result = resQ.data;
  const canEdit = test.status === "draft" || test.status === "paused";

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <div>
          <Link to="/abtest" className="text-link text-sm">
            ← к списку
          </Link>
          {/* TASK-UI-011: detail-страница с back-link + dynamic title,
              PageHeader props не покрывают back-link слот — inline-h1. */}
          <h1 className="text-2xl font-semibold mt-1">{test.name}</h1>
          <div className="text-muted text-sm mt-1">
            nm_id <span className="font-mono">{test.nm_id}</span> •{" "}
            <span
              className={`inline-block px-2 py-0.5 rounded text-xs ${STATUS_BADGE[test.status]}`}
            >
              {test.status}
            </span>{" "}
            • {test.test_mode}/{test.traffic_source} • {test.trigger_mode}=
            {test.trigger_value}
            {test.trigger_mode === "TIME" && " мин"}
            {test.trigger_mode === "BUDGET" && " ₽"}
          </div>
        </div>
        <div className="flex gap-2">
          {test.status === "draft" && (
            <button
              className="btn btn-primary"
              onClick={() => action(() => abtestApi.start(id))}
            >
              Запустить
            </button>
          )}
          {test.status === "running" && (
            <>
              <button
                className="btn"
                onClick={() => action(() => abtestApi.pause(id))}
              >
                Пауза
              </button>
              <button
                className="btn"
                onClick={() => setStopOpen(true)}
              >
                Остановить
              </button>
              <button
                className="btn"
                onClick={() => action(() => abtestApi.syncNow(id))}
              >
                Sync stat
              </button>
            </>
          )}
          {test.status === "paused" && (
            <button
              className="btn btn-primary"
              onClick={() => action(() => abtestApi.resume(id))}
            >
              Возобновить
            </button>
          )}
          {(test.status === "paused" ||
            test.status === "completed" ||
            test.status === "cancelled") &&
            !test.archived_at && (
              <button
                className="btn"
                onClick={() => action(() => abtestApi.archive(id))}
              >
                В архив
              </button>
            )}
          {test.archived_at && (
            <button
              className="btn"
              onClick={() => action(() => abtestApi.unarchive(id))}
            >
              Из архива
            </button>
          )}
        </div>
      </div>

      {alerts.length > 0 && (
        <div className="space-y-1">
          {alerts.map((a) => (
            <div
              key={a.id}
              className="card flex items-start gap-2 text-warn border-warn"
            >
              <div className="flex-1">{a.message}</div>
              <button
                className="btn-link text-xs"
                onClick={() => action(() => abtestApi.resolveAlert(a.id))}
              >
                <Icon name="check" size={12} /> Resolve
              </button>
            </div>
          ))}
        </div>
      )}

      <section>
        {(() => {
          const usedLabels = variants.map((v) => v.label);
          const next = nextLabel(usedLabels);
          const canAdd = canEdit && next !== null && variants.length < 4;
          return (
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-lg font-medium">
                Варианты{" "}
                <span className="text-muted text-sm font-normal">
                  ({variants.length}/4)
                </span>
              </h2>
              {canAdd && (
                <button
                  className="btn-link text-sm"
                  onClick={() => addVariantMut.mutate(next!)}
                  disabled={addVariantMut.isPending}
                >
                  + Вариант {next}
                </button>
              )}
            </div>
          );
        })()}
        {/* 2-4 варианта на ряд (зависит от количества). Для 2 — две большие
            колонки 1:1, фото aspect-3/4 займут ~50% ширины контента → крупно,
            как в wbab. Для 3-4 вариантов плотнее. */}
        <div
          className={`grid gap-3 ${
            variants.length <= 2
              ? "grid-cols-1 md:grid-cols-2"
              : variants.length === 3
                ? "grid-cols-1 md:grid-cols-3"
                : "grid-cols-1 md:grid-cols-2 lg:grid-cols-4"
          }`}
        >
          {variants.map((v) => (
            <VariantCard
              key={v.id}
              abtestId={id}
              variant={v}
              testStatus={test.status}
              onChange={invalidate}
            />
          ))}
        </div>
      </section>

      {result && result.variants.some((v) => v.impressions > 0) && (
        <section className="space-y-2">
          <h2 className="text-lg font-medium">Результат</h2>

          {result.ctr_winner && (
            <div className="card border-success">
              <div className="text-success font-medium">
                <Icon name="star" size={12} /> Победитель по «{scenarioLabels(test.test_mode, test.traffic_source).top}»: вариант {result.ctr_winner.label}
              </div>
              {(test.status === "running" || test.status === "paused") && (
                <button
                  className="btn btn-primary mt-2"
                  onClick={() =>
                    action(() =>
                      abtestApi.applyWinner(id, result.ctr_winner!.variant_id),
                    )
                  }
                >
                  Зафиксировать победителя
                </button>
              )}
            </div>
          )}

          {/* Прогресс выборки — визуальные бары per variant */}
          <div className="card space-y-2">
            <h3 className="text-sm text-muted">Прогресс выборки</h3>
            {result.sample_progress.map((s) => (
              <div key={s.variant_id} className="flex items-center gap-2 text-sm">
                <span className="font-mono w-6">{s.label}</span>
                <div className="flex-1 bg-surface-2 rounded overflow-hidden h-2 relative">
                  <div
                    className={`h-full ${s.pct >= 100 ? "bg-success" : "bg-accent"}`}
                    style={{ width: `${Math.min(s.pct, 100)}%` }}
                  />
                </div>
                <span className="text-muted text-xs font-mono w-32 text-right">
                  {s.current}/{s.target} ({s.pct}%)
                </span>
              </div>
            ))}
          </div>

          <div className="card overflow-x-auto p-0">
            <table className="min-w-full text-sm">
              <thead className="bg-surface-2 text-muted text-xs uppercase">
                <tr>
                  <th className="text-left p-2">Вариант</th>
                  <th className="text-right p-2">Показы</th>
                  <th className="text-right p-2">Клики</th>
                  <th className="text-right p-2">Заказы</th>
                  <th
                    className="text-right p-2"
                    title={scenarioLabels(test.test_mode, test.traffic_source).top}
                  >
                    {scenarioLabels(test.test_mode, test.traffic_source).top}
                  </th>
                  <th className="text-right p-2">CI (95%)</th>
                  <th className="text-right p-2">Выборка</th>
                </tr>
              </thead>
              <tbody>
                {result.variants.map((v) => {
                  const ctr = result.ctr[String(v.variant_id)];
                  const prog = result.sample_progress.find(
                    (s) => s.variant_id === v.variant_id,
                  );
                  return (
                    <tr key={v.variant_id} className="border-t border-border">
                      <td className="p-2 font-medium">{v.label}</td>
                      <td className="p-2 text-right">{v.impressions}</td>
                      <td className="p-2 text-right">{v.clicks}</td>
                      <td className="p-2 text-right font-mono">{v.orders}</td>
                      <td className="p-2 text-right font-mono">
                        {(ctr?.rate * 100).toFixed(2)}%
                      </td>
                      <td className="p-2 text-right text-muted text-xs font-mono">
                        {(ctr?.ci_low * 100).toFixed(2)}–
                        {(ctr?.ci_high * 100).toFixed(2)}%
                      </td>
                      <td className="p-2 text-right">
                        {prog?.current}/{prog?.target} ({prog?.pct}%)
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="card">
            <h3 className="text-sm text-muted mb-2">
              Попарные тесты (p-value &lt; {result.alpha})
            </h3>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart
                data={result.variants.map((v) => ({
                  label: v.label,
                  CTR: Number(
                    ((result.ctr[String(v.variant_id)]?.rate ?? 0) * 100).toFixed(2),
                  ),
                }))}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" />
                <YAxis unit="%" />
                <Tooltip />
                <Legend />
                <Bar dataKey="CTR" fill="#4f46e5" />
              </BarChart>
            </ResponsiveContainer>
            <table className="min-w-full text-xs mt-2">
              <thead>
                <tr className="text-muted">
                  <th className="text-left p-1">Пара</th>
                  <th className="text-right p-1">CTR p-value</th>
                  <th className="text-right p-1">Знач.</th>
                </tr>
              </thead>
              <tbody>
                {result.pairwise.map((p) => (
                  <tr
                    key={`${p.a_id}-${p.b_id}`}
                    className={p.ctr_significant ? "text-success" : ""}
                  >
                    <td className="p-1">
                      {p.a_label} ↔ {p.b_label}
                    </td>
                    <td className="p-1 text-right font-mono">
                      {p.ctr_p_value.toExponential(2)}
                    </td>
                    <td className="p-1 text-right">
                      {p.ctr_significant ? "✓" : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <TimelineSection
        abtestId={id}
        variants={variants}
        rotations={recent_rotations}
      />

      <PositionsSection abtestId={id} />

      <StopDialog
        open={stopOpen}
        hasOriginalSnapshot={
          Array.isArray(test.original_photos) && test.original_photos.length > 0
        }
        onClose={() => setStopOpen(false)}
        onStop={async (mode) => {
          try {
            await abtestApi.stop(id, mode);
            setStopOpen(false);
            invalidate();
          } catch (e) {
            alert(`Не удалось остановить: ${(e as Error).message}`);
          }
        }}
      />
    </div>
  );
}
