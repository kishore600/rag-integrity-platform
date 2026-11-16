import{r as a,j as t,L as r}from"./index-BhgQ-ZFD.js";import{M as i,r as d,a as u}from"./prose-DGdJrW0p.js";const c=`# Privacy Policy

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
- A workspace, named after the part of your email before the \`@\`.

We do not ask for your name, phone number or payment details.

### Signing in and security

- **The sign-in cookie** \`ragi_session\` keeps you signed in for up to 7 days. Scripts on the page cannot read it, and on the hosted service it is only sent over HTTPS. We store only a hash of its value.
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

- document and tenant identifiers, file paths (for example \`s3://bucket/folder/file.pdf\`), content hashes, versions, sizes and chunk counts;
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
- To see how the service is used. Our admin dashboard shows each account's email address, when it signed up and was last active, which kinds of systems it has saved (not their details), and a summary of its audits. It never shows passwords, keys, connection details or IP addresses.
- To answer your messages and give you the free audit you asked for.

We do not sell your data, use it for advertising, or use your content to train AI models.

## 4. Cookies and tracking

The only cookie is the sign-in cookie \`ragi_session\`. There are no analytics, advertising or tracking cookies, and the pages of the app load no scripts or fonts from other companies. The one exception is the developer API documentation (\`/docs\` and \`/redoc\`), which loads scripts and fonts from jsDelivr and Google Fonts.

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
`,h=`# Terms of Service

*Last updated: 15 November 2026*

These terms are an agreement between you and RAGGuard ("RAGGuard", "we", "us") for using the hosted RAGGuard service. By creating an account or using the service, you accept them. If you use RAGGuard for a company or another organisation, you accept them for it and confirm that you are allowed to.

**In short** (the full terms below are what count)

- RAGGuard is in beta, and it is free while it is in beta.
- It reads your systems and never writes to them. Repairs are carried out by your own worker.
- Check its findings before you act on them. We work hard to get them right, but we do not promise they are free of errors.
- You can stop at any time and ask us to delete your data.

## 1. The service

RAGGuard compares your source documents, your vector index and, if you connect one, your processing manifest, and reports where they disagree. It can prepare repair plans and send them to a worker you run. We may change, add or remove features.

The source code of RAGGuard is published under the MIT License. These terms cover the hosted service only, not your use of the code.

## 2. Beta and price

The service is in beta and free while it is in beta. We may introduce paid plans later. We will tell you before any charge applies, and you will never be charged unless you choose a paid plan.

We may end the beta or the service. If we do, we will tell you in advance where we can, so you can export your results.

## 3. Your account

- You must be at least 18 and give an email address that you can read.
- Keep your password and API keys secret. You are responsible for what happens in your account.
- Tell us straight away if you think someone else got into your account.

## 4. Your systems and your data

- You must own the systems you connect, or have permission to let RAGGuard read them.
- Give RAGGuard read-only credentials where you can. RAGGuard is designed only to list, read and query your systems.
- Your data stays yours. You let us read it, and store the parts described in our [Privacy Policy](/privacy), only to provide the service to you.
- If your systems hold personal data, you are responsible for having a lawful basis to let RAGGuard process it.
- **Repairs.** RAGGuard sends signed repair requests to the worker address you set. Your worker decides what to change in your systems, and you are responsible for it. If you set clean-up to run automatically, removal requests are sent without a separate approval.

## 5. Acceptable use

Do not:

- connect systems you are not allowed to access, or use RAGGuard to probe or attack anyone's systems;
- try to get into other workspaces, get around rate limits or security controls, or overload the service;
- use the service for anything illegal;
- resell access to the hosted service without our written agreement.

We may suspend an account that breaks these rules or puts the service or other people at risk.

## 6. Free audits

If you book a free audit, we help you connect RAGGuard and go through the results with you. We look only at what you show us, keep it confidential, and use it only to help you.

## 7. Feedback

If you send us ideas or feedback, we may use them freely, without owing you anything.

## 8. Our name and service

We own the RAGGuard name, logo, website and hosted service. The MIT License gives you rights to the source code. It does not give you rights to our name or logo.

## 9. No warranty

The service is provided "as is" and "as available". Findings, scores, cost estimates and repair plans can be incomplete or wrong. Check them before you rely on them or change your systems. To the extent the law allows, we disclaim all warranties, including fitness for a particular purpose and uninterrupted or error-free service.

## 10. Limitation of liability

To the extent the law allows:

- we are not liable for indirect or consequential losses, lost profits, lost data or business interruption;
- our total liability for all claims is limited to the greater of the amount you paid us in the 12 months before the claim and INR 5,000.

Nothing in these terms limits any liability that the law does not allow to be limited.

## 11. Indemnity

If someone makes a claim against us because you connected systems you were not allowed to, or because you broke these terms, you will cover our reasonable costs of that claim.

## 12. Ending

You can stop using RAGGuard at any time and ask us to delete your account at [kishore.knaresh07@gmail.com](mailto:kishore.knaresh07@gmail.com). We may suspend or close an account that breaks these terms, telling you first where we can. Sections 9 to 13 still apply after this agreement ends.

## 13. Law and disputes

These terms are governed by the laws of India. Please write to us first: we will try to solve the problem with you. If we cannot, the courts of India have exclusive jurisdiction.

## 14. Changes to these terms

We may update these terms. We will post the new version on this page with a new date, and tell you before important changes apply. If you keep using RAGGuard after that, the new terms apply.

## 15. Contact

**[kishore.knaresh07@gmail.com](mailto:kishore.knaresh07@gmail.com)**

See also our [Privacy Policy](/privacy).
`,l={privacy:{title:"Privacy Policy",text:c},terms:{title:"Terms of Service",text:h}},y={a({href:e,children:n}){return e!=null&&e.startsWith("/")?t.jsx(r,{to:e,children:n}):t.jsx("a",{href:e,children:n})},table({children:e}){return t.jsx("div",{className:"help-table",children:t.jsx("table",{children:e})})}};function w({doc:e}){const{title:n,text:o}=l[e];return a.useEffect(()=>{const s=document.title;return document.title=`${n} · RAGGuard`,()=>{document.title=s}},[n]),t.jsx("article",{className:"help-prose mx-auto py-4",children:t.jsx(i,{remarkPlugins:[u],rehypePlugins:[d],components:y,children:o})})}export{w as default};
