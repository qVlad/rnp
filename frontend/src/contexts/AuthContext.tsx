import { createContext, useContext, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Me, setOn401Handler } from "@/api/client";

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
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [needsBootstrap, setNeedsBootstrap] = useState(false);
  const navigate = useNavigate();

  const refresh = async () => {
    try {
      const me = await api.authMe();
      setUser(me);
      setNeedsBootstrap(false);
    } catch {
      setUser(null);
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
    // Wire the 401 handler so any API call from any page that fails with
    // 401 redirects through the auth flow rather than each query crashing.
    setOn401Handler(() => {
      setUser(null);
      navigate("/login", { replace: true });
    });
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = async (username: string, password: string) => {
    const me = await api.authLogin(username, password);
    setUser(me);
    setNeedsBootstrap(false);
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
    return me;
  };

  const logout = async () => {
    await api.authLogout().catch(() => {});
    setUser(null);
    navigate("/login", { replace: true });
  };

  return (
    <Ctx.Provider
      value={{ user, loading, needsBootstrap, refresh, login, bootstrap, logout }}
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
