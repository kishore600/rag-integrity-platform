# The video walkthrough

A five-minute narrated video shows two parts of RAGGuard in action: the **Documents** page, where you inspect every document and its index, and the **Isolation** page, which checks that one customer's content can never reach another. It uses the real product on demo data, so you see exactly what you will see on your own workspace. This chapter lists what is in the video, with timestamps, and points to the written chapter that explains each part in full.

**On this page**

- [Where the video is](#where-the-video-is)
- [What is in it](#what-is-in-it)
- [What the video does not cover](#what-the-video-does-not-cover)
- [Follow along on your own workspace](#follow-along-on-your-own-workspace)
- [Captions and sound](#captions-and-sound)
- [Related chapters](#related-chapters)

---

## Where the video is

| File | What it is |
|---|---|
| [`video/RAGGuard-walkthrough.mp4`](video/RAGGuard-walkthrough.mp4) | The video: 4 minutes 59 seconds, 1280 by 720, with narration. |
| [`video/RAGGuard-walkthrough.vtt`](video/RAGGuard-walkthrough.vtt) | The captions: every spoken sentence with its time, as a standard WebVTT file. Most video players load it next to the video, and you can also read it as plain text. |

> **About the data.** The video was recorded on a demo workspace connected to a synthetic knowledge base: three tenants (acme, globex and initech), a few hundred documents, and about 50 deliberate faults. Your numbers, names and documents will differ. The layout, the labels and the meaning of every value are the same.

---

## What is in it

| Time | Part | What you see and hear | Read more |
|---|---|---|---|
| 0:00 | **Introduction** | The title card, then a workspace that is already connected to its three systems and has finished its first audit. The **Health score** and **Open issues** cards. | [Overview](05-overview.md), [Connect your data sources](04-data-sources.md) |
| 0:31 | **The Documents page** | The five status cards and how a click filters the table. Every column: embedding status, source and indexed versions with the warning, chunks, issues. Search. Opening a document: the **Overview** tab (where it lives, hashes, versions, whether it is present in the source, the manifest and the index), the **Chunks** tab with **Inspect live**, and the **Issues** tab with **Re-audit document**. | [Documents](10-documents.md) |
| 2:06 | **The Isolation page** | The status banner and its one-sentence answer. The six cards, including **Confirmed reachable by a search** and how many leaks were searched. The five checks. The **Tenants** table and **Open findings (live)**. The **Run isolation drill** dialog: the DRILL badge, the pretend relabel, what the audit would raise, the exact alert it would post, and the read-only confirmation. **Download evidence report (.md)**. | [Isolation](20-isolation.md) |
| 3:53 | **When the check is limited** | Settings, then the **Policy** tab: the switch **Only audit documents found in the source (S3)**. After an audit the Isolation page says **This check is limited**, explains why in plain words, shows **Not checked** on the cards instead of a false all-clear, and keeps the drill available. | [Isolation](20-isolation.md), [Settings](14-settings.md) |
| 4:47 | **Summary** | A closing card that points to the written chapters. | [Contents](README.md) |

Yellow numbered boxes on the screen mark the part being talked about, and the short label next to each one repeats the key point, so you can pause and read.

---

## What the video does not cover

Five minutes is enough for two pages, not for all ten. Everything else is in the written guide, in the order you would meet it:

| To learn about | Read |
|---|---|
| Signing up, the sidebar, search, the bell, the account menu | [Sign in and find your way around](03-interface-and-sign-in.md) |
| Connecting Amazon S3, the PostgreSQL manifest and Qdrant, with every field | [Connect your data sources](04-data-sources.md) |
| The health score, the charts and the lists | [Overview](05-overview.md) |
| The three-way comparison, scoped audits, exports | [Reconciliation](06-reconciliation.md) |
| Reading and ignoring issues, all 11 issue types | [Integrity issues](07-integrity-issues.md) |
| Repairing: plans, the worker, verification, cleanup | [Repair plans](08-repair-plans.md) |
| What-if analysis before a change | [Impact analysis](09-impact-analysis.md) |
| Every audit and every event | [Audit history](11-audit-history.md) |
| The repair webhook and API keys | [Integrations](12-integrations.md) |
| Webhook alerts | [Alerts](13-alerts.md) |
| Pipeline, policy, password, security | [Settings](14-settings.md) |
| One continuous path from sign-up to a verified fix | [End-to-end journey](15-end-to-end-journey.md) |

---

## Follow along on your own workspace

1. [Connect your three systems](04-data-sources.md) and run an audit with **Run audit** in the top bar.
2. Open **Documents** in the sidebar. Click the **Needs attention** card, open the first row, and press **Inspect live** on the **Chunks** tab. Compare what you see with the video.
3. Open **Isolation**. Read the banner, then press **Run isolation drill**. The drill is read-only, so it is safe on any workspace, and it works even when the page is limited or when you have only one tenant.
4. Press **Download evidence report (.md)** and open the file.
5. To see the limited state yourself, turn on **Only audit documents found in the source (S3)** under **Settings, Policy**, run an audit, and open **Isolation**. Turn the switch off again and run a full audit to get the real result back.

---

## Captions and sound

- The narration is a synthetic voice. If you cannot play sound, open the captions file: it has every sentence that is spoken, in order.
- All the information in the video is also on screen as text, in the callout labels, and in the written chapters linked above.
- The screenshots in this guide were captured from the same demo workspace, so they match the video.

---

## Related chapters

- [Documents](10-documents.md)
- [Isolation](20-isolation.md)
- [End-to-end journey](15-end-to-end-journey.md)
- [Contents](README.md)
