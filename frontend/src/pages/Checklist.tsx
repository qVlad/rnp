/**
 * Чек-лист (10X-методика).
 *
 * Сводный режим — таблица всех SKU с количеством красных/жёлтых правил,
 * сортировка «сначала проблемные». Клик по строке → детали по SKU
 * (правила + рекомендуемые действия).
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";

type Status = "red" | "yellow" | "green" | "ok";

const STATUS_COLORS: Record<Status, string> = {
  red: "text-danger",
  yellow: "text-warn",
  green: "text-success",
  ok: "text-muted",
};

const STATUS_BG: Record<Status, string> = {
  red: "bg-danger/15 border-danger/40",
  yellow: "bg-warn/15 border-warn/40",
  green: "bg-success/15 border-success/40",
  ok: "bg-surface-2/50 border-border",
};

export default function Checklist() {
  const [days, setDays] = useState(30);
  const [filter, setFilter] = useState("");
  const [selectedNm, setSelectedNm] = useState<number | null>(null);

  const summary = useQuery({
    queryKey: ["checklist-summary", days],
    queryFn: () => api.checklistSummary(days),
  });

  const detail = useQuery({
    queryKey: ["checklist-sku", selectedNm, days],
    queryFn: () => api.checklistSku(selectedNm!, days),
    enabled: selectedNm != null,
  });

  const items = summary.data?.items ?? [];
  const filtered = filter
    ? items.filter(
        (i: any) =>
          String(i.nm_id).includes(filter) ||
          (i.vendor_code ?? "").toLowerCase().includes(filter.toLowerCase()) ||
          (i.brand ?? "").toLowerCase().includes(filter.toLowerCase()),
      )
    : items;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold">Чек-лист SKU</h1>
          <div className="text-xs text-muted mt-1">
            Готовый to-do list по каждому товару — что не так и что сделать.
          </div>
        </div>
        <div className="flex items-end gap-3 flex-wrap">
          <label className="flex flex-col text-xs text-muted">
            Период (дней)
            <select
              className="bg-surface border border-border rounded-md p-1.5 text-sm text-white"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
            >
              <option value={7}>7</option>
              <option value={14}>14</option>
              <option value={30}>30</option>
              <option value={60}>60</option>
              <option value={90}>90</option>
            </select>
          </label>
          <input
            placeholder="Поиск по nmId / артикулу / бренду"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="bg-surface border border-border rounded-md p-1.5 text-sm w-72"
          />
        </div>
      </div>

      {summary.data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KpiBox
            label="Всего SKU"
            value={summary.data.total_skus}
            tone="ok"
          />
          <KpiBox
            label="Красных"
            value={summary.data.red_skus}
            tone={summary.data.red_skus > 0 ? "red" : "green"}
          />
          <KpiBox
            label="Жёлтых"
            value={summary.data.yellow_skus}
            tone={summary.data.yellow_skus > 0 ? "yellow" : "green"}
          />
          <KpiBox
            label="Зелёных (всё ок)"
            value={summary.data.green_skus}
            tone="green"
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_minmax(0,560px)] gap-4">
        {/* Левая колонка — таблица SKU */}
        <section className="card overflow-x-auto">
          {summary.isLoading && <div className="text-muted text-sm">Загрузка…</div>}
          {summary.data && filtered.length === 0 && (
            <div className="text-muted text-sm">SKU не найдены.</div>
          )}
          {filtered.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted text-xs uppercase">
                  <th className="text-left p-2 sticky left-0 bg-surface">nmId / Артикул</th>
                  <th className="text-right p-2">🔴</th>
                  <th className="text-right p-2">🟡</th>
                  <th className="text-right p-2">Выручка</th>
                  <th className="text-right p-2">Маржа/ед</th>
                  <th className="text-right p-2">Дн. до 0</th>
                  <th className="text-left p-2">Топ-проблемы</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((it: any) => {
                  const sel = it.nm_id === selectedNm;
                  return (
                    <tr
                      key={it.nm_id}
                      onClick={() => setSelectedNm(it.nm_id)}
                      className={`border-t border-border cursor-pointer hover:bg-surface-2/50 ${
                        sel ? "bg-accent/10" : ""
                      }`}
                    >
                      <td className="p-2 sticky left-0 bg-surface">
                        <div className="font-mono">{it.nm_id}</div>
                        <div className="text-xs text-muted">
                          {it.vendor_code ?? ""}{" "}
                          {it.brand && (
                            <span className="text-accent">· {it.brand}</span>
                          )}
                        </div>
                      </td>
                      <td className="p-2 text-right text-danger font-medium">
                        {it.counts.red || ""}
                      </td>
                      <td className="p-2 text-right text-warn font-medium">
                        {it.counts.yellow || ""}
                      </td>
                      <td className="p-2 text-right font-mono">
                        {fmtRub(it.summary.rd_revenue)}
                      </td>
                      <td
                        className={`p-2 text-right font-mono ${
                          it.summary.margin_per_unit < 0 ? "text-danger" : ""
                        }`}
                      >
                        {fmtRub(it.summary.margin_per_unit)}
                      </td>
                      <td
                        className={`p-2 text-right ${
                          it.summary.days_to_stockout != null &&
                          it.summary.days_to_stockout < 14
                            ? "text-danger font-medium"
                            : "text-muted"
                        }`}
                      >
                        {it.summary.days_to_stockout != null
                          ? `${it.summary.days_to_stockout.toFixed(0)}`
                          : "—"}
                      </td>
                      <td className="p-2 text-xs">
                        {it.top_issues.length === 0 ? (
                          <span className="text-success">всё ок</span>
                        ) : (
                          it.top_issues.map((p: any) => (
                            <span
                              key={p.rule_id}
                              className={`inline-block mr-2 ${STATUS_COLORS[p.status as Status]}`}
                              title={p.label}
                            >
                              ● {p.label}
                            </span>
                          ))
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>

        {/* Правая колонка — детали выбранной SKU */}
        <section className="card">
          {selectedNm == null && (
            <div className="text-muted text-sm">
              Кликни на SKU слева, чтобы увидеть полный чек-лист с правилами и
              рекомендуемыми действиями.
            </div>
          )}
          {detail.isLoading && (
            <div className="text-muted text-sm">Загрузка чек-листа…</div>
          )}
          {detail.data && (
            <div className="flex flex-col gap-3">
              <div>
                <div className="text-xs text-muted">SKU</div>
                <div className="text-lg font-semibold font-mono">
                  {detail.data.nm_id}
                </div>
                <div className="text-sm text-muted">
                  {detail.data.vendor_code ?? "—"}{" "}
                  {detail.data.brand && (
                    <span className="text-accent">· {detail.data.brand}</span>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs">
                <Mini label="Выручка" value={fmtRub(detail.data.summary.rd_revenue)} />
                <Mini label="Выкуп" value={`${detail.data.summary.buyout_pct}%`} />
                <Mini
                  label="Возвраты"
                  value={`${detail.data.summary.return_pct}%`}
                />
                <Mini label="ДРР" value={`${detail.data.summary.drr_pct}%`} />
                <Mini
                  label="Маржа на ед"
                  value={fmtRub(detail.data.summary.margin_per_unit)}
                />
                <Mini
                  label="Остаток"
                  value={`${detail.data.summary.stock_qty}`}
                />
              </div>

              <div className="flex flex-col gap-2">
                {detail.data.checks.map((c: any) => (
                  <div
                    key={c.rule_id}
                    className={`rounded-md border p-3 ${STATUS_BG[c.status as Status]}`}
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <div className={`font-medium ${STATUS_COLORS[c.status as Status]}`}>
                        {c.status === "red"
                          ? "🔴"
                          : c.status === "yellow"
                            ? "🟡"
                            : "🟢"}{" "}
                        {c.label}
                      </div>
                      <div className="text-xs text-muted">{c.detail}</div>
                    </div>
                    {c.action && (
                      <div className="text-sm text-white mt-1">→ {c.action}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function KpiBox({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "ok" | "red" | "yellow" | "green";
}) {
  const color =
    tone === "red"
      ? "text-danger"
      : tone === "yellow"
        ? "text-warn"
        : tone === "green"
          ? "text-success"
          : "text-white";
  return (
    <div className="card flex flex-col">
      <div className="text-xs text-muted uppercase">{label}</div>
      <div className={`text-2xl font-semibold ${color}`}>{value}</div>
    </div>
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
