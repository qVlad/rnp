import { useEffect, useState } from "react";
import { getCachedActiveTests, getLastSync, getSettings } from "@/lib/storage";
import type { ActiveTest } from "@/lib/types";

export function PopupApp() {
  const [tests, setTests] = useState<ActiveTest[]>([]);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [wbabUrl, setWbabUrl] = useState("https://rnp.sellerfriends.ru");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const [cached, sync, settings] = await Promise.all([
        getCachedActiveTests(),
        getLastSync(),
        getSettings(),
      ]);
      setTests(cached);
      setLastSync(sync);
      setWbabUrl(settings.wbabUrl);
      setLoading(false);
    })();
  }, []);

  async function refreshNow() {
    setLoading(true);
    try {
      await chrome.runtime.sendMessage({ type: "wbab:trigger-poll" });
    } catch {
      /* SW might be sleeping */
    }
    const [cached, sync] = await Promise.all([getCachedActiveTests(), getLastSync()]);
    setTests(cached);
    setLastSync(sync);
    setLoading(false);
  }

  function openTest(t: ActiveTest) {
    const url = `${(wbabUrl || "https://rnp.sellerfriends.ru").replace(/\/$/, "")}/abtest/${t.id}`;
    chrome.tabs.create({ url });
  }

  function openWbab() {
    chrome.tabs.create({ url: wbabUrl || "https://rnp.sellerfriends.ru" });
  }

  function openOptions() {
    chrome.runtime.openOptionsPage();
  }

  const withWinner = tests.filter((t) => t.winnerVariantLabel != null);
  const running = tests.filter((t) => t.winnerVariantLabel == null && t.status === "running");

  return (
    <>
      <div className="popup-header">
        <h1>
          <span>🧪</span> <span>РНП — A/B-тесты Wildberries</span>
        </h1>
        <div className="sub">
          {lastSync ? (
            <>Обновлено {formatRelative(lastSync)}</>
          ) : (
            <>Ещё нет данных — настройте подключение</>
          )}
        </div>
      </div>

      <div className="popup-body">
        {withWinner.length > 0 && (
          <div className="section">
            <h2>🏆 Найден победитель ({withWinner.length})</h2>
            {withWinner.map((t) => (
              <div key={t.id} className="test-item winner" onClick={() => openTest(t)}>
                <div className="name">{t.name}</div>
                <div className="meta">
                  <span>nmId {t.nmId}</span>
                  <span>·</span>
                  <span>победитель {t.winnerVariantLabel}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {running.length > 0 && (
          <div className="section">
            <h2>▶ Активные тесты ({running.length})</h2>
            {running.map((t) => (
              <div key={t.id} className="test-item" onClick={() => openTest(t)}>
                <div className="name">{t.name}</div>
                <div className="meta">
                  <span>
                    <span className="status-dot green" />
                    {t.activeVariantLabel}
                  </span>
                  <span>·</span>
                  <span>{t.sampleProgressPct}% выборки</span>
                  <span>·</span>
                  <span>nmId {t.nmId}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && tests.length === 0 && (
          <div className="empty">
            Активных тестов нет. Откройте карточку в seller.wildberries.ru —
            появится кнопка «Запустить A/B-тест».
          </div>
        )}
        {loading && <div className="empty">Загрузка…</div>}
      </div>

      <div className="footer">
        <button type="button" className="btn" onClick={refreshNow}>
          Обновить
        </button>
        <button type="button" className="btn" onClick={openOptions}>
          Настройки
        </button>
        <button type="button" className="btn btn-primary" onClick={openWbab}>
          Открыть РНП
        </button>
      </div>
    </>
  );
}

function formatRelative(ts: number): string {
  const diff = Date.now() - ts;
  if (diff < 60_000) return "только что";
  const mins = Math.floor(diff / 60_000);
  if (mins < 60) return `${mins} мин назад`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} ч назад`;
  return `${Math.floor(hours / 24)} дн назад`;
}
