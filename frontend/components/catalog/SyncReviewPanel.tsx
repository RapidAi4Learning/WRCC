"use client";

// The screen where a scrape becomes the live catalog.
//
// Approving a sync is a bulk write to everything this app publishes from, and
// it is the one place where courses get taken off the site. So the panel shows
// the actual staged rows — named, priced, dated, with a before/after on every
// changed field — rather than a row of counters. Counters tell you a sync
// happened; they cannot tell you whether it is safe to apply.
//
// Every row is a tick box, because a reviewer who can only take the changeset
// whole has no real veto: one wrong price in a 200-row scrape would otherwise
// force them to throw away 199 good changes. Unticking is "not now" — the live
// rows stay put, so the next crawl stages the same difference again.
//
// Ordering is deliberate: removals sit at the top, because a broken scrape
// shows up as an unexpected pile of deactivations and that is the failure this
// review exists to catch.

import { useMemo, useState } from "react";

import type { ChangeSelection, FieldChange, SyncRun } from "@/types/course";
import {
  SECTION_KEYS,
  SECTION_TITLES,
  SECTION_TONES,
  buildItems,
  buildSkipSelection,
  countSkipped,
  destructiveWarning,
  fieldLabel,
  formatFieldValue,
  formatRunTiming,
  itemLabel,
  setSectionSkipped,
  skipKey,
  tallyLabel,
  toggleSkip,
  type ReviewItem,
  type SectionKey,
} from "@/lib/syncChangeset";
import {
  Badge,
  Button,
  Callout,
  TextArea,
  cardClass,
  type BadgeTone,
} from "@/components/ui";
import styles from "./SyncReviewPanel.module.css";

// Long sections start collapsed and render in one page, so a first-ever sync
// (every course is "new") does not bury the actions under hundreds of rows.
const AUTO_OPEN_MAX = 10;
const INITIAL_VISIBLE = 12;

// Tone is carried by colour (accent = added, warn = changed, danger = removed)
// rather than by icons, so the tallies and the sections agree at a glance.
const COUNT_TONES: Record<string, BadgeTone> = {
  add: "accent",
  update: "warn",
  remove: "danger",
};

interface SyncReviewPanelProps {
  run: SyncRun;
  isBusy: boolean;
  /** Live course code → title, so a change can name the course it touches. */
  courseTitles: Record<string, string>;
  onApprove: (skip?: ChangeSelection) => void;
  onReject: (reason?: string) => void;
}

interface Section {
  key: SectionKey;
  items: ReviewItem[];
}

function FieldDiffs({ changes }: { changes: Record<string, FieldChange> }) {
  return (
    <dl className={styles.diff}>
      {Object.entries(changes).map(([field, change]) => (
        <div key={field} className={styles.diffRow}>
          <dt className={styles.diffField}>{fieldLabel(field)}</dt>
          <dd className={styles.diffValues}>
            <del className={styles.was}>{formatFieldValue(field, change.from)}</del>
            <span aria-hidden="true" className={styles.arrow}>
              →
            </span>
            <ins className={styles.now}>{formatFieldValue(field, change.to)}</ins>
          </dd>
        </div>
      ))}
    </dl>
  );
}

function ItemRow({
  item,
  isSkipped,
  isBusy,
  onToggle,
}: {
  item: ReviewItem;
  isSkipped: boolean;
  isBusy: boolean;
  onToggle: () => void;
}) {
  return (
    <li className={styles.item} data-skipped={isSkipped}>
      <label className={styles.tick}>
        <input
          type="checkbox"
          checked={!isSkipped}
          onChange={onToggle}
          disabled={isBusy}
          aria-label={`Apply ${itemLabel(item)}`}
        />
      </label>
      <div className={styles.itemBody}>
        <p className={styles.itemHead}>
          <span className={styles.code}>{item.courseCode ?? item.code}</span>
          {item.title ? (
            <span className={styles.itemTitle}>{item.title}</span>
          ) : null}
          {isSkipped ? (
            <Badge shape="tag" tone="outline">
              Skipped
            </Badge>
          ) : null}
        </p>
        {item.meta ? <p className={styles.itemMeta}>{item.meta}</p> : null}
        {item.changes ? <FieldDiffs changes={item.changes} /> : null}
      </div>
    </li>
  );
}

function SectionBlock({
  section,
  skipped,
  isBusy,
  onToggleItem,
  onToggleSection,
}: {
  section: Section;
  skipped: Set<string>;
  isBusy: boolean;
  onToggleItem: (key: string) => void;
  onToggleSection: (section: Section, skip: boolean) => void;
}) {
  const { key, items } = section;
  const [isOpen, setIsOpen] = useState(items.length <= AUTO_OPEN_MAX);
  const [showAll, setShowAll] = useState(false);

  const skippedHere = countSkipped(skipped, key, items);
  const allSkipped = skippedHere === items.length;
  const visible = showAll ? items : items.slice(0, INITIAL_VISIBLE);
  const hidden = items.length - visible.length;

  return (
    <details
      className={styles.section}
      data-tone={SECTION_TONES[key]}
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
      <summary className={styles.sectionSummary}>
        <span className={styles.sectionTitle}>{SECTION_TITLES[key]}</span>
        <Badge
          tone={COUNT_TONES[SECTION_TONES[key]] ?? "neutral"}
          className={styles.sectionCount}
        >
          {skippedHere > 0
            ? `${items.length - skippedHere} of ${items.length}`
            : items.length}
        </Badge>
        <Button
          size="sm"
          disabled={isBusy}
          // Inside a summary, so the click must not also fold the section.
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onToggleSection(section, !allSkipped);
          }}
        >
          {allSkipped ? "Include all" : "Skip all"}
        </Button>
      </summary>
      <ul className={styles.items}>
        {visible.map((item) => {
          const itemKey = skipKey(key, item.code);
          return (
            <ItemRow
              key={itemKey}
              item={item}
              isSkipped={skipped.has(itemKey)}
              isBusy={isBusy}
              onToggle={() => onToggleItem(itemKey)}
            />
          );
        })}
      </ul>
      {hidden > 0 ? (
        <button
          type="button"
          className={styles.showAll}
          onClick={() => setShowAll(true)}
        >
          Show the remaining {hidden}
        </button>
      ) : null}
    </details>
  );
}

export default function SyncReviewPanel({
  run,
  isBusy,
  courseTitles,
  onApprove,
  onReject,
}: SyncReviewPanelProps) {
  // Entry keys the reviewer unticked. Empty means "apply the lot", which is
  // what an approve has always been.
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  // `null` means the reject form is closed; a string is the reason so far.
  const [reason, setReason] = useState<string | null>(null);

  const changeset = run.changeset ?? {};
  const sections: Section[] = useMemo(
    () =>
      SECTION_KEYS.map((key) => ({
        key,
        items: buildItems(key, changeset, courseTitles),
      })).filter((section) => section.items.length > 0),
    [changeset, courseTitles],
  );

  const staged = sections.reduce((sum, s) => sum + s.items.length, 0);
  const skippedCount = sections.reduce(
    (sum, s) => sum + countSkipped(skipped, s.key, s.items),
    0,
  );
  const selected = staged - skippedCount;

  const selectedIn = (key: SectionKey) => {
    const section = sections.find((candidate) => candidate.key === key);
    if (!section) return 0;
    return section.items.length - countSkipped(skipped, key, section.items);
  };

  const warning = destructiveWarning(
    selectedIn("courses_removed"),
    selectedIn("offerings_removed"),
  );
  const isEmpty = staged === 0;
  const nothingSelected = staged > 0 && selected === 0;

  const approveLabel = isEmpty
    ? "Close out this run"
    : skippedCount === 0
      ? `Approve & apply ${staged} ${staged === 1 ? "change" : "changes"}`
      : `Approve & apply ${selected} of ${staged} changes`;

  return (
    <section
      className={cardClass({ padding: "lg", className: styles.panel })}
      aria-labelledby="sync-review-heading"
    >
      <header className={styles.header}>
        <Badge tone="warn" isCaps className={styles.pill}>
          Awaiting your review
        </Badge>
        <h2 id="sync-review-heading" className={styles.headline}>
          {isEmpty
            ? "No changes — the site already matches this catalog"
            : `${staged} ${staged === 1 ? "change" : "changes"} staged`}
        </h2>
        <p className={styles.meta}>
          {`Crawled ${run.courses_found} courses · ${run.offerings_found} dates · ${formatRunTiming(run)}`}
        </p>
      </header>

      {sections.length > 0 ? (
        <ul className={styles.tallies}>
          {sections.map(({ key, items }) => {
            const kept = items.length - countSkipped(skipped, key, items);
            return (
              <li key={key} className={styles.tally} data-tone={SECTION_TONES[key]}>
                <span className={styles.tallyCount}>{kept}</span>
                {kept !== items.length ? (
                  <span className={styles.tallyOf}>of {items.length}</span>
                ) : null}
                <span className={styles.tallyLabel}>{tallyLabel(key, kept)}</span>
              </li>
            );
          })}
        </ul>
      ) : null}

      {warning ? (
        <Callout tone="danger" isRuled>
          <strong>Removals in this changeset.</strong> {warning}
        </Callout>
      ) : null}

      {sections.length > 0 ? (
        <div className={styles.sections}>
          {sections.map((section) => (
            <SectionBlock
              key={section.key}
              section={section}
              skipped={skipped}
              isBusy={isBusy}
              onToggleItem={(key) =>
                setSkipped((previous) => toggleSkip(previous, key))
              }
              onToggleSection={(target, skip) =>
                setSkipped((previous) =>
                  setSectionSkipped(previous, target.key, target.items, skip),
                )
              }
            />
          ))}
        </div>
      ) : (
        <p className={styles.note}>
          Approving closes this run out without touching the catalog.
        </p>
      )}

      {skippedCount > 0 ? (
        <p className={styles.skipNote}>
          {skippedCount === 1 ? "1 change stays" : `${skippedCount} changes stay`} as
          they are. Skipping is not a decision against them — the next sync finds
          the same difference upstream and stages it again.
        </p>
      ) : null}

      {reason === null ? (
        <div className={styles.actions}>
          <Button
            variant="primary"
            onClick={() => onApprove(buildSkipSelection(skipped))}
            disabled={isBusy || nothingSelected}
          >
            {approveLabel}
          </Button>
          <Button onClick={() => setReason("")} disabled={isBusy}>
            Reject
          </Button>
          {nothingSelected ? (
            <span className={styles.note}>
              Nothing is ticked — reject the run instead.
            </span>
          ) : null}
        </div>
      ) : (
        <form
          className={styles.rejectForm}
          onSubmit={(event) => {
            event.preventDefault();
            onReject(reason.trim() || undefined);
          }}
        >
          <label className={styles.rejectLabel} htmlFor="sync-reject-reason">
            Why are you discarding this changeset?
            <span className={styles.optional}>
              Optional — it is kept on the run so the next person knows.
            </span>
          </label>
          <TextArea
            id="sync-reject-reason"
            controlSize="sm"
            rows={2}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="e.g. prices look wrong, the site was mid-update"
          />
          <div className={styles.actions}>
            <Button type="submit" variant="danger" disabled={isBusy}>
              Discard changeset
            </Button>
            <Button onClick={() => setReason(null)} disabled={isBusy}>
              Keep it
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}
