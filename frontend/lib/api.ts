// Thin API client for the FastAPI backend. Server state is fetched here; the
// page handles loading/empty/error states (container/presentational split).

import type { AuthUser, LoginCredentials } from "@/types/auth";
import type {
  ContentItem,
  ContentStatus,
  GenerateContentInput,
  GenerateContentResult,
  ImageQuality,
  ImageSuggestions,
  MediaAsset,
  MediaLibrary,
  Platform,
  SetSelectionResult,
  WorkflowAction,
} from "@/types/content";
import type {
  ChangeSelection,
  Course,
  CourseDetail,
  SyncRun,
} from "@/types/course";
import type {
  AccountVerification,
  AuthorizeUrl,
  Publication,
  PublishPreflight,
  SocialAccount,
} from "@/types/publishing";

// Strip any trailing slash so `${API_BASE}/api/...` can't produce a double
// slash. Lets the env var be set with or without a trailing slash safely.
// Exported so <img>/<a> tags can reference backend-served files directly.
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body — keep the generic message.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

// ── Auth ──

export function loginSession(credentials: LoginCredentials): Promise<AuthUser> {
  return request<AuthUser>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(credentials),
  });
}

export function logoutSession(): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/api/auth/logout", { method: "POST" });
}

export function fetchCurrentUser(signal?: AbortSignal): Promise<AuthUser> {
  return request<AuthUser>("/api/auth/me", { signal });
}

// ── Content ──

export function generateContent(
  input: GenerateContentInput,
): Promise<GenerateContentResult> {
  return request<GenerateContentResult>("/api/content/generate", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function fetchContent(filters?: {
  platform?: Platform;
  status?: ContentStatus;
  course_id?: string;
}): Promise<ContentItem[]> {
  const params = new URLSearchParams();
  if (filters?.platform) params.set("platform", filters.platform);
  if (filters?.status) params.set("status_filter", filters.status);
  if (filters?.course_id) params.set("course_id", filters.course_id);
  const query = params.toString();
  return request<ContentItem[]>(`/api/content${query ? `?${query}` : ""}`);
}

export function fetchContentItem(itemId: string): Promise<ContentItem> {
  return request<ContentItem>(`/api/content/${itemId}`);
}

export function contentAction(
  itemId: string,
  action: WorkflowAction,
  payload?: { reason?: string; instruction?: string },
): Promise<ContentItem> {
  return request<ContentItem>(`/api/content/${itemId}/${action}`, {
    method: "POST",
    body: payload ? JSON.stringify(payload) : undefined,
  });
}

export function editContent(itemId: string, body: string): Promise<ContentItem> {
  return request<ContentItem>(`/api/content/${itemId}`, {
    method: "PUT",
    body: JSON.stringify({ body }),
  });
}

// ── Post media ──

export function fetchImageSuggestions(itemId: string): Promise<ImageSuggestions> {
  return request<ImageSuggestions>(`/api/content/${itemId}/images/suggestions`, {
    method: "POST",
  });
}

export function generateImage(
  itemId: string,
  prompt: string,
  // Absent keeps the server's IMAGE_QUALITY.
  quality?: ImageQuality,
): Promise<MediaAsset> {
  return request<MediaAsset>(`/api/content/${itemId}/images`, {
    method: "POST",
    body: JSON.stringify({ prompt, quality }),
  });
}

export function fetchImages(itemId: string): Promise<MediaAsset[]> {
  return request<MediaAsset[]>(`/api/content/${itemId}/images`);
}

export function fetchMedia(itemId: string): Promise<MediaLibrary> {
  return request<MediaLibrary>(`/api/content/${itemId}/media`);
}

// Multipart, so this deliberately bypasses `request`: setting a JSON
// Content-Type here would strip the boundary the server needs to parse the
// body, and the failure would look like a malformed upload rather than a
// header mistake.
export async function uploadMedia(
  itemId: string,
  files: File[],
): Promise<MediaAsset[]> {
  const form = new FormData();
  for (const file of files) form.append("files", file);

  const response = await fetch(`${API_BASE}/api/content/${itemId}/media`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!response.ok) {
    let detail = `Upload failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body — keep the generic message.
    }
    throw new ApiError(response.status, detail);
  }
  return response.json();
}

export function saveMediaSelection(
  itemId: string,
  assetIds: string[],
  applyToGroup = false,
): Promise<SetSelectionResult> {
  return request<SetSelectionResult>(`/api/content/${itemId}/media/selection`, {
    method: "PUT",
    body: JSON.stringify({ asset_ids: assetIds, apply_to_group: applyToGroup }),
  });
}

export async function deleteMediaAsset(assetId: string): Promise<void> {
  // 204 No Content — there is no body to parse, so this bypasses `request`.
  const response = await fetch(`${API_BASE}/api/content/media/${assetId}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok) {
    let detail = "Could not delete the image.";
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Non-JSON error body — keep the generic message.
    }
    throw new ApiError(response.status, detail);
  }
}

export function imageFileUrl(image: MediaAsset, download = false): string {
  return `${API_BASE}${image.file_url}${download ? "?download=true" : ""}`;
}

// ── Connected social accounts ──

export function fetchSocialAccounts(signal?: AbortSignal): Promise<SocialAccount[]> {
  return request<SocialAccount[]>("/api/social/accounts", { signal });
}

// Returns the provider's consent URL rather than redirecting, so a
// misconfiguration surfaces as a readable error instead of an opaque
// cross-origin redirect the page could not report on.
export function fetchAuthorizeUrl(platform: Platform): Promise<AuthorizeUrl> {
  return request<AuthorizeUrl>(`/api/social/${platform}/connect`);
}

// Pings the network. Resolves even when the token is dead — read `ok`.
export function verifySocialAccount(
  accountId: string,
): Promise<AccountVerification> {
  return request<AccountVerification>(
    `/api/social/accounts/${accountId}/verify`,
    { method: "POST" },
  );
}

export function activateSocialAccount(accountId: string): Promise<SocialAccount> {
  return request<SocialAccount>(`/api/social/accounts/${accountId}/activate`, {
    method: "POST",
  });
}

export async function disconnectSocialAccount(accountId: string): Promise<void> {
  // 204 No Content — there is no body to parse, so this bypasses `request`.
  const response = await fetch(`${API_BASE}/api/social/accounts/${accountId}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok) {
    throw new ApiError(response.status, "Could not disconnect the account.");
  }
}

// ── Publishing ──

// `assetIds` undefined means "whatever the post has saved"; an empty array
// means "send no images", which is a different instruction.
export function fetchPublishPreflight(
  itemId: string,
  assetIds?: string[],
): Promise<PublishPreflight> {
  const query =
    assetIds === undefined
      ? ""
      : `?asset_ids=${encodeURIComponent(assetIds.join(","))}`;
  return request<PublishPreflight>(
    `/api/content/${itemId}/publish/preflight${query}`,
  );
}

export function publishContent(
  itemId: string,
  assetIds?: string[],
): Promise<Publication> {
  return request<Publication>(`/api/content/${itemId}/publish`, {
    method: "POST",
    body: JSON.stringify({ asset_ids: assetIds ?? null }),
  });
}

export function fetchPublications(itemId: string): Promise<Publication[]> {
  return request<Publication[]>(`/api/content/${itemId}/publications`);
}

// ── Catalog ──

export function fetchCourses(filters?: {
  category?: string;
  search?: string;
  accredited?: boolean;
}): Promise<Course[]> {
  const params = new URLSearchParams();
  if (filters?.category) params.set("category", filters.category);
  if (filters?.search) params.set("search", filters.search);
  if (filters?.accredited !== undefined) {
    params.set("accredited", String(filters.accredited));
  }
  const query = params.toString();
  return request<Course[]>(`/api/courses${query ? `?${query}` : ""}`);
}

export function fetchCourse(courseId: string): Promise<CourseDetail> {
  return request<CourseDetail>(`/api/courses/${courseId}`);
}

// ── Catalog sync (HITL) ──

export function startSync(): Promise<SyncRun> {
  return request<SyncRun>("/api/courses/sync", { method: "POST" });
}

export function fetchSyncRuns(): Promise<SyncRun[]> {
  return request<SyncRun[]>("/api/courses/sync");
}

export function fetchSyncRun(runId: string): Promise<SyncRun> {
  return request<SyncRun>(`/api/courses/sync/${runId}`);
}

export function approveSyncRun(
  runId: string,
  skip?: ChangeSelection,
): Promise<SyncRun> {
  return request<SyncRun>(`/api/courses/sync/${runId}/approve`, {
    method: "POST",
    body: JSON.stringify({ skip: skip ?? null }),
  });
}

export function rejectSyncRun(runId: string, reason?: string): Promise<SyncRun> {
  return request<SyncRun>(`/api/courses/sync/${runId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}
