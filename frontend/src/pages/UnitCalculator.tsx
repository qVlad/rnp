import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub, fmtPct } from "@/lib/format";
import { computeUnitEconomics, type CalcInput } from "@/lib/calc";

const blank = (): CalcInput => ({
  price: 1990,
  commission_pct: 18,
  acquiring_pct: 1.5,
  logistics_per_unit: 80,
  buyout_pct: 80,
  cost_rub: 500,
  packaging_rub: 30,
  fulfillment_rub: 20,
  marketing_per_unit: 100,
  tax_system: "usn_income",
  tax_rate: 6,
  tax_min_rate: 1,
  reduce_by_insurance: false,
  vat_payer: false,
  vat_rate: 0,
});

const TAX_SYSTEMS: { value: string; label: string }[] = [
  { value: "none", label: "Без налога" },
  { value: "usn_income", label: "УСН «Доходы»" },
  { value: "usn_income_expense", label: "УСН «Доходы − Расходы»" },
  { value: "osn", label: "ОСН" },
  { value: "patent", label: "Патент" },
  { value: "npd", label: "НПД" },
  { value: "ausn_income", label: "АУСН «Доходы»" },
  { value: "ausn_income_expense", label: "АУСН «Доходы − Расходы»" },
];

export default function UnitCalculator() {
  const [input, setInput] = useState<CalcInput>(blank());

  const cats = useQuery({
    queryKey: ["calc-categories"],
    queryFn: () => api.calcCategories(),
  });
  const defaults = useQuery({
    queryKey: ["calc-defaults"],
    queryFn: () => api.calcDefaults(),
  });

  // На первом успехе применяем налоговые настройки пользователя
  useEffect(() => {
    if (defaults.data) {
      setInput((p) => ({
        ...p,
        tax_system: defaults.data!.tax_system || p.tax_system,
        tax_rate: defaults.data!.tax_rate || p.tax_rate,
        tax_min_rate: defaults.data!.tax_min_rate || p.tax_min_rate,
        vat_payer: defaults.data!.vat_payer,
        vat_rate: defaults.data!.vat_rate,
        acquiring_pct: defaults.data!.acquiring_pct ?? p.acquiring_pct,
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defaults.data]);

  const result = useMemo(() => computeUnitEconomics(input), [input]);

  const set = (patch: Partial<CalcInput>) => setInput((p) => ({ ...p, ...patch }));

  const applyCategory = (id: number) => {
    const c = cats.data?.items.find((x) => x.id === id);
    if (!c) return;
    set({
      commission_pct: c.commission_pct,
      logistics_per_unit: c.default_logistics_per_unit,
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Юнит-калькулятор «what-if»</h1>

      <div className="card text-sm text-muted leading-relaxed">
        Прикиньте маржу и ROI ещё до завоза товара. Меняйте параметры — расчёт
        моментальный. Категория подставит ориентировочный % комиссии WB и
        логистики; точные значения берите из тарифной сетки WB.
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* INPUTS */}
        <div className="flex flex-col gap-4">
          <section className="card">
            <h2 className="font-medium mb-3">Категория и цена</h2>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Категория WB">
                <select
                  className="input"
                  onChange={(e: any) => applyCategory(Number(e.target.value))}
                >
                  <option value="">— выберите —</option>
                  {(cats.data?.items ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.commission_pct}%)
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Цена для покупателя, ₽">
                <input
                  type="number"
                  className="input"
                  value={input.price}
                  onChange={(e: any) => set({ price: Number(e.target.value) || 0 })}
                  step="1"
                />
              </Field>
              <Field label="Комиссия WB, %">
                <input
                  type="number"
                  className="input"
                  value={input.commission_pct}
                  onChange={(e: any) =>
                    set({ commission_pct: Number(e.target.value) || 0 })
                  }
                  step="0.1"
                />
              </Field>
              <Field label="Эквайринг, %">
                <input
                  type="number"
                  className="input"
                  value={input.acquiring_pct}
                  onChange={(e: any) =>
                    set({ acquiring_pct: Number(e.target.value) || 0 })
                  }
                  step="0.1"
                />
              </Field>
            </div>
          </section>

          <section className="card">
            <h2 className="font-medium mb-3">Логистика и выкуп</h2>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Логистика за ед., ₽">
                <input
                  type="number"
                  className="input"
                  value={input.logistics_per_unit}
                  onChange={(e: any) =>
                    set({ logistics_per_unit: Number(e.target.value) || 0 })
                  }
                  step="1"
                />
              </Field>
              <Field label="Выкуп, %">
                <input
                  type="number"
                  className="input"
                  value={input.buyout_pct}
                  onChange={(e: any) =>
                    set({ buyout_pct: Number(e.target.value) || 0 })
                  }
                  step="1"
                  max={100}
                  min={0}
                />
              </Field>
            </div>
            <div className="text-xs text-muted mt-2">
              При выкупе &lt; 100% часть товара возвращается → логистика учитывается
              как: <code>logistics × (2 − buyout/100)</code>.
            </div>
          </section>

          <section className="card">
            <h2 className="font-medium mb-3">Себестоимость и маркетинг</h2>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Себестоимость, ₽">
                <input
                  type="number"
                  className="input"
                  value={input.cost_rub}
                  onChange={(e: any) => set({ cost_rub: Number(e.target.value) || 0 })}
                  step="1"
                />
              </Field>
              <Field label="Упаковка, ₽">
                <input
                  type="number"
                  className="input"
                  value={input.packaging_rub}
                  onChange={(e: any) =>
                    set({ packaging_rub: Number(e.target.value) || 0 })
                  }
                  step="1"
                />
              </Field>
              <Field label="Фулфилмент, ₽">
                <input
                  type="number"
                  className="input"
                  value={input.fulfillment_rub}
                  onChange={(e: any) =>
                    set({ fulfillment_rub: Number(e.target.value) || 0 })
                  }
                  step="1"
                />
              </Field>
              <Field label="Маркетинг на ед., ₽">
                <input
                  type="number"
                  className="input"
                  value={input.marketing_per_unit}
                  onChange={(e: any) =>
                    set({ marketing_per_unit: Number(e.target.value) || 0 })
                  }
                  step="1"
                />
              </Field>
            </div>
          </section>

          <section className="card">
            <h2 className="font-medium mb-3">Налоги и НДС</h2>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Система налогообложения">
                <select
                  className="input"
                  value={input.tax_system}
                  onChange={(e: any) => set({ tax_system: e.target.value })}
                >
                  {TAX_SYSTEMS.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Ставка налога, %">
                <input
                  type="number"
                  className="input"
                  value={input.tax_rate}
                  onChange={(e: any) => set({ tax_rate: Number(e.target.value) || 0 })}
                  step="0.1"
                />
              </Field>
              <Field label="Плательщик НДС">
                <label className="flex items-center gap-2 mt-2">
                  <input
                    type="checkbox"
                    checked={input.vat_payer}
                    onChange={(e: any) => set({ vat_payer: e.target.checked })}
                  />
                  <span className="text-sm">да</span>
                </label>
              </Field>
              {input.vat_payer && (
                <Field label="Ставка НДС, %">
                  <select
                    className="input"
                    value={input.vat_rate}
                    onChange={(e: any) => set({ vat_rate: Number(e.target.value) || 0 })}
                  >
                    <option value="0">0%</option>
                    <option value="5">5%</option>
                    <option value="7">7%</option>
                    <option value="22">22%</option>
                  </select>
                </Field>
              )}
            </div>
          </section>
        </div>

        {/* OUTPUTS */}
        <div className="flex flex-col gap-4">
          <section className="card">
            <h2 className="font-medium mb-3">Итог</h2>
            <div className="grid grid-cols-3 gap-3">
              <BigKpi
                label="Маржа"
                value={fmtRub(result.margin)}
                tone={result.margin > 0 ? "good" : "bad"}
              />
              <BigKpi
                label="Маржа %"
                value={fmtPct(result.margin_pct, 1)}
                tone={result.margin_pct > 15 ? "good" : result.margin_pct > 0 ? "warn" : "bad"}
              />
              <BigKpi
                label="ROI"
                value={fmtPct(result.roi_pct, 0)}
                tone={result.roi_pct > 50 ? "good" : result.roi_pct > 0 ? "warn" : "bad"}
              />
            </div>
            <div className="grid grid-cols-2 gap-3 mt-3">
              <SmallKpi label="ДРР" value={fmtPct(result.drr_pct, 1)} />
              <SmallKpi
                label="Безубыточная цена"
                value={fmtRub(result.break_even_price)}
                hint="ниже этой цены продажа уйдёт в минус"
              />
            </div>
          </section>

          <section className="card">
            <h2 className="font-medium mb-3">Разбор по статьям</h2>
            <table className="w-full text-sm">
              <tbody>
                <Row label="Цена для покупателя" value={result.revenue_gross} sign="+" />
                {input.vat_payer && (
                  <Row label="НДС (исходящий, выделен)" value={-result.vat} sub />
                )}
                <Row
                  label="Чистая выручка (без НДС)"
                  value={result.revenue_net_vat}
                  emphasize
                />
                <Row label="Комиссия WB" value={-result.wb_commission} />
                <Row label="Эквайринг" value={-result.acquiring} />
                <Row
                  label="Логистика (с поправкой на выкуп)"
                  value={-result.logistics_effective}
                />
                <Row label="Себестоимость + упаковка + ФФ" value={-result.total_cogs} />
                <Row label="Маркетинг" value={-result.marketing} />
                <Row
                  label="Прибыль до налога"
                  value={result.profit_before_tax}
                  emphasize
                />
                <Row label="Налог" value={-result.tax} />
                <Row label="Чистая маржа" value={result.margin} emphasize bold />
              </tbody>
            </table>
          </section>

          <section className="card text-xs text-muted">
            <strong>Замечания:</strong>
            <ul className="list-disc list-inside mt-1 space-y-1">
              <li>Категория задаёт ориентир — реальный % комиссии и логистика зависят от подкатегории и могут меняться. Сверяйтесь с тарифной сеткой WB.</li>
              <li>Безубыточная цена считается итеративно (бинарный поиск, точность ~1 ₽).</li>
              <li>Расчёт идентичен формулам нашего P&amp;L: налоги, НДС, комиссии — те же что и в реальных отчётах.</li>
              <li>Хранение, штрафы, прочие OPEX не учитываются в калькуляторе на одну единицу — это операционные расходы, их учитывайте через P&amp;L.</li>
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: any }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      {children}
    </label>
  );
}

function Row({
  label,
  value,
  sign,
  sub,
  emphasize,
  bold,
}: {
  label: string;
  value: number;
  sign?: "+" | "-";
  sub?: boolean;
  emphasize?: boolean;
  bold?: boolean;
}) {
  const cls = [
    "p-2",
    sub ? "text-muted text-xs" : "",
    emphasize ? "border-t border-border" : "",
    bold ? "font-semibold" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const valColor =
    value > 0 ? "text-emerald-400" : value < 0 ? "text-red-400" : "text-muted";
  const display =
    sign && sign === "+" && value >= 0 ? `+${fmtRub(value)}` : fmtRub(value);
  return (
    <tr className={emphasize ? "bg-bg/30" : ""}>
      <td className={cls}>{label}</td>
      <td className={`${cls} text-right font-mono ${valColor}`}>{display}</td>
    </tr>
  );
}

function BigKpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "good" | "warn" | "bad";
}) {
  const color =
    tone === "good"
      ? "text-emerald-400"
      : tone === "warn"
      ? "text-yellow-400"
      : "text-red-400";
  return (
    <div className="border border-border rounded-md p-3 bg-bg/30">
      <div className="text-xs text-muted">{label}</div>
      <div className={`text-2xl font-semibold mt-1 ${color}`}>{value}</div>
    </div>
  );
}

function SmallKpi({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="border border-border rounded-md p-3 bg-bg/30">
      <div className="text-xs text-muted">{label}</div>
      <div className="text-lg font-semibold mt-1">{value}</div>
      {hint && <div className="text-xs text-muted mt-1">{hint}</div>}
    </div>
  );
}
