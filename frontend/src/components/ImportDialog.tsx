import { FormEvent, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Check, ClipboardCopy, FileText, FolderOpen, Sparkles, Upload, X } from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";

interface PreviewResult {
  job_id: string;
  format: string;
  total_rows: number;
  valid_rows: number;
  empty_rows: number;
  duplicates_in_file: number;
  error_count: number;
  sample: Array<Record<string, string>>;
  errors: Array<{ line: number; message: string }>;
  suggested_title?: string;
  suggested_front_lang?: string;
  suggested_back_lang?: string;
  is_folder?: boolean;
  folder_title?: string;
  total_sets?: number;
  sets?: Array<{ id: string; title: string; href: string }>;
}

interface FolderImportResult {
  ok: boolean;
  folder_id: string;
  folder_name: string;
  imported_sets_count: number;
  total_cards_count: number;
  sets: Array<{ id: string; title: string; card_count: number }>;
}

export function ImportDialog({ onClose }: { onClose: () => void }) {
  const { t } = useApp();
  const qc = useQueryClient();
  const navigate = useNavigate();

  // Tabs: "quizlet" (default) or "file"
  const [activeTab, setActiveTab] = useState<"quizlet" | "file">("quizlet");

  // Quizlet tab state
  const [quizletText, setQuizletText] = useState("");
  const [quizletTermDelim, setQuizletTermDelim] = useState("auto");
  const [quizletCardDelim, setQuizletCardDelim] = useState("auto");

  // File tab state
  const fileRef = useRef<HTMLInputElement>(null);
  const [filePasted, setFilePasted] = useState("");
  const [fileDelimiter, setFileDelimiter] = useState("auto");
  const [hasHeader, setHasHeader] = useState("auto");

  // Preview & Confirm state
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [frontLang, setFrontLang] = useState("");
  const [backLang, setBackLang] = useState("");

  // Folder import state
  const [folderName, setFolderName] = useState("");
  const [selectedSetIds, setSelectedSetIds] = useState<Set<string>>(new Set());
  const [folderResult, setFolderResult] = useState<FolderImportResult | null>(null);

  const previewMut = useMutation({
    mutationFn: async (overrideText?: string) => {
      const fd = new FormData();

      if (activeTab === "quizlet") {
        const textToUse = typeof overrideText === "string" ? overrideText : quizletText;
        if (!textToUse.trim()) {
          throw new Error("Вставьте скопированный текст из Quizlet или ссылку на набор.");
        }
        fd.append("text", textToUse.trim());
        fd.append("format", "quizlet");
        fd.append("term_delimiter", quizletTermDelim);
        fd.append("card_delimiter", quizletCardDelim);
      } else {
        if (fileRef.current?.files?.[0]) {
          fd.append("file", fileRef.current.files[0]);
        } else if (filePasted.trim()) {
          fd.append("text", filePasted.trim());
        } else {
          throw new Error("Выберите файл или вставьте текст для импорта.");
        }
        fd.append("delimiter", fileDelimiter);
        fd.append("has_header", hasHeader);
      }

      return api<PreviewResult>("/imports/preview", { formData: fd });
    },
    onSuccess: (data) => {
      setPreview(data);
      if (data.is_folder) {
        setFolderName(data.folder_title || data.suggested_title || "Папка из Quizlet");
        setSelectedSetIds(new Set((data.sets || []).map((s) => s.id)));
        setFolderResult(null);
      } else {
        if (data.suggested_title) {
          setNewTitle(data.suggested_title);
        } else if (!newTitle.trim()) {
          setNewTitle(activeTab === "quizlet" ? "Импорт из Quizlet" : "Импортированный набор");
        }
        if (data.suggested_front_lang) setFrontLang(data.suggested_front_lang);
        if (data.suggested_back_lang) setBackLang(data.suggested_back_lang);
      }
    },
  });

  const confirmMut = useMutation({
    mutationFn: () =>
      api<{ set_id: string }>("/imports", {
        body: {
          job_id: preview!.job_id,
          mode: "new",
          new_set: {
            title: newTitle.trim(),
            front_language: frontLang.trim().toLowerCase(),
            back_language: backLang.trim().toLowerCase(),
          },
        },
      }),
    onSuccess: async (data) => {
      await qc.invalidateQueries({ queryKey: ["sets"] });
      onClose();
      navigate(`/sets/${data.set_id}`);
    },
  });

  const folderImportMut = useMutation({
    mutationFn: () =>
      api<FolderImportResult>("/imports/quizlet/folder/import", {
        body: {
          url: quizletText.trim(),
          folder_name: folderName.trim(),
          selected_set_ids: Array.from(selectedSetIds),
        },
      }),
    onSuccess: async (data) => {
      setFolderResult(data);
      await qc.invalidateQueries({ queryKey: ["sets"] });
      await qc.invalidateQueries({ queryKey: ["folders"] });
    },
  });


  const handlePasteFromClipboard = async () => {
    try {
      const clip = await navigator.clipboard.readText();
      if (clip && clip.trim()) {
        setQuizletText(clip);
        previewMut.mutate(clip);
      }
    } catch {
      // clipboard read blocked by browser permissions
    }
  };

  const submitPreview = (e: FormEvent) => {
    e.preventDefault();
    previewMut.mutate();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={t("import_sets")}
      onKeyDown={(e) => e.key === "Escape" && onClose()}
    >
      <div className="card my-8 w-full max-w-2xl p-7 sm:p-9 rounded-3xl shadow-modal border border-[var(--border)] bg-[var(--surface-1)]">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl sm:text-3xl font-black tracking-tight flex items-center gap-2">
            <Sparkles className="text-[var(--accent)]" size={28} aria-hidden />
            {t("import_sets")}
          </h2>
          <button
            type="button"
            className="btn btn-ghost p-2 rounded-xl text-[var(--text-muted)] hover:text-[var(--text-main)]"
            onClick={onClose}
            aria-label={t("close")}
          >
            <X size={20} aria-hidden />
          </button>
        </div>

        {!preview ? (
          <form onSubmit={submitPreview} className="space-y-5">
            {/* Вкладки: Quizlet или Файл */}
            <div className="flex rounded-2xl bg-[var(--surface-2)] p-1.5 border border-[var(--border)]">
              <button
                type="button"
                className={`flex-1 py-2.5 px-4 text-sm sm:text-base font-bold rounded-xl transition-all flex items-center justify-center gap-2 ${
                  activeTab === "quizlet"
                    ? "bg-[var(--accent)] text-white shadow-sm"
                    : "text-[var(--text-muted)] hover:text-[var(--text-main)]"
                }`}
                onClick={() => setActiveTab("quizlet")}
              >
                <Sparkles size={18} aria-hidden />
                Копирование из Quizlet
              </button>
              <button
                type="button"
                className={`flex-1 py-2.5 px-4 text-sm sm:text-base font-bold rounded-xl transition-all flex items-center justify-center gap-2 ${
                  activeTab === "file"
                    ? "bg-[var(--accent)] text-white shadow-sm"
                    : "text-[var(--text-muted)] hover:text-[var(--text-main)]"
                }`}
                onClick={() => setActiveTab("file")}
              >
                <FileText size={18} aria-hidden />
                Файл CSV / TSV / JSON
              </button>
            </div>

            {/* Контент вкладки Quizlet */}
            {activeTab === "quizlet" && (
              <div className="space-y-4">
                <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface-2)]/60 p-4 text-sm leading-relaxed flex items-start gap-3">
                  <Sparkles className="text-[var(--accent)] shrink-0 mt-0.5" size={18} aria-hidden />
                  <div>
                    <span className="font-bold text-[var(--text-main)] block mb-1">
                      Импорт по ссылке или тексту из Quizlet:
                    </span>
                    <p className="text-xs text-[var(--text-muted)] leading-relaxed">
                      Вставьте <strong>ссылку на набор, папку или класс Quizlet</strong> (например, <code className="rounded bg-[var(--surface-3)] px-1.5 py-0.5 text-[var(--text-main)] font-mono">https://quizlet.com/000000000/...</code> или <code className="rounded bg-[var(--surface-3)] px-1.5 py-0.5 text-[var(--text-main)] font-mono">https://quizlet.com/join/...</code>) или скопированный текст карточек. Recall автоматически загрузит набор или целую папку с наборами.
                    </p>
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-bold text-[var(--text-muted)]" htmlFor="quizlet-input">
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
                    id="quizlet-input"
                    className="textarea font-mono text-sm sm:text-base rounded-2xl p-4 leading-relaxed w-full min-h-[10rem]"
                    value={quizletText}
                    onChange={(e) => setQuizletText(e.target.value)}
                    placeholder={"https://quizlet.com/000000000/flash-cards/\nhttps://quizlet.com/join/TESTCODE\n\nили вставьте текст карточек:\napple\tяблоко\ndog\tсобака"}
                    autoFocus
                  />
                </div>

                <div className="grid gap-3 sm:grid-cols-2 text-xs sm:text-sm">
                  <div>
                    <label className="mb-1.5 block font-bold text-[var(--text-muted)]" htmlFor="import-quizlet-delim">
                      Разделитель термина и определения (для текста)
                    </label>
                    <select
                      id="import-quizlet-delim"
                      className="select w-full rounded-xl min-h-[2.75rem]"
                      value={quizletTermDelim}
                      onChange={(e) => setQuizletTermDelim(e.target.value)}
                    >
                      <option value="auto">Авто (Табуляция, дефис, двоеточие, чередование)</option>
                      <option value="tab">Табуляция (по умолчанию в Quizlet)</option>
                      <option value="dash">Дефис / Тире ( - , — , – )</option>
                      <option value="colon">Двоеточие ( : )</option>
                      <option value="comma">Запятая ( , )</option>
                      <option value="alternating">Чередование строк (термин на строке 1, перевод на 2)</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1.5 block font-bold text-[var(--text-muted)]" htmlFor="import-quizlet-card-delim">
                      Разделитель между карточками (для текста)
                    </label>
                    <select
                      id="import-quizlet-card-delim"
                      className="select w-full rounded-xl min-h-[2.75rem]"
                      value={quizletCardDelim}
                      onChange={(e) => setQuizletCardDelim(e.target.value)}
                    >
                      <option value="auto">Авто (Новая строка)</option>
                      <option value="newline">Новая строка</option>
                      <option value="double_newline">Пустая строка (через строку)</option>
                      <option value="semicolon">Точка с запятой ( ; )</option>
                    </select>
                  </div>
                </div>
              </div>
            )}

            {/* Контент вкладки Файл */}
            {activeTab === "file" && (
              <div className="space-y-4">
                <div>
                  <label className="mb-2 block text-sm font-bold text-[var(--text-muted)]" htmlFor="import-file">
                    Файл CSV / TSV / JSON (до 10 MiB)
                  </label>
                  <input
                    id="import-file"
                    ref={fileRef}
                    type="file"
                    accept=".csv,.tsv,.json,.txt"
                    className="input h-12 text-base rounded-2xl file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-semibold file:bg-[var(--accent)] file:text-white hover:file:bg-[var(--accent-hover)] cursor-pointer"
                    onChange={() => setFilePasted("")}
                  />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-bold text-[var(--text-muted)]" htmlFor="import-text">
                    …или вставьте сырой текст
                  </label>
                  <textarea
                    id="import-text"
                    className="textarea font-mono text-base rounded-2xl p-4 leading-relaxed w-full min-h-[8rem]"
                    rows={5}
                    value={filePasted}
                    onChange={(e) => setFilePasted(e.target.value)}
                    placeholder={"apple,яблоко\ndog,собака"}
                  />
                </div>
                <div className="grid gap-4 sm:grid-cols-2 text-xs sm:text-sm">
                  <div>
                    <label className="mb-1.5 block font-bold text-[var(--text-muted)]" htmlFor="import-delim">
                      Разделитель
                    </label>
                    <select
                      id="import-delim"
                      className="select min-h-[2.75rem] text-sm rounded-xl w-full"
                      value={fileDelimiter}
                      onChange={(e) => setFileDelimiter(e.target.value)}
                    >
                      <option value="auto">Авто</option>
                      <option value="tab">Табуляция</option>
                      <option value="comma">Запятая</option>
                      <option value="semicolon">Точка с запятой</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1.5 block font-bold text-[var(--text-muted)]" htmlFor="import-header">
                      Первая строка
                    </label>
                    <select
                      id="import-header"
                      className="select min-h-[2.75rem] text-sm rounded-xl w-full"
                      value={hasHeader}
                      onChange={(e) => setHasHeader(e.target.value)}
                    >
                      <option value="auto">Авто</option>
                      <option value="true">Заголовок</option>
                      <option value="false">Данные</option>
                    </select>
                  </div>
                </div>
              </div>
            )}

            {previewMut.isError && (
              <p
                role="alert"
                className="rounded-2xl p-4 text-sm font-medium whitespace-pre-line"
                style={{ background: "var(--danger-soft)", color: "var(--danger)" }}
              >
                {(previewMut.error as Error).message}
              </p>
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
                type="submit"
                className="btn btn-primary min-h-[3rem] px-6 text-base font-bold rounded-2xl shadow-md flex items-center gap-2"
                disabled={previewMut.isPending}
              >
                <Upload size={18} aria-hidden />
                {previewMut.isPending ? t("loading") : "Показать предпросмотр →"}
              </button>
            </div>
          </form>
        ) : preview.is_folder ? (
          /* Экран предпросмотра папки */
          <div className="space-y-5">
            {!folderResult ? (
              <>
                <div className="flex items-center gap-3 mb-2">
                  <FolderOpen className="text-[var(--accent)]" size={28} />
                  <div>
                    <h3 className="text-xl font-black">{preview.folder_title}</h3>
                    <p className="text-sm text-[var(--text-muted)]">
                      {preview.total_sets} {preview.total_sets === 1 ? "набор" : preview.total_sets! < 5 ? "набора" : "наборов"} найдено в папке Quizlet
                    </p>
                  </div>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-bold text-[var(--text-muted)]" htmlFor="folder-name">
                    Название папки в Recall
                  </label>
                  <input
                    id="folder-name"
                    className="input h-12 text-base rounded-2xl"
                    value={folderName}
                    onChange={(e) => setFolderName(e.target.value)}
                    placeholder="Название папки"
                  />
                </div>

                <div className="flex items-center justify-between text-sm">
                  <span className="font-bold text-[var(--text-muted)]">
                    Выбрано {selectedSetIds.size} из {(preview.sets || []).length}
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="btn btn-secondary text-xs py-1 px-3 rounded-xl"
                      onClick={() => setSelectedSetIds(new Set((preview.sets || []).map((s) => s.id)))}
                    >
                      Выбрать все
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary text-xs py-1 px-3 rounded-xl"
                      onClick={() => setSelectedSetIds(new Set())}
                    >
                      Снять все
                    </button>
                  </div>
                </div>

                <div className="max-h-72 overflow-y-auto rounded-2xl border border-[var(--border)] divide-y divide-[var(--border)]">
                  {(preview.sets || []).map((s) => (
                    <label
                      key={s.id}
                      className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--surface-2)]/30 cursor-pointer transition-colors"
                    >
                      <input
                        type="checkbox"
                        checked={selectedSetIds.has(s.id)}
                        onChange={() => {
                          const next = new Set(selectedSetIds);
                          if (next.has(s.id)) next.delete(s.id);
                          else next.add(s.id);
                          setSelectedSetIds(next);
                        }}
                        className="w-5 h-5 rounded accent-[var(--accent)]"
                      />
                      <span className="font-semibold text-base flex-1">{s.title}</span>
                    </label>
                  ))}
                </div>

                {folderImportMut.isError && (
                  <p
                    role="alert"
                    className="rounded-2xl p-4 text-sm font-medium"
                    style={{ background: "var(--danger-soft)", color: "var(--danger)" }}
                  >
                    {(folderImportMut.error as Error).message}
                  </p>
                )}

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    className="btn btn-secondary min-h-[3rem] px-5 text-base font-semibold rounded-2xl"
                    onClick={() => setPreview(null)}
                  >
                    ← Назад
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary min-h-[3rem] px-6 text-base font-bold rounded-2xl shadow-md flex items-center gap-2"
                    disabled={selectedSetIds.size === 0 || !folderName.trim() || folderImportMut.isPending}
                    onClick={() => folderImportMut.mutate()}
                  >
                    <FolderOpen size={18} aria-hidden />
                    {folderImportMut.isPending
                      ? "Загрузка наборов…"
                      : `Импортировать ${selectedSetIds.size} ${selectedSetIds.size === 1 ? "набор" : selectedSetIds.size < 5 ? "набора" : "наборов"}`}
                  </button>
                </div>
              </>
            ) : (
              /* Результат импорта папки */
              <div className="space-y-5">
                <div className="flex items-center gap-3 text-[var(--success)]">
                  <Check size={32} />
                  <div>
                    <h3 className="text-xl font-black text-[var(--text-main)]">Папка импортирована!</h3>
                    <p className="text-sm text-[var(--text-muted)]">
                      {folderResult.imported_sets_count} наборов, {folderResult.total_cards_count} карточек
                    </p>
                  </div>
                </div>

                <div className="rounded-2xl border border-[var(--border)] divide-y divide-[var(--border)]">
                  {folderResult.sets.map((s) => (
                    <div key={s.id} className="flex items-center justify-between px-4 py-3">
                      <span className="font-semibold">{s.title}</span>
                      <span className="badge text-xs font-bold px-2.5 py-0.5 rounded-lg">
                        {s.card_count} карт.
                      </span>
                    </div>
                  ))}
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button"
                    className="btn btn-secondary min-h-[3rem] px-5 text-base font-semibold rounded-2xl"
                    onClick={onClose}
                  >
                    Закрыть
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary min-h-[3rem] px-6 text-base font-bold rounded-2xl shadow-md"
                    onClick={() => {
                      onClose();
                      navigate("/folders");
                    }}
                  >
                    Перейти в папки →
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          /* Экран предпросмотра карточек */
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div className="card p-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)]/50 text-center">
                <div className="text-3xl font-black text-[var(--accent)]">{preview.valid_rows}</div>
                <div className="mt-1 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  пригодных
                </div>
              </div>
              <div className="card p-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)]/50 text-center">
                <div className="text-3xl font-black">{preview.duplicates_in_file}</div>
                <div className="mt-1 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  дубликатов
                </div>
              </div>
              <div className="card p-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)]/50 text-center">
                <div className="text-3xl font-black">{preview.empty_rows}</div>
                <div className="mt-1 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  пустых
                </div>
              </div>
              <div className="card p-4 rounded-2xl border border-[var(--border)] bg-[var(--surface-2)]/50 text-center">
                <div
                  className="text-3xl font-black"
                  style={{ color: preview.error_count > 0 ? "var(--danger)" : undefined }}
                >
                  {preview.error_count}
                </div>
                <div className="mt-1 text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                  ошибок
                </div>
              </div>
            </div>

            <div className="max-h-60 overflow-y-auto rounded-2xl border border-[var(--border)]">
              <table className="w-full text-base">
                <thead>
                  <tr className="sticky top-0 border-b border-[var(--border)] bg-[var(--surface-2)] text-left text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
                    <th className="py-2.5 px-4 w-12">#</th>
                    <th className="py-2.5 px-4 w-1/2">{t("front")}</th>
                    <th className="py-2.5 px-4 w-1/2">{t("back")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {preview.sample.map((row, i) => (
                    <tr key={i} className="hover:bg-[var(--surface-2)]/30 transition-colors">
                      <td className="py-2.5 px-4 text-sm font-semibold text-[var(--text-muted)]">{row.line}</td>
                      <td className="py-2.5 px-4 font-medium">{row.front_text}</td>
                      <td className="py-2.5 px-4 font-medium">{row.back_text}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {preview.errors.length > 0 && (
              <div className="rounded-2xl p-4 text-base" style={{ background: "var(--warning-soft)" }}>
                <div className="font-bold">{t("explanation")}:</div>
                <ul className="mt-2 list-inside list-disc space-y-1">
                  {preview.errors.slice(0, 5).map((e, i) => (
                    <li key={i}>
                      строка {e.line}: {e.message}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-3">
              <div className="sm:col-span-3">
                <label className="mb-2 block text-sm font-bold text-[var(--text-muted)]" htmlFor="import-title">
                  Название нового набора *
                </label>
                <input
                  id="import-title"
                  className="input h-12 text-base rounded-2xl"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="Введите название набора"
                />
              </div>
              <div>
                <label className="mb-2 block text-sm font-bold text-[var(--text-muted)]" htmlFor="import-flang">
                  Язык вопроса
                </label>
                <input
                  id="import-flang"
                  className="input h-12 text-base rounded-2xl"
                  value={frontLang}
                  onChange={(e) => setFrontLang(e.target.value)}
                  placeholder="en"
                />
              </div>
              <div>
                <label className="mb-2 block text-sm font-bold text-[var(--text-muted)]" htmlFor="import-blang">
                  Язык ответа
                </label>
                <input
                  id="import-blang"
                  className="input h-12 text-base rounded-2xl"
                  value={backLang}
                  onChange={(e) => setBackLang(e.target.value)}
                  placeholder="ru"
                />
              </div>
            </div>

            {confirmMut.isError && (
              <p
                role="alert"
                className="rounded-2xl p-4 text-base font-medium"
                style={{ background: "var(--danger-soft)", color: "var(--danger)" }}
              >
                {(confirmMut.error as Error).message}
              </p>
            )}

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                className="btn btn-secondary min-h-[3rem] px-5 text-base font-semibold rounded-2xl"
                onClick={() => setPreview(null)}
              >
                ← Назад
              </button>
              <button
                type="button"
                className="btn btn-primary min-h-[3rem] px-6 text-base font-bold rounded-2xl shadow-md flex items-center gap-2"
                disabled={!newTitle.trim() || confirmMut.isPending || preview.valid_rows === 0}
                onClick={() => confirmMut.mutate()}
              >
                <Sparkles size={18} aria-hidden />
                {confirmMut.isPending ? t("saving") : `Создать набор из ${preview.valid_rows} карточек`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
