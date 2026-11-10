import type {
  AuthResponse,
  CheckoutResponse,
  ExportOptions,
  ModelId,
  OutputFormat,
  PlanId,
  PlanInterval,
  PlansResponse,
  ProcessedMetadata,
  Usage,
  User,
} from "../types/studio";

const API_ORIGIN = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");
const API_ROOT = `${API_ORIGIN}/api`;

const TOKEN_KEY = "cutout.token";
const CLIENT_KEY = "cutout.client";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface RemoveResult {
  blob: Blob;
  metadata: ProcessedMetadata;
  jobId: string;
}

export interface RemoveOptions {
  model?: ModelId;
  outputFormat?: OutputFormat;
  maxDimension?: number | null;
  quality?: number;
  signal?: AbortSignal;
}

export interface ExportedFile {
  blob: Blob;
  width: number;
  height: number;
  format: OutputFormat;
}

function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage may be unavailable; the session still works in memory per request.
  }
}

export function hasToken(): boolean {
  return Boolean(readToken());
}

export function setToken(token: string | null): void {
  writeToken(token);
}

export function getClientId(): string {
  let value: string | null = null;
  try {
    value = localStorage.getItem(CLIENT_KEY);
  } catch {
    value = null;
  }
  if (value) return value;

  const generated =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `client-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
  try {
    localStorage.setItem(CLIENT_KEY, generated);
  } catch {
    // Ignore storage failures.
  }
  return generated;
}

function requestHeaders(json: boolean): Headers {
  const headers = new Headers();
  headers.set("X-Client-Id", getClientId());
  if (json) headers.set("Content-Type", "application/json");
  headers.set("Accept", "application/json");
  const token = readToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

function messageFromBody(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const parts = detail
        .map((item) =>
          item && typeof item === "object" && "msg" in item
            ? String((item as { msg?: unknown }).msg ?? "")
            : "",
        )
        .filter(Boolean);
      if (parts.length) return parts.join("; ");
    }
  }
  return fallback;
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let message = "The request could not be completed.";
  try {
    const body: unknown = await response.json();
    message = messageFromBody(body, message);
  } catch {
    // Keep the fallback message.
  }
  return new ApiError(response.status, message);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: requestHeaders(Boolean(init.body)),
  });
  if (!response.ok) throw await errorFromResponse(response);
  return (await response.json()) as T;
}

export function fetchPlans(): Promise<PlansResponse> {
  return request<PlansResponse>("/plans");
}

export function fetchUsage(): Promise<Usage> {
  return request<Usage>("/usage");
}

export function fetchMe(): Promise<User> {
  return request<User>("/auth/me");
}

export async function signUp(email: string, password: string): Promise<AuthResponse> {
  const response = await request<AuthResponse>("/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  writeToken(response.token);
  return response;
}

export async function signIn(email: string, password: string): Promise<AuthResponse> {
  const response = await request<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  writeToken(response.token);
  return response;
}

export async function signOut(): Promise<void> {
  try {
    await request<{ ok: boolean }>("/auth/logout", { method: "POST" });
  } finally {
    writeToken(null);
  }
}

export function createCheckout(
  plan: PlanId,
  interval: PlanInterval,
): Promise<CheckoutResponse> {
  return request<CheckoutResponse>("/billing/checkout", {
    method: "POST",
    body: JSON.stringify({ plan, interval }),
  });
}

export function openBillingPortal(): Promise<CheckoutResponse> {
  return request<CheckoutResponse>("/billing/portal", { method: "POST" });
}

export function cancelSubscription(): Promise<CheckoutResponse> {
  return request<CheckoutResponse>("/billing/cancel", { method: "POST" });
}

function readMetadata(
  xhr: XMLHttpRequest,
  fallbackModel: ModelId,
  blob: Blob,
): ProcessedMetadata {
  let raw: Partial<Record<string, unknown>> = {};
  try {
    const header = xhr.getResponseHeader("X-Metadata");
    if (header) raw = JSON.parse(header) as Record<string, unknown>;
  } catch {
    raw = {};
  }

  const headerNumber = (name: string): number => {
    const value = Number(xhr.getResponseHeader(name));
    return Number.isFinite(value) ? value : 0;
  };

  const number = (key: string, fallback: number): number => {
    const value = raw[key];
    return typeof value === "number" && Number.isFinite(value) ? value : fallback;
  };

  return {
    model: (raw.model as ModelId) ?? fallbackModel,
    width: number("width", headerNumber("X-Image-Width")),
    height: number("height", headerNumber("X-Image-Height")),
    originalWidth: number("original_width", headerNumber("X-Original-Width")),
    originalHeight: number(
      "original_height",
      headerNumber("X-Original-Height"),
    ),
    wasResized: raw.was_resized === true,
    processingMs: number(
      "processing_ms",
      headerNumber("X-Processing-Time-Ms"),
    ),
    fileSizeBytes: number("file_size_bytes", blob.size),
  };
}

async function toError(blob: Blob, status: number): Promise<ApiError> {
  let message = "The image could not be processed.";
  try {
    const text = (await blob.text()).trim();
    if (text) {
      const body = JSON.parse(text) as unknown;
      message = messageFromBody(body, message);
    }
  } catch {
    // Keep the fallback message.
  }
  return new ApiError(status, message);
}

export function removeBackground(
  file: File,
  options: RemoveOptions = {},
): Promise<RemoveResult> {
  const {
    model = "u2net",
    outputFormat = "png",
    maxDimension = null,
    quality = 90,
    signal,
  } = options;

  return new Promise<RemoveResult>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Cancelled.", "AbortError"));
      return;
    }

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_ROOT}/remove`);
    xhr.responseType = "blob";
    xhr.timeout = 180_000;
    xhr.setRequestHeader("X-Client-Id", getClientId());
    const token = readToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    const cleanup = () => signal?.removeEventListener("abort", handleAbort);
    const handleAbort = () => xhr.abort();

    xhr.onload = () => {
      cleanup();
      if (xhr.status >= 200 && xhr.status < 300) {
        const blob = xhr.response as Blob;
        resolve({
          blob,
          metadata: readMetadata(xhr, model, blob),
          jobId: xhr.getResponseHeader("X-Job-Id") ?? "",
        });
        return;
      }
      void toError(xhr.response as Blob, xhr.status)
        .then(reject)
        .catch(() =>
          reject(new ApiError(xhr.status, "The image could not be processed.")),
        );
    };

    xhr.onerror = () => {
      cleanup();
      reject(
        new ApiError(
          0,
          "Could not reach the server. Make sure the backend is running.",
        ),
      );
    };

    xhr.ontimeout = () => {
      cleanup();
      reject(new ApiError(0, "The request timed out. Please try again."));
    };

    xhr.onabort = () => {
      cleanup();
      reject(new DOMException("Cancelled.", "AbortError"));
    };

    signal?.addEventListener("abort", handleAbort, { once: true });

    const form = new FormData();
    form.append("image", file, file.name);
    form.append("model", model);
    form.append("output_format", outputFormat);
    form.append("quality", String(quality));
    if (maxDimension !== null) {
      form.append("max_dimension", String(maxDimension));
    }
    xhr.send(form);
  });
}

export async function exportJob(
  jobId: string,
  options: ExportOptions,
): Promise<ExportedFile> {
  const response = await fetch(`${API_ROOT}/jobs/${jobId}/export`, {
    method: "POST",
    headers: requestHeaders(true),
    body: JSON.stringify({
      output_format: options.format,
      max_dimension: options.maxDimension,
      quality: options.quality,
    }),
  });
  if (!response.ok) throw await errorFromResponse(response);

  const blob = await response.blob();
  return {
    blob,
    width: Number(response.headers.get("X-Image-Width") ?? 0),
    height: Number(response.headers.get("X-Image-Height") ?? 0),
    format: options.format,
  };
}
