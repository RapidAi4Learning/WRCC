"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { ApiError, loginSession } from "@/lib/api";
import { setCurrentUser } from "@/lib/auth";
import styles from "./login.module.css";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const user = await loginSession({ email, password });
      setCurrentUser(user);
      const next = searchParams.get("next");
      // Only follow same-origin relative paths — never an absolute URL.
      const destination = next && next.startsWith("/") && !next.startsWith("//")
        ? next
        : "/generate";
      router.push(destination);
      router.refresh();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Unable to log in. Please try again.",
      );
      setIsSubmitting(false);
    }
  }

  return (
    <form className={styles.card} onSubmit={handleSubmit}>
      <p className={styles.brand}>WRCC</p>
      <h1 className={styles.title}>Content Studio</h1>
      <p className={styles.subtitle}>
        Sign in to generate and review social content for Western Riverina
        Community College.
      </p>

      <label className={styles.label} htmlFor="email">
        Email
      </label>
      <input
        id="email"
        type="email"
        autoComplete="email"
        required
        className={styles.input}
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />

      <label className={styles.label} htmlFor="password">
        Password
      </label>
      <input
        id="password"
        type="password"
        autoComplete="current-password"
        required
        className={styles.input}
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />

      {error ? (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      ) : null}

      <button type="submit" className={styles.submit} disabled={isSubmitting}>
        {isSubmitting ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className={styles.page}>
      {/* useSearchParams requires a Suspense boundary during prerender. */}
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </main>
  );
}
