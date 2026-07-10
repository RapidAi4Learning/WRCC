"use client";

// Persistent generation history: filters + expandable rows with the full
// workflow (approve/reject/edit/duplicate/regenerate…).

import { useCallback, useEffect, useState } from "react";

import { ApiError, fetchContent } from "@/lib/api";
import type { ContentItem, ContentStatus, Platform } from "@/types/content";
import { PlatformBadge, StatusBadge } from "@/components/Badges";
import VariantCard from "@/components/VariantCard";
import styles from "./history.module.css";

const PLATFORM_OPTIONS: Array<{ value: Platform | ""; label: string }> = [
  { value: "", label: "All platforms" },
  { value: "facebook", label: "Facebook" },
  { value: "instagram", label: "Instagram" },
  { value: "linkedin", label: "LinkedIn" },
];

const STATUS_OPTIONS: Array<{ value: ContentStatus | ""; label: string }> = [
  { value: "", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "pending_approval", label: "Pending approval" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "archived", label: "Archived" },
];

export default function HistoryPage() {
  const [items, setItems] = useState<ContentItem[]>([]);
  const [platform, setPlatform] = useState<Platform | "">("");
  const [status, setStatus] = useState<ContentStatus | "">("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const fetched = await fetchContent({
        platform: platform || undefined,
        status: status || undefined,
      });
      setItems(fetched);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not load history.",
      );
    } finally {
      setIsLoading(false);
    }
  }, [platform, status]);

  useEffect(() => {
    void load();
  }, [load]);

  function handleItemChange(updated: ContentItem, action: string) {
    if (action === "duplicate" || action === "regenerate") {
      // A new row was created — refetch so it appears with current filters.
      void load();
      return;
    }
    setItems((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>History</h1>
          <p className={styles.lede}>
            Everything ever generated, with its approval trail.
          </p>
        </div>
        <div className={styles.filters}>
          <select
            className={styles.select}
            value={platform}
            onChange={(event) => setPlatform(event.target.value as Platform | "")}
            aria-label="Filter by platform"
          >
            {PLATFORM_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            className={styles.select}
            value={status}
            onChange={(event) => setStatus(event.target.value as ContentStatus | "")}
            aria-label="Filter by status"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </header>

      {error ? (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      ) : null}

      {isLoading ? (
        <p className={styles.empty}>Loading…</p>
      ) : items.length === 0 ? (
        <p className={styles.empty}>
          Nothing here yet — generate some content first.
        </p>
      ) : (
        <ul className={styles.list}>
          {items.map((item) => (
            <li key={item.id} className={styles.row}>
              <button
                type="button"
                className={styles.rowButton}
                onClick={() =>
                  setExpandedId((current) => (current === item.id ? null : item.id))
                }
                aria-expanded={expandedId === item.id}
              >
                <PlatformBadge platform={item.platform} />
                <span className={styles.rowTopic}>
                  {item.topic ?? item.body.slice(0, 80)}
                </span>
                <span className={styles.rowDate}>
                  {new Date(item.created_at).toLocaleDateString()}
                </span>
                <StatusBadge status={item.status} />
              </button>
              {expandedId === item.id ? (
                <div className={styles.expanded}>
                  <VariantCard item={item} onChange={handleItemChange} showPlatform />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
