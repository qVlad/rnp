/**
 * Страница «Перемерки WB» — TASK-LEAD-129.
 *
 * WB периодически делает перемерку товаров на складе → меняет
 * `dimensions: {length, width, height}` в карточке → объём растёт →
 * тариф логистики растёт → маржа падает. Эта страница показывает все
 * перемерки в одном списке + позволяет вручную дёрнуть sync.
 *
 * Источник данных: таблица `wb_product_dimensions_history` (миграция 0063),
 * заполняется Celery-таском `sync.product_volume` ежедневно 05:45 MSK.
 * При detected изменении — TG-нотификация директорам.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type DimensionsHistoryRow } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";
import PageHeader from "@/components/PageHeader";
import { Icon } from "@/components/Icon";

function fmtCm(v: number | null | undefined): string {
  if (v == null) return "—";
  const s = v.toFixed(2).replace(/\.?0+$/, "");
  return s || "0";
}

function fmtVol(v: number | null | undefined): string {
  if (v == null) return "—";
  const s = v.toFixed(3).replace(/\.?0+$/, "");
  return s || "0";
}

function fmtDelta(prev: number | null, next: number | null): {
  text: string;
  tone: "success" | "danger" | "muted";
} {
  if (prev == null || next == null || prev === 0) {
    return { text: "", tone: "muted" };
  }
  const pct = ((next - prev) / prev) * 100;
  const arrow = pct > 0 ? "↑" : "↓";
  return {
    text: `${arrow}${Math.abs(pct).toFixed(1)}%`,
    // Перемерка вверх — это плохо (логистика дороже),
    // вниз — хорошо (но WB так почти не делает).
    tone: pct > 0 ? "danger" : "success",
  };
}

function fmtDate(s: string | null): string {
  if (!s) return "—";
  const d = new Date(s);
  return d.toLocaleString("ru-RU", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function DimensionsHistory() {
  const { user } = useAuth();
  const canSync =
    user?.role === "director" || user?.role === "head_of_sales";

  const [onlyChanges, setOnlyChanges] = useState(true);
  const [limit, setLimit] = useState(100);

  const listQ = useQuery({
    queryKey: ["dimensions-history", onlyChanges, limit],
    queryFn: () =>
      api.dimensionsHistory({ only_changes: onlyChanges, limit }),
  });

  const syncMut = useMutation({
    mutationFn: () => api.dimensionsSyncNow(),
    onSuccess: () => {
      alert(
        "Запущен sync габаритов. Это занимает 1-3 мин. Обнови страницу через минуту.",
      );
    },
    onError: (e: any) => {
      alert(`Не удалось запустить: ${e?.message ?? e}`);
    },
  });

  const items: DimensionsHistoryRow[] = listQ.data?.items ?? [];

  const stats = useMemo(() => {
    const changes = items.filter((r) => r.change_kind === "changed").length;
    const initial = items.filter((r) => r.change_kind === "initial").length;
    return { changes, initial, total: items.length };
  }, [items]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Перемерки WB"
        subtitle="История изменений габаритов карточек. WB периодически делает перемерку — это меняет тариф логистики."
        actions={
          <div className="flex items-center gap-2">
            {canSync && (
              <button
                className="btn"
                onClick={() => syncMut.mutate()}
                disabled={syncMut.isPending}
              >
                <Icon name="refresh" />
                {syncMut.isPending ? "Запускаю…" : "Sync сейчас"}
              </button>
            )}
          </div>
        }
      />

      <div className="card p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={onlyChanges}
              onChange={(e) => setOnlyChanges(e.target.checked)}
            />
            Только реальные перемерки (скрыть первичные снимки)
          </label>
          <label className="flex items-center gap-2 text-sm">
            Показать:
            <select
              className="input"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            >
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={200}>200</option>
              <option value={500}>500</option>
            </select>
          </label>
          <div className="text-sm text-muted ml-auto">
            Всего записей: <b>{stats.total}</b>
            {onlyChanges ? null : (
              <>
                {" • "}
                перемерки: <b>{stats.changes}</b>
                {" • "}
                первичные: <b>{stats.initial}</b>
              </>
            )}
          </div>
        </div>
      </div>

      {listQ.isLoading && (
        <div className="card p-8 text-center text-muted">Загружаю…</div>
      )}
      {listQ.isError && (
        <div className="card p-8 text-center text-danger">
          Ошибка загрузки: {String((listQ.error as any)?.message ?? "")}
        </div>
      )}
      {!listQ.isLoading && !listQ.isError && items.length === 0 && (
        <div className="card p-8 text-center text-muted">
          {onlyChanges
            ? "Перемерок не зафиксировано. Если только что подключили WB — подожди первого запуска sync (05:45 МСК) или нажми «Sync сейчас»."
            : "Истории нет."}
        </div>
      )}

      {items.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-muted">
              <tr>
                <th className="px-3 py-2">Дата</th>
                <th className="px-3 py-2">Фото</th>
                <th className="px-3 py-2">SKU</th>
                <th className="px-3 py-2">Бренд</th>
                <th className="px-3 py-2">Было (см)</th>
                <th className="px-3 py-2">Стало (см)</th>
                <th className="px-3 py-2">Объём (л)</th>
                <th className="px-3 py-2">Δ</th>
                <th className="px-3 py-2">Тип</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => {
                const delta = fmtDelta(r.prev_volume_l, r.volume_l);
                const oldLwh =
                  r.change_kind === "initial"
                    ? "—"
                    : `${fmtCm(r.prev_length_cm)}×${fmtCm(r.prev_width_cm)}×${fmtCm(r.prev_height_cm)}`;
                const newLwh = `${fmtCm(r.length_cm)}×${fmtCm(r.width_cm)}×${fmtCm(r.height_cm)}`;
                const oldVol =
                  r.change_kind === "initial" ? "—" : fmtVol(r.prev_volume_l);
                const newVol = fmtVol(r.volume_l);
                return (
                  <tr
                    key={r.id}
                    className="border-t border-soft hover:bg-soft/40"
                  >
                    <td className="px-3 py-2 whitespace-nowrap text-muted">
                      {fmtDate(r.detected_at)}
                    </td>
                    <td className="px-3 py-2">
                      {r.photo_url ? (
                        <a
                          href={`https://www.wildberries.ru/catalog/${r.nm_id}/detail.aspx`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <img
                            src={r.photo_url}
                            alt=""
                            className="w-10 h-10 object-cover rounded"
                            loading="lazy"
                          />
                        </a>
                      ) : (
                        <div className="w-10 h-10 bg-soft rounded" />
                      )}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <a
                        href={`https://www.wildberries.ru/catalog/${r.nm_id}/detail.aspx`}
                        target="_blank"
                        rel="noreferrer"
                        className="text-accent hover:underline"
                      >
                        {r.nm_id}
                      </a>
                      {r.name && (
                        <div className="text-xs text-muted truncate max-w-[200px]">
                          {r.name}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {r.brand ?? "—"}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-muted">
                      {oldLwh}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap font-medium">
                      {newLwh}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <span className="text-muted">{oldVol}</span>
                      {" → "}
                      <span className="font-medium">{newVol}</span>
                    </td>
                    <td
                      className={`px-3 py-2 whitespace-nowrap text-${delta.tone}`}
                    >
                      {delta.text}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {r.change_kind === "initial" ? (
                        <span className="text-muted text-xs">первичный</span>
                      ) : (
                        <span className="text-warn text-xs">перемерка</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="text-xs text-muted">
        Sync габаритов — автоматически каждый день 05:45 МСК через Celery
        beat <code>sync-product-volume-daily</code>. При обнаружении
        перемерки — Telegram-нотификация директорам.
        <span> Игнорировать использование функции — </span>
        <a href="/unit-plan" className="text-accent hover:underline">
          проверь /unit-plan
        </a>
        , тариф логистики мог измениться.
        <br />
        Не путать с алертом «нет габаритов» на дашборде — там SKU без
        замеров вообще, тут — история уже-известных.
      </div>
    </div>
  );
}
