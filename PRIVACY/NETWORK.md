# Network endpoints

What the `openoutreach` process contacts, and what it does not. This is the
runtime of the installed command (`openoutreach`, `python manage.py`), not
the upstream website and not a standalone `outfind` / `outsend` process.
Those two still contain the upstream contacts-store client; the guard below
is installed by this package when its settings load.

Silent telemetry is turned off in code at startup (`openoutreach/privacy.py`),
before either child is imported. A variable you export yourself is left
alone.

## Off unless you opt in

| Endpoint | What it would have sent | When |
| --- | --- | --- |
| `https://hub.openoutreach.app` (`/api/v2/register/`, `/contribute/`, `/profiles/`, `/companies/`, `/resolve/`) | Operator email and build id on register. After a paid email lookup: profile URL, country, work email. On every discovery page, for an operator outside the EEA/UK/CH: profile URL, country, name, headline, title, seniority, industry, region, employer name and domain, and a locally computed embedding. Not the mailbox password. | **Not called.** The client functions are replaced with no-ops, a stored token is not exported, and the hostname is refused at name resolution. Set `OPENOUTREACH_ENABLE_HUB=1` before the process starts to turn this back on. The wizard never sets it. |

## User-configured, and only when that step runs

These are the services you named. Prospect text and mail go to the model
you chose. Mail and the mailbox password go only to the mailbox you named.
They are not sent to the contacts store.

| When | Endpoint | What leaves the machine |
| --- | --- | --- |
| Onboarding verifies the model key. A find qualifies a person. A send writes or answers mail. | The provider in `OPENOUTFIND_AI_MODEL` / `OUTSEND_AI_MODEL`. `anthropic` uses `https://api.anthropic.com`. `openai` uses the OpenAI SDK's default host. `groq`, `google`, `mistral` and `cohere` use that vendor's API as the installed SDK defines it. `openai_compatible` uses `OPENOUTFIND_LLM_API_BASE` / `OUTSEND_LLM_API_BASE` exactly, including a local Ollama or vLLM. | The prompt: product description, target market, profile text, and (for the sender) the thread with that lead. The API key is the credential for that request. The mailbox password is not included. The Google SDK also sends its library version in a header on that same request. |
| `find`, while discovering | `https://app.bettercontact.rocks/api/v2/lead_finder/async` | Your BetterContact key and the search filters (titles, industries, country, company size). |
| `find` with addresses (`emails` / `--emails`), and `run` | `https://app.bettercontact.rocks/api/v2/async` and `https://app.bettercontact.rocks/api/v2/account` | Your BetterContact key and the profile URL being enriched. The response is the work email. The account call reads the credit balance. |
| First time a profile is embedded | Hugging Face Hub, for the public model `BAAI/bge-small-en-v1.5` (weights and the small metadata the hub serves with them). Cached under the state directory's `.cache/fastembed`. | The model files. The text being embedded stays on this machine. `HF_HUB_DISABLE_TELEMETRY=1` and `DO_NOT_TRACK=1` are set before that library is imported, and a request to `huggingface.co/api/telemetry` is refused. A Hugging Face token in the environment is not attached (`HF_HUB_DISABLE_IMPLICIT_TOKEN=1`). |
| `send` / `run`, mailbox transport (the default) | The SMTP host you set, or `smtp.gmail.com:587` with STARTTLS. IMAP is the host you set, or `imap.gmail.com:993`. | The message, and the mailbox username and app password, over TLS that checks the server certificate. |
| `send` / `run` only when `OUTSEND_TRANSPORT=resend` | `https://api.resend.com`. A received message's raw bytes are fetched only from `https://cdn.resend.dev` or `api.resend.com`, and a redirect to any other host is refused. | The message and the Resend API key. |

`OPENOUTFIND_APOLLO_API_KEY` can be stored and exported. The pinned finder
does not call Apollo; BetterContact is the only finder it ships.

## Shown, not fetched

| URL | When |
| --- | --- |
| `https://bettercontact.rocks?fpr=openoutreach` | Printed by the wizard as a signup link. The process does not request it. |
| `https://openoutreach.app/go/email-finder` | Returned in `status` as the finder's signup URL string. The process does not request it. |

## Local only

| Item | What happens |
| --- | --- |
| `OPENOUTFIND_NEWSLETTER` | Stored on the config row if you export `true`. Onboarding does not set it and does not ask. The pinned finder does not read it, and this process does not send a subscription request. |
| `Sent with OpenOutreach` | A fixed line at the end of each message. No URL, no tracking pixel, no install id. |
| SQLite database | API keys and the mailbox password are stored in plaintext in `data/db.sqlite3` (or `OPENOUTREACH_DB`). The file is mode `0600`. `data/` and an installed `~/.openoutreach` are mode `0700`. |

## Disabled telemetry

Set with `setdefault` at startup, so an explicit export still wins. Also
refused at name resolution when the flag that would enable them is off:

| Variable set | What it turns off |
| --- | --- |
| `HF_HUB_DISABLE_TELEMETRY=1`, `DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1` | Hugging Face Hub telemetry. |
| `HF_HUB_DISABLE_IMPLICIT_TOKEN=1` | Sending a stored Hugging Face token on the model download. |
| `ANONYMIZED_TELEMETRY=false` | Libraries (Chroma, LangChain and similar) that phone home unless this is `false`. |
| `CREWAI_DISABLE_TELEMETRY=true` | CrewAI's telemetry host. CrewAI is not a dependency of this install; the flag is set so a later dependency cannot turn it on quietly. `telemetry.crewai.com` is refused. |
| `LANGCHAIN_TRACING_V2=false`, `LANGSMITH_TRACING=false` | LangSmith tracing. `api.smith.langchain.com` and `eu.api.smith.langchain.com` are refused unless you set one of those variables true. |
| `OTEL_SDK_DISABLED=true` and `OTEL_*_EXPORTER=none` | An OpenTelemetry exporter. The install has the API package, not an exporter. |
| `ANTHROPIC_OPEN_TELEMETRY=false`, `ANTHROPIC_OPEN_TELEMETRY_PROPAGATION=false` | The Anthropic SDK's own spans, which default to on and would attach to a collector if you added one. |
| `SCARF_NO_ANALYTICS=true`, `POSTHOG_DISABLED=1` | Scarf and PostHog defaults. PostHog hosts and `*.ingest.sentry.io` are refused unless `SENTRY_DSN` is set. Logfire hosts are refused unless `LOGFIRE_TOKEN` is set. Neither service is a dependency. |
| `OUTSEND_REPLIES=hold` | Automatic answers to inbound mail. A clear one-line opt-out (`stop`, `unsubscribe`, and the short phrases in `openoutreach/privacy.py`) is still written to the suppression list before any model call. Set `OUTSEND_REPLIES=model` to let the model answer other replies. |

LangChain, LangSmith, LiteLLM, CrewAI, PostHog, Sentry and a Logfire
exporter are not installed. There is no update check, license ping, or
usage ping in this package.

## Mail safety that does not leave the machine

- A suppression list is checked when a lead is ingested and again immediately
  before every send, including a send the model just drafted.
- Every mailbox message carries a `List-Unsubscribe: <mailto:you+unsub@your-domain>`
  header and a plain-text opt-out line. Mail to that alias is recorded as an
  opt-out. A one-line "stop" / "unsubscribe" is recorded the same way without
  asking the model.
- Cold sends are paced (at least three minutes apart, with jitter) and capped
  per mailbox per day. `run` and `send` are the approval to send: both exit
  when the pass is done. Replies are not sent on their own while
  `OUTSEND_REPLIES=hold`.

## Not in this process

No web server is started. `ALLOWED_HOSTS` is empty. The image's command is
one `openoutreach find` and it exits. GitHub Actions no longer dispatches
`image-updated` to `eracle/hub.openoutreach.app`.
