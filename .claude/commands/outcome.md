# /outcome - Record What Happened to an Application

Adapted from ai-job-search (MIT), `.claude/commands/outcome.md`: same flow, rewired to the `cvforge` tracker.

You record what happened to a job application: the candidate submitted it, a test or interview was scheduled or done, an offer arrived, or the process ended. You also own the stretch before there is news: the **follow-up branch** (Step 2b) drafts a short follow-up for applications that went quiet, and the **stale sweep** (Step 2c) closes applications that never answered.

Every write goes through `.venv/bin/cvforge track status`, `.venv/bin/cvforge track stage` or `.venv/bin/cvforge track done`, and what needs attention is read with `.venv/bin/cvforge due`. **Never read or edit `data/tracker.csv` directly.**

Paths: `<slug>` is the application id; `<app>` is `data/applications/<slug>`.

Follow these steps **in order**.

---

## Step 0: Parse input

`$ARGUMENTS` may contain:

- Nothing: show what needs attention and ask which application to update.
- A slug, or a company name with an optional role, e.g. `/outcome acme` or `/outcome acme backend`: target that application, then read the rest of the message as what happened (e.g. `/outcome acme-backend-engineer applied`).
- `followup`: the follow-up branch (Step 2b) over every quiet application, threshold **10 days**.
- `followup <N>`: the follow-up branch with an N-day threshold (N of 10 or more).
- `followup <slug or company>`: draft a follow-up for that application now, whatever its age.
- `stale` or `sweep`: the stale sweep (Step 2c), threshold **60 days**.
- `stale <N>` or `sweep <N>`: the stale sweep with an N-day threshold (N of 60 or more).

---

## Step 1: Identify the application

1. Run `.venv/bin/cvforge due`. It prints three sections:
   - **Stages**: open stages due in the next 7 days or overdue (`<slug>: <name> (<kind>) due <date>`).
   - **Follow up**: `applied` or `assessment` applications with no update for 10 to 59 days.
   - **Stale**: open applications with no update for 60 days or more.

   Each application line shows the slug, company, role, status and last update date.
2. **With an argument:** find the slug. Match it against the lines of `cvforge due` and the folder names in `data/applications/` (each folder is a slug, `<company>-<role>`; `<app>/posting.json` holds the company and title). One match: proceed. Several: list them and ask. None: the application was made outside `/apply`; ask for the company, role and link, and send the candidate to `/apply` with the link (or pasted posting) so it gets a folder and a tracker row.
3. **Without an argument:** show the `cvforge due` output as a short table, flag overdue stages first, and ask which application to update. If any are listed under **Follow up**, add one line: "Some of these went quiet. Want a follow-up draft? (`/outcome followup`)". If any are listed under **Stale**, add: "Some have been quiet for 60+ days. Run `/outcome stale` to close them." If all three sections are empty, say so and stop.

---

## Tracker status vocabulary

The only status values `cvforge track status` accepts:

`drafted` | `applied` | `assessment` | `interview` | `offer` | `hired` | `rejected` | `no_response` | `offer_declined` | `withdrawn` | `skipped`

- **Final** (application closed): `hired`, `rejected`, `no_response`, `offer_declined`, `withdrawn`, `skipped`
- **Open**: everything else.
- **`drafted`**: documents made, nothing sent yet. Never chased: nobody is late replying to something that was never sent.
- **`assessment`**: a test, case or questionnaire is in progress.
- **`skipped`**: written by `cvforge check` when a job fails the eligibility check. Never set it by hand.

Stage kinds for `cvforge track stage --kind`: `test`, `interview`, `case`, `form`, `other`.

---

## Step 2: Record what happened

Ask what happened if the message does not say, then map it to commands. Dates are `YYYY-MM-DD`. Notes are one short line, in the candidate's words where possible.

**Submitted** (status was `drafted`):
```
.venv/bin/cvforge track status <slug> applied
```
This stamps today as the applied date. If the candidate says it was sent on an earlier day, add `--note "submitted <date>"`.

**Test, case or questionnaire** (online test, take-home, assessment, extra form):
```
.venv/bin/cvforge track status <slug> assessment
.venv/bin/cvforge track stage <slug> "<stage name>" --kind test --due <date>
```
Use `--kind case` for a case study or take-home project and `--kind form` for extra questions. Leave out `--due` only when there is no deadline. Then write `<app>/prep.md` (see **Prep notes** below).

**Interview scheduled:**
```
.venv/bin/cvforge track status <slug> interview
.venv/bin/cvforge track stage <slug> "<stage name, e.g. technical interview>" --kind interview --due <date>
```
Write or update `<app>/prep.md` for this stage too.

**Stage done:**
```
.venv/bin/cvforge track done <slug> "<stage name>"
```
The name must match the stage as it was added (case and spacing do not matter). After an interview stage is done, offer: "Want a short thank-you note for the interviewer?" If yes, draft it under the drafting rules of Step 2b.

**Offer received:** `.venv/bin/cvforge track status <slug> offer --note "<what was offered>"`

**Final resolutions:**
- Accepted an offer: `.venv/bin/cvforge track status <slug> hired`
- Turned an offer down: `.venv/bin/cvforge track status <slug> offer_declined`
- Rejected at any stage: `.venv/bin/cvforge track status <slug> rejected --note "<stage reached, feedback if any>"`
- No reply: `.venv/bin/cvforge track status <slug> no_response`. If the candidate is unsure whether to call it, say how long it has been since the last update and let them decide. Do not impose a cutoff.
- The candidate pulled out: `.venv/bin/cvforge track status <slug> withdrawn --note "<reason>"`

Also ask, without interrogating (one or two open questions are enough), for any feedback received, verbatim where remembered, and record it in the `--note` of the status change.

### Prep notes

When a test, case or interview stage is added, write `<app>/prep.md` (append a dated section if it exists):

- the stage, its kind and its due date
- what it is likely to cover, drawn from `<app>/posting.md` and what the candidate was told
- what to review, mapped to the posting's requirements and to the master facts in `<app>/tailored.yaml` the candidate may be asked about
- the logistics the candidate mentioned (platform, duration, who they meet)

**Never solve the test, case or take-home, and never write answers to it.** Prep notes say what to study, not what to submit. If the candidate shares the test itself and asks you to do it, decline and offer to help them review the topics instead.

---

## Step 2b: Follow-up branch (chase a quiet application)

Enter from the `followup` argument or from the offer in Step 1. Standard practice is a brief, polite follow-up one to two weeks after applying, at most twice.

**Candidates.** Take the **Follow up** section of `cvforge due`. With `followup <N>`, keep only those whose last update is N or more days ago. Each follow-up is logged as a stage named `followup <date>` in `<app>/stages.yaml`: count them, and drop applications that already have **two**, or whose latest follow-up is less than the threshold ago. Present the rest as a table (company, role, status, days quiet, follow-ups sent) and draft only for the ones the candidate picks.

**Drafting.** For each selected application:

1. Every claim comes from what was submitted: `<app>/tailored.yaml` (CV, letter, recruiter note, answers) and `<app>/posting.md`. No new skills, experience or numbers.
2. Match the application's language (`lang` in `tailored.yaml`). Warm but direct, no clichés, no em dash.
3. Roughly 60 to 120 words: greet the contact by name if the candidate gives one (otherwise the hiring team); one sentence restating interest in the specific role; one concrete reminder of value from the submitted materials; one polite question about the timeline. No pressure, no "just checking in" filler.
4. Shape it for the channel: email with a subject line, LinkedIn message (shorter, no subject), or portal message (plain text).
5. Show the draft and iterate until the candidate is happy.

**Logging.** Once the candidate says they sent it (or will), log it in the same turn:
```
.venv/bin/cvforge track stage <slug> "followup <date>" --kind other
.venv/bin/cvforge track done <slug> "followup <date>"
```
Save the final text as `<app>/followup_<date>.md`. If the candidate decides not to send it, log nothing.

**Termination.** After two silent follow-ups, do not offer a third: say how long it has been and ask whether to record `no_response` (Step 2). If the candidate mentions an actual reply while in this branch, leave the branch and record it through Step 2.

---

## Step 2c: Stale sweep (batch-close quiet applications)

Enter from the `stale` or `sweep` argument or from the offer in Step 1.

**Candidates.** Take the **Stale** section of `cvforge due`. With `stale <N>`, keep only those whose last update is N or more days ago. If none qualify, say "No open applications have been quiet for <N>+ days." and stop.

**Presentation.** Show a numbered table:

```
| # | Slug | Company | Role | Last update | Days quiet | Status | Proposed |
|---|------|---------|------|-------------|------------|--------|----------|
| 1 | acme-backend-engineer | Acme | Backend Engineer | <date> | 75 | applied | no_response |
```

Then ask: **`all`** (close every row as `no_response`), **`select`** (give the numbers, e.g. "1, 3" or "1-4"), or **`skip`** (change nothing). Wait for an explicit answer before writing anything.

**Execution.** For each confirmed application:
```
.venv/bin/cvforge track status <slug> no_response --note "stale: no reply after <days> days"
```
A row the candidate says actually moved (an interview, a rejection) goes through Step 2 instead.

---

## Step 3: Confirm

Summarise what was recorded:

> **Updated <Role> at <Company>** (`<slug>`)
> - Status: <old> to <new>
> - Stages: <added or done, with due dates>
> - Files: <prep.md or followup note written, if any>

If an interview or test stage is coming up, point to `<app>/prep.md`. If the new status is `hired`, congratulate the candidate warmly first.

---

## Important rules

1. **Writes only through `track status`, `track stage` and `track done`.** Never open, rewrite or reorder `data/tracker.csv` yourself.
2. **Never fabricate.** Feedback is recorded as the candidate reports it. Follow-ups and thank-you notes add no new claims.
3. **Never solve tests.** Prep notes cover what to review, never the answers.
4. **Draft only, never send.** Follow-ups and thank-you notes are text for the candidate to send. Nothing is emailed, messaged or submitted, and nothing is automated on LinkedIn.
5. **At most two follow-ups per application.** After the second silent one, the honest move is recording the outcome.
6. **Stale sweep waits for confirmation.** Nothing is closed as `no_response` without the candidate's explicit `all` or `select`.
