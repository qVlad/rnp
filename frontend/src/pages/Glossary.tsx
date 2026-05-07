/**
 * Единый справочник терминов и формул.
 * Anchor-ссылки совпадают с `kpi.key` из API дашборда — клик по ⓘ на
 * KPI-карточке ведёт сюда с #anchor.
 */
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
    id: "margin",
    title: "Маржинальная прибыль",
    unit: "₽",
    formula: "revenue_net − sold_cogs − ad_cost",
    body:
      "Contribution margin: выручка после WB-комиссии минус себестоимость проданных товаров и реклама. НЕ вычитает: OPEX (зарплаты/аренда), налоги, НДС, fixed-costs. Полная прибыль компании — на странице P&L.",
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
      <div>
        <h1 className="text-xl font-semibold">Глоссарий</h1>
        <p className="text-sm text-muted mt-1">
          Что значит каждая метрика на дашборде, как считается и откуда берётся.
        </p>
      </div>

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
