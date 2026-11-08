import { Check, Eye, Globe, Lock } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import type { SystemKind, SystemStatus } from "../_settings-form";

const STEPS: { kind: SystemKind; title: string; text: string }[] = [
  { kind: "s3", title: "Source", text: "Amazon S3 holds the documents that should be searchable." },
  { kind: "manifest", title: "Manifest", text: "A PostgreSQL table where your pipeline records what it indexed." },
  { kind: "qdrant", title: "Index", text: "Qdrant holds the vectors that answer searches." },
];

/** The three promises that make connecting safe to do. Shown while setting up, and again as a reminder afterwards. */
export function TrustPoints({ className }: { className?: string }) {
  const items = [
    { Icon: Lock, text: "Credentials are encrypted before they are stored, are used only from this server to read your systems, and are never shown again after you save them." },
    { Icon: Eye, text: "RAGGuard only reads. It never writes to your S3 bucket, your manifest database or your vector index." },
    { Icon: Globe, text: "In hosted mode only public hosts are accepted. Addresses on a private network or on localhost are refused, and the server tells you so if you enter one." },
  ];
  return (
    <ul className={cn("space-y-3", className)}>
      {items.map(({ Icon, text }) => (
        <li key={text} className="flex items-start gap-3 text-body text-ink">
          <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-light text-brand">
            <Icon className="h-3.5 w-3.5" aria-hidden />
          </span>
          <span>{text}</span>
        </li>
      ))}
    </ul>
  );
}

/** Three steps with the current one highlighted: shown until all three connections are saved. */
export function SetupGuide({ systems }: { systems: SystemStatus[] }) {
  const current = STEPS.findIndex((s) => !systems.find((x) => x.kind === s.kind)?.configured);
  return (
    <Card>
      <CardHeader title="Connect your three systems" description="RAGGuard needs all three before it can run an audit. Start with the highlighted step." />
      <CardBody className="space-y-5">
        <ol className="grid gap-3 md:grid-cols-3">
          {STEPS.map((s, i) => {
            const done = !!systems.find((x) => x.kind === s.kind)?.configured;
            const isCurrent = i === current;
            return (
              <li
                key={s.kind}
                aria-current={isCurrent ? "step" : undefined}
                className={cn("rounded-card border p-4", isCurrent ? "border-brand bg-brand-light" : done ? "border-success/30 bg-success-bg" : "border-line bg-app")}
              >
                <div className="flex items-center gap-2.5">
                  <span
                    className={cn(
                      "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-card",
                      done ? "bg-success text-white" : isCurrent ? "bg-brand text-white" : "bg-surface text-ink-2",
                    )}
                  >
                    {done ? <Check className="h-4 w-4" aria-hidden /> : i + 1}
                  </span>
                  <h3 className="text-card text-ink">
                    {s.title}
                    <span className="sr-only">{done ? " (done)" : isCurrent ? " (current step)" : ""}</span>
                  </h3>
                </div>
                <p className="mt-2 text-support text-ink-2">{s.text}</p>
              </li>
            );
          })}
        </ol>
        <TrustPoints />
      </CardBody>
    </Card>
  );
}
