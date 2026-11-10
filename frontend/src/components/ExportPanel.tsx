import { useMemo, useState } from "react";
import { Download, Loader2 } from "lucide-react";
import { exportJob } from "../services/api";
import { buildDownloadName, formatBytes } from "../utils/format";
import { OUTPUT_FORMATS } from "../types/studio";
import type { OutputFormat } from "../types/studio";

interface ExportPanelProps {
  jobId: string;
  fileName: string;
  maxDimension: number;
  formats: string[];
}

const RESOLUTIONS = [512, 1024, 2048, 4096, 8192];

export default function ExportPanel({
  jobId,
  fileName,
  maxDimension,
  formats,
}: ExportPanelProps) {
  const availableFormats = useMemo(
    () => OUTPUT_FORMATS.filter((item) => formats.includes(item.id)),
    [formats],
  );
  const availableResolutions = useMemo(
    () => RESOLUTIONS.filter((value) => value <= maxDimension),
    [maxDimension],
  );

  const [format, setFormat] = useState<OutputFormat>(
    availableFormats[0]?.id ?? "png",
  );
  const [resolution, setResolution] = useState("original");
  const [quality, setQuality] = useState(90);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const download = async () => {
    if (!jobId || busy) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      const file = await exportJob(jobId, {
        format,
        maxDimension: resolution === "original" ? null : Number(resolution),
        quality,
      });
      const url = URL.createObjectURL(file.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = buildDownloadName(fileName, format);
      anchor.rel = "noopener";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setInfo(
        `${file.width} × ${file.height} px · ${formatBytes(file.blob.size)}`,
      );
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "The export could not be created.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 rounded-xl border border-line bg-panel p-3 sm:p-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-[6rem] flex-1">
          <span className="block text-[10px] font-medium uppercase tracking-[0.14em] text-muted">
            Format
          </span>
          <select
            value={format}
            onChange={(event) => setFormat(event.target.value as OutputFormat)}
            className="mt-1 w-full rounded-lg border border-line bg-page px-2.5 py-2 text-xs text-ink outline-none transition focus:border-ink/30 focus:ring-2 focus:ring-ink/10"
          >
            {availableFormats.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        <label className="min-w-[8rem] flex-1">
          <span className="block text-[10px] font-medium uppercase tracking-[0.14em] text-muted">
            Resolution
          </span>
          <select
            value={resolution}
            onChange={(event) => setResolution(event.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-page px-2.5 py-2 text-xs text-ink outline-none transition focus:border-ink/30 focus:ring-2 focus:ring-ink/10"
          >
            <option value="original">Original (≤ {maxDimension} px)</option>
            {availableResolutions.map((value) => (
              <option key={value} value={value}>
                {value} px
              </option>
            ))}
          </select>
        </label>

        {format !== "png" ? (
          <label className="min-w-[9rem] flex-[1.4]">
            <span className="flex items-center justify-between text-[10px] font-medium uppercase tracking-[0.14em] text-muted">
              <span>Quality</span>
              <span className="tabular-nums text-ink">{quality}</span>
            </span>
            <input
              type="range"
              min={40}
              max={100}
              step={1}
              value={quality}
              onChange={(event) => setQuality(Number(event.target.value))}
              className="mt-2.5 h-1 w-full cursor-pointer accent-ink"
            />
          </label>
        ) : null}

        <button
          type="button"
          className="btn-primary shrink-0"
          onClick={() => void download()}
          disabled={busy || !jobId}
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} />
          ) : (
            <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
          )}
          Export
        </button>
      </div>

      {error ? (
        <p className="mt-3 text-[11px] leading-relaxed text-rose-600 dark:text-rose-400">
          {error}
        </p>
      ) : info ? (
        <p className="mt-3 text-[11px] text-muted">Downloaded {info}</p>
      ) : null}
    </div>
  );
}
