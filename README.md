# HIPAA Automated De-identification System

A production-ready prototype that detects and redacts all 18 HIPAA Safe Harbor identifiers from medical documents using LLaMA-3.3-70B (via Groq) + a regex safety-net layer.

\---

## Features

|Feature|Detail|
|-|-|
|**All 18 HIPAA identifiers**|Names, dates, phones, emails, URLs, MRNs, SSNs, ages, addresses, geographic, sample IDs, etc.|
|**Context-aware disambiguation**|Distinguishes phone numbers from sample/barcode IDs based on surrounding text context|
|**OCR pipeline**|Digital PDFs → PyMuPDF; scanned/handwritten images → Tesseract with enhanced preprocessing|
|**Synthetic data generation** *(bonus)*|Replaces PHI with realistic fake Indian names, dates, phones — preserves clinical context|
|**Handwriting OCR** *(bonus)*|Contrast/sharpness enhancement + higher DPI for handwritten text|
|**Compliance Dashboard** *(bonus)*|Cross-document PHI statistics, category breakdown chart, pie chart, per-document audit log|
|**Audit trail**|Every upload logged with filename, timestamp, PHI count, categories, and redaction mode|

\---

## Quick Start

### Prerequisites

* Docker and Docker Compose installed
* A free Groq API key from [console.groq.com](https://console.groq.com)

### 1. Clone and configure

```bash
git clone https://github.com/Sreekar50/AI-Powered-HIPAA-Medical-De-identification-System
cd hipaa-deidentify
cp .env.example .env
# Edit .env and set your GROQ_API_KEY
```

### 2\. Build and run

```bash
docker compose up --build
```

### 3\. Open the app

Navigate to **http://localhost:8000**

\---

## API Endpoints

|Method|Endpoint|Description|
|-|-|-|
|`POST`|`/deidentify`|Upload a file for de-identification|
|`GET`|`/dashboard`|Compliance dashboard data (JSON)|
|`GET`|`/health`|Service health check|

### POST /deidentify parameters

|Parameter|Type|Default|Description|
|-|-|-|-|
|`file`|file|required|PDF, PNG, JPG, TIFF, or TXT|
|`synthetic`|bool|`false`|Enable synthetic data generation|
|`handwriting`|bool|`false`|Enable handwriting OCR enhancement|

\---

## Implementation Design

### Model Choice: LLaMA-3.3-70B via Groq

**Why Groq + LLaMA-3.3-70B:**

* Free tier with fast inference (LPU hardware)
* 70B parameter model provides excellent contextual understanding
* Understands medical terminology and document structure
* Handles inconsistent lab report formatting, names in unexpected positions (e.g. technician names in parentheses), and varied date formats

**Why not a smaller model or rule-based only:**

* Medical reports have inconsistent formatting across labs
* Names appear in unexpected positions (technician names in parentheses, footer signatures, etc.)
* A pure regex approach cannot reliably detect names or contextual PHI

### OCR Pipeline

1. **Digital PDFs** → PyMuPDF (`fitz`) extracts text directly — fast and accurate
2. **Scanned pages** (no extractable text) → PyMuPDF renders page to PNG at 300 DPI → Tesseract OCR
3. **Handwriting mode** → additional preprocessing: grayscale conversion, contrast enhancement (2×), sharpening, 2× upscaling (if width < 1500px), Tesseract with `--oem 1 --psm 6`

### Context Preservation Strategy

The system uses a **two-layer approach** to ensure medical meaning is never lost:

1. **Placeholder mode** (default): PHI → `\[PATIENT\_NAME]`, `\[DATE]`, etc. The placeholder type tells a reader *what kind* of information was there, preserving semantic context.
2. **Synthetic data mode** *(bonus)*: PHI → realistic fake data (Indian names, plausible dates, valid-format phone numbers). The clinical record reads naturally for research/training purposes while containing zero real PHI.

### Phone Number Rule (Absolute)

**Every standalone 10-digit number is always classified as `PHONE_NUMBER` — no exceptions.**

This rule is enforced at three independent layers so it cannot be bypassed by any context or label:

1. **Regex patterns**: The generic sweep uses `\d{10}` to match all 10-digit numbers regardless of starting digit. `SAMPLE_ID` label patterns are explicitly restricted to non-10-digit lengths (6–9 or 11–12 digits), so a 10-digit number after a barcode label still resolves to `PHONE_NUMBER`.
2. **`regex_postprocess()`**: After pattern matching, an absolute override re-checks every matched string — if it is exactly 10 digits, `entity_type` is forced to `PHONE_NUMBER` regardless of which pattern fired.
3. **`call_groq()` post-processing**: After the LLM responds, every returned entity is inspected. If the original text is exactly 10 digits and the LLM labelled it as anything other than `PHONE_NUMBER`, it is silently corrected before being used.

### Sample ID Classification

A number is classified as `SAMPLE_ID` only when **both** conditions are true:

* It appears immediately after an explicit label: `Sample Collection`, `Barcode`, `Specimen ID`, or `Collection ID/No`
* It is **not** exactly 10 digits (i.e. 6–9 or 11–12 digit barcodes only)

### Regex Safety Net

The LLM handles complex contextual cases, but a regex layer runs afterward on the original text to catch anything missed. It covers:

* All 10-digit numbers (`\d{10}`) → `PHONE_NUMBER`
* Explicitly labelled phone/fax/mobile numbers
* Pipe-separated header number pairs (both classified as `PHONE_NUMBER`)
* Email addresses
* Domain names / URLs (including short ones like `Drlogy.com`)
* SSNs (`\d{3}-\d{2}-\d{4}`)
* Sample barcodes (non-10-digit lengths) after explicit labels
* Indian address patterns — inline (e.g. `125, Shivam Bungalow, S G Road, Mumbai`) and all-caps footer addresses with PIN codes
* City names as standalone `GEOGRAPHIC` entities

\---

## Supported HIPAA Safe Harbor Identifiers

1. Names (patient, doctor, staff, technician)
2. Geographic subdivisions (cities, addresses, zip codes)
3. Dates (all forms: registration, collection, DOB, timestamps)
4. Phone numbers
5. Fax numbers
6. Email addresses
7. URLs / website domains
8. Social Security Numbers
9. Medical Record Numbers (MRN, PID, Report ID)
10. Account numbers
11. Certificate / License numbers
12. Vehicle identifiers
13. Device identifiers / serial numbers (Sample/Barcode IDs)
14. Web Universal Resource Locators
15. IP addresses
16. Biometric identifiers
17. Full-face photographs
18. Any other unique identifying number or code

\---

## Project Structure

```
hipaa-deidentify/
├── main.py              # FastAPI backend + all logic
├── static/
│   └── index.html       # Frontend UI (upload + dashboard)
├── audit\_store/
│   └── cumulative\_audit.json   # Persistent audit log (Docker volume)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

\---

## Compliance Notes

* This system implements **HIPAA Safe Harbor** de-identification (45 CFR §164.514(b))
* All processing is server-side; no PHI is sent to any service other than the configured LLM API
* The audit log stores only metadata (filename, PHI counts, categories) — not the original PHI values
* For production use, deploy with HTTPS and access controls
