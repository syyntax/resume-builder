export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="size-8 shrink-0" aria-hidden>
        <rect width="32" height="32" rx="7" fill="#1F3A5F" />
        <path d="M10 8h9l5 5v11a1 1 0 0 1-1 1H10a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z" fill="#fff" />
        <path d="M12.5 15h7M12.5 18.5h7M12.5 22h4.5" stroke="#1F3A5F" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
      {!compact && <span className="text-lg font-semibold tracking-tight text-slate-900 dark:text-white">Resume Tailor</span>}
    </span>
  );
}
