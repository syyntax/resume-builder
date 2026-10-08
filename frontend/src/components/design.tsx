import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useId } from "react";

import { api } from "../api/client";
import type { TemplateCatalog, Theme } from "../api/types";
import { Badge, Checkbox, Spinner, cn, inputClass } from "./ui";

export const templatesKey = ["templates"] as const;

export function useTemplates() {
  return useQuery({ queryKey: templatesKey, queryFn: () => api<TemplateCatalog>("GET", "/api/templates"), staleTime: Infinity });
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: { value: string; label: string }[]; onChange: (value: string) => void }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-400">{label}</label>
      <select id={id} className={cn(inputClass, "py-1.5")} value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

/** Template and theme choices (TPL-3). Controlled: the page saves changes and refreshes the preview. */
export function DesignPanel({ template, theme, onChange, error }: {
  template: string;
  theme: Theme;
  onChange: (template: string, theme: Theme) => void;
  error?: string | null;
}) {
  const catalog = useTemplates();
  const colorId = useId();
  if (catalog.isPending) return <Spinner />;
  if (catalog.isError) return null;
  const { templates, options } = catalog.data;
  const set = (patch: Partial<Theme>) => onChange(template, { ...theme, ...patch });
  const custom = !options.accents.some((a) => a.value === theme.accent);

  return (
    <div className="space-y-4">
      <div>
        <p className="mb-1.5 text-xs font-medium text-slate-600 dark:text-slate-400">Template</p>
        <div className="grid grid-cols-2 gap-2">
          {templates.map((t) => {
            const selected = t.key === template;
            return (
              <button key={t.key} type="button" disabled={!t.available} aria-pressed={selected} title={t.description}
                // a template brings its own colors and fonts; the other options (paper, density…) stay
                onClick={() => !selected && onChange(t.key, { ...theme, ...(t.defaultTheme as Partial<Theme>) })}
                className={cn("group overflow-hidden rounded-lg border text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60",
                  selected ? "border-brand-500 ring-1 ring-brand-500" : "border-slate-200 hover:border-slate-400 dark:border-slate-700")}>
                <img src={t.thumbnailUrl} alt="" loading="lazy" className="aspect-[400/518] w-full border-b border-slate-100 bg-white object-cover object-top dark:border-slate-800" />
                <span className="block px-2.5 py-2">
                  <span className="flex items-center justify-between gap-2 font-medium text-slate-900 dark:text-slate-100">
                    {t.label}
                    {selected ? <Check className="size-4 text-brand-600 dark:text-brand-300" aria-hidden /> : !t.available && <Badge>Soon</Badge>}
                  </span>
                  <span className="block text-xs text-slate-500 dark:text-slate-400">{t.layout}</span>
                  <span className="block text-xs text-slate-500 dark:text-slate-400">ATS: {t.ats.toLowerCase()}</span>
                </span>
              </button>
            );
          })}
        </div>
        <p className="mt-1.5 text-xs text-slate-500 dark:text-slate-400">Each template brings its own colors and fonts. Change them below.</p>
      </div>

      <div>
        <p className="mb-1.5 text-xs font-medium text-slate-600 dark:text-slate-400">Accent color</p>
        <div className="flex flex-wrap items-center gap-2">
          {options.accents.map((a) => (
            <button key={a.value} type="button" title={a.label} aria-label={a.label} aria-pressed={theme.accent === a.value}
              onClick={() => set({ accent: a.value })}
              className={cn("size-7 rounded-full ring-offset-2 transition dark:ring-offset-slate-900",
                theme.accent === a.value ? "ring-2 ring-slate-900 dark:ring-white" : "hover:scale-110")}
              style={{ backgroundColor: a.value }} />
          ))}
          <label htmlFor={colorId} className={cn("relative size-7 cursor-pointer overflow-hidden rounded-full border border-dashed border-slate-400 ring-offset-2 dark:ring-offset-slate-900",
            custom && "ring-2 ring-slate-900 dark:ring-white")} title="Custom color"
            style={custom ? { backgroundColor: theme.accent } : undefined}>
            <span className="sr-only">Custom color</span>
            <input id={colorId} type="color" className="absolute inset-0 cursor-pointer opacity-0" value={theme.accent.toLowerCase()}
              onChange={(e) => set({ accent: e.target.value.toUpperCase() })} />
          </label>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Select label="Fonts" value={theme.fonts} options={options.fonts} onChange={(v) => set({ fonts: v as Theme["fonts"] })} />
        <Select label="Density" value={theme.density} options={options.densities} onChange={(v) => set({ density: v as Theme["density"] })} />
        <Select label="Paper" value={theme.paper} options={options.papers} onChange={(v) => set({ paper: v as Theme["paper"] })} />
        <Select label="Margins" value={theme.margins} options={options.margins} onChange={(v) => set({ margins: v as Theme["margins"] })} />
        <Select label="Dates" value={theme.dateFormat} options={options.dateFormats} onChange={(v) => set({ dateFormat: v as Theme["dateFormat"] })} />
        <div className="flex items-end pb-2">
          <Checkbox label="Contact icons" checked={theme.contactIcons} onChange={(e) => set({ contactIcons: e.target.checked })} />
        </div>
      </div>
      {error && <p className="text-sm text-red-600 dark:text-red-400" role="alert">{error}</p>}
    </div>
  );
}
