// Thin API client for the FastAPI backend. Server state is fetched here; the
// page handles loading/empty/error states (container/presentational split).

import type { AuthUser, LoginCredentials } from "@/types/auth";
import type {
  ContentImage,
  ContentItem,
  ContentStatus,
  GenerateContentInput,
  GenerateContentResult,
  ImageSuggestions,
  Platform,
  WorkflowAction,
} from "@/types/content";
import type { Course, CourseDetail, SyncRun } from "@/types/course";

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

// ── Post images ──

export function fetchImageSuggestions(itemId: string): Promise<ImageSuggestions> {
  return request<ImageSuggestions>(`/api/content/${itemId}/images/suggestions`, {
    method: "POST",
  });
}

export function generateImage(
  itemId: string,
  prompt: string,
): Promise<ContentImage> {
  return request<ContentImage>(`/api/content/${itemId}/images`, {
    method: "POST",
    body: JSON.stringify({ prompt }),
  });
}

export function fetchImages(itemId: string): Promise<ContentImage[]> {
  return request<ContentImage[]>(`/api/content/${itemId}/images`);
}

export function imageFileUrl(image: ContentImage, download = false): string {
  return `${API_BASE}${image.file_url}${download ? "?download=true" : ""}`;
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

export function approveSyncRun(runId: string): Promise<SyncRun> {
  return request<SyncRun>(`/api/courses/sync/${runId}/approve`, { method: "POST" });
}

export function rejectSyncRun(runId: string, reason?: string): Promise<SyncRun> {
  return request<SyncRun>(`/api/courses/sync/${runId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  });
}
