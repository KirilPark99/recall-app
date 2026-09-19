import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";
import { cardsLabel } from "../i18n";

interface SetItem {
  id: string;
  title: string;
  description: string;
  card_count: number;
  owner_username: string;
  tags: string[];
}

export function DiscoverPage() {
  const { t, locale } = useApp();
  const sets = useQuery({
    queryKey: ["discover"],
    queryFn: () => api<{ items: SetItem[]; total: number }>("/discover/sets"),
  });

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-3xl sm:text-4xl font-black tracking-tight">{t("nav_discover")}</h1>
        <p className="mt-2 text-base text-[var(--text-muted)]">
          {t("discover_hint")}
        </p>
      </div>

      {sets.isLoading ? (
        <div className="skeleton h-32 rounded-3xl" />
      ) : sets.data && sets.data.items.length > 0 ? (
        <ul className="space-y-4">
          {sets.data.items.map((s) => (
            <li key={s.id}>
              <Link to={`/sets/${s.id}`} className="card block p-6 sm:p-7 rounded-3xl shadow-card hover:shadow-card-hover border border-[var(--border)] transition-all duration-200">
                <div className="text-xl sm:text-2xl font-bold">{s.title}</div>
                {s.description && <div className="mt-2 text-base text-[var(--text-muted)] leading-relaxed">{s.description}</div>}
                <div className="mt-4 flex items-center gap-3 text-sm font-semibold text-[var(--text-muted)]">
                  <span className="badge py-1 px-3 text-xs font-bold">{cardsLabel(locale, s.card_count)}</span>
                  <span>{t("owner")}: {s.owner_username}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="card p-10 text-center text-base text-[var(--text-muted)] rounded-3xl shadow-card border border-[var(--border)]">
          {t("discover_empty")}
        </p>
      )}
    </div>
  );
}
