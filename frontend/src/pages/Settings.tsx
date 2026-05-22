import React, { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import CustomMetricsSection from "@/components/CustomMetricsSection";
import { Icon } from "../components/Icon";
import PageHeader from "@/components/PageHeader";

export default function Settings() {
  const qc = useQueryClient();
  const settingsQ = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.getSettings() as Promise<any>,
    // Авто-обновление таблицы «Последние синхронизации» — каждые 5 сек.
    // Чтобы пользователь видел изменения статусов sync без F5.
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
  });
  const whoQ = useQuery({ queryKey: ["whoami"], queryFn: () => api.whoami() });
  const cooldownQ = useQuery({
    queryKey: ["cooldown"],
    queryFn: () => api.getCooldown(),
    refetchInterval: 10_000,
  });
  const tgQ = useQuery({
    queryKey: ["tg-status"],
    queryFn: () => api.tgStatus(),
    refetchInterval: 30_000,
  });

  const [taxSystem, setTaxSystem] = useState("none");
  const [taxRate, setTaxRate] = useState("");
  const [taxMinRate, setTaxMinRate] = useState("");
  const [reduceByInsurance, setReduceByInsurance] = useState(false);
  const [vatPayer, setVatPayer] = useState(false);
  const [vatRate, setVatRate] = useState("0");
  const [fixed, setFixed] = useState("");
  const [buyoutMin, setBuyoutMin] = useState("");
  const [drrMax, setDrrMax] = useState("");
  const [stockoutDays, setStockoutDays] = useState("");
  // TASK-DEV-010: пороги расширенных детекторов
  const [marginMin, setMarginMin] = useState("");
  const [revenueDipDod, setRevenueDipDod] = useState("");
  const [turnoverDropWow, setTurnoverDropWow] = useState("");
  const [newSkuNoSalesDays, setNewSkuNoSalesDays] = useState("");
  const [outlierZ, setOutlierZ] = useState("");
  const [outlierIqr, setOutlierIqr] = useState("");
  const [uploadResult, setUploadResult] = useState<string | null>(null);
  const [syncResult, setSyncResult] = useState<string | null>(null);

  useEffect(() => {
    const s = settingsQ.data?.settings || {};
    setTaxSystem(s.tax_system ?? "none");
    setTaxRate(s.tax_rate ?? "");
    setTaxMinRate(s.tax_min_rate ?? "");
    setReduceByInsurance(s.reduce_by_insurance === "1");
    setVatPayer(s.vat_payer === "1");
    setVatRate(s.vat_rate ?? "0");
    setFixed(s.fixed_costs_monthly ?? "");
    setBuyoutMin(s.buyout_min_pct ?? "");
    setDrrMax(s.drr_max_pct ?? "");
    setStockoutDays(s.stockout_warning_days ?? "");
    setMarginMin(s.margin_min_pct ?? "");
    setRevenueDipDod(s.revenue_dip_dod_pct ?? "");
    setTurnoverDropWow(s.turnover_drop_wow_pct ?? "");
    setNewSkuNoSalesDays(s.new_sku_no_sales_days ?? "");
    setOutlierZ(s.outlier_z_threshold ?? "");
    setOutlierIqr(s.outlier_iqr_multiplier ?? "");
  }, [settingsQ.data]);

  const saveMut = useMutation({
    mutationFn: () =>
      api.putSettings({
        tax_system: taxSystem,
        tax_rate: taxRate ? Number(taxRate) : null,
        tax_min_rate: taxMinRate ? Number(taxMinRate) : null,
        reduce_by_insurance: reduceByInsurance,
        vat_payer: vatPayer,
        vat_rate: vatPayer ? Number(vatRate) : 0,
        fixed_costs_monthly: fixed ? Number(fixed) : null,
        buyout_min_pct: buyoutMin ? Number(buyoutMin) : null,
        drr_max_pct: drrMax ? Number(drrMax) : null,
        stockout_warning_days: stockoutDays ? Number(stockoutDays) : null,
        margin_min_pct: marginMin ? Number(marginMin) : null,
        revenue_dip_dod_pct: revenueDipDod ? Number(revenueDipDod) : null,
        turnover_drop_wow_pct: turnoverDropWow ? Number(turnoverDropWow) : null,
        new_sku_no_sales_days: newSkuNoSalesDays ? Number(newSkuNoSalesDays) : null,
        outlier_z_threshold: outlierZ ? Number(outlierZ) : null,
        outlier_iqr_multiplier: outlierIqr ? Number(outlierIqr) : null,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings"] }),
  });

  const uploadMut = useMutation({
    mutationFn: (f: File) => api.uploadCogs(f),
    onSuccess: (data: any) => {
      setUploadResult(`Загружено: ${data.inserted}, пропущено: ${data.skipped}`);
      qc.invalidateQueries({ queryKey: ["units"] });
    },
    onError: (e: any) => setUploadResult(`Ошибка: ${e.message}`),
  });

  const syncMut = useMutation({
    mutationFn: (payload: { entity: string; daysBack?: number }) =>
      api.triggerSync(payload.entity, payload.daysBack),
    onSuccess: (d, payload) =>
      setSyncResult(
        `Запущена задача ${payload.entity}${
          payload.daysBack ? ` за ${payload.daysBack} дней` : ""
        } → ${d.task_id}`,
      ),
    onError: (e: any) => setSyncResult(`Ошибка: ${e.message}`),
  });

  const tgTestMut = useMutation({
    mutationFn: () => api.tgTest(),
  });
  const tgDigestMut = useMutation({
    mutationFn: (enabled: boolean) => api.tgSetDigest(enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tg-status"] }),
  });
  const tgUnlinkMut = useMutation({
    mutationFn: () => api.tgUnlinkChat(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tg-status"] }),
  });

  // WB token validator (legacy, для проверки токена .env через diagnostics)
  const [tokenInput, setTokenInput] = useState("");
  const [validateResult, setValidateResult] = useState<any | null>(null);
  const validateMut = useMutation({
    mutationFn: (t?: string) => api.validateWbToken(t),
    onSuccess: (d) => setValidateResult(d),
    onError: (e: any) => setValidateResult({ ok: false, error: e.message }),
  });

  // Per-tenant WB-токен (multi-tenant, хранится в БД).
  const wbTokenStatusQ = useQuery({
    queryKey: ["wb-token-status"],
    queryFn: () => api.getWbTokenStatus(),
  });
  const [newWbToken, setNewWbToken] = useState("");
  const [testResult, setTestResult] = useState<{
    valid: boolean;
    error: string | null;
    seller_id: string | null;
  } | null>(null);
  const [autoSyncMsg, setAutoSyncMsg] = useState<string | null>(null);
  const setTokenMut = useMutation({
    mutationFn: (t: string) => api.setWbToken(t),
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["wb-token-status"] });
      qc.invalidateQueries({ queryKey: ["whoami"] });
      qc.invalidateQueries({ queryKey: ["sync-status"] });
      setNewWbToken("");
      setTestResult(null);
      const triggered: string[] = data?.auto_sync_triggered ?? [];
      if (triggered.length > 0) {
        setAutoSyncMsg(
          `✓ Запущен первичный sync за 90 дней: ${triggered.join(
            ", ",
          )}. Прогресс — внизу sidebar'а или в таблице ниже.`,
        );
      } else {
        setAutoSyncMsg(null);
      }
    },
  });
  const testTokenMut = useMutation({
    mutationFn: (t: string) => api.testTenantWbToken(t),
    onSuccess: (d) => setTestResult(d),
  });
  const clearTokenMut = useMutation({
    mutationFn: () => api.clearWbToken(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["wb-token-status"] }),
  });

  const clearCooldownMut = useMutation({
    mutationFn: (cat: string) => api.clearCooldown(cat),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cooldown"] }),
  });

  const sync = settingsQ.data?.sync ?? [];

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <PageHeader title="Настройки" />

      <CustomMetricsSection />

      {/* Новый multi-tenant блок: WB-токен per-tenant хранится в БД,
          вводится через UI. Старый блок ниже («Подключение через .env»)
          — диагностика. */}
      <section className="card">
        <h2 className="font-medium mb-3">Подключение к WB</h2>
        <div className="text-sm text-muted mb-3">
          Вставьте сюда свой WB API-токен — сервис подтянет вашу аналитику.{" "}
          Токен хранится в БД, привязан к вашей компании. Только директор может
          его менять.
        </div>

        <div className="text-sm mb-2">
          Текущий статус:{" "}
          {wbTokenStatusQ.data?.set ? (
            <span className="text-success">
              <Icon name="check" size={12} /> токен установлен{" "}
              {wbTokenStatusQ.data.seller_id && (
                <span className="text-muted">
                  (seller: {wbTokenStatusQ.data.seller_id.slice(0, 8)}…)
                </span>
              )}{" "}
              {wbTokenStatusQ.data.validated_at && (
                <span className="text-muted">
                  · проверен{" "}
                  {new Date(wbTokenStatusQ.data.validated_at).toLocaleString(
                    "ru",
                  )}
                </span>
              )}
            </span>
          ) : (
            <span className="text-warn"><Icon name="close" size={12} /> не настроен</span>
          )}
        </div>

        <textarea
          className="input w-full font-mono text-xs"
          rows={3}
          placeholder="eyJhbGciOi…"
          value={newWbToken}
          onChange={(e: any) => {
            setNewWbToken(e.target.value);
            setTestResult(null);
          }}
        />

        <div className="flex gap-2 mt-2 items-center flex-wrap">
          <button
            type="button"
            className="btn"
            disabled={!newWbToken.trim() || testTokenMut.isPending}
            onClick={() => testTokenMut.mutate(newWbToken.trim())}
          >
            {testTokenMut.isPending ? "Проверяю…" : "Проверить"}
          </button>
          <button
            type="button"
            className="btn border-accent text-accent"
            disabled={
              !newWbToken.trim() ||
              setTokenMut.isPending ||
              (testResult ? !testResult.valid : false)
            }
            onClick={() => setTokenMut.mutate(newWbToken.trim())}
          >
            {setTokenMut.isPending ? "Сохраняю…" : "Сохранить"}
          </button>
          {wbTokenStatusQ.data?.set && (
            <button
              type="button"
              className="btn text-danger"
              disabled={clearTokenMut.isPending}
              onClick={() => {
                if (confirm("Удалить WB-токен? Sync остановится."))
                  clearTokenMut.mutate();
              }}
            >
              Удалить
            </button>
          )}
        </div>

        {testResult && (
          <div className="mt-2 text-sm">
            {testResult.valid ? (
              <span className="text-success">
                <Icon name="check" size={12} /> токен валиден
                {testResult.seller_id &&
                  ` · seller_id: ${testResult.seller_id}`}
              </span>
            ) : (
              <span className="text-danger">
                <Icon name="close" size={12} /> {testResult.error || "ошибка"}
              </span>
            )}
          </div>
        )}

        {setTokenMut.isError && (
          <div className="mt-2 text-danger text-sm">
            {(setTokenMut.error as any)?.message || "ошибка сохранения"}
          </div>
        )}

        {autoSyncMsg && (
          <div className="mt-2 rounded-md bg-success/10 border border-success/30 px-3 py-2 text-sm text-success">
            {autoSyncMsg}
          </div>
        )}
      </section>

      <section className="card">
        <h2 className="font-medium mb-3">Подключение к WB (legacy via .env)</h2>
        <div className="text-sm text-muted leading-relaxed">
          <strong>Альтернатива: токен в `.env`</strong> (используется только
          для default-tenant при single-tenant установке). Если уже задали
          токен через форму выше — этот блок не нужен.
          <br />
          <br />
          <strong>Как получить токен:</strong>
          <ol className="list-decimal list-inside mt-2 space-y-1">
            <li>
              Откройте ЛК WB → <em>Профиль → Настройки → Доступ к API</em>
            </li>
            <li>
              Создайте <strong>не-тестовый</strong> токен (галка «Тестовый» — снять)
            </li>
            <li>
              Включите категории прав:{" "}
              <code className="text-white">Statistics</code>,{" "}
              <code className="text-white">Promotion</code>,{" "}
              <code className="text-white">Finance</code> (рекомендуется)
            </li>
            <li>
              Скопируйте JWT-строку (начинается с <code>eyJ…</code>)
            </li>
            <li>
              В <code className="text-white">.env</code> установите{" "}
              <code className="text-white">WB_TOKEN=&lt;токен&gt;</code> и
              перезапустите контейнеры
            </li>
          </ol>
        </div>
        <div className="mt-3 text-sm">
          Токен в <code>.env</code>:{" "}
          <span className={whoQ.data?.wb_token_configured ? "text-success" : "text-danger"}>
            {whoQ.data?.wb_token_configured ? (
              <><Icon name="check" size={12} /> настроен</>
            ) : (
              <><Icon name="close" size={12} /> не настроен</>
            )}
          </span>
        </div>

        <div className="mt-4 border-t border-border pt-4">
          <h3 className="font-medium text-sm uppercase tracking-wide text-muted mb-2">
            Валидатор токена
          </h3>
          <div className="text-xs text-muted mb-2">
            Проверьте токен <em>до</em> того как класть его в <code>.env</code>: декодируем
            JWT, отправляем один пробный запрос в WB и показываем что вернулось.
          </div>
          <div className="flex gap-2 items-start">
            <input
              type="password"
              className="input flex-1 font-mono text-xs"
              placeholder="Вставьте JWT (eyJ…) или оставьте пустым чтобы проверить токен из .env"
              value={tokenInput}
              onChange={(e: any) => setTokenInput(e.target.value)}
            />
            <button
              className="btn-primary"
              disabled={validateMut.isPending}
              onClick={() => validateMut.mutate(tokenInput || undefined)}
            >
              Проверить
            </button>
          </div>

          {validateResult && (
            <div className="mt-4 text-sm">
              <div
                className={`text-base font-semibold ${
                  validateResult.ok ? "text-success" : "text-danger"
                }`}
              >
                {validateResult.ok ? (
                  <><Icon name="check" size={14} /> Токен валиден</>
                ) : (
                  <><Icon name="close" size={14} /> Есть проблемы</>
                )}
              </div>
              {validateResult.error && (
                <div className="text-danger text-xs mt-1">{validateResult.error}</div>
              )}
              {validateResult.verdict && (
                <div className="text-xs text-muted mt-1">{validateResult.verdict}</div>
              )}

              {validateResult.decoded && (
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-mono">
                  <div>
                    <span className="text-muted">Тип:</span>{" "}
                    {validateResult.decoded.t ? (
                      <span className="text-warn">Тестовый (узкие лимиты!)</span>
                    ) : (
                      <span className="text-success">Обычный</span>
                    )}
                  </div>
                  <div>
                    <span className="text-muted">Истекает:</span>{" "}
                    {validateResult.decoded.expired ? (
                      <span className="text-danger">
                        {validateResult.decoded.expires_at} (истёк!)
                      </span>
                    ) : (
                      validateResult.decoded.expires_at || "—"
                    )}
                  </div>
                  <div>
                    <span className="text-muted">Account:</span>{" "}
                    {validateResult.decoded.acc ?? "—"}
                  </div>
                  <div>
                    <span className="text-muted">Owner ID:</span>{" "}
                    {validateResult.decoded.oid ?? "—"}
                  </div>
                  <div className="col-span-2">
                    <span className="text-muted">Scope bitmask (s):</span>{" "}
                    {validateResult.decoded.scope_bits ?? "—"}
                  </div>
                </div>
              )}

              {validateResult.probe && (
                <div className="mt-3 text-xs">
                  <div className="text-muted">Probe-запрос:</div>
                  <div className="font-mono">
                    HTTP{" "}
                    <span
                      className={
                        validateResult.probe.status === 200
                          ? "text-success"
                          : "text-danger"
                      }
                    >
                      {validateResult.probe.status || "—"}
                    </span>
                    {validateResult.probe.headers &&
                      Object.entries(validateResult.probe.headers).map(([k, v]) => (
                        <div key={k} className="text-muted">
                          {k}: {String(v)}
                        </div>
                      ))}
                  </div>
                  {validateResult.probe.body_preview && (
                    <pre className="text-muted mt-1 overflow-x-auto whitespace-pre-wrap">
                      {validateResult.probe.body_preview}
                    </pre>
                  )}
                </div>
              )}

              {validateResult.issues && validateResult.issues.length > 0 && (
                <ul className="mt-3 list-disc list-inside text-xs text-warn">
                  {validateResult.issues.map((iss: string, i: number) => (
                    <li key={i}>{iss}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </section>

      <section className="card">
        <h2 className="font-medium mb-3">Финансовые параметры</h2>

        <h3 className="font-medium mt-2 mb-3 text-muted text-sm uppercase tracking-wide">
          Налогообложение
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Система налогообложения">
            <select
              value={taxSystem}
              onChange={(e) => {
                const v = e.target.value;
                setTaxSystem(v);
                // подставим дефолтную ставку, если поле пустое
                if (!taxRate) {
                  const defaults: Record<string, string> = {
                    usn_income: "6",
                    usn_income_expense: "15",
                    osn: "25",
                    npd: "6",
                    ausn_income: "8",
                    ausn_income_expense: "20",
                  };
                  if (defaults[v]) setTaxRate(defaults[v]);
                }
                if (!taxMinRate) {
                  if (v === "usn_income_expense") setTaxMinRate("1");
                  if (v === "ausn_income_expense") setTaxMinRate("3");
                }
              }}
              className="input"
            >
              <option value="none">Без налога</option>
              <option value="usn_income">УСН «Доходы»</option>
              <option value="usn_income_expense">УСН «Доходы − Расходы»</option>
              <option value="osn">ОСН (налог на прибыль)</option>
              <option value="patent">Патент (ПСН)</option>
              <option value="npd">НПД (Самозанятые)</option>
              <option value="ausn_income">АУСН «Доходы»</option>
              <option value="ausn_income_expense">АУСН «Доходы − Расходы»</option>
            </select>
          </Field>
          <Field label="Ставка налога, %">
            <input
              value={taxRate}
              onChange={(e) => setTaxRate(e.target.value)}
              placeholder="6"
              className="input"
              disabled={taxSystem === "none" || taxSystem === "patent"}
            />
          </Field>
          {(taxSystem === "usn_income_expense" || taxSystem === "ausn_income_expense") && (
            <Field label="Минимальный налог, %">
              <input
                value={taxMinRate}
                onChange={(e) => setTaxMinRate(e.target.value)}
                placeholder={taxSystem === "ausn_income_expense" ? "3" : "1"}
                className="input"
              />
            </Field>
          )}
          {taxSystem === "usn_income" && (
            <Field label="Уменьшение на страховые">
              <label className="flex items-center gap-2 mt-2">
                <input
                  type="checkbox"
                  checked={reduceByInsurance}
                  onChange={(e) => setReduceByInsurance(e.target.checked)}
                />
                <span className="text-sm">−50% на страховые взносы (ИП без работников)</span>
              </label>
            </Field>
          )}
        </div>

        <h3 className="font-medium mt-6 mb-3 text-muted text-sm uppercase tracking-wide">
          НДС
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Плательщик НДС">
            <label className="flex items-center gap-2 mt-2">
              <input
                type="checkbox"
                checked={vatPayer}
                onChange={(e) => setVatPayer(e.target.checked)}
              />
              <span className="text-sm">
                Да (для УСН — оборот &gt; 60 млн ₽/год; для ОСН — всегда)
              </span>
            </label>
          </Field>
          {vatPayer && (
            <Field label="Ставка НДС, %">
              <select
                value={vatRate}
                onChange={(e) => setVatRate(e.target.value)}
                className="input"
              >
                <option value="0">0% (экспорт / без НДС)</option>
                <option value="5">5% (УСН, оборот 60–250 млн ₽)</option>
                <option value="7">7% (УСН, оборот 250–450 млн ₽)</option>
                <option value="22">22% (общий, с 01.01.2026)</option>
              </select>
            </Field>
          )}
        </div>

        <h3 className="font-medium mt-6 mb-3 text-muted text-sm uppercase tracking-wide">
          Постоянные расходы
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Постоянные расходы / мес, ₽">
            <input
              value={fixed}
              onChange={(e) => setFixed(e.target.value)}
              placeholder="100000"
              className="input"
            />
          </Field>
        </div>
        <div className="text-xs text-muted mt-2">
          Сюда включайте ФОТ, аренду офиса/склада, бухгалтерию, патент (если ПСН) — всё что
          не зависит от объёма продаж. Распределяется в P&amp;L по дням периода равномерно.
        </div>

        <h3 className="font-medium mt-6 mb-3">Пороги алертов</h3>
        <div className="grid grid-cols-3 gap-4">
          <Field label="Минимум выкупа, %">
            <input
              value={buyoutMin}
              onChange={(e) => setBuyoutMin(e.target.value)}
              placeholder="60"
              className="input"
            />
          </Field>
          <Field label="Максимум ДРР, %">
            <input
              value={drrMax}
              onChange={(e) => setDrrMax(e.target.value)}
              placeholder="25"
              className="input"
            />
          </Field>
          <Field label="Дней до стокаута">
            <input
              value={stockoutDays}
              onChange={(e) => setStockoutDays(e.target.value)}
              placeholder="3"
              className="input"
            />
          </Field>
        </div>

        {/* TASK-DEV-010: расширенные пороги (5 новых детекторов) */}
        <h3 className="font-medium mt-6 mb-3">Расширенные пороги аномалий</h3>
        <div className="text-xs text-muted mb-3">
          5 новых детекторов в дополнение к старым 6: маржа, день-к-дню,
          неделя-к-неделе, новые SKU без продаж. Пусто = дефолт (5% / 30% / 25% / 14 дн).
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <Field label="Маржа меньше, %">
            <input
              value={marginMin}
              onChange={(e) => setMarginMin(e.target.value)}
              placeholder="5"
              className="input"
              title="Алерт если маржинальная прибыль компании за неделю меньше N%"
            />
          </Field>
          <Field label="Дневное падение выручки, %">
            <input
              value={revenueDipDod}
              onChange={(e) => setRevenueDipDod(e.target.value)}
              placeholder="30"
              className="input"
              title="Алерт если выручка вчера упала на N% относительно позавчерашнего дня"
            />
          </Field>
          <Field label="Недельное падение заказов, %">
            <input
              value={turnoverDropWow}
              onChange={(e) => setTurnoverDropWow(e.target.value)}
              placeholder="25"
              className="input"
              title="Алерт если заказов на этой неделе на N% меньше прошлой"
            />
          </Field>
          <Field label="SKU без продаж, дней">
            <input
              value={newSkuNoSalesDays}
              onChange={(e) => setNewSkuNoSalesDays(e.target.value)}
              placeholder="14"
              className="input"
              title="Алерт для SKU старше N дней без единого заказа"
            />
          </Field>
          <Field label="Z-порог outlier-детектора">
            <input
              type="number"
              step="0.1"
              value={outlierZ}
              onChange={(e) => setOutlierZ(e.target.value)}
              placeholder="2.0"
              className="input"
              title="TASK-LEAD-026 — порог z-score для статистических аномалий выручки/DRR/выкупа. По умолчанию 2.0 (=отклонение раз в 20 дней). Снизить = больше алертов, повысить = реже."
            />
          </Field>
          <Field label="IQR-множитель Tukey-fence">
            <input
              type="number"
              step="0.1"
              value={outlierIqr}
              onChange={(e) => setOutlierIqr(e.target.value)}
              placeholder="1.5"
              className="input"
              title="TASK-LEAD-026 — множитель Tukey-fence (1.5×IQR). По умолчанию 1.5. Влияет на ширину коридора нормальных значений."
            />
          </Field>
        </div>

        <button
          className="btn-primary mt-4"
          onClick={() => saveMut.mutate()}
          disabled={saveMut.isPending}
        >
          {saveMut.isPending ? "Сохранение…" : "Сохранить"}
        </button>
      </section>

      <section className="card">
        <h2 className="font-medium mb-3">Себестоимость (CSV)</h2>
        <div className="text-sm text-muted mb-3">
          Формат:{" "}
          <code className="text-white">nmId;cost_rub;packaging_rub;fulfillment_rub</code>{" "}
          (разделитель — точка с запятой). Заголовок опционален.
        </div>
        <input
          type="file"
          accept=".csv"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) uploadMut.mutate(f);
          }}
          className="text-sm"
        />
        {uploadResult && <div className="text-sm mt-3">{uploadResult}</div>}
      </section>

      <section className="card">
        <h2 className="font-medium mb-3">Telegram-бот</h2>
        {!tgQ.data?.token_configured ? (
          <div className="text-sm text-muted leading-relaxed">
            Бот не настроен. Чтобы получать ежедневные сводки и реагировать на алерты:
            <ol className="list-decimal list-inside mt-2 space-y-1">
              <li>Создайте бота через <code>@BotFather</code> в Telegram</li>
              <li>Добавьте в <code>.env</code> строку <code>TG_BOT_TOKEN=&lt;ваш токен&gt;</code></li>
              <li>Перезапустите контейнеры: <code>docker compose up -d</code></li>
              <li>Найдите бота в Telegram и отправьте ему <code>/start</code></li>
            </ol>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-xs text-muted">Бот</div>
              <div className="text-sm">
                {tgQ.data.bot_info ? (
                  <span className="text-success">
                    @{tgQ.data.bot_info.username} ({tgQ.data.bot_info.first_name})
                  </span>
                ) : (
                  <span className="text-warn">токен задан, но бот не отвечает</span>
                )}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted">Привязанный чат</div>
              <div className="text-sm">
                {tgQ.data.chat_id ? (
                  <>
                    <span className="text-success">id {tgQ.data.chat_id}</span>{" "}
                    <button
                      className="btn text-xs ml-2"
                      onClick={() => {
                        if (confirm("Отвязать текущий чат? Следующий /start свяжет новый.")) {
                          tgUnlinkMut.mutate();
                        }
                      }}
                    >
                      Отвязать
                    </button>
                  </>
                ) : (
                  <span className="text-warn">
                    не привязан — отправьте <code>/start</code> боту
                  </span>
                )}
              </div>
            </div>
            <div className="col-span-2">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={tgQ.data.digest_enabled}
                  onChange={(e: any) => tgDigestMut.mutate(e.target.checked)}
                />
                <span className="text-sm">
                  Ежедневная утренняя сводка в 09:00 МСК
                </span>
              </label>
            </div>
            <div className="col-span-2 flex gap-2 flex-wrap items-center">
              <button
                className="btn"
                disabled={!tgQ.data.chat_id || tgTestMut.isPending}
                onClick={() => tgTestMut.mutate()}
              >
                Отправить тестовое сообщение
              </button>
              {tgTestMut.isSuccess && (
                <span className="text-success text-xs"><Icon name="check" size={12} /> Отправлено</span>
              )}
              {tgTestMut.isError && (
                <span className="text-danger text-xs">
                  Ошибка: {(tgTestMut.error as Error).message}
                </span>
              )}
            </div>
            <div className="col-span-2 text-xs text-muted">
              Команды бота: <code>/now</code> /<code>/alerts</code> /<code>/pnl</code>{" "}
              /<code>/help</code>
            </div>
          </div>
        )}

        <MyTgSubsection />
      </section>

      <section className="card">
        <h2 className="font-medium mb-3">Cooldown WB API</h2>
        <div className="text-sm text-muted mb-3">
          Когда WB отвечает 429, мы блокируем соответствующую категорию на 10 минут,
          чтобы не углублять penalty. Здесь видно текущее состояние и можно снять
          блокировку вручную (только если WB реально остыл).
        </div>
        <div className="grid grid-cols-3 gap-3">
          {(["statistics", "advert", "common"] as const).map((cat) => {
            const sec = cooldownQ.data?.[cat] ?? 0;
            return (
              <div key={cat} className="border border-border rounded-md p-3">
                <div className="text-xs text-muted uppercase">{cat}</div>
                <div className={`text-lg font-semibold ${sec > 0 ? "text-warn" : "text-success"}`}>
                  {sec > 0 ? `остыть ${sec}s` : "свободно"}
                </div>
                {sec > 0 && (
                  <button
                    className="btn text-xs mt-2"
                    onClick={() => clearCooldownMut.mutate(cat)}
                  >
                    Снять
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </section>

      <TimelineSection />

      <UnitPlanGlobalConfigSection />

      <WbTariffsSection />

      <ExtensionTokensSection />

      <ExcelSection />

      <section className="card">
        <h2 className="font-medium mb-3">Синхронизация</h2>

        {/* Первичный backfill — большая яркая кнопка для нового кабинета.
            Запускает per-tenant таски для report_detail / orders / sales /
            stocks / paid_storage / redeem / offset_acts / ad_* с указанным
            окном в днях. */}
        <div className="rounded-lg bg-accent/10 border border-accent/30 p-3 mb-4">
          <div className="font-medium mb-1">Первичная выгрузка (для нового кабинета)</div>
          <div className="text-sm text-muted mb-3">
            Запустит фоновый sync всех видов данных за выбранный период. Можно
            закрыть страницу — задачи продолжат идти. Прогресс виден внизу
            sidebar'а (точка-индикатор) и в таблице ниже. Полная выгрузка
            года: ~40-60 минут (finance-api 1 req/мин).
          </div>
          <div className="flex flex-wrap gap-2 items-center">
            {[
              [30, "30 дней"],
              [90, "90 дней"],
              [180, "6 месяцев"],
              [365, "1 год"],
              [505, "С 01.01.2025"],
              [1825, "Вся история (5 лет)"],
            ].map(([days, label]) => (
              <button
                key={String(days)}
                className="btn"
                onClick={() =>
                  syncMut.mutate({ entity: "all", daysBack: Number(days) })
                }
                disabled={syncMut.isPending}
                title={
                  Number(days) > 365
                    ? "WB не у всех кабинетов хранит так глубоко — успешные периоды появятся, остальное вернётся пусто без ошибки"
                    : undefined
                }
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="text-xs uppercase tracking-wider text-faint mb-2">
          Обычный sync (свежие данные кабинета)
        </div>
        <div className="text-tiny text-muted mb-2">
          Подтянуть свежие данные одной сущности. Только для текущего кабинета.
          Для глубокой выгрузки → секция «Первичная выгрузка» сверху или «Отчёт
          реализации» ниже.
        </div>
        <div className="flex flex-wrap gap-2 mb-4">
          {[
            ["orders", "Заказы", "Заказы с WB (по retention 90 дней)"],
            ["sales", "Продажи", "Продажи с WB"],
            ["stocks", "Остатки", "Снэпшот остатков на складах"],
            ["paid_storage", "Платное хранение", "Расходы на хранение, последние 7 дней"],
            ["ad_campaigns", "Реклама: кампании", "Обновить список рекламных кампаний"],
            ["ad_stats", "Реклама: стат-ка", "Расходы и клики по кампаниям, ~60 дней"],
          ].map(([key, label, tooltip]) => (
            <button
              key={key}
              className="btn"
              onClick={() => syncMut.mutate({ entity: key })}
              disabled={syncMut.isPending}
              title={tooltip}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="text-xs uppercase tracking-wider text-faint mb-2">
          Отчёт реализации — выбор глубины
        </div>
        <div className="text-tiny text-muted mb-2">
          Финансовый отчёт WB (P&L / Reconciliation / налоги). Глубже → дольше
          (finance-api 1 запрос/минуту).
        </div>
        <div className="flex flex-wrap gap-2 mb-4">
          {[
            [14, "2 недели"],
            [90, "12 недель"],
            [180, "6 месяцев"],
            [365, "1 год"],
            [505, "С 01.01.2025"],
            [1825, "Вся история"],
          ].map(([days, label]) => (
            <button
              key={String(days)}
              className="btn"
              onClick={() =>
                syncMut.mutate({ entity: "report_detail", daysBack: Number(days) })
              }
              disabled={syncMut.isPending}
              title={`Отчёт реализации за ${days} дней назад (только текущий кабинет)`}
            >
              {label}
            </button>
          ))}
        </div>
        {syncResult && <div className="text-sm mb-3">{syncResult}</div>}

        <table className="w-full text-sm">
          <thead className="text-muted text-xs uppercase">
            <tr>
              <th className="text-left p-2">Сущность</th>
              <th className="text-left p-2">Последний синк</th>
              <th className="text-left p-2">Статус</th>
              <th className="text-right p-2">Строк</th>
              <th className="text-left p-2">Ошибка</th>
            </tr>
          </thead>
          <tbody>
            {sync.length === 0 && (
              <tr>
                <td colSpan={5} className="p-4 text-center text-muted">
                  Ещё не было синхронизаций
                </td>
              </tr>
            )}
            {sync.map((s: any) => (
              <tr key={s.entity} className="border-t border-border">
                <td className="p-2 font-mono">{s.entity}</td>
                <td className="p-2" title={s.last_synced_at ?? ""}>
                  {s.last_synced_at
                    ? new Date(s.last_synced_at).toLocaleString("ru-RU", {
                        year: "numeric",
                        month: "2-digit",
                        day: "2-digit",
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })
                    : "—"}
                </td>
                <td className="p-2">
                  <span
                    className={
                      s.last_status === "ok"
                        ? "text-success"
                        : s.last_status
                          ? "text-danger"
                          : "text-muted"
                    }
                  >
                    {s.last_status ?? "—"}
                  </span>
                </td>
                <td className="p-2 text-right">{s.rows_processed}</td>
                <td className="p-2 text-danger text-xs">{s.last_error ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <style>{`.input { background: #13161d; border: 1px solid #262a35; border-radius: 6px; padding: 8px 10px; font-size: 14px; color: white; width: 100%; }`}</style>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted uppercase tracking-wide">{label}</span>
      {children}
    </label>
  );
}

/** Подсказка под полем ИЛ/ИРП-коэф: фактический коэффициент из истории
 * за N дней + кнопка «Применить» (копирует в input). Скрывает себя если
 * данных не хватает (нет продаж / нет тарифов / нет volume_l). */
function CoefRecommendationHint({
  kind,
  actual,
  rowsUsed,
  periodDays,
  currentDraft,
  onApply,
}: {
  kind: "il" | "irp";
  actual: string | null;
  rowsUsed: number;
  periodDays: number;
  currentDraft: string;
  onApply: (v: string) => void;
}) {
  if (actual == null || rowsUsed === 0) {
    return (
      <div className="text-tiny text-muted mt-1">
        📊 Фактический коэффициент пока недоступен (нужны данные продаж за
        последние {periodDays} дн +{" "}
        {kind === "il" ? "volume_l и WB-тарифы по складам" : "поле paid_acceptance"}
        ).
      </div>
    );
  }
  const sameValue = currentDraft && Math.abs(Number(currentDraft) - Number(actual)) < 1e-6;
  return (
    <div className="text-tiny text-muted mt-1 flex items-center gap-2">
      <span>
        📊 Фактический за {periodDays} дн:{" "}
        <span className="font-mono text-fg">{actual}</span>
        {kind === "irp" && (
          <>
            {" "}(
            <span className="font-mono">
              {(Number(actual) * 100).toFixed(2)}%
            </span>
            )
          </>
        )}
        {" · "}
        <span className="text-faint">{rowsUsed} шт</span>
      </span>
      {!sameValue && (
        <button
          type="button"
          className="btn btn-secondary text-tiny px-2 py-0.5"
          onClick={() => onApply(actual)}
          title="Подставить фактический коэффициент в поле"
        >
          Применить
        </button>
      )}
    </div>
  );
}

function ActorSection() {
  // Until full Users/Auth lands the operator picks a name here. Stored in
  // localStorage and sent on every API call as `X-Actor:` header → audit log
  // records who did each mutation. Default empty → audit shows "system".
  const [actor, setActor] = useState<string>(() => {
    try {
      return localStorage.getItem("rnp.actor") || "";
    } catch {
      return "";
    }
  });
  const [saved, setSaved] = useState(false);

  const save = () => {
    try {
      const v = actor.trim().slice(0, 64);
      if (v) localStorage.setItem("rnp.actor", v);
      else localStorage.removeItem("rnp.actor");
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      /* ignore */
    }
  };

  return (
    <section className="card">
      <h2 className="font-medium mb-1">Кто я (для audit-log)</h2>
      <div className="text-xs text-muted mb-3">
        Имя сохранится в браузере и будет отправляться в каждую CRUD-операцию
        как заголовок <code>X-Actor</code>. В Audit log будет видно кто именно
        менял COGS / OPEX / налоги / группы. Пусто → «system».
      </div>
      <div className="flex gap-2 items-end">
        <input
          type="text"
          className="input flex-1 max-w-sm"
          placeholder="напр. Иван Петров"
          value={actor}
          onChange={(e: any) => setActor(e.target.value)}
        />
        <button className="btn-primary" onClick={save}>
          Сохранить
        </button>
        {saved && <span className="text-success text-sm self-center">✓</span>}
      </div>
    </section>
  );
}

// Human-readable labels for timelineable keys (used in the dropdown)
const TIMELINE_KEY_LABELS: Record<string, string> = {
  tax_system: "Система налогообложения (tax_system)",
  tax_rate: "Налоговая ставка, % (tax_rate)",
  tax_min_rate: "Мин. налог, % (tax_min_rate)",
  reduce_by_insurance: "Уменьшать УСН-Д на страховые (reduce_by_insurance)",
  vat_payer: "Плательщик НДС (vat_payer)",
  vat_rate: "Ставка НДС, % (vat_rate)",
};

const TAX_SYSTEM_OPTIONS: Array<[string, string]> = [
  ["none", "Нет"],
  ["usn_income", "УСН «Доходы»"],
  ["usn_income_expense", "УСН «Доходы − Расходы»"],
  ["osn", "ОСН"],
  ["patent", "Патент"],
  ["npd", "НПД"],
  ["ausn_income", "АУСН «Доходы»"],
  ["ausn_income_expense", "АУСН «Доходы − Расходы»"],
];

function TimelineSection() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["setting-timeline"],
    queryFn: () => api.listSettingTimeline(),
  });
  const [key, setKey] = useState("vat_rate");
  const [value, setValue] = useState("");
  const [effFrom, setEffFrom] = useState("");
  const [comment, setComment] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const createMut = useMutation({
    mutationFn: () =>
      api.createSettingTimeline({
        key,
        value,
        effective_from: effFrom,
        comment: comment || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["setting-timeline"] });
      setValue("");
      setEffFrom("");
      setComment("");
      setErr(null);
    },
    onError: (e: any) => setErr(e.message),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deleteSettingTimeline(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["setting-timeline"] }),
  });

  const items = q.data?.items ?? [];
  const allowed = q.data?.allowed_keys ?? [];

  // Group entries by key for the table
  const grouped: Record<string, typeof items> = {};
  for (const it of items) (grouped[it.key] ||= []).push(it);

  return (
    <section className="card">
      <h2 className="font-medium mb-1">Расписание налогов / НДС</h2>
      <div className="text-xs text-muted mb-3">
        Если ставка налога/НДС или система налогообложения должны измениться
        с конкретной даты — добавьте запись здесь. P&L будет считать каждый
        бакет с актуальным значением для его даты. Если для даты нет записи в
        расписании — берётся текущее значение из секции «Налоги» выше.
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-2 items-end mb-3">
        <Field label="Ключ">
          <select
            className="input"
            value={key}
            onChange={(e: any) => setKey(e.target.value)}
          >
            {allowed.map((k) => (
              <option key={k} value={k}>
                {TIMELINE_KEY_LABELS[k] || k}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Действует с">
          <input
            type="date"
            className="input"
            value={effFrom}
            onChange={(e: any) => setEffFrom(e.target.value)}
          />
        </Field>
        <Field label="Значение">
          {key === "tax_system" ? (
            <select
              className="input"
              value={value}
              onChange={(e: any) => setValue(e.target.value)}
            >
              <option value="">— выберите —</option>
              {TAX_SYSTEM_OPTIONS.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          ) : key === "vat_payer" || key === "reduce_by_insurance" ? (
            <select
              className="input"
              value={value}
              onChange={(e: any) => setValue(e.target.value)}
            >
              <option value="">— выберите —</option>
              <option value="1">Да</option>
              <option value="0">Нет</option>
            </select>
          ) : (
            <input
              type="number"
              step="0.01"
              className="input"
              placeholder={key === "vat_rate" ? "0 / 5 / 7 / 22" : "число"}
              value={value}
              onChange={(e: any) => setValue(e.target.value)}
            />
          )}
        </Field>
        <Field label="Комментарий">
          <input
            type="text"
            className="input"
            placeholder="напр. «Ставка НДС 22% с 2026»"
            value={comment}
            onChange={(e: any) => setComment(e.target.value)}
          />
        </Field>
        <button
          className="btn-primary"
          disabled={!key || !value || !effFrom || createMut.isPending}
          onClick={() => createMut.mutate()}
        >
          Добавить
        </button>
      </div>

      {err && <div className="text-danger text-xs mb-2">{err}</div>}

      {Object.keys(grouped).length === 0 ? (
        <div className="text-muted text-sm">
          Записей нет — все периоды считаются по текущим значениям из секции
          «Налоги».
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-muted text-xs uppercase">
            <tr>
              <th className="text-left p-2">Ключ</th>
              <th className="text-left p-2">Действует с</th>
              <th className="text-left p-2">Значение</th>
              <th className="text-left p-2">Комментарий</th>
              <th className="p-2"></th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(grouped).map(([k, rows]) =>
              rows.map((r, idx) => (
                <tr key={r.id} className="border-t border-border">
                  <td className="p-2">
                    {idx === 0 ? (
                      <span className="font-mono text-xs">{k}</span>
                    ) : (
                      <span className="text-muted text-xs">↳</span>
                    )}
                  </td>
                  <td className="p-2 font-mono">{r.effective_from}</td>
                  <td className="p-2 font-medium">{r.value}</td>
                  <td className="p-2 text-muted text-xs">
                    {r.comment ?? ""}
                  </td>
                  <td className="p-2 text-right">
                    <button
                      className="btn text-xs"
                      onClick={() => deleteMut.mutate(r.id)}
                    >
                      <Icon name="close" size={12} />
                    </button>
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      )}
    </section>
  );
}

type ImportResult = {
  inserted: number;
  updated: number;
  skipped: number;
  errors: string[];
};

// ─────────────────────────────────────────────────────────────────────────
// UNIT-PLAN-007 — глобальные константы UNIT-плана (UNIT_PLAN.md §2).
// Только директор (страница уже под directorOnly в App.tsx).
// PUT создаёт НОВУЮ запись в unit_plan_global_config (timeline-версионирование),
// текущая остаётся в истории. UI читает latest через GET.
// ─────────────────────────────────────────────────────────────────────────

type UnitPlanConfigDraft = {
  effective_date: string;
  wb_club_pct: string;
  spp_default_pct: string;
  wb_wallet_pct: string;
  acquiring_pct: string;
  il_coef: string;
  irp_coef: string;
  marketing_pct: string;
  tax_pct: string;
  vat_mode: "include" | "exclude" | "none";
  vat_pct: string;
  acceptance_rub_per_liter: string;
  acceptance_multiplier: string;
  velocity_days: string;
  buyout_fallback_pct: string;
  storage_days: string;
  reverse_logistics_mode: "tariff" | "flat_50";
  spp_by_subject: Array<{ subject: string; pct: string }>;
};

const EMPTY_DRAFT: UnitPlanConfigDraft = {
  effective_date: "",
  wb_club_pct: "",
  spp_default_pct: "",
  wb_wallet_pct: "",
  acquiring_pct: "",
  il_coef: "",
  irp_coef: "",
  marketing_pct: "",
  tax_pct: "",
  vat_mode: "exclude",
  vat_pct: "",
  acceptance_rub_per_liter: "",
  acceptance_multiplier: "",
  velocity_days: "",
  buyout_fallback_pct: "",
  storage_days: "",
  reverse_logistics_mode: "tariff",
  spp_by_subject: [],
};

function tomorrowISO(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
}

function draftFromConfig(c: any): UnitPlanConfigDraft {
  const sbs = c?.spp_by_subject ?? {};
  return {
    effective_date: c?.effective_date ?? "",
    wb_club_pct: c?.wb_club_pct?.toString() ?? "",
    spp_default_pct: c?.spp_default_pct?.toString() ?? "",
    wb_wallet_pct: c?.wb_wallet_pct?.toString() ?? "",
    acquiring_pct: c?.acquiring_pct?.toString() ?? "",
    il_coef: c?.il_coef?.toString() ?? "",
    irp_coef: c?.irp_coef?.toString() ?? "",
    marketing_pct: c?.marketing_pct?.toString() ?? "",
    tax_pct: c?.tax_pct?.toString() ?? "",
    vat_mode: (c?.vat_mode as any) ?? "exclude",
    vat_pct: c?.vat_pct?.toString() ?? "",
    acceptance_rub_per_liter: c?.acceptance_rub_per_liter?.toString() ?? "",
    acceptance_multiplier: c?.acceptance_multiplier?.toString() ?? "",
    velocity_days: c?.velocity_days?.toString() ?? "",
    buyout_fallback_pct: c?.buyout_fallback_pct?.toString() ?? "",
    storage_days: c?.storage_days?.toString() ?? "",
    reverse_logistics_mode:
      (c?.reverse_logistics_mode as "tariff" | "flat_50") ?? "tariff",
    spp_by_subject: Object.entries(sbs).map(([subject, pct]) => ({
      subject,
      pct: String(pct),
    })),
  };
}

function UnitPlanGlobalConfigSection() {
  const qc = useQueryClient();
  const cfgQ = useQuery({
    queryKey: ["unit-plan-global-config"],
    queryFn: () => api.unitPlanGlobalConfig(),
  });
  // Фактические il/irp коэф из истории (для подсказки под полями).
  const coefRecQ = useQuery({
    queryKey: ["unit-plan-coef-recs", 30],
    queryFn: () => api.unitPlanCoefRecommendations(30),
    retry: false,
    staleTime: 5 * 60_000,
  });

  const [draft, setDraft] = useState<UnitPlanConfigDraft>(EMPTY_DRAFT);
  const [newEffDate, setNewEffDate] = useState<string>("");
  const [errors, setErrors] = useState<string[]>([]);
  const [okMsg, setOkMsg] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);

  useEffect(() => {
    if (cfgQ.data) setDraft(draftFromConfig(cfgQ.data));
  }, [cfgQ.data]);

  useEffect(() => {
    if (!newEffDate) setNewEffDate(tomorrowISO());
  }, [newEffDate]);

  const validate = (): string[] => {
    const errs: string[] = [];
    const pct = (label: string, v: string, min = 0, max = 100) => {
      const n = Number(v);
      if (!isFinite(n)) errs.push(`${label}: не число`);
      else if (n < min || n > max) errs.push(`${label}: вне диапазона ${min}-${max}%`);
    };
    pct("WB Клуб %", draft.wb_club_pct);
    pct("СПП default %", draft.spp_default_pct);
    pct("WB Wallet %", draft.wb_wallet_pct);
    pct("Эквайринг %", draft.acquiring_pct);
    pct("Реклама %", draft.marketing_pct);
    pct("Налог %", draft.tax_pct);
    pct("НДС %", draft.vat_pct);
    pct("Fallback % выкупа", draft.buyout_fallback_pct);
    // ИЛ-коэф 0.5-3.0
    const il = Number(draft.il_coef);
    if (!isFinite(il) || il < 0.5 || il > 3.0)
      errs.push("ИЛ-коэф: вне диапазона 0.5-3.0");
    // ИРП-коэф 0-0.1 (доля)
    const irp = Number(draft.irp_coef);
    if (!isFinite(irp) || irp < 0 || irp > 0.1)
      errs.push("ИРП-коэф: вне диапазона 0-0.1 (как доля, напр. 0.017 = 1.7%)");
    // int > 0
    const intPositive = (label: string, v: string) => {
      const n = Number(v);
      if (!Number.isInteger(n) || n <= 0)
        errs.push(`${label}: целое число > 0`);
    };
    intPositive("velocity_days", draft.velocity_days);
    intPositive("storage_days", draft.storage_days);
    // acceptance — >= 0
    const acc = Number(draft.acceptance_rub_per_liter);
    if (!isFinite(acc) || acc < 0) errs.push("Платная приёмка ₽/л: >= 0");
    const accMul = Number(draft.acceptance_multiplier);
    if (!isFinite(accMul) || accMul <= 0)
      errs.push("Множитель приёмки: > 0");
    // spp_by_subject
    draft.spp_by_subject.forEach((row, i) => {
      if (!row.subject.trim())
        errs.push(`СПП по предметам #${i + 1}: пустой предмет`);
      const n = Number(row.pct);
      if (!isFinite(n) || n < 0 || n > 100)
        errs.push(`СПП по предметам "${row.subject}": % вне 0-100`);
    });
    // effective_date
    if (!newEffDate) errs.push("Не указана дата вступления в силу");
    return errs;
  };

  const saveMut = useMutation({
    mutationFn: () => {
      const sbs: Record<string, number> = {};
      for (const r of draft.spp_by_subject) {
        sbs[r.subject.trim()] = Number(r.pct);
      }
      return api.unitPlanSetGlobalConfig({
        effective_date: newEffDate,
        wb_club_pct: Number(draft.wb_club_pct),
        spp_default_pct: Number(draft.spp_default_pct),
        spp_by_subject: sbs,
        wb_wallet_pct: Number(draft.wb_wallet_pct),
        acquiring_pct: Number(draft.acquiring_pct),
        il_coef: Number(draft.il_coef),
        irp_coef: Number(draft.irp_coef),
        marketing_pct: Number(draft.marketing_pct),
        tax_pct: Number(draft.tax_pct),
        vat_mode: draft.vat_mode,
        vat_pct: Number(draft.vat_pct),
        acceptance_rub_per_liter: Number(draft.acceptance_rub_per_liter),
        acceptance_multiplier: Number(draft.acceptance_multiplier),
        velocity_days: Number(draft.velocity_days),
        buyout_fallback_pct: Number(draft.buyout_fallback_pct),
        storage_days: Number(draft.storage_days),
        reverse_logistics_mode: draft.reverse_logistics_mode,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["unit-plan-global-config"] });
      qc.invalidateQueries({ queryKey: ["unit-plan-rows"] });
      setOkMsg(`✓ Сохранено. Новая версия действует с ${newEffDate}.`);
      setNewEffDate(tomorrowISO());
      setTimeout(() => setOkMsg(null), 5000);
    },
    onError: (e: any) => setErrors([e.message || "Ошибка сохранения"]),
  });

  const onSave = () => {
    const errs = validate();
    setErrors(errs);
    if (errs.length === 0) saveMut.mutate();
  };

  const onReset = () => {
    if (cfgQ.data) setDraft(draftFromConfig(cfgQ.data));
    setErrors([]);
    setOkMsg(null);
  };

  const addSubjectRow = () =>
    setDraft((d) => ({
      ...d,
      spp_by_subject: [...d.spp_by_subject, { subject: "", pct: "" }],
    }));

  const updateSubjectRow = (
    i: number,
    patch: Partial<{ subject: string; pct: string }>,
  ) =>
    setDraft((d) => ({
      ...d,
      spp_by_subject: d.spp_by_subject.map((row, j) =>
        j === i ? { ...row, ...patch } : row,
      ),
    }));

  const removeSubjectRow = (i: number) =>
    setDraft((d) => ({
      ...d,
      spp_by_subject: d.spp_by_subject.filter((_, j) => j !== i),
    }));

  return (
    <section id="unit-plan" className="card">
      <div className="flex items-baseline justify-between flex-wrap gap-2 mb-1">
        <h2 className="font-medium">UNIT-план — параметры расчёта</h2>
        <button
          type="button"
          className="btn text-xs"
          onClick={() => setHistoryOpen((v) => !v)}
        >
          {historyOpen ? "Скрыть историю" : "История версий ▾"}
        </button>
      </div>
      <div className="text-xs text-muted mb-4">
        Глобальные константы расчёта UNIT-плана: pricing ladder, ИЛ/ИРП-коэфы,
        % рекламы, налогов, НДС, приёмки и скорость распродажи. Сохранение
        создаёт <strong>новую версию</strong> с указанной датой вступления в
        силу — текущие настройки остаются в истории. См.{" "}
        <code className="text-white">UNIT_PLAN.md §2</code>.
      </div>

      {cfgQ.isLoading && (
        <div className="text-sm text-muted">Загрузка…</div>
      )}
      {cfgQ.isError && (
        <div className="text-sm text-danger">
          Не удалось загрузить конфиг: {(cfgQ.error as Error)?.message}
        </div>
      )}

      {cfgQ.data && (
        <>
          <div className="text-sm mb-3">
            Текущая версия: effective_date ={" "}
            <strong>{cfgQ.data.effective_date}</strong>
            {cfgQ.data.id !== undefined && (
              <span className="text-muted"> · id {cfgQ.data.id}</span>
            )}
          </div>

          {historyOpen && (
            <UnitPlanGlobalConfigHistory currentId={cfgQ.data?.id} />
          )}

          {/* Group 1: Price ladder */}
          <h3 className="font-medium mt-2 mb-3 text-muted text-sm uppercase tracking-wide">
            Pricing ladder
          </h3>
          <div className="grid grid-cols-2 gap-4">
            <Field label="WB Клуб, %">
              <input
                type="number"
                className="input"
                step="0.01"
                min="0"
                max="100"
                value={draft.wb_club_pct}
                onChange={(e: any) =>
                  setDraft((d) => ({ ...d, wb_club_pct: e.target.value }))
                }
              />
            </Field>
            <Field label="СПП default, %">
              <input
                type="number"
                className="input"
                step="0.01"
                min="0"
                max="100"
                value={draft.spp_default_pct}
                onChange={(e: any) =>
                  setDraft((d) => ({ ...d, spp_default_pct: e.target.value }))
                }
              />
            </Field>
            <Field label="WB Wallet, %">
              <input
                type="number"
                className="input"
                step="0.01"
                min="0"
                max="100"
                value={draft.wb_wallet_pct}
                onChange={(e: any) =>
                  setDraft((d) => ({ ...d, wb_wallet_pct: e.target.value }))
                }
              />
            </Field>
            <Field label="Эквайринг, %">
              <input
                type="number"
                className="input"
                step="0.01"
                min="0"
                max="100"
                value={draft.acquiring_pct}
                onChange={(e: any) =>
                  setDraft((d) => ({ ...d, acquiring_pct: e.target.value }))
                }
              />
            </Field>
          </div>

          {/* SPP by subject (mini-table) */}
          <div className="mt-4">
            <div className="text-xs text-muted uppercase tracking-wide mb-2">
              СПП по предметам (опционально, перекрывает default)
            </div>
            <div className="text-xs text-muted mb-2">
              Приоритет: per-row override → per-subject (здесь) → global
              default. Например, «Пижамы» → 28%.
            </div>
            {draft.spp_by_subject.length === 0 && (
              <div className="text-xs text-muted mb-2">
                Пока нет переопределений. Все предметы используют СПП default.
              </div>
            )}
            {draft.spp_by_subject.map((row, i) => (
              <div
                key={i}
                className="flex gap-2 items-center mb-2"
              >
                <input
                  type="text"
                  className="input flex-1 max-w-sm"
                  placeholder="Название предмета (напр. Пижамы)"
                  value={row.subject}
                  onChange={(e: any) =>
                    updateSubjectRow(i, { subject: e.target.value })
                  }
                />
                <input
                  type="number"
                  className="input w-24"
                  step="0.01"
                  min="0"
                  max="100"
                  placeholder="%"
                  value={row.pct}
                  onChange={(e: any) =>
                    updateSubjectRow(i, { pct: e.target.value })
                  }
                />
                <button
                  type="button"
                  className="btn text-xs text-danger"
                  onClick={() => removeSubjectRow(i)}
                  title="Удалить строку"
                >
                  <Icon name="close" size={12} />
                </button>
              </div>
            ))}
            <button
              type="button"
              className="btn text-xs"
              onClick={addSubjectRow}
            >
              + Добавить предмет
            </button>
          </div>

          {/* Group 2: Coefs */}
          <h3 className="font-medium mt-6 mb-3 text-muted text-sm uppercase tracking-wide">
            Coefs
          </h3>
          <div className="grid grid-cols-2 gap-4">
            <Field label="ИЛ-коэф (логистика, 1.16)">
              <input
                type="number"
                className="input"
                step="0.01"
                min="0.5"
                max="3.0"
                value={draft.il_coef}
                onChange={(e: any) =>
                  setDraft((d) => ({ ...d, il_coef: e.target.value }))
                }
              />
              <CoefRecommendationHint
                kind="il"
                actual={coefRecQ.data?.il_coef_actual ?? null}
                rowsUsed={coefRecQ.data?.rows_used_il ?? 0}
                periodDays={coefRecQ.data?.period_days ?? 30}
                currentDraft={draft.il_coef}
                onApply={(v) =>
                  setDraft((d) => ({ ...d, il_coef: v }))
                }
              />
            </Field>
            <Field label="ИРП-коэф (% от цены, как доля 0.017 = 1.7%)">
              <input
                type="number"
                className="input"
                step="0.001"
                min="0"
                max="0.1"
                value={draft.irp_coef}
                onChange={(e: any) =>
                  setDraft((d) => ({ ...d, irp_coef: e.target.value }))
                }
              />
              <CoefRecommendationHint
                kind="irp"
                actual={coefRecQ.data?.irp_coef_actual ?? null}
                rowsUsed={coefRecQ.data?.rows_used_irp ?? 0}
                periodDays={coefRecQ.data?.period_days ?? 30}
                currentDraft={draft.irp_coef}
                onApply={(v) =>
                  setDraft((d) => ({ ...d, irp_coef: v }))
                }
              />
            </Field>
          </div>

          {/* Group 3: Cost percentages */}
          <h3 className="font-medium mt-6 mb-3 text-muted text-sm uppercase tracking-wide">
            Cost percentages
          </h3>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Реклама, %">
              <input
                type="number"
                className="input"
                step="0.01"
                min="0"
                max="100"
                value={draft.marketing_pct}
                onChange={(e: any) =>
                  setDraft((d) => ({ ...d, marketing_pct: e.target.value }))
                }
              />
            </Field>
            <Field label="Налог, %">
              <input
                type="number"
                className="input"
                step="0.01"
                min="0"
                max="100"
                value={draft.tax_pct}
                onChange={(e: any) =>
                  setDraft((d) => ({ ...d, tax_pct: e.target.value }))
                }
              />
            </Field>
            <Field label="НДС режим">
              <select
                className="input"
                value={draft.vat_mode}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    vat_mode: e.target.value as
                      | "include"
                      | "exclude"
                      | "none",
                  }))
                }
              >
                <option value="include">include (в цене)</option>
                <option value="exclude">exclude (сверху)</option>
                <option value="none">none (не считаем)</option>
              </select>
            </Field>
            <Field label="НДС ставка, %">
              <input
                type="number"
                className="input"
                step="0.01"
                min="0"
                max="100"
                value={draft.vat_pct}
                onChange={(e: any) =>
                  setDraft((d) => ({ ...d, vat_pct: e.target.value }))
                }
              />
            </Field>
          </div>

          {/* Group 4: Acceptance + velocity */}
          <h3 className="font-medium mt-6 mb-3 text-muted text-sm uppercase tracking-wide">
            Приёмка и скорость
          </h3>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Платная приёмка, ₽/л">
              <input
                type="number"
                className="input"
                step="0.01"
                min="0"
                value={draft.acceptance_rub_per_liter}
                onChange={(e: any) =>
                  setDraft((d) => ({
                    ...d,
                    acceptance_rub_per_liter: e.target.value,
                  }))
                }
              />
            </Field>
            <Field label="Множитель приёмки">
              <input
                type="number"
                className="input"
                step="0.01"
                min="0"
                value={draft.acceptance_multiplier}
                onChange={(e: any) =>
                  setDraft((d) => ({
                    ...d,
                    acceptance_multiplier: e.target.value,
                  }))
                }
              />
            </Field>
            <Field label="velocity_days (окно расчёта days_to_stockout)">
              <input
                type="number"
                className="input"
                step="1"
                min="1"
                value={draft.velocity_days}
                onChange={(e: any) =>
                  setDraft((d) => ({ ...d, velocity_days: e.target.value }))
                }
              />
            </Field>
            <Field label="buyout_fallback, % (если в Воронке = 0)">
              <input
                type="number"
                className="input"
                step="0.01"
                min="0"
                max="100"
                value={draft.buyout_fallback_pct}
                onChange={(e: any) =>
                  setDraft((d) => ({
                    ...d,
                    buyout_fallback_pct: e.target.value,
                  }))
                }
              />
            </Field>
            <Field label="storage_days (горизонт хранения для расчёта)">
              <input
                type="number"
                className="input"
                step="1"
                min="1"
                value={draft.storage_days}
                onChange={(e: any) =>
                  setDraft((d) => ({ ...d, storage_days: e.target.value }))
                }
              />
            </Field>
            <Field label="Обратная логистика (AG в Excel)">
              <select
                className="input"
                value={draft.reverse_logistics_mode}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    reverse_logistics_mode: e.target.value as
                      | "tariff"
                      | "flat_50",
                  }))
                }
              >
                <option value="tariff">tariff — AG из WB-тарифа (правильно)</option>
                <option value="flat_50">flat_50 — фикс 50 ₽ (как в Excel-эталоне)</option>
              </select>
            </Field>
          </div>

          {/* Validation errors */}
          {errors.length > 0 && (
            <div className="mt-4 rounded-md bg-danger/10 border border-danger/30 px-3 py-2 text-sm text-danger">
              <div className="font-medium mb-1">Ошибки валидации:</div>
              <ul className="list-disc list-inside text-xs">
                {errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
          {okMsg && (
            <div className="mt-4 rounded-md bg-success/10 border border-success/30 px-3 py-2 text-sm text-success">
              {okMsg}
            </div>
          )}

          {/* Save bar */}
          <div className="mt-5 flex flex-wrap items-end gap-3">
            <Field label="Действует с (effective_date)">
              <input
                type="date"
                className="input"
                value={newEffDate}
                onChange={(e: any) => setNewEffDate(e.target.value)}
              />
            </Field>
            <button
              type="button"
              className="btn"
              onClick={onReset}
              disabled={saveMut.isPending}
            >
              Сбросить
            </button>
            <button
              type="button"
              className="btn border-accent text-accent"
              onClick={onSave}
              disabled={saveMut.isPending}
            >
              {saveMut.isPending
                ? "Сохраняю…"
                : "Сохранить как новую версию →"}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

/**
 * История версий UNIT-plan global_config.
 *
 * Загружает `/api/unit-plan/global-config/versions`, рендерит таблицу с
 * датой эфф., автором и ключевыми параметрами (СПП, НДС, налог, marketing).
 * Каждая строка clickable — expand с полным шейпом (все 16 полей).
 * Latest по effective_date — подсвечена «(текущая)».
 */
function UnitPlanGlobalConfigHistory({ currentId }: { currentId?: number }) {
  const versionsQ = useQuery({
    queryKey: ["unit-plan-global-config-versions"],
    queryFn: () => api.unitPlanGlobalConfigVersions(),
  });
  const [expandedId, setExpandedId] = useState<number | null>(null);

  if (versionsQ.isLoading) {
    return (
      <div className="rounded-md border border-border bg-bg p-3 mb-4 text-xs text-muted">
        Загрузка истории…
      </div>
    );
  }
  if (versionsQ.isError) {
    return (
      <div className="rounded-md border border-border bg-bg p-3 mb-4 text-xs text-danger">
        Не удалось загрузить историю:{" "}
        {(versionsQ.error as Error)?.message}
      </div>
    );
  }
  const items = versionsQ.data?.items ?? [];
  if (items.length === 0) {
    return (
      <div className="rounded-md border border-border bg-bg p-3 mb-4 text-xs text-muted">
        Версий ещё нет — текущая (latest) ещё не сохранена. Сохраните
        форму ниже как первую версию.
      </div>
    );
  }

  // Latest = первая (DESC backend-сортировка); подсвечиваем явно по id если есть.
  const latestId = items[0].id;

  // local helper equivalent to fmtPct from @/lib/format with 2-digit precision
  const fmtPct = (n: number | null | undefined) =>
    n == null ? "—" : `${Number(n).toFixed(2)}%`;
  const fmtNum = (n: number | null | undefined, suffix = "") =>
    n == null ? "—" : `${n}${suffix}`;
  const fmtVat = (mode: string | undefined, pct: number | undefined) => {
    if (!mode) return "—";
    if (mode === "none") return "none 0%";
    return `${mode} ${pct ?? 0}%`;
  };

  return (
    <div className="rounded-md border border-border bg-bg mb-4 overflow-x-auto">
      <table className="text-xs w-full">
        <thead>
          <tr className="border-b border-border text-muted">
            <th className="text-left p-2 font-medium">Дата эфф.</th>
            <th className="text-left p-2 font-medium">id</th>
            <th className="text-right p-2 font-medium">WB Клуб</th>
            <th className="text-right p-2 font-medium">СПП</th>
            <th className="text-right p-2 font-medium">НДС</th>
            <th className="text-right p-2 font-medium">Налог</th>
            <th className="text-right p-2 font-medium">Реклама</th>
            <th className="text-right p-2 font-medium">Velocity</th>
            <th className="p-2"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((v) => {
            const isLatest = v.id === latestId || v.id === currentId;
            const isExpanded = expandedId === v.id;
            return (
              <React.Fragment key={v.id ?? v.effective_date}>
                <tr
                  className={`border-b border-border cursor-pointer hover:bg-card ${
                    isLatest ? "bg-card/50" : ""
                  }`}
                  onClick={() =>
                    setExpandedId(isExpanded ? null : v.id ?? null)
                  }
                >
                  <td className="p-2">
                    {v.effective_date}
                    {isLatest && (
                      <span className="ml-2 text-success font-medium">
                        (текущая)
                      </span>
                    )}
                  </td>
                  <td className="p-2 text-muted">{v.id ?? "—"}</td>
                  <td className="p-2 text-right font-mono">{fmtPct(v.wb_club_pct)}</td>
                  <td className="p-2 text-right font-mono">
                    {fmtPct(v.spp_default_pct)}
                  </td>
                  <td className="p-2 text-right">
                    {fmtVat(v.vat_mode, v.vat_pct)}
                  </td>
                  <td className="p-2 text-right font-mono">{fmtPct(v.tax_pct)}</td>
                  <td className="p-2 text-right font-mono">
                    {fmtPct(v.marketing_pct)}
                  </td>
                  <td className="p-2 text-right font-mono">
                    {fmtNum(v.velocity_days, "д")}
                  </td>
                  <td className="p-2 text-muted">{isExpanded ? "▾" : "▸"}</td>
                </tr>
                {isExpanded && (
                  <tr className="border-b border-border bg-bg/60">
                    <td colSpan={9} className="p-3">
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
                        <KV k="effective_date" v={v.effective_date} />
                        <KV k="wb_club_pct" v={fmtPct(v.wb_club_pct)} />
                        <KV
                          k="spp_default_pct"
                          v={fmtPct(v.spp_default_pct)}
                        />
                        <KV k="wb_wallet_pct" v={fmtPct(v.wb_wallet_pct)} />
                        <KV k="acquiring_pct" v={fmtPct(v.acquiring_pct)} />
                        <KV k="il_coef" v={fmtNum(v.il_coef)} />
                        <KV k="irp_coef" v={fmtNum(v.irp_coef)} />
                        <KV k="marketing_pct" v={fmtPct(v.marketing_pct)} />
                        <KV k="tax_pct" v={fmtPct(v.tax_pct)} />
                        <KV
                          k="vat"
                          v={fmtVat(v.vat_mode, v.vat_pct)}
                        />
                        <KV
                          k="acceptance_rub_per_liter"
                          v={fmtNum(v.acceptance_rub_per_liter, " ₽/л")}
                        />
                        <KV
                          k="acceptance_multiplier"
                          v={fmtNum(v.acceptance_multiplier, "×")}
                        />
                        <KV
                          k="velocity_days"
                          v={fmtNum(v.velocity_days, " д")}
                        />
                        <KV
                          k="buyout_fallback_pct"
                          v={fmtPct(v.buyout_fallback_pct)}
                        />
                        <KV
                          k="storage_days"
                          v={fmtNum(v.storage_days, " д")}
                        />
                        {(v as any).spp_by_subject &&
                          Object.keys((v as any).spp_by_subject).length >
                            0 && (
                            <div className="col-span-full">
                              <div className="text-muted mb-1">
                                spp_by_subject:
                              </div>
                              <div className="pl-2 grid grid-cols-2 md:grid-cols-3 gap-1">
                                {Object.entries(
                                  (v as any).spp_by_subject as Record<
                                    string,
                                    number
                                  >,
                                ).map(([subj, pct]) => (
                                  <div key={subj}>
                                    <span className="text-muted">{subj}:</span>{" "}
                                    {pct}%
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        {(v as any).created_at && (
                          <KV
                            k="created_at"
                            v={String((v as any).created_at)}
                          />
                        )}
                        {(v as any).created_by != null && (
                          <KV
                            k="created_by"
                            v={String((v as any).created_by)}
                          />
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-2 border border-border rounded px-2 py-1">
      <span className="text-muted">{k}</span>
      <span>{v}</span>
    </div>
  );
}

function ExcelSection() {
  const entitiesQ = useQuery({
    queryKey: ["excel-entities"],
    queryFn: () => api.listExcelEntities(),
  });
  const qc = useQueryClient();
  const [results, setResults] = useState<Record<string, ImportResult | { error: string }>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const onImport = async (entity: string, file: File) => {
    setBusy(entity);
    try {
      const res = await api.excelImport(entity, file);
      setResults((r) => ({ ...r, [entity]: res }));
      // invalidate the queries that may render affected entities
      qc.invalidateQueries();
    } catch (e: any) {
      setResults((r) => ({ ...r, [entity]: { error: e.message || String(e) } }));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="card">
      <h2 className="font-medium mb-1">Excel: импорт / экспорт</h2>
      <div className="text-xs text-muted mb-3">
        Экспорт скачивает все строки таблицы в .xlsx. Импорт делает upsert по
        естественному ключу (id / nm_id / name / period+scope в зависимости от
        сущности). Лишние колонки в файле игнорируются, плохие строки
        пропускаются с указанием номера.
      </div>

      <table className="w-full text-sm">
        <thead className="text-muted text-xs uppercase">
          <tr>
            <th className="text-left p-2">Справочник</th>
            <th className="text-left p-2">Колонки</th>
            <th className="text-right p-2">Действия</th>
          </tr>
        </thead>
        <tbody>
          {entitiesQ.data?.items?.map((it) => {
            const res = results[it.name];
            const isImport = (r: any): r is ImportResult =>
              r && typeof r.inserted === "number";
            return (
              <tr key={it.name} className="border-t border-border align-top">
                <td className="p-2">
                  <div className="font-medium">{it.label}</div>
                  <div className="font-mono text-xs text-muted">{it.name}</div>
                </td>
                <td className="p-2 text-xs text-muted">
                  {it.columns.join(", ")}
                </td>
                <td className="p-2">
                  <div className="flex flex-col items-end gap-2">
                    <a
                      href={api.excelExportUrl(it.name)}
                      className="btn text-xs"
                      download
                    >
                      ⬇ Экспорт
                    </a>
                    <label className="btn text-xs cursor-pointer">
                      ⬆ Импорт
                      <input
                        type="file"
                        accept=".xlsx"
                        className="hidden"
                        disabled={busy === it.name}
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) onImport(it.name, f);
                          e.target.value = "";
                        }}
                      />
                    </label>
                    {busy === it.name && (
                      <span className="text-xs text-muted">импорт…</span>
                    )}
                    {res && isImport(res) && (
                      <div className="text-xs text-right">
                        <div>
                          <span className="text-success">+{res.inserted}</span>{" "}
                          <span className="text-muted">/</span>{" "}
                          <span className="text-warn">~{res.updated}</span>{" "}
                          <span className="text-muted">/</span>{" "}
                          <span className="text-danger">×{res.skipped}</span>
                        </div>
                        {res.errors.length > 0 && (
                          <details className="mt-1 text-left">
                            <summary className="cursor-pointer text-danger">
                              {res.errors.length} ошибок
                            </summary>
                            <ul className="mt-1 list-disc list-inside max-h-32 overflow-y-auto">
                              {res.errors.slice(0, 30).map((m, i) => (
                                <li key={i}>{m}</li>
                              ))}
                              {res.errors.length > 30 && (
                                <li className="text-muted">…</li>
                              )}
                            </ul>
                          </details>
                        )}
                      </div>
                    )}
                    {res && !isImport(res) && (
                      <div className="text-xs text-danger text-right">
                        {(res as { error: string }).error}
                      </div>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}


// ─────────────────────────────────────────────────────────────────────────
// WB Tariffs — read-only view + Sync now (UNIT-PLAN-006)
// ─────────────────────────────────────────────────────────────────────────

type TariffKind = "box" | "pallet" | "commission";

function WbTariffsSection() {
  const qc = useQueryClient();
  const [kind, setKind] = useState<TariffKind>("box");
  const [search, setSearch] = useState("");
  const [onDate, setOnDate] = useState<string>(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["wb-tariffs-list", kind, onDate, search],
    queryFn: () =>
      api.tariffList(kind, {
        date: onDate || undefined,
        search: search.trim() || undefined,
        limit: 2000,
      }),
    // Кэшируем 5 минут — тарифы меняются max раз в неделю.
    staleTime: 5 * 60_000,
  });

  const syncMut = useMutation({
    mutationFn: () => api.tariffSyncNow(),
    onSuccess: (r) => {
      setSyncMsg(`✓ Запущено (task ${r.task_id.slice(0, 8)}…). Прогресс в sidebar.`);
      setTimeout(() => setSyncMsg(null), 8000);
      // Перезагрузим список через 5 сек — обычно sync проходит за ~5 сек.
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["wb-tariffs-list"] });
      }, 5000);
    },
    onError: (e: any) => setSyncMsg(`✗ Ошибка: ${e.message ?? "unknown"}`),
  });

  const items: any[] = q.data?.items ?? [];

  return (
    <section className="card">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
        <div>
          <h2 className="font-medium">WB Tariffs</h2>
          <div className="text-xs text-muted">
            Тарифы коробов, монопаллетов и комиссий из WB Tariffs API. Sync
            ежедневно 08:00 MSK. SCD2 — показывается действующий на выбранную
            дату.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            className="btn"
            onClick={() => syncMut.mutate()}
            disabled={syncMut.isPending}
            title="Только director. Запускает sync.tariffs (Celery)."
          >
            {syncMut.isPending ? "..." : "↻ Sync now"}
          </button>
        </div>
      </div>

      {syncMsg && (
        <div
          className={`text-xs mb-3 ${
            syncMsg.startsWith("✓") ? "text-success" : "text-danger"
          }`}
        >
          {syncMsg}
        </div>
      )}

      <div className="flex flex-wrap gap-2 mb-3">
        {(["box", "pallet", "commission"] as TariffKind[]).map((k) => (
          <button
            key={k}
            className={`btn ${kind === k ? "btn-primary" : ""}`}
            onClick={() => setKind(k)}
          >
            {k === "box"
              ? "Короб"
              : k === "pallet"
              ? "Монопаллет"
              : "Комиссии"}
          </button>
        ))}
        <input
          type="date"
          className="input"
          value={onDate}
          onChange={(e) => setOnDate(e.target.value)}
          style={{ maxWidth: 160 }}
          title="Действующие на дату"
        />
        <input
          type="text"
          className="input"
          placeholder={
            kind === "commission" ? "поиск по предмету..." : "поиск по складу..."
          }
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ minWidth: 240, flex: 1 }}
        />
      </div>

      {q.isLoading && <div className="text-muted text-sm">Загрузка...</div>}
      {q.error && (
        <div className="text-danger text-sm">
          {(q.error as Error).message}
        </div>
      )}

      {q.data && (
        <div className="text-xs text-muted mb-2">
          Показано {items.length} из {q.data.total}. As of {q.data.as_of}.
        </div>
      )}

      {items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              {kind === "commission" ? (
                <tr className="text-left text-muted border-b border-border">
                  <th className="py-1.5 pr-2">Предмет</th>
                  <th className="py-1.5 pr-2">subject_id</th>
                  <th className="py-1.5 pr-2 text-right">FBO %</th>
                  <th className="py-1.5 pr-2 text-right">FBS %</th>
                  <th className="py-1.5 pr-2 text-right">Express %</th>
                  <th className="py-1.5 pr-2 text-right">Paid storage %</th>
                  <th className="py-1.5 pr-2 text-right">Return ₽</th>
                  <th className="py-1.5 pr-2">eff. from</th>
                </tr>
              ) : (
                <tr className="text-left text-muted border-b border-border">
                  <th className="py-1.5 pr-2">Склад</th>
                  <th className="py-1.5 pr-2 text-right">delivery_base ₽</th>
                  <th className="py-1.5 pr-2 text-right">delivery_liter ₽</th>
                  <th className="py-1.5 pr-2 text-right">delivery_expr</th>
                  <th className="py-1.5 pr-2 text-right">storage_base ₽</th>
                  <th className="py-1.5 pr-2 text-right">storage_liter ₽</th>
                  {kind === "pallet" && (
                    <th className="py-1.5 pr-2 text-right">storage_expr</th>
                  )}
                  <th className="py-1.5 pr-2">eff. from</th>
                </tr>
              )}
            </thead>
            <tbody>
              {items.map((r: any, i: number) =>
                kind === "commission" ? (
                  <tr key={i} className="border-b border-border/40 hover:bg-card-hover">
                    <td className="py-1 pr-2">{r.subject_name}</td>
                    <td className="py-1 pr-2 text-muted">
                      {r.subject_id ?? "—"}
                    </td>
                    <td className="py-1 pr-2 text-right">
                      {r.commission_fbo ?? "—"}
                    </td>
                    <td className="py-1 pr-2 text-right">
                      {r.commission_fbs ?? "—"}
                    </td>
                    <td className="py-1 pr-2 text-right">
                      {r.commission_express ?? "—"}
                    </td>
                    <td className="py-1 pr-2 text-right">
                      {r.paid_storage_kgvp ?? "—"}
                    </td>
                    <td className="py-1 pr-2 text-right">
                      {r.return_cost ?? "—"}
                    </td>
                    <td className="py-1 pr-2 text-muted">{r.effective_from}</td>
                  </tr>
                ) : (
                  <tr key={i} className="border-b border-border/40 hover:bg-card-hover">
                    <td className="py-1 pr-2">{r.warehouse_name}</td>
                    <td className="py-1 pr-2 text-right">
                      {r.delivery_base ?? "—"}
                    </td>
                    <td className="py-1 pr-2 text-right">
                      {r.delivery_liter ?? "—"}
                    </td>
                    <td className="py-1 pr-2 text-right">
                      {r.delivery_expr ?? "—"}
                    </td>
                    <td className="py-1 pr-2 text-right">
                      {r.storage_base ?? "—"}
                    </td>
                    <td className="py-1 pr-2 text-right">
                      {r.storage_liter ?? "—"}
                    </td>
                    {kind === "pallet" && (
                      <td className="py-1 pr-2 text-right">
                        {r.storage_expr ?? "—"}
                      </td>
                    )}
                    <td className="py-1 pr-2 text-muted">{r.effective_from}</td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}

      {!q.isLoading && items.length === 0 && (
        <div className="text-muted text-sm">
          Данные пустые. Проверьте что был хотя бы один sync.tariffs (кнопка «↻
          Sync now») и что у текущего tenant'а есть валидный WB-токен.
        </div>
      )}
    </section>
  );
}

function ExtensionTokensSection() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["extension-api-tokens"],
    queryFn: () => api.extensionApiTokenList(),
  });
  const [label, setLabel] = useState("");
  const [expiresInDays, setExpiresInDays] = useState<string>("");
  const [justCreated, setJustCreated] = useState<{
    token: string;
    label: string;
  } | null>(null);

  const createMut = useMutation({
    mutationFn: () =>
      api.extensionApiTokenCreate(
        label.trim() || "Chrome extension",
        expiresInDays.trim() ? parseInt(expiresInDays, 10) : null,
      ),
    onSuccess: (data) => {
      setJustCreated({ token: data.token, label: data.label });
      setLabel("");
      setExpiresInDays("");
      qc.invalidateQueries({ queryKey: ["extension-api-tokens"] });
    },
  });

  const revokeMut = useMutation({
    mutationFn: (id: number) => api.extensionApiTokenRevoke(id),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["extension-api-tokens"] }),
  });

  const items = q.data || [];

  return (
    <section className="card">
      <h2 className="font-medium mb-1">Токены для Chrome-расширения</h2>
      <p className="text-muted text-sm mb-3">
        JWT в cookie живёт 12 часов — расширение приходится переподключать
        ежедневно. Здесь генерируется отдельный long-lived токен формата
        <code className="mx-1">rnpext_…</code> с настраиваемым сроком жизни
        (или без срока). Вставь токен в options расширения вместо JWT из
        cookie.
      </p>

      <div className="flex flex-wrap gap-2 items-end mb-3">
        <div>
          <label className="block text-xs text-muted mb-1">
            Название (для себя)
          </label>
          <input
            className="input"
            placeholder="Chrome на ноутбуке"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">
            Срок жизни (дней, пусто = бессрочно)
          </label>
          <input
            type="number"
            className="input"
            placeholder="365"
            value={expiresInDays}
            onChange={(e) => setExpiresInDays(e.target.value)}
            min={1}
            max={3650}
          />
        </div>
        <button
          className="btn"
          onClick={() => createMut.mutate()}
          disabled={createMut.isPending}
        >
          {createMut.isPending ? "Создание…" : "+ Создать токен"}
        </button>
      </div>

      {justCreated && (
        <div className="card mb-3" style={{ borderColor: "var(--accent)" }}>
          <div className="text-sm font-medium mb-1">
            Токен «{justCreated.label}» создан. Скопируй его прямо сейчас — он
            больше не покажется:
          </div>
          <div className="flex items-center gap-2">
            <code className="flex-1 p-2 text-xs break-all bg-surface-2 rounded">
              {justCreated.token}
            </code>
            <button
              className="btn"
              onClick={() => {
                navigator.clipboard.writeText(justCreated.token);
              }}
            >
              Копировать
            </button>
            <button
              className="btn btn-ghost"
              onClick={() => setJustCreated(null)}
            >
              <Icon name="close" size={12} />
            </button>
          </div>
        </div>
      )}

      {q.isLoading && <div className="text-muted text-sm">Загрузка…</div>}

      {!q.isLoading && items.length === 0 && (
        <div className="text-muted text-sm">
          Токенов ещё нет. Создай первый кнопкой выше.
        </div>
      )}

      {items.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted">
              <th className="py-1">Префикс</th>
              <th className="py-1">Название</th>
              <th className="py-1">Создан</th>
              <th className="py-1">Использован</th>
              <th className="py-1">Истекает</th>
              <th className="py-1">Статус</th>
              <th className="py-1"></th>
            </tr>
          </thead>
          <tbody>
            {items.map((t) => {
              const isRevoked = t.revokedAt != null;
              const isExpired =
                t.expiresAt != null && new Date(t.expiresAt) < new Date();
              const status = isRevoked
                ? "отозван"
                : isExpired
                ? "истёк"
                : "активен";
              return (
                <tr
                  key={t.id}
                  className={
                    isRevoked || isExpired ? "text-muted" : undefined
                  }
                >
                  <td className="py-1 font-mono text-xs">{t.prefix}…</td>
                  <td className="py-1">{t.label || "—"}</td>
                  <td className="py-1 text-xs">
                    {new Date(t.createdAt).toLocaleString("ru")}
                  </td>
                  <td className="py-1 text-xs">
                    {t.lastUsedAt
                      ? new Date(t.lastUsedAt).toLocaleString("ru")
                      : "—"}
                  </td>
                  <td className="py-1 text-xs">
                    {t.expiresAt
                      ? new Date(t.expiresAt).toLocaleDateString("ru")
                      : "∞"}
                  </td>
                  <td className="py-1 text-xs">{status}</td>
                  <td className="py-1 text-right">
                    {!isRevoked && !isExpired && (
                      <button
                        className="btn btn-ghost"
                        onClick={() => {
                          if (
                            window.confirm(
                              `Отозвать токен «${t.label || t.prefix}»? Расширения с ним перестанут работать.`,
                            )
                          ) {
                            revokeMut.mutate(t.id);
                          }
                        }}
                      >
                        Отозвать
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

// TASK-DEV-014/017 follow-up — per-user TG-binding
function MyTgSubsection() {
  const qc = useQueryClient();
  const meTgQ = useQuery({
    queryKey: ["my-tg"],
    queryFn: () => api.myTgGet(),
  });
  const [chatInput, setChatInput] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [bindCode, setBindCode] = useState<{ code: string; expires_at: number } | null>(null);
  useEffect(() => {
    setChatInput(meTgQ.data?.chat_id ?? "");
  }, [meTgQ.data]);

  const saveMut = useMutation({
    mutationFn: (cid: string | null) => api.myTgPut(cid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["my-tg"] });
      setMsg("✓ Сохранено");
      setTimeout(() => setMsg(null), 4000);
    },
  });

  // TASK: multi-tenant bot — clean-bind через одноразовый 6-символьный код
  const codeMut = useMutation({
    mutationFn: () => api.myTgGenBindCode(),
    onSuccess: (d) => {
      const expires_at = Date.now() + d.expires_in_sec * 1000;
      setBindCode({ code: d.code, expires_at });
      setTimeout(() => setBindCode(null), d.expires_in_sec * 1000);
    },
  });

  return (
    <div className="mt-4 pt-3 border-t border-border/60">
      <div className="font-medium text-sm mb-2">
        Мой Telegram-чат (multi-recipient broadcast)
      </div>
      <div className="text-xs text-muted mb-2 leading-relaxed">
        <strong>Рекомендуемый способ — clean-bind через код:</strong> жмите
        «🔑 Сгенерировать код», скопируйте 6 символов, в боте SellerFriends пишите
        <code> /bind &lt;код&gt;</code>. Бот сам подвяжет ваш chat_id.<br/>
        <strong>Ручная привязка</strong> (legacy): узнайте chat_id написав
        <code> /start</code> боту, вставьте в поле ниже, сохраните.
      </div>

      {/* Bind-code generation */}
      <div className="mb-3 flex items-center gap-2">
        <button
          type="button"
          className="btn text-xs"
          onClick={() => codeMut.mutate()}
          disabled={codeMut.isPending}
        >
          {codeMut.isPending ? "Генерация…" : "Сгенерировать код привязки"}
        </button>
        {bindCode && (
          <span className="font-mono text-base bg-surface-2/60 px-2 py-1 rounded">
            {bindCode.code}
          </span>
        )}
        {bindCode && (
          <span className="text-xs text-muted">
            истекает через {Math.max(0, Math.round((bindCode.expires_at - Date.now()) / 1000))}с
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <input
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          placeholder="123456789 (chat_id из бота)"
          className="input text-sm w-72"
        />
        <button
          className="btn text-xs"
          onClick={() =>
            saveMut.mutate(chatInput.trim() ? chatInput.trim() : null)
          }
          disabled={saveMut.isPending}
        >
          {saveMut.isPending ? "Сохранение…" : "Сохранить"}
        </button>
        {meTgQ.data?.chat_id && (
          <button
            className="btn text-xs text-danger"
            onClick={() => saveMut.mutate(null)}
          >
            Отвязать
          </button>
        )}
        {msg && <span className="text-xs text-success">{msg}</span>}
      </div>
    </div>
  );
}
