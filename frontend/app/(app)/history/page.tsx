"use client";

// Persistent generation history: filters + expandable rows with the full
// workflow (approve/reject/edit/duplicate/regenerate…).

import { useCallback, useEffect, useState } from "react";

import { fetchContent } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { PLATFORMS, PLATFORM_LABELS, STATUSES, STATUS_LABELS } from "@/lib/platforms";
import type { ContentItem, ContentStatus, Platform } from "@/types/content";
import { PlatformBadge, StatusBadge } from "@/components/content/Badges";
import VariantCard from "@/components/content/VariantCard";
import {
  Callout,
  DisclosureList,
  DisclosureRow,
  EmptyState,
  PageHeader,
  Select,
} from "@/components/ui";
import styles from "./history.module.css";

const PLATFORM_OPTIONS: Array<{ value: Platform | ""; label: string }> = [
  { value: "", label: "All platforms" },
  ...PLATFORMS.map((platform) => ({ value: platform, label: PLATFORM_LABELS[platform] })),
];

const STATUS_OPTIONS: Array<{ value: ContentStatus | ""; label: string }> = [
  { value: "", label: "All statuses" },
  ...STATUSES.map((status) => ({ value: status, label: STATUS_LABELS[status] })),
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
      setError(errorMessage(err, "Could not load history."));
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
      <PageHeader
        title="History"
        lede="Everything ever generated, with its approval trail."
        actions={
          <>
            <Select
              value={platform}
              onChange={(event) => setPlatform(event.target.value as Platform | "")}
              aria-label="Filter by platform"
            >
              {PLATFORM_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
            <Select
              value={status}
              onChange={(event) => setStatus(event.target.value as ContentStatus | "")}
              aria-label="Filter by status"
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </>
        }
      />

      {error ? (
        <Callout tone="danger" role="alert">
          {error}
        </Callout>
      ) : null}

      {isLoading ? (
        <EmptyState>Loading…</EmptyState>
      ) : items.length === 0 ? (
        <EmptyState>Nothing here yet — generate some content first.</EmptyState>
      ) : (
        <DisclosureList>
          {items.map((item) => (
            <DisclosureRow
              key={item.id}
              isExpanded={expandedId === item.id}
              onToggle={() =>
                setExpandedId((current) => (current === item.id ? null : item.id))
              }
              summary={
                <>
                  <PlatformBadge platform={item.platform} />
                  <span className={styles.rowTopic}>
                    {item.topic ?? item.body.slice(0, 80)}
                  </span>
                  <span className={styles.rowDate}>
                    {new Date(item.created_at).toLocaleDateString()}
                  </span>
                  <StatusBadge status={item.status} />
                </>
              }
            >
              <VariantCard item={item} onChange={handleItemChange} showPlatform />
            </DisclosureRow>
          ))}
        </DisclosureList>
      )}
    </div>
  );
}
