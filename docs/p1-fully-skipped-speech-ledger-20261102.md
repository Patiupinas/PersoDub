# P1: account for fully skipped synthesized speech

The standard Qwen assembly previously logged a line skipped due to an identical or too-close next start, or a start after video end, but did not include that line in `clipped_lines.json`. The completed-job Quality check consequently undercounted lost dubbed speech.

The existing `place_lines(..., clipped=...)` collection now includes an entry for each entirely skipped generated line: `{"line": <1-based>, "cut_s": <duration>, "skipped": true}`. Partial cuts retain their prior schema with no `skipped` field. The existing job writer and Quality check accept both without requiring a new ledger or a migration. No text or private media enters the ledger.

This is **detection, not speech recovery**. The assembler continues to honor source-clock collisions and the video boundary; selection of shorter text or a regenerated take must occur upstream. Existing completed jobs are unchanged. Two regression cases cover equal starts and a line beginning beyond video end. The original four-minute lesson has not been regenerated with this branch.
