/**
 * TASK-LEAD-077 (2026-05-22) — Калькулятор стоимости транзитной поставки WB.
 *
 * Отличие от обычной поставки (`SupplyCalculator`):
 *   - Транзитная поставка идёт через хаб → конечный склад.
 *   - WB Tariffs API НЕ отдаёт транзитные тарифы (доступны только в ЛК WB →
 *     Поставки → Транзитные направления). Поэтому юзер вводит тариф ₽/л вручную.
 *
 * Формула (см. research-transit-shipments-2026-05-22.md):
 *   - total_volume = units × liters_per_unit
 *   - rate = total_volume < threshold(=1500л) ? rate_small : rate_large
 *   - transit_cost = total_volume × rate
 *   - storage_cost = wb_tariff_box[final_warehouse].storage × units × days
 *     (хранение после транзита на конечном складе — обычный тариф)
 *
 * Compare с обычной поставкой на тот же конечный склад показывает Δ.
 *
 * Frontend-only, persist в localStorage["transit-calculator.v2"].
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type TariffTimelineRow } from "@/api/client";
import { fmtRub, fmtNum } from "@/lib/format";
import PageHeader from "@/components/PageHeader";

const STORAGE_KEY = "transit-calculator.v2";

type SavedParams = {
  hub: string; // транзитный склад (хаб) — свободный текст
  final_warehouse: string; // конечный склад (из wb_tariff_box)
  units: number;
  liters_per_unit: number;
  storage_days: number;
  rate_small: number; // ₽/л при объёме < threshold
  rate_large: number; // ₽/л при объёме ≥ threshold
  volume_threshold_l: number;
  // Прямой тариф довоза (если знаешь точное значение и не хочешь возиться
  // с двухступенчатой шкалой). Когда > 0 — используется ВМЕСТО small/large.
  rate_direct: number;
};

const DEFAULTS: SavedParams = {
  hub: "",
  final_warehouse: "",
  units: 100,
  liters_per_unit: 1,
  storage_days: 30,
  rate_small: 8.0,
  rate_large: 2.0,
  volume_threshold_l: 1500,
  rate_direct: 0,
};

// Известные хабы WB (на 2026-05, из research). Список свободно редактируется
// юзером — это просто подсказки в datalist.
const KNOWN_HUBS = [
  "Обухово",
  "Шушары",
  "Чашниково",
  "Чехов 1",
  "Чехов 2",
  "Электросталь",
  "Подольск",
  "Краснодар",
  "Казань",
  "Екатеринбург",
  "Новосибирск",
  "Тула",
];

function loadParams(): SavedParams {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const v = JSON.parse(raw);
      return {
        hub: typeof v.hub === "string" ? v.hub : DEFAULTS.hub,
        final_warehouse:
          typeof v.final_warehouse === "string"
            ? v.final_warehouse
            : DEFAULTS.final_warehouse,
        units: Number.isFinite(v.units) ? Number(v.units) : DEFAULTS.units,
        liters_per_unit: Number.isFinite(v.liters_per_unit)
          ? Number(v.liters_per_unit)
          : DEFAULTS.liters_per_unit,
        storage_days: Number.isFinite(v.storage_days)
          ? Number(v.storage_days)
          : DEFAULTS.storage_days,
        rate_small: Number.isFinite(v.rate_small)
          ? Number(v.rate_small)
          : DEFAULTS.rate_small,
        rate_large: Number.isFinite(v.rate_large)
          ? Number(v.rate_large)
          : DEFAULTS.rate_large,
        volume_threshold_l: Number.isFinite(v.volume_threshold_l)
          ? Number(v.volume_threshold_l)
          : DEFAULTS.volume_threshold_l,
        rate_direct: Number.isFinite(v.rate_direct)
          ? Number(v.rate_direct)
          : DEFAULTS.rate_direct,
      };
    }
  } catch {}
  return DEFAULTS;
}

function saveParams(p: SavedParams) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
  } catch {}
}

type TransitResult = {
  totalVolume: number;
  appliedRate: number;
  rateTier: "small" | "large";
  transitCost: number;
  storagePerUnitPerDay: number;
  storageTotal: number;
  grandTotal: number;
};

function computeTransit(
  finalTariff: TariffTimelineRow | null,
  p: SavedParams,
): TransitResult | null {
  const totalVolume = p.units * p.liters_per_unit;
  if (!Number.isFinite(totalVolume) || totalVolume <= 0) return null;

  // Если задан прямой тариф (rate_direct > 0) — используем его, игнорируем
  // двухступенчатую шкалу. Это удобный шорткат когда юзер точно знает тариф
  // для своей пары хаб→склад из ЛК WB.
  const useDirect = Number.isFinite(p.rate_direct) && p.rate_direct > 0;
  const rateTier: "small" | "large" =
    useDirect || totalVolume < p.volume_threshold_l ? "small" : "large";
  const appliedRate = useDirect
    ? p.rate_direct
    : rateTier === "small"
      ? p.rate_small
      : p.rate_large;
  const transitCost = totalVolume * appliedRate;

  // Хранение на конечном складе — обычный тариф box (если выбран и есть тариф)
  let storagePerUnitPerDay = 0;
  if (finalTariff) {
    const storageBase = finalTariff.storage_base ?? 0;
    const storageLiter = finalTariff.storage_liter ?? 0;
    const ceilL = Math.max(1, Math.ceil(p.liters_per_unit));
    const extraLiters = Math.max(0, ceilL - 1);
    storagePerUnitPerDay = storageBase + extraLiters * storageLiter;
  }
  const storageTotal = storagePerUnitPerDay * p.units * p.storage_days;
  const grandTotal = transitCost + storageTotal;

  return {
    totalVolume,
    appliedRate,
    rateTier,
    transitCost,
    storagePerUnitPerDay,
    storageTotal,
    grandTotal,
  };
}

function computeDirectSupply(
  finalTariff: TariffTimelineRow | null,
  p: SavedParams,
): { acceptanceTotal: number; storageTotal: number; grandTotal: number } | null {
  if (!finalTariff) return null;
  const base = finalTariff.delivery_base ?? 0;
  const perLiter = finalTariff.delivery_liter ?? 0;
  const storageBase = finalTariff.storage_base ?? 0;
  const storageLiter = finalTariff.storage_liter ?? 0;
  const ceilL = Math.max(1, Math.ceil(p.liters_per_unit));
  const extraLiters = Math.max(0, ceilL - 1);
  const acceptancePerUnit = base + extraLiters * perLiter;
  const storagePerUnitPerDay = storageBase + extraLiters * storageLiter;
  const acceptanceTotal = acceptancePerUnit * p.units;
  const storageTotal = storagePerUnitPerDay * p.units * p.storage_days;
  return {
    acceptanceTotal,
    storageTotal,
    grandTotal: acceptanceTotal + storageTotal,
  };
}

export default function TransitCalculator() {
  const [params, setParams] = useState<SavedParams>(loadParams);

  const update = (patch: Partial<SavedParams>) => {
    setParams((p) => {
      const next = { ...p, ...patch };
      saveParams(next);
      return next;
    });
  };

  const whQ = useQuery({
    queryKey: ["transit-warehouses"],
    queryFn: () => api.tariffWarehouses(),
  });
  const tariffsQ = useQuery({
    queryKey: ["transit-tariffs-box"],
    queryFn: () => api.tariffCurrent("box"),
  });

  const warehouses = whQ.data?.items ?? [];
  const finalTariff = useMemo<TariffTimelineRow | null>(() => {
    if (!params.final_warehouse) return null;
    const items = tariffsQ.data?.items ?? [];
    return items.find((t) => t.warehouse_name === params.final_warehouse) ?? null;
  }, [params.final_warehouse, tariffsQ.data]);

  const transit = useMemo(() => computeTransit(finalTariff, params), [
    finalTariff,
    params,
  ]);
  const direct = useMemo(() => computeDirectSupply(finalTariff, params), [
    finalTariff,
    params,
  ]);

  return (
    <div className="flex flex-col gap-4 max-w-5xl">
      <PageHeader
        title="Калькулятор стоимости транзитной поставки"
        subtitle={
          <>
            Транзитная поставка идёт{" "}
            <b>через хаб → конечный склад</b>: вы привозите партию в
            транзитный пункт WB (Обухово / Шушары / …), оттуда WB сама развозит
            по сети. Тарифы транзита WB <b>не отдаёт через API</b> — впиши{" "}
            <code>₽/л</code> вручную из ЛК. Для прямой поставки см.{" "}
            <a className="text-accent" href="/supply-calculator">
              Калькулятор поставки
            </a>
            .
          </>
        }
      />

      {/* Important warning */}
      <section className="card text-xs" style={{ background: "rgba(255,193,7,0.08)" }}>
        <p>
          <b>⚠️ Где взять тариф транзита:</b>{" "}
          <a
            className="text-accent"
            href="https://seller.wildberries.ru"
            target="_blank"
            rel="noreferrer"
          >
            ЛК WB
          </a>{" "}
          → Поставки и заказы → Поставки (FBW) → <b>Транзитные направления</b>.
          Выбери пару «хаб → конечный_склад» и впиши <code>₽/л</code> ниже.
          Тариф зависит от объёма (двухступенчатая шкала: до 1500 л — выше,
          от 1500 л — ниже). С 1 апреля 2026 WB поднял тарифы транзита в
          среднем на ~20%.
        </p>
      </section>

      {/* Form */}
      <section className="card">
        <h3 className="font-medium mb-3 text-sm">Параметры партии</h3>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted uppercase tracking-wide">
              Хаб (транзитный склад)
            </span>
            <input
              type="text"
              className="input"
              list="transit-hubs"
              value={params.hub}
              onChange={(e: any) => update({ hub: e.target.value })}
              placeholder="например, Обухово"
            />
            <datalist id="transit-hubs">
              {KNOWN_HUBS.map((h) => (
                <option key={h} value={h} />
              ))}
            </datalist>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted uppercase tracking-wide">
              Конечный склад
            </span>
            <select
              className="input"
              value={params.final_warehouse}
              onChange={(e: any) => update({ final_warehouse: e.target.value })}
              disabled={whQ.isLoading}
            >
              <option value="">— выбери склад —</option>
              {warehouses.map((w) => (
                <option key={w} value={w}>
                  {w}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted uppercase tracking-wide">
              Кол-во штук
            </span>
            <input
              type="number"
              className="input"
              min="1"
              step="1"
              value={params.units}
              onChange={(e: any) => update({ units: Number(e.target.value) || 0 })}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Объём одного товара в литрах. Общий объём партии = units × liters_per_unit."
            >
              Литров / шт
            </span>
            <input
              type="number"
              className="input"
              min="0.01"
              step="0.1"
              value={params.liters_per_unit}
              onChange={(e: any) =>
                update({ liters_per_unit: Number(e.target.value) || 0 })
              }
            />
          </label>
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Сколько дней партия пролежит на конечном WB-складе после транзита."
            >
              Хранение, дней
            </span>
            <input
              type="number"
              className="input"
              min="0"
              step="1"
              value={params.storage_days}
              onChange={(e: any) =>
                update({ storage_days: Number(e.target.value) || 0 })
              }
            />
          </label>
        </div>
      </section>

      {/* Transit tariff inputs */}
      <section className="card">
        <h3 className="font-medium mb-3 text-sm">
          Тариф транзита (вписать из ЛК WB)
        </h3>

        {/* Simple: один тариф ₽/л — если знаешь точную цену довоза. */}
        <div className="mb-3">
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Если у тебя в ЛК WB опубликован прямой тариф довоза для пары «хаб → конечный склад» — впиши его сюда. Когда поле > 0 — двухступенчатая шкала ниже игнорируется."
            >
              Прямой тариф довоза ₽/л
              <span className="text-faint normal-case font-normal">
                {" "}— рекомендуется, если знаешь точное значение
              </span>
            </span>
            <input
              type="number"
              className="input"
              min="0"
              step="0.1"
              value={params.rate_direct}
              placeholder="напр. 5.5"
              onChange={(e: any) =>
                update({ rate_direct: Number(e.target.value) || 0 })
              }
            />
            <span className="text-tiny text-muted">
              Общая стоимость довоза = общий объём партии × этот тариф.
              {params.rate_direct > 0 &&
                " Двухступенчатая шкала ниже сейчас игнорируется."}
            </span>
          </label>
        </div>

        <details className="mb-2">
          <summary className="text-xs text-muted cursor-pointer hover:text-fg">
            ⚙ Двухступенчатый тариф (если точного значения нет — fallback по
            порогу объёма)
          </summary>
        </details>
        <div
          className={`grid grid-cols-1 md:grid-cols-3 gap-3 ${
            params.rate_direct > 0 ? "opacity-50" : ""
          }`}
        >
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Ставка ₽ за литр, когда общий объём партии меньше порога."
            >
              Тариф ₽/л (объём &lt; порога)
            </span>
            <input
              type="number"
              className="input"
              min="0"
              step="0.1"
              value={params.rate_small}
              onChange={(e: any) =>
                update({ rate_small: Number(e.target.value) || 0 })
              }
            />
          </label>
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Ставка ₽ за литр, когда общий объём партии больше или равен порогу. Обычно ниже."
            >
              Тариф ₽/л (объём ≥ порога)
            </span>
            <input
              type="number"
              className="input"
              min="0"
              step="0.1"
              value={params.rate_large}
              onChange={(e: any) =>
                update({ rate_large: Number(e.target.value) || 0 })
              }
            />
          </label>
          <label className="flex flex-col gap-1">
            <span
              className="text-xs text-muted uppercase tracking-wide"
              title="Порог переключения тарифов. У WB обычно 1500 л."
            >
              Порог переключения, л
            </span>
            <input
              type="number"
              className="input"
              min="1"
              step="100"
              value={params.volume_threshold_l}
              onChange={(e: any) =>
                update({ volume_threshold_l: Number(e.target.value) || 0 })
              }
            />
          </label>
        </div>
      </section>

      {/* Tariff info for final warehouse */}
      {finalTariff && (
        <section className="card text-xs text-muted">
          <div className="font-medium text-fg mb-1">
            Конечный склад «{finalTariff.warehouse_name}» — обычные WB-тарифы
            (для хранения)
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div>
              Хранение база/день:{" "}
              <span className="font-mono text-fg">
                {fmtRub(finalTariff.storage_base ?? 0)}
              </span>
            </div>
            <div>
              +₽ за литр сверх 1/день:{" "}
              <span className="font-mono text-fg">
                {fmtRub(finalTariff.storage_liter ?? 0)}
              </span>
            </div>
            <div>
              Прямая логистика база:{" "}
              <span className="font-mono text-fg">
                {fmtRub(finalTariff.delivery_base ?? 0)}
              </span>
            </div>
            <div>
              +₽ за литр сверх 1:{" "}
              <span className="font-mono text-fg">
                {fmtRub(finalTariff.delivery_liter ?? 0)}
              </span>
            </div>
          </div>
        </section>
      )}

      {/* Result */}
      {!transit ? (
        <section className="card text-muted">
          Введи кол-во штук и литров на шт, чтобы посмотреть расчёт.
        </section>
      ) : (
        <>
          <section className="card">
            <h2 className="font-medium mb-3">
              Стоимость партии {fmtNum(params.units)} шт через транзит
              {params.hub ? <> «{params.hub}»</> : null}
              {params.final_warehouse ? (
                <> → «{params.final_warehouse}»</>
              ) : null}
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <div className="text-xs text-muted uppercase">Транзит</div>
                <div className="text-2xl font-mono font-semibold mt-1">
                  {fmtRub(transit.transitCost)}
                </div>
                <div className="text-xs text-muted mt-1">
                  {fmtNum(transit.totalVolume)} л × {fmtRub(transit.appliedRate)}/л
                  <br />
                  тариф «{transit.rateTier === "small" ? "до" : "от"}{" "}
                  {fmtNum(params.volume_threshold_l)} л»
                </div>
              </div>
              <div>
                <div className="text-xs text-muted uppercase">
                  Хранение за {params.storage_days} дн (конечный склад)
                </div>
                <div className="text-2xl font-mono font-semibold mt-1">
                  {fmtRub(transit.storageTotal)}
                </div>
                <div className="text-xs text-muted mt-1">
                  {finalTariff ? (
                    <>
                      {fmtRub(transit.storagePerUnitPerDay)} × {fmtNum(params.units)}{" "}
                      шт × {params.storage_days} дн
                    </>
                  ) : (
                    <span className="text-warn">
                      Выбери конечный склад, чтобы посчитать хранение
                    </span>
                  )}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted uppercase">ИТОГО</div>
                <div className="text-3xl font-mono font-semibold mt-1 text-accent">
                  {fmtRub(transit.grandTotal)}
                </div>
                <div className="text-xs text-muted mt-1">
                  ≈ {fmtRub(transit.grandTotal / Math.max(1, params.units))} / шт
                </div>
              </div>
            </div>
          </section>

          {/* Compare with direct supply */}
          {direct && (
            <section className="card">
              <h3 className="font-medium mb-3 text-sm">
                Сравнение с прямой поставкой на «{params.final_warehouse}»
              </h3>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted uppercase">
                    <th className="text-left p-2">Тип</th>
                    <th className="text-right p-2">Логистика / транзит</th>
                    <th className="text-right p-2">
                      Хранение ({params.storage_days} дн)
                    </th>
                    <th className="text-right p-2">ИТОГО</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="border-t border-border">
                    <td className="p-2">Прямая поставка (acceptance)</td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(direct.acceptanceTotal)}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(direct.storageTotal)}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(direct.grandTotal)}
                    </td>
                  </tr>
                  <tr className="border-t border-border">
                    <td className="p-2">Транзитная поставка</td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(transit.transitCost)}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(transit.storageTotal)}
                    </td>
                    <td className="p-2 text-right font-mono">
                      {fmtRub(transit.grandTotal)}
                    </td>
                  </tr>
                  <tr className="border-t border-border font-semibold">
                    <td className="p-2">Δ (транзит − прямая)</td>
                    <td className="p-2 text-right font-mono"></td>
                    <td className="p-2 text-right font-mono"></td>
                    <td
                      className={
                        "p-2 text-right font-mono " +
                        (transit.grandTotal > direct.grandTotal
                          ? "text-warn"
                          : "text-success")
                      }
                    >
                      {transit.grandTotal > direct.grandTotal ? "+" : ""}
                      {fmtRub(transit.grandTotal - direct.grandTotal)}
                    </td>
                  </tr>
                </tbody>
              </table>
              <p className="text-xs text-muted mt-2">
                Транзит обычно дороже прямой поставки, но позволяет везти груз
                на близкий хаб вместо удалённого конечного склада. Сравнение
                имеет смысл только если у вас есть выбор.
              </p>
            </section>
          )}
        </>
      )}

      <section className="card text-xs text-muted">
        <p className="mb-1">
          <b>Формула — рабочая гипотеза.</b> Сверена с открытой инструкцией WB
          (postavleno.ru, seller.wildberries.ru) на 2026-05-22. Уточни точный
          тариф через ЛК WB → Поставки → Транзитные направления — там видна
          актуальная пара (хаб → склад) с ₽/л.
        </p>
        <ul className="list-disc list-inside space-y-1">
          <li>
            Не входит: внешняя логистика до хаба (твоя), acceptance fee на хабе,
            COGS товара, WB-комиссия при продаже.
          </li>
          <li>
            Тариф транзита WB периодически пересматривается (последнее
            обновление: с 2026-04-01 в среднем +20%).
          </li>
          <li>
            Для типа «Монопаллета» формула другая: <code>тариф × паллет</code>.
            Этот калькулятор для типа «Короб» (per-литр).
          </li>
        </ul>
        <p className="mt-2">
          Research-методичка:{" "}
          <code>agents/references/research-transit-shipments-2026-05-22.md</code>
          .
        </p>
      </section>
    </div>
  );
}
