"use client";

// Catalog screen: live course list + the sync HITL panel (run → review the
// staged changeset → approve/reject).

import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  approveSyncRun,
  fetchCourse,
  fetchCourses,
  fetchSyncRuns,
  rejectSyncRun,
  startSync,
} from "@/lib/api";
import type { Course, CourseDetail, SyncRun } from "@/types/course";
import styles from "./catalog.module.css";

const RUNNING_POLL_MS = 2000;

export default function CatalogPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<CourseDetail | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [fetchedCourses, fetchedRuns] = await Promise.all([
        fetchCourses(search ? { search } : undefined),
        fetchSyncRuns(),
      ]);
      setCourses(fetchedCourses);
      setRuns(fetchedRuns);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load catalog.");
    }
  }, [search]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll while a crawl is running so the pending changeset appears unaided.
  const hasRunningRun = runs.some((run) => run.status === "running");
  useEffect(() => {
    if (!hasRunningRun) return;
    const interval = setInterval(() => void load(), RUNNING_POLL_MS);
    return () => clearInterval(interval);
  }, [hasRunningRun, load]);

  const pendingRun = runs.find((run) => run.status === "pending") ?? null;
  const latestRun = runs[0] ?? null;

  async function withBusy(work: () => Promise<unknown>) {
    setIsBusy(true);
    setError(null);
    try {
      await work();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setIsBusy(false);
    }
  }

  async function toggleCourse(course: Course) {
    if (expanded?.id === course.id) {
      setExpanded(null);
      return;
    }
    try {
      setExpanded(await fetchCourse(course.id));
    } catch {
      setError("Could not load course offerings.");
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Course catalog</h1>
          <p className={styles.lede}>
            Scraped from wrcc.nsw.edu.au — changes only go live after your
            approval.
          </p>
        </div>
        <button
          type="button"
          className={styles.syncButton}
          onClick={() => void withBusy(startSync)}
          disabled={isBusy || hasRunningRun || pendingRun !== null}
        >
          {hasRunningRun ? "Sync running…" : "Run sync"}
        </button>
      </header>

      {error ? (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      ) : null}

      {pendingRun ? (
        <section className={styles.pendingPanel} aria-label="Pending sync review">
          <h2 className={styles.pendingTitle}>Changeset awaiting review</h2>
          <p className={styles.pendingMeta}>
            {pendingRun.courses_found} courses · {pendingRun.offerings_found}{" "}
            offerings crawled
          </p>
          {pendingRun.changeset?.summary ? (
            <dl className={styles.summary}>
              {Object.entries(pendingRun.changeset.summary).map(([key, value]) => (
                <div key={key} className={styles.summaryItem}>
                  <dt>{key.replace(/_/g, " ")}</dt>
                  <dd data-nonzero={Number(value) > 0}>{value as number}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          <div className={styles.pendingActions}>
            <button
              type="button"
              className={styles.approve}
              onClick={() => void withBusy(() => approveSyncRun(pendingRun.id))}
              disabled={isBusy}
            >
              Approve &amp; apply
            </button>
            <button
              type="button"
              className={styles.reject}
              onClick={() => {
                const reason = window.prompt("Reason (optional):") ?? undefined;
                void withBusy(() => rejectSyncRun(pendingRun.id, reason));
              }}
              disabled={isBusy}
            >
              Reject
            </button>
          </div>
        </section>
      ) : latestRun && latestRun.status === "failed" ? (
        <p className={styles.error}>Last sync failed: {latestRun.error}</p>
      ) : null}

      <div className={styles.toolbar}>
        <input
          type="search"
          className={styles.search}
          placeholder="Search title or code…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          aria-label="Search courses"
        />
        <span className={styles.count}>{courses.length} active courses</span>
      </div>

      {courses.length === 0 ? (
        <p className={styles.empty}>
          No courses yet — run a sync and approve the changeset.
        </p>
      ) : (
        <ul className={styles.list}>
          {courses.map((course) => (
            <li key={course.id} className={styles.row}>
              <button
                type="button"
                className={styles.rowButton}
                onClick={() => void toggleCourse(course)}
                aria-expanded={expanded?.id === course.id}
              >
                <span className={styles.code}>{course.course_code}</span>
                <span className={styles.rowTitle}>{course.title}</span>
                {course.category ? (
                  <span className={styles.category}>{course.category}</span>
                ) : null}
                {course.is_accredited ? (
                  <span className={styles.accredited}>Accredited</span>
                ) : null}
              </button>
              {expanded?.id === course.id ? (
                <div className={styles.offerings}>
                  {expanded.offerings.length === 0 ? (
                    <p className={styles.empty}>No scheduled offerings.</p>
                  ) : (
                    <table className={styles.table}>
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Time</th>
                          <th>Location</th>
                          <th>Spaces</th>
                          <th>Cost</th>
                        </tr>
                      </thead>
                      <tbody>
                        {expanded.offerings.map((offering) => (
                          <tr key={offering.id}>
                            <td>
                              {offering.start_date ?? "On demand"}
                              {offering.finish_date &&
                              offering.finish_date !== offering.start_date
                                ? ` → ${offering.finish_date}`
                                : ""}
                            </td>
                            <td>{offering.time_text ?? "—"}</td>
                            <td>{offering.location ?? "—"}</td>
                            <td>{offering.places_available ?? "—"}</td>
                            <td>
                              {offering.price !== null
                                ? `$${offering.price.toFixed(2)}`
                                : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
