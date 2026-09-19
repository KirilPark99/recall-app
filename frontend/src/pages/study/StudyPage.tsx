import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { useApp } from "../../state/AppContext";
import { useHeartbeat } from "../../hooks/useHeartbeat";
import { CardsRunner, WriteRunner } from "./BasicRunners";
import { LearnRunner } from "./LearnRunner";
import { TestRunner } from "./TestRunner";
import { MatchRunner } from "./MatchRunner";
import type { SessionDto } from "./types";

export function StudyPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { t } = useApp();
  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api<SessionDto>(`/study-sessions/${sessionId}`),
  });

  useHeartbeat(sessionId ?? null, !!session.data && session.data.status === "active");

  if (session.isLoading) {
    return <div className="mx-auto max-w-3xl p-6"><div className="skeleton h-40" /></div>;
  }
  if (session.isError || !session.data) {
    return (
      <div className="p-8 text-center">
        <p>{t("error_generic")}</p>
        <Link to="/" className="btn btn-secondary mt-3">{t("nav_home")}</Link>
      </div>
    );
  }
  const s = session.data;

  if (s.status === "completed") {
    window.location.replace(`/study/${s.id}/result`);
    return null;
  }

  switch (s.mode) {
    case "cards":
      return <CardsRunner session={s} />;
    case "write":
      return <WriteRunner session={s} spell={false} />;
    case "spell":
      return <WriteRunner session={s} spell />;
    case "learn":
      return <LearnRunner sessionId={s.id} />;
    case "test":
      return <TestRunner session={s} />;
    case "match":
      return <MatchRunner session={s} />;
    default:
      return <div className="p-8 text-center">Неизвестный режим: {s.mode}</div>;
  }
}
