// Session-scoped cache of the authenticated user (module-level, per tab).

import { fetchCurrentUser, logoutSession } from "@/lib/api";
import type { AuthUser } from "@/types/auth";

let currentUser: AuthUser | null = null;

export function setCurrentUser(user: AuthUser | null): void {
  currentUser = user;
}

export async function getCurrentUser(options?: {
  refresh?: boolean;
  signal?: AbortSignal;
}): Promise<AuthUser> {
  if (currentUser && !options?.refresh) return currentUser;
  currentUser = await fetchCurrentUser(options?.signal);
  return currentUser;
}

export async function logout(): Promise<void> {
  await logoutSession();
  currentUser = null;
}
