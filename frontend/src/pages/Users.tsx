import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";
import { Icon } from "../components/Icon";

export default function Users() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const usersQ = useQuery({
    queryKey: ["users"],
    queryFn: () => api.listUsers(),
  });

  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("manager");
  const [newFullName, setNewFullName] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const createMut = useMutation({
    mutationFn: () =>
      api.createUser({
        username: newUsername,
        password: newPassword,
        role: newRole,
        full_name: newFullName || null,
        is_active: true,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      setNewUsername("");
      setNewPassword("");
      setNewFullName("");
      setNewRole("manager");
      setErr(null);
    },
    onError: (e: any) => setErr(parseError(e.message)),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) =>
      api.updateUser(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
    onError: (e: any) => alert(parseError(e.message)),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => api.deleteUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
    onError: (e: any) => alert(parseError(e.message)),
  });

  if (user?.role !== "director") {
    return (
      <div className="card text-warn">
        Эта страница доступна только пользователю с ролью{" "}
        <code>director</code>.
      </div>
    );
  }

  const items = usersQ.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline gap-3">
        <h1 className="text-xl font-semibold">Пользователи</h1>
        <span className="text-xs text-muted">
          роль <code>director</code> = полный доступ; <code>manager</code> =
          ограниченный (нет редактирования налогов / OPEX-категорий /
          расписания налогов / списка пользователей)
        </span>
      </div>

      <section className="card">
        <h2 className="font-medium mb-2">Создать пользователя</h2>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-2 items-end">
          <Field label="Логин">
            <input
              className="input"
              type="text"
              value={newUsername}
              onChange={(e: any) =>
                setNewUsername(e.target.value.toLowerCase())
              }
              autoComplete="off"
            />
          </Field>
          <Field label="Пароль (≥ 8)">
            <input
              className="input"
              type="password"
              value={newPassword}
              onChange={(e: any) => setNewPassword(e.target.value)}
              autoComplete="new-password"
            />
          </Field>
          <Field label="Роль">
            <select
              className="input"
              value={newRole}
              onChange={(e: any) => setNewRole(e.target.value)}
            >
              <option value="manager">manager</option>
              <option value="head_of_sales">head_of_sales</option>
              <option value="director">director</option>
            </select>
          </Field>
          <Field label="Имя">
            <input
              className="input"
              type="text"
              value={newFullName}
              onChange={(e: any) => setNewFullName(e.target.value)}
            />
          </Field>
          <button
            className="btn-primary"
            onClick={() => createMut.mutate()}
            disabled={
              !newUsername.trim() ||
              newPassword.length < 8 ||
              createMut.isPending
            }
          >
            Создать
          </button>
        </div>
        {err && <div className="text-danger text-xs mt-2">{err}</div>}
      </section>

      <section className="card">
        <h2 className="font-medium mb-2">Список ({items.length})</h2>
        {items.length === 0 ? (
          <div className="text-muted text-sm">Нет пользователей.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-muted text-xs uppercase">
              <tr>
                <th className="text-left p-2">Логин</th>
                <th className="text-left p-2">Имя</th>
                <th className="text-left p-2">Роль</th>
                <th className="text-left p-2">Активен</th>
                <th className="text-left p-2">Последний вход</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((u) => (
                <tr key={u.id} className="border-t border-border">
                  <td className="p-2 font-mono text-xs">
                    {u.username}
                    {user?.id === u.id && (
                      <span className="ml-2 text-accent">(вы)</span>
                    )}
                  </td>
                  <td className="p-2 text-xs text-muted">
                    {u.full_name || "—"}
                  </td>
                  <td className="p-2">
                    <select
                      className="input text-xs py-1"
                      value={u.role}
                      disabled={user?.id === u.id}
                      onChange={(e: any) =>
                        updateMut.mutate({
                          id: u.id,
                          body: { role: e.target.value },
                        })
                      }
                    >
                      <option value="manager">manager</option>
                      <option value="head_of_sales">head_of_sales</option>
                      <option value="director">director</option>
                    </select>
                  </td>
                  <td className="p-2">
                    <input
                      type="checkbox"
                      checked={u.is_active}
                      disabled={user?.id === u.id}
                      onChange={(e: any) =>
                        updateMut.mutate({
                          id: u.id,
                          body: { is_active: e.target.checked },
                        })
                      }
                    />
                  </td>
                  <td className="p-2 font-mono text-xs">
                    {u.last_login_at
                      ? u.last_login_at.replace("T", " ").slice(0, 16)
                      : "—"}
                  </td>
                  <td className="p-2 text-right whitespace-nowrap">
                    <button
                      className="btn text-xs mr-1"
                      onClick={() => {
                        const newPass = prompt(
                          `Новый пароль для ${u.username} (≥ 8 символов):`,
                        );
                        if (newPass && newPass.length >= 8) {
                          updateMut.mutate({
                            id: u.id,
                            body: { password: newPass },
                          });
                        }
                      }}
                    >
                      <Icon name="settings" size={12} /> пароль
                    </button>
                    <button
                      className="btn text-xs"
                      disabled={user?.id === u.id}
                      onClick={() => {
                        if (
                          confirm(
                            `Удалить пользователя ${u.username}? Это действие необратимо.`,
                          )
                        )
                          deleteMut.mutate(u.id);
                      }}
                    >
                      <Icon name="close" size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
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

function parseError(msg: string): string {
  const m = msg.match(/"detail":"([^"]+)"/);
  if (m) return m[1];
  return msg;
}
