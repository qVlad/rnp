import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";

export default function Settings() {
  const qc = useQueryClient();
  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: () => api.getSettings() as Promise<any> });
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
    mutationFn: (entity: string) => api.triggerSync(entity),
    onSuccess: (d, entity) => setSyncResult(`Запущена задача ${entity} → ${d.task_id}`),
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
  const setTokenMut = useMutation({
    mutationFn: (t: string) => api.setWbToken(t),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["wb-token-status"] });
      qc.invalidateQueries({ queryKey: ["whoami"] });
      setNewWbToken("");
      setTestResult(null);
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
      <h1 className="text-xl font-semibold">Настройки</h1>

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
              ✓ токен установлен{" "}
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
            <span className="text-warn">✗ не настроен</span>
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
                ✓ токен валиден
                {testResult.seller_id &&
                  ` · seller_id: ${testResult.seller_id}`}
              </span>
            ) : (
              <span className="text-danger">
                ✗ {testResult.error || "ошибка"}
              </span>
            )}
          </div>
        )}

        {setTokenMut.isError && (
          <div className="mt-2 text-danger text-sm">
            {(setTokenMut.error as any)?.message || "ошибка сохранения"}
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
            {whoQ.data?.wb_token_configured ? "✓ настроен" : "✗ не настроен"}
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
                {validateResult.ok ? "✓ Токен валиден" : "✗ Есть проблемы"}
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
                  <span className="text-emerald-400">
                    @{tgQ.data.bot_info.username} ({tgQ.data.bot_info.first_name})
                  </span>
                ) : (
                  <span className="text-yellow-400">токен задан, но бот не отвечает</span>
                )}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted">Привязанный чат</div>
              <div className="text-sm">
                {tgQ.data.chat_id ? (
                  <>
                    <span className="text-emerald-400">id {tgQ.data.chat_id}</span>{" "}
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
                  <span className="text-yellow-400">
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
                <span className="text-emerald-400 text-xs">✓ Отправлено</span>
              )}
              {tgTestMut.isError && (
                <span className="text-red-400 text-xs">
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

      <ExcelSection />

      <section className="card">
        <h2 className="font-medium mb-3">Синхронизация</h2>
        <div className="flex flex-wrap gap-2 mb-4">
          {[
            ["all", "Запустить всё"],
            ["orders", "Заказы"],
            ["sales", "Продажи"],
            ["stocks", "Остатки"],
            ["ad_campaigns", "Реклама: кампании"],
            ["ad_stats", "Реклама: стат-ка"],
            ["report_detail", "Отчёт реализации"],
          ].map(([key, label]) => (
            <button
              key={key}
              className="btn"
              onClick={() => syncMut.mutate(key)}
              disabled={syncMut.isPending}
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
                <td className="p-2">{s.last_synced_at?.replace("T", " ")?.slice(0, 19) ?? "—"}</td>
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
                      ✕
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
