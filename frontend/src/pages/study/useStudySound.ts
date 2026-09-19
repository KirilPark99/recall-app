import { useCallback, useState } from "react";
import { stopSpeaking } from "../../lib/tts";

export function useStudySound(sessionAutoTts?: unknown) {
  const [soundOn, setSoundOn] = useState<boolean>(() => {
    if (typeof sessionAutoTts === "boolean") return sessionAutoTts;
    return localStorage.getItem("study_auto_tts") === "true";
  });

  const toggleSound = useCallback(() => {
    setSoundOn((prev) => {
      const next = !prev;
      localStorage.setItem("study_auto_tts", next ? "true" : "false");
      if (!next) {
        stopSpeaking();
      }
      return next;
    });
  }, []);

  return { soundOn, toggleSound };
}
