# The background worker

A web request has a time limit. On the hosted service an audit gets 270 seconds. An index of millions of vectors takes far longer, so such an
audit stops again and again: it is *resumable* (GUIDE 3.12: slices, checkpoints, `partial`, **Resume**), but a person has to press Resume after
every stop.

The worker is what presses it for you. It adds no second way of auditing: every stretch is the ordinary sliced audit, so the result is the
same as one that was never interrupted.

## How it works, end to end

```
 you click "Run audit"            (or a nightly job calls POST /api/audits)
        |   RAGI_AUDIT_QUEUE=true: the request only queues the audit and answers {"status": "queued"}
        v
 QUEUED           a run waiting in the ledger (nothing runs yet)
        |
        v   a worker picks it up:  ragi worker   or   POST /api/worker/step
 RUNNING          the ordinary sliced audit, for as long as the worker has (a step: the host's limit, a worker: until done)
        |            every finished slice is recorded in the ledger at once (the checkpoint)
        |            the worker reports in every 20 s (its heartbeat)
        |
        +-- finished all slices ------------------------------------> COMPLETED
        |
        +-- time ran out / the index could not be reached ----------> PARTIAL, and the next stretch is QUEUED (resumes at the checkpoint)
        |
        +-- the worker died (no heartbeat for 180 s) ---------------> taken back: PARTIAL from its last checkpoint, next stretch QUEUED
```

What a person sees (`GET /api/overview` -> `audit_progress`, shown on the Overview and Reconciliation pages):

| `state` | Meaning | Message |
|---|---|---|
| `working` | a worker is on it | "Checking 12,400 of 98,000 documents (12.7%)" |
| `queued` | paused at a checkpoint, or just queued | "Paused at a checkpoint: ... Waiting for the next step." |
| `waiting_for_worker` | nobody picked it up for 90 seconds | the dashboard runs it from its own page (section C); the message also says how to start a worker |
| `silent` | the worker has not reported for 90 seconds | after 180 seconds the audit is taken back |

## Choosing who carries the audit on

### A. `ragi worker` on a server that stays up

```bash
ragi worker                       # waits for queued audits, works as long as it takes
ragi worker --once --budget 240   # one stretch, then exit (for a cron job)
```

The same Docker image runs it: `docker run ... ghcr.io/<owner>/rag-integrity-platform ragi worker`. In `app` mode one worker serves every
workspace; it needs the same `RAGI_DATABASE_URL` and `RAGI_SECRET_KEY` as the web app (it decrypts each workspace's connection secrets), so
keep it private. In `live` mode it uses the connection settings from its environment.

### B. `POST /api/worker/step` where no process can stay up (Vercel)

One call does one stretch of work (up to the host's time limit, 270 seconds on Vercel) and answers:

```json
{"run_id": "...", "status": "partial", "documents_done": 41200, "documents_total": 98000, "percent": 42.0, "next": "<queued run id>"}
```

Call it again and again until it answers `{"status": "idle"}`. It takes a session or an API key (Integrations page). Any scheduler can drive it;
for example a GitHub Actions job:

```yaml
name: finish-audit
on:
  schedule: [{cron: "*/5 * * * *"}]     # every five minutes; a step that finds nothing to do answers "idle" at once
jobs:
  step:
    runs-on: ubuntu-latest
    steps:
      - run: |
          for i in 1 2 3; do
            out=$(curl -sS -X POST "$RAGI_URL/api/worker/step" -H "Authorization: Bearer $RAGI_KEY")
            echo "$out"; echo "$out" | grep -q '"idle"' && break
          done
    env: {RAGI_URL: "${{ secrets.RAGI_URL }}", RAGI_KEY: "${{ secrets.RAGI_KEY }}"}
```

### C. The dashboard itself, when nobody else does (nothing to set up)

An audit must never wait for nobody. When an audit has waited 90 seconds with no worker (`waiting_for_worker`), the dashboard does the
worker's job from the page the person has open: it calls `POST /api/worker/step` (the call of section B) and, when a stretch stops part-way
and queues the next one, calls it again, until the audit is over. A real worker and the dashboard never clash: the first to claim the audit
gets it, and the other call answers `idle`. If the call fails it waits 30 seconds and tries again, and after three failures in a row it says
so and stops.

It works only **while the page stays open**, and each stretch has the host's time limit, so it finishes a big index only when the audit is
resumable (see below). For a very large index, or for audits nobody watches, run section A.

## Requirements and limits

| | |
|---|---|
| Resumable audit | *Only audit documents found in the source (S3)* is on (GUIDE 3.12). An audit that reads the whole index is one pass: a worker runs it in one go with no time limit, but a crash starts it again. |
| Qdrant | Every slice filters by document id. Without a keyword payload index on that field a filtered scroll costs about one pass over the collection (measured, GUIDE 3.12): ask whoever runs your Qdrant to create one. |
| An index too big for the host | A whole-index read that ran out of the host's time limit fails the same way every time, so the audit is **paused** (Run audit is switched off, `POST /api/audits` answers `409`) and the alert says what to change (GUIDE 3.12). A worker on a server has no limit: **Run it anyway** (`force: true`) queues the audit for it. |
| Queue mode | `RAGI_AUDIT_QUEUE=true`. Only whole-corpus audits are queued; a tenant or a few documents is small and runs in the request. Without it, **Run audit** works as before and only a person (or a call with `resume: true`) continues a partial audit. |
| Each stretch | Starts by reading the source and the manifest again, then the next slice after the checkpoint. |
| A worker that keeps failing | A stretch that made no progress three times in a row (the index stays unreachable) is not queued again: the audit stays `partial` and `resumable_audit` shows it, for a person to resume. |
| Documents that change while it runs | Each slice is judged against the files and rows as they are when that slice is read. The grace period (`RAGI_GRACE_MINUTES`) and the next audit settle a document that was being ingested. |
| No new database tables | The queue and the heartbeat live in the existing `audit_runs.stats` column (a queued audit is a run with status `queued`). |
