import { AlertTriangle, Check, CheckCircle2, Copy, Info, Loader2, XCircle } from "lucide-react";
import {
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
  useId,
  useState,
} from "react";

export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

// ---- buttons ---------------------------------------------------------------------------------------

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const buttonVariants: Record<ButtonVariant, string> = {
  primary:
    "bg-brand-600 text-white shadow-sm hover:bg-brand-700 disabled:bg-brand-600/60 dark:bg-brand-500 dark:hover:bg-brand-400",
  secondary:
    "border border-slate-300 bg-white text-slate-800 shadow-sm hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:bg-slate-800",
  ghost: "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
  danger: "bg-red-600 text-white shadow-sm hover:bg-red-700 disabled:bg-red-600/60",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  className,
  children,
  disabled,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-sm",
        buttonVariants[variant],
        className,
      )}
      {...props}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

export const linkButtonClass = (variant: ButtonVariant = "secondary", size: "sm" | "md" = "md") =>
  cn(
    "inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-colors",
    size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-sm",
    buttonVariants[variant],
  );

// ---- form fields -----------------------------------------------------------------------------------

export const inputClass =
  "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30 disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:disabled:bg-slate-800";

interface FieldProps {
  label: string;
  hint?: ReactNode;
  error?: string;
}

export function TextField({ label, hint, error, className, ...props }: FieldProps & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error || hint ? `${id}-desc` : undefined}
        className={cn(inputClass, error && "border-red-500 focus:border-red-500 focus:ring-red-500/30")}
        {...props}
      />
      {(error || hint) && (
        <p id={`${id}-desc`} className={cn("mt-1.5 text-xs", error ? "text-red-600 dark:text-red-400" : "text-slate-500")}>
          {error ?? hint}
        </p>
      )}
    </div>
  );
}

export function TextArea({ label, hint, error, className, ...props }: FieldProps & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
        {label}
      </label>
      <textarea id={id} aria-invalid={error ? true : undefined} className={cn(inputClass, "min-h-24")} {...props} />
      {(error || hint) && (
        <p className={cn("mt-1.5 text-xs", error ? "text-red-600 dark:text-red-400" : "text-slate-500")}>{error ?? hint}</p>
      )}
    </div>
  );
}

export function Checkbox({ label, ...props }: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="inline-flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
      <input
        type="checkbox"
        className="size-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500 dark:border-slate-600"
        {...props}
      />
      {label}
    </label>
  );
}

// ---- layout & feedback ---------------------------------------------------------------------------

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <section
      className={cn(
        "rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function CardHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
      <div className="min-w-0">
        <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("px-5 py-4", className)}>{children}</div>;
}

type Tone = "info" | "success" | "warning" | "error";

const alertTones: Record<Tone, { box: string; icon: ReactNode }> = {
  info: {
    box: "border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-900 dark:bg-sky-950/50 dark:text-sky-100",
    icon: <Info className="size-5 shrink-0 text-sky-600 dark:text-sky-400" aria-hidden />,
  },
  success: {
    box: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-100",
    icon: <CheckCircle2 className="size-5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden />,
  },
  warning: {
    box: "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-100",
    icon: <AlertTriangle className="size-5 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />,
  },
  error: {
    box: "border-red-200 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950/50 dark:text-red-100",
    icon: <XCircle className="size-5 shrink-0 text-red-600 dark:text-red-400" aria-hidden />,
  },
};

export function Alert({ tone = "info", title, children, className }: { tone?: Tone; title?: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cn("flex gap-3 rounded-lg border px-4 py-3 text-sm", alertTones[tone].box, className)}>
      {alertTones[tone].icon}
      <div className="min-w-0 space-y-1">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className="leading-relaxed">{children}</div>}
      </div>
    </div>
  );
}

const badgeTones = {
  neutral: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  brand: "bg-brand-50 text-brand-700 dark:bg-brand-900/60 dark:text-brand-200",
  green: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  amber: "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  red: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
};

export function Badge({ tone = "neutral", children }: { tone?: keyof typeof badgeTones; children: ReactNode }) {
  return <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", badgeTones[tone])}>{children}</span>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-5 animate-spin text-slate-400", className)} aria-label="Loading" />;
}

export function FullPageSpinner() {
  return (
    <div className="grid min-h-dvh place-items-center">
      <Spinner className="size-7" />
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function EmptyState({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="mb-3 rounded-full bg-slate-100 p-3 text-slate-500 dark:bg-slate-800 dark:text-slate-400">{icon}</div>
      <p className="font-medium text-slate-900 dark:text-slate-100">{title}</p>
      {children && <div className="mt-1 max-w-md text-sm text-slate-500 dark:text-slate-400">{children}</div>}
    </div>
  );
}

export function CopyField({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-300">
        {label}
      </label>
      <div className="flex gap-2">
        <input id={id} readOnly value={value} className={cn(inputClass, "font-mono text-xs")} onFocus={(e) => e.currentTarget.select()} />
        <Button
          variant="secondary"
          icon={copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
          onClick={async () => {
            await navigator.clipboard?.writeText(value);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
  );
}
