"use client";

// The last screen before a post leaves this app.
//
// Publishing is the only action here with an effect on someone else's server
// that we cannot undo, so this dialog is deliberately unhurried: it shows the
// exact text that will be sent, the account it goes to and the image that will
// be attached, and it keeps the button disabled until the server's own
// preflight says every rule passes. The client never decides readiness itself —
// a second, drifting copy of those rules is precisely how a post gets sent that
// the backend would have refused.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import {
  fetchMedia,
  fetchPublishPreflight,
  imageFileUrl,
  publishContent,
} from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { PLATFORM_LABELS } from "@/lib/platforms";
import { publishingHold } from "@/lib/publishing";
import { toggleOrdered } from "@/lib/selection";
import type { MediaAsset, ContentItem } from "@/types/content";
import type { Publication, PublishPreflight } from "@/types/publishing";
import PostPreview from "@/components/content/PostPreview";
import {
  Badge,
  Button,
  Callout,
  Modal,
  ModalFooter,
  SectionLabel,
  SelectableThumb,
} from "@/components/ui";
import styles from "./PublishDialog.module.css";

interface PublishDialogProps {
  item: ContentItem;
  onClose: () => void;
  // Fired only for an attempt that actually went live, so the card can refresh
  // itself. A failed attempt is reported inside the dialog instead.
  onPublished: (publication: Publication) => void;
}

export default function PublishDialog({
  item,
  onClose,
  onPublished,
}: PublishDialogProps) {
  const [preflight, setPreflight] = useState<PublishPreflight | null>(null);
  const [library, setLibrary] = useState<MediaAsset[] | null>(null);
  // `null` means "whatever the post has saved". The saved selection comes back
  // in the preflight, so it is derived rather than copied — copying it into
  // state would cost a second round trip and give it a chance to disagree.
  // A non-null empty array is a real instruction: send no images.
  const [override, setOverride] = useState<string[] | null>(null);
  const [isChecking, setIsChecking] = useState(true);
  const [isPublishing, setIsPublishing] = useState(false);
  const [isArmed, setIsArmed] = useState(false);
  const [result, setResult] = useState<Publication | null>(null);
  const [error, setError] = useState<string | null>(null);

  const label = PLATFORM_LABELS[item.platform];
  // A hold on the whole network. Kept here as well as on the card that opens
  // this dialog: the preflight knows nothing about it, so a dialog reached by
  // any other route would otherwise show a live Publish button.
  const hold = publishingHold(item.platform);

  const runPreflight = useCallback(
    async (assetIds: string[] | null) => {
      setIsChecking(true);
      try {
        setPreflight(await fetchPublishPreflight(item.id, assetIds ?? undefined));
        setError(null);
      } catch (err) {
        setError(errorMessage(err, "Could not check this post."));
      } finally {
        setIsChecking(false);
      }
    },
    [item.id],
  );

  useEffect(() => {
    void runPreflight(override);
  }, [runPreflight, override]);

  useEffect(() => {
    let cancelled = false;
    fetchMedia(item.id)
      .then((media) => {
        if (!cancelled) setLibrary(media.library);
      })
      .catch(() => {
        // The picker is an aid; preflight already reports a missing image as a
        // blocker, so failing to list them must not block publishing.
        if (!cancelled) setLibrary([]);
      });
    return () => {
      cancelled = true;
    };
  }, [item.id]);

  // What will actually be sent, in order: the operator's override if they have
  // touched the picker, otherwise whatever the server says the post holds.
  const selectedIds = override ?? preflight?.image_ids ?? [];
  const selectedAssets = selectedIds
    .map((id) => (library ?? []).find((asset) => asset.id === id))
    .filter((asset): asset is MediaAsset => asset !== undefined);

  function toggleImage(assetId: string) {
    // Past the ceiling the tick is simply ignored — the counter beside the
    // thumbnails already says why.
    const max = preflight?.max_images ?? Number.POSITIVE_INFINITY;
    const { list, isOverLimit } = toggleOrdered(selectedIds, assetId, max);
    if (!isOverLimit) setOverride(list);
  }

  async function runPublish() {
    setError(null);
    setIsPublishing(true);
    try {
      const publication = await publishContent(item.id, selectedIds);
      setResult(publication);
      if (publication.status === "succeeded") {
        onPublished(publication);
      } else {
        // A failed attempt comes back 200 with the reason — it is a durable
        // record, not a transport error. Re-check so the button reflects
        // whatever the failure left behind.
        void runPreflight(override);
      }
    } catch (err) {
      // 409 (already live) and 422 (blockers) both land here; both change what
      // preflight would now say.
      setError(errorMessage(err, "Publishing failed."));
      void runPreflight(override);
    } finally {
      setIsPublishing(false);
      setIsArmed(false);
    }
  }

  const succeeded = result?.status === "succeeded";
  // The network took the post but would not name it, so something is probably
  // live. Preflight cannot see that — the item is still `approved` and every
  // rule still passes — so the button has to be held shut here. Re-publishing
  // is the one thing that must not be one click away from this state.
  const isAmbiguous = result?.status === "failed" && result.error_code === "ambiguous";
  const isOverLimit = preflight ? preflight.char_count > preflight.char_limit : false;
  const canPublish =
    hold === null &&
    preflight !== null &&
    preflight.ready &&
    !isChecking &&
    !isPublishing &&
    !isAmbiguous;

  return (
    <Modal
      title={`Publish to ${label}`}
      hint="This sends the post to the live account. It cannot be undone from here."
      accent={item.platform}
      onClose={onClose}
    >
      {succeeded && result ? (
        <PublishedPanel label={label} result={result} onClose={onClose} />
      ) : (
        <>
          {/* The whole network is closed to us, which is not an error in this post. */}
          {hold ? (
            <Callout tone="warn" role="status" className={styles.message}>
              {hold}
            </Callout>
          ) : null}

          {error ? (
            <Callout tone="danger" role="alert" className={styles.message}>
              {error}
            </Callout>
          ) : null}

          {/* "It probably went out" is not the same as "it failed", and must not
              read as an invitation to press the button again — hence the rule. */}
          {result?.status === "failed" ? (
            <Callout
              tone={isAmbiguous ? "warn" : "danger"}
              isRuled={isAmbiguous}
              role="alert"
              className={styles.message}
            >
              {isAmbiguous ? <strong>Check before retrying. </strong> : null}
              {result.error ?? "The network rejected this post."}
              {result.error_code === "reauth" ? (
                <>
                  {" "}
                  <Link className={styles.inlineLink} href="/settings">
                    Reconnect the account
                  </Link>
                  .
                </>
              ) : null}
              {isAmbiguous ? (
                <>
                  {" "}
                  Publishing is disabled here until you close this dialog, so
                  you cannot post it twice by accident.
                </>
              ) : null}
            </Callout>
          ) : null}

          <div className={styles.body}>
            <section className={styles.section}>
              <SectionLabel as="h3">Destination</SectionLabel>
              {preflight?.account ? (
                <>
                  <p className={styles.destination}>
                    {preflight.account.display_name}
                  </p>
                  {preflight.account.handle ? (
                    <p className={styles.destinationHandle}>
                      @{preflight.account.handle}
                    </p>
                  ) : null}
                </>
              ) : (
                <p className={styles.destinationMissing}>
                  No {label} account connected.{" "}
                  <Link className={styles.inlineLink} href="/settings">
                    Connect one in Settings
                  </Link>
                  .
                </p>
              )}
            </section>

            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <SectionLabel as="h3">
                  Images
                  {preflight ? (
                    <span className={styles.imageCount}>
                      {" "}
                      {selectedIds.length}/{preflight.max_images}
                    </span>
                  ) : null}
                </SectionLabel>
                {preflight?.image_required ? <Badge tone="warn">Required</Badge> : null}
              </div>
              {library === null ? (
                <p className={styles.muted}>Loading images…</p>
              ) : library.length === 0 ? (
                <p className={styles.muted}>
                  {preflight?.image_required
                    ? `${label} needs an image — add one from the Media panel first.`
                    : "No image on this post; it will go out as text only."}
                </p>
              ) : (
                <>
                  <ul className={styles.thumbs}>
                    {library.map((image) => {
                      const position = selectedIds.indexOf(image.id);
                      return (
                        <li key={image.id}>
                          <SelectableThumb
                            src={imageFileUrl(image)}
                            label={image.prompt ?? image.filename ?? "Image"}
                            isSelected={position !== -1}
                            order={position + 1}
                            onToggle={() => toggleImage(image.id)}
                          />
                        </li>
                      );
                    })}
                  </ul>
                  <p className={styles.muted}>
                    The number is the order they will appear in.
                  </p>
                </>
              )}
            </section>

            <section className={styles.sectionWide}>
              <div className={styles.sectionHeader}>
                <SectionLabel as="h3">Exactly what will be sent</SectionLabel>
                {preflight ? (
                  <span className={isOverLimit ? styles.counterOver : styles.counter}>
                    {preflight.char_count.toLocaleString()} /{" "}
                    {preflight.char_limit.toLocaleString()} characters ·{" "}
                    {preflight.hashtag_count} hashtags
                  </span>
                ) : null}
              </div>
              {/* The text is the server's own `compose_post_text` output,
                  handed straight to the preview. Recomposing it here would
                  make this panel the one thing in the app that can lie about
                  what is going out. */}
              <PostPreview
                platform={item.platform}
                text={preflight?.text ?? ""}
                images={selectedAssets}
                account={preflight?.account ?? null}
              />
            </section>

            {preflight && preflight.blockers.length > 0 ? (
              <section className={styles.sectionWide}>
                <SectionLabel as="h3">Blocking</SectionLabel>
                <Callout tone="danger" as="ul">
                  {preflight.blockers.map((blocker) => (
                    <li key={blocker}>{blocker}</li>
                  ))}
                </Callout>
              </section>
            ) : null}

            {preflight && preflight.warnings.length > 0 ? (
              <section className={styles.sectionWide}>
                <SectionLabel as="h3">Worth a look</SectionLabel>
                <Callout tone="warn" as="ul">
                  {preflight.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </Callout>
              </section>
            ) : null}
          </div>

          {/* A commit bar rather than a row of equal buttons. */}
          <ModalFooter>
            {isArmed ? (
              <>
                <span className={styles.confirmText}>
                  Send this to the live {label} account now?
                </span>
                <Button
                  variant="primary"
                  onClick={() => void runPublish()}
                  disabled={!canPublish}
                >
                  {isPublishing ? "Publishing…" : "Yes, publish now"}
                </Button>
                <Button onClick={() => setIsArmed(false)} disabled={isPublishing}>
                  Not yet
                </Button>
              </>
            ) : (
              <>
                <span className={styles.footerStatus}>
                  {hold
                    ? "On hold."
                    : isChecking
                      ? "Checking…"
                      : preflight?.ready
                        ? "Ready to publish."
                        : "Not ready yet."}
                </span>
                <Button
                  variant="primary"
                  onClick={() => setIsArmed(true)}
                  disabled={!canPublish}
                >
                  Publish to {label}
                </Button>
                <Button onClick={onClose}>Cancel</Button>
              </>
            )}
          </ModalFooter>
        </>
      )}
    </Modal>
  );
}

function PublishedPanel({
  label,
  result,
  onClose,
}: {
  label: string;
  result: Publication;
  onClose: () => void;
}) {
  return (
    <div className={styles.success} role="status">
      <p className={styles.successTitle}>Published to {label}.</p>
      {result.permalink ? (
        <a
          className={styles.viewPost}
          href={result.permalink}
          target="_blank"
          rel="noopener noreferrer"
        >
          View post ↗
        </a>
      ) : (
        // The post is live either way; Instagram in particular can succeed and
        // still fail the follow-up permalink lookup.
        <p className={styles.muted}>
          The network did not return a link to the post.
        </p>
      )}
      <Button onClick={onClose}>Done</Button>
    </div>
  );
}
