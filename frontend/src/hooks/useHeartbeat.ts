import { useEffect, useRef } from "react";
import { api } from "../api/client";

// Оценка активного времени: считаем только видимые и активные интервалы,
// ограничиваем длину одного интервала на сервере.
export function useHeartbeat(sessionId: string | null, enabled: boolean) {
  const activeMs = useRef(0);
  const lastTick = useRef<number | null>(null);
  const idle = useRef(false);

  useEffect(() => {
    if (!sessionId || !enabled) return;
    const tick = () => {
      const now = Date.now();
      if (lastTick.current !== null && !document.hidden && !idle.current) {
        activeMs.current += now - lastTick.current;
      }
      lastTick.current = now;
    };
    const interval = setInterval(tick, 5000);
    const onVisibility = () => {
      if (document.hidden) tick();
      else lastTick.current = Date.now();
    };
    let idleTimer: ReturnType<typeof setTimeout> | null = null;
    const resetIdle = () => {
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        idle.current = true;
      }, 120000);
    };
    const onActivity = () => {
      idle.current = false;
      resetIdle();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pointerdown", onActivity);
    window.addEventListener("keydown", onActivity);
    resetIdle();

    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pointerdown", onActivity);
      window.removeEventListener("keydown", onActivity);
      if (idleTimer) clearTimeout(idleTimer);
      // Финальная отправка
      if (activeMs.current > 0) {
        const delta = activeMs.current;
        activeMs.current = 0;
        void api(`/study-sessions/${sessionId}/progress`, {
          method: "PATCH",
          body: { active_ms_delta: delta },
        }).catch(() => undefined);
      }
    };
  }, [sessionId, enabled]);

  useEffect(() => {
    if (!sessionId || !enabled) return;
    const interval = setInterval(() => {
      if (activeMs.current >= 10000) {
        const delta = activeMs.current;
        activeMs.current = 0;
        void api(`/study-sessions/${sessionId}/progress`, {
          method: "PATCH",
          body: { active_ms_delta: delta },
        }).catch(() => undefined);
      }
    }, 30000);
    return () => clearInterval(interval);
  }, [sessionId, enabled]);
}
