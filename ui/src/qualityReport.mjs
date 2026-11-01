// Read-only quality report for the current finished video or reviewed Overdub.
// Source files and voice models are never changed by viewing this report.
import { escapeHtml, errorText } from "./format.mjs";
import { t } from "./i18n.mjs";

function countOf(issue) {
  return Number.isFinite(issue.count) ? issue.count : 1;
}

export function qualityIssueText(issue) {
  switch (issue.code) {
    case "speech_audio_clipped":
      return t("{n} speech line(s) cut; {seconds} seconds lost.", {
        n: countOf(issue), seconds: issue.total_cut_seconds,
      });
    case "timing_slot_overruns":
      return t("{n} generated speech line(s) exceed the available time by {seconds} seconds.", {
        n: countOf(issue), seconds: issue.total_excess_seconds,
      });
    case "speaker_reference_too_short":
      return t("Speaker {speaker} has only {seconds} seconds of reference audio.", {
        speaker: issue.speaker, seconds: issue.audio_seconds,
      });
    case "speaker_reference_text_mismatch":
      return t("Speaker {speaker}'s reference text does not fit the recorded audio.", {
        speaker: issue.speaker,
      });
    case "source_track_missing":
      return t("Expected {expected} audio streams; found {actual}.", {
        expected: issue.expected_audio_tracks, actual: issue.actual_audio_tracks,
      });
    case "output_mode_mismatch":
      return t("Expected {expected} mode, but this video is {actual}.", {
        expected: issue.expected, actual: issue.actual,
      });
    case "overdub_stream_metadata_mismatch":
      return t("Overdub and Original audio streams have incorrect labels or defaults.");
    case "source_timeline_unmatched":
      return t("Source and translated scripts contain different numbers of lines.");
    case "source_line_timing_unmatched":
      return t("Line {line} does not match the source timestamp.", { line: issue.line });
    case "speaker_reference_missing":
      return t("Speaker {speaker} is missing a reference recording.", {
        speaker: issue.speaker,
      });
    case "media_stream_missing":
      return t("The finished video is missing a video or audio stream.");
    default:
      return t("A technical quality issue needs review: {code}", {
        code: String(issue.code || "unknown"),
      });
  }
}

export function qualitySummary(report) {
  const count = Array.isArray(report.issues) ? report.issues.length : 0;
  if (report.status === "review_required" || count) {
    return count === 1 ? t("1 issue detected") : t("{n} issues detected", { n: count });
  }
  return t("No automated issues; listening not verified");
}

/** Load on job change and explicit refresh, not on every polling tick. */
export function initQualityReport({ $, fetchFn = (...args) => fetch(...args) }) {
  const root = $("qualityAudit");
  const status = $("qualityAuditStatus");
  const scope = $("qualityAuditScope");
  const issues = $("qualityAuditIssues");
  const human = $("qualityAuditHuman");
  const refreshButton = $("qualityAuditRefresh");
  let selectedJob = null;
  let selectedFile = null;
  let generation = 0;

  function clear() {
    ++generation;
    selectedJob = null;
    selectedFile = null;
    root.hidden = true;
    root.open = false;
    status.textContent = "";
    issues.innerHTML = "";
  }

  async function load() {
    if (!selectedJob) return;
    const jobId = selectedJob;
    const file = selectedFile;
    const token = ++generation;
    root.hidden = false;
    refreshButton.disabled = true;
    status.textContent = t("Checking finished media…");
    scope.textContent = "";
    issues.innerHTML = "";
    human.hidden = true;
    try {
      const url = `/api/dub/jobs/${encodeURIComponent(jobId)}/quality`
        + (file ? `?file=${encodeURIComponent(file)}` : "");
      const response = await fetchFn(url);
      const data = await response.json().catch(() => ({}));
      if (token !== generation) return;
      if (!response.ok) throw new Error(data.detail || t("Quality report unavailable"));
      status.textContent = qualitySummary(data);
      scope.textContent = file
        ? t("Reviewed Overdub export: {file} ({n} audio streams)", {
          file: data.output_file, n: data.actual_audio_streams,
        })
        : t("Current dubbed video: {mode} ({n} audio stream(s))", {
          mode: data.declared_audio_mode, n: data.actual_audio_streams,
        });
      const found = Array.isArray(data.issues) ? data.issues : [];
      issues.innerHTML = found.map((item) => `<li>${escapeHtml(qualityIssueText(item))}</li>`).join("");
      human.textContent = t(
        "Not measured here: Russian accent, speaker similarity, pauses and listening quality."
      );
      human.hidden = false;
    } catch (err) {
      if (token !== generation) return;
      status.textContent = t("Quality report unavailable");
      scope.textContent = errorText(err);
    } finally {
      if (token === generation) refreshButton.disabled = false;
    }
  }

  function show(job) {
    if (!job || job.status !== "done" || job.dub_mode === "perso"
        || (job.kind && job.kind !== "dub")) {
      clear();
      return;
    }
    if (selectedJob === job.id) return;
    selectedJob = job.id;
    selectedFile = null;
    root.open = false;
    return load();
  }

  function showOverdub(jobId, filename) {
    if (selectedJob !== jobId || !/^finished-overdub(?:-[0-9]+)?\.mp4$/.test(filename)) {
      return;
    }
    selectedFile = filename;
    root.open = true;
    return load();
  }

  function refresh() { return load(); }
  refreshButton.addEventListener("click", refresh);
  return { show, showOverdub, refresh, clear };
}
