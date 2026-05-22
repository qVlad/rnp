/**
 * Руководство пользователя — единая точка входа для всей встроенной документации.
 *
 * Side-nav слева; статьи фильтруются по роли пользователя:
 *  - `all`           — видят все три роли
 *  - `manager+`      — manager / head_of_sales / director
 *  - `head+`         — head_of_sales / director (для РОП и выше)
 *  - `director`      — только director
 *
 * Каждая статья — короткий «как это работает» гайд с реальными путями
 * страниц приложения. Глоссарий формул остаётся отдельно на /glossary.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

type RoleGate = "all" | "manager+" | "head+" | "director";

type Article = {
  id: string;
  title: string;
  group: "intro" | "manager" | "head" | "director";
  role: RoleGate;
  body: React.ReactNode;
};

const ROLE_ORDER: Record<string, number> = {
  manager: 1,
  head_of_sales: 2,
  director: 3,
};

function canSee(role: string | undefined, gate: RoleGate): boolean {
  const r = ROLE_ORDER[role ?? ""] ?? 0;
  if (gate === "all") return r >= 1;
  if (gate === "manager+") return r >= 1;
  if (gate === "head+") return r >= 2;
  if (gate === "director") return r >= 3;
  return false;
}

const ARTICLES: Article[] = [
  // ─── Общее (видят все) ─────────────────────────────────────────────
  {
    id: "getting-started",
    title: "Что это за сервис",
    group: "intro",
    role: "all",
    body: (
      <>
        <p>
          SellerFriends — аналитика продаж и финансов на Wildberries для одного селлера.
          Сервис подтягивает данные из WB (orders, sales, отчёт реализации,
          реклама, остатки), считает P&amp;L, ДДС, юнит-экономику, прогноз
          остатков; всё привязано к карточке товара (nm_id) и периоду.
        </p>
        <p>
          Главное правило: <b>WB-кабинет — источник истины</b>. Если наша
          цифра расходится с WB-кабинетом &gt; 1% — это сигнал ошибки синки
          (не повод править вручную). Страница{" "}
          <Link to="/pnl-reconciliation" className="text-accent underline">
            Сверка с WB
          </Link>{" "}
          специально для этого.
        </p>
      </>
    ),
  },
  {
    id: "preliminary-vs-final",
    title: "Preliminary vs Final на дашборде",
    group: "intro",
    role: "all",
    body: (
      <>
        <p>
          Дашборд показывает данные из двух источников — переключатель в шапке:
        </p>
        <ul className="list-disc list-inside space-y-1">
          <li>
            <b>Preliminary</b> — заказы/продажи из WB Statistics API. Обновляется
            каждые 30 мин. Цифры на 5-15% выше final — включает «свежие» заказы,
            часть которых ещё не выкуплена.
          </li>
          <li>
            <b>Final</b> — финальный отчёт реализации (приходит раз в неделю).
            Совпадает с WB-кабинетом в копейку. Лаг ~14 дней.
          </li>
        </ul>
        <p className="text-muted text-sm">
          Для оперативного контроля — preliminary. Для бухгалтерии и сверки —
          final.
        </p>
      </>
    ),
  },
  {
    id: "kpi-help",
    title: "Как читать KPI на дашборде",
    group: "intro",
    role: "all",
    body: (
      <>
        <p>
          Рядом с названием каждого KPI есть значок{" "}
          <code className="text-accent">ⓘ</code>. При наведении — короткая
          формула и пояснение; при клике — переход в полный{" "}
          <Link to="/glossary" className="text-accent underline">
            глоссарий
          </Link>{" "}
          с описанием каждой метрики.
        </p>
        <p>
          Цифры под KPI: процентное изменение к предыдущему периоду такой же
          длины. Зелёный = лучше, красный = хуже. Для метрик «реклама», «ДРР»,
          «возвраты», «комиссии» — наоборот: рост = хуже.
        </p>
      </>
    ),
  },

  // ─── Гайд менеджера ────────────────────────────────────────────────
  {
    id: "manager-scope",
    title: "Менеджер: что вы видите",
    group: "manager",
    role: "manager+",
    body: (
      <>
        <p>
          Если у вас роль <code>manager</code>, в аналитических разделах вы
          видите только данные по своим брендам (назначены{" "}
          <Link to="/brands" className="text-accent underline">
            РОПом или директором
          </Link>
          ). Если назначений нет — все таблицы пустые.
        </p>
        <p>
          <b>P&L в scope=brands</b> показывает contribution-margin (выручка
          бренда − его комиссия/логистика/COGS/реклама). OPEX, налоги, НДС не
          вычитаются — это компанейский уровень, недоступный по брендам.
          Полная чистая прибыль компании видна только у директора/РОПа.
        </p>
      </>
    ),
  },
  {
    id: "manager-workflow",
    title: "Менеджер: ежедневный цикл работы",
    group: "manager",
    role: "manager+",
    body: (
      <>
        <ol className="list-decimal list-inside space-y-2">
          <li>
            <b>Утро</b>: открыть{" "}
            <Link to="/" className="text-accent underline">
              дашборд
            </Link>{" "}
            (preliminary mode) — проверить алёрты в шапке. Падение buyout_pct,
            сток-аут, рост ДРР — реагировать сразу.
          </li>
          <li>
            <Link to="/abc" className="text-accent underline">
              ABC-анализ
            </Link>
            : смотреть «C-категория» — кандидаты на скидку/вывод из ассортимента.
          </li>
          <li>
            <Link to="/supply" className="text-accent underline">
              Поставки
            </Link>
            : сток-аут прогноз. Если SKU в красной зоне (≤14 дней до 0) —
            ставить отгрузку.
          </li>
          <li>
            <Link to="/units" className="text-accent underline">
              Юнит-экономика
            </Link>
            : смотреть рентабельность каждой SKU за последние 30 дней.
            Отрицательная маржа — повод поднять цену или вытащить из рекламы.
          </li>
          <li>
            <Link to="/plans" className="text-accent underline">
              План-Факт
            </Link>
            : чтобы видеть «отстаём от плана / опережаем» по своим брендам.
          </li>
        </ol>
      </>
    ),
  },
  {
    id: "manager-cogs",
    title: "Менеджер: что делать когда COGS пустая",
    group: "manager",
    role: "manager+",
    body: (
      <>
        <p>
          Алёрт «cogs_missing» на дашборде показывает % торгующих SKU без
          себестоимости. Без COGS — P&L и unit-economics показывают «прибыль =
          выручке», что неправда.
        </p>
        <p>
          На странице{" "}
          <Link to="/cost-history" className="text-accent underline">
            Себестоимость
          </Link>{" "}
          для каждой SKU можно увидеть таймлайн COGS. Если по вашим брендам
          есть пробелы — попросите РОПа/директора заполнить (роль{" "}
          <code>manager</code> только читает, CUD только у head/director).
        </p>
      </>
    ),
  },

  // ─── Гайд РОП ──────────────────────────────────────────────────────
  {
    id: "head-overview",
    title: "РОП: что вам доступно",
    group: "head",
    role: "head+",
    body: (
      <>
        <p>
          Роль <code>head_of_sales</code> — полный доступ ко всей аналитике
          компании, плюс CRUD на брендах и финансовых справочниках.{" "}
          <b>Недоступно</b>: управление пользователями, аудит-лог, настройки
          (налоги, токены, JWT). Это уровень директора.
        </p>
        <ul className="list-disc list-inside space-y-1">
          <li>
            P&L / ДДС / Капитализация — в режиме <i>company</i> (полные цифры).
          </li>
          <li>
            <Link to="/brands" className="text-accent underline">
              Бренды
            </Link>{" "}
            — назначаете бренды менеджерам (one-to-one).
          </li>
          <li>
            <Link to="/opex" className="text-accent underline">
              OPEX
            </Link>{" "}
            и{" "}
            <Link to="/external-marketing" className="text-accent underline">
              Внешний маркетинг
            </Link>{" "}
            — ввод расходов вне маркетплейса (зарплаты, аренда, блогеры, фото).
          </li>
          <li>
            <Link to="/revenue-corrections" className="text-accent underline">
              Корректировки выручки
            </Link>{" "}
            — самовыкупы / самозаказы / раздачи / DBS.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "head-brand-assignments",
    title: "РОП: назначение брендов менеджерам",
    group: "head",
    role: "head+",
    body: (
      <>
        <p>
          На странице{" "}
          <Link to="/brands" className="text-accent underline">
            Бренды
          </Link>{" "}
          вы выбираете бренд (из справочника nm_id → brand) и привязываете его к
          конкретному менеджеру. Связь one-to-one: один бренд → один менеджер,
          но один менеджер может вести несколько брендов.
        </p>
        <p>
          После назначения менеджер видит весь nm_id этого бренда в своих
          разделах. Если бренд снять с менеджера — он теряет доступ к
          историческим данным этого бренда мгновенно.
        </p>
        <p className="text-muted text-sm">
          Audit-log пишется на каждое назначение/снятие — директор видит кто
          и когда менял.
        </p>
      </>
    ),
  },
  {
    id: "head-monthly-review",
    title: "РОП: ежемесячный финансовый ритуал",
    group: "head",
    role: "head+",
    body: (
      <>
        <ol className="list-decimal list-inside space-y-2">
          <li>
            До 5-го числа: проверить{" "}
            <Link to="/pnl-reconciliation" className="text-accent underline">
              Сверка с WB
            </Link>{" "}
            за прошлый месяц. Алёртов быть не должно. Если есть — копать (audit-log,
            re-sync report_detail).
          </li>
          <li>
            Внести все{" "}
            <Link to="/opex" className="text-accent underline">
              OPEX
            </Link>{" "}
            за месяц: зарплаты, аренда, бухгалтерия. Не забывать поле{" "}
            <b>Контрагент</b> — оно понадобится для аудита «куда деньги ушли».
          </li>
          <li>
            Внешний маркетинг —{" "}
            <Link to="/external-marketing" className="text-accent underline">
              сюда
            </Link>
            . Блогеры, инфографика, баннеры, фотосессии. Привязка к nm_id или
            бренду — иначе ДРР искажается.
          </li>
          <li>
            Если были раздачи/бартеры —{" "}
            <Link to="/revenue-corrections" className="text-accent underline">
              Корректировки выручки
            </Link>{" "}
            (раздел «Артефакты выручки»). Дата заказа + дата выкупа должны быть
            ≥ 2 дня.
          </li>
          <li>
            Закрыть{" "}
            <Link to="/plans" className="text-accent underline">
              План-Факт
            </Link>{" "}
            — выставить план на следующий месяц по компании / брендам / SKU.
          </li>
          <li>
            Открыть{" "}
            <Link to="/cash-flow" className="text-accent underline">
              ДДС
            </Link>{" "}
            — сверить остаток операционной кассы с банком.
          </li>
        </ol>
      </>
    ),
  },
  {
    id: "head-reconciliation",
    title: "РОП: как пользоваться сверкой с WB",
    group: "head",
    role: "head+",
    body: (
      <>
        <p>
          Открыть{" "}
          <Link to="/pnl-reconciliation" className="text-accent underline">
            Сверка с WB
          </Link>
          . Каждая строка — закрытая неделя. Слева в столбце <i>WB:</i> — что
          присылает финальный отчёт реализации, справа <i>Наша:</i> — что
          посчитала наша P&L за тот же диапазон дат.
        </p>
        <p>
          <b>Кликни на строку</b> — раскроется wizard с пошаговой инструкцией:
          какие поля сличать в xlsx, ссылка прямо в WB-кабинет, таблица «Поле →
          WB → Наша → Δ». Δ &lt; 1 ₽ — норма, &gt; — копать.
        </p>
        <p>
          <b>Норма «Доля выплаты»</b> (payout / gross) = 25-40% для FBO.
          Резкое падение — WB взял больше штрафов/удержаний; рост — снизил
          логистику или коммисию.
        </p>
      </>
    ),
  },
  {
    id: "head-corrections",
    title: "РОП: артефакты выручки vs сторонний канал",
    group: "head",
    role: "head+",
    body: (
      <>
        <p>
          На странице{" "}
          <Link to="/revenue-corrections" className="text-accent underline">
            Корректировки выручки
          </Link>{" "}
          два смысловых блока:
        </p>
        <ul className="list-disc list-inside space-y-1">
          <li>
            <b className="text-warn">Артефакты выручки</b> — самозаказ /
            самовыкуп / раздача. Это <i>фиктивные</i> продажи (накрутка
            рейтинга, бартер). Сумма <b>вычитается</b> из чистой выручки —
            чтобы P&L отражал только реальные деньги.
          </li>
          <li>
            <b className="text-success">Сторонний канал доставки</b> — DBS
            и rFBS. Это <i>реальные</i> продажи через свою логистику, которые
            WB не показывает в /supplier/sales. Сумма <b>добавляется</b> к
            выручке.
          </li>
        </ul>
        <p className="text-muted text-sm">
          Поле «Услуги подрядчика» — оплата агентству / блогеру / фулфилменту.
          Идёт отдельной статьёй в P&L (расход), не уменьшает выручку.
        </p>
      </>
    ),
  },

  // ─── Гайд директора ────────────────────────────────────────────────
  {
    id: "director-full-access",
    title: "Директор: полный доступ",
    group: "director",
    role: "director",
    body: (
      <>
        <p>
          Роль <code>director</code> — единственная, у которой есть:
        </p>
        <ul className="list-disc list-inside space-y-1">
          <li>
            <Link to="/users" className="text-accent underline">
              Пользователи
            </Link>{" "}
            — CRUD аккаунтов (создать, сменить роль, удалить).
          </li>
          <li>
            <Link to="/audit-log" className="text-accent underline">
              Audit log
            </Link>{" "}
            — лог всех изменений финансовых данных (кто/когда/что менял).
          </li>
          <li>
            <Link to="/settings" className="text-accent underline">
              Настройки
            </Link>{" "}
            — налоги (timeline-ставки УСН/ОСНО/НДС), WB-токены, Excel I/O для
            всех справочников.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "director-users",
    title: "Директор: управление пользователями",
    group: "director",
    role: "director",
    body: (
      <>
        <p>
          Три роли с фиксированной иерархией:
        </p>
        <ul className="list-disc list-inside space-y-1">
          <li>
            <code>director</code> — вы. Один на компанию.
          </li>
          <li>
            <code>head_of_sales</code> (РОП) — видит всю аналитику, не видит
            пользователей/настроек/audit. Назначает бренды менеджерам.
          </li>
          <li>
            <code>manager</code> — видит только свои бренды. CUD финансовых
            данных запрещён.
          </li>
        </ul>
        <p>
          Создаёте юзера в{" "}
          <Link to="/users" className="text-accent underline">
            /users
          </Link>
          , даёте ему пароль (он может сам сменить через bcrypt). Сессия — JWT
          в HttpOnly cookie, TTL 12 часов.
        </p>
      </>
    ),
  },
  {
    id: "director-tax-timeline",
    title: "Директор: налоги и timeline-ставки",
    group: "director",
    role: "director",
    body: (
      <>
        <p>
          Налоговые ставки и НДС в{" "}
          <Link to="/settings" className="text-accent underline">
            /settings
          </Link>{" "}
          ведутся как timeline: «с какой даты действует». Если в 2025 году
          перешли с УСН-6% на УСН-15% — заводите две записи, и P&L пересчитает
          историю корректно.
        </p>
        <p>
          Поддержка: USN-income (6%), USN-income-expense (15% + min 1%), OSN
          (25%), patent, NPD, AUSN-income (8%), AUSN-income-expense (20% + min
          3%), none.
        </p>
        <p className="text-muted text-sm">
          На странице P&L две колонки налога:{" "}
          <code>tax</code> — управленческий, и <code>tax_for_fns</code> — по
          методике бухгалтера (для сверки с 1С).
        </p>
      </>
    ),
  },
  {
    id: "director-audit",
    title: "Директор: audit-log — что туда пишется",
    group: "director",
    role: "director",
    body: (
      <>
        <p>
          В{" "}
          <Link to="/audit-log" className="text-accent underline">
            /audit-log
          </Link>{" "}
          пишутся все CUD-операции (create / update / delete) над финансовыми
          справочниками: налоги, OPEX, себестоимость, группы товаров,
          назначения брендов. Для каждой записи виден before/after JSON.
        </p>
        <p>
          Не пишутся (пока): корректировки выручки (artificial_orders),
          внешний маркетинг (external_ad_costs), планы (sales_plans),
          off-platform остатки. План добавить.
        </p>
      </>
    ),
  },
  {
    id: "director-backup-deploy",
    title: "Директор: деплой и бэкапы (для админа)",
    group: "director",
    role: "director",
    body: (
      <>
        <p>
          Каждый деплой делает автоматический pg_dump <i>до</i> накатки
          (`./scripts/remote.sh deploy`). Бэкапы лежат на сервере в{" "}
          <code>/opt/rnp/backups/</code>, бессрочно.
        </p>
        <p>
          Ручной бэкап:{" "}
          <code>./scripts/remote.sh backup &lt;label&gt;</code>. Восстановление:{" "}
          <code>./scripts/remote.sh restore &lt;файл&gt;</code> — перед restore
          скрипт делает ещё один pre-restore бэкап автоматически.
        </p>
        <p className="text-muted text-sm">
          Это вопрос к админу/разработчику, не к директору как пользователю —
          но полезно знать что данные защищены.
        </p>
      </>
    ),
  },
];

const GROUP_LABELS: Record<Article["group"], string> = {
  intro: "Общее",
  manager: "Гайд менеджера",
  head: "Гайд РОП",
  director: "Гайд директора",
};

export default function Docs() {
  const { user } = useAuth();
  const role = user?.role;
  const visible = ARTICLES.filter((a) => canSee(role, a.role));
  const [activeId, setActiveId] = useState<string>(visible[0]?.id ?? "");
  const active = visible.find((a) => a.id === activeId) ?? visible[0];

  // Группируем для side-nav
  const grouped: Record<Article["group"], Article[]> = {
    intro: [],
    manager: [],
    head: [],
    director: [],
  };
  visible.forEach((a) => grouped[a.group].push(a));

  return (
    <div className="flex flex-col lg:flex-row gap-4">
      <aside className="lg:w-64 flex-shrink-0">
        <div className="card flex flex-col gap-3 sticky top-4">
          <div>
            {/* TASK-UI-011: h1 живёт внутри sticky-sidebar (не page-shell),
                PageHeader не подходит — оставлен inline. */}
            <h1 className="text-lg font-semibold">Помощь</h1>
            <div className="text-xs text-muted">
              Вы вошли как <code className="text-accent">{role}</code>
            </div>
          </div>
          {(["intro", "manager", "head", "director"] as Article["group"][]).map(
            (g) =>
              grouped[g].length > 0 && (
                <div key={g}>
                  <div className="text-xs uppercase tracking-wide text-muted mb-1">
                    {GROUP_LABELS[g]}
                  </div>
                  <ul className="flex flex-col">
                    {grouped[g].map((a) => (
                      <li key={a.id}>
                        <button
                          className={`text-left text-sm py-1 px-2 rounded-md w-full ${
                            a.id === active?.id
                              ? "bg-accent/10 text-accent"
                              : "hover:bg-surface-2/50 text-white"
                          }`}
                          onClick={() => setActiveId(a.id)}
                        >
                          {a.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ),
          )}
          <div className="border-t border-border pt-3 text-xs text-muted">
            Формулы и KPI →{" "}
            <Link to="/glossary" className="text-accent underline">
              Глоссарий
            </Link>
          </div>
        </div>
      </aside>

      <article className="card flex-1 max-w-3xl">
        {active ? (
          <>
            <h2 className="text-xl font-semibold mb-3">{active.title}</h2>
            <div className="prose-doc flex flex-col gap-3 text-sm leading-relaxed">
              {active.body}
            </div>
          </>
        ) : (
          <div className="text-muted">Нет доступных разделов для вашей роли.</div>
        )}
      </article>
    </div>
  );
}
