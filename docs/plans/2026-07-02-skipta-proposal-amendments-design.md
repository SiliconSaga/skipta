# Skipta Phase 2 — Proposal-Aware Amendments (Design)

**Date:** 2026-07-02 · **Status:** approved design, pre-implementation · **Builds on:** the shipped MVP (`2026-07-01-skipta-field-amendments-design.md`)

Phase 2 makes Skipta amend *existing* proposals — the primary field need. A tech dictates "Amend Rasmus' SPAN panel proposal to add a sub panel with four 20 amp breakers and 2 30 amp breakers"; Skipta finds the proposal PDF in Drive, confirms the match with the tech, reads it for the customer's email, address, and original price, and produces a signed amendment that references the original and presents Original / This amendment / Grand total. The phase-1 flow remains a first-class sibling: a work order priced from scratch (`kind=new`).

## Goals

- Two first-class intake flows from one dictation box: **new work order** (phase-1 behavior) and **amend existing proposal**, with intent detected by extraction and confirmed explicitly by the tech.
- Proposal discovery in the shared `Skipta/` Drive tree with human disambiguation — never a silent wrong-document match.
- Proposal facts (original total, customer email, address, title) parsed from the PDF by Gemini with visible provenance on the signing page and PDF; humans are the checkpoint, and a missing fact renders as "not found in document" rather than blocking or inventing.
- Grand total appears only when the original total was actually parsed.

## Non-goals

- No write access to Drive (service accounts cannot own Drive content; reads of shared files are unaffected). The PDF archive stays in GCS, public-read per the accepted demo posture.
- No persisted "pending clarification" state — disambiguation is synchronous on the intake form; no row exists until the flow resolves.
- No editing of the original proposal document; the amendment references it.

## Flow and API

One endpoint, three response shapes. `POST /api/v1/amendments` accepts `{voice_text, customer_name?, proposal_file_id?}`:

```
├─ extraction pass 1 → {intent: new|amend, proposal_hint, customer_name, panel?, breakers[]}
├─ intent=new ──────────────────────→ 201 {amendment_id, signing_url}          (phase-1 flow, row kind=new)
├─ intent=amend, no proposal_file_id → 200 {status: "choose_proposal",
│                                           candidates: [{file_id, name, folder}],
│                                           note?: "nothing matched the hint"}
└─ intent=amend + proposal_file_id ──→ Drive get_media (≤10 MB)
                                       → Gemini pass 2 (PDF bytes, strict schema)
                                       → price delta items → row kind=amend
                                       → 201 {amendment_id, signing_url}
```

- The candidates response **always** includes the client-side choice "None of these → proceed as new work order"; picking it re-POSTs with `proposal_file_id: ""` which routes to the new-flow with `kind=new`.
- The re-POST carries the same `voice_text`; extraction simply re-runs (stateless — one extra flash-tier call beats token plumbing, and there is nothing client-supplied to trust beyond the file id the server itself offered).
- Zero candidates → the pick-list ships only the proceed-as-new choice plus a note, so a missing document is a visible fact, not an error page.
- Proposal download or parse failure after selection → honest 502 (no row written).

## Extraction changes (pass 1)

`AmendmentPayload` grows `intent: "new" | "amend"` (schema-enforced enum, default "new") and `proposal_hint: str` (verbatim phrase naming the document, empty when none). `BreakerRequirement.poles` becomes optional: when the note doesn't state poles, pricing matches by amps alone **iff exactly one Breakers row has those amps**; multiple or zero amp matches → UNMATCHED line item (the phase-1 guard unchanged). The prompt keeps the never-invent instruction and adds: report the proposal reference exactly as spoken, do not guess intent from pricing content.

## Proposal pipeline (new module `app/proposals.py`)

| Function | Contract |
|---|---|
| `search_proposals(drive, root_folder_id, customer_name, hint) -> list[Candidate]` | Lists the `Skipta/` tree via Drive `files.list`. Scoring: customer-subfolder name match first, then filename token overlap with the hint. Returns PDFs and Google Docs. `Candidate = {file_id, name, folder}` |
| `fetch_pdf(drive, file_id) -> bytes` | `files.get_media` for PDFs; Google Docs export as PDF so pass 2 is uniform. Hard cap 10 MB → `ProposalTooLarge` |
| `parse_proposal(model_factory, model_names, pdf_bytes) -> ProposalFacts` | Gemini multimodal (`Part.from_data`, `application/pdf`) with a strict response schema; same model fallback chain as extraction. `ProposalFacts = {proposal_title, original_total: float|None, customer_email: str, customer_address: str}` — absent facts come back empty/None, never invented |

`build_drive` returns to `google_clients.py` (read-only Drive use is unaffected by the consumer-SA storage-quota wall; the `drive` scope is already requested).

## Data model

The `Amendments` tab grows columns K–P (the human adds headers; existing short rows already pad on read):

`K kind` (`new` | `amend`) · `L proposal_file_id` · `M proposal_name` · `N original_total` (empty when not parsed) · `O customer_email` · `P customer_address`

`AmendmentRecord` gains the six fields with the same to_row/from_row padding discipline; `mark_signed` (H:J) is untouched.

## Signing page and PDF

Both templates gain an **Original proposal** block for `kind=amend`: source filename ("as stated in span-quote.pdf"), original total, customer email and address — each rendering "not found in document" when parsing came back empty. The totals ladder replaces the single total for amendments: **Original proposal** / **This amendment** / **Grand total**, with the grand row present only when `original_total` was parsed. `kind=new` renders exactly as phase 1. The intake form renders `choose_proposal` candidates as tappable buttons plus "None of these — proceed as new work order".

## Error handling

| Failure | Response |
|---|---|
| Amend intent, search finds nothing | `choose_proposal` with empty candidates + note (proceed-as-new remains available) |
| Selected file too large / download fails / export fails | 502 with the upstream reason; no row written |
| Pass-2 parse returns schema-invalid output after fallback chain | 502 ("could not read the proposal"); no row written |
| Parse succeeds but facts missing | Row written; missing facts empty; provenance block shows "not found in document"; grand total omitted |
| Everything else | Phase-1 table unchanged (404/409/422/502) |

## Testing

Fake-injection throughout, as phase 1: `FakeDrive` grows `list`/`get_media`/export surfaces; pass-2 Gemini gets canned responses (all-facts, missing-total, garbage→fallback→502). Route tests pin all three response shapes, the proceed-as-new path, poles-inference (unique amps match + ambiguous→UNMATCHED), and a `kind=new` regression suite proving phase-1 behavior is untouched. Live smoke: the real Rasmus SPAN flow end-to-end on the phone.

## Deferred

- Full-text (`fullText contains`) Drive search — filename+folder scoring first; revisit if real usage misses documents.
- Private bucket + signed URLs for the PDF archive (explicitly deprioritized by the owner; public-read accepted).
- Multi-proposal amendments and amendment-of-amendment chains.
