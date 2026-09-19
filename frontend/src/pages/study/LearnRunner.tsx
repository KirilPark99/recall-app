import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Volume2 } from "lucide-react";
import { api } from "../../api/client";
import { useApp } from "../../state/AppContext";
import { MediaList, StudyChrome } from "./BasicRunners";
import type { Feedback, TaskDto } from "./types";
import { speak, stopSpeaking } from "../../lib/tts";
import { useStudySound } from "./useStudySound";

interface NextResponse {
  round_complete: boolean;
  status?: string;
  summary?: { mastered: string[]; round_failed: string[]; hints_used: number; remaining: string[]; total_batches: number; batch_index: number };
  task?: TaskDto;
  batch_info?: { batch_index: number; total_batches: number; queue_remaining: number; mastered_count: number };
}

export function LearnRunner({ sessionId }: { sessionId: string }) {
  const { t, prefs } = useApp();
  const navigate = useNavigate();
  const { soundOn, toggleSound } = useStudySound();
  const [task, setTask] = useState<TaskDto | null>(null);
  const [batchInfo, setBatchInfo] = useState<NextResponse["batch_info"] | null>(null);
  const [roundComplete, setRoundComplete] = useState<NextResponse["summary"] | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [text, setText] = useState("");
  const [hintShown, setHintShown] = useState(false);
  const [offline, setOffline] = useState(false);
  const [poolDone, setPoolDone] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const writtenInputRef = useRef<HTMLInputElement>(null);
  const isFinishedRef = useRef(false);
  const isTransitioningRef = useRef(false);
  const busyRef = useRef(false);

  useEffect(() => {
    if (task?.task_type === "written" && !feedback) {
      const focusInput = () => {
        writtenInputRef.current?.focus();
      };
      focusInput();
      const raf = requestAnimationFrame(focusInput);
      const timer = setTimeout(focusInput, 50);
      return () => {
        cancelAnimationFrame(raf);
        clearTimeout(timer);
      };
    }
  }, [task?.item_id, task?.task_type, feedback]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (task?.task_type === "written" && !feedback && writtenInputRef.current && document.activeElement !== writtenInputRef.current) {
        if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
          writtenInputRef.current.focus();
        }
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [task?.task_type, feedback]);

  const finish = useCallback(async () => {
    if (isFinishedRef.current) return;
    isFinishedRef.current = true;
    try {
      await api(`/study-sessions/${sessionId}/complete`, { method: "POST" });
    } catch { /* noop */ }
    navigate(`/study/${sessionId}/result`, { replace: true });
  }, [sessionId, navigate]);

  const fetchNext = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api<NextResponse>(`/study-sessions/${sessionId}/next`);
      if (res.round_complete) {
        setTask(null);
        setRoundComplete(res.summary ?? null);
        setPoolDone(res.status === "pool_complete");
      } else if (res.task) {
        setTask(res.task);
        if (res.batch_info) setBatchInfo(res.batch_info);
        setFeedback(null);
        setText("");
        setHintShown(false);
        setOffline(false);
        setRoundComplete(null);
      } else {
        void finish();
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Не удалось загрузить задание");
    } finally {
      setLoading(false);
    }
  }, [sessionId, finish]);

  useEffect(() => {
    void fetchNext();
  }, [fetchNext]);

  useEffect(() => {
    if (task && soundOn && task.question_text) {
      speak(task.question_text, { rate: prefs?.tts_rate, volume: prefs?.volume });
      return () => stopSpeaking();
    }
  }, [task?.item_id, soundOn, prefs]);

  const answer = async (payload: Record<string, unknown>, assisted: boolean) => {
    if (!task || busyRef.current) return;
    busyRef.current = true;
    try {
      const fb = await api<Feedback>(`/study-sessions/${sessionId}/answers`, {
        body: {
          item_id: task.item_id,
          client_event_id: crypto.randomUUID(),
          answer: { ...payload, used_hint: assisted },
        },
      });
      setOffline(false);
      setFeedback(fb);
      const ansToSpeak = fb.correct_text || (payload.choice as string) || (payload.text as string);
      if (soundOn && ansToSpeak) {
        speak(ansToSpeak, { rate: prefs?.tts_rate, volume: prefs?.volume });
      }
      if (fb.mastered) {
        setTimeout(() => void fetchNext(), 1200);
      }
    } catch {
      setOffline(true);
    } finally {
      busyRef.current = false;
    }
  };

  const submitText = async () => {
    if (!task) return;
    await answer({ text }, hintShown);
  };

  const choose = async (choice: string) => {
    if (!task || feedback) return;
    await answer({ choice }, hintShown);
  };

  const selfAssess = async (known: boolean) => {
    await answer({ known }, hintShown);
  };

  const repeatFailed = async () => {
    if (loading || isTransitioningRef.current) return;
    isTransitioningRef.current = true;
    setLoading(true);
    setError(null);
    try {
      await api(`/study-sessions/${sessionId}/learn/repeat-failed`, { method: "POST" });
      setRoundComplete(null);
      await fetchNext();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Ошибка при повторе ошибок");
      setLoading(false);
    } finally {
      isTransitioningRef.current = false;
    }
  };

  const nextBatch = async () => {
    if (loading || isTransitioningRef.current) return;
    isTransitioningRef.current = true;
    setRoundComplete(null);
    try {
      await fetchNext();
    } finally {
      isTransitioningRef.current = false;
    }
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (roundComplete) {
        if (!e.repeat && (e.code === "Space" || e.key === "Enter")) {
          e.preventDefault();
          if (roundComplete.round_failed.length > 0) {
            void repeatFailed();
          } else if (!poolDone && roundComplete.batch_index < roundComplete.total_batches) {
            void nextBatch();
          } else {
            void finish();
          }
        }
        return;
      }

      if (!task) return;
      const isInput = (e.target as HTMLElement)?.tagName?.match(/INPUT|TEXTAREA|SELECT/);

      // Feedback is showing
      if (feedback) {
        if (!e.repeat && (e.key === "Enter" || e.code === "Space")) {
          if (!feedback.mastered && task.task_type !== "self_assess") {
            e.preventDefault();
            void fetchNext();
          }
        } else if (e.key === "r" || e.key === "R" || e.key === "к" || e.key === "К") {
          const ans = feedback.correct_text;
          if (ans) {
            speak(ans, { rate: prefs?.tts_rate, volume: prefs?.volume });
          }
        }
        if (task.task_type === "self_assess") {
          if (!e.repeat && (e.key === "1" || e.code === "Digit1" || e.key === "Escape")) {
            e.preventDefault();
            void selfAssess(false);
          } else if (!e.repeat && (e.key === "2" || e.code === "Digit2")) {
            e.preventDefault();
            void selfAssess(true);
          }
        }
        return;
      }

      // No feedback yet
      if (task.task_type === "recognition") {
        if (e.key === "Escape") {
          e.preventDefault();
          void answer({ choice: "" }, hintShown);
        } else if (["1", "2", "3", "4"].includes(e.key)) {
          const idx = parseInt(e.key, 10) - 1;
          const choices = task.choices ?? [];
          if (choices[idx]) {
            e.preventDefault();
            void choose(choices[idx]);
          }
        } else if ((e.key === "r" || e.key === "R" || e.key === "к" || e.key === "К") && !isInput) {
          if (task.question_text) {
            speak(task.question_text, { rate: prefs?.tts_rate, volume: prefs?.volume });
          }
        }
      } else if (task.task_type === "self_assess") {
        if (!e.repeat && (e.key === "1" || e.code === "Digit1" || e.key === "Escape")) {
          e.preventDefault();
          void selfAssess(false);
        } else if (!e.repeat && (e.code === "Space" || e.key === "Enter" || e.code === "ArrowDown")) {
          e.preventDefault();
          api<{ correct_text: string }>(`/study-sessions/${sessionId}/items/${task.item_id}/reveal`, { method: "POST" })
            .then((res) => {
              setFeedback({ correct: false, correct_text: res.correct_text, assisted: true });
              if (soundOn && res.correct_text) {
                speak(res.correct_text, { rate: prefs?.tts_rate, volume: prefs?.volume });
              }
            })
            .catch(() => undefined);
        } else if ((e.key === "r" || e.key === "R" || e.key === "к" || e.key === "К") && !isInput) {
          if (task.question_text) {
            speak(task.question_text, { rate: prefs?.tts_rate, volume: prefs?.volume });
          }
        }
      } else if (task.task_type === "written") {
        if (isInput) {
          if ((e.ctrlKey || e.metaKey) && (e.key === "h" || e.key === "H" || e.key === "р" || e.key === "Р")) {
            e.preventDefault();
            if (task.hint && !hintShown) setHintShown(true);
          }
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          void answer({ text: "" }, hintShown);
        } else if (!e.repeat && e.key === "Enter" && document.activeElement !== writtenInputRef.current) {
          e.preventDefault();
          if (text.trim()) {
            void submitText();
          } else {
            writtenInputRef.current?.focus();
          }
        } else if ((e.ctrlKey || e.metaKey) && (e.key === "h" || e.key === "H" || e.key === "р" || e.key === "Р")) {
          e.preventDefault();
          if (task.hint && !hintShown) setHintShown(true);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [roundComplete, task, feedback, poolDone, sessionId, soundOn, prefs, hintShown, loading]); // eslint-disable-line react-hooks/exhaustive-deps

  if (roundComplete) {
    return (
      <StudyChrome onExit={() => void finish()} progress={t("round_complete")}>
        <div className="flex flex-1 flex-col items-center justify-center gap-6 text-center">
          <h2 className="text-2xl sm:text-3xl font-black tracking-tight">
            {roundComplete.round_failed.length > 0 ? t("repeat_mistakes_round") : t("round_complete")}
          </h2>
          <div className="card w-full max-w-md p-6 sm:p-8 rounded-3xl shadow-card space-y-3">
            <div className="flex items-center justify-between py-2 border-b border-[var(--border)] text-base">
              <span className="text-[var(--text-muted)] font-medium">{t("mastered")}</span>
              <strong className="text-xl font-black" style={{ color: "var(--success)" }}>{roundComplete.mastered.length}</strong>
            </div>
            <div className="flex items-center justify-between py-2 border-b border-[var(--border)] text-base">
              <span className="text-[var(--text-muted)] font-medium">{t("remaining")}</span>
              <strong className="text-xl font-black">{roundComplete.round_failed.length + roundComplete.remaining.length}</strong>
            </div>
            <div className="flex items-center justify-between py-2 text-base">
              <span className="text-[var(--text-muted)] font-medium">{t("hint")}</span>
              <strong className="text-xl font-black">{roundComplete.hints_used}</strong>
            </div>
          </div>
          <div className="flex flex-wrap justify-center gap-3">
            {roundComplete.round_failed.length > 0 ? (
              <button
                type="button"
                className="btn btn-primary min-h-[3.25rem] px-8 text-base font-bold rounded-xl"
                onClick={() => void repeatFailed()}
                disabled={loading}
              >
                {loading ? "Загрузка..." : `${t("repeat_mistakes")} (${roundComplete.round_failed.length})`}
              </button>
            ) : !poolDone && roundComplete.batch_index < roundComplete.total_batches ? (
              <button
                type="button"
                className="btn btn-primary min-h-[3.25rem] px-8 text-base font-bold rounded-xl"
                onClick={() => void nextBatch()}
                disabled={loading}
              >
                {loading ? "Загрузка..." : t("next_batch")}
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-primary min-h-[3.25rem] px-8 text-base font-bold rounded-xl"
                onClick={() => void finish()}
                disabled={loading}
              >
                {t("finish")}
              </button>
            )}
            <button
              type="button"
              className="btn btn-ghost min-h-[3.25rem] px-6 text-base font-medium rounded-xl"
              onClick={() => void finish()}
            >
              {t("finish")}
            </button>
          </div>
          <p className="max-w-sm text-sm text-[var(--text-muted)]">
            {t("learned_note")}
          </p>
        </div>
      </StudyChrome>
    );
  }

  if (error) {
    return (
      <StudyChrome onExit={() => void finish()}>
        <div className="flex flex-1 flex-col items-center justify-center p-6 text-center">
          <div className="study-card p-8 max-w-md w-full rounded-3xl shadow-card">
            <h3 className="text-xl font-bold text-red-600 mb-2">Произошла ошибка</h3>
            <p className="text-sm text-[var(--text-muted)] mb-6">{error}</p>
            <div className="flex gap-3 justify-center">
              <button className="btn btn-primary px-6" onClick={() => void fetchNext()}>
                Повторить попытку
              </button>
              <button className="btn btn-ghost px-4" onClick={() => void finish()}>
                Завершить
              </button>
            </div>
          </div>
        </div>
      </StudyChrome>
    );
  }

  if (loading || !task) {
    return (
      <StudyChrome onExit={() => void finish()}>
        <div className="flex flex-1 items-center justify-center p-8">
          <div className="skeleton w-full max-w-md h-64 rounded-3xl" />
        </div>
      </StudyChrome>
    );
  }

  return (
    <StudyChrome
      onExit={() => void finish()}
      stageInfo={{
        batchIndex: batchInfo ? batchInfo.batch_index - 1 : undefined,
        totalBatches: batchInfo?.total_batches,
        modeLabel: t(`task_type_${task.task_type}` as never) || taskLabel(task.task_type),
      }}
      soundOn={soundOn}
      onToggleSound={toggleSound}
    >
      <div className="flex flex-1 flex-col justify-center">
        <div className="study-card p-7 sm:p-10 rounded-3xl shadow-card">
          {task.task_type === "recognition" && (
            <>
              <div className="flex items-center justify-center gap-2">
                <p className="text-center text-2xl sm:text-3xl font-bold tracking-tight">{task.question_text}</p>
                <button
                  type="button"
                  className="btn btn-ghost p-1.5 rounded-xl text-[var(--text-muted)] hover:text-[var(--text-main)]"
                  aria-label="Озвучить"
                  title="Озвучить [R]"
                  onClick={() => speak(task.question_text ?? "", { rate: prefs?.tts_rate, volume: prefs?.volume })}
                >
                  <Volume2 size={20} aria-hidden />
                </button>
              </div>
              {task.question_context && <p className="mt-2 text-center text-base sm:text-lg text-[var(--text-muted)]">{task.question_context}</p>}
              <MediaList media={task.media_question} />
              <div className="mt-6 grid gap-3">
                {(task.choices ?? []).map((choice, i) => (
                  <button
                    key={choice}
                    className="btn btn-secondary justify-start min-h-[3.5rem] px-5 py-4 text-base sm:text-lg font-medium rounded-2xl hover:translate-x-1 transition-all flex items-center"
                    onClick={() => void choose(choice)}
                    disabled={!!feedback}
                  >
                    <kbd className="mr-3 px-2 py-0.5 rounded-lg bg-[var(--surface-3)] text-xs font-mono font-bold text-[var(--text)]">{i + 1}</kbd>
                    <span>{choice}</span>
                  </button>
                ))}
              </div>
              {!feedback && (
                <div className="mt-4 flex justify-center">
                  <button
                    className="btn btn-ghost text-sm font-medium text-[var(--text-muted)] hover:text-[var(--text)] flex items-center gap-1.5"
                    onClick={() => void answer({ choice: "" }, hintShown)}
                  >
                    <span>{t("dont_know") || "Не знаю"}</span>
                    <kbd className="px-1.5 py-0.5 text-xs font-mono bg-[var(--surface-2)] border border-[var(--border)] rounded">Esc</kbd>
                  </button>
                </div>
              )}
            </>
          )}

          {task.task_type === "written" && (
            <>
              <div className="flex items-center justify-center gap-2">
                <p className="text-center text-2xl sm:text-3xl font-bold tracking-tight">{task.question_text}</p>
                <button
                  type="button"
                  className="btn btn-ghost p-1.5 rounded-xl text-[var(--text-muted)] hover:text-[var(--text-main)]"
                  aria-label="Озвучить"
                  title="Озвучить"
                  onClick={() => speak(task.question_text ?? "", { rate: prefs?.tts_rate, volume: prefs?.volume })}
                >
                  <Volume2 size={20} aria-hidden />
                </button>
              </div>
              {task.question_context && <p className="mt-2 text-center text-base sm:text-lg text-[var(--text-muted)]">{task.question_context}</p>}
              <MediaList media={task.media_question} />
              <input
                ref={writtenInputRef}
                key={task.item_id}
                className="input mt-6 text-center text-xl sm:text-2xl min-h-[3.75rem] py-3 rounded-2xl"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !feedback) {
                    e.preventDefault();
                    e.stopPropagation();
                    void submitText();
                  } else if (e.key === "Escape" && !feedback) {
                    e.preventDefault();
                    e.stopPropagation();
                    void answer({ text: "" }, hintShown);
                  }
                }}
                disabled={!!feedback}
                autoFocus
                aria-label={t("answer")}
              />
              <div className="mt-4 flex justify-center gap-3">
                <button className="btn btn-primary min-h-[3rem] px-8 text-base font-bold rounded-xl flex items-center gap-2" onClick={() => void submitText()} disabled={!text.trim() || !!feedback}>
                  <span>{t("check")}</span>
                  <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-white/25 rounded">Enter</kbd>
                </button>
                <button
                  className="btn btn-secondary min-h-[3rem] px-6 text-base font-bold rounded-xl flex items-center gap-2"
                  onClick={() => void answer({ text: "" }, hintShown)}
                  disabled={!!feedback}
                >
                  <span>{t("dont_know") || "Не знаю"}</span>
                  <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-[var(--surface-2)] border border-[var(--border)] rounded text-[var(--text-muted)]">Esc</kbd>
                </button>
                {task.hint && !hintShown && (
                  <button className="btn btn-ghost min-h-[3rem] px-5 text-base font-semibold rounded-xl flex items-center gap-1.5" onClick={() => setHintShown(true)}>
                    <span>{t("hint")}</span>
                    <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-[var(--surface-2)] border border-[var(--border)] rounded text-[var(--text-muted)]">Ctrl+H</kbd>
                  </button>
                )}
              </div>
              {hintShown && (
                <p className="mt-3 text-center text-base font-medium" style={{ color: "var(--warning)" }}>
                  {task.hint}
                </p>
              )}
            </>
          )}

          {task.task_type === "self_assess" && (
            <>
              <p className="text-center text-base text-[var(--text-muted)] font-medium">Вспомните ответ и оцените себя</p>
              <div className="mt-3 flex items-center justify-center gap-2">
                <p className="text-center text-2xl sm:text-3xl font-bold tracking-tight">{task.question_text}</p>
                <button
                  type="button"
                  className="btn btn-ghost p-1.5 rounded-xl text-[var(--text-muted)] hover:text-[var(--text-main)]"
                  aria-label="Озвучить"
                  title="Озвучить [R]"
                  onClick={() => speak(task.question_text ?? "", { rate: prefs?.tts_rate, volume: prefs?.volume })}
                >
                  <Volume2 size={20} aria-hidden />
                </button>
              </div>
              <MediaList media={task.media_question} />
              {!feedback ? (
                <div className="mt-6 flex justify-center gap-4">
                  <button className="btn btn-secondary min-h-[3.25rem] px-7 text-base font-bold rounded-2xl flex items-center gap-2" onClick={() => void selfAssess(false)}>
                    <span>{t("dont_know")}</span>
                    <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-[var(--surface-2)] border border-[var(--border)] rounded text-[var(--text-muted)]">1 / Esc</kbd>
                  </button>
                  <button
                    className="btn btn-primary min-h-[3.25rem] px-6 text-base font-semibold rounded-2xl flex items-center gap-2 shadow-sm"
                    onClick={async () => {
                      const res = await api<{ correct_text: string }>(`/study-sessions/${sessionId}/items/${task.item_id}/reveal`, { method: "POST" });
                      setFeedback({ correct: false, correct_text: res.correct_text, assisted: true });
                      if (soundOn && res.correct_text) {
                        speak(res.correct_text, { rate: prefs?.tts_rate, volume: prefs?.volume });
                      }
                    }}
                  >
                    <span>{t("show_answer")}</span>
                    <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-white/25 rounded">Пробел</kbd>
                  </button>
                </div>
              ) : (
                <div className="mt-6 text-center">
                  <div className="flex items-center justify-center gap-2 flex-wrap">
                    <p className="text-2xl font-bold">{feedback.correct_text}</p>
                    <button
                      type="button"
                      className="btn btn-ghost p-1.5 text-[var(--accent)] hover:bg-[var(--accent-soft)] rounded-xl"
                      onClick={() => {
                        if (feedback.correct_text) {
                          speak(feedback.correct_text, { rate: prefs?.tts_rate, volume: prefs?.volume });
                        }
                      }}
                      title="Озвучить ответ [R]"
                      aria-label="Озвучить"
                    >
                      <Volume2 size={20} aria-hidden />
                    </button>
                  </div>
                  <p className="mt-4 text-base text-[var(--text-muted)] font-medium">{t("know")}?</p>
                  <div className="mt-3 flex justify-center gap-4">
                    <button className="btn btn-secondary min-h-[3.25rem] px-7 text-base font-bold rounded-2xl flex items-center gap-2 border border-red-200 dark:border-red-900/40 bg-red-50 hover:bg-red-100 text-red-600 dark:bg-red-950/30 dark:hover:bg-red-950/50 dark:text-red-400" onClick={() => void selfAssess(false)}>
                      <span>{t("dont_know")}</span>
                      <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-white/70 dark:bg-black/40 rounded">1 / Esc</kbd>
                    </button>
                    <button className="btn btn-primary min-h-[3.25rem] px-8 text-base font-bold rounded-2xl flex items-center gap-2 border border-emerald-200 dark:border-emerald-900/40 bg-emerald-50 hover:bg-emerald-100 text-emerald-600 dark:bg-emerald-950/30 dark:hover:bg-emerald-950/50 dark:text-emerald-400" onClick={() => void selfAssess(true)}>
                      <span>{t("know")}</span>
                      <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-white/70 dark:bg-black/40 rounded">2</kbd>
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          {feedback && task.task_type !== "self_assess" && <FeedbackBlock feedback={feedback} />}

          {offline && (
            <div role="alert" className="mt-4 rounded-xl p-4 text-base" style={{ background: "var(--warning-soft)" }}>
              {t("save_error_offline")}
              <button
                className="btn btn-secondary mt-3 w-full min-h-[2.85rem] text-base font-semibold rounded-xl"
                onClick={() => (task.task_type === "written" ? void submitText() : undefined)}
              >
                {t("retry")}
              </button>
            </div>
          )}

          {feedback && task.task_type !== "self_assess" && !feedback.mastered && (
            <div className="mt-6 text-center">
              <button className="btn btn-primary min-h-[3.25rem] px-8 text-base font-bold rounded-2xl flex items-center gap-2 mx-auto shadow-md" onClick={() => void fetchNext()}>
                <span>{t("next")}</span>
                <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-white/25 rounded">Enter</kbd>
              </button>
            </div>
          )}
          {feedback && task.task_type !== "self_assess" && feedback.mastered && (
            <p className="mt-5 text-center text-base font-bold" style={{ color: "var(--success)" }}>
              {t("mastered")} ✓
            </p>
          )}

          {/* Keyboard hints footer */}
          <div className="mt-6 hidden sm:flex flex-wrap items-center justify-center gap-2.5 text-xs text-[var(--text-muted)] opacity-75">
            {task.task_type === "recognition" && (
              <>
                <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">1</kbd>–<kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">4</kbd> Выбор</span>
                <span>•</span>
                <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Esc</kbd> Не знаю</span>
                <span>•</span>
              </>
            )}
            {task.task_type === "self_assess" && (
              <>
                <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Пробел</kbd> Ответ</span>
                <span>•</span>
                <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Esc</kbd> / <kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">1</kbd> Не знаю</span>
                <span>•</span>
                <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">2</kbd> Знаю</span>
                <span>•</span>
              </>
            )}
            {task.task_type === "written" && (
              <>
                <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Enter</kbd> Проверить</span>
                <span>•</span>
                <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Esc</kbd> Не знаю</span>
                <span>•</span>
              </>
            )}
            {feedback && !feedback.mastered && (
              <>
                <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Enter</kbd> Далее</span>
                <span>•</span>
              </>
            )}
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">R</kbd> Звук</span>
            <span>•</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Shift+Esc</kbd> Выход</span>
          </div>
        </div>
      </div>
    </StudyChrome>
  );
}

function FeedbackBlock({ feedback }: { feedback: Feedback }) {
  const { prefs } = useApp();
  return (
    <div
      role="status"
      aria-live="polite"
      className="mt-5 rounded-2xl p-5 text-base sm:text-lg"
      style={{
        background: feedback.correct ? "var(--success-soft)" : "var(--danger-soft)",
        color: feedback.correct ? "var(--success)" : "var(--danger)",
      }}
    >
      <div className="font-bold">
        {feedback.correct ? (feedback.assisted ? "Верно (с подсказкой)" : "Верно!") : feedback.possible_typo ? "Возможно, опечатка" : "Неверно"}
      </div>
      {feedback.correct_text && (
        <div className="mt-2 text-[var(--text)] text-base flex items-center justify-between gap-2 flex-wrap">
          <span>
            {feedback.correct ? "Ответ: " : "Правильный ответ: "}
            <strong className="font-bold">{feedback.correct_text}</strong>
          </span>
          <button
            type="button"
            className="btn btn-ghost px-2.5 py-1 text-[var(--accent)] hover:bg-[var(--accent-soft)] rounded-xl flex items-center gap-1.5 text-sm font-semibold shrink-0"
            onClick={() => speak(feedback.correct_text!, { rate: prefs?.tts_rate, volume: prefs?.volume })}
            title="Прослушать ответ"
            aria-label="Прослушать ответ"
          >
            <Volume2 size={18} aria-hidden />
            <span>Прослушать ответ</span>
          </button>
        </div>
      )}
      {feedback.explanation && <div className="mt-2 text-sm text-[var(--text-muted)]">{feedback.explanation}</div>}
    </div>
  );
}

function taskLabel(type: string): string {
  return { recognition: "MC", written: "Written", self_assess: "Self" }[type] ?? type;
}
