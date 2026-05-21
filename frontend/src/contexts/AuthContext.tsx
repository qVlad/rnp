import { createContext, useContext, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  api,
  type AvailableTenant,
  type Me,
  setOn401Handler,
} from "@/api/client";

type AuthState = {
  user: Me | null;
  loading: boolean; // true while we resolve initial /me on mount
  needsBootstrap: boolean; // first-run flag
  refresh: () => Promise<void>;
  login: (username: string, password: string) => Promise<Me>;
  bootstrap: (
    username: string,
    password: string,
    full_name?: string,
  ) => Promise<Me>;
  logout: () => Promise<void>;
  // TASK-LEAD-039 Фаза C — multi-cabinet workspace
  availableTenants: AvailableTenant[];
  activeTenantId: number | null;
  switchTenant: (tenantId: number) => Promise<void>;
};

const Ctx = createContext<AuthState | null>(null);

const ACTIVE_TENANT_KEY = "activeTenantId.v1";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [needsBootstrap, setNeedsBootstrap] = useState(false);
  // TASK-LEAD-039 — multi-cabinet
  const [availableTenants, setAvailableTenants] = useState<AvailableTenant[]>([]);
  const [activeTenantId, setActiveTenantId] = useState<number | null>(() => {
    try {
      const v = localStorage.getItem(ACTIVE_TENANT_KEY);
      return v ? Number(v) : null;
    } catch {
      return null;
    }
  });
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const loadAvailableTenants = async () => {
    try {
      const list = await api.availableTenants();
      setAvailableTenants(list);
      // Если активного нет в local — взять первый из списка (back-end отдаёт
      // sorted DESC по last_active_at). Persist в localStorage.
      if (list.length > 0) {
        setActiveTenantId((cur) => {
          if (cur && list.some((t) => t.tenant_id === cur)) return cur;
          const next = list[0].tenant_id;
          try {
            localStorage.setItem(ACTIVE_TENANT_KEY, String(next));
          } catch {}
          return next;
        });
      }
    } catch {
      // 401 / no access — оставляем пустой список, dropdown скроется
      setAvailableTenants([]);
    }
  };

  const refresh = async () => {
    try {
      const me = await api.authMe();
      setUser(me);
      setNeedsBootstrap(false);
      await loadAvailableTenants();
    } catch {
      setUser(null);
      setAvailableTenants([]);
      try {
        const r = await api.authNeedsBootstrap();
        setNeedsBootstrap(r.needs_bootstrap);
      } catch {
        setNeedsBootstrap(false);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setOn401Handler(() => {
      setUser(null);
      setAvailableTenants([]);
      navigate("/login", { replace: true });
    });
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = async (username: string, password: string) => {
    const me = await api.authLogin(username, password);
    setUser(me);
    setNeedsBootstrap(false);
    await loadAvailableTenants();
    return me;
  };

  const bootstrap = async (
    username: string,
    password: string,
    full_name?: string,
  ) => {
    const me = await api.authBootstrap({ username, password, full_name });
    setUser(me);
    setNeedsBootstrap(false);
    await loadAvailableTenants();
    return me;
  };

  const logout = async () => {
    await api.authLogout().catch(() => {});
    setUser(null);
    setAvailableTenants([]);
    setActiveTenantId(null);
    try {
      localStorage.removeItem(ACTIVE_TENANT_KEY);
    } catch {}
    navigate("/login", { replace: true });
  };

  const switchTenant = async (tenantId: number) => {
    // Backend проверит access и установит cookie rnp_active_tenant.
    const resp = await api.switchTenant(tenantId);
    if (!resp.ok) {
      throw new Error("Не удалось переключить кабинет");
    }
    // Инвалидируем ВСЕ queries — все данные теперь от другого tenant'а.
    queryClient.removeQueries();
    // Обновим user (role может быть per-tenant) и список tenants (last_active_at update).
    try {
      const me = await api.authMe();
      setUser(me);
    } catch {
      // если что-то пошло не так — logout
      await logout();
      return;
    }
    await loadAvailableTenants();
    setActiveTenantId(tenantId);
    try {
      localStorage.setItem(ACTIVE_TENANT_KEY, String(tenantId));
    } catch {}
  };

  return (
    <Ctx.Provider
      value={{
        user,
        loading,
        needsBootstrap,
        refresh,
        login,
        bootstrap,
        logout,
        availableTenants,
        activeTenantId,
        switchTenant,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used within AuthProvider");
  return v;
}
