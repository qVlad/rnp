/**
 * TransitCalculatorMini — quick-view калькулятора транзитной поставки на
 * `/redistribution` (HYP-003). Формула (упрощённая копия из
 * `pages/TransitCalculator.tsx`):
 *
 *   total_volume = units × liters_per_unit
 *   rate = total_volume < threshold ? rate_small : rate_large
 *   transit_cost = total_volume × rate
 *
 * При выборе пары хаб → склад делается lookup в `wb_transit_tariff`
 * (auto-fetched расширением). Если нет — graceful fallback на пустые поля
 * (юзер вводит rate вручную). Полная версия со складами / стораджем /
 * довозом до хаба / per-SKU autopick — на `/transit-calculator`.
 *
 * Persist в `localStorage["redistribution.transit-mini.v1"]`.
 */
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, type TransitTariffRow } from "@/api/client";
import { fmtRub, fmtNum } from "@/lib/format";

const STORAGE_KEY = "redistribution.transit-mini.v1";

type SavedParams = {
  hub: string;
  destination: string;
  units: number;
  liters_per_unit: number;
  rate_small: number;
  rate_large: number;
  threshold_l: number;
};

const DEFAULTS: SavedParams = {
  hub: "",
  destination: "",
  units: 100,
  liters_per_unit: 1,
  rate_small: 8.0,
  rate_large: 2.0,
  threshold_l: 1500,
};

function loadParams(): SavedParams {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const v = JSON.parse(raw);
      return {
        hub: typeof v.hub === "string" ? v.hub : DEFAULTS.hub,
        destination:
          typeof v.destination === "string" ? v.destination : DEFAULTS.destination,
        units: Number.isFinite(v.units) ? Number(v.units) : DEFAULTS.units,
        liters_per_unit: Number.isFinite(v.liters_per_unit)
          ? Number(v.liters_per_unit)
          : DEFAULTS.liters_per_unit,
        rate_small: Number.isFinite(v.rate_small)
          ? Number(v.rate_small)
          : DEFAULTS.rate_small,
        rate_large: Number.isFinite(v.rate_large)
          ? Number(v.rate_large)
          : DEFAULTS.rate_large,
        threshold_l: Number.isFinite(v.threshold_l)
          ? Number(v.threshold_l)
          : DEFAULTS.threshold_l,
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

export default function TransitCalculatorMini() {
  const [params, setParams] = useState<SavedParams>(loadParams);

  const update = (patch: Partial<SavedParams>) => {
    setParams((p) => {
      const next = { ...p, ...patch };
      saveParams(next);
      return next;
    });
  };

  // Загружаем весь список транзит-тарифов (lookup-таблица невелика —
  // десятки/сотни строк). Из них выводим hub/destination dropdown'ы и
  // подставляем rate_small / rate_large / threshold при выборе пары.
  const tariffsQ = useQuery({
    queryKey: ["transit-mini-tariffs"],
    queryFn: () => api.transitTariffsList(),
  });
  const items: TransitTariffRow[] = tariffsQ.data?.items ?? [];

  const hubs = useMemo(() => {
    const s = new Set<string>();
    for (const r of items) s.add(r.hub_name);
    return Array.from(s).sort();
  }, [items]);
  const destinations = useMemo(() => {
    const s = new Set<string>();
    for (const r of items) {
      if (!params.hub || r.hub_name === params.hub) s.add(r.destination_warehouse);
    }
    return Array.from(s).sort();
  }, [items, params.hub]);

  // Auto-fill rate_small / rate_large / threshold_l при выборе пары.
  // Если у юзера ничего не выбрано или пары нет в lookup — оставляем как есть.
  useEffect(() => {
    if (!params.hub || !params.destination) return;
    const match = items.find(
      (r) =>
        r.hub_name === params.hub &&
        r.destination_warehouse === params.destination,
    );
    if (!match) return;
    const patch: Partial<SavedParams> = {};
    if (match.rate_small != null) patch.rate_small = match.rate_small;
    if (match.rate_large != null) patch.rate_large = match.rate_large;
    if (match.threshold_l != null) patch.threshold_l = match.threshold_l;
    if (Object.keys(patch).length > 0) {
      setParams((p) => {
        const next = { ...p, ...patch };
        saveParams(next);
        return next;
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.hub, params.destination, items.length]);

  const totalVolume = params.units * params.liters_per_unit;
  const rateTier: "small" | "large" =
    totalVolume < params.threshold_l ? "small" : "large";
  const appliedRate =
    rateTier === "small" ? params.rate_small : params.rate_large;
  const transitCost = totalVolume * appliedRate;

  const hasPair =
    params.hub && params.destination
      ? items.some(
          (r) =>
            r.hub_name === params.hub &&
            r.destination_warehouse === params.destination,
        )
      : false;

  return (
    <div className="flex flex-col gap-3">
      <div className="text-xs text-muted">
        Стоимость довоза через хаб → конечный склад. Тарифы — `wb_transit_tariff`
        (auto-fetched расширением из ЛК WB → «Транзитные направления»). Если
        пары нет в lookup — введи rate вручную. Полная версия со складами /
        стораджем / per-SKU autopick — на отдельной странице.
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Хаб</span>
          <select
            className="input"
            value={params.hub}
            onChange={(e: any) =>
              update({ hub: e.target.value, destination: "" })
            }
            disabled={tariffsQ.isLoading}
          >
            <option value="">— выбери хаб —</option>
            {hubs.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase">Конечный склад</span>
          <select
            className="input"
            value={params.destination}
            onChange={(e: any) => update({ destination: e.target.value })}
            disabled={tariffsQ.isLoading || !params.hub}
          >
            <option value="">— выбери склад —</option>
            {destinations.map((d) => (
              <option key={d} value={d}>
                {d}
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
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <label className="flex flex-col gap-1">
          <span
            className="text-xs text-muted uppercase"
            title="₽/л для объёма < threshold (мелкая партия)"
          >
            ₽/л small
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
            className="text-xs text-muted uppercase"
            title="₽/л для объёма ≥ threshold (крупная партия)"
          >
            ₽/л large
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
          <span className="text-xs text-muted uppercase">
            Threshold, л
          </span>
          <input
            type="number"
            className="input"
            min="0"
            step="100"
            value={params.threshold_l}
            onChange={(e: any) =>
              update({ threshold_l: Number(e.target.value) || 0 })
            }
          />
        </label>
      </div>

      {/* Source hint */}
      <div className="text-xs text-muted">
        {hasPair ? (
          <span className="text-success">
            ✓ Тариф из `wb_transit_tariff` для пары {params.hub} → {params.destination}
          </span>
        ) : params.hub && params.destination ? (
          <span className="text-warning">
            ⚠ Пара {params.hub} → {params.destination} не найдена в lookup. Тариф —
            из ручного ввода.
          </span>
        ) : (
          <span>Выбери хаб и склад — тариф подставится автоматически.</span>
        )}
      </div>

      {/* Result */}
      {totalVolume > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <div className="text-xs text-muted uppercase">Объём</div>
            <div className="text-xl font-mono font-semibold mt-1">
              {fmtNum(totalVolume)} л
            </div>
            <div className="text-xs text-muted mt-1">
              {fmtNum(params.units)} шт × {params.liters_per_unit} л
            </div>
          </div>
          <div>
            <div className="text-xs text-muted uppercase">
              Применённый rate ({rateTier})
            </div>
            <div className="text-xl font-mono font-semibold mt-1">
              {fmtRub(appliedRate)} / л
            </div>
            <div className="text-xs text-muted mt-1">
              {rateTier === "small"
                ? `< ${fmtNum(params.threshold_l)} л`
                : `≥ ${fmtNum(params.threshold_l)} л`}
            </div>
          </div>
          <div>
            <div className="text-xs text-muted uppercase">Стоимость транзита</div>
            <div className="text-2xl font-mono font-semibold mt-1 text-accent">
              {fmtRub(transitCost)}
            </div>
            <div className="text-xs text-muted mt-1">
              ≈ {fmtRub(transitCost / Math.max(1, params.units))} / шт
            </div>
          </div>
        </div>
      )}

      <div className="flex justify-end pt-2">
        <Link to="/transit-calculator" className="btn text-xs">
          ↗ Полная версия на /transit-calculator
        </Link>
      </div>
    </div>
  );
}
