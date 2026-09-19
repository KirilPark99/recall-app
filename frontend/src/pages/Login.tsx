import { FormEvent, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useApp } from "../state/AppContext";
import { ApiError } from "../api/client";

export function LoginPage() {
  const { t, login } = useApp();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username.trim(), password);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "USER_BLOCKED") setError(t("user_blocked"));
        else setError(t("invalid_credentials"));
      } else {
        setError(t("error_generic"));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-8">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div
            className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl text-2xl font-black shadow-lg"
            style={{ background: "linear-gradient(135deg, #6366f1 0%, #4338ca 100%)", color: "#ffffff" }}
          >
            R
          </div>
          <h1 className="text-3xl sm:text-4xl font-black tracking-tight">{t("login_title")}</h1>
        </div>
        <form onSubmit={submit} className="card space-y-5 p-8 sm:p-10 rounded-3xl shadow-card" noValidate>
          <div>
            <label htmlFor="username" className="mb-2 block text-base font-semibold">
              {t("username")}
            </label>
            <input
              id="username"
              className="input text-base min-h-[3.25rem] rounded-xl"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="password" className="mb-2 block text-base font-semibold">
              {t("password")}
            </label>
            <div className="relative">
              <input
                id="password"
                type={show ? "text" : "password"}
                className="input text-base min-h-[3.25rem] rounded-xl pr-12"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1.5 text-[var(--text-muted)] cursor-pointer"
                onClick={() => setShow((s) => !s)}
                aria-label={show ? t("hide_password") : t("show_password")}
              >
                {show ? <EyeOff size={20} aria-hidden /> : <Eye size={20} aria-hidden />}
              </button>
            </div>
          </div>
          {error && (
            <p role="alert" className="rounded-xl px-4 py-3 text-base" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
              {error}
            </p>
          )}
          <button type="submit" className="btn btn-primary w-full min-h-[3.25rem] text-base font-bold rounded-xl" disabled={busy}>
            {busy ? t("loading") : t("sign_in")}
          </button>
        </form>
      </div>
    </div>
  );
}
