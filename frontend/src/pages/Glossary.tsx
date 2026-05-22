/**
 * Единый справочник терминов и формул.
 * Anchor-ссылки совпадают с `kpi.key` из API дашборда — клик по ⓘ на
 * KPI-карточке ведёт сюда с #anchor.
 */
import PageHeader from "@/components/PageHeader";

type Entry = {
  id: string;
  title: string;
  unit?: string;
  formula?: string;
  body: string;
  source?: string;
};

const KPIS: Entry[] = [
  {
    id: "revenue_gross",
    title: "Выручка (gross)",
    unit: "₽",
    formula:
      "preliminary: Σ wb_orders.total_price × (1 − discount/100), активных (non-cancel)\nfinal: Σ wb_report_detail.retail_price_withdisc_rub (Продажа) − Σ ppvz_for_pay (Добровольных компенсаций)",
    body:
      "Сумма заказанных или выкупленных товаров за период. Это «брутто» выручка — до WB-комиссии, логистики, налогов и НДС. Базовая верхняя строка P&L.",
    source: "Preliminary — wb_orders по order_dt; Final — wb_report_detail по sale_dt",
  },
  {
    id: "revenue_net",
    title: "Чистая выручка (forPay)",
    unit: "₽",
    formula: "Σ ppvz_for_pay (продажи) − Σ ppvz_for_pay (возвраты)",
    body:
      "Деньги, которые WB перечислит селлеру по итогам недели (после WB-комиссии, до логистики/хранения/штрафов/налогов). Это НЕ «итог по товарам» из WB-кабинета — там отнимается ещё много чего.",
    source: "preliminary: wb_sales.for_pay; final: wb_report_detail.ppvz_for_pay",
  },
  {
    id: "orders",
    title: "Заказы (активные)",
    unit: "шт",
    formula: "COUNT(*) WHERE NOT is_cancel",
    body:
      "Количество заказов за период без учёта отменённых покупателем. Знаменатель «выкупа» использует ВСЕ заказы (active + cancellations), а не только активные.",
    source: "preliminary: wb_orders по order_dt; final: wb_report_detail.Продажа по sale_dt",
  },
  {
    id: "returns",
    title: "Возвраты",
    unit: "шт",
    formula: "COUNT(*) WHERE is_return = true",
    body: "Сколько товаров вернули покупатели за период. Используется для расчёта выкупа и retention.",
    source: "preliminary: wb_sales.is_return; final: wb_report_detail.Возврат по sale_dt",
  },
  {
    id: "buyout_pct",
    title: "Выкуп",
    unit: "%",
    formula: "(sales − returns) / (orders + cancellations) × 100",
    body:
      "Какой процент заказов покупатели реально выкупили. Знаменатель — ВСЕ заказы за период (включая отменённые покупателем). Эта метрика совпадает с «% выкупа» в WB-кабинете. Норма 30-50%, ниже 35% — порог алёрта.",
    source: "Орёлы из wb_orders + продажи из wb_sales/report_detail",
  },
  {
    id: "ad_cost",
    title: "Реклама (расход)",
    unit: "₽",
    formula: "Σ wb_ad_stats_daily.sum_spent + Σ external_ad_costs.amount",
    body:
      "WB-реклама из advert API + внешний маркетинг (блогеры, инфографика, баннеры, SEO).\n\n⚠ Расхождение с WB-кабинетом: WB финансовый отчёт обычно показывает рекламу на 20-40% больше, потому что включает Boost / WB Промо / промо-инструменты которых нет в /adv/v3/fullstats. Это known issue WB API.",
    source: "wb_ad_stats_daily (WB advert) + external_ad_costs (вручную)",
  },
  {
    id: "drr_pct",
    title: "ДРР (от заказов)",
    unit: "%",
    formula: "ad_cost / revenue_gross × 100",
    body:
      "Доля рекламных расходов от gross-выручки заказов. Используется маркетологами: показывает «сколько % съедает реклама от валовой выручки». Норма ≤ 8%, выше 12% — реклама в убыток.",
  },
  {
    id: "drr_sales_pct",
    title: "ДРР (от выкупов)",
    unit: "%",
    formula: "ad_cost / revenue_net × 100",
    body:
      "Доля рекламных расходов от чистой выручки (после WB-комиссии). Используется финансистом: показывает «сколько % реальных денег уходит на рекламу». Всегда выше чем ДРР от заказов.",
  },
  {
    id: "cpl",
    title: "CPL — стоимость клика",
    unit: "₽",
    formula: "spent / clicks",
    body:
      "Cost Per Lead — средняя стоимость одного клика по рекламному объявлению. Используется на /ads → тепловая карта (TASK-LEAD-033). Считается агрегированно: Σ расход / Σ клики (НЕ среднее средних). Если кликов 0 — null (нет данных).\n\nКуда смотреть: 5-15 ₽ — норма для большинства категорий; >30 ₽ — дорогой трафик, проверь карточку и таргетинг.",
    source: "wb_ad_stats_daily.sum_spent / wb_ad_stats_daily.clicks",
  },
  {
    id: "cps",
    title: "CPS — стоимость заказа",
    unit: "₽",
    formula: "spent / orders",
    body:
      "Cost Per Sale — средняя стоимость одного заказа из рекламы. Считается агрегированно (Σ расход / Σ заказы), не среднее средних. Если заказов 0 — null.\n\nКуда смотреть: должно быть в разы меньше среднего чека. Если CPS > среднего чека — реклама в минус.",
    source: "wb_ad_stats_daily.sum_spent / wb_ad_stats_daily.orders",
  },
  {
    id: "basket_conv",
    title: "Конверсия в корзину (basket conv)",
    unit: "%",
    formula: "atbs / clicks × 100",
    body:
      "Процент людей, которые после клика по рекламе добавили товар в корзину (Add To Basket). Источник — `wb_ad_stats_daily.atbs`. Используется в funnel и /ads → тепловая карта (TASK-LEAD-033).\n\nНорма 5-20%. <5% — карточка или цена не привлекают, >20% — отличный визуал. Если кликов 0 — null.",
    source: "wb_ad_stats_daily.atbs / wb_ad_stats_daily.clicks",
  },
  {
    id: "order_conv",
    title: "Конверсия в заказ (order conv)",
    unit: "%",
    formula: "orders / clicks × 100",
    body:
      "Процент людей, которые после клика по рекламе оформили заказ. Считается агрегированно (Σ заказы / Σ клики).\n\nНорма 1-5%. <1% — карточка плохая или цена не конкурентна, >5% — отличный продукт-маркет фит. Связь с basket_conv: order_conv ≤ basket_conv (заказ не оформляется без корзины).",
    source: "wb_ad_stats_daily.orders / wb_ad_stats_daily.clicks",
  },
  {
    id: "margin",
    title: "Маржинальная прибыль",
    unit: "₽",
    formula: "revenue_net − sold_cogs − ad_cost",
    body:
      "Contribution margin (упрощённый дашбордный): выручка после WB-комиссии минус себестоимость проданных товаров и реклама. НЕ вычитает: OPEX (зарплаты/аренда), налоги, НДС, fixed-costs, прочие WB-удержания (хранение/штрафы). Полная контрибуционная маржа — см. ‘Маржа без операционных расходов’.",
  },
  {
    id: "contribution_margin",
    title: "Маржа без операционных расходов",
    unit: "₽",
    formula:
      "revenue_net − COGS − WB-удержания (комиссия+логистика+хранение+эквайринг+штрафы+удержания) − реклама",
    body:
      "Контрибуционная маржа — прибыль до операционных и фиксированных расходов. Берётся из pnl_builder.profit_from_sales (gross_profit − commercial_expenses).\n\nЧто входит в вычитание: COGS (себестоимость), commission, delivery, storage, penalty, deduction, acquiring, ad_cost (WB+внешний), contractor_fees.\n\nЧто НЕ входит: OPEX (зарплаты, аренда, бухгалтерия), fixed_costs, налоги, НДС. Эти строки добавляются дальше при расчёте net_profit (на странице P&L).\n\nЗачем смотреть: показывает «способна ли матрица товар-канал-цена покрывать постоянные расходы». Норма ≥ 0; если стабильно ниже OPEX/30 — бизнес операционно убыточный.",
  },
  {
    id: "contribution_margin_pct",
    title: "Маржа без OPEX, %",
    unit: "%",
    formula: "contribution_margin / revenue_after_vat × 100",
    body:
      "Контрибуционная маржа в % от чистой выручки (после НДС). Норма 10-30%; ниже — операционные расходы (OPEX + налоги) могут увести бизнес в минус.",
  },
  {
    id: "margin_pct",
    title: "Маржа",
    unit: "%",
    formula: "margin / revenue_net × 100",
    body: "Маржа в % от чистой выручки. Норма для маркетплейса: 5-25%. Меньше 5% — на грани, больше 25% — отлично или что-то не учтено в расходах.",
  },
  {
    id: "roi_pct",
    title: "Рентабельность (ROI)",
    unit: "%",
    formula: "margin / sold_cogs × 100",
    body:
      "Сколько копеек прибыли приносит каждый рубль вложенный в закупку. Для понимания «оборачиваемости денег»:\n• ROI 50% — на каждые 100₽ закупки 50₽ прибыли\n• ROI 100% — удвоение\n• < 30% — низкая, нужно повышать цену или уменьшать COGS\n• > 200% — отличная, можно увеличивать объёмы",
  },
  {
    id: "commission_wb",
    title: "Комиссия WB",
    unit: "₽",
    formula:
      "Σ (retail_price_withdisc_rub − ppvz_for_pay − acquiring_fee) для Продаж\n− та же сумма для Возвратов\n+ Σ acquiring_fee",
    body:
      "Комиссия WB и эквайринг — то что WB удерживает с каждого выкупа. В WB-кабинете показано столбцом «Комиссия WB и эквайринг». Доступно только в Final режиме (источник — wb_report_detail).",
    source: "wb_report_detail",
  },
  {
    id: "logistics_wb",
    title: "Логистика WB",
    unit: "₽",
    formula: "Σ wb_report_detail.delivery_rub",
    body:
      "Расходы на логистику WB за период: доставка до ПВЗ + обратная логистика возвратов. Совпадает со столбцом «Логистика» в WB-кабинете. Доступно только в Final режиме.",
    source: "wb_report_detail.delivery_rub",
  },
  {
    id: "storage_wb",
    title: "Хранение WB",
    unit: "₽",
    formula: "Σ wb_report_detail.storage_fee",
    body:
      "Плата за хранение товара на FBO-складах WB. Если товар лежит долго и не продаётся — растёт. Совпадает со столбцом «Хранение» в WB-кабинете. Доступно только в Final режиме.",
    source: "wb_report_detail.storage_fee",
  },
  {
    id: "payout_to_account",
    title: "Деньги на счёт (Итог по товарам)",
    unit: "₽",
    formula:
      "ppvz_net − логистика − хранение − штрафы − удержания + доплаты\n\nгде ppvz_net = Σ ppvz_for_pay (Продажа) − Σ ppvz_for_pay (Возврат)",
    body:
      "Деньги, которые WB реально переведёт на расчётный счёт за период.\n\nЭто то «что физически придёт на банк». Совпадает со строкой «Итог по товарам» в WB-кабинете.\n\nНе путать с маржинальной прибылью (это после COGS и рекламы) и с чистой выручкой (это до логистики/хранения). Деньги на счёт = промежуточная цифра между ними.\n\nДоступно только в Final режиме.",
    source: "wb_report_detail",
  },
  {
    id: "net_profit",
    title: "Чистая прибыль",
    unit: "₽",
    formula:
      "= revenue_net − все_удержания_WB − COGS − реклама − OPEX − налоги − НДС − fixed_costs",
    body:
      "Финальная прибыль компании после ВСЕХ расходов. Это та цифра, которая остаётся у бизнеса в конце месяца.\n\nВключает в себя: чистую выручку (после WB-комиссии), минус логистику, хранение, штрафы, удержания, COGS, рекламу (WB+внешнюю), OPEX (зарплаты/аренда/прочее), налоги/НДС, fixed_costs.\n\nИсточник — build_pnl() из wb_report_detail, не зависит от режима Preliminary/Final дашборда.\n\nДля менеджера в scope=brands вычитаются только attributable (по nm_id) расходы — это contribution margin вид, OPEX и налоги не вычитаются (они компанейские).\n\nСовпадает со строкой PROFIT на странице /pnl за тот же период.",
  },
  {
    id: "stock_units",
    title: "Остатки (шт)",
    unit: "шт",
    formula: "Σ wb_stocks_snapshot.quantity (последний snapshot)",
    body: "Сколько единиц товара сейчас на складах WB. FBO + FBS объединённо. Snapshot обновляется 2 раза в сутки.",
    source: "wb_stocks_snapshot",
  },
  {
    id: "stock_value",
    title: "Остатки в COGS",
    unit: "₽",
    formula: "Σ (qty × current_cogs)",
    body: "Стоимость остатков в закупочных ценах. Это «замороженный капитал» в товарах. Если остатки большие, а оборот низкий — деньги стоят на складе вместо того чтобы работать.",
  },
];

const CONCEPTS: Entry[] = [
  {
    id: "preliminary-vs-final",
    title: "Preliminary vs Final",
    body:
      "Дашборд может показывать данные из двух источников.\n\n• Preliminary — из wb_orders/wb_sales (advert/statistics API), обновляется каждые 30 мин. Включает «свежие» заказы, часть из которых ещё не выкуплена. Цифры могут быть выше final на 5-15% (preliminary включает потенциальные продажи).\n\n• Final — из wb_report_detail (финальный недельный отчёт WB). Совпадает с WB-кабинетом 1:1. Лаг ~14 дней: WB закрывает неделю по понедельникам.\n\nПереключатель в шапке. Для тренд-анализа лучше preliminary, для бухгалтерии — final.",
  },
  {
    id: "scope-company-brands",
    title: "Scope: Company vs Brands",
    body:
      "P&L и дашборд могут показывать данные либо для всей компании (director / head_of_sales), либо только для брендов конкретного менеджера (brands).\n\nВ scope=brands НЕ показываются: OPEX, fixed_costs, налоги, НДС — они компанейского уровня и не делятся на бренды. Поэтому manager profit > director profit (контракт-маржа выше «полной» прибыли).\n\nНазначение брендов менеджерам — на странице /brands.",
  },
  {
    id: "cogs",
    title: "COGS (себестоимость)",
    body:
      "Себестоимость проданного = закупочная цена + упаковка + фулфилмент. Хранится в таблице с версиями (valid_from): если перезаключили контракт с поставщиком, добавил новую запись, старые остаются — P&L прошлых периодов не пересчитывается.\n\nЕсли у SKU нет COGS — P&L и юнит-экономика для него считают cost=0. Алерт «cogs_missing» на дашборде показывает % торгующих SKU без COGS.\n\nСтраница: /cost-history",
  },
  {
    id: "report-detail",
    title: "wb_report_detail (финансовый отчёт)",
    body:
      "Главный источник финансовых данных. WB присылает 1 раз в неделю по понедельникам отчёт за прошлую неделю (Пн-Вс). Поля: retail_amount, retail_price_withdisc_rub (с учётом СПП), ppvz_for_pay (к выплате), commission, delivery_rub, storage_fee, penalty, deduction, acquiring_fee.\n\nWB-кабинет показывает выгрузку именно из этой таблицы. P&L и страница «Сверка с WB» работают с ней же.",
  },
  {
    id: "reconciliation",
    title: "Сверка с WB (Reconciliation)",
    body:
      "Страница /pnl-reconciliation сравнивает наш P&L с финальным отчётом WB по каждой неделе. Каждая строка — закрытая неделя WB (понедельник→воскресенье).\n\nКолонки «WB:…» — то, что WB прислал в отчёте реализации. Это эталон.\nКолонки «Наша:…» — наш расчёт P&L за тот же период.\n\nГлавная метрика — «Δ Выручка»: расхождение нашей gross-выручки с WB. Если > порога (по умолчанию 1 %) — строка подсвечена красным. Это значит либо синхронизация лажает, либо WB прислал retro-correction.\n\n«Доля выплаты» (payout / gross) — какой % gross-выручки реально дошёл до селлера после WB-удержаний. Норма для маркетплейса 25–40 %; если резко падает — копать в логистику/комиссию/штрафы.",
  },
  {
    id: "supplier_oper_name",
    title: "supplier_oper_name vs doc_type_name",
    body:
      "В wb_report_detail у каждой строки два поля категории. doc_type_name — одно из «Продажа / Возврат / null». supplier_oper_name — детальное (Продажа / Возврат / Логистика / Хранение / Штраф / Возмещение / Лояльность / Добровольная компенсация / ...).\n\nДля «Выкупов» в WB-кабинете используется именно supplier_oper_name='Продажа', и из неё ещё вычитается ppvz_for_pay строк «Добровольная компенсация при возврате» — последние WB относит к «Потери/подмены».",
  },
];

function Item({ e }: { e: Entry }) {
  return (
    <section id={e.id} className="card flex flex-col gap-2 scroll-mt-20">
      <div className="flex items-baseline gap-3 flex-wrap">
        <h2 className="text-lg font-semibold">{e.title}</h2>
        {e.unit && <span className="text-xs text-muted">единица: {e.unit}</span>}
        <a
          href={`#${e.id}`}
          className="ml-auto text-xs text-muted hover:text-accent no-underline"
          title="ссылка на этот раздел"
        >
          #
        </a>
      </div>
      {e.formula && (
        <div className="text-xs font-mono bg-bg border border-border rounded-md p-2 whitespace-pre-line">
          {e.formula}
        </div>
      )}
      <div className="text-sm leading-relaxed whitespace-pre-line">{e.body}</div>
      {e.source && (
        <div className="text-xs text-muted">Источник: {e.source}</div>
      )}
    </section>
  );
}

export default function Glossary() {
  return (
    <div className="flex flex-col gap-4 max-w-4xl">
      <PageHeader
        title="Глоссарий"
        subtitle="Что значит каждая метрика на дашборде, как считается и откуда берётся."
      />

      <nav className="card text-sm flex flex-wrap gap-x-4 gap-y-2">
        <span className="text-muted text-xs uppercase mr-2">KPI:</span>
        {KPIS.map((e) => (
          <a key={e.id} href={`#${e.id}`} className="text-accent no-underline hover:underline">
            {e.title}
          </a>
        ))}
      </nav>

      <h2 className="text-base font-semibold mt-2">Метрики дашборда</h2>
      <div className="flex flex-col gap-3">
        {KPIS.map((e) => (
          <Item key={e.id} e={e} />
        ))}
      </div>

      <h2 className="text-base font-semibold mt-4">Концепции</h2>
      <div className="flex flex-col gap-3">
        {CONCEPTS.map((e) => (
          <Item key={e.id} e={e} />
        ))}
      </div>
    </div>
  );
}
