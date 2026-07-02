# Skipta

**Skipta** is Old Norse for exchanging and shifting — making a trade, or moving between states. The idiom *skipta máli* means "to make a difference; to alter the meaning or matter." Both are the job description: a mid-job change order trades scope, and a signed amendment alters the agreement.

Skipta is an AI-backed field amendment & signing service — a GDD showcase. A field tech dictates a change order; Gemini (Vertex AI structured output) extracts a strict parts payload; Google Sheets prices it; both parties sign on an HTML5 canvas page; the flattened PDF lands in the customer's Google Drive folder. The amendment itself shifts states the same way: `draft` → `signed`, one row in the sheet.

Design: [docs/plans/2026-07-01-skipta-field-amendments-design.md](docs/plans/2026-07-01-skipta-field-amendments-design.md) · Implementation plan: [docs/plans/2026-07-01-skipta-field-amendments-plan.md](docs/plans/2026-07-01-skipta-field-amendments-plan.md)

## Local dev

1. `python -m venv .venv`
2. `.venv/Scripts/python -m pip install -r requirements-dev.txt` (POSIX: `.venv/bin/python`)
3. Copy `.env.template` to `.env`, fill the spreadsheet/folder IDs.
4. Auth as the service the pod runs as: `gcloud auth application-default login --impersonate-service-account=skipta-gsa@teralivekubernetes.iam.gserviceaccount.com`
5. `make run` → http://localhost:8000

Note: WeasyPrint needs GTK libs; on Windows the PDF test auto-skips — CI and the container cover it.

## Deploy

GitHub Actions builds `ghcr.io/siliconsaga/skipta` on push to main; apply `k8s/base` with kustomize (in the GDD workspace: `ws k8s apply -k components/skipta/k8s/base -n skipta`).
