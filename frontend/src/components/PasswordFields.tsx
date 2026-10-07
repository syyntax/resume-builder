import { TextField, cn } from "./ui";

/** Rough strength estimate for the meter. The server's policy (length + common-password list) decides. */
export function passwordStrength(password: string): 0 | 1 | 2 | 3 | 4 {
  if (password.length < 12) return password.length === 0 ? 0 : 1;
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(password)).length;
  const words = password.trim().split(/[\s\-_.]+/).filter((w) => w.length >= 3).length;
  if (password.length >= 20 || words >= 4) return 4;
  if (password.length >= 16 || classes >= 3 || words >= 3) return 3;
  return 2;
}

const labels = ["", "Too short", "OK", "Strong", "Very strong"];
const colors = ["bg-slate-200", "bg-red-500", "bg-amber-500", "bg-emerald-500", "bg-emerald-600"];

interface PasswordFieldsProps {
  password: string;
  confirm: string;
  onPassword: (value: string) => void;
  onConfirm: (value: string) => void;
  error?: string;
  label?: string;
}

export function PasswordFields({ password, confirm, onPassword, onConfirm, error, label = "Password" }: PasswordFieldsProps) {
  const strength = passwordStrength(password);
  const mismatch = confirm.length > 0 && confirm !== password;
  return (
    <>
      <div>
        <TextField
          label={label}
          type="password"
          autoComplete="new-password"
          required
          minLength={12}
          maxLength={128}
          value={password}
          onChange={(e) => onPassword(e.target.value)}
          error={error}
          hint="At least 12 characters. A few random words make a strong, memorable passphrase."
        />
        <div className="mt-2 flex items-center gap-2" aria-live="polite">
          <div className="flex h-1.5 flex-1 gap-1">
            {[1, 2, 3, 4].map((step) => (
              <span key={step} className={cn("flex-1 rounded-full", strength >= step ? colors[strength] : "bg-slate-200 dark:bg-slate-800")} />
            ))}
          </div>
          <span className="w-20 text-right text-xs text-slate-500">{labels[strength]}</span>
        </div>
      </div>
      <TextField
        label="Confirm password"
        type="password"
        autoComplete="new-password"
        required
        value={confirm}
        onChange={(e) => onConfirm(e.target.value)}
        error={mismatch ? "Passwords don't match." : undefined}
      />
    </>
  );
}
