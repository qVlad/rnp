/**
 * Юнит-экономика "what-if" — чистая функция расчёта без побочных эффектов.
 *
 * Логика согласована с pnl_builder.py:
 *   - НДС извлекается из выручки если плательщик НДС
 *   - Комиссия WB / эквайринг считаются от gross-выручки (с НДС)
 *   - Налог УСН/АУСН считается от выручки без НДС
 *   - Маржа = выручка_без_НДС − все_расходы − налог
 */

export interface CalcInput {
  // Цена
  price: number;                 // цена для покупателя (то что он платит, с НДС если есть)
  // Категория
  commission_pct: number;        // % комиссии WB
  acquiring_pct: number;         // % эквайринга (обычно 1.5)
  // Логистика
  logistics_per_unit: number;    // ₽ за единицу (среднее, обе стороны)
  buyout_pct: number;            // % выкупа: 100 = идеал, реально 60-80
  // Себестоимость
  cost_rub: number;
  packaging_rub: number;
  fulfillment_rub: number;
  // Маркетинг
  marketing_per_unit: number;
  // Налоги
  tax_system: string;
  tax_rate: number;
  tax_min_rate: number;
  reduce_by_insurance: boolean;
  // НДС
  vat_payer: boolean;
  vat_rate: number;
  // MAX-калькуляторы (опционально, для расчёта границ рекламы по 10X-методике).
  // Если не заданы — соответствующие max_* поля = 0.
  organic_pct?: number;            // % заказов из органики (без рекламы); рекламные затраты «размазываются» только по платным
  cart_conversion_pct?: number;    // конверсия клик→корзина, %
  order_conversion_pct?: number;   // конверсия корзина→заказ, %
  target_margin_pct?: number;      // желаемая маржа после маркетинга, % от revenue_net_vat (для расчёта MAX-цен)
}

export interface CalcOutput {
  revenue_gross: number;         // = price (то что платит покупатель)
  vat: number;                   // выделенный НДС
  revenue_net_vat: number;       // выручка без НДС
  wb_commission: number;
  acquiring: number;
  logistics_effective: number;   // logistics_per_unit с поправкой на выкуп
  total_cogs: number;            // cost+packaging+fulfillment
  marketing: number;
  total_expenses: number;        // все, кроме налога
  profit_before_tax: number;
  tax: number;
  margin: number;                // = profit_before_tax − tax
  margin_pct: number;            // от revenue_net_vat
  roi_pct: number;               // от total_cogs
  drr_pct: number;               // marketing / revenue_gross
  break_even_price: number;      // цена с НДС, при которой маржа = 0
  // MAX-границы для управления рекламой (10X-методика).
  // Все «работают в 0» при target_margin_pct (по умолчанию 0% — break-even);
  // дальше своих значений = убыток на единицу.
  max_marketing_per_order: number; // ₽ — максимум маркетинга на 1 заказ (≈ выкуп) до target_margin
  max_cpc: number;                 // ₽ за клик; учитывает organic% (бесплатные клики не «съедают» бюджет)
  max_cpm: number;                 // ₽ за 1000 показов
  max_basket_price: number;        // ₽ — макс цена за добавление в корзину
  max_order_price: number;         // ₽ — макс цена за заказ
  max_buyout_price: number;        // ₽ — макс цена за выкуп (учитывая % выкупа)
}

const safe = (x: number | undefined | null): number =>
  typeof x === "number" && Number.isFinite(x) ? x : 0;

function computeTax(
  system: string,
  revenue_after_vat: number,
  expenses: number,
  rate: number,
  min_rate: number,
  reduceByInsurance: boolean,
): number {
  const r = rate / 100;
  switch (system) {
    case "usn_income":
    case "ausn_income": {
      let tax = Math.max(0, revenue_after_vat) * r;
      if (reduceByInsurance && system === "usn_income") tax *= 0.5;
      return tax;
    }
    case "usn_income_expense":
    case "ausn_income_expense": {
      const base = Math.max(0, revenue_after_vat - expenses);
      const tax = base * r;
      const min = Math.max(0, revenue_after_vat) * (min_rate / 100);
      return Math.max(tax, min);
    }
    case "osn":
      return Math.max(0, revenue_after_vat - expenses) * r;
    case "npd":
      return Math.max(0, revenue_after_vat) * r;
    case "patent":
    case "none":
    default:
      return 0;
  }
}

export function computeUnitEconomics(input: CalcInput): CalcOutput {
  const price = safe(input.price);
  const buyout = Math.max(0, Math.min(100, input.buyout_pct || 100)) / 100;

  // VAT extraction
  const vat =
    input.vat_payer && input.vat_rate > 0
      ? price - price / (1 + input.vat_rate / 100)
      : 0;
  const revenue_net_vat = price - vat;

  // WB commission (от gross-цены, как WB её и удерживает)
  const wb_commission = price * (input.commission_pct / 100);
  const acquiring = price * (input.acquiring_pct / 100);

  // Логистика — на 100% заказов, выкуп влияет только на возврат:
  // если buyout=70%, то 30% возвращаются, для них логистика тоже платная (грубо, x2 за рейс).
  // Эффективная логистика = logistics * (1 + (1-buyout)) = logistics * (2 - buyout).
  // Но это упрощение; реальная WB-логистика сложнее. Делаем opt-in: если buyout=100, без надбавки.
  const logistics_effective = input.logistics_per_unit * (2 - buyout);

  const total_cogs =
    safe(input.cost_rub) + safe(input.packaging_rub) + safe(input.fulfillment_rub);
  const marketing = safe(input.marketing_per_unit);

  const total_expenses =
    wb_commission + acquiring + logistics_effective + total_cogs + marketing;

  const profit_before_tax = revenue_net_vat - total_expenses;

  const tax = computeTax(
    input.tax_system,
    revenue_net_vat,
    total_expenses,
    input.tax_rate,
    input.tax_min_rate,
    input.reduce_by_insurance,
  );

  const margin = profit_before_tax - tax;
  const margin_pct = revenue_net_vat > 0 ? (margin / revenue_net_vat) * 100 : 0;
  const roi_pct = total_cogs > 0 ? (margin / total_cogs) * 100 : 0;
  const drr_pct = price > 0 ? (marketing / price) * 100 : 0;

  // break-even: при какой цене (с НДС) margin = 0?
  // Решаем относительно price. Многие расходы пропорциональны цене (commission, acquiring,
  // VAT extraction), остальные фиксированы. Подбираем итеративно через бинарный поиск.
  const break_even_price = findBreakEven(input);

  // ── MAX-границы рекламы (10X-методика) ─────────────────────────────────────
  // Логика: «макс маркетинга на 1 ЗАКАЗ при которой ещё есть target_margin».
  // Расходы без маркетинга: wb_commission + acquiring + logistics_eff + cogs.
  // target_margin_amt = revenue_net_vat × target_margin_pct/100.
  // max_marketing_per_order = revenue_net_vat − налог(приближённо) − все_остальные_расходы − target_margin_amt.
  // Налог берём от текущего расчёта чтобы не подвисал второй биссекшен. Если
  // система — «доходы», налог не меняется от рекламы; если «доходы−расходы» —
  // изменится незначительно, и для MAX-калькулятора это приемлемая
  // погрешность (1-2 ₽).
  const target_margin_pct_v = safe(input.target_margin_pct) || 0;
  const target_margin_amt = (revenue_net_vat * target_margin_pct_v) / 100;
  const expenses_without_marketing = wb_commission + acquiring + logistics_effective + total_cogs;
  const max_marketing_per_order = Math.max(
    0,
    revenue_net_vat - expenses_without_marketing - tax - target_margin_amt,
  );

  // % органики — какая доля заказов приходит без рекламы. Если organic=25%,
  // то рекламный бюджет «распределяется» только на 75% платных. Поэтому
  // допустимый платный CPC выше: max_paid = max_per_order / (1 - organic).
  const organic_v = Math.max(0, Math.min(100, safe(input.organic_pct))) / 100;
  const paid_share = Math.max(0.01, 1 - organic_v); // защита от деления на 0
  const max_marketing_per_paid_order = max_marketing_per_order / paid_share;

  // Maxes от per-paid-order через конверсии. Если конверсии не указаны — оставляем 0.
  const cart_conv = Math.max(0, Math.min(100, safe(input.cart_conversion_pct))) / 100;
  const order_conv = Math.max(0, Math.min(100, safe(input.order_conversion_pct))) / 100;
  const buyout_ratio = buyout; // уже [0..1]

  // max_buyout_price (МАХ за выкуп): прямо равен max_marketing_per_order × выкуп
  const max_buyout_price = max_marketing_per_order * buyout_ratio;
  // max_order_price (МАХ за заказ): max_marketing_per_paid_order
  const max_order_price = max_marketing_per_paid_order;
  // max_basket_price: order × order_conv (заказ из корзины); если order_conv не задан — 0
  const max_basket_price = order_conv > 0 ? max_order_price * order_conv : 0;
  // max_cpc = basket × cart_conv (корзина из клика)
  const max_cpc = cart_conv > 0 && max_basket_price > 0 ? max_basket_price * cart_conv : 0;
  // max_cpm: 1000 показов × max_cpc если CTR известен (через cart_conv не считаем,
  // пользователь обычно знает CTR отдельно). Возвращаем 0 если CTR не оценим.
  // Для простоты приближаем CPM = CPC × CTR × 1000 — у нас CTR не введён, считаем как 0.
  const max_cpm = 0;

  return {
    revenue_gross: price,
    vat,
    revenue_net_vat,
    wb_commission,
    acquiring,
    logistics_effective,
    total_cogs,
    marketing,
    total_expenses,
    profit_before_tax,
    tax,
    margin,
    margin_pct,
    roi_pct,
    drr_pct,
    break_even_price,
    max_marketing_per_order,
    max_cpc,
    max_cpm,
    max_basket_price,
    max_order_price,
    max_buyout_price,
  };
}

function findBreakEven(input: CalcInput): number {
  // Бинарный поиск цены (от 0 до 10×total_cogs+max(1)) при которой margin = 0.
  // Если уже maximum_price даёт margin < 0 — товар нельзя сделать прибыльным
  // при текущих параметрах.
  const cogs =
    safe(input.cost_rub) + safe(input.packaging_rub) + safe(input.fulfillment_rub);
  const lo = 0;
  const hi = Math.max(cogs * 10, 1000) + input.logistics_per_unit * 2 + input.marketing_per_unit;
  const ITER = 60;

  let l = lo,
    r = hi;
  for (let i = 0; i < ITER; i++) {
    const mid = (l + r) / 2;
    const m = computeMarginOnly({ ...input, price: mid });
    if (m < 0) l = mid;
    else r = mid;
  }
  return r;
}

// Lightweight margin-only helper to avoid recursion through computeUnitEconomics.
function computeMarginOnly(input: CalcInput): number {
  const price = safe(input.price);
  const buyout = Math.max(0, Math.min(100, input.buyout_pct || 100)) / 100;
  const vat =
    input.vat_payer && input.vat_rate > 0
      ? price - price / (1 + input.vat_rate / 100)
      : 0;
  const revenue_net_vat = price - vat;
  const wb_commission = price * (input.commission_pct / 100);
  const acquiring = price * (input.acquiring_pct / 100);
  const logistics_effective = input.logistics_per_unit * (2 - buyout);
  const total_cogs =
    safe(input.cost_rub) + safe(input.packaging_rub) + safe(input.fulfillment_rub);
  const marketing = safe(input.marketing_per_unit);
  const total_expenses =
    wb_commission + acquiring + logistics_effective + total_cogs + marketing;
  const tax = computeTax(
    input.tax_system,
    revenue_net_vat,
    total_expenses,
    input.tax_rate,
    input.tax_min_rate,
    input.reduce_by_insurance,
  );
  return revenue_net_vat - total_expenses - tax;
}
