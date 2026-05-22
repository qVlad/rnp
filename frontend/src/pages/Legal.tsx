import { Link } from "react-router-dom";

/** Privacy policy + Terms — статика. Минимально достаточный текст для
 *  публичного multi-tenant сервиса. Открывается без авторизации.
 *  Tab переключает между двумя разделами. */
export default function Legal() {
  return (
    <div className="min-h-screen bg-bg text-white py-10">
      <div className="max-w-3xl mx-auto px-6">
        <div className="flex items-baseline justify-between mb-8">
          <div className="font-bold text-xl">
            <span className="text-accent">●</span> РНП
          </div>
          <Link to="/login" className="text-sm text-accent underline">
            ← Войти
          </Link>
        </div>

        {/* TASK-UI-011: Legal — публичная страница без app-shell,
            оставлен inline-h1 (semantic h1 нормализован глобальным CSS). */}
        <h1 className="text-2xl font-semibold mb-4">Правила и приватность</h1>
        <p className="text-sm text-muted mb-6">
          Сервис «РНП — Wildberries аналитика» (далее «Сервис») предоставляет
          селлерам Wildberries инструменты аналитики на базе данных WB API.
          Регистрируясь, вы принимаете условия ниже.
        </p>

        <section className="card mb-6">
          <h2 className="text-lg font-semibold mb-3">Условия использования</h2>
          <ol className="list-decimal list-inside space-y-2 text-sm leading-relaxed">
            <li>
              Сервис — single-tenant SaaS. Вы получаете изолированное хранилище
              данных под свою компанию. Сервис не передаёт ваши данные третьим
              лицам кроме случаев, предусмотренных законом РФ.
            </li>
            <li>
              Вы предоставляете Сервису WB API-токен. Сервис использует его
              исключительно для чтения вашей собственной аналитики
              (заказы/продажи/остатки/реклама/финансы). Токен хранится в БД в
              зашифрованном виде (Fernet AES-128).
            </li>
            <li>
              Сервис не несёт ответственности за: (а) перебои в работе WB API,
              (б) расхождения данных WB-кабинета и Сервиса в пределах нормы
              (~1-3% — связано с разными агрегаторами WB), (в) задержки sync
              (типично 2-6 часов до Final-данных).
            </li>
            <li>
              Запрещено: реверс-инжиниринг, перепродажа доступа, использование
              для скрапинга чужих WB-кабинетов. Нарушения = немедленная
              блокировка без возврата средств.
            </li>
            <li>
              Сервис может быть приостановлен на время технических работ с
              предварительным уведомлением. Бэкапы БД делаются автоматически
              ежедневно и хранятся 30 дней.
            </li>
          </ol>
        </section>

        <section className="card mb-6">
          <h2 className="text-lg font-semibold mb-3">Политика приватности</h2>
          <div className="text-sm leading-relaxed space-y-3">
            <p>
              <strong>Какие данные мы собираем:</strong>
            </p>
            <ul className="list-disc list-inside space-y-1 ml-2">
              <li>
                Регистрационные: название компании, имя владельца, email/логин,
                bcrypt-хеш пароля.
              </li>
              <li>WB API-токен (зашифрован Fernet).</li>
              <li>
                WB-аналитика, выгружаемая через ваш токен: заказы, продажи,
                остатки, реклама, финансовые отчёты. Эти данные принадлежат
                вам, мы только храним и считаем агрегаты.
              </li>
              <li>
                Технические логи: IP-адрес запроса (для rate-limit), timestamp,
                URL endpoint'а. Логи хранятся 14 дней.
              </li>
            </ul>
            <p>
              <strong>Кому передаём:</strong> никому. Wildberries — только в
              рамках API-запросов от вашего имени с вашим токеном.
            </p>
            <p>
              <strong>Где хранится:</strong> PostgreSQL на нашем сервере
              (Россия). Бэкапы — там же.
            </p>
            <p>
              <strong>Cookies:</strong> один HttpOnly cookie с JWT-сессией (срок
              жизни 12 часов). Без аналитики, без рекламы, без сторонних
              сервисов.
            </p>
            <p>
              <strong>Удаление данных:</strong> по запросу на e-mail владельца
              сервиса в течение 7 дней. Удаление tenant'а удаляет все
              связанные с ним строки (CASCADE).
            </p>
          </div>
        </section>

        <section className="card mb-6">
          <h2 className="text-lg font-semibold mb-3">Контакты</h2>
          <p className="text-sm">
            По вопросам приватности и технических сбоев — пишите владельцу
            сервиса (контакт в шапке кабинета после входа).
          </p>
        </section>

        <p className="text-xs text-muted mt-8">
          Последнее обновление: май 2026. Сервис вправе обновить условия в
          одностороннем порядке с уведомлением активных пользователей минимум
          за 7 дней до вступления изменений в силу.
        </p>
      </div>
    </div>
  );
}
