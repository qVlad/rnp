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

type Link = {
  to: string;
  label: string;
  end?: boolean;
  directorOnly?: boolean;
  directorOrHead?: boolean;
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
    ],
  },
  {
    label: "Налоги и деньги",
    items: [
      { to: "/tax-report", label: "Налог. отчёт", directorOrHead: true },
      { to: "/tax-report-ausn", label: "АУСН-Доходы 8%", directorOrHead: true },
      { to: "/tax-report-usn", label: "УСН-Доходы 6%", directorOrHead: true },
      { to: "/tax-report-usn-vat5", label: "УСН 6% + НДС 5%", directorOrHead: true },
      { to: "/tax-report-usn-vat7", label: "УСН 6% + НДС 7%", directorOrHead: true },
      { to: "/cash-flow", label: "ДДС", directorOrHead: true },
      { to: "/payment-calendar", label: "Платёжный календарь", directorOrHead: true },
      { to: "/capitalization", label: "Капитализация", directorOrHead: true },
    ],
  },
  {
    label: "SKU и продажи",
    items: [
      { to: "/units", label: "Юнит-экономика" },
      { to: "/abc", label: "ABC-анализ" },
      { to: "/plans", label: "План-Факт" },
      { to: "/season-plan", label: "План сезона", directorOrHead: true },
      { to: "/supply", label: "Поставки" },
      { to: "/supplies", label: "Закупки", directorOrHead: true },
      { to: "/product-groups", label: "Группы" },
      { to: "/cost-history", label: "Себестоимость" },
      { to: "/new-products", label: "Новинки", directorOrHead: true },
      { to: "/jam", label: "Джем" },
      { to: "/calc", label: "Калькулятор" },
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
      { to: "/brands", label: "Бренды", directorOrHead: true },
    ],
  },
  {
    label: "Контроль",
    items: [
      { to: "/notifications", label: "Уведомления", directorOrHead: true },
      { to: "/checklist", label: "Чек-лист" },
    ],
  },
  {
    label: "Справка",
    items: [
      { to: "/glossary", label: "Глоссарий" },
      { to: "/docs", label: "Помощь" },
    ],
  },
  {
    label: "Админка",
    items: [
      { to: "/audit-log", label: "Audit log", directorOnly: true },
      { to: "/users", label: "Пользователи", directorOnly: true },
      { to: "/settings", label: "Настройки", directorOnly: true },
    ],
  },
];

const COLLAPSED_KEY = "sidebar.collapsed.v1";

export default function Layout() {
  const { user, logout } = useAuth();
  const isDirector = user?.role === "director";
  const isHead = user?.role === "head_of_sales";
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
      if (l.directorOnly) return isDirector;
      if (l.directorOrHead) return sees_all_brands;
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
          {!collapsed && user && (
            <div className="text-muted leading-tight mb-2">
              <div className="text-fg truncate">{user.full_name || user.username}</div>
              <div
                className={
                  isDirector
                    ? "text-success"
                    : isHead
                    ? "text-accent"
                    : "text-muted"
                }
              >
                {user.role}
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
        <Outlet />
      </main>
      <CommandPalette />
    </div>
  );
}
