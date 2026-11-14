# The practice lab

Learn RAGGuard by using it on **your own computer**, with data you can break and fix without risking anything.

You get your own S3 (a fake one called "moto"), PostgreSQL and Qdrant, filled with **30 documents that have every kind of fault planted on purpose**, and
two copies of RAGGuard to explore them:

| | Address | What it is | You do |
|---|---|---|---|
| **Lab A** | http://localhost:8000 | 30 documents, already connected | Press **Run audit** and compare with the answer sheet. Then fix problems with a repair plan. |
| **Lab B** | http://localhost:8001 | A miniature of the real "bills" setup, **empty** | Create an account and type the settings in, exactly as a real customer would. Then repair its two broken bills. |
| Answer sheet | [`WORKBOOK.md`](WORKBOOK.md) | Every planted fault, what RAGGuard should show, the fix | Keep it open next to the app. |

Nothing here touches your real systems: it reads no `.env` file, every port is bound to your own computer, and the lab's seeding script
refuses any address that is not local.

## 1. Before you start

- **Docker Desktop must be running** (the whale icon is steady, not "starting"). Check with:

```bash
docker info
```

  If that prints a long report, you are ready. If it says it cannot connect to the Docker API, open Docker Desktop and wait.
- Free these ports: `6333`, `8000`, `8001`, `9000`, `55432` (the lab uses 55432 for PostgreSQL on purpose, so it does not clash
  with a Postgres you may already run on 5432).
- About 3 GB of disk space, and 3 to 6 minutes the first time (it downloads images and builds one).

## 2. Start it

From the project folder:

```bash
docker compose -f docker-compose.lab.yml up --build
```

Leave that window open. Wait until you see:

```
seed-1  | Done. Lab A planted 14 faulty documents (see lab/WORKBOOK.md). Open the apps and run an audit:
```

then open http://localhost:8000 (Lab A) and http://localhost:8001 (Lab B).

To stop it, press `Ctrl+C`. To stop it and **throw everything away** (a clean start next time):

```bash
docker compose -f docker-compose.lab.yml down -v
```

## 3. Lab A: find the planted faults

1. Open http://localhost:8000. There is no sign-in; the connections are already made (look at **Data Sources**: three green cards).
2. Click **Run audit** (top right). It takes a few seconds.
3. Open **Integrity Issues** and compare with [`WORKBOOK.md`](WORKBOOK.md). You should see **31 documents compared, 14 findings, health 54.8%**,
   and a warning about one **duplicate manifest ID** (on **Overview** and **Audit History**).
4. Click an issue to read: what is wrong, why it matters, the evidence, the recommended fix.
5. Look at the other pages with the answer sheet beside you:
   - **Documents**: three ticks per document (S3, manifest, index). Open `initech/policies/zenith-019.md` and press **Inspect live** on the
     *Chunks* tab: it says "success" in the manifest but has no pieces in Qdrant.
   - **Reconciliation**: the three-way comparison.
   - **Isolation**: red, because document 13 carries another tenant's label. Press **Run isolation drill** to see the read-only drill.
   - **Impact analysis** (inside Integrity Issues): see how far the problems reach.
6. The three `acme/2000x` documents are healthy even though Qdrant stores their ID as a number, a decimal and text. That is the
   "numbers versus text" fix working.

### Fix the problems (the repair loop)

Lab A has a stand-in for your ingestion pipeline (the *reference worker*), so you can run the whole loop:

1. **Integrity Issues** → tick several open issues → **Create repair plan**.
2. Open the plan → **Trigger repair**. RAGGuard sends a signed request to the worker, which re-indexes the documents.
3. **Verify now**. RAGGuard re-reads the real index and checks every document. A worker that only half did the job fails here.
4. For leftovers (orphans, duplicates, old versions) press **Approve cleanup**. It tells you exactly how many vectors will be removed.
5. **Run audit** again. The issues you fixed turn *resolved*; the health score goes up.

Re-seeding puts everything back as it was:

```bash
docker compose -f docker-compose.lab.yml run --rm seed
```

## 4. Lab B: practise the real onboarding

This is the part that matches what a customer does, and what you did with your own data.

1. Open http://localhost:8001 and **create an account** (any email and password; they stay on your computer).
2. It shows *Connect your data*. On **Data Sources** open each card and type the values from the **Lab B table in
   [`WORKBOOK.md`](WORKBOOK.md#lab-b-mini-bills-practise-the-real-sign-up-and-settings-flow)** (bucket `bills-lab`, key prefix `bills/` **with the slash**, endpoint `http://s3:5000`,
   the key pattern, the column map, the payload field map). Press **Save**, then **Test connection**.
3. Under **Settings → Policy** set **Grace period** to `0`, **Required payload fields** to `document_id`, and switch on
   **Only audit documents found in the source (S3)**.
4. Press **Check setup** on Data Sources and read what it says (it is the setup and coverage checker).
5. **Run audit**. Expected: **5 documents, 2 findings** (one critical, one high), health 60%.
6. Do the four **exercises** at the end of the workbook: change one setting at a time and see how the answer changes. They teach what each
   switch is for, and where the blind spots are.
7. **Repair the two broken bills.** Lab B has its own worker (`worker-bills`), because a worker is *your* pipeline and Lab B's files, vectors and
   table are laid out differently from Lab A's. Open **Integrations → Repair webhook → Configure**, type the address
   `http://worker-bills:9000/ragi-webhook` and the signing secret `local-lab-secret`, press **Check settings** and **Save**. Then follow
   **Repair practice** at the end of the workbook: create a plan for both open issues, **Trigger repair**, **Verify now**, **Run audit**.
   Expected: **5 documents, 0 findings, health 100%**.

   (Do not use `http://worker:9000/...` here: that worker belongs to Lab A. It accepts the request and then cannot find Lab B's files, so
   **Verify now** reports the bills as not fixed.)

## 5. Which gap shows up where

| Gap | Where to see it |
|---|---|
| IDs not lining up (setup check) | Lab B: type a wrong **Payload field map** (for example `{"document_id":"nothing"}`) and press **Check setup**. |
| Duplicate IDs | Lab A: the duplicate-manifest-ID warning. Lab B exercise 4. |
| Numbers versus text | Lab A: the `acme/2000x` documents. Lab B: bill `2300003`. |
| One ID per document | Lab B exercise 4 (bill `2200001` has two documents). |
| The lookup blind spot | Lab B exercise 1 (file `9000001`). |
| Why "only audit documents in the source" exists | Lab B exercise 2. |
| False success (the pipeline lied) | Lab A document 2 and Lab B bill `2300004`. |

## 6. Useful commands

Run an audit from the command line inside Lab A and print the result:

```bash
docker compose -f docker-compose.lab.yml exec app-lab ragi audit
```

Check the setup of Lab A:

```bash
docker compose -f docker-compose.lab.yml exec app-lab ragi setup-check
```

See what each container is saying:

```bash
docker compose -f docker-compose.lab.yml logs --tail 50
```

The fake S3 has no web page of its own: see the files on the app's **Documents** page. Qdrant's web page (to see the pieces):
http://localhost:6333/dashboard.

## 7. If something goes wrong

| Problem | What to do |
|---|---|
| "cannot connect to the Docker API" | Docker Desktop is not running. Start it and wait until it says it is running. |
| "port is already allocated" | Something else uses that port. Close it, or change the left-hand number in `docker-compose.lab.yml`. |
| The seed step fails | Run it again: `docker compose -f docker-compose.lab.yml run --rm seed`. It is safe to repeat. |
| A page is empty or an audit says "setup required" | Lab A: reload and press **Run audit**. Lab B: finish the four steps in section 4. |
| Lab B says **0 documents, 0 issues** | Almost always the **Key prefix**: it must be `bills/` **with the slash at the end**. Without it the key pattern cannot match, RAGGuard finds no source documents, and "only audit documents found in the source" then leaves nothing to compare. Fix the prefix, press **Test connection** (the *Key pattern* line must turn green), then **Run audit**. |
| In Lab A, **Trigger repair** was accepted but **Verify now** says the documents are not fixed | Check the worker: `docker compose -f docker-compose.lab.yml logs worker`. (An old version of the worker failed on the lab's keyless manifest table. Update it with `docker compose -f docker-compose.lab.yml up -d --build --no-deps worker`, then press **Verify now** and **Send repair again**.) |
| In Lab B, **Trigger repair** was accepted but **Verify now** says the bills are not fixed | The repair webhook points at the wrong worker, or the Lab B worker is not running. The address must be `http://worker-bills:9000/ragi-webhook` (not `http://worker:9000/...`, which is Lab A's). Check it is up with `docker compose -f docker-compose.lab.yml logs worker-bills`. If you updated the project, start it with `docker compose -f docker-compose.lab.yml up -d --build` so the new worker exists. |
| Everything is a mess | `docker compose -f docker-compose.lab.yml down -v`, then start again. |
| Docker will not start at all | You can still explore with the built-in demo: `ragi serve --demo` (fake data with faults planted, no Docker needed). |

## 8. How this lab stays correct

[`WORKBOOK.md`](WORKBOOK.md) is generated by running the real audit on the lab, and `tests/test_lab.py` fails if the lab, the answer sheet or
the compose file drift apart. The same lab was also run for real against separate S3-over-HTTP, Postgres and Qdrant servers, and Lab B's
sign-up and settings flow was driven through the app's web API, with the same results as in the tables above.
