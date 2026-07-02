/**
 * CabinetsSection (DEV-092) — Настройки → «Кабинеты WB».
 *
 * Мульти-кабинет по образцу TrueStats: таблица подключённых кабинетов +
 * модалка «Добавить кабинет» (название + WB API-токен). Действия: переключиться /
 * переименовать / заменить токен / отключить токен / скрыть (архив) / доступы.
 * Удаления кабинета НЕТ: «отключение + скрытие», данные остаются в БД.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type TenantCabinet } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";

function fmtDt(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("ru");
  } catch {
    return iso;
  }
}

const ROLE_LABELS: Record<string, string> = {
  director: "директор",
  head_of_sales: "РОП",
  manager: "менеджер",
  bookkeeper: "бухгалтер",
};

export default function CabinetsSection() {
  const { user, activeTenantId, switchTenant, refresh } = useAuth();
  const qc = useQueryClient();

  const tenantsQ = useQuery({
    queryKey: ["tenants-list"],
    queryFn: () => api.listTenants(),
    enabled: user?.role === "director",
  });

  const [addOpen, setAddOpen] = useState(false);
  const [accessFor, setAccessFor] = useState<TenantCabinet | null>(null);
  const [replaceFor, setReplaceFor] = useState<TenantCabinet | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const invalidate = async () => {
    qc.invalidateQueries({ queryKey: ["tenants-list"] });
    qc.invalidateQueries({ queryKey: ["available-tenants"] });
    await refresh(); // AuthContext.availableTenants → dropdown «Кабинет» в сайдбаре
  };

  const patchMut = useMutation({
    mutationFn: (p: { id: number; name?: string; hidden?: boolean }) =>
      api.patchTenant(p.id, { name: p.name, hidden: p.hidden }),
    onSuccess: () => invalidate(),
    onError: (e: any) => setMsg(`Ошибка: ${e.message}`),
  });
  const clearTokenMut = useMutation({
    mutationFn: (id: number) => api.clearTenantToken(id),
    onSuccess: () => invalidate(),
    onError: (e: any) => setMsg(`Ошибка: ${e.message}`),
  });

  if (user?.role !== "director") return null;

  const items = tenantsQ.data?.items ?? [];
  const visible = items.filter((t) => !t.hidden);
  const hidden = items.filter((t) => t.hidden);

  return (
    <section className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-medium">Кабинеты WB</h2>
        <button className="btn" onClick={() => { setMsg(null); setAddOpen(true); }}>
          + Добавить кабинет
        </button>
      </div>
      <div className="text-sm text-muted mb-3">
        Один аккаунт сервиса — несколько кабинетов WB. Аналитика по умолчанию
        показывает <b>свод по всем кабинетам</b> (фильтр «Магазины» сужает).
        Настройки, налоги и ручные записи ведутся в <b>активном кабинете</b>{" "}
        (переключатель в сайдбаре).
      </div>

      {msg && <div className="text-sm mb-2 text-warning">{msg}</div>}

      {tenantsQ.isLoading ? (
        <div className="text-sm text-muted">Загрузка…</div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted">
              <th className="py-1 pr-2">Кабинет</th>
              <th className="py-1 pr-2">Токен</th>
              <th className="py-1 pr-2">Роль</th>
              <th className="py-1 pr-2 text-right">Действия</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((t) => (
              <tr key={t.tenant_id} className="border-t border-border">
                <td className="py-2 pr-2">
                  <span className="font-medium">{t.name}</span>{" "}
                  {t.tenant_id === activeTenantId && (
                    <span className="text-[11px] px-1.5 py-0.5 rounded-full bg-accent/10 text-accent">
                      активный
                    </span>
                  )}
                  {t.seller_id && (
                    <div className="text-[11px] text-muted">
                      seller: {t.seller_id.slice(0, 10)}…
                    </div>
                  )}
                </td>
                <td className="py-2 pr-2">
                  {t.token_set ? (
                    <span className="text-success">
                      ✓ установлен
                      {t.validated_at && (
                        <span className="text-muted"> · {fmtDt(t.validated_at)}</span>
                      )}
                    </span>
                  ) : (
                    <span className="text-muted">✗ не настроен</span>
                  )}
                </td>
                <td className="py-2 pr-2">{ROLE_LABELS[t.role] ?? t.role}</td>
                <td className="py-2 pr-0 text-right whitespace-nowrap">
                  {t.tenant_id !== activeTenantId && (
                    <button
                      className="text-xs text-accent hover:underline mr-2"
                      onClick={() => switchTenant(t.tenant_id).catch(console.error)}
                    >
                      Переключиться
                    </button>
                  )}
                  <button
                    className="text-xs text-muted hover:text-fg mr-2"
                    onClick={() => {
                      const name = prompt("Новое название кабинета:", t.name);
                      if (name && name.trim() && name.trim() !== t.name)
                        patchMut.mutate({ id: t.tenant_id, name: name.trim() });
                    }}
                  >
                    Переименовать
                  </button>
                  <button
                    className="text-xs text-muted hover:text-fg mr-2"
                    onClick={() => { setMsg(null); setReplaceFor(t); }}
                  >
                    Заменить токен
                  </button>
                  {t.token_set && (
                    <button
                      className="text-xs text-muted hover:text-fg mr-2"
                      onClick={() => {
                        if (
                          confirm(
                            `Отключить токен «${t.name}»? Sync остановится, данные кабинета сохраняются.`,
                          )
                        )
                          clearTokenMut.mutate(t.tenant_id);
                      }}
                    >
                      Отключить токен
                    </button>
                  )}
                  <button
                    className="text-xs text-muted hover:text-fg mr-2"
                    onClick={() => setAccessFor(t)}
                  >
                    Доступы
                  </button>
                  <button
                    className="text-xs text-muted hover:text-fg"
                    onClick={() => {
                      if (
                        confirm(
                          `Скрыть кабинет «${t.name}»? Он исчезнет из списков и свода, sync остановится. Данные сохраняются, кабинет можно вернуть.`,
                        )
                      )
                        patchMut.mutate({ id: t.tenant_id, hidden: true });
                    }}
                  >
                    Скрыть
                  </button>
                </td>
              </tr>
            ))}
            {visible.length === 0 && (
              <tr>
                <td colSpan={4} className="py-3 text-muted">
                  Нет кабинетов
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {hidden.length > 0 && (
        <div className="mt-4">
          <div className="text-sm text-muted mb-1">Скрытые кабинеты</div>
          {hidden.map((t) => (
            <div
              key={t.tenant_id}
              className="flex items-center justify-between text-sm py-1 border-t border-border"
            >
              <span className="text-muted">{t.name}</span>
              <button
                className="text-xs text-accent hover:underline"
                onClick={() => patchMut.mutate({ id: t.tenant_id, hidden: false })}
              >
                Вернуть
              </button>
            </div>
          ))}
        </div>
      )}

      {addOpen && (
        <AddCabinetModal
          onClose={() => setAddOpen(false)}
          onCreated={async (r) => {
            setAddOpen(false);
            await invalidate();
            setMsg(
              `✓ Кабинет «${r.name}» подключён. Запущен первичный sync за 90 дней` +
                (r.auto_sync_triggered.length
                  ? ` (${r.auto_sync_triggered.join(", ")})`
                  : "") +
                ". Не забудьте настроить налоги: переключитесь на кабинет и откройте /settings.",
            );
            if (
              confirm(
                `Кабинет «${r.name}» подключён. Переключиться на него сейчас, чтобы настроить налоги?`,
              )
            ) {
              await switchTenant(r.tenant_id).catch(console.error);
            }
          }}
        />
      )}

      {replaceFor && (
        <ReplaceTokenModal
          cabinet={replaceFor}
          onClose={() => setReplaceFor(null)}
          onDone={async () => {
            setReplaceFor(null);
            await invalidate();
          }}
        />
      )}

      {accessFor && (
        <AccessModal cabinet={accessFor} onClose={() => setAccessFor(null)} />
      )}
    </section>
  );
}

// ── Модалка «Добавить кабинет» ──────────────────────────────────────────────

function AddCabinetModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (r: {
    tenant_id: number;
    name: string;
    auto_sync_triggered: string[];
  }) => void;
}) {
  const [name, setName] = useState("");
  const [token, setToken] = useState("");
  const [test, setTest] = useState<{
    valid: boolean;
    error: string | null;
    seller_id: string | null;
  } | null>(null);
  const [dupWarn, setDupWarn] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const testMut = useMutation({
    mutationFn: (t: string) => api.testTenantWbToken(t),
    onSuccess: (d) => setTest(d),
    onError: (e: any) => setErr(`Ошибка проверки: ${e.message}`),
  });

  const createMut = useMutation({
    mutationFn: (p: { force?: boolean }) =>
      api.createTenant({ name: name.trim(), token: token.trim(), force: p.force }),
    onSuccess: (r) => onCreated(r),
    onError: (e: any) => {
      const m = String(e.message || "");
      if (m.includes("duplicate_seller")) {
        setDupWarn(
          "Кабинет этого продавца уже подключён. Подключить ещё раз (будет дубль данных)?",
        );
      } else {
        setErr(m);
      }
    },
  });

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="card w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-medium">Добавление кабинета WB</h3>
          <button className="text-muted hover:text-fg" onClick={onClose}>✕</button>
        </div>

        <label className="block text-sm mb-1">Название кабинета</label>
        <input
          className="input w-full mb-3"
          placeholder="Например: ООО Ромашка"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />

        <label className="block text-sm mb-1">WB API-токен</label>
        <textarea
          className="input w-full h-24 mb-2 font-mono text-xs"
          placeholder="Токен из ЛК WB: Настройки → Доступ к API"
          value={token}
          onChange={(e) => {
            setToken(e.target.value);
            setTest(null);
            setDupWarn(null);
          }}
        />

        {test && (
          <div className={`text-sm mb-2 ${test.valid ? "text-success" : "text-danger"}`}>
            {test.valid
              ? `✓ Токен валиден${test.seller_id ? ` (seller: ${test.seller_id.slice(0, 10)}…)` : ""}`
              : `✗ ${test.error}`}
          </div>
        )}
        {dupWarn && <div className="text-sm mb-2 text-warning">⚠ {dupWarn}</div>}
        {err && <div className="text-sm mb-2 text-danger">{err}</div>}

        <div className="flex gap-2">
          <button
            className="btn"
            disabled={token.trim().length < 100 || testMut.isPending}
            onClick={() => { setErr(null); testMut.mutate(token.trim()); }}
          >
            {testMut.isPending ? "Проверяю…" : "Проверить"}
          </button>
          {dupWarn ? (
            <button
              className="btn btn-primary"
              disabled={createMut.isPending}
              onClick={() => createMut.mutate({ force: true })}
            >
              {createMut.isPending ? "Подключаю…" : "Всё равно подключить"}
            </button>
          ) : (
            <button
              className="btn btn-primary"
              disabled={
                !name.trim() ||
                token.trim().length < 100 ||
                createMut.isPending ||
                (test !== null && !test.valid)
              }
              onClick={() => { setErr(null); createMut.mutate({}); }}
            >
              {createMut.isPending ? "Подключаю…" : "Подключить"}
            </button>
          )}
          <button className="btn" onClick={onClose}>Отмена</button>
        </div>
        <div className="text-[11px] text-muted mt-2">
          Токен проверяется через WB /ping до создания кабинета и хранится в БД
          в зашифрованном виде. После подключения автоматически запустится
          загрузка данных за 90 дней (~5 минут). Подключайте кабинеты по одному.
        </div>
      </div>
    </div>
  );
}

// ── Модалка «Заменить токен» ────────────────────────────────────────────────

function ReplaceTokenModal({
  cabinet,
  onClose,
  onDone,
}: {
  cabinet: TenantCabinet;
  onClose: () => void;
  onDone: () => void;
}) {
  const [token, setToken] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const mut = useMutation({
    mutationFn: (t: string) => api.setTenantToken(cabinet.tenant_id, t),
    onSuccess: () => onDone(),
    onError: (e: any) => setErr(String(e.message || "")),
  });
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="card w-full max-w-lg">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-medium">Токен кабинета «{cabinet.name}»</h3>
          <button className="text-muted hover:text-fg" onClick={onClose}>✕</button>
        </div>
        <textarea
          className="input w-full h-24 mb-2 font-mono text-xs"
          placeholder="Новый WB API-токен"
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        {err && <div className="text-sm mb-2 text-danger">{err}</div>}
        <div className="flex gap-2">
          <button
            className="btn btn-primary"
            disabled={token.trim().length < 100 || mut.isPending}
            onClick={() => { setErr(null); mut.mutate(token.trim()); }}
          >
            {mut.isPending ? "Сохраняю…" : "Сохранить"}
          </button>
          <button className="btn" onClick={onClose}>Отмена</button>
        </div>
      </div>
    </div>
  );
}

// ── Модалка «Доступы» ───────────────────────────────────────────────────────

function AccessModal({
  cabinet,
  onClose,
}: {
  cabinet: TenantCabinet;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const accessQ = useQuery({
    queryKey: ["tenant-access", cabinet.tenant_id],
    queryFn: () => api.tenantAccessList(cabinet.tenant_id),
  });
  const usersQ = useQuery({ queryKey: ["users"], queryFn: () => api.listUsers() });
  const [err, setErr] = useState<string | null>(null);
  const [addUserId, setAddUserId] = useState<number | "">("");
  const [addRole, setAddRole] = useState("manager");

  const grantMut = useMutation({
    mutationFn: (p: { user_id: number; role: string }) =>
      api.grantTenantAccess(cabinet.tenant_id, p),
    onSuccess: () => {
      setErr(null);
      qc.invalidateQueries({ queryKey: ["tenant-access", cabinet.tenant_id] });
    },
    onError: (e: any) => setErr(String(e.message || "")),
  });
  const revokeMut = useMutation({
    mutationFn: (userId: number) =>
      api.revokeTenantAccess(cabinet.tenant_id, userId),
    onSuccess: () => {
      setErr(null);
      qc.invalidateQueries({ queryKey: ["tenant-access", cabinet.tenant_id] });
    },
    onError: (e: any) => setErr(String(e.message || "")),
  });

  const accessItems = accessQ.data?.items ?? [];
  const accessIds = new Set(accessItems.map((a) => a.user_id));
  const candidates = (usersQ.data?.items ?? []).filter((u) => !accessIds.has(u.id));

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="card w-full max-w-lg">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-medium">Доступы — «{cabinet.name}»</h3>
          <button className="text-muted hover:text-fg" onClick={onClose}>✕</button>
        </div>

        {err && <div className="text-sm mb-2 text-danger">{err}</div>}

        {accessItems.map((a) => (
          <div
            key={a.user_id}
            className="flex items-center justify-between text-sm py-1 border-t border-border"
          >
            <span>
              {a.full_name || a.username}{" "}
              <span className="text-muted">({a.username})</span>
            </span>
            <span className="flex items-center gap-2">
              <select
                className="input text-xs py-0.5"
                value={a.role}
                onChange={(e) =>
                  grantMut.mutate({ user_id: a.user_id, role: e.target.value })
                }
              >
                {Object.entries(ROLE_LABELS).map(([r, label]) => (
                  <option key={r} value={r}>{label}</option>
                ))}
              </select>
              <button
                className="text-xs text-danger hover:underline"
                onClick={() => {
                  if (confirm(`Отозвать доступ у ${a.username}?`))
                    revokeMut.mutate(a.user_id);
                }}
              >
                Отозвать
              </button>
            </span>
          </div>
        ))}

        {candidates.length > 0 && (
          <div className="flex items-center gap-2 mt-3 pt-2 border-t border-border">
            <select
              className="input text-xs flex-1"
              value={addUserId}
              onChange={(e) =>
                setAddUserId(e.target.value ? Number(e.target.value) : "")
              }
            >
              <option value="">+ выдать доступ…</option>
              {candidates.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name || u.username}
                </option>
              ))}
            </select>
            <select
              className="input text-xs"
              value={addRole}
              onChange={(e) => setAddRole(e.target.value)}
            >
              {Object.entries(ROLE_LABELS).map(([r, label]) => (
                <option key={r} value={r}>{label}</option>
              ))}
            </select>
            <button
              className="btn text-xs"
              disabled={addUserId === "" || grantMut.isPending}
              onClick={() => {
                if (addUserId !== "")
                  grantMut.mutate({ user_id: addUserId, role: addRole });
              }}
            >
              Выдать
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
