"use client";

import { useState, type ReactNode } from "react";

import { PlatformBadge, StatusBadge } from "@/components/content/Badges";
import {
  Badge,
  Button,
  Callout,
  DisclosureList,
  DisclosureRow,
  EmptyState,
  Field,
  IconButton,
  Modal,
  ModalFooter,
  OrderBadge,
  PageHeader,
  SectionLabel,
  Select,
  SelectableThumb,
  Skeleton,
  Tab,
  TabList,
  TextArea,
  TextInput,
  ToggleChip,
  cardClass,
  type BadgeTone,
  type ButtonVariant,
} from "@/components/ui";
import { PLATFORMS, STATUSES } from "@/lib/platforms";
import styles from "./ui-kit.module.css";

const VARIANTS: ButtonVariant[] = ["primary", "secondary", "ghost", "danger", "link", "linkDanger"];
const TONES: BadgeTone[] = ["neutral", "outline", "accent", "solid", "warn", "danger"];
const SAMPLE_IMAGE =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#7a4f9e"/><circle cx="7" cy="3" r="1.6" fill="#fff" fill-opacity=".5"/></svg>',
  );

function Specimen({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={cardClass({ className: styles.specimen })}>
      <SectionLabel as="h2">{title}</SectionLabel>
      <div className={styles.row}>{children}</div>
    </section>
  );
}

export default function UiKit() {
  const [chips, setChips] = useState<string[]>(["facebook"]);
  const [tab, setTab] = useState("one");
  const [segment, setSegment] = useState("generate");
  const [expanded, setExpanded] = useState<string | null>("first");
  const [picked, setPicked] = useState<string[]>(["a"]);
  const [isModalOpen, setIsModalOpen] = useState(false);

  return (
    <div className={styles.page}>
      <PageHeader
        title="UI kit"
        lede="Every shared primitive in every state. Development only."
        actions={<Button variant="primary">Page action</Button>}
      />

      <Specimen title="Buttons">
        {VARIANTS.map((variant) => (
          <div key={variant} className={styles.stack}>
            {(["sm", "md", "lg"] as const).map((size) => (
              <Button key={size} variant={variant} size={size}>
                {variant} {size}
              </Button>
            ))}
            <Button variant={variant} disabled>
              disabled
            </Button>
          </div>
        ))}
        <div className={styles.stack}>
          <Button variant="primary" icon="✨">
            With icon
          </Button>
          <IconButton label="Close">✕</IconButton>
          <IconButton label="Move up" variant="outline" size="sm">
            ↑
          </IconButton>
        </div>
      </Specimen>

      <Specimen title="Badges">
        {TONES.map((tone) => (
          <Badge key={tone} tone={tone}>
            {tone}
          </Badge>
        ))}
        <Badge shape="tag" tone="accent">
          AI
        </Badge>
        <Badge shape="tag" tone="outline">
          Uploaded
        </Badge>
        <Badge tone="warn" isCaps>
          Awaiting your review
        </Badge>
        <OrderBadge n={1} />
        <OrderBadge n={2} size="sm" />
        {PLATFORMS.map((platform) => (
          <PlatformBadge key={platform} platform={platform} />
        ))}
        {STATUSES.map((status) => (
          <StatusBadge key={status} status={status} />
        ))}
      </Specimen>

      <Specimen title="Callouts">
        <div className={styles.stackWide}>
          <Callout tone="danger">Could not load history.</Callout>
          <Callout tone="warn">LinkedIn publishing is on hold.</Callout>
          <Callout tone="success">Connected facebook.</Callout>
          <Callout tone="neutral">Crawling every category and course page.</Callout>
          <Callout tone="warn" isRuled>
            <strong>Check before retrying.</strong> The network took the post.
          </Callout>
          <Callout tone="danger" as="ul">
            <li>Instagram posts need an image.</li>
            <li>The connection expired.</li>
          </Callout>
        </div>
      </Specimen>

      <Specimen title="Fields">
        <div className={styles.stackWide}>
          <Field label="Free topic" htmlFor="kit-topic">
            <TextInput id="kit-topic" placeholder="e.g. Spring first aid" icon="✎" />
          </Field>
          <Field label="Reference URL" htmlFor="kit-url" isOptional hint="Used for context only.">
            <TextInput id="kit-url" placeholder="https://…" />
          </Field>
          <Field label="Password" htmlFor="kit-password">
            <TextInput
              id="kit-password"
              type="password"
              trailing={
                <Button variant="ghost" size="sm">
                  Show
                </Button>
              }
            />
          </Field>
          <Field label="Notes" htmlFor="kit-notes" isOptional>
            <TextArea id="kit-notes" rows={3} placeholder="Anything the posts must mention" />
          </Field>
          <Select aria-label="Filter">
            <option>All platforms</option>
          </Select>
        </div>
      </Specimen>

      <Specimen title="Chips and tabs">
        <div className={styles.stack}>
          <div className={styles.row}>
            {PLATFORMS.map((platform) => (
              <ToggleChip
                key={platform}
                checked={chips.includes(platform)}
                onChange={() =>
                  setChips((current) =>
                    current.includes(platform)
                      ? current.filter((entry) => entry !== platform)
                      : [...current, platform],
                  )
                }
              >
                <PlatformBadge platform={platform} />
              </ToggleChip>
            ))}
          </div>
          <TabList label="Pills">
            {["one", "two", "three"].map((name) => (
              <Tab key={name} isSelected={tab === name} onClick={() => setTab(name)}>
                {name}
              </Tab>
            ))}
          </TabList>
          <TabList label="Segmented" variant="segmented">
            {["generate", "upload"].map((name) => (
              <Tab key={name} isSelected={segment === name} onClick={() => setSegment(name)}>
                {name}
              </Tab>
            ))}
          </TabList>
        </div>
      </Specimen>

      <Specimen title="Disclosure list">
        <div className={styles.stackWide}>
          <DisclosureList>
            {["first", "second"].map((name) => (
              <DisclosureRow
                key={name}
                isExpanded={expanded === name}
                onToggle={() => setExpanded((current) => (current === name ? null : name))}
                summary={<strong>{name} row</strong>}
              >
                Expanded content for the {name} row.
              </DisclosureRow>
            ))}
          </DisclosureList>
        </div>
      </Specimen>

      <Specimen title="Empty, loading, thumbnails">
        <div className={styles.stackWide}>
          <EmptyState variant="dashed" size="lg" title="Your ideas land here">
            Fill in the left panel and generate.
          </EmptyState>
          <EmptyState variant="dashed" size="sm">
            Nothing selected — this post will go out as text only.
          </EmptyState>
          <EmptyState>Nothing here yet.</EmptyState>
          <Skeleton />
          <Skeleton variant="line" />
        </div>
        <div className={styles.row}>
          {["a", "b", "c"].map((id) => (
            <SelectableThumb
              key={id}
              src={SAMPLE_IMAGE}
              label={`Image ${id}`}
              isSelected={picked.includes(id)}
              order={picked.indexOf(id) + 1}
              onToggle={() =>
                setPicked((current) =>
                  current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id],
                )
              }
            />
          ))}
        </div>
      </Specimen>

      <Specimen title="Section labels and modal">
        <SectionLabel step={1} size="sm" tone="brand">
          Create a post
        </SectionLabel>
        <SectionLabel>Suggestions</SectionLabel>
        <Button onClick={() => setIsModalOpen(true)}>Open modal</Button>
        {isModalOpen ? (
          <Modal
            title="Publish to Facebook"
            hint="This sends the post to the live account."
            accent="facebook"
            onClose={() => setIsModalOpen(false)}
          >
            <div className={styles.modalBody}>Dialog body.</div>
            <ModalFooter>
              <span className={styles.spacer}>Ready to publish.</span>
              <Button variant="primary">Publish</Button>
              <Button onClick={() => setIsModalOpen(false)}>Cancel</Button>
            </ModalFooter>
          </Modal>
        ) : null}
      </Specimen>
    </div>
  );
}
