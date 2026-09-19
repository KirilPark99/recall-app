import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ClipboardCopy, FolderOpen, Sparkles, X } from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";

interface ParsedCard {
  front_text: string;
  back_text: string;
  front_hint?: string;
  back_hint?: string;
}

interface QuizletParseResponse {
  ok: boolean;
  total_rows: number;
  valid_rows: number;
  empty_rows: number;
  duplicates_in_file: number;
  cards: ParsedCard[];
  suggested_title?: string;
  suggested_front_lang?: string;
  suggested_back_lang?: string;
  is_folder?: boolean;
  folder_title?: string;
  total_sets?: number;
  sets?: Array<{ id: string; title: string; href: string }>;
}

interface QuizletImportModalProps {
  onClose: () => void;
  onAddCards: (cards: ParsedCard[]) => Promise<void> | void;
}

export function QuizletImportModal({ onClose, onAddCards }: QuizletImportModalProps) {
  const { t } = useApp();
  const [text, setText] = useState("");
  const [termDelim, setTermDelim] = useState("auto");
  const [cardDelim, setCardDelim] = useState("auto");
  const [customTermDelim, setCustomTermDelim] = useState("");
  const [parsedResult, setParsedResult] = useState<QuizletParseResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const parseMut = useMutation({
    mutationFn: (overrideText?: string) => {
      setErrorMsg(null);
      const textToParse = (overrideText !== undefined ? overrideText : text).trim();
      const effectiveTermDelim = termDelim === "custom" ? customTermDelim : termDelim;
      return api<QuizletParseResponse>("/imports/quizlet/parse", {
        body: {
          text: textToParse,
          term_delimiter: effectiveTermDelim,
          card_delimiter: cardDelim,
        },
      });
    },
    onSuccess: (data) => {
      setParsedResult(data);
    },
    onError: (e) => {
      setErrorMsg((e as Error).message);
    },
  });

  const addMut = useMutation({
    mutationFn: async () => {
      if (!parsedResult?.cards?.length) return;
      await onAddCards(parsedResult.cards);
    },
    onSuccess: () => {
      onClose();
    },
    onError: (e) => {
      setErrorMsg((e as Error).message);
    },
  });

  const handlePasteFromClipboard = async () => {
    try {
      const clip = await navigator.clipboard.readText();
      if (clip && clip.trim()) {
        setText(clip);
        parseMut.mutate(clip);
      }
    } catch {
      setErrorMsg("Браузер заблокировал чтение буфера. Пожалуйста, вставьте текст вручную нажатием Ctrl+V.");
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Импорт карточек из Quizlet"
      onKeyDown={(e) => e.key === "Escape" && onClose()}
    >
      <div className="card my-8 w-full max-w-3xl rounded-3xl p-6 sm:p-8 shadow-modal border border-[var(--border)] bg-[var(--surface-1)] space-y-5">
        <div className="flex items-center justify-between border-b border-[var(--border)] pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[var(--accent)] text-white shadow-md">
              <Sparkles size={22} aria-hidden />
            </div>
            <div>
              <h2 className="text-2xl font-black tracking-tight">Копирование с Quizlet</h2>
              <p className="text-xs sm:text-sm text-[var(--text-muted)]">
                Мгновенный перенос любого набора карточек в Recall
              </p>
            </div>
          </div>
          <button
            type="button"
            className="btn btn-ghost p-2 rounded-xl text-[var(--text-muted)] hover:text-[var(--text-main)]"
            onClick={onClose}
            aria-label={t("close")}
          >
            <X size={20} aria-hidden />
          </button>
        </div>

        {/* Инфо блок */}
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-2)]/60 p-4 text-sm leading-relaxed flex items-start gap-3">
          <Sparkles className="text-[var(--accent)] shrink-0 mt-0.5" size={18} aria-hidden />
          <div>
            <span className="font-bold text-[var(--text-main)] block mb-1">
              Импорт по ссылке или тексту из Quizlet:
            </span>
            <p className="text-xs text-[var(--text-muted)] leading-relaxed">
              Вставьте <strong>ссылку на любой набор Quizlet</strong> (например, <code className="rounded bg-[var(--surface-3)] px-1.5 py-0.5 text-[var(--text-main)] font-mono">https://quizlet.com/000000000/...</code>) или скопированный текст карточек. Recall автоматически загрузит набор, обойдя защиту Cloudflare через EzSolver.
            </p>
          </div>
        </div>

        {!parsedResult ? (
          <div className="space-y-4">
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-bold text-[var(--text-muted)]" htmlFor="quizlet-textarea">
                  Ссылка на Quizlet или текст карточек *
                </label>
                <button
                  type="button"
                  onClick={handlePasteFromClipboard}
                  className="btn btn-secondary text-xs py-1 px-3 rounded-xl border border-[var(--border)] flex items-center gap-1.5 font-bold hover:border-[var(--accent)]"
                >
                  <ClipboardCopy size={15} /> Вставить из буфера
                </button>
              </div>
              <textarea
                id="quizlet-textarea"
                className="textarea font-mono text-sm sm:text-base rounded-2xl p-4 leading-relaxed w-full min-h-[11rem]"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={"https://quizlet.com/000000000/flash-cards/\n\nили вставьте текст карточек:\napple\tяблоко\ndog\tсобака"}
                autoFocus
              />
            </div>

            {/* Настройки разделителей */}
            <div className="grid gap-3 sm:grid-cols-2 text-xs sm:text-sm">
              <div>
                <label className="mb-1.5 block font-bold text-[var(--text-muted)]" htmlFor="term-delim-select">
                  Разделитель термина и определения
                </label>
                <select
                  id="term-delim-select"
                  className="select w-full rounded-xl min-h-[2.5rem]"
                  value={termDelim}
                  onChange={(e) => setTermDelim(e.target.value)}
                >
                  <option value="auto">Авто (Табуляция, дефис, двоеточие, чередование)</option>
                  <option value="tab">Табуляция (по умолчанию в Quizlet)</option>
                  <option value="dash">Дефис / Тире ( - , — , – )</option>
                  <option value="colon">Двоеточие ( : )</option>
                  <option value="comma">Запятая ( , )</option>
                  <option value="alternating">Чередование строк (термин, след. строка — перевод)</option>
                  <option value="custom">Свой символ…</option>
                </select>
                {termDelim === "custom" && (
                  <input
                    className="input mt-2 text-sm rounded-xl"
                    placeholder="Введите символ разделителя"
                    value={customTermDelim}
                    onChange={(e) => setCustomTermDelim(e.target.value)}
                  />
                )}
              </div>

              <div>
                <label className="mb-1.5 block font-bold text-[var(--text-muted)]" htmlFor="card-delim-select">
                  Разделитель между карточками
                </label>
                <select
                  id="card-delim-select"
                  className="select w-full rounded-xl min-h-[2.5rem]"
                  value={cardDelim}
                  onChange={(e) => setCardDelim(e.target.value)}
                >
                  <option value="auto">Авто (Новая строка)</option>
                  <option value="newline">Новая строка</option>
                  <option value="double_newline">Пустая строка (через строку)</option>
                  <option value="semicolon">Точка с запятой ( ; )</option>
                </select>
              </div>
            </div>

            {errorMsg && (
              <div
                role="alert"
                className="rounded-2xl p-4 text-sm font-medium whitespace-pre-line border border-red-200 dark:border-red-900"
                style={{ background: "var(--danger-soft)", color: "var(--danger)" }}
              >
                {errorMsg}
              </div>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                className="btn btn-secondary min-h-[3rem] px-5 text-base font-semibold rounded-2xl"
                onClick={onClose}
              >
                {t("cancel")}
              </button>
              <button
                type="button"
                className="btn btn-primary min-h-[3rem] px-6 text-base font-bold rounded-2xl shadow-md flex items-center gap-2"
                disabled={!text.trim() || parseMut.isPending}
                onClick={() => parseMut.mutate()}
              >
                {parseMut.isPending ? t("loading") : "Распознать карточки →"}
              </button>
            </div>
          </div>
        ) : parsedResult.is_folder ? (
          /* Экран выбора набора из папки Quizlet */
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <FolderOpen className="text-[var(--accent)] shrink-0" size={26} />
              <div>
                <h3 className="text-lg font-bold">{parsedResult.folder_title}</h3>
                <p className="text-xs text-[var(--text-muted)]">
                  Папка содержит {parsedResult.total_sets} наборов. Выберите набор, чтобы добавить его карточки:
                </p>
              </div>
            </div>

            <div className="max-h-[22rem] overflow-y-auto rounded-2xl border border-[var(--border)] divide-y divide-[var(--border)]">
              {(parsedResult.sets || []).map((s) => (
                <div key={s.id} className="flex items-center justify-between p-3.5 hover:bg-[var(--surface-2)] transition-colors">
                  <span className="font-semibold text-sm truncate mr-3">{s.title}</span>
                  <button
                    type="button"
                    className="btn btn-secondary text-xs py-1.5 px-3 rounded-xl shrink-0 font-bold"
                    disabled={parseMut.isPending}
                    onClick={() => {
                      const setUrl = s.href || `https://quizlet.com/${s.id}`;
                      setText(setUrl);
                      parseMut.mutate(setUrl);
                    }}
                  >
                    {parseMut.isPending ? t("loading") : "Выбрать этот набор →"}
                  </button>
                </div>
              ))}
            </div>

            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-2)]/50 p-3 text-xs text-[var(--text-muted)]">
              💡 Чтобы импортировать всю папку целиком со всеми наборами в отдельные наборы Recall, используйте кнопку <strong>«Импортировать»</strong> в разделе «Папки» или «Наборы».
            </div>

            <div className="flex justify-start pt-2">
              <button
                type="button"
                className="btn btn-secondary min-h-[3rem] px-5 text-base font-semibold rounded-2xl"
                onClick={() => setParsedResult(null)}
              >
                ← Назад
              </button>
            </div>
          </div>
        ) : (
          /* Предпросмотр распознанных карточек */
          <div className="space-y-4">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div>
                <span className="text-lg font-bold">Распознано карточек: </span>
                <span className="text-lg font-black text-[var(--accent)]">{parsedResult.valid_rows}</span>
                {parsedResult.duplicates_in_file > 0 && (
                  <span className="ml-2 text-xs text-[var(--text-muted)]">
                    (дубликатов удалено: {parsedResult.duplicates_in_file})
                  </span>
                )}
              </div>
              <button
                type="button"
                className="btn btn-ghost text-sm font-bold text-[var(--accent)]"
                onClick={() => setParsedResult(null)}
              >
                ← Изменить текст / разделители
              </button>
            </div>

            <div className="max-h-[22rem] overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--surface-2)] p-2">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-[var(--border)] text-xs font-bold text-[var(--text-muted)]">
                    <th className="p-3 w-12">#</th>
                    <th className="p-3">Термин</th>
                    <th className="p-3">Определение</th>
                  </tr>
                </thead>
                <tbody>
                  {parsedResult.cards.slice(0, 100).map((c, i) => (
                    <tr key={i} className="border-b border-[var(--border)]/40 last:border-0 hover:bg-[var(--surface-1)]">
                      <td className="p-3 text-xs text-[var(--text-muted)] font-mono">{i + 1}</td>
                      <td className="p-3 font-semibold text-[var(--text-main)]">
                        {c.front_text}
                        {c.front_hint && <span className="ml-1 text-xs text-[var(--text-muted)]">({c.front_hint})</span>}
                      </td>
                      <td className="p-3 text-[var(--text-muted)]">
                        {c.back_text}
                        {c.back_hint && <span className="ml-1 text-xs text-[var(--text-muted)]">({c.back_hint})</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {parsedResult.cards.length > 100 && (
              <p className="text-center text-xs text-[var(--text-muted)]">
                Показаны первые 100 карточек из {parsedResult.cards.length}
              </p>
            )}

            {errorMsg && (
              <p
                role="alert"
                className="rounded-2xl p-4 text-sm font-medium"
                style={{ background: "var(--danger-soft)", color: "var(--danger)" }}
              >
                {errorMsg}
              </p>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                className="btn btn-secondary min-h-[3rem] px-5 text-base font-semibold rounded-2xl"
                onClick={() => setParsedResult(null)}
              >
                Назад
              </button>
              <button
                type="button"
                className="btn btn-primary min-h-[3rem] px-7 text-base font-bold rounded-2xl shadow-md flex items-center gap-2"
                disabled={addMut.isPending || !parsedResult.valid_rows}
                onClick={() => addMut.mutate()}
              >
                {addMut.isPending ? t("saving") : `Добавить карточки (${parsedResult.valid_rows})`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
