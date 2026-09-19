import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Archive, BookOpen, Copy, LayoutGrid, Layers, List, ListChecks, Pencil, Share2,
  Shuffle, SpellCheck, Star, Type, Download, Edit3, Trash2, RefreshCcw, RefreshCw, Volume2,
} from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";
import { cardsLabel } from "../i18n";
import { speak } from "../lib/tts";
import type { SetItem } from "./Sets";
import { ShareDialog } from "../components/ShareDialog";

export interface CardDto {
  id: string;
  set_id: string;
  position: number;
  content_version: number;
  front_text: string;
  back_text: string;
  front_context: string;
  back_context: string;
  front_hint: string;
  back_hint: string;
  front_explanation: string;
  back_explanation: string;
  front_example: string;
  back_example: string;
  front_language: string | null;
  back_language: string | null;
  enabled_front_to_back: boolean;
  enabled_back_to_front: boolean;
  written_check_front: boolean;
  written_check_back: boolean;
  accepted_front: string[];
  accepted_back: string[];
  front_media: Array<{ id: string; media_type: string; mime_type: string; description: string }>;
  back_media: Array<{ id: string; media_type: string; mime_type: string; description: string }>;
  is_starred: boolean;
}

interface SetDetailDto extends SetItem {
  created_at: string;
  viewer_role: string;
  folders: string[];
}

export function SetDetailPage() {
  const { setId } = useParams<{ setId: string }>();
  const { t, locale, prefs } = useApp();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [view, setView] = useState<"tiles" | "list">("list");
  const [showShare, setShowShare] = useState(false);
  const [showEditMeta, setShowEditMeta] = useState(false);

  const setQ = useQuery({
    queryKey: ["set", setId],
    queryFn: () => api<SetDetailDto>(`/sets/${setId}`),
  });
  const cardsQ = useQuery({
    queryKey: ["cards", setId],
    queryFn: () => api<{ items: CardDto[]; total: number; set_content_version: number }>(`/sets/${setId}/cards?page_size=200`),
  });

  const favoriteMut = useMutation({
    mutationFn: (enabled: boolean) => api(`/sets/${setId}/favorite`, { method: "PUT", body: { enabled } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["set", setId] }),
  });
  const archiveMut = useMutation({
    mutationFn: (archived: boolean) => api(`/sets/${setId}/${archived ? "archive" : "restore"}`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["set", setId] });
      qc.invalidateQueries({ queryKey: ["sets"] });
    },
  });
  const copyMut = useMutation({
    mutationFn: () => api<{ id: string }>(`/sets/${setId}/copy`, { method: "POST" }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["sets"] });
      navigate(`/sets/${data.id}`);
    },
  });
  const deleteMut = useMutation({
    mutationFn: () => api(`/sets/${setId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sets"] });
      navigate("/sets");
    },
  });
  const patchMetaMut = useMutation({
    mutationFn: (patch: { title: string; description: string; front_language: string; back_language: string }) =>
      api(`/sets/${setId}`, {
        method: "PATCH",
        body: {
          ...patch,
          expected_content_version: setQ.data?.content_version,
        },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["set", setId] });
      qc.invalidateQueries({ queryKey: ["sets"] });
      setShowEditMeta(false);
    },
  });
  const starCardMut = useMutation({
    mutationFn: ({ cardId, starred }: { cardId: string; starred: boolean }) =>
      api(`/cards/${cardId}/star`, { method: "PUT", body: { enabled: starred, starred } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cards", setId] }),
  });
  const swapSidesMut = useMutation({
    mutationFn: () =>
      api(`/sets/${setId}/cards/swap-sides`, {
        body: { expected_content_version: setQ.data?.content_version },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["set", setId] });
      void qc.invalidateQueries({ queryKey: ["cards", setId] });
    },
  });
  const swapCardSidesMut = useMutation({
    mutationFn: (cardId: string) =>
      api(`/sets/${setId}/cards/${cardId}/swap-sides`, { method: "POST" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["set", setId] });
      void qc.invalidateQueries({ queryKey: ["cards", setId] });
    },
  });

  if (setQ.isLoading) {
    return (
      <div className="mx-auto max-w-6xl space-y-4">
        <div className="skeleton h-10 w-80" />
        <div className="skeleton h-40" />
      </div>
    );
  }
  if (setQ.isError || !setQ.data) {
    return (
      <div className="card mx-auto max-w-4xl p-12 text-center">
        <p className="text-xl font-bold">{t("not_found")}</p>
        <Link to="/sets" className="btn btn-secondary mt-5">
          {t("nav_sets")}
        </Link>
      </div>
    );
  }

  const s = setQ.data;
  const isOwner = s.viewer_role === "owner";
  const modes = [
    { mode: "cards", icon: LayoutGrid, enabled: (cardsQ.data?.total ?? 0) >= 1 },
    { mode: "learn", icon: Layers, enabled: (cardsQ.data?.total ?? 0) >= 1 },
    { mode: "write", icon: Type, enabled: (cardsQ.data?.total ?? 0) >= 1 },
    { mode: "spell", icon: SpellCheck, enabled: (cardsQ.data?.total ?? 0) >= 1 },
    { mode: "test", icon: ListChecks, enabled: (cardsQ.data?.total ?? 0) >= 1 },
    { mode: "match", icon: Shuffle, enabled: (cardsQ.data?.total ?? 0) >= 2 },
  ];

  const startStudy = (mode: string) => {
    if (mode === "match" && (cardsQ.data?.total ?? 0) < 6) {
      navigate(`/study/new?set=${setId}&mode=match`);
      return;
    }
    navigate(`/study/new?set=${setId}&mode=${mode}`);
  };

  return (
    <div className="mx-auto max-w-6xl space-y-8">
      {/* Header section with Metadata and Operations */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-2xl">
          <h1 className="text-3xl font-black tracking-tight sm:text-4xl">{s.title}</h1>
          {s.description && (
            <p className="mt-2 text-base text-[var(--text-muted)] leading-relaxed">{s.description}</p>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2.5 text-sm text-[var(--text-muted)]">
            <span className="badge badge-accent font-semibold">{cardsLabel(locale, s.card_count)}</span>
            <span className="badge">
              {s.front_language || "?"} → {s.back_language || "?"}
            </span>
            <span className="badge">{t(`visibility_${s.visibility}` as never)}</span>
            {s.is_admin_created && !s.is_own && (
              <span className="badge badge-primary font-semibold">🔒 Назначено администратором</span>
            )}
            {!s.is_own && <span className="text-xs">{t("owner")}: {s.owner_username}</span>}
            {s.tags.map((tag) => (
              <span key={tag} className="badge">
                {tag}
              </span>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap gap-2.5">
          {isOwner && (
            <button id="btn-edit-details" className="btn btn-secondary" onClick={() => setShowEditMeta(true)}>
              <Edit3 size={18} aria-hidden /> Изменить
            </button>
          )}
          {isOwner ? (
            <Link to={`/sets/${setId}/edit`} className="btn btn-primary">
              <Pencil size={18} aria-hidden /> {t("editor_title")}
            </Link>
          ) : null}
          <button id="btn-copy-set" className="btn btn-secondary" onClick={() => copyMut.mutate()} disabled={copyMut.isPending}>
            <Copy size={18} aria-hidden /> {t("copy")}
          </button>
          {s.in_library && (
            <button
              id="btn-favorite-set"
              className="btn btn-secondary"
              onClick={() => favoriteMut.mutate(!s.is_favorite)}
              aria-pressed={s.is_favorite}
            >
              <Star
                size={18}
                aria-hidden
                style={{
                  color: s.is_favorite ? "var(--warning)" : undefined,
                  fill: s.is_favorite ? "var(--warning)" : "none",
                }}
              />
              {s.is_favorite ? t("unfavorite") : t("favorite")}
            </button>
          )}
          {isOwner && (
            <>
              <button
                id="btn-swap-set"
                className="btn btn-secondary"
                onClick={() => {
                  if (window.confirm(locale === "ru" ? "Поменять местами вопрос и ответ для всех карточек набора?" : "Swap term and definition for all cards in this set?")) {
                    swapSidesMut.mutate();
                  }
                }}
                disabled={swapSidesMut.isPending || !cardsQ.data?.items.length}
                title={t("swap_all_sides")}
              >
                <RefreshCcw size={18} className={swapSidesMut.isPending ? "animate-spin" : ""} aria-hidden /> {t("swap_all_sides")}
              </button>
              <button id="btn-share-set" className="btn btn-secondary" onClick={() => setShowShare(true)}>
                <Share2 size={18} aria-hidden /> {t("nav_discover")}
              </button>
              <button
                id="btn-archive-set"
                className="btn btn-secondary"
                onClick={() => archiveMut.mutate(!s.archived)}
                disabled={archiveMut.isPending}
              >
                <Archive size={18} aria-hidden /> {s.archived ? t("restore") : t("archive")}
              </button>
              <button
                id="btn-delete-set"
                className="btn btn-danger"
                onClick={() => {
                  if (window.confirm("Удалить этот набор?")) {
                    deleteMut.mutate();
                  }
                }}
                disabled={deleteMut.isPending}
              >
                <Trash2 size={18} aria-hidden /> {t("delete")}
              </button>
            </>
          )}
          <a className="btn btn-secondary" href={`/api/v1/sets/${setId}/export?format=json`} download>
            <Download size={18} aria-hidden /> JSON
          </a>
        </div>
      </div>

      {s.archived && (
        <div className="rounded-xl px-5 py-4 text-base font-medium shadow-sm" style={{ background: "var(--warning-soft)", color: "var(--warning)" }}>
          ⚠️ Набор в архиве: новые занятия недоступны.
        </div>
      )}

      {/* Study Modes Grid */}
      <section aria-label={t("modes")} className="space-y-3">
        <h2 className="text-xl font-bold tracking-tight sm:text-2xl">{t("modes")}</h2>
        <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-6">
          {modes.map((m) => (
            <button
              key={m.mode}
              className="card group flex flex-col items-center gap-3 p-5 text-center transition-all hover:border-[var(--accent)] hover:shadow-md disabled:opacity-40"
              onClick={() => startStudy(m.mode)}
              disabled={!m.enabled || s.archived}
              title={m.enabled ? t(`mode_${m.mode}` as never) : "Недостаточно карточек"}
            >
              <div
                className="flex h-13 w-13 items-center justify-center rounded-2xl transition-transform group-hover:scale-110"
                style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
              >
                <m.icon size={26} aria-hidden />
              </div>
              <span className="text-base font-bold">{t(`mode_${m.mode}` as never)}</span>
            </button>
          ))}
        </div>
      </section>

      {/* Cards List Section */}
      <section aria-label={t("answers") === t("answers") ? t("cards_count") : t("cards_count")} className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-bold tracking-tight sm:text-2xl">
            {t("cards_count")} ({cardsQ.data?.total ?? 0})
          </h2>
          <div className="flex items-center gap-2.5">
            {isOwner && (
              <button
                type="button"
                className="btn btn-secondary min-h-[2.4rem] px-3 text-sm font-semibold rounded-xl flex items-center gap-1.5"
                onClick={() => {
                  if (
                    window.confirm(
                      locale === "ru"
                        ? "Поменять местами вопрос и ответ для всех карточек набора?"
                        : "Swap term and definition for all cards in this set?"
                    )
                  ) {
                    swapSidesMut.mutate();
                  }
                }}
                disabled={swapSidesMut.isPending || !cardsQ.data?.items.length}
                title="Поменять местами вопрос и ответ для всех карточек"
              >
                <RefreshCcw size={15} className={swapSidesMut.isPending ? "animate-spin" : ""} aria-hidden />
                {t("swap_all_sides")}
              </button>
            )}
            <div className="flex" role="group">
              <button
                className={`btn ${view === "list" ? "btn-primary" : "btn-secondary"} rounded-r-none px-3.5`}
                onClick={() => setView("list")}
                aria-pressed={view === "list"}
                aria-label="Список"
              >
                <List size={18} aria-hidden />
              </button>
              <button
                className={`btn ${view === "tiles" ? "btn-primary" : "btn-secondary"} rounded-l-none px-3.5`}
                onClick={() => setView("tiles")}
                aria-pressed={view === "tiles"}
                aria-label="Плитки"
              >
                <BookOpen size={18} aria-hidden />
              </button>
            </div>
          </div>
        </div>

        {cardsQ.isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="skeleton h-16" />
            ))}
          </div>
        ) : (cardsQ.data?.total ?? 0) === 0 ? (
          <div className="card p-10 text-center text-base text-[var(--text-muted)]">
            {t("no_cards_yet")}{" "}
            {isOwner && (
              <Link to={`/sets/${setId}/edit`} className="font-semibold underline" style={{ color: "var(--accent)" }}>
                Добавить в редакторе →
              </Link>
            )}
          </div>
        ) : view === "list" ? (
          <ol className="space-y-3">
            {cardsQ.data!.items.map((c, i) => (
              <li
                key={c.id}
                className="card flex items-center justify-between gap-4 p-4 transition-all hover:border-[var(--border-hover)]"
              >
                <div className="flex items-center gap-4 flex-1 min-w-0">
                  <span className="w-8 text-center text-sm font-semibold text-[var(--text-muted)]">{i + 1}</span>
                  <div className="grid flex-1 grid-cols-1 sm:grid-cols-2 gap-4 text-base py-0.5">
                    <div className="flex items-start justify-between gap-2 min-w-0">
                      <span className="font-medium text-[var(--text)] break-words whitespace-pre-wrap">{c.front_text}</span>
                      <button
                        type="button"
                        className="btn btn-ghost p-1 text-[var(--text-muted)] hover:text-[var(--text)] shrink-0"
                        onClick={() => speak(c.front_text, { lang: c.front_language || s.front_language || undefined, rate: prefs?.tts_rate, volume: prefs?.volume })}
                        title="Озвучить вопрос"
                        aria-label="Озвучить"
                      >
                        <Volume2 size={15} aria-hidden />
                      </button>
                    </div>
                    <div className="flex items-start justify-between gap-2 min-w-0 sm:border-l sm:pl-4">
                      <span className="text-[var(--text-muted)] break-words whitespace-pre-wrap">{c.back_text}</span>
                      <button
                        type="button"
                        className="btn btn-ghost p-1 text-[var(--text-muted)] hover:text-[var(--text)] shrink-0"
                        onClick={() => speak(c.back_text, { lang: c.back_language || s.back_language || undefined, rate: prefs?.tts_rate, volume: prefs?.volume })}
                        title="Озвучить ответ"
                        aria-label="Озвучить"
                      >
                        <Volume2 size={15} aria-hidden />
                      </button>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {isOwner && (
                    <button
                      type="button"
                      className="btn btn-ghost p-2 text-[var(--text-muted)] hover:text-[var(--text)]"
                      onClick={() => swapCardSidesMut.mutate(c.id)}
                      disabled={swapCardSidesMut.isPending && swapCardSidesMut.variables === c.id}
                      title="Поменять местами стороны этой карточки"
                      aria-label="Поменять местами"
                    >
                      <RefreshCw size={16} className={swapCardSidesMut.isPending && swapCardSidesMut.variables === c.id ? "animate-spin" : ""} aria-hidden />
                    </button>
                  )}
                  <button
                    className="btn btn-ghost p-2 card-star-btn shrink-0"
                    onClick={() => starCardMut.mutate({ cardId: c.id, starred: !c.is_starred })}
                    aria-label={c.is_starred ? "Убрать звезду" : "Отметить звёздочкой"}
                    aria-pressed={c.is_starred}
                    title={c.is_starred ? "Убрать звезду" : "Отметить звёздочкой"}
                  >
                    <Star
                      size={20}
                      style={{
                        color: c.is_starred ? "var(--warning)" : "var(--text-muted)",
                        fill: c.is_starred ? "var(--warning)" : "none",
                      }}
                      aria-hidden
                    />
                  </button>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {cardsQ.data!.items.map((c) => (
              <div key={c.id} className="card p-5 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-base font-bold text-[var(--text)]">{c.front_text}</div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      className="btn btn-ghost p-1 text-[var(--text-muted)] hover:text-[var(--text)]"
                      onClick={() => speak(c.front_text, { lang: c.front_language || s.front_language || undefined, rate: prefs?.tts_rate, volume: prefs?.volume })}
                      title="Озвучить вопрос"
                    >
                      <Volume2 size={15} aria-hidden />
                    </button>
                    {isOwner && (
                      <button
                        type="button"
                        className="btn btn-ghost p-1 text-[var(--text-muted)] hover:text-[var(--text)]"
                        onClick={() => swapCardSidesMut.mutate(c.id)}
                        disabled={swapCardSidesMut.isPending && swapCardSidesMut.variables === c.id}
                        title="Поменять местами стороны карточки"
                      >
                        <RefreshCw size={15} className={swapCardSidesMut.isPending && swapCardSidesMut.variables === c.id ? "animate-spin" : ""} aria-hidden />
                      </button>
                    )}
                  </div>
                </div>
                <div className="flex items-center justify-between gap-2 border-t pt-2">
                  <div className="text-base text-[var(--text-muted)]">{c.back_text}</div>
                  <button
                    type="button"
                    className="btn btn-ghost p-1 text-[var(--text-muted)] hover:text-[var(--text)] shrink-0"
                    onClick={() => speak(c.back_text, { lang: c.back_language || s.back_language || undefined, rate: prefs?.tts_rate, volume: prefs?.volume })}
                    title="Озвучить ответ"
                  >
                    <Volume2 size={15} aria-hidden />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {showShare && <ShareDialog setId={setId!} onClose={() => setShowShare(false)} />}
      {showEditMeta && (
        <EditMetadataDialog
          set={s}
          onClose={() => setShowEditMeta(false)}
          onSave={(data) => patchMetaMut.mutate(data)}
          isPending={patchMetaMut.isPending}
        />
      )}
    </div>
  );
}

function EditMetadataDialog({
  set,
  onClose,
  onSave,
  isPending,
}: {
  set: SetDetailDto;
  onClose: () => void;
  onSave: (data: { title: string; description: string; front_language: string; back_language: string }) => void;
  isPending: boolean;
}) {
  const { t } = useApp();
  const [title, setTitle] = useState(set.title);
  const [description, setDescription] = useState(set.description || "");
  const [frontLang, setFrontLang] = useState(set.front_language || "");
  const [backLang, setBackLang] = useState(set.back_language || "");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (title.trim()) {
      onSave({
        title: title.trim(),
        description: description.trim(),
        front_language: frontLang.trim().toLowerCase(),
        back_language: backLang.trim().toLowerCase(),
      });
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0, 0, 0, 0.5)" }}
      role="dialog"
      aria-modal="true"
      aria-label="Редактировать набор"
    >
      <div className="card w-full max-w-lg p-7 shadow-2xl" onKeyDown={(e) => e.key === "Escape" && onClose()}>
        <h2 className="mb-5 text-xl font-bold">Редактировать набор</h2>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label htmlFor="edit-set-title" className="mb-1.5 block text-sm font-semibold">
              Название *
            </label>
            <input
              id="edit-set-title"
              className="input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              maxLength={300}
            />
          </div>
          <div>
            <label htmlFor="edit-set-desc" className="mb-1.5 block text-sm font-semibold">
              Описание
            </label>
            <textarea
              id="edit-set-desc"
              className="textarea"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="edit-set-flang" className="mb-1.5 block text-sm font-semibold">
                Язык стороны вопроса
              </label>
              <input
                id="edit-set-flang"
                className="input"
                value={frontLang}
                onChange={(e) => setFrontLang(e.target.value)}
                placeholder="en"
                maxLength={10}
              />
            </div>
            <div>
              <label htmlFor="edit-set-blang" className="mb-1.5 block text-sm font-semibold">
                Язык стороны ответа
              </label>
              <input
                id="edit-set-blang"
                className="input"
                value={backLang}
                onChange={(e) => setBackLang(e.target.value)}
                placeholder="ru"
                maxLength={10}
              />
            </div>
          </div>
          <div className="mt-6 flex justify-end gap-3 pt-2">
            <button type="button" className="btn btn-secondary" onClick={onClose}>
              {t("cancel")}
            </button>
            <button type="submit" className="btn btn-primary" disabled={isPending}>
              {isPending ? t("loading") : t("save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
