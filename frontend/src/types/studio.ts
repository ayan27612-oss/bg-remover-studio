export type ModelId = "u2net" | "u2netp" | "isnet-general-use";

export type OutputFormat = "png" | "webp" | "jpg";

export type PlanId = "free" | "pro" | "business";

export type PlanInterval = "month" | "year";

export interface ProcessedMetadata {
  model: ModelId;
  width: number;
  height: number;
  originalWidth: number;
  originalHeight: number;
  wasResized: boolean;
  processingMs: number;
  fileSizeBytes: number;
}

export interface Plan {
  id: PlanId;
  name: string;
  tagline: string;
  price_monthly: number;
  price_yearly: number;
  credits: number;
  period: string;
  max_dimension: number;
  formats: string[];
  highlighted: boolean;
  features: string[];
}

export interface PlansResponse {
  plans: Plan[];
  billing_mode: "dev" | "stripe";
}

export interface Usage {
  authenticated: boolean;
  plan: PlanId | "guest";
  plan_name: string;
  used: number;
  limit: number;
  remaining: number;
  period: string;
  resets_at: string;
  max_dimension: number;
  formats: string[];
}

export interface User {
  id: string;
  email: string;
  plan: PlanId;
  plan_interval: PlanInterval;
  plan_renews_at: string | null;
  created_at: string;
}

export interface AuthResponse {
  token: string;
  user: User;
}

export interface CheckoutResponse {
  mode: "dev" | "stripe";
  url: string | null;
  upgraded: boolean;
  canceled_at_period_end: boolean;
  downgraded: boolean;
  user?: User | null;
  usage?: Usage | null;
}

export interface ExportOptions {
  format: OutputFormat;
  maxDimension: number | null;
  quality: number;
}

export const MAX_FILE_BYTES = 25 * 1024 * 1024;

export const ACCEPTED_IMAGE_TYPES = [
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/bmp",
  "image/tiff",
];

export const ACCEPT_ATTRIBUTE = ".png,.jpg,.jpeg,.webp,.bmp,.tif,.tiff";

export const OUTPUT_FORMATS: { id: OutputFormat; label: string }[] = [
  { id: "png", label: "PNG" },
  { id: "webp", label: "WebP" },
  { id: "jpg", label: "JPG" },
];
