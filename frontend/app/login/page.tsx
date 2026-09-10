"use client";

import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { loginSession } from "@/lib/api";
import { setCurrentUser } from "@/lib/auth";
import { errorMessage } from "@/lib/errors";
import BrandLogo from "@/components/layout/BrandLogo";
import PageBackground from "@/components/layout/PageBackground";
import { Button, Callout, Field, TextInput, cardClass } from "@/components/ui";
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
      setError(errorMessage(err, "Unable to log in. Please try again."));
      setIsSubmitting(false);
    }
  }

  return (
    <form className={cardClass({ padding: "xl", className: styles.card })} onSubmit={handleSubmit}>
      <div className={styles.intro}>
        <BrandLogo size="lg" />
        <h1 className={styles.title}>Social Media Marketing</h1>
        <p className={styles.subtitle}>
          Sign in to generate and review social content for Western Riverina
          Community College.
        </p>
      </div>

      <Field label="Email" htmlFor="email">
        <TextInput
          id="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </Field>

      {/* The reveal control sits inside the field rather than beside it, so the
          form keeps its single column and the label still names the input. */}
      <Field label="Password" htmlFor="password">
        <TextInput
          id="password"
          type={isPasswordVisible ? "text" : "password"}
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          trailing={
            <Button
              variant="ghost"
              size="sm"
              className={styles.reveal}
              onClick={() => setIsPasswordVisible((visible) => !visible)}
              aria-pressed={isPasswordVisible}
              aria-label={isPasswordVisible ? "Hide password" : "Show password"}
              aria-controls="password"
            >
              {isPasswordVisible ? "Hide" : "Show"}
            </Button>
          }
        />
      </Field>

      {error ? (
        <Callout tone="danger" role="alert">
          {error}
        </Callout>
      ) : null}

      <Button type="submit" variant="primary" size="lg" block disabled={isSubmitting}>
        {isSubmitting ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className={styles.page}>
      <PageBackground />
      {/* useSearchParams requires a Suspense boundary during prerender. */}
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </main>
  );
}
