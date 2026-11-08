import { Eye, Globe, KeyRound, Lock, ShieldCheck, UserCheck, type LucideIcon } from "lucide-react";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { LinkButton } from "@/components/shared/link-button";
import { NotAvailable } from "@/components/shared/states";
import type { Session } from "@/types/api";

interface Fact {
  Icon: LucideIcon;
  title: string;
  text: string;
}

const READ_ONLY: Fact = {
  Icon: Eye,
  title: "RAGGuard only reads from your systems",
  text: "It lists and reads object metadata in S3, queries the manifest inside a read-only transaction, and reads from Qdrant. Repairs are sent to your own worker, which does the writing.",
};

const APP_FACTS: Fact[] = [
  {
    Icon: Lock,
    title: "Connection secrets are encrypted at rest",
    text: "Every field marked as a secret (access keys, the database connection string, the Qdrant key, the alert webhook address and the repair signing secret) is encrypted before it reaches the database. The encryption key exists only in the server's environment.",
  },
  {
    Icon: ShieldCheck,
    title: "Saved secrets are never shown again",
    text: "The API never returns a saved secret. Settings pages show only that a value is saved, and you can replace it or remove it.",
  },
  {
    Icon: UserCheck,
    title: "Sessions are protected",
    text: "Your session cookie is HttpOnly, so scripts on the page cannot read it, and every change is checked to come from this site. Only a hash of the session token is stored. Passwords are hashed, and changing yours signs out your other sessions. Repeated sign-in attempts are rate limited.",
  },
  {
    Icon: Globe,
    title: "Private addresses are refused",
    text: "In hosted mode, addresses on a private network, on localhost or on a cloud metadata service are refused when you save them and again before each connection.",
  },
  READ_ONLY,
];

export function SecurityTab({ session }: { session: Session }) {
  const facts = session.app ? APP_FACTS : [READ_ONLY];
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="How your data is protected" description="What RAGGuard does with your connections and your account." />
        <CardBody>
          <ul className="space-y-4">
            {facts.map(({ Icon, title, text }) => (
              <li key={title} className="flex items-start gap-3">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-control bg-brand-light text-brand">
                  <Icon className="h-4 w-4" aria-hidden />
                </span>
                <div className="min-w-0">
                  <h3 className="text-card text-ink">{title}</h3>
                  <p className="mt-0.5 text-body text-ink-2">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>

      {session.app ? (
        <Card>
          <CardHeader title="API keys" description="Keys for CI jobs and scripts are shown once, stored as a hash, and can be revoked at any time. They cannot read settings, create keys or change passwords." />
          <CardBody>
            <LinkButton to="/integrations" variant="secondary">
              <KeyRound className="h-4 w-4" aria-hidden /> Manage API keys
            </LinkButton>
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardHeader title="Access to this server" description="Single-user mode has no accounts or sessions." />
          <CardBody>
            <p className="text-body text-ink-2">
              {session.api_key_required
                ? "Access is protected by one shared API key (RAGI_API_KEY) that the server's operator sets."
                : "No API key is required to use this server. Set RAGI_API_KEY in the server's environment to protect it."}
            </p>
          </CardBody>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <NotAvailable title="Two-factor authentication" description="Sign-in uses an email and a password only." />
        <NotAvailable title="Single sign-on" description="Accounts are created with an email and a password." />
      </div>
    </div>
  );
}
