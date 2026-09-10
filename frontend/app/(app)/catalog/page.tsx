"use client";

// Catalog screen: live course list + the sync HITL panel (run → review the
// staged changeset → approve/reject).

import { useCallback, useEffect, useState } from "react";

import {
  approveSyncRun,
  fetchCourse,
  fetchCourses,
  fetchSyncRuns,
  rejectSyncRun,
  startSync,
} from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { Course, CourseDetail, SyncRun } from "@/types/course";
import SyncReviewPanel from "@/components/catalog/SyncReviewPanel";
import { RefreshCw, Search } from "@/components/icons";
import {
  Badge,
  Button,
  Callout,
  DisclosureList,
  DisclosureRow,
  EmptyState,
  PageHeader,
  TextInput,
} from "@/components/ui";
import styles from "./catalog.module.css";

const RUNNING_POLL_MS = 2000;

export default function CatalogPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<CourseDetail | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  // Code → title for every course seen so far. The changeset identifies courses
  // by code, and the list above it can be filtered down by a search, so the
  // review panel needs a lookup that outlives the current filter.
  const [courseTitles, setCourseTitles] = useState<Record<string, string>>({});
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
      setCourseTitles((previous) => ({
        ...previous,
        ...Object.fromEntries(
          fetchedCourses.map((course) => [course.course_code, course.title]),
        ),
      }));
      setError(null);
    } catch (err) {
      setError(errorMessage(err, "Could not load catalog."));
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
      setError(errorMessage(err, "Action failed."));
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
      <PageHeader
        title="Course catalog"
        lede="Scraped from wrcc.nsw.edu.au — changes only go live after your approval."
        actions={
          <Button
            variant="primary"
            icon={<RefreshCw size={16} />}
            onClick={() => void withBusy(startSync)}
            disabled={isBusy || hasRunningRun || pendingRun !== null}
          >
            {hasRunningRun ? "Sync running…" : "Run sync"}
          </Button>
        }
      />

      {error ? (
        <Callout tone="danger" role="alert">
          {error}
        </Callout>
      ) : null}

      {hasRunningRun ? (
        <Callout tone="neutral">
          Crawling every category and course page. Nothing changes until the
          result comes back here for review.
        </Callout>
      ) : null}

      {pendingRun ? (
        <SyncReviewPanel
          run={pendingRun}
          isBusy={isBusy}
          courseTitles={courseTitles}
          onApprove={(skip) =>
            void withBusy(() => approveSyncRun(pendingRun.id, skip))
          }
          onReject={(reason) =>
            void withBusy(() => rejectSyncRun(pendingRun.id, reason))
          }
        />
      ) : latestRun && latestRun.status === "failed" ? (
        <Callout tone="danger">Last sync failed: {latestRun.error}</Callout>
      ) : null}

      <div className={styles.toolbar}>
        <TextInput
          type="search"
          controlSize="sm"
          icon={<Search size={18} />}
          className={styles.search}
          placeholder="Search title or code…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          aria-label="Search courses"
        />
        <span className={styles.count}>{courses.length} active courses</span>
      </div>

      {courses.length === 0 ? (
        <EmptyState>No courses yet — run a sync and approve the changeset.</EmptyState>
      ) : (
        <DisclosureList>
          {courses.map((course) => (
            <DisclosureRow
              key={course.id}
              isExpanded={expanded?.id === course.id}
              onToggle={() => void toggleCourse(course)}
              bodyVariant="flush"
              summary={
                <>
                  <span className={styles.code}>{course.course_code}</span>
                  <span className={styles.rowTitle}>{course.title}</span>
                  {course.category ? (
                    <span className={styles.category}>{course.category}</span>
                  ) : null}
                  {course.is_accredited ? <Badge tone="accent">Accredited</Badge> : null}
                </>
              }
            >
              {expanded && expanded.offerings.length === 0 ? (
                <EmptyState size="sm">No scheduled offerings.</EmptyState>
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
                    {expanded?.offerings.map((offering) => (
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
            </DisclosureRow>
          ))}
        </DisclosureList>
      )}
    </div>
  );
}
