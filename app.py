"""
H&G Invoice Email Sync Server
==============================
Receives forwarded invoice emails from Power Automate,
extracts PDF attachment, reads with Claude AI,
pushes invoice data to Firebase Realtime Database.

Deploy to Railway.app — free tier is enough.
"""

import os
import json
import base64
import httpx
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import anthropic
import firebase_admin
from firebase_admin import credentials, db as firebase_db

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="H&G Invoice Sync Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Firebase init ──────────────────────────────────────────────────────────────
FIREBASE_URL = os.environ.get("FIREBASE_URL", "https://hg-invoices-default-rtdb.asia-southeast1.firebasedatabase.app")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Firebase service account JSON stored as env var
fb_cred_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")
if fb_cred_json and not firebase_admin._apps:
    try:
        cred_dict = json.loads(fb_cred_json)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_URL})
        print("✅ Firebase initialized")
    except Exception as e:
        print(f"⚠️ Firebase init error: {e}")

# ── Claude AI PDF reader ───────────────────────────────────────────────────────
async def parse_invoice_pdf(pdf_base64: str) -> list[dict]:
    """Use Claude to extract all invoices from PDF."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = """Extract ALL invoices from this H&G DEVELOPMENT ENTERPRISE invoice PDF.
Return ONLY a valid JSON array, no markdown, no explanation.

Each invoice:
{
  "invoiceNo": "INV2603/001",
  "clientName": "J.T.RAYA HARDWARE",
  "date": "2026-03-02",
  "amount": 9219.00,
  "deliveries": [
    {
      "date": "2026-03-02",
      "mNo": "MBT003",
      "plate": "QMG4267",
      "tonnes": 10.5,
      "doNo": "8596",
      "site": "DESA MURNI PERMYJAYA",
      "gang": ""
    }
  ]
}

Rules:
- Extract ALL invoices, not just the first
- date format: YYYY-MM-DD
- amount: number only, no RM/commas
- gang: "P" if carry/pikul, "" if normal
- Merge multi-page invoices (same invoiceNo) into one entry"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_base64
                    }
                },
                {"type": "text", "text": prompt}
            ]
        }]
    )

    text = "".join(b.text for b in response.content if hasattr(b, "text"))
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)

# ── Firebase helpers ───────────────────────────────────────────────────────────
def push_invoices_to_firebase(invoices: list[dict]) -> dict:
    """Push parsed invoices to Firebase under /hg_invoices/"""
    ref = firebase_db.reference("hg_invoices")
    existing_raw = ref.get() or {}

    # Build lookup of existing invoice numbers
    existing = {}
    for key, val in existing_raw.items():
        if isinstance(val, dict) and "invoiceNo" in val:
            existing[val["invoiceNo"]] = key

    added = 0
    skipped = 0

    for inv in invoices:
        inv_no = inv.get("invoiceNo", "")
        if not inv_no or not inv.get("amount"):
            continue
        if inv_no in existing:
            skipped += 1
            continue
        # Add metadata
        inv["paid"] = False
        inv["paidDate"] = None
        inv["paidRef"] = None
        inv["slipUrl"] = None
        inv["syncedAt"] = {".sv": "timestamp"}
        ref.push(inv)
        added += 1

    return {"added": added, "skipped": skipped, "total": len(invoices)}

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "H&G Invoice Sync Server"}

@app.get("/health")
def health():
    return {"status": "healthy", "firebase": bool(firebase_admin._apps)}


@app.post("/webhook/email")
async def receive_email_webhook(request: Request):
    """
    Receives POST from Power Automate when new invoice email arrives.
    Expected JSON body:
    {
        "subject": "Invoice INV2603/001",
        "from": "hgdevelopmententerprise@hotmail.com",
        "attachments": [
            {
                "name": "Invoice INV2603001.pdf",
                "contentBytes": "<base64 encoded PDF>"
            }
        ]
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Security: verify secret token
    secret = request.headers.get("X-Webhook-Secret", "")
    expected = os.environ.get("WEBHOOK_SECRET", "hg_cement_sync_2026")
    if secret != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    attachments = body.get("attachments", [])
    if not attachments:
        return {"status": "no_attachments", "message": "No PDF attachments found"}

    all_results = []
    for attachment in attachments:
        name = attachment.get("name", "")
        content = attachment.get("contentBytes", "")

        # Only process PDFs
        if not name.lower().endswith(".pdf") and "pdf" not in attachment.get("contentType", ""):
            continue
        if not content:
            continue

        try:
            # Parse PDF with Claude AI
            invoices = await asyncio.to_thread(parse_invoice_pdf, content)
            if not invoices:
                all_results.append({"file": name, "status": "no_invoices_found"})
                continue

            # Push to Firebase
            result = push_invoices_to_firebase(invoices)
            all_results.append({"file": name, "status": "success", **result})

        except Exception as e:
            all_results.append({"file": name, "status": "error", "error": str(e)})

    return {"status": "processed", "results": all_results}


@app.post("/webhook/manual")
async def manual_pdf_upload(request: Request):
    """
    Manual PDF upload endpoint — called directly from the H&G app
    when user uploads a PDF in the Import tab.
    Body: { "pdfBase64": "<base64>", "filename": "invoice.pdf" }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    pdf_b64 = body.get("pdfBase64", "")
    if not pdf_b64:
        raise HTTPException(status_code=400, detail="No PDF data")

    try:
        invoices = await asyncio.to_thread(parse_invoice_pdf, pdf_b64)
        if not invoices:
            return {"status": "no_invoices_found", "invoices": []}
        result = push_invoices_to_firebase(invoices)
        return {"status": "success", **result, "invoices": invoices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/invoices")
def get_invoices():
    """Get all invoices from Firebase — for app to sync from."""
    try:
        ref = firebase_db.reference("hg_invoices")
        data = ref.get() or {}
        invoices = []
        for key, val in data.items():
            if isinstance(val, dict):
                val["_fbKey"] = key
                invoices.append(val)
        return {"status": "ok", "count": len(invoices), "invoices": invoices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/invoices/{fb_key}")
async def update_invoice(fb_key: str, request: Request):
    """Update invoice payment status from the app."""
    try:
        body = await request.json()
        ref = firebase_db.reference(f"hg_invoices/{fb_key}")
        ref.update(body)
        return {"status": "updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
