import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  Archive,
  ChevronLeft,
  ChevronRight,
  FileText,
  Folder as FolderIcon,
  FolderPlus,
  Layers,
  LayoutGrid,
  List,
  Plus,
  Search,
  Star,
  Upload,
  X,
} from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";
import { cardsLabel, formatDate } from "../i18n";
import { ImportDialog } from "../components/ImportDialog";
import { CreateSetDialog } from "../components/CreateSetDialog";

export interface SetItem {
  id: string;
  title: string;
  description: string;
  front_language: string;
  back_language: string;
  visibility: string;
  archived: boolean;
  tags: string[];
  card_count: number;
  owner_username: string;
  is_own: boolean;
  is_favorite: boolean;
  in_library: boolean;
  in_folder_id: string | null;
  last_studied_at: string | null;
  updated_at: string;
  content_version: number;
  is_admin_created?: boolean;
}

interface Folder {
  id: string;
  name: string;
  set_count: number;
  created_by_admin?: boolean;
}

export function SetsPage() {
  const { t, locale } = useApp();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [sort, setSort] = useState("updated");
  const [archived, setArchived] = useState(false);
  const [view, setView] = useState<"grid" | "list">("grid");
  const [showNewFolder, setShowNewFolder] = useState(false);

  useEffect(() => {
    const id = setTimeout(() => setDebouncedQ(q), 350);
    return () => clearTimeout(id);
  }, [q]);

  // Запрос всех доступных пользователю папок
  const folders = useQuery({
    queryKey: ["folders"],
    queryFn: () => api<Folder[]>("/folders"),
  });

  // Запрос всех наборов для подсчета общих и нераспределенных наборов
  const allSetsSummary = useQuery({
    queryKey: ["sets", "summary-counts"],
    queryFn: () => api<SetItem[]>("/sets?page_size=200"),
  });

  // Определение активной вкладки папки
  const folderParam = params.get("folder");
  const activeFolderId =
    folderParam !== null
      ? folderParam
      : (folders.data?.[0]?.id ?? "all");

  const selectFolder = (fid: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("folder", fid);
      return next;
    });
  };

  // Horizontal scroll controller for folder tabs
  const tabsContainerRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const isDraggingRef = useRef(false);
  const startXRef = useRef(0);
  const scrollLeftStartRef = useRef(0);
  const hasMovedRef = useRef(false);

  const updateScrollState = useCallback(() => {
    const el = tabsContainerRef.current;
    if (!el) return;
    const { scrollLeft, scrollWidth, clientWidth } = el;
    setCanScrollLeft(scrollLeft > 4);
    setCanScrollRight(scrollLeft < scrollWidth - clientWidth - 4);
  }, []);

  useEffect(() => {
    const el = tabsContainerRef.current;
    if (!el) return;

    updateScrollState();
    el.addEventListener("scroll", updateScrollState, { passive: true });

    const ro = new ResizeObserver(updateScrollState);
    ro.observe(el);

    const onWheel = (e: WheelEvent) => {
      // If user scrolls vertically with mouse wheel, convert to horizontal scroll smoothly
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && el.scrollWidth > el.clientWidth) {
        e.preventDefault();
        el.scrollLeft += e.deltaY;
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });

    return () => {
      el.removeEventListener("scroll", updateScrollState);
      el.removeEventListener("wheel", onWheel);
      ro.disconnect();
    };
  }, [updateScrollState, folders.data]);

  const scrollByDirection = (direction: "left" | "right") => {
    const el = tabsContainerRef.current;
    if (!el) return;
    const offset = direction === "left" ? -260 : 260;
    el.scrollBy({ left: offset, behavior: "smooth" });
  };

  // Auto-scroll active tab into view
  useEffect(() => {
    const el = tabsContainerRef.current;
    if (!el) return;
    const activeTab = el.querySelector('[aria-pressed="true"]');
    if (activeTab && typeof activeTab.scrollIntoView === "function") {
      activeTab.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
    }
  }, [activeFolderId]);

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    const el = tabsContainerRef.current;
    if (!el) return;
    isDraggingRef.current = true;
    setIsDragging(true);
    startXRef.current = e.pageX - el.offsetLeft;
    scrollLeftStartRef.current = el.scrollLeft;
    hasMovedRef.current = false;
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDraggingRef.current) return;
    const el = tabsContainerRef.current;
    if (!el) return;
    e.preventDefault();
    const x = e.pageX - el.offsetLeft;
    const walk = x - startXRef.current;
    if (Math.abs(walk) > 4) {
      hasMovedRef.current = true;
    }
    el.scrollLeft = scrollLeftStartRef.current - walk;
  };

  const handleMouseUp = () => {
    isDraggingRef.current = false;
    setIsDragging(false);
  };

  const sets = useQuery({
    queryKey: ["sets", { q: debouncedQ, sort, archived, folder_id: activeFolderId }],
    queryFn: () => {
      const queryParams = new URLSearchParams({
        sort,
        archived: String(archived),
      });
      if (debouncedQ) queryParams.set("q", debouncedQ);
      if (activeFolderId && activeFolderId !== "all") {
        queryParams.set("folder_id", activeFolderId);
      }
      return api<SetItem[]>(`/sets?${queryParams.toString()}`);
    },
  });

  const totalCount = allSetsSummary.data?.length ?? 0;
  const unassignedCount = allSetsSummary.data
    ? allSetsSummary.data.filter((s) => !s.in_folder_id).length
    : 0;

  const activeFolderObj = folders.data?.find((f) => f.id === activeFolderId);

  const showCreate = params.get("create") === "1";
  const showImport = params.get("import") === "1";

  const closeModals = () => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("create");
      next.delete("import");
      return next;
    });
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      {/* Header with Title and Action buttons */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black tracking-tight sm:text-4xl">{t("nav_sets")}</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">
            {sets.data ? `${sets.data.length} ${t("cards_count")}` : ""}
          </p>
        </div>
        <div className="flex gap-3">
          <button
            className="btn btn-primary"
            onClick={() =>
              setParams((p) => {
                const n = new URLSearchParams(p);
                n.set("create", "1");
                return n;
              })
            }
          >
            <Plus size={20} aria-hidden /> {t("create_set")}
          </button>
          <button
            className="btn btn-secondary"
            onClick={() =>
              setParams((p) => {
                const n = new URLSearchParams(p);
                n.set("import", "1");
                return n;
              })
            }
          >
            <Upload size={20} aria-hidden /> {t("import_sets")}
          </button>
        </div>
      </div>

      {/* Вкладки папок с удобной горизонтальной прокруткой */}
      <div className="space-y-3">
        <div className="relative flex items-center group/tabs">
          {/* Левая стрелка прокрутки */}
          {canScrollLeft && (
            <button
              type="button"
              onClick={() => scrollByDirection("left")}
              className="absolute left-0 z-20 flex h-9 w-9 items-center justify-center rounded-full bg-[var(--surface)] text-[var(--text)] shadow-md border border-[var(--border)] hover:bg-[var(--surface-2)] transition-all cursor-pointer -ml-2"
              title="Прокрутить вкладки влево"
              aria-label="Прокрутить вкладки влево"
            >
              <ChevronLeft size={18} />
            </button>
          )}

          {/* Левый градиентный фейд */}
          {canScrollLeft && (
            <div className="pointer-events-none absolute left-0 top-0 bottom-0 w-10 bg-gradient-to-r from-[var(--bg)] via-[var(--bg)]/80 to-transparent z-10" />
          )}

          {/* Контейнер вкладок */}
          <div
            ref={tabsContainerRef}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            className={`border-b border-[var(--border)] pb-2 overflow-x-auto no-scrollbar scroll-smooth select-none flex-1 flex items-center gap-2 py-1 ${
              isDragging ? "cursor-grabbing" : "cursor-grab"
            }`}
          >
            {folders.data &&
              folders.data.map((f) => {
                const isActive = activeFolderId === f.id;
                return (
                  <button
                    key={f.id}
                    type="button"
                    onClick={(e) => {
                      if (hasMovedRef.current) {
                        e.preventDefault();
                        return;
                      }
                      selectFolder(f.id);
                    }}
                    className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm transition-all cursor-pointer shrink-0 ${
                      isActive
                        ? "bg-[var(--accent)] text-white font-bold shadow-md"
                        : "bg-[var(--surface-2)] text-[var(--text-muted)] hover:bg-[var(--surface-1)] hover:text-[var(--text-main)] font-semibold border border-transparent hover:border-[var(--border)]"
                    }`}
                    aria-pressed={isActive}
                  >
                    <FolderIcon
                      size={17}
                      className={isActive ? "text-white" : "text-[var(--accent)]"}
                    />
                    <span>{f.name}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded-md text-xs font-bold ${
                        isActive
                          ? "bg-white/25 text-white"
                          : "bg-[var(--surface-1)] text-[var(--text-muted)]"
                      }`}
                    >
                      {f.set_count}
                    </span>
                    {f.created_by_admin && (
                      <span title="Назначено администратором" className="text-xs opacity-90">
                        🔒
                      </span>
                    )}
                  </button>
                );
              })}

            {/* Вкладка «Без папки» */}
            {unassignedCount > 0 && (
              <button
                type="button"
                onClick={(e) => {
                  if (hasMovedRef.current) {
                    e.preventDefault();
                    return;
                  }
                  selectFolder("unassigned");
                }}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm transition-all cursor-pointer shrink-0 ${
                  activeFolderId === "unassigned"
                    ? "bg-[var(--accent)] text-white font-bold shadow-md"
                    : "bg-[var(--surface-2)] text-[var(--text-muted)] hover:bg-[var(--surface-1)] hover:text-[var(--text-main)] font-semibold border border-transparent hover:border-[var(--border)]"
                }`}
                aria-pressed={activeFolderId === "unassigned"}
              >
                <FileText size={16} />
                <span>Без папки</span>
                <span
                  className={`px-1.5 py-0.5 rounded-md text-xs font-bold ${
                    activeFolderId === "unassigned"
                      ? "bg-white/25 text-white"
                      : "bg-[var(--surface-1)] text-[var(--text-muted)]"
                  }`}
                >
                  {unassignedCount}
                </span>
              </button>
            )}

            {/* Вкладка «Все наборы» */}
            <button
              type="button"
              onClick={(e) => {
                if (hasMovedRef.current) {
                  e.preventDefault();
                  return;
                }
                selectFolder("all");
              }}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm transition-all cursor-pointer shrink-0 ${
                activeFolderId === "all"
                  ? "bg-[var(--accent)] text-white font-bold shadow-md"
                  : "bg-[var(--surface-2)] text-[var(--text-muted)] hover:bg-[var(--surface-1)] hover:text-[var(--text-main)] font-semibold border border-transparent hover:border-[var(--border)]"
              }`}
              aria-pressed={activeFolderId === "all"}
            >
              <Layers size={16} />
              <span>Все наборы</span>
              <span
                className={`px-1.5 py-0.5 rounded-md text-xs font-bold ${
                  activeFolderId === "all"
                    ? "bg-white/25 text-white"
                    : "bg-[var(--surface-1)] text-[var(--text-muted)]"
                }`}
              >
                {totalCount}
              </span>
            </button>

            {/* Кнопка создания новой папки */}
            <button
              type="button"
              onClick={() => setShowNewFolder(true)}
              className="btn btn-ghost text-xs px-3.5 py-2.5 rounded-xl font-bold flex items-center gap-1.5 border border-dashed border-[var(--border)] hover:border-[var(--accent)] text-[var(--text-muted)] hover:text-[var(--text-main)] shrink-0"
              title="Создать новую папку"
            >
              <FolderPlus size={16} /> Новая папка
            </button>
          </div>

          {/* Правый градиентный фейд */}
          {canScrollRight && (
            <div className="pointer-events-none absolute right-0 top-0 bottom-0 w-10 bg-gradient-to-l from-[var(--bg)] via-[var(--bg)]/80 to-transparent z-10" />
          )}

          {/* Правая стрелка прокрутки */}
          {canScrollRight && (
            <button
              type="button"
              onClick={() => scrollByDirection("right")}
              className="absolute right-0 z-20 flex h-9 w-9 items-center justify-center rounded-full bg-[var(--surface)] text-[var(--text)] shadow-md border border-[var(--border)] hover:bg-[var(--surface-2)] transition-all cursor-pointer -mr-2"
              title="Прокрутить вкладки вправо"
              aria-label="Прокрутить вкладки вправо"
            >
              <ChevronRight size={18} />
            </button>
          )}
        </div>

        {/* Информационная строка активной вкладки/папки */}
        <div className="flex flex-wrap items-center justify-between gap-3 px-1 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-[var(--text-muted)]">Текущая папка:</span>
            <strong className="text-[var(--text-main)] font-bold text-base">
              {activeFolderObj
                ? activeFolderObj.name
                : activeFolderId === "unassigned"
                ? "Без папки"
                : "Все наборы"}
            </strong>
            {activeFolderObj?.created_by_admin && (
              <span className="badge badge-primary text-xs font-semibold">
                🔒 Назначено администратором
              </span>
            )}
            <span className="text-xs text-[var(--text-muted)]">
              ({sets.data ? cardsLabel(locale, sets.data.length) : "..."})
            </span>
          </div>
          {activeFolderObj && (
            <Link
              to="/folders"
              className="text-xs font-bold text-[var(--accent)] hover:underline flex items-center gap-1"
            >
              Управление папками в разделе «Папки» →
            </Link>
          )}
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-64 flex-1">
          <Search
            size={20}
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
            aria-hidden
          />
          <input
            className="input pl-11"
            placeholder={
              activeFolderObj
                ? `Поиск в папке «${activeFolderObj.name}»...`
                : t("search_placeholder")
            }
            value={q}
            onChange={(e) => setQ(e.target.value)}
            aria-label={t("search_placeholder")}
          />
        </div>
        <select
          className="select w-auto"
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          aria-label={t("sort_updated")}
        >
          <option value="updated">{t("sort_updated")}</option>
          <option value="title">{t("sort_title")}</option>
          <option value="last_studied">{t("sort_last_studied")}</option>
          <option value="cards">{t("sort_cards")}</option>
        </select>
        <button
          className={`btn ${archived ? "btn-primary" : "btn-secondary"}`}
          onClick={() => setArchived((a) => !a)}
          aria-pressed={archived}
        >
          <Archive size={18} aria-hidden /> {t("archive")}
        </button>
        <div className="flex" role="group" aria-label="Вид списка">
          <button
            className={`btn ${view === "grid" ? "btn-primary" : "btn-secondary"} rounded-r-none px-3.5`}
            onClick={() => setView("grid")}
            aria-pressed={view === "grid"}
            aria-label="Сетка"
          >
            <LayoutGrid size={18} aria-hidden />
          </button>
          <button
            className={`btn ${view === "list" ? "btn-primary" : "btn-secondary"} rounded-l-none px-3.5`}
            onClick={() => setView("list")}
            aria-pressed={view === "list"}
            aria-label="Список"
          >
            <List size={18} aria-hidden />
          </button>
        </div>
      </div>

      {/* Sets Grid / List */}
      {sets.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="skeleton h-32" />
          ))}
        </div>
      ) : sets.data && sets.data.length > 0 ? (
        <div
          className={
            view === "grid"
              ? "grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
              : "flex flex-col gap-3"
          }
        >
          {sets.data.map((s) => (
            <Link
              key={s.id}
              to={`/sets/${s.id}`}
              className="card group flex flex-col justify-between p-5 transition-all hover:border-[var(--border-hover)] shadow-card"
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex flex-col gap-1">
                    <h2 className="text-base font-bold group-hover:text-[var(--accent)] sm:text-lg">
                      {s.title}
                    </h2>
                    {s.is_admin_created && !s.is_own && (
                      <span className="badge badge-primary text-xs font-semibold w-fit">
                        🔒 Назначено администратором
                      </span>
                    )}
                  </div>
                  {s.is_favorite && (
                    <Star
                      size={18}
                      aria-label={t("favorite")}
                      style={{ color: "var(--warning)", fill: "var(--warning)" }}
                    />
                  )}
                </div>
                {s.description && (
                  <p className="mt-1 line-clamp-2 text-sm text-[var(--text-muted)]">
                    {s.description}
                  </p>
                )}
                {s.tags.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {s.tags.slice(0, 4).map((tag) => (
                      <span key={tag} className="badge">
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div className="mt-4 flex items-center justify-between border-t border-[var(--border)] pt-3 text-xs text-[var(--text-muted)]">
                <span className="badge badge-accent font-semibold">
                  {cardsLabel(locale, s.card_count)}
                </span>
                <span>{formatDate(s.updated_at, locale)}</span>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="card p-12 text-center space-y-4 rounded-3xl shadow-card">
          <p className="text-lg font-bold">
            {archived
              ? t("archive_empty")
              : activeFolderObj
              ? `В папке «${activeFolderObj.name}» пока нет наборов.`
              : t("no_sets")}
          </p>
          <p className="text-sm text-[var(--text-muted)] max-w-md mx-auto">
            {activeFolderObj
              ? "Создайте новый набор карточек или скопируйте его из Quizlet прямо в эту папку."
              : t("no_sets_hint")}
          </p>
          {!archived && (
            <div className="flex flex-wrap justify-center gap-3 pt-2">
              <button
                className="btn btn-primary font-bold px-6 py-2.5 rounded-xl shadow-md flex items-center gap-2"
                onClick={() =>
                  setParams((p) => {
                    const n = new URLSearchParams(p);
                    n.set("create", "1");
                    return n;
                  })
                }
              >
                <Plus size={18} /> Создать набор в этой папке
              </button>
              <button
                className="btn btn-secondary font-bold px-6 py-2.5 rounded-xl flex items-center gap-2"
                onClick={() =>
                  setParams((p) => {
                    const n = new URLSearchParams(p);
                    n.set("import", "1");
                    return n;
                  })
                }
              >
                <Upload size={18} /> Импортировать из Quizlet
              </button>
            </div>
          )}
        </div>
      )}

      {showCreate && (
        <CreateSetDialog
          onClose={closeModals}
          defaultFolderId={activeFolderId}
        />
      )}
      {showImport && <ImportDialog onClose={closeModals} />}

      {showNewFolder && (
        <CreateFolderModal
          onClose={() => setShowNewFolder(false)}
          onCreated={(newFolderId) => {
            void qc.invalidateQueries({ queryKey: ["folders"] });
            selectFolder(newFolderId);
          }}
        />
      )}
    </div>
  );
}

function CreateFolderModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => api<Folder>("/folders", { body: { name: name.trim() } }),
    onSuccess: (data) => {
      onCreated(data.id);
      onClose();
    },
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Создать новую папку"
    >
      <div
        className="card w-full max-w-md p-7 rounded-3xl shadow-2xl space-y-4"
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold tracking-tight">Новая папка</h2>
          <button
            type="button"
            className="btn btn-ghost p-1.5 rounded-xl text-[var(--text-muted)]"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) create.mutate();
          }}
          className="space-y-4"
        >
          <div>
            <label
              htmlFor="folder-name-input"
              className="mb-2 block text-sm font-semibold"
            >
              Название папки *
            </label>
            <input
              id="folder-name-input"
              className="input text-base min-h-[3rem] rounded-xl"
              placeholder="Например, Английский B2"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              required
              maxLength={100}
            />
          </div>
          {create.isError && (
            <p className="text-sm font-medium" style={{ color: "var(--danger)" }}>
              Папка с таким названием уже существует.
            </p>
          )}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              className="btn btn-secondary min-h-[2.75rem] px-5 rounded-xl font-semibold"
              onClick={onClose}
            >
              Отмена
            </button>
            <button
              type="submit"
              className="btn btn-primary min-h-[2.75rem] px-6 rounded-xl font-bold shadow-md"
              disabled={!name.trim() || create.isPending}
            >
              {create.isPending ? "Создание..." : "Создать папку"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
