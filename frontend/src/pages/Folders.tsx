import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { FolderPlus, Trash2, Upload, Users, X } from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";
import { ImportDialog } from "../components/ImportDialog";

interface Folder {
  id: string;
  name: string;
  set_count: number;
  created_by_admin?: boolean;
}
interface SetItem {
  id: string;
  title: string;
  in_folder_id: string | null;
}

export function FoldersPage() {
  const { t, user } = useApp();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [openFolder, setOpenFolder] = useState<string | null>(null);
  const [assignModalFolder, setAssignModalFolder] = useState<Folder | null>(null);
  const [showImport, setShowImport] = useState(false);

  const folders = useQuery({ queryKey: ["folders"], queryFn: () => api<Folder[]>("/folders") });
  const sets = useQuery({ queryKey: ["sets", "all"], queryFn: () => api<SetItem[]>("/sets?page_size=200") });

  const create = useMutation({
    mutationFn: () => api("/folders", { body: { name: name.trim() } }),
    onSuccess: () => {
      setName("");
      void qc.invalidateQueries({ queryKey: ["folders"] });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/folders/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setOpenFolder(null);
      void qc.invalidateQueries({ queryKey: ["folders"] });
    },
  });
  const addToFolder = useMutation({
    mutationFn: ({ folderId, setId }: { folderId: string; setId: string }) =>
      api(`/folders/${folderId}/sets/${setId}`, { method: "PUT" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["folders"] });
      void qc.invalidateQueries({ queryKey: ["sets"] });
    },
  });
  const removeFromFolder = useMutation({
    mutationFn: ({ folderId, setId }: { folderId: string; setId: string }) =>
      api(`/folders/${folderId}/sets/${setId}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["folders"] });
      void qc.invalidateQueries({ queryKey: ["sets"] });
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) create.mutate();
  };

  const folderSets = (fid: string) => (sets.data ?? []).filter((s) => s.in_folder_id === fid);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-3xl sm:text-4xl font-black tracking-tight">{t("nav_folders")}</h1>
        <button
          type="button"
          className="btn btn-secondary min-h-[3rem] px-5 rounded-xl font-bold flex items-center gap-2 shadow-sm"
          onClick={() => setShowImport(true)}
        >
          <Upload size={18} aria-hidden /> {t("import_sets")}
        </button>
      </div>

      <form onSubmit={submit} className="flex gap-3">
        <input className="input flex-1 text-base min-h-[3rem] rounded-xl" placeholder={t("new_folder")} value={name} onChange={(e) => setName(e.target.value)} aria-label={t("new_folder")} />
        <button className="btn btn-primary min-h-[3rem] px-6 text-base font-bold rounded-xl" disabled={!name.trim() || create.isPending}>
          <FolderPlus size={18} aria-hidden /> {t("create_folder")}
        </button>
      </form>
      {create.isError && <p className="rounded-xl px-4 py-3 text-base" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>Папка с таким названием уже есть.</p>}

      {folders.data && folders.data.length > 0 ? (
        <ul className="space-y-3">
          {folders.data.map((f) => (
            <li key={f.id} className="card p-5 sm:p-6 rounded-2xl shadow-card">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <button className="text-left text-lg sm:text-xl font-bold flex flex-wrap items-center gap-2 cursor-pointer flex-1 min-w-0" onClick={() => setOpenFolder(openFolder === f.id ? null : f.id)} aria-expanded={openFolder === f.id}>
                  <span className="break-words">{f.name}</span>
                  <span className="badge text-sm font-bold px-2.5 py-0.5 rounded-lg">{f.set_count}</span>
                  {f.created_by_admin && (
                    <span className="badge badge-primary text-xs font-semibold">🔒 Назначено администратором</span>
                  )}
                </button>
                <div className="flex items-center gap-2 shrink-0">
                  {user?.role === "admin" && !f.created_by_admin && (
                    <button
                      className="btn btn-secondary text-sm font-semibold px-3 py-1.5 rounded-xl flex items-center gap-1.5"
                      onClick={() => setAssignModalFolder(f)}
                      title="Назначить эту папку пользователям"
                    >
                      <Users size={16} aria-hidden /> Назначить пользователям
                    </button>
                  )}
                  {!f.created_by_admin && (
                    <button
                      className="btn btn-ghost p-2 rounded-xl text-[var(--danger)]"
                      onClick={() => {
                        if (window.confirm(t("delete_folder_confirm"))) remove.mutate(f.id);
                      }}
                      aria-label={t("delete")}
                    >
                      <Trash2 size={18} aria-hidden />
                    </button>
                  )}
                </div>
              </div>
              {openFolder === f.id && (
                <div className="mt-4 space-y-3 border-t border-[var(--border)] pt-4">
                  {folderSets(f.id).map((s) => (
                    <div key={s.id} className="flex items-center justify-between rounded-xl px-3 py-2 text-base" style={{ background: "var(--surface-2)" }}>
                      <Link to={`/sets/${s.id}`} className="font-semibold">{s.title}</Link>
                      {!f.created_by_admin && (
                        <button className="btn btn-ghost text-sm text-[var(--danger)]" onClick={() => removeFromFolder.mutate({ folderId: f.id, setId: s.id })}>
                          {t("remove_from_folder")}
                        </button>
                      )}
                    </div>
                  ))}
                  {f.created_by_admin ? (
                    <p className="text-xs text-[var(--text-muted)] italic pt-1">
                      Папка управляется администратором. Изменение наборов недоступно.
                    </p>
                  ) : (
                    <select
                      className="select text-base min-h-[3rem] rounded-xl"
                      defaultValue=""
                      onChange={(e) => {
                        if (e.target.value) addToFolder.mutate({ folderId: f.id, setId: e.target.value });
                      }}
                      aria-label="Добавить набор"
                    >
                      <option value="">{t("add_set")}</option>
                      {(sets.data ?? []).filter((s) => s.in_folder_id !== f.id).map((s) => (
                        <option key={s.id} value={s.id}>{s.title}</option>
                      ))}
                    </select>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="card p-10 text-center text-base text-[var(--text-muted)] rounded-2xl">
          {t("folders_empty")}
        </p>
      )}
      {assignModalFolder && (
        <FolderAssignModal
          folder={assignModalFolder}
          onClose={() => setAssignModalFolder(null)}
        />
      )}
      {showImport && <ImportDialog onClose={() => setShowImport(false)} />}
    </div>
  );
}

interface FolderAssignmentUser {
  id: string;
  username: string;
  is_assigned: boolean;
}

interface FolderAssignmentData {
  folder: { id: string; name: string; set_count: number };
  users: FolderAssignmentUser[];
}

function FolderAssignModal({ folder, onClose }: { folder: Folder; onClose: () => void }) {
  const qc = useQueryClient();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [initialized, setInitialized] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const assignmentsQ = useQuery({
    queryKey: ["admin", "folder-assignments", folder.id],
    queryFn: () => api<FolderAssignmentData>(`/admin/folders/${folder.id}/assignments`),
  });

  useEffect(() => {
    if (assignmentsQ.data && !initialized) {
      setInitialized(true);
      const initiallyAssigned = new Set(
        assignmentsQ.data.users.filter((u) => u.is_assigned).map((u) => u.id)
      );
      setSelectedIds(initiallyAssigned);
    }
  }, [assignmentsQ.data, initialized]);

  const saveMut = useMutation({
    mutationFn: () =>
      api(`/admin/folders/${folder.id}/assignments`, {
        body: { user_ids: Array.from(selectedIds) },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "folder-assignments", folder.id] });
      qc.invalidateQueries({ queryKey: ["folders"] });
      onClose();
    },
    onError: (e) => setErrorMsg((e as Error).message),
  });

  const toggleUser = (userId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  };

  const selectAll = () => {
    if (!assignmentsQ.data) return;
    setSelectedIds(new Set(assignmentsQ.data.users.map((u) => u.id)));
  };

  const deselectAll = () => {
    setSelectedIds(new Set());
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="card w-full max-w-lg space-y-5 rounded-3xl p-6 shadow-2xl bg-[var(--surface-1)] border border-[var(--border)]">
        <div className="flex items-center justify-between border-b pb-3">
          <div>
            <h3 className="text-xl font-bold">Назначить папку пользователям</h3>
            <p className="text-sm text-[var(--text-muted)]">
              Папка «{folder.name}» и все её наборы станут доступны выбранным пользователям
            </p>
          </div>
          <button className="btn btn-ghost p-2 rounded-xl" onClick={onClose} aria-label="Закрыть">
            <X size={20} aria-hidden />
          </button>
        </div>

        {errorMsg && (
          <p className="rounded-xl px-4 py-2.5 text-sm" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
            {errorMsg}
          </p>
        )}

        {assignmentsQ.isLoading ? (
          <div className="space-y-3 py-6">
            <div className="skeleton h-8 w-full" />
            <div className="skeleton h-8 w-full" />
            <div className="skeleton h-8 w-full" />
          </div>
        ) : assignmentsQ.data ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between text-xs text-[var(--text-muted)]">
              <span>Всего пользователей: {assignmentsQ.data.users.length}</span>
              <div className="flex gap-2">
                <button className="hover:underline font-semibold" onClick={selectAll}>
                  Выбрать всех
                </button>
                <span>•</span>
                <button className="hover:underline font-semibold" onClick={deselectAll}>
                  Снять выбор
                </button>
              </div>
            </div>

            {assignmentsQ.data.users.length === 0 ? (
              <p className="text-center py-6 text-sm text-[var(--text-muted)] italic">
                Нет других активных пользователей для назначения
              </p>
            ) : (
              <ul className="max-h-64 overflow-y-auto space-y-2 pr-1">
                {assignmentsQ.data.users.map((u) => {
                  const isChecked = selectedIds.has(u.id);
                  return (
                    <li
                      key={u.id}
                      onClick={() => toggleUser(u.id)}
                      className="flex items-center justify-between p-3 rounded-xl cursor-pointer transition-colors"
                      style={{ background: isChecked ? "var(--surface-3, var(--surface-2))" : "var(--surface-2)" }}
                    >
                      <div className="flex items-center gap-3 select-none">
                        <input
                          type="checkbox"
                          className="h-5 w-5 rounded pointer-events-none"
                          checked={isChecked}
                          readOnly
                        />
                        <span className="font-semibold text-base">{u.username}</span>
                      </div>
                      {u.is_assigned && (
                        <span className="badge text-xs font-semibold">Назначено сейчас</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}

            <div className="flex justify-end gap-3 border-t pt-4">
              <button className="btn btn-secondary min-h-[2.75rem] px-5 rounded-xl font-semibold" onClick={onClose}>
                Отмена
              </button>
              <button
                className="btn btn-primary min-h-[2.75rem] px-6 rounded-xl font-bold"
                disabled={saveMut.isPending}
                onClick={() => saveMut.mutate()}
              >
                {saveMut.isPending ? "Сохранение..." : "Сохранить назначения"}
              </button>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

