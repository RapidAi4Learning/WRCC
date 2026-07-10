"use client";

// Compose screen: ground the generation in a real course OR a free topic
// (+ optional reference URL and notes), pick platforms, get 3 ideas each.

import { FormEvent, useState } from "react";

import { ApiError, generateContent } from "@/lib/api";
import type {
  ContentItem,
  GenerateContentResult,
  Platform,
} from "@/types/content";
import type { Course } from "@/types/course";
import CoursePicker from "@/components/CoursePicker";
import VariantCard from "@/components/VariantCard";
import { PlatformBadge } from "@/components/Badges";
import styles from "./generate.module.css";

const ALL_PLATFORMS: Platform[] = ["facebook", "instagram", "linkedin"];

export default function GeneratePage() {
  const [course, setCourse] = useState<Course | null>(null);
  const [topic, setTopic] = useState("");
  const [referenceUrl, setReferenceUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [platforms, setPlatforms] = useState<Platform[]>(["facebook"]);
  const [result, setResult] = useState<GenerateContentResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const canSubmit =
    platforms.length > 0 && (course !== null || topic.trim().length > 0);

  function togglePlatform(platform: Platform) {
    setPlatforms((current) =>
      current.includes(platform)
        ? current.filter((p) => p !== platform)
        : [...current, platform],
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setError(null);
    setIsGenerating(true);
    try {
      const generated = await generateContent({
        topic: topic.trim() || undefined,
        reference_url: referenceUrl.trim() || undefined,
        notes: notes.trim() || undefined,
        course_id: course?.id,
        platforms,
      });
      setResult(generated);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Generation failed. Try again.",
      );
    } finally {
      setIsGenerating(false);
    }
  }

  function handleItemChange(updated: ContentItem) {
    setResult((current) =>
      current
        ? {
            ...current,
            items: current.items.map((item) =>
              item.id === updated.id ? updated : item,
            ),
          }
        : current,
    );
  }

  const itemsByPlatform = new Map<Platform, ContentItem[]>();
  for (const item of result?.items ?? []) {
    itemsByPlatform.set(item.platform, [
      ...(itemsByPlatform.get(item.platform) ?? []),
      item,
    ]);
  }

  return (
    <div className={styles.page}>
      <header>
        <h1 className={styles.title}>Generate content</h1>
        <p className={styles.lede}>
          Three post ideas per platform — grounded in a real course from the
          catalog, or in a free topic.
        </p>
      </header>

      <form className={styles.form} onSubmit={handleSubmit}>
        <fieldset className={styles.fieldset}>
          <legend className={styles.legend}>1 · Ground it</legend>
          <label className={styles.label}>Course from the catalog</label>
          <CoursePicker selected={course} onSelect={setCourse} />

          <label className={styles.label} htmlFor="topic">
            …or a free topic
          </label>
          <input
            id="topic"
            className={styles.input}
            placeholder="e.g. Spring first aid enrolments in Griffith"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
          />

          <label className={styles.label} htmlFor="reference">
            Reference URL <span className={styles.optional}>(optional)</span>
          </label>
          <input
            id="reference"
            type="url"
            className={styles.input}
            placeholder="https://…"
            value={referenceUrl}
            onChange={(event) => setReferenceUrl(event.target.value)}
          />

          <label className={styles.label} htmlFor="notes">
            Notes <span className={styles.optional}>(optional)</span>
          </label>
          <textarea
            id="notes"
            className={styles.textarea}
            rows={3}
            placeholder="Anything the posts must mention"
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
          />
        </fieldset>

        <fieldset className={styles.fieldset}>
          <legend className={styles.legend}>2 · Platforms</legend>
          <div className={styles.platforms}>
            {ALL_PLATFORMS.map((platform) => (
              <label key={platform} className={styles.platformOption}>
                <input
                  type="checkbox"
                  checked={platforms.includes(platform)}
                  onChange={() => togglePlatform(platform)}
                />
                <PlatformBadge platform={platform} />
              </label>
            ))}
          </div>
        </fieldset>

        {error ? (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        ) : null}

        <button
          type="submit"
          className={styles.submit}
          disabled={!canSubmit || isGenerating}
        >
          {isGenerating ? "Generating…" : "Generate 3 ideas per platform"}
        </button>
      </form>

      {result ? (
        <section className={styles.results} aria-label="Generated variants">
          {result.warnings.map((warning) => (
            <p key={warning} className={styles.warning}>
              ⚠ {warning}
            </p>
          ))}
          {ALL_PLATFORMS.filter((platform) => itemsByPlatform.has(platform)).map(
            (platform) => (
              <div key={platform} className={styles.platformGroup}>
                <h2 className={styles.platformHeading}>
                  <PlatformBadge platform={platform} />
                </h2>
                <div className={styles.cards}>
                  {itemsByPlatform.get(platform)!.map((item) => (
                    <VariantCard
                      key={item.id}
                      item={item}
                      onChange={handleItemChange}
                    />
                  ))}
                </div>
              </div>
            ),
          )}
        </section>
      ) : null}
    </div>
  );
}
