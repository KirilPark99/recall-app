import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Circle, CircleCheck, CircleDashed, Flag, Volume2 } from "lucide-react";
import { api } from "../../api/client";
import { useApp } from "../../state/AppContext";
import { MediaList, StudyChrome } from "./BasicRunners";
import { speak, stopSpeaking } from "../../lib/tts";
import type { SessionDto, TaskDto } from "./types";
import { useStudySound } from "./useStudySound";

export function TestRunner({ session }: { session: SessionDto }) {
  const { t, prefs } = useApp();
  const navigate = useNavigate();
  const tasks = session.tasks ?? [];
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [marked, setMarked] = useState<Set<string>>(new Set());
  const [draftVersions, setDraftVersions] = useState<Record<string, number>>({});
  const [draftDirty, setDraftDirty] = useState(false);
  const [confirmFinish, setConfirmFinish] = useState(false);
  const [now, setNow] = useState(Date.now());
  const { soundOn, toggleSound } = useStudySound(session.settings?.auto_tts);
  const task = tasks[index];
  const testInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (task?.task_type === "test_written") {
      const timer = setTimeout(() => {
        testInputRef.current?.focus();
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [index, task?.item_id, task?.task_type]);

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (task?.task_type === "test_written" && testInputRef.current && document.activeElement !== testInputRef.current) {
        if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
          testInputRef.current.focus();
        }
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [task?.task_type]);

  useEffect(() => {
    if (task && soundOn) {
      const textToSpeak = task.statement ?? task.question_text ?? "";
      if (textToSpeak) {
        speak(textToSpeak, { lang: task.language ?? undefined, rate: prefs?.tts_rate, volume: prefs?.volume });
      }
      return () => stopSpeaking();
    }
  }, [index, task, soundOn, prefs]);

  const deadline = session.deadline_at ? new Date(session.deadline_at).getTime() : null;

  useEffect(() => {
    if (!deadline) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [deadline]);

  const remainingSec = deadline ? Math.max(0, Math.floor((deadline - now) / 1000)) : null;
  const timeExpired = remainingSec !== null && remainingSec <= 0;

  const answeredCount = useMemo(() => Object.values(answers).filter((v) => v.trim()).length, [answers]);
  const skippedCount = tasks.length - answeredCount;

  // Черновик: сохранение с дебаунсом и версией (устаревший запрос не перезапишет новый).
  useEffect(() => {
    if (!task) return;
    const draft = answers[task.item_id] ?? "";
    if (!draftDirty) return;
    const id = setTimeout(async () => {
      setDraftDirty(false);
      try {
        const res = await api<{ draft_version: number }>(
          `/study-sessions/${session.id}/items/${task.item_id}/draft`,
          { method: "PUT", body: { draft, draft_version: draftVersions[task.item_id] ?? 0 } }
        );
        setDraftVersions((prev) => ({ ...prev, [task.item_id]: res.draft_version }));
      } catch {
        /* draft is best-effort */
      }
    }, 600);
    return () => clearTimeout(id);
  }, [answers, task, draftDirty]); // eslint-disable-line react-hooks/exhaustive-deps

  const submitted = useRef<Set<string>>(new Set());

  const submitTaskAnswer = async (tk: TaskDto, raw: string) => {
    if (submitted.current.has(tk.item_id) || !raw.trim()) return;
    let answer: Record<string, unknown>;
    if (tk.task_type === "test_mc") answer = { choice: raw };
    else if (tk.task_type === "test_written") answer = { text: raw };
    else if (tk.task_type === "test_tf") answer = { is_true: raw === "true" };
    else if (tk.task_type === "test_match") answer = { mapping: JSON.parse(raw) };
    else answer = {};
    try {
      await api(`/study-sessions/${session.id}/answers`, {
        body: { item_id: tk.item_id, client_event_id: crypto.randomUUID(), answer },
      });
      submitted.current.add(tk.item_id);
    } catch {
      /* ответ уже принят или сеть: complete посчитает по сохранённым */
    }
  };

  const finalize = async () => {
    // Сначала фиксируем финальные ответы на сервере, затем завершаем.
    for (const tk of tasks) {
      const raw = answers[tk.item_id] ?? "";
      await submitTaskAnswer(tk, raw);
    }
    try {
      await api(`/study-sessions/${session.id}/complete`, { method: "POST" });
      navigate(`/study/${session.id}/result`, { replace: true });
    } catch {
      /* already completed */
      navigate(`/study/${session.id}/result`, { replace: true });
    }
  };

  useEffect(() => {
    if (timeExpired) void finalize();
  }, [timeExpired]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!task) return null;

  const setAnswer = (value: string) => {
    setAnswers((prev) => ({ ...prev, [task.item_id]: value }));
    setDraftDirty(true);
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (confirmFinish) {
        if (e.key === "Enter") {
          e.preventDefault();
          void finalize();
        } else if (e.key === "Escape") {
          e.preventDefault();
          setConfirmFinish(false);
        }
        return;
      }

      const isInput = (e.target as HTMLElement)?.tagName?.match(/INPUT|TEXTAREA|SELECT/);

      if (isInput) {
        if (e.key === "Enter" && task?.task_type === "test_written") {
          e.preventDefault();
          if (index + 1 < tasks.length) {
            navigateTo(index + 1);
          } else {
            setConfirmFinish(true);
          }
        } else if (e.key === "Escape") {
          e.preventDefault();
          if (index + 1 < tasks.length) {
            navigateTo(index + 1);
          } else {
            setConfirmFinish(true);
          }
        }
        return;
      }

      if (e.key === "Escape") {
        e.preventDefault();
        if (index + 1 < tasks.length) {
          navigateTo(index + 1);
        } else {
          setConfirmFinish(true);
        }
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        navigateTo(Math.max(0, index - 1));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        navigateTo(Math.min(tasks.length - 1, index + 1));
      } else if (e.key === "m" || e.key === "M" || e.key === "ь" || e.key === "Ь") {
        if (task) {
          e.preventDefault();
          setMarked((prev) => {
            const next = new Set(prev);
            if (next.has(task.item_id)) next.delete(task.item_id);
            else next.add(task.item_id);
            return next;
          });
        }
      } else if (e.key === "r" || e.key === "R" || e.key === "к" || e.key === "К") {
        const textToSpeak = task?.statement ?? task?.question_text ?? "";
        if (textToSpeak) {
          speak(textToSpeak, { lang: task?.language ?? undefined, rate: prefs?.tts_rate, volume: prefs?.volume });
        }
      } else if (task?.task_type === "test_mc") {
        if (["1", "2", "3", "4"].includes(e.key)) {
          const idx = parseInt(e.key, 10) - 1;
          const choices = task.choices ?? [];
          if (choices[idx]) {
            e.preventDefault();
            setAnswer(choices[idx]);
          }
        }
      } else if (task?.task_type === "test_tf") {
        if (e.key === "1" || e.key === "t" || e.key === "T" || e.key === "е" || e.key === "Е") {
          e.preventDefault();
          setAnswer("true");
        } else if (e.key === "2" || e.key === "f" || e.key === "F" || e.key === "а" || e.key === "А") {
          e.preventDefault();
          setAnswer("false");
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [confirmFinish, index, tasks, task, answers, marked, prefs]); // eslint-disable-line react-hooks/exhaustive-deps

  const navigateTo = (i: number) => setIndex(i);

  return (
    <StudyChrome
      onExit={() => setConfirmFinish(true)}
      stageInfo={{
        current: index + 1,
        total: tasks.length,
        modeLabel: t("mode_test") || "Тест",
      }}
      soundOn={soundOn}
      onToggleSound={toggleSound}
      extra={
        remainingSec !== null ? (
          <span
            className="rounded-lg px-2.5 py-1 font-mono text-sm font-semibold"
            style={{
              background: "var(--surface-2)",
              color: remainingSec < 60 ? "var(--danger)" : "var(--text)",
            }}
            aria-live="off"
          >
            {Math.floor(remainingSec / 60)}:{String(remainingSec % 60).padStart(2, "0")}
          </span>
        ) : undefined
      }
    >
      <div className="flex flex-1 flex-col">
        {/* Навигатор вопросов */}
        <div className="mb-4 flex flex-wrap gap-1.5" role="tablist" aria-label={t("questions_count")}>
          {tasks.map((tk, i) => {
            const answered = (answers[tk.item_id] ?? "").trim().length > 0;
            const isMarked = marked.has(tk.item_id);
            return (
              <button
                key={tk.item_id}
                role="tab"
                aria-selected={i === index}
                className={`h-10 w-10 sm:h-11 sm:w-11 rounded-xl border flex items-center justify-center text-sm font-semibold transition-all cursor-pointer ${i === index ? "border-[var(--accent)] scale-105" : ""}`}
                style={{
                  background: i === index ? "var(--accent-soft)" : "var(--surface)",
                  color: answered ? "var(--success)" : "var(--text-muted)",
                }}
                onClick={() => navigateTo(i)}
                title={`Вопрос ${i + 1}${answered ? " — отвечен" : ""}${isMarked ? " — отмечен" : ""}`}
              >
                {answered ? <CircleCheck size={18} aria-hidden /> : isMarked ? <CircleDashed size={18} aria-hidden /> : <Circle size={18} aria-hidden />}
              </button>
            );
          })}
        </div>

        <div className="study-card flex-1 p-7 sm:p-10 rounded-3xl shadow-card">
          <p className="mb-3 text-xs uppercase tracking-wider font-bold text-[var(--text-muted)]">
            {task.task_type === "test_mc" ? "Выберите ответ" : task.task_type === "test_written" ? "Введите ответ" : task.task_type === "test_tf" ? "Верно или неверно?" : "Сопоставьте пары"}
          </p>

          {task.task_type === "test_match" ? (
            <MatchQuestion
              task={task}
              value={answers[task.item_id]}
              onChange={(mapping) => setAnswers((prev) => ({ ...prev, [task.item_id]: JSON.stringify(mapping) }))}
            />
          ) : (
            <>
              <div className="flex items-start justify-between gap-3">
                <p className="text-xl sm:text-2xl font-bold tracking-tight">{task.statement ?? task.question_text}</p>
                <button
                  type="button"
                  className="btn btn-ghost p-2 text-[var(--accent)] hover:bg-[var(--accent-soft)] rounded-xl shrink-0"
                  onClick={() => {
                    const textToSpeak = task.statement ?? task.question_text ?? "";
                    if (textToSpeak) {
                      speak(textToSpeak, { lang: task.language ?? undefined, rate: prefs?.tts_rate, volume: prefs?.volume });
                    }
                  }}
                  title="Озвучить вопрос [R]"
                  aria-label="Озвучить вопрос"
                >
                  <Volume2 size={22} aria-hidden />
                </button>
              </div>
              {task.question_context && <p className="mt-2 text-base text-[var(--text-muted)]">{task.question_context}</p>}
              <MediaList media={task.media_question} />

              {task.task_type === "test_mc" && (
                <div className="mt-6 grid gap-3">
                  {(task.choices ?? []).map((choice, i) => (
                    <div
                      key={choice}
                      className={`btn btn-secondary justify-between min-h-[3.5rem] px-5 py-3.5 text-base sm:text-lg font-medium rounded-2xl cursor-pointer ${answers[task.item_id] === choice ? "!border-[var(--accent)] !bg-[var(--accent-soft)] shadow-sm" : ""}`}
                      onClick={() => setAnswer(choice)}
                    >
                      <label className="flex items-center flex-1 cursor-pointer">
                        <kbd className="mr-3 px-2 py-0.5 rounded-lg bg-[var(--surface-3)] text-xs font-mono font-bold text-[var(--text)]">{i + 1}</kbd>
                        <input
                          type="radio"
                          name={task.item_id}
                          className="mr-3 h-5 w-5 accent-[var(--accent)]"
                          checked={answers[task.item_id] === choice}
                          onChange={() => setAnswer(choice)}
                        />
                        {choice}
                      </label>
                      <button
                        type="button"
                        className="btn btn-ghost p-1.5 text-[var(--text-muted)] hover:text-[var(--text)] ml-2 shrink-0 rounded-lg"
                        onClick={(e) => {
                          e.stopPropagation();
                          speak(choice, { rate: prefs?.tts_rate, volume: prefs?.volume });
                        }}
                        title="Озвучить вариант"
                        aria-label="Озвучить вариант"
                      >
                        <Volume2 size={16} aria-hidden />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {task.task_type === "test_written" && (
                <div className="mt-6">
                  <input
                    ref={testInputRef}
                    key={task.item_id}
                    className="input text-lg sm:text-xl min-h-[3.5rem] py-3 rounded-2xl w-full"
                    value={answers[task.item_id] ?? ""}
                    onChange={(e) => setAnswer(e.target.value)}
                    placeholder="Введите ответ и нажмите Enter"
                    aria-label={t("answer")}
                    autoFocus
                  />
                  <p className="mt-2 text-xs text-[var(--text-muted)]">Нажмите Enter для перехода к следующему вопросу</p>
                </div>
              )}

              {task.task_type === "test_tf" && (
                <div className="mt-6 flex gap-4">
                  {[
                    [true, "Верно", "1"],
                    [false, "Неверно", "2"],
                  ].map(([value, label, keyHint]) => (
                    <label key={String(value)} className={`btn btn-secondary flex-1 min-h-[3.5rem] px-6 text-base sm:text-lg font-bold rounded-2xl cursor-pointer flex items-center justify-center gap-2 ${answers[task.item_id] === String(value) ? "!border-[var(--accent)] !bg-[var(--accent-soft)] shadow-sm" : ""}`}>
                      <kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-3)] text-xs font-mono font-bold text-[var(--text)]">{keyHint as string}</kbd>
                      <input
                        type="radio"
                        name={`tf-${task.item_id}`}
                        className="mr-2 h-5 w-5 accent-[var(--accent)]"
                        checked={answers[task.item_id] === String(value)}
                        onChange={() => setAnswer(String(value))}
                      />
                      {label as string}
                    </label>
                  ))}
                </div>
              )}
            </>
          )}

          <div className="mt-8 flex justify-between items-center gap-3">
            <button className="btn btn-secondary min-h-[2.85rem] px-5 text-base font-semibold rounded-xl flex items-center gap-1.5" onClick={() => navigateTo(index - 1)} disabled={index === 0}>
              <span>←</span>
              <kbd className="hidden sm:inline-block px-1 py-0.5 text-[10px] font-mono opacity-60">←</kbd>
            </button>
            <button
              className="btn btn-ghost text-base font-medium rounded-xl flex items-center gap-1.5"
              onClick={() => {
                const next = new Set(marked);
                if (next.has(task.item_id)) next.delete(task.item_id);
                else next.add(task.item_id);
                setMarked(next);
              }}
              aria-pressed={marked.has(task.item_id)}
            >
              <CircleDashed size={16} aria-hidden />
              <span>Отметить</span>
              <kbd className="hidden sm:inline-block px-1 py-0.5 text-[10px] font-mono opacity-60">M</kbd>
            </button>
            {index + 1 < tasks.length ? (
              <button className="btn btn-primary min-h-[2.85rem] px-6 text-base font-semibold rounded-xl flex items-center gap-1.5" onClick={() => navigateTo(index + 1)}>
                <span>→</span>
                <kbd className="hidden sm:inline-block px-1 py-0.5 text-[10px] font-mono opacity-60 bg-white/20 rounded">→</kbd>
              </button>
            ) : (
              <button className="btn btn-primary min-h-[2.85rem] px-6 text-base font-bold rounded-xl flex items-center gap-1.5" onClick={() => setConfirmFinish(true)}>
                <Flag size={16} aria-hidden />
                <span>{t("finish_test")}</span>
              </button>
            )}
          </div>

          {/* Keyboard hints footer */}
          <div className="mt-6 hidden sm:flex flex-wrap items-center justify-center gap-2.5 text-xs text-[var(--text-muted)] opacity-75">
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">←</kbd> <kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">→</kbd> Навигация</span>
            <span>•</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Esc</kbd> Пропустить</span>
            <span>•</span>
            {task.task_type === "test_mc" && <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">1</kbd>–<kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">4</kbd> Выбор • </span>}
            {task.task_type === "test_tf" && <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">1</kbd>/<kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">2</kbd> Выбор • </span>}
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">M</kbd> Отметить</span>
            <span>•</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">R</kbd> Звук</span>
            <span>•</span>
            <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Shift+Esc</kbd> Выход</span>
          </div>
        </div>

        <div className="mt-4 text-center">
          <button className="btn btn-secondary min-h-[2.85rem] px-6 text-base font-semibold rounded-xl" onClick={() => setConfirmFinish(true)}>
            {t("finish_test")} ({answeredCount}/{tasks.length})
          </button>
        </div>
      </div>

      {confirmFinish && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="alertdialog" aria-modal="true">
          <div className="card w-full max-w-md p-8 text-center rounded-3xl shadow-2xl">
            <p className="text-lg font-bold">{skippedCount > 0 ? t("finish_with_skipped") : t("finish_test")}</p>
            <div className="mt-6 flex justify-center gap-3">
              <button className="btn btn-secondary min-h-[2.85rem] px-6 text-base font-semibold rounded-xl" onClick={() => setConfirmFinish(false)}>
                {t("cancel")}
              </button>
              <button className="btn btn-primary min-h-[2.85rem] px-6 text-base font-bold rounded-xl" onClick={() => void finalize()}>
                {t("confirm")}
              </button>
            </div>
          </div>
        </div>
      )}
    </StudyChrome>
  );
}

function MatchQuestion({
  task,
  value,
  onChange,
}: {
  task: TaskDto;
  value: string | undefined;
  onChange: (mapping: Record<string, string>) => void;
}) {
  const [selectedLeft, setSelectedLeft] = useState<string | null>(null);
  const mapping: Record<string, string> = value ? JSON.parse(value) : {};
  const rights = task.match_rights ?? [];
  const [shuffled] = useState(() => [...rights].sort(() => Math.random() - 0.5));

  const pickRight = (rightId: string) => {
    if (!selectedLeft) return;
    const next = { ...mapping, [selectedLeft]: rightId };
    onChange(next);
    setSelectedLeft(null);
  };

  return (
    <div className="mt-4 grid grid-cols-2 gap-4">
      <div className="space-y-3">
        {(task.match_lefts ?? []).map((l) => (
          <button
            key={l.id}
            className={`btn btn-secondary w-full justify-start min-h-[3.25rem] px-4 py-3 text-base font-medium rounded-xl ${selectedLeft === l.id ? "!border-[var(--accent)] !bg-[var(--accent-soft)]" : ""}`}
            onClick={() => setSelectedLeft(l.id)}
          >
            {l.text}
            {mapping[l.id] && <span className="ml-auto badge badge-accent">✓</span>}
          </button>
        ))}
      </div>
      <div className="space-y-3">
        {shuffled.map((r) => (
          <button key={r.id} className="btn btn-secondary w-full justify-start min-h-[3.25rem] px-4 py-3 text-base font-medium rounded-xl" onClick={() => pickRight(r.id)}>
            {r.text}
          </button>
        ))}
      </div>
      <p className="col-span-2 text-sm text-[var(--text-muted)]">
        Выберите элемент слева, затем его пару справа. Одна пара — один балл.
      </p>
    </div>
  );
}
