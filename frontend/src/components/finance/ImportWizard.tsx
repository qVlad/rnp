/**
 * Мастер импорта банковской выписки (DEV-093): файл → авто-детект формата
 * (1С 1CClientBankExchange / Excel / CSV) → [маппинг колонок] → счёт →
 * превью → импорт. Дедуп на сервере: повторная загрузка того же файла
 * не создаёт дублей.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type FinanceImportRow } from "@/api/client";
import { fmtRub } from "@/lib/format";

const FIELD_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "— не импортировать —" },
  { value: "op_date", label: "Дата" },
  { value: "op_kind", label: "Тип (Доход/Расход)" },
  { value: "amount", label: "Сумма" },
  { value: "account_name", label: "Счёт" },
  { value: "article_name", label: "Статья" },
  { value: "counterparty", label: "Контрагент" },
  { value: "raw_description", label: "Назначение платежа" },
  { value: "doc_number", label: "№ документа" },
];

export default function ImportWizard({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const qc = useQueryClient();
  const [batch, setBatch] = useState<{
    batch_id: number; status: string; detected_format: string;
    columns: string[]; mapping_suggest: Record<string, string>;
    rows_total: number; preview: FinanceImportRow[]; our_accounts: string[];
  } | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [accountId, setAccountId] = useState<number | "">("");
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<{ imported: number; skipped_duplicates: number; rules_applied: number } | null>(null);

  const accountsQ = useQuery({ queryKey: ["finance-accounts"], queryFn: () => api.financeAccounts() });
  const accounts = (accountsQ.data?.items ?? []).filter((a) => !a.archived);

  const upload = useMutation({
    mutationFn: (file: File) => api.financeImportUpload(file),
    onSuccess: (d) => { setBatch(d); setMapping(d.mapping_suggest || {}); setErr(null); },
    onError: (e: any) => setErr(String(e.message || "")),
  });
  const commit = useMutation({
    mutationFn: () =>
      api.financeImportCommit(batch!.batch_id, {
        account_id: Number(accountId),
        ...(batch!.status === "needs_mapping" ? { mapping } : {}),
      }),
    onSuccess: (d) => {
      setResult(d);
      qc.invalidateQueries({ queryKey: ["manual-ops"] });
      qc.invalidateQueries({ queryKey: ["cf-matrix"] });
      qc.invalidateQueries({ queryKey: ["finance-accounts"] });
      qc.invalidateQueries({ queryKey: ["finance-imports"] });
    },
    onError: (e: any) => setErr(String(e.message || "")),
  });

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="card w-full max-w-2xl max-h-[90vh] overflow-auto">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-medium">Импорт банковской выписки</h3>
          <button className="text-muted hover:text-fg" onClick={onClose}>✕</button>
        </div>

        {result ? (
          <div className="flex flex-col gap-3">
            <div className="text-sm">
              ✓ Импортировано операций: <b>{result.imported}</b>
              {result.skipped_duplicates > 0 && (
                <span className="text-muted"> · пропущено дублей: {result.skipped_duplicates}</span>
              )}
              {result.rules_applied > 0 && (
                <span className="text-muted"> · ⚡ автоправила применены к {result.rules_applied}</span>
              )}
            </div>
            <button className="btn btn-primary w-fit" onClick={onDone}>Готово</button>
          </div>
        ) : !batch ? (
          <div className="flex flex-col gap-3">
            <div className="text-sm text-muted">
              Поддерживаются: выписка 1С (файл .txt «1CClientBankExchange» — его выгружает
              любой банк: ТБанк, ВТБ, Сбер…), Excel по{" "}
              <a className="text-accent" href="/api/finance-imports/template.xlsx">нашему шаблону</a>{" "}
              или произвольный Excel/CSV (колонки сопоставите на следующем шаге).
            </div>
            <label className="border-2 border-dashed border-border rounded-lg p-8 text-center cursor-pointer hover:bg-soft/40">
              <input
                type="file"
                className="hidden"
                accept=".txt,.xlsx,.xls,.csv"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) upload.mutate(f);
                }}
              />
              {upload.isPending ? "Загружаю…" : "Выберите файл выписки или перетащите сюда"}
            </label>
            {err && <div className="text-sm text-danger">{err}</div>}
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="text-sm">
              Файл распознан: <b>{batch.detected_format === "1c" ? "выписка 1С" : batch.detected_format}</b>
              {batch.rows_total > 0 && <span className="text-muted"> · строк: {batch.rows_total}</span>}
              {batch.our_accounts.length > 0 && (
                <div className="text-xs text-muted mt-1">Р/с в выписке: {batch.our_accounts.join(", ")}</div>
              )}
            </div>

            {batch.status === "needs_mapping" && (
              <div className="flex flex-col gap-1">
                <div className="text-sm font-medium">Сопоставьте колонки (обязательны Дата и Сумма):</div>
                {batch.columns.map((col) => (
                  <div key={col} className="flex items-center gap-2 text-sm">
                    <span className="w-56 truncate text-muted">{col}</span>
                    <select
                      className="input text-xs flex-1"
                      value={mapping[col] ?? ""}
                      onChange={(e) => setMapping({ ...mapping, [col]: e.target.value })}
                    >
                      {FIELD_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            )}

            <div className="flex items-center gap-2">
              <span className="text-sm">Счёт:</span>
              <select
                className="input text-sm"
                value={accountId}
                onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : "")}
              >
                <option value="">— выберите счёт —</option>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
              {accounts.length === 0 && (
                <span className="text-xs text-danger">Сначала создайте счёт: Финансы → Дополнительно → Счета</span>
              )}
            </div>

            {batch.preview.length > 0 && (
              <div className="overflow-auto max-h-64 border border-border rounded">
                <table className="w-full text-xs">
                  <thead><tr className="text-left text-muted border-b border-border">
                    <th className="p-1.5">Дата</th><th className="p-1.5">Тип</th>
                    <th className="p-1.5 text-right">Сумма</th><th className="p-1.5">Контрагент</th>
                    <th className="p-1.5">Назначение</th>
                  </tr></thead>
                  <tbody>
                    {batch.preview.map((r, i) => (
                      <tr key={i} className="border-b border-border/50">
                        <td className="p-1.5">{r.op_date}</td>
                        <td className="p-1.5">{r.op_kind === "income" ? "Доход" : "Расход"}</td>
                        <td className="p-1.5 text-right font-mono">{fmtRub(r.amount)}</td>
                        <td className="p-1.5 truncate max-w-[140px]">{r.counterparty}</td>
                        <td className="p-1.5 truncate max-w-[240px] text-muted">{r.raw_description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {err && <div className="text-sm text-danger">{err}</div>}
            <div className="flex gap-2">
              <button
                className="btn btn-primary"
                disabled={accountId === "" || commit.isPending}
                onClick={() => { setErr(null); commit.mutate(); }}
              >
                {commit.isPending ? "Импортирую…" : "Импортировать"}
              </button>
              <button className="btn" onClick={() => { setBatch(null); setErr(null); }}>← Другой файл</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
