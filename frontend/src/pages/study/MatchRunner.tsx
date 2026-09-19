import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import { useApp } from "../../state/AppContext";
import { StudyChrome } from "./BasicRunners";
import { speak, stopSpeaking } from "../../lib/tts";
import type { SessionDto } from "./types";
import { useStudySound } from "./useStudySound";

interface Tile {
  key: string;
  itemId: string;
  text: string;
  side: "left" | "right";
}

const MATCH_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "q", "w", "e", "r", "t", "y"];

export function MatchRunner({ session }: { session: SessionDto }) {
  const { t, prefs } = useApp();
  const navigate = useNavigate();
  const tasks = session.tasks ?? [];
  const { soundOn, toggleSound } = useStudySound(session.settings?.auto_tts);
  const [tiles, setTiles] = useState<Tile[]>([]);
  const [selected, setSelected] = useState<Tile | null>(null);
  const [matched, setMatched] = useState<Set<string>>(new Set());
  const [wrong, setWrong] = useState<string[]>([]);
  const [mistakes, setMistakes] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [cursorIndex, setCursorIndex] = useState<number | null>(null);
  const startRef = useRef(Date.now());
  const busy = useRef(false);

  useEffect(() => () => stopSpeaking(), []);

  useEffect(() => {
    const left: Tile[] = tasks.map((tk) => ({
      key: `${tk.item_id}:left`,
      itemId: tk.item_id,
      text: tk.question_text ?? "",
      side: "left" as const,
    }));
    const right: Tile[] = tasks.map((tk) => ({
      key: `${tk.item_id}:right`,
      itemId: tk.item_id,
      text: tk.match_right_text ?? "",
      side: "right" as const,
    }));
    // Для Match сервер кладёт текст пары в snapshot: question_text слева,
    // справа — ответ; берём из answer_key нельзя, поэтому сервер даёт пары в tasks.
    setTiles([...left.sort(() => Math.random() - 0.5), ...right.sort(() => Math.random() - 0.5)]);
  }, [tasks]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const id = setInterval(() => setElapsedMs(Date.now() - startRef.current), 200);
    return () => clearInterval(id);
  }, []);

  const boardSize = tasks.length;

  const finishBoard = useMemo(() => matched.size >= boardSize && boardSize > 0, [matched, boardSize]);

  useEffect(() => {
    if (!finishBoard) return;
    const finalSec = Math.round(elapsedMs / 1000);
    void api(`/study-sessions/${session.id}/complete`, { method: "POST" })
      .catch(() => undefined)
      .finally(() => navigate(`/study/${session.id}/result?time=${finalSec}`, { replace: true }));
  }, [finishBoard, navigate, session.id]);

  if (!tiles.length) return null;

  const pick = async (tile: Tile) => {
    if (busy.current || matched.has(tile.itemId)) return;
    if (tile.text && soundOn) {
      speak(tile.text, { rate: prefs?.tts_rate, volume: prefs?.volume });
    }
    if (!selected) {
      setSelected(tile);
      return;
    }
    if (selected.key === tile.key) {
      setSelected(null);
      return;
    }
    if (selected.side === tile.side) {
      setSelected(tile);
      return;
    }
    busy.current = true;
    const first = selected;
    setSelected(null);
    try {
      const res = await api<{ correct: boolean; mistakes?: number; complete?: boolean }>(
        `/study-sessions/${session.id}/match-moves`,
        { body: { first_item_id: first.itemId, second_item_id: tile.itemId } }
      );
      if (res.correct) {
        setMatched((prev) => new Set(prev).add(first.itemId));
        if (soundOn && tile.text) {
          speak(tile.text, { rate: prefs?.tts_rate, volume: prefs?.volume });
        }
      } else {
        setMistakes(res.mistakes ?? mistakes + 1);
        setWrong([first.key, tile.key]);
        setTimeout(() => setWrong([]), 500);
      }
    } catch {
      // Сеть: снимаем выделение, позволяем попробовать снова.
    }
    busy.current = false;
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName?.match(/INPUT|TEXTAREA|SELECT/)) return;

      if (e.key === "Escape") {
        e.preventDefault();
        if (selected) {
          setSelected(null);
        } else {
          setCursorIndex(null);
        }
        return;
      }

      const keyLower = e.key.toLowerCase();
      const keyIdx = MATCH_KEYS.indexOf(keyLower);
      if (keyIdx !== -1 && tiles[keyIdx]) {
        e.preventDefault();
        setCursorIndex(keyIdx);
        void pick(tiles[keyIdx]);
        return;
      }

      if (e.key === "ArrowRight") {
        e.preventDefault();
        setCursorIndex((cur) => (cur === null ? 0 : Math.min(tiles.length - 1, cur + 1)));
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        setCursorIndex((cur) => (cur === null ? 0 : Math.max(0, cur - 1)));
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setCursorIndex((cur) => (cur === null ? 0 : Math.min(tiles.length - 1, cur + 2)));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setCursorIndex((cur) => (cur === null ? 0 : Math.max(0, cur - 2)));
      } else if (e.code === "Space" || e.key === "Enter") {
        if (cursorIndex !== null && tiles[cursorIndex]) {
          e.preventDefault();
          void pick(tiles[cursorIndex]);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [tiles, cursorIndex, selected, matched]); // eslint-disable-line react-hooks/exhaustive-deps

  const penaltyMs = mistakes * 3000;

  return (
    <StudyChrome
      onExit={async () => {
        await api(`/study-sessions/${session.id}/abandon`, { method: "POST" }).catch(() => undefined);
        navigate(-1);
      }}
      stageInfo={{
        current: matched.size,
        total: boardSize,
        modeLabel: t("mode_match") || "Подбор пар",
      }}
      soundOn={soundOn}
      onToggleSound={toggleSound}
      extra={
        <span className="font-mono text-base font-bold px-3 py-1 rounded-xl" style={{ background: "var(--surface-sunken)" }}>
          {(Math.floor(elapsedMs / 1000) + penaltyMs / 1000)}s
          {mistakes > 0 && <span style={{ color: "var(--danger)" }}> (+{mistakes}×3с)</span>}
        </span>
      }
    >
      <div className="flex flex-1 flex-col justify-center">
        <p className="mb-4 text-center text-base sm:text-lg font-medium text-[var(--text-muted)]">{t("match_start")}</p>
        <div className="grid grid-cols-2 gap-3 sm:gap-4">
          {tiles.map((tile, i) => {
            const isMatched = matched.has(tile.itemId);
            const isWrong = wrong.includes(tile.key);
            const isSelected = selected?.key === tile.key;
            const isFocused = cursorIndex === i;
            return (
              <button
                key={tile.key}
                className={`study-card min-h-[4.5rem] sm:min-h-[5.5rem] p-4 sm:p-6 text-base sm:text-xl font-bold flex items-center justify-center text-center rounded-2xl cursor-pointer transition-all duration-150 relative ${
                  isWrong ? "animate-pulse" : ""
                } ${isFocused && !isMatched ? "ring-2 ring-[var(--accent)] ring-offset-2" : ""}`}
                style={{
                  background: isMatched ? "var(--success-soft)" : isSelected ? "var(--accent-soft)" : "var(--surface)",
                  color: isMatched ? "var(--success)" : isWrong ? "var(--danger)" : "var(--text)",
                  borderColor: isWrong ? "var(--danger)" : isSelected ? "var(--accent)" : undefined,
                  borderWidth: isSelected || isWrong ? "2.5px" : undefined,
                  opacity: isMatched ? 0.45 : 1,
                  transform: isSelected ? "scale(1.02)" : undefined,
                  boxShadow: isSelected ? "0 0 0 4px var(--accent-soft)" : undefined,
                }}
                onClick={() => {
                  setCursorIndex(i);
                  void pick(tile);
                }}
                disabled={isMatched}
                aria-pressed={isSelected}
              >
                {!isMatched && MATCH_KEYS[i] && (
                  <kbd className="absolute top-2 left-2 px-1.5 py-0.5 rounded text-[10px] font-mono opacity-50 bg-[var(--surface-2)] border border-[var(--border)] uppercase">
                    {MATCH_KEYS[i]}
                  </kbd>
                )}
                {tile.text}
              </button>
            );
          })}
        </div>

        {/* Keyboard hints footer */}
        <div className="mt-6 hidden sm:flex flex-wrap items-center justify-center gap-2.5 text-xs text-[var(--text-muted)] opacity-75">
          <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">1</kbd>–<kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">0</kbd> / <kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Q</kbd>–<kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Y</kbd> Выбор</span>
          <span>•</span>
          <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Стрелки</kbd> + <kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Пробел</kbd> Навигация</span>
          <span>•</span>
          <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Esc</kbd> Снять выбор</span>
          <span>•</span>
          <span><kbd className="px-1.5 py-0.5 rounded bg-[var(--surface-2)] border border-[var(--border)] font-mono text-[11px]">Shift+Esc</kbd> Выход</span>
        </div>
      </div>
    </StudyChrome>
  );
}
