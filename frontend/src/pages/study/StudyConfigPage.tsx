import { FormEvent, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowLeftRight, ArrowRight, Clock, ListOrdered, Shuffle, Volume2 } from "lucide-react";
import { api, ApiError } from "../../api/client";
import { useApp } from "../../state/AppContext";

const MODE_TITLES: Record<string, string> = {
  cards: "Карточки",
  learn: "Обучение",
  write: "Письменный ответ",
  spell: "Диктант",
  test: "Тест",
  match: "Подбор пар",
};

export function StudyConfigPage() {
  const [params] = useSearchParams();
  const setId = params.get("set") ?? params.get("set_id") ?? "";
  const mode = params.get("mode") ?? "cards";
  const { t, prefs } = useApp();
  const navigate = useNavigate();

  const [direction, setDirection] = useState(prefs?.default_direction ?? "front_to_back");
  const [cardFilter, setCardFilter] = useState("all");
  const [order, setOrder] = useState("random");
  const [questionTypes, setQuestionTypes] = useState<string[]>(["mc", "written"]);
  const [timerOn, setTimerOn] = useState(false);
  const [timerSeconds, setTimerSeconds] = useState(600);
  const [boardSize, setBoardSize] = useState(6);
  const [autoTts, setAutoTts] = useState<boolean>(() => localStorage.getItem("study_auto_tts") === "true");
  const [error, setError] = useState<string | null>(null);

  const setQ = useQuery({
    queryKey: ["set", setId],
    queryFn: () => api<{ id: string; title: string; card_count: number }>(`/sets/${setId}`),
    enabled: !!setId,
  });

  const create = useMutation({
    mutationFn: async () => {
      const settings: Record<string, unknown> = {
        batch_size: prefs?.batch_size ?? 7,
        auto_tts: autoTts,
      };
      if (mode === "test") {
        settings.question_types = questionTypes;
        settings.question_count = setQ.data?.card_count ?? 0;
        if (timerOn) settings.timer_seconds = timerSeconds;
      }
      if (mode === "match") settings.board_size = boardSize;
      localStorage.setItem("study_auto_tts", autoTts ? "true" : "false");
      return api<{ id: string }>("/study-sessions", {
        body: {
          mode,
          set_ids: setId ? [setId] : null,
          direction,
          card_filter: cardFilter,
          limit: 0,
          order,
          settings,
        },
      });
    },
    onSuccess: (data) => navigate(`/study/${data.id}`, { replace: true }),
    onError: (e) => {
      if (e instanceof ApiError) setError(e.message);
      else setError(t("error_generic"));
    },
  });

  if (!setId) {
    return (
      <div className="p-8 text-center">
        <p>{t("source_not_specified")}</p>
        <Link to="/sets" className="btn btn-secondary mt-3">{t("nav_sets")}</Link>
      </div>
    );
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  const modeName = t(`mode_${mode === "match" ? "match" : mode}` as never) || MODE_TITLES[mode] || mode;

  return (
    <div className="mx-auto max-w-2xl p-4 sm:p-6 pb-14">
      <Link
        to={`/sets/${setId}`}
        className="inline-flex items-center gap-1.5 text-sm font-semibold text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors mb-4"
      >
        <ArrowLeft size={16} aria-hidden />
        <span>{setQ.data?.title || t("back_to_set")}</span>
      </Link>

      <div className="mb-6">
        <h1 className="text-3xl sm:text-4xl font-black tracking-tight text-[var(--text)]">
          {modeName}
        </h1>
        <p className="mt-1 text-sm sm:text-base text-[var(--text-muted)]">
          {setQ.data ? `${setQ.data.card_count} ${t("cards_count")}` : t("loading")}
        </p>
      </div>

      <form onSubmit={submit} className="card space-y-7 p-6 sm:p-8 rounded-3xl shadow-card bg-[var(--surface)] border border-[var(--border)]">
        {/* Direction segment selector */}
        <div>
          <label className="mb-3 block text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
            {t("default_direction")}
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {[
              { id: "front_to_back", label: t("dir_front_to_back"), desc: "Вопрос → Ответ", icon: ArrowRight },
              { id: "back_to_front", label: t("dir_back_to_front"), desc: "Ответ → Вопрос", icon: ArrowLeft },
              { id: "both", label: t("dir_both"), desc: "Случайная сторона", icon: ArrowLeftRight },
            ].map((opt) => {
              const active = direction === opt.id;
              const Icon = opt.icon;
              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => setDirection(opt.id)}
                  className={`flex flex-col items-start p-4 rounded-2xl border text-left transition-all relative ${
                    active
                      ? "border-[var(--accent)] bg-[var(--accent-soft)] shadow-sm ring-2 ring-[var(--accent)]/30"
                      : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--border-hover)] hover:bg-[var(--surface-2)]"
                  }`}
                >
                  <div className="flex items-center justify-between w-full mb-2">
                    <div className={`p-2 rounded-xl ${active ? "bg-[var(--accent)] text-white" : "bg-[var(--surface-2)] text-[var(--text-muted)]"}`}>
                      <Icon size={18} aria-hidden />
                    </div>
                    {active && (
                      <span className="w-2.5 h-2.5 rounded-full bg-[var(--accent)]"></span>
                    )}
                  </div>
                  <span className={`text-base font-bold leading-tight ${active ? "text-[var(--accent)]" : "text-[var(--text)]"}`}>
                    {opt.label}
                  </span>
                  <span className="mt-1 text-xs text-[var(--text-muted)] leading-tight">
                    {opt.desc}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Filter and Order selectors */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          <div>
            <label className="mb-2 block text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
              Карточки
            </label>
            <div className="grid grid-cols-2 gap-2 bg-[var(--surface-2)] p-1.5 rounded-2xl border border-[var(--border)]">
              <button
                type="button"
                onClick={() => setCardFilter("all")}
                className={`py-2.5 px-3 rounded-xl text-sm font-bold transition-all text-center ${
                  cardFilter === "all"
                    ? "bg-[var(--surface)] text-[var(--text)] shadow-sm border border-[var(--border)]"
                    : "text-[var(--text-muted)] hover:text-[var(--text)]"
                }`}
              >
                {t("filter_all")}
              </button>
              <button
                type="button"
                onClick={() => setCardFilter("starred")}
                className={`py-2.5 px-3 rounded-xl text-sm font-bold transition-all text-center flex items-center justify-center gap-1.5 ${
                  cardFilter === "starred"
                    ? "bg-[var(--surface)] text-amber-500 shadow-sm border border-[var(--border)]"
                    : "text-[var(--text-muted)] hover:text-amber-500"
                }`}
              >
                <span>★</span>
                <span>{t("filter_favorites")}</span>
              </button>
            </div>
          </div>

          <div>
            <label className="mb-2 block text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
              Порядок
            </label>
            <div className="grid grid-cols-2 gap-2 bg-[var(--surface-2)] p-1.5 rounded-2xl border border-[var(--border)]">
              <button
                type="button"
                onClick={() => setOrder("random")}
                className={`py-2.5 px-3 rounded-xl text-sm font-bold transition-all text-center flex items-center justify-center gap-1.5 ${
                  order === "random"
                    ? "bg-[var(--surface)] text-[var(--text)] shadow-sm border border-[var(--border)]"
                    : "text-[var(--text-muted)] hover:text-[var(--text)]"
                }`}
              >
                <Shuffle size={15} aria-hidden />
                <span>{t("order_random")}</span>
              </button>
              <button
                type="button"
                onClick={() => setOrder("original")}
                className={`py-2.5 px-3 rounded-xl text-sm font-bold transition-all text-center flex items-center justify-center gap-1.5 ${
                  order === "original"
                    ? "bg-[var(--surface)] text-[var(--text)] shadow-sm border border-[var(--border)]"
                    : "text-[var(--text-muted)] hover:text-[var(--text)]"
                }`}
              >
                <ListOrdered size={15} aria-hidden />
                <span>{t("order_original")}</span>
              </button>
            </div>
          </div>
        </div>

        {/* Test mode specific options */}
        {mode === "test" && (
          <div className="space-y-5 pt-2 border-t border-[var(--border)]">
            <fieldset>
              <legend className="mb-3 block text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
                {t("question_types")}
              </legend>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {[
                  { id: "mc", label: t("type_mc"), hint: "4 варианта ответа" },
                  { id: "written", label: t("type_written"), hint: "Ввод ответа вручную" },
                  { id: "tf", label: t("type_tf"), hint: "Верно / Неверно" },
                  { id: "match", label: t("type_match"), hint: "Соединение пар" },
                ].map((item) => {
                  const checked = questionTypes.includes(item.id);
                  return (
                    <label
                      key={item.id}
                      className={`flex items-start gap-3 p-3.5 rounded-2xl border cursor-pointer transition-all ${
                        checked
                          ? "border-[var(--accent)] bg-[var(--accent-soft)]/50 shadow-sm"
                          : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--border-hover)]"
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="mt-0.5 h-5 w-5 rounded accent-[var(--accent)] cursor-pointer"
                        checked={checked}
                        onChange={(e) =>
                          setQuestionTypes((prev) =>
                            e.target.checked ? [...prev, item.id] : prev.filter((x) => x !== item.id)
                          )
                        }
                      />
                      <div className="flex flex-col">
                        <span className="text-base font-bold text-[var(--text)] leading-tight">{item.label}</span>
                        <span className="text-xs text-[var(--text-muted)] mt-0.5">{item.hint}</span>
                      </div>
                    </label>
                  );
                })}
              </div>
            </fieldset>

            {/* Test timer */}
            <div className="rounded-2xl border border-[var(--border)] p-4 bg-[var(--surface-2)]">
              <label className="flex items-center justify-between cursor-pointer select-none">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-xl bg-[var(--surface)] text-[var(--text)] shadow-sm">
                    <Clock size={18} aria-hidden />
                  </div>
                  <div>
                    <span className="text-base font-bold text-[var(--text)]">{t("timer_on")}</span>
                    <p className="text-xs text-[var(--text-muted)]">Ограничить время на тест</p>
                  </div>
                </div>
                <input
                  type="checkbox"
                  className="h-5 w-5 rounded accent-[var(--accent)] cursor-pointer"
                  checked={timerOn}
                  onChange={(e) => setTimerOn(e.target.checked)}
                />
              </label>

              {timerOn && (
                <div className="mt-4 pt-3 border-t border-[var(--border)]">
                  <label className="mb-2 block text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
                    Время на прохождение
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {[300, 600, 900, 1200, 1800].map((sec) => (
                      <button
                        key={sec}
                        type="button"
                        onClick={() => setTimerSeconds(sec)}
                        className={`py-1.5 px-3 rounded-xl text-xs font-bold transition-all ${
                          timerSeconds === sec
                            ? "bg-[var(--accent)] text-white shadow-sm"
                            : "bg-[var(--surface)] text-[var(--text)] border border-[var(--border)] hover:border-[var(--border-hover)]"
                        }`}
                      >
                        {sec / 60} мин
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Match mode options */}
        {mode === "match" && (
          <div>
            <label className="mb-2 block text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
              {t("pairs_on_board")}
            </label>
            <div className="grid grid-cols-3 gap-2 bg-[var(--surface-2)] p-1.5 rounded-2xl border border-[var(--border)] max-w-sm">
              {[6, 8, 12].map((size) => (
                <button
                  key={size}
                  type="button"
                  onClick={() => setBoardSize(size)}
                  className={`py-2 px-3 rounded-xl text-sm font-bold transition-all text-center ${
                    boardSize === size
                      ? "bg-[var(--surface)] text-[var(--accent)] shadow-sm border border-[var(--border)]"
                      : "text-[var(--text-muted)] hover:text-[var(--text)]"
                  }`}
                >
                  {size} пар
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Sound card */}
        <div className="rounded-2xl border border-[var(--border)] p-4 sm:p-5 bg-[var(--surface-2)] flex items-center justify-between gap-4">
          <div className="flex items-start sm:items-center gap-3.5">
            <div className="p-2.5 rounded-2xl bg-[var(--accent-soft)] text-[var(--accent)] shrink-0">
              <Volume2 size={22} aria-hidden />
            </div>
            <div>
              <label htmlFor="cfg-auto-tts" className="text-base font-bold text-[var(--text)] cursor-pointer block leading-tight">
                {t("auto_speak_study")}
              </label>
              <p className="text-xs sm:text-sm text-[var(--text-muted)] mt-1">
                {t("auto_speak_hint")}
              </p>
            </div>
          </div>
          <label className="relative inline-flex items-center cursor-pointer shrink-0">
            <input
              id="cfg-auto-tts"
              type="checkbox"
              className="sr-only peer"
              checked={autoTts}
              onChange={(e) => {
                setAutoTts(e.target.checked);
                localStorage.setItem("study_auto_tts", e.target.checked ? "true" : "false");
              }}
            />
            <div className="w-12 h-7 bg-[var(--surface-3)] peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-6 after:w-6 after:transition-all peer-checked:bg-[var(--accent)]"></div>
          </label>
        </div>

        {error && (
          <p role="alert" className="rounded-2xl px-4 py-3 text-base" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
            {error}
          </p>
        )}

        {/* Start / Cancel actions */}
        <div className="pt-2 space-y-3">
          <button
            type="submit"
            className="btn btn-primary w-full min-h-[3.5rem] text-base sm:text-lg font-bold rounded-2xl shadow-lg hover:shadow-xl transition-all"
            disabled={create.isPending}
          >
            {create.isPending ? t("loading") : `Начать занятие →`}
          </button>
          <div className="text-center">
            <Link
              to={`/sets/${setId}`}
              className="inline-block text-sm font-semibold text-[var(--text-muted)] hover:text-[var(--text)] transition-colors py-2"
            >
              {t("cancel")}
            </Link>
          </div>
        </div>
      </form>
    </div>
  );
}
