"use client";

// Per-post image workspace, presented as a modal dialog so it never grows
// the page: compose (suggestions + editable prompt) on the left, the image
// history on the right, each scrolling independently.

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import {
  ApiError,
  fetchImageSuggestions,
  fetchImages,
  generateImage,
  imageFileUrl,
} from "@/lib/api";
import type { ContentImage } from "@/types/content";
import styles from "./ImagePanel.module.css";

interface ImagePanelProps {
  itemId: string;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export default function ImagePanel({ itemId }: ImagePanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [images, setImages] = useState<ContentImage[] | null>(null);
  const [suggestions, setSuggestions] = useState<string[] | null>(null);
  const [prompt, setPrompt] = useState("");
  const [isSuggesting, setIsSuggesting] = useState(false);
  const [busyPrompt, setBusyPrompt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadSuggestions = useCallback(async () => {
    setIsSuggesting(true);
    setError(null);
    try {
      const result = await fetchImageSuggestions(itemId);
      setSuggestions(result.prompts);
    } catch (err) {
      setError(errorMessage(err, "Could not load prompt suggestions."));
    } finally {
      setIsSuggesting(false);
    }
  }, [itemId]);

  useEffect(() => {
    if (!isOpen || images !== null) return;
    let cancelled = false;
    fetchImages(itemId)
      .then((result) => {
        if (!cancelled) setImages(result);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err, "Could not load images."));
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, images, itemId]);

  useEffect(() => {
    // Suggestions load once per post, on first open (then cached in state).
    if (isOpen && suggestions === null && !isSuggesting) {
      void loadSuggestions();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // The page behind the dialog must not scroll while it is open.
  useEffect(() => {
    if (!isOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setIsOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen]);

  async function runGenerate(usedPrompt: string) {
    const trimmed = usedPrompt.trim();
    if (!trimmed) return;
    setError(null);
    setBusyPrompt(usedPrompt);
    try {
      const image = await generateImage(itemId, trimmed);
      setImages((current) => [image, ...(current ?? [])]);
    } catch (err) {
      setError(errorMessage(err, "Image generation failed."));
    } finally {
      setBusyPrompt(null);
    }
  }

  const isBusy = busyPrompt !== null;
  const imageCount = images?.length ?? 0;

  const modal = isOpen ? (
    <div
      className={styles.backdrop}
      onClick={(event) => {
        if (event.target === event.currentTarget) setIsOpen(false);
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Post images"
        className={styles.dialog}
      >
        <header className={styles.dialogHeader}>
          <div>
            <h2 className={styles.dialogTitle}>Post images</h2>
            <p className={styles.dialogHint}>
              Pick a suggestion, tweak the prompt, generate — every image is
              kept below.
            </p>
          </div>
          <button
            type="button"
            className={styles.close}
            onClick={() => setIsOpen(false)}
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        {error ? (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        ) : null}

        <div className={styles.dialogBody}>
          <div className={styles.compose}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionTitle}>Suggestions</span>
              <button
                type="button"
                className={styles.small}
                onClick={() => void loadSuggestions()}
                disabled={isSuggesting}
              >
                {isSuggesting ? "Thinking…" : "↻ New ideas"}
              </button>
            </div>

            {suggestions === null && isSuggesting ? (
              <>
                <div className={styles.skeleton} />
                <div className={styles.skeleton} />
                <div className={styles.skeleton} />
              </>
            ) : null}
            {suggestions?.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                className={
                  prompt === suggestion
                    ? styles.suggestionActive
                    : styles.suggestion
                }
                title={suggestion}
                onClick={() => setPrompt(suggestion)}
              >
                <span className={styles.clamp}>{suggestion}</span>
              </button>
            ))}

            <label className={styles.sectionTitle} htmlFor={`prompt-${itemId}`}>
              Prompt
            </label>
            <textarea
              id={`prompt-${itemId}`}
              className={styles.textarea}
              value={prompt}
              rows={5}
              placeholder="Describe the image you want, or pick a suggestion and edit it here."
              onChange={(event) => setPrompt(event.target.value)}
            />
            <button
              type="button"
              className={styles.primary}
              onClick={() => void runGenerate(prompt)}
              disabled={isBusy || prompt.trim().length < 3}
            >
              {isBusy ? "Generating…" : "Generate image"}
            </button>
          </div>

          <div className={styles.gallery}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionTitle}>
                Generated {imageCount > 0 ? `(${imageCount})` : ""}
              </span>
            </div>

            {isBusy ? <div className={styles.imageSkeleton} /> : null}

            {images && images.length > 0 ? (
              <ul className={styles.grid}>
                {images.map((image) => (
                  <li key={image.id} className={styles.gridItem}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={imageFileUrl(image)}
                      alt={image.prompt}
                      className={styles.image}
                      loading="lazy"
                      width={512}
                      height={512}
                    />
                    <p className={styles.caption} title={image.prompt}>
                      {image.prompt}
                    </p>
                    <div className={styles.itemActions}>
                      <a className={styles.small} href={imageFileUrl(image, true)}>
                        Download
                      </a>
                      <button
                        type="button"
                        className={styles.small}
                        onClick={() => void runGenerate(image.prompt)}
                        disabled={isBusy}
                      >
                        Regenerate
                      </button>
                      <button
                        type="button"
                        className={styles.small}
                        onClick={() => setPrompt(image.prompt)}
                      >
                        Edit prompt
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : images !== null && !isBusy ? (
              <p className={styles.empty}>
                No images yet — generate the first one from the left panel.
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  ) : null;

  return (
    <>
      <button
        type="button"
        className={styles.toggle}
        onClick={() => setIsOpen(true)}
      >
        🖼 Images{imageCount > 0 ? ` (${imageCount})` : ""}
      </button>
      {modal ? createPortal(modal, document.body) : null}
    </>
  );
}
