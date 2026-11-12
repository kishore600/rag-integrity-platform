const e=`# RAGGuard user guide

RAGGuard tells you when your RAG index is wrong, before your users do. It compares three things that should always agree: your source documents (Amazon S3), the record your pipeline keeps of what it indexed (a PostgreSQL manifest), and what is actually searchable (Qdrant). When they disagree it shows you exactly what drifted, how serious it is, and how to fix it safely.

This guide explains every page, every section, every field and every value in the product, and walks you from a new account to a verified fix. It is written for someone who has never seen the product. You can read it from top to bottom, or jump to the page you are on. You can also watch the [narrated video walkthrough](19-video-walkthrough.md), which follows the same path.

> **Read it inside the product.** Everything in this guide, and the video, is also built into RAGGuard: choose **Help and user guide** at the bottom of the left menu (or in the account menu), or open the address \`/help\`. You can read it before you have an account (the landing page has a **User guide** link).

> **About the screenshots.** They come from a demo workspace that is connected to a synthetic knowledge base (three tenants, a few hundred documents, and about 50 deliberate faults). Your numbers, names and documents will differ. The layout, the labels and the meaning of every value are the same.

## Start here

| If you want to... | Read |
|---|---|
| Understand what RAGGuard is and what you need before you start | [1. Getting started](01-getting-started.md) |
| Learn the words used throughout the product | [2. Concepts you need](02-concepts.md) |
| See everything in order, from sign-up to a verified fix | [15. End-to-end journey](15-end-to-end-journey.md) |
| Watch the whole thing instead of reading it | [19. The video walkthrough](19-video-walkthrough.md) |

## Chapters

### Set up
| Chapter | What it covers |
|---|---|
| [1. Getting started](01-getting-started.md) | What the product does, what you need, a 10-minute quick start, the landing page |
| [2. Concepts you need](02-concepts.md) | Source, manifest, index, tenant, chunk, audit, issue, severity, health score, and the rest |
| [3. Sign in and find your way around](03-interface-and-sign-in.md) | Sign-up and sign-in, the sidebar, the top bar, search, notifications, the account menu, phones |
| [4. Connect your data sources](04-data-sources.md) | Every field for Amazon S3, the PostgreSQL manifest and Qdrant, and what each connection test checks |

### The pages
| Chapter | What it covers |
|---|---|
| [5. Overview](05-overview.md) | The health score, the cards, the charts and the lists |
| [6. Reconciliation](06-reconciliation.md) | The three-way comparison, scoped audits, exports, the documents table |
| [7. Integrity issues](07-integrity-issues.md) | Filtering and reading issues, the issue panel, ignoring, and all 11 issue types |
| [20. Isolation](20-isolation.md) | Whether one tenant's content can reach another: banner, checks, tenants, the drill and the evidence report (this page sits right after Integrity Issues in the menu) |
| [8. Repair plans](08-repair-plans.md) | Recommended work, plans, the repair webhook flow, verification and cleanup |
| [9. Impact analysis](09-impact-analysis.md) | What-if analysis for open issues, pipeline changes and ingestion failures |
| [10. Documents](10-documents.md) | Every document, its embedding status, live inspection of its chunks |
| [11. Audit history](11-audit-history.md) | Every audit, run detail pages, the activity log |
| [12. Integrations](12-integrations.md) | The repair webhook and API keys |
| [13. Alerts](13-alerts.md) | Webhook alerts, when they fire, and delivery history |
| [14. Settings](14-settings.md) | Account, target pipeline, audit policy, security, team and billing |

### Putting it to work
| Chapter | What it covers |
|---|---|
| [15. End-to-end journey](15-end-to-end-journey.md) | One continuous walkthrough from nothing to a verified fix |
| [16. Practical use cases](16-use-cases.md) | Nightly audits, model changes, outages, user reports, cost control and more |
| [17. Reference: every value](17-reference.md) | Lookup tables for every status, badge, severity, event, limit and term |
| [18. Troubleshooting](18-troubleshooting.md) | Symptoms, causes and fixes |
| [19. The video walkthrough](19-video-walkthrough.md) | A six-minute narrated demo of the Documents and Isolation pages, with timestamps and captions |

## Conventions

- **Bold** is text you see on screen, exactly as written. \`Code font\` is something you type or a technical name.
- "Not available yet" is shown in the product for features that do not exist today. This guide says so wherever one appears, and never promises them.
- Example numbers are marked "for example". Numbers on screenshots come from the demo data.

## More documentation

This guide is for people who use the product. For the complete technical reference, see [GUIDE.md](../../GUIDE.md). For how to deploy and run it, see the [README](../../README.md) and the other files in [docs/](../).
`;export{e as default};
