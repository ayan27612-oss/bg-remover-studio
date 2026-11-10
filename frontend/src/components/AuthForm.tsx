import { useState } from "react";
import type { FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { signIn, signUp } from "../services/api";
import type { AuthResponse } from "../types/studio";

interface AuthFormProps {
  onAuthenticated: (account: AuthResponse) => void;
}

type Mode = "signin" | "signup";

export default function AuthForm({ onAuthenticated }: AuthFormProps) {
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const account =
        mode === "signin"
          ? await signIn(email.trim(), password)
          : await signUp(email.trim(), password);
      onAuthenticated(account);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Could not sign in right now.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-md animate-fade-in">
      <div className="text-center">
        <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
          Account
        </p>
        <h1 className="mt-4 text-3xl font-semibold tracking-[-0.03em]">
          {mode === "signin" ? "Welcome back." : "Create your account."}
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-muted">
          {mode === "signin"
            ? "Sign in to keep your plan, usage and exports in one place."
            : "Get 5 free removals every month. No card required."}
        </p>
      </div>

      <form
        onSubmit={submit}
        className="mt-8 rounded-2xl border border-line bg-panel p-6"
      >
        <label className="block text-xs font-medium text-muted" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="mt-1.5 w-full rounded-xl border border-line bg-page px-3.5 py-2.5 text-sm text-ink outline-none transition focus:border-ink/30 focus:ring-2 focus:ring-ink/10"
          placeholder="you@example.com"
        />

        <label
          className="mt-4 block text-xs font-medium text-muted"
          htmlFor="password"
        >
          Password
        </label>
        <input
          id="password"
          type="password"
          autoComplete={mode === "signin" ? "current-password" : "new-password"}
          required
          minLength={8}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mt-1.5 w-full rounded-xl border border-line bg-page px-3.5 py-2.5 text-sm text-ink outline-none transition focus:border-ink/30 focus:ring-2 focus:ring-ink/10"
          placeholder={mode === "signup" ? "At least 8 characters" : "Your password"}
        />

        {error ? (
          <p className="mt-4 rounded-lg border border-line bg-panel2 px-3 py-2 text-xs leading-relaxed text-rose-600 dark:text-rose-400">
            {error}
          </p>
        ) : null}

        <button type="submit" className="btn-primary mt-5 w-full" disabled={busy}>
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} />
          ) : null}
          {mode === "signin" ? "Sign in" : "Create account"}
        </button>

        <p className="mt-4 text-center text-xs text-muted">
          {mode === "signin" ? "No account yet?" : "Already have an account?"}{" "}
          <button
            type="button"
            className="font-medium text-ink underline decoration-line underline-offset-4 hover:decoration-ink/40"
            onClick={() => {
              setMode(mode === "signin" ? "signup" : "signin");
              setError(null);
            }}
          >
            {mode === "signin" ? "Create one" : "Sign in"}
          </button>
        </p>
      </form>
    </div>
  );
}
