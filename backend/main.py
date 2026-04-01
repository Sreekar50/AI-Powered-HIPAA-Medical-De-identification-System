"""
HIPAA De-identification System — Backend v6
Model  : Groq LLaMA-3.3-70B  (free, context-aware)
OCR    : PyMuPDF (digital PDF) + Tesseract (scanned/handwritten images)
Extras : Regex post-processor, Synthetic data generation, Compliance Dashboard
"""
import os, re, json, uuid, random
from pathlib import Path
from datetime import datetime, timezone, date
from html import escape as html_escape
from typing import Optional

import fitz
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import io

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from groq import Groq

app = FastAPI(title="HIPAA De-identification System", version="6.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

STATIC_DIR  = Path(__file__).parent / "static"
AUDIT_DIR   = Path(__file__).parent / "audit_store"
AUDIT_DIR.mkdir(exist_ok=True)
AUDIT_FILE  = AUDIT_DIR / "cumulative_audit.json"

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", response_class=HTMLResponse)
def serve_ui():
    return (STATIC_DIR / "index.html").read_text()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
groq_client  = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
GROQ_MODEL   = "llama-3.3-70b-versatile"

SYNTH_PATIENT_NAMES = [
    "Arjun K. Sharma", "Priya R. Mehta", "Rahul S. Gupta", "Anita D. Patel",
    "Suresh V. Nair", "Kavita B. Reddy", "Mohit A. Joshi", "Deepa C. Iyer",
    "Vijay M. Singh", "Sunita P. Rao", "Arun K. Bose", "Rekha J. Menon",
]
SYNTH_DOCTOR_NAMES = [
    "Dr. Amit Verma", "Dr. Sunita Kapoor", "Dr. Rajesh Kumar", "Dr. Priya Singh",
    "Dr. Vikram Patel", "Dr. Ananya Gupta", "Dr. Suresh Nair", "Dr. Leela Sharma",
]
SYNTH_AGES = ["28 Years", "34 Years", "45 Years", "52 Years", "61 Years", "38 Years", "29 Years"]
SYNTH_MRNS = lambda: f"MRN-{random.randint(1000,9999)}"
SYNTH_PHONES = lambda: f"{random.choice(['98','97','96','95','94','93','92','91','90','89'])}{random.randint(10000000,99999999)}"
SYNTH_EMAILS = lambda n: f"patient{random.randint(100,999)}@healthsys.in"
SYNTH_DATES = [
    "15 Jan, 20XX", "22 Mar, 20XX", "08 Jun, 20XX",
    "30 Sep, 20XX", "11 Nov, 20XX", "04 Feb, 20XX",
]
SYNTH_ADDRESSES = [
    "42, Green Park Colony, MG Road, [CITY]",
    "17/A, Sunrise Apartments, Station Road, [CITY]",
    "Plot 8, Health Nagar, Ring Road, [CITY]",
]
SYNTH_CITIES = ["Cityville", "Medtown", "Healthpur", "Careville"]

_synth_counters: dict = {}

def next_synth(entity_type: str) -> str:
    """Return a consistent synthetic replacement for the Nth occurrence."""
    idx = _synth_counters.get(entity_type, 0)
    _synth_counters[entity_type] = idx + 1
    if entity_type == "PATIENT_NAME":
        return SYNTH_PATIENT_NAMES[idx % len(SYNTH_PATIENT_NAMES)]
    if entity_type == "DOCTOR_NAME":
        return SYNTH_DOCTOR_NAMES[idx % len(SYNTH_DOCTOR_NAMES)]
    if entity_type == "AGE":
        return SYNTH_AGES[idx % len(SYNTH_AGES)]
    if entity_type == "MEDICAL_RECORD_NUMBER":
        return SYNTH_MRNS()
    if entity_type == "PHONE_NUMBER":
        return SYNTH_PHONES()
    if entity_type == "EMAIL_ADDRESS":
        return SYNTH_EMAILS(idx)
    if entity_type == "DATE":
        return SYNTH_DATES[idx % len(SYNTH_DATES)]
    if entity_type == "ADDRESS":
        city = random.choice(SYNTH_CITIES)
        return SYNTH_ADDRESSES[idx % len(SYNTH_ADDRESSES)].replace("[CITY]", city)
    if entity_type == "GEOGRAPHIC":
        return random.choice(SYNTH_CITIES)
    return REPLACEMENTS.get(entity_type, "[REDACTED]")

COLORS = {
    "PATIENT_NAME":          "#ff6b6b",
    "DOCTOR_NAME":           "#ff9f43",
    "DATE":                  "#ffd93d",
    "PHONE_NUMBER":          "#74b9ff",
    "FAX_NUMBER":            "#74b9ff",
    "EMAIL_ADDRESS":         "#a29bfe",
    "URL":                   "#55efc4",
    "MEDICAL_RECORD_NUMBER": "#e17055",
    "SAMPLE_ID":             "#fd7272",
    "AGE":                   "#fd79a8",
    "ADDRESS":               "#6bcb77",
    "GEOGRAPHIC":            "#badc58",
    "ACCOUNT_NUMBER":        "#f9ca24",
    "LICENSE_NUMBER":        "#e056fd",
    "SSN":                   "#eb4d4b",
}
PHI_LABELS = {
    "PATIENT_NAME":          "Patient Name",
    "DOCTOR_NAME":           "Doctor / Staff Name",
    "DATE":                  "Date",
    "PHONE_NUMBER":          "Phone Number",
    "FAX_NUMBER":            "Fax Number",
    "EMAIL_ADDRESS":         "Email Address",
    "URL":                   "URL / Website",
    "MEDICAL_RECORD_NUMBER": "Medical Record Number",
    "SAMPLE_ID":             "Sample / Barcode ID",
    "AGE":                   "Age",
    "ADDRESS":               "Full Address",
    "GEOGRAPHIC":            "Geographic Location",
    "ACCOUNT_NUMBER":        "Account Number",
    "LICENSE_NUMBER":        "License Number",
    "SSN":                   "Social Security Number",
}
REPLACEMENTS = {
    "PATIENT_NAME":          "[PATIENT_NAME]",
    "DOCTOR_NAME":           "[DOCTOR_NAME]",
    "DATE":                  "[DATE]",
    "PHONE_NUMBER":          "[PHONE_NUMBER]",
    "FAX_NUMBER":            "[FAX_NUMBER]",
    "EMAIL_ADDRESS":         "[EMAIL]",
    "URL":                   "[URL]",
    "MEDICAL_RECORD_NUMBER": "[MEDICAL_RECORD_NO]",
    "SAMPLE_ID":             "[SAMPLE_ID]",
    "AGE":                   "[AGE]",
    "ADDRESS":               "[ADDRESS]",
    "GEOGRAPHIC":            "[LOCATION]",
    "ACCOUNT_NUMBER":        "[ACCOUNT_NO]",
    "LICENSE_NUMBER":        "[LICENSE_NO]",
    "SSN":                   "[SSN]",
}



REGEX_PATTERNS = [
    # Email addresses
    (r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b', "EMAIL_ADDRESS"),

    #  Domain names / URLs
    (r'\b(?:www\.)?[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?'
     r'\.(?:com|org|net|in|edu|gov|io|co\.in|health|care|med|clinic|lab)\b',
     "URL"),

    #  SAMPLE / BARCODE IDs — only non-10-digit sequences after explicit labels.
    #    Negative lookahead/lookbehind ensures we never match exactly 10 digits.
    #    Pattern: 6-9 digits OR 11-12 digits (not 10).
    (r'(?i)(?:sample\s+collection|barcode|specimen\s*(?:id|no)|'
     r'collection\s*(?:id|no))[:\s#]*(\d{6,9}|\d{11,12})\b',
     "SAMPLE_ID"),

    # PHONE NUMBERS — ABSOLUTE RULE: every standalone 10-digit number.

    # 1. Explicitly labelled phone/fax/mobile — any 10-digit number
    (r'(?i)(?:phone|tel|mob(?:ile)?|fax|contact)[:\s]*(\d{10})\b', "PHONE_NUMBER"),

    (r'\b(\d{10})\b(?=\s*\|)', "PHONE_NUMBER"),
    (r'(?<=\|\s)\b(\d{10})\b',  "PHONE_NUMBER"),

    # 3. Generic sweep — ANY standalone 10-digit number, any starting digit.
    #    This is the catch-all and runs after SAMPLE_ID patterns, but since
    #    SAMPLE_ID patterns are restricted to non-10-digit lengths, there is
    #    no conflict.
    (r'\b(\d{10})\b', "PHONE_NUMBER"),

    # SSN
    (r'\b\d{3}-\d{2}-\d{4}\b', "SSN"),

    # Pattern A — inline patient / collection address
    (
        r'(?i)\b(?:\d[\w/\-]*\s*,\s*)?'
        r'[\w\s\.\-/]{3,40},\s*'
        r'[\w\s\.\-/]{2,40}'
        r'(?:,\s*[\w\s\.\-/]{2,40})*'
        r'(?:,\s*(?:' + '|'.join([
            "Mumbai", "Delhi", "Bangalore", "Vijayapura", "Hyderabad",
            "Chennai", "Kolkata", "Pune", "Ahmedabad", "Jaipur",
            "Surat", "Lucknow", "Kanpur", "Nagpur", "Vadodara",
        ]) + r')|\s*[\u2013\-]\s*\d{6})\b',
        "ADDRESS",
    ),

    # Pattern B — all-caps footer/lab address with PIN
    (
        r'(?:[A-Z][A-Z0-9\.\-/]*(?:\s+[A-Z][A-Z0-9\.\-/]*)+\s*,\s*){2,}'
        r'[A-Z][A-Z0-9\.\-/]*(?:\s+[A-Z][A-Z0-9\.\-/]*)*'
        r'(?:\s*[\u2013\-]\s*\d{6})?',
        "ADDRESS",
    ),
]

CITY_NAMES = [
    "Mumbai", "Delhi", "Bangalore", "Vijayapura", "Hyderabad",
    "Chennai", "Kolkata", "Pune", "Ahmedabad", "Jaipur",
    "Surat", "Lucknow", "Kanpur", "Nagpur", "Vadodara",
]



SYSTEM_PROMPT = r"""You are a HIPAA Safe Harbor de-identification expert. Identify ALL 18 categories of Protected Health Information (PHI) in medical document text.

=== THE 18 HIPAA SAFE HARBOR IDENTIFIERS ===
1. NAMES — patient, doctor, staff, technician names
2. GEOGRAPHIC — any geographic subdivision smaller than a state: cities, towns, districts, streets, zip codes, addresses
3. DATES — all dates related to the individual: DOB, admission, discharge, registration, collection, reporting dates; months + years; combined date-times
4. PHONE_NUMBER — all telephone and fax numbers (any format: with/without dashes, spaces, parentheses)
5. FAX_NUMBER — fax numbers
6. EMAIL_ADDRESS — any email address
7. URL — websites, domain names including short ones without "www": "Drlogy.com", "www.example.com"
8. SSN — Social Security Numbers
9. MEDICAL_RECORD_NUMBER — patient IDs, MRN, PID, Report ID, registration numbers assigned to patients
10. ACCOUNT_NUMBER — bank or health plan account numbers
11. SAMPLE_ID — collection barcodes, specimen IDs, sample tracking numbers that are NOT 10 digits long
12. AGE — patient age when expressed as a value (e.g., "21 Years", "39y", "/ 39y", "Age: 21")
13. LICENSE_NUMBER — medical license, professional license numbers
14. VEHICLE_IDENTIFIER — vehicle IDs, license plates
15. IP_ADDRESS — IP addresses
16. BIOMETRIC — fingerprints, retinal scans
17. PHOTO — full face photographs
18. OTHER_UID — any other unique identifying number or code

=== CRITICAL RULES — READ CAREFULLY ===

ALWAYS FLAG:
- Patient names → PATIENT_NAME
- Doctor/staff/technician names → DOCTOR_NAME
- Ages: "21 Years", "39y", "Male / 39y" → AGE (flag only the age part, not "Male")
- All calendar dates and date+time combos → DATE

PHONE NUMBERS — ABSOLUTE RULE, NO EXCEPTIONS:
  *** ANY 10-digit number is ALWAYS a PHONE_NUMBER. ***
  *** There are NO exceptions to this rule. ***
  *** Even if a 10-digit number appears after "Sample Collection", "Barcode",  ***
  *** "Specimen ID", or any other label — it is still PHONE_NUMBER, not SAMPLE_ID. ***

  Examples:
  - "0123456789" anywhere in the document → PHONE_NUMBER
  - "0912345678" in the lab header → PHONE_NUMBER
  - "7411783298" after "Phone:" → PHONE_NUMBER
  - "7795598177" near a phone icon → PHONE_NUMBER
  - "0123456789 | 0912345678" (pipe-separated) → BOTH are PHONE_NUMBER
  - "Sample Collection: 0123456789" → the 10-digit number is PHONE_NUMBER (NOT SAMPLE_ID)

SAMPLE_ID RULE:
  Only flag a number as SAMPLE_ID if BOTH conditions are true:
  1. It appears immediately after an explicit label: "Sample Collection", "Barcode",
     "Specimen ID", or "Collection ID/No"
  2. It is NOT exactly 10 digits (e.g. 6, 7, 8, 9, 11, or 12 digit barcodes)

ADDRESSES — ALWAYS FLAG full address strings:
- Patient collection addresses like "125, Shivam Bungalow, S G Road, Mumbai" → ADDRESS
- Lab footer addresses like "105-108, SMART VISION COMPLEX, HEALTHCARE ROAD,
  OPPOSITE HEALTHCARE COMPLEX. MUMBAI - 689578" → ADDRESS
- Multi-line addresses like "B.M. NAGTHAN BUILDING, OPP KANNAT MASJID,
  J.M. ROAD, NEAR BADI KAMAN, VIJAYAPURA – 586101" → ADDRESS
- Flag the full address string as a single ADDRESS entity, not piecemeal.
- City / place names that appear as part of an address → GEOGRAPHIC (if separate)
  or included in the ADDRESS entity (if inline).

OTHER:
- Emails → EMAIL_ADDRESS
- Domain names/URLs including short ones: "Drlogy.com", "www.drlogy.com" → URL
- Patient/Report IDs: "PID : 555", "Report ID: 725" → MEDICAL_RECORD_NUMBER

NEVER FLAG:
- Medical qualifications: "MD", "DMLT", "BMLT"
- Lab reference ranges: "4.5 - 5.5", "00 - 300", "150000 - 410000"
- Lab result numeric values
- Instrument names: "Mindray 300"
- Lab/hospital ORGANISATION names (e.g. "DRLOGY PATHOLOGY LAB", "DR. N.M. KAZI MEDICAL LABORATORY")
- Result flags: "High", "Low"
- Units: "%", "g/dL", "cells/mcL"
- Test/section names: "HEMOGLOBIN", "CBC", "LIPID PROFILE"
- "SELF", "Calculated", "Blood", "Male", "Female"
- Business hours like "8 AM TO 11 PM"
- "Page 1 of 1"

=== OUTPUT FORMAT ===
Return ONLY a valid JSON array. No markdown fences, no explanation.
Each object: {"original": "exact text as it appears", "entity_type": "TYPE", "replacement": "[PLACEHOLDER]"}

Entity types → replacements:
PATIENT_NAME → [PATIENT_NAME]
DOCTOR_NAME → [DOCTOR_NAME]
DATE → [DATE]
PHONE_NUMBER → [PHONE_NUMBER]
FAX_NUMBER → [FAX_NUMBER]
EMAIL_ADDRESS → [EMAIL]
URL → [URL]
MEDICAL_RECORD_NUMBER → [MEDICAL_RECORD_NO]
SAMPLE_ID → [SAMPLE_ID]
AGE → [AGE]
ADDRESS → [ADDRESS]
GEOGRAPHIC → [LOCATION]
ACCOUNT_NUMBER → [ACCOUNT_NO]
LICENSE_NUMBER → [LICENSE_NO]
SSN → [SSN]

If nothing found: []"""


def call_groq(text: str) -> list:
    if not groq_client:
        raise RuntimeError("GROQ_API_KEY not configured. See .env.example.")

    resp = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        temperature=0.0,
        max_tokens=4096,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"De-identify this medical document:\n\n{text[:60000]}"},
        ],
    )
    raw = resp.choices[0].message.content.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw).strip()

    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        items = json.loads(m.group()) if m else []

    seen, clean = set(), []
    for d in items:
        if not isinstance(d, dict):
            continue
        orig = d.get("original", "").strip()
        if not orig or orig in seen:
            continue
        seen.add(orig)

        entity_type = d.get("entity_type", "PATIENT_NAME")

        # Hard enforcement: if the LLM labelled a 10-digit number as anything
        #    other than PHONE_NUMBER, correct it here unconditionally.
        if re.fullmatch(r'\d{10}', orig) and entity_type != "PHONE_NUMBER":
            entity_type = "PHONE_NUMBER"

        clean.append({
            "original":    orig,
            "entity_type": entity_type,
            "replacement": REPLACEMENTS.get(entity_type, "[REDACTED]"),
        })
    return clean


def regex_postprocess(text: str, already_found: set) -> list:
    """
    Regex safety net.

    v6 guarantee: every 10-digit number is PHONE_NUMBER.
    - SAMPLE_ID patterns are restricted to non-10-digit lengths (6-9, 11-12).
    - The generic \d{10} sweep catches everything else.
    - No context-based reclassification is performed — the rule is absolute.
    """
    extra = []
    seen  = set(already_found)

    for pattern, entity_type in REGEX_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            orig = (m.group(1) if m.lastindex and m.lastindex >= 1
                    and m.group(1) else m.group(0)).strip()
            if not orig or orig in seen:
                continue
            if orig.startswith("[") and orig.endswith("]"):
                continue
            # Skip bare reference-range strings like "4.5 - 5.5"
            if re.fullmatch(r'\d+\s*-\s*\d+', orig):
                continue

            # Absolute 10-digit rule
            # If the matched text is exactly 10 digits, it is PHONE_NUMBER
            # regardless of which pattern triggered and what label surrounds it.
            if re.fullmatch(r'\d{10}', orig):
                entity_type = "PHONE_NUMBER"

            seen.add(orig)
            extra.append({
                "original":    orig,
                "entity_type": entity_type,
                "replacement": REPLACEMENTS.get(entity_type, "[REDACTED]"),
            })

    #City-name safety net
    for city in CITY_NAMES:
        pat = r'\b' + re.escape(city) + r'\b'
        for m in re.finditer(pat, text, re.IGNORECASE):
            orig = m.group(0)
            if orig in seen:
                continue
            before = text[max(0, m.start()-20):m.start()]
            if "[" in before:
                continue
            seen.add(orig)
            extra.append({
                "original":    orig,
                "entity_type": "GEOGRAPHIC",
                "replacement": "[LOCATION]",
            })

    return extra


def apply_redactions(text: str, detections: list, synthetic: bool = False) -> str:
    """Apply redactions. If `synthetic=True`, replace with realistic fake data."""
    repl_map = {}
    _synth_counters.clear()

    for d in sorted(detections, key=lambda x: len(x["original"]), reverse=True):
        orig = d["original"]
        if synthetic:
            repl_map[orig] = next_synth(d["entity_type"])
        else:
            repl_map[orig] = d["replacement"]

    for orig, repl in sorted(repl_map.items(), key=lambda x: len(x[0]), reverse=True):
        text = text.replace(orig, repl)
    return text


def build_highlighted_html(text: str, detections: list) -> str:
    spans, used = [], []
    for d in sorted(detections, key=lambda x: len(x["original"]), reverse=True):
        orig, et = d["original"], d["entity_type"]
        pos = 0
        while True:
            p = text.find(orig, pos)
            if p == -1:
                break
            e = p + len(orig)
            if not any(s < e and en > p for s, en in used):
                spans.append((p, e, et))
                used.append((p, e))
            pos = p + 1

    spans.sort(key=lambda x: x[0])
    html, last = "", 0
    for (p, e, et) in spans:
        if p < last:
            continue
        html += html_escape(text[last:p])
        color = COLORS.get(et, "#dfe6e9")
        label = PHI_LABELS.get(et, et)
        html += (
            f'<mark style="background:{color};padding:1px 5px;border-radius:3px;'
            f'cursor:help;" title="{label}">'
            f'{html_escape(text[p:e])}</mark>'
        )
        last = e
    html += html_escape(text[last:])
    return html


def preprocess_for_handwriting(img: Image.Image) -> Image.Image:
    """Apply preprocessing optimised for handwritten text recognition."""
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)
    w, h = img.size
    if w < 1500:
        img = img.resize((w * 2, h * 2), Image.LANCZOS)
    return img


def image_to_text_enhanced(data: bytes, handwriting_mode: bool = False) -> str:
    """OCR with optional handwriting enhancement."""
    img = Image.open(io.BytesIO(data))
    if handwriting_mode:
        img_proc = preprocess_for_handwriting(img)
        config = r'--oem 1 --psm 6'
        text = pytesseract.image_to_string(img_proc, config=config)
    else:
        text = pytesseract.image_to_string(img)
    return text


def pdf_to_text(data: bytes, handwriting_mode: bool = False) -> str:
    doc = fitz.open(stream=data, filetype="pdf")
    pages = []
    for page in doc:
        t = page.get_text()
        if t.strip():
            pages.append(t)
        else:
            pix = page.get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            pages.append(image_to_text_enhanced(img_bytes, handwriting_mode=handwriting_mode))
    doc.close()
    return "\n".join(pages)


def load_audit_store() -> list:
    if AUDIT_FILE.exists():
        try:
            return json.loads(AUDIT_FILE.read_text())
        except Exception:
            return []
    return []


def save_audit_entry(entry: dict):
    store = load_audit_store()
    store.append(entry)
    if len(store) > 500:
        store = store[-500:]
    AUDIT_FILE.write_text(json.dumps(store, indent=2))


def deidentify(text: str, synthetic: bool = False, filename: str = "unknown") -> dict:
    # Step 1: LLM context-aware detection
    llm_detections = call_groq(text)
    already_found  = {d["original"] for d in llm_detections}

    # Step 2: Regex safety net on ORIGINAL text
    regex_detections = regex_postprocess(text, already_found)

    # Merge
    all_detections = llm_detections + regex_detections

    # Step 3: Apply redactions (placeholder or synthetic)
    highlighted = build_highlighted_html(text, all_detections)
    redacted    = apply_redactions(text, all_detections, synthetic=synthetic)

    # Build report
    by_cat: dict = {}
    for d in all_detections:
        by_cat.setdefault(d["entity_type"], []).append({
            "value":       d["original"],
            "replaced_by": d["replacement"] if not synthetic else next_synth(d["entity_type"]),
        })

    report = {
        "total_phi_detected": len(all_detections),
        "phi_by_category":    {k: len(v) for k, v in by_cat.items()},
        "details":            by_cat,
        "processed_at":       datetime.now(timezone.utc).isoformat(),
        "mode":               "synthetic" if synthetic else "placeholder",
    }

    audit_entry = {
        "id":               str(uuid.uuid4())[:8],
        "filename":         filename,
        "processed_at":     report["processed_at"],
        "total_phi":        report["total_phi_detected"],
        "phi_by_category":  report["phi_by_category"],
        "mode":             report["mode"],
    }
    save_audit_entry(audit_entry)

    return {
        "original_text":        text,
        "redacted_text":        redacted,
        "highlighted_original": highlighted,
        "report":               report,
    }


@app.post("/deidentify")
async def deidentify_file(
    file: UploadFile = File(...),
    synthetic: bool = Query(False, description="Use synthetic data generation instead of placeholders"),
    handwriting: bool = Query(False, description="Enable handwriting OCR enhancement"),
):
    data = await file.read()
    name = (file.filename or "unknown").lower()
    try:
        if name.endswith(".pdf"):
            text = pdf_to_text(data, handwriting_mode=handwriting)
        elif name.endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp")):
            text = image_to_text_enhanced(data, handwriting_mode=handwriting)
        elif name.endswith(".txt"):
            text = data.decode("utf-8", errors="replace")
        else:
            raise HTTPException(400, "Unsupported format. Use PDF, image, or .txt")

        if not text.strip():
            raise HTTPException(400, "No text could be extracted.")

        return JSONResponse(deidentify(text, synthetic=synthetic, filename=file.filename or "unknown"))

    except RuntimeError as exc:
        raise HTTPException(500, str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Processing error: {exc}")


@app.get("/dashboard")
def compliance_dashboard():
    """Return aggregated compliance stats across all processed documents."""
    store = load_audit_store()
    if not store:
        return JSONResponse({"entries": [], "summary": {}})

    total_phi = sum(e.get("total_phi", 0) for e in store)
    category_totals: dict = {}
    for e in store:
        for cat, cnt in e.get("phi_by_category", {}).items():
            category_totals[cat] = category_totals.get(cat, 0) + cnt

    return JSONResponse({
        "entries":  store[-50:],
        "summary": {
            "total_documents":  len(store),
            "total_phi_items":  total_phi,
            "category_totals":  category_totals,
        },
    })


@app.get("/health")
def health():
    return {"status": "ok", "model": GROQ_MODEL, "api_key_set": bool(GROQ_API_KEY)}
