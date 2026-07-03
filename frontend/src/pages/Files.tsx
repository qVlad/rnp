/**
 * Файлы (DEV-094, как TS «Файлы») — единый журнал импортов/файлов из всех
 * модулей: банковские выписки (вкл. email-приём), аудит-режим, сверки.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/api/client";
import PageHeader from "@/components/PageHeader";
import { fmtNum } from "@/lib/format";

export default function Files() {
  const q = useQuery({ queryKey: ["files"], queryFn: () => api.filesList() });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Файлы"
        subtitle="Журнал загруженных файлов по всем модулям: банковские выписки (вкл. присланные на email), аудит-режим, сверки."
      />
      <div className="card overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted border-b border-border">
              <th className="p-2">Дата</th><th className="p-2">Тип</th><th className="p-2">Файл</th>
              <th className="p-2">Статус</th><th className="p-2">Комментарий</th>
              <th className="p-2 text-right">Строк</th><th className="p-2">Кто</th>
            </tr>
          </thead>
          <tbody>
            {(q.data?.items ?? []).map((f, i) => (
              <tr key={i} className="border-b border-border/50 hover:bg-soft/40">
                <td className="p-2 whitespace-nowrap">{f.created_at ? new Date(f.created_at).toLocaleString("ru") : ""}</td>
                <td className="p-2"><Link className="text-accent hover:underline" to={f.page}>{f.kind}</Link></td>
                <td className="p-2 max-w-[300px] truncate" title={f.filename ?? ""}>{f.filename}</td>
                <td className={`p-2 ${f.is_error ? "text-danger" : "text-success"}`}>{f.status}</td>
                <td className="p-2 max-w-[320px] truncate text-muted" title={f.comment ?? ""}>{f.comment}</td>
                <td className="p-2 text-right">{f.rows != null ? fmtNum(f.rows) : "—"}</td>
                <td className="p-2 text-muted">{f.by}</td>
              </tr>
            ))}
            {q.data && q.data.items.length === 0 && (
              <tr><td colSpan={7} className="p-4 text-center text-muted">Файлов ещё не было.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
