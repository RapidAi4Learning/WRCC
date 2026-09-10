"use client";

// Compose screen: ground the generation in a real course OR a free topic
// (+ optional reference URL and notes), pick platforms, get 3 ideas each.

import { FormEvent, useState } from "react";

import { generateContent } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { PLATFORMS } from "@/lib/platforms";
import type {
  ContentItem,
  GenerateContentResult,
  Platform,
} from "@/types/content";
import type { Course } from "@/types/course";
import CoursePicker from "@/components/content/CoursePicker";
import VariantCard from "@/components/content/VariantCard";
import { PlatformBadge } from "@/components/content/Badges";
import {
  Button,
  Callout,
  EmptyState,
  Field,
  PageHeader,
  SectionLabel,
  Tab,
  TabList,
  TextArea,
  TextInput,
  ToggleChip,
  cardClass,
} from "@/components/ui";
import styles from "./generate.module.css";

export default function GeneratePage() {
  const [course, setCourse] = useState<Course | null>(null);
  const [topic, setTopic] = useState("");
  const [referenceUrl, setReferenceUrl] = useState("");
  const [notes, setNotes] = useState("");
  const [platforms, setPlatforms] = useState<Platform[]>(["facebook"]);
  const [result, setResult] = useState<GenerateContentResult | null>(null);
  const [activePlatform, setActivePlatform] = useState<Platform | null>(null);
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
      setActivePlatform(generated.items[0]?.platform ?? null);
    } catch (err) {
      setError(errorMessage(err, "Generation failed. Try again."));
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
  const resultPlatforms = PLATFORMS.filter((platform) =>
    itemsByPlatform.has(platform),
  );
  // Guard against a stale tab (e.g. platform deselected on the next run).
  const shownPlatform =
    activePlatform && itemsByPlatform.has(activePlatform)
      ? activePlatform
      : resultPlatforms[0] ?? null;

  return (
    <div className={styles.page}>
      <PageHeader
        title="Generate content"
        lede="Three post ideas per platform — grounded in a real course from the catalog, or in a free topic."
      />

      <div className={styles.workspace}>
        <form className={cardClass({ className: styles.form })} onSubmit={handleSubmit}>
          <fieldset className={styles.fieldset}>
            <SectionLabel as="legend" step={1} size="sm" tone="brand" className={styles.legend}>
              Create a post
            </SectionLabel>
            <Field label="Course from the catalog">
              <CoursePicker selected={course} onSelect={setCourse} />
            </Field>

            <Field label="…or a free topic" htmlFor="topic">
              <TextInput
                id="topic"
                placeholder="e.g. Spring first aid enrolments in Griffith"
                value={topic}
                onChange={(event) => setTopic(event.target.value)}
              />
            </Field>

            <Field label="Reference URL" htmlFor="reference" isOptional>
              <TextInput
                id="reference"
                type="url"
                placeholder="https://…"
                value={referenceUrl}
                onChange={(event) => setReferenceUrl(event.target.value)}
              />
            </Field>

            <Field label="Notes" htmlFor="notes" isOptional>
              <TextArea
                id="notes"
                rows={3}
                placeholder="Anything the posts must mention"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </Field>
          </fieldset>

          <fieldset className={styles.fieldset}>
            <SectionLabel as="legend" step={2} size="sm" tone="brand" className={styles.legend}>
              Platforms
            </SectionLabel>
            {/* Toggle chips: the chip itself shows the checked state, so the
                three platforms fit on one row inside the narrow column. */}
            <div className={styles.platforms}>
              {PLATFORMS.map((platform) => (
                <ToggleChip
                  key={platform}
                  checked={platforms.includes(platform)}
                  onChange={() => togglePlatform(platform)}
                >
                  <PlatformBadge platform={platform} />
                </ToggleChip>
              ))}
            </div>
          </fieldset>

          {error ? (
            <Callout tone="danger" role="alert">
              {error}
            </Callout>
          ) : null}

          <Button
            type="submit"
            variant="primary"
            size="lg"
            className={styles.submit}
            disabled={!canSubmit || isGenerating}
          >
            {isGenerating ? "Generating…" : "Generate 3 ideas per platform"}
          </Button>
        </form>

        <section className={styles.results} aria-label="Generated variants">
          {result ? (
            <>
              {result.warnings.map((warning) => (
                <Callout key={warning} tone="warn">
                  ⚠ {warning}
                </Callout>
              ))}

              {resultPlatforms.length > 1 ? (
                <TabList label="Platform">
                  {resultPlatforms.map((platform) => (
                    <Tab
                      key={platform}
                      isSelected={platform === shownPlatform}
                      onClick={() => setActivePlatform(platform)}
                    >
                      <PlatformBadge platform={platform} />
                      <span className={styles.tabCount}>
                        {itemsByPlatform.get(platform)!.length}
                      </span>
                    </Tab>
                  ))}
                </TabList>
              ) : null}

              {shownPlatform ? (
                <div
                  key={shownPlatform}
                  role={resultPlatforms.length > 1 ? "tabpanel" : undefined}
                  className={styles.cards}
                >
                  {itemsByPlatform.get(shownPlatform)!.map((item) => (
                    <VariantCard
                      key={item.id}
                      item={item}
                      onChange={handleItemChange}
                    />
                  ))}
                </div>
              ) : null}
            </>
          ) : (
            <EmptyState
              variant="dashed"
              size="lg"
              aria-hidden="true"
              title={isGenerating ? "Generating ideas…" : "Your ideas land here"}
            >
              {isGenerating
                ? "The AI is drafting three variants per platform."
                : "Fill in the left panel and generate — results appear side by side, no scrolling."}
            </EmptyState>
          )}
        </section>
      </div>
    </div>
  );
}
