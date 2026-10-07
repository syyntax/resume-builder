import { CheckCircle2, Circle, KeyRound, Sparkles, Upload } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { useMe } from "../auth/auth";
import { Badge, Card, CardBody, CardHeader, cn, linkButtonClass } from "../components/ui";
import { timeAgo } from "../lib/format";
import { useMasters } from "./MastersPages";

function Step({ done, title, description, action, soon }: { done: boolean; title: string; description: string; action?: ReactNode; soon?: boolean }) {
  return (
    <li className="flex items-start gap-4 px-5 py-4">
      {done ? (
        <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-emerald-600" aria-label="Done" />
      ) : (
        <Circle className="mt-0.5 size-5 shrink-0 text-slate-300 dark:text-slate-600" aria-label="Not done yet" />
      )}
      <div className="min-w-0 flex-1">
        <p className={cn("font-medium", done ? "text-slate-500 line-through decoration-slate-300" : "text-slate-900 dark:text-slate-100")}>
          {title} {soon && <Badge>Coming soon</Badge>}
        </p>
        <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{description}</p>
      </div>
      {action}
    </li>
  );
}

export function HomePage() {
  const { data: me } = useMe();
  const masters = useMasters();
  const hasMaster = (masters.data?.length ?? 0) > 0;
  const firstName = me?.user.displayName.split(" ")[0] ?? "";

  return (
    <>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">Welcome, {firstName}</h1>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Resume Tailor turns one master résumé into a tailored résumé and cover letter for each job.
        </p>
      </div>

      <Card className="mb-6">
        <CardHeader title="Get set up" description="A few one-time steps." />
        <ol className="divide-y divide-slate-200 dark:divide-slate-800">
          <Step
            done={hasMaster}
            title="Add your master résumé"
            description="Upload a JSON file with your full history. Start from the example if you don't have one."
            action={
              !hasMaster && (
                <Link to="/masters" className={linkButtonClass("primary", "sm")}>
                  <Upload className="size-4" aria-hidden /> Upload
                </Link>
              )
            }
          />
          <Step
            done={false}
            soon
            title="Connect your Anthropic API key"
            description="AI tailoring runs on your own key, encrypted at rest. This arrives with the next release."
            action={<KeyRound className="size-5 text-slate-300 dark:text-slate-600" aria-hidden />}
          />
          <Step
            done={false}
            soon
            title="Tailor your first application"
            description="Paste a job posting to get a tailored résumé and cover letter."
            action={<Sparkles className="size-5 text-slate-300 dark:text-slate-600" aria-hidden />}
          />
        </ol>
      </Card>

      {hasMaster && (
        <Card>
          <CardHeader title="Your master résumés" actions={<Link to="/masters" className={linkButtonClass("ghost", "sm")}>View all</Link>} />
          <CardBody className="divide-y divide-slate-200 py-0 dark:divide-slate-800">
            {masters.data?.slice(0, 5).map((m) => (
              <Link key={m.id} to={`/masters/${m.id}`} className="flex items-center justify-between gap-4 py-3 text-sm hover:text-brand-700 dark:hover:text-brand-200">
                <span className="font-medium">{m.label}</span>
                <span className="text-slate-500">updated {timeAgo(m.updatedAt)}</span>
              </Link>
            ))}
          </CardBody>
        </Card>
      )}
    </>
  );
}
