import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { BookOpen, Plus, Repeat, Upload, ChevronRight, Target } from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";
import { cardsLabel, formatRelative } from "../i18n";

interface SessionInfo {
  id: string;
  mode: string;
  status: string;
  item_count: number;
}
interface SetItem {
  id: string;
  title: string;
  card_count: number;
  updated_at: string;
  last_studied_at: string | null;
}
interface SrsOverview {
  due_now: number;
  new: number;
  new_limit: number;
}
interface Goal {
  enabled: boolean;
  target_reviews: number;
  reviews_done: number;
  target_minutes: number;
  minutes_done: number;
}

export function HomePage() {
  const { t, locale, prefs } = useApp();
  const navigate = useNavigate();

  const sessions = useQuery({
    queryKey: ["sessions", "latest"],
    queryFn: () => api<SessionInfo[]>("/study-sessions?limit=1"),
  });
  const sets = useQuery({
    queryKey: ["sets", "recent", locale],
    queryFn: () => api<SetItem[]>("/sets?page_size=6&sort=updated"),
  });
  const srs = useQuery({
    queryKey: ["srs", "overview"],
    queryFn: () => api<SrsOverview>("/srs/overview"),
  });
  const goal = useQuery({
    queryKey: ["stats", "summary"],
    queryFn: () => api<{ goal: Goal }>("/stats/summary"),
  });

  const activeSession = sessions.data?.find((s) => s.status === "active" || s.status === "paused");
  const goalData = goal.data?.goal;
  const goalPct =
    goalData && goalData.target_reviews > 0
      ? Math.min(100, Math.round((goalData.reviews_done / goalData.target_reviews) * 100))
      : null;

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      {/* Header section */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black tracking-tight sm:text-4xl">{t("nav_home")}</h1>
          <p className="mt-1 text-base text-[var(--text-muted)]">
            {locale === "ru" ? "Изучайте карточки и достигайте ежедневных целей" : "Master your flashcards with adaptive spaced repetition"}
          </p>
        </div>
      </div>

      {/* Action Heroes / Quick launcher */}
      <div className="grid gap-4 sm:grid-cols-2">
        {activeSession ? (
          <button
            className="card group flex items-center justify-between p-5 text-left transition-all hover:border-[var(--accent)]"
            onClick={() => navigate(`/study/${activeSession.id}`)}
          >
            <div className="flex items-center gap-4">
              <div
                className="flex h-13 w-13 items-center justify-center rounded-2xl shadow-sm transition-transform group-hover:scale-105"
                style={{ background: "var(--accent)", color: "#ffffff" }}
              >
                <BookOpen size={26} aria-hidden />
              </div>
              <div>
                <p className="text-base font-bold sm:text-lg">{t("continue_session")}</p>
                <p className="text-sm text-[var(--text-muted)]">
                  {t(`mode_${activeSession.mode === "write" ? "write" : activeSession.mode}` as never)} · {activeSession.item_count} {t("cards_count")}
                </p>
              </div>
            </div>
            <ChevronRight size={22} className="text-[var(--text-muted)] transition-transform group-hover:translate-x-1" aria-hidden />
          </button>
        ) : (
          <button
            className="card group flex items-center justify-between p-5 text-left transition-all hover:border-[var(--accent)]"
            onClick={() => navigate("/review")}
          >
            <div className="flex items-center gap-4">
              <div
                className="flex h-13 w-13 items-center justify-center rounded-2xl shadow-sm transition-transform group-hover:scale-105"
                style={{
                  background: srs.data && srs.data.due_now + srs.data.new > 0 ? "var(--accent)" : "var(--surface-2)",
                  color: srs.data && srs.data.due_now + srs.data.new > 0 ? "#ffffff" : "var(--accent)",
                }}
              >
                <Repeat size={26} aria-hidden />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <p className="text-base font-bold sm:text-lg">{t("to_review")}</p>
                  {srs.data && srs.data.due_now + srs.data.new > 0 && (
                    <span className="badge badge-accent font-bold">
                      {srs.data.due_now + srs.data.new}
                    </span>
                  )}
                </div>
                <p className="text-sm text-[var(--text-muted)]">
                  {srs.data && srs.data.due_now > 0
                    ? `${srs.data.due_now} к повторению прямо сейчас`
                    : "Интервальное повторение FSRS"}
                </p>
              </div>
            </div>
            <ChevronRight size={22} className="text-[var(--text-muted)] transition-transform group-hover:translate-x-1" aria-hidden />
          </button>
        )}

        <div className="grid grid-cols-2 gap-3">
          <button
            className="btn btn-primary flex-col gap-2 p-5 text-center sm:flex-row sm:text-left"
            onClick={() => navigate("/sets?create=1")}
          >
            <Plus size={22} aria-hidden />
            <span className="text-base font-bold">{t("create_set")}</span>
          </button>
          <button
            className="btn btn-secondary flex-col gap-2 p-5 text-center sm:flex-row sm:text-left"
            onClick={() => navigate("/sets?import=1")}
          >
            <Upload size={22} aria-hidden />
            <span className="text-base font-bold">{t("import_sets")}</span>
          </button>
        </div>
      </div>

      {/* Daily Goal Card */}
      {prefs?.goals_enabled !== false && goalData && goalData.target_reviews > 0 && (
        <section className="card p-6" aria-label={t("daily_goal")}>
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
                <Target size={22} aria-hidden />
              </div>
              <div>
                <span className="text-base font-bold sm:text-lg">{t("daily_goal")}</span>
                <p className="text-sm text-[var(--text-muted)]">
                  {goalData.reviews_done} из {goalData.target_reviews} {t("reviews_today")}
                </p>
              </div>
            </div>
            <span className="badge badge-accent text-sm font-bold">
              {goalPct ?? 0}%
            </span>
          </div>

          <div className="h-3.5 overflow-hidden rounded-full p-0.5" style={{ background: "var(--surface-2)" }}>
            <div
              className="h-full rounded-full transition-all duration-500 ease-out"
              style={{
                width: `${goalPct ?? 0}%`,
                background: "linear-gradient(90deg, var(--accent) 0%, #818cf8 100%)",
              }}
              role="progressbar"
              aria-valuenow={goalPct ?? 0}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
        </section>
      )}

      {/* Recent Sets Section */}
      <section aria-label={t("recent_sets")} className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold tracking-tight sm:text-2xl">{t("recent_sets")}</h2>
          <Link to="/sets" className="flex items-center gap-1 text-sm font-semibold hover:underline" style={{ color: "var(--accent)" }}>
            {t("nav_sets")} <ChevronRight size={16} aria-hidden />
          </Link>
        </div>

        {sets.isLoading ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="skeleton h-28" />
            ))}
          </div>
        ) : sets.data && sets.data.length > 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {sets.data.map((s) => (
              <Link
                key={s.id}
                to={`/sets/${s.id}`}
                className="card group flex flex-col justify-between p-5 transition-all hover:border-[var(--border-hover)]"
              >
                <div>
                  <h3 className="text-base font-bold group-hover:text-[var(--accent)] sm:text-lg">{s.title}</h3>
                  <div className="mt-3 flex items-center gap-2">
                    <span className="badge">{cardsLabel(locale, s.card_count)}</span>
                  </div>
                </div>
                <div className="mt-4 border-t pt-3 text-xs text-[var(--text-muted)]">
                  {s.last_studied_at
                    ? `${t("last_studied")} ${formatRelative(s.last_studied_at, locale)}`
                    : t("never_studied")}
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="card p-10 text-center">
            <p className="text-base font-bold sm:text-lg">{t("no_sets")}</p>
            <p className="mt-1 text-sm text-[var(--text-muted)]">{t("no_sets_hint")}</p>
          </div>
        )}
      </section>
    </div>
  );
}
