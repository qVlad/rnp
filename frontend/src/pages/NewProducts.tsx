import { useEffect, useMemo, useState } from "react";
import { Icon } from "@/components/Icon";
import { fmtRub, fmtPct } from "@/lib/format";
import {
  DEFAULT_MARKET,
  type CbrRates,
  type ImportItem,
  type MarketParams,
  type WbCalcRow,
  computeImport,
  computeWbRow,
  fetchCbrRates,
  loadState,
  saveState,
} from "@/lib/newProductsCalc";

const newId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;

const blankImport = (name = ""): ImportItem => ({
  id: newId(),
  name,
  vendor_code: "",
  length_cm: 0,
  width_cm: 0,
  height_cm: 0,
  weight_kg: 0,
  cost_cny: 0,
  duty_per_unit_eur: 0,
  duty_per_kg_eur: 0,
});

const blankWbRow = (name = ""): WbCalcRow => ({
  id: newId(),
  name,
  price_rub: 0,
  commission_pct: 37,
  buyout_pct: 30,
  turnover_days: 60,
  promo_pct: 3,
  other_rub: 180,
});

export default function NewProducts() {
  const [market, setMarket] = useState<MarketParams>(DEFAULT_MARKET);
  const [imports, setImports] = useState<ImportItem[]>([]);
  const [wbRows, setWbRows] = useState<WbCalcRow[]>([]);
  const [openParams, setOpenParams] = useState(false);
  const [activeScenario, setActiveScenario] = useState(0);
  const [cbrRates, setCbrRates] = useState<CbrRates | null>(null);
  const [cbrLoading, setCbrLoading] = useState(false);
  const [cbrError, setCbrError] = useState<string | null>(null);

  // Load from localStorage on mount
  useEffect(() => {
    const saved = loadState();
    if (saved) {
      setMarket(saved.market);
      setImports(saved.imports);
      setWbRows(saved.wbRows);
    } else {
      // Дефолтная демо-строка
      const demoName = "Пример: кеды кожаные";
      setImports([{
        ...blankImport(demoName),
        length_cm: 30, width_cm: 8, height_cm: 11,
        weight_kg: 0.2, cost_cny: 145,
        duty_per_unit_eur: 0.34, duty_per_kg_eur: 0,
      }]);
      setWbRows([{
        ...blankWbRow(demoName),
        price_rub: 8000,
      }]);
    }
  }, []);

  // Fetch CBR rates in background. На первой загрузке (когда сохранения нет)
  // автоматически применяем; если у пользователя есть сохранённое состояние —
  // показываем баннер с кнопкой «Применить» и не трогаем market без согласия.
  const refreshCbr = async (autoApply: boolean) => {
    setCbrLoading(true);
    setCbrError(null);
    const r = await fetchCbrRates();
    setCbrLoading(false);
    if (!r) {
      setCbrError("Не удалось получить курсы ЦБ РФ");
      return;
    }
    setCbrRates(r);
    if (autoApply) {
      setMarket((m) => ({ ...m, rub_cny: r.rub_cny, rub_eur: r.rub_eur }));
    }
  };

  useEffect(() => {
    // Если localStorage пуст — применяем сразу. Иначе только показываем.
    const hadSaved = !!loadState();
    refreshCbr(!hadSaved);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyCbr = () => {
    if (!cbrRates) return;
    setMarket((m) => ({ ...m, rub_cny: cbrRates.rub_cny, rub_eur: cbrRates.rub_eur }));
  };

  const ratesDiffer =
    cbrRates !== null &&
    (Math.abs(market.rub_cny - cbrRates.rub_cny) > 0.001 ||
      Math.abs(market.rub_eur - cbrRates.rub_eur) > 0.001);

  // Persist on change
  useEffect(() => {
    saveState({ market, imports, wbRows });
  }, [market, imports, wbRows]);

  const importByName = useMemo(() => {
    const m = new Map<string, ImportItem>();
    for (const it of imports) m.set(it.name, it);
    return m;
  }, [imports]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline gap-4">
        <h1 className="text-xl font-semibold">Калькулятор новинок</h1>
        <span className="text-xs text-muted">
          импорт из Китая → себестоимость → юнит-экономика WB с 4 сценариями НДС
        </span>
      </div>

      <div className="card text-xs text-muted leading-relaxed">
        <div className="font-medium text-white mb-1">Как пользоваться</div>
        <ol className="list-decimal ml-5 space-y-1">
          <li>В блоке <b>Параметры рынка</b> (открой ↓) задай курсы, тарифы WB, ставки НДС/УСН. Сохранятся в браузере.</li>
          <li>В таблице <b>Импорт из Китая</b> добавь товары — габариты, вес, цена в юанях, пошлины. Себестоимость с НДС считается автоматически.</li>
          <li>В таблице <b>WB Калькулятор</b> укажи цену продажи WB. Себестоимость подтянется по совпадению названия (текст в колонке «Наименование» обеих таблиц должен совпадать).</li>
          <li>Справа — 4 сценария НДС. Переключай вкладки сравнения.</li>
        </ol>
        <div className="mt-2 text-warn">
          <Icon name="warning" size={12} className="inline mr-1" />Данные хранятся локально в браузере, не на сервере. Не работает между устройствами и слетит при clear-cache.
        </div>
      </div>

      {/* Баннер курсов ЦБ — появляется если курсы получены и отличаются от текущих */}
      {cbrRates && ratesDiffer && (
        <section className="card flex items-center gap-3 text-xs bg-accent/5 border-accent/30">
          <span>
            <b className="text-accent">Курсы ЦБ РФ на {cbrRates.date}</b>:
            {" "}1 ¥ = <b>{cbrRates.rub_cny.toFixed(4)} ₽</b>,
            {" "}1 € = <b>{cbrRates.rub_eur.toFixed(4)} ₽</b>
            {" "}<span className="text-muted">(сейчас {market.rub_cny.toFixed(2)} / {market.rub_eur.toFixed(2)})</span>
          </span>
          <button className="btn text-xs ml-auto" onClick={applyCbr}>
            Применить курсы ЦБ
          </button>
        </section>
      )}
      {cbrError && (
        <section className="card text-xs text-warn">
          <Icon name="warning" size={12} className="inline mr-1" />{cbrError} — используются ваши значения. Можно повторить через кнопку ↻ в параметрах.
        </section>
      )}

      <ParamsPanel
        market={market}
        onChange={setMarket}
        open={openParams}
        onToggle={() => setOpenParams((x) => !x)}
        cbrRates={cbrRates}
        cbrLoading={cbrLoading}
        onRefreshCbr={() => refreshCbr(false)}
      />

      {/* Таблица «Импорт из Китая» */}
      <section className="card">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold">Импорт из Китая — себестоимость</h2>
          <button
            className="btn text-xs"
            onClick={() => setImports([...imports, blankImport()])}
          >
            + Товар
          </button>
        </div>
        <ImportTable
          items={imports}
          market={market}
          onChange={setImports}
        />
      </section>

      {/* Таблица «WB Калькулятор» */}
      <section className="card">
        <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
          <h2 className="font-semibold">WB Калькулятор — юнит-экономика</h2>
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-xs text-muted">Сценарий НДС:</span>
            {["В1: УСН без НДС", "В2: УСН + НДС 5%", "В3: УСН + НДС 7%", "В4: НДС 22% возврат"].map((label, i) => (
              <button
                key={i}
                className={`btn text-xs ${activeScenario === i ? "border-accent text-accent" : ""}`}
                onClick={() => setActiveScenario(i)}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            className="btn text-xs"
            onClick={() => setWbRows([...wbRows, blankWbRow()])}
          >
            + Строка
          </button>
        </div>
        <WbTable
          rows={wbRows}
          imports={imports}
          importByName={importByName}
          market={market}
          activeScenario={activeScenario}
          onChange={setWbRows}
        />
      </section>
    </div>
  );
}

// ── Params panel ────────────────────────────────────────────────────────

function ParamsPanel({
  market, onChange, open, onToggle,
  cbrRates, cbrLoading, onRefreshCbr,
}: {
  market: MarketParams;
  onChange: (m: MarketParams) => void;
  open: boolean;
  onToggle: () => void;
  cbrRates: CbrRates | null;
  cbrLoading: boolean;
  onRefreshCbr: () => void;
}) {
  return (
    <section className="card">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <button
          className="text-sm font-medium text-left flex items-center gap-2"
          onClick={onToggle}
        >
          <span>Параметры рынка (курсы, тарифы WB, налоги)</span>
          <span className="text-muted">{open ? "▴" : "▾"}</span>
        </button>
        <div className="flex items-center gap-2 text-xs text-muted">
          {cbrRates ? (
            <span title={`ЦБ РФ • USD ${cbrRates.rub_usd.toFixed(4)} ₽`}>
              ЦБ {cbrRates.date}: 1¥={cbrRates.rub_cny.toFixed(2)} 1€={cbrRates.rub_eur.toFixed(2)}
            </span>
          ) : (
            <span>курсы ЦБ не загружены</span>
          )}
          <button
            type="button"
            className="btn text-xs px-2 py-1"
            disabled={cbrLoading}
            onClick={onRefreshCbr}
            title="Запросить актуальные курсы ЦБ РФ"
          >
            {cbrLoading ? "…" : "↻"}
          </button>
        </div>
      </div>
      {open && (
        <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <NumField label="Курс RUB/CNY" v={market.rub_cny} on={(v) => onChange({ ...market, rub_cny: v })} />
          <NumField label="Курс RUB/EUR" v={market.rub_eur} on={(v) => onChange({ ...market, rub_eur: v })} />
          <NumField label="Доставка ₽/кг" v={market.delivery_per_kg} on={(v) => onChange({ ...market, delivery_per_kg: v })} />
          <NumField label="Комиссия перевода %" v={market.payment_fee_pct} on={(v) => onChange({ ...market, payment_fee_pct: v })} />
          <NumField label="НДС вход %" v={market.vat_input_pct} on={(v) => onChange({ ...market, vat_input_pct: v })} />
          <NumField label="К_склада" v={market.k_warehouse} on={(v) => onChange({ ...market, k_warehouse: v })} />
          <NumField label="К_хран" v={market.k_storage} on={(v) => onChange({ ...market, k_storage: v })} />
          <NumField label="К_прием" v={market.k_acceptance} on={(v) => onChange({ ...market, k_acceptance: v })} />
          <NumField label="Индекс лог (ИЛ)" v={market.il} on={(v) => onChange({ ...market, il: v })} step={0.01} />
          <NumField label="ИРП % (платёжный сервис)" v={market.irp_pct} on={(v) => onChange({ ...market, irp_pct: v })} step={0.01} />
          <NumField label="Хранение ₽/л/сут" v={market.storage_per_l_day} on={(v) => onChange({ ...market, storage_per_l_day: v })} step={0.01} />
          <NumField label="УСН ставка %" v={market.usn_rate_pct} on={(v) => onChange({ ...market, usn_rate_pct: v })} />
          <div className="flex flex-col gap-1">
            <span className="text-muted uppercase">УСН тип</span>
            <select
              className="input"
              value={market.usn_type}
              onChange={(e) => onChange({ ...market, usn_type: Number(e.target.value) as 1 | 2 })}
            >
              <option value={1}>Доходы</option>
              <option value={2}>Доходы − Расходы</option>
            </select>
          </div>
          <NumField label="Опции WB %" v={market.wb_options_pct} on={(v) => onChange({ ...market, wb_options_pct: v })} step={0.01} />
          <NumField label="Эквайринг WB %" v={market.wb_acquiring_pct} on={(v) => onChange({ ...market, wb_acquiring_pct: v })} step={0.01} />
          <NumField label="НДС услуг WB %" v={market.wb_vat_pct} on={(v) => onChange({ ...market, wb_vat_pct: v })} />
        </div>
      )}
    </section>
  );
}

function NumField({
  label, v, on, step = 1,
}: { label: string; v: number; on: (x: number) => void; step?: number }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-muted uppercase">{label}</span>
      <input
        type="number"
        className="input"
        step={step}
        value={v}
        onChange={(e) => on(Number(e.target.value))}
      />
    </label>
  );
}

// ── Import table ────────────────────────────────────────────────────────

function ImportTable({
  items, market, onChange,
}: { items: ImportItem[]; market: MarketParams; onChange: (i: ImportItem[]) => void }) {
  const update = (id: string, patch: Partial<ImportItem>) => {
    onChange(items.map((it) => (it.id === id ? { ...it, ...patch } : it)));
  };
  const remove = (id: string) => onChange(items.filter((it) => it.id !== id));

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-xs">
        <thead className="text-muted border-b border-border">
          <tr>
            <th className="text-left p-1.5">Наименование</th>
            <th className="text-left p-1.5">Артикул</th>
            <th className="text-right p-1.5">Д см</th>
            <th className="text-right p-1.5">Ш см</th>
            <th className="text-right p-1.5">В см</th>
            <th className="text-right p-1.5">V л</th>
            <th className="text-right p-1.5">Вес кг</th>
            <th className="text-right p-1.5">Цена ¥</th>
            <th className="text-right p-1.5" title="Пошлина обуви (фикс ставка за шт)">Пошл €/шт</th>
            <th className="text-right p-1.5" title="Пошлина одежды (за кг)">Пошл €/кг</th>
            <th className="text-right p-1.5">Себест без НДС ₽</th>
            <th className="text-right p-1.5">+ Доставка</th>
            <th className="text-right p-1.5">+ Пошлина</th>
            <th className="text-right p-1.5">НДС</th>
            <th className="text-right p-1.5 text-accent">Итого с НДС</th>
            <th className="p-1.5"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const c = computeImport(it, market);
            return (
              <tr key={it.id} className="border-b border-border/40">
                <td className="p-1.5"><Input value={it.name} on={(v) => update(it.id, { name: v })} /></td>
                <td className="p-1.5"><Input value={it.vendor_code || ""} on={(v) => update(it.id, { vendor_code: v })} /></td>
                <td className="p-1.5"><NumIn value={it.length_cm} on={(v) => update(it.id, { length_cm: v })} /></td>
                <td className="p-1.5"><NumIn value={it.width_cm} on={(v) => update(it.id, { width_cm: v })} /></td>
                <td className="p-1.5"><NumIn value={it.height_cm} on={(v) => update(it.id, { height_cm: v })} /></td>
                <td className="p-1.5 text-right text-muted font-mono">{c.volume_l.toFixed(2)}</td>
                <td className="p-1.5"><NumIn value={it.weight_kg} on={(v) => update(it.id, { weight_kg: v })} step={0.01} /></td>
                <td className="p-1.5"><NumIn value={it.cost_cny} on={(v) => update(it.id, { cost_cny: v })} /></td>
                <td className="p-1.5"><NumIn value={it.duty_per_unit_eur} on={(v) => update(it.id, { duty_per_unit_eur: v })} step={0.01} /></td>
                <td className="p-1.5"><NumIn value={it.duty_per_kg_eur} on={(v) => update(it.id, { duty_per_kg_eur: v })} step={0.01} /></td>
                <td className="p-1.5 text-right text-muted font-mono">{fmtRub(c.cost_rub_no_vat)}</td>
                <td className="p-1.5 text-right text-muted font-mono">{fmtRub(c.delivery_rub)}</td>
                <td className="p-1.5 text-right text-muted font-mono">{fmtRub(c.duty_rub)}</td>
                <td className="p-1.5 text-right text-muted font-mono">{fmtRub(c.vat_rub)}</td>
                <td className="p-1.5 text-right text-accent font-medium font-mono">{fmtRub(c.total_with_vat)}</td>
                <td className="p-1.5">
                  <button className="text-error hover:underline" onClick={() => remove(it.id)} title="Удалить"><Icon name="close" size={12} /></button>
                </td>
              </tr>
            );
          })}
          {items.length === 0 && (
            <tr><td colSpan={16} className="text-center text-muted py-3">Нет товаров — нажми «+ Товар»</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── WB table ────────────────────────────────────────────────────────────

function WbTable({
  rows, imports, importByName, market, activeScenario, onChange,
}: {
  rows: WbCalcRow[];
  imports: ImportItem[];
  importByName: Map<string, ImportItem>;
  market: MarketParams;
  activeScenario: number;
  onChange: (r: WbCalcRow[]) => void;
}) {
  const update = (id: string, patch: Partial<WbCalcRow>) => {
    onChange(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };
  const remove = (id: string) => onChange(rows.filter((r) => r.id !== id));

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-xs">
        <thead className="text-muted border-b border-border">
          <tr>
            <th className="text-left p-1.5">Товар (выбрать из «Импорт»)</th>
            <th className="text-right p-1.5">Цена ₽</th>
            <th className="text-right p-1.5" title="Комиссия товарной группы WB (без опций и эквайринга)">Комис %</th>
            <th className="text-right p-1.5" title="Эффективный кВВ = комиссия + опции + эквайринг">кВВ %</th>
            <th className="text-right p-1.5">Выкуп %</th>
            <th className="text-right p-1.5">Оборач дн</th>
            <th className="text-right p-1.5">Продв %</th>
            <th className="text-right p-1.5">Прочие ₽</th>
            <th className="text-right p-1.5 text-muted">V л</th>
            <th className="text-right p-1.5 text-muted">Себест ₽</th>
            <th className="text-right p-1.5 text-muted">Баз.лог</th>
            <th className="text-right p-1.5 text-muted">Лог итого</th>
            <th className="text-right p-1.5 text-muted">Хран</th>
            <th className="text-right p-1.5 text-muted">Комис WB</th>
            <th className="text-right p-1.5">Расход</th>
            <th className="text-right p-1.5">Налог</th>
            <th className="text-right p-1.5 text-accent">Прибыль</th>
            <th className="text-right p-1.5 text-accent">Маржа %</th>
            <th className="text-right p-1.5 text-accent">ROI %</th>
            <th className="p-1.5"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const importItem = importByName.get(r.name) ?? null;
            const c = computeWbRow(r, importItem, market);
            const sc = c.scenarios[activeScenario] || c.scenarios[0];
            return (
              <tr key={r.id} className="border-b border-border/40">
                <td className="p-1.5">
                  <select
                    className="input w-full text-xs"
                    value={r.name}
                    onChange={(e) => update(r.id, { name: e.target.value })}
                  >
                    <option value="">— нет привязки —</option>
                    {imports.map((it) => (
                      <option key={it.id} value={it.name}>{it.name}</option>
                    ))}
                  </select>
                </td>
                <td className="p-1.5"><NumIn value={r.price_rub} on={(v) => update(r.id, { price_rub: v })} /></td>
                <td className="p-1.5"><NumIn value={r.commission_pct} on={(v) => update(r.id, { commission_pct: v })} step={0.1} /></td>
                <td className="p-1.5 text-right text-muted font-mono">{c.kvv_pct.toFixed(2)}</td>
                <td className="p-1.5"><NumIn value={r.buyout_pct} on={(v) => update(r.id, { buyout_pct: v })} /></td>
                <td className="p-1.5"><NumIn value={r.turnover_days} on={(v) => update(r.id, { turnover_days: v })} /></td>
                <td className="p-1.5"><NumIn value={r.promo_pct} on={(v) => update(r.id, { promo_pct: v })} step={0.1} /></td>
                <td className="p-1.5"><NumIn value={r.other_rub} on={(v) => update(r.id, { other_rub: v })} /></td>
                <td className="p-1.5 text-right text-muted font-mono">{c.volume_l.toFixed(2)}</td>
                <td className="p-1.5 text-right text-muted font-mono">{fmtRub(c.full_cost_with_vat)}</td>
                <td className="p-1.5 text-right text-muted font-mono">{fmtRub(c.base_logistics)}</td>
                <td className="p-1.5 text-right text-muted font-mono">{fmtRub(c.logistics_total)}</td>
                <td className="p-1.5 text-right text-muted font-mono">{fmtRub(c.storage)}</td>
                <td className="p-1.5 text-right text-muted font-mono">{fmtRub(c.wb_commission)}</td>
                <td className="p-1.5 text-right font-mono">{fmtRub(sc.expenses_rub)}</td>
                <td className="p-1.5 text-right font-mono">{fmtRub(sc.tax_rub)}</td>
                <td className={`p-1.5 text-right font-medium ${sc.profit_rub >= 0 ? "text-success" : "text-error"}`}>
                  {fmtRub(sc.profit_rub)}
                </td>
                <td className={`p-1.5 text-right ${sc.margin_pct >= 0 ? "text-success" : "text-error"}`}>
                  {fmtPct(sc.margin_pct, 1)}
                </td>
                <td className={`p-1.5 text-right ${sc.roi_pct >= 0 ? "text-success" : "text-error"}`}>
                  {fmtPct(sc.roi_pct, 1)}
                </td>
                <td className="p-1.5">
                  <button className="text-error hover:underline" onClick={() => remove(r.id)} title="Удалить"><Icon name="close" size={12} /></button>
                </td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr><td colSpan={20} className="text-center text-muted py-3">Нет строк — нажми «+ Строка»</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ── Cell editors ────────────────────────────────────────────────────────

function Input({ value, on }: { value: string; on: (v: string) => void }) {
  return (
    <input
      className="input w-full text-xs px-1.5 py-0.5"
      value={value}
      onChange={(e) => on(e.target.value)}
    />
  );
}

function NumIn({
  value, on, step = 1,
}: { value: number; on: (v: number) => void; step?: number }) {
  return (
    <input
      type="number"
      className="input w-20 text-xs px-1.5 py-0.5 text-right"
      step={step}
      value={value}
      onChange={(e) => on(Number(e.target.value))}
    />
  );
}
