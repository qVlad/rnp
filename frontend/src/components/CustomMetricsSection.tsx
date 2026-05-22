/**
 * UI для создания / редактирования кастомных формул KPI (TASK-DEV-011).
 *
 * Размещается в /settings. Только для роли director (CUD).
 *
 *   1. Таблица существующих templates с inline-edit + delete.
 *   2. Кнопка «Добавить» открывает форму создания с live-preview.
 *   3. Live-preview шлёт POST /preview на каждом изменении formula
 *      (debounced 500ms). Показывает либо value (с форматированием),
 *      либо ошибку валидации.
 *   4. Dropdown переменных + функций для подсказки юзеру какие имена
 *      доступны.
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtNum, fmtPct } from "@/lib/format";
import { Icon } from "./Icon";
import { Icon } from "./Icon";

type Format = "currency" | "percent" | "number";

interface Template {
  id: number;
  name: string;
  formula: string;
  format: Format;
  description: string | null;
}

function formatValue(value: number, fmt: Format): string {
  if (fmt === "currency") return fmtRub(value);
  if (fmt === "percent") return fmtPct(value);
  return fmtNum(value);
}

function useDebounced<T>(value: T, delay: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

export default function CustomMetricsSection() {
  const qc = useQueryClient();
  const listQ = useQuery({
    queryKey: ["metric-templates"],
    queryFn: () => api.metricTemplatesList(),
  });
  const varsQ = useQuery({
    queryKey: ["metric-templates-vars"],
    queryFn: () => api.metricTemplatesVariables(),
  });

  const [editing, setEditing] = useState<Template | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  return (
    <section id="custom-metrics" className="card">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="font-medium">Кастомные KPI (формулы)</h2>
        <button
          type="button"
          className="btn-primary text-xs"
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
        >
          + Добавить формулу
        </button>
      </div>

      <div className="text-xs text-muted mb-3 leading-relaxed">
        Пиши свои KPI как формулы из переменных Dashboard. Например:{" "}
        <code className="text-fg">(revenue_net - ad_cost) / orders</code> —
        чистая прибыль на заказ. Доступные переменные:{" "}
        <span className="font-mono">
          {varsQ.data?.variables.map((v) => v.key).join(", ")}
        </span>
        . Функции:{" "}
        <span className="font-mono">{varsQ.data?.functions.join(", ")}</span>.
      </div>

      {listQ.data && listQ.data.items.length === 0 && !formOpen && (
        <div className="text-sm text-muted">
          Пока нет ни одной формулы. Жми «+ Добавить формулу».
        </div>
      )}

      {listQ.data && listQ.data.items.length > 0 && (
        <table className="w-full text-sm mb-3">
          <thead>
            <tr className="text-xs text-muted border-b border-border">
              <th className="text-left p-2">Название</th>
              <th className="text-left p-2">Формула</th>
              <th className="text-left p-2">Формат</th>
              <th className="text-right p-2"></th>
            </tr>
          </thead>
          <tbody>
            {listQ.data.items.map((m) => (
              <tr key={m.id} className="border-b border-border/40">
                <td className="p-2 font-medium">{m.name}</td>
                <td className="p-2 font-mono text-xs">{m.formula}</td>
                <td className="p-2 text-xs text-muted">{m.format}</td>
                <td className="p-2 text-right">
                  <button
                    type="button"
                    className="btn text-xs mr-1"
                    onClick={() => {
                      setEditing(m as Template);
                      setFormOpen(true);
                    }}
                  >
                    <Icon name="edit" size={12} />
                  </button>
                  <button
                    type="button"
                    className="btn text-xs text-danger"
                    onClick={async () => {
                      if (!confirm(`Удалить «${m.name}»?`)) return;
                      await api.metricTemplatesDelete(m.id);
                      qc.invalidateQueries({ queryKey: ["metric-templates"] });
                      qc.invalidateQueries({ queryKey: ["metric-templates-evaluate"] });
                    }}
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {formOpen && (
        <MetricForm
          existing={editing}
          variables={varsQ.data?.variables ?? []}
          onClose={() => {
            setFormOpen(false);
            setEditing(null);
            qc.invalidateQueries({ queryKey: ["metric-templates"] });
            qc.invalidateQueries({ queryKey: ["metric-templates-evaluate"] });
          }}
        />
      )}
    </section>
  );
}

function MetricForm({
  existing,
  variables,
  onClose,
}: {
  existing: Template | null;
  variables: Array<{ key: string; description: string }>;
  onClose: () => void;
}) {
  const [name, setName] = useState(existing?.name || "");
  const [formula, setFormula] = useState(existing?.formula || "");
  const [format, setFormat] = useState<Format>(existing?.format || "number");
  const [description, setDescription] = useState(existing?.description || "");
  const debouncedFormula = useDebounced(formula, 500);

  const previewMut = useMutation({
    mutationFn: (f: string) => api.metricTemplatesPreview(f),
  });

  useEffect(() => {
    if (debouncedFormula.trim()) {
      previewMut.mutate(debouncedFormula);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedFormula]);

  const preview = previewMut.data;

  const saveMut = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), formula: formula.trim(), format, description: description.trim() || null };
      return existing
        ? api.metricTemplatesUpdate(existing.id, body)
        : api.metricTemplatesCreate(body);
    },
    onSuccess: onClose,
  });

  const canSave = useMemo(
    () => name.trim() && formula.trim() && preview?.ok === true,
    [name, formula, preview],
  );

  return (
    <div className="border border-border rounded p-3 mt-3 bg-surface-2/40">
      <div className="font-medium mb-2">
        {existing ? `Редактировать «${existing.name}»` : "Новая формула"}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="flex flex-col text-xs text-muted">
          Название
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Например, Маржа на заказ"
          />
        </label>
        <label className="flex flex-col text-xs text-muted">
          Формат
          <select
            className="input"
            value={format}
            onChange={(e) => setFormat(e.target.value as Format)}
          >
            <option value="number">Число</option>
            <option value="currency">Рубли (₽)</option>
            <option value="percent">Процент (%)</option>
          </select>
        </label>
        <label className="flex flex-col text-xs text-muted md:col-span-2">
          Формула
          <input
            className="input font-mono text-sm"
            value={formula}
            onChange={(e) => setFormula(e.target.value)}
            placeholder="(revenue_net - ad_cost) / orders"
          />
        </label>
        <label className="flex flex-col text-xs text-muted md:col-span-2">
          Описание (опционально)
          <input
            className="input"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Что показывает эта метрика — для tooltip'а на Dashboard"
          />
        </label>
      </div>

      {/* Live preview */}
      <div className="mt-3 text-xs">
        {previewMut.isPending && <span className="text-muted">проверяю…</span>}
        {preview?.ok === true && (
          <span className="text-success">
            <Icon name="check" size={12} /> За эту неделю значение ={" "}
            <strong>{formatValue(preview.value || 0, format)}</strong>
          </span>
        )}
        {preview?.ok === false && (
          <span className="text-danger"><Icon name="warning" size={12} /> {preview.error}</span>
        )}
      </div>

      {/* Vars hint */}
      <details className="text-xs text-muted mt-2">
        <summary className="cursor-pointer text-accent hover:underline">
          Список переменных ({variables.length})
        </summary>
        <table className="w-full mt-2">
          <tbody>
            {variables.map((v) => (
              <tr key={v.key} className="border-b border-border/30">
                <td className="font-mono py-1 pr-3">{v.key}</td>
                <td className="py-1 text-muted">{v.description}</td>
                <td className="py-1 text-right">
                  <button
                    type="button"
                    className="btn text-[10px]"
                    onClick={() => setFormula((f) => f + v.key)}
                    title="Вставить в формулу"
                  >
                    + вставить
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      <div className="flex gap-2 mt-3">
        <button
          type="button"
          className="btn-primary text-xs"
          disabled={!canSave || saveMut.isPending}
          onClick={() => saveMut.mutate()}
        >
          {saveMut.isPending ? "Сохраняю…" : existing ? "Сохранить" : "Создать"}
        </button>
        <button type="button" className="btn text-xs" onClick={onClose}>
          Отмена
        </button>
        {saveMut.isError && (
          <span className="text-danger text-xs self-center">
            {(saveMut.error as Error).message}
          </span>
        )}
      </div>
    </div>
  );
}
