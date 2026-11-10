import { Loader2 } from "lucide-react";
import type { Usage, User } from "../types/studio";

interface AccountViewProps {
  user: User;
  usage: Usage | null;
  billingMode: "dev" | "stripe";
  busy: string | null;
  onSignOut: () => void;
  onCancel: () => void;
  onPortal: () => void;
  onPricing: () => void;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function AccountView({
  user,
  usage,
  billingMode,
  busy,
  onSignOut,
  onCancel,
  onPortal,
  onPricing,
}: AccountViewProps) {
  const isPaid = user.plan !== "free";
  const used = usage?.used ?? 0;
  const limit = usage?.limit ?? 0;
  const percent = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;

  return (
    <div className="mx-auto w-full max-w-2xl animate-fade-in">
      <div className="text-center">
        <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
          Account
        </p>
        <h1 className="mt-4 text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">
          Your Cutout account.
        </h1>
        <p className="mt-3 text-sm text-muted">{user.email}</p>
      </div>

      <div className="mt-8 rounded-2xl border border-line bg-panel p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted">
              Current plan
            </p>
            <p className="mt-1 text-2xl font-semibold tracking-tight capitalize">
              {usage?.plan_name ?? user.plan}
            </p>
            <p className="mt-1 text-xs text-muted">
              {isPaid
                ? `${user.plan_interval === "year" ? "Yearly" : "Monthly"} billing · renews ${formatDate(user.plan_renews_at)}`
                : "Free forever · no card on file"}
            </p>
          </div>
          <button type="button" className="btn-secondary" onClick={onPricing}>
            {isPaid ? "Change plan" : "Upgrade"}
          </button>
        </div>

        <div className="mt-6 rounded-xl border border-line bg-page p-4">
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-xs font-medium">Usage this {usage?.period ?? "month"}</p>
            <p className="text-xs tabular-nums text-muted">
              {used} / {limit}
            </p>
          </div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-line">
            <div
              className="h-full rounded-full bg-ink transition-[width] duration-500"
              style={{ width: `${percent}%` }}
            />
          </div>
          <div className="mt-2 flex items-center justify-between text-[11px] text-muted">
            <span>{usage?.remaining ?? 0} remaining</span>
            <span>Resets {formatDate(usage?.resets_at ?? null)}</span>
          </div>
          {usage ? (
            <p className="mt-2 text-[11px] text-muted">
              Exports up to {usage.max_dimension} px ·{" "}
              {usage.formats.map((format) => format.toUpperCase()).join(", ")}
            </p>
          ) : null}
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-2">
          {isPaid ? (
            <>
              <button
                type="button"
                className="btn-secondary"
                onClick={onPortal}
                disabled={busy === "portal"}
              >
                {busy === "portal" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} />
                ) : null}
                Manage billing
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  if (
                    window.confirm(
                      billingMode === "stripe"
                        ? "Cancel your subscription? Your plan stays active until the end of the billing period."
                        : "Cancel your plan now and return to Free?",
                    )
                  ) {
                    onCancel();
                  }
                }}
                disabled={busy === "cancel"}
              >
                {busy === "cancel" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} />
                ) : null}
                Cancel plan
              </button>
            </>
          ) : null}
          <button
            type="button"
            className="btn-secondary ml-auto"
            onClick={onSignOut}
            disabled={busy === "signout"}
          >
            {busy === "signout" ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} />
            ) : null}
            Sign out
          </button>
        </div>

        {billingMode === "dev" ? (
          <p className="mt-4 text-[11px] leading-relaxed text-muted">
            Test mode is active. Upgrades and cancellations apply instantly without
            contacting a payment provider.
          </p>
        ) : null}
      </div>
    </div>
  );
}
