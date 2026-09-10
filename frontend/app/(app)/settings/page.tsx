"use client";

// Connections: one card per network, showing where posts would go and how
// long the connection has left. Status is the hierarchy here — a connected
// card carries its network's colour and states its destination in large type;
// a disconnected one stays quiet and outline-only.

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  activateSocialAccount,
  disconnectSocialAccount,
  fetchAuthorizeUrl,
  fetchSocialAccounts,
  verifySocialAccount,
} from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import { PLATFORMS, PLATFORM_LABELS } from "@/lib/platforms";
import type { Platform } from "@/types/content";
import type { SocialAccount } from "@/types/publishing";
import { publishingHold } from "@/lib/publishing";
import { Badge, Button, Callout, EmptyState, PageHeader } from "@/components/ui";
import styles from "./settings.module.css";

const EXPIRY_WARNING_DAYS = 7;

const PLATFORM_BLURBS: Record<Platform, string> = {
  facebook: "Publishes to a Page you administer. Text posts, with or without an image.",
  instagram:
    "Needs a Business account linked to the Facebook Page. Every post requires an image.",
  linkedin: "Publishes to the Company Page you administer.",
};

type Expiry =
  | { kind: "none" }
  | { kind: "expired" }
  | { kind: "soon"; days: number; date: string }
  | { kind: "ok"; date: string };

function describeExpiry(account: SocialAccount): Expiry {
  // Meta Page tokens carry no expiry at all; only LinkedIn's really run out.
  if (!account.token_expires_at) return { kind: "none" };
  const expiresAt = new Date(account.token_expires_at);
  const date = expiresAt.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  if (account.token_expired) return { kind: "expired" };
  const days = Math.ceil((expiresAt.getTime() - Date.now()) / 86_400_000);
  return days <= EXPIRY_WARNING_DAYS ? { kind: "soon", days, date } : { kind: "ok", date };
}

function SettingsContent() {
  const searchParams = useSearchParams();
  const [accounts, setAccounts] = useState<SocialAccount[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setAccounts(await fetchSocialAccounts());
      setError(null);
    } catch (err) {
      setError(errorMessage(err, "Could not load connected accounts."));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // The OAuth callback redirects back here with the outcome in the query.
  useEffect(() => {
    const connected = searchParams.get("connected");
    const failed = searchParams.get("error");
    if (connected) setNotice(`Connected ${connected}.`);
    if (failed) setError(failed);
  }, [searchParams]);

  async function handleConnect(platform: Platform) {
    setBusy(platform);
    setError(null);
    try {
      const { authorize_url } = await fetchAuthorizeUrl(platform);
      window.location.assign(authorize_url);
    } catch (err) {
      setError(errorMessage(err, "Could not start the connection."));
      setBusy(null);
    }
  }

  async function handleDisconnect(account: SocialAccount) {
    if (
      !window.confirm(
        `Disconnect ${account.display_name}? Posts already published stay live.`,
      )
    ) {
      return;
    }
    setBusy(account.id);
    setError(null);
    try {
      await disconnectSocialAccount(account.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, "Could not disconnect the account."));
    } finally {
      setBusy(null);
    }
  }

  async function handleActivate(account: SocialAccount) {
    setBusy(account.id);
    setError(null);
    try {
      await activateSocialAccount(account.id);
      await load();
    } catch (err) {
      setError(errorMessage(err, "Could not switch the destination."));
    } finally {
      setBusy(null);
    }
  }

  async function handleVerify(account: SocialAccount) {
    setBusy(account.id);
    setError(null);
    setNotice(null);
    try {
      const result = await verifySocialAccount(account.id);
      // The call succeeds either way; `ok` carries the verdict.
      if (result.ok) {
        setNotice(`${account.display_name} is connected and working.`);
      } else {
        setError(result.error ?? "That connection is no longer working.");
      }
    } catch (err) {
      setError(errorMessage(err, "Could not check the connection."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className={styles.page} aria-labelledby="settings-heading">
      <PageHeader
        title="Connections"
        titleId="settings-heading"
        lede="Approved posts publish to whichever account is set as the destination for its network."
      />

      {notice ? (
        <Callout tone="success" role="status">
          {notice}
        </Callout>
      ) : null}
      {error ? (
        <Callout tone="danger" role="alert">
          {error}
        </Callout>
      ) : null}

      {accounts === null ? (
        <EmptyState>Loading connections…</EmptyState>
      ) : (
        <div className={styles.cards}>
          {PLATFORMS.map((platform) => (
            <PlatformCard
              key={platform}
              platform={platform}
              label={PLATFORM_LABELS[platform]}
              blurb={PLATFORM_BLURBS[platform]}
              accounts={accounts.filter((a) => a.platform === platform)}
              busy={busy}
              onConnect={() => void handleConnect(platform)}
              onActivate={(account) => void handleActivate(account)}
              onVerify={(account) => void handleVerify(account)}
              onDisconnect={(account) => void handleDisconnect(account)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

interface PlatformCardProps {
  platform: Platform;
  label: string;
  blurb: string;
  accounts: SocialAccount[];
  busy: string | null;
  onConnect: () => void;
  onActivate: (account: SocialAccount) => void;
  onVerify: (account: SocialAccount) => void;
  onDisconnect: (account: SocialAccount) => void;
}

function PlatformCard({
  platform,
  label,
  blurb,
  accounts,
  busy,
  onConnect,
  onActivate,
  onVerify,
  onDisconnect,
}: PlatformCardProps) {
  const isConnected = accounts.length > 0;
  const needsAttention = accounts.some((a) => a.token_expired);
  // A network we are not cleared to post to is a network there is no point
  // connecting: the OAuth round trip would fail at the provider, and a
  // connection that cannot publish is worse than none — it looks ready.
  // Disconnecting and checking stay open, so an existing connection is never
  // stranded by a hold arriving later.
  const hold = publishingHold(platform);
  const holdId = `${platform}-hold`;

  return (
    <article
      className={isConnected ? styles.cardConnected : styles.card}
      data-platform={platform}
      data-attention={needsAttention ? "true" : undefined}
    >
      <header className={styles.cardHeader}>
        <h2 className={styles.cardTitle}>{label}</h2>
        <span className={isConnected ? styles.dotOn : styles.dotOff} aria-hidden />
        <span className="sr-only">{isConnected ? "Connected" : "Not connected"}</span>
      </header>

      {isConnected ? (
        <ul className={styles.accountList}>
          {accounts.map((account) => (
            <AccountRow
              key={account.id}
              account={account}
              isBusy={busy === account.id}
              onActivate={() => onActivate(account)}
              onVerify={() => onVerify(account)}
              onDisconnect={() => onDisconnect(account)}
            />
          ))}
        </ul>
      ) : (
        <p className={styles.blurb}>{blurb}</p>
      )}

      {/* Why the Connect button below is dead. A notice, not an error: nothing
          has gone wrong, the network is simply not open to us yet. */}
      {hold ? (
        <Callout id={holdId} tone="warn" size="sm">
          {hold}
        </Callout>
      ) : null}

      <footer className={styles.cardFooter}>
        <Button
          variant={isConnected ? "secondary" : "primary"}
          onClick={onConnect}
          disabled={busy !== null || hold !== null}
          aria-describedby={hold ? holdId : undefined}
        >
          {isConnected ? "Reconnect" : `Connect ${label}`}
        </Button>
      </footer>
    </article>
  );
}

function AccountRow({
  account,
  isBusy,
  onActivate,
  onVerify,
  onDisconnect,
}: {
  account: SocialAccount;
  isBusy: boolean;
  onActivate: () => void;
  onVerify: () => void;
  onDisconnect: () => void;
}) {
  const expiry = describeExpiry(account);
  return (
    <li className={styles.account}>
      <div className={styles.accountMain}>
        <p className={styles.accountName}>{account.display_name}</p>
        {account.handle ? (
          <p className={styles.accountHandle}>@{account.handle}</p>
        ) : null}
        {account.is_active ? <Badge tone="accent">Destination</Badge> : null}
      </div>

      {expiry.kind === "expired" ? (
        <p className={styles.expiryBad}>
          Connection expired — reconnect to keep publishing.
        </p>
      ) : expiry.kind === "soon" ? (
        <p className={styles.expiryWarn}>
          Expires in {expiry.days} {expiry.days === 1 ? "day" : "days"} ({expiry.date})
        </p>
      ) : expiry.kind === "ok" ? (
        <p className={styles.expiryOk}>Valid until {expiry.date}</p>
      ) : (
        <p className={styles.expiryOk}>Long-lived — no expiry</p>
      )}

      <div className={styles.accountActions}>
        {account.is_active ? null : (
          <Button variant="link" size="sm" onClick={onActivate} disabled={isBusy}>
            Use this one
          </Button>
        )}
        <Button variant="link" size="sm" onClick={onVerify} disabled={isBusy}>
          Check connection
        </Button>
        <Button variant="linkDanger" size="sm" onClick={onDisconnect} disabled={isBusy}>
          Disconnect
        </Button>
      </div>
    </li>
  );
}

export default function SettingsPage() {
  // useSearchParams needs a Suspense boundary to keep the route statically
  // renderable in the app router.
  return (
    <Suspense fallback={<EmptyState>Loading connections…</EmptyState>}>
      <SettingsContent />
    </Suspense>
  );
}
