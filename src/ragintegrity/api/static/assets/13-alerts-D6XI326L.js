const e=`# Alerts\r
\r
The Alerts page tells RAGGuard where to send a message when an audit finds something new, and shows what happened to every message. You give it one **alert webhook** (a web address that accepts messages, such as a Slack incoming webhook) and a **minimum severity**. After each finished audit RAGGuard sends one message listing the issues that are new, that came back, or that got worse and that are at or above that severity. This chapter explains the card, both fields, how to create a Slack webhook, exactly when a message is and is not sent, what the message contains, and how to read the **Recent deliveries** table.\r
\r
**On this page**\r
\r
- [Purpose, who needs it, how to open it](#purpose-who-needs-it-how-to-open-it)\r
- [The page at a glance](#the-page-at-a-glance)\r
- [The Alert webhook card](#the-alert-webhook-card)\r
- [Set up a Slack incoming webhook](#set-up-a-slack-incoming-webhook)\r
- [How alerts work](#how-alerts-work)\r
- [Recent deliveries](#recent-deliveries)\r
- [More ways to be notified: not available yet](#more-ways-to-be-notified-not-available-yet)\r
- [Single-user mode](#single-user-mode)\r
- [States you may see](#states-you-may-see)\r
- [Tips and common mistakes](#tips-and-common-mistakes)\r
- [Related chapters](#related-chapters)\r
\r
---\r
\r
## Purpose, who needs it, how to open it\r
\r
**Purpose.** You should not have to open RAGGuard every day to learn that something broke. With an alert webhook, the news comes to the place your team already watches.\r
\r
**Who needs it.** Anyone who wants to be told about new problems, usually the owner of the pipeline or an on-call channel.\r
\r
**How to open it.** Choose **Alerts** in the left menu. The page header reads "Get told when an audit finds something new."\r
\r
---\r
\r
## The page at a glance\r
\r
![The Alerts page: the Alert webhook card with its two fields and the Check settings and Save buttons](images/alerts-config.png)\r
\r
*The Alert webhook card on the left, with Webhook URL and Minimum severity.*\r
\r
From top to bottom:\r
\r
1. A two-column area on a wide screen (stacked on a narrow one): the **Alert webhook** card on the left and the **How alerts work** card on the right.\r
2. **Recent deliveries**: a table with a **Show** filter.\r
3. **More ways to be notified**: three dashed cards marked **Not available yet**.\r
\r
---\r
\r
## The Alert webhook card\r
\r
The header reads "Alert webhook", with the line "A Slack-compatible incoming webhook. It is saved encrypted and never shown again." and a badge: **Configured** (green) or **Not configured** (grey). **Configured** means you have saved at least one value in this group. It does not prove the webhook works, and saving only **Minimum severity** also counts as configured.\r
\r
The form is on the card itself (there is no dialog). Its parts, top to bottom:\r
\r
| Element | What it does |\r
|---|---|\r
| **Webhook URL** | The address messages are posted to (secret) |\r
| **Minimum severity** | The lowest severity that triggers a message |\r
| **Saved line** | "Not saved yet." or "Saved 3 h ago." (hover for the exact time). No test history is kept for this group |\r
| **Note** | "Checks that the values are valid and the address is allowed. It does not send a message." |\r
| **"No unsaved changes."** | Appears when the form matches what is saved. It disappears as soon as you change something |\r
| **Check settings** | Validates the values without sending anything (see below) |\r
| **Save** | Stores your changes. Greyed out until something changed. A message "Alerts saved" appears when it works |\r
\r
The shared form controls (required markers, the secret box and **Remove saved value**, inline errors) work as described in [Connect your data sources](04-data-sources.md#the-configure-dialog-every-control).\r
\r
### The fields\r
\r
| Label | Required | Secret | Default | Example |\r
|---|---|---|---|---|\r
| **Webhook URL** | No | Yes | None | \`https://hooks.slack.com/services/T0000/B0000/XXXX\` |\r
| **Minimum severity** | No | No | \`high\` (shown as **Use server default**) | \`high\` |\r
\r
**Webhook URL** (secret)\r
- *What it is:* the address of a Slack-compatible incoming webhook. RAGGuard sends it one JSON message per audit (when there is something to say). It is treated as a secret because the address itself acts as the password: anyone who has it can post to your channel. It is stored encrypted and never shown again.\r
- *What it changes:* with an address, alerts are on. With none, alerts are off, and each audit records "No alert webhook was configured." To switch alerts off later, press **Remove saved value** under the field, then **Save**.\r
- *Rules:* it must start with \`https://\` or \`http://\`, must not contain a user name or password, and must point to a public host (see [public addresses](04-data-sources.md#hosted-mode-accepts-public-addresses-only)). Because the field is secret, the browser only checks that it is not empty; the server checks the format when you save or press **Check settings**, and a rejection appears in a red box starting with "Webhook URL: ".\r
- *Common mistakes:* pasting a Slack channel link instead of a webhook address; an address from a deleted or revoked webhook (deliveries then fail); a private address.\r
\r
**Minimum severity** (drop-down: **Use server default**, \`critical\`, \`high\`, \`medium\`, \`low\`)\r
- *What it is:* the lowest severity that is worth a message. The order, highest first, is critical, high, medium, low.\r
- *What it changes:* an issue only triggers a message if its severity is at or above this level. \`critical\` means only the most serious. \`low\` means almost everything. The default, \`high\`, covers critical and high. If you leave the drop-down on **Use server default**, \`high\` applies.\r
- *Common mistakes:* choosing \`low\` and being flooded by minor bookkeeping issues; choosing \`critical\` and missing high-severity problems such as missing or stale vectors.\r
\r
### Check settings\r
\r
**Check settings** answers one question: "are these values acceptable?" It checks the format, and that the address is allowed. It does **not** post a message, so it cannot tell you whether Slack will accept the webhook. A pass shows a green **Test passed** panel with the line "Settings: valid". If you have saved nothing and typed nothing, you see "Nothing to check yet. Fill in a field first." A rejected value (for example a private address) shows a red message instead, for example "Webhook URL: localhost is not a public host name."\r
\r
To prove that the whole chain works, post to your webhook yourself with the command in [Set up a Slack incoming webhook](#set-up-a-slack-incoming-webhook), or lower the minimum severity temporarily and run an audit that finds something new.\r
\r
### What Save does\r
\r
Only the fields you changed are stored. The webhook address is encrypted. A message "Alerts saved" appears, and the card's badge and saved line update. The new settings are used by the **next** audit.\r
\r
---\r
\r
## Set up a Slack incoming webhook\r
\r
These steps use Slack's own screens, which may be named slightly differently over time. Slack's documentation for "incoming webhooks" is the authority.\r
\r
1. In Slack, open the apps page (api.slack.com/apps) and create a new app **from scratch**. Give it a name such as "RAGGuard alerts" and choose your workspace.\r
2. In the app's settings, open **Incoming Webhooks** and turn the feature **on**.\r
3. Choose **Add New Webhook to Workspace**, pick the channel that should receive the alerts and allow it.\r
4. Copy the **Webhook URL**. It starts with \`https://hooks.slack.com/services/\`.\r
5. In RAGGuard, open **Alerts**, paste it into **Webhook URL**, choose a **Minimum severity**, press **Check settings**, then **Save**.\r
6. Optional: confirm that Slack accepts the address by posting a test message from a terminal (replace the address with yours):\r
\r
\`\`\`bash\r
curl -X POST -H "Content-Type: application/json" \\\r
  -d '{"text": "Test message from my terminal"}' \\\r
  "https://hooks.slack.com/services/T0000/B0000/XXXX"\r
\`\`\`\r
\r
If the message appears in the channel, the webhook works.\r
\r
**Other tools.** Any tool that accepts Slack-style incoming webhooks (a POST with JSON that has a \`text\` field) can receive RAGGuard's alerts. Check that tool's documentation for how to create the address. RAGGuard also sends a few extra fields next to \`text\`; a tool that is strict about unknown fields may not accept them.\r
\r
---\r
\r
## How alerts work\r
\r
![The How alerts work card with its five points and the request body by shape](images/alerts-how.png)\r
\r
*The How alerts work card: five points and the shape of the request body.*\r
\r
The card lists five points. Here they are in plain words, with the details behind each.\r
\r
### 1. When it runs\r
\r
After **every audit that finishes**, RAGGuard compares the issues that audit found with the issues it already knew about. That includes full audits, scoped audits (one tenant or a few documents) and the verification audits that run after a repair. A scoped audit can only report on its own scope. An audit that fails does not alert.\r
\r
### 2. What triggers an alert\r
\r
Only issues that are **new**, **reopened** or **escalated**, and only if their severity is **at or above the minimum severity**. An issue that is still open and unchanged never alerts again.\r
\r
| Situation | Alert? |\r
|---|---|\r
| An audit finds a problem RAGGuard has not recorded before, at or above the minimum severity | **Yes** (new) |\r
| A problem that was marked resolved is found again | **Yes** (reopened) |\r
| An open issue's severity goes up (for example medium to high) and the new severity is at or above the minimum | **Yes** (escalated) |\r
| An open issue stays open at the same severity | No |\r
| An open issue's severity goes down | No |\r
| An issue you ignored appears again | No |\r
| An issue is below the minimum severity | No |\r
\r
"New" means new to RAGGuard's record, not new to your webhook. If earlier audits already recorded an issue, adding a webhook later does not make that issue alert. If you save the webhook **before** the first audit, that first audit treats everything it finds as new, so expect one larger message.\r
\r
### 3. What is sent\r
\r
One JSON request to your webhook. The \`text\` field is a readable summary for Slack:\r
\r
\`\`\`\r
*RAG Integrity*: 3 new issue(s) at or above \`high\` (health 87%)\r
• [CRITICAL] Document has no embeddings in the index (pipeline claims success) - \`acme/policies/leave.pdf\`\r
• [HIGH] Embeddings are from an older version of the document - \`acme/runbooks/restart.md\`\r
• [HIGH] ...\r
\`\`\`\r
\r
(The numbers, titles and document names here are only an example, and the product separates the title from the document with a long dash. The first line says how many issues, the minimum severity and the health score of that audit. After it come up to 10 issues, most severe first, each as the severity in capitals, the title and \`tenant/document\`. If there are more than 10 a last line says "and N more". The summary still uses the name RAG Integrity, the product's earlier name.)\r
\r
The same request carries more structured data, for tools that read it:\r
\r
\`\`\`json\r
{\r
  "text": "<short summary for Slack>",\r
  "run_id": "<audit run id>",\r
  "summary": { "new_issues": 3, "health_score": 87 },\r
  "issues": [\r
    { "id": "...", "type": "...", "severity": "...", "tenant_id": "...", "document_id": "...", "title": "..." }\r
  ]\r
}\r
\`\`\`\r
\r
| Field | Meaning |\r
|---|---|\r
| \`text\` | The readable summary described above |\r
| \`run_id\` | The audit run that found these issues. Open it in [Audit history](11-audit-history.md) |\r
| \`summary.new_issues\` | How many issues qualified (not capped) |\r
| \`summary.health_score\` | The health score of that audit, as a percentage |\r
| \`issues\` | Up to 25 qualifying issues. Each has \`id\`, \`type\` (the issue type, for example \`missing_embedding\`), \`severity\`, \`tenant_id\`, \`document_id\` and \`title\` |\r
\r
### 4. If delivery fails\r
\r
RAGGuard makes **one attempt** and waits up to **10 seconds**. It does not retry. A failed delivery never fails the audit: the error is stored on the run and listed under **Recent deliveries**, and the audit and its results are unaffected. Fix the webhook and the next audit that has something new will deliver.\r
\r
### 5. When nothing is sent\r
\r
If no webhook is saved, or no issue qualifies, nothing is sent, and the reason is recorded on the run (it shows in the **Detail** column below).\r
\r
---\r
\r
## Recent deliveries\r
\r
![The Recent deliveries table with a Show filter, the Audit run, Outcome, Issues included and Detail columns](images/alerts-deliveries.png)\r
\r
*Recent deliveries: what happened to the alert after each of the latest audits.*\r
\r
This card shows "What happened to the alert after each of the latest audits." It reads the 50 most recent audits and lists the ones that recorded an alert result. An audit that failed has none, so it is not listed.\r
\r
### The Show filter\r
\r
One drop-down labelled **Show**:\r
\r
| Choice | Lists |\r
|---|---|\r
| **Delivered or failed** (the default) | Audits where RAGGuard tried to send something and either succeeded or failed |\r
| **Every audit** | Every audit with an alert result, including those where nothing was sent. Use it to find out why nothing arrived |\r
| **Delivered** | Only successful deliveries |\r
| **Failed** | Only failed deliveries |\r
| **Not sent** | Audits where nothing was attempted |\r
\r
When the filter is not the default, a **Clear filters** button appears. The choice is kept in the page address (as \`outcome\`), so you can bookmark or share a view.\r
\r
### The columns\r
\r
| Column | What it shows | How to read it |\r
|---|---|---|\r
| **Audit run** | The date and time the audit started, as a link, with a line under it such as "Full audit, 5 min ago" (the kind is Full, Scoped or Verify) | Click the date to open that run in [Audit history](11-audit-history.md). Sortable. The table starts with the newest first |\r
| **Outcome** | A badge: **Delivered** (green), **Failed** (red) or **Not sent** (grey) | See below. Sortable |\r
| **Issues included** | The number of issues in the message, or "None" | How many issues the alert listed. Sortable |\r
| **Detail** | A sentence | The reason or the error. Red for a failure |\r
\r
### Outcomes and the text in Detail\r
\r
| Outcome | Meaning | Text in **Detail** |\r
|---|---|---|\r
| **Delivered** | The webhook accepted the message | "Sent to the alert webhook." |\r
| **Failed** | RAGGuard tried and the webhook did not accept it, or could not be reached, or took longer than 10 seconds | The error: its type, then the first part of its message with every web address removed, for example \`HTTPStatusError: Client error '404 Not Found' for url '<webhook>'\`. See the note below |\r
| **Not sent** | Nothing was attempted | "No alert webhook was configured." (no address was saved), or "No new issues at or above the minimum severity." (the audit found nothing that qualifies), or the recorded reason, or "Nothing to send." |\r
\r
**Common reasons for a failure.** A revoked or deleted Slack webhook (the webhook answers with an error status), a mistyped address (not found), a network problem, or a slow endpoint (more than 10 seconds).\r
\r
**The address is never shown.** The webhook address is a secret, and the error a web library produces quotes it. RAGGuard replaces it before the error is stored, shown or logged: the address you saved appears as \`<webhook>\`, and any other web address in the message (including where a redirect pointed, even a relative one) appears as \`<url>\`. The error type and the status code stay, so you can still tell a 404 (deleted or mistyped address) from a 500 or a refused connection. The same applies to the error of a failed repair delivery. Audits recorded by an earlier version of RAGGuard could hold the address in this column; RAGGuard now removes any web address from that text whenever it reads a run, so old rows are cleaned too. If you ever pasted such a run into a ticket or a chat, rotate the webhook.\r
\r
### Paging and counts\r
\r
Under the table: "Showing 1 to 10 of N" and the note "From the latest 50 audits.", a **Rows** drop-down (10, 25, 50 or 100; it starts at 10) and **Previous page** and **Next page** arrows with "Page 1 of N".\r
\r
### Empty states\r
\r
| Where | What you see |\r
|---|---|\r
| No audit has an alert result at all | "No alerts have been sent yet": "After every audit RAGGuard checks for new issues. Once an alert webhook is saved and an audit finds something new, each delivery is listed here." |\r
| Audits exist, but none attempted an alert, and the filter is the default | "No alerts have been sent yet": "Audits have run, but none produced an alert. Choose Every audit to see why." |\r
| You chose another filter and nothing matches | "No audits match this filter": "Choose another outcome to see more." |\r
| The audits could not be loaded | "We couldn't load this" with a **Try again** button |\r
\r
While loading, grey placeholder rows are shown.\r
\r
---\r
\r
## More ways to be notified: not available yet\r
\r
Three dashed cards at the bottom are each marked **Not available yet**. Nothing here can be configured.\r
\r
| Card | What it says |\r
|---|---|\r
| **Email alerts** | "Alerts go to a webhook only." |\r
| **Per-issue-type rules** | "The only filter is the minimum severity." |\r
| **Digest and quiet hours** | "An alert is sent right after each audit that finds something new." |\r
\r
---\r
\r
## Single-user mode\r
\r
On a server that runs for one team without accounts (live or demo mode) the card is read-only. It shows "Alert webhook" with the line "A Slack-compatible incoming webhook." and the note "Configured by the server's environment variables (RAGI_*)": "Set RAGI_ALERT_WEBHOOK_URL to turn alerts on, and RAGI_ALERT_MIN_SEVERITY to choose the minimum severity." **How alerts work**, **Recent deliveries** and the **Not available yet** cards work the same way.\r
\r
---\r
\r
## States you may see\r
\r
| State | What you see | What to do |\r
|---|---|---|\r
| **Loading** | A tall grey placeholder where the card goes, and grey rows in the table | Wait a moment |\r
| **Not configured** | A grey **Not configured** badge, and every audit records "No alert webhook was configured." | Paste a webhook address and **Save** |\r
| **Configured** | A green badge | Check **Recent deliveries** after the next audit |\r
| **A rejected value** | A red box under the form beginning with "Webhook URL: " | Fix the address |\r
| **Cannot load** | "We couldn't load this" and **Try again** | Press **Try again** |\r
\r
---\r
\r
## Tips and common mistakes\r
\r
- **Start with \`high\`.** It keeps the channel quiet enough that people read it. Lower it only if you want to see everything.\r
- **A steady state is silent.** If your channel is quiet, either nothing new happened or nothing reached the minimum severity. Choose **Every audit** under **Show** to see which.\r
- **Check settings does not send anything.** To test delivery, use the \`curl\` command above.\r
- **The webhook address is a secret.** If it leaks, delete the webhook in Slack, create a new one and replace it here.\r
- **Hosted RAGGuard does not run audits on a timer.** To get alerts every morning, schedule a call to the API with an API key (see [Integrations](12-integrations.md#use-a-key)).\r
- **To switch alerts off,** use **Remove saved value** under **Webhook URL**, then **Save**.\r
\r
---\r
\r
## Related chapters\r
\r
- [Integrations](12-integrations.md): API keys for scheduling audits, and the repair webhook\r
- [Integrity issues](07-integrity-issues.md): what the issue types and severities mean\r
- [Audit history](11-audit-history.md): open the run that produced an alert\r
- [Connect your data sources](04-data-sources.md): the shared form controls and the public-address rule\r
- [Settings](14-settings.md)\r
- [Troubleshooting](18-troubleshooting.md)\r
`;export{e as default};
