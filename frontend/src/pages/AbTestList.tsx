/**
 * A/B тесты — список с фильтрами.
 * Конструкция: тонкий UI поверх abtestApi.list(). React-Query кеширует.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
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

  const q = useQuery({
    queryKey: ["abtest-list", includeArchived, statusFilter],
    queryFn: () =>
      abtestApi.list({
        include_archived: includeArchived,
        status: statusFilter || undefined,
      }),
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
            <thead className="bg-bg-2 text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-3">Название</th>
                <th className="text-left p-3">SKU</th>
                <th className="text-left p-3">Статус</th>
                <th className="text-left p-3">Режим</th>
                <th className="text-left p-3">Триггер</th>
                <th className="text-left p-3">Старт</th>
                <th className="text-left p-3">Архив</th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id} className="border-t border-border-1 hover:bg-bg-2">
                  <td className="p-3">
                    <Link
                      to={`/abtest/${t.id}`}
                      className="text-link font-medium"
                    >
                      {t.name}
                    </Link>
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
                  <td className="p-3 text-muted">{fmtDate(t.archived_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
