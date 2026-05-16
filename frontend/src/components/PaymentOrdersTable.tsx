/**
 * Таблица заявок WB (wb_payment_order) с возможностью bookkeeper-override:
 * пометить отчёт как «не входит в налоговую базу».
 *
 * Используется на /tax-report-ausn и /tax-report-usn. И там и там флаг
 * действует одинаково (исключает строку из всех компонентов налоговой
 * базы — Bank, ВЗЗ, УПД, AA).
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { fmtRub } from "@/lib/format";
import { Icon } from "@/components/Icon";

type Scope = "ausn" | "usn" | "both";

const SCOPE_HINT: Record<Scope, string> = {
  ausn:
    "Исключить из расчёта АУСН 8% (cash-basis):\n\n" +
    "Типичные случаи когда нужно:\n" +
    "• Ошибочный импорт / дубль\n" +
    "• Внутренний взаимозачёт между периодами\n\n" +
    "ВНИМАНИЕ: для фискально-годового перехода (отчёт декабря, оплачен в январе)\n" +
    "обычно НЕ исключают из АУСН (cash-basis — доход признаётся когда деньги пришли).",
  usn:
    "Исключить из расчёта УСН 6% (accrual):\n\n" +
    "Типичный случай:\n" +
    "• Отчёт прошлого фискального года, оплата пришла в новом — для УСН это доход\n" +
    "  прошлого года (декларация уже подана), но для АУСН доход нового года.\n" +
    "• Ошибочный импорт.",
  both:
    "Исключить из обоих режимов (АУСН + УСН).\n\n" +
    "Случаи: явный дубль, тестовая строка, абсолютно ошибочный импорт.",
};

export default function PaymentOrdersTable({
  items,
  showExtendedColumns = false,
  onDelete,
  scope = "both",
}: {
  items: any[];
  showExtendedColumns?: boolean;
  onDelete?: (payment_order_id: string) => void;
  /** Какой режим управляется этой таблицей. По умолчанию управляет обоими. */
  scope?: Scope;
}) {
  const qc = useQueryClient();
  const [editingReason, setEditingReason] = useState<string | null>(null);
  const [reasonText, setReasonText] = useState("");

  const toggleMut = useMutation({
    mutationFn: ({
      payment_order_id,
      excluded,
      reason,
    }: {
      payment_order_id: string;
      excluded: boolean;
      reason: string | null;
    }) =>
      api.paymentOrderToggleExclude(payment_order_id, scope, excluded, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["payment-orders"] });
      qc.invalidateQueries({ queryKey: ["tax-report-ausn"] });
      qc.invalidateQueries({ queryKey: ["tax-report-usn"] });
    },
  });

  // Локальная "is excluded в этом режиме" логика
  const isExcludedForScope = (item: any) => {
    if (scope === "ausn") return !!item.excluded_from_ausn;
    if (scope === "usn") return !!item.excluded_from_usn;
    return !!item.excluded_from_ausn && !!item.excluded_from_usn;
  };

  const handleToggle = (item: any) => {
    if (isExcludedForScope(item)) {
      toggleMut.mutate({
        payment_order_id: item.payment_order_id,
        excluded: false,
        reason: null,
      });
    } else {
      setEditingReason(item.payment_order_id);
      setReasonText("");
    }
  };

  const confirmExclude = (payment_order_id: string) => {
    toggleMut.mutate({
      payment_order_id,
      excluded: true,
      reason: reasonText.trim() || null,
    });
    setEditingReason(null);
    setReasonText("");
  };

  const scopeLabel = scope === "ausn" ? "АУСН" : scope === "usn" ? "УСН" : "Оба";

  return (
    <table className="min-w-full text-xs">
      <thead className="sticky top-0 bg-surface-2 border-b border-border z-10">
        <tr>
          <th className="text-left py-2 px-2">ID заявки</th>
          <th className="text-left py-2 px-2 text-muted">Создан</th>
          <th className="text-left py-2 px-2 text-muted">Зачислен</th>
          {showExtendedColumns && (
            <>
              <th className="text-left py-2 px-2 text-muted">Period end</th>
              <th className="text-left py-2 px-2 text-muted">Тип</th>
            </>
          )}
          <th className="text-right py-2 px-2">Сумма</th>
          {showExtendedColumns && (
            <>
              <th className="text-right py-2 px-2 text-muted">УПД доставки</th>
              <th className="text-right py-2 px-2 text-muted">Возвраты выкупы</th>
            </>
          )}
          <th className="text-left py-2 px-2 text-muted">Статус</th>
          <th
            className="text-center py-2 px-2 text-muted cursor-help"
            title={SCOPE_HINT[scope]}
          >
            <span className="inline-flex items-center gap-1">Исключить из {scopeLabel} <Icon name="help" size={11} className="text-accent" /></span>
          </th>
          {onDelete && <th></th>}
        </tr>
      </thead>
      <tbody>
        {items.map((o: any) => {
          const isExcluded = isExcludedForScope(o);
          const isEditing = editingReason === o.payment_order_id;
          return (
            <tr
              key={o.payment_order_id}
              className={`border-b border-border/40 hover:bg-surface-2/60 ${
                isExcluded ? "opacity-50 line-through" : ""
              }`}
            >
              <td className="py-2 px-2 font-mono">{o.payment_order_id}</td>
              <td className="py-2 px-2 text-muted">{o.created_dt}</td>
              <td className="py-2 px-2 text-muted">
                {o.paid_dt ?? <span className="text-warn">—</span>}
              </td>
              {showExtendedColumns && (
                <>
                  <td className="py-2 px-2 text-muted">{o.period_end ?? "—"}</td>
                  <td className="py-2 px-2 text-muted">{o.report_type ?? "—"}</td>
                </>
              )}
              <td className="py-2 px-2 text-right">{fmtRub(o.amount)}</td>
              {showExtendedColumns && (
                <>
                  <td className="py-2 px-2 text-right text-muted">
                    {o.upd_delivery_amount > 0 ? fmtRub(o.upd_delivery_amount) : "—"}
                  </td>
                  <td className="py-2 px-2 text-right text-muted">
                    {o.buyout_returns_amount > 0 ? fmtRub(o.buyout_returns_amount) : "—"}
                  </td>
                </>
              )}
              <td
                className={
                  "py-2 px-2 " +
                  (o.status === "paid"
                    ? "text-success"
                    : o.status === "processing"
                    ? "text-warn"
                    : "text-muted")
                }
              >
                {o.status}
              </td>
              <td className="py-2 px-2 text-center">
                {isEditing ? (
                  <div className="flex gap-1 items-center justify-center">
                    <input
                      type="text"
                      autoFocus
                      className="input text-xs w-32"
                      placeholder="Причина (опционально)"
                      value={reasonText}
                      onChange={(e) => setReasonText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") confirmExclude(o.payment_order_id);
                        if (e.key === "Escape") {
                          setEditingReason(null);
                          setReasonText("");
                        }
                      }}
                    />
                    <button
                      className="btn text-xs px-2"
                      onClick={() => confirmExclude(o.payment_order_id)}
                      aria-label="Подтвердить"
                    >
                      <Icon name="check" size={12} />
                    </button>
                    <button
                      className="btn text-xs px-2"
                      onClick={() => {
                        setEditingReason(null);
                        setReasonText("");
                      }}
                      aria-label="Отмена"
                    >
                      <Icon name="close" size={12} />
                    </button>
                  </div>
                ) : (
                  <label
                    className="flex items-center justify-center gap-1 cursor-pointer"
                    title={
                      isExcluded
                        ? `Исключено${o.exclusion_reason ? ": " + o.exclusion_reason : ""}. Клик чтобы включить обратно.`
                        : SCOPE_HINT[scope]
                    }
                  >
                    <input
                      type="checkbox"
                      checked={isExcluded}
                      onChange={() => handleToggle(o)}
                      disabled={toggleMut.isPending}
                    />
                    {isExcluded && o.exclusion_reason && (
                      <span className="text-[10px] text-muted truncate max-w-[100px] no-underline" style={{ textDecoration: "none" }}>
                        {o.exclusion_reason}
                      </span>
                    )}
                  </label>
                )}
              </td>
              <td className="py-2 px-2 text-muted truncate max-w-xs">
                {o.bank_comment}
              </td>
              {onDelete && (
                <td className="py-2 px-2">
                  <button
                    className="text-danger/70 hover:text-danger text-xs"
                    onClick={() => onDelete(o.payment_order_id)}
                    title="Удалить заявку"
                    aria-label="Удалить"
                  >
                    <Icon name="trash" size={12} />
                  </button>
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
