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
import { createPortal } from "react-dom";
import Link from "next/link";

import {
  ApiError,
  fetchImages,
  fetchPublishPreflight,
  imageFileUrl,
  publishContent,
} from "@/lib/api";
import type { ContentImage, ContentItem } from "@/types/content";
import type { Publication, PublishPreflight } from "@/types/publishing";
import { PLATFORM_LABELS } from "@/components/Badges";
import { publishingHold } from "@/lib/publishing";
import styles from "./PublishDialog.module.css";

interface PublishDialogProps {
  item: ContentItem;
  onClose: () => void;
  // Fired only for an attempt that actually went live, so the card can refresh
  // itself. A failed attempt is reported inside the dialog instead.
  onPublished: (publication: Publication) => void;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export default function PublishDialog({
  item,
  onClose,
  onPublished,
}: PublishDialogProps) {
  const [preflight, setPreflight] = useState<PublishPreflight | null>(null);
  const [images, setImages] = useState<ContentImage[] | null>(null);
  // `null` means "whatever the server picks" (the most recent image). The
  // server's choice comes back in the preflight, so selection is derived rather
  // than copied — copying it back into state would cost a second round trip.
  const [chosenImageId, setChosenImageId] = useState<string | null>(null);
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
    async (imageId: string | null) => {
      setIsChecking(true);
      try {
        setPreflight(await fetchPublishPreflight(item.id, imageId ?? undefined));
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
    void runPreflight(chosenImageId);
  }, [runPreflight, chosenImageId]);

  useEffect(() => {
    let cancelled = false;
    fetchImages(item.id)
      .then((loaded) => {
        if (!cancelled) setImages(loaded);
      })
      .catch(() => {
        // The picker is an aid; preflight already reports a missing image as a
        // blocker, so failing to list them must not block publishing.
        if (!cancelled) setImages([]);
      });
    return () => {
      cancelled = true;
    };
  }, [item.id]);

  // The page behind the dialog must not scroll while it is open.
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const selectedImageId = chosenImageId ?? preflight?.image_id ?? null;

  async function runPublish() {
    setError(null);
    setIsPublishing(true);
    try {
      const publication = await publishContent(
        item.id,
        selectedImageId ?? undefined,
      );
      setResult(publication);
      if (publication.status === "succeeded") {
        onPublished(publication);
      } else {
        // A failed attempt comes back 200 with the reason — it is a durable
        // record, not a transport error. Re-check so the button reflects
        // whatever the failure left behind.
        void runPreflight(chosenImageId);
      }
    } catch (err) {
      // 409 (already live) and 422 (blockers) both land here; both change what
      // preflight would now say.
      setError(errorMessage(err, "Publishing failed."));
      void runPreflight(chosenImageId);
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

  const dialog = (
    <div
      className={styles.backdrop}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Publish to ${label}`}
        className={styles.dialog}
        data-platform={item.platform}
      >
        <header className={styles.header}>
          <div>
            <h2 className={styles.title}>Publish to {label}</h2>
            <p className={styles.hint}>
              This sends the post to the live account. It cannot be undone from
              here.
            </p>
          </div>
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        {succeeded && result ? (
          <PublishedPanel label={label} result={result} onClose={onClose} />
        ) : (
          <>
            {hold ? (
              <p role="status" className={styles.hold}>
                {hold}
              </p>
            ) : null}

            {error ? (
              <p role="alert" className={styles.error}>
                {error}
              </p>
            ) : null}

            {result?.status === "failed" ? (
              <p
                role="alert"
                className={isAmbiguous ? styles.ambiguous : styles.error}
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
              </p>
            ) : null}

            <div className={styles.body}>
              <section className={styles.section}>
                <h3 className={styles.sectionTitle}>Destination</h3>
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
                  <h3 className={styles.sectionTitle}>Image</h3>
                  {preflight?.image_required ? (
                    <span className={styles.required}>Required</span>
                  ) : null}
                </div>
                {images === null ? (
                  <p className={styles.muted}>Loading images…</p>
                ) : images.length === 0 ? (
                  <p className={styles.muted}>
                    {preflight?.image_required
                      ? `${label} needs an image — generate one from the Images panel first.`
                      : "No image on this post; it will go out as text only."}
                  </p>
                ) : (
                  <ul className={styles.thumbs}>
                    {images.map((image) => (
                      <li key={image.id}>
                        <button
                          type="button"
                          className={
                            image.id === selectedImageId
                              ? styles.thumbActive
                              : styles.thumb
                          }
                          onClick={() => setChosenImageId(image.id)}
                          aria-pressed={image.id === selectedImageId}
                          title={image.prompt}
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={imageFileUrl(image)}
                            alt={image.prompt}
                            width={96}
                            height={96}
                            loading="lazy"
                          />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className={styles.sectionWide}>
                <div className={styles.sectionHeader}>
                  <h3 className={styles.sectionTitle}>Exactly what will be sent</h3>
                  {preflight ? (
                    <span
                      className={isOverLimit ? styles.counterOver : styles.counter}
                    >
                      {preflight.char_count.toLocaleString()} /{" "}
                      {preflight.char_limit.toLocaleString()} characters ·{" "}
                      {preflight.hashtag_count} hashtags
                    </span>
                  ) : null}
                </div>
                <pre className={styles.preview}>
                  {preflight?.text ?? "Loading…"}
                </pre>
              </section>

              {preflight && preflight.blockers.length > 0 ? (
                <section className={styles.sectionWide}>
                  <h3 className={styles.sectionTitle}>Blocking</h3>
                  <ul className={styles.blockers}>
                    {preflight.blockers.map((blocker) => (
                      <li key={blocker}>{blocker}</li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {preflight && preflight.warnings.length > 0 ? (
                <section className={styles.sectionWide}>
                  <h3 className={styles.sectionTitle}>Worth a look</h3>
                  <ul className={styles.warnings}>
                    {preflight.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </div>

            <footer className={styles.footer}>
              {isArmed ? (
                <>
                  <span className={styles.confirmText}>
                    Send this to the live {label} account now?
                  </span>
                  <button
                    type="button"
                    className={styles.publish}
                    onClick={() => void runPublish()}
                    disabled={!canPublish}
                  >
                    {isPublishing ? "Publishing…" : "Yes, publish now"}
                  </button>
                  <button
                    type="button"
                    className={styles.secondary}
                    onClick={() => setIsArmed(false)}
                    disabled={isPublishing}
                  >
                    Not yet
                  </button>
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
                  <button
                    type="button"
                    className={styles.publish}
                    onClick={() => setIsArmed(true)}
                    disabled={!canPublish}
                  >
                    Publish to {label}
                  </button>
                  <button
                    type="button"
                    className={styles.secondary}
                    onClick={onClose}
                  >
                    Cancel
                  </button>
                </>
              )}
            </footer>
          </>
        )}
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
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
      <button type="button" className={styles.secondary} onClick={onClose}>
        Done
      </button>
    </div>
  );
}
