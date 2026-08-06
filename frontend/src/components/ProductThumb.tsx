/**
 * Миниатюра фото товара по `nm_id` (TASK-DEV-098).
 *
 * Источник — существующий прокси `/api/products/{nm_id}/photo`: он сам ходит в
 * WB CDN и кэширует в Redis на 24 ч, поэтому отдельная синхронизация картинок
 * не нужна — достаточно подключённого кабинета.
 *
 * Без `nm_id` (баркод ещё не связан с товаром в справочнике ШК) и при ошибке
 * загрузки место не занимаем: на складе таких строк много, «битые» иконки в
 * таблице только мешают.
 */
import { useState } from "react";

type Props = {
  nmId: number | null | undefined;
  /** Размер стороны в tailwind-классах — по умолчанию компактный для таблиц. */
  className?: string;
  alt?: string;
};

export function ProductThumb({ nmId, className, alt = "" }: Props) {
  const [failed, setFailed] = useState(false);
  if (!nmId || failed) return null;
  return (
    <img
      src={`/api/products/${nmId}/photo`}
      alt={alt}
      loading="lazy"
      title={String(nmId)}
      className={
        className ??
        "h-9 w-7 shrink-0 rounded border border-muted/30 bg-bg object-cover"
      }
      onError={() => setFailed(true)}
    />
  );
}

export default ProductThumb;
