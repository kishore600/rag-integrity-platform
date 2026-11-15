/** Where the landing page's "Book a free audit" and "Contact" links send people. Public: it is shown on the page. */
export const CONTACT_EMAIL = "kishore.knaresh07@gmail.com";

const AUDIT_SUBJECT = "Free RAGGuard audit";
const AUDIT_BODY = [
  "Hi, I would like a free RAGGuard audit.",
  "",
  "Where my documents are (for example Amazon S3):",
  "Where my vectors are (Qdrant or pgvector):",
  "Roughly how many documents:",
  "",
].join("\n");

/** A pre-filled email asking for a free audit, so the first reply already knows the setup. */
export const AUDIT_MAILTO = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(AUDIT_SUBJECT)}&body=${encodeURIComponent(AUDIT_BODY)}`;

export const CONTACT_MAILTO = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent("RAGGuard")}`;
