import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useApp } from "../state/AppContext";

export function SharePage() {
  const params = useParams<{ token?: string }>();
  const token =
    params.token ??
    (params as Record<string, string>)["*"] ??
    window.location.pathname.split("/share/")[1]?.split("/")[0] ??
    window.location.hash.replace(/^#/, "");
  const { user } = useApp();
  const navigate = useNavigate();
  const [result, setResult] = useState<{ set_id: string; title: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Токен не оставляем в URL/истории после обмена.
    if (window.location.hash) {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, []);

  const redeem = useMutation({
    mutationFn: () => api<{ set_id: string; title: string }>("/share-links/redeem", { body: { token } }),
    onSuccess: (data) => {
      setResult(data);
      window.history.replaceState(null, "", `/sets/${data.set_id}`);
    },
    onError: (e) => setError((e as Error).message),
  });

  useEffect(() => {
    if (user && token && !result && !error) {
      redeem.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, token]);

  if (!user) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center p-4">
        <div className="card w-full max-w-md p-8 sm:p-10 text-center rounded-3xl shadow-modal border border-[var(--border)] space-y-6">
          <p className="text-xl font-bold">Для открытия набора по ссылке нужно войти.</p>
          <Link to="/login" className="btn btn-primary min-h-[3rem] px-8 text-base font-bold rounded-2xl w-full shadow-md" state={{ returnPath: window.location.pathname }}>
            Войти
          </Link>
        </div>
      </div>
    );
  }

  if (result) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center p-4">
        <div className="card w-full max-w-md p-8 sm:p-10 text-center rounded-3xl shadow-modal border border-[var(--border)] space-y-6">
          <p className="text-xl font-bold">Набор «{result.title}» добавлен в ваши наборы (доступ читателя).</p>
          <button className="btn btn-primary min-h-[3rem] px-8 text-base font-bold rounded-2xl w-full shadow-md" onClick={() => navigate(`/sets/${result.set_id}`)}>
            Открыть набор
          </button>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center p-4">
        <div className="card w-full max-w-md p-8 sm:p-10 text-center rounded-3xl shadow-modal border border-[var(--border)] space-y-6">
          <p role="alert" className="text-xl font-bold" style={{ color: "var(--danger)" }}>{error || "Ссылка недействительна."}</p>
          <Link to="/" className="btn btn-secondary min-h-[3rem] px-8 text-base font-bold rounded-2xl w-full">
            На главную
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="skeleton h-14 w-48 rounded-2xl" aria-busy="true" />
    </div>
  );
}
