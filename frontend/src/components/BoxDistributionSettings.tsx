/**
 * BoxDistributionSettings (DEV-091) — секция в /settings:
 * загрузка файла «Распределение», сводка складов и слияние их названий.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

export default function BoxDistributionSettings() {
  const qc = useQueryClient();
  const [info, setInfo] = useState<string | null>(null);
  // mergeInto[canonical] = целевое имя (если задано — слить туда)
  const [mergeInto, setMergeInto] = useState<Record<string, string>>({});

  const whQ = useQuery({
    queryKey: ["box-dist-warehouses"],
    queryFn: api.boxDistWarehouses,
  });

  const uploadMut = useMutation({
    mutationFn: (f: File) => api.boxDistUpload(f),
    onSuccess: (d) => {
      setInfo(
        `✓ Загружено: ${d.boxes} коробов, ${d.rows} строк. Листы: ${d.sheets.join(", ")}.`,
      );
      qc.invalidateQueries({ queryKey: ["box-dist-warehouses"] });
      qc.invalidateQueries({ queryKey: ["box-dist-status"] });
    },
    onError: (e) => setInfo(`Ошибка: ${String((e as Error).message || e)}`),
  });

  const rangesMut = useMutation({
    mutationFn: () =>
      api.boxDistPutWbRanges({
        cities: (whQ.data?.warehouses || []).map((w) => w.warehouse),
        start: 1541505000,
        per_city: 300,
      }),
    onSuccess: () => setInfo("✓ WB-диапазоны зафиксированы (300 на город)"),
    onError: (e) => setInfo(`Ошибка: ${String((e as Error).message || e)}`),
  });

  const aliasMut = useMutation({
    mutationFn: () => {
      // строим карту raw→canonical из текущих слияний
      const aliases: Record<string, string> = { ...(whQ.data?.aliases || {}) };
      for (const w of whQ.data?.warehouses || []) {
        const target = (mergeInto[w.warehouse] || "").trim();
        if (!target || target === w.warehouse) continue;
        for (const raw of w.raw_names) aliases[raw] = target;
      }
      return api.boxDistPutAliases(aliases);
    },
    onSuccess: (d) => {
      setInfo(`✓ Склады объединены, пересчитано строк: ${d.rows_renormalized}`);
      setMergeInto({});
      qc.invalidateQueries({ queryKey: ["box-dist-warehouses"] });
    },
    onError: (e) => setInfo(`Ошибка: ${String((e as Error).message || e)}`),
  });

  const warehouses = whQ.data?.warehouses || [];
  const hasMerges = useMemo(
    () => Object.values(mergeInto).some((v) => v.trim()),
    [mergeInto],
  );

  return (
    <section className="card space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Раскладка коробов (QR-сканер)</h2>
        <Link to="/box-scan" className="text-xs text-accent underline">
          → Открыть сканер
        </Link>
      </div>
      <p className="text-sm text-muted">
        Загрузите файл «Распределение» (.xlsx, листы брендов). Затем на телефоне
        откройте <b>/box-scan</b> и сканируйте QR коробов. Загрузка нового файла
        начинает новую сессию (прошлые WB-короба очищаются).
      </p>

      <div className="flex items-center gap-3 flex-wrap">
        <label className="btn cursor-pointer">
          {uploadMut.isPending ? "Загрузка…" : "Загрузить файл .xlsx"}
          <input
            type="file"
            accept=".xlsx,.xls"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) uploadMut.mutate(f);
              e.target.value = "";
            }}
          />
        </label>
        {info && <span className="text-sm text-muted">{info}</span>}
      </div>

      {warehouses.length > 0 && (
        <div className="mt-2">
          <div className="text-sm font-medium mb-1">
            Склады в файле ({warehouses.length}) — можно объединить
          </div>
          <div className="text-xs text-muted mb-2">
            Если два названия — это один склад, впишите в «Объединить в» общее имя
            (напр. для «Екатеринбург-Перспективная» → «Екатеринбург»).
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-muted text-xs uppercase">
                <tr>
                  <th className="text-left p-1">Склад (канон.)</th>
                  <th className="text-right p-1">Строк</th>
                  <th className="text-left p-1">Исходные названия</th>
                  <th className="text-left p-1">Объединить в</th>
                </tr>
              </thead>
              <tbody>
                {warehouses.map((w) => (
                  <tr key={w.warehouse} className="border-t border-border">
                    <td className="p-1 font-medium">{w.warehouse}</td>
                    <td className="p-1 text-right font-mono">{w.rows}</td>
                    <td className="p-1 text-xs text-muted">
                      {w.raw_names.join(", ")}
                    </td>
                    <td className="p-1">
                      <input
                        className="input w-44"
                        placeholder="(оставить как есть)"
                        value={mergeInto[w.warehouse] ?? ""}
                        onChange={(e) =>
                          setMergeInto((p) => ({
                            ...p,
                            [w.warehouse]: e.target.value,
                          }))
                        }
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button
            className="btn-primary mt-2"
            disabled={!hasMerges || aliasMut.isPending}
            onClick={() => aliasMut.mutate()}
          >
            Применить объединение
          </button>

          <div className="mt-4 border-t border-border pt-3">
            <div className="text-sm font-medium mb-1">
              WB-короба по городам (300 номеров на город)
            </div>
            <div className="text-xs text-muted mb-2">
              Фиксирует диапазоны WB-номеров с WB_1541505000 (по 300 на каждый
              город). Сервис выдаёт короба города из его диапазона.
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <button
                className="btn"
                disabled={rangesMut.isPending}
                onClick={() => rangesMut.mutate()}
              >
                Зафиксировать диапазоны
              </button>
              <a className="btn text-xs" href={api.boxDistWbRangesUrl()} download>
                ⬇ Excel «WB-короб → город»
              </a>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
