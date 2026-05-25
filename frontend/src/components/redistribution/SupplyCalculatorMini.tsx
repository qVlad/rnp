/**
 * SupplyCalculatorMini — quick-view калькулятора обычной поставки на
 * `/redistribution` (HYP-003). Формула — копия из `pages/SupplyCalculator.tsx`:
 *
 *   acceptance_per_unit = delivery_base + max(0, ceil(L)-1) × delivery_liter
 *   storage_per_unit_per_day = storage_base + max(0, ceil(L)-1) × storage_liter
 *   total = (acceptance + storage × days) × units
 *
 * Persist в `localStorage["redistribution.supply-mini.v1"]`. Полная версия с
 * детализацией per-единица / тарифной справкой — на `/supply-calculator`.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type TariffTimelineRow } from "@/api/client";
import { fmtRub, fmtNum } from "@/lib/format";

const STORAGE_KEY = "redistribution.supply-mini.v1";

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
    const raw = localStorage.getItem(STORAGE_KEY);
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
    localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
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
  const ceilL = Math.max(1, Math.ceil(litersPerUnit));
  const extraLiters = Math.max(0, ceilL - 1);
  const acceptancePerUnit = base + extraLiters * perLiter;
  const storagePerUnitPerDay = storageBase + extraLiters * storageLiter;
  const acceptanceTotal = acceptancePerUnit * units;
  const storageTotal = storagePerUnitPerDay * units * storageDays;
  return {
    acceptanceTotal,
    storageTotal,
    grandTotal: acceptanceTotal + storageTotal,
  };
}

export default function SupplyCalculatorMini() {
  const [params, setParams] = useState<SavedParams>(loadParams);

  const update = (patch: Partial<SavedParams>) => {
    setParams((p) => {
      const next = { ...p, ...patch };
      saveParams(next);
      return next;
    });
  };

  const whQ = useQuery({
    queryKey: ["supply-mini-warehouses"],
    queryFn: () => api.tariffWarehouses(),
  });
  const tariffsQ = useQuery({
    queryKey: ["supply-mini-tariffs"],
    queryFn: () => api.tariffCurrent("box"),
  });

  const warehouses = whQ.data?.items ?? [];
  const tariff = useMemo<TariffTimelineRow | null>(() => {
    if (!params.warehouse) return null;
    const items = tariffsQ.data?.items ?? [];
    return items.find((t) => t.warehouse_name === params.warehouse) ?? null;
  }, [params.warehouse, tariffsQ.data]);

  const result = useMemo(
    () =>
      computeCosts(
        tariff,
        params.units,
        params.liters_per_unit,
        params.storage_days,
      ),
    [tariff, params.units, params.liters_per_unit, params.storage_days],
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted">
        Логистика (acceptance) + хранение для партии прямой поставки на склад
        WB. Тарифы — `wb_tariff_box` (sync ежедневно 08:00 MSK). Полная версия с
        детализацией per-единица — на отдельной странице.
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Склад WB</span>
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
          <span className="text-xs text-muted uppercase">Кол-во штук</span>
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
          <span className="text-xs text-muted uppercase">Литров / шт</span>
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
          <span className="text-xs text-muted uppercase">Хранение, дней</span>
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

      {/* Result */}
      {!params.warehouse ? (
        <div className="text-muted text-sm">Выбери склад для расчёта.</div>
      ) : tariffsQ.isLoading ? (
        <div className="text-muted text-sm">Загрузка тарифов…</div>
      ) : !tariff ? (
        <div className="text-warn text-sm">
          Тариф для склада «{params.warehouse}» не найден. Запусти sync в /tariffs.
        </div>
      ) : result ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <div className="text-xs text-muted uppercase">Логистика</div>
            <div className="text-xl font-mono font-semibold mt-1">
              {fmtRub(result.acceptanceTotal)}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted uppercase">
              Хранение за {params.storage_days} дн
            </div>
            <div className="text-xl font-mono font-semibold mt-1">
              {fmtRub(result.storageTotal)}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted uppercase">ИТОГО</div>
            <div className="text-2xl font-mono font-semibold mt-1 text-accent">
              {fmtRub(result.grandTotal)}
            </div>
            <div className="text-xs text-muted mt-1">
              ≈ {fmtRub(result.grandTotal / Math.max(1, params.units))} / шт
              ({fmtNum(params.units)} шт)
            </div>
          </div>
        </div>
      ) : null}

      <div className="flex justify-end pt-2">
        <Link to="/supply-calculator" className="btn text-xs">
          Полная версия →
        </Link>
      </div>
    </div>
  );
}
