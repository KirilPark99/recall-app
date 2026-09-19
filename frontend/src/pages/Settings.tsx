import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, User, Volume2, Shield, Laptop, Smartphone, LogOut, Loader2, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";
import { Locale } from "../i18n";
import { speak } from "../lib/tts";

interface SessionRow {
  id: string;
  created_at: string;
  last_seen_at: string;
  user_agent: string | null;
  ip: string | null;
  is_current: boolean;
}

function parseUserAgent(ua: string | null): { name: string; isMobile: boolean } {
  if (!ua) return { name: "Устройство", isMobile: false };
  const isMobile = /Android|iPhone|iPad|Mobile/i.test(ua);
  let browser = "Браузер";
  if (/Firefox\/([0-9.]+)/i.test(ua)) browser = "Firefox";
  else if (/Edg\/([0-9.]+)/i.test(ua)) browser = "Edge";
  else if (/Chrome\/([0-9.]+)/i.test(ua)) browser = "Chrome";
  else if (/Safari\/([0-9.]+)/i.test(ua) && !/Chrome/i.test(ua)) browser = "Safari";
  else if (/curl/i.test(ua)) browser = "cURL";
  else if (/python-httpx/i.test(ua)) browser = "HTTPX (скрипт)";
  else if (/requests/i.test(ua)) browser = "Requests (скрипт)";
  else if (/Secondary-Device/i.test(ua)) browser = "Secondary Device";

  let os = "";
  if (/Windows/i.test(ua)) os = "Windows";
  else if (/Android/i.test(ua)) os = "Android";
  else if (/iPhone|iPad/i.test(ua)) os = "iOS";
  else if (/Macintosh|Mac OS/i.test(ua)) os = "macOS";
  else if (/Linux/i.test(ua)) os = "Linux";

  const name = os ? `${browser} на ${os}` : browser;
  return { name, isMobile };
}

export function SettingsPage() {
  const { t, locale, user, prefs, setLocale, setTheme, refreshPrefs, logout } = useApp();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [passwordMsg, setPasswordMsg] = useState<string | null>(null);
  const [timezone, setTimezone] = useState(user?.timezone ?? "UTC");
  const [sessionAlert, setSessionAlert] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const sessions = useQuery({
    queryKey: ["auth", "sessions"],
    queryFn: () => api<SessionRow[]>("/auth/sessions"),
  });

  const [batchSizeInput, setBatchSizeInput] = useState<number | string>(prefs?.batch_size ?? 7);

  useEffect(() => {
    if (prefs?.batch_size !== undefined) {
      setBatchSizeInput(prefs.batch_size);
    }
  }, [prefs?.batch_size]);

  const commitBatchSize = (rawVal?: string | number) => {
    const src = rawVal !== undefined ? rawVal : batchSizeInput;
    const parsed = typeof src === "string" ? parseInt(src, 10) : src;
    const clamped = isNaN(parsed) ? 7 : Math.max(3, Math.min(50, parsed));
    setBatchSizeInput(clamped);
    if (clamped !== prefs?.batch_size) {
      patchPrefs.mutate({ batch_size: clamped });
    }
  };

  const patchPrefs = useMutation({
    mutationFn: (patch: Record<string, unknown>) => api("/me/preferences", { method: "PATCH", body: patch }),
    onSuccess: () => void refreshPrefs(),
  });

  const saveTimezone = useMutation({
    mutationFn: () => api("/me", { method: "PATCH", body: { timezone } }),
  });

  const changePassword = async (e: FormEvent) => {
    e.preventDefault();
    setPasswordMsg(null);
    try {
      await api("/auth/change-password", { body: { current_password: currentPassword, new_password: newPassword } });
      setPasswordMsg(t("password_changed"));
      setCurrentPassword("");
      setNewPassword("");
      void qc.invalidateQueries({ queryKey: ["auth", "sessions"] });
    } catch (err) {
      setPasswordMsg((err as Error).message);
    }
  };

  const revokeSession = useMutation({
    mutationFn: (id: string) => api(`/auth/sessions/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setSessionAlert({ type: "success", message: t("revoke_session_success") });
      void qc.invalidateQueries({ queryKey: ["auth", "sessions"] });
    },
    onError: (err) => {
      setSessionAlert({ type: "error", message: (err as Error).message || t("error_generic") });
    },
  });

  const revokeOthers = useMutation({
    mutationFn: () => api("/auth/sessions/revoke-others", { method: "POST" }),
    onSuccess: () => {
      setSessionAlert({ type: "success", message: t("revoke_others_success") });
      void qc.invalidateQueries({ queryKey: ["auth", "sessions"] });
    },
    onError: (err) => {
      setSessionAlert({ type: "error", message: (err as Error).message || t("error_generic") });
    },
  });

  const cleanupSessions = useMutation({
    mutationFn: () => api<{ ok: boolean; deleted: number }>("/auth/sessions/cleanup", { method: "POST" }),
    onSuccess: () => {
      setSessionAlert({ type: "success", message: t("cleanup_sessions_success") });
      void qc.invalidateQueries({ queryKey: ["auth", "sessions"] });
    },
    onError: (err) => {
      setSessionAlert({ type: "error", message: (err as Error).message || t("error_generic") });
    },
  });

  const revokeAll = useMutation({
    mutationFn: () => api("/auth/logout-all", { method: "POST" }),
    onSuccess: async () => {
      await logout();
      navigate("/login");
    },
    onError: (err) => {
      setSessionAlert({ type: "error", message: (err as Error).message || t("error_generic") });
    },
  });

  if (!user) return null;

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <div>
        <h1 className="text-3xl font-black tracking-tight sm:text-4xl">{t("settings_title")}</h1>
        <p className="mt-1 text-base text-[var(--text-muted)]">
          {locale === "ru" ? "Управление профилем, параметрами изучения и безопасностью" : "Manage your profile, study preferences and security"}
        </p>
      </div>

      {/* Profile & Theme */}
      <section className="card space-y-5 p-7">
        <div className="flex items-center gap-3 border-b pb-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
            <User size={20} aria-hidden />
          </div>
          <h2 className="text-xl font-bold">{t("profile")}</h2>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-semibold" htmlFor="lang">{t("language")}</label>
            <select
              id="lang"
              className="select"
              value={user.preferred_locale}
              onChange={(e) => void setLocale(e.target.value as Locale)}
            >
              <option value="ru">Русский</option>
              <option value="en">English</option>
            </select>
          </div>
          <div>
            <label className="mb-2 block text-sm font-semibold" htmlFor="theme">{t("theme")}</label>
            <select
              id="theme"
              className="select"
              value={user.theme}
              onChange={(e) => void setTheme(e.target.value as "light" | "dark" | "system")}
            >
              <option value="light">{t("theme_light")}</option>
              <option value="dark">{t("theme_dark")}</option>
              <option value="system">{t("theme_system")}</option>
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="mb-2 block text-sm font-semibold" htmlFor="tz">{t("timezone")}</label>
            <div className="flex gap-3">
              <input id="tz" className="input flex-1" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
              <button className="btn btn-secondary px-6" onClick={() => saveTimezone.mutate()} disabled={saveTimezone.isPending}>
                {t("save")}
              </button>
            </div>
            {saveTimezone.isError && <p className="mt-2 text-sm font-medium" style={{ color: "var(--danger)" }}>Неизвестный часовой пояс.</p>}
          </div>
        </div>
      </section>

      {/* Study & Sound Preferences */}
      {prefs && (
        <section className="card space-y-6 p-7">
          <div className="flex items-center gap-3 border-b pb-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
              <Volume2 size={20} aria-hidden />
            </div>
            <h2 className="text-xl font-bold">{t("study_and_sound")}</h2>
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label className="mb-2 block text-sm font-semibold" htmlFor="dir">{t("default_direction")}</label>
              <select
                id="dir"
                className="select"
                value={prefs.default_direction}
                onChange={(e) => patchPrefs.mutate({ default_direction: e.target.value })}
              >
                <option value="front_to_back">{t("dir_front_to_back")}</option>
                <option value="back_to_front">{t("dir_back_to_front")}</option>
                <option value="both">{t("dir_both")}</option>
              </select>
            </div>
            <div>
              <label className="mb-2 block text-sm font-semibold" htmlFor="batch-size">{t("batch_size_label")}</label>
              <input
                id="batch-size"
                type="number"
                className="input"
                min={3}
                max={50}
                value={batchSizeInput}
                onChange={(e) => {
                  setBatchSizeInput(e.target.value);
                  const parsed = parseInt(e.target.value, 10);
                  if (!isNaN(parsed) && parsed >= 3 && parsed <= 50 && parsed !== prefs?.batch_size) {
                    patchPrefs.mutate({ batch_size: parsed });
                  }
                }}
                onBlur={(e) => commitBatchSize(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && commitBatchSize(e.currentTarget.value)}
              />
              <p className="mt-1.5 text-xs text-[var(--text-muted)]">{t("batch_size_hint")}</p>
            </div>
            <div>
              <label className="mb-2 block text-sm font-semibold" htmlFor="tts-rate">{t("speech_rate")} ({prefs.tts_rate}x)</label>
              <input
                id="tts-rate"
                type="range"
                min={0.5}
                max={2}
                step={0.1}
                value={prefs.tts_rate}
                onChange={(e) => patchPrefs.mutate({ tts_rate: parseFloat(e.target.value) })}
                className="w-full accent-[var(--accent)]"
              />
            </div>
            <div>
              <label className="mb-2 block text-sm font-semibold" htmlFor="goal">{t("daily_goal")} (SRS)</label>
              <input
                id="goal"
                type="number"
                className="input"
                min={0}
                max={1000}
                value={prefs.daily_goal_reviews}
                onChange={(e) => patchPrefs.mutate({ daily_goal_reviews: parseInt(e.target.value || "0", 10) })}
              />
            </div>
            <div className="sm:col-span-2">
              <label className="mb-2 block text-sm font-semibold" htmlFor="font">{t("font_size")} ({Math.round(prefs.font_scale * 100)}%)</label>
              <input
                id="font"
                type="range"
                min={0.8}
                max={1.5}
                step={0.05}
                value={prefs.font_scale}
                onChange={(e) => patchPrefs.mutate({ font_scale: parseFloat(e.target.value) })}
                className="w-full accent-[var(--accent)]"
              />
            </div>

            <div className="sm:col-span-2 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)]/60 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-bold text-sm block text-[var(--text-main)]">
                    🎙️ Естественная нейроозвучка (Neural HD)
                  </span>
                  <span className="text-xs text-[var(--text-muted)]">
                    Человеческое студийное произношение на русском, английском и других языках без роботизированного синтезатора.
                  </span>
                </div>
              </div>
              <div className="flex flex-wrap gap-2 pt-1">
                <button
                  type="button"
                  className="btn btn-secondary text-xs py-1.5 px-3 rounded-xl flex items-center gap-1.5 font-bold hover:border-[var(--accent)]"
                  onClick={() => speak("Привет! Это естественный человеческий голос Recall.", { lang: "ru", rate: prefs.tts_rate })}
                >
                  <Volume2 size={14} /> Проверить русский
                </button>
                <button
                  type="button"
                  className="btn btn-secondary text-xs py-1.5 px-3 rounded-xl flex items-center gap-1.5 font-bold hover:border-[var(--accent)]"
                  onClick={() => speak("Hello! This is a natural human voice in Recall.", { lang: "en", rate: prefs.tts_rate })}
                >
                  <Volume2 size={14} /> Check English
                </button>
              </div>
            </div>
          </div>

          <div className="space-y-3 pt-2">
            <label className="flex items-center gap-3 text-base font-medium cursor-pointer">
              <input type="checkbox" className="h-5 w-5 accent-[var(--accent)] rounded" checked={prefs.sound_enabled} onChange={(e) => patchPrefs.mutate({ sound_enabled: e.target.checked })} />
              {t("sound")}
            </label>
            <label className="flex items-center gap-3 text-base font-medium cursor-pointer">
              <input type="checkbox" className="h-5 w-5 accent-[var(--accent)] rounded" checked={prefs.allow_network_voices} onChange={(e) => patchPrefs.mutate({ allow_network_voices: e.target.checked })} />
              {t("allow_network_voices")}
            </label>
            <label className="flex items-center gap-3 text-base font-medium cursor-pointer">
              <input type="checkbox" className="h-5 w-5 accent-[var(--accent)] rounded" checked={prefs.reduced_motion} onChange={(e) => patchPrefs.mutate({ reduced_motion: e.target.checked })} />
              {t("reduced_motion")}
            </label>
          </div>
        </section>
      )}

      {/* Security */}
      <section className="card space-y-5 p-7">
        <div className="flex items-center gap-3 border-b pb-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
            <Shield size={20} aria-hidden />
          </div>
          <h2 className="text-xl font-bold">{t("security")}</h2>
        </div>

        <form onSubmit={changePassword} className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-semibold" htmlFor="cur-pass">{t("current_password")}</label>
            <input id="cur-pass" type="password" className="input" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} autoComplete="current-password" required />
          </div>
          <div>
            <label className="mb-2 block text-sm font-semibold" htmlFor="new-pass">{t("new_password")}</label>
            <input id="new-pass" type="password" className="input" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} minLength={8} autoComplete="new-password" required />
          </div>
          {passwordMsg && (
            <p role="status" className="sm:col-span-2 rounded-xl p-3.5 text-sm font-semibold" style={{
              background: passwordMsg === t("password_changed") ? "var(--success-soft)" : "var(--danger-soft)",
              color: passwordMsg === t("password_changed") ? "var(--success)" : "var(--danger)",
            }}>
              {passwordMsg}
            </p>
          )}
          <div className="sm:col-span-2 pt-1">
            <button className="btn btn-primary px-7 min-h-[3rem]" type="submit">{t("change_password")}</button>
          </div>
        </form>
      </section>

      {/* Active Sessions */}
      <section className="card space-y-5 p-7">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
              <Laptop size={20} aria-hidden />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-bold">{t("active_sessions")}</h2>
                {sessions.data && (
                  <span className="rounded-full px-2.5 py-0.5 text-xs font-semibold" style={{ background: "var(--surface-3)", color: "var(--text-muted)" }}>
                    {sessions.data.length}
                  </span>
                )}
              </div>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                {locale === "ru" ? "Управление активными входами и устройствами" : "Manage active sessions and devices"}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn btn-secondary text-xs sm:text-sm px-3 py-1.5 flex items-center gap-1.5"
              onClick={() => revokeOthers.mutate()}
              disabled={revokeOthers.isPending || (sessions.data ?? []).length <= 1}
              title={t("revoke_others")}
            >
              {revokeOthers.isPending ? <Loader2 size={15} className="animate-spin" /> : <LogOut size={15} />}
              <span>{t("revoke_others")}</span>
            </button>

            <button
              type="button"
              className="btn btn-ghost text-xs sm:text-sm px-3 py-1.5 flex items-center gap-1.5"
              onClick={() => cleanupSessions.mutate()}
              disabled={cleanupSessions.isPending}
              title={t("cleanup_stale_sessions")}
            >
              <RefreshCw size={15} className={cleanupSessions.isPending ? "animate-spin" : ""} />
              <span>{t("cleanup_stale_sessions")}</span>
            </button>

            <button
              type="button"
              className="btn btn-danger text-xs sm:text-sm px-3 py-1.5 flex items-center gap-1.5"
              onClick={() => revokeAll.mutate()}
              disabled={revokeAll.isPending}
            >
              {revokeAll.isPending ? <Loader2 size={15} className="animate-spin" /> : null}
              <span>{t("logout_all_devices")}</span>
            </button>
          </div>
        </div>

        {sessionAlert && (
          <div
            role="status"
            className="flex items-center justify-between rounded-xl p-3.5 text-sm font-semibold transition-all"
            style={{
              background: sessionAlert.type === "success" ? "var(--success-soft)" : "var(--danger-soft)",
              color: sessionAlert.type === "success" ? "var(--success)" : "var(--danger)",
            }}
          >
            <span>{sessionAlert.message}</span>
            <button
              type="button"
              className="ml-2 text-xs opacity-75 hover:opacity-100 underline"
              onClick={() => setSessionAlert(null)}
            >
              {t("close")}
            </button>
          </div>
        )}

        {sessions.isLoading ? (
          <div className="flex items-center justify-center p-8 text-[var(--text-muted)] gap-2">
            <Loader2 size={20} className="animate-spin" />
            <span>{t("loading")}</span>
          </div>
        ) : sessions.isError ? (
          <div className="rounded-xl p-4 text-sm" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
            {t("error_generic")}
          </div>
        ) : (sessions.data ?? []).length === 0 ? (
          <div className="p-6 text-center text-sm text-[var(--text-muted)]">
            {t("empty_state_title")}
          </div>
        ) : (
          <ul className="space-y-3">
            {(sessions.data ?? []).map((s) => {
              const { name: uaName, isMobile } = parseUserAgent(s.user_agent);
              const isPendingThis = revokeSession.isPending && revokeSession.variables === s.id;

              return (
                <li
                  key={s.id}
                  className="flex items-center justify-between gap-3 rounded-xl p-4 transition-all"
                  style={{
                    background: s.is_current ? "var(--surface-3)" : "var(--surface-2)",
                    border: s.is_current ? "1px solid var(--accent)" : "1px solid transparent",
                  }}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
                      style={{
                        background: s.is_current ? "var(--accent-soft)" : "var(--surface-3)",
                        color: s.is_current ? "var(--accent)" : "var(--text-muted)",
                      }}
                    >
                      {isMobile ? <Smartphone size={18} aria-hidden /> : <Laptop size={18} aria-hidden />}
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="truncate text-base font-semibold" title={s.user_agent || undefined}>
                          {uaName}
                        </span>
                        {s.is_current && (
                          <span
                            className="rounded-md px-2 py-0.5 text-xs font-bold uppercase tracking-wider"
                            style={{ background: "var(--accent)", color: "#fff" }}
                          >
                            {t("current_session")}
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-[var(--text-muted)] flex items-center gap-2 flex-wrap">
                        <span>{new Date(s.last_seen_at).toLocaleString()}</span>
                        {s.ip && <span>· {s.ip}</span>}
                        {s.user_agent && s.user_agent !== uaName && (
                          <span className="opacity-60 truncate max-w-xs hidden sm:inline" title={s.user_agent}>
                            · {s.user_agent}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {!s.is_current && (
                    <button
                      type="button"
                      className="btn btn-ghost p-2 text-[var(--danger)] hover:bg-[var(--danger-soft)]"
                      onClick={() => revokeSession.mutate(s.id)}
                      disabled={isPendingThis}
                      aria-label={t("revoke")}
                      title={t("revoke")}
                    >
                      {isPendingThis ? (
                        <Loader2 size={16} className="animate-spin" aria-hidden />
                      ) : (
                        <Trash2 size={16} aria-hidden />
                      )}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
