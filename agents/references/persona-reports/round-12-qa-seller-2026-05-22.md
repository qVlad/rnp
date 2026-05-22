# QA + Seller feedback — раунд 12 (2026-05-22)

Reviewer: Claude Opus 4.7 (QA + UX-Validator --as seller).
Метод: чтение кода без запуска прода. Версия в зеркале: v0.27.3 (round 6 release).

## Скан фич

- **TASK-LEAD-042 WeekProfitHero** — Working, есть один gap по reporting_mode + не учитывает RBAC.
- **TASK-LEAD-043 ReconciliationHeroWidget + explainer** — Working, виджет крепкий, explainer внутри `/pnl-reconciliation` развёрнутый. Hero-виджет на дашборде местами слишком оптимистичный («сходятся ✓» когда threshold по умолчанию 1.0%).
- **TASK-LEAD-050 PromoCalculator** — Working, формулы корректные, но velocity_boost у seller'а вызовет паралич выбора + buyout_rate захардкожен в 1.0.
- **TASK-LEAD-055 KPI Breakdown popups** — Working с двумя нюансами (commission на returns знак, truncated «прочее» вывод пустой).

## QA замечания (баги / риски)

| Severity | Фича | Что | Where |
|---|---|---|---|
| P2 | 042 | `WeekProfitHero` всегда дёргает `mode=final` без `reporting_mode` — после деплоя TASK-LEAD-054 toggle operational/financial есть глобально, но hero его игнорирует. Если юзер переключился на financial, остальной дашборд изменит цифры, а Hero-виджет нет — рассинхрон в шапке. | `frontend/src/components/WeekProfitHero.tsx:70-75` |
| P2 | 042 | `lastClosedWeek()` использует `today - 14 days` и откатывает к воскресенью локального TZ браузера. В Калининграде/Владивостоке «прошлая закрытая неделя» сдвинется на день относительно сервера (UTC sale_dt). На границах недели возможен показ Δ=−98% или revenue ≈ 0. | `WeekProfitHero.tsx:22-34` |
| P2 | 042 | Component не учитывает роль: показан **всем** включая manager (видит свой brand-scope net_profit, формулировка «Прибыль за прошлую закрытую неделю» подразумевает компанию). Для bookkeeper'а `/api/dashboard` вернёт 403 — упадёт на error, но Dashboard для bookkeeper'а скрыт в Layout, так что live impact нулевой. Manager — реальное смешение терминов. | `Dashboard.tsx:203` (no role guard) |
| P2 | 042 | Loading-state показывает «— ₽» без skeleton — flicker'ит в noopv6, потом резко меняется на сумму. На медленных запросах (>1с) выглядит как «нет данных, потом появилось». | `WeekProfitHero.tsx:77-84` |
| P3 | 042 | Math для `0 → +X` WoW: если `prevProfit === 0` — wow = null, отображается «—» без объяснения. Стоит подписать «пред. периода нет/0» в caption. | `WeekProfitHero.tsx:93-96` |
| P3 | 042 | `tooltip` собирается строкой и пихается в HTML `title=""` — native browser tooltip часто обрезается / тормозит / не показывает многострочно в Chrome. Лучше использовать существующий компонент-тултип как в `KpiCard`. | `WeekProfitHero.tsx:116-128` |
| P1 | 043 | `ReconciliationHeroWidget` запрашивает `api.pnlReconciliation(4, 1.0)` (threshold 1%), но в `PnLReconciliation.tsx` дефолт юзера 1.0 тоже. ОК. **НО** — `diff.alert` приходит из backend'а уже с применённым threshold (видимо). Если юзер на детальной странице поставит threshold 0.5 — на Hero всё ещё будет «всё сходится ✓». Нет указания «threshold = 1%» в самом виджете. | `ReconciliationHeroWidget.tsx:40, 121-125` |
| P2 | 043 | `q.data?.periods?.[0]` — предполагается DESC sort. Если backend случайно вернёт ASC (мы видели такие баги в audit-mode) — hero виджет покажет неделю годовой давности как «последнюю закрытую». Нет sort guarantee assertion в виджете. | `ReconciliationHeroWidget.tsx:43-45` |
| P3 | 043 | `weeks=4` тащится с фронта, хотя используется только [0]. Лишний overhead (4× больше JOIN'ов на backend'е). Достаточно weeks=1. | `ReconciliationHeroWidget.tsx:40` |
| P3 | 043 | «Δ ≤ 1% — наши цифры сходятся с WB-кабинетом» — для seller'а зелёный чекмарк психологически закрывает вопрос. Но 1% может быть 50-100k ₽ при объёме 5-10М ₽/нед. Стоит дописать «(в пределах ₽X тыс)». | `ReconciliationHeroWidget.tsx:121-125` |
| P2 | 050 | `buyout_rate = 1.0` захардкожено (`promo_calculator.py:387`). Комментарий говорит «velocity уже NET — поэтому buyout_rate номинальный». Но если promo даёт +80% velocity по orders а buyout всё ещё 70% — реальные продажи будут не на 80% больше, а на ~56%. Сделано осознанно как safe-default, но в UI про это никак не объяснено — seller не знает что boost % это про NET-velocity, не про orders. | `promo_calculator.py:387` + `PromoCalculator.tsx:296-316` |
| P2 | 050 | `commission_rate` рассчитывается из `(rev_sale − ppvz_sale) / rev_sale` — это **WB-комиссия + эквайринг** (1.5%). При скидке цена падает, в реальности эквайринг (acquiring_fee_pct ~1.5%) считается от новой цены, а WB-комиссия % остаётся той же ставкой. Сейчас `commission_rate × new_price` — ОК, оба пропорциональны. Но если WB меняет % на акционных товарах (часто бывает скрытое повышение комиссии в акции) — мы это не учитываем. Не баг, но критичная оговорка для seller'а. | `promo_calculator.py:362-366` |
| P3 | 050 | `if commission_rate < 0` — при возвратах больше чем продаж в окне (редко, но бывает на новых SKU) `rev_sale - ppvz_sale` может быть отрицательным → commission_rate cap 0.0 (sanity). Но `avg_price = rev_sale / units_sale` — если в окне только returns → 0 / 0 = пропуск; если sale + большой return → avg_price завышен. Edge case: SKU с одной разовой продажей и потом возвратом другого. | `promo_calculator.py:359` |
| P3 | 050 | Backend N+1 нет (3 запроса: rd, products, cogs). Но без индекса `(nm_id, sale_dt)` на wb_report_detail с большим окном 30d × 200 SKU — может тормозить. Проверить EXPLAIN на проде. | `promo_calculator.py:285-313` |
| P3 | 050 | Frontend для search использует `fetch(...)` напрямую вместо `api.client` — обходит global error handling / auth interceptor. Inconsistent с остальным кодом. | `PromoCalculator.tsx:71` |
| P3 | 050 | `truncated` фичи нет на бэке (returns max 200 SKU из request). Если seller ввёл 200 SKU — `nm_ids` лимит работает (`Field(..., max_length=200)`), но без сообщения «обрезано». | `api/promo_calculator.py:40` |
| P2 | 055 | UI текст про truncated: `«показаны топ-{d.items.length}, остальные {fmtNum(0)} в «прочее»»` — `fmtNum(0)` хардкод. Должно показывать total остального или хотя бы «N штук». Сейчас всегда «остальные 0 в «прочее»» — выглядит как баг. | `MetricBreakdownPopup.tsx:143-147` |
| P2 | 055 | `commission_wb` breakdown для returns: `case (OP_RETURN, -1 × retail × pct / 100)` — комиссия за возврат вычитается из total. Это **противоположно** тому, что делает Dashboard KPI `commission_wb` который суммирует положительные удержания (комиссия за возврат компенсируется WB обратно селлеру, но в управленческом учёте показывается как уменьшение комиссии). Может дать рассинхрон Σ breakdown ≠ KPI `commission_wb`. Стоит сверить с `metrics.py:_final_*_aggregate`. | `kpi_breakdown.py:94-100` |
| P2 | 055 | `BREAKDOWN_KEYS` дублирован в двух местах: `MetricBreakdownPopup.tsx:186-192` (`BREAKDOWN_METRICS` set) и `KpiCard.tsx:67-73` (inline `BREAKDOWN_KEYS` set). Если добавить новую метрику — нужно правки в двух местах, ничего не подскажет о расхождении. | `KpiCard.tsx:67-73` |
| P2 | 055 | Backend `compute_kpi_breakdown` использует `period.end + time.max` (включая, не exclusive). Это расхождение с каноничным `period_aggregates.sale_dt_filter()` который полуоткрытый интервал. Если seller выбрал «текущий день» — может попасть лишняя секунда полуночи следующего дня (с очень большой натяжкой, но всё же drift relative to dashboard KPI). | `kpi_breakdown.py:85-86` |
| P3 | 055 | `outerjoin(Product)` — для SKU без products record (что в нашей multi-tenant модели не должно быть, но защита от мусора в WB-данных) — vendor_code/brand=null. Если manager-фильтр включён → `WHERE Product.brand.in_(brands)` после outerjoin отфильтрует null → правильно. OK. | `kpi_breakdown.py:115-141` |
| P3 | 055 | Тестов нет (искал в `backend/tests/`). Для финансовой фичи где собственник принимает решения по breakdown — рискованно. | (нет файла) |

## UX-as-seller замечания

«Утро, открываю дашборд, что вижу первым?»

| Степень боли | Фича | Что | Что предлагаю |
|---|---|---|---|
| Moderate | 042 | Hero-виджет говорит «Прибыль за прошлую закрытую неделю». Я (seller) психологически жду «сколько я **вчера** заработал». Под виджетом ниже есть TodayVsYesterdayStrip — там как раз вчера. Получается hero отвечает на другой вопрос, и текст «(за прошлую закрытую неделю)» — мелкий, под header'ом. Меняет ожидание уже после того как я увидел сумму. | Сделать заголовок крупнее и однозначнее: «За неделю 12-18 мая (закрыта)». Не использовать слово «прибыль» рядом с «вчера» — путает. |
| Minor | 042 | WoW «+47.3%» зелёный — приятно. Но при низкой базе (пред. неделя = 50к, эта = 200к) собственник может не понять что это статистический шум от просадки прошлой недели, а не реальный рост. | Добавить тип сравнения «vs средняя за 4 недели» как опциональный таб (рядом с WoW). |
| Minor | 042 | Loading «— ₽» опаздывает запрос на 1-2 сек на холодном кэше — собственник видит «—», думает «нет данных, кабинет сломан», pаздражается. | Skeleton-stripe вместо «— ₽», или сразу cached value (stale-while-revalidate). |
| Moderate | 043 | Hero-виджет: «Δ revenue +0.4% ✓ цифры сходятся». Я как seller вижу «✓» и закрываю вопрос. Но 0.4% от моих 8М/нед = 32к — не копейки. Кнопка «Подробнее →» неактивно-выглядящая (`text-xs`), не привлекает. | На hero виджете показывать абсолютную дельту крупным шрифтом тоже («+32к ₽» а не только «+0.4%»). Серый = «в пределах нормы», но цифра видна. |
| Critical | 043 | «Открой подробную сверку чтобы понять причину (неучтённые удержания / задержка sync / ретроспективная корректировка WB)» — я кликаю → попадаю на `/pnl-reconciliation` со списком 12 недель, ищу глазами свою красную → кликаю строку → разворачивается wizard. **3 клика**, и wizard wizard'а не для seller'а а для разработчика (там фразы «синки» / «sync_report_detail» / «supplier_oper_name регистр»). | Hero «Объяснить →» должно сразу открывать развёрнутую строку проблемной недели (deep-link через URL hash `#period=2026-05-12_2026-05-18`). И в wizard убрать разработческие термины — это страница для бухгалтера/seller'а. |
| Moderate | 043 | «Доля выплаты 32%» в Hero отсутствует, есть только Δ revenue. Но для seller'а доля выплаты = «сколько реально пришло на счёт» — важнее чем сходимость с WB. | Добавить компактно в hero третью цифру: «WB выплатит: 32% = 2.5М ₽». Это и есть «сколько я заработал», ради чего seller вообще смотрит дашборд. |
| Critical | 050 | «Ожидаемый рост продаж, %» — слайдер 0-500% с подписью «в среднем WB-акции дают +50…150%». Seller, никогда не запускавший акции, видит слайдер и **парализуется**: «откуда я знаю?». Указание +80% как default — авторитарная подсказка без объяснения. | Добавить tooltip / link «как оценить boost» с короткой методичкой: «если уже участвовал в акциях — посмотри прошлые в /promotions; если впервые — поставь conservative +30% и breakeven boost подскажет минимум». Альтернативно — пресеты «conservative +30% / typical +80% / optimistic +150%». |
| Moderate | 050 | «Breakeven boost» — отличная фича для аналитика, но seller не понимает терминологии. «недостижим» вообще пугает (значит можно проиграть бесконечно?). | Переименовать в «Минимальный рост для break-even» или просто «Минимум для окупаемости». «недостижим» → «не окупится при любом росте → не вступать». |
| Moderate | 050 | Velocity per day показывается двумя цифрами «baseline → new» в одной ячейке. Если seller не понимает «velocity» — это слово может пугать. | Переименовать в «Шт/день». |
| Minor | 050 | После «Симулировать» — кнопка остаётся в той же позиции, table появляется ниже. На laptop-экране форма + хедер съедают экран и table приходится скроллить. UX подсказка: после симуляции форма должна скукожиться (collapsed) или ползунок параметров остаться в sticky-header. | Sticky controls после симуляции, или 2-column layout: form слева 40%, results справа 60%. |
| Moderate | 050 | «Прибыльных SKU: 5/10. Лучше baseline: 3/10» — две цифры одним рядом, без отступа, легко промахнуться какая что. И «лучше baseline» = «лучше чем без акции» — не очевидно. | Разбить на две карточки: «✓ Будут прибыльны: 5 из 10» / «↗ Лучше чем без акции: 3 из 10». Слово «baseline» убрать из UI seller'а. |
| Moderate | 055 | Клик на KPI «Логистика WB» → popup TOP-10 SKU. ОК, понятно. Но total в шапке popup'а = сумма за период, без сравнения «это много/мало». Seller не знает: 200к/нед на логистику — это норма или нет? | Добавить «vs пред. неделя/месяц» в шапку popup'а. Например «+15% к пред. неделе» — даёт контекст. |
| Minor | 055 | Сортировка по умолчанию правильная — DESC по value (top contributor первый). Это OK. Но нет фильтра «показать только убыточные» или «только новые SKU» — для seller'а с 500+ SKU топ-10 это 2-3% картинки. | TOP-10 default OK; добавить slider «показать top-N» или хотя бы expander «показать все». Сейчас limit=10 захардкожен в frontend. |
| Minor | 055 | «(показаны топ-10, остальные 0 в «прочее»)» — баг (см. QA), но даже после фикса фраза «в прочее» странная — куда они «попали»? | «(топ-10 из 47 SKU за период; остальные суммарно X ₽)». |
| Moderate | 055 | Popup закрывается по ESC и клику на overlay — OK. Но **нет ссылки на /units/?nm_id=X** или /pnl?brand= с конкретного SKU. Seller увидел «этот SKU съел 60к на логистику» и хочет сразу копать. | Каждый ряд — клик на nm_id ведёт на /units?nm_id=X (per-SKU drill). Если есть фото в Products — также показать миниатюру (как в PromoCalculator). |

## Что предложить как новые TASK / HYP / BUG

(synthesis работа для Lead/PM/Strategist, не моя — просто список идей)

- **042**: `WeekProfitHero` → respect `reporting_mode` toggle.
- **042**: убрать слово «прибыль» из субзаголовка с временным разрезом «вчера»; альтернативный «vs средняя за 4 недели».
- **043**: deep-link `Объяснить →` сразу на развёрнутую строку проблемной недели; убрать dev-термины из wizard (sync_report_detail / supplier_oper_name).
- **043**: добавить «доля выплаты» (payout/gross) в Hero-виджет 3-й цифрой — это «сколько реально на счёт».
- **043**: показывать абсолютное Δ в ₽ а не только %.
- **050**: пресеты для velocity_boost («conservative/typical/optimistic»), убрать слово «velocity» из UI; ссылка «как оценить».
- **050**: явно объяснять что boost = NET-velocity (после buyout), не orders.
- **050**: переименовать «Breakeven boost» → «Минимум для окупаемости»; «недостижим» → понятная формулировка «не окупится — не вступать».
- **050**: sticky-controls после симуляции / 2-column layout.
- **050**: «Лучше baseline» → «Лучше чем без акции».
- **055**: фикс bug `fmtNum(0)` → реальное число остальных.
- **055**: фикс знак commission на returns (или подтвердить интенцию, добавить unit-test).
- **055**: per-SKU drill-down ссылка из popup на /units?nm_id=X + фото.
- **055**: WoW сравнение в шапке popup'а.
- **055**: dedupe `BREAKDOWN_KEYS` constant.

**HYP candidate (для Product Strategist):**
- HYP: seller'у нужен **«один взгляд» на дашборде вместо 4 виджетов**. WeekProfitHero + ReconciliationHero + TodayVsYesterday + WeeklyChanges — overload «что важнее?». Возможно одна composite-карточка «State of Business» с tabbed view.

## Что отбросить (нет смысла в internal-tool контексте)

- Skeleton-loading polish для 042 — это для SaaS-app fit-and-finish, наш кабинет однопользовательский, разовый flicker терпимый.
- Custom-tooltip компонент для Hero — title="" работает, не критично.
- N+1 / индекс EXPLAIN на promo_calculator — single-tenant, окно макс 30 дней × 200 SKU, не блокер.
- «Conservative/typical/optimistic» как UI-affordance — для internal-tool с одним собственником, который знает свой бизнес, default 80% + slider достаточно. Главное — пояснить что boost про NET-velocity.

## Что чисто (нашёл проверкой, нечего сказать)

- TASK-LEAD-043 explainer внутри `/pnl-reconciliation` (WizardRow) — глубокий, корректный, формулы apples-to-apples (см. комментарий 281-296). Это лучшая часть пакета 042-043-050-055.
- TASK-LEAD-055 RBAC: `current_brands_filter` через Depends в `api/dashboard.py:132` — manager попадёт через brand-фильтр; bookkeeper кидает 403 (узкий scope, нет brand-аналитики) → не доберётся до dashboard вообще.
- TASK-LEAD-050 pure-function `simulate_promo` без БД — testable, разумно изолировано.
- TASK-LEAD-050 sanity caps (discount 0..99, boost 0..1000, duration ≥1) — есть.
- WeekProfitHero корректно скрывается (`return null`) если `curProfit == null` — не блокирует UI на новом кабинете без final-данных.
- ReconciliationHeroWidget правильно gated на director/head в Dashboard.tsx:205.
