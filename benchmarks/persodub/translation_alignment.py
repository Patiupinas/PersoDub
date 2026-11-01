"""Bounded, monotone time alignment for translation quality benchmarks."""
import math


def align_cues(source: list[dict], translation: list[dict]) -> list[dict]:
    """Match 1:1, 1:N, N:1 or unpaired subtitle intervals.

    A simple overlap-connected-component algorithm chains an entire lesson
    together when adjacent source and target subtitle boundaries differ.
    Dynamic programming keeps each comparison local and independently rated.
    """
    n, m = len(source), len(translation)
    cost = [[math.inf] * (m + 1) for _ in range(n + 1)]
    back = {}
    cost[0][0] = 0.0

    def consider(i, j, ni, nj, step_cost):
        next_cost = cost[i][j] + step_cost
        if next_cost < cost[ni][nj] - 1e-9:
            cost[ni][nj] = next_cost
            back[(ni, nj)] = (i, j)

    for i in range(n + 1):
        for j in range(m + 1):
            if not math.isfinite(cost[i][j]):
                continue
            for a in range(1, min(3, n - i) + 1):
                left = source[i:i + a]
                for b in range(1, min(3, m - j) + 1):
                    right = translation[j:j + b]
                    left_start = left[0]["start"]
                    left_end = max(cue["end"] for cue in left)
                    right_start = right[0]["start"]
                    right_end = max(cue["end"] for cue in right)
                    if min(left_end, right_end) - max(left_start, right_start) <= 0.025:
                        continue
                    # Every cue in a matched group must overlap the other side.
                    def touches(a, b):
                        return min(a["end"], b["end"]) - max(a["start"], b["start"]) > 0.025
                    if (any(not any(touches(s, t) for t in right) for s in left)
                            or any(not any(touches(s, t) for s in left) for t in right)):
                        continue
                    edge_error = (
                        abs(left_start - right_start)
                        + abs(left_end - right_end)
                    )
                    consider(i, j, i + a, j + b,
                             edge_error + 0.6 * (a + b - 2))
            if i < n:
                consider(i, j, i + 1, j, 2.5)
            if j < m:
                consider(i, j, i, j + 1, 2.5)

    steps = []
    point = (n, m)
    while point != (0, 0):
        start = back[point]
        steps.append((start, point))
        point = start
    steps.reverse()

    groups = []
    for (i, j), (end_i, end_j) in steps:
        source_cues = source[i:end_i]
        target_cues = translation[j:end_j]
        both = source_cues + target_cues
        groups.append({
            "start_s": round(min(cue["start"] for cue in both), 3),
            "end_s": round(max(cue["end"] for cue in both), 3),
            "source_cues": list(range(i + 1, end_i + 1)),
            "translation_cues": list(range(j + 1, end_j + 1)),
            "source_text": " ".join(c["text"] for c in source_cues).strip(),
            "translation_text": " ".join(c["text"] for c in target_cues).strip(),
        })
    return groups
