// Dev-лог (без секретов).
export function devLog(message: string): void {
  if (import.meta.env.DEV) {
    console.info(`[recall] ${message}`);
  }
}
