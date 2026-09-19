import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, setCsrfToken, setUnauthorizedHandler } from "../api/client";
import { Locale, translate } from "../i18n";
import { devLog } from "../dev";

export interface User {
  id: string;
  username: string;
  role: string;
  preferred_locale: Locale;
  timezone: string;
  theme: "light" | "dark" | "system";
}

interface Preferences {
  daily_goal_reviews: number;
  daily_goal_minutes: number;
  daily_goal_new_cards: number;
  batch_size: number;
  goals_enabled: boolean;
  streak_enabled: boolean;
  sound_enabled: boolean;
  autoplay_audio: boolean;
  volume: number;
  tts_rate: number;
  prefer_local_voices: boolean;
  allow_network_voices: boolean;
  default_direction: string;
  normalization_policy: string;
  font_scale: number;
  reduced_motion: boolean;
}

interface AppState {
  user: User | null;
  prefs: Preferences | null;
  loading: boolean;
  locale: Locale;
  t: (key: Parameters<typeof translate>[1], params?: Record<string, string | number>) => string;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  setLocale: (locale: Locale) => Promise<void>;
  setTheme: (theme: "light" | "dark" | "system") => Promise<void>;
  refreshPrefs: () => Promise<void>;
}

const AppContext = createContext<AppState | null>(null);

export function useApp(): AppState {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp outside provider");
  return ctx;
}

function applyTheme(theme: "light" | "dark" | "system") {
  const dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [localeState, setLocaleState] = useState<Locale>("ru");

  const t = useCallback(
    (key: Parameters<typeof translate>[1], params?: Record<string, string | number>) =>
      translate(localeState, key, params),
    [localeState]
  );

  const bootstrapCsrf = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/auth/csrf", { credentials: "same-origin" });
      if (res.ok) {
        const data = (await res.json()) as { csrf_token: string };
        setCsrfToken(data.csrf_token);
      }
    } catch {
      devLog("csrf bootstrap failed");
    }
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      const me = await api<User>("/me");
      setUser(me);
      setLocaleState(me.preferred_locale === "en" ? "en" : "ru");
      applyTheme(me.theme);
      try {
        const p = await api<Preferences>("/me/preferences");
        setPrefs(p);
        document.documentElement.style.setProperty("--font-scale", String(p.font_scale ?? 1));
      } catch {
        setPrefs(null);
      }
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    (async () => {
      await bootstrapCsrf();
      await refreshUser();
      setLoading(false);
    })();
  }, [bootstrapCsrf, refreshUser]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setCsrfToken(null);
      setUser(null);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      if (user?.theme === "system") applyTheme("system");
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [user?.theme]);

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await api<{ user: User; csrf_token: string }>("/auth/login", {
        body: { username, password },
      });
      setCsrfToken(res.csrf_token);
      setUser(res.user);
      setLocaleState(res.user.preferred_locale === "en" ? "en" : "ru");
      applyTheme(res.user.theme);
      const p = await api<Preferences>("/me/preferences").catch(() => null);
      setPrefs(p);
    },
    []
  );

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      setCsrfToken(null);
      setUser(null);
      setPrefs(null);
    }
  }, []);

  const setLocale = useCallback(
    async (loc: Locale) => {
      await api("/me", { method: "PATCH", body: { preferred_locale: loc } });
      setLocaleState(loc);
      setUser((u) => (u ? { ...u, preferred_locale: loc } : u));
    },
    []
  );

  const setTheme = useCallback(
    async (theme: "light" | "dark" | "system") => {
      applyTheme(theme);
      await api("/me", { method: "PATCH", body: { theme } });
      setUser((u) => (u ? { ...u, theme } : u));
    },
    []
  );

  const refreshPrefs = useCallback(async () => {
    try {
      const p = await api<Preferences>("/me/preferences");
      setPrefs(p);
      document.documentElement.style.setProperty("--font-scale", String(p.font_scale ?? 1));
    } catch {
      /* noop */
    }
  }, []);

  const value = useMemo(
    () => ({ user, prefs, loading, locale: localeState, t, login, logout, refreshUser, setLocale, setTheme, refreshPrefs }),
    [user, prefs, loading, localeState, t, login, logout, refreshUser, setLocale, setTheme, refreshPrefs]
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
