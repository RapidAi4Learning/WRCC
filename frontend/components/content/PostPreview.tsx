"use client";

// What the post will look like on the network it is going to.
//
// One rule governs this whole file: **the text is never recomposed here.** It
// arrives from the server's preflight — the output of `compose_post_text`,
// character for character — and is rendered as-is. A second composer living in
// a preview component would be a third copy of that logic, and the copy that
// drifted would be the one the operator was looking at when they hit Publish.
//
// The chrome is an approximation and says so. Fold thresholds below are each
// network's *UI* behaviour, not an API limit; the real limits are enforced by
// the server's preflight and shown in the character counter beside this panel.

import { useState } from "react";

import { imageFileUrl } from "@/lib/api";
import { initials } from "@/lib/initials";
import type { MediaAsset, Platform } from "@/types/content";
import type { SocialAccount } from "@/types/publishing";
import styles from "./PostPreview.module.css";

// Where each network hides the rest of a long caption behind a "more" control.
// Cosmetic: these numbers change what the preview folds, never what is sent.
const PREVIEW_FOLD: Record<Platform, { chars: number; label: string }> = {
  facebook: { chars: 477, label: "See more" },
  instagram: { chars: 125, label: "more" },
  linkedin: { chars: 200, label: "…see more" },
};

// Instagram crops everything outside this range, and applies the first image's
// ratio to every other image in a carousel.
const IG_MIN_ASPECT = 0.8;
const IG_MAX_ASPECT = 1.91;

interface PostPreviewProps {
  platform: Platform;
  // Straight from `preflight.text`. Never derived, never re-joined.
  text: string;
  images: MediaAsset[];
  account: SocialAccount | null;
}

/** Split the text at the fold, on a word boundary so it does not cut mid-word. */
function fold(text: string, limit: number): { head: string; tail: string } {
  if (text.length <= limit) return { head: text, tail: "" };
  const slice = text.slice(0, limit);
  const lastSpace = slice.lastIndexOf(" ");
  const cut = lastSpace > limit * 0.6 ? lastSpace : limit;
  return { head: text.slice(0, cut), tail: text.slice(cut) };
}

/** Hashtags rendered in the network's link colour, everything else verbatim. */
function withHashtags(text: string) {
  return text.split(/(#[\p{L}\p{N}_]+)/gu).map((part, index) =>
    part.startsWith("#") ? (
      <span key={index} className={styles.hashtag}>
        {part}
      </span>
    ) : (
      // A fragment, not a span: the text must render exactly as given,
      // whitespace and line breaks included.
      <span key={index}>{part}</span>
    ),
  );
}

function PostText({
  text,
  platform,
  prefix,
}: {
  text: string;
  platform: Platform;
  prefix?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const { chars, label } = PREVIEW_FOLD[platform];
  const { head, tail } = fold(text, chars);

  return (
    <p className={styles.body}>
      {prefix ? <span className={styles.captionAuthor}>{prefix}</span> : null}
      {withHashtags(expanded || !tail ? text : head)}
      {tail && !expanded ? (
        <>
          {"… "}
          <button
            type="button"
            className={styles.more}
            onClick={() => setExpanded(true)}
          >
            {label}
          </button>
        </>
      ) : null}
    </p>
  );
}

/** Facebook's photo mosaic: 1 full-width, 2 side by side, 3+ a 1 + n grid. */
function PhotoMosaic({ images }: { images: MediaAsset[] }) {
  if (images.length === 0) return null;
  if (images.length === 1) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={imageFileUrl(images[0])}
        alt=""
        className={styles.singlePhoto}
        loading="lazy"
      />
    );
  }
  const [lead, ...rest] = images;
  const overflow = rest.length - 3;
  return (
    <div className={styles.mosaic} data-count={Math.min(images.length, 4)}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={imageFileUrl(lead)} alt="" className={styles.mosaicLead} loading="lazy" />
      <div className={styles.mosaicRest}>
        {rest.slice(0, 3).map((image, index) => (
          <div key={image.id} className={styles.mosaicCell}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={imageFileUrl(image)} alt="" loading="lazy" />
            {index === 2 && overflow > 0 ? (
              <span className={styles.mosaicOverflow}>+{overflow}</span>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Instagram's square-ish frame plus carousel controls. */
function Carousel({ images }: { images: MediaAsset[] }) {
  const [index, setIndex] = useState(0);
  if (images.length === 0) {
    return <div className={styles.igEmpty}>Instagram needs an image.</div>;
  }

  // Every image in a carousel is cropped to the first one's ratio, clamped to
  // what Instagram accepts — which is the crop the operator will actually get,
  // and the reason this is worth showing rather than describing.
  const first = images[0];
  const raw = first.height > 0 ? first.width / first.height : 1;
  const aspect = Math.min(Math.max(raw, IG_MIN_ASPECT), IG_MAX_ASPECT);
  const current = images[Math.min(index, images.length - 1)];

  return (
    <div className={styles.igMedia} style={{ aspectRatio: String(aspect) }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={imageFileUrl(current)} alt="" loading="lazy" />
      {images.length > 1 ? (
        <>
          <button
            type="button"
            className={styles.igPrev}
            onClick={() => setIndex((i) => Math.max(0, i - 1))}
            disabled={index === 0}
            aria-label="Previous image"
          >
            ‹
          </button>
          <button
            type="button"
            className={styles.igNext}
            onClick={() => setIndex((i) => Math.min(images.length - 1, i + 1))}
            disabled={index >= images.length - 1}
            aria-label="Next image"
          >
            ›
          </button>
          <span className={styles.igCounter}>
            {index + 1}/{images.length}
          </span>
          <div className={styles.igDots} aria-hidden="true">
            {images.map((image, dot) => (
              <span
                key={image.id}
                className={dot === index ? styles.igDotActive : styles.igDot}
              />
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

export default function PostPreview({
  platform,
  text,
  images,
  account,
}: PostPreviewProps) {
  const name = account?.display_name ?? "Your WRCC account";
  const handle = account?.handle;

  return (
    <div className={styles.frame} data-platform={platform}>
      <div className={styles.chromeLabel}>
        Approximate preview · {platform}
      </div>

      <article className={styles.post}>
        <header className={styles.postHeader}>
          <span className={styles.avatar} aria-hidden="true">
            {initials(name)}
          </span>
          <div className={styles.identity}>
            <span className={styles.author}>
              {platform === "instagram" && handle ? handle : name}
            </span>
            <span className={styles.meta}>
              {platform === "facebook" ? "Just now · 🌐" : null}
              {platform === "linkedin" ? "Just now · Western Riverina" : null}
              {platform === "instagram" ? "Sponsored" : null}
            </span>
          </div>
          <span className={styles.dots} aria-hidden="true">
            ···
          </span>
        </header>

        {platform === "instagram" ? (
          <>
            <Carousel images={images} />
            <div className={styles.igActions} aria-hidden="true">
              <span>♡</span>
              <span>💬</span>
              <span>➤</span>
            </div>
            <div className={styles.igCaption}>
              <PostText
                text={text}
                platform={platform}
                prefix={handle ?? name}
              />
            </div>
          </>
        ) : (
          <>
            <PostText text={text} platform={platform} />
            <PhotoMosaic images={images} />
            <div className={styles.reactions} aria-hidden="true">
              {platform === "facebook" ? (
                <>
                  <span>👍 Like</span>
                  <span>💬 Comment</span>
                  <span>↪ Share</span>
                </>
              ) : (
                <>
                  <span>👍 Like</span>
                  <span>💬 Comment</span>
                  <span>↻ Repost</span>
                  <span>➤ Send</span>
                </>
              )}
            </div>
          </>
        )}
      </article>
    </div>
  );
}
