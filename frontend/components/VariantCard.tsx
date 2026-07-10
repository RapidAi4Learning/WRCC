"use client";

// One generated variant with inline workflow actions. Used by Generate
// (fresh results) and History (expanded row).

import { useState } from "react";

import { ApiError, contentAction, editContent } from "@/lib/api";
import type { ContentItem, WorkflowAction } from "@/types/content";
import { PlatformBadge, StatusBadge } from "@/components/Badges";
import styles from "./VariantCard.module.css";

const STYLE_LABELS: Record<string, string> = {
  direct: "A · Direct",
  story_led: "B · Story-led",
  question_led: "C · Question-led",
};

interface VariantCardProps {
  item: ContentItem;
  onChange: (updated: ContentItem, action: WorkflowAction | "edit") => void;
  showPlatform?: boolean;
}

export default function VariantCard({
  item,
  onChange,
  showPlatform = false,
}: VariantCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [draftBody, setDraftBody] = useState(item.body);
  const [error, setError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  async function runAction(
    action: WorkflowAction,
    payload?: { reason?: string; instruction?: string },
  ) {
    setError(null);
    setBusyAction(action);
    try {
      const updated = await contentAction(item.id, action, payload);
      onChange(updated, action);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Action failed.");
    } finally {
      setBusyAction(null);
    }
  }

  async function saveEdit() {
    setError(null);
    setBusyAction("edit");
    try {
      const updated = await editContent(item.id, draftBody);
      setIsEditing(false);
      onChange(updated, "edit");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Edit failed.");
    } finally {
      setBusyAction(null);
    }
  }

  function handleReject() {
    const reason = window.prompt("Reason for rejection (optional):") ?? undefined;
    void runAction("reject", reason ? { reason } : undefined);
  }

  function handleRegenerate() {
    const instruction =
      window.prompt("Instruction for the regeneration (optional):") ?? undefined;
    void runAction("regenerate", instruction ? { instruction } : undefined);
  }

  const actions: Array<{ label: string; onClick: () => void; show: boolean }> = [
    {
      label: "Submit for approval",
      onClick: () => void runAction("submit"),
      show: item.status === "draft",
    },
    {
      label: "Approve",
      onClick: () => void runAction("approve"),
      show: item.status === "pending_approval",
    },
    {
      label: "Reject",
      onClick: handleReject,
      show: item.status === "pending_approval",
    },
    {
      label: "Edit",
      onClick: () => {
        setDraftBody(item.body);
        setIsEditing(true);
      },
      show: !isEditing && item.status !== "archived" && item.status !== "approved",
    },
    {
      label: "Duplicate",
      onClick: () => void runAction("duplicate"),
      show: true,
    },
    {
      label: "Regenerate",
      onClick: handleRegenerate,
      show: item.status !== "archived",
    },
    {
      label: "Archive",
      onClick: () => void runAction("archive"),
      show: item.status !== "archived",
    },
    {
      label: "Restore",
      onClick: () => void runAction("restore"),
      show: item.status === "archived",
    },
  ];

  return (
    <article className={styles.card} data-status={item.status}>
      <header className={styles.header}>
        <span className={styles.style}>
          {STYLE_LABELS[item.variant_style] ?? item.variant_style}
        </span>
        {showPlatform ? <PlatformBadge platform={item.platform} /> : null}
        <StatusBadge status={item.status} />
      </header>

      {isEditing ? (
        <div className={styles.editArea}>
          <textarea
            className={styles.textarea}
            value={draftBody}
            rows={6}
            onChange={(event) => setDraftBody(event.target.value)}
            aria-label="Edit post body"
          />
          <div className={styles.editActions}>
            <button
              type="button"
              className={styles.primary}
              onClick={() => void saveEdit()}
              disabled={busyAction === "edit"}
            >
              Save
            </button>
            <button
              type="button"
              className={styles.action}
              onClick={() => setIsEditing(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <p className={styles.body}>{item.body}</p>
      )}

      {item.hashtags.length > 0 ? (
        <p className={styles.hashtags}>{item.hashtags.join(" ")}</p>
      ) : null}
      {item.call_to_action ? (
        <p className={styles.cta}>{item.call_to_action}</p>
      ) : null}

      {error ? (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      ) : null}

      <footer className={styles.actions}>
        {actions
          .filter((action) => action.show)
          .map((action) => (
            <button
              key={action.label}
              type="button"
              className={styles.action}
              onClick={action.onClick}
              disabled={busyAction !== null}
            >
              {action.label}
            </button>
          ))}
      </footer>
    </article>
  );
}
