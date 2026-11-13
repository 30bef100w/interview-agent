/** Preserve the exact existing draft; live hypotheses replace only the speech suffix. */
export function appendSpeechDraft(base: string, transcript: string): string {
  const text = transcript.trim();
  if (!text) return base;
  return `${base}${base && !/\s$/.test(base) ? " " : ""}${text}`;
}
