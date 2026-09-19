// Высококачественный человекоподобный нейросетевой TTS (Neural HD)
// с кэшированием на сервере и защитой от роботизированных синтезаторов речи.

let currentAudio: HTMLAudioElement | null = null;
let activeRequestId = 0;
let isAudioUnlocked = false;
let pendingSpeech: { text: string; opts: SpeakOptions } | null = null;

// Разблокировка воспроизведения аудио при первом взаимодействии пользователя
function initAudioUnlock() {
  if (typeof window === "undefined" || isAudioUnlocked) return;
  const unlock = () => {
    isAudioUnlocked = true;
    window.removeEventListener("pointerdown", unlock);
    window.removeEventListener("keydown", unlock);
    window.removeEventListener("click", unlock);
    if (pendingSpeech) {
      const p = pendingSpeech;
      pendingSpeech = null;
      speak(p.text, p.opts);
    }
  };
  window.addEventListener("pointerdown", unlock, { once: true, passive: true });
  window.addEventListener("keydown", unlock, { once: true, passive: true });
  window.addEventListener("click", unlock, { once: true, passive: true });
}

if (typeof window !== "undefined") {
  initAudioUnlock();
}

export interface SpeakOptions {
  lang?: string;
  rate?: number;
  volume?: number;
  voice?: string;
  gender?: "female" | "male";
  useServerTts?: boolean;
}

export function ttsSupported(): boolean {
  return typeof window !== "undefined" && ("Audio" in window || "speechSynthesis" in window);
}

export function stopSpeaking(): void {
  activeRequestId++;
  pendingSpeech = null;

  if (currentAudio) {
    try {
      currentAudio.pause();
      currentAudio.currentTime = 0;
      // Очищаем обработчики до сброса src, чтобы не вызывать onerror
      currentAudio.onended = null;
      currentAudio.onerror = null;
      currentAudio.src = "";
    } catch {
      // ignore
    }
    currentAudio = null;
  }

  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    try {
      window.speechSynthesis.cancel();
    } catch {
      // ignore
    }
  }
}

const CYRILLIC_PATTERN = /[\u0400-\u04FF]/;

export function getTtsAudioUrl(text: string, opts: SpeakOptions = {}): string {
  const clean = text.trim();
  const params = new URLSearchParams({
    text: clean,
  });

  // Автоопределение скрипта: если кириллица — русский, если только латиница и указан ru — английский
  let lang = opts.lang?.trim() || "";
  const hasCyrillic = CYRILLIC_PATTERN.test(clean);
  if (hasCyrillic && !lang.toLowerCase().startsWith("ru") && !lang.toLowerCase().startsWith("uk")) {
    lang = "ru";
  } else if (!hasCyrillic && lang.toLowerCase().startsWith("ru")) {
    lang = "en";
  } else if (!lang) {
    lang = hasCyrillic ? "ru" : "en";
  }

  params.set("lang", lang);
  if (opts.rate) params.set("rate", opts.rate.toString());
  if (opts.voice) params.set("voice", opts.voice);
  if (opts.gender) params.set("gender", opts.gender);
  return `/api/v1/tts?${params.toString()}`;
}

export function speak(text: string, opts: SpeakOptions = {}): boolean {
  const clean = text?.trim();
  if (!clean) return false;

  stopSpeaking();
  const reqId = ++activeRequestId;

  const useServer = opts.useServerTts !== false;
  const volume = opts.volume ?? 1;
  const rate = opts.rate ?? 1;

  if (useServer && typeof window !== "undefined" && "Audio" in window) {
    try {
      const url = getTtsAudioUrl(clean, opts);
      const audio = new Audio(url);
      audio.volume = Math.max(0, Math.min(1, volume));
      audio.playbackRate = Math.max(0.5, Math.min(2.0, rate));
      currentAudio = audio;

      audio.onended = () => {
        if (activeRequestId === reqId) {
          currentAudio = null;
        }
      };

      audio.onerror = () => {
        // Игнорируем ошибки для отменённых или устаревших запросов
        if (activeRequestId !== reqId) return;
        currentAudio = null;
        speakFallbackBrowser(clean, opts);
      };

      const playPromise = audio.play();
      if (playPromise) {
        playPromise.catch((err) => {
          if (activeRequestId !== reqId) return;
          // Если автовоспроизведение заблокировано политикой браузера до клика — сохраняем до первого клика
          if (err.name === "NotAllowedError") {
            pendingSpeech = { text: clean, opts };
            return;
          }
          if (err.name !== "AbortError") {
            speakFallbackBrowser(clean, opts);
          }
        });
      }
      return true;
    } catch {
      // fallback
    }
  }

  return speakFallbackBrowser(clean, opts);
}

// Проверка на роботизированный синтезатор (espeak, pico и т.д.)
function isRobotVoice(v: SpeechSynthesisVoice): boolean {
  const name = (v.name + " " + v.voiceURI).toLowerCase();
  return (
    name.includes("espeak") ||
    name.includes("pico") ||
    name.includes("klatt") ||
    name.includes("festival") ||
    name.includes("mbrola")
  );
}

function speakFallbackBrowser(text: string, opts: SpeakOptions): boolean {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return false;
  window.speechSynthesis.cancel();
  const voices = window.speechSynthesis.getVoices();

  const hasCyrillic = CYRILLIC_PATTERN.test(text);
  let targetLang = opts.lang || (hasCyrillic ? "ru-RU" : "en-US");
  if (hasCyrillic && !targetLang.toLowerCase().startsWith("ru")) {
    targetLang = "ru-RU";
  }

  // Исключаем роботизированные голоса! Пользователю нужны только качественные голоса
  const nonRobotVoices = voices.filter((v) => !isRobotVoice(v));

  // Ищем голос под нужный язык
  let candidates = nonRobotVoices.filter((v) =>
    v.lang.toLowerCase().startsWith(targetLang.slice(0, 2).toLowerCase())
  );

  // Если нет качественного голоса для этого языка, НЕ воспроизводим роботом
  if (candidates.length === 0) {
    // Пробуем любые качественные голоса браузера (например, Google / Microsoft / Apple)
    candidates = nonRobotVoices;
  }

  // Если вообще нет ни одного нормального человеческого голоса (только espeak на Linux) —
  // лучше промолчать, чем пугать пользователя жутким роботом
  if (candidates.length === 0) {
    return false;
  }

  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = targetLang;
  utter.rate = opts.rate ?? 1;
  if (candidates[0]) {
    utter.voice = candidates[0];
  }
  window.speechSynthesis.speak(utter);
  return true;
}

export function getVoices(): SpeechSynthesisVoice[] {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return [];
  return window.speechSynthesis.getVoices().filter((v) => !isRobotVoice(v));
}

export function onVoicesChanged(cb: () => void): () => void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return () => undefined;
  const handler = () => cb();
  window.speechSynthesis.addEventListener("voiceschanged", handler);
  return () => window.speechSynthesis.removeEventListener("voiceschanged", handler);
}
