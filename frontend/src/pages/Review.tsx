import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Eye, Undo2, CheckCircle2, Volume2, VolumeX } from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";
import { speak, stopSpeaking } from "../lib/tts";
import { useStudySound } from "./study/useStudySound";

interface QueueItem {
  card_id: string;
  state_id: string | null;
  direction: string;
  state_name: string;
  is_new: boolean;
  question_text: string;
  answer_text: string;
  hint: string;
  context: string;
}
interface Overview {
  due_now: number;
  later: number;
  new: number;
  new_limit: number;
  learning: number;
  suspended: number;
}
interface Enrollment {
  set_id: string;
  enabled: boolean;
  forward_enabled: boolean;
  reverse_enabled: boolean;
}

const RATINGS = [
  ["again", "Не помню", "var(--danger)"],
  ["hard", "Трудно", "var(--warning)"],
  ["good", "Помню", "var(--success)"],
  ["easy", "Легко", "var(--accent)"],
] as const;

export function ReviewPage() {
  const { t, prefs } = useApp();
  const qc = useQueryClient();
  const { soundOn, toggleSound } = useStudySound();
  const [showAnswer, setShowAnswer] = useState(false);
  const [lastReview, setLastReview] = useState<{ card_id: string; direction: string; review_id: string } | null>(null);
  const [undoDone, setUndoDone] = useState(false);

  const overview = useQuery({ queryKey: ["srs", "overview"], queryFn: () => api<Overview>("/srs/overview") });
  const queue = useQuery({
    queryKey: ["srs", "queue"],
    queryFn: () => api<{ items: QueueItem[] }>("/srs/queue?limit=20"),
  });
  const enrollments = useQuery({
    queryKey: ["srs", "enrollments"],
    queryFn: () => api<Enrollment[]>("/srs/enrollments"),
  });
  const mySets = useQuery({
    queryKey: ["sets", "for-enroll"],
    queryFn: () => api<Array<{ id: string; title: string }>>("/sets?page_size=100"),
  });

  const review = useMutation({
    mutationFn: ({ item, rating }: { item: QueueItem; rating: string }) =>
      api<{ review_id: string }>("/srs/reviews", {
        body: {
          card_id: item.card_id,
          direction: item.direction,
          rating,
          client_event_id: crypto.randomUUID(),
        },
      }),
    onSuccess: (data, vars) => {
      setLastReview({ card_id: vars.item.card_id, direction: vars.item.direction, review_id: data.review_id });
      setShowAnswer(false);
      setUndoDone(false);
      qc.invalidateQueries({ queryKey: ["srs"] });
    },
  });

  const undo = useMutation({
    mutationFn: () => api(`/srs/reviews/${lastReview!.review_id}/undo`, { method: "POST" }),
    onSuccess: () => {
      setUndoDone(true);
      setLastReview(null);
      qc.invalidateQueries({ queryKey: ["srs"] });
    },
  });

  const enroll = useMutation({
    mutationFn: (setId: string) =>
      api("/srs/enroll", { body: { set_id: setId, enabled: true, forward_enabled: true, reverse_enabled: false } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["srs"] }),
  });

  const items = queue.data?.items ?? [];
  const current = items[0];
  const enrolledSetIds = new Set((enrollments.data ?? []).filter((e) => e.enabled).map((e) => e.set_id));
  const notEnrolled = (mySets.data ?? []).filter((s) => !enrolledSetIds.has(s.id));

  useEffect(() => {
    if (current && soundOn) {
      speak(current.question_text, { rate: prefs?.tts_rate, volume: prefs?.volume });
      return () => stopSpeaking();
    }
  }, [current?.card_id, current?.direction, soundOn, prefs]);

  useEffect(() => {
    if (showAnswer && current && soundOn) {
      speak(current.answer_text, { rate: prefs?.tts_rate, volume: prefs?.volume });
    }
  }, [showAnswer, current, soundOn, prefs]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName?.match(/INPUT|TEXTAREA|SELECT/)) return;

      if (e.key === "m" || e.key === "M" || e.key === "ь" || e.key === "Ь") {
        toggleSound();
        return;
      }

      if ((e.key === "z" || e.key === "Z" || e.key === "я" || e.key === "Я" || e.key === "u" || e.key === "U") && lastReview && !undoDone) {
        e.preventDefault();
        undo.mutate();
        return;
      }

      if (!current) return;

      if (!showAnswer) {
        if (e.key === "Escape") {
          e.preventDefault();
          setShowAnswer(true);
        } else if (e.code === "Space" || e.key === "Enter" || e.code === "ArrowDown") {
          e.preventDefault();
          setShowAnswer(true);
        } else if (e.key === "r" || e.key === "R" || e.key === "к" || e.key === "К") {
          speak(current.question_text, { rate: prefs?.tts_rate, volume: prefs?.volume });
        }
      } else {
        if ((e.key === "Escape" || e.key === "1" || e.code === "Digit1") && !review.isPending) {
          e.preventDefault();
          review.mutate({ item: current, rating: "again" });
        } else if (["2", "3", "4"].includes(e.key) && !review.isPending) {
          e.preventDefault();
          const idx = parseInt(e.key, 10) - 1;
          const ratingKey = RATINGS[idx]?.[0];
          if (ratingKey) {
            review.mutate({ item: current, rating: ratingKey });
          }
        } else if (e.key === "r" || e.key === "R" || e.key === "к" || e.key === "К") {
          speak(current.answer_text, { rate: prefs?.tts_rate, volume: prefs?.volume });
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [current, showAnswer, lastReview, undoDone, review, undo, prefs, toggleSound]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => stopSpeaking(), []);

  return (
    <div className="mx-auto max-w-4xl space-y-7 pb-12">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black tracking-tight sm:text-4xl">{t("nav_review")}</h1>
          <p className="mt-1 text-base text-[var(--text-muted)]">
            Интервальное повторение FSRS (Free Spaced Repetition Scheduler)
          </p>
        </div>
        <button
          type="button"
          className={`btn btn-ghost rounded-full p-2.5 transition-all ${
            soundOn
              ? "text-[var(--accent)] bg-[var(--accent-soft)] hover:bg-[var(--accent-soft)]"
              : "text-[var(--text-muted)] hover:bg-[var(--surface-2)]"
          }`}
          onClick={toggleSound}
          title={soundOn ? "Автоозвучка включена [M]" : "Автоозвучка выключена [M]"}
          aria-label={soundOn ? "Выключить озвучку" : "Включить озвучку"}
          aria-pressed={soundOn}
        >
          {soundOn ? <Volume2 size={24} aria-hidden /> : <VolumeX size={24} aria-hidden />}
        </button>
      </div>

      {overview.data && (
        <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-4">
          <Counter label={t("due_now")} value={overview.data.due_now} highlight={overview.data.due_now > 0} />
          <Counter label={t("new_cards")} value={`${Math.min(overview.data.new, overview.data.new_limit)}/${overview.data.new_limit}`} />
          <Counter label={t("mode_learn")} value={overview.data.learning} />
          <Counter label={t("sort_last_studied")} value={overview.data.later} />
        </div>
      )}

      {undoDone && (
        <p role="status" className="rounded-xl px-4 py-3 text-base font-semibold shadow-sm" style={{ background: "var(--success-soft)", color: "var(--success)" }}>
          ✓ Последняя оценка отменена.
        </p>
      )}

      {current ? (
        <div className="study-card p-8 sm:p-12 text-center min-h-[340px] flex flex-col justify-between rounded-3xl shadow-card">
          <div className="flex items-center justify-between text-sm text-[var(--text-muted)]">
            <span className="badge badge-accent font-semibold">{current.is_new ? t("new_cards") : stateLabel(current.state_name)}</span>
            <span className="badge">{current.direction === "front_to_back" ? t("dir_front_to_back") : t("dir_back_to_front")}</span>
          </div>

          <div className="my-6">
            <div className="flex items-center justify-center gap-3">
              <p className="text-2xl sm:text-3xl md:text-4xl font-bold tracking-tight text-[var(--text)] leading-snug">
                {current.question_text}
              </p>
              <button
                type="button"
                className="btn btn-ghost p-2 text-[var(--accent)] hover:bg-[var(--accent-soft)] rounded-xl shrink-0"
                onClick={() => speak(current.question_text, { rate: prefs?.tts_rate, volume: prefs?.volume })}
                title="Озвучить вопрос [R]"
                aria-label="Озвучить"
              >
                <Volume2 size={24} aria-hidden />
              </button>
            </div>
            {current.context && (
              <p className="mt-3 text-base text-[var(--text-muted)]">{current.context}</p>
            )}
          </div>

          {!showAnswer ? (
            <div>
              <button className="btn btn-primary mx-auto min-h-[3.25rem] px-8 text-base font-bold shadow-md rounded-2xl flex items-center gap-2" onClick={() => setShowAnswer(true)}>
                <Eye size={20} aria-hidden />
                <span>{t("show_answer")}</span>
                <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-white/25 rounded">Пробел</kbd>
              </button>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="rounded-2xl p-6 flex items-center justify-center gap-3" style={{ background: "var(--surface-2)" }} aria-live="polite">
                <p className="text-2xl sm:text-3xl font-bold tracking-tight text-[var(--accent)] leading-snug">
                  {current.answer_text}
                </p>
                <button
                  type="button"
                  className="btn btn-ghost p-2 text-[var(--accent)] hover:bg-[var(--accent-soft)] rounded-xl shrink-0"
                  onClick={() => speak(current.answer_text, { rate: prefs?.tts_rate, volume: prefs?.volume })}
                  title="Озвучить ответ [R]"
                  aria-label="Озвучить"
                >
                  <Volume2 size={24} aria-hidden />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {RATINGS.map(([rating, label, color], i) => (
                  <button
                    key={rating}
                    className="btn btn-secondary min-h-[3.5rem] text-base font-bold transition-all hover:scale-102 rounded-2xl flex items-center justify-center gap-2"
                    style={{ color: color as string }}
                    disabled={review.isPending}
                    onClick={() => review.mutate({ item: current, rating })}
                  >
                    <kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-3)] text-xs font-mono font-bold text-[var(--text)]">{i === 0 ? "1 / Esc" : i + 1}</kbd>
                    <span>{label}</span>
                  </button>
                ))}
              </div>
              <p className="text-center text-xs text-[var(--text-muted)]">
                {t("rating_hint")}
              </p>
            </div>
          )}

          {lastReview && !undoDone && (
            <div className="mt-5 text-center border-t pt-3">
              <button className="btn btn-ghost text-sm font-medium flex items-center gap-1.5 mx-auto" onClick={() => undo.mutate()} disabled={undo.isPending}>
                <Undo2 size={16} aria-hidden />
                <span>{t("undo_review")}</span>
                <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-[var(--surface-2)] border border-[var(--border)] rounded text-[var(--text-muted)]">Z</kbd>
              </button>
            </div>
          )}

          {/* Keyboard hints footer */}
          <div className="mt-6 hidden sm:flex flex-wrap items-center justify-center gap-2.5 text-xs text-[var(--text-muted)] opacity-75 border-t pt-4">
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Пробел</kbd> / <kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">↓</kbd> Показать ответ</span>
            <span>•</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Esc</kbd> / <kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">1</kbd> Не помню</span>
            <span>•</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">2</kbd>–<kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">4</kbd> Оценка</span>
            <span>•</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Z</kbd> Отменить</span>
            <span>•</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">R</kbd> Звук</span>
            <span>•</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">M</kbd> Вкл/выкл звук</span>
          </div>
        </div>
      ) : (
        <div className="card p-12 text-center">
          <CheckCircle2 size={48} className="mx-auto mb-4 text-[var(--success)]" aria-hidden />
          <p className="text-xl font-bold">{t("srs_nothing_due")}</p>
          <p className="mt-2 text-base text-[var(--text-muted)]">{t("srs_nothing_due_hint")}</p>
        </div>
      )}

      {/* Enroll sets */}
      <section className="space-y-3">
        <h2 className="text-xl font-bold tracking-tight sm:text-2xl">{t("nav_sets")}</h2>
        {notEnrolled.length > 0 ? (
          <ul className="space-y-2.5">
            {notEnrolled.slice(0, 8).map((s) => (
              <li key={s.id} className="card flex items-center justify-between p-4 transition-all hover:border-[var(--border-hover)]">
                <Link to={`/sets/${s.id}`} className="text-base font-semibold hover:text-[var(--accent)]">{s.title}</Link>
                <button className="btn btn-secondary min-h-[2.5rem] px-5 text-sm font-semibold" onClick={() => enroll.mutate(s.id)} disabled={enroll.isPending}>
                  {t("enroll")}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-[var(--text-muted)]">{t("empty_state_title")}</p>
        )}
      </section>
    </div>
  );
}

function stateLabel(s: string): string {
  return { learning: "Изучается", review: "На повторении", relearning: "Переучивается" }[s] ?? s;
}

function Counter({ label, value, highlight }: { label: string; value: string | number; highlight?: boolean }) {
  return (
    <div
      className="card p-5 text-center transition-transform hover:scale-102"
      style={highlight ? { borderColor: "var(--accent)", background: "var(--accent-soft)" } : undefined}
    >
      <div
        className="text-2xl sm:text-3xl font-black"
        style={highlight ? { color: "var(--accent)" } : undefined}
      >
        {value}
      </div>
      <div className="mt-1 text-sm font-medium text-[var(--text-muted)]">{label}</div>
    </div>
  );
}
