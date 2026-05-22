/**
 * Юридический disclaimer перед первым подключением LK WB (TASK-DEV-009).
 *
 * Модальное окно показывается на /redistribution когда:
 *   • Юзер ещё не согласился (`localStorage["redistribution.disclaimer.agreed.v1"] !== "true"`)
 *   • LK ещё не подключен (status.lk_connected === false)
 *
 * После согласия:
 *   • localStorage["redistribution.disclaimer.agreed.v1"] = "true"
 *   • localStorage["redistribution.disclaimer.agreed_at"] = ISO timestamp
 *   • Модалка больше не показывается на этом устройстве
 *
 * Это **обязательный документ** для grey-area интеграции с LK WB через
 * extension proxy — селлер явно соглашается что credentials предоставлены
 * добровольно (как у QuotaBot/WBCON/Супербот). Без согласия — кнопка
 * «Подключить через расширение» не работает.
 *
 * Compliance-аудит (запись в БД с timestamp + IP) — отдельный шаг
 * (миграция `wb_lk_accounts.disclaimer_agreed_at TIMESTAMP`). Сейчас
 * localStorage достаточно для MVP — юзер согласился = на этом устройстве
 * больше не спрашиваем.
 */
import { useEffect, useState } from "react";

export const DISCLAIMER_KEY = "redistribution.disclaimer.agreed.v1";
export const DISCLAIMER_TIMESTAMP_KEY = "redistribution.disclaimer.agreed_at";

export function hasAgreedDisclaimer(): boolean {
  try {
    return localStorage.getItem(DISCLAIMER_KEY) === "true";
  } catch {
    return false;
  }
}

export default function LkDisclaimerModal({
  open,
  onAgree,
  onCancel,
}: {
  open: boolean;
  onAgree: () => void;
  onCancel: () => void;
}) {
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    if (open) setChecked(false);
  }, [open]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="card max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-semibold mb-3">
          Согласие на подключение кабинета WB
        </h2>
        <div className="text-sm text-muted leading-relaxed space-y-2">
          <p>
            Подключая кабинет селлера Wildberries (LK WB) к SellerFriends, вы
            <strong className="text-fg"> добровольно</strong> предоставляете
            нашему сервису доступ к своим временным авторизационным токенам
            (<code>AuthorizeV3</code>, <code>Wb-Seller-Lk</code>).
          </p>
          <p>
            <strong className="text-fg">Что мы будем делать с этими токенами:</strong>
          </p>
          <ul className="list-disc list-inside space-y-1 ml-2">
            <li>
              Отправлять заявки на услугу{" "}
              <em>«Перераспределение остатков»</em> от вашего имени по
              утверждённым вами рекомендациям.
            </li>
            <li>
              Опрашивать остатки и доступные слоты раз в 2 минуты для
              срабатывания автобронирования.
            </li>
            <li>
              Хранить токены в зашифрованном виде (Fernet) только до их
              истечения у WB (~30-60 мин для AuthorizeV3).
            </li>
          </ul>
          <p>
            <strong className="text-fg">Чего мы НЕ делаем:</strong> не
            отправляем заявки без вашего <code>approve</code>, не меняем
            цены, не списываем рекламу, не имеем доступа к вашему банковскому
            кабинету. Все действия логируются в журнал и видны в очереди
            заявок.
          </p>
          <p>
            <strong className="text-fg">Юридический статус:</strong> WB не
            предоставляет публичный API для перераспределения. Интеграция
            работает через ваше Chrome-расширение как прокси (аналогично
            QuotaBot, WBCON, Супербот). По условиям WB любой автоматизированный
            доступ к кабинету селлера через session-credentials —{" "}
            <strong className="text-warn">серая зона</strong>: WB не запрещает
            явно, но и не одобряет официально. Используя этот модуль, вы
            принимаете на себя возможный риск блокировки кабинета (по нашему
            опыту и опыту конкурентов — практически нулевой за 3+ года
            операций).
          </p>
          <p>
            Отвязать LK можно в любой момент кнопкой «Отвязать» на этой
            странице. После отвязки токены немедленно удаляются из БД.
          </p>
        </div>

        <label className="flex items-start gap-2 mt-4 cursor-pointer">
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
            className="mt-0.5"
          />
          <span className="text-sm">
            Я ознакомлен(а) и согласен(а) с условиями. Подключение токенов LK
            WB к SellerFriends — моё добровольное решение.
          </span>
        </label>

        <div className="flex gap-2 mt-4 justify-end">
          <button type="button" className="btn text-xs" onClick={onCancel}>
            Отмена
          </button>
          <button
            type="button"
            className="btn-primary text-xs"
            disabled={!checked}
            onClick={() => {
              try {
                localStorage.setItem(DISCLAIMER_KEY, "true");
                localStorage.setItem(
                  DISCLAIMER_TIMESTAMP_KEY,
                  new Date().toISOString(),
                );
              } catch {}
              onAgree();
            }}
          >
            Принять и продолжить
          </button>
        </div>
      </div>
    </div>
  );
}
