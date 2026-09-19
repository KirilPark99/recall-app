import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";

interface ActivityDay {
  date: string;
  srs_reviews: number;
  study_answers: number;
  sessions: number;
}
interface WeakCard {
  card_id: string;
  front_text: string;
  back_text: string;
  mistakes: number;
}
interface Summary {
  goal: { enabled: boolean; target_reviews: number; reviews_done: number; target_minutes: number; minutes_done: number };
  srs: { due_now: number; later: number; new: number; suspended: number; learning: number };
  streak_days: number;
  streak_note: string;
}
interface TestRow {
  session_id: string;
  score: number;
  max_score: number;
  percent: number | null;
  finished_at: string;
}

export function StatsPage() {
  const { t, locale } = useApp();
  const summary = useQuery({ queryKey: ["stats", "summary"], queryFn: () => api<Summary>("/stats/summary") });
  const activity = useQuery({ queryKey: ["stats", "activity"], queryFn: () => api<{ days: ActivityDay[] }>("/stats/activity?days=30") });
  const weak = useQuery({ queryKey: ["stats", "weak"], queryFn: () => api<{ items: WeakCard[] }>("/stats/weak-cards") });
  const tests = useQuery({ queryKey: ["stats", "tests"], queryFn: () => api<TestRow[]>("/stats/tests") });

  const maxCount = Math.max(1, ...(activity.data?.days ?? []).map((d) => Math.max(d.srs_reviews, d.study_answers)));

  return (
    <div className="mx-auto max-w-4xl space-y-7">
      <h1 className="text-3xl sm:text-4xl font-black tracking-tight">{t("stats_title")}</h1>

      <section className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Counter label={t("due_now")} value={summary.data?.srs.due_now ?? "—"} />
        <Counter label={t("new_cards")} value={summary.data?.srs.new ?? "—"} />
        <Counter label={t("stats_title")} value={summary.data ? `${summary.data.streak_days} (${summary.data.streak_note})` : "—"} />
        <Counter
          label={t("minutes_short")}
          value={summary.data ? `${summary.data.goal.minutes_done}/${summary.data.goal.target_minutes}` : "—"}
        />
      </section>

      <section className="card p-6 sm:p-7 rounded-3xl shadow-card">
        <h2 className="mb-4 text-xl font-bold tracking-tight">{t("stats_title")} · 30d</h2>
        {activity.data && activity.data.days.length > 0 ? (
          <div className="flex h-44 items-end gap-1.5" role="img" aria-label="График активности по дням">
            {activity.data.days.map((d) => (
              <div key={d.date} className="group relative flex flex-1 flex-col justify-end" title={`${d.date}: ${d.srs_reviews} повторений, ${d.study_answers} ответов`}>
                <div
                  className="w-full rounded-t-md"
                  style={{ height: `${(d.srs_reviews / maxCount) * 60}%`, background: "var(--accent)" }}
                />
                <div
                  className="w-full rounded-t-md"
                  style={{ height: `${(d.study_answers / maxCount) * 40}%`, background: "var(--accent-soft)" }}
                />
                <span className="pointer-events-none absolute -top-9 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded-xl bg-[var(--surface)] px-3 py-1.5 text-xs font-bold shadow-lg group-hover:block border border-[var(--border)]">
                  {d.date}: {d.srs_reviews} / {d.study_answers}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="py-8 text-center text-base text-[var(--text-muted)]">
            {t("empty_state_title")}
          </p>
        )}
        <div className="mt-4 flex gap-6 text-sm font-medium text-[var(--text-muted)]">
          <span className="flex items-center gap-2">
            <span className="inline-block h-3.5 w-3.5 rounded-full" style={{ background: "var(--accent)" }} /> SRS
          </span>
          <span className="flex items-center gap-2">
            <span className="inline-block h-3.5 w-3.5 rounded-full" style={{ background: "var(--accent-soft)" }} /> {t("answers")}
          </span>
        </div>
      </section>

      <div className="grid gap-5 md:grid-cols-2">
        <section className="card p-6 rounded-3xl shadow-card">
          <h2 className="mb-4 text-xl font-bold tracking-tight">{t("result_incorrect")}</h2>
          {weak.data && weak.data.items.length > 0 ? (
            <ul className="space-y-2">
              {weak.data.items.slice(0, 8).map((c) => (
                <li key={c.card_id} className="flex items-center justify-between gap-3 rounded-xl px-3 py-2 text-base font-medium" style={{ background: "var(--surface-2)" }}>
                  <span className="min-w-0 truncate">{c.front_text}</span>
                  <span className="badge shrink-0 text-sm font-bold px-2.5 py-0.5">{c.mistakes} ✗</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-6 text-center text-base text-[var(--text-muted)]">{t("empty_state_title")}</p>
          )}
        </section>

        <section className="card p-6 rounded-3xl shadow-card">
          <h2 className="mb-4 text-xl font-bold tracking-tight">{t("test_history")}</h2>
          {tests.data && tests.data.length > 0 ? (
            <ul className="space-y-2">
              {tests.data.slice(0, 8).map((tr) => (
                <li key={tr.session_id} className="flex items-center justify-between rounded-xl px-3 py-2 text-base font-medium" style={{ background: "var(--surface-2)" }}>
                  <span>{new Date(tr.finished_at).toLocaleDateString(locale === "ru" ? "ru-RU" : "en-US")}</span>
                  <span className="font-bold">{tr.percent != null ? `${tr.percent}%` : `${tr.score}/${tr.max_score}`}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-6 text-center text-base text-[var(--text-muted)]">{t("empty_state_title")}</p>
          )}
        </section>
      </div>

      <p className="text-sm text-[var(--text-muted)]">
        {t("learned_note")}
      </p>
    </div>
  );
}

function Counter({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card p-5 text-center rounded-2xl shadow-card">
      <div className="text-2xl sm:text-3xl font-black tracking-tight">{value}</div>
      <div className="mt-1 text-sm font-medium text-[var(--text-muted)]">{label}</div>
    </div>
  );
}
