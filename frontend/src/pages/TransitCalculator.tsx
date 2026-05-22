/**
 * TASK-LEAD-053 — Калькулятор стоимости поставки на WB-склад.
 *
 * РОП хочет: «сколько стоит положить N штук партии на склад X?»
 * Формула WB box-тарифа (миграция 0040, sync ежедневно 08:00 MSK):
 *   - acceptance per unit = delivery_base + max(0, ceil(liters)-1) × delivery_liter
 *   - storage per unit per day = storage_base + max(0, ceil(liters)-1) × storage_liter
 *
 * Используем `tariffList('box')` — текущие тарифы по складам.
 * Frontend-only: backend ничего считать не нужно, всё на клиенте.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type TariffTimelineRow } from "@/api/client";
import { fmtRub, fmtNum } from "@/lib/format";

const TRANSIT_KEY = "transit-calc.params.v1";

type SavedParams = {
  warehouse: string;
  units: number;
  liters_per_unit: number;
  storage_days: number;
};

const DEFAULTS: SavedParams = {
  warehouse: "",
  units: 100,
  liters_per_unit: 1,
  storage_days: 30,
};

function loadParams(): SavedParams {
  try {
    const raw = localStorage.getItem(TRANSIT_KEY);
    if (raw) {
      const v = JSON.parse(raw);
      return {
        warehouse: typeof v.warehouse === "string" ? v.warehouse : DEFAULTS.warehouse,
        units: Number.isFinite(v.units) ? Number(v.units) : DEFAULTS.units,
        liters_per_unit: Number.isFinite(v.liters_per_unit)
          ? Number(v.liters_per_unit)
          : DEFAULTS.liters_per_unit,
        storage_days: Number.isFinite(v.storage_days)
          ? Number(v.storage_days)
          : DEFAULTS.storage_days,
      };
    }
  } catch {}
  return DEFAULTS;
}

function saveParams(p: SavedParams) {
  try {
    localStorage.setItem(TRANSIT_KEY, JSON.stringify(p));
  } catch {}
}

function computeCosts(
  tariff: TariffTimelineRow | null,
  units: number,
  litersPerUnit: number,
  storageDays: number,
) {
  if (!tariff) return null;
  const base = tariff.delivery_base ?? 0;
  const perLiter = tariff.delivery_liter ?? 0;
  const storageBase = tariff.storage_base ?? 0;
  const storageLiter = tariff.storage_liter ?? 0;
  // WB-формула: round-up литров для unit-volume < 1, иначе ceil. Для >1 — учитываем extra liters.
  const ceilL = Math.max(1, Math.ceil(litersPerUnit));
  const extraLiters = Math.max(0, ceilL - 1);
  const acceptancePerUnit = base + extraLiters * perLiter;
  const storagePerUnitPerDay = storageBase + extraLiters * storageLiter;

  const acceptanceTotal = acceptancePerUnit * units;
  const storageTotal = storagePerUnitPerDay * units * storageDays;
  const grandTotal = acceptanceTotal + storageTotal;

  return {
    acceptancePerUnit,
    storagePerUnitPerDay,
    acceptanceTotal,
    storageTotal,
    grandTotal,
    base,
    perLiter,
    storageBase,
    storageLiter,
    extraLiters,
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
  const tariff = useMemo<TariffTimelineRow | null>(() => {
    if (!params.warehouse) return null;
    const items = tariffsQ.data?.items ?? [];
    return items.find((t) => t.warehouse_name === params.warehouse) ?? null;
  }, [params.warehouse, tariffsQ.data]);

  const result = useMemo(
    () => computeCosts(tariff, params.units, params.liters_per_unit, params.storage_days),
    [tariff, params.units, params.liters_per_unit, params.storage_days],
  );

  return (
    <div className="flex flex-col gap-4 max-w-5xl">
      <div>
        <h1 className="text-xl font-semibold">Калькулятор стоимости поставки</h1>
        <p className="text-sm text-muted mt-1">
          Считает <b>логистику</b> (acceptance) и <b>хранение</b> для партии N штук
          на конкретный WB-склад. Использует текущие WB-тарифы (миграция 0040,
          обновляется ежедневно 08:00 MSK).
        </p>
      </div>

      {/* Form */}
      <section className="card">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted uppercase tracking-wide">Склад WB</span>
            <select
              className="input"
              value={params.warehouse}
              onChange={(e: any) => update({ warehouse: e.target.value })}
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
              title="Объём одного товара в литрах. WB округляет вверх (ceil) для тарифа."
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
              title="Сколько дней партия пролежит на WB-складе. По умолчанию 30 = месяц."
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

      {/* Tariff info */}
      {tariff && (
        <section className="card text-xs text-muted">
          <div className="font-medium text-fg mb-1">Тариф «{tariff.warehouse_name}» (box)</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div>
              Базовая логистика: <span className="font-mono text-fg">{fmtRub(tariff.delivery_base ?? 0)}</span>
            </div>
            <div>
              +₽ за литр сверх 1: <span className="font-mono text-fg">{fmtRub(tariff.delivery_liter ?? 0)}</span>
            </div>
            <div>
              Хранение база/день: <span className="font-mono text-fg">{fmtRub(tariff.storage_base ?? 0)}</span>
            </div>
            <div>
              +₽ за литр сверх 1/день: <span className="font-mono text-fg">{fmtRub(tariff.storage_liter ?? 0)}</span>
            </div>
          </div>
          {tariff.effective_from && (
            <div className="mt-1">
              Тариф действует с <span className="font-mono">{tariff.effective_from}</span>
            </div>
          )}
        </section>
      )}

      {/* Result */}
      {!params.warehouse ? (
        <section className="card text-muted">Выбери склад чтобы посмотреть расчёт.</section>
      ) : tariffsQ.isLoading ? (
        <section className="card text-muted">Загрузка тарифов…</section>
      ) : !tariff ? (
        <section className="card text-warn">
          Тариф для склада «{params.warehouse}» не найден. Проверь актуальность
          справочника (`/tariffs` → Sync).
        </section>
      ) : result ? (
        <>
          <section className="card">
            <h2 className="font-medium mb-3">Стоимость партии {fmtNum(params.units)} шт</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <div className="text-xs text-muted uppercase">Логистика (acceptance)</div>
                <div className="text-2xl font-mono font-semibold mt-1">
                  {fmtRub(result.acceptanceTotal)}
                </div>
                <div className="text-xs text-muted mt-1">
                  {fmtRub(result.acceptancePerUnit)} × {fmtNum(params.units)} шт
                </div>
              </div>
              <div>
                <div className="text-xs text-muted uppercase">
                  Хранение за {params.storage_days} дн
                </div>
                <div className="text-2xl font-mono font-semibold mt-1">
                  {fmtRub(result.storageTotal)}
                </div>
                <div className="text-xs text-muted mt-1">
                  {fmtRub(result.storagePerUnitPerDay)} × {fmtNum(params.units)} шт × {params.storage_days} дн
                </div>
              </div>
              <div>
                <div className="text-xs text-muted uppercase">ИТОГО</div>
                <div className="text-3xl font-mono font-semibold mt-1 text-accent">
                  {fmtRub(result.grandTotal)}
                </div>
                <div className="text-xs text-muted mt-1">
                  ≈ {fmtRub(result.grandTotal / Math.max(1, params.units))} / шт
                </div>
              </div>
            </div>
          </section>

          {/* Per-unit breakdown */}
          <section className="card text-sm">
            <h3 className="font-medium mb-2">Детализация per-единица</h3>
            <table className="w-full font-mono">
              <tbody>
                <tr className="border-b border-border">
                  <td className="p-2 text-muted">Базовая логистика</td>
                  <td className="p-2 text-right font-mono">{fmtRub(result.base)}</td>
                </tr>
                <tr className="border-b border-border">
                  <td className="p-2 text-muted">
                    Доп. литры (ceil({params.liters_per_unit}) − 1 = {result.extraLiters} × {fmtRub(result.perLiter)})
                  </td>
                  <td className="p-2 text-right font-mono">
                    {fmtRub(result.acceptancePerUnit - result.base)}
                  </td>
                </tr>
                <tr className="border-b border-border font-semibold">
                  <td className="p-2">Логистика на 1 шт</td>
                  <td className="p-2 text-right font-mono">{fmtRub(result.acceptancePerUnit)}</td>
                </tr>
                <tr className="border-b border-border">
                  <td className="p-2 text-muted">Хранение база / день</td>
                  <td className="p-2 text-right font-mono">{fmtRub(result.storageBase)}</td>
                </tr>
                <tr className="border-b border-border">
                  <td className="p-2 text-muted">
                    Доп. литры хранение ({result.extraLiters} × {fmtRub(result.storageLiter)})
                  </td>
                  <td className="p-2 text-right font-mono">
                    {fmtRub(result.storagePerUnitPerDay - result.storageBase)}
                  </td>
                </tr>
                <tr className="font-semibold">
                  <td className="p-2">Хранение на 1 шт / день</td>
                  <td className="p-2 text-right font-mono">{fmtRub(result.storagePerUnitPerDay)}</td>
                </tr>
              </tbody>
            </table>
          </section>
        </>
      ) : null}

      <section className="card text-xs text-muted">
        <p className="mb-1">
          <b>Примечание:</b> расчёт — только WB-сторона (acceptance + storage). Не включает:
        </p>
        <ul className="list-disc list-inside space-y-1">
          <li>Стоимость доставки до WB-склада из твоего склада / Китая — это твоя внешняя логистика</li>
          <li>Платную приёмку (acceptance_fee), если она включена для склада</li>
          <li>Себестоимость товара и комиссию WB при продаже</li>
        </ul>
        <p className="mt-2">
          Для полного CIF-расчёта (Китай → твой склад → WB) — смотри{" "}
          <a className="text-accent" href="/new-products">/new-products</a>.
        </p>
      </section>
    </div>
  );
}
