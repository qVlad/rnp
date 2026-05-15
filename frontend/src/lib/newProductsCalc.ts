/**
 * Калькулятор новинок: импорт из Китая + юнит-экономика WB с 4 сценариями НДС.
 *
 * Логика воспроизводит Excel-файл клиента «Расчёт цены на новинки» (2026-05-15).
 * Два уровня:
 *   1. `ImportItem` → CIF-себестоимость товара (юань → ₽ + пошлина + НДС + доставка)
 *   2. `WbCalcRow` → юнит-экономика WB при заданной цене для 4 сценариев НДС
 */

// ── Параметры рынка ─────────────────────────────────────────────────────

export type MarketParams = {
  // Курсы и логистика (Лист «Товар Китай»)
  rub_cny: number;            // RUB/CNY курс
  rub_eur: number;            // RUB/EUR курс
  delivery_per_kg: number;    // ₽/кг автодоставки целой фурой
  payment_fee_pct: number;    // комиссия перевода в %, e.g. 6
  vat_input_pct: number;      // НДС входной % (вход НДС на закуп), e.g. 22

  // Параметры склада WB (Лист «Калькулятор WB» B2:O3)
  k_warehouse: number;        // К_склада (надбавка за регион склада), e.g. 1.8
  k_storage: number;          // К_хран (множитель тарифа хранения), e.g. 1.7
  k_acceptance: number;       // К_прием (платная приёмка коэф), e.g. 0
  il: number;                 // Индекс логистики (ИЛ), e.g. 1.01
  irp_pct: number;            // Индекс расходов на платёжный сервис, как доля цены, e.g. 0.0044
  storage_per_l_day: number;  // тариф хранения ₽/л/сут, e.g. 0.2

  // Налоги и НДС
  usn_rate_pct: number;       // ставка УСН %, e.g. 15
  usn_type: 1 | 2;            // 1 = доходы, 2 = доходы−расходы
  wb_options_pct: number;     // комиссия за опции WB %, e.g. 2.25
  wb_acquiring_pct: number;   // эквайринг %, e.g. 4
  wb_vat_pct: number;         // ставка НДС на услуги WB %, e.g. 20
};

export const DEFAULT_MARKET: MarketParams = {
  rub_cny: 12,
  rub_eur: 100,
  delivery_per_kg: 61,
  payment_fee_pct: 6,
  vat_input_pct: 22,
  k_warehouse: 1.8,
  k_storage: 1.7,
  k_acceptance: 0,
  il: 1.01,
  irp_pct: 0.44,
  storage_per_l_day: 0.2,
  usn_rate_pct: 15,
  usn_type: 2,
  wb_options_pct: 2.25,
  wb_acquiring_pct: 4,
  wb_vat_pct: 20,
};

// ── Импорт из Китая ─────────────────────────────────────────────────────

export type ImportItem = {
  id: string;
  name: string;
  vendor_code?: string;       // артикул поставщика
  length_cm: number;
  width_cm: number;
  height_cm: number;
  weight_kg: number;
  cost_cny: number;
  duty_per_unit_eur: number;  // для обуви (фикс за шт), 0 если не применимо
  duty_per_kg_eur: number;    // для одежды (за кг), 0 если не применимо
};

export type ImportComputed = {
  volume_l: number;           // V л = L×W×H/1000
  cost_rub_no_vat: number;    // юани × курс RUB/CNY × (1 + payment_fee)
  delivery_rub: number;       // weight × delivery_per_kg
  duty_rub: number;           // (duty_per_unit + duty_per_kg×weight) × курс EUR
  total_no_vat: number;       // cost_no_vat + delivery + duty
  vat_rub: number;            // total_no_vat × vat_input_pct/100 (вход НДС)
  total_with_vat: number;     // = total_no_vat + vat_rub
};

export function computeImport(item: ImportItem, p: MarketParams): ImportComputed {
  const volume_l =
    item.length_cm > 0 && item.width_cm > 0 && item.height_cm > 0
      ? (item.length_cm * item.width_cm * item.height_cm) / 1000
      : 0;
  // Excel формула «Товар Китай» col I: =G3*$R$2*(1+$V$2) — но R2/V2 у клиента
  // в формате 12 (курс) и 0.06 (доля комиссии). Мы храним payment_fee_pct=6 и
  // делим на 100 — приводим к той же семантике.
  const cost_rub_no_vat = item.cost_cny * p.rub_cny * (1 + p.payment_fee_pct / 100);
  const delivery_rub = item.weight_kg * p.delivery_per_kg;
  const duty_rub =
    (item.duty_per_unit_eur + item.duty_per_kg_eur * item.weight_kg) * p.rub_eur;
  const total_no_vat = cost_rub_no_vat + delivery_rub + duty_rub;
  const vat_rub = (total_no_vat * p.vat_input_pct) / 100;
  return {
    volume_l: round2(volume_l),
    cost_rub_no_vat: round2(cost_rub_no_vat),
    delivery_rub: round2(delivery_rub),
    duty_rub: round2(duty_rub),
    total_no_vat: round2(total_no_vat),
    vat_rub: round2(vat_rub),
    total_with_vat: round2(total_no_vat + vat_rub),
  };
}

// ── WB юнит-экономика с 4 сценариями НДС ────────────────────────────────

export type WbCalcRow = {
  id: string;
  name: string;               // matches ImportItem.name (link)
  price_rub: number;          // цена со скидкой продавца ₽ (без СПП — то что WB отображает покупателю)
  commission_pct: number;     // комиссия товарной группы (e.g. 37)
  buyout_pct: number;         // % выкупа, e.g. 30..100
  turnover_days: number;      // оборачиваемость в днях
  promo_pct: number;          // % на продвижение, e.g. 3
  other_rub: number;          // прочие ₽ на 1 единицу
};

export type ScenarioBreakdown = {
  name: string;
  vat_outgoing_rub: number;   // выделенный НДС из цены (для сценариев V2/V3/V4)
  expenses_rub: number;       // полный расход за единицу
  profit_before_tax: number;
  tax_rub: number;
  profit_rub: number;
  margin_pct: number;         // прибыль / цена × 100
  roi_pct: number;            // прибыль / полная себестоимость × 100
};

export type WbCalcComputed = {
  volume_l: number;
  full_cost_no_vat: number;   // total_no_vat из импорта
  full_cost_with_vat: number; // total_with_vat
  base_logistics: number;     // ₽ за единицу по таблице V
  kvv_pct: number;            // commission + опции + эквайринг = эффективный кВВ
  wb_commission: number;
  logistics_total: number;
  storage: number;
  acceptance: number;
  promo: number;
  // Сценарии:
  scenarios: ScenarioBreakdown[];
};

// Тариф WB логистики по объёму (Excel: формула col N row 8)
// =IF(D<=0.2,23, IF(D<=0.4,26, IF(D<=0.6,29, IF(D<=0.8,30, IF(D<=1,32, 46+(D-1)*14)))))
export function baseLogisticsByVolume(volume_l: number): number {
  if (volume_l <= 0) return 0;
  if (volume_l <= 0.2) return 23;
  if (volume_l <= 0.4) return 26;
  if (volume_l <= 0.6) return 29;
  if (volume_l <= 0.8) return 30;
  if (volume_l <= 1.0) return 32;
  return 46 + (volume_l - 1) * 14;
}

export function computeWbRow(
  row: WbCalcRow,
  importItem: ImportItem | null,
  p: MarketParams,
): WbCalcComputed {
  const imp = importItem ? computeImport(importItem, p) : null;
  const volume_l = imp?.volume_l ?? 0;
  const full_cost_no_vat = imp?.total_no_vat ?? 0;
  const full_cost_with_vat = imp?.total_with_vat ?? 0;
  const vat_input = imp?.vat_rub ?? 0;

  const base_log = baseLogisticsByVolume(volume_l);
  const kvv_pct = row.commission_pct + p.wb_options_pct + p.wb_acquiring_pct;

  const wb_commission = row.price_rub > 0 ? (row.price_rub * kvv_pct) / 100 : 0;

  // Логистика итого (Excel col P8):
  //   = (Баз_лог × К_склада × ИЛ + Цена × ИРП%) × (100 / выкуп%)
  //     + Баз_лог × (100−выкуп)/выкуп × некий коэф (в Excel — *0 фактически,
  //     но мы для надёжности используем формулу с возвратной логистикой)
  // Упрощённо: ((баз × К × ИЛ) + (цена × ИРП/100)) × 100/выкуп.
  const buyout_share = row.buyout_pct > 0 ? row.buyout_pct / 100 : 1;
  const logistics_total =
    ((base_log * p.k_warehouse * p.il) + (row.price_rub * p.irp_pct) / 100) /
    Math.max(buyout_share, 0.01);

  // Хранение (Excel col Q): тариф × V × К_хран × оборачиваемость
  const storage = p.storage_per_l_day * volume_l * p.k_storage * row.turnover_days;
  // Платная приёмка (Excel col R): 1.7 × V × К_прием
  const acceptance = 1.7 * volume_l * p.k_acceptance;
  // Продвижение (Excel col S): цена × promo%
  const promo = (row.price_rub * row.promo_pct) / 100;

  // ── 4 сценария НДС ────────────────────────────────────────────────
  // V1: УСН без НДС. Расход = комиссия + лог + хран + приём + продв +
  //     полная себестоимость С НДС + прочие
  // V2: УСН + НДС 5% невозвр. Так же, но из цены выделяется 5/105
  // V3: УСН + НДС 7%. Так же, выделение 7/107
  // V4: НДС 22% возврат с зачётом услуг WB. Цена − выделенный НДС 22% =
  //     налогооблагаемая база; расход берёт себестоимость БЕЗ входного НДС
  //     (он возвращается); НДС WB на услуги тоже зачитывается

  const scenarios: ScenarioBreakdown[] = [];

  const baseExpense =
    wb_commission + logistics_total + storage + acceptance + promo +
    full_cost_with_vat + row.other_rub;

  // V1 — УСН без НДС
  {
    const expenses = baseExpense;
    const profit_before_tax = row.price_rub - expenses;
    const tax = computeUsnTax(row.price_rub, expenses, p);
    const profit = profit_before_tax - tax;
    scenarios.push({
      name: "В1: УСН без НДС",
      vat_outgoing_rub: 0,
      expenses_rub: round2(expenses),
      profit_before_tax: round2(profit_before_tax),
      tax_rub: round2(tax),
      profit_rub: round2(profit),
      margin_pct: row.price_rub > 0 ? round2((profit / row.price_rub) * 100) : 0,
      roi_pct:
        full_cost_with_vat > 0 ? round2((profit / full_cost_with_vat) * 100) : 0,
    });
  }
  // V2 — УСН + НДС 5%
  {
    const vat_out = (row.price_rub * 5) / 105;
    const expenses = baseExpense;
    // База налога для УСН-д-р: (цена − vat_out) − расходы
    const base_for_tax = Math.max(0, row.price_rub - vat_out - expenses);
    const tax = p.usn_type === 1
      ? Math.max(0, row.price_rub - vat_out) * (p.usn_rate_pct / 100)
      : base_for_tax * (p.usn_rate_pct / 100);
    const profit = row.price_rub - expenses - vat_out - tax;
    scenarios.push({
      name: "В2: УСН + НДС 5%",
      vat_outgoing_rub: round2(vat_out),
      expenses_rub: round2(expenses),
      profit_before_tax: round2(row.price_rub - expenses - vat_out),
      tax_rub: round2(tax),
      profit_rub: round2(profit),
      margin_pct: row.price_rub > 0 ? round2((profit / row.price_rub) * 100) : 0,
      roi_pct:
        full_cost_with_vat > 0 ? round2((profit / full_cost_with_vat) * 100) : 0,
    });
  }
  // V3 — УСН + НДС 7%
  {
    const vat_out = (row.price_rub * 7) / 107;
    const expenses = baseExpense;
    const base_for_tax = Math.max(0, row.price_rub - vat_out - expenses);
    const tax = p.usn_type === 1
      ? Math.max(0, row.price_rub - vat_out) * (p.usn_rate_pct / 100)
      : base_for_tax * (p.usn_rate_pct / 100);
    const profit = row.price_rub - expenses - vat_out - tax;
    scenarios.push({
      name: "В3: УСН + НДС 7%",
      vat_outgoing_rub: round2(vat_out),
      expenses_rub: round2(expenses),
      profit_before_tax: round2(row.price_rub - expenses - vat_out),
      tax_rub: round2(tax),
      profit_rub: round2(profit),
      margin_pct: row.price_rub > 0 ? round2((profit / row.price_rub) * 100) : 0,
      roi_pct:
        full_cost_with_vat > 0 ? round2((profit / full_cost_with_vat) * 100) : 0,
    });
  }
  // V4 — НДС 22% возвратный (с зачётом услуг WB)
  {
    const vat_out = (row.price_rub * 22) / 122;
    // НДС услуг WB можно зачесть (Excel col AK):
    //   (комиссия × (100 − k_vat_wb)/100 + продвижение) × 22/122
    const wb_services_vat =
      ((wb_commission * (100 - p.wb_vat_pct)) / 100 + promo) * (22 / 122);
    const vat_to_pay = Math.max(0, vat_out - vat_input - wb_services_vat);
    // Расход без входного НДС (он возвращается)
    const expenses_no_input_vat =
      wb_commission + logistics_total + storage + acceptance + promo +
      full_cost_no_vat + row.other_rub - wb_services_vat;
    const base_for_tax = Math.max(0, row.price_rub - vat_out - expenses_no_input_vat);
    const tax = p.usn_type === 1
      ? Math.max(0, row.price_rub - vat_out) * (p.usn_rate_pct / 100)
      : base_for_tax * (p.usn_rate_pct / 100);
    const profit = row.price_rub - expenses_no_input_vat - vat_out - tax;
    scenarios.push({
      name: "В4: НДС 22% возвратный",
      vat_outgoing_rub: round2(vat_to_pay),
      expenses_rub: round2(expenses_no_input_vat),
      profit_before_tax: round2(row.price_rub - expenses_no_input_vat - vat_out),
      tax_rub: round2(tax),
      profit_rub: round2(profit),
      margin_pct: row.price_rub > 0 ? round2((profit / row.price_rub) * 100) : 0,
      roi_pct:
        full_cost_no_vat > 0 ? round2((profit / full_cost_no_vat) * 100) : 0,
    });
  }

  return {
    volume_l,
    full_cost_no_vat,
    full_cost_with_vat,
    base_logistics: round2(base_log),
    kvv_pct: round2(kvv_pct),
    wb_commission: round2(wb_commission),
    logistics_total: round2(logistics_total),
    storage: round2(storage),
    acceptance: round2(acceptance),
    promo: round2(promo),
    scenarios,
  };
}

function computeUsnTax(price: number, expenses: number, p: MarketParams): number {
  const rate = p.usn_rate_pct / 100;
  if (p.usn_type === 1) return Math.max(0, price) * rate;
  // д-р: max(0, цена − расходы) × ставка
  return Math.max(0, price - expenses) * rate;
}

function round2(x: number): number {
  return Math.round(x * 100) / 100;
}

// ── Курсы ЦБ РФ ─────────────────────────────────────────────────────────

export type CbrRates = {
  date: string;          // ISO дата выгрузки ЦБ (например, "2026-05-15")
  rub_cny: number;       // RUB за 1 CNY
  rub_eur: number;       // RUB за 1 EUR
  rub_usd: number;       // RUB за 1 USD (для информации)
};

/**
 * Загружает официальные курсы ЦБ РФ на сегодня (или последний рабочий день).
 * Endpoint: https://www.cbr-xml-daily.ru/daily_json.js — публичный JSON
 * без auth и с CORS-доступом. Кешируется ЦБ на 1 час; обновляется ~11:30 МСК.
 *
 * Возвращает null при сетевой ошибке — caller должен использовать прежние
 * значения и показать пользователю что-то типа «не удалось обновить курсы».
 */
export async function fetchCbrRates(): Promise<CbrRates | null> {
  try {
    const resp = await fetch("https://www.cbr-xml-daily.ru/daily_json.js", {
      // Не отправляем cookies, не нужны
      credentials: "omit",
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    const v = data?.Valute ?? {};
    const get = (code: string): number => {
      const e = v[code];
      if (!e || !e.Value || !e.Nominal) return 0;
      return Number(e.Value) / Number(e.Nominal);
    };
    const rub_cny = get("CNY");
    const rub_eur = get("EUR");
    const rub_usd = get("USD");
    if (rub_cny <= 0 || rub_eur <= 0) return null;
    // Date format: "2026-05-15T11:30:00+03:00"
    const date = String(data?.Date || "").slice(0, 10) || new Date().toISOString().slice(0, 10);
    return {
      date,
      rub_cny: Math.round(rub_cny * 10000) / 10000,
      rub_eur: Math.round(rub_eur * 10000) / 10000,
      rub_usd: Math.round(rub_usd * 10000) / 10000,
    };
  } catch {
    return null;
  }
}

// ── localStorage persistence ───────────────────────────────────────────

const LS_KEY = "rnp_new_products_state_v1";

export type NewProductsState = {
  market: MarketParams;
  imports: ImportItem[];
  wbRows: WbCalcRow[];
};

export function loadState(): NewProductsState | null {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as NewProductsState;
  } catch {
    return null;
  }
}

export function saveState(s: NewProductsState): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(s));
  } catch {
    // ignore (quota / private mode)
  }
}
