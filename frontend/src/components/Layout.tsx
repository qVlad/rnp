import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import VersionBadge from "@/components/VersionBadge";

type Link = {
  to: string;
  label: string;
  end?: boolean;
  directorOnly?: boolean;
  directorOrHead?: boolean;
};

const links: Link[] = [
  { to: "/", label: "Дашборд", end: true },
  { to: "/pnl", label: "P&L" },
  { to: "/pnl-reconciliation", label: "Сверка с WB" },
  { to: "/tax-report", label: "Налог. отчёт", directorOrHead: true },
  { to: "/cash-flow", label: "ДДС", directorOrHead: true },
  { to: "/capitalization", label: "Капитализация", directorOrHead: true },
  { to: "/product-groups", label: "Группы" },
  { to: "/units", label: "Юнит-экономика" },
  { to: "/calc", label: "Калькулятор" },
  { to: "/abc", label: "ABC-анализ" },
  { to: "/supply", label: "Поставки" },
  { to: "/plans", label: "План-Факт" },
  { to: "/cost-history", label: "Себестоимость" },
  { to: "/external-marketing", label: "Внеш. маркетинг", directorOrHead: true },
  { to: "/revenue-corrections", label: "Корректировки", directorOrHead: true },
  { to: "/opex", label: "OPEX", directorOrHead: true },
  { to: "/brands", label: "Бренды", directorOrHead: true },
  { to: "/glossary", label: "Глоссарий" },
  { to: "/docs", label: "Помощь" },
  { to: "/audit-log", label: "Audit log", directorOnly: true },
  { to: "/users", label: "Пользователи", directorOnly: true },
  { to: "/settings", label: "Настройки", directorOnly: true },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const isDirector = user?.role === "director";
  const isHead = user?.role === "head_of_sales";
  const sees_all_brands = isDirector || isHead;
  const visibleLinks = links.filter((l) => {
    if (l.directorOnly) return isDirector;
    if (l.directorOrHead) return sees_all_brands;
    return true;
  });


  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border bg-surface">
        <div className="max-w-[1400px] mx-auto flex items-center gap-4 px-6 py-3">
          <div className="font-bold text-lg">
            <span className="text-accent">●</span> РНП{" "}
            <span className="text-muted text-sm">Wildberries</span>
          </div>
          <nav className="flex gap-1 ml-6 flex-wrap">
            {visibleLinks.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.end}
                className={({ isActive }: { isActive: boolean }) =>
                  `nav-link ${isActive ? "active" : ""}`
                }
              >
                {l.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-xs">
            <VersionBadge />
            {user && (
              <>
                <span className="text-muted">
                  {user.full_name || user.username}{" "}
                  <span
                    className={
                      isDirector
                        ? "text-success"
                        : isHead
                        ? "text-accent"
                        : "text-muted"
                    }
                    title={
                      isDirector
                        ? "роль director — полный доступ"
                        : isHead
                        ? "роль head_of_sales — расширенный доступ"
                        : "роль manager — ограниченный доступ"
                    }
                  >
                    · {user.role}
                  </span>
                </span>
                <button
                  className="btn text-xs"
                  onClick={() => logout()}
                  title="Выйти"
                >
                  ⏻ Выйти
                </button>
              </>
            )}
          </div>
        </div>
      </header>
      <main className="flex-1 max-w-[1400px] w-full mx-auto px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
