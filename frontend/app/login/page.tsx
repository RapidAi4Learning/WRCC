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
  // Typing a password blind is where a failed login usually comes from — on a
  // phone keyboard especially. Revealing is opt-in and resets on every render
  // of the page, so nothing is left uncovered on a shared screen.
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);
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
      <h1 className={styles.title}>Social Media Marketing</h1>
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
      <div className={styles.passwordField}>
        <input
          id="password"
          type={isPasswordVisible ? "text" : "password"}
          autoComplete="current-password"
          required
          className={`${styles.input} ${styles.passwordInput}`}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <button
          // Inside a form, so it has to say it is not the submit button.
          type="button"
          className={styles.reveal}
          onClick={() => setIsPasswordVisible((visible) => !visible)}
          aria-pressed={isPasswordVisible}
          aria-label={isPasswordVisible ? "Hide password" : "Show password"}
          aria-controls="password"
        >
          {isPasswordVisible ? "Hide" : "Show"}
        </button>
      </div>

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
