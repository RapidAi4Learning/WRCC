"use client";

// Compose screen: ground the generation in a real course OR a free topic
// (+ optional reference URL and notes), pick platforms, get 3 ideas each.

import { FormEvent, useEffect, useState } from "react";

import { generateContent } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { PLATFORMS } from "@/lib/platforms";
import type {
  ContentItem,
  GenerateContentResult,
  Platform,
  ReasoningEffort,
} from "@/types/content";
import type { Course } from "@/types/course";
import CoursePicker from "@/components/content/CoursePicker";
import IdeasIllustration from "@/components/content/IdeasIllustration";
import VariantCard from "@/components/content/VariantCard";
import { PlatformName } from "@/components/content/Badges";
import { FileText, Link2, Pencil, Sparkles } from "@/components/icons";
import {
  Button,
  Callout,
  EmptyState,
  Field,
  PageHeader,
  SectionLabel,
  SegmentedControl,
  Skeleton,
  Tab,
  TabList,
  TextArea,
  TextInput,
  ToggleChip,
  cardClass,
} from "@/components/ui";
import styles from "./generate.module.css";

const VARIANTS_PER_PLATFORM = 3;

// Speed against copy quality, remembered per device. The times are what a
// three-platform generation measured against the live API
// (docs/GENERATION-LATENCY-PLAN.md): Fast 9 s, Balanced 10–18 s, Best quality
// 27 s without a course — with a course its calls take about twice as long,
// hence the range.
const SPEED_STORAGE_KEY = "wrcc.generate.speed";
const DEFAULT_SPEED: ReasoningEffort = "low";
const SPEEDS: ReadonlyArray<{ value: ReasoningEffort; label: string; hint: string }> = [
  { value: "minimal", label: "Fast", hint: "~10 s" },
  { value: "low", label: "Balanced", hint: "~15 s" },
  { value: "medium", label: "Best quality", hint: "30–60 s" },
];

function isOfferedSpeed(value: string | null): value is ReasoningEffort {
  return SPEEDS.some((speed) => speed.value === value);
}

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
  const [speed, setSpeed] = useState<ReasoningEffort>(DEFAULT_SPEED);

  // Read after mount rather than in the initial state: the page is prerendered
  // on the server, where there is no storage, and a first browser render that
  // differed from it would not hydrate.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(SPEED_STORAGE_KEY);
      if (isOfferedSpeed(stored)) setSpeed(stored);
    } catch {
      // Storage blocked (private mode, site data off): keep the default.
    }
  }, []);

  function chooseSpeed(next: ReasoningEffort) {
    setSpeed(next);
    try {
      window.localStorage.setItem(SPEED_STORAGE_KEY, next);
    } catch {
      // Not remembered this time; the choice still applies to this page.
    }
  }

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
        reasoning_effort: speed,
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

  function renderResults() {
    // A fresh run replaces the old results, so while it is running the panel
    // shows the shape of what is coming rather than the previous batch.
    if (isGenerating) {
      return (
        <>
          <p role="status" className="sr-only">
            Generating ideas…
          </p>
          <div className={styles.cards} aria-hidden="true">
            {Array.from({ length: VARIANTS_PER_PLATFORM }, (_, index) => (
              <Skeleton key={index} variant="card" />
            ))}
          </div>
        </>
      );
    }

    if (!result) {
      return (
        <EmptyState
          variant="dashed"
          size="lg"
          className={styles.empty}
          icon={<IdeasIllustration />}
          title="Your ideas land here"
        >
          Fill in the left panel and generate — results appear side by side, no
          scrolling.
        </EmptyState>
      );
    }

    return (
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
                className={styles.tab}
              >
                <PlatformName platform={platform} />
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
              <VariantCard key={item.id} item={item} onChange={handleItemChange} />
            ))}
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div className={styles.page}>
      <PageHeader
        title="Generate content"
        lede="Three post ideas per platform — grounded in a real course from the catalog, or in a free topic."
      />

      <div className={styles.workspace}>
        <form
          className={cardClass({ padding: "lg", className: styles.form })}
          onSubmit={handleSubmit}
        >
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
                icon={<Pencil size={20} />}
                placeholder="e.g. Spring first aid enrolments in Griffith"
                value={topic}
                onChange={(event) => setTopic(event.target.value)}
              />
            </Field>

            <Field label="Reference URL" htmlFor="reference" isOptional>
              <TextInput
                id="reference"
                type="url"
                icon={<Link2 size={20} />}
                placeholder="https://…"
                value={referenceUrl}
                onChange={(event) => setReferenceUrl(event.target.value)}
              />
            </Field>

            <Field label="Notes" htmlFor="notes" isOptional>
              <TextArea
                id="notes"
                rows={3}
                icon={<FileText size={20} />}
                placeholder="Anything the posts must mention"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </Field>
          </fieldset>

          <hr className={styles.divider} />

          <fieldset className={styles.fieldset}>
            <SectionLabel as="legend" step={2} size="sm" tone="brand" className={styles.legend}>
              Platforms
            </SectionLabel>
            {/* Toggle chips carrying each network's own mark: the chip itself
                shows the checked state, three to a row. */}
            <div className={styles.platforms}>
              {PLATFORMS.map((platform) => (
                <ToggleChip
                  key={platform}
                  className={styles.platformChip}
                  checked={platforms.includes(platform)}
                  onChange={() => togglePlatform(platform)}
                >
                  <PlatformName platform={platform} />
                </ToggleChip>
              ))}
            </div>
          </fieldset>

          <SegmentedControl
            label="Writing speed"
            name="speed"
            value={speed}
            options={SPEEDS}
            onChange={chooseSpeed}
          />

          {error ? (
            <Callout tone="danger" role="alert">
              {error}
            </Callout>
          ) : null}

          {/* Pinned to the bottom of the window while the form is longer than
              it, so the one action on this screen is visible at any height. */}
          <div className={styles.submitBar}>
            <Button
              type="submit"
              variant="primary"
              size="lg"
              block
              icon={<Sparkles size={22} />}
              disabled={!canSubmit || isGenerating}
            >
              {isGenerating ? "Generating…" : "Generate 3 ideas per platform"}
            </Button>
          </div>
        </form>

        <section className={styles.results} aria-label="Generated variants">
          {renderResults()}
        </section>
      </div>
    </div>
  );
}
