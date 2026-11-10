import { useCallback, useRef, useState } from "react";
import type { DragEvent } from "react";
import { ImagePlus } from "lucide-react";
import {
  ACCEPTED_IMAGE_TYPES,
  ACCEPT_ATTRIBUTE,
  MAX_FILE_BYTES,
} from "../types/studio";

interface UploaderProps {
  onFile: (file: File) => void;
  disabled?: boolean;
}

function isImage(file: File): boolean {
  if (ACCEPTED_IMAGE_TYPES.includes(file.type)) return true;
  return /\.(png|jpe?g|webp|bmp|tiff?)$/i.test(file.name);
}

export default function Uploader({ onFile, disabled = false }: UploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const depth = useRef(0);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accept = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (!file) return;
      if (!isImage(file)) {
        setError("Choose a PNG, JPG, WebP, BMP or TIFF image.");
        return;
      }
      if (file.size > MAX_FILE_BYTES) {
        setError("That file is larger than 25 MB.");
        return;
      }
      setError(null);
      onFile(file);
    },
    [onFile],
  );

  const onDragEnter = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    if (disabled) return;
    depth.current += 1;
    setDragging(true);
  };

  const onDragLeave = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    depth.current = Math.max(0, depth.current - 1);
    if (depth.current === 0) setDragging(false);
  };

  const onDrop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    depth.current = 0;
    setDragging(false);
    if (disabled) return;
    accept(event.dataTransfer.files);
  };

  return (
    <div>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT_ATTRIBUTE}
        className="hidden"
        onChange={(event) => {
          accept(event.target.files);
          event.target.value = "";
        }}
      />
      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        onDragEnter={onDragEnter}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={`group flex w-full flex-col items-center justify-center rounded-2xl border border-dashed px-6 py-14 text-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ink/25 disabled:cursor-not-allowed disabled:opacity-60 sm:py-16 ${
          dragging
            ? "border-ink/50 bg-panel2"
            : "border-line bg-panel hover:border-ink/30 hover:bg-panel2/60"
        }`}
      >
        <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-line bg-page text-ink transition-transform duration-300 group-hover:-translate-y-0.5">
          <ImagePlus className="h-5 w-5" strokeWidth={1.6} />
        </span>
        <span className="mt-5 text-sm font-medium text-ink">
          Drop an image here
        </span>
        <span className="mt-1 text-xs text-muted">
          or{" "}
          <span className="underline decoration-line underline-offset-4 group-hover:decoration-ink/40">
            browse files
          </span>
        </span>
        <span className="mt-7 text-[10px] font-medium uppercase tracking-[0.16em] text-muted">
          PNG · JPG · WebP · BMP · TIFF
        </span>
      </button>
      {error ? (
        <p className="mt-3 text-center text-xs text-rose-600 dark:text-rose-400">
          {error}
        </p>
      ) : null}
    </div>
  );
}
