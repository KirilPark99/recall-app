import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Download, FolderKanban, Globe, Loader2, ShieldCheck, Trash2, UserPlus } from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";

interface AdminUser {
  id: string;
  username: string;
  role: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  set_count: number;
}
interface Status {
  app_version: string;
  env: string;
  migrations_applied: boolean;
  database: { size_bytes: number; users: number; sets: number };
  media: { count: number; size_bytes: number };
  last_backup: { name: string } | null;
}
interface AuditRow {
  id: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  created_at: string;
}

interface ServerSettings {
  registration_enabled: boolean;
  quizlet_proxy_url: string;
  quizlet_headless: boolean;
}

export function AdminPage() {
  const { t } = useApp();
  const qc = useQueryClient();
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [proxyInput, setProxyInput] = useState<string | null>(null);
  const [proxyTestResult, setProxyTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  const users = useQuery({ queryKey: ["admin", "users"], queryFn: () => api<{ items: AdminUser[] }>("/admin/users") });
  const status = useQuery({ queryKey: ["admin", "status"], queryFn: () => api<Status>("/admin/status") });
  const settings = useQuery({
    queryKey: ["admin", "settings"],
    queryFn: () => api<ServerSettings>("/admin/settings"),
  });
  const backups = useQuery({ queryKey: ["admin", "backups"], queryFn: () => api<Array<{ name: string; size_bytes: number }>>("/admin/backups") });
  const audit = useQuery({ queryKey: ["admin", "audit"], queryFn: () => api<AuditRow[]>("/admin/audit-events?limit=20") });

  const currentProxyValue = proxyInput !== null ? proxyInput : (settings.data?.quizlet_proxy_url ?? "");

  const testProxyMutation = useMutation({
    mutationFn: (url: string) =>
      api<{ ok: boolean; message: string; latency_ms?: number }>("/admin/proxy/test", {
        method: "POST",
        body: { proxy_url: url.trim() },
      }),
    onSuccess: (data) => {
      setProxyTestResult({ ok: true, message: data.message });
    },
    onError: (err) => {
      setProxyTestResult({ ok: false, message: (err as Error).message });
    },
  });

  const patchUser = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) =>
      api(`/admin/users/${id}`, { method: "PATCH", body: patch }),
    onSuccess: () => {
      setMsg(null);
      qc.invalidateQueries({ queryKey: ["admin"] });
    },
    onError: (e) => setMsg((e as Error).message),
  });
  const deleteUser = useMutation({
    mutationFn: (id: string) => api(`/admin/users/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin"] }),
    onError: (e) => setMsg((e as Error).message),
  });
  const createUser = useMutation({
    mutationFn: () => api("/admin/users", { body: { username: newUsername.trim(), password: newPassword } }),
    onSuccess: () => {
      setNewUsername("");
      setNewPassword("");
      qc.invalidateQueries({ queryKey: ["admin"] });
    },
    onError: (e) => setMsg((e as Error).message),
  });
  const patchSettings = useMutation({
    mutationFn: (patch: Record<string, unknown>) => api("/admin/settings", { method: "PATCH", body: patch }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin"] }),
  });
  const createBackup = useMutation({
    mutationFn: () => api("/admin/backups", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin"] }),
  });

  const submitCreate = (e: FormEvent) => {
    e.preventDefault();
    createUser.mutate();
  };

  const fmtSize = (b: number) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MiB` : `${Math.round(b / 1024)} KiB`);

  return (
    <div className="mx-auto max-w-4xl space-y-7">
      <h1 className="text-3xl sm:text-4xl font-black tracking-tight">{t("nav_admin")}</h1>
      {msg && (
        <p role="alert" className="rounded-xl px-4 py-3 text-base" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
          {msg}
        </p>
      )}

      <section className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Пользователи" value={status.data?.database.users ?? "—"} />
        <Stat label="Наборы" value={status.data?.database.sets ?? "—"} />
        <Stat label="База" value={status.data ? fmtSize(status.data.database.size_bytes) : "—"} />
        <Stat label="Медиа" value={status.data ? `${status.data.media.count} / ${fmtSize(status.data.media.size_bytes)}` : "—"} />
      </section>

      <section className="card space-y-4 p-6 sm:p-7 rounded-3xl shadow-card">
        <h2 className="text-xl font-bold tracking-tight">{t("server_settings")}</h2>
        <label className="flex items-center gap-2.5 text-base font-medium cursor-pointer">
          <input
            type="checkbox"
            className="h-5 w-5 rounded"
            checked={settings.data?.registration_enabled ?? false}
            onChange={(e) => patchSettings.mutate({ registration_enabled: e.target.checked })}
          />
          {t("allow_registration")}
        </label>
        <p className="text-sm text-[var(--text-muted)]">
          {t("env_limits_note")}
        </p>
      </section>

      <section className="card space-y-5 p-6 sm:p-7 rounded-3xl shadow-card">
        <div className="flex items-center gap-2.5">
          <Globe className="text-[var(--primary)]" size={24} aria-hidden />
          <h2 className="text-xl font-bold tracking-tight">Импорт из Quizlet: Headless режим и Прокси</h2>
        </div>
        <p className="text-sm text-[var(--text-muted)]">
          Настройки сетевого доступа для фонового копирования наборов и классов из Quizlet.
        </p>

        <div className="space-y-4 pt-1">
          {/* Headless режим */}
          <label className="flex items-start gap-3 text-base font-medium cursor-pointer">
            <input
              type="checkbox"
              className="mt-1 h-5 w-5 rounded"
              checked={settings.data?.quizlet_headless ?? true}
              onChange={(e) => patchSettings.mutate({ quizlet_headless: e.target.checked })}
            />
            <div>
              <div className="font-bold">Headless режим (фоновый браузер без всплывающего окна)</div>
              <p className="text-sm text-[var(--text-muted)] font-normal">
                При включении Chrome работает полностью невидимо в фоне, автоматически проходя проверки Cloudflare Turnstile при импорте карточек и папок.
              </p>
            </div>
          </label>

          {/* Прокси сервер */}
          <div className="space-y-2 pt-2 border-t border-[var(--border)]">
            <label htmlFor="proxy-url-input" className="block text-sm font-bold">
              Прокси-сервер для импорта (HTTP / SOCKS5)
            </label>
            <p className="text-xs text-[var(--text-muted)]">
              Если Quizlet блокирует IP вашего сервера или выдаёт капчу (PerimeterX / Cloudflare), укажите рабочий прокси. Все запросы на импорт будут направляться через него.
            </p>
            <div className="flex flex-col sm:flex-row gap-2.5 pt-1">
              <input
                id="proxy-url-input"
                className="input flex-1 text-base min-h-[3rem] rounded-xl font-mono text-sm"
                placeholder="http://user:pass@host:port или socks5://host:port"
                value={currentProxyValue}
                onChange={(e) => {
                  setProxyInput(e.target.value);
                  setProxyTestResult(null);
                }}
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  className="btn btn-secondary min-h-[3rem] px-4 text-sm font-semibold rounded-xl flex items-center gap-2"
                  disabled={testProxyMutation.isPending || !currentProxyValue.trim()}
                  onClick={() => testProxyMutation.mutate(currentProxyValue)}
                >
                  {testProxyMutation.isPending ? (
                    <>
                      <Loader2 size={16} className="animate-spin" aria-hidden /> Проверка...
                    </>
                  ) : (
                    "Проверить прокси"
                  )}
                </button>
                <button
                  type="button"
                  className="btn btn-primary min-h-[3rem] px-5 text-sm font-bold rounded-xl"
                  disabled={patchSettings.isPending || proxyInput === null || proxyInput === (settings.data?.quizlet_proxy_url ?? "")}
                  onClick={() => {
                    patchSettings.mutate(
                      { quizlet_proxy_url: currentProxyValue.trim() },
                      {
                        onSuccess: () => {
                          setProxyInput(null);
                        },
                      }
                    );
                  }}
                >
                  Сохранить
                </button>
              </div>
            </div>

            {/* Результат проверки прокси */}
            {proxyTestResult && (
              <div
                className={`rounded-xl px-4 py-3 text-sm flex items-start gap-2.5 transition-all ${
                  proxyTestResult.ok
                    ? "bg-[var(--surface-2)] text-[var(--text)] border border-[var(--accent)]"
                    : "text-[var(--danger)]"
                }`}
                style={!proxyTestResult.ok ? { background: "var(--danger-soft)" } : {}}
              >
                {proxyTestResult.ok ? (
                  <CheckCircle2 size={18} className="text-[var(--accent)] shrink-0 mt-0.5" />
                ) : (
                  <AlertCircle size={18} className="text-[var(--danger)] shrink-0 mt-0.5" />
                )}
                <div>
                  <div className="font-bold">{proxyTestResult.ok ? "Прокси работает корректно" : "Ошибка прокси"}</div>
                  <div>{proxyTestResult.message}</div>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="card space-y-5 p-6 sm:p-7 rounded-3xl shadow-card">
        <h2 className="text-xl font-bold tracking-tight">{t("users")}</h2>
        <form onSubmit={submitCreate} className="flex flex-wrap gap-3">
          <input className="input flex-1 min-w-[140px] sm:w-48 text-base min-h-[3rem] rounded-xl" placeholder="имя" value={newUsername} onChange={(e) => setNewUsername(e.target.value)} aria-label="Имя нового пользователя" />
          <input className="input flex-1 min-w-[180px] sm:w-56 text-base min-h-[3rem] rounded-xl" placeholder="пароль (мин. 8)" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} aria-label="Пароль" />
          <button className="btn btn-primary min-h-[3rem] px-6 text-base font-bold rounded-xl" disabled={!newUsername || newPassword.length < 8 || createUser.isPending}>
            <UserPlus size={18} aria-hidden /> Создать
          </button>
        </form>
        <ul className="space-y-2">
          {(users.data?.items ?? []).map((u) => (
            <li key={u.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl p-4 text-base" style={{ background: "var(--surface-2)" }}>
              <div>
                <span className="font-bold">{u.username}</span>
                <span className="badge ml-2 font-bold">{u.role === "admin" ? t("role_admin") : "user"}</span>
                {!u.is_active && <span className="badge ml-1 font-bold" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>{t("blocked")}</span>}
                <div className="mt-0.5 text-sm text-[var(--text-muted)]">{u.set_count} наборов</div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  className={`btn ${selectedUserId === u.id ? "btn-primary" : "btn-secondary"} text-sm font-semibold rounded-xl`}
                  onClick={() => setSelectedUserId(selectedUserId === u.id ? null : u.id)}
                >
                  <FolderKanban size={14} aria-hidden /> {selectedUserId === u.id ? "Скрыть контент" : "Папки и наборы"}
                </button>
                <button
                  className="btn btn-secondary text-sm font-semibold rounded-xl"
                  onClick={() => patchUser.mutate({ id: u.id, patch: { role: u.role === "admin" ? "user" : "admin" } })}
                >
                  <ShieldCheck size={14} aria-hidden /> {u.role === "admin" ? "-admin" : "+admin"}
                </button>
                <button
                  className="btn btn-secondary text-sm font-semibold rounded-xl"
                  onClick={() => patchUser.mutate({ id: u.id, patch: { is_active: !u.is_active } })}
                >
                  {u.is_active ? t("archive") : t("restore")}
                </button>
                <button
                  className="btn btn-danger text-sm font-semibold rounded-xl"
                  onClick={() => {
                    if (window.confirm(`Удалить пользователя «${u.username}»? Его наборы будут удалены.`)) deleteUser.mutate(u.id);
                  }}
                >
                  <Trash2 size={14} aria-hidden />
                </button>
              </div>
              {selectedUserId === u.id && (
                <div className="w-full mt-3">
                  <UserContentManager
                    userId={u.id}
                    username={u.username}
                    onClose={() => setSelectedUserId(null)}
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="card space-y-4 p-6 sm:p-7 rounded-3xl shadow-card">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold tracking-tight">{t("backups")}</h2>
          <button className="btn btn-primary min-h-[2.85rem] px-6 text-base font-bold rounded-xl" onClick={() => createBackup.mutate()} disabled={createBackup.isPending}>
            <Download size={16} aria-hidden /> {createBackup.isPending ? "…" : t("create_backup")}
          </button>
        </div>
        <ul className="space-y-2 text-base">
          {(backups.data ?? []).map((b) => (
            <li key={b.name} className="flex items-center justify-between rounded-xl px-4 py-3" style={{ background: "var(--surface-2)" }}>
              <span className="font-semibold">{b.name}</span>
              <a className="btn btn-secondary text-sm font-semibold rounded-xl" href={`/api/v1/admin/backups/${encodeURIComponent(b.name)}/download`}>
                {t("download")} ({fmtSize(b.size_bytes)})
              </a>
            </li>
          ))}
          {backups.data?.length === 0 && <li className="text-[var(--text-muted)]">{t("empty_state_title")}</li>}
        </ul>
        <p className="text-sm text-[var(--text-muted)]">
          {t("restore_hint")} <code className="rounded bg-[var(--surface-2)] px-1.5 py-0.5">python -m app.cli backup restore PATH --confirm</code>
        </p>
      </section>

      <section className="card p-6 sm:p-7 rounded-3xl shadow-card">
        <h2 className="mb-3 text-xl font-bold tracking-tight">{t("audit_log")}</h2>
        <ul className="space-y-2 text-sm">
          {(audit.data ?? []).map((a) => (
            <li key={a.id} className="flex justify-between rounded-xl px-3 py-2" style={{ background: "var(--surface-2)" }}>
              <span className="font-medium">{a.action}</span>
              <span className="text-[var(--text-muted)]">{new Date(a.created_at).toLocaleString()}</span>
            </li>
          ))}
          {audit.data?.length === 0 && <li className="text-[var(--text-muted)]">{t("empty_state_title")}</li>}
        </ul>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card p-5 text-center rounded-2xl shadow-card">
      <div className="text-2xl sm:text-3xl font-black tracking-tight">{value}</div>
      <div className="mt-1 text-sm font-medium text-[var(--text-muted)]">{label}</div>
    </div>
  );
}

interface UserContentFolder {
  id: string;
  name: string;
  created_by_admin: boolean;
  created_at: string;
  set_count: number;
  sets: Array<{ id: string; title: string }>;
}

interface UserContentSet {
  id: string;
  title: string;
  owner_username: string;
  is_own: boolean;
  is_admin_created: boolean;
}

interface AvailableAdminSet {
  id: string;
  title: string;
  is_assigned: boolean;
}

interface AvailableAdminFolder {
  id: string;
  name: string;
  set_count: number;
  sets: Array<{ id: string; title: string }>;
  is_assigned: boolean;
}

interface UserContentData {
  user: { id: string; username: string; role: string };
  folders: UserContentFolder[];
  assigned_sets: UserContentSet[];
  available_admin_sets: AvailableAdminSet[];
  available_admin_folders?: AvailableAdminFolder[];
}

function UserContentManager({ userId, username, onClose }: { userId: string; username: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [selectedSetToAssign, setSelectedSetToAssign] = useState("");
  const [selectedFolderToAssign, setSelectedFolderToAssign] = useState("");
  const [newFolderName, setNewFolderName] = useState("");
  const [folderAddSet, setFolderAddSet] = useState<Record<string, string>>({});

  const contentQ = useQuery({
    queryKey: ["admin", "user-content", userId],
    queryFn: () => api<UserContentData>(`/admin/users/${userId}/content`),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["admin", "user-content", userId] });

  const assignSet = useMutation({
    mutationFn: (setId: string) => api(`/admin/users/${userId}/sets`, { body: { set_id: setId } }),
    onSuccess: () => {
      setSelectedSetToAssign("");
      invalidate();
    },
  });

  const unassignSet = useMutation({
    mutationFn: (setId: string) => api(`/admin/users/${userId}/sets/${setId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  const assignFolder = useMutation({
    mutationFn: (adminFolderId: string) =>
      api(`/admin/users/${userId}/folders/assign`, { body: { admin_folder_id: adminFolderId } }),
    onSuccess: () => {
      setSelectedFolderToAssign("");
      invalidate();
    },
  });

  const createFolder = useMutation({
    mutationFn: (name: string) => api(`/admin/users/${userId}/folders`, { body: { name } }),
    onSuccess: () => {
      setNewFolderName("");
      invalidate();
    },
  });

  const deleteFolder = useMutation({
    mutationFn: (folderId: string) => api(`/admin/users/${userId}/folders/${folderId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  const addSetToFolder = useMutation({
    mutationFn: ({ folderId, setId }: { folderId: string; setId: string }) =>
      api(`/admin/users/${userId}/folders/${folderId}/sets/${setId}`, { method: "PUT" }),
    onSuccess: () => {
      setFolderAddSet({});
      invalidate();
    },
  });

  const removeSetFromFolder = useMutation({
    mutationFn: ({ folderId, setId }: { folderId: string; setId: string }) =>
      api(`/admin/users/${userId}/folders/${folderId}/sets/${setId}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  if (contentQ.isLoading) {
    return (
      <div className="card p-5 space-y-3 bg-[var(--surface-1)] border border-[var(--border)] rounded-2xl">
        <div className="skeleton h-6 w-48" />
        <div className="skeleton h-20" />
      </div>
    );
  }

  const data = contentQ.data;
  if (!data) return null;

  const unassignedAdminSets = data.available_admin_sets.filter((s) => !s.is_assigned);

  return (
    <div className="card p-5 sm:p-6 space-y-6 bg-[var(--surface-1)] border-2 border-[var(--accent)] rounded-2xl shadow-lg">
      <div className="flex items-center justify-between border-b pb-3">
        <div>
          <h3 className="text-lg font-bold">Управление контентом: {username}</h3>
          <p className="text-xs text-[var(--text-muted)]">
            Администратор управляет доступом к наборам и папкам пользователя
          </p>
        </div>
        <button className="btn btn-secondary text-xs px-3 py-1.5 rounded-lg" onClick={onClose}>
          Закрыть
        </button>
      </div>

      {/* 1. Наборы пользователя */}
      <div className="space-y-3">
        <h4 className="text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
          Наборы пользователя ({data.assigned_sets.length})
        </h4>

        {/* Назначить набор из доступных администраторских */}
        <div className="flex flex-wrap gap-2 items-center">
          <select
            className="select text-sm rounded-xl flex-1 min-w-[200px]"
            value={selectedSetToAssign}
            onChange={(e) => setSelectedSetToAssign(e.target.value)}
            aria-label="Выбрать набор для назначения"
          >
            <option value="">-- Выберите набор администратора для назначения --</option>
            {unassignedAdminSets.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
          <button
            className="btn btn-primary text-sm font-bold px-4 rounded-xl"
            disabled={!selectedSetToAssign || assignSet.isPending}
            onClick={() => assignSet.mutate(selectedSetToAssign)}
          >
            + Назначить набор
          </button>
        </div>

        {data.assigned_sets.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)] italic">У пользователя нет доступных наборов</p>
        ) : (
          <ul className="space-y-2">
            {data.assigned_sets.map((s) => (
              <li
                key={s.id}
                className="flex items-center justify-between p-3 rounded-xl text-sm"
                style={{ background: "var(--surface-2)" }}
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{s.title}</span>
                  {s.is_admin_created ? (
                    <span className="badge badge-primary text-xs font-semibold">🔒 Назначен админом</span>
                  ) : (
                    <span className="badge text-xs font-semibold">Собственный набор</span>
                  )}
                </div>
                {s.is_admin_created && (
                  <button
                    className="btn btn-ghost text-xs text-[var(--danger)] px-2.5 py-1"
                    onClick={() => {
                      if (window.confirm(`Отозвать набор «${s.title}» у пользователя ${username}?`)) {
                        unassignSet.mutate(s.id);
                      }
                    }}
                  >
                    Отозвать
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 2. Папки пользователя */}
      <div className="space-y-3 border-t pt-4">
        <h4 className="text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
          Папки пользователя ({data.folders.length})
        </h4>

        {/* Назначить готовую папку администратора */}
        <div className="flex flex-wrap gap-2 items-center">
          <select
            className="select text-sm rounded-xl flex-1 min-w-[200px]"
            value={selectedFolderToAssign}
            onChange={(e) => setSelectedFolderToAssign(e.target.value)}
            aria-label="Выбрать готовую папку администратора"
          >
            <option value="">-- Выберите готовую папку администратора для назначения --</option>
            {(data.available_admin_folders ?? [])
              .filter((f) => !f.is_assigned)
              .map((f) => (
                <option key={f.id} value={f.id}>
                  📁 {f.name} ({f.set_count} наборов)
                </option>
              ))}
          </select>
          <button
            className="btn btn-primary text-sm font-bold px-4 rounded-xl"
            disabled={!selectedFolderToAssign || assignFolder.isPending}
            onClick={() => assignFolder.mutate(selectedFolderToAssign)}
          >
            + Назначить папку
          </button>
        </div>

        {/* Создать папку для пользователя */}
        <div className="flex flex-wrap gap-2 items-center">
          <input
            className="input text-sm rounded-xl flex-1 min-w-[200px]"
            placeholder="Название новой папки для пользователя"
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            aria-label="Название новой папки"
          />
          <button
            className="btn btn-primary text-sm font-bold px-4 rounded-xl"
            disabled={!newFolderName.trim() || createFolder.isPending}
            onClick={() => createFolder.mutate(newFolderName.trim())}
          >
            + Создать папку
          </button>
        </div>

        {data.folders.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)] italic">У пользователя нет папок</p>
        ) : (
          <ul className="space-y-3">
            {data.folders.map((f) => (
              <li
                key={f.id}
                className="p-4 rounded-xl border border-[var(--border)] space-y-3"
                style={{ background: "var(--surface-2)" }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-bold">{f.name}</span>
                    <span className="badge text-xs font-bold">{f.set_count} наборов</span>
                    {f.created_by_admin && (
                      <span className="badge badge-primary text-xs font-semibold">🔒 Создана админом</span>
                    )}
                  </div>
                  <button
                    className="btn btn-ghost text-xs text-[var(--danger)] p-1.5"
                    onClick={() => {
                      if (window.confirm(`Удалить папку «${f.name}» у пользователя ${username}?`)) {
                        deleteFolder.mutate(f.id);
                      }
                    }}
                    aria-label={`Удалить папку ${f.name}`}
                  >
                    <Trash2 size={16} aria-hidden />
                  </button>
                </div>

                {/* Наборы внутри папки */}
                {f.sets.length > 0 && (
                  <div className="space-y-1.5 pl-2 border-l-2 border-[var(--accent)]">
                    {f.sets.map((s) => (
                      <div key={s.id} className="flex items-center justify-between text-xs py-1">
                        <span>• {s.title}</span>
                        <button
                          className="btn btn-ghost text-xs text-[var(--danger)] px-2 py-0.5"
                          onClick={() => removeSetFromFolder.mutate({ folderId: f.id, setId: s.id })}
                        >
                          Убрать
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {/* Добавить набор в папку */}
                <div className="flex gap-2 items-center pt-1">
                  <select
                    className="select text-xs rounded-xl flex-1"
                    value={folderAddSet[f.id] || ""}
                    onChange={(e) => setFolderAddSet((prev) => ({ ...prev, [f.id]: e.target.value }))}
                    aria-label="Добавить набор в папку"
                  >
                    <option value="">-- Добавить набор в эту папку --</option>
                    {data.assigned_sets
                      .filter((s) => !f.sets.some((fs) => fs.id === s.id))
                      .map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.title}
                        </option>
                      ))}
                  </select>
                  <button
                    className="btn btn-secondary text-xs px-3 py-1.5 rounded-xl font-semibold"
                    disabled={!folderAddSet[f.id] || addSetToFolder.isPending}
                    onClick={() => {
                      const sId = folderAddSet[f.id];
                      if (sId) addSetToFolder.mutate({ folderId: f.id, setId: sId });
                    }}
                  >
                    + В папку
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

