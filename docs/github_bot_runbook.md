# Running the live GitHub bot

The bot is the production face of the pipeline: a webhook receiver that reviews pull
requests and, when the detector says the intent is unclear, asks the author one
question first. This page is the checklist for putting it on a real repository.

What it does, per event:

| Event | Behaviour |
|---|---|
| `pull_request` opened / reopened / ready_for_review | Ingest, decide. Clear: review now. Unclear: post one question (marked with a hidden comment), park the run in SQLite. Drafts and already-reviewed heads are skipped. Bot-authored PRs are reviewed but never asked. |
| `pull_request` synchronize | Parked: swap in the new code, keep the question and deadline, never re-ask. Otherwise review the new head once (`CLARIFYREVIEW_REVIEW_ON_PUSH`). |
| `pull_request` closed | Cancel the parked run. |
| `issue_comment` created | Only on pull requests, only from the PR author, never from a Bot account, `CLARIFYREVIEW_BOT_LOGIN`, or a comment carrying a `<!-- clarifyreview` marker. Revives the parked run and posts the review. |
| `pull_request_review_comment`, `pull_request_review` (optional) | Same rule; an author's inline reply or review body counts as the answer. |
| deadline passes | `sweep_expired` posts the review with a "No answer was received" note. |

Parked runs, posted reviews and seen webhook deliveries live in the same SQLite file
as the experiment log (`CLARIFYREVIEW_DB`), so a restart loses nothing. Production
runs are logged with `condition = github_live` and never mix with Study A.

## 1. Credentials: personal access token (quickest)

Create a **fine-grained personal access token**, ideally on a **separate bot
account** (see the caveat below), scoped to the repositories you want covered:

| Permission | Level |
|---|---|
| Pull requests | Read and write |
| Issues | Read and write |
| Contents | Read |
| Metadata | Read |

Put it in `.env` yourself - do not paste it into a chat or a commit:

```
GITHUB_TOKEN=github_pat_...
GITHUB_WEBHOOK_SECRET=<a long random string>
```

Generate the secret with `python -c "import secrets; print(secrets.token_hex(32))"`.

**Why a separate account.** GitHub shows a token's comments as its owner, so with
your own token on your own PR the bot's question looks like the author's comment.
The bot copes: everything it posts carries a hidden `<!-- clarifyreview ... -->`
marker, and a comment with a marker is never an answer. That makes single-account
testing work (your unmarked reply is the answer), but a separate bot account is
still cleaner, and it lets you set `CLARIFYREVIEW_BOT_LOGIN=<that login>` so PRs the
bot account itself opens are reviewed rather than asked about. Or use the App path.

## 2. Credentials: GitHub App (for anything shared)

Comments come from `<slug>[bot]`, which is never the PR author, and installation
tokens are short-lived.

1. Create an App with the same permissions as above, subscribe it to *Pull request*
   and *Issue comment* events (add *Pull request review comment* and *Pull request
   review* if you want inline replies to count), set the webhook URL and secret as
   in step 3, and generate a private key (PEM).
2. Install the App on the repositories.
3. `pip install -e ".[app]"` (adds `pyjwt[crypto]`) and set:

```
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY_PATH=C:\keys\clarifyreview.pem
GITHUB_WEBHOOK_SECRET=<the App's webhook secret>
```

The installation id arrives in each webhook payload; `GITHUB_TOKEN` is not needed.
If the App variables are unset the bot uses `GITHUB_TOKEN`.

## 3. Webhook

Repository (or App) settings, Webhooks:

- **Payload URL:** `https://<your-tunnel>/webhook`
- **Content type:** `application/json`
- **Secret:** the same value as `GITHUB_WEBHOOK_SECRET`
- **Events:** *Pull requests* and *Issue comments*. Optionally *Pull request review
  comments* and *Pull request reviews*.

## 4. A public URL for your laptop

GitHub has to reach your machine. Use a tunnel that forwards the request body
untouched:

```
cloudflared tunnel --url http://127.0.0.1:8000
# or
ngrok http 8000
```

Do **not** use smee.io: it re-serialises the JSON, which breaks the HMAC signature,
and every delivery will be rejected with 401.

## 5. Start the server

```
.venv\Scripts\clarifyreview serve --host 127.0.0.1 --port 8000
```

`GET /health` returns `{"status": "ok", "parked_runs": N}`. A background loop sweeps
expired runs every `CLARIFYREVIEW_SWEEP_INTERVAL_S` seconds (`--sweep-interval`
overrides it); every webhook also triggers a sweep. If you would rather not keep the
server running, set the interval to 0 and run `clarifyreview sweep` from cron or
Task Scheduler.

## 6. Smoke test

1. Open a test repository's PR that removes a guard, with the single commit message
   `fix` and no description (the heuristic detector will ask).
2. Within seconds the bot posts **one** comment beginning "ClarifyReview - one thing
   before I review". `GET /health` shows `parked_runs: 1`.
3. Reply **as the PR author** (not the bot account). The bot posts the review and
   `parked_runs` returns to 0.
4. To see the timeout path, set `CLARIFYREVIEW_CLARIFY_TIMEOUT=120`, restart, open a
   second PR and do not answer; after two minutes (plus up to one sweep interval)
   the review arrives with the note "No answer was received".
5. Push to the parked PR: no second question appears, and the eventual review is of
   the new head.

Check the log in `data/clarifyreview.db`:

```
sqlite3 data/clarifyreview.db "select pr_id, condition, detector, asked, answered, timed_out from runs order by id desc limit 5"
```

## Behaviour worth knowing

- **Redelivery is safe.** GitHub's "Redeliver" button resends the same delivery id,
  which the bot ignores (unless the first attempt *failed*, in which case it retries).
  Deliveries accepted but never finished because the process died are replayed on
  the next start.
- **One review per head commit.** A review is recorded per `(PR, head sha)`; a
  second `opened`/`reopened` event for the same commit does nothing.
- **Failures are visible.** If a run fails (model error, GitHub error), the bot posts
  one short notice per head commit - the exception class only, no stack trace - and
  releases the parked run for up to three retries. Details are in the server log.
- **Big PRs.** Commits and comments are fully paginated; a diff too large for
  GitHub's diff media type is rebuilt from per-file patches (files without a patch,
  such as binaries, are omitted). Comments are cut to
  `CLARIFYREVIEW_MAX_COMMENT_CHARS` (60,000).
- **Rate limits.** The client sleeps until the reset (up to 15 minutes) and honours
  `Retry-After`; longer waits abort the run and are reported.
- **Fork PRs.** Nothing is checked out; everything comes from the API, so they work
  with a token that can read the base repository.
- **What this does not do.** No inline review comments - the review is a single
  issue comment. No dashboard.

## Configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `GITHUB_TOKEN` | | Token used unless App credentials are set |
| `GITHUB_WEBHOOK_SECRET` | | HMAC secret; the receiver refuses everything without it |
| `CLARIFYREVIEW_DETECTOR` | `heuristic` | `heuristic`, `classifier`, `sampling`, `perturbation` |
| `CLARIFYREVIEW_CLARIFY_TIMEOUT` | `86400` | Seconds to wait for the author. `0` posts the question and reviews immediately as unanswered |
| `CLARIFYREVIEW_SWEEP_INTERVAL_S` | `300` | Background sweep period; `0` disables |
| `CLARIFYREVIEW_BOT_LOGIN` | | The bot's own account, if it has one: its PRs are never asked about and its comments never count as answers |
| `CLARIFYREVIEW_REVIEW_ON_PUSH` | `true` | Review new heads of PRs that are not parked |
| `CLARIFYREVIEW_SKIP_DRAFTS` | `true` | Ignore draft PRs until ready for review |
| `CLARIFYREVIEW_MAX_COMMENT_CHARS` | `60000` | Truncate longer reviews |
| `CLARIFYREVIEW_BOT_CONDITION` | `github_live` | `runs.condition` for production runs |
| `GITHUB_API_URL` | `https://api.github.com` | GitHub Enterprise: `https://host/api/v3` |
| `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH` | | GitHub App auth |
