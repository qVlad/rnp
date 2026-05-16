/**
 * Стандартизированный page-header (P2.19 из UI_UX_AUDIT.md).
 *
 * Использование:
 *   <PageHeader
 *     title="Юнит-экономика"
 *     subtitle="27 SKU · период 30 дней"
 *     actions={<><button>...</button></>}
 *   />
 *
 * Заменяет inline `<h1 className="text-xl font-semibold">` который раскидан
 * по 30 страницам с разным spacing/font/layout. Унифицирует:
 *   - H1 размер (24px / line-height 32px)
 *   - Subtitle (13px muted)
 *   - Actions справа (flex-wrap при узких ширинах)
 *   - Нижний отступ ровно 16px
 */
import { ReactNode } from "react";

export default function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex items-end justify-between flex-wrap gap-3 mb-4">
      <div className="flex flex-col gap-1 min-w-0">
        <h1 className="text-h2 font-semibold leading-tight truncate">
          {title}
        </h1>
        {subtitle && (
          <p className="text-tiny text-muted leading-tight">{subtitle}</p>
        )}
      </div>
      {actions && (
        <div className="flex items-end gap-2 flex-wrap">{actions}</div>
      )}
    </header>
  );
}
