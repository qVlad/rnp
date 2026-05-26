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
import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  indicative: boolean = false,
): { delta: number | null; tone: DeltaTone; label: string } {
  if (wb === null || isNaN(wb)) {
    return { delta: null, tone: "none", label: "—" };
  }
  const d = our - wb;
  const abs = Math.abs(d);
  // Индикативные метрики (заказы из Воронки) — Δ нейтральная (не красная),
  // т.к. расхождение с supplier/orders API ожидаемо.
  if (indicative) {
    if (abs < 1) return { delta: d, tone: "ok", label: isCount ? "0" : "≈0" };
    return {
      delta: d,
      tone: "none",
      label: (d > 0 ? "+" : "") + (isCount ? String(d) : fmtMoney(d)),
    };
  }
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
  const qc = useQueryClient();
  const [weekStart, setWeekStart] = useState(lastClosedWeekStart);
  const [wbValues, setWbValues] = useState<Record<number, string>>({}); // user input by rule_number
  const fileRef = useRef<HTMLInputElement>(null);

  const q = useQuery({
    queryKey: ["reconciliation-auto", weekStart],
    queryFn: () => api.reconciliationAuto(weekStart),
  });

  // TASK-LEAD-138: при смене недели — если extension загрузил данные за эту
  // неделю, автозаполняем колонку «WB ЛК». User'ский ввод не перетираем
  // (если он уже что-то набил вручную) — поэтому проверяем что wbValues
  // пуст для соответствующих правил.
  useEffect(() => {
    // Объединяем метрики отчёта реализации (1-8,12-17) и extra (9,10,11
    // реклама/заказы) — обе автозаполняют WB-колонку.
    const fromReport = q.data?.extension_upload?.metrics_by_rule ?? {};
    const fromExtra = q.data?.extension_extra?.metrics_by_rule ?? {};
    const merged = { ...fromReport, ...fromExtra };
    if (Object.keys(merged).length === 0) return;
    setWbValues((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const [k, v] of Object.entries(merged)) {
        const rn = Number(k);
        if (!(rn in next) || next[rn] === "" || next[rn] === undefined) {
          next[rn] = String(v);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    // Дозаполняем при любом изменении агрегата (uploaded_at + состав отчётов
    // + сами метрики), а не только uploaded_at — иначе после setWbValues({})
    // колонка могла остаться пустой если uploaded_at не сменился.
  }, [
    q.data?.extension_upload?.uploaded_at,
    q.data?.extension_upload?.report_ids?.join(","),
    JSON.stringify(q.data?.extension_upload?.metrics_by_rule ?? {}),
    q.data?.extension_extra?.uploaded_at,
    JSON.stringify(q.data?.extension_extra?.metrics_by_rule ?? {}),
  ]);

  const xlsxMut = useMutation({
    mutationFn: (file: File) => api.reconciliationAutoUploadXlsx(file),
    onSuccess: (data) => {
      if (data.stored) {
        // Сохранено per-report → агрегат обновится через рефетч GET.
        // wbValues очищаем чтобы useEffect пере-заполнил из агрегата.
        setWbValues({});
        qc.invalidateQueries({ queryKey: ["reconciliation-auto"] });
      } else {
        // Не удалось определить report_id (нестандартное имя файла) —
        // fallback: пишем напрямую в колонку.
        const next: Record<number, string> = {};
        for (const [k, v] of Object.entries(data.metrics_by_rule)) {
          next[Number(k)] = String(v);
        }
        setWbValues(next);
      }
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

  // TASK-LEAD-138: предупреждение о несовпадении кабинета. Extension source_url
  // содержит /report/{realization_id}. Если этот id НЕ среди realization_ids
  // нашей БД за эту неделю — значит в ЛК WB открыт отчёт ДРУГОГО юрлица.
  const cabinetMismatch = useMemo(() => {
    const upload = data?.extension_upload;
    if (!upload?.report_ids?.length || !data) return null;
    if (data.realization_ids.length === 0) return null;
    // Несовпадение: ни один загруженный отчёт не входит в наши realization_ids.
    const anyMatch = upload.report_ids.some((id) =>
      data.realization_ids.includes(id),
    );
    if (anyMatch) return null;
    return {
      extReportIds: upload.report_ids,
      ourIds: data.realization_ids,
    };
  }, [data?.extension_upload?.report_ids, data?.realization_ids]);

  // Какие отчёты недели ещё НЕ загружены через extension (для подсказки).
  const missingReports = useMemo(() => {
    const upload = data?.extension_upload;
    if (!data || data.realization_ids.length <= 1) return [];
    const loaded = new Set(upload?.report_ids ?? []);
    return data.realization_ids.filter((id) => !loaded.has(id));
  }, [data?.extension_upload?.report_ids, data?.realization_ids]);

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
              accept=".xlsx,.zip"
              hidden
              onChange={onFile}
            />
            <button
              className="btn"
              onClick={onPick}
              disabled={xlsxMut.isPending}
              title="Загрузить отчёт WB (xlsx или zip из кнопки «Скачать») — автозаполнит колонку «WB ЛК»"
            >
              <Icon name="upload" />
              {xlsxMut.isPending ? "Парсю…" : "Загрузить xlsx/zip WB"}
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
            {data.extension_upload && (
              <span className="ml-3 text-success">
                📡 Через расширение:{" "}
                {data.extension_upload.reports_count} отчёт(ов) (№
                {data.extension_upload.report_ids.join(", №")}),{" "}
                {data.extension_upload.rows_count.toLocaleString("ru-RU")} строк
              </span>
            )}
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

      {cabinetMismatch && (
        <div className="card p-4 border border-danger/40 bg-danger/10">
          <div className="flex items-start gap-2">
            <span className="text-danger text-lg">⚠️</span>
            <div className="text-sm">
              <b className="text-danger">Несовпадение кабинета.</b> Расширение
              загрузило отчёт(ы) <b>№{cabinetMismatch.extReportIds.join(", №")}</b>{" "}
              из ЛК WB, но в данных РНП за эту неделю —{" "}
              <b>№{cabinetMismatch.ourIds.join(", №")}</b>. Это разные
              WB-кабинеты/юрлица — сверка будет некорректной.
              <div className="text-muted mt-1">
                Открой в ЛК WB отчёт того кабинета, чей токен подключён к РНП,
                либо переключи активный кабинет в РНП.
              </div>
            </div>
          </div>
        </div>
      )}

      {missingReports.length > 0 && (
        <div className="card p-3 border border-warn/40 bg-warn/10 text-sm">
          <span className="text-warn">⚠️ Загружены не все отчёты недели.</span>{" "}
          В РНП за эту неделю {data!.realization_ids.length} отчёта, через
          расширение загружено{" "}
          {data!.extension_upload?.reports_count ?? 0}. Не хватает: №
          {missingReports.join(", №")}. Открой их в ЛК WB (Финансы → Отчёт
          реализации) — WB-колонка досуммируется и Δ сойдётся.
        </div>
      )}

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
                const meta = m.meta;
                const wbInput = wbValues[m.rule_number];
                const wbNum =
                  wbInput !== undefined && wbInput !== ""
                    ? Number(wbInput.replace(",", ".").replace(/\s/g, ""))
                    : null;
                const di = deltaInfo(
                  m.our_value,
                  wbNum,
                  !!m.is_count,
                  m.status === "indicative",
                );
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
                      {meta?.excluded_by_keyword &&
                        Object.keys(meta.excluded_by_keyword).length > 0 && (
                          <details className="text-xs mt-1 text-muted">
                            <summary className="cursor-pointer">
                              📋 По TS чистые прочие:{" "}
                              {fmtMoney(meta.ts_clean ?? 0)} ₽ (исключено{" "}
                              {fmtMoney(meta.excluded_total ?? 0)} ₽ из{" "}
                              {fmtMoney(meta.raw_total ?? 0)} ₽)
                            </summary>
                            <ul className="pl-4 list-disc">
                              {Object.entries(meta.excluded_by_keyword)
                                .sort((a, b) => b[1] - a[1])
                                .map(([kw, sum]) => (
                                  <li key={kw}>
                                    «{kw}»: {fmtMoney(sum)} ₽
                                  </li>
                                ))}
                            </ul>
                          </details>
                        )}
                      {meta?.stage1 !== undefined && (
                        <details className="text-xs mt-1 text-muted">
                          <summary className="cursor-pointer">
                            📋 3 этапа TS
                          </summary>
                          <ul className="pl-4 list-disc">
                            <li>Stage 1 (база): {fmtMoney(meta.stage1)} ₽</li>
                            <li>
                              Stage 2 (sale):{" "}
                              {fmtMoney(meta.stage2_sale ?? 0)} ₽
                            </li>
                            <li>
                              Stage 3 (return, −):{" "}
                              {fmtMoney(meta.stage3_return ?? 0)} ₽
                            </li>
                          </ul>
                        </details>
                      )}
                      {meta?.wb_source && (
                        <div className="text-xs text-muted mt-1">
                          📡 Авто из расширения (открой в ЛК WB:{" "}
                          {meta.wb_source}) или введи вручную →
                        </div>
                      )}
                      {meta?.indicative_note && (
                        <div className="text-xs text-faint mt-1 italic">
                          ℹ️ {meta.indicative_note}
                        </div>
                      )}
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
