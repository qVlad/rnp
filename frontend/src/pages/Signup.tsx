import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api } from "@/api/client";
import VersionBadge from "@/components/VersionBadge";

/** Signup новой компании — создаёт tenant + первого director'а.
 *  После успеха — авто-логин (cookie ставится backend'ом). */
export default function Signup() {
  const navigate = useNavigate();
  const [companyName, setCompanyName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [acceptTerms, setAcceptTerms] = useState(false);

  const submit = async (e: any) => {
    e.preventDefault();
    setError(null);
    if (!acceptTerms) {
      setError("необходимо принять условия использования");
      return;
    }
    if (!companyName.trim()) {
      setError("укажите название компании");
      return;
    }
    if (username.length < 3) {
      setError("логин не короче 3 символов");
      return;
    }
    if (password.length < 8) {
      setError("пароль не короче 8 символов");
      return;
    }
    setSubmitting(true);
    try {
      await api.authSignup({
        company_name: companyName.trim(),
        username: username.trim().toLowerCase(),
        password,
        full_name: fullName.trim() || undefined,
      });
      // После signup сразу залогинены — идём в дашборд (он будет пустым
      // пока не введут WB-токен).
      navigate("/settings", { replace: true });
    } catch (err: any) {
      const msg = err.message || String(err);
      setError(msg.replace(/^\d+:\s*/, ""));
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
          <span className="text-accent">●</span> РНП · Регистрация компании
        </div>

        <p className="text-xs text-muted -mt-3">
          После регистрации укажете WB-токен в настройках — и сервис начнёт
          подтягивать аналитику по вашему кабинету.
        </p>

        <label className="flex flex-col gap-1 text-sm">
          Название компании
          <input
            value={companyName}
            onChange={(e: any) => setCompanyName(e.target.value)}
            placeholder="Например: ONYX"
            className="input"
            autoComplete="organization"
            required
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          Имя владельца (опционально)
          <input
            value={fullName}
            onChange={(e: any) => setFullName(e.target.value)}
            className="input"
            autoComplete="name"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          Логин (только латиница, без пробелов)
          <input
            value={username}
            onChange={(e: any) => setUsername(e.target.value)}
            className="input"
            autoComplete="username"
            required
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          Пароль (≥ 8 символов)
          <input
            type="password"
            value={password}
            onChange={(e: any) => setPassword(e.target.value)}
            className="input"
            autoComplete="new-password"
            required
          />
        </label>

        <label className="flex items-start gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={acceptTerms}
            onChange={(e: any) => setAcceptTerms(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            Я принимаю{" "}
            <Link to="/legal" target="_blank" className="underline text-accent">
              условия использования и политику приватности
            </Link>
            . Я понимаю, что мой WB-токен будет храниться в зашифрованном виде
            и использоваться только для чтения моей собственной аналитики.
          </span>
        </label>

        {error && (
          <div className="text-danger text-sm whitespace-pre-line">{error}</div>
        )}

        <button
          type="submit"
          disabled={submitting || !acceptTerms}
          className="btn border-accent text-accent"
        >
          {submitting ? "Создаём…" : "Зарегистрировать"}
        </button>

        <div className="text-xs text-muted text-center mt-2">
          Уже есть аккаунт?{" "}
          <Link to="/login" className="underline text-accent">
            Войти
          </Link>
        </div>
      </form>
    </div>
  );
}
