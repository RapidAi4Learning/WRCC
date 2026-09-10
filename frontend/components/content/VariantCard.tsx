"use client";

// One generated variant with inline workflow actions. Used by Generate
// (fresh results) and History (expanded row).

import { useEffect, useState } from "react";

import {
  contentAction,
  editContent,
  fetchContentItem,
  fetchPublications,
} from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { composePostText } from "@/lib/postText";
import { publishingHold } from "@/lib/publishing";
import type { ContentItem, WorkflowAction } from "@/types/content";
import type { Publication } from "@/types/publishing";
import { PlatformBadge, StatusBadge } from "@/components/content/Badges";
import MediaPanel from "@/components/content/MediaPanel";
import PublishDialog from "@/components/content/PublishDialog";
import { Check, Copy } from "@/components/icons";
import { Button, Callout, PromptDialog, TextArea, cardClass } from "@/components/ui";
import styles from "./VariantCard.module.css";

const COPIED_FEEDBACK_MS = 2000;
const ICON_SIZE = 14;

const STYLE_LABELS: Record<string, string> = {
  direct: "A · Direct",
  story_led: "B · Story-led",
  question_led: "C · Question-led",
};

// The two actions that take a short piece of text before running.
type Prompted = "reject" | "regenerate";

const PROMPTS: Record<
  Prompted,
  { title: string; label: string; placeholder: string; confirmLabel: string; field: "reason" | "instruction" }
> = {
  reject: {
    title: "Reject this post?",
    label: "Reason",
    placeholder: "e.g. The course date is wrong",
    confirmLabel: "Reject post",
    field: "reason",
  },
  regenerate: {
    title: "Regenerate this post",
    label: "Instruction",
    placeholder: "e.g. Shorter, and mention the Leeton date",
    confirmLabel: "Regenerate post",
    field: "instruction",
  },
};

interface VariantCardProps {
  item: ContentItem;
  onChange: (
    updated: ContentItem,
    action: WorkflowAction | "edit" | "publish",
  ) => void;
  showPlatform?: boolean;
}

interface CardAction {
  label: string;
  onClick: () => void;
  show: boolean;
  /** The one next step for this status: drawn as the lime call to action. */
  isPrimary?: boolean;
  disabled?: boolean;
  title?: string;
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
  const [hasCopied, setHasCopied] = useState(false);
  const [isPublishOpen, setIsPublishOpen] = useState(false);
  const [prompted, setPrompted] = useState<Prompted | null>(null);
  const [permalink, setPermalink] = useState<string | null>(null);

  const isPublished = item.status === "published";
  // A network-wide hold outranks the item's own workflow state: the post can be
  // perfectly approved and still have nowhere to go.
  const hold = publishingHold(item.platform);

  // A published card states where it went live. The permalink lives on the
  // attempt, not the item, so it costs one small request — only for the cards
  // that have something to link to.
  useEffect(() => {
    if (!isPublished || permalink !== null) return;
    let cancelled = false;
    fetchPublications(item.id)
      .then((publications) => {
        const live = publications.find((p) => p.status === "succeeded");
        if (!cancelled && live?.permalink) setPermalink(live.permalink);
      })
      .catch(() => {
        // The badge already says it is published; a missing link is not worth
        // an error banner on an otherwise healthy card.
      });
    return () => {
      cancelled = true;
    };
  }, [isPublished, permalink, item.id]);

  // Revert the "Copied" label on its own; the cleanup also covers the card
  // unmounting (History collapsing a row) before the timer fires.
  useEffect(() => {
    if (!hasCopied) return;
    const timer = window.setTimeout(() => setHasCopied(false), COPIED_FEEDBACK_MS);
    return () => window.clearTimeout(timer);
  }, [hasCopied]);

  async function handleCopy() {
    setError(null);
    try {
      // Throws when the Clipboard API is missing entirely — it needs a secure
      // context, so serving the app over plain http on a LAN IP has none.
      await navigator.clipboard.writeText(composePostText(item));
      setHasCopied(true);
    } catch {
      setError("Could not copy to the clipboard.");
    }
  }

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
      setError(errorMessage(err, "Action failed."));
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
      setError(errorMessage(err, "Edit failed."));
    } finally {
      setBusyAction(null);
    }
  }

  function submitPrompt(kind: Prompted, value: string) {
    setPrompted(null);
    // Blank means "no reason given", not an empty reason.
    void runAction(kind, value ? { [PROMPTS[kind].field]: value } : undefined);
  }

  async function handlePublished(publication: Publication) {
    setPermalink(publication.permalink);
    // The dialog stays open on its success panel; refresh the item underneath
    // from the server rather than assuming what the publish did to its status.
    try {
      onChange(await fetchContentItem(item.id), "publish");
    } catch {
      // The post is live either way — the card catches up on the next load.
    }
  }

  const actions: CardAction[] = [
    {
      label: "Submit for approval",
      onClick: () => void runAction("submit"),
      show: item.status === "draft",
      isPrimary: true,
    },
    {
      label: "Approve",
      onClick: () => void runAction("approve"),
      show: item.status === "pending_approval",
      isPrimary: true,
    },
    {
      label: "Reject",
      onClick: () => setPrompted("reject"),
      show: item.status === "pending_approval",
    },
    {
      // Opens the preflight dialog, which is where the actual publish is
      // confirmed — so the card's button promises a look, not a post.
      label: "Preview",
      onClick: () => setIsPublishOpen(true),
      show: item.status === "approved",
      isPrimary: true,
      // Disabled rather than hidden: a missing button reads as a bug, and the
      // reason is worth telling the person who was about to click it.
      disabled: hold !== null,
      title: hold ?? undefined,
    },
    {
      label: "Edit",
      onClick: () => {
        setDraftBody(item.body);
        setIsEditing(true);
      },
      // Published is absent for the same reason approved is, only harder: the
      // text is already live on someone else's server, so editing it here would
      // silently put our copy out of step with theirs.
      show:
        !isEditing &&
        item.status !== "archived" &&
        item.status !== "approved" &&
        !isPublished,
    },
    {
      label: "Duplicate",
      onClick: () => void runAction("duplicate"),
      show: true,
    },
    {
      label: "Regenerate",
      onClick: () => setPrompted("regenerate"),
      show: item.status !== "archived" && !isPublished,
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
      isPrimary: true,
    },
  ];

  return (
    <article
      className={cardClass({ padding: "sm", className: styles.card })}
      data-status={item.status}
    >
      <header className={styles.header}>
        <span className={styles.style}>
          {STYLE_LABELS[item.variant_style] ?? item.variant_style}
        </span>
        {showPlatform ? <PlatformBadge platform={item.platform} /> : null}
        <StatusBadge status={item.status} />
        {permalink ? (
          <a
            className={styles.permalink}
            href={permalink}
            target="_blank"
            rel="noopener noreferrer"
          >
            View post ↗
          </a>
        ) : null}
        {/* In the header next to the badges, so it stays reachable whether the
            card is a fresh result or an expanded History row. The confirmed
            state borrows the primary look so it reads as success. */}
        <Button
          size="sm"
          variant={hasCopied ? "primary" : "secondary"}
          icon={hasCopied ? <Check size={ICON_SIZE} /> : <Copy size={ICON_SIZE} />}
          onClick={() => void handleCopy()}
        >
          {hasCopied ? "Copied" : "Copy"}
        </Button>
      </header>

      {isEditing ? (
        <div className={styles.editArea}>
          <TextArea
            controlSize="sm"
            value={draftBody}
            rows={6}
            onChange={(event) => setDraftBody(event.target.value)}
            aria-label="Edit post body"
          />
          <div className={styles.editActions}>
            <Button
              size="sm"
              variant="primary"
              onClick={() => void saveEdit()}
              disabled={busyAction === "edit"}
            >
              Save
            </Button>
            <Button size="sm" onClick={() => setIsEditing(false)}>
              Cancel
            </Button>
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
        <Callout tone="danger" size="sm" role="alert">
          {error}
        </Callout>
      ) : null}

      <footer className={styles.actions}>
        {actions
          .filter((action) => action.show)
          .map((action) => (
            <Button
              key={action.label}
              size="sm"
              variant={action.isPrimary ? "primary" : "secondary"}
              onClick={action.onClick}
              disabled={busyAction !== null || action.disabled === true}
              title={action.title}
            >
              {action.label}
            </Button>
          ))}
      </footer>

      <MediaPanel itemId={item.id} />

      {/* Why the Preview button above is dead: a notice, not an error. */}
      {hold && item.status === "approved" ? (
        <Callout tone="warn" size="sm">
          {hold}
        </Callout>
      ) : null}

      {prompted ? (
        <PromptDialog
          title={PROMPTS[prompted].title}
          label={PROMPTS[prompted].label}
          placeholder={PROMPTS[prompted].placeholder}
          confirmLabel={PROMPTS[prompted].confirmLabel}
          tone={prompted === "reject" ? "danger" : "primary"}
          onSubmit={(value) => submitPrompt(prompted, value)}
          onCancel={() => setPrompted(null)}
        />
      ) : null}

      {isPublishOpen && !hold ? (
        <PublishDialog
          item={item}
          onClose={() => setIsPublishOpen(false)}
          onPublished={(publication) => void handlePublished(publication)}
        />
      ) : null}
    </article>
  );
}
