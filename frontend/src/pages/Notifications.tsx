import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Icon } from "@/components/Icon";
import PageHeader from "@/components/PageHeader";

const METRIC_LABELS: Record<string, string> = {
  stock_below: "Остаток SKU ниже",
  daily_revenue_below: "Выручка за вчера ниже",
  drr_above: "ДРР рекламы выше %",
  returns_pct_above: "% возвратов вчера выше",
};

const METRIC_DEFAULTS: Record<string, { operator: string; threshold: number; cooldown: number }> = {
  stock_below: { operator: "<", threshold: 50, cooldown: 1440 },
  daily_revenue_below: { operator: "<", threshold: 200000, cooldown: 1440 },
  drr_above: { operator: ">", threshold: 30, cooldown: 1440 },
  returns_pct_above: { operator: ">", threshold: 40, cooldown: 1440 },
};

export default function Notifications() {
  const qc = useQueryClient();
  const q = useQuery<any>({
    queryKey: ["notification-rules"],
    queryFn: () => api.notificationsList(),
  });
  const rules: any[] = q.data?.items || [];

  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<any>({
    name: "",
    metric: "stock_below",
    operator: "<",
    threshold: 50,
    cooldown_minutes: 1440,
    is_active: true,
  });

  const createMut = useMutation({
    mutationFn: (payload: any) => api.notificationsCreate(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notification-rules"] });
      setAdding(false);
      setDraft({
        name: "",
        metric: "stock_below",
        operator: "<",
        threshold: 50,
        cooldown_minutes: 1440,
        is_active: true,
      });
    },
    onError: (e: any) => alert(`Ошибка: ${e?.message || e}`),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: any }) =>
      api.notificationsUpdate(id, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notification-rules"] }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.notificationsDelete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notification-rules"] }),
  });

  const dryRunMut = useMutation({
    mutationFn: () => api.notificationsEvaluate(true),
    onSuccess: (r: any) => {
      const triggered = r.evaluations.filter((e: any) => e.triggered);
      if (triggered.length === 0) {
        alert("Сейчас ни одно правило не сработало бы (dry-run).");
      } else {
        alert(
          `Сработали бы ${triggered.length} правил(а):\n` +
            triggered.map((e: any) => `• ${e.rule_name} — ${e.hits_count} hits`).join("\n"),
        );
      }
    },
    onError: (e: any) => alert(`Ошибка: ${e?.message || e}`),
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title="Уведомления"
        subtitle="Настраиваемые правила-алерты с отправкой в Telegram. Engine запускается раз в час, после срабатывания правило молчит `cooldown_minutes` (default 24 ч)."
      />

      <section className="card flex gap-3 items-center">
        <button className="btn text-sm" onClick={() => setAdding(true)}>
          <Icon name="plus" size={14} /> Новое правило
        </button>
        <button
          className="btn text-sm"
          onClick={() => dryRunMut.mutate()}
          disabled={dryRunMut.isPending}
        >
          <Icon name={dryRunMut.isPending ? "spinner" : "search"} size={14} className={dryRunMut.isPending ? "animate-spin" : ""} />
          {dryRunMut.isPending ? "Проверка…" : "Прогон сейчас (dry-run)"}
        </button>
      </section>

      {adding && (
        <section className="card space-y-3">
          <div className="font-medium">Новое правило</div>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1 text-xs">
              Название
              <input
                type="text"
                className="input"
                value={draft.name}
                placeholder="Напр. Остаток ниже 50"
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              Метрика
              <select
                className="input"
                value={draft.metric}
                onChange={(e) => {
                  const m = e.target.value;
                  const def = METRIC_DEFAULTS[m];
                  setDraft({
                    ...draft,
                    metric: m,
                    operator: def?.operator || "<",
                    threshold: def?.threshold ?? 0,
                    cooldown_minutes: def?.cooldown || 1440,
                  });
                }}
              >
                {Object.entries(METRIC_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs">
              Оператор
              <select
                className="input"
                value={draft.operator}
                onChange={(e) => setDraft({ ...draft, operator: e.target.value })}
              >
                {["<", ">", "<=", ">="].map((op) => (
                  <option key={op} value={op}>{op}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs">
              Порог
              <input
                type="number"
                className="input"
                step="any"
                value={draft.threshold}
                onChange={(e) => setDraft({ ...draft, threshold: Number(e.target.value) })}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              Cooldown, мин
              <input
                type="number"
                className="input"
                min={60}
                value={draft.cooldown_minutes}
                onChange={(e) => setDraft({ ...draft, cooldown_minutes: Number(e.target.value) })}
              />
            </label>
            <label className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={draft.is_active}
                onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
              />
              Активно
            </label>
          </div>
          <div className="flex gap-2">
            <button
              className="btn text-sm border-accent text-accent"
              disabled={!draft.name.trim() || createMut.isPending}
              onClick={() => createMut.mutate(draft)}
            >
              Создать
            </button>
            <button className="btn text-sm" onClick={() => setAdding(false)}>
              Отмена
            </button>
          </div>
        </section>
      )}

      <section className="card overflow-x-auto">
        {q.isLoading && <div className="text-muted">Загрузка…</div>}
        {rules.length === 0 && !q.isLoading && (
          <div className="text-muted text-center py-6">
            Правил ещё нет. Создайте первое — например «Остаток SKU ниже 50».
          </div>
        )}
        {rules.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-xs uppercase text-muted">
              <tr className="border-b border-border">
                <th className="text-left p-2">Активно</th>
                <th className="text-left p-2">Название</th>
                <th className="text-left p-2">Метрика</th>
                <th className="text-right p-2">Op</th>
                <th className="text-right p-2">Порог</th>
                <th className="text-right p-2">Cooldown</th>
                <th className="text-left p-2">Последний раз сработало</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r: any) => (
                <tr key={r.id} className={`border-b border-border/40 ${!r.is_active ? "opacity-60" : ""}`}>
                  <td className="p-2">
                    <input
                      type="checkbox"
                      checked={r.is_active}
                      onChange={(e) =>
                        updateMut.mutate({
                          id: r.id,
                          patch: { is_active: e.target.checked },
                        })
                      }
                    />
                  </td>
                  <td className="p-2">{r.name}</td>
                  <td className="p-2 text-muted">{METRIC_LABELS[r.metric] || r.metric}</td>
                  <td className="p-2 text-right font-mono">{r.operator}</td>
                  <td className="p-2 text-right font-mono">{r.threshold}</td>
                  <td className="p-2 text-right">{r.cooldown_minutes} мин</td>
                  <td className="p-2 text-muted text-xs">
                    {r.last_fired_at ? new Date(r.last_fired_at).toLocaleString("ru-RU") : "—"}
                  </td>
                  <td className="p-2 text-right">
                    <button
                      className="text-danger/70 hover:text-danger text-xs"
                      onClick={() => {
                        if (confirm(`Удалить правило «${r.name}»?`)) deleteMut.mutate(r.id);
                      }}
                    >
                      <Icon name="close" size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card text-xs text-muted">
        <strong className="text-fg">Доступные метрики:</strong>
        <ul className="mt-2 space-y-1 list-disc pl-5">
          <li><code>stock_below</code> — остаток отдельных SKU ниже порога</li>
          <li><code>daily_revenue_below</code> — выручка за вчерашний день ниже порога (preliminary)</li>
          <li><code>drr_above</code> — кампании с ДРР за неделю выше %</li>
          <li><code>returns_pct_above</code> — % возвратов от заказов вчера выше</li>
        </ul>
        <div className="mt-3">
          <strong className="text-fg">Канал:</strong> Telegram. Чат берётся из <code>app_settings.tg_chat_id</code>,
          токен — из переменной окружения <code>TG_BOT_TOKEN</code> бэкенда.
        </div>
      </section>
    </div>
  );
}
