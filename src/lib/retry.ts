import { RETRY_ATTEMPTS, RETRY_BACKOFF_SECONDS } from "./config.ts";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Retry a flaky call with linear backoff. Rethrows the last error if every
 * attempt fails. Port of old/pipeline.py's retry(). */
export async function retry<T>(
	fn: () => Promise<T>,
	what: string,
	attempts = RETRY_ATTEMPTS,
	backoffSeconds = RETRY_BACKOFF_SECONDS,
): Promise<T> {
	let lastErr: unknown;
	for (let attempt = 1; attempt <= attempts; attempt++) {
		try {
			return await fn();
		} catch (e) {
			lastErr = e;
			console.warn(`${what} failed (attempt ${attempt}/${attempts}): ${e}`);
			if (attempt < attempts) await sleep(backoffSeconds * attempt * 1000);
		}
	}
	throw lastErr;
}
