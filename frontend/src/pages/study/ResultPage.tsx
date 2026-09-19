import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Home, Volume2, X } from "lucide-react";
import { api } from "../../api/client";
import { useApp } from "../../state/AppContext";
import { speak } from "../../lib/tts";

interface ResultItem {
  item_id: string;
  task_type: string;
  question: string;
  user_answer: string | null;
  correct?: boolean | null;
  correct_text?: string;
  explanation?: string;
  assisted?: boolean;
  status: string;
  skipped?: boolean;
}
interface ResultDto {
  session_id: string;
  mode: string;
  status: string;
  active_ms: number;
  item_count: number;
  set_id?: string | null;
  set_title?: string | null;
  set_ids?: string[];
  known?: number;
  unknown?: number;
  correct?: number;
  incorrect?: number;
  assisted_count?: number;
  mastered?: string[];
  round_failed?: string[];
  hints_used?: number;
  score?: number;
  max_score?: number;
  percent?: number | null;
  detail?: Array<Record<string, unknown>>;
  history?: Array<{ session_id: string; percent: number | null; finished_at: string }>;
  elapsed_ms?: number;
  mistakes?: number;
  penalty_ms?: number;
  final_ms?: number;
  best_ms?: number | null;
  items?: ResultItem[];
}

export function ResultPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { t, locale } = useApp();
  const result = useQuery({
    queryKey: ["result", sessionId],
    queryFn: () => api<ResultDto>(`/study-sessions/${sessionId}/result`),
  });

  if (result.isLoading) {
    return <div className="mx-auto max-w-3xl p-6"><div className="skeleton h-40" /></div>;
  }
  if (result.isError || !result.data) {
    return <div className="p-8 text-center">{t("error_generic")}</div>;
  }
  const r = result.data;

  return (
    <div className="mx-auto max-w-4xl space-y-7 p-4 sm:p-6">
      {/* Верхняя панель: заголовок и быстрая кнопка выхода */}
      <div className="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-[var(--border)]">
        <div className="min-w-0">
          {r.set_title && (
            <Link
              to={r.set_id ? `/sets/${r.set_id}` : "/sets"}
              className="text-sm sm:text-base font-semibold text-[var(--accent)] hover:underline inline-flex items-center gap-1.5 mb-1.5"
            >
              <ArrowLeft size={16} aria-hidden />
              <span className="truncate max-w-md">{r.set_title}</span>
            </Link>
          )}
          <h1 className="text-3xl sm:text-4xl font-black tracking-tight">{t("session_complete")}</h1>
        </div>

        <div className="flex items-center gap-2.5">
          {r.set_id && (
            <Link
              to={`/sets/${r.set_id}`}
              id="btn-exit-to-set"
              className="btn btn-primary min-h-[3rem] px-5 sm:px-6 text-base font-bold rounded-2xl shadow-sm flex items-center gap-2 hover:scale-[1.02] active:scale-[0.98] transition-all"
            >
              <ArrowLeft size={18} aria-hidden />
              <span>{t("exit_to_set")}</span>
            </Link>
          )}
          <Link
            to="/"
            id="btn-exit-top"
            className={`btn ${r.set_id ? "btn-secondary" : "btn-primary"} min-h-[3rem] px-5 sm:px-6 text-base font-bold rounded-2xl shadow-sm flex items-center gap-2 hover:scale-[1.02] active:scale-[0.98] transition-all`}
            title={t("exit")}
            aria-label={t("exit_session")}
          >
            <X size={20} aria-hidden />
            <span>{t("exit")}</span>
          </Link>
        </div>
      </div>

      {/* Сводка по режимам */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {r.mode === "cards" && (
          <>
            <Stat label={t("know")} value={r.known ?? 0} />
            <Stat label={t("dont_know")} value={r.unknown ?? 0} />
            <Stat label={t("cards_count")} value={r.item_count} />
            <Stat label={t("result_time")} value={formatMs(r.active_ms)} />
          </>
        )}
        {(r.mode === "write" || r.mode === "spell") && (
          <>
            <Stat label={t("result_correct")} value={r.correct ?? 0} />
            <Stat label={t("result_incorrect")} value={r.incorrect ?? 0} />
            <Stat label={t("hint")} value={r.assisted_count ?? 0} />
            <Stat label={t("result_time")} value={formatMs(r.active_ms)} />
          </>
        )}
        {r.mode === "test" && (
          <>
            <Stat label={t("result_score")} value={`${r.score}/${r.max_score}`} />
            <Stat label="%" value={r.percent != null ? `${r.percent}%` : "—"} />
            <Stat label={t("questions_count")} value={r.item_count} />
            <Stat label={t("result_time")} value={formatMs(r.active_ms)} />
          </>
        )}
        {r.mode === "match" && (
          <>
            <Stat label={t("result_time")} value={formatMs(r.final_ms ?? 0)} />
            <Stat label={t("result_time")} value={formatMs(r.elapsed_ms ?? 0)} />
            <Stat label={t("result_mistakes")} value={r.mistakes ?? 0} />
            <Stat label={t("result_best")} value={r.best_ms ? formatMs(r.best_ms) : formatMs(r.final_ms ?? 0)} />
          </>
        )}
        {r.mode === "learn" && (
          <>
            <Stat label={t("mastered")} value={r.mastered?.length ?? 0} />
            <Stat label={t("remaining")} value={r.round_failed?.length ?? 0} />
            <Stat label={t("hint")} value={r.hints_used ?? 0} />
            <Stat label={t("result_time")} value={formatMs(r.active_ms)} />
          </>
        )}
      </div>

      {/* Тест: разбор */}
      {r.mode === "test" && r.detail && (
        <section className="space-y-3">
          <h2 className="text-xl sm:text-2xl font-bold tracking-tight">{t("question")}</h2>
          {r.detail.map((d, i) => {
            const earned = d.earned as number;
            const max = d.max as number;
            return (
              <div key={i} className="card p-5 sm:p-6 rounded-2xl shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-lg font-bold">
                      {typeof d.question === "string" && d.question ? d.question : "Сопоставление"}
                    </div>
                    {d.user_answer != null && (
                      <div className="mt-1.5 text-base">
                        {t("answer")}: <span className="font-semibold">{typeof d.user_answer === "string" ? d.user_answer || "—" : JSON.stringify(d.user_answer)}</span>
                      </div>
                    )}
                    {d.correct_answer != null && !earned && (
                      <div className="mt-1 text-base font-semibold" style={{ color: "var(--success)" }}>
                        {t("correct_answer_was")}: {String(d.correct_answer)}
                      </div>
                    )}
                    {d.explanation ? <div className="mt-1.5 text-sm text-[var(--text-muted)]">{String(d.explanation)}</div> : null}
                  </div>
                  <span
                    className="badge shrink-0 text-base font-bold px-3 py-1 rounded-xl"
                    style={{
                      background: earned === max ? "var(--success-soft)" : "var(--danger-soft)",
                      color: earned === max ? "var(--success)" : "var(--danger)",
                    }}
                  >
                    {earned}/{max}
                  </span>
                </div>
              </div>
            );
          })}
        </section>
      )}

      {/* Write/spell/cards: список ответов с фильтром ошибок */}
      {(r.mode === "write" || r.mode === "spell" || r.mode === "cards") && r.items && (
        <MistakesList items={r.items} />
      )}

      {/* Test history */}
      {r.mode === "test" && r.history && r.history.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-xl sm:text-2xl font-bold tracking-tight">{t("test_history")}</h2>
          <ul className="space-y-2">
            {r.history.slice(0, 10).map((h) => (
              <li key={h.session_id} className="flex justify-between items-center rounded-xl px-4 py-3 text-base" style={{ background: "var(--surface-2)" }}>
                <span>{new Date(h.finished_at).toLocaleString(locale === "ru" ? "ru-RU" : "en-US")}</span>
                <span className="font-bold text-lg">{h.percent != null ? `${h.percent}%` : "—"}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="flex flex-wrap gap-3 pt-2">
        <Link to={`/study/new?mode=${r.mode}&set=${r.session_id ? "" : ""}`} className="hidden" aria-hidden />
        {r.set_id && (
          <Link to={`/sets/${r.set_id}`} className="btn btn-primary min-h-[3rem] px-7 text-base font-bold rounded-xl flex items-center gap-2">
            <ArrowLeft size={18} aria-hidden /> {t("exit_to_set")}
          </Link>
        )}
        <Link to="/" className="btn btn-secondary min-h-[3rem] px-7 text-base font-bold rounded-xl flex items-center gap-2">
          <Home size={18} aria-hidden /> {t("nav_home")}
        </Link>
      </div>
      <p className="text-sm text-[var(--text-muted)]">
        {t("learned_note")}
      </p>
    </div>
  );
}

function MistakesList({ items }: { items: ResultItem[] }) {
  const { t, prefs } = useApp();
  const [onlyMistakes, setOnlyMistakes] = useState(false);
  const answerLabel = (v: string | null) =>
    v === "known" ? t("know") : v === "unknown" ? t("dont_know") : v;
  const filtered = onlyMistakes ? items.filter((i) => i.correct === false) : items;
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xl sm:text-2xl font-bold tracking-tight">{t("answers")}</h2>
        <label className="flex items-center gap-2 text-base font-medium cursor-pointer">
          <input type="checkbox" className="h-5 w-5 rounded" checked={onlyMistakes} onChange={(e) => setOnlyMistakes(e.target.checked)} />
          {t("only_mistakes")}
        </label>
      </div>
      {filtered.map((item) => (
        <div key={item.item_id} className="card p-4 sm:p-5 rounded-2xl shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-base sm:text-lg font-semibold">{item.question}</span>
                <button
                  type="button"
                  className="btn btn-ghost p-1 text-[var(--text-muted)] hover:text-[var(--text)] rounded-lg"
                  onClick={() => speak(item.question, { rate: prefs?.tts_rate, volume: prefs?.volume })}
                  title="Озвучить вопрос"
                  aria-label="Озвучить вопрос"
                >
                  <Volume2 size={16} aria-hidden />
                </button>
              </div>
              <div className="mt-1.5 text-base text-[var(--text-muted)] flex items-center gap-2 flex-wrap">
                <span>{item.user_answer ? `Ответ: ${answerLabel(item.user_answer)}` : "Без ответа"}</span>
                {item.correct_text && item.correct === false && (
                  <span className="flex items-center gap-1.5">
                    <span>· правильно: <strong className="text-[var(--text)]">{item.correct_text}</strong></span>
                    <button
                      type="button"
                      className="btn btn-ghost p-1 text-[var(--accent)] hover:bg-[var(--accent-soft)] rounded-lg"
                      onClick={() => speak(item.correct_text!, { rate: prefs?.tts_rate, volume: prefs?.volume })}
                      title="Озвучить правильный ответ"
                      aria-label="Озвучить правильный ответ"
                    >
                      <Volume2 size={16} aria-hidden />
                    </button>
                  </span>
                )}
              </div>
              {item.explanation && <div className="mt-1 text-sm text-[var(--text-muted)]">{item.explanation}</div>}
            </div>
            {item.correct != null && (
              <span
                className="badge shrink-0 text-base font-bold px-3 py-1 rounded-xl"
                style={{
                  background: item.correct ? "var(--success-soft)" : "var(--danger-soft)",
                  color: item.correct ? "var(--success)" : "var(--danger)",
                }}
              >
                {item.correct ? "✓" : "✗"}
              </span>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="card p-5 sm:p-6 text-center rounded-2xl shadow-card hover:shadow-card-hover transition-all">
      <div className="text-xl font-bold sm:text-4xl sm:font-black tracking-tight">{value}</div>
      <div className="mt-1 text-sm font-medium text-[var(--text-muted)]">{label}</div>
    </div>
  );
}

function formatMs(ms: number): string {
  const totalSec = Math.round(ms / 1000);
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return min > 0 ? `${min} мин ${sec} с` : `${sec} с`;
}
