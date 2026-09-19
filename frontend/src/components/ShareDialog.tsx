import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, Link2, Plus, Trash2, UserPlus, X } from "lucide-react";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";

interface ShareLink {
  id: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  token?: string;
}
interface Permission {
  id: string;
  user_id: string;
  username: string;
  source: string;
  created_at: string;
}

export function ShareDialog({ setId, onClose }: { setId: string; onClose: () => void }) {
  const { t } = useApp();
  const qc = useQueryClient();
  const [newToken, setNewToken] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [copied, setCopied] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialogRef.current?.focus();
    const handler = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const links = useQuery({
    queryKey: ["share-links", setId],
    queryFn: () => api<ShareLink[]>(`/sets/${setId}/share-links`),
  });
  const perms = useQuery({
    queryKey: ["permissions", setId],
    queryFn: () => api<Permission[]>(`/sets/${setId}/permissions`),
  });

  const createLink = useMutation({
    mutationFn: () => api<ShareLink>(`/sets/${setId}/share-links`, { body: {} }),
    onSuccess: (data) => {
      setNewToken(data.token ?? null);
      qc.invalidateQueries({ queryKey: ["share-links", setId] });
    },
  });
  const revokeLink = useMutation({
    mutationFn: (linkId: string) => api(`/sets/${setId}/share-links/${linkId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["share-links", setId] }),
  });
  const grant = useMutation({
    mutationFn: () => api(`/sets/${setId}/permissions`, { body: { username: username.trim() } }),
    onSuccess: () => {
      setUsername("");
      qc.invalidateQueries({ queryKey: ["permissions", setId] });
    },
  });
  const revokePerm = useMutation({
    mutationFn: (grantId: string) => api(`/sets/${setId}/permissions/${grantId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["permissions", setId] }),
  });

  const shareUrl = newToken ? `${window.location.origin}/share/${newToken}` : "";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4" role="dialog" aria-modal="true">
      <div ref={dialogRef} tabIndex={-1} className="card my-8 w-full max-w-lg p-7 sm:p-8 rounded-3xl shadow-modal border border-[var(--border)] outline-none">
        <div className="mb-6 flex items-center justify-between">
          <h2 className="flex items-center gap-2.5 text-2xl font-black tracking-tight">
            <Link2 size={24} className="text-[var(--accent)]" aria-hidden /> Доступ к набору
          </h2>
          <button className="btn btn-ghost h-10 w-10 p-0 rounded-xl" onClick={onClose} aria-label={t("close")}>
            <X size={20} aria-hidden />
          </button>
        </div>

        {newToken && (
          <div className="mb-6 rounded-2xl p-4" style={{ background: "var(--accent-soft)" }}>
            <div className="mb-2 text-sm font-bold text-[var(--accent)]">Ссылка создана — сохраните её:</div>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-xl bg-[var(--surface)] px-3 py-2 text-sm font-mono border border-[var(--border)]">{shareUrl}</code>
              <button
                className="btn btn-secondary min-h-[2.5rem] px-3.5 text-sm font-semibold rounded-xl shrink-0"
                onClick={async () => {
                  await navigator.clipboard.writeText(shareUrl);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                }}
              >
                {copied ? <Check size={16} aria-hidden /> : <Copy size={16} aria-hidden />}
                {copied ? "Скопировано" : "Копировать"}
              </button>
            </div>
          </div>
        )}

        <section aria-label="Ссылки">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">Ссылки доступа</h3>
            <button className="btn btn-secondary min-h-[2.5rem] px-3.5 text-sm font-semibold rounded-xl" onClick={() => createLink.mutate()} disabled={createLink.isPending}>
              <Plus size={16} aria-hidden /> Создать ссылку
            </button>
          </div>
          <ul className="space-y-2 text-base">
            {(links.data ?? []).map((l) => (
              <li key={l.id} className="card flex items-center justify-between p-3.5 rounded-2xl border border-[var(--border)]">
                <span className={l.revoked_at ? "text-[var(--text-muted)] line-through" : "font-medium"}>
                  {l.revoked_at ? "отозвана" : l.expires_at ? "до " + new Date(l.expires_at).toLocaleDateString() : "бессрочная"}
                </span>
                {!l.revoked_at && (
                  <button className="btn btn-ghost h-9 w-9 p-0 rounded-xl text-[var(--danger)]" onClick={() => revokeLink.mutate(l.id)} aria-label={t("delete")}>
                    <Trash2 size={16} aria-hidden />
                  </button>
                )}
              </li>
            ))}
            {links.data?.length === 0 && <li className="text-base text-[var(--text-muted)] p-2">Ссылок пока нет</li>}
          </ul>
        </section>

        <section className="mt-6" aria-label="Пользователи">
          <h3 className="mb-3 text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">Прямой доступ</h3>
          <form
            className="mb-3 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              grant.mutate();
            }}
          >
            <input
              className="input h-12 text-base rounded-2xl flex-1"
              placeholder="имя пользователя"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              aria-label="Имя пользователя"
            />
            <button className="btn btn-primary min-h-[3rem] px-5 text-base font-bold rounded-2xl shadow-md shrink-0" disabled={!username.trim() || grant.isPending}>
              <UserPlus size={18} aria-hidden /> Дать доступ
            </button>
          </form>
          {grant.isError && (
            <p role="alert" className="mb-3 rounded-2xl p-3 text-base font-medium" style={{ background: "var(--danger-soft)", color: "var(--danger)" }}>
              {(grant.error as Error).message}
            </p>
          )}
          <ul className="space-y-2 text-base">
            {(perms.data ?? []).map((p) => (
              <li key={p.id} className="card flex items-center justify-between p-3.5 rounded-2xl border border-[var(--border)]">
                <span className="font-medium flex items-center gap-2">
                  {p.username} <span className="badge py-0.5 px-2.5 text-xs font-semibold">{p.source === "direct" ? "лично" : "по ссылке"}</span>
                </span>
                <button className="btn btn-ghost h-9 w-9 p-0 rounded-xl text-[var(--danger)]" onClick={() => revokePerm.mutate(p.id)} aria-label={t("delete")}>
                  <Trash2 size={16} aria-hidden />
                </button>
              </li>
            ))}
            {perms.data?.length === 0 && <li className="text-base text-[var(--text-muted)] p-2">Только вы</li>}
          </ul>
        </section>
      </div>
    </div>
  );
}
