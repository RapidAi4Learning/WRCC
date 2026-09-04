"use client";

// Per-post media workspace. Replaces the old generate-only ImagePanel.
//
// Three things share this dialog, and the layout says which is which:
//
//   compose (left)  — two clearly separate actions, Generate and Upload
//   library (right) — every asset in this generation, sibling platforms
//                     included, each one tickable
//   selection strip — what THIS post sends, in order, capped at the platform's
//                     own ceiling
//
// The selection is the part that matters: what goes out is what is ticked, in
// the order it is ticked. Before this, the most recent image went out and
// nothing on screen said so.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  ApiError,
  deleteMediaAsset,
  fetchImageSuggestions,
  fetchMedia,
  generateImage,
  imageFileUrl,
  saveMediaSelection,
  uploadMedia,
} from "@/lib/api";
import type { MediaAsset } from "@/types/content";
import styles from "./MediaPanel.module.css";

// Mirrors the server's accepted formats. A client-side check that disagrees
// with the server is worse than none, so this is a courtesy — the upload is
// still refused server-side if it slips through.
const ACCEPTED_TYPES = ["image/png", "image/jpeg", "image/webp"];
const ACCEPT_ATTRIBUTE = ACCEPTED_TYPES.join(",");
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

type Tab = "generate" | "upload";

interface MediaPanelProps {
  itemId: string;
  // Lets the card show a live count without a second request.
  onCountChange?: (selected: number, available: number) => void;
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function assetLabel(asset: MediaAsset): string {
  return asset.prompt ?? asset.filename ?? "Uploaded image";
}

export default function MediaPanel({ itemId, onCountChange }: MediaPanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("generate");

  const [library, setLibrary] = useState<MediaAsset[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [maxImages, setMaxImages] = useState(10);

  const [suggestions, setSuggestions] = useState<string[] | null>(null);
  const [prompt, setPrompt] = useState("");
  const [isSuggesting, setIsSuggesting] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const byId = useMemo(
    () => new Map((library ?? []).map((asset) => [asset.id, asset])),
    [library],
  );

  const loadMedia = useCallback(async () => {
    const media = await fetchMedia(itemId);
    setLibrary(media.library);
    setSelected(media.selection.map((row) => row.media_asset_id));
    setMaxImages(media.max_images);
  }, [itemId]);

  // The card's counter needs the numbers whether or not the dialog was ever
  // opened, so this runs on mount rather than on first open.
  useEffect(() => {
    let cancelled = false;
    fetchMedia(itemId)
      .then((media) => {
        if (cancelled) return;
        setLibrary(media.library);
        setSelected(media.selection.map((row) => row.media_asset_id));
        setMaxImages(media.max_images);
      })
      .catch(() => {
        // A card that cannot count its images is not worth an error banner;
        // opening the panel will surface the real failure.
      });
    return () => {
      cancelled = true;
    };
  }, [itemId]);

  useEffect(() => {
    onCountChange?.(selected.length, library?.length ?? 0);
  }, [selected.length, library?.length, onCountChange]);

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
    // Suggestions cost an LLM call, so they load once, and only if the
    // operator actually opens the Generate tab.
    if (isOpen && tab === "generate" && suggestions === null && !isSuggesting) {
      void loadSuggestions();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, tab]);

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

  // ── selection ──

  async function persist(next: string[], applyToGroup = false) {
    const previous = selected;
    setSelected(next); // optimistic; the strip must feel immediate
    setIsSaving(true);
    setError(null);
    try {
      const result = await saveMediaSelection(itemId, next, applyToGroup);
      setSelected(result.selection.map((row) => row.media_asset_id));
      setNotice(
        result.warnings.length > 0
          ? result.warnings.join(" ")
          : applyToGroup
            ? "Applied to the other platforms in this generation."
            : null,
      );
    } catch (err) {
      setSelected(previous); // roll back rather than lie about what is saved
      setError(errorMessage(err, "Could not save the selection."));
    } finally {
      setIsSaving(false);
    }
  }

  function toggle(assetId: string) {
    if (selected.includes(assetId)) {
      void persist(selected.filter((id) => id !== assetId));
      return;
    }
    if (selected.length >= maxImages) {
      setError(
        `This platform accepts at most ${maxImages} images. Remove one first.`,
      );
      return;
    }
    void persist([...selected, assetId]);
  }

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= selected.length) return;
    const next = [...selected];
    [next[index], next[target]] = [next[target], next[index]];
    void persist(next);
  }

  // ── create ──

  async function runGenerate(usedPrompt: string) {
    const trimmed = usedPrompt.trim();
    if (!trimmed) return;
    setError(null);
    setNotice(null);
    setIsGenerating(true);
    try {
      await generateImage(itemId, trimmed);
      // Re-read rather than splice: the server also attaches the new asset to
      // this post's selection, and guessing at that would drift.
      await loadMedia();
    } catch (err) {
      setError(errorMessage(err, "Image generation failed."));
    } finally {
      setIsGenerating(false);
    }
  }

  async function runUpload(files: FileList | File[]) {
    const chosen = Array.from(files);
    if (chosen.length === 0) return;

    const rejected = chosen.filter(
      (file) => !ACCEPTED_TYPES.includes(file.type) || file.size > MAX_UPLOAD_BYTES,
    );
    if (rejected.length > 0) {
      setError(
        `Skipped ${rejected.map((file) => file.name).join(", ")} — only PNG, ` +
          `JPEG and WebP under ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB.`,
      );
    }
    const accepted = chosen.filter((file) => !rejected.includes(file));
    if (accepted.length === 0) return;

    setIsUploading(true);
    setNotice(null);
    try {
      await uploadMedia(itemId, accepted);
      await loadMedia();
      if (rejected.length === 0) setError(null);
    } catch (err) {
      setError(errorMessage(err, "Upload failed."));
    } finally {
      setIsUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function removeAsset(asset: MediaAsset) {
    setError(null);
    try {
      await deleteMediaAsset(asset.id);
      await loadMedia();
    } catch (err) {
      setError(errorMessage(err, "Could not delete the image."));
    }
  }

  const isBusy = isGenerating || isUploading || isSaving;
  const selectedAssets = selected
    .map((id) => byId.get(id))
    .filter((asset): asset is MediaAsset => asset !== undefined);

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
        aria-label="Post media"
        className={styles.dialog}
      >
        <header className={styles.dialogHeader}>
          <div>
            <h2 className={styles.dialogTitle}>Post media</h2>
            <p className={styles.dialogHint}>
              Generate images or upload your own, then tick the ones this post
              should send — in the order they should appear.
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
        {notice ? (
          <p role="status" className={styles.notice}>
            {notice}
          </p>
        ) : null}

        <div className={styles.dialogBody}>
          <div className={styles.compose}>
            {/* The client asked for these two to be visibly different things,
                and this is where that is answered. */}
            <div className={styles.tabs} role="tablist" aria-label="Add images">
              <button
                type="button"
                role="tab"
                aria-selected={tab === "generate"}
                className={tab === "generate" ? styles.tabActive : styles.tab}
                onClick={() => setTab("generate")}
              >
                ✨ Generate with AI
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === "upload"}
                className={tab === "upload" ? styles.tabActive : styles.tab}
                onClick={() => setTab("upload")}
              >
                ⬆ Upload files
              </button>
            </div>

            {tab === "generate" ? (
              <>
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
                  {isGenerating ? "Generating…" : "Generate image"}
                </button>
              </>
            ) : (
              <>
                <span className={styles.sectionTitle}>Upload your own</span>
                <div
                  className={isDragging ? styles.dropZoneActive : styles.dropZone}
                  onDragOver={(event) => {
                    event.preventDefault();
                    setIsDragging(true);
                  }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={(event) => {
                    event.preventDefault();
                    setIsDragging(false);
                    void runUpload(event.dataTransfer.files);
                  }}
                >
                  <p className={styles.dropText}>
                    Drag images here, or
                  </p>
                  <button
                    type="button"
                    className={styles.primary}
                    onClick={() => fileInput.current?.click()}
                    disabled={isBusy}
                  >
                    {isUploading ? "Uploading…" : "Choose files"}
                  </button>
                  <input
                    ref={fileInput}
                    type="file"
                    accept={ACCEPT_ATTRIBUTE}
                    multiple
                    className={styles.fileInput}
                    aria-label="Upload images"
                    onChange={(event) => {
                      if (event.target.files) void runUpload(event.target.files);
                    }}
                  />
                  <p className={styles.dropHint}>
                    PNG, JPEG or WebP · up to{" "}
                    {MAX_UPLOAD_BYTES / (1024 * 1024)} MB each
                  </p>
                </div>
                <p className={styles.dropNote}>
                  Uploads are resized and their metadata (including any location
                  recorded by a phone) is stripped before they are stored.
                </p>
              </>
            )}

            <div className={styles.selection}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>
                  In this post ({selected.length}/{maxImages})
                </span>
                {selected.length > 0 ? (
                  <button
                    type="button"
                    className={styles.small}
                    onClick={() => void persist(selected, true)}
                    disabled={isBusy}
                  >
                    Use on other platforms
                  </button>
                ) : null}
              </div>

              {selectedAssets.length === 0 ? (
                <p className={styles.selectionEmpty}>
                  Nothing selected — this post will go out as text only.
                </p>
              ) : (
                <ol className={styles.selectionList}>
                  {selectedAssets.map((asset, index) => (
                    <li key={asset.id} className={styles.selectionItem}>
                      <span className={styles.orderBadge}>{index + 1}</span>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={imageFileUrl(asset)}
                        alt={assetLabel(asset)}
                        width={48}
                        height={48}
                        className={styles.selectionThumb}
                        loading="lazy"
                      />
                      <span className={styles.selectionName}>
                        {assetLabel(asset)}
                      </span>
                      <button
                        type="button"
                        className={styles.iconButton}
                        onClick={() => move(index, -1)}
                        disabled={index === 0 || isBusy}
                        aria-label={`Move ${assetLabel(asset)} earlier`}
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        className={styles.iconButton}
                        onClick={() => move(index, 1)}
                        disabled={index === selectedAssets.length - 1 || isBusy}
                        aria-label={`Move ${assetLabel(asset)} later`}
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        className={styles.iconButton}
                        onClick={() => toggle(asset.id)}
                        disabled={isBusy}
                        aria-label={`Remove ${assetLabel(asset)} from this post`}
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>

          <div className={styles.gallery}>
            <div className={styles.sectionHeader}>
              <span className={styles.sectionTitle}>
                Library {library && library.length > 0 ? `(${library.length})` : ""}
              </span>
              <span className={styles.galleryHint}>
                Shared with the other platforms in this generation
              </span>
            </div>

            {isGenerating || isUploading ? (
              <div className={styles.imageSkeleton} />
            ) : null}

            {library && library.length > 0 ? (
              <ul className={styles.grid}>
                {library.map((asset) => {
                  const position = selected.indexOf(asset.id);
                  const isSelected = position !== -1;
                  return (
                    <li
                      key={asset.id}
                      className={isSelected ? styles.gridItemActive : styles.gridItem}
                    >
                      <button
                        type="button"
                        className={styles.pick}
                        onClick={() => toggle(asset.id)}
                        aria-pressed={isSelected}
                        disabled={isBusy}
                        title={assetLabel(asset)}
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={imageFileUrl(asset)}
                          alt={assetLabel(asset)}
                          className={styles.image}
                          loading="lazy"
                          width={asset.width || 512}
                          height={asset.height || 512}
                        />
                        {isSelected ? (
                          <span className={styles.pickBadge}>{position + 1}</span>
                        ) : null}
                      </button>

                      <div className={styles.metaRow}>
                        <span
                          className={
                            asset.source === "uploaded"
                              ? styles.badgeUpload
                              : styles.badgeAi
                          }
                        >
                          {asset.source === "uploaded" ? "Uploaded" : "AI"}
                        </span>
                        <span className={styles.dimensions}>
                          {asset.width}×{asset.height}
                        </span>
                      </div>
                      <p className={styles.caption} title={assetLabel(asset)}>
                        {assetLabel(asset)}
                      </p>

                      <div className={styles.itemActions}>
                        <a className={styles.small} href={imageFileUrl(asset, true)}>
                          Download
                        </a>
                        {asset.prompt ? (
                          <button
                            type="button"
                            className={styles.small}
                            onClick={() => {
                              setTab("generate");
                              setPrompt(asset.prompt ?? "");
                            }}
                          >
                            Edit prompt
                          </button>
                        ) : null}
                        <button
                          type="button"
                          className={styles.small}
                          onClick={() => void removeAsset(asset)}
                          disabled={isBusy}
                        >
                          Delete
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : library !== null && !isBusy ? (
              <p className={styles.empty}>
                No images yet — generate one or upload your own from the left.
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
        🖼 Media
        {library
          ? ` (${selected.length} selected · ${library.length} available)`
          : ""}
      </button>
      {modal ? createPortal(modal, document.body) : null}
    </>
  );
}
