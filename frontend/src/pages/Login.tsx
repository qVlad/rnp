import { useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import VersionBadge from "@/components/VersionBadge";

export default function Login() {
  const { login, bootstrap, needsBootstrap } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const redirectTo =
    (location.state as { from?: string } | null)?.from || "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: any) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (needsBootstrap) {
        if (password.length < 8) {
          throw new Error("пароль должен быть не короче 8 символов");
        }
        await bootstrap(username, password, fullName || undefined);
      } else {
        await login(username, password);
      }
      navigate(redirectTo, { replace: true });
    } catch (err: any) {
      setError(parseError(err.message || String(err)));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg">
      <VersionBadge floating />
      <form
        onSubmit={submit}
        className="card w-full max-w-md flex flex-col gap-4"
      >
        <div className="font-bold text-xl mb-2">
          <span className="text-accent">●</span> SellerFriends ·{" "}
          {needsBootstrap ? "Первый запуск" : "Вход"}
        </div>

        {needsBootstrap && (
          <div className="text-xs text-warn bg-warn/10 border border-warn/30 rounded-md p-3">
            Это первый запуск системы. Создайте учётную запись администратора
            (роль <code>director</code>) — она получит полный доступ. Дальше
            можно будет добавить менеджеров через страницу «Пользователи».
          </div>
        )}

        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase tracking-wide">
            Логин
          </span>
          <input
            className="input"
            type="text"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e: any) => setUsername(e.target.value.toLowerCase())}
            required
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted uppercase tracking-wide">
            Пароль{needsBootstrap ? " (минимум 8 символов)" : ""}
          </span>
          <input
            className="input"
            type="password"
            autoComplete={needsBootstrap ? "new-password" : "current-password"}
            value={password}
            onChange={(e: any) => setPassword(e.target.value)}
            required
          />
        </label>

        {needsBootstrap && (
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted uppercase tracking-wide">
              Имя (для audit log)
            </span>
            <input
              className="input"
              type="text"
              placeholder="напр. Иван Петров"
              value={fullName}
              onChange={(e: any) => setFullName(e.target.value)}
            />
          </label>
        )}

        {error && <div className="text-danger text-sm">{error}</div>}

        <button
          type="submit"
          className="btn-primary"
          disabled={submitting || !username || !password}
        >
          {submitting
            ? "..."
            : needsBootstrap
              ? "Создать аккаунт администратора"
              : "Войти"}
        </button>

        {!needsBootstrap && (
          <div className="text-xs text-muted text-center mt-2">
            Нет аккаунта?{" "}
            <Link to="/signup" className="underline text-accent">
              Зарегистрировать компанию
            </Link>
          </div>
        )}
      </form>

      <style>{`
        .input { background: #13161d; border: 1px solid #262a35; border-radius: 6px; padding: 8px 10px; font-size: 14px; color: white; width: 100%; }
        .input:focus { outline: none; border-color: var(--accent, #4f46e5); }
      `}</style>
    </div>
  );
}

function parseError(msg: string): string {
  // FastAPI 401/400 errors come as `API 401: {"detail":"..."}`. Pull out the detail.
  const m = msg.match(/"detail":"([^"]+)"/);
  if (m) return m[1];
  return msg;
}
