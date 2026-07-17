# Kirana Store Agent

A conversational agent that runs an Indian kirana store end-to-end from Telegram — receiving stock, cutting GST-correct bills, running khata (credit), closing the day, and generating invoices and analysis decks on request. No web app, no admin panel: the chat is the product.

**Live bot:** 
- Phone: https://t.me/chandans_kirana_store_bot 
- Web: https://web.telegram.org/k/#@chandans_kirana_store_bot

**Demo recording:** https://drive.google.com/file/d/1WVmNbG5z-5J0FFyc4YK_JgtsL4jPChOZ/view?usp=sharing

Note: the bot may take a few seconds to respond to the first message after a period of inactivity — Cloud Run is scaled to zero instances (a budget choice), so the first request pays a cold-start cost before the container is warm.

## Harness & model

**Pydantic AI**, not the Claude Agent SDK. The Agent SDK is genuinely powerful, but under the hood it spawns the Claude Code CLI (a Node.js binary) as a subprocess and talks to it over stdio — a model built for long-lived interactive coding sessions with file/bash access, not a stateless HTTP handler invoked once per Telegram update. Forcing that model into "spin up a Node subprocess per webhook call, inside a Python container" fights the deployment shape rather than fitting it. Pydantic AI is a pure-Python library: no subprocess, tools are typed Python functions with schemas generated from type hints (the same mechanism FastAPI uses for its own routes), and it slots directly into a codebase already built on SQLModel/Pydantic without introducing a second mental model.

Model: DeepSeek's `deepseek-v4-pro`, via its Anthropic-compatible endpoint (`ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`). Pydantic AI's `AnthropicProvider` accepts a `base_url` override, so the harness is unchanged — only the provider config differs from pointing at `api.anthropic.com` directly. Reasons well enough to handle ambiguous requests and ask good clarifying questions, at a fraction of the cost of keeping an always-on demo bot running on Claude directly.

## Architecture & control loop

FastAPI on Cloud Run, Postgres on Neon, SQLModel + Alembic, deployed via Cloud Build on push to `master`.

```
Telegram → POST /webhook → verify secret token → enqueue via Cloud Tasks → 200 OK
                                                        ↓
                                          POST /tasks/handle (OIDC-verified)
                                                        ↓
                                    load Conversation history → agent.run() →
                                    save history → reply (or Confirm/Cancel buttons)
```

Telegram needs a fast 200 or it redelivers; the actual agent turn (LLM call, DB writes) can take a few seconds, so `webhook.py` does almost nothing but auth-check and hand off. Cloud Tasks names each task after the Telegram `update_id`, so a redelivered update collapses into the same task instead of double-processing. Conversation history is Pydantic AI's serialized message list, stored per `chat_id` in Postgres and reloaded each turn — the container is stateless between invocations, so this is what makes multi-turn bills and ongoing chat context work at all. `/new` archives and clears that chat's conversation row (`ConversationArchive`, an append-only audit log) without touching stock, bills, khata, or preferences — those live in tables `/new` never reaches.

**Callback buttons get a separate fast path.** A button tap answers immediately in `webhook.py`, before the Cloud Tasks round trip — routing it through the queue first made taps look unresponsive. The actual finalize logic still runs through the normal async path afterward.

**Infra is Terraform, not console click-ops.** `terraform/` provisions the Cloud Run service, the Cloud Tasks queue, the service accounts and OIDC wiring behind `tasks_auth.py`, Secret Manager entries, the Artifact Registry repo, and the Cloud Build trigger that deploys on push to `master` — none of it set up by hand in the GCP console. Wasn't asked for by the brief, but a deployed service without a repeatable, versioned way to stand it back up felt like an obvious gap. One guardrail worth calling out: an agent session only ever runs `init`/`validate`/`fmt` against it — `apply` and `plan` are deliberately left to be run by hand, not delegated, since infra changes are the one category of mistake here that isn't easily undone.

## Data model: what's global vs. what's per-chat

`Product`, `Customer`, and `KhataEntry` have no `chat_id` — they're shop-wide shared state, because it's one shop, potentially with multiple operators (staff phones) each running their own till concurrently. `Bill` and `Conversation` are `chat_id`-scoped, because a draft-in-progress and a chat's context are legitimately per-operator. This distinction matters in practice: `list_past_bills` and sales analytics are shop-wide (so a reviewer messaging from a fresh Telegram account sees the shop's real sales history, not an empty one scoped to a chat they've never used before); only the *draft* bill tools and the default "send me that bill" lookup stay chat-scoped.

## Skill & tool design

- **Inventory** (`tools/products.py`): `search_products` / `list_products` (fuzzy and full-catalog lookup — both return `qty_on_hand` inline so most stock questions resolve without a second call), `add_product`, `receive_stock` (row-locked, refuses on an unknown SKU rather than auto-creating), `list_low_stock`, `suggest_reorders` (velocity-based: projects days-until-stockout from actual `StockMovement` sale history, not just a static threshold).
- **Billing** (`tools/bills.py`): `start_bill` / `set_item_qty` / `view_draft_bill` / `cancel_draft_bill` / `list_past_bills` build and edit a draft with no stock impact. `request_finalize_confirmation` stores payment info and flags the reply for Confirm/Cancel buttons — it does not finalize. `finalize_confirmed_bill` is a plain function, **not** an `@agent.tool`, reachable only from the callback-button handler — no tool call, correct or hallucinated, can finalize a bill.
- **Khata** (`tools/khata.py`): `search_customers` / `list_customers` / `add_credit` (auto-creates a customer — a name has no price/GST to invent) / `record_payment` (refuses on a nonexistent customer) / `get_balance`. Deliberately **not** wired as a bill payment mode — the spec's Payments line lists only Cash/UPI/Card, and adding a fourth would contradict a literal requirement.
- **Analytics** (`tools/analytics.py`): `get_sales_summary` / `get_sales_trend`, both range-based (`compute_summary`/`compute_daily_breakdown` in `services/core/analytics.py`) so "today's sales" and a weekly deck share the same tested aggregation logic instead of duplicating it.
- **Documents** (`tools/documents.py`): `generate_invoice_pdf` is fully deterministic (`reportlab` — a GST invoice has a legally expected shape, no room for model creativity). `build_analysis_deck` is the opposite: it renders whatever `SlideSpec` content the model hands it (title/text/table/chart slides, `python-pptx` native charts, not pasted images), so the model decides *which* data to gather and what insight to write, while the renderer deterministically handles layout — this is what makes "make this week's deck" and "just show me top items" produce genuinely different decks instead of the same fixed template.
- **Preferences** (`tools/preferences.py`): a `Preference` key-value store scoped to a constrained `Literal` key set (extensible, but not free-text — prevents the same preference silently fragmenting under two slightly different key names), global rather than per-chat, since "remembered across chats" only makes sense if it doesn't live inside any one conversation.

## How each hard part was solved

1. **Grounding** — every price, GST slab, and stock figure comes from a tool call against Postgres, never the model's own estimate. Extended to dates too: the system prompt injects the real current IST date every turn (`@agent.system_prompt`), since a model with no live clock will otherwise guess "today" when computing a relative date range.
2. **Oversell guard** — `finalize_confirmed_bill` takes `SELECT ... FOR UPDATE` on every involved product (locked in a fixed, sorted order to avoid deadlocking a concurrent finalize), refusing the entire bill if any line would oversell. A softer, non-locking check at draft-edit time gives early warning without being the authoritative gate.
3. **GST correctness** — `services/core/gst.py`: MRP is treated as GST-inclusive (Indian Legal Metrology rules), so taxable value is back-calculated. CGST and SGST are computed identically from the same half-rate (so they're always exactly equal, matching real invoice convention), and taxable value is derived as the remainder against the rounded line total — guaranteeing the three figures always sum correctly, unit-tested against a regression case and a property sweep across qty/price/slab combinations.
4. **Multi-turn bills** — a `Bill` is `draft` until `finalize_confirmed_bill` runs; totals are computed on demand from `BillItem` rows while drafting and only frozen at finalize, so editing a draft can never leave stale totals.
5. **Idempotency** — layered: Cloud Tasks names tasks after `update_id` (collapses a Telegram redelivery at the transport layer); `finalize_confirmed_bill`'s query only ever matches `status='draft'` under a row lock, so a retried finalize naturally finds nothing left to do and reports the already-finalized bill instead of double-deducting stock.
6. **Concurrency** — a partial unique index (`chat_id` where `status='draft'`) makes two simultaneous drafts per chat structurally impossible; verified directly with a script that runs two concurrent `finalize_confirmed_bill` calls against the same SKU from two different chats and asserts stock never goes negative or gets double-decremented.
7. **Guardrails** — `ModelRetry` (not a bare exception or a silent error dict) for every refusal, so the model gets the failure fed back as something to reason about. Nothing ever hard-deletes a `Product` or `StockMovement`; a draft bill is the one thing safe to delete outright, since it hasn't touched stock yet.
8. **Real artifacts** — GST-correct PDF invoice and a model-authored PPTX deck with native PowerPoint charts, both described above.
9. **Memory across sessions** — the `Preference` table lives entirely outside the conversation, so a `/new` chat clears context but never touches standing preferences (default payment mode, preferred brand, shop name/GSTIN on invoices).

## Stretch goals implemented

- **Reorder suggestions from sales velocity** — `suggest_reorders` projects actual days-until-stockout from recent sale history, catching a fast-mover that's still above its static reorder point before `list_low_stock` would.
- **Multi-language** — no special-casing needed; the system prompt defaults to English but switches to whatever language the owner writes in, and the underlying model handles Hindi/Hinglish naturally.

## What I'd do with more time

- **Link khata to bill finalization** — letting a finalized bill go straight onto a customer's tab as a fourth "settle on credit" path. Deliberately cut: the spec's Payments line only lists Cash/UPI/Card, and adding a credit payment mode would contradict that literally, even though it's a natural real-world flow.
- **Fuzzy duplicate-customer detection** — the current unique constraint is case-insensitive exact match, so "Ramesh" and "Ramesh Kumar" (same person, different phrasing) aren't caught. Needs either fuzzy entity resolution or an owner-confirmation step, not just a stricter index.
- **Scheduled weekly deck / khata reminders** — both need the same missing piece (a scheduled trigger plus a "who gets notified" registry, since today everything is reactive to an incoming message); worth building once, since it unlocks both stretch items at once.
