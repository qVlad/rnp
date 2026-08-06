/**
 * Человеческие тексты ошибок склада (TASK-DEV-098).
 *
 * Раньше страница показывала сырое `API 409: {"detail":"link_exists"}` — по такому
 * сообщению непонятно ни что случилось, ни что делать. Backend отдаёт коды (иногда
 * с контекстом), здесь они превращаются в подсказку на русском.
 */

type Detail = { code?: string; [k: string]: unknown };

/** Вытащить `detail` из текста ошибки `API <code>: <body>`. */
function parseDetail(message: string): { status?: number; detail?: unknown } {
  const m = message.match(/API (\d+): (.*)$/s);
  if (!m) return {};
  const status = Number(m[1]);
  try {
    const body = JSON.parse(m[2]);
    return { status, detail: body?.detail ?? body };
  } catch {
    return { status, detail: m[2] };
  }
}

const SIMPLE: Record<string, string> = {
  warehouse_not_found: "Склад не найден — возможно, его удалили в другой вкладке.",
  cabinet_not_found: "Кабинет не найден.",
  cabinet_has_no_token: "У кабинета не задан WB-токен — добавьте его в «Настройки → Кабинеты WB».",
  cell_not_found: "Ячейка не найдена: проверьте код.",
  cell_inactive: "Ячейка помечена неактивной — включите её на «Карте склада».",
  box_not_found: "Короб не найден на этом складе. Проверьте склад в шапке и ШК короба.",
  warehouse_exists: "Склад с таким названием уже есть.",
  warehouse_required: "Не удалось определить склад: выберите склад в шапке или добавьте колонку «Склад» в файл.",
  no_boxes_found: "В файле не нашлось ни одного короба — проверьте, что это PackingList.",
  no_cells_found: "В файле не нашлось ни одной ячейки.",
  confirm_required: "Нужно подтверждение — действие необратимо.",
  supply_not_found: "Поставка с таким номером на этом складе не найдена. Номер виден в колонке «Поставка».",
  pick_order_not_found: "Лист отбора не найден.",
  pick_line_not_found: "Строка отбора не найдена.",
  line_has_no_source: "У строки нет источника: товара нет ни в ячейках, ни на хранении.",
  nothing_left_in_box: "В коробе уже ничего не осталось — обновите лист отбора.",
  no_orders_in_pick: "В листе нет сборочных заданий.",
  supply_not_created: "Поставка ещё не создана — сначала нажмите «Поставка».",
  supply_already_created: "Поставка уже создана, отменить лист нельзя.",
  link_exists_here: "Такая связка на этом складе уже есть.",
  no_wb_links: "Нет связок с кабинетами WB — заполните вкладку «Кабинеты WB».",
};

/** Ошибка склада → текст для пользователя. */
export function warehouseErrorText(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e);
  const { status, detail } = parseDetail(raw);

  // Объект с кодом и контекстом
  if (detail && typeof detail === "object") {
    const d = detail as Detail;
    if (d.code === "link_taken") {
      return (
        `Этот склад продавца WB уже привязан к складу «${d.warehouse_name ?? d.warehouse_id}». ` +
        "Один склад WB может относиться только к одному нашему складу — иначе непонятно, откуда отбирать заказ."
      );
    }
    if (d.code && SIMPLE[d.code]) return SIMPLE[d.code];
    if (d.code) return String(d.code);
  }

  // Строковые коды, иногда с «:контекстом»
  if (typeof detail === "string") {
    const [code, ...rest] = detail.split(":");
    const ctx = rest.join(":");
    if (SIMPLE[code]) return SIMPLE[code];
    switch (code) {
      case "warehouse_not_empty":
        return `На складе ещё ${ctx} коробов. Разберите их или удалите склад вместе с содержимым.`;
      case "warehouse_has_history":
        return `По складу есть ${ctx} записей в журнале движений. Обычно достаточно снять «Активен» — данные сохранятся.`;
      case "cell_occupied":
        return `Ячейка занята коробом ${ctx}. Уберите его на хранение или выберите другую ячейку.`;
      case "supply_exists":
        return `Поставка уже создана: ${ctx}.`;
      case "orders_already_in_supply":
        return `Задания уже лежат в поставке WB (${ctx}) — вторую создавать нельзя, нажмите «В доставку».`;
      case "unreadable_file":
        return `Файл не читается: ${ctx || "проверьте, что это .xlsx"}`;
      default:
        break;
    }
    if (detail.trim()) return detail;
  }

  if (status === 401) return "Сессия истекла — войдите заново.";
  if (status === 403) return "Недостаточно прав для этого действия.";
  if (status === 502 || status === 503)
    return "Сервис перезапускается (деплой) — повторите через минуту.";
  return raw;
}
