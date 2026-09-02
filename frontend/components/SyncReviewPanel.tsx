"use client";

// The screen where a scrape becomes the live catalog.
//
// Approving a sync is a bulk write to everything this app publishes from, and
// it is the one place where courses get taken off the site. So the panel shows
// the actual staged rows — named, priced, dated, with a before/after on every
// changed field — rather than a row of counters. Counters tell you a sync
// happened; they cannot tell you whether it is safe to apply.
//
// Ordering is deliberate: removals sit at the top, because a broken scrape
// shows up as an unexpected pile of deactivations and that is the failure this
// review exists to catch.

import { useState } from "react";

import type {
  Changeset,
  FieldChange,
  StagedCourseAdded,
  StagedCourseUpdate,
  StagedOffering,
  StagedOfferingUpdate,
  SyncRun,
} from "@/types/course";
import {
  SECTION_KEYS,
  SECTION_TITLES,
  SECTION_TONES,
  changesetTotals,
  destructiveWarning,
  fieldLabel,
  formatDate,
  formatFieldValue,
  formatMoney,
  formatRunTiming,
  removedCourse,
  removedOffering,
  sectionCount,
  tallyLabel,
  type SectionKey,
} from "@/lib/syncChangeset";
import styles from "./SyncReviewPanel.module.css";

// Long sections start collapsed and render in one page, so a first-ever sync
// (every course is "new") does not bury the actions under hundreds of rows.
const AUTO_OPEN_MAX = 10;
const INITIAL_VISIBLE = 12;

interface SyncReviewPanelProps {
  run: SyncRun;
  isBusy: boolean;
  /** Live course code → title, so a change can name the course it touches. */
  courseTitles: Record<string, string>;
  onApprove: () => void;
  onReject: (reason?: string) => void;
}

function metaLine(parts: Array<string | null | undefined>): string {
  return parts.filter((part): part is string => Boolean(part)).join(" · ");
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

function ItemHead({ code, name }: { code: string | null; name?: string | null }) {
  return (
    <p className={styles.itemHead}>
      <span className={styles.code}>{code ?? "Unknown"}</span>
      {name ? <span className={styles.itemTitle}>{name}</span> : null}
    </p>
  );
}

function offeringMeta(offering: StagedOffering): string {
  const start = formatDate(offering.start_date);
  const finish = offering.finish_date;
  const dates =
    finish && finish !== offering.start_date
      ? `${start} → ${formatDate(finish)}`
      : start;
  return metaLine([
    offering.start_date ? dates : "On demand",
    offering.location,
    offering.price !== null && offering.price !== undefined
      ? formatMoney(offering.price)
      : null,
    offering.places_available !== null && offering.places_available !== undefined
      ? `${offering.places_available} places`
      : null,
  ]);
}

function renderItems(
  key: SectionKey,
  changeset: Changeset,
  courseTitles: Record<string, string>,
): JSX.Element[] {
  const nameOf = (code: string | null | undefined) =>
    code ? courseTitles[code] ?? null : null;

  switch (key) {
    case "courses_added":
      return (changeset.courses_added ?? []).map((course: StagedCourseAdded) => (
        <li key={course.course_code} className={styles.item}>
          <ItemHead code={course.course_code} name={course.title} />
          <p className={styles.itemMeta}>
            {metaLine([
              course.category,
              course.is_accredited ? "Accredited" : null,
              `${course.offerings.length} ${
                course.offerings.length === 1 ? "date" : "dates"
              }`,
            ])}
          </p>
        </li>
      ));

    case "courses_updated":
      return (changeset.courses_updated ?? []).map((update: StagedCourseUpdate) => (
        <li key={update.course_code} className={styles.item}>
          <ItemHead
            code={update.course_code}
            // A renamed course has no live title under the new name yet, so the
            // old one from the diff is the honest label.
            name={
              nameOf(update.course_code) ??
              (typeof update.changes.title?.from === "string"
                ? update.changes.title.from
                : null)
            }
          />
          <FieldDiffs changes={update.changes} />
        </li>
      ));

    case "courses_removed":
      return (changeset.courses_removed ?? []).map((entry) => {
        const course = removedCourse(entry);
        return (
          <li key={course.course_code} className={styles.item}>
            <ItemHead
              code={course.course_code}
              name={course.title ?? nameOf(course.course_code)}
            />
            <p className={styles.itemMeta}>
              {metaLine([
                course.category,
                course.offerings_affected > 0
                  ? `${course.offerings_affected} scheduled ${
                      course.offerings_affected === 1 ? "date" : "dates"
                    } go with it`
                  : "no scheduled dates",
              ])}
            </p>
          </li>
        );
      });

    case "offerings_added":
      return (changeset.offerings_added ?? []).map((offering) => (
        <li key={offering.offering_code} className={styles.item}>
          <ItemHead
            code={offering.course_code ?? null}
            name={nameOf(offering.course_code)}
          />
          <p className={styles.itemMeta}>{offeringMeta(offering)}</p>
        </li>
      ));

    case "offerings_updated":
      return (changeset.offerings_updated ?? []).map(
        (update: StagedOfferingUpdate) => (
          <li key={update.offering_code} className={styles.item}>
            <ItemHead
              code={update.course_code}
              name={nameOf(update.course_code)}
            />
            <FieldDiffs changes={update.changes} />
          </li>
        ),
      );

    case "offerings_removed":
      return (changeset.offerings_removed ?? []).map((entry) => {
        const offering = removedOffering(entry);
        return (
          <li key={offering.offering_code} className={styles.item}>
            <ItemHead
              code={offering.course_code}
              name={nameOf(offering.course_code)}
            />
            <p className={styles.itemMeta}>
              {metaLine([
                offering.start_date ? formatDate(offering.start_date) : "On demand",
                offering.location,
                offering.price !== null ? formatMoney(offering.price) : null,
              ])}
            </p>
          </li>
        );
      });
  }
}

function Section({
  sectionKey,
  items,
}: {
  sectionKey: SectionKey;
  items: JSX.Element[];
}) {
  const [isOpen, setIsOpen] = useState(items.length <= AUTO_OPEN_MAX);
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? items : items.slice(0, INITIAL_VISIBLE);
  const hidden = items.length - visible.length;

  return (
    <details
      className={styles.section}
      data-tone={SECTION_TONES[sectionKey]}
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
    >
      <summary className={styles.sectionSummary}>
        <span className={styles.sectionTitle}>{SECTION_TITLES[sectionKey]}</span>
        <span className={styles.sectionCount}>{items.length}</span>
      </summary>
      <ul className={styles.items}>{visible}</ul>
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
  // `null` means the reject form is closed; a string is the reason so far.
  const [reason, setReason] = useState<string | null>(null);

  const changeset = run.changeset ?? {};
  const { total, isEmpty } = changesetTotals(changeset);
  const warning = destructiveWarning(changeset);
  const populated = SECTION_KEYS.filter((key) => sectionCount(changeset, key) > 0);

  return (
    <section className={styles.panel} aria-labelledby="sync-review-heading">
      <header className={styles.header}>
        <p className={styles.pill}>Awaiting your review</p>
        <h2 id="sync-review-heading" className={styles.headline}>
          {isEmpty
            ? "No changes — the site already matches this catalog"
            : `${total} ${total === 1 ? "change" : "changes"} staged`}
        </h2>
        <p className={styles.meta}>
          {metaLine([
            `Crawled ${run.courses_found} courses · ${run.offerings_found} dates`,
            formatRunTiming(run),
          ])}
        </p>
      </header>

      {populated.length > 0 ? (
        <ul className={styles.tallies}>
          {populated.map((key) => {
            const count = sectionCount(changeset, key);
            return (
              <li
                key={key}
                className={styles.tally}
                data-tone={SECTION_TONES[key]}
              >
                <span className={styles.tallyCount}>{count}</span>
                <span className={styles.tallyLabel}>{tallyLabel(key, count)}</span>
              </li>
            );
          })}
        </ul>
      ) : null}

      {warning ? (
        <p className={styles.warning}>
          <strong>Removals in this changeset.</strong> {warning}
        </p>
      ) : null}

      {populated.length > 0 ? (
        <div className={styles.sections}>
          {populated.map((key) => (
            <Section
              key={key}
              sectionKey={key}
              items={renderItems(key, changeset, courseTitles)}
            />
          ))}
        </div>
      ) : (
        <p className={styles.emptyNote}>
          Approving closes this run out without touching the catalog.
        </p>
      )}

      {reason === null ? (
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.approve}
            onClick={onApprove}
            disabled={isBusy}
          >
            {isEmpty
              ? "Close out this run"
              : `Approve & apply ${total} ${total === 1 ? "change" : "changes"}`}
          </button>
          <button
            type="button"
            className={styles.reject}
            onClick={() => setReason("")}
            disabled={isBusy}
          >
            Reject
          </button>
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
          <textarea
            id="sync-reject-reason"
            className={styles.rejectInput}
            rows={2}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="e.g. prices look wrong, the site was mid-update"
          />
          <div className={styles.actions}>
            <button
              type="submit"
              className={styles.confirmReject}
              disabled={isBusy}
            >
              Discard changeset
            </button>
            <button
              type="button"
              className={styles.cancel}
              onClick={() => setReason(null)}
              disabled={isBusy}
            >
              Keep it
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
