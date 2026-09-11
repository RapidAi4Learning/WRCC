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

import {
  deleteMediaAsset,
  fetchImageSuggestions,
  fetchMedia,
  generateImage,
  imageFileUrl,
  saveMediaSelection,
  uploadMedia,
} from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { moveItem, toggleOrdered } from "@/lib/selection";
import { useStoredChoice } from "@/lib/useStoredChoice";
import type { ImageQuality, MediaAsset } from "@/types/content";
import {
  ArrowDown,
  ArrowUp,
  ImagePlus,
  RefreshCw,
  Sparkles,
  Upload,
  X,
} from "@/components/icons";
import {
  Badge,
  Button,
  Callout,
  EmptyState,
  IconButton,
  Modal,
  OrderBadge,
  SectionLabel,
  SegmentedControl,
  SelectableThumb,
  Skeleton,
  Tab,
  TabList,
  TextArea,
  buttonClass,
} from "@/components/ui";
import styles from "./MediaPanel.module.css";

// Mirrors the server's accepted formats. A client-side check that disagrees
// with the server is worse than none, so this is a courtesy — the upload is
// still refused server-side if it slips through.
const ACCEPTED_TYPES = ["image/png", "image/jpeg", "image/webp"];
const ACCEPT_ATTRIBUTE = ACCEPTED_TYPES.join(",");
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const FALLBACK_IMAGE_SIZE = 512;

// Time and cost against detail, remembered per browser. Draft is for trying
// prompts out — about a quarter of the cost, but details such as a CPR
// manikin come out visibly wrong; Standard is what the server does by default.
// The times are gpt-image-1 at 1024×1024 against the live API: low 10–15 s,
// medium 18–19 s (docs/GENERATION-LATENCY-PLAN.md). "high" is not offered: it
// can outlast the server's image timeout.
const QUALITY_STORAGE_KEY = "wrcc.media.quality";
const DEFAULT_QUALITY: ImageQuality = "medium";
const QUALITIES: ReadonlyArray<{ value: ImageQuality; label: string; hint: string }> = [
  { value: "low", label: "Draft", hint: "~12 s" },
  { value: "medium", label: "Standard", hint: "~20 s" },
];
const QUALITY_VALUES = QUALITIES.map((quality) => quality.value);

type Tab = "generate" | "upload";

interface MediaPanelProps {
  itemId: string;
  // Lets the card show a live count without a second request.
  onCountChange?: (selected: number, available: number) => void;
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
  const [quality, chooseQuality] = useStoredChoice(
    QUALITY_STORAGE_KEY,
    QUALITY_VALUES,
    DEFAULT_QUALITY,
  );
  const [isUploading, setIsUploading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const close = useCallback(() => setIsOpen(false), []);

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
    const { list, isOverLimit } = toggleOrdered(selected, assetId, maxImages);
    if (isOverLimit) {
      setError(
        `This platform accepts at most ${maxImages} images. Remove one first.`,
      );
      return;
    }
    void persist(list);
  }

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= selected.length) return;
    void persist(moveItem(selected, index, delta));
  }

  // ── create ──

  async function runGenerate(usedPrompt: string) {
    const trimmed = usedPrompt.trim();
    if (!trimmed) return;
    setError(null);
    setNotice(null);
    setIsGenerating(true);
    try {
      await generateImage(itemId, trimmed, quality);
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

  const generatePane = (
    <>
      <div className={styles.sectionHeader}>
        <SectionLabel>Suggestions</SectionLabel>
        <Button
          size="sm"
          icon={<RefreshCw size={14} />}
          onClick={() => void loadSuggestions()}
          disabled={isSuggesting}
        >
          {isSuggesting ? "Thinking…" : "Regenerate"}
        </Button>
      </div>

      {suggestions === null && isSuggesting ? (
        <>
          <Skeleton />
          <Skeleton />
          <Skeleton />
        </>
      ) : null}
      {suggestions?.map((suggestion) => (
        <button
          key={suggestion}
          type="button"
          className={prompt === suggestion ? styles.suggestionActive : styles.suggestion}
          title={suggestion}
          onClick={() => setPrompt(suggestion)}
        >
          <span className={styles.clamp}>{suggestion}</span>
        </button>
      ))}

      <SectionLabel as="label" htmlFor={`prompt-${itemId}`}>
        Edit suggestion or create prompt
      </SectionLabel>
      <TextArea
        id={`prompt-${itemId}`}
        controlSize="sm"
        className={styles.prompt}
        value={prompt}
        rows={5}
        placeholder="Describe the image you want, or pick a suggestion and edit it here."
        onChange={(event) => setPrompt(event.target.value)}
      />
      <SegmentedControl
        label="Image quality"
        name={`quality-${itemId}`}
        value={quality}
        options={QUALITIES}
        onChange={chooseQuality}
      />
      <Button
        variant="primary"
        onClick={() => void runGenerate(prompt)}
        disabled={isBusy || prompt.trim().length < 3}
      >
        {isGenerating ? "Generating…" : "Generate image"}
      </Button>
    </>
  );

  const uploadPane = (
    <>
      <SectionLabel>Upload your own</SectionLabel>
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
        <p className={styles.dropText}>Drag images here, or</p>
        <Button
          variant="primary"
          onClick={() => fileInput.current?.click()}
          disabled={isBusy}
        >
          {isUploading ? "Uploading…" : "Choose files"}
        </Button>
        <input
          ref={fileInput}
          type="file"
          accept={ACCEPT_ATTRIBUTE}
          multiple
          className="sr-only"
          aria-label="Upload images"
          onChange={(event) => {
            if (event.target.files) void runUpload(event.target.files);
          }}
        />
        <p className={styles.dropHint}>
          PNG, JPEG or WebP · up to {MAX_UPLOAD_BYTES / (1024 * 1024)} MB each
        </p>
      </div>
      <p className={styles.dropNote}>
        Uploads are resized and their metadata (including any location recorded
        by a phone) is stripped before they are stored.
      </p>
    </>
  );

  const selectionStrip = (
    <div className={styles.selection}>
      <div className={styles.sectionHeader}>
        <SectionLabel>
          In this post ({selected.length}/{maxImages})
        </SectionLabel>
        {selected.length > 0 ? (
          <Button size="sm" onClick={() => void persist(selected, true)} disabled={isBusy}>
            Use on other platforms
          </Button>
        ) : null}
      </div>

      {selectedAssets.length === 0 ? (
        <EmptyState variant="dashed" size="sm">
          Nothing selected — this post will go out as text only.
        </EmptyState>
      ) : (
        <ol className={styles.selectionList}>
          {selectedAssets.map((asset, index) => (
            <li key={asset.id} className={styles.selectionItem}>
              <OrderBadge n={index + 1} />
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={imageFileUrl(asset)}
                alt={assetLabel(asset)}
                width={48}
                height={48}
                className={styles.selectionThumb}
                loading="lazy"
              />
              <span className={styles.selectionName}>{assetLabel(asset)}</span>
              <IconButton
                variant="outline"
                size="sm"
                label={`Move ${assetLabel(asset)} earlier`}
                onClick={() => move(index, -1)}
                disabled={index === 0 || isBusy}
              >
                <ArrowUp size={14} />
              </IconButton>
              <IconButton
                variant="outline"
                size="sm"
                label={`Move ${assetLabel(asset)} later`}
                onClick={() => move(index, 1)}
                disabled={index === selectedAssets.length - 1 || isBusy}
              >
                <ArrowDown size={14} />
              </IconButton>
              <IconButton
                variant="outline"
                size="sm"
                label={`Remove ${assetLabel(asset)} from this post`}
                onClick={() => toggle(asset.id)}
                disabled={isBusy}
              >
                <X size={14} />
              </IconButton>
            </li>
          ))}
        </ol>
      )}
    </div>
  );

  const gallery = (
    <div className={styles.gallery}>
      <div className={styles.sectionHeader}>
        <SectionLabel>
          Library {library && library.length > 0 ? `(${library.length})` : ""}
        </SectionLabel>
        <span className={styles.galleryHint}>
          Shared with the other platforms in this generation
        </span>
      </div>

      {isGenerating || isUploading ? <Skeleton variant="image" /> : null}

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
                <SelectableThumb
                  variant="tile"
                  src={imageFileUrl(asset)}
                  label={assetLabel(asset)}
                  isSelected={isSelected}
                  order={position + 1}
                  onToggle={() => toggle(asset.id)}
                  disabled={isBusy}
                  width={asset.width || FALLBACK_IMAGE_SIZE}
                  height={asset.height || FALLBACK_IMAGE_SIZE}
                />

                <div className={styles.metaRow}>
                  <Badge shape="tag" tone={asset.source === "uploaded" ? "outline" : "accent"}>
                    {asset.source === "uploaded" ? "Uploaded" : "AI"}
                  </Badge>
                  <span className={styles.dimensions}>
                    {asset.width}×{asset.height}
                  </span>
                </div>
                <p className={styles.caption} title={assetLabel(asset)}>
                  {assetLabel(asset)}
                </p>

                <div className={styles.itemActions}>
                  <a className={buttonClass({ size: "sm" })} href={imageFileUrl(asset, true)}>
                    Download
                  </a>
                  {asset.prompt ? (
                    <Button
                      size="sm"
                      onClick={() => {
                        setTab("generate");
                        setPrompt(asset.prompt ?? "");
                      }}
                    >
                      Edit prompt
                    </Button>
                  ) : null}
                  <Button size="sm" onClick={() => void removeAsset(asset)} disabled={isBusy}>
                    Delete
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      ) : library !== null && !isBusy ? (
        <EmptyState variant="dashed" size="md">
          No images yet — generate one or upload your own from the left.
        </EmptyState>
      ) : null}
    </div>
  );

  return (
    <>
      <Button
        size="sm"
        icon={<ImagePlus size={16} />}
        className={styles.toggle}
        onClick={() => setIsOpen(true)}
      >
        Media
        {library
          ? ` (${selected.length} selected · ${library.length} available)`
          : ""}
      </Button>
      {isOpen ? (
        <Modal
          title="Post media"
          hint="Generate images or upload your own, then tick the ones this post should send — in the order they should appear."
          size="lg"
          onClose={close}
        >
          {error ? (
            <Callout tone="danger" size="sm" role="alert" className={styles.message}>
              {error}
            </Callout>
          ) : null}
          {notice ? (
            <Callout tone="success" size="sm" role="status" className={styles.message}>
              {notice}
            </Callout>
          ) : null}

          <div className={styles.dialogBody}>
            <div className={styles.compose}>
              {/* The client asked for these two to be visibly different
                  things, and this is where that is answered. */}
              <TabList label="Add images" variant="segmented">
                <Tab isSelected={tab === "generate"} onClick={() => setTab("generate")}>
                  <Sparkles size={16} aria-hidden="true" />
                  Generate with AI
                </Tab>
                <Tab isSelected={tab === "upload"} onClick={() => setTab("upload")}>
                  <Upload size={16} aria-hidden="true" />
                  Upload files
                </Tab>
              </TabList>

              {tab === "generate" ? generatePane : uploadPane}
              {selectionStrip}
            </div>
            {gallery}
          </div>
        </Modal>
      ) : null}
    </>
  );
}
