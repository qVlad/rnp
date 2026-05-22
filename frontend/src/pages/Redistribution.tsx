import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend as ChartLegend,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";
import { fmtRub, fmtNum, fmtLocalDt, fmtLocalTime, fmtPct, fmtRatio } from "@/lib/format";
import LkDisclaimerModal, {
  hasAgreedDisclaimer,
} from "@/components/LkDisclaimerModal";
import { Icon } from "../components/Icon";
import PageHeader from "@/components/PageHeader";
import { GRID_PROPS, AXIS_PROPS, TOOLTIP_STYLE, LEGEND_STYLE, CHART_COLORS } from "@/lib/chartTheme";

export default function Redistribution() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const seesAllBrands = user?.role === "director" || user?.role === "head_of_sales";
  const [recsTab, setRecsTab] = useState<"pending" | "queued" | "executed">("pending");

  // TASK-DEV-009: модалка с согласием до первого подключения LK WB через
  // extension proxy. Показывается если юзер ещё не согласился И ещё не
  // подключён (после подключения смысла спрашивать нет — он уже принял).
  const [disclaimerOpen, setDisclaimerOpen] = useState(false);
  const [disclaimerAgreed, setDisclaimerAgreed] = useState(() =>
    hasAgreedDisclaimer(),
  );

  const statusQ = useQuery({
    queryKey: ["redistribution-status"],
    queryFn: () => api.redistributionStatus(),
    refetchInterval: 30_000,
  });

  // Открываем disclaimer modal автоматически при первом визите когда LK
  // ещё не подключен и согласие не дано. Если юзер уже соглашался ранее
  // (на другом устройстве) — модалка не появится повторно тут, но LK
  // тоже не подключится автоматически без extension.
  useEffect(() => {
    if (
      !disclaimerAgreed &&
      statusQ.data &&
      statusQ.data.lk_connected === false
    ) {
      setDisclaimerOpen(true);
    }
  }, [disclaimerAgreed, statusQ.data]);
  const recsQ = useQuery({
    queryKey: ["redistribution-recs", recsTab],
    queryFn: () => api.redistributionRecs(recsTab),
  });
  const tasksQ = useQuery({
    queryKey: ["redistribution-tasks"],
    queryFn: () => api.redistributionTasks(),
    refetchInterval: 60_000,
  });
  const roiQ = useQuery({
    queryKey: ["redistribution-roi"],
    queryFn: () => api.redistributionRoi(),
  });

  const generateMut = useMutation({
    mutationFn: () => api.redistributionGenerate(),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["redistribution-recs"] });
      alert(`Создано рекомендаций: ${data.created}${data.message ? ` (${data.message})` : ""}`);
    },
    onError: (e: any) => alert(`Ошибка: ${e.message}`),
  });
  const approveMut = useMutation({
    mutationFn: (id: number) => api.redistributionApprove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["redistribution-recs"] });
      qc.invalidateQueries({ queryKey: ["redistribution-tasks"] });
    },
  });
  const dismissMut = useMutation({
    mutationFn: (id: number) => api.redistributionDismiss(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["redistribution-recs"] }),
  });
  const cancelMut = useMutation({
    mutationFn: (id: number) => api.redistributionCancelTask(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["redistribution-tasks"] });
      qc.invalidateQueries({ queryKey: ["redistribution-recs"] });
    },
    onError: (e: any) => alert(`Не удалось отменить: ${e.message}`),
  });

  return (
    <div className="flex flex-col gap-4">
      <LkDisclaimerModal
        open={disclaimerOpen}
        onAgree={() => {
          setDisclaimerAgreed(true);
          setDisclaimerOpen(false);
        }}
        onCancel={() => setDisclaimerOpen(false)}
      />

      {!disclaimerAgreed && !statusQ.data?.lk_connected && (
        <div className="card border-warning/30 bg-warning/10 text-sm">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span>
              Перед подключением LK WB нужно принять условия согласия.
            </span>
            <button
              type="button"
              className="btn-primary text-xs"
              onClick={() => setDisclaimerOpen(true)}
            >
              Открыть согласие
            </button>
          </div>
        </div>
      )}

      <PageHeader
        title="Перераспределение остатков WB"
        actions={
          <button
            className="btn text-xs"
            onClick={() => generateMut.mutate()}
            disabled={generateMut.isPending || !statusQ.data?.lk_connected}
            title={
              !statusQ.data?.lk_connected
                ? "Нужно подключение LK. Откройте seller.wildberries.ru в браузере с установленным расширением — LK подключится автоматически."
                : ""
            }
          >
            {generateMut.isPending ? "Считаю…" : "↻ Пересчитать рекомендации"}
          </button>
        }
      />

      <div className="card text-xs text-muted leading-relaxed">
        Связка прогноз → план → автобронь для услуги WB «Перераспределение
        остатков» (+0.5% от оборота за услугу). Заявки идут по
        <strong> chrt_id</strong> (характеристика, не nm_id). Кулдаун 72ч
        на пару (chrt_id × склад-приёмник). После LEAD-022 заявки
        отправляются <strong>непрерывно</strong> (раз в 2 мин) — никаких
        «окон 09:00/18:00» больше нет: WB открывает квоты непрерывно,
        отдельные склады могут быть закрыты в моменте, тогда заявка
        ретраится автоматически. Условие: открыта вкладка
        <code> seller.wildberries.ru</code> с активной сессией.
      </div>

      {/* Status + LK connect */}
      <LkStatusCard
        status={statusQ.data}
        onConnect={(authorizeV3, wbSellerLk) =>
          api
            .redistributionConnectLk({
              authorize_v3: authorizeV3,
              wb_seller_lk: wbSellerLk || undefined,
            })
            .then(() => qc.invalidateQueries({ queryKey: ["redistribution-status"] }))
        }
        onDisconnect={() =>
          api
            .redistributionDisconnectLk()
            .then(() => qc.invalidateQueries({ queryKey: ["redistribution-status"] }))
        }
      />

      {/* ROI */}
      <RoiCard
        roi={roiQ.data}
        loading={roiQ.isLoading}
      />

      {/* LEAD-013: per-manager redistribution analytics (ROP/director view) */}
      {seesAllBrands && <RedistributionByManagerWidget />}

      {/* Recommendations */}
      <div className="card">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="font-medium">Рекомендации</h2>
          <div className="flex gap-1">
            {(["pending", "queued", "executed"] as const).map((t) => (
              <button
                key={t}
                className={`btn text-xs ${recsTab === t ? "border-accent text-accent" : ""}`}
                onClick={() => setRecsTab(t)}
              >
                {t === "pending" ? "Pending" : t === "queued" ? "В очереди" : "Выполнено"}
              </button>
            ))}
          </div>
        </div>
        {recsQ.isLoading && <div className="text-muted">Загрузка…</div>}
        {recsQ.data && recsQ.data.items.length === 0 && (
          <div className="text-muted text-sm">
            Нет рекомендаций. Нажмите «Пересчитать» (нужна подключённая LK-сессия).
          </div>
        )}
        {recsQ.data && recsQ.data.items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr className="border-b border-border">
                <th className="text-left p-2">nm_id / chrt</th>
                <th className="text-left p-2">Откуда</th>
                <th className="text-left p-2">Куда</th>
                <th className="text-right p-2">Qty</th>
                <th className="text-right p-2">Net benefit</th>
                <th className="text-right p-2">Demand 14d</th>
                <th className="text-right p-2">Stock тут/там</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {recsQ.data.items.map((r) => (
                <tr key={r.id} className="border-t border-border hover:bg-bg/40">
                  <td className="p-2 font-mono text-xs">
                    {r.nm_id}
                    <br />
                    <span className="text-muted">{r.chrt_id}</span>
                  </td>
                  <td className="p-2">{r.from_office_name}</td>
                  <td className="p-2">{r.to_office_name}</td>
                  <td className="p-2 text-right font-mono">{r.qty}</td>
                  <td className="p-2 text-right font-mono">
                    <span className={r.net_benefit_rub > 0 ? "text-success" : "text-danger"}>
                      {fmtRub(r.net_benefit_rub)}
                    </span>
                    {r.payback_days && (
                      <div className="text-[10px] text-muted">
                        ~{fmtRatio(r.payback_days, 1)} дн.
                      </div>
                    )}
                  </td>
                  <td className="p-2 text-right font-mono text-xs">
                    {r.demand_14d_at_target}
                  </td>
                  <td className="p-2 text-right font-mono text-xs text-muted">
                    {r.current_stock_at_source} → {r.current_stock_at_target}
                  </td>
                  <td className="p-2 text-right">
                    {r.status === "pending" && (
                      <div className="flex gap-1 justify-end">
                        <button
                          className="btn text-xs"
                          onClick={() => approveMut.mutate(r.id)}
                          disabled={approveMut.isPending}
                        >
                          <Icon name="check" size={12} /> В очередь
                        </button>
                        <button
                          className="btn text-xs text-muted"
                          onClick={() => dismissMut.mutate(r.id)}
                          disabled={dismissMut.isPending}
                        >
                          <Icon name="close" size={12} />
                        </button>
                      </div>
                    )}
                    {r.status !== "pending" && (
                      <span className="text-xs text-muted">{r.status}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Tasks */}
      <div className="card">
        <h2 className="font-medium mb-3">Очередь и история бронирований</h2>
        <div className="text-xs text-muted mb-3 leading-relaxed">
          Бэкенд опрашивает очередь каждые 2 мин (LEAD-022). Перед отправкой
          проверяется и квота склада-источника (dst тоже), реальная
          отправка кэп'ируется по <code>min(src, dst)</code>. Заявка
          остаётся в <code>queued</code> и ретраится бесконечно пока WB не
          отдаст success — для всех транзитных ошибок (расширение оффлайн,
          dst-квота=0, src дневной лимит исчерпан, 401/токены LK истекли,
          не резолвится office_id). Permanent <code>failed</code> только
          если потерян <code>nm_id</code> (recommendation удалена).
          Зависшую заявку можно снять кнопкой ✕. После accepted ставится
          72-часовой кулдаун на пару (chrt_id × склад-приёмник). В колонке
          «В очереди» цвет: жёлтый &gt;12ч, красный &gt;24ч.
        </div>
        {tasksQ.isLoading && <div className="text-muted">Загрузка…</div>}
        {tasksQ.data && tasksQ.data.items.length === 0 && (
          <div className="text-muted text-sm">Задач в очереди нет.</div>
        )}
        {tasksQ.data && tasksQ.data.items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr className="border-b border-border">
                <th className="text-left p-2">Создана</th>
                <th className="text-left p-2">В очереди</th>
                <th className="text-left p-2">chrt</th>
                <th className="text-left p-2">Откуда → Куда</th>
                <th className="text-right p-2">Qty</th>
                <th className="text-left p-2">Статус</th>
                <th className="text-right p-2">Попыток<br/><span className="text-[10px] normal-case">посл.</span></th>
                <th className="text-left p-2">Последний ответ</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {tasksQ.data.items.map((t) => (
                <tr key={t.id} className="border-t border-border align-top">
                  <td className="p-2 font-mono text-xs">
                    {fmtLocalDt(t.created_at || t.target_window_at)}
                  </td>
                  <td className="p-2 text-xs">
                    <QueueAgeBadge createdAt={t.created_at} status={t.status} />
                  </td>
                  <td className="p-2 font-mono text-xs">{t.chrt_id}</td>
                  <td className="p-2 text-xs">
                    {t.from_office_name} → {t.to_office_name}
                  </td>
                  <td className="p-2 text-right font-mono">{t.qty}</td>
                  <td className="p-2">
                    <TaskStatusBadge status={t.status} acceptedAt={t.accepted_at} />
                  </td>
                  <td className="p-2 text-right font-mono">
                    {t.attempt_count}
                    {t.last_attempt_at && (
                      <div className="text-[10px] text-muted">
                        {fmtLocalTime(t.last_attempt_at)}
                      </div>
                    )}
                  </td>
                  <td className="p-2 text-xs text-muted max-w-[280px]">
                    {t.last_status_code != null && (
                      <span
                        className={`font-mono mr-1 ${
                          t.last_status_code >= 200 && t.last_status_code < 300
                            ? "text-success"
                            : "text-danger"
                        }`}
                      >
                        HTTP {t.last_status_code}
                      </span>
                    )}
                    {t.last_response ? (
                      <span title={t.last_response} className="break-words">
                        {t.last_response.length > 80
                          ? t.last_response.slice(0, 80) + "…"
                          : t.last_response}
                      </span>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="p-2 text-right">
                    {(t.status === "queued" || t.status === "failed") && (
                      <button
                        className="btn text-xs text-muted hover:text-danger"
                        onClick={() => {
                          if (
                            confirm(
                              `Отменить задачу #${t.id} (${t.from_office_name} → ${t.to_office_name}, ${t.qty} шт.)?`,
                            )
                          )
                            cancelMut.mutate(t.id);
                        }}
                        disabled={cancelMut.isPending}
                        title="Снять с polling. Заявка не будет отправлена в WB."
                      >
                        <Icon name="close" size={12} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card text-xs text-muted leading-relaxed">
        <strong>Как это работает:</strong> сервис генерирует рекомендации по
        ROI (логистика + uplift выручки), вы одобряете → попадают в очередь.
        Каждые ~2 мин Celery-консьюмер берёт queued-task'и tenant'а,
        группирует по (склад-источник, склад-приёмник, nmID) и через
        расширение шлёт <code>POST /order</code> в LK shifts API. На каждой
        паре (chrt_id × склад-приёмник) ставится 72-часовой кулдаун. При
        401 — статус LK переходит в «нужен перелогин» (откройте seller.wb.ru
        и переавторизуйтесь — расширение обновит токены автоматически).
      </div>
    </div>
  );
}

function LkStatusCard({
  status,
  onConnect,
  onDisconnect,
}: {
  status: any;
  onConnect: (authorizeV3: string, wbSellerLk: string) => Promise<any>;
  onDisconnect: () => Promise<any>;
}) {
  const [showManual, setShowManual] = useState(false);
  const [tokenA3, setTokenA3] = useState("");
  const [tokenLk, setTokenLk] = useState("");

  if (!status) return <div className="card text-muted">Загрузка…</div>;

  return (
    <div className="card">
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="font-medium">Подключение к LK WB</h2>
        <div className="text-xs">
          {status.lk_connected ? (
            <span className="text-success"><Icon name="check" size={12} /> Подключено</span>
          ) : status.lk_needs_relogin ? (
            <span className="text-warn"><Icon name="warning" size={12} /> Нужен перелогин в WB</span>
          ) : (
            <span className="text-muted">Не подключено</span>
          )}
        </div>
      </div>

      {status.lk_connected ? (
        <>
          <div className="text-xs text-muted leading-relaxed">
            {status.supplier_fid && <>Supplier {status.supplier_fid} · </>}
            {status.phone_last4 && <>Phone ***{status.phone_last4} · </>}
            AuthorizeV3 до: {status.authorize_v3_expires_at?.slice(0, 16) || "—"}
            {status.last_success_at && (
              <> · last success {status.last_success_at.slice(0, 16)}</>
            )}
          </div>
          <div className="text-xs text-muted mt-2 leading-relaxed">
            Токены LK обновляются автоматически расширением, пока открыта
            вкладка <code>seller.wildberries.ru</code>. Бэкенд опрашивает
            очередь заявок каждые 2 мин.
          </div>
          <div className="flex gap-2 mt-3">
            <button
              className="btn text-xs text-danger"
              onClick={() =>
                window.confirm("Отвязать LK-сессию? Бронирования остановятся.") &&
                onDisconnect()
              }
            >
              Отвязать
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="text-xs text-muted leading-relaxed">
            <strong>Как подключить:</strong>
            <ol className="list-decimal list-inside mt-1 space-y-1">
              <li>
                Установите Chrome-расширение SellerFriends (если ещё нет).
              </li>
              <li>
                Откройте{" "}
                <a
                  href="https://seller.wildberries.ru"
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent underline"
                >
                  seller.wildberries.ru
                </a>{" "}
                и залогиньтесь.
              </li>
              <li>
                Подключение произойдёт автоматически в течение 10-30 сек —
                страница обновится сама.
              </li>
            </ol>
          </div>
          <button
            className="text-xs text-muted underline mt-3"
            onClick={() => setShowManual((v) => !v)}
          >
            {showManual ? "Скрыть" : "Подключить вручную (если нет расширения)"}
          </button>
        </>
      )}

      {showManual && !status.lk_connected && (
        <div className="mt-3 border-t border-border pt-3">
          <div className="text-xs text-muted mb-2 leading-relaxed">
            Открой <code>seller.wildberries.ru</code> → F12 → Network →
            фильтр <code>seller-weekly-report</code> → Headers → скопируй{" "}
            <strong>оба</strong> заголовка.
            <br />
            <span className="text-warn">⚠</span> <code>Wb-Seller-Lk</code>{" "}
            живёт 5 мин — нужен только для первого окна. Дальше расширение
            обновляет его само (если оно установлено).
          </div>
          <div className="text-xs text-muted mb-1">AuthorizeV3:</div>
          <textarea
            className="input w-full text-xs font-mono mb-2"
            rows={3}
            value={tokenA3}
            onChange={(e) => setTokenA3(e.target.value)}
            placeholder="eyJhbGciOiJSUzI1NiIs..."
          />
          <div className="text-xs text-muted mb-1">Wb-Seller-Lk (опц.):</div>
          <textarea
            className="input w-full text-xs font-mono"
            rows={2}
            value={tokenLk}
            onChange={(e) => setTokenLk(e.target.value)}
            placeholder="eyJhbGciOiJFZERTQSI..."
          />
          <div className="flex gap-2 mt-2">
            <button
              className="btn text-xs border-accent text-accent"
              onClick={async () => {
                try {
                  await onConnect(tokenA3.trim(), tokenLk.trim());
                  setShowManual(false);
                  setTokenA3("");
                  setTokenLk("");
                } catch (e: any) {
                  alert(`Ошибка: ${e.message}`);
                }
              }}
              disabled={!tokenA3.trim()}
            >
              Сохранить
            </button>
            <button
              className="btn text-xs"
              onClick={() => {
                setShowManual(false);
                setTokenA3("");
                setTokenLk("");
              }}
            >
              Отмена
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function TaskStatusBadge({
  status,
  acceptedAt,
}: {
  status: string;
  acceptedAt: string | null;
}) {
  const tone =
    status === "accepted"
      ? "text-success"
      : status === "failed"
        ? "text-danger"
        : status === "queued"
          ? "text-accent"
          : status === "cancelled"
            ? "text-muted line-through"
            : "text-muted";
  const label =
    status === "queued"
      ? "в очереди"
      : status === "accepted"
        ? "✓ принята"
        : status === "failed"
          ? "✗ ошибка"
          : status === "cancelled"
            ? "отменена"
            : status;
  return (
    <div>
      <span className={`text-xs ${tone}`}>{label}</span>
      {acceptedAt && status === "accepted" && (
        <div className="text-[10px] text-muted font-mono">
          {fmtLocalDt(acceptedAt)}
        </div>
      )}
    </div>
  );
}

function QueueAgeBadge({
  createdAt,
  status,
}: {
  createdAt: string | null;
  status: string;
}) {
  // Возраст показываем только для активных задач — accepted/cancelled
  // зафиксированы и age уже не информативен.
  if (!createdAt || (status !== "queued" && status !== "failed")) {
    return <span className="text-muted">—</span>;
  }
  const ageMs = Date.now() - new Date(createdAt).getTime();
  const ageHours = ageMs / 3_600_000;
  const ageMin = Math.floor((ageMs / 60_000) % 60);
  const ageH = Math.floor(ageHours);
  const text =
    ageH > 0 ? `${ageH}ч ${ageMin}м` : `${ageMin}м`;
  const tone =
    ageHours > 24
      ? "text-danger font-medium"
      : ageHours > 12
        ? "text-warn"
        : "text-muted";
  return <span className={`font-mono ${tone}`}>{text}</span>;
}

function RoiCard({ roi, loading }: { roi: any; loading: boolean }) {
  // TASK-DEV-012: расширенный ROI-дашборд с period selector.
  // Дифференциатор vs QuotaBot/WBCON — у них только % успешных бронирований,
  // у нас ROI в ₽ (экономия логистики − комиссия) + чистая прибыль модуля.
  const [period, setPeriod] = useState<"week" | "month" | "quarter" | "ytd" | "all">("month");

  // Конвертируем period в date_from/date_to
  const range = (() => {
    const today = new Date();
    const fmt = (d: Date) => d.toISOString().slice(0, 10);
    if (period === "all") return {};
    if (period === "ytd") return { from: `${today.getFullYear()}-01-01`, to: fmt(today) };
    const back = period === "week" ? 7 : period === "month" ? 30 : 90;
    const start = new Date(today.getTime() - back * 86400000);
    return { from: fmt(start), to: fmt(today) };
  })();

  // Если переключили period — перезапросить. Но parent уже передаёт `roi`
  // (без period в queryKey) — оставим как есть для MVP, period фильтрует
  // на UI-уровне через локальный fetch (parallel). MVP: показываем то что
  // прилетело + переключатель для UX. Полный реактивный refetch — позже.
  const roiQ = useQuery({
    queryKey: ["redistribution-roi-period", period],
    queryFn: () => api.redistributionRoi(range.from, range.to),
  });
  const r = roiQ.data ?? roi;

  if (loading || (roiQ.isLoading && !r)) {
    return <div className="card text-muted">Загрузка ROI…</div>;
  }
  if (!r) return null;
  const hasData = (r.revenue_rub || 0) > 0 || (r.successful_tasks_count || 0) > 0;
  const netProfit = (r.logistics_saving_rub || 0) - (r.redistribution_fee_rub || 0);

  const periodLabels: Record<string, string> = {
    week: "7 дн",
    month: "30 дн",
    quarter: "3 мес",
    ytd: "С нач.года",
    all: "Всё время",
  };

  return (
    <div className="card">
      <div className="flex items-baseline justify-between mb-3 flex-wrap gap-2">
        <h2 className="font-medium">ROI-дашборд</h2>
        <div className="flex gap-1 text-xs">
          {(Object.keys(periodLabels) as Array<keyof typeof periodLabels>).map((p) => (
            <button
              key={p}
              type="button"
              className={`btn text-xs ${period === p ? "border-accent text-accent" : ""}`}
              onClick={() => setPeriod(p as any)}
            >
              {periodLabels[p]}
            </button>
          ))}
        </div>
      </div>

      {!hasData && (
        <div className="text-xs text-muted mb-3">
          Данных за период «{periodLabels[period]}» ещё нет. Снапшоты ROI
          накапливаются после первых успешных бронирований.
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <Stat
          label="Выручка через перераспр."
          value={fmtRub(r.revenue_rub || 0)}
        />
        <Stat
          label="Экономия на логистике"
          value={fmtRub(r.logistics_saving_rub || 0)}
          tone="success"
        />
        <Stat
          label="Комиссия +0.5%"
          value={fmtRub(r.redistribution_fee_rub || 0)}
          tone="red"
        />
        <Stat
          label="Чистая прибыль модуля"
          value={fmtRub(netProfit)}
          tone={netProfit > 0 ? "success" : netProfit < 0 ? "red" : "muted"}
        />
        <Stat
          label="ROI"
          value={r.roi_pct !== null && r.roi_pct !== undefined ? `+${fmtPct(r.roi_pct, 0)}` : "—"}
          tone={r.roi_pct && r.roi_pct > 0 ? "success" : "muted"}
        />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mt-3">
        <Stat
          label="Успешных бронирований"
          value={fmtNum(r.successful_tasks_count || 0)}
          tone="success"
        />
        <Stat
          label="Неудачных"
          value={fmtNum(r.failed_tasks_count || 0)}
          tone={(r.failed_tasks_count || 0) > 0 ? "red" : "muted"}
        />
        <Stat
          label="Индекс локализации (avg)"
          value={r.il_avg_pct ? `${fmtPct(r.il_avg_pct, 1)}` : "—"}
        />
      </div>
      {hasData && (
        <div className="text-xs text-muted mt-3 leading-relaxed">
          За «{periodLabels[period]}» перераспределение принесло{" "}
          <span className={netProfit > 0 ? "text-success" : "text-danger"}>
            {netProfit > 0 ? "+" : ""}{fmtRub(netProfit)}
          </span>{" "}
          чистой прибыли (экономия на логистике −0.5% комиссии WB). Это{" "}
          <strong>наш дифференциатор</strong> — у QuotaBot/WBCON есть только %
          успешных бронирований, в ₽ никто не считает.
        </div>
      )}

      {/* Monthly bar-chart (доводка TASK-DEV-012) */}
      {r.monthly && r.monthly.length > 0 && (
        <div className="mt-4 pt-4 border-t border-border">
          <div className="text-xs text-muted uppercase tracking-wide mb-2">
            Динамика по месяцам
          </div>
          <RoiMonthlyChart data={r.monthly} />
        </div>
      )}

      {/* Top-10 SKU breakdown (доводка TASK-DEV-012) */}
      {r.top_skus && r.top_skus.length > 0 && (
        <div className="mt-4 pt-4 border-t border-border">
          <div className="text-xs text-muted uppercase tracking-wide mb-2">
            Топ-10 SKU по экономии логистики
          </div>
          <table className="w-full text-sm">
            <thead className="text-xs text-muted">
              <tr>
                <th className="text-left p-1">Артикул WB</th>
                <th className="text-left p-1">Артикул селлера</th>
                <th className="text-left p-1">Бренд</th>
                <th className="text-right p-1">Бронирований</th>
                <th className="text-right p-1">Перевезено (шт)</th>
                <th className="text-right p-1">Экономия ₽</th>
              </tr>
            </thead>
            <tbody>
              {r.top_skus.map((s: any) => (
                <tr key={s.nm_id} className="border-t border-border/30">
                  <td className="p-1 font-mono">{s.nm_id}</td>
                  <td className="p-1">{s.vendor_code || "—"}</td>
                  <td className="p-1 text-muted">{s.brand || "—"}</td>
                  <td className="p-1 text-right font-mono">{fmtNum(s.tasks_count)}</td>
                  <td className="p-1 text-right font-mono">{fmtNum(s.total_qty)}</td>
                  <td className="p-1 text-right text-success font-mono">
                    {fmtRub(s.total_saving_rub)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RoiMonthlyChart({ data }: { data: any[] }) {
  // Простой recharts BarChart с двумя сериями: экономия (зелёный) и комиссия (красный).
  // Tooltip показывает все 4 метрики (revenue / saving / fee / net_profit).
  return (
    <div style={{ width: "100%", height: 220 }}>
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid {...GRID_PROPS} />
          <XAxis {...AXIS_PROPS} dataKey="month" />
          <YAxis
            {...AXIS_PROPS}
            tickFormatter={(v) =>
              Math.abs(v) >= 1000 ? `${Math.round(v / 1000)}k` : String(v)
            }
          />
          <ChartTooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v: any) => fmtRub(v as number)}
          />
          <ChartLegend wrapperStyle={LEGEND_STYLE} />
          <Bar
            dataKey="saving_rub"
            fill={CHART_COLORS[0]}
            name="Экономия логистики"
            stackId="a"
          />
          <Bar
            dataKey="fee_rub"
            fill={CHART_COLORS[4]}
            name="Комиссия +0.5%"
            stackId="b"
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "success" | "red" | "muted";
}) {
  const cls =
    tone === "success" ? "text-success" :
    tone === "red" ? "text-danger" :
    tone === "muted" ? "text-muted" : "text-fg";
  return (
    <div>
      <div className="text-xs text-muted uppercase tracking-wide">{label}</div>
      <div className={`text-lg font-mono tabular-nums mt-1 ${cls}`}>{value}</div>
    </div>
  );
}


/** LEAD-013: per-manager аналитика redistribution. Видна только для
 * director / head_of_sales. Сортирует по net_benefit DESC — кто принёс
 * больше потенциальной экономии.
 */
function RedistributionByManagerWidget() {
  const q = useQuery({
    queryKey: ["redistribution-by-manager"],
    queryFn: () => api.redistributionByManager(),
    refetchInterval: 5 * 60_000,
  });
  if (q.isLoading) return null;
  const users = q.data?.by_user || [];
  if (users.length === 0) return null;
  const sorted = [...users].sort((a, b) => b.total_net_benefit - a.total_net_benefit);

  return (
    <div className="card">
      <h2 className="font-medium mb-3">Перераспределение по менеджерам</h2>
      <table className="w-full text-sm">
        <thead className="text-muted text-xs uppercase">
          <tr className="border-b border-border">
            <th className="text-left p-2">Менеджер</th>
            <th className="text-right p-2">Всего рек.</th>
            <th className="text-right p-2">Net benefit</th>
            <th className="text-right p-2">Saving</th>
            <th className="text-right p-2">Pending</th>
            <th className="text-right p-2">Approved</th>
            <th className="text-right p-2">Executed</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((u) => (
            <tr key={u.user_id ?? "unassigned"} className="border-t border-border">
              <td className="p-2">
                {u.full_name}
                <div className="text-xs text-muted">@{u.username}</div>
              </td>
              <td className="p-2 text-right font-mono">{u.total_count}</td>
              <td className="p-2 text-right font-mono text-success">
                {fmtRub(u.total_net_benefit)}
              </td>
              <td className="p-2 text-right font-mono text-muted">
                {fmtRub(u.total_saving)}
              </td>
              <td className="p-2 text-right font-mono">
                {u.by_status.pending?.count ?? 0}
              </td>
              <td className="p-2 text-right font-mono text-accent">
                {(u.by_status.approved?.count ?? 0) +
                  (u.by_status.queued?.count ?? 0)}
              </td>
              <td className="p-2 text-right font-mono text-success">
                {u.by_status.executed?.count ?? 0}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
