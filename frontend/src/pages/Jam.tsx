/**
 * Джем — поисковая аналитика по кластерам (10X-методика).
 *
 * Сейчас интеграция с WB Jam API — в roadmap. Страница показывает
 * empty-state с инструкцией подключения. Когда WB Jam будет подключён —
 * заменим на реальный component с таблицей кластеров.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

export default function Jam() {
  const [nmInput, setNmInput] = useState("");
  const [nmId, setNmId] = useState<number | null>(null);

  const status = useQuery({
    queryKey: ["jam-status"],
    queryFn: () => api.jamStatus(),
  });

  const clusters = useQuery({
    queryKey: ["jam-clusters", nmId],
    queryFn: () => api.jamClusters(nmId!),
    enabled: nmId != null,
  });

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold">Джем — поисковая аналитика</h1>
        <div className="text-xs text-muted mt-1">
          Кластеризованные поисковые запросы из WB Jam с MAX-границами
          рекламы по каждому кластеру (10X-методика).
        </div>
      </div>

      {status.data?.status === "not_configured" && (
        <div className="card border-warn/40 bg-warn/5">
          <div className="font-medium text-warn mb-2">
            🚧 Интеграция с WB Jam в разработке
          </div>
          <div className="text-sm leading-relaxed">
            {status.data.message}
          </div>
          <div className="mt-3 text-xs text-muted">
            <strong>Что будет, когда подключим:</strong>
            <ul className="list-disc list-inside mt-1 space-y-1">
              <li>Кластеры поисковых запросов сгруппированные по смыслу.</li>
              <li>
                По каждому кластеру: заказы, клики, просмотры, конверсии в
                корзину/заказ, доля продаж, расходы РК, ДРР, СРМ.
              </li>
              <li>
                MAX-границы (CPC / корзина / заказ) с цветовой разметкой:
                <span className="text-danger">красный</span> = выше MAX (убыток),
                <span className="text-warn"> жёлтый</span> = 70-100% от MAX
                (граница), <span className="text-success">зелёный</span> = ниже
                70% (с маржой).
              </li>
              <li>
                Раз в час обновление с WB Jam API. Хранение 90 дней.
              </li>
            </ul>
          </div>
          <div className="mt-3 text-xs">
            <a
              href={status.data.docs_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent underline"
            >
              Подключить WB Jam в кабинете →
            </a>
          </div>
        </div>
      )}

      <section className="card">
        <h2 className="font-medium mb-3">Кластеры по SKU (превью UI)</h2>
        <div className="flex items-end gap-3 mb-3">
          <input
            placeholder="nmId WB"
            value={nmInput}
            onChange={(e) => setNmInput(e.target.value)}
            className="bg-surface border border-border rounded-md p-2 text-sm w-48"
          />
          <button
            className="btn-primary"
            onClick={() => setNmId(Number(nmInput) || null)}
            disabled={!nmInput}
          >
            Загрузить
          </button>
        </div>

        {clusters.data?.clusters?.length === 0 && (
          <div className="text-muted text-sm">
            {clusters.data?.message ?? "Нет данных."}
          </div>
        )}

        {clusters.data && clusters.data.clusters.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">Кластер</th>
                <th className="text-right p-2">Заказов</th>
                <th className="text-right p-2">Клики</th>
                <th className="text-right p-2">CTR</th>
                <th className="text-right p-2">Корзина%</th>
                <th className="text-right p-2">Заказ%</th>
                <th className="text-right p-2">CPC</th>
                <th className="text-right p-2">MAX CPC</th>
                <th className="text-right p-2">ДРР</th>
              </tr>
            </thead>
            <tbody>
              {clusters.data.clusters.map((c: any, i: number) => (
                <tr key={i} className="border-t border-border">
                  <td className="p-2">{c.cluster}</td>
                  <td className="p-2 text-right">{c.orders}</td>
                  <td className="p-2 text-right">{c.clicks}</td>
                  <td className="p-2 text-right">{c.ctr}%</td>
                  <td className="p-2 text-right">{c.cart_pct}%</td>
                  <td className="p-2 text-right">{c.order_pct}%</td>
                  <td className="p-2 text-right">{c.cpc}</td>
                  <td className="p-2 text-right">{c.max_cpc}</td>
                  <td className="p-2 text-right">{c.drr}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
