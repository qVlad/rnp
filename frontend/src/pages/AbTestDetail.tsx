/**
 * Детали одного A/B теста: метаданные, варианты с фото-uploader'ом,
 * последние ротации, alerts, результат (значимость + графики).
 */
import { useRef, useState } from "react";
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

const STATUS_BADGE: Record<AbTestStatus | string, string> = {
  draft: "bg-surface-2 text-muted",
  running: "bg-success-bg text-success",
  paused: "bg-warn-bg text-warn",
  completed: "bg-info-bg text-info",
  cancelled: "bg-surface-2 text-muted",
};

function fmtDate(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleString("ru-RU");
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
  const fileRef = useRef<HTMLInputElement>(null);
  const [photoOrder, setPhotoOrder] = useState(1);
  const [uploading, setUploading] = useState(false);

  const canEdit = testStatus === "draft" || testStatus === "paused";

  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      setUploading(true);
      try {
        return await abtestApi.uploadPhoto(abtestId, variant.id, photoOrder, file);
      } finally {
        setUploading(false);
      }
    },
    onSuccess: () => {
      onChange();
      qc.invalidateQueries({ queryKey: ["abtest", abtestId] });
      if (fileRef.current) fileRef.current.value = "";
    },
  });

  const deletePhotoMut = useMutation({
    mutationFn: (photoId: number) =>
      abtestApi.deletePhoto(abtestId, variant.id, photoId),
    onSuccess: () => {
      onChange();
      qc.invalidateQueries({ queryKey: ["abtest", abtestId] });
    },
  });

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
        <h3 className="text-lg font-medium">
          Вариант {variant.label}
          {variant.eliminated_at && (
            <span className="ml-2 text-warn text-sm">
              (отсеян {fmtDate(variant.eliminated_at)})
            </span>
          )}
        </h3>
        <button
          className="btn-link text-xs"
          onClick={() => eliminateMut.mutate()}
          disabled={eliminateMut.isPending}
        >
          {variant.eliminated_at ? "↩ Вернуть" : "✕ Отсеять"}
        </button>
      </div>

      {(() => {
        const sorted = [...variant.photos].sort((a, b) => a.photo_order - b.photo_order);
        const main = sorted.find((p) => p.photo_order === 1) ?? sorted[0];
        const extras = sorted.filter((p) => p !== main);
        // Главное фото: aspect-[3/4] (WB стандарт 900×1200) на всю ширину
        // колонки. Доп. фото — сетка 3-в-ряд, aspect-[3/4] поменьше.
        return (
          <>
            {/* Главное фото варианта (photo_order=1) */}
            {main ? (
              <div className="relative group">
                <img
                  src={abtestApi.photoUrl(abtestId, variant.id, main.id)}
                  alt={`Вариант ${variant.label} — главное`}
                  className="aspect-[3/4] w-full object-cover rounded-lg border border-border"
                />
                <div className="absolute bottom-1 left-1 text-xs bg-surface/90 backdrop-blur px-1.5 py-0.5 rounded">
                  #{main.photo_order} главное
                </div>
                {canEdit && (
                  <button
                    className="absolute top-1 right-1 grid h-6 w-6 place-items-center rounded-full bg-fg/80 text-bg text-xs opacity-0 group-hover:opacity-100"
                    onClick={() => deletePhotoMut.mutate(main.id)}
                    title="Удалить главное"
                  >
                    ✕
                  </button>
                )}
              </div>
            ) : (
              <div className="aspect-[3/4] w-full rounded-lg border-2 border-dashed border-border bg-surface-2 flex items-center justify-center text-muted text-sm">
                Главное фото не загружено
              </div>
            )}
            {/* Доп. фото — 3-в-ряд, aspect-3/4 */}
            {extras.length > 0 && (
              <div className="grid grid-cols-3 gap-2 mt-2">
                {extras.map((p) => (
                  <div key={p.id} className="relative group">
                    <img
                      src={abtestApi.photoUrl(abtestId, variant.id, p.id)}
                      alt={`#${p.photo_order}`}
                      className="aspect-[3/4] w-full object-cover rounded border border-border"
                    />
                    <div className="absolute bottom-0.5 left-0.5 text-[10px] bg-surface/90 backdrop-blur px-1 rounded">
                      #{p.photo_order}
                    </div>
                    {canEdit && (
                      <button
                        className="absolute top-0.5 right-0.5 grid h-5 w-5 place-items-center rounded-full bg-fg/80 text-bg text-[10px] opacity-0 group-hover:opacity-100"
                        onClick={() => deletePhotoMut.mutate(p.id)}
                        title="Удалить"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        );
      })()}

      {canEdit && (
        <div className="border-t border-border pt-3 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label>Позиция:</label>
            <input
              type="number"
              min={1}
              max={20}
              className="input w-14"
              value={photoOrder}
              onChange={(e) => setPhotoOrder(Number(e.target.value))}
            />
            <span className="text-xs text-muted">
              (1 = главное, 2-10 = доп.)
            </span>
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,video/mp4"
              className="text-xs"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) uploadMut.mutate(f);
              }}
              disabled={uploading}
            />
            {uploading && <span className="text-xs text-muted">загрузка…</span>}
          </div>
          {uploadMut.error && (
            <div className="text-warn text-xs">
              {(uploadMut.error as Error).message}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function AbTestDetail() {
  const { id: idStr } = useParams<{ id: string }>();
  const id = Number(idStr);
  const qc = useQueryClient();
  const [addingVariant, setAddingVariant] = useState(false);
  const [newLabel, setNewLabel] = useState("");

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

  const addVariantMut = useMutation({
    mutationFn: () => abtestApi.addVariant(id, newLabel),
    onSuccess: () => {
      setAddingVariant(false);
      setNewLabel("");
      invalidate();
    },
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
                onClick={() => action(() => abtestApi.stop(id))}
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
                ✓ Resolve
              </button>
            </div>
          ))}
        </div>
      )}

      <section>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-medium">Варианты</h2>
          {canEdit && !addingVariant && (
            <button
              className="btn-link text-sm"
              onClick={() => setAddingVariant(true)}
            >
              + Вариант
            </button>
          )}
        </div>
        {addingVariant && (
          <div className="card mb-2 flex gap-2 items-center">
            <input
              className="input"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="Лейбл (C, D, ...)"
              maxLength={8}
            />
            <button
              className="btn btn-primary"
              onClick={() => addVariantMut.mutate()}
              disabled={!newLabel || addVariantMut.isPending}
            >
              Добавить
            </button>
            <button className="btn" onClick={() => setAddingVariant(false)}>
              Отмена
            </button>
          </div>
        )}
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
                Победитель по CTR: вариант {result.ctr_winner.label}
              </div>
              {test.status === "running" && (
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

          <div className="card overflow-x-auto p-0">
            <table className="min-w-full text-sm">
              <thead className="bg-surface-2 text-muted text-xs uppercase">
                <tr>
                  <th className="text-left p-2">Вариант</th>
                  <th className="text-right p-2">Показы</th>
                  <th className="text-right p-2">Клики</th>
                  <th className="text-right p-2">Заказы</th>
                  <th className="text-right p-2">CTR</th>
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
                      <td className="p-2 text-right">{v.orders}</td>
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

      <section>
        <h2 className="text-lg font-medium mb-2">Последние ротации</h2>
        {recent_rotations.length === 0 ? (
          <div className="card text-muted">Ротаций ещё не было.</div>
        ) : (
          <div className="card overflow-x-auto p-0">
            <table className="min-w-full text-sm">
              <thead className="bg-surface-2 text-muted text-xs uppercase">
                <tr>
                  <th className="text-left p-2">Время</th>
                  <th className="text-left p-2">Вариант</th>
                  <th className="text-left p-2">Статус</th>
                  <th className="text-left p-2">Ошибка</th>
                </tr>
              </thead>
              <tbody>
                {recent_rotations.map((r) => {
                  const v = variants.find((x) => x.id === r.variant_id);
                  return (
                    <tr key={r.id} className="border-t border-border">
                      <td className="p-2 text-muted">{fmtDate(r.applied_at)}</td>
                      <td className="p-2">{v?.label || `#${r.variant_id}`}</td>
                      <td
                        className={`p-2 ${r.success ? "text-success" : "text-warn"}`}
                      >
                        {r.success ? "✓ OK" : "✕ FAIL"}
                      </td>
                      <td className="p-2 text-muted text-xs">{r.error || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
