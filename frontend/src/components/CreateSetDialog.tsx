import { FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";

export function CreateSetDialog({
  onClose,
  defaultFolderId,
}: {
  onClose: () => void;
  defaultFolderId?: string | null;
}) {
  const { t } = useApp();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [frontLang, setFrontLang] = useState("");
  const [backLang, setBackLang] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api<{ id: string }>("/sets", {
        body: {
          title: title.trim(),
          description: description.trim(),
          front_language: frontLang.trim().toLowerCase(),
          back_language: backLang.trim().toLowerCase(),
        },
      }),
    onSuccess: async (data) => {
      if (defaultFolderId && defaultFolderId !== "all" && defaultFolderId !== "unassigned") {
        try {
          await api(`/folders/${defaultFolderId}/sets/${data.id}`, { method: "PUT" });
          await qc.invalidateQueries({ queryKey: ["folders"] });
        } catch {
          // ignore
        }
      }
      await qc.invalidateQueries({ queryKey: ["sets"] });
      onClose();
      navigate(`/sets/${data.id}/edit`);
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (title.trim()) create.mutate();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-label={t("create_set")}>
      <div className="card w-full max-w-lg p-7 sm:p-8 rounded-3xl shadow-2xl" onKeyDown={(e) => e.key === "Escape" && onClose()}>
        <h2 className="mb-5 text-2xl font-bold tracking-tight">{t("create_set")}</h2>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label htmlFor="set-title" className="mb-2 block text-base font-semibold">
              Название *
            </label>
            <input
              id="set-title"
              className="input text-base min-h-[3rem] rounded-xl"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              autoFocus
              required
              maxLength={300}
            />
          </div>
          <div>
            <label htmlFor="set-desc" className="mb-2 block text-base font-semibold">
              Описание
            </label>
            <textarea id="set-desc" className="textarea text-base rounded-xl" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="set-flang" className="mb-2 block text-base font-semibold">
                Язык стороны вопроса
              </label>
              <input id="set-flang" className="input text-base min-h-[3rem] rounded-xl" placeholder="en" value={frontLang} onChange={(e) => setFrontLang(e.target.value)} maxLength={16} />
            </div>
            <div>
              <label htmlFor="set-blang" className="mb-2 block text-base font-semibold">
                Язык стороны ответа
              </label>
              <input id="set-blang" className="input text-base min-h-[3rem] rounded-xl" placeholder="ru" value={backLang} onChange={(e) => setBackLang(e.target.value)} maxLength={16} />
            </div>
          </div>
          {create.isError && (
            <p role="alert" className="rounded-xl px-4 py-3 text-base" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
              Не удалось создать набор.
            </p>
          )}
          <div className="flex justify-end gap-3 pt-3">
            <button type="button" className="btn btn-secondary min-h-[3rem] px-6 text-base font-semibold rounded-xl" onClick={onClose}>
              {t("cancel")}
            </button>
            <button type="submit" className="btn btn-primary min-h-[3rem] px-8 text-base font-bold rounded-xl" disabled={!title.trim() || create.isPending}>
              {t("save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
