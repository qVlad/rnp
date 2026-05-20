import { Icon } from "@/components/Icon";

/**
 * Баннер для роли manager — показывает что данные фильтруются по
 * назначенным брендам. Закрывает QA/UX-замечание: manager не понимал
 * почему он видит мало данных и не было способа проверить свои
 * назначения без обращения к директору.
 */
export default function ManagerBrandsBanner({ brands }: { brands: string[] }) {
  if (brands.length === 0) {
    return (
      <div className="mb-3 flex items-start gap-2 rounded border border-warning/30 bg-warning/10 px-3 py-2 text-xs">
        <Icon name="help" size={14} className="mt-0.5 shrink-0 text-warning" />
        <div>
          <div className="font-medium text-warning">У вас нет назначенных брендов</div>
          <div className="text-muted">
            Все аналитические разделы будут пустыми. Обратитесь к директору,
            чтобы он назначил вас на бренды в разделе «Бренды».
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="mb-3 flex items-center gap-2 rounded border border-border bg-surface-2 px-3 py-1.5 text-xs text-muted">
      <Icon name="layers" size={12} className="shrink-0" />
      <span>
        Показаны данные только по вашим брендам:{" "}
        <span className="text-fg font-medium">{brands.join(", ")}</span>
      </span>
    </div>
  );
}
