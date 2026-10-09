import os
import re
import json
import csv
import hmac
from zoneinfo import ZoneInfo
import difflib
import unicodedata
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from supabase import create_client, Client
from groq import Groq
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import pandas as pd
from io import BytesIO, StringIO
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors

load_dotenv()

EAT = ZoneInfo("Africa/Mogadishu")

def now_eat():
    return datetime.now(EAT)

def today_eat():
    return now_eat().date()

# Setup the core application framework
app = FastAPI()

# Securely load credentials from Render's Environment panel variables
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

INSTANCE_ID = os.getenv("GREEN_API_INSTANCE_ID", "710722758620")
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN", "")
GREEN_API_BASE = os.getenv("GREEN_API_BASE", "https://7107.api.greenapi.com")

SYSTEM_PROMPT = """You are Daynjir, a Somali debt management assistant for small shopkeepers. 
Extract transaction intent from chaotic, unstructured Somali text into raw JSON. 
Do not include any conversational filler, markdown syntax, or backticks.

Extract ALL debt entries from the message.
For each entry, extract: customer_name, amount, promised_date (YYYY-MM-DD), phone_number

ALWAYS return a JSON array, even for single entries.

Response format (JSON array):
[
  {"action": "ADD" or "PAY" or "LIST" or "SEARCH" or "EDIT" or "DELETE" or "HISTORY" or "REPORT" or "EXPORT", "customer_name": "string or null", "amount": number or null, "days_until_due": number or null, "customer_phone": "string or null", "promised_date": "YYYY-MM-DD or null", "filter_date": "YYYY-MM-DD or null", "filter_type": "today" or "tomorrow" or "date" or "week" or "month" or null, "new_amount": number or null, "new_date": "YYYY-MM-DD or null", "new_phone": "string or null", "payment_type": "FULL" or "PARTIAL" or "UNKNOWN" or null}
]

Examples - ADD:
'Cali 20$ oo bari ah' -> Use today's date + 1 day for promised_date
'Cali $34 oct 8, Axmed $50 oct 9' -> [{"action": "ADD", "customer_name": "Cali", "amount": 34, "days_until_due": 1, "customer_phone": null, "promised_date": "YYYY-MM-DD", "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}, {"action": "ADD", "customer_name": "Axmed", "amount": 50, "days_until_due": 2, "customer_phone": null, "promised_date": "YYYY-MM-DD", "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]

Examples - PAY:
'Cali wuu bixiyay' -> [{"action": "PAY", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null, "payment_type": "FULL"}]
'Gaawe wuxuu bixiyay $5' -> [{"action": "PAY", "customer_name": "Gaawe", "amount": 5, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null, "payment_type": "PARTIAL"}]
'Cali wuu bixiyay, Axmed wuu bixiyay' -> [{"action": "PAY", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}, {"action": "PAY", "customer_name": "Axmed", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]
'Cali wuxuu bixiyay $10, Axmed wuxuu bixiyay $20' -> [{"action": "PAY", "customer_name": "Cali", "amount": 10, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}, {"action": "PAY", "customer_name": "Axmed", "amount": 20, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]

Examples - LIST:
'Liiska deynta' -> [{"action": "LIST", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]
'Balamaha maanta' -> Use today's date for filter_date
'Balamaha berri' -> Use today's date + 1 day for filter_date
'Balamaha Oct 15' -> [{"action": "LIST", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": "2026-10-15", "filter_type": "date", "new_amount": null, "new_date": null, "new_phone": null}]

Examples - SEARCH:
'Cali' (when Cali exists in debts) -> [{"action": "SEARCH", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]
'Show Cali debt' -> [{"action": "SEARCH", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]

Examples - EDIT:
'edit Cali $50' -> [{"action": "EDIT", "customer_name": "Cali", "amount": 50, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": 50, "new_date": null, "new_phone": null}]
'edit Cali oct 20' -> [{"action": "EDIT", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": "2026-10-20", "filter_date": null, "filter_type": null, "new_amount": null, "new_date": "2026-10-20", "new_phone": null}]
'edit Cali $50 oct 20' -> [{"action": "EDIT", "customer_name": "Cali", "amount": 50, "days_until_due": null, "customer_phone": null, "promised_date": "2026-10-20", "filter_date": null, "filter_type": null, "new_amount": 50, "new_date": "2026-10-20", "new_phone": null}]

Examples - DELETE:
'delete Cali' -> [{"action": "DELETE", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]
'remove Cali' -> [{"action": "DELETE", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]

Examples - HISTORY:
'Cali history' -> [{"action": "HISTORY", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]
'Cali taariikh' -> [{"action": "HISTORY", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]
'payment history Cali' or 'statement Cali' or 'Cali xisaab' -> HISTORY for Cali

Examples - REPORT:
'Bishan report' -> [{"action": "REPORT", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": "month", "new_amount": null, "new_date": null, "new_phone": null}]
'Todobaadkan report' -> [{"action": "REPORT", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": "week", "new_amount": null, "new_date": null, "new_phone": null}]
'Weekly report' -> [{"action": "REPORT", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": "week", "new_amount": null, "new_date": null, "new_phone": null}]
'Monthly report' -> [{"action": "REPORT", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": "month", "new_amount": null, "new_date": null, "new_phone": null}]

Examples - EXPORT:
'Export' -> [{"action": "EXPORT", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]
'Download debts' -> [{"action": "EXPORT", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]

Examples - PHONE:
'Cali 615123456' -> [{"action": "ADD", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": "615123456", "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": "615123456"}]
'Save Cali phone 615123456' -> [{"action": "ADD", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": "615123456", "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": "615123456"}]

Somali casual-language rules (understand spelling mistakes and informal phrasing):
- "Yuusuf $30 amaah ah ayuu qaatay" -> ADD, customer_name="Yuusuf", amount=30.
- "Jaamac 60 ayuu iga qaatay" -> ADD, customer_name="Jaamac", amount=60.
- "Axmed $10 deyn ah" -> ADD, customer_name="Axmed", amount=10.
- "Cali ka jar $10" -> PAY, customer_name="Cali", amount=10, payment_type="PARTIAL".
- "Cali waan ka helay $10" -> PAY, customer_name="Cali", amount=10, payment_type="PARTIAL".
- "Cali wuxuu bixiyay $10" -> PAY, customer_name="Cali", amount=10, payment_type="PARTIAL".
- "Cali wuu bixiyay" or "Cali deyntii oo dhan wuu bixiyay" -> PAY, customer_name="Cali", amount=null, payment_type="FULL".
- "Cali waan ka helay" without an amount -> PAY, customer_name="Cali", amount=null, payment_type="UNKNOWN". Do not assume full payment; ask how much was received.
- "Cali deyntiisa ka dhig $50" -> EDIT, customer_name="Cali", new_amount=50.
- "Cali balantiisa ka dhig 2026-10-20" -> EDIT, customer_name="Cali", new_date="2026-10-20".
- "Cali deynta $50 ka dhig, balantana 2026-10-20" -> EDIT with new_amount=50 and new_date="2026-10-20".

PAYMENT SAFETY:
- Return the field payment_type for every entry: "FULL", "PARTIAL", "UNKNOWN", or null.
- Use FULL only when the message clearly means the entire debt was paid.
- If a payment amount is stated, use PARTIAL; the code will cap it at the outstanding balance.
- If the message suggests money was received but gives no amount and does not clearly say the entire debt was paid, use UNKNOWN.
- Do not confuse taking/borrowing money (ADD) with paying money back (PAY).
- For EDIT, use new_amount and new_date. For ADD/PAY, use amount.
- If intent is unclear, choose SEARCH only when the user is asking about a debt; otherwise ask for clarification rather than changing data.

CUSTOMER NAME EXTRACTION RULES:
- Extract the complete customer name, including first and second names, whenever provided.
- For HISTORY, PAY, EDIT, and DELETE, remove only command/action words; do not drop other words that may be part of the name.
- Example: "Bagadh mamulka history" -> action="HISTORY", customer_name="Bagadh mamulka".
- Example: "Delete Dhakalaf" -> action="DELETE", customer_name="Dhakalaf".
- Example: "Bagadh mamulka wuxuu bixiyay $90" -> action="PAY", customer_name="Bagadh mamulka", amount=90.
- Never return only the last word of a multi-word customer name when the full name appears in the message.

Also support English:
'Add debt' = ADD action
'List debts' = LIST action
'Pay' = PAY action
'Search' = SEARCH action
'Edit' = EDIT action
'Delete' = DELETE action
'History' = HISTORY action
'Report' = REPORT action
'Export' = EXPORT action
"""

def send_whatsapp(to_phone: str, message: str):
    clean_phone = str(to_phone).lstrip("+").split("@")[0].strip()
    if not GREEN_API_TOKEN:
        print("❌ GREEN_API_TOKEN is not configured in environment variables")
        return
    url = f"{GREEN_API_BASE}/waInstance{INSTANCE_ID}/sendMessage/{GREEN_API_TOKEN}"
    chat_id = f"{clean_phone}@c.us"
    payload = {"chatId": chat_id, "message": message}
    print(f"🔍 send_whatsapp called:")
    print(f"   to_phone: {to_phone}")
    print(f"   clean_phone: {clean_phone}")
    print(f"   chat_id: {chat_id}")
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"📡 Green-API Status: {res.status_code} - Response: {res.text}")
    except Exception as e:
        print(f"❌ Error sending WhatsApp: {e}")

def send_whatsapp_file(to_phone: str, filename: str, content: bytes, mime_type: str, caption: str = ""):
    """Send a generated file through Green-API's sendFileByUpload endpoint."""
    clean_phone = str(to_phone).lstrip("+").split("@")[0].strip()
    if not GREEN_API_TOKEN:
        print("❌ GREEN_API_TOKEN is not configured; cannot send file")
        return False
    url = f"{GREEN_API_BASE}/waInstance{INSTANCE_ID}/sendFileByUpload/{GREEN_API_TOKEN}"
    try:
        response = requests.post(
            url,
            data={"chatId": f"{clean_phone}@c.us", "caption": caption, "fileName": filename},
            files={"file": (filename, content, mime_type)},
            timeout=45,
        )
        print(f"📎 Green-API file upload: {response.status_code} - {response.text[:500]}")
        response.raise_for_status()
        return True
    except Exception as exc:
        print(f"❌ Could not send WhatsApp file {filename}: {type(exc).__name__}: {exc}")
        return False

def build_statement_pdf(customer_name, debts, payments_by_debt, total_paid, total_balance):
    """Build a compact PDF statement in memory; never writes customer data to disk."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = [Paragraph("Daynjir - Customer Debt Statement", styles["Title"]),
             Paragraph(f"Customer: {escape(str(customer_name))}", styles["Heading2"]),
             Spacer(1, 10)]
    rows = [["Debt #", "Created", "Due date", "Current balance", "Status"]]
    for idx, debt in enumerate(debts, 1):
        balance = max(float(debt.get("amount") or 0), 0.0)
        status = "Paid" if debt.get("is_paid") is True or balance <= 0 else "Unpaid"
        rows.append([str(idx), str(debt.get("created_at") or "")[:10] or "Unknown",
                     str(debt.get("promised_date") or "Not set"), f"${balance:.2f}", status])
    table = Table(rows, repeatRows=1, colWidths=[42, 85, 85, 100, 70])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([table, Spacer(1, 14),
                  Paragraph(f"Recorded payments: ${total_paid:.2f}", styles["Normal"]),
                  Paragraph(f"Current outstanding balance: ${total_balance:.2f}", styles["Heading2"]),
                  Spacer(1, 10), Paragraph("Payment ledger", styles["Heading2"])])
    payment_rows = [["Debt #", "Payment date", "Amount"]]
    for idx, debt in enumerate(debts, 1):
        for payment in payments_by_debt.get(str(debt.get("id")), []):
            payment_rows.append([str(idx), str(payment.get("paid_at") or "")[:10] or "Unknown",
                                 f"${float(payment.get('amount') or 0):.2f}"])
    if len(payment_rows) == 1:
        payment_rows.append(["-", "No payments recorded", "$0.00"])
    pay_table = Table(payment_rows, repeatRows=1, colWidths=[70, 150, 100])
    pay_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(pay_table)
    doc.build(story)
    return buffer.getvalue()

OWNER_PHONE = os.getenv("OWNER_PHONE", "").lstrip("+").strip()
# Required for /cron/* endpoints: set a long random CRON_SECRET and send it as
# the x-cron-secret header (or Authorization: Bearer <secret>).

@app.get("/")
def home():
    return {"status": "Daynjir Bot Engine is running live."}
def normalize_customer_name(value):
    """Normalize names for case/punctuation/spacing-insensitive comparison."""
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^\w\s]", " ", value)
    return " ".join(value.split())


def _edit_distance(left, right):
    """Levenshtein distance, used to tolerate small typing/spelling mistakes."""
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, 1):
        current = [i]
        for j, right_char in enumerate(right, 1):
            current.append(min(
                current[j - 1] + 1,
                previous[j] + 1,
                previous[j - 1] + (left_char != right_char),
            ))
        previous = current
    return previous[-1]


def _token_match_score(left, right):
    if left == right:
        return 1.0
    distance = _edit_distance(left, right)
    longest = max(len(left), len(right))
    # Permit 1 typo for short names and up to 2 for longer names.
    max_errors = 1 if longest <= 4 else 2
    if distance > max_errors:
        return 0.0
    # Once within the allowed edit-distance window, keep the score high enough
    # that a legitimate one-character typo (e.g. Ali/Aly) is not rejected.
    return 0.80 + 0.20 * (1.0 - distance / max(1, longest))


def _name_similarity(requested, stored):
    """Score full names while allowing small spelling errors in each name part."""
    requested_norm = normalize_customer_name(requested)
    stored_norm = normalize_customer_name(stored)
    if not requested_norm or not stored_norm:
        return 0.0
    if requested_norm == stored_norm:
        return 1.0

    requested_parts = requested_norm.split()
    stored_parts = stored_norm.split()

    # Match every supplied name part against a distinct stored name part.
    # This prevents a shared first name alone from overriding a matching surname.
    available = list(stored_parts)
    part_scores = []
    for part in requested_parts:
        if not available:
            return 0.0
        best = max(range(len(available)), key=lambda i: _token_match_score(part, available[i]))
        score = _token_match_score(part, available[best])
        if score == 0.0:
            return 0.0
        part_scores.append(score)
        available.pop(best)

    # If the user provided only one part of a multi-part name, allow it as a
    # lookup, but the caller will be shown alternatives when names are ambiguous.
    token_score = sum(part_scores) / len(part_scores)
    if len(requested_parts) == 1 and len(stored_parts) > 1:
        return min(token_score, 0.88)

    # A typo of one or two characters is accepted, but full-name alignment matters.
    return 0.65 * token_score + 0.35 * difflib.SequenceMatcher(None, requested_norm, stored_norm).ratio()


def resolve_name_from_original_message(shopkeeper_id, message_text, ai_name):
    """Recover a complete stored debtor name when the original message contains it.

    This corrects cases where the AI extracts only the first name from a full
    name such as 'Edit Hinda bire oct 10'. It only resolves names that actually
    appear as a complete phrase in the original message, and prefers the
    longest phrase to avoid matching a shorter name inside a longer one.
    """
    if not ai_name or not message_text:
        return None

    normalized_message = f" {normalize_customer_name(message_text)} "
    ai_norm = normalize_customer_name(ai_name)
    if not ai_norm:
        return None

    result = (
        supabase.table("debtors")
        .select("name")
        .eq("shopkeeper_id", shopkeeper_id)
        .execute()
    )
    stored_names = {}
    for row in (result.data or []):
        display = str(row.get("name") or "").strip()
        normalized = normalize_customer_name(display)
        if normalized:
            stored_names.setdefault(normalized, display)

    # First accept an exact full-name phrase. If the customer typed a small
    # spelling variation (e.g. MAT AAN vs MATAN), compare same-length word
    # windows from the original message against stored names.
    message_parts = normalize_customer_name(message_text).split()
    requested_parts = normalize_customer_name(ai_name).split()
    candidates = []

    for normalized, display in stored_names.items():
        stored_parts = normalized.split()
        if not stored_parts:
            continue
        if f" {normalized} " in normalized_message:
            score = 1.0
        else:
            # Compare contiguous phrase windows of the same word count. This
            # avoids treating a shared token like CALI as a full-name match.
            windows = [
                " ".join(message_parts[i:i + len(stored_parts)])
                for i in range(max(0, len(message_parts) - len(stored_parts) + 1))
            ]
            score = max((_name_similarity(window, normalized) for window in windows), default=0.0)

        has_related_token = any(
            _token_match_score(req, stored) >= 0.78
            for req in requested_parts
            for stored in stored_parts
        )
        if score >= 0.78 and has_related_token:
            candidates.append((score, len(stored_parts), len(normalized), display, normalized))

    if not candidates:
        return None

    candidates.sort(key=lambda c: (c[0], c[1], c[2]), reverse=True)
    best_score = candidates[0][0]
    # Only auto-resolve when one stored name clearly wins. If two names are
    # similarly close, leave the AI's name unchanged so normal disambiguation runs.
    best = [c for c in candidates if best_score - c[0] <= 0.04]
    unique_names = {c[3] for c in best}
    if len(unique_names) == 1:
        resolved = next(iter(unique_names))
        print(f"🔎 Recovered full debtor name from original message: {ai_name!r} -> {resolved!r} (score={best_score:.3f})")
        return resolved
    return None


def find_debtor_matches(shopkeeper_id, name):
    """Find exact names first, then aligned partial names, then safe fuzzy matches.

    A fuzzy match is not silently selected when another distinct customer name is
    nearly as likely; in that case all candidates are returned for clarification.
    """
    requested = normalize_customer_name(name)
    if not requested:
        return []

    result = (
        supabase.table("debtors")
        .select("*")
        .eq("shopkeeper_id", shopkeeper_id)
        .order("name")
        .execute()
    )
    rows = result.data or []
    if not rows:
        return []

    # Keep each distinct spelling/name together so repeated debts for the same
    # customer do not count as different people during name disambiguation.
    names = {}
    for row in rows:
        display_name = str(row.get("name") or "").strip()
        names.setdefault(normalize_customer_name(display_name), {"display": display_name, "rows": []})["rows"].append(row)

    # Exact normalized full-name match has priority.
    if requested in names:
        return names[requested]["rows"]

    requested_parts = requested.split()

    # Prefer exact stored name tokens before fuzzy matching.
    exact_token_matches = []
    for normalized, item in names.items():
        stored_parts = normalized.split()
        if all(part in stored_parts for part in requested_parts):
            exact_token_matches.append((len(stored_parts), normalized, item))
    if exact_token_matches:
        shortest_length = min(item[0] for item in exact_token_matches)
        preferred = [item for item in exact_token_matches if item[0] == shortest_length]
        return [row for _, _, item in preferred for row in item["rows"]]

    # Next try word-boundary partial names.
    partial = [
        item for normalized, item in names.items()
        if f" {requested} " in f" {normalized} " or f" {normalized} " in f" {requested} "
    ]
    if partial:
        return [row for item in partial for row in item["rows"]]

    # Only then consider typo-tolerant fuzzy matches.
    scored = []
    for normalized, item in names.items():
        score = _name_similarity(requested, normalized)
        if score >= 0.78:
            scored.append((score, normalized, item))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score = scored[0][0]
    # If another distinct name is almost as close, ask the user to identify the
    # right full name rather than risking a payment, edit, or deletion on the wrong person.
    close = [entry for entry in scored if best_score - entry[0] <= 0.08]
    if len(close) > 1:
        return [row for _, _, item in close for row in item["rows"]]
    return scored[0][2]["rows"]


def ask_for_full_name(sender_phone, matches, action):
    message = "⚠️ Dad isku magac ah ayaan helay:\n\n"

    for number, debtor in enumerate(matches, start=1):
        due_date = debtor.get("promised_date") or "lama gelin"
        message += (
            f"{number}. {debtor['name']} — "
            f"${debtor['amount']} — Ballan: {due_date}\n"
        )

    if action == "PAY":
        example = f"{matches[0]['name']} wuu bixiyay"
    elif action == "DELETE":
        example = f"delete {matches[0]['name']}"
    elif action == "HISTORY":
        example = f"{matches[0]['name']} history"
    elif action == "SEARCH":
        example = f"Show {matches[0]['name']} debt"
    else:
        example = f"edit {matches[0]['name']} $50"

    message += (
        "\n✍️ Fadlan mar kale qor magaca oo buuxa.\n"
        f"Tusaale: {example}"
    )

    send_whatsapp(sender_phone, message)
  
def send_due_list_followup(phone):
    send_whatsapp(
        phone,
        "Si aad u eegto liiska deynta oo dhan soo qor:\n"
        "Liiska daynta\n"
        "ama\n"
        "Liiska daynta iyo balamaha"
    )
@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    print(f"📥 Green-API webhook received: type={data.get('typeWebhook')}")
    
    allowed_types = {"incomingMessageReceived"}
    if data.get("typeWebhook") not in allowed_types:
        # Ignore outgoing API messages; otherwise the bot may process its own replies.
        return {"status": "ignored"}
        
    sender_data = data.get("senderData", {})
    sender_chat_id = sender_data.get("chatId")
    if not sender_chat_id:
        return {"status": "no_chat_id"}
        
    sender_phone = sender_chat_id.split("@")[0]
    print(f"🔍 SENDER PHONE: {sender_phone}")
    
    message_data = data.get("messageData", {})
    type_message = message_data.get("typeMessage")
    
    message_text = ""
    
    # ✅ HANDLE EXCEL/CSV FILES
    if type_message == "documentMessage":
        print("📄 Excel/CSV file detected!")
        try:
            doc_data = message_data["fileMessageData"]
            file_name = doc_data.get("fileName", "")
            
            if not (file_name.endswith('.xlsx') or file_name.endswith('.xls') or file_name.endswith('.csv')):
                send_whatsapp(sender_phone, "❌ Please send Excel (.xlsx, .xls) or CSV file only.")
                return {"status": "unsupported_file_type"}
            
            download_url = doc_data.get("downloadUrl")
            if not download_url:
                send_whatsapp(sender_phone, "❌ Could not download file.")
                return {"status": "no_download_url"}
            
            print(f"📥 Downloading file: {file_name}")
            
            file_response = requests.get(download_url, timeout=30)
            if file_response.status_code != 200:
                send_whatsapp(sender_phone, "❌ Failed to download file.")
                return {"status": "download_failed"}
            
            try:
                print("🔍 Parsing file...")
                if file_name.endswith('.csv'):
                    df = pd.read_csv(BytesIO(file_response.content))
                else:
                    df = pd.read_excel(BytesIO(file_response.content), engine='openpyxl')
                
                print(f"📊 Found {len(df)} rows in file")
                print(f"📋 Columns: {list(df.columns)}")
                if 'Due' in df.columns:
                    print(f"🔍 Due values: {df['Due'].tolist()}")
                elif 'Due Date' in df.columns:
                    print(f"🔍 Due Date values: {df['Due Date'].tolist()}")
                elif 'due_date' in df.columns:
                    print(f"🔍 due_date values: {df['due_date'].tolist()}")
                else:
                    print("🔍 No Due column found!")
                
                required_cols = ['Name', 'Amount']
                if not all(col in df.columns for col in required_cols):
                    send_whatsapp(sender_phone, "❌ File must have 'Name' and 'Amount' columns.")
                    return {"status": "missing_columns"}
                
                try:
                    sk_query = supabase.table("shopkeepers").select("*").eq("phone_number", sender_phone).execute()
                    if not sk_query.data:
                        sk_insert = supabase.table("shopkeepers").insert({"phone_number": sender_phone}).execute()
                        shopkeeper_id = sk_insert.data[0]["id"]
                    else:
                        shopkeeper_id = sk_query.data[0]["id"]
                except Exception as db_err:
                    print(f"❌ DATABASE ERROR: {db_err}")
                    send_whatsapp(sender_phone, "❌ Database error.")
                    return {"status": "shopkeeper_db_error"}
                
                added_count = 0
                failed_count = 0
                
                for index, row in df.iterrows():
                    try:
                        name = str(row['Name']).strip()
                        amount = float(row['Amount'])
                        
                        # FIX: Handle Excel date properly - check all column variations
                        due_date = None
                        due_val = None
                        
                        # Try all possible column names
                        for col_name in ['Due', 'Due Date', 'due_date', 'due']:
                            if col_name in df.columns:
                                due_val = row[col_name]
                                break
                        
                        if due_val is not None and str(due_val).strip().lower() not in ("nan", ""):
                            if hasattr(due_val, "strftime"):
                                due_date = due_val.strftime("%Y-%m-%d")
                            else:
                                due_str = str(due_val).strip()
                                due_date = None

                                for fmt in (
                                    "%Y-%m-%d",
                                    "%d/%m/%Y",
                                    "%d-%m-%Y",
                                    "%m/%d/%Y",
                                ):
                                    try:
                                        parsed_date = datetime.strptime(due_str, fmt)
                                        due_date = parsed_date.strftime("%Y-%m-%d")
                                        break
                                    except ValueError:
                                        pass

                                if due_date is None:
                                    due_date = (
                                        now_eat()
                                    ).date().isoformat()
                        else:
                            due_date = (
                                now_eat()
                            ).date().isoformat()

                        starting_amount = float(amount)

                        debtor_data = {
                            "shopkeeper_id": shopkeeper_id,
                            "name": name,
                            "amount": starting_amount,
                            "original_amount": starting_amount,
                            "promised_date": due_date,
                            "is_paid": False
                        }

                        supabase.table("debtors").insert(debtor_data).execute()
                        added_count += 1
                        print(f"  ✅ Added: {name} - ${amount}")
                        
                    except Exception as row_err:
                        print(f"  ❌ Row {index} failed: {row_err}")
                        failed_count += 1
                
                if added_count > 0:
                    send_whatsapp(sender_phone, f"✅ Imported {added_count} debts from Excel!\n\n📊 **Summary**:\n✅ Added: {added_count}")
                else:
                    send_whatsapp(sender_phone, "❌ No valid debts found in file.")
                
                return {"status": "success"}
                
            except Exception as parse_err:
                print(f"❌ Parse error: {parse_err}")
                send_whatsapp(sender_phone, f"❌ File error: {parse_err}")
                return {"status": "parse_error"}
                
        except Exception as file_err:
            print(f"❌ File error: {str(file_err)}")
            send_whatsapp(sender_phone, f"❌ File error: {str(file_err)}")
            return {"status": "file_error"}
    
    # ✅ HANDLE TEXT MESSAGES
    try:
        if type_message == "textMessage":
            message_text = message_data["textMessageData"]["textMessage"]
        elif type_message == "extendedTextMessage":
            message_text = message_data["extendedTextMessageData"]["text"]
        else:
            return {"status": "unsupported_message_type"}
    except KeyError:
        return {"status": "no_text_payload"}
        
    if not message_text:
        return {"status": "empty_text"}
    
    # Normalize sender; GREEN-API chat IDs may include "@c.us".
    sender_phone = str(sender_phone).replace("+", "").split("@")[0].strip()
    owner_phone = str(OWNER_PHONE).replace("+", "").split("@")[0].strip()

    # Owner approves/rejects with: APPROVE 252... or REJECT 252...
    parts = message_text.strip().split(maxsplit=1)
    command = parts[0].upper() if parts else ""

    if sender_phone == owner_phone and command in {"APPROVE", "REJECT"}:
        if len(parts) != 2:
            send_whatsapp(sender_phone, "Use: APPROVE 252... or REJECT 252...")
            return {"status": "invalid_approval_command"}

        applicant_phone = parts[1].replace("+", "").split("@")[0].strip()
        new_status = "approved" if command == "APPROVE" else "rejected"

        try:
            applicant = (
                supabase.table("shopkeepers")
                .select("id, phone_number")
                .eq("phone_number", applicant_phone)
                .execute()
            )

            if not applicant.data:
                send_whatsapp(sender_phone, f"❌ No request found for {applicant_phone}.")
                return {"status": "applicant_not_found"}

            (
                supabase.table("shopkeepers")
                .update({"approval_status": new_status})
                .eq("phone_number", applicant_phone)
                .execute()
            )

            send_whatsapp(sender_phone, f"✅ {applicant_phone} is {new_status}.")
            send_whatsapp(
                applicant_phone,
                "✅ Your access is approved."
                if new_status == "approved"
                else "❌ Your access request was rejected."
            )
            return {"status": new_status}

        except Exception as approval_err:
            print(f"❌ APPROVAL UPDATE ERROR: {approval_err}")
            send_whatsapp(sender_phone, "❌ Could not update the request. Check server logs.")
            return {"status": "approval_update_error"}

    # Find this sender's shopkeeper; do NOT auto-create unknown senders here.
    try:
        sk_query = (
            supabase.table("shopkeepers")
            .select("id, phone_number, approval_status")
            .eq("phone_number", sender_phone)
            .execute()
        )

        if not sk_query.data:
            send_whatsapp(
                sender_phone,
                "⏳ Weli isma aadan diwaan gelinin. soo qor JOIN si laguu aqbalo."
            )
            return {"status": "not_registered"}

        shopkeeper = sk_query.data[0]
        if shopkeeper.get("approval_status") != "approved":
            send_whatsapp(
                sender_phone,
                "⏳ codsigaaga waa la diray. fadlan sug jawaabta."
            )
            return {"status": "not_approved"}

        shopkeeper_id = shopkeeper["id"]

    except Exception as db_err:
        print(f"❌ DATABASE ERROR (Shopkeepers Lookup): {db_err}")
        return {"status": "shopkeeper_db_error"}
    
    today_str = today_eat().isoformat()
    dynamic_system_prompt = f"{SYSTEM_PROMPT}\nToday's date is strictly: {today_str}. Use this to calculate calendar targets or relative days offsets like 'berri'."
    
    chat_completion = groq_client.chat.completions.create(
        messages=[{"role": "system", "content": dynamic_system_prompt}, {"role": "user", "content": message_text}],
        model="openai/gpt-oss-20b",
        temperature=0.0
    )
    
    try:
        ai_response = chat_completion.choices[0].message.content.strip()
    except Exception as parse_err:
        print(f"⚠️ Direct extraction failed, casting raw string: {parse_err}")
        ai_response = str(chat_completion).strip()
        
    print(f"🤖 Groq AI Processed Output: {ai_response}")
    
    try:
        json_match = re.search(r'[\[{].*[\]}]', ai_response, re.DOTALL)
        if not json_match:
            raise Exception("No JSON found")
        
        clean_json = json_match.group()
        parsed = json.loads(clean_json)
        
        if isinstance(parsed, dict):
            entries = [parsed]
        else:
            entries = parsed
        
        if not entries:
            raise Exception("Empty entries")
            
    except Exception as e:
        # AI may return plain text or [] for a valid customer-name query (for
        # example, "XIIS" or "Search XIIS CALI MATAAN"). Before giving up,
        # safely try the original message as a SEARCH against this shopkeeper's
        # own debtor records. Never use this fallback for ADD/PAY/EDIT/DELETE.
        print(f"⚠️ AI output was not usable JSON ({e}); trying customer-search fallback")
        raw_query = str(message_text or "").strip()
        search_query = re.sub(
            r"^\s*(?:search|find|show|lookup|look up|check|raadi|raadso|eeg|hubi)\b\s*[:,-]?\s*",
            "",
            raw_query,
            flags=re.IGNORECASE,
        ).strip()
        if not search_query:
            search_query = raw_query

        fallback_matches = []
        if search_query:
            try:
                fallback_matches = find_debtor_matches(shopkeeper_id, search_query)
            except Exception as fallback_err:
                print(f"⚠️ Customer-search fallback failed: {type(fallback_err).__name__}: {fallback_err}")

        if fallback_matches:
            print(f"🔎 AI fallback matched customer query {search_query!r}; routing to SEARCH")
            entries = [{"action": "SEARCH", "customer_name": search_query}]
        else:
            instructions = """❌ Ma fahmin qoraalkaaga.

📖 **Fadlan Raac Tilmaamahan:**

✅ **Si aad u kaydiso deyn cusub:**
   Qor magaca iyo lacagta
   Tusaale: Axmed $100 balanta=beri

✅ **Raadi macmiil:**
   Search kadib magaca macmiilka
   Ama qor magaca macmiilka oo keliya

✅ **Liiska deynta:**
   Liiska deynta
   Balamaha maanta

✅ **Deyn bixinta:**
   Cali wuu bixiyay
   Axmed wuxuu bixiyay $50

✅ **Tirtir:**
   delete Cali
   remove Axmed

✅ **Warbixin:**
   Report
"""
            send_whatsapp(sender_phone, instructions)
            return {"status": "parsing_failed"}

    # Make explicit customer-search commands deterministic, like HISTORY:
    # don't depend on Groq choosing the correct action or extracting the full name.
    # HISTORY/statement wording takes priority and is never converted to SEARCH.
    original_text = str(message_text or "").strip()
    lower_text = original_text.casefold()
    is_history_request = any(word in lower_text for word in (
        "history", "taariikh", "statement", "xisaab"
    ))
    search_prefix = re.match(
        r"^\s*(?:search|find|lookup|look up|raadi|raadso)\b\s*[:,-]?\s*(.+?)\s*$",
        original_text,
        flags=re.IGNORECASE,
    )
    if search_prefix and not is_history_request:
        explicit_search_name = search_prefix.group(1).strip()
        if explicit_search_name:
            print(f"🔎 Explicit search command detected; routing directly to SEARCH: {explicit_search_name!r}")
            entries = [{"action": "SEARCH", "customer_name": explicit_search_name}]

    successful_inserts = []
    failed_inserts = []
    
    for entry in entries:
        action = entry.get("action", "ADD")
        name = entry.get("customer_name")
        amount = entry.get("amount")
        promised_date = entry.get("promised_date")
        days_until_due = entry.get("days_until_due")
        customer_phone = entry.get("customer_phone")
        new_amount = entry.get("new_amount")
        new_date = entry.get("new_date")
        new_phone = entry.get("new_phone")
        payment_type = str(entry.get("payment_type") or "UNKNOWN").upper()
        filter_date = entry.get("filter_date")
        filter_type = entry.get("filter_type")

        date_only_update = False
        # If a message has a customer name + due date but NO amount, treat it as
        # a request to update that customer's existing debt date, not create a
        # second debt with amount 0. Example: existing debt is $4 with no due
        # date; "C/SAMAD SANDHEERE oct 10" should update its date to Oct 10.
        if action == "ADD" and amount is None and not new_phone:
            date_only = promised_date
            if not date_only and days_until_due is not None:
                try:
                    date_only = (today_eat() + timedelta(days=int(days_until_due))).isoformat()
                except (TypeError, ValueError):
                    date_only = None
            if date_only:
                action = "EDIT"
                date_only_update = True
                new_date = date_only
                entry["action"] = "EDIT"
                entry["new_date"] = date_only
                print(f"🗓️ Date-only ADD converted to EDIT for {name!r}: {date_only}")
            else:
                send_whatsapp(
                    sender_phone,
                    "⚠️ Lacagta deynta lama sheegin.\n\n"
                    "Haddii aad rabto inaad beddesho ballanta deyn hore, qor magaca iyo taariikhda.\n"
                    "Tusaale: Cali oct 10\n"
                    "Deyn cusubna ku qor: faarax $40 oct 10"
                )
                failed_inserts.append({"name": name or "Unknown", "reason": "Amount missing for new debt"})
                continue

        # Recover the full stored name from the original WhatsApp message if AI shortened it.
        if name and action in {"PAY", "EDIT", "DELETE", "HISTORY", "SEARCH"}:
            try:
                recovered_name = resolve_name_from_original_message(
                    shopkeeper_id, message_text, name
                )
                if recovered_name:
                    name = recovered_name
                    entry["customer_name"] = recovered_name
            except Exception as name_err:
                print(f"⚠️ Original-message name resolution failed: {name_err}")
        
        if not name and action not in ["LIST", "REPORT", "EXPORT"]:
            failed_inserts.append({"name": "Unknown", "reason": "No name"})
            continue
        
        if action == "ADD":
            try:
                if amount is None and not new_phone:
                    send_whatsapp(sender_phone, "⚠️ ma cada cadadka deyntu, fadlan xaqiiji)
                    failed_inserts.append({"name": name, "reason": "Amount missing for new debt"})
                    continue
                if not promised_date and days_until_due is not None:
                    promised_date = (today_eat() + timedelta(days=int(days_until_due))).isoformat()
                # Keep promised_date as None when the user did not specify a due date.
                
                if new_phone and not amount:
                    phone_matches = find_debtor_matches(shopkeeper_id, name)
                    distinct_phone_names = {normalize_customer_name(d.get("name")) for d in phone_matches}
                    if len(distinct_phone_names) > 1:
                        ask_for_full_name(sender_phone, phone_matches, "EDIT")
                        continue
                    if phone_matches:
                        matched_name = phone_matches[0]["name"]
                        updated = (supabase.table("debtors").update({"phone_number": new_phone})
                                   .eq("shopkeeper_id", shopkeeper_id).eq("name", matched_name).execute())
                        if updated.data:
                            send_whatsapp(sender_phone, f"✅ {matched_name} phone number saved: {new_phone}")
                            successful_inserts.append(entry)
                        else:
                            send_whatsapp(sender_phone, f"❌ Lambarka {matched_name} lama cusboonaysiin.")
                            failed_inserts.append({"name": name, "reason": "Phone update returned no rows"})
                        continue
                    else:
                        send_whatsapp(sender_phone, f"❌ Lama helin qofka {name} si lambarkiisa loo kaydiyo.")
                        failed_inserts.append({"name": name, "reason": "Debtor not found for phone update"})
                        continue
                
                debtor_data = {
                    'shopkeeper_id': shopkeeper_id,
                    'name': name,
                    'amount': float(amount) if amount else 0,
                    'promised_date': promised_date,
                    'phone_number': new_phone if new_phone else None,
                    'is_paid': False
                }
                
                result = supabase.table("debtors").insert(debtor_data).execute()
                successful_inserts.append(entry)
                
            except Exception as e:
                failed_inserts.append({"name": name, "reason": str(e)})
        
        elif action == "PAY":
            try:
                payment_amount = entry.get("amount")
                payment_type = str(entry.get("payment_type") or "UNKNOWN").upper()
                matches = find_debtor_matches(shopkeeper_id, name)

                if len(matches) == 0:
                    send_whatsapp(sender_phone, f"❌ Lama helin deynta aan weli la bixin ee {name}.")
                    failed_inserts.append({"name": name, "reason": "Unpaid debtor not found"})
                    continue

                if len(matches) > 1:
                    ask_for_full_name(sender_phone, matches, "PAY")
                    continue

                debtor = matches[0]
                current_balance = float(debtor.get("amount") or 0)

                if current_balance <= 0 or debtor.get("is_paid") is True:
                    send_whatsapp(sender_phone, f"✅ {debtor['name']} hore ayuu u bixiyay deyntiisa.")
                    continue

                # A missing amount is a full payment ONLY when the AI explicitly says FULL.
                if payment_amount is None and payment_type != "FULL":
                    send_whatsapp(
                        sender_phone,
                        f"💵 {debtor['name']} lacag intee le'eg ayaad ka heshay?\n"
                        f"Tusaale: {debtor['name']} ka jar $10.\n"
                        "Haddii uu deynta oo dhan bixiyay, qor: "
                        f"{debtor['name']} wuu bixiyay deyntii oo dhan."
                    )
                    continue

                if payment_amount is None:
                    payment_amount = current_balance
                else:
                    try:
                        payment_amount = float(payment_amount)
                    except (TypeError, ValueError):
                        send_whatsapp(sender_phone, "❌ cadadka Lacagta ma fahmin.")
                        continue

                if payment_amount <= 0:
                    send_whatsapp(sender_phone, "❌ Lacagta la bixiyay waa inay ka badan tahay $0.")
                    continue

                if payment_amount - current_balance > 0.009:
                    send_whatsapp(
                        sender_phone,
                        f"⚠️ {debtor['name']} haraaga deyntiisu waa ${current_balance:.2f}, "
                        f"laakiin waxaad sheegtay ${payment_amount:.2f}. Lacag-bixintan lama diiwaangelin "
                        "si aan haraaga uga dhigin tiro taban. Hubi lacagta oo mar kale dir."
                    )
                    continue
                actual_payment = round(payment_amount, 2)
                new_balance = round(max(0.0, current_balance - actual_payment), 2)
                is_now_paid = new_balance <= 0

                # Atomically insert the payment and update the balance inside PostgreSQL.
                # Apply the companion SQL migration file before deploying this version.
                rpc_result = supabase.rpc("record_debt_payment", {
                    "p_debtor_id": str(debtor["id"]),
                    "p_shopkeeper_id": str(shopkeeper_id),
                    "p_amount": actual_payment,
                }).execute()
                rpc_data = rpc_result.data
                if isinstance(rpc_data, list):
                    rpc_data = rpc_data[0] if rpc_data else None
                if not isinstance(rpc_data, dict) or not rpc_data.get("id"):
                    raise RuntimeError("record_debt_payment returned no debt row; apply supabase_record_debt_payment.sql and check RLS")
                updated_debtor = rpc_data
                new_balance = float(updated_debtor.get("amount") or 0)
                is_now_paid = bool(updated_debtor.get("is_paid")) or new_balance <= 0
                if is_now_paid:
                    send_whatsapp(
                        sender_phone,
                        f"✅ {updated_debtor['name']} deyntii oo dhan waa la bixiyay. "
                        f"Lacagta la diiwaangeliyay: ${actual_payment:.2f}."
                    )
                else:
                    send_whatsapp(
                        sender_phone,
                        f"✅ {updated_debtor['name']} wuxuu bixiyay ${actual_payment:.2f}. "
                        f"Haray: ${float(updated_debtor['amount']):.2f}."
                    )

            except Exception as e:
                print(f"❌ Payment error: {type(e).__name__}: {e}")
                send_whatsapp(
                    sender_phone,
                    f"❌ Lacag-bixintu way fashilantay ({type(e).__name__}). Hubi server logs-ka."
                )
                failed_inserts.append({"name": name, "reason": f"Payment error: {type(e).__name__}: {e}"})
        
        elif action == "LIST":
            try:
                # Detect whether the user asked for due dates
                text_lower = message_text.lower()

                wants_due_dates = any(keyword in text_lower for keyword in [
                    "balanta",
                    "balamaha",
                    "ballanta",
                    "ballamaha",
                    "balan",
                    "due",
                    "date"
                ])

                # Start with unpaid debts only
                query = (
                    supabase.table("debtors")
                    .select("*")
                    .eq("shopkeeper_id", shopkeeper_id)
                    .eq("is_paid", False)
                )

                # If a specific date was requested, filter by that date
                if filter_date:
                    query = query.eq("promised_date", filter_date)

                    if filter_type == "today":
                        message_title = "📋 *Balamaha Maanta*"
                    elif filter_type == "tomorrow":
                        message_title = "📋 *Balamaha Berri*"
                    else:
                        message_title = f"📋 *Balamaha {filter_date}*"

                    wants_due_dates = True
                else:
                    query = query.order("promised_date", desc=False)

                    if wants_due_dates:
                        message_title = "📋 *Liiska Deynta iyo Balamaha*"
                    else:
                        message_title = "📋 *Liiska Deynta*"

                debts_query = query.execute()

                if not debts_query.data:
                    if filter_date:
                        send_whatsapp(
                            sender_phone,
                            f"✅ Ma jiraan deymo balantoodu tahay {filter_date}."
                        )
                        send_due_list_followup(sender_phone)
                    else:
                        send_whatsapp(
                            sender_phone,
                            "✅ Ma jirto deyn aan la bixin."
                        )
                    continue

                debt_list = []
                total = 0
                overdue_count = 0
                today = today_eat()

                for index, debt in enumerate(debts_query.data, start=1):
                    debtor_name = debt["name"]
                    debtor_amount = float(debt["amount"])
                    due_date = debt.get("promised_date")

                    total += debtor_amount

                    if wants_due_dates:
                        status = ""

                        if due_date:
                            try:
                                due = datetime.strptime(
                                    due_date,
                                    "%Y-%m-%d"
                                ).date()

                                days_left = (due - today).days

                                if days_left < 0:
                                    status = (
                                        f" ⚠️ Balan dhaaf "
                                        f"({abs(days_left)} maalin)"
                                    )
                                    overdue_count += 1
                                elif days_left == 0:
                                    status = " 🔴 Balanta maanta"
                                else:
                                    status = f" 📅 {due_date}"

                            except (TypeError, ValueError):
                                status = f" 📅 {due_date}"

                        debt_list.append(
                            f"{index}. {debtor_name}: "
                            f"${debtor_amount:.2f}{status} "
                            f"— Ballan: {due_date or 'lama gelin'}"
                        )
                    else:
                        debt_list.append(
                            f"{index}. {debtor_name}: "
                            f"${debtor_amount:.2f}"
                        )

                message = (
                    f"{message_title} "
                    f"({len(debts_query.data)} macmiil):\n\n"
                    + "\n".join(debt_list)
                )

                if wants_due_dates and overdue_count > 0:
                    message = (
                        f"⚠️ {overdue_count} deymaha balandhaafka ah:\n\n"
                        + message
                    )

                message += (
                    f"\n\n💰 Lacagta guud: "
                    f"${total:.2f}"
                )

                send_whatsapp(sender_phone, message)

                if filter_date:
                    send_due_list_followup(sender_phone)

            except Exception as e:
                print(f"❌ List error: {e}")
                send_whatsapp(
                    sender_phone,
                    "❌ Khalad ayaa dhacay marka liiska la soo saarayay."
                )
                failed_inserts.append({
                    "name": "LIST",
                    "reason": f"List error: {str(e)}"
                })

        elif action == "EDIT":
            try:
                matches = find_debtor_matches(shopkeeper_id, name)

                if len(matches) == 0:
                    send_whatsapp(sender_phone, f"❌ ma helin deyn aan weli la bixin oo ku qoran {name}.")
                    failed_inserts.append({"name": name, "reason": "Debtor not found"})
                    continue

                if date_only_update:
                    # Do not select by due date if fuzzy matching returned different people.
                    distinct_names = {normalize_customer_name(row.get("name")) for row in matches}
                    if len(distinct_names) > 1:
                        ask_for_full_name(sender_phone, matches, "EDIT")
                        continue
                    # Prefer the unique unpaid debt without a due date. Never create
                    # a new debt for a date-only message or guess between records.
                    undated_matches = [
                        row for row in matches
                        if not row.get("promised_date")
                        and float(row.get("amount") or 0) > 0
                        and row.get("is_paid") is not True
                    ]
                    if not undated_matches:
                        # Older code assigned today's date automatically when
                        # none was provided. Support that legacy case only when
                        # exactly one positive, unpaid row is due today.
                        today_str = today_eat().isoformat()
                        legacy_today_matches = [
                            row for row in matches
                            if row.get("promised_date") == today_str
                            and float(row.get("amount") or 0) > 0
                            and row.get("is_paid") is not True
                        ]
                        if len(legacy_today_matches) == 1:
                            undated_matches = legacy_today_matches
                    if len(undated_matches) == 1:
                        matches = undated_matches
                    elif len(undated_matches) == 0 and len(matches) == 1 and matches[0].get("is_paid") is not True and float(matches[0].get("amount") or 0) > 0:
                        # A single existing unpaid debt is an unambiguous target even if it already has a date.
                        pass
                    else:
                        ask_for_full_name(sender_phone, matches, "EDIT")
                        continue
                elif len(matches) > 1:
                    ask_for_full_name(sender_phone, matches, "EDIT")
                    continue

                debtor = matches[0]
                update_data = {}

                # Fallbacks support inconsistent model output, e.g. amount instead of new_amount.
                amount_to_set = new_amount if new_amount is not None else amount
                date_to_set = new_date if new_date is not None else promised_date

                if amount_to_set is not None:
                    try:
                        amount_to_set = float(amount_to_set)
                    except (TypeError, ValueError):
                        send_whatsapp(sender_phone, "❌ Lacagta cusub ma saxna.")
                        continue
                    if amount_to_set < 0:
                        send_whatsapp(sender_phone, "❌ Lacagtu ma noqon karto tiro taban.")
                        continue
                    update_data["amount"] = amount_to_set
                    update_data["is_paid"] = amount_to_set <= 0

                if date_to_set is not None:
                    try:
                        parsed_date = datetime.strptime(str(date_to_set), "%Y-%m-%d").date()
                        update_data["promised_date"] = parsed_date.isoformat()
                    except (TypeError, ValueError):
                        send_whatsapp(sender_phone, "❌ Taariikh khaldan. Isticmaal YYYY-MM-DD, tusaale 2026-10-20.")
                        continue

                if not update_data:
                    send_whatsapp(
                        sender_phone,
                        "❌ Ma diwaan gelin lacag ama taariikh cusub.\n"
                    )
                    failed_inserts.append({"name": name, "reason": "No changes supplied"})
                    continue

                result = (
                    supabase.table("debtors")
                    .update(update_data)
                    .eq("id", debtor["id"])
                    .eq("shopkeeper_id", shopkeeper_id)
                    .select("id, name, amount, promised_date, is_paid")
                    .execute()
                )
                if not result.data:
                    send_whatsapp(sender_phone, "❌ Waxba lama beddelin. Hubi rukhsadaha database-ka (RLS).")
                    failed_inserts.append({"name": name, "reason": "Update returned no rows"})
                    continue

                updated = result.data[0]
                changes = []
                if "amount" in update_data:
                    changes.append(f"💵 Lacag: ${float(debtor['amount']):.2f} → ${float(updated['amount']):.2f}")
                if "promised_date" in update_data:
                    changes.append(f"📅 Ballan: {debtor.get('promised_date') or 'lama gelin'} → {updated['promised_date']}")

                send_whatsapp(sender_phone, f"✅ {updated['name']} waa la cusboonaysiiyay:\n" + "\n".join(changes))
                successful_inserts.append(entry)

            except Exception as e:
                print(f"❌ Edit error: {type(e).__name__}: {e}")
                send_whatsapp(sender_phone, f"❌ Wax ka beddelku wuu fashilmay ({type(e).__name__}). Hubi server logs-ka.")
                failed_inserts.append({"name": name, "reason": f"Edit error: {type(e).__name__}: {e}"})
        
        elif action == "DELETE":
            try:
                matches = find_debtor_matches(shopkeeper_id, name)

                if len(matches) == 0:
                    send_whatsapp(sender_phone, f"❌ Lama helin {name}.")
                    failed_inserts.append({
                        "name": name,
                        "reason": "Debtor not found"
                    })
                    continue

                if len(matches) > 1:
                    ask_for_full_name(sender_phone, matches, "DELETE")
                    continue

                debtor = matches[0]

                (
                    supabase.table("debtors")
                    .delete()
                    .eq("id", debtor["id"])
                    .eq("shopkeeper_id", shopkeeper_id)
                    .execute()
                )

                send_whatsapp(
                    sender_phone,
                    f"✅ Deynta {debtor['name']} (${debtor['amount']}) waa la tirtiray."
                )
                successful_inserts.append(entry)

            except Exception as e:
                print(f"❌ Delete error: {e}")
                send_whatsapp(
                    sender_phone,
                    "❌ Khalad ayaa dhacay marka deynta la tirtirayay."
                )
                failed_inserts.append({
                    "name": name,
                    "reason": f"Delete error: {str(e)}"
                })
        
        elif action == "SEARCH":
            try:
                search_matches = find_debtor_matches(shopkeeper_id, name)
                if not search_matches:
                    send_whatsapp(sender_phone, f"❌ Lama helin qofka {name}. Hubi higgaadda magaca ama isku day magaciisa oo buuxa.")
                    continue

                distinct_search_names = {normalize_customer_name(d.get("name")) for d in search_matches}
                if len(distinct_search_names) > 1:
                    ask_for_full_name(sender_phone, search_matches, "SEARCH")
                    continue

                matched_name = search_matches[0].get("name", name)
                total_debt = sum(float(d.get("amount") or 0) for d in search_matches if not d.get("is_paid"))
                unpaid_count = sum(1 for d in search_matches if not d.get("is_paid"))
                paid_count = sum(1 for d in search_matches if d.get("is_paid"))
                lines = []
                for i, debt in enumerate(sorted(search_matches, key=lambda d: str(d.get("created_at") or ""), reverse=True), 1):
                    status = "✅ LA BIXIYAY" if debt.get("is_paid") else "⏳ WELI LAMA BIXIN"
                    lines.append(f"{i}. ${float(debt.get('amount') or 0):.2f} — Ballan: {debt.get('promised_date') or 'lama gelin'} — {status}")
                message = (
                    f"🔎 *Natiijada raadinta: {matched_name}*\n\n"
                    f"💰 Wadarta deynta harsan: *${total_debt:.2f}*\n"
                    f"⏳ Deymo aan la bixin: {unpaid_count} | ✅ La bixiyay: {paid_count}\n\n"
                    + "\n".join(lines)
                )
                send_whatsapp(sender_phone, message)
            except Exception as e:
                print(f"❌ Search error: {type(e).__name__}: {e}")
                send_whatsapp(sender_phone, "❌ Khalad ayaa dhacay markii aan magacan la raadinayay. Fadlan mar kale isku day.")
                failed_inserts.append({"name": name, "reason": f"Search error: {type(e).__name__}: {e}"})

        elif action == "HISTORY":
            try:
                # Full customer statement: debt records, payment events, and current outstanding balance.
                history_matches = find_debtor_matches(shopkeeper_id, name)

                if not history_matches:
                    send_whatsapp(sender_phone, f"❌ macmiilkan malaha dhaqdhaqaaq {name}.")
                elif len({normalize_customer_name(d.get("name")) for d in history_matches}) > 1:
                    ask_for_full_name(sender_phone, history_matches, "HISTORY")
                else:
                    history_matches.sort(key=lambda d: str(d.get("created_at") or ""))
                    debtor_ids = [d.get("id") for d in history_matches if d.get("id") is not None]
                    payment_rows = []
                    if debtor_ids:
                        payment_result = (
                            supabase.table("payments")
                            .select("amount, paid_at, debtor_id")
                            .eq("shopkeeper_id", shopkeeper_id)
                            .in_("debtor_id", debtor_ids)
                            .order("paid_at")
                            .execute()
                        )
                        payment_rows = payment_result.data or []

                    payments_by_debt = {}
                    for payment in payment_rows:
                        payments_by_debt.setdefault(str(payment.get("debtor_id")), []).append(payment)

                    lines = [f"📒 *STATEMENT / XISAABTA MACMIILKA: {history_matches[0].get('name', name)}*", ""]
                    total_balance = 0.0
                    total_paid = 0.0
                    for index, debt in enumerate(history_matches, 1):
                        balance = float(debt.get("amount") or 0)
                        debt_paid = bool(debt.get("is_paid")) or balance <= 0
                        total_balance += max(balance, 0.0)
                        lines.append(
                            f"*Deyn #{index}* — {str(debt.get('created_at') or '')[:10] or 'Taariikh lama hayo'}"
                        )
                        lines.append(f"  • Haraaga hadda: ${max(balance, 0.0):.2f}")
                        due_date = debt.get("promised_date")
                        lines.append(f"  • Ballan: {due_date if due_date else 'Lama cayimin'}")
                        lines.append(f"  • Xaalad: {'✅ LA BIXIYAY' if debt_paid else '⏳ WELI LAGAMA BIXIN'}")

                        debt_payments = payments_by_debt.get(str(debt.get("id")), [])
                        if debt_payments:
                            lines.append("  • Lacag-bixinnada:")
                            for payment in debt_payments:
                                paid_amount = float(payment.get("amount") or 0)
                                total_paid += paid_amount
                                paid_date = str(payment.get("paid_at") or "")[:10] or "Taariikh lama hayo"
                                lines.append(f"    - {paid_date}: ${paid_amount:.2f}")
                        else:
                            lines.append("  • Lacag-bixin hore: Ma jirto")
                        lines.append("")

                    # If the same customer has several debt rows, list all associated payments.
                    if not payment_rows:
                        total_paid = 0.0
                    lines.extend([
                        "━━━━━━━━━━━━━━",
                        f"💵 *Wadarta lacagta la bixiyay ee diiwaangashan:* ${total_paid:.2f}",
                        f"📌 *Wadarta hadhaaga deynta:* ${total_balance:.2f}",
                        "_Warbixintani waxay ku salaysan tahay diiwaannada hadda ku jira nidaamka._"
                    ])
                    message = "\n".join(lines)
                    # WhatsApp has a message-size limit; trim long statements safely.
                    if len(message) > 6000:
                        message = message[:5850] + "\n\n… Liiska waa la soo gaabiyay; macmiilku wuxuu leeyahay diiwaanno badan."
                    send_whatsapp(sender_phone, message)
                    try:
                        pdf_bytes = build_statement_pdf(
                            history_matches[0].get("name", name), history_matches,
                            payments_by_debt, total_paid, total_balance
                        )
                        send_whatsapp_file(
                            sender_phone,
                            f"daynjir_statement_{re.sub(r'[^A-Za-z0-9_-]+', '_', str(history_matches[0].get('name', 'customer')))}.pdf",
                            pdf_bytes,
                            "application/pdf",
                            "📄 Statement PDF / Xisaabta macmiilka"
                        )
                    except Exception as pdf_error:
                        print(f"⚠️ PDF statement generation failed: {type(pdf_error).__name__}: {pdf_error}")

            except Exception as e:
                print(f"❌ Statement/history error: {type(e).__name__}: {e}")
                send_whatsapp(sender_phone, "❌ Khalad ayaa dhacay markii la diyaarinayay statement-ka. Hubi payments table iyo permissions-ka.")
                failed_inserts.append({"name": name, "reason": f"History error: {type(e).__name__}: {e}"})
        
        elif action == "REPORT":
            try:
                all_debts_result = (
                    supabase.table("debtors").select("*")
                    .eq("shopkeeper_id", shopkeeper_id).execute()
                )
                all_debts = all_debts_result.data or []
                if not all_debts:
                    send_whatsapp(sender_phone, "✅ Ma jiraan deymo ku jira nidaamka.")
                    continue

                today = today_eat()
                if filter_type == "week":
                    period_start = today - timedelta(days=today.weekday())
                    title = "📊 Warbixinta toddobaadka"
                elif filter_type == "month":
                    period_start = today.replace(day=1)
                    title = "📊 Warbixinta bisha"
                else:
                    period_start = today
                    title = "📊 Warbixinta maanta"

                start_utc = datetime.combine(period_start, datetime.min.time(), tzinfo=EAT).astimezone(timezone.utc)
                end_utc = datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=EAT).astimezone(timezone.utc)
                start_iso = start_utc.isoformat()
                end_iso = end_utc.isoformat()

                payments_result = (
                    supabase.table("payments").select("amount, paid_at, debtor_id")
                    .eq("shopkeeper_id", shopkeeper_id)
                    .gte("paid_at", start_iso).lt("paid_at", end_iso).execute()
                )
                period_payments = payments_result.data or []
                new_debts = [d for d in all_debts if d.get("created_at") and start_iso <= str(d.get("created_at")) < end_iso]
                total_outstanding = sum(max(float(d.get("amount") or 0), 0.0) for d in all_debts if d.get("is_paid") is not True)
                period_collected = sum(float(p.get("amount") or 0) for p in period_payments)
                overdue = [d for d in all_debts if d.get("is_paid") is not True and d.get("promised_date") and str(d.get("promised_date")) < today.isoformat()]
                due_today = [d for d in all_debts if d.get("is_paid") is not True and d.get("promised_date") == today.isoformat()]

                message = (
                    f"{title}\n\n"
                    f"🆕 Diiwaanno deyn cusub ah muddadan: {len(new_debts)}\n"
                    f"💵 Lacag la qabtay muddadan (payments table): ${period_collected:.2f}\n"
                    f"📌 Haraaga guud ee deynta hadda: ${total_outstanding:.2f}\n"
                    f"⚠️ Deyn ballan dhaaftay: {len(overdue)} macaamiil / ${sum(float(d.get('amount') or 0) for d in overdue):.2f}\n"
                    f"📅 Ballan maanta: {len(due_today)} macaamiil\n\n"
                    "Fiiro gaar ah: lacagaha la qabtay waxay ku salaysan yihiin diiwaannada payments; deymo hore oo aan lahayn diiwaan lacag-bixin waxaa laga yaabaa in taariikhdoodu dhammaystirnayn."
                )
                send_whatsapp(sender_phone, message)
            except Exception as e:
                print(f"❌ Report error: {type(e).__name__}: {e}")
                send_whatsapp(sender_phone, "❌ Warbixinta lama diyaarin. Hubi payments table iyo permissions-ka.")
                failed_inserts.append({"name": "REPORT", "reason": str(e)})
        
        elif action == "EXPORT":
            try:
                all_debts_result = (
                    supabase.table("debtors").select("*")
                    .eq("shopkeeper_id", shopkeeper_id)
                    .order("promised_date", desc=False).execute()
                )
                debts_to_export = all_debts_result.data or []
                if not debts_to_export:
                    send_whatsapp(sender_phone, "✅ Ma jiraan deymo la soo saari karo.")
                    continue

                csv_buffer = StringIO()
                writer = csv.writer(csv_buffer)
                writer.writerow(["Name", "Current Balance", "Due Date", "Phone", "Status", "Created At"])
                for debt in debts_to_export:
                    balance = max(float(debt.get("amount") or 0), 0.0)
                    status = "PAID" if debt.get("is_paid") is True or balance <= 0 else "UNPAID"
                    writer.writerow([debt.get("name", ""), f"{balance:.2f}", debt.get("promised_date") or "",
                                     debt.get("phone_number") or "", status, debt.get("created_at") or ""])
                csv_content = csv_buffer.getvalue().encode("utf-8-sig")
                sent = send_whatsapp_file(
                    sender_phone, f"daynjir_debts_{today_eat().isoformat()}.csv", csv_content,
                    "text/csv", f"📥 Deymaha la dhoofiyay: {len(debts_to_export)} diiwaan"
                )
                if not sent:
                    send_whatsapp(sender_phone, "❌ Faylka CSV lama dirin.")
            except Exception as e:
                print(f"❌ Export error: {type(e).__name__}: {e}")
                send_whatsapp(sender_phone, "❌ Dhoofinta CSV way fashilantay.")
                failed_inserts.append({"name": "EXPORT", "reason": str(e)})

    # Send confirmation for ADD actions
    if successful_inserts:
        add_entries = [e for e in successful_inserts if e.get('action') == 'ADD']
        if add_entries:
            if len(add_entries) == 1:
                entry = add_entries[0]
                if entry.get('customer_phone'):
                    success_message = f"✅ Phone saved for {entry['customer_name']}: {entry['customer_phone']}"
                else:
                    success_message = f"""✅ Deyntan waa la keydiyay!

👤 Macmiilka: {entry['customer_name']}
💵 Lacagta: ${entry['amount']}
📅 Ballanta: {entry['promised_date']}"""
            else:
                success_message = f"""✅ Deymahan waa la keydiyay!

"""
                for entry in add_entries:
                    success_message += f"""👤 {entry['customer_name']}: ${entry['amount']} - {entry['promised_date']}
"""
            
            send_whatsapp(sender_phone, success_message)

    if failed_inserts:
        error_message = f"❌ {len(failed_inserts)} deyntii ma keydsamin:\n"
        for fail in failed_inserts:
            error_message += f"- {fail['name']}: {fail['reason']}\n"
        send_whatsapp(sender_phone, error_message)
    
    return {"status": "success"}


def cron_authorized(request: Request):
    secret = os.getenv("CRON_SECRET", "").strip()
    if not secret:
        # Fail closed: configure CRON_SECRET in the deployment environment.
        return False
    supplied = request.headers.get("x-cron-secret", "")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        supplied = auth[7:].strip()
    return hmac.compare_digest(supplied, secret)

@app.get("/cron/daily-digest")
async def daily_digest(request: Request):
    if not cron_authorized(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized cron request")
    print("🔔 DAILY DIGEST STARTED")
    today = today_eat().isoformat()
    print(f"📅 Today's date: {today}")
    
    shopkeepers = supabase.table("shopkeepers").select("*").execute()
    print(f"👥 Found {len(shopkeepers.data)} shopkeepers")
    
    for sk in shopkeepers.data:
        sk_id = sk["id"]
        sk_phone = sk["phone_number"]
        print(f"📱 Processing shopkeeper: {sk_phone} (ID: {sk_id})")
        
        debt_records = supabase.table("debtors").select("*").eq("shopkeeper_id", sk_id).eq("is_paid", False).execute()
        print(f"💰 Found {len(debt_records.data)} unpaid debts")
        
        if not debt_records.data:
            print("⚠️ No debts, skipping...")
            continue
            
        due_today = []
        for record in debt_records.data:
            print(f"  - Checking: {record['name']}, due: {record['promised_date']}")
            due_date = record.get("promised_date")
            if not due_date:
                # Debts without a due date must not crash the reminder job.
                continue
            if str(due_date) <= today:
                print(f"  ✅ Adding to due_today: {record['name']}")
                due_today.append(f"• {record['name']}: ${float(record.get('amount') or 0):.2f} (ballan: {due_date})")
        
        if due_today:
            print(f"📤 Sending message to {sk_phone}")
            msg = "☀️ *Xasuusinta Maalinle ah ee Daynjir* ☀️\n\n*Balamaha maanta & kuwa dhaafay: *\n" + "\n".join(due_today)
            send_whatsapp(sk_phone, msg)
        else:
            print("⚠️ No debts due today")
            
    print("✅ DAILY DIGEST COMPLETED")
    return {"status": "done"}
  
@app.get("/cron/evening-checkin")
async def evening_checkin(request: Request):
    if not cron_authorized(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Unauthorized cron request")
    # East Africa Time is UTC+3.
    now_eat_value = now_eat()
    today = now_eat_value.date()

    # Use UTC boundaries for database timestamps.
    start_utc = datetime.combine(today, datetime.min.time(), tzinfo=EAT).astimezone(timezone.utc)
    end_utc = start_utc + timedelta(days=1)

    start_iso = start_utc.isoformat()
    end_iso = end_utc.isoformat()

    shopkeepers = supabase.table("shopkeepers").select("*").execute()

    for shopkeeper in shopkeepers.data or []:
        shopkeeper_id = shopkeeper["id"]
        shopkeeper_phone = shopkeeper["phone_number"]

        # Debts newly recorded today.
        new_debts_result = (
            supabase.table("debtors")
            .select("name, amount, created_at")
            .eq("shopkeeper_id", shopkeeper_id)
            .gte("created_at", start_iso)
            .lt("created_at", end_iso)
            .execute()
        )
        new_debts = new_debts_result.data or []

        # Payments recorded today.
        payments_result = (
            supabase.table("payments")
            .select("amount, paid_at, debtor_id")
            .eq("shopkeeper_id", shopkeeper_id)
            .gte("paid_at", start_iso)
            .lt("paid_at", end_iso)
            .execute()
        )
        payments = payments_result.data or []

        lines = ["🌙 *Natiijada maanta*"]

        if not new_debts and not payments:
            lines.extend([
                "",
                "Maanta maxaa deyn soo xarooday, maxaase kaa baxay?",
            ])
        else:
            lines.append("")

            if new_debts:
                lines.append("🆕 *Liiska Deymaha kaa baxay maanta:*")
              
                for debt in new_debts:
                    lines.append(
                        f"• {debt['name']}: ${float(debt['amount']):.2f}"
                    )


            if payments:
                lines.append("")
                lines.append("💵 *Daymaha maanta kuusoo xarooday:*")

                for payment in payments:
                    debtor_result = (
                        supabase.table("debtors")
                        .select("name")
                        .eq("id", payment["debtor_id"])
                        .eq("shopkeeper_id", shopkeeper_id)
                        .limit(1)
                        .execute()
                    )
                    debtor_name = (
                        debtor_result.data[0]["name"]
                        if debtor_result.data
                        else "Macmiil"
                    )
                    lines.append(
                        f"• {debtor_name}: ${float(payment['amount']):.2f}"
                    )
            else:
                lines.append("")
                lines.append("💵 Ma jirto lacag-bixin la diiwaangeliyay maanta.")

            lines.extend([
                "",
                "Hadii ay jiraan Deymo kale oo maanta soo xarooday "
                "ama mid cusub oo baxday?",
                "fadlan ii soo dir magaca iyo lacagta."
            ])

        send_whatsapp(shopkeeper_phone, "\n".join(lines))

    return {"status": "evening_checkin_sent"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
