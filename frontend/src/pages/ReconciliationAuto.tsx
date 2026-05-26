/**
 * `/reconciliation-auto` — автосверка с WB ЛК (TASK-LEAD-137).
 *
 * 17 правил TrueStats art.74754. Колонки:
 *   - Правило #
 *   - Метрика + формула
 *   - Наша БД (our_value, рассчитан backend'ом из wb_report_detail)
 *   - WB ЛК (manual input ИЛИ автозаполняется из xlsx-upload)
 *   - Δ (наша − WB) с цветовой индикацией
 *
 * Цветовая индикация Δ:
 *   - ✅ < 1₽ — совпадение
 *   - ⚠️ 1..100₽ — подозрительно
 *   - 🔴 > 100₽ — расхождение
 *
 * Loading xlsx: drag-drop или file input → POST /upload-xlsx → backend парсит
 * и возвращает 17 чисел → подставляются в `wb_value` колонку.
 *
 * Методология и cross-link на RECON_GUIDE.md.
 */
import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  api,
  type ReconciliationAutoMetric,
  type ReconciliationAutoResponse,
} from "@/api/client";
import PageHeader from "@/components/PageHeader";
import { Icon } from "@/components/Icon";

function fmtMoney(v: number, isCount: boolean = false): string {
  if (isCount) return Math.round(v).toLocaleString("ru-RU");
  return v.toLocaleString("ru-RU", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function lastClosedWeekStart(): string {
  const today = new Date();
  const daysSinceMon = (today.getDay() + 6) % 7; // Mon=0, Sun=6
  const thisMon = new Date(today);
  thisMon.setDate(today.getDate() - daysSinceMon);
  const lastMon = new Date(thisMon);
  lastMon.setDate(thisMon.getDate() - 7);
  return lastMon.toISOString().slice(0, 10);
}

type DeltaTone = "ok" | "warn" | "danger" | "none";

function deltaInfo(
  our: number,
  wb: number | null,
  isCount: boolean,
): { delta: number | null; tone: DeltaTone; label: string } {
  if (wb === null || isNaN(wb)) {
    return { delta: null, tone: "none", label: "—" };
  }
  const d = our - wb;
  const abs = Math.abs(d);
  if (isCount) {
    if (abs === 0) return { delta: d, tone: "ok", label: "0" };
    if (abs <= 2) return { delta: d, tone: "warn", label: d > 0 ? `+${d}` : `${d}` };
    return { delta: d, tone: "danger", label: d > 0 ? `+${d}` : `${d}` };
  }
  if (abs < 1) return { delta: d, tone: "ok", label: "≈0" };
  if (abs < 100)
    return {
      delta: d,
      tone: "warn",
      label: (d > 0 ? "+" : "") + fmtMoney(d),
    };
  return {
    delta: d,
    tone: "danger",
    label: (d > 0 ? "+" : "") + fmtMoney(d),
  };
}

const TONE_BG: Record<DeltaTone, string> = {
  ok: "bg-success/10 text-success",
  warn: "bg-warn/10 text-warn",
  danger: "bg-danger/10 text-danger",
  none: "text-muted",
};

const STATUS_BADGE: Record<string, { icon: string; tone: string; tooltip: string }> = {
  ok: { icon: "check", tone: "text-success", tooltip: "Формула актуальна" },
  gap_135: {
    icon: "alert-triangle",
    tone: "text-warn",
    tooltip: "TASK-LEAD-135: разложение на 4 компонента − 14 исключений в работе",
  },
  gap_136: {
    icon: "alert-triangle",
    tone: "text-warn",
    tooltip: "TASK-LEAD-136: 3-этапный TS-процесс не реализован",
  },
};

export default function ReconciliationAuto() {
  const [weekStart, setWeekStart] = useState(lastClosedWeekStart);
  const [wbValues, setWbValues] = useState<Record<number, string>>({}); // user input by rule_number
  const fileRef = useRef<HTMLInputElement>(null);

  const q = useQuery({
    queryKey: ["reconciliation-auto", weekStart],
    queryFn: () => api.reconciliationAuto(weekStart),
  });

  const xlsxMut = useMutation({
    mutationFn: (file: File) => api.reconciliationAutoUploadXlsx(file),
    onSuccess: (data) => {
      const next: Record<number, string> = {};
      for (const [k, v] of Object.entries(data.metrics_by_rule)) {
        next[Number(k)] = String(v);
      }
      setWbValues(next);
    },
    onError: (e: any) => {
      alert(`Не удалось распарсить xlsx: ${e?.message ?? e}`);
    },
  });

  const onPick = () => fileRef.current?.click();
  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) xlsxMut.mutate(f);
    if (fileRef.current) fileRef.current.value = "";
  };

  const data: ReconciliationAutoResponse | undefined = q.data;

  const grouped = useMemo(() => {
    if (!data) return [] as Array<[string, ReconciliationAutoMetric[]]>;
    const map = new Map<string, ReconciliationAutoMetric[]>();
    for (const m of data.metrics) {
      if (!map.has(m.group)) map.set(m.group, []);
      map.get(m.group)!.push(m);
    }
    // Order groups
    const order = ["sales", "logistics", "deductions", "ads_orders", "advanced"];
    return order
      .filter((g) => map.has(g))
      .map((g) => [g, map.get(g)!.sort((a, b) => a.rule_number - b.rule_number)] as [string, ReconciliationAutoMetric[]]);
  }, [data]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Автосверка с WB ЛК"
        subtitle={
          <>
            17 правил по{" "}
            <a
              href="https://truestats.usedocs.com/article/74754"
              target="_blank"
              rel="noreferrer"
              className="text-accent hover:underline"
            >
              методологии TrueStats art.74754
            </a>
            . Полная инструкция:{" "}
            <a href="/docs/RECON_GUIDE" className="text-accent hover:underline">
              📖 RECON_GUIDE
            </a>
          </>
        }
        actions={
          <div className="flex gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".xlsx"
              hidden
              onChange={onFile}
            />
            <button
              className="btn"
              onClick={onPick}
              disabled={xlsxMut.isPending}
              title="Загрузить WB-xlsx «Еженедельный детализированный отчёт» — автозаполнит колонку «WB ЛК»"
            >
              <Icon name="upload" />
              {xlsxMut.isPending ? "Парсю…" : "Загрузить xlsx WB"}
            </button>
          </div>
        }
      />

      <div className="card p-4 flex flex-wrap items-center gap-4">
        <label className="text-sm">
          Неделя (пн):{" "}
          <input
            type="date"
            className="input ml-2"
            value={weekStart}
            onChange={(e) => setWeekStart(e.target.value)}
          />
        </label>
        {data && (
          <div className="text-sm text-muted">
            Период: <b>{data.week_start}</b> .. <b>{data.week_end}</b>
            {" · "}
            Реализаций: <b>{data.realization_ids.length}</b>
            {data.realization_ids.length > 0 && (
              <span className="text-faint">
                {" "}
                ({data.realization_ids.join(", ")})
              </span>
            )}
            {" · "}
            Строк: <b>{data.rows_count.toLocaleString("ru-RU")}</b>
            {" · "}
            Scope: <b>{data.scope}</b>
          </div>
        )}
        <button
          className="btn-secondary text-xs ml-auto"
          onClick={() => setWbValues({})}
          disabled={Object.keys(wbValues).length === 0}
          title="Очистить ручной ввод"
        >
          Сбросить «WB ЛК»
        </button>
      </div>

      {q.isLoading && (
        <div className="card p-8 text-center text-muted">Загружаю…</div>
      )}
      {q.isError && (
        <div className="card p-8 text-center text-danger">
          Ошибка: {String((q.error as any)?.message ?? "")}
        </div>
      )}

      {data && data.metrics.length === 0 && (
        <div className="card p-8 text-center text-muted">
          Нет данных за выбранную неделю. Проверь что sync `report_detail` отработал
          — в /settings → sync-checkpoints.
        </div>
      )}

      {grouped.map(([groupKey, metrics]) => (
        <div key={groupKey} className="card overflow-hidden">
          <div className="px-4 py-2 border-b border-soft bg-soft/30">
            <h3 className="font-medium">{data!.groups[groupKey] ?? groupKey}</h3>
          </div>
          <table className="w-full text-sm">
            <thead className="text-left text-muted">
              <tr>
                <th className="px-3 py-2 w-10">#</th>
                <th className="px-3 py-2">Метрика</th>
                <th className="px-3 py-2 text-right">Наша БД (РНП)</th>
                <th className="px-3 py-2 text-right">WB ЛК</th>
                <th className="px-3 py-2 text-right w-32">Δ</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => {
                const wbInput = wbValues[m.rule_number];
                const wbNum =
                  wbInput !== undefined && wbInput !== ""
                    ? Number(wbInput.replace(",", ".").replace(/\s/g, ""))
                    : null;
                const di = deltaInfo(m.our_value, wbNum, !!m.is_count);
                const badge = STATUS_BADGE[m.status] ?? STATUS_BADGE.ok;
                return (
                  <tr
                    key={m.rule_number}
                    className="border-t border-soft hover:bg-soft/40"
                  >
                    <td className="px-3 py-2 text-muted font-mono">
                      {m.rule_number}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span className={badge.tone} title={badge.tooltip}>
                          <Icon name={badge.icon as any} size={12} />
                        </span>
                        <span className="font-medium">{m.name}</span>
                      </div>
                      <div className="text-xs text-muted font-mono mt-0.5">
                        {m.formula}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {fmtMoney(m.our_value, m.is_count)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <input
                        type="text"
                        inputMode="decimal"
                        className="input text-right font-mono w-32"
                        value={wbInput ?? ""}
                        onChange={(e) =>
                          setWbValues((p) => ({
                            ...p,
                            [m.rule_number]: e.target.value,
                          }))
                        }
                        placeholder="—"
                      />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span
                        className={`px-2 py-0.5 rounded font-mono text-xs ${TONE_BG[di.tone]}`}
                      >
                        {di.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}

      <div className="text-xs text-muted">
        Маппинги полей (vipryn 2026-05-26):{" "}
        <code>commission_percent</code> = «Размер кВВ, %» (правило 14);{" "}
        <code>retail_amount</code> = «Вайлдберриз реализовал Товар (Пр)» (правило
        15); эквайринг — split sale−return (правило 16). Прочие удержания
        (правило 8) и Компенсации (правило 17) — пока raw, см.{" "}
        <a href="/docs/RECON_GUIDE" className="text-accent hover:underline">
          RECON_GUIDE
        </a>
        .
      </div>
    </div>
  );
}
