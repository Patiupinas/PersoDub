// timeoutMs is how long a process may stay silent. An answer `busy` accepts
// (the voice engine saying it is still loading its model) is progress: it
// starts that clock again, up to maxMs in all -- a slow computer is not a
// hung one. `alive` is asked before every try, so a process that has already
// exited ends the wait at once instead of running the clock out on it.
export async function waitForHealth(url, { timeoutMs, intervalMs = 250, predicate = () => true,
                                           busy = () => false, maxMs = timeoutMs, alive = () => true } = {}) {
  const start = Date.now();
  let quietUntil = start + timeoutMs;
  let lastError = null;
  while (Date.now() < Math.min(quietUntil, start + maxMs)) {
    if (!alive()) {
      const err = new Error(`The process stopped before it answered: ${url}`);
      err.exited = true;
      throw err;
    }
    try {
      // A server that takes the connection and never answers must not hold
      // the loop past the next liveness check.
      const res = await fetch(url, { signal: AbortSignal.timeout(5000) });
      if (res.ok) {
        const body = await res.json();
        if (predicate(body)) return body;
        if (busy(body)) quietUntil = Date.now() + timeoutMs;
      }
    } catch (err) {
      lastError = err;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  const hint = lastError ? ` (last error: ${lastError.message})` : "";
  throw new Error(`Health check timed out after ${Date.now() - start}ms: ${url}${hint}`);
}
