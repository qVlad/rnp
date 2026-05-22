import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";
import { Icon } from "../components/Icon";
import PageHeader from "@/components/PageHeader";

// Хелпер: первый день месяца / последний день месяца — для periods picker'а
const firstOfMonth = (d: Date) =>
  new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
const lastOfMonth = (d: Date) =>
  new Date(d.getFullYear(), d.getMonth() + 1, 0).toISOString().slice(0, 10);

const today = new Date();
const defaultMonth = new Date(today.getFullYear(), today.getMonth() - 1, 1); // прошлый месяц

const SOURCE_LABEL: Record<string, string> = {
  ours: "Наш",
  wb_cabinet: "WB",
  bookkeeper: "Бух.",
};

export default function Audit() {
  const qc = useQueryClient();
  const [periodStart, setPeriodStart] = useState(firstOfMonth(defaultMonth));
  const [periodEnd, setPeriodEnd] = useState(lastOfMonth(defaultMonth));
  const [bkPreview, setBkPreview] = useState<any | null>(null);
  const [bkFile, setBkFile] = useState<File | null>(null);

  const wbInputRef = useRef<HTMLInputElement | null>(null);
  const bkInputRef = useRef<HTMLInputElement | null>(null);

  const importsQ = useQuery({
    queryKey: ["audit-imports", periodStart, periodEnd],
    queryFn: () => api.auditListImports(periodStart, periodEnd),
  });
  const compareQ = useQuery({
    queryKey: ["audit-compare", periodStart, periodEnd],
    queryFn: () => api.auditCompare(periodStart, periodEnd),
  });

  const wbUploadMut = useMutation({
    mutationFn: (file: File) =>
      api.auditCreateImport(file, "wb_cabinet", periodStart, periodEnd),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["audit-imports"] });
      qc.invalidateQueries({ queryKey: ["audit-compare"] });
    },
  });

  const bkUploadMut = useMutation({
    mutationFn: ({ file, mapping }: { file: File; mapping: Record<string, any> }) =>
      api.auditCreateImport(file, "bookkeeper", periodStart, periodEnd, mapping),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["audit-imports"] });
      qc.invalidateQueries({ queryKey: ["audit-compare"] });
      setBkPreview(null);
      setBkFile(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.auditDeleteImport(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["audit-imports"] });
      qc.invalidateQueries({ queryKey: ["audit-compare"] });
    },
  });

  const decisionMut = useMutation({
    mutationFn: api.auditCreateDecision,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["audit-decisions"] });
    },
  });

  const onWbFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    await wbUploadMut.mutateAsync(f);
    if (wbInputRef.current) wbInputRef.current.value = "";
  };

  const onBkFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setBkFile(f);
    try {
      const preview = await api.auditPreviewBookkeeper(f);
      setBkPreview(preview);
    } catch (err: any) {
      alert(`Не удалось прочитать файл: ${err.message || err}`);
      setBkFile(null);
    }
    if (bkInputRef.current) bkInputRef.current.value = "";
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Аудит-режим — сверка трёх источников"
        actions={
          <div className="flex items-end gap-3">
            <label className="flex flex-col text-xs text-muted">
              Период с
              <input
                type="date"
                value={periodStart}
                onChange={(e: any) => setPeriodStart(e.target.value)}
                className="input"
              />
            </label>
            <label className="flex flex-col text-xs text-muted">
              По
              <input
                type="date"
                value={periodEnd}
                onChange={(e: any) => setPeriodEnd(e.target.value)}
                className="input"
              />
            </label>
          </div>
        }
      />

      <div className="card text-xs text-muted leading-relaxed">
        Сравнивает 3 источника: наш P&L (расчёт), WB-кабинет (загруженный XLSX
        «Реализация») и бухгалтер (загруженный XLSX с настраиваемым маппингом
        колонок). Строки с расхождением Δ &gt; 0.01₽ подсвечиваются — можно
        зафиксировать решение «принять одну из версий», запись попадает в
        audit-log.
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* WB upload */}
        <div className="card">
          <div className="text-sm font-medium mb-2">WB-кабинет</div>
          {importsQ.data?.wb_cabinet ? (
            <div className="flex flex-col gap-2 text-xs">
              <div>
                <span className="text-muted">Файл:</span>{" "}
                <span className="font-mono">
                  {importsQ.data.wb_cabinet.file_name}
                </span>
              </div>
              <div>
                <span className="text-muted">Загружено:</span>{" "}
                {importsQ.data.wb_cabinet.imported_by} ·{" "}
                {importsQ.data.wb_cabinet.imported_at?.slice(0, 19)}
              </div>
              <div>
                <span className="text-muted">Строк обработано:</span>{" "}
                {importsQ.data.wb_cabinet.rows_count}
              </div>
              <div className="flex gap-2 mt-1">
                <button
                  className="btn text-xs"
                  onClick={() => wbInputRef.current?.click()}
                >
                  Заменить
                </button>
                <button
                  className="btn text-xs text-danger"
                  onClick={() =>
                    deleteMut.mutate(importsQ.data!.wb_cabinet!.id)
                  }
                >
                  Удалить
                </button>
              </div>
            </div>
          ) : (
            <div>
              <button
                className="btn text-xs"
                onClick={() => wbInputRef.current?.click()}
                disabled={wbUploadMut.isPending}
              >
                {wbUploadMut.isPending
                  ? "Загружаю…"
                  : "+ Загрузить WB XLSX «Реализация»"}
              </button>
              <div className="text-[11px] text-muted mt-1">
                ЛК WB → Финансы → Финансовые отчёты → «Реализация в excel»
              </div>
            </div>
          )}
          <input
            ref={wbInputRef}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={onWbFile}
          />
        </div>

        {/* Bookkeeper upload */}
        <div className="card">
          <div className="text-sm font-medium mb-2">Бухгалтер</div>
          {importsQ.data?.bookkeeper && !bkPreview ? (
            <div className="flex flex-col gap-2 text-xs">
              <div>
                <span className="text-muted">Файл:</span>{" "}
                <span className="font-mono">
                  {importsQ.data.bookkeeper.file_name}
                </span>
              </div>
              <div>
                <span className="text-muted">Загружено:</span>{" "}
                {importsQ.data.bookkeeper.imported_by} ·{" "}
                {importsQ.data.bookkeeper.imported_at?.slice(0, 19)}
              </div>
              <div>
                <span className="text-muted">Строк обработано:</span>{" "}
                {importsQ.data.bookkeeper.rows_count}
              </div>
              <div className="flex gap-2 mt-1">
                <button
                  className="btn text-xs"
                  onClick={() => bkInputRef.current?.click()}
                >
                  Заменить
                </button>
                <button
                  className="btn text-xs text-danger"
                  onClick={() =>
                    deleteMut.mutate(importsQ.data!.bookkeeper!.id)
                  }
                >
                  Удалить
                </button>
              </div>
            </div>
          ) : (
            <div>
              <button
                className="btn text-xs"
                onClick={() => bkInputRef.current?.click()}
                disabled={bkUploadMut.isPending}
              >
                {bkUploadMut.isPending
                  ? "Загружаю…"
                  : "+ Загрузить XLSX от бухгалтера"}
              </button>
              <div className="text-[11px] text-muted mt-1">
                Любой формат — wizard поможет сопоставить колонки
              </div>
            </div>
          )}
          <input
            ref={bkInputRef}
            type="file"
            accept=".xlsx"
            className="hidden"
            onChange={onBkFile}
          />
        </div>
      </div>

      {/* Bookkeeper mapping wizard */}
      {bkPreview && bkFile && (
        <BookkeeperMappingWizard
          preview={bkPreview}
          onCancel={() => {
            setBkPreview(null);
            setBkFile(null);
          }}
          onSubmit={(mapping) => bkUploadMut.mutateAsync({ file: bkFile, mapping })}
        />
      )}

      {/* Compare table */}
      {compareQ.data && (
        <div className="card">
          <div className="flex items-baseline justify-between mb-3">
            <h2 className="font-medium">Сравнение по строкам ОПиУ</h2>
            <div className="text-xs text-muted">
              Расхождений: {compareQ.data.discrepancy_count} · WB:{" "}
              {compareQ.data.source_status.wb_cabinet ? "✓" : "—"} · Бух:{" "}
              {compareQ.data.source_status.bookkeeper ? "✓" : "—"}
            </div>
          </div>
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr className="border-b border-border">
                <th className="text-left p-2">Строка</th>
                <th className="text-right p-2">Наш</th>
                <th className="text-right p-2">WB</th>
                <th className="text-right p-2">Бух.</th>
                <th className="text-center p-2 w-12"></th>
                <th className="text-center p-2"></th>
              </tr>
            </thead>
            <tbody>
              {compareQ.data.rows.map((r) => (
                <tr
                  key={r.code}
                  className={`border-t border-border ${
                    r.has_discrepancy ? "bg-danger-subtle" : ""
                  }`}
                >
                  <td className="p-2">{r.label}</td>
                  <td className="p-2 text-right font-mono">{fmtRub(r.ours ?? 0)}</td>
                  <td className="p-2 text-right font-mono text-muted">
                    {r.wb !== null ? fmtRub(r.wb) : "—"}
                  </td>
                  <td className="p-2 text-right font-mono text-muted">
                    {r.bk !== null ? fmtRub(r.bk) : "—"}
                  </td>
                  <td className="p-2 text-center">
                    {r.has_discrepancy ? (
                      <span title="расхождение > 0.01₽" className="text-danger">
                        <Icon name="warning" size={12} />
                      </span>
                    ) : r.ours !== null ? (
                      <span className="text-success" title="сходится">
                        <Icon name="check" size={12} />
                      </span>
                    ) : (
                      ""
                    )}
                  </td>
                  <td className="p-2 text-right">
                    {r.has_discrepancy && (
                      <div className="flex gap-1 justify-end">
                        {(["ours", "wb_cabinet", "bookkeeper"] as const).map((src) => {
                          const value =
                            src === "ours" ? r.ours : src === "wb_cabinet" ? r.wb : r.bk;
                          if (value === null) return null;
                          return (
                            <button
                              key={src}
                              className="btn text-[10px] px-1.5 py-0.5"
                              onClick={() =>
                                decisionMut.mutate({
                                  period_start: periodStart,
                                  period_end: periodEnd,
                                  line_code: r.code,
                                  chosen_source: src,
                                  delta_ours_wb: r.delta_ours_wb,
                                  delta_ours_bk: r.delta_ours_bk,
                                })
                              }
                              title={`Принять ${SOURCE_LABEL[src]}: ${fmtRub(value)}`}
                            >
                              {SOURCE_LABEL[src]}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Bookkeeper mapping wizard ───
function BookkeeperMappingWizard({
  preview,
  onCancel,
  onSubmit,
}: {
  preview: { sheets: Array<{ name: string; suggested_header_row: number; header: string[]; preview_rows: string[][] }> };
  onCancel: () => void;
  onSubmit: (mapping: Record<string, any>) => Promise<any>;
}) {
  const qc = useQueryClient();
  const [sheetIdx, setSheetIdx] = useState(0);
  const sheet = preview.sheets[sheetIdx];
  const [headerRow, setHeaderRow] = useState(sheet.suggested_header_row);
  // map: columnName -> canonical code
  const [colMap, setColMap] = useState<Record<string, string>>({});

  // LEAD-015: загружаемые / сохраняемые шаблоны
  const templatesQ = useQuery({
    queryKey: ["audit-templates"],
    queryFn: () => api.auditListTemplates(),
  });
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | "">("");
  const [saveAsName, setSaveAsName] = useState("");

  const saveTemplateMut = useMutation({
    mutationFn: (mapping: Record<string, any>) =>
      api.auditSaveTemplate(saveAsName.trim(), mapping),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["audit-templates"] });
      alert("Шаблон сохранён.");
      setSaveAsName("");
    },
    onError: (e: any) => alert(`Ошибка: ${e.message}`),
  });

  const deleteTemplateMut = useMutation({
    mutationFn: (id: number) => api.auditDeleteTemplate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["audit-templates"] }),
  });

  const applyTemplate = (id: number | "") => {
    setSelectedTemplateId(id);
    if (!id) return;
    const tpl = templatesQ.data?.items.find((t) => t.id === id);
    if (!tpl) return;
    const m = tpl.mapping_json || {};
    // Найдём соответствующий sheet (по имени) если есть
    if (m.sheet_name) {
      const idx = preview.sheets.findIndex((s) => s.name === m.sheet_name);
      if (idx >= 0) setSheetIdx(idx);
    }
    if (m.header_row) setHeaderRow(Number(m.header_row));
    setColMap((m.column_to_code as Record<string, string>) || {});
  };

  const CANONICAL_CODES = [
    { code: "revenue_gross", label: "Выручка (gross)" },
    { code: "revenue_returns", label: "Возвраты" },
    { code: "revenue_net", label: "Чистая выручка" },
    { code: "commission_wb", label: "Комиссия WB" },
    { code: "delivery_wb", label: "Логистика WB" },
    { code: "storage_wb", label: "Хранение WB" },
    { code: "acquiring", label: "Эквайринг" },
    { code: "penalty", label: "Штрафы" },
    { code: "deduction", label: "Удержания" },
    { code: "ppvz_for_pay", label: "К перечислению" },
    { code: "ad_cost", label: "Реклама" },
    { code: "cogs", label: "Себестоимость" },
    { code: "vat_paid", label: "НДС к уплате" },
    { code: "tax_paid", label: "Налог" },
    { code: "net_profit", label: "Чистая прибыль" },
  ];

  const submit = async () => {
    const column_to_code = Object.fromEntries(
      Object.entries(colMap).filter(([, code]) => code),
    );
    if (Object.keys(column_to_code).length === 0) {
      alert("Сопоставьте хотя бы одну колонку");
      return;
    }
    await onSubmit({
      format: "wide",
      sheet_name: sheet.name,
      header_row: headerRow,
      column_to_code,
    });
  };

  return (
    <div className="card border-l-4 border-accent">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="font-medium">Сопоставление колонок бухгалтерского XLSX</h3>
        <button className="btn text-xs" onClick={onCancel}>
          Отмена
        </button>
      </div>

      {/* LEAD-015: Templates — load existing or save current as new */}
      {(templatesQ.data?.items?.length ?? 0) > 0 && (
        <div className="text-xs mb-2 flex items-center gap-2">
          <span className="text-muted">Шаблон:</span>
          <select
            className="input text-xs"
            value={selectedTemplateId}
            onChange={(e: any) =>
              applyTemplate(e.target.value ? Number(e.target.value) : "")
            }
          >
            <option value="">— настроить вручную —</option>
            {templatesQ.data!.items.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          {selectedTemplateId !== "" && (
            <button
              className="btn text-xs text-danger"
              onClick={() => deleteTemplateMut.mutate(Number(selectedTemplateId))}
              title="Удалить выбранный шаблон"
            >
              <Icon name="close" size={12} />
            </button>
          )}
        </div>
      )}

      {preview.sheets.length > 1 && (
        <div className="text-xs mb-2">
          <span className="text-muted">Лист: </span>
          {preview.sheets.map((s, i) => (
            <button
              key={i}
              className={`btn text-xs mr-1 ${
                i === sheetIdx ? "border-accent text-accent" : ""
              }`}
              onClick={() => setSheetIdx(i)}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}

      <div className="text-xs mb-2">
        <span className="text-muted">Строка с заголовками: </span>
        <input
          type="number"
          min={1}
          max={20}
          value={headerRow}
          onChange={(e: any) => setHeaderRow(Number(e.target.value))}
          className="input w-20 ml-1 inline"
        />
      </div>

      <div className="overflow-x-auto mb-3">
        <table className="text-xs">
          <thead>
            <tr>
              {sheet.header.map((h, i) => (
                <th key={i} className="px-2 py-1 border border-border bg-surface-2">
                  {h || `(пустая)`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sheet.preview_rows.slice(0, 3).map((row, i) => (
              <tr key={i}>
                {row.map((c, j) => (
                  <td
                    key={j}
                    className="px-2 py-1 border border-border text-muted font-mono"
                  >
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
        {sheet.header.map((colName, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="font-mono text-muted flex-1 truncate">
              {colName || `Колонка ${i + 1}`}
            </span>
            <span className="text-muted">→</span>
            <select
              value={colMap[colName] || ""}
              onChange={(e) =>
                setColMap((prev) => ({ ...prev, [colName]: e.target.value }))
              }
              className="input text-xs"
            >
              <option value="">(не использовать)</option>
              {CANONICAL_CODES.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button className="btn border-accent text-accent" onClick={submit}>
          Загрузить с этим маппингом
        </button>
        {/* LEAD-015: сохранить текущий маппинг как шаблон */}
        <input
          type="text"
          className="input text-xs"
          placeholder="Имя шаблона (для сохранения)"
          value={saveAsName}
          onChange={(e: any) => setSaveAsName(e.target.value)}
        />
        <button
          className="btn text-xs"
          onClick={() => {
            const column_to_code = Object.fromEntries(
              Object.entries(colMap).filter(([, code]) => code),
            );
            if (!saveAsName.trim()) {
              alert("Введи имя шаблона");
              return;
            }
            if (Object.keys(column_to_code).length === 0) {
              alert("Сначала сопоставь хотя бы одну колонку");
              return;
            }
            saveTemplateMut.mutate({
              format: "wide",
              sheet_name: sheet.name,
              header_row: headerRow,
              column_to_code,
            });
          }}
          disabled={!saveAsName.trim() || saveTemplateMut.isPending}
          title="Сохранить текущий маппинг чтобы переиспользовать на следующих файлах"
        >
          <Icon name="save" size={12} /> Сохранить шаблон
        </button>
      </div>
    </div>
  );
}
