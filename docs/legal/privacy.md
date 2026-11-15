# Privacy Policy

*Last updated: 15 November 2026*

This policy explains what the hosted RAGGuard service collects, why, who else handles it, how long we keep it and what you can ask us to do. RAGGuard is in beta. We wrote this policy to match what the software really does. If you find a place where it does not, tell us and we will fix the policy or the software.

**In short**

- We store your email address, a scrambled (hashed) form of your password, and the settings you need to run audits.
- When RAGGuard checks your systems, it keeps identifiers and fingerprints: document IDs, file names, hashes and counts. It does **not** store the text of your documents, your vectors or your users' questions.
- Your connection secrets are encrypted before they are stored and are never shown again.
- No advertising, no analytics, no tracking, and we never sell data. The only cookie keeps you signed in.
- To see, correct or delete your data, email **kishore.knaresh07@gmail.com**.

## 1. Who we are

RAGGuard ("RAGGuard", "we", "us") runs this service. RAGGuard is an early-stage product based in India and does not yet have a registered company name. For anything about your data, write to **[kishore.knaresh07@gmail.com](mailto:kishore.knaresh07@gmail.com)**. The same address reaches our Grievance Officer (see [section 10](#10-grievance-officer)).

## 2. What we collect

### Your account

- Your **email address**.
- Your **password**, stored only as a scrypt hash with a random salt. We cannot read it.
- When the account was created and when you last signed in.
- A workspace, named after the part of your email before the `@`.

We do not ask for your name, phone number or payment details.

### Signing in and security

- **The sign-in cookie** `ragi_session` keeps you signed in for up to 7 days. Scripts on the page cannot read it, and on the hosted service it is only sent over HTTPS. We store only a hash of its value.
- With each sign-in session we store your **IP address**, a short **description of your browser** (its user agent), and when the session was created and last used.
- To slow down password guessing, we count sign-up and sign-in attempts **per IP address** and per email address. In these counters the email address is stored only as part of a hash.

### Connection settings

To audit your RAG index, you give RAGGuard read access to your systems.

- **Stored encrypted:** S3 access keys, database connection strings (the manifest and pgvector), the Qdrant API key, the repair signing secret, the alert webhook address and the mail server password. They are encrypted before they are stored and are never shown again.
- **Stored as plain settings:** the bucket name, prefix, region and endpoint; the Qdrant address and collection names; schema, table and column names and field mappings; the mail server's host, port, user name and sender address; the repair worker's address; and your audit and alert preferences.
- **API keys you create:** we store a hash and the first few characters, so you can recognise a key. We do not store the key itself.

### What audits read and keep

During an audit RAGGuard reads your source storage, your vector index and, if you connect one, your manifest table. It **only reads**. It never writes to these systems.

It **keeps**, for each document and finding:

- document and tenant identifiers, file paths (for example `s3://bucket/folder/file.pdf`), content hashes, versions, sizes and chunk counts;
- vector point identifiers, chunk identifiers, and the names and versions of the parser, chunker and embedding model;
- the evidence for each finding (expected versus actual values), its status, and any note you type when you ignore one;
- the results of retrieval checks: ranks, scores and the identifiers of the top results;
- the history of audits, repair plans and notifications.

It **does not keep**:

- the text of your documents or chunks, or your vector values. Connection tests read a few sample records to check field names; their content is held in memory only and then discarded. In the "compute" hash mode, file contents are read to calculate a fingerprint and then thrown away;
- the text of your users' questions. If you send a query log through the API, a question is stored only as a hash, together with the identifiers of the documents it retrieved.

Retrieval checks search **your own index** with a vector that is already stored in it. RAGGuard does not use any AI or embedding service, so nothing is sent to one.

### Repairs and emails you send

- When you send a repair plan, we store the plan, the delivery results and the answer your worker sends back.
- When you email a repair plan, we store the recipients' addresses. The email itself goes out through **your own** mail server.

### When you contact us

If you email us, for example with **Book a free audit**, we receive your email address and what you write. These emails are handled in our Gmail account.

## 3. How we use it

- To create your account, sign you in and keep your workspace separate from everyone else's.
- To run the audits you start or schedule, show the results and prepare repair plans.
- To send what you set up: alerts to your webhook, repair requests to your worker, and audit alert emails.
- To protect the service: stop password guessing, look into abuse and fix errors.
- To answer your messages and give you the free audit you asked for.

We do not sell your data, use it for advertising, or use your content to train AI models.

## 4. Cookies and tracking

The only cookie is the sign-in cookie `ragi_session`. There are no analytics, advertising or tracking cookies, and the pages of the app load no scripts or fonts from other companies. The one exception is the developer API documentation (`/docs` and `/redoc`), which loads scripts and fonts from jsDelivr and Google Fonts.

## 5. Who else handles your data

We use these providers to run the service:

| Provider | What for | What they handle |
|---|---|---|
| Vercel | Hosting the website and the application | Every request, including your IP address |
| Supabase | Our database | Everything RAGGuard stores, as described in section 2 |
| Our email delivery provider, when email alerts are switched on for the service | Sending audit alert emails and test emails | Your email address and the content of the alert |
| Google (Gmail) | Our contact inbox | Emails you send us |

When you ask it to, RAGGuard also sends data to destinations **you** configure:

- your own storage, database and index, to read them;
- your alert webhook: an audit summary with up to 25 findings, by identifier;
- your repair worker: document identifiers, file paths, hashes and point identifiers;
- your mail server, and the recipients you type in.

We may disclose data when the law requires it, or to protect the service or other people from harm. If RAGGuard is ever sold or merged into another business, your data would move with it under this policy, and we would tell you first.

## 6. Where data is stored

Our providers may store and process data outside India. Data travels between you, our providers and your systems over encrypted connections.

## 7. How we protect it

- Connection secrets are encrypted with a key that exists only in the server's environment.
- Passwords, sign-in session tokens and API keys are stored only as hashes.
- RAGGuard only reads your systems, and it refuses addresses inside private networks.
- Every database query is limited to your workspace.
- The app is served over HTTPS with a strict content security policy.

No system is perfectly secure. If a breach affects your data, we will tell you, and the authorities, as the law requires.

## 8. How long we keep it

- **Your account, settings and audit history:** as long as your account exists. Audit history does not yet expire on its own.
- **Notifications:** the newest 200 for each workspace.
- **Sign-in sessions:** until you sign out or change your password, or until they expire after 7 days. Expired sessions are then removed automatically.
- **Sign-in attempt counters,** which can include your IP address: kept to protect the service. They are not yet removed automatically; we delete them when you ask.
- **When we delete your account,** we delete your user, your workspace, saved connections, API keys, sessions and all audit, issue, repair and notification history. Copies may stay in our database provider's backups for a limited time.
- **Emails you send us:** as long as we need them to answer you.

## 9. Your rights

You can ask us to:

- give you a summary or a copy of your data;
- correct it;
- delete your account and your data. There is no delete button in the app yet, so email us;
- stop processing it, which withdraws your consent. We will then delete your account;
- let someone you nominate exercise these rights if you die or become unable to, as India's Digital Personal Data Protection Act, 2023 allows.

If the GDPR or a similar law applies to you, you also have the rights to object, to restrict processing and to data portability, and to complain to your data protection authority.

We reply within 30 days. If you are not satisfied with our answer, you can complain to the Data Protection Board of India.

## 10. Grievance Officer

For questions or complaints about how we handle personal data, write to our Grievance Officer at **[kishore.knaresh07@gmail.com](mailto:kishore.knaresh07@gmail.com)**. We aim to reply within 7 days and to resolve complaints within 30 days.

## 11. Data in your systems about other people

Your systems may hold identifiers or file names that relate to other people, for example your own customers. You decide what RAGGuard can read. We process it only to provide the service to you and on your instructions. You are responsible for having the right to let RAGGuard read it.

## 12. Children

RAGGuard is a tool for businesses and professionals. It is not meant for anyone under 18, and we do not knowingly collect their data.

## 13. Changes to this policy

We will post any change on this page and update the date at the top. If a change matters, we will tell you before it applies.

## 14. Contact

**[kishore.knaresh07@gmail.com](mailto:kishore.knaresh07@gmail.com)**

See also our [Terms of Service](/terms).
