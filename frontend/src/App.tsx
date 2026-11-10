import { useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Loader2, RotateCcw } from "lucide-react";
import Logo from "./components/Logo";
import ThemeToggle from "./components/ThemeToggle";
import Uploader from "./components/Uploader";
import CompareView from "./components/CompareView";
import AuthForm from "./components/AuthForm";
import PricingView from "./components/PricingView";
import AccountView from "./components/AccountView";
import ExportPanel from "./components/ExportPanel";
import { useTheme } from "./hooks/useTheme";
import {
  ApiError,
  cancelSubscription,
  createCheckout,
  fetchMe,
  fetchPlans,
  fetchUsage,
  hasToken,
  openBillingPortal,
  removeBackground,
  setToken,
  signOut,
} from "./services/api";
import { formatBytes, formatDuration } from "./utils/format";
import type {
  AuthResponse,
  Plan,
  PlanId,
  PlanInterval,
  ProcessedMetadata,
  Usage,
  User,
} from "./types/studio";

type Phase = "idle" | "processing" | "done" | "error";

type View = "studio" | "pricing" | "account";

interface Result {
  url: string;
  blob: Blob;
  jobId: string;
  metadata: ProcessedMetadata;
}

function viewFromHash(): View {
  if (typeof window === "undefined") return "studio";
  const raw = window.location.hash.replace(/^#\/?/, "");
  if (raw.startsWith("pricing")) return "pricing";
  if (raw.startsWith("account")) return "account";
  return "studio";
}

function navClass(active: boolean): string {
  return `rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
    active ? "bg-panel2 text-ink" : "text-muted hover:text-ink"
  }`;
}

export default function App() {
  const { theme, toggle } = useTheme();
  const [view, setView] = useState<View>(viewFromHash);
  const [user, setUser] = useState<User | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [billingMode, setBillingMode] = useState<"dev" | "stripe">("dev");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [originalUrl, setOriginalUrl] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);

  const controllerRef = useRef<AbortController | null>(null);
  const originalUrlRef = useRef<string | null>(null);
  const resultUrlRef = useRef<string | null>(null);

  const navigate = useCallback((next: View) => {
    const hash = next === "studio" ? "" : `#${next}`;
    if (window.location.hash !== hash) window.location.hash = hash;
    setView(next);
  }, []);

  useEffect(() => {
    const onHashChange = () => setView(viewFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const refreshUsage = useCallback(async () => {
    try {
      setUsage(await fetchUsage());
    } catch {
      // Usage is a hint; the API still enforces quotas.
    }
  }, []);

  const refreshSession = useCallback(async () => {
    if (!hasToken()) {
      setUser(null);
      await refreshUsage();
      return;
    }
    try {
      setUser(await fetchMe());
    } catch {
      setToken(null);
      setUser(null);
    }
    await refreshUsage();
  }, [refreshUsage]);

  useEffect(() => {
    void refreshSession();
    void fetchPlans()
      .then((response) => {
        setPlans(response.plans);
        setBillingMode(response.billing_mode);
      })
      .catch(() => undefined);
  }, [refreshSession]);

  useEffect(() => {
    if (!window.location.hash.includes("checkout=success")) return;
    window.history.replaceState(null, "", `${window.location.pathname}#account`);
    setView("account");
    setNotice("Subscription updated. Thanks for supporting Cutout.");
    void refreshSession();
  }, [refreshSession]);

  const releaseUrls = useCallback(() => {
    if (originalUrlRef.current) URL.revokeObjectURL(originalUrlRef.current);
    if (resultUrlRef.current) URL.revokeObjectURL(resultUrlRef.current);
    originalUrlRef.current = null;
    resultUrlRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
      releaseUrls();
    };
  }, [releaseUrls]);

  const start = useCallback(
    async (incoming: File) => {
      controllerRef.current?.abort();
      releaseUrls();

      const previewUrl = URL.createObjectURL(incoming);
      originalUrlRef.current = previewUrl;
      setFile(incoming);
      setOriginalUrl(previewUrl);
      setResult(null);
      setError(null);
      setNotice(null);
      setPhase("processing");

      const controller = new AbortController();
      controllerRef.current = controller;

      try {
        const response = await removeBackground(incoming, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;

        const processedUrl = URL.createObjectURL(response.blob);
        resultUrlRef.current = processedUrl;
        setResult({
          url: processedUrl,
          blob: response.blob,
          jobId: response.jobId,
          metadata: response.metadata,
        });
        setPhase("done");
        void refreshUsage();
      } catch (caught) {
        if (controller.signal.aborted) return;
        if (caught instanceof DOMException && caught.name === "AbortError") {
          return;
        }
        if (caught instanceof ApiError && caught.status === 402) {
          setNotice(caught.message);
        }
        setError(
          caught instanceof Error
            ? caught.message
            : "The image could not be processed.",
        );
        setPhase("error");
      } finally {
        if (controllerRef.current === controller) {
          controllerRef.current = null;
        }
      }
    },
    [refreshUsage, releaseUrls],
  );

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    releaseUrls();
    setFile(null);
    setOriginalUrl(null);
    setResult(null);
    setError(null);
    setPhase("idle");
  }, [releaseUrls]);

  const retry = useCallback(() => {
    if (file) void start(file);
  }, [file, start]);

  const handleAuthenticated = useCallback(
    (account: AuthResponse) => {
      setUser(account.user);
      setNotice("You are signed in.");
      void refreshUsage();
    },
    [refreshUsage],
  );

  const handleSignOut = useCallback(async () => {
    setBusy("signout");
    try {
      await signOut();
    } catch {
      setToken(null);
    }
    setUser(null);
    setNotice("Signed out.");
    setBusy(null);
    await refreshUsage();
    navigate("studio");
  }, [navigate, refreshUsage]);

  const handleChoosePlan = useCallback(
    async (plan: PlanId, interval: PlanInterval) => {
      if (!user) {
        setNotice("Create an account or sign in to subscribe.");
        navigate("account");
        return;
      }
      setBusy(`plan-${plan}`);
      setNotice(null);
      try {
        const response = await createCheckout(plan, interval);
        if (response.mode === "stripe" && response.url) {
          window.location.assign(response.url);
          return;
        }
        if (response.user) setUser(response.user);
        if (response.usage) setUsage(response.usage);
        else await refreshUsage();
        setNotice(response.upgraded ? `${plan} plan activated.` : "Plan updated.");
        navigate("account");
      } catch (caught) {
        setNotice(
          caught instanceof Error ? caught.message : "The plan could not be updated.",
        );
      } finally {
        setBusy(null);
      }
    },
    [navigate, refreshUsage, user],
  );

  const handlePortal = useCallback(async () => {
    setBusy("portal");
    setNotice(null);
    try {
      const response = await openBillingPortal();
      if (response.url) {
        window.location.assign(response.url);
        return;
      }
      setNotice("Billing management is unavailable in test mode.");
    } catch (caught) {
      setNotice(
        caught instanceof Error
          ? caught.message
          : "Billing could not be opened.",
      );
    } finally {
      setBusy(null);
    }
  }, []);

  const handleCancel = useCallback(async () => {
    if (!user) return;
    setBusy("cancel");
    setNotice(null);
    try {
      const response = await cancelSubscription();
      if (response.user) setUser(response.user);
      if (response.usage) setUsage(response.usage);
      else await refreshUsage();
      setNotice(
        response.canceled_at_period_end
          ? "Your plan stays active until the end of the billing period."
          : "You are now on the Free plan.",
      );
    } catch (caught) {
      setNotice(
        caught instanceof Error
          ? caught.message
          : "The subscription could not be cancelled.",
      );
    } finally {
      setBusy(null);
    }
  }, [refreshUsage, user]);

  const subtitle =
    phase === "processing"
      ? "Removing background…"
      : phase === "error"
        ? "Something went wrong"
        : phase === "done"
          ? "Cutout ready"
          : "";

  const quotaNote = usage
    ? usage.remaining > 0
      ? usage.authenticated
        ? `${usage.remaining} of ${usage.limit} removals left this ${usage.period}`
        : `${usage.remaining} of ${usage.limit} free previews left today`
      : usage.authenticated
        ? "Your monthly quota is used up. Upgrade to keep going."
        : "Today's free previews are used up. Create a free account to keep going."
    : "Upload an image to begin.";

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-line/80">
        <div className="mx-auto flex h-16 w-full max-w-5xl items-center justify-between gap-3 px-5 sm:px-6">
          <button
            type="button"
            onClick={() => navigate("studio")}
            className="flex items-center gap-2.5 rounded-full focus:outline-none focus-visible:ring-2 focus-visible:ring-ink/25"
          >
            <Logo />
            <span className="text-[15px] font-semibold tracking-tight">
              Cutout
            </span>
          </button>

          <nav className="flex items-center gap-1">
            <button
              type="button"
              className={navClass(view === "studio")}
              onClick={() => navigate("studio")}
            >
              Remove
            </button>
            <button
              type="button"
              className={navClass(view === "pricing")}
              onClick={() => navigate("pricing")}
            >
              Pricing
            </button>
            {user ? (
              <button
                type="button"
                className={navClass(view === "account")}
                onClick={() => navigate("account")}
              >
                Account
              </button>
            ) : (
              <button
                type="button"
                className="btn-primary ml-1 h-8 px-3 text-xs"
                onClick={() => navigate("account")}
              >
                Sign in
              </button>
            )}
            <span className="mx-1 hidden h-5 w-px bg-line sm:block" />
            <ThemeToggle theme={theme} onToggle={toggle} />
          </nav>
        </div>
      </header>

      {notice ? (
        <div className="border-b border-line bg-panel2">
          <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-3 px-5 py-2.5 sm:px-6">
            <p className="text-xs leading-relaxed text-muted">{notice}</p>
            <button
              type="button"
              className="shrink-0 text-[11px] font-medium text-ink underline decoration-line underline-offset-4 hover:decoration-ink/40"
              onClick={() => setNotice(null)}
            >
              Dismiss
            </button>
          </div>
        </div>
      ) : null}

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-5 py-10 sm:px-6 sm:py-16">
        {view === "pricing" ? (
          <PricingView
            plans={plans}
            billingMode={billingMode}
            authenticated={Boolean(user)}
            currentPlan={user?.plan ?? usage?.plan ?? "guest"}
            busyPlan={busy?.startsWith("plan-") ? busy.slice(5) : null}
            onChoose={(plan, interval) => void handleChoosePlan(plan, interval)}
            onSignIn={() => navigate("account")}
          />
        ) : view === "account" ? (
          user ? (
            <AccountView
              user={user}
              usage={usage}
              billingMode={billingMode}
              busy={busy}
              onSignOut={() => void handleSignOut()}
              onCancel={() => void handleCancel()}
              onPortal={() => void handlePortal()}
              onPricing={() => navigate("pricing")}
            />
          ) : (
            <AuthForm onAuthenticated={handleAuthenticated} />
          )
        ) : phase === "idle" ? (
          <div className="mx-auto w-full max-w-2xl animate-fade-in">
            <div className="text-center">
              <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
                Background remover
              </p>
              <h1 className="mt-4 text-balance text-4xl font-semibold leading-[1.05] tracking-[-0.035em] sm:text-5xl">
                Remove the background.
              </h1>
              <p className="mx-auto mt-4 max-w-sm text-pretty text-sm leading-relaxed text-muted">
                Upload an image and download a clean, transparent cutout in PNG,
                WebP or JPG.
              </p>
            </div>
            <div className="mt-10 sm:mt-12">
              <Uploader onFile={(next) => void start(next)} />
            </div>
            <p className="mt-4 text-center text-[11px] leading-relaxed text-muted">
              {quotaNote}
              {usage && !usage.authenticated ? (
                <>
                  {" · "}
                  <button
                    type="button"
                    className="font-medium text-ink underline decoration-line underline-offset-4 hover:decoration-ink/40"
                    onClick={() => navigate("account")}
                  >
                    Create a free account
                  </button>
                </>
              ) : null}
            </p>
          </div>
        ) : (
          <div className="animate-fade-in">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{file?.name}</p>
                <p className="mt-0.5 text-xs text-muted">{subtitle}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={reset}
                >
                  <RotateCcw className="h-3.5 w-3.5" strokeWidth={1.75} />
                  New image
                </button>
              </div>
            </div>

            {phase === "error" && error ? (
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-panel p-4">
                <div className="flex min-w-0 items-start gap-3">
                  <AlertCircle
                    className="mt-0.5 h-4 w-4 shrink-0 text-rose-500"
                    strokeWidth={1.75}
                  />
                  <div className="min-w-0">
                    <p className="text-sm font-medium">
                      Could not process this image
                    </p>
                    <p className="mt-0.5 text-xs leading-relaxed text-muted">
                      {error}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => navigate("pricing")}
                  >
                    View plans
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={retry}
                  >
                    Try again
                  </button>
                </div>
              </div>
            ) : null}

            {phase === "done" && result ? (
              <CompareView
                originalUrl={originalUrl ?? ""}
                processedUrl={result.url}
                alt={file?.name ?? "Background removal result"}
              />
            ) : (
              <div className="relative flex h-[clamp(300px,58vh,660px)] w-full items-center justify-center overflow-hidden rounded-2xl border border-line bg-panel2">
                {originalUrl ? (
                  <img
                    src={originalUrl}
                    alt="Selected image"
                    className={`h-full w-full object-contain ${
                      phase === "processing" ? "opacity-35 blur-[1px]" : ""
                    }`}
                  />
                ) : null}
                {phase === "processing" ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
                    <Loader2
                      className="h-5 w-5 animate-spin"
                      strokeWidth={1.75}
                    />
                    <p className="text-sm text-muted">Removing background…</p>
                    <div className="h-0.5 w-44 overflow-hidden rounded-full bg-line">
                      <div className="h-full w-1/3 animate-pulse rounded-full bg-ink/50" />
                    </div>
                  </div>
                ) : null}
              </div>
            )}

            {phase === "done" && result ? (
              <>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
                  <span>
                    {result.metadata.width} × {result.metadata.height} px
                    {result.metadata.wasResized ? " (resized)" : ""}
                  </span>
                  <span>
                    {formatBytes(result.metadata.fileSizeBytes)} ·{" "}
                    {formatDuration(result.metadata.processingMs)}
                  </span>
                </div>
                <ExportPanel
                  jobId={result.jobId}
                  fileName={file?.name ?? "cutout.png"}
                  maxDimension={usage?.max_dimension ?? 1024}
                  formats={usage?.formats ?? ["png", "webp", "jpg"]}
                />
              </>
            ) : null}
          </div>
        )}
      </main>

      <footer className="border-t border-line/80">
        <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-2 px-5 py-5 text-[11px] text-muted sm:px-6">
          <span>Cutout — clean cutouts, nothing extra.</span>
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="hover:text-ink"
              onClick={() => navigate("pricing")}
            >
              Pricing
            </button>
            <button
              type="button"
              className="hover:text-ink"
              onClick={() => navigate(user ? "account" : "studio")}
            >
              {user ? "Account" : "Remove"}
            </button>
          </div>
        </div>
      </footer>
    </div>
  );
}
