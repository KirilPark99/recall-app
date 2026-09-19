import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowDown, ArrowUp, Eye, GripVertical, ImagePlus, Plus, RefreshCcw, Search,
  Sparkles, Trash2, X,
} from "lucide-react";
import { api, ApiError } from "../api/client";
import { useApp } from "../state/AppContext";
import { QuizletImportModal } from "../components/QuizletImportModal";
import type { CardDto } from "./SetDetail";

type SaveStatus = "clean" | "dirty" | "saving" | "saved" | "error";

interface EditorCard extends CardDto {
  _local: boolean; // ещё не сохранён на сервере
  _deleted?: boolean;
}

export function EditorPage() {
  const { setId } = useParams<{ setId: string }>();
  const { t, locale } = useApp();
  const qc = useQueryClient();
  const navigate = useNavigate();

  const setQ = useQuery({
    queryKey: ["set", setId],
    queryFn: () => api<{ id: string; title: string; content_version: number; front_language: string; back_language: string; viewer_role?: string; is_admin_created?: boolean }>(`/sets/${setId}`),
  });
  const cardsQ = useQuery({
    queryKey: ["cards", setId],
    queryFn: async () => {
      const first = await api<{ items: CardDto[]; total: number; set_content_version: number }>(`/sets/${setId}/cards?page=1&page_size=200`);
      const items = [...first.items];
      for (let page = 2; items.length < first.total; page += 1) {
        const next = await api<{ items: CardDto[] }>(`/sets/${setId}/cards?page=${page}&page_size=200`);
        items.push(...next.items);
      }
      return { ...first, items };
    },
  });

  const [cards, setCards] = useState<EditorCard[]>([]);
  const [status, setStatus] = useState<SaveStatus>("clean");
  const [conflict, setConflict] = useState<null | { local: EditorCard }>(null);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [previewCard, setPreviewCard] = useState<EditorCard | null>(null);
  const [lastUndeleted, setLastUndeleted] = useState<EditorCard | null>(null);
  const [showQuizletImport, setShowQuizletImport] = useState(false);
  const initialized = useRef(false);
  const saveTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const saveQueue = useRef<Promise<void>>(Promise.resolve());
  const versionRef = useRef(1);
  const cardsRef = useRef<EditorCard[]>([]);
  useEffect(() => {
    if (setQ.data) versionRef.current = setQ.data.content_version;
  }, [setQ.data]);

  useEffect(() => {
    cardsRef.current = cards;
  }, [cards]);

  useEffect(() => {
    if (cardsQ.data && !initialized.current) {
      initialized.current = true;
      setCards(cardsQ.data.items.map((c) => ({ ...c, _local: false })));
    }
  }, [cardsQ.data]);

  // Предупреждение при уходе с несохранёнными изменениями
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (status === "dirty" || status === "saving" || cards.some((c) => c._local)) {
        e.preventDefault();
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [status, cards]);

  const patchCard = useMutation({
    mutationFn: ({ cardId, patch, version }: { cardId: string; patch: Record<string, unknown>; version?: number }) => {
      const query = version != null ? `?expected_content_version=${version}` : "";
      return api<CardDto>(`/sets/${setId}/cards/${cardId}${query}`, { method: "PATCH", body: patch });
    },
  });
  const createCard = useMutation({
    mutationFn: ({ patch, position }: { patch: Record<string, unknown>; position?: number }) =>
      api<CardDto>(`/sets/${setId}/cards${position == null ? "" : `?at_position=${position}`}`, { body: patch }),
  });
  const deleteCard = useMutation({
    mutationFn: (cardId: string) => api(`/sets/${setId}/cards/${cardId}`, { method: "DELETE" }),
  });
  const reorderMut = useMutation({
    mutationFn: (orderedIds: string[]) =>
      api<{ content_version: number }>(`/sets/${setId}/cards/reorder`, {
        body: { ordered_ids: orderedIds, expected_content_version: versionRef.current },
      }),
    onSuccess: (result) => {
      versionRef.current = result.content_version;
      qc.invalidateQueries({ queryKey: ["set", setId] });
      setStatus("saved");
    },
    onError: () => setStatus("error"),
  });
  const swapMut = useMutation({
    mutationFn: () =>
      api(`/sets/${setId}/cards/swap-sides`, {
        body: {},
      }),
    onSuccess: () => {
      initialized.current = false;
      void qc.invalidateQueries({ queryKey: ["cards", setId] });
      void qc.invalidateQueries({ queryKey: ["set", setId] });
      setStatus("saved");
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) {
        setConflict({ local: (cards[0] ?? { id: "" }) as EditorCard });
      }
    },
  });

  const handleSwapAll = async () => {
    if (!cards.length) return;
    if (
      !window.confirm(
        locale === "ru"
          ? "Поменять местами вопрос и ответ для всех карточек в наборе?"
          : "Swap question and answer for all cards in this set?"
      )
    ) {
      return;
    }
    setCards((prev) =>
      prev.map((c) => ({
        ...c,
        front_text: c.back_text,
        back_text: c.front_text,
        front_context: c.back_context,
        back_context: c.front_context,
        front_hint: c.back_hint,
        back_hint: c.front_hint,
        front_explanation: c.back_explanation,
        back_explanation: c.front_explanation,
        front_example: c.back_example,
        back_example: c.front_example,
        front_language: c.back_language,
        back_language: c.front_language,
        enabled_front_to_back: c.enabled_back_to_front,
        enabled_back_to_front: c.enabled_front_to_back,
        written_check_front: c.written_check_back,
        written_check_back: c.written_check_front,
        accepted_front: c.accepted_back,
        accepted_back: c.accepted_front,
        front_media: c.back_media,
        back_media: c.front_media,
      }))
    );
    try {
      await swapMut.mutateAsync();
    } catch (err) {
      console.error("Swap sides failed:", err);
    }
  };

  const handleSwapSelected = async () => {
    if (selected.size === 0) return;
    const ids = new Set(selected);
    setCards((prev) =>
      prev.map((c) => {
        if (!ids.has(c.id)) return c;
        return {
          ...c,
          front_text: c.back_text,
          back_text: c.front_text,
          front_context: c.back_context,
          back_context: c.front_context,
          front_hint: c.back_hint,
          back_hint: c.front_hint,
          front_explanation: c.back_explanation,
          back_explanation: c.front_explanation,
          front_example: c.back_example,
          back_example: c.front_example,
          front_language: c.back_language,
          back_language: c.front_language,
          enabled_front_to_back: c.enabled_back_to_front,
          enabled_back_to_front: c.enabled_front_to_back,
          written_check_front: c.written_check_back,
          written_check_back: c.written_check_front,
          accepted_front: c.accepted_back,
          accepted_back: c.accepted_front,
          front_media: c.back_media,
          back_media: c.front_media,
        };
      })
    );
    for (const cardId of selected) {
      await api(`/sets/${setId}/cards/${cardId}/swap-sides`, { method: "POST" }).catch(() => undefined);
    }
    void qc.invalidateQueries({ queryKey: ["cards", setId] });
    void qc.invalidateQueries({ queryKey: ["set", setId] });
  };
  const bulkDeleteMut = useMutation({
    mutationFn: (ids: string[]) =>
      api<{ content_version: number }>(`/sets/${setId}/cards/bulk-delete`, {
        body: { card_ids: ids, expected_content_version: versionRef.current },
      }),
    onSuccess: (result) => {
      versionRef.current = result.content_version;
      initialized.current = false;
      void qc.invalidateQueries({ queryKey: ["cards", setId] });
      void qc.invalidateQueries({ queryKey: ["set", setId] });
      setSelected(new Set());
    },
  });
  const moveMut = useMutation({
    mutationFn: ({ ids, targetSetId, targetVersion }: { ids: string[]; targetSetId: string; targetVersion: number }) =>
      api<{ content_version: number }>(`/sets/${setId}/cards/bulk-move`, {
        body: { card_ids: ids, target_set_id: targetSetId, expected_content_version: versionRef.current, target_expected_content_version: targetVersion },
      }),
    onSuccess: (result) => {
      versionRef.current = result.content_version;
      initialized.current = false;
      void qc.invalidateQueries({ queryKey: ["cards", setId] });
      setSelected(new Set());
    },
  });

  const mySets = useQuery({
    queryKey: ["sets", "own"],
    queryFn: () => api<Array<{ id: string; title: string; content_version: number }>>("/sets?page_size=100"),
    enabled: selected.size > 0,
  });

  const bumpVersion = () => {
    versionRef.current += 1;
    if (setQ.data) {
      qc.setQueryData(["set", setId], { ...setQ.data, content_version: versionRef.current });
    }
  };

  const scheduleSave = useCallback(
    (cardId: string) => {
      setStatus("dirty");
      const prev = saveTimers.current.get(cardId);
      if (prev) clearTimeout(prev);
      const timer = setTimeout(() => {
        saveQueue.current = saveQueue.current.then(async () => {
        // читаем актуальные данные через ref: замыкание содержит устаревший массив
        const card = cardsRef.current.find((c) => c.id === cardId);
        if (!card || card._local) return;
        setStatus("saving");
        try {
          const patch = {
            front_text: card.front_text,
            back_text: card.back_text,
            front_context: card.front_context,
            back_context: card.back_context,
            front_hint: card.front_hint,
            back_hint: card.back_hint,
            front_explanation: card.front_explanation,
            back_explanation: card.back_explanation,
            front_example: card.front_example,
            back_example: card.back_example,
            front_language: card.front_language,
            back_language: card.back_language,
            enabled_front_to_back: card.enabled_front_to_back,
            enabled_back_to_front: card.enabled_back_to_front,
            written_check_front: card.written_check_front,
            written_check_back: card.written_check_back,
            accepted_front: card.accepted_front,
            accepted_back: card.accepted_back,
          };
          await patchCard.mutateAsync({ cardId, patch, version: versionRef.current });
          bumpVersion();
          setStatus("saved");
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) {
            setConflict({ local: card });
          } else {
            setStatus("error");
          }
        }
        });
      }, 800);
      saveTimers.current.set(cardId, timer);
    },
    [patchCard, setQ.data, qc, setId]
  );

  const updateCard = (cardId: string, field: keyof CardDto, value: unknown) => {
    setCards((prev) => prev.map((c) => (c.id === cardId ? { ...c, [field]: value } as EditorCard : c)));
    scheduleSave(cardId);
  };

  const addCard = async (after?: EditorCard) => {
    const position = after ? cards.findIndex((c) => c.id === after.id) + 1 : cards.length;
    try {
      const created = await createCard.mutateAsync({
        position,
        patch: {
          front_text: "",
          back_text: "",
          accepted_front: [],
          accepted_back: [],
        },
      });
      const local: EditorCard = { ...created, _local: false };
      setCards((prev) => {
        const next = [...prev];
        next.splice(position, 0, local);
        return next;
      });
      bumpVersion();
      setStatus("saved");
      setTimeout(() => document.getElementById(`front-${created.id}`)?.focus(), 50);
    } catch {
      setStatus("error");
    }
  };

  const onAddCardsFromQuizlet = async (
    importedCards: Array<{ front_text: string; back_text: string; front_hint?: string; back_hint?: string }>
  ) => {
    if (!importedCards.length || !setId) return;
    setStatus("saving");
    try {
      await api(`/sets/${setId}/cards/batch`, {
        body: {
          cards: importedCards.map((c) => ({
            front_text: c.front_text,
            back_text: c.back_text,
            front_hint: c.front_hint || "",
            back_hint: c.back_hint || "",
            accepted_front: [],
            accepted_back: [],
          })),
          expected_content_version: versionRef.current,
        },
      });
      initialized.current = false;
      await qc.invalidateQueries({ queryKey: ["cards", setId] });
      await qc.invalidateQueries({ queryKey: ["set", setId] });
      setStatus("saved");
    } catch {
      setStatus("error");
      throw new Error("Не удалось добавить карточки в набор.");
    }
  };

  const removeCard = async (card: EditorCard) => {
    setLastUndeleted(card);
    setCards((prev) => prev.filter((c) => c.id !== card.id));
    if (!card._local) {
      try {
        await deleteCard.mutateAsync(card.id);
        bumpVersion();
        setStatus("saved");
      } catch {
        setStatus("error");
      }
    }
  };

  const undoDelete = async () => {
    if (!lastUndeleted) return;
    const toRestore = lastUndeleted;
    setLastUndeleted(null);
    try {
      const created = await api<CardDto>(`/sets/${setId}/cards/${toRestore.id}/restore?at_position=${toRestore.position}`, { method: "POST" });
      setCards((prev) => {
        const next = [...prev];
        next.splice(Math.min(toRestore.position, next.length), 0, { ...created, _local: false });
        return next;
      });
      bumpVersion();
      setStatus("saved");
    } catch {
      setStatus("error");
    }
  };

  const move = (card: EditorCard, delta: number) => {
    const next = [...cardsRef.current];
    const idx = next.findIndex((c) => c.id === card.id);
      const target = idx + delta;
      if (idx < 0 || target < 0 || target >= next.length) return;
      const a = next[idx];
      const b = next[target];
      if (a === undefined || b === undefined) return;
      next[idx] = b;
      next[target] = a;
    setCards(next);
    reorderMut.mutate(next.map((c) => c.id));
  };

  const moveToPosition = (card: EditorCard, posStr: string) => {
    const pos = parseInt(posStr, 10);
    if (Number.isNaN(pos)) return;
    const next = [...cardsRef.current];
      const idx = next.findIndex((c) => c.id === card.id);
      if (idx < 0) return;
      const item = next.splice(idx, 1)[0];
      if (item === undefined) return;
      next.splice(Math.max(0, Math.min(pos - 1, next.length)), 0, item);
    setCards(next);
    reorderMut.mutate(next.map((c) => c.id));
  };

  // Drag-and-drop (нативный HTML5, доступная альтернатива — кнопки/ввод позиции)
  const dragId = useRef<string | null>(null);
  const onDrop = (targetId: string) => {
    const srcId = dragId.current;
    dragId.current = null;
    if (!srcId || srcId === targetId) return;
    const next = [...cardsRef.current];
      const from = next.findIndex((c) => c.id === srcId);
      const to = next.findIndex((c) => c.id === targetId);
      if (from < 0 || to < 0) return;
      const item = next.splice(from, 1)[0];
      if (item === undefined) return;
      next.splice(to, 0, item);
    setCards(next);
    reorderMut.mutate(next.map((c) => c.id));
  };

  const duplicate = async (card: EditorCard) => {
    try {
      const idx = cards.findIndex((c) => c.id === card.id);
      const created = await api<CardDto>(`/sets/${setId}/cards/${card.id}/duplicate?at_position=${idx + 1}`, { method: "POST" });
      setCards((prev) => {
        const next = [...prev];
        next.splice(idx + 1, 0, { ...created, _local: false });
        return next;
      });
      bumpVersion();
    } catch {
      setStatus("error");
    }
  };

  const attachMedia = async (card: EditorCard, side: "front" | "back") => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/png,image/jpeg,image/webp,image/gif,audio/mpeg,audio/wav,audio/ogg";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      try {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("description", "");
        const media = await api<{ id: string }>("/media/upload", { formData: fd });
        await api(`/sets/${setId}/cards/${card.id}/media`, { body: { media_id: media.id, side } });
        initialized.current = false;
        await qc.invalidateQueries({ queryKey: ["cards", setId] });
        bumpVersion();
      } catch (e) {
        setStatus("error");
        if (e instanceof ApiError) alert(e.message);
      }
    };
    input.click();
  };

  const detachMedia = async (card: EditorCard, mediaId: string) => {
    await api(`/sets/${setId}/cards/${card.id}/media/${mediaId}`, { method: "DELETE" });
    initialized.current = false;
    await qc.invalidateQueries({ queryKey: ["cards", setId] });
  };

  const visible = useMemo(() => {
    if (!filter.trim()) return cards;
    const f = filter.trim().toLowerCase();
    return cards.filter(
      (c) => c.front_text.toLowerCase().includes(f) || c.back_text.toLowerCase().includes(f)
    );
  }, [cards, filter]);

  if (setQ.isLoading || (cardsQ.isLoading && !initialized.current)) {
    return (
      <div className="mx-auto max-w-4xl space-y-3 p-4">
        <div className="skeleton h-10 w-64" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="skeleton h-16" />
        ))}
      </div>
    );
  }

  if (setQ.data && setQ.data.viewer_role && setQ.data.viewer_role !== "owner") {
    return (
      <div className="card mx-auto max-w-2xl p-10 text-center rounded-3xl shadow-card space-y-4 my-10">
        <div className="text-4xl">🔒</div>
        <h2 className="text-2xl font-bold">Редактирование недоступно</h2>
        <p className="text-base text-[var(--text-muted)]">
          Этот набор создан администратором и доступен только для чтения.
        </p>
        <div>
          <Link to={`/sets/${setId}`} className="btn btn-primary min-h-[3rem] px-6 text-base font-bold rounded-xl">
            ← Вернуться к набору
          </Link>
        </div>
      </div>
    );
  }

  const statusLabel =
    status === "dirty" ? t("unsaved_changes") :
    status === "saving" ? t("saving") :
    status === "saved" ? t("saved") :
    status === "error" ? t("save_failed") : t("saved");

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-2 sm:p-4">
      {/* Метаданные */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link to={`/sets/${setId}`} className="text-base sm:text-lg font-bold hover:underline" style={{ color: "var(--accent)" }}>
            ← {setQ.data?.title}
          </Link>
          <span
            className={`badge py-1.5 px-3.5 text-sm font-semibold ${status === "error" ? "" : "badge-accent"}`}
            style={status === "error" ? { background: "var(--danger-soft)", color: "var(--danger)" } : undefined}
            aria-live="polite"
          >
            {statusLabel}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-secondary min-h-[2.75rem] px-4 text-base font-semibold" onClick={() => setPreviewCard(visible[0] ?? null)} disabled={!visible.length}>
            <Eye size={18} aria-hidden /> {t("preview")}
          </button>
        </div>
      </div>

      {selected.size > 0 && (
        <div className="card flex flex-wrap items-center gap-3 p-4 rounded-2xl shadow-card">
          <span className="badge badge-accent py-1 px-3 text-base font-bold">{selected.size}</span>
          <button
            type="button"
            className="btn btn-secondary min-h-[2.5rem] px-4 text-sm font-semibold flex items-center gap-1.5"
            onClick={handleSwapSelected}
            title="Поменять местами стороны выбранных карточек"
          >
            <RefreshCcw size={15} aria-hidden />
            Поменять стороны ({selected.size})
          </button>
          <button className="btn btn-danger min-h-[2.5rem] px-4 text-sm font-semibold" onClick={() => bulkDeleteMut.mutate([...selected])}>
            <Trash2 size={16} aria-hidden /> {t("delete")}
          </button>
          <select
            className="select w-auto min-h-[2.5rem] text-sm rounded-xl"
            defaultValue=""
            onChange={(e) => {
              const target = mySets.data?.find((s) => s.id === e.target.value);
              if (target) moveMut.mutate({ ids: [...selected], targetSetId: target.id, targetVersion: target.content_version });
            }}
            aria-label="Перенести в набор"
          >
            <option value="">Перенести в…</option>
            {(mySets.data ?? []).filter((s) => s.id !== setId).map((s) => (
              <option key={s.id} value={s.id}>{s.title}</option>
            ))}
          </select>
          <button className="btn btn-ghost min-h-[2.5rem] px-4 text-sm font-semibold" onClick={() => setSelected(new Set())}>
            {t("cancel")}
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={20} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" aria-hidden />
          <input className="input h-12 pl-11 text-base rounded-2xl" placeholder={t("search_placeholder")} value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        <button
          type="button"
          className="btn btn-secondary min-h-[3rem] px-5 text-base font-bold rounded-2xl shadow-sm border border-[var(--border)] flex items-center gap-2"
          onClick={handleSwapAll}
          disabled={swapMut.isPending || !cards.length}
          title="Поменять местами вопрос и ответ для всех карточек"
        >
          <RefreshCcw size={18} className={swapMut.isPending ? "animate-spin" : ""} aria-hidden />
          Поменять стороны у всех
        </button>
        <button
          type="button"
          className="btn btn-secondary min-h-[3rem] px-5 text-base font-bold rounded-2xl shadow-sm border border-[var(--border)] flex items-center gap-2"
          onClick={() => setShowQuizletImport(true)}
          title="Импорт карточек из Quizlet"
        >
          <Sparkles size={18} className="text-amber-500" aria-hidden />
          Импорт из Quizlet
        </button>
        <button className="btn btn-primary min-h-[3rem] px-6 text-base font-bold rounded-2xl shadow-md" onClick={() => void addCard()}>
          <Plus size={18} aria-hidden /> {t("add_card")}
        </button>
      </div>

      {/* Карточки */}
      <div className="space-y-4">
        {visible.map((card, idx) => (
          <div
            key={card.id}
            className="card p-5 sm:p-6 rounded-3xl shadow-card hover:shadow-card-hover border border-[var(--border)] transition-all duration-200"
            draggable
            onDragStart={() => (dragId.current = card.id)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => onDrop(card.id)}
          >
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-3.5 h-5 w-5 rounded-md accent-[var(--accent)] cursor-pointer"
                checked={selected.has(card.id)}
                onChange={(e) => {
                  const next = new Set(selected);
                  if (e.target.checked) next.add(card.id);
                  else next.delete(card.id);
                  setSelected(next);
                }}
                aria-label={`Выбрать карточку ${idx + 1}`}
              />
              <GripVertical size={20} className="mt-3.5 cursor-grab text-[var(--text-muted)]" aria-hidden />
              <div className="grid min-w-0 flex-1 gap-4 md:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-sm font-bold text-[var(--text-muted)]" htmlFor={`front-${card.id}`}>
                    {t("front")}
                  </label>
                  <textarea
                    id={`front-${card.id}`}
                    className="textarea min-h-[5.5rem] text-base sm:text-lg p-3.5 rounded-2xl leading-relaxed"
                    rows={2}
                    value={card.front_text}
                    onChange={(e) => updateCard(card.id, "front_text", e.target.value)}
                  />
                  {(card.front_media.length > 0) && (
                    <div className="mt-2 flex gap-2">
                      {card.front_media.map((m) => (
                        <MediaChip key={m.id} mediaId={m.id} mime={m.mime_type} onRemove={() => void detachMedia(card, m.id)} />
                      ))}
                    </div>
                  )}
                </div>
                <div>
                  <label className="mb-1.5 block text-sm font-bold text-[var(--text-muted)]" htmlFor={`back-${card.id}`}>
                    {t("back")}
                  </label>
                  <textarea
                    id={`back-${card.id}`}
                    className="textarea min-h-[5.5rem] text-base sm:text-lg p-3.5 rounded-2xl leading-relaxed"
                    rows={2}
                    value={card.back_text}
                    onChange={(e) => updateCard(card.id, "back_text", e.target.value)}
                  />
                  {(card.back_media.length > 0) && (
                    <div className="mt-2 flex gap-2">
                      {card.back_media.map((m) => (
                        <MediaChip key={m.id} mediaId={m.id} mime={m.mime_type} onRemove={() => void detachMedia(card, m.id)} />
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div className="flex flex-col items-center gap-1.5 pt-1">
                <input
                  className="input w-14 h-9 px-1 text-center text-sm font-bold rounded-xl"
                  value={idx + 1}
                  aria-label="Позиция"
                  onChange={(e) => moveToPosition(card, e.target.value)}
                />
                <button className="btn btn-ghost h-9 w-9 p-0 rounded-xl" onClick={() => move(card, -1)} disabled={idx === 0} aria-label={t("move_up")}>
                  <ArrowUp size={16} aria-hidden />
                </button>
                <button className="btn btn-ghost h-9 w-9 p-0 rounded-xl" onClick={() => move(card, 1)} disabled={idx === visible.length - 1} aria-label={t("move_down")}>
                  <ArrowDown size={16} aria-hidden />
                </button>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2 pt-2 border-t border-[var(--border)]">
              <button className="btn btn-ghost min-h-[2.25rem] px-3.5 text-sm font-medium rounded-xl" onClick={() => setExpanded(expanded === card.id ? null : card.id)}>
                {expanded === card.id ? t("close") : t("preview")}
              </button>
              <button className="btn btn-ghost min-h-[2.25rem] px-3.5 text-sm font-medium rounded-xl" onClick={() => void attachMedia(card, "front")}>
                <ImagePlus size={15} aria-hidden /> Медиа →
              </button>
              <button className="btn btn-ghost min-h-[2.25rem] px-3.5 text-sm font-medium rounded-xl" onClick={() => void attachMedia(card, "back")}>
                <ImagePlus size={15} aria-hidden /> Медиа ←
              </button>
              <button
                type="button"
                className="btn btn-ghost min-h-[2.25rem] px-3.5 text-sm font-medium rounded-xl"
                onClick={() => {
                  setCards((prev) =>
                    prev.map((c) => {
                      if (c.id !== card.id) return c;
                      return {
                        ...c,
                        front_text: c.back_text,
                        back_text: c.front_text,
                        front_context: c.back_context,
                        back_context: c.front_context,
                        front_hint: c.back_hint,
                        back_hint: c.front_hint,
                        front_media: c.back_media,
                        back_media: c.front_media,
                        front_language: c.back_language,
                        back_language: c.front_language,
                        dirty: true,
                      };
                    })
                  );
                }}
                title={t("swap_sides")}
              >
                <RefreshCcw size={15} aria-hidden /> {t("swap_sides")}
              </button>
              <button className="btn btn-ghost min-h-[2.25rem] px-3.5 text-sm font-medium rounded-xl" onClick={() => void duplicate(card)}>
                {t("duplicate_card")}
              </button>
              <button className="btn btn-ghost min-h-[2.25rem] px-3.5 text-sm font-medium rounded-xl" onClick={() => void removeCard(card)} style={{ color: "var(--danger)" }}>
                <Trash2 size={15} aria-hidden /> {t("delete_card")}
              </button>
              {lastUndeleted && (
                <button className="btn btn-ghost min-h-[2.25rem] px-3.5 text-sm font-medium rounded-xl" onClick={undoDelete}>
                  {t("retry")}
                </button>
              )}
            </div>

            {expanded === card.id && (
              <div className="mt-4 p-5 rounded-2xl bg-[var(--surface-2)]/50 border border-[var(--border)] grid gap-4 md:grid-cols-2">
                <Field label={t("question")} value={card.front_context} onChange={(v) => updateCard(card.id, "front_context", v)} />
                <Field label={t("answer")} value={card.back_context} onChange={(v) => updateCard(card.id, "back_context", v)} />
                <Field label={t("hint")} value={card.front_hint} onChange={(v) => updateCard(card.id, "front_hint", v)} />
                <Field label={t("explanation")} value={card.back_explanation} onChange={(v) => updateCard(card.id, "back_explanation", v)} />
                <Field label="Пример" value={card.back_example} onChange={(v) => updateCard(card.id, "back_example", v)} />
                <Field
                  label="Допустимые ответы (через | )"
                  value={card.accepted_back.join(" | ")}
                  onChange={(v) =>
                    updateCard(card.id, "accepted_back", v.split("|").map((s) => s.trim()).filter(Boolean))
                  }
                />
                <label className="flex items-center gap-3 text-base font-medium cursor-pointer">
                  <input
                    type="checkbox"
                    className="h-5 w-5 rounded-md accent-[var(--accent)] cursor-pointer"
                    checked={card.written_check_back}
                    onChange={(e) => updateCard(card.id, "written_check_back", e.target.checked)}
                  />
                  Письменная проверка ответа
                </label>
                <label className="flex items-center gap-3 text-base font-medium cursor-pointer">
                  <input
                    type="checkbox"
                    className="h-5 w-5 rounded-md accent-[var(--accent)] cursor-pointer"
                    checked={card.enabled_back_to_front}
                    onChange={(e) => updateCard(card.id, "enabled_back_to_front", e.target.checked)}
                  />
                  Разрешить обратное направление
                </label>
              </div>
            )}
          </div>
        ))}
      </div>

      {visible.length === 0 && (
        <div className="card p-10 text-center rounded-3xl shadow-card border border-[var(--border)]">
          <p className="text-lg text-[var(--text-muted)]">{filter ? t("not_found") : t("add_card")}</p>
        </div>
      )}

      {/* Добавление и импорт карточек внизу списка */}
      <div className="flex flex-wrap items-center justify-center gap-4 pt-4 pb-8">
        <button
          type="button"
          className="btn btn-primary min-h-[3.25rem] px-8 text-base font-bold rounded-2xl shadow-md flex items-center gap-2"
          onClick={() => void addCard()}
        >
          <Plus size={20} aria-hidden /> {t("add_card")}
        </button>
        <button
          type="button"
          className="btn btn-secondary min-h-[3.25rem] px-8 text-base font-bold rounded-2xl shadow-sm border border-[var(--border)] flex items-center gap-2"
          onClick={() => setShowQuizletImport(true)}
        >
          <Sparkles size={20} className="text-amber-500" aria-hidden />
          Импорт из Quizlet
        </button>
      </div>

      {/* Конфликт версий */}
      {conflict && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="alertdialog" aria-modal="true">
          <div className="card w-full max-w-lg p-7 rounded-3xl shadow-modal border border-[var(--border)]">
            <h2 className="mb-3 flex items-center gap-2 text-2xl font-bold">
              <Sparkles size={22} aria-hidden /> {t("conflict_title")}
            </h2>
            <p className="text-base text-[var(--text-muted)] leading-relaxed">{t("conflict_message")}</p>
            <div className="mt-4 rounded-2xl p-4 text-base" style={{ background: "var(--surface-2)" }}>
              <div className="font-semibold">Ваш текст сохранён на экране:</div>
              <div className="mt-1 text-[var(--text-muted)]">{conflict.local.front_text || "—"} → {conflict.local.back_text || "—"}</div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button
                className="btn btn-secondary min-h-[3rem] px-5 text-base font-semibold rounded-2xl"
                onClick={async () => {
                  // Создать копию правок: новый набор с текущим текстом карточки
                  const newSet = await api<{ id: string }>("/sets", {
                    body: { title: `${setQ.data?.title} (правки)`, description: "" },
                  });
                  await api(`/sets/${newSet.id}/cards/batch`, {
                    body: {
                      cards: cards.filter((c) => !c._local).map((c) => ({
                        front_text: c.front_text,
                        back_text: c.back_text,
                        accepted_front: c.accepted_front,
                        accepted_back: c.accepted_back,
                      })),
                    },
                  });
                  navigate(`/sets/${newSet.id}`);
                }}
              >
                {t("copy")}
              </button>
              <button
                className="btn btn-primary min-h-[3rem] px-5 text-base font-bold rounded-2xl shadow-md"
                onClick={async () => {
                  initialized.current = false;
                  await qc.invalidateQueries({ queryKey: ["cards", setId] });
                  await qc.invalidateQueries({ queryKey: ["set", setId] });
                  setConflict(null);
                }}
              >
                {t("reload")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Предпросмотр */}
      {previewCard && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" onClick={() => setPreviewCard(null)}>
          <div className="study-card max-w-xl w-full p-8 sm:p-10 rounded-3xl shadow-modal border border-[var(--border)]" onClick={(e) => e.stopPropagation()}>
            <div className="text-2xl sm:text-3xl font-bold">{previewCard.front_text}</div>
            <hr className="my-5 border-[var(--border)]" />
            <div className="text-2xl sm:text-3xl font-bold text-[var(--accent)]">{previewCard.back_text}</div>
            {previewCard.back_explanation && (
              <p className="mt-4 text-base text-[var(--text-muted)] leading-relaxed">{previewCard.back_explanation}</p>
            )}
            <button className="btn btn-secondary min-h-[3rem] text-base font-bold rounded-2xl mt-8 w-full shadow-sm" onClick={() => setPreviewCard(null)}>
              {t("close")}
            </button>
          </div>
        </div>
      )}

      {/* Модальное окно импорта из Quizlet */}
      {showQuizletImport && (
        <QuizletImportModal
          onClose={() => setShowQuizletImport(false)}
          onAddCards={onAddCardsFromQuizlet}
        />
      )}
    </div>
  );
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="mb-1.5 block text-sm font-semibold text-[var(--text-muted)]">{label}</label>
      <textarea className="textarea min-h-[3rem] text-base rounded-xl p-3" rows={1} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function MediaChip({ mediaId, mime, onRemove }: { mediaId: string; mime: string; onRemove: () => void }) {
  const isImage = mime.startsWith("image/");
  return (
    <div className="relative inline-block">
      {isImage ? (
        <img
          src={`/api/v1/media/${mediaId}`}
          alt=""
          className="h-14 w-14 rounded-xl border border-[var(--border)] object-cover shadow-sm"
        />
      ) : (
        <audio controls src={`/api/v1/media/${mediaId}`} className="h-9" />
      )}
      <button
        className="absolute -right-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full shadow"
        style={{ background: "var(--danger)", color: "#fff" }}
        onClick={onRemove}
        aria-label="Убрать медиа"
      >
        <X size={12} aria-hidden />
      </button>
    </div>
  );
}
