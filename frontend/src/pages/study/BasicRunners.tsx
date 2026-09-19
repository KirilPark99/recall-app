import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, Volume2, VolumeX, X } from "lucide-react";
import { api, ApiError } from "../../api/client";
import { useApp } from "../../state/AppContext";
import { speak, stopSpeaking } from "../../lib/tts";
import { cardsLabel } from "../../i18n";
import type { Feedback, SessionDto, TaskDto } from "./types";
import { useStudySound } from "./useStudySound";

function chunkTasks<T>(array: T[], size: number): T[][] {
  const chunks: T[][] = [];
  const s = Math.max(1, size);
  for (let i = 0; i < array.length; i += s) {
    chunks.push(array.slice(i, i + s));
  }
  return chunks.length > 0 ? chunks : [[]];
}

export function useSubmitAnswer(sessionId: string) {
  return useCallback(
    async (taskId: string, answer: Record<string, unknown>): Promise<{ feedback: Feedback; error: ApiError | null }> => {
      const eventId = crypto.randomUUID();
      try {
        const feedback = await api<Feedback>(`/study-sessions/${sessionId}/answers`, {
          body: { item_id: taskId, client_event_id: eventId, answer },
        });
        return { feedback, error: null };
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          return { feedback: { correct: false }, error: e };
        }
        return { feedback: { correct: false }, error: e as ApiError };
      }
    },
    [sessionId]
  );
}

export interface StudyStageInfo {
  current?: number;
  total?: number;
  batchIndex?: number;
  totalBatches?: number;
  round?: number;
  modeLabel?: string;
}

export function StudyChrome({
  children,
  onExit,
  progress,
  stageInfo,
  extra,
  soundOn,
  onToggleSound,
}: {
  children: React.ReactNode;
  onExit: () => void;
  progress?: string;
  stageInfo?: StudyStageInfo;
  extra?: React.ReactNode;
  soundOn?: boolean;
  onToggleSound?: () => void;
}) {
  const match = progress ? progress.match(/(\d+)\s*\/\s*(\d+)/) : null;
  const matchCur = match && match[1] ? parseInt(match[1], 10) : null;
  const matchTot = match && match[2] ? parseInt(match[2], 10) : null;
  const pct =
    stageInfo?.current !== undefined && stageInfo?.total !== undefined && stageInfo.total > 0
      ? Math.min(100, Math.max(0, Math.round((stageInfo.current / stageInfo.total) * 100)))
      : matchCur !== null && matchTot !== null && matchTot > 0
      ? Math.min(100, Math.max(0, Math.round((matchCur / matchTot) * 100)))
      : null;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.shiftKey && e.key === "Escape") || (e.altKey && (e.key === "q" || e.key === "Q" || e.key === "й" || e.key === "Й"))) {
        e.preventDefault();
        onExit();
      } else if (
        (e.key === "m" || e.key === "M" || e.key === "ь" || e.key === "Ь") &&
        !(e.target as HTMLElement)?.tagName?.match(/INPUT|TEXTAREA|SELECT/)
      ) {
        onToggleSound?.();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onExit, onToggleSound]);

  return (
    <div className="mx-auto flex min-h-screen max-w-4xl flex-col px-4 py-4 sm:px-8 sm:py-6">
      {/* Top progress bar */}
      {pct !== null && (
        <div className="w-full bg-[var(--surface-3)] h-1.5 rounded-full overflow-hidden mb-4">
          <div
            className="h-full bg-[var(--accent)] transition-all duration-300 ease-out rounded-full"
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      {/* Header bar */}
      <div className="mb-6 flex items-center justify-between gap-3 border-b border-[var(--border)] pb-4">
        <button
          className="btn btn-ghost rounded-full p-2.5 text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors"
          onClick={onExit}
          title="Выйти из занятия [Shift+Esc]"
          aria-label="Выйти из занятия"
        >
          <X size={22} aria-hidden />
        </button>

        {/* Center stage & progress information */}
        <div className="flex flex-col items-center justify-center gap-1 text-center">
          {stageInfo ? (
            <>
              <div className="flex items-center gap-1.5 flex-wrap justify-center">
                {stageInfo.totalBatches !== undefined && stageInfo.totalBatches > 1 && (
                  <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-[var(--surface-2)] text-[var(--text-muted)] border border-[var(--border)]">
                    Порция {(stageInfo.batchIndex ?? 0) + 1} из {stageInfo.totalBatches}
                  </span>
                )}
                {stageInfo.round !== undefined && stageInfo.round > 1 && (
                  <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                    Круг {stageInfo.round}
                  </span>
                )}
                {stageInfo.modeLabel && (
                  <span className="text-xs font-medium text-[var(--text-muted)]">
                    {stageInfo.modeLabel}
                  </span>
                )}
              </div>
              {stageInfo.current !== undefined && stageInfo.total !== undefined && (
                <div className="text-base sm:text-lg font-black tracking-tight text-[var(--text)] leading-none">
                  {stageInfo.current} <span className="font-normal text-[var(--text-muted)] text-sm sm:text-base">/</span> {stageInfo.total}
                </div>
              )}
            </>
          ) : (
            <span className="badge badge-accent py-1 px-3.5 text-sm sm:text-base font-bold">
              {progress}
            </span>
          )}
        </div>

        {/* Right action controls */}
        <div className="flex items-center gap-2">
          {onToggleSound !== undefined && (
            <button
              type="button"
              className={`btn btn-ghost rounded-full p-2.5 transition-all ${
                soundOn
                  ? "text-[var(--accent)] bg-[var(--accent-soft)] hover:bg-[var(--accent-soft)] shadow-sm"
                  : "text-[var(--text-muted)] hover:bg-[var(--surface-2)]"
              }`}
              onClick={onToggleSound}
              title={soundOn ? "Автоозвучка включена (нажмите, чтобы выключить)" : "Автоозвучка выключена (нажмите, чтобы включить)"}
              aria-label={soundOn ? "Выключить озвучку" : "Включить озвучку"}
              aria-pressed={soundOn}
            >
              {soundOn ? <Volume2 size={22} aria-hidden /> : <VolumeX size={22} aria-hidden />}
            </button>
          )}
          {extra}
        </div>
      </div>
      <div className="flex flex-1 flex-col">{children}</div>
    </div>
  );
}

export function MediaList({ media }: { media: Array<{ id: string; mime_type: string; description: string }> }) {
  if (!media.length) return null;
  return (
    <div className="mt-3 flex flex-wrap justify-center gap-2">
      {media.map((m) =>
        m.mime_type.startsWith("image/") ? (
          <img key={m.id} src={`/api/v1/media/${m.id}`} alt={m.description || "изображение"} className="max-h-48 rounded-lg border" />
        ) : (
          <audio key={m.id} controls src={`/api/v1/media/${m.id}`} className="max-w-full" />
        )
      )}
    </div>
  );
}

export function FeedbackPanel({ feedback }: { feedback: Feedback }) {
  const { prefs } = useApp();
  return (
    <div
      role="status"
      aria-live="polite"
      className="mt-4 rounded-2xl p-4 sm:p-5"
      style={{
        background: feedback.correct ? "var(--success-soft)" : "var(--danger-soft)",
        color: feedback.correct ? "var(--success)" : "var(--danger)",
      }}
    >
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="font-bold text-base sm:text-lg">
          {feedback.correct ? (feedback.assisted ? "Верно (с подсказкой)" : "Верно!") : feedback.possible_typo ? "Возможно, опечатка" : "Неверно"}
        </div>
        {feedback.correct_text && (
          <button
            type="button"
            className="btn btn-ghost px-2.5 py-1 text-[var(--accent)] hover:bg-[var(--accent-soft)] rounded-xl flex items-center gap-1.5 text-sm font-semibold"
            onClick={() => speak(feedback.correct_text!, { rate: prefs?.tts_rate, volume: prefs?.volume })}
            title="Прослушать ответ"
            aria-label="Прослушать ответ"
          >
            <Volume2 size={18} aria-hidden />
            <span>Прослушать ответ</span>
          </button>
        )}
      </div>
      {feedback.correct_text && (
        <div className="mt-2 text-[var(--text)] text-base flex items-center gap-2 flex-wrap">
          <span>
            {feedback.correct ? "Ответ: " : "Правильный ответ: "}
            <strong className="font-bold">{feedback.correct_text}</strong>
            {feedback.answer_context ? ` (${feedback.answer_context})` : ""}
          </span>
        </div>
      )}
      {feedback.explanation && <div className="mt-2 text-sm text-[var(--text-muted)]">{feedback.explanation}</div>}
      {feedback.example && <div className="mt-1 text-sm italic text-[var(--text-muted)]">{feedback.example}</div>}
    </div>
  );
}

/* ---------- Карточки / Письменный ответ / Диктант ---------- */

export function CardsRunner({ session }: { session: SessionDto }) {
  const { t, prefs, locale } = useApp();
  const navigate = useNavigate();
  const tasks = session.tasks ?? [];

  const batchSize = Math.max(1, (session.settings?.batch_size as number) || prefs?.batch_size || 7);
  const batches = useMemo(() => chunkTasks(tasks, batchSize), [tasks, batchSize]);

  const [batchIndex, setBatchIndex] = useState(0);
  const [round, setRound] = useState(1);
  const [currentQueue, setCurrentQueue] = useState<TaskDto[]>(() => batches[0] ?? []);
  const [missedInRound, setMissedInRound] = useState<TaskDto[]>([]);
  const [queueIndex, setQueueIndex] = useState(0);
  const [batchCompleted, setBatchCompleted] = useState(false);

  const [flipped, setFlipped] = useState(false);
  const [revealed, setRevealed] = useState<{ text: string; media: TaskDto["media_answer"] } | null>(null);
  const [knownCount, setKnownCount] = useState(0);
  const [answered, setAnswered] = useState(0);
  const [busy, setBusy] = useState(false);
  const { soundOn, toggleSound } = useStudySound(session.settings?.auto_tts);
  const submit = useSubmitAnswer(session.id);
  const task = currentQueue[queueIndex];

  const speakIfEnabled = useCallback(
    (text: string, lang?: string) => {
      if (soundOn && text) {
        speak(text, { lang, rate: prefs?.tts_rate, volume: prefs?.volume });
      }
    },
    [soundOn, prefs]
  );

  useEffect(() => {
    setFlipped(false);
    setRevealed(null);
    if (task) speakIfEnabled(task.question_text ?? "", task.language ?? "");
    return () => stopSpeaking();
  }, [queueIndex, currentQueue, task]); // eslint-disable-line react-hooks/exhaustive-deps

  const flip = async () => {
    if (flipped || !task) return;
    setFlipped(true);
    try {
      const res = await api<{ correct_text: string }>(`/study-sessions/${session.id}/items/${task.item_id}/reveal`, { method: "POST" });
      setRevealed({ text: res.correct_text, media: task.media_answer });
      if (soundOn && res.correct_text) {
        speak(res.correct_text, { rate: prefs?.tts_rate, volume: prefs?.volume });
      }
    } catch {
      setRevealed({ text: "", media: [] });
    }
  };

  const isFinishedRef = useRef(false);
  const isTransitioningRef = useRef(false);
  const busyRef = useRef(false);

  const finish = useCallback(async () => {
    if (isFinishedRef.current) return;
    isFinishedRef.current = true;
    try {
      await api(`/study-sessions/${session.id}/complete`, { method: "POST" });
    } catch {
      /* already completed */
    }
    navigate(`/study/${session.id}/result`, { replace: true });
  }, [session.id, navigate]);

  const grade = async (known: boolean) => {
    if (busyRef.current || busy || !task) return;
    busyRef.current = true;
    setBusy(true);
    try {
      const { error } = await submit(task.item_id, { known });
      if (error) return; // offline: остаёмся на карточке
      setAnswered((a) => a + 1);
      if (known) setKnownCount((k) => k + 1);

      const rawNextMissed = !known
        ? (missedInRound.some((m) => m.item_id === task.item_id) ? missedInRound : [...missedInRound, task])
        : missedInRound.filter((m) => m.item_id !== task.item_id);
      const nextMissed = Array.from(new Map(rawNextMissed.map((m) => [m.item_id, m])).values());

      if (queueIndex + 1 < currentQueue.length) {
        setMissedInRound(nextMissed);
        setQueueIndex((i) => i + 1);
      } else {
        // Конец текущего круга!
        if (nextMissed.length > 0) {
          // Есть карточки с ошибками — идём на следующий круг этой порции!
          setRound((r) => r + 1);
          setCurrentQueue(nextMissed);
          setMissedInRound([]);
          setQueueIndex(0);
        } else {
          // Все карточки в этой порции отвечены верно!
          setFlipped(false);
          setRevealed(null);
          if (batchIndex + 1 < batches.length) {
            setBatchCompleted(true);
          } else {
            // Все порции завершены!
            await finish();
          }
        }
      }
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const nextBatch = useCallback(() => {
    if (isTransitioningRef.current) return;
    isTransitioningRef.current = true;
    setTimeout(() => {
      isTransitioningRef.current = false;
    }, 250);

    const nextB = batchIndex + 1;
    if (nextB >= batches.length) {
      void finish();
      return;
    }
    setFlipped(false);
    setRevealed(null);
    setBatchIndex(nextB);
    setRound(1);
    setCurrentQueue(batches[nextB] ?? []);
    setMissedInRound([]);
    setQueueIndex(0);
    setBatchCompleted(false);
  }, [batchIndex, batches, finish]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName?.match(/INPUT|TEXTAREA|SELECT/)) return;
      if (batchCompleted) {
        if (!e.repeat && (e.code === "Space" || e.key === "Enter")) {
          e.preventDefault();
          nextBatch();
        }
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        if (!flipped) {
          void flip();
        } else if (!busy) {
          void grade(false);
        }
      } else if (e.code === "Space" || e.code === "ArrowDown" || e.code === "ArrowUp") {
        e.preventDefault();
        if (task) void flip();
      } else if (e.code === "ArrowRight") {
        setQueueIndex((i) => Math.min(i + 1, currentQueue.length - 1));
      } else if (e.code === "ArrowLeft") {
        setQueueIndex((i) => Math.max(i - 1, 0));
      } else if (flipped && !busy) {
        if (e.key === "1" || e.code === "Digit1") {
          void grade(false);
        } else if (e.key === "2" || e.code === "Digit2") {
          void grade(true);
        }
      } else if (e.key === "s" || e.key === "S" || e.key === "ы" || e.key === "Ы" || e.key === "f" || e.key === "F") {
        if (task) {
          void api(`/cards/${task.card_id}/star`, { method: "PUT", body: { enabled: true } });
        }
      } else if (e.key === "r" || e.key === "R" || e.key === "к" || e.key === "К" || e.key === "a" || e.key === "A") {
        const textToSpeak = flipped ? (revealed?.text ?? "") : (task?.question_text ?? "");
        if (textToSpeak) {
          speak(textToSpeak, { rate: prefs?.tts_rate, volume: prefs?.volume });
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [task, flipped, busy, currentQueue, batchCompleted, revealed, prefs, nextBatch]);

  if (batchCompleted) {
    return (
      <StudyChrome
        onExit={() => void finish()}
        stageInfo={{
          current: batches[batchIndex]?.length ?? 0,
          total: batches[batchIndex]?.length ?? 0,
          batchIndex,
          totalBatches: batches.length,
        }}
      >
        <div className="flex flex-1 flex-col items-center justify-center">
          <div className="study-card w-full max-w-md p-8 text-center rounded-3xl shadow-card">
            <h2 className="text-2xl font-bold mb-2">🎉 {t("batch_congrats")}</h2>
            <p className="text-sm text-[var(--text-muted)] mb-6">
              {t("batch_header")} {batchIndex + 1} из {batches.length} ({batches[batchIndex]?.length} слов) полностью освоен.
            </p>
            <button
              type="button"
              className="btn btn-primary w-full py-3 text-base rounded-2xl shadow-md"
              onClick={nextBatch}
            >
              {t("next_batch_btn")} ({cardsLabel(locale, batches[batchIndex + 1]?.length ?? 0)}) →
            </button>
          </div>
        </div>
      </StudyChrome>
    );
  }

  if (!task) {
    if (batches.length === 0 || batchIndex >= batches.length) {
      void finish();
      return null;
    }
    return (
      <StudyChrome onExit={() => void finish()}>
        <div className="flex flex-1 flex-col items-center justify-center p-8 gap-4">
          <div className="skeleton w-full max-w-md h-64 rounded-3xl" />
          <button
            type="button"
            className="btn btn-secondary rounded-xl px-6 py-2"
            onClick={() => {
              if (batches[batchIndex]?.length) {
                setCurrentQueue(batches[batchIndex]);
                setQueueIndex(0);
              } else {
                void finish();
              }
            }}
          >
            Продолжить
          </button>
        </div>
      </StudyChrome>
    );
  }

  return (
    <StudyChrome
      onExit={async () => {
        await finish();
      }}
      stageInfo={{
        current: queueIndex + 1,
        total: currentQueue.length,
        batchIndex,
        totalBatches: batches.length,
        round,
      }}
      soundOn={soundOn}
      onToggleSound={toggleSound}
      extra={
        <button
          className="btn btn-ghost rounded-full p-2.5 text-amber-500 hover:bg-[var(--surface-2)]"
          aria-label={t("favorite")}
          title="Добавить в избранное"
          onClick={() => void api(`/cards/${task.card_id}/star`, { method: "PUT", body: { enabled: true } })}
        >
          ★
        </button>
      }
    >
      <div className="flex flex-1 flex-col items-center justify-center">
        <div
          className="study-card w-full max-w-2xl cursor-pointer p-8 sm:p-12 md:p-14 text-center min-h-[340px] md:min-h-[400px] flex flex-col items-center justify-center transition-all hover:border-[var(--border-hover)] hover:shadow-xl rounded-3xl relative select-none"
          onClick={() => void flip()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => e.code === "Space" && e.preventDefault()}
          aria-live="polite"
        >
          {!flipped ? (
            <>
              <div className="mb-4 inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-[var(--surface-2)] text-[var(--text-muted)] border border-[var(--border)]">
                <span>{t("question") || "Вопрос"}</span>
              </div>
              <p className="text-2xl sm:text-3xl md:text-4xl font-bold tracking-tight text-[var(--text)] leading-snug">{task.question_text}</p>
              {task.question_context && <p className="mt-4 text-base text-[var(--text-muted)]">{task.question_context}</p>}
              <MediaList media={task.media_question} />
              <p className="mt-6 text-xs text-[var(--text-muted)] font-medium select-none">
                {t("space_hint") || "Нажмите на карточку или Пробел"}
              </p>
            </>
          ) : (
            <>
              <div className="mb-4 inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-[var(--accent-soft)] text-[var(--accent)] border border-[var(--accent)]/30">
                <span>{t("answer") || "Ответ"}</span>
              </div>
              <div className="flex items-center justify-center gap-3">
                <p className="text-2xl sm:text-3xl md:text-4xl font-bold tracking-tight text-[var(--accent)] leading-snug">
                  {revealed?.text || "…"}
                </p>
                {revealed?.text && (
                  <button
                    type="button"
                    className="btn btn-ghost p-2 text-[var(--accent)] hover:bg-[var(--accent-soft)] rounded-full shrink-0"
                    onClick={(e) => {
                      e.stopPropagation();
                      speak(revealed.text, { rate: prefs?.tts_rate, volume: prefs?.volume });
                    }}
                    title="Прослушать ответ"
                    aria-label="Прослушать ответ"
                  >
                    <Volume2 size={26} aria-hidden />
                  </button>
                )}
              </div>
              <MediaList media={revealed?.media ?? []} />
            </>
          )}
        </div>

        <div className="mt-6 flex items-center justify-center gap-3">
          <button
            className="btn btn-secondary rounded-2xl px-3.5 min-h-[3rem] text-[var(--text-muted)] hover:text-[var(--text)]"
            onClick={() => setQueueIndex((i) => Math.max(0, i - 1))}
            disabled={queueIndex === 0}
            aria-label="Назад"
          >
            <ArrowLeft size={18} aria-hidden />
          </button>
          <button
            className="btn btn-secondary rounded-2xl px-6 min-h-[3rem] text-base font-semibold shadow-sm hover:border-[var(--border-hover)] flex items-center gap-2"
            onClick={() => void flip()}
          >
            <span>{flipped ? (t("question") || "Вопрос") : t("flip")}</span>
            <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-[var(--surface-2)] border border-[var(--border)] rounded text-[var(--text-muted)]">Пробел</kbd>
          </button>
          <button
            className="btn btn-ghost rounded-2xl px-3 min-h-[3rem] text-[var(--text-muted)] hover:text-[var(--text)]"
            aria-label="Озвучить"
            title={flipped ? "Озвучить ответ" : "Озвучить вопрос"}
            onClick={() => {
              const textToSpeak = flipped ? (revealed?.text ?? "") : (task.question_text ?? "");
              if (textToSpeak) {
                speak(textToSpeak, { rate: prefs?.tts_rate, volume: prefs?.volume });
              }
            }}
          >
            <Volume2 size={18} aria-hidden />
          </button>
          <button
            className="btn btn-secondary rounded-2xl px-3.5 min-h-[3rem] text-[var(--text-muted)] hover:text-[var(--text)]"
            onClick={() => setQueueIndex((i) => Math.min(currentQueue.length - 1, i + 1))}
            disabled={queueIndex === currentQueue.length - 1}
            aria-label="Вперёд"
          >
            <ArrowRight size={18} aria-hidden />
          </button>
        </div>

        {flipped && (
          <div className="mt-5 flex items-center justify-center gap-4 w-full max-w-md">
            <button
              className="btn flex-1 min-h-[3.5rem] rounded-2xl text-base font-bold transition-all shadow-sm flex items-center justify-center gap-2 border border-red-200 dark:border-red-900/40 bg-red-50 hover:bg-red-100 text-red-600 dark:bg-red-950/30 dark:hover:bg-red-950/50 dark:text-red-400"
              disabled={busy}
              onClick={() => void grade(false)}
            >
              <span>{t("dont_know")}</span>
              <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-white/70 dark:bg-black/40 rounded">1 / Esc</kbd>
            </button>
            <button
              className="btn flex-1 min-h-[3.5rem] rounded-2xl text-base font-bold transition-all shadow-sm flex items-center justify-center gap-2 border border-emerald-200 dark:border-emerald-900/40 bg-emerald-50 hover:bg-emerald-100 text-emerald-600 dark:bg-emerald-950/30 dark:hover:bg-emerald-950/50 dark:text-emerald-400"
              disabled={busy}
              onClick={() => void grade(true)}
            >
              <span>{t("know")}</span>
              <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-white/70 dark:bg-black/40 rounded">2</kbd>
            </button>
          </div>
        )}

        <div className="mt-6 flex items-center gap-3 sm:gap-4 text-xs sm:text-sm font-medium text-[var(--text-muted)]">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
            {t("know")}: <strong className="text-[var(--text)]">{knownCount}</strong>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-400"></span>
            {t("dont_know")}: <strong className="text-[var(--text)]">{answered - knownCount}</strong>
          </span>
          <span className="text-[var(--border)]">•</span>
          <span>{answered} {t("count_graded")}</span>
        </div>

        {/* Keyboard hints footer */}
        <div className="mt-5 hidden sm:flex flex-wrap items-center justify-center gap-2.5 text-xs text-[var(--text-muted)] opacity-75">
          <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Пробел</kbd> / <kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">↓</kbd> Перевернуть</span>
          <span>•</span>
          <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">←</kbd> <kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">→</kbd> Навигация</span>
          <span>•</span>
          <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Esc</kbd> / <kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">1</kbd> Не знаю</span>
          <span>•</span>
          <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">2</kbd> Знаю</span>
          <span>•</span>
          <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">R</kbd> Звук</span>
          <span>•</span>
          <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">S</kbd> ★</span>
          <span>•</span>
          <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Shift+Esc</kbd> Выход</span>
        </div>
      </div>
    </StudyChrome>
  );
}

export function WriteRunner({ session, spell }: { session: SessionDto; spell: boolean }) {
  const { t, prefs, locale } = useApp();
  const navigate = useNavigate();
  const tasks = session.tasks ?? [];

  const batchSize = Math.max(1, (session.settings?.batch_size as number) || prefs?.batch_size || 7);
  const batches = useMemo(() => chunkTasks(tasks, batchSize), [tasks, batchSize]);

  const [batchIndex, setBatchIndex] = useState(0);
  const [round, setRound] = useState(1);
  const [currentQueue, setCurrentQueue] = useState<TaskDto[]>(() => batches[0] ?? []);
  const [missedInRound, setMissedInRound] = useState<TaskDto[]>([]);
  const [queueIndex, setQueueIndex] = useState(0);
  const [batchCompleted, setBatchCompleted] = useState(false);

  const [text, setText] = useState("");
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [corrected, setCorrected] = useState(false);
  const [offlineAnswer, setOfflineAnswer] = useState<string | null>(null);
  const [hintShown, setHintShown] = useState(false);
  const [ttsRate, setTtsRate] = useState(prefs?.tts_rate ?? 1);
  const inputRef = useRef<HTMLInputElement>(null);
  const { soundOn, toggleSound } = useStudySound(session.settings?.auto_tts);
  const submit = useSubmitAnswer(session.id);
  const task = currentQueue[queueIndex];

  useEffect(() => {
    setText("");
    setFeedback(null);
    setHintShown(false);
    setOfflineAnswer(null);
    setCorrected(false);
    if (task && (spell || soundOn)) {
      const textToPlay = spell ? (task.tts_text ?? "") : (task.question_text ?? "");
      if (textToPlay) {
        speak(textToPlay, {
          lang: task.language ?? undefined,
          rate: ttsRate,
          volume: prefs?.volume,
        });
      }
      return () => stopSpeaking();
    }
  }, [queueIndex, currentQueue, task, soundOn, ttsRate]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-focus input when a new question is loaded or feedback cleared
  useEffect(() => {
    if (!feedback && !batchCompleted) {
      const focusInput = () => {
        inputRef.current?.focus();
      };
      focusInput();
      const raf = requestAnimationFrame(focusInput);
      const timer = setTimeout(focusInput, 50);
      return () => {
        cancelAnimationFrame(raf);
        clearTimeout(timer);
      };
    }
  }, [queueIndex, feedback, batchCompleted, task?.item_id]);

  // Route any typed letter directly into input so user never has to click with mouse
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!feedback && !batchCompleted && inputRef.current && document.activeElement !== inputRef.current) {
        if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
          inputRef.current.focus();
        }
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [feedback, batchCompleted]);

  const isFinishedRef = useRef(false);
  const isTransitioningRef = useRef(false);
  const busyRef = useRef(false);

  const finish = useCallback(async () => {
    if (isFinishedRef.current) return;
    isFinishedRef.current = true;
    try {
      await api(`/study-sessions/${session.id}/complete`, { method: "POST" });
    } catch { /* noop */ }
    navigate(`/study/${session.id}/result`, { replace: true });
  }, [session.id, navigate]);

  const nextBatch = useCallback(() => {
    if (isFinishedRef.current) return;
    if (isTransitioningRef.current) return;
    isTransitioningRef.current = true;
    setTimeout(() => {
      isTransitioningRef.current = false;
    }, 200);

    const nextB = batchIndex + 1;
    if (nextB >= batches.length) {
      void finish();
      return;
    }
    setText("");
    setFeedback(null);
    setHintShown(false);
    setOfflineAnswer(null);
    setCorrected(false);
    setBatchIndex(nextB);
    setRound(1);
    setCurrentQueue(batches[nextB] ?? []);
    setMissedInRound([]);
    setQueueIndex(0);
    setBatchCompleted(false);
  }, [batchIndex, batches, finish]);

  const check = useCallback(async () => {
    if (!task || busyRef.current || isTransitioningRef.current || isFinishedRef.current) return;
    busyRef.current = true;
    try {
      const answerText = text;
      const { feedback: fb, error } = await submit(task.item_id, { text: answerText });
      if (error && error.status !== 409) {
        setOfflineAnswer(answerText);
        return;
      }
      setOfflineAnswer(null);
      setFeedback(fb);
      if (!fb.correct) {
        setMissedInRound((prev) => prev.some((m) => m.item_id === task.item_id) ? prev : [...prev, task]);
      }
      const ansToPlay = fb.correct_text || answerText;
      if (soundOn && ansToPlay) {
        speak(ansToPlay, { rate: prefs?.tts_rate, volume: prefs?.volume });
      }
    } finally {
      busyRef.current = false;
    }
  }, [task, text, submit, soundOn, prefs]);

  const next = useCallback(async () => {
    if (isFinishedRef.current) return;
    if (isTransitioningRef.current) return;
    isTransitioningRef.current = true;
    setTimeout(() => {
      isTransitioningRef.current = false;
    }, 200);

    const wasCorrect = (feedback?.correct || corrected);
    const rawNextMissed = !task
      ? missedInRound
      : !wasCorrect
      ? (missedInRound.some((m) => m.item_id === task.item_id) ? missedInRound : [...missedInRound, task])
      : missedInRound.filter((m) => m.item_id !== task.item_id);

    // Strictly ensure no duplicates by item_id
    const nextMissed = Array.from(new Map(rawNextMissed.map((m) => [m.item_id, m])).values());

    if (queueIndex + 1 < currentQueue.length) {
      setText("");
      setFeedback(null);
      setHintShown(false);
      setOfflineAnswer(null);
      setCorrected(false);
      setMissedInRound(nextMissed);
      setQueueIndex((i) => i + 1);
    } else {
      // Конец текущего круга!
      if (nextMissed.length > 0) {
        setText("");
        setFeedback(null);
        setHintShown(false);
        setOfflineAnswer(null);
        setCorrected(false);
        setRound((r) => r + 1);
        setCurrentQueue(nextMissed);
        setMissedInRound([]);
        setQueueIndex(0);
      } else {
        // Все слова в этой порции отвечены верно!
        if (batchIndex + 1 < batches.length) {
          setText("");
          setFeedback(null);
          setHintShown(false);
          setOfflineAnswer(null);
          setCorrected(false);
          setBatchCompleted(true);
        } else {
          void finish();
        }
      }
    }
  }, [feedback, corrected, task, missedInRound, queueIndex, currentQueue.length, batchIndex, batches.length, finish]);

  const dontKnow = useCallback(async () => {
    if (!task || busyRef.current || isTransitioningRef.current || isFinishedRef.current) return;
    busyRef.current = true;
    try {
      const { feedback: fb } = await submit(task.item_id, { text: "", used_hint: hintShown });
      const res = await api<{ correct_text: string }>(`/study-sessions/${session.id}/items/${task.item_id}/reveal`, { method: "POST" }).catch(() => undefined);
      const correctText = fb.correct_text || res?.correct_text || "";
      setFeedback({ ...fb, correct: false, correct_text: correctText });
      setMissedInRound((prev) => prev.some((m) => m.item_id === task.item_id) ? prev : [...prev, task]);
      if (soundOn && correctText) {
        speak(correctText, { rate: prefs?.tts_rate, volume: prefs?.volume });
      }
    } finally {
      busyRef.current = false;
    }
  }, [task, submit, hintShown, session.id, soundOn, prefs]);

  const markCorrect = useCallback(async () => {
    if (!feedback || !feedback.answer_id || !task) return;
    try {
      await api(`/study-sessions/${session.id}/answers/${feedback.answer_id}/correction`, {
        method: "POST",
        body: { final_correct: true },
      });
      setCorrected(true);
      setFeedback((prev) => (prev ? { ...prev, correct: true } : null));
      setMissedInRound((prev) => prev.filter((m) => m.item_id !== task.item_id));
    } catch {
      /* repeat */
    }
  }, [feedback, task, session.id]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (batchCompleted) {
        if (!e.repeat && (e.code === "Space" || e.key === "Enter")) {
          e.preventDefault();
          nextBatch();
        }
        return;
      }
      if (feedback) {
        if (!e.repeat && (e.key === "Enter" || e.code === "Space")) {
          e.preventDefault();
          void next();
        } else if ((e.key === "c" || e.key === "C" || e.key === "с" || e.key === "С") && !feedback.correct && !corrected && feedback.answer_id) {
          e.preventDefault();
          void markCorrect();
        } else if (e.key === "r" || e.key === "R" || e.key === "к" || e.key === "К") {
          e.preventDefault();
          const ansToPlay = feedback.correct_text || text;
          if (ansToPlay) {
            speak(ansToPlay, { rate: prefs?.tts_rate, volume: prefs?.volume });
          }
        }
      } else {
        const isInput = (e.target as HTMLElement)?.tagName?.match(/INPUT|TEXTAREA|SELECT/);
        if (isInput) {
          // Input element handles typing, Enter, and Escape directly via onKeyDown
          if ((e.ctrlKey || e.metaKey) && (e.key === "h" || e.key === "H" || e.key === "р" || e.key === "Р")) {
            e.preventDefault();
            if (task?.hint && !hintShown) setHintShown(true);
          } else if ((e.ctrlKey || e.altKey) && (e.key === "r" || e.key === "R")) {
            e.preventDefault();
            const qText = task?.question_text || task?.tts_text || "";
            if (qText) {
              speak(qText, { lang: task?.language ?? undefined, rate: prefs?.tts_rate, volume: prefs?.volume });
            }
          }
          return;
        }

        if (!e.repeat && (e.key === "Escape" || ((e.ctrlKey || e.metaKey) && e.key === "Enter"))) {
          e.preventDefault();
          void dontKnow();
        } else if (!e.repeat && e.key === "Enter" && document.activeElement !== inputRef.current) {
          e.preventDefault();
          if (text.trim()) {
            void check();
          } else {
            inputRef.current?.focus();
          }
        } else if ((e.ctrlKey || e.metaKey) && (e.key === "h" || e.key === "H" || e.key === "р" || e.key === "Р")) {
          e.preventDefault();
          if (task?.hint && !hintShown) setHintShown(true);
        } else if ((e.ctrlKey || e.altKey) && (e.key === "r" || e.key === "R" || e.code === "Space")) {
          e.preventDefault();
          const qText = task?.question_text || task?.tts_text || "";
          if (qText) {
            speak(qText, { lang: task?.language ?? undefined, rate: prefs?.tts_rate, volume: prefs?.volume });
          }
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [batchCompleted, feedback, corrected, nextBatch, next, markCorrect, dontKnow, check, text, hintShown, task, prefs]);

  if (batchCompleted) {
    return (
      <StudyChrome
        onExit={() => void finish()}
        stageInfo={{
          current: batches[batchIndex]?.length ?? 0,
          total: batches[batchIndex]?.length ?? 0,
          batchIndex,
          totalBatches: batches.length,
          modeLabel: spell ? (t("mode_spell") || "Диктант") : (t("mode_write") || "Письменный ответ"),
        }}
      >
        <div className="flex flex-1 flex-col items-center justify-center">
          <div className="study-card w-full max-w-md p-8 text-center rounded-3xl shadow-card">
            <h2 className="text-2xl font-bold mb-2">🎉 {t("batch_congrats")}</h2>
            <p className="text-sm text-[var(--text-muted)] mb-6">
              {t("batch_header")} {batchIndex + 1} из {batches.length} ({batches[batchIndex]?.length} слов) полностью освоен.
            </p>
            <button
              type="button"
              className="btn btn-primary w-full py-3 text-base rounded-2xl shadow-md"
              onClick={nextBatch}
            >
              {t("next_batch_btn")} ({cardsLabel(locale, batches[batchIndex + 1]?.length ?? 0)}) →
            </button>
          </div>
        </div>
      </StudyChrome>
    );
  }

  if (!task) {
    if (batches.length === 0 || batchIndex >= batches.length) {
      void finish();
      return null;
    }
    return (
      <StudyChrome onExit={() => void finish()}>
        <div className="flex flex-1 flex-col items-center justify-center p-8 gap-4">
          <div className="skeleton w-full max-w-md h-64 rounded-3xl" />
          <button
            type="button"
            className="btn btn-secondary rounded-xl px-6 py-2"
            onClick={() => {
              if (batches[batchIndex]?.length) {
                setCurrentQueue(batches[batchIndex]);
                setQueueIndex(0);
              } else {
                void finish();
              }
            }}
          >
            Продолжить
          </button>
        </div>
      </StudyChrome>
    );
  }

  const hasUploadedAudio = task ? task.media_answer.some((m) => !m.mime_type.startsWith("image/")) : false;

  return (
    <StudyChrome
      onExit={() => void finish()}
      stageInfo={{
        current: queueIndex + 1,
        total: currentQueue.length,
        batchIndex,
        totalBatches: batches.length,
        round,
        modeLabel: spell ? (t("mode_spell") || "Диктант") : (t("mode_write") || "Письменный ответ"),
      }}
      soundOn={soundOn}
      onToggleSound={toggleSound}
      extra={spell ? <SpellRateControl rate={ttsRate} onChange={setTtsRate} /> : undefined}
    >
      <div className="flex flex-1 flex-col justify-center">
        <div
          className="study-card p-8 sm:p-12 text-center max-w-2xl mx-auto w-full rounded-3xl shadow-card cursor-text"
          onClick={() => !feedback && inputRef.current?.focus()}
        >
          <div className="mb-4 inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-[var(--surface-2)] text-[var(--text-muted)] border border-[var(--border)]">
            <span>{spell ? (t("mode_spell") || "Диктант") : (t("question") || "Вопрос")}</span>
          </div>
          {!spell ? (
            <>
              <div className="flex items-center justify-center gap-3">
                <p className="text-2xl sm:text-3xl font-bold tracking-tight text-[var(--text)] leading-snug">{task.question_text}</p>
                <button
                  type="button"
                  className="btn btn-ghost p-2 text-[var(--accent)] hover:bg-[var(--accent-soft)] rounded-xl shrink-0"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (task.question_text) {
                      speak(task.question_text, { lang: task.language ?? undefined, rate: ttsRate, volume: prefs?.volume });
                    }
                  }}
                  title="Озвучить вопрос [Alt+R]"
                  aria-label="Озвучить вопрос"
                >
                  <Volume2 size={22} aria-hidden />
                </button>
              </div>
              {task.question_context && <p className="mt-3 text-base text-[var(--text-muted)]">{task.question_context}</p>}
              <MediaList media={task.media_question} />
            </>
          ) : (
            <>
              <p className="text-base font-semibold text-[var(--text-muted)]">{t("hear_and_type")}</p>
              <div className="mt-4 flex items-center justify-center gap-3">
                <button
                  type="button"
                  className="btn btn-secondary px-6 py-3 rounded-2xl flex items-center gap-2.5 text-base font-bold shadow-sm hover:border-[var(--accent)] hover:text-[var(--accent)] transition-all"
                  onClick={(e) => {
                    e.stopPropagation();
                    const textToPlay = task.tts_text || task.question_text || "";
                    if (textToPlay) {
                      speak(textToPlay, { lang: task.language ?? undefined, rate: ttsRate, volume: prefs?.volume });
                    }
                  }}
                  title="Повторить озвучку [Alt+R]"
                  aria-label="Повторить озвучку"
                >
                  <Volume2 size={22} aria-hidden />
                  <span>Повторить аудио</span>
                  <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-[var(--surface-2)] border border-[var(--border)] rounded text-[var(--text-muted)]">Alt+R</kbd>
                </button>
              </div>
              {hasUploadedAudio && (
                <div className="mt-3">
                  <MediaList media={task.media_answer.filter((m) => !m.mime_type.startsWith("image/"))} />
                </div>
              )}
              {!hasUploadedAudio && !soundOn && (
                <p className="mt-3 text-sm font-medium" style={{ color: "var(--warning)" }}>
                  {t("sound_disabled_hint") || "Озвучка отключена. Включите звук в шапке или нажмите M."}
                </p>
              )}
              {task.question_context && <p className="mt-3 text-base text-[var(--text-muted)]">{task.question_context}</p>}
            </>
          )}

          <div className="mx-auto mt-6 max-w-lg">
            <label htmlFor="answer-input" className="sr-only">
              {t("answer")}
            </label>
            <input
              ref={inputRef}
              key={task.item_id}
              id="answer-input"
              className="input text-center text-xl sm:text-2xl font-semibold min-h-[3.75rem] py-3 rounded-2xl border-2 focus:border-[var(--accent)] shadow-sm bg-[var(--surface)] text-[var(--text)]"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !feedback) {
                  e.preventDefault();
                  e.stopPropagation();
                  void check();
                } else if (e.key === "Escape" && !feedback) {
                  e.preventDefault();
                  e.stopPropagation();
                  void dontKnow();
                }
              }}
              autoFocus
              disabled={!!feedback}
              autoComplete="off"
            />
          </div>

          {offlineAnswer !== null && (
            <div role="alert" className="mx-auto mt-4 max-w-lg rounded-2xl p-4 text-sm" style={{ background: "var(--warning-soft)" }}>
              {t("save_error_offline")}
              <button className="btn btn-secondary mt-2 w-full min-h-[2.85rem] rounded-xl" onClick={() => void check()}>
                {t("retry")}
              </button>
            </div>
          )}

          {!feedback && (
            <div className="mt-6 flex flex-wrap justify-center gap-3">
              <button
                type="button"
                className="btn btn-primary min-h-[3.25rem] px-8 text-base font-bold shadow-md rounded-2xl flex items-center gap-2"
                onClick={() => void check()}
                disabled={!text.trim()}
              >
                <span>{t("check")}</span>
                <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-white/25 rounded">Enter</kbd>
              </button>
              <button
                type="button"
                className="btn btn-secondary min-h-[3.25rem] px-6 text-base font-bold rounded-2xl flex items-center gap-2"
                onClick={() => void dontKnow()}
              >
                <span>{t("dont_know_answer")}</span>
                <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-[var(--surface-2)] border border-[var(--border)] rounded text-[var(--text-muted)]">Esc</kbd>
              </button>
              {task.hint && !hintShown && (
                <button
                  type="button"
                  className="btn btn-ghost min-h-[3.25rem] px-4 text-base font-medium rounded-2xl flex items-center gap-1.5"
                  onClick={() => setHintShown(true)}
                  title="Подсказка [Ctrl+H]"
                >
                  <span>{t("hint")}</span>
                  <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-[var(--surface-2)] border border-[var(--border)] rounded text-[var(--text-muted)]">Ctrl+H</kbd>
                </button>
              )}
            </div>
          )}

          {hintShown && !feedback && (
            <p className="mt-3 text-base font-medium" style={{ color: "var(--warning)" }}>
              {t("hint")}: {task.hint}
            </p>
          )}

          {feedback && <FeedbackPanel feedback={feedback} />}

          {feedback && !feedback.correct && !corrected && feedback.answer_id && (
            <button
              type="button"
              className="btn btn-secondary mt-3 rounded-xl flex items-center gap-2 mx-auto"
              onClick={async () => {
                try {
                  await api(`/study-sessions/${session.id}/answers/${feedback.answer_id}/correction`, {
                    method: "POST",
                    body: { final_correct: true },
                  });
                  setCorrected(true);
                  setFeedback((prev) => prev ? { ...prev, correct: true } : null);
                  setMissedInRound((prev) => prev.filter((m) => m.item_id !== task.item_id));
                } catch {
                  /* повторить можно ещё раз */
                }
              }}
            >
              <span>{t("count_correct")}</span>
              <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-[var(--surface-2)] border border-[var(--border)] rounded text-[var(--text-muted)]">C</kbd>
            </button>
          )}

          {feedback && (
            <button
              type="button"
              className="btn btn-primary mt-4 min-h-[3.25rem] px-8 text-base font-bold rounded-2xl shadow-md flex items-center gap-2 mx-auto"
              onClick={() => void next()}
            >
              <span>{queueIndex + 1 < currentQueue.length ? t("next") : (missedInRound.length > 0 || (!feedback.correct && !corrected) ? t("next") : (batchIndex + 1 < batches.length ? t("next") : t("finish")))}</span>
              <kbd className="hidden sm:inline-block px-1.5 py-0.5 text-xs font-mono bg-white/25 rounded">Enter</kbd>
            </button>
          )}

          {/* Keyboard hints footer */}
          <div className="mt-6 hidden sm:flex flex-wrap items-center justify-center gap-2.5 text-xs text-[var(--text-muted)] opacity-75">
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Enter</kbd> {feedback ? "Далее" : "Проверить"}</span>
            <span>•</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Esc</kbd> Не знаю</span>
            {task.hint && <span>• <kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Ctrl+H</kbd> Подсказка</span>}
            <span>•</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Alt+R</kbd> Звук</span>
            <span>•</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Shift+Esc</kbd> Выход</span>
          </div>
        </div>
      </div>
    </StudyChrome>
  );
}

function SpellRateControl({ rate, onChange }: { rate: number; onChange: (r: number) => void }) {
  return (
    <select
      className="select select-sm w-auto py-1 px-2.5 text-xs font-semibold rounded-xl bg-[var(--surface-2)] border border-[var(--border)] text-[var(--text)] hover:border-[var(--accent)] transition-colors"
      value={rate}
      onChange={(e) => onChange(parseFloat(e.target.value))}
      title="Скорость озвучки"
      aria-label="Скорость озвучки"
    >
      <option value="0.7">0.7×</option>
      <option value="1">1×</option>
      <option value="1.3">1.3×</option>
    </select>
  );
}
