import { ApiError } from "@/lib/api";

/**
 * The message to show for a failed call: the server's own `detail` when it sent
 * one, otherwise the caller's fallback. Anything that is not an ApiError (a
 * network failure, a bug) gets the fallback — its raw message is not written
 * for the person reading the screen.
 */
export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}
