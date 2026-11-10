import { useState } from "react";
import { Check, Loader2 } from "lucide-react";
import type { Plan, PlanId, PlanInterval } from "../types/studio";

interface PricingViewProps {
  plans: Plan[];
  billingMode: "dev" | "stripe";
  authenticated: boolean;
  currentPlan: PlanId | "guest";
  busyPlan: string | null;
  onChoose: (plan: PlanId, interval: PlanInterval) => void;
  onSignIn: () => void;
}

function priceLabel(plan: Plan, interval: PlanInterval): string {
  if (plan.price_monthly === 0) return "$0";
  return `$${interval === "year" ? plan.price_yearly : plan.price_monthly}`;
}

export default function PricingView({
  plans,
  billingMode,
  authenticated,
  currentPlan,
  busyPlan,
  onChoose,
  onSignIn,
}: PricingViewProps) {
  const [interval, setInterval] = useState<PlanInterval>("month");

  return (
    <div className="mx-auto w-full max-w-5xl animate-fade-in">
      <div className="text-center">
        <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-muted">
          Pricing
        </p>
        <h1 className="mt-4 text-balance text-4xl font-semibold leading-[1.05] tracking-[-0.035em] sm:text-5xl">
          Simple plans. Clean cutouts.
        </h1>
        <p className="mx-auto mt-4 max-w-md text-pretty text-sm leading-relaxed text-muted">
          Start free, then pick a plan as your workload grows. Cancel any time.
        </p>
      </div>

      <div className="mt-8 flex justify-center">
        <div className="inline-flex rounded-full border border-line bg-panel p-1 text-xs font-medium">
          {(["month", "year"] as PlanInterval[]).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setInterval(option)}
              className={`rounded-full px-3.5 py-1.5 transition-colors ${
                interval === option
                  ? "bg-accent text-on-accent"
                  : "text-muted hover:text-ink"
              }`}
            >
              {option === "month" ? "Monthly" : "Yearly"}
              {option === "year" ? (
                <span className="ml-1.5 text-[10px] uppercase tracking-wide opacity-70">
                  Save 2 mo
                </span>
              ) : null}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-8 grid gap-4 md:grid-cols-3">
        {plans.map((plan) => {
          const isCurrent = currentPlan === plan.id;
          const isLoading = busyPlan === plan.id;
          const isPaid = plan.price_monthly > 0;
          const label = !isPaid
            ? authenticated
              ? isCurrent
                ? "Current plan"
                : "Free forever"
              : "Create free account"
            : isCurrent
              ? "Current plan"
              : `Choose ${plan.name}`;

          return (
            <div
              key={plan.id}
              className={`flex flex-col rounded-2xl border bg-panel p-6 ${
                plan.highlighted ? "border-ink/40" : "border-line"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-sm font-semibold">{plan.name}</h2>
                {plan.highlighted ? (
                  <span className="rounded-full border border-line px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em] text-muted">
                    Popular
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-xs text-muted">{plan.tagline}</p>

              <div className="mt-5 flex items-end gap-1">
                <span className="text-3xl font-semibold tracking-tight">
                  {priceLabel(plan, interval)}
                </span>
                {isPaid ? (
                  <span className="pb-1 text-xs text-muted">
                    /{interval === "year" ? "yr" : "mo"}
                  </span>
                ) : null}
              </div>
              <p className="mt-1 h-4 text-[11px] text-muted">
                {isPaid && interval === "year"
                  ? `$${(plan.price_yearly / 12).toFixed(2)}/mo billed yearly`
                  : isPaid
                    ? "Billed monthly"
                    : "No card required"}
              </p>

              <ul className="mt-5 flex-1 space-y-2.5">
                {plan.features.map((feature) => (
                  <li key={feature} className="flex items-start gap-2 text-xs">
                    <Check
                      className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink/70"
                      strokeWidth={2}
                    />
                    <span className="leading-relaxed text-muted">{feature}</span>
                  </li>
                ))}
              </ul>

              <button
                type="button"
                disabled={
                  isLoading ||
                  (isCurrent && isPaid) ||
                  (!isPaid && authenticated)
                }
                onClick={() => {
                  if (!authenticated) {
                    onSignIn();
                    return;
                  }
                  if (isPaid) onChoose(plan.id as PlanId, interval);
                }}
                className={`mt-6 w-full ${
                  plan.highlighted ? "btn-primary" : "btn-secondary"
                }`}
              >
                {isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} />
                ) : null}
                {label}
              </button>
            </div>
          );
        })}
      </div>

      <p className="mt-6 text-center text-[11px] text-muted">
        {billingMode === "stripe"
          ? "Secure checkout and billing management provided by Stripe."
          : "Test mode: plans activate instantly without a payment provider."}
      </p>
    </div>
  );
}
