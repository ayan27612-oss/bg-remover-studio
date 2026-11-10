export default function Logo() {
  return (
    <span className="flex h-7 w-7 items-center justify-center rounded-[8px] bg-accent text-on-accent">
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
        aria-hidden="true"
      >
        <rect
          x="3.5"
          y="3.5"
          width="17"
          height="17"
          rx="4"
          stroke="currentColor"
          strokeWidth="1.6"
        />
        <circle cx="12" cy="12" r="3.6" fill="currentColor" />
      </svg>
    </span>
  );
}
