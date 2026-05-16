/**
 * Command palette (P3.9 из UI_UX_AUDIT.md).
 *
 * ⌘K / Ctrl+K открывает overlay для быстрого перехода между страницами,
 * SKU, и быстрых действий.
 *
 * Источники команд:
 *   1. Все pages (sidebar nav)
 *   2. SKUs из /api/products (поиск по nm_id, vendor_code, brand)
 *   3. Быстрые действия (сменить период, экспорт PDF, и т.д.)
 */
import { useEffect, useMemo, useState } from "react";
import { Command } from "cmdk";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { Icon, IconName } from "@/components/Icon";

type Action = {
  id: string;
  title: string;
  hint?: string;
  icon?: IconName;
  section: "Перейти" | "Действия" | "SKU";
  onSelect: () => void;
};

const NAV_ACTIONS: Omit<Action, "onSelect">[] = [
  { id: "/", title: "Дашборд", icon: "layers", section: "Перейти" },
  { id: "/pnl", title: "P&L", icon: "list", section: "Перейти" },
  { id: "/pnl-reconciliation", title: "Сверка с WB", icon: "check", section: "Перейти" },
  { id: "/units", title: "Юнит-экономика", icon: "package", section: "Перейти" },
  { id: "/abc", title: "ABC-анализ", section: "Перейти" },
  { id: "/cash-flow", title: "ДДС", section: "Перейти" },
  { id: "/payment-calendar", title: "Платёжный календарь", icon: "calendar", section: "Перейти" },
  { id: "/tax-report-ausn", title: "АУСН-Доходы 8%", section: "Перейти" },
  { id: "/tax-report-usn", title: "УСН-Доходы 6%", section: "Перейти" },
  { id: "/ads-heatmap", title: "Реклама heatmap", section: "Перейти" },
  { id: "/notifications", title: "Уведомления", icon: "bell", section: "Перейти" },
  { id: "/plans", title: "План-Факт", section: "Перейти" },
  { id: "/supplies", title: "Закупки", section: "Перейти" },
  { id: "/cost-history", title: "Себестоимость", section: "Перейти" },
  { id: "/opex", title: "OPEX", section: "Перейти" },
  { id: "/glossary", title: "Глоссарий KPI", icon: "help", section: "Перейти" },
  { id: "/settings", title: "Настройки", icon: "settings", section: "Перейти" },
  { id: "/audit-log", title: "Audit log", section: "Перейти" },
];

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const navigate = useNavigate();

  // ⌘K / Ctrl+K
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const productsQ = useQuery<any>({
    queryKey: ["palette-products"],
    queryFn: () => api.listProducts({ include_archived: true }),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  });
  const products = productsQ.data?.items ?? productsQ.data ?? [];

  const skuActions: Action[] = useMemo(() => {
    if (!Array.isArray(products)) return [];
    return products.slice(0, 100).map((p: any) => ({
      id: `sku-${p.nm_id}`,
      title: `${p.vendor_code || "SKU"} · #${p.nm_id}`,
      hint: p.brand ? `Бренд: ${p.brand}` : undefined,
      icon: "package" as IconName,
      section: "SKU" as const,
      onSelect: () => {
        navigate(`/units?nm=${p.nm_id}`);
        setOpen(false);
      },
    }));
  }, [products, navigate]);

  const navActions: Action[] = NAV_ACTIONS.map((a) => ({
    ...a,
    onSelect: () => {
      navigate(a.id);
      setOpen(false);
    },
  }));

  const quickActions: Action[] = [
    {
      id: "act-refresh",
      title: "Перезагрузить страницу",
      icon: "refresh",
      section: "Действия",
      onSelect: () => {
        window.location.reload();
      },
    },
    {
      id: "act-logout",
      title: "Выйти",
      icon: "logout",
      section: "Действия",
      onSelect: () => {
        navigate("/login");
        setOpen(false);
      },
    },
  ];

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-start justify-center pt-[10vh]"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-xl bg-surface border border-border rounded-lg shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <Command label="Command palette" loop>
          <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
            <Icon name="search" size={14} className="text-muted" />
            <Command.Input
              autoFocus
              placeholder="Поиск страниц, SKU, действий…"
              value={search}
              onValueChange={setSearch}
              className="flex-1 bg-transparent outline-none text-sm text-fg placeholder:text-muted"
            />
            <kbd className="text-tiny text-muted bg-surface-2 px-1.5 py-0.5 rounded border border-border">esc</kbd>
          </div>
          <Command.List className="max-h-[400px] overflow-y-auto p-1">
            <Command.Empty className="text-muted text-sm py-6 text-center">
              Ничего не найдено
            </Command.Empty>
            <Command.Group heading="Перейти к" className="[&_[cmdk-group-heading]]:text-tiny [&_[cmdk-group-heading]]:text-faint [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1">
              {navActions.map((a) => (
                <Command.Item
                  key={a.id}
                  value={`${a.title} ${a.id}`}
                  onSelect={a.onSelect}
                  className="flex items-center gap-2 px-2 py-1.5 rounded text-sm text-fg cursor-pointer aria-selected:bg-accent-subtle aria-selected:text-accent"
                >
                  {a.icon && <Icon name={a.icon} size={14} className="text-muted" />}
                  <span>{a.title}</span>
                </Command.Item>
              ))}
            </Command.Group>
            {skuActions.length > 0 && (
              <Command.Group heading="SKU" className="[&_[cmdk-group-heading]]:text-tiny [&_[cmdk-group-heading]]:text-faint [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1">
                {skuActions.map((a) => (
                  <Command.Item
                    key={a.id}
                    value={`${a.title} ${a.hint || ""}`}
                    onSelect={a.onSelect}
                    className="flex items-center gap-2 px-2 py-1.5 rounded text-sm text-fg cursor-pointer aria-selected:bg-accent-subtle aria-selected:text-accent"
                  >
                    <Icon name="package" size={14} className="text-muted" />
                    <span className="truncate">{a.title}</span>
                    {a.hint && <span className="ml-auto text-tiny text-muted">{a.hint}</span>}
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            <Command.Group heading="Действия" className="[&_[cmdk-group-heading]]:text-tiny [&_[cmdk-group-heading]]:text-faint [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1">
              {quickActions.map((a) => (
                <Command.Item
                  key={a.id}
                  value={a.title}
                  onSelect={a.onSelect}
                  className="flex items-center gap-2 px-2 py-1.5 rounded text-sm text-fg cursor-pointer aria-selected:bg-accent-subtle aria-selected:text-accent"
                >
                  {a.icon && <Icon name={a.icon} size={14} className="text-muted" />}
                  <span>{a.title}</span>
                </Command.Item>
              ))}
            </Command.Group>
          </Command.List>
          <div className="border-t border-border px-3 py-2 text-tiny text-muted flex items-center gap-3">
            <span>
              <kbd className="bg-surface-2 px-1 rounded border border-border">↑↓</kbd> навигация
            </span>
            <span>
              <kbd className="bg-surface-2 px-1 rounded border border-border">↵</kbd> выбор
            </span>
            <span className="ml-auto">
              <kbd className="bg-surface-2 px-1 rounded border border-border">⌘K</kbd> открыть/закрыть
            </span>
          </div>
        </Command>
      </div>
    </div>
  );
}
