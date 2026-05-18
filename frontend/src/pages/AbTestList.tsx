/**
 * A/B тесты — список с фильтрами.
 * Конструкция: тонкий UI поверх abtestApi.list(). React-Query кеширует.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { abtestApi, AbTestStatus } from "@/api/abtest";

const STATUS_LABELS: Record<AbTestStatus | string, string> = {
  draft: "Черновик",
  running: "Идёт",
  paused: "Пауза",
  completed: "Завершён",
  cancelled: "Остановлен",
};

const STATUS_COLOR: Record<string, string> = {
  draft: "text-muted",
  running: "text-success",
  paused: "text-warn",
  completed: "text-info",
  cancelled: "text-muted",
};

function fmtDate(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleString("ru-RU", {
    day: "2-digit", month: "2-digit", year: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

export default function AbTestList() {
  const [includeArchived, setIncludeArchived] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["abtest-list", includeArchived, statusFilter],
    queryFn: () =>
      abtestApi.list({
        include_archived: includeArchived,
        status: statusFilter || undefined,
      }),
  });

  const archiveMut = useMutation({
    mutationFn: ({ id, archived }: { id: number; archived: boolean }) =>
      archived ? abtestApi.unarchive(id) : abtestApi.archive(id),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["abtest-list"] }),
    onError: (e) => alert(`Не удалось: ${(e as Error).message}`),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => abtestApi.delete(id),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["abtest-list"] }),
    onError: (e) => alert(`Не удалось: ${(e as Error).message}`),
  });

  const items = q.data?.items || [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">A/B тесты карточек</h1>
        <Link to="/abtest/new" className="btn btn-primary">
          + Новый тест
        </Link>
      </div>

      <div className="flex gap-3 items-center">
        <select
          className="input w-40"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">Все статусы</option>
          <option value="draft">Черновик</option>
          <option value="running">Идёт</option>
          <option value="paused">Пауза</option>
          <option value="completed">Завершён</option>
          <option value="cancelled">Остановлен</option>
        </select>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          Включая архивные
        </label>
        <div className="text-muted text-sm ml-auto">
          {q.isLoading ? "Загрузка…" : `${items.length} тестов`}
        </div>
      </div>

      {q.error ? (
        <div className="card text-warn">{(q.error as Error).message}</div>
      ) : items.length === 0 ? (
        <div className="card text-muted">
          {q.isLoading
            ? "…"
            : "Ни одного теста не найдено. Создайте первый — кнопка «Новый тест» справа сверху."}
        </div>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="min-w-full text-sm">
            <thead className="bg-surface-2 text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-3">Название</th>
                <th className="text-left p-3">SKU</th>
                <th className="text-left p-3">Статус</th>
                <th className="text-left p-3">Режим</th>
                <th className="text-left p-3">Триггер</th>
                <th className="text-left p-3">Старт</th>
                <th className="text-right p-3">Действия</th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => {
                const archived = t.archived_at != null;
                const canDelete = t.status !== "running";
                return (
                  <tr
                    key={t.id}
                    className="border-t border-border hover:bg-surface-2"
                  >
                    <td className="p-3">
                      <Link
                        to={`/abtest/${t.id}`}
                        className="text-link font-medium"
                      >
                        {t.name}
                      </Link>
                      {archived && (
                        <span className="ml-2 text-xs text-muted">📦</span>
                      )}
                    </td>
                    <td className="p-3 font-mono">{t.nm_id}</td>
                    <td className={`p-3 ${STATUS_COLOR[t.status] || ""}`}>
                      {STATUS_LABELS[t.status] || t.status}
                    </td>
                    <td className="p-3">
                      {t.test_mode}/{t.traffic_source}
                    </td>
                    <td className="p-3">
                      {t.trigger_mode}={t.trigger_value}
                      {t.trigger_mode === "TIME" && " мин"}
                      {t.trigger_mode === "BUDGET" && " ₽"}
                    </td>
                    <td className="p-3 text-muted">{fmtDate(t.started_at)}</td>
                    <td className="p-3 text-right whitespace-nowrap">
                      <button
                        className="btn-link text-xs mr-2"
                        title={archived ? "Вернуть из архива" : "В архив"}
                        onClick={() =>
                          archiveMut.mutate({ id: t.id, archived })
                        }
                        disabled={archiveMut.isPending || t.status === "running"}
                      >
                        {archived ? "↺ Из архива" : "📦 Архив"}
                      </button>
                      <button
                        className="btn-link text-xs text-warn"
                        title={
                          canDelete
                            ? "Удалить тест и все его данные"
                            : "Сначала остановите тест"
                        }
                        onClick={() => {
                          if (
                            window.confirm(
                              `Удалить тест «${t.name}»? Это удалит варианты, фото и историю ротаций.`,
                            )
                          ) {
                            deleteMut.mutate(t.id);
                          }
                        }}
                        disabled={deleteMut.isPending || !canDelete}
                      >
                        ✕ Удалить
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
