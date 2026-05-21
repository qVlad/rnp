/**
 * Сайдбар-навигация (P1.2 из UI_UX_AUDIT.md).
 *
 * Слева — 240px sidebar с группами пунктов; cвернуть до 60px по
 * горячей клавише `[`. Активный пункт: accent border-left. Группы —
 * uppercase faint label'ы.
 */
import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import VersionBadge from "@/components/VersionBadge";
import { Icon, IconName } from "@/components/Icon";
import CommandPalette from "@/components/CommandPalette";
import SyncStatusIndicator from "@/components/SyncStatusIndicator";
import ManagerBrandsBanner from "@/components/ManagerBrandsBanner";
import ToastHost from "@/components/ToastHost";

type Link = {
  to: string;
  label: string;
  end?: boolean;
  directorOnly?: boolean;
  directorOrHead?: boolean;
  // TASK-LEAD-040 frontend: whitelist для bookkeeper-роли. Без флага пункт
  // скрыт для bookkeeper'а (безопаснее blacklist — новые pages по default
  // скрыты, явно открываются здесь).
  bookkeeperOk?: boolean;
  icon?: IconName;
};

type Group = { label: string; items: Link[] };

const GROUPS: Group[] = [
  {
    label: "Обзор",
    items: [
      { to: "/", label: "Дашборд", end: true, icon: "layers" },
      { to: "/pnl", label: "P&L", icon: "list" },
      { to: "/pnl-reconciliation", label: "Сверка с WB", icon: "check" },
      { to: "/reconciliation-4way", label: "4-way Сверка", icon: "check", directorOrHead: true },
      { to: "/audit", label: "Аудит-режим", icon: "check", directorOrHead: true, bookkeeperOk: true },
    ],
  },
  {
    label: "Налоги и деньги",
    items: [
      // TASK-LEAD-041: 5 налоговых страниц объединены в одну `/taxes` с табами.
      // Старые URL делают redirect → bookmark'и работают.
      { to: "/taxes", label: "Налоги", directorOrHead: true, bookkeeperOk: true },
      { to: "/cash-flow", label: "ДДС", directorOrHead: true },
      { to: "/payment-calendar", label: "Платёжный календарь", directorOrHead: true, bookkeeperOk: true },
      { to: "/inventory", label: "Капитализация WB" },
      { to: "/off-platform", label: "Внеплатформенные движения", directorOrHead: true },
      { to: "/tariffs", label: "Тарифы WB" },
    ],
  },
  {
    label: "SKU и продажи",
    items: [
      { to: "/units", label: "Юнит-экономика" },
      { to: "/funnel", label: "Воронка" },
      { to: "/unit-plan", label: "Плановая юнит-эк." },
      { to: "/abc", label: "ABC-анализ" },
      { to: "/plans", label: "План-Факт" },
      { to: "/season-plan", label: "План сезона", directorOrHead: true },
      { to: "/supply", label: "Поставки" },
      { to: "/localization", label: "Локализация" },
      { to: "/redistribution", label: "Перераспределение" },
      { to: "/supplies", label: "Закупки", directorOrHead: true },
      { to: "/product-groups", label: "Группы" },
      { to: "/cost-history", label: "Себестоимость" },
      { to: "/new-products", label: "Новинки", directorOrHead: true },
      { to: "/jam", label: "Джем" },
      { to: "/calc", label: "Калькулятор" },
      { to: "/transit-calculator", label: "Калькулятор поставки" },
      { to: "/promo-calculator", label: "Калькулятор акций" },
    ],
  },
  {
    label: "Маркетинг",
    items: [
      { to: "/external-marketing", label: "Внеш. маркетинг", directorOrHead: true },
      { to: "/ads-heatmap", label: "Реклама heatmap" },
      { to: "/abtest", label: "A/B тесты" },
    ],
  },
  {
    label: "Расходы",
    items: [
      { to: "/opex", label: "OPEX", directorOrHead: true },
      { to: "/revenue-corrections", label: "Корректировки", directorOrHead: true },
      { to: "/chargebacks", label: "Чарджбэки WB" },
      { to: "/brands", label: "Бренды", directorOrHead: true },
    ],
  },
  {
    label: "Контроль",
    items: [
      { to: "/managers-kpi", label: "KPI менеджеров", directorOrHead: true },
      { to: "/weekly-report", label: "Еженедельный отчёт" },
      { to: "/notifications", label: "Уведомления", directorOrHead: true },
      { to: "/checklist", label: "Чек-лист" },
    ],
  },
  {
    label: "Справка",
    items: [
      { to: "/glossary", label: "Глоссарий", icon: "list", bookkeeperOk: true },
      { to: "/docs", label: "Помощь", icon: "help", bookkeeperOk: true },
      { to: "/features", label: "Каталог функций", icon: "layers", bookkeeperOk: true },
    ],
  },
  {
    label: "Админка",
    items: [
      { to: "/audit-log", label: "Журнал изменений", directorOnly: true },
      { to: "/users", label: "Пользователи", directorOnly: true },
      { to: "/settings", label: "Настройки", directorOnly: true },
    ],
  },
];

const COLLAPSED_KEY = "sidebar.collapsed.v1";
const PROFILE_KEY = "sidebar.profile.v1";

// TASK-LEAD-041: UX-режимы поверх RBAC. Это не доступ (URL остаётся), а
// визуальный фильтр меню для собственника / менеджера / бухгалтера, чтобы
// не показывать 47+ пунктов когда нужны 5-7.
//
// «Полный» — текущее поведение (RBAC как есть).
// «owner» — главные 5-7 пунктов собственника (Dashboard / P&L / Сверка / Plans / Налоги).
// «manager» — узкое меню менеджера (SKU + Plans read).
// «bookkeeper» — эмуляция bookkeeper-режима (для director/head — посмотреть глазами бухгалтера).
type Profile = "full" | "owner" | "manager" | "bookkeeper";

const PROFILE_LABELS: Record<Profile, string> = {
  full: "Полный",
  owner: "Собственник",
  manager: "Менеджер",
  bookkeeper: "Бухгалтер",
};

// Whitelist of paths visible in each profile. «full» — no extra filter.
const PROFILE_WHITELIST: Record<Exclude<Profile, "full">, Set<string>> = {
  owner: new Set([
    "/",
    "/pnl",
    "/pnl-reconciliation",
    "/reconciliation-4way",
    "/plans",
    "/taxes",
  ]),
  manager: new Set([
    "/",
    "/units",
    "/unit-plan",
    "/abc",
    "/supply",
    "/plans",
    "/redistribution",
    "/product-groups",
  ]),
  bookkeeper: new Set([
    "/audit",
    "/taxes",
    "/payment-calendar",
    "/glossary",
    "/docs",
    "/features",
  ]),
};

function readProfile(): Profile {
  try {
    const v = localStorage.getItem(PROFILE_KEY);
    if (v === "full" || v === "owner" || v === "manager" || v === "bookkeeper") {
      return v;
    }
  } catch {}
  return "full";
}

export default function Layout() {
  const { user, logout, availableTenants, activeTenantId, switchTenant } = useAuth();
  const isDirector = user?.role === "director";
  const isHead = user?.role === "head_of_sales";
  const isBookkeeper = user?.role === "bookkeeper";
  const sees_all_brands = isDirector || isHead;

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(COLLAPSED_KEY) === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {}
  }, [collapsed]);

  // TASK-LEAD-041: UX-режим («Полный» / «Собственник» / «Менеджер» / «Бухгалтер»).
  // Доступен только для director/head — у них есть из чего выбирать. Для
  // manager/bookkeeper меню и так узкое (RBAC), переключатель скрыт.
  const profileVisible = sees_all_brands;
  const [profile, setProfile] = useState<Profile>(() =>
    profileVisible ? readProfile() : "full"
  );
  useEffect(() => {
    if (!profileVisible) return;
    try {
      localStorage.setItem(PROFILE_KEY, profile);
    } catch {}
  }, [profile, profileVisible]);

  // Hotkey `[` toggles sidebar
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "[" && !["INPUT", "TEXTAREA"].includes((e.target as HTMLElement)?.tagName)) {
        setCollapsed((c) => !c);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const filterItems = (items: Link[]) =>
    items.filter((l) => {
      // TASK-LEAD-040 frontend: для bookkeeper'а — whitelist через bookkeeperOk.
      // Без флага пункт скрыт (новые pages по default не показываем).
      if (isBookkeeper) return !!l.bookkeeperOk;
      if (l.directorOnly && !isDirector) return false;
      if (l.directorOrHead && !sees_all_brands) return false;
      // TASK-LEAD-041: UX-профиль накладывается поверх RBAC. «Полный» —
      // ничего не скрывает. Для остальных режимов — whitelist путей.
      if (profileVisible && profile !== "full") {
        const allowed = PROFILE_WHITELIST[profile];
        if (!allowed.has(l.to)) return false;
      }
      return true;
    });

  return (
    <div className="min-h-screen flex">
      <aside
        className={`${
          collapsed ? "w-[60px]" : "w-[240px]"
        } shrink-0 border-r border-border bg-surface flex flex-col h-screen sticky top-0 transition-[width] duration-150 ease-out`}
      >
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border h-[52px]">
          <span className="inline-block w-2 h-2 rounded-full bg-accent" aria-hidden />
          {!collapsed && (
            <div className="font-bold text-base leading-tight">
              РНП
              <span className="text-muted text-tiny font-normal ml-1">Wildberries</span>
            </div>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            className="ml-auto text-muted hover:text-fg transition-colors"
            title="Свернуть/развернуть (горячая [ )"
            aria-label="Свернуть/развернуть"
          >
            <Icon name="menu" size={14} />
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto py-2">
          {GROUPS.map((g) => {
            const items = filterItems(g.items);
            if (items.length === 0) return null;
            return (
              <div key={g.label} className="mb-3">
                {!collapsed && (
                  <div className="px-4 py-1 text-[10px] uppercase tracking-wider text-faint">
                    {g.label}
                  </div>
                )}
                {items.map((l) => (
                  <NavLink
                    key={l.to}
                    to={l.to}
                    end={l.end}
                    title={collapsed ? l.label : undefined}
                    className={({ isActive }) =>
                      `flex items-center gap-2 px-4 py-1.5 text-sm transition-colors duration-150 border-l-2 ${
                        isActive
                          ? "border-accent text-fg bg-accent-subtle"
                          : "border-transparent text-muted hover:text-fg hover:bg-surface-2"
                      }`
                    }
                  >
                    {l.icon && <Icon name={l.icon} size={14} className="shrink-0" />}
                    {!collapsed && <span className="truncate">{l.label}</span>}
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>
        {!collapsed && (
          <div className="border-t border-border px-2 py-1">
            <SyncStatusIndicator />
          </div>
        )}
        <div className="border-t border-border px-3 py-2 text-tiny">
          {/* TASK-LEAD-039 Фаза C — Multi-cabinet workspace switcher.
              Виден только если у user'а ≥2 доступных tenant'ов.
              При выборе — invalidate всех queries, reload /me, persist в cookie+localStorage. */}
          {!collapsed && availableTenants.length > 1 && (
            <div className="mb-2">
              <label
                htmlFor="sidebar-cabinet"
                className="block text-faint uppercase tracking-wider text-[10px] mb-1"
              >
                Кабинет
              </label>
              <select
                id="sidebar-cabinet"
                className="input w-full text-xs py-1"
                value={activeTenantId ?? ""}
                onChange={(e) => {
                  const id = Number(e.target.value);
                  if (Number.isFinite(id) && id !== activeTenantId) {
                    switchTenant(id).catch((err) => {
                      // eslint-disable-next-line no-console
                      console.error("Switch tenant failed", err);
                    });
                  }
                }}
                title="Переключение WB-кабинета. Все данные перезагружаются для выбранного tenant'а."
              >
                {availableTenants.map((t) => (
                  <option key={t.tenant_id} value={t.tenant_id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          {!collapsed && profileVisible && (
            <div className="mb-2">
              <label
                htmlFor="sidebar-profile"
                className="block text-faint uppercase tracking-wider text-[10px] mb-1"
              >
                Режим меню
              </label>
              <select
                id="sidebar-profile"
                className="input w-full text-xs py-1"
                value={profile}
                onChange={(e) => setProfile(e.target.value as Profile)}
                title="UX-фильтр меню. Не меняет доступ — только что показано в сайдбаре."
              >
                {(Object.keys(PROFILE_LABELS) as Profile[]).map((p) => (
                  <option key={p} value={p}>
                    {PROFILE_LABELS[p]}
                  </option>
                ))}
              </select>
            </div>
          )}
          {!collapsed && user && (
            <div className="text-muted leading-tight mb-2">
              <div className="text-fg truncate">{user.full_name || user.username}</div>
              <div
                className={
                  isDirector
                    ? "text-success"
                    : isHead
                    ? "text-accent"
                    : isBookkeeper
                    ? "text-warn"
                    : "text-muted"
                }
              >
                {isDirector
                  ? "Директор"
                  : isHead
                  ? "РОП"
                  : isBookkeeper
                  ? "Бухгалтер"
                  : "Менеджер"}
              </div>
            </div>
          )}
          {user && (
            <button
              className="btn text-xs w-full"
              onClick={() => logout()}
              title="Выйти"
              aria-label="Выйти"
            >
              <Icon name="logout" size={12} />
              {!collapsed && <span>Выйти</span>}
            </button>
          )}
          {!collapsed && <div className="mt-2"><VersionBadge /></div>}
        </div>
      </aside>
      <main className="flex-1 min-w-0 px-6 py-6">
        {user && user.role === "manager" && (
          <ManagerBrandsBanner brands={user.brands ?? []} />
        )}
        <Outlet />
      </main>
      <CommandPalette />
      <ToastHost />
    </div>
  );
}
