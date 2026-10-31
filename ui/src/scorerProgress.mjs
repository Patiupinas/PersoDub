// Live ASR counters are advisory, not saved project state or an ETA.
import { t } from "./i18n.mjs";

export function scorerProgressText(job) {
  const p = job?.scorer_progress;
  if (job?.status !== "running" || p?.phase !== "asr") return "";
  const { done, total, reused } = p;
  if (![done, total, reused].every(Number.isSafeInteger)
      || reused < 0 || reused > done || done < 0 || done > total
      || total < 1 || total > 1000000) return "";
  return t("Checking pronunciation: {done}/{total}", { done, total });
}
