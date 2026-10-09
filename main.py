import os
import re
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from supabase import create_client, Client
from groq import Groq
import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import pandas as pd
from io import BytesIO

load_dotenv()

# Setup the core application framework
app = FastAPI()

# Securely load credentials from Render's Environment panel variables
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

INSTANCE_ID = "710722758620"
GREEN_API_TOKEN = "feb8f9b99fa047a3b8b3442b303b6cbb8564a60129604f149c"
GREEN_API_BASE = "https://7107.api.greenapi.com"

SYSTEM_PROMPT = """You are Daynjir, a Somali debt management assistant for small shopkeepers. 
Extract transaction intent from chaotic, unstructured Somali text into raw JSON. 
Do not include any conversational filler, markdown syntax, or backticks.

Extract ALL debt entries from the message.
For each entry, extract: customer_name, amount, promised_date (YYYY-MM-DD), phone_number

ALWAYS return a JSON array, even for single entries.

Response format (JSON array):
[
  {"action": "ADD" or "PAY" or "LIST" or "SEARCH" or "EDIT" or "DELETE" or "HISTORY" or "REPORT" or "EXPORT", "customer_name": "string or null", "amount": number or null, "days_until_due": number or null, "customer_phone": "string or null", "promised_date": "YYYY-MM-DD or null", "filter_date": "YYYY-MM-DD or null", "filter_type": "today" or "tomorrow" or "date" or "week" or "month" or null, "new_amount": number or null, "new_date": "YYYY-MM-DD or null", "new_phone": "string or null"}
]

Examples - ADD:
'Cali 20$ oo bari ah' -> Use today's date + 1 day for promised_date
'Cali $34 oct 8, Axmed $50 oct 9' -> [{"action": "ADD", "customer_name": "Cali", "amount": 34, "days_until_due": 1, "customer_phone": null, "promised_date": "YYYY-MM-DD", "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}, {"action": "ADD", "customer_name": "Axmed", "amount": 50, "days_until_due": 2, "customer_phone": null, "promised_date": "YYYY-MM-DD", "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]

Examples - PAY:
'Cali wuu bixiyay' -> [{"action": "PAY", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]
'Gaawe wuxuu bixiyay $5' -> [{"action": "PAY", "customer_name": "Gaawe", "amount": 5, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null, "new_amount": null, "new_date": null, "new_phone": null}]
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
    url = "https://7107.api.greenapi.com/waInstance710722758620/sendMessage/feb8f9b99fa047a3b8b3442b303b6cbb8564a60129604f149c"
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

OWNER_PHONE = os.getenv("OWNER_PHONE", "").lstrip("+").strip()

@app.get("/")
def home():
    return {"status": "Daynjir Bot Engine is running live."}
def find_debtor_matches(shopkeeper_id, name):
    result = (
        supabase.table("debtors")
        .select("*")
        .eq("shopkeeper_id", shopkeeper_id)
        .eq("is_paid", False)
        .ilike("name", f"%{name.strip()}%")
        .order("name")
        .execute()
    )
    return result.data or []


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
    print(f"📥 RAW GREEN-API WEBHOOK PAYLOAD: {json.dumps(data)}")
    
    allowed_types = ["incomingMessageReceived", "outgoingMessageReceived"]
    if data.get("typeWebhook") not in allowed_types:
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
                                        datetime.utcnow() + timedelta(hours=3)
                                    ).date().isoformat()
                        else:
                            due_date = (
                                datetime.utcnow() + timedelta(hours=3)
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
                "⏳ You are not registered. Send JOIN to request access."
            )
            return {"status": "not_registered"}

        shopkeeper = sk_query.data[0]
        if shopkeeper.get("approval_status") != "approved":
            send_whatsapp(
                sender_phone,
                "⏳ Your request is pending approval. Please wait for the owner."
            )
            return {"status": "not_approved"}

        shopkeeper_id = shopkeeper["id"]

    except Exception as db_err:
        print(f"❌ DATABASE ERROR (Shopkeepers Lookup): {db_err}")
        return {"status": "shopkeeper_db_error"}
    
    today_str = (datetime.utcnow() + timedelta(hours=3)).date().isoformat()
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
        instructions = """❌ Ma fahmin qoraalkaaga.

📖 **Fadlan Raac Tilmaamahan:*

✅ **si aad u Keydiso deyn cusub:**
   qor magaca iyo $ lacagta
   tusaale:
   Axmed $100 balanta=beri

✅ **Liiska deynta:
   Liiska deynta
   Balamaha maanta

✅ **Deyn bixinta:
   Cali wuu bixiyay
   Axmed wuxuu bixiyay $50

✅ **Tirtir:
   delete Cali
   remove Axmed

✅ **Warbixin:**
   Report
  """
        
        send_whatsapp(sender_phone, instructions)
        return {"status": "parsing_failed"}

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
        filter_date = entry.get("filter_date")
        filter_type = entry.get("filter_type")
        
        if not name and action not in ["LIST", "REPORT", "EXPORT"]:
            failed_inserts.append({"name": "Unknown", "reason": "No name"})
            continue
        
        if action == "ADD":
            try:
                if not promised_date and days_until_due is not None:
                    promised_date = (datetime.utcnow() + timedelta(days=int(days_until_due))).date().isoformat()
                elif not promised_date:
                    promised_date = datetime.utcnow().date().isoformat()
                
                if new_phone and not amount:
                    debtor_query = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).ilike("name", f"%{name}%").eq("is_paid", False).limit(1).execute()
                    if debtor_query.data:
                        updated = supabase.table("debtors").update({"phone_number": new_phone}).eq("shopkeeper_id", shopkeeper_id).eq("name", debtor_query.data[0]["name"]).execute()
                        send_whatsapp(sender_phone, f"✅ {name} phone number saved: {new_phone}")
                        successful_inserts.append(entry)
                        continue
                    else:
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
                matches = find_debtor_matches(shopkeeper_id, name)

                if len(matches) == 0:
                    send_whatsapp(sender_phone, f"❌ Lama helin deynta {name}.")
                    failed_inserts.append({
                        "name": name,
                        "reason": "Debtor not found"
                    })
                    continue

                if len(matches) > 1:
                    ask_for_full_name(sender_phone, matches, "PAY")
                    continue

                debtor = matches[0]
                current_balance = float(debtor["amount"])

                # No amount specified: treat this as full payment.
                if payment_amount is None:
                    if current_balance <= 0:
                        send_whatsapp(
                            sender_phone,
                            f"✅ {debtor['name']} hore ayuu u bixiyay deyntiisa."
                        )
                        continue

                    # Save the payment transaction before updating the balance.
                    supabase.table("payments").insert({
                        "debtor_id": debtor["id"],
                        "shopkeeper_id": shopkeeper_id,
                        "amount": current_balance
                    }).execute()

                    (
                        supabase.table("debtors")
                        .update({"amount": 0, "is_paid": True})
                        .eq("id", debtor["id"])
                        .eq("shopkeeper_id", shopkeeper_id)
                        .execute()
                    )

                    send_whatsapp(
                        sender_phone,
                        f"✅ {debtor['name']} wuu bixiyay deyntii oo dhan "
                        f"(${current_balance:.2f})."
                    )

                else:
                    payment_amount = float(payment_amount)

                    if payment_amount <= 0:
                        send_whatsapp(
                            sender_phone,
                            "❌ Lacagta la bixiyay waa inay ka badan tahay $0."
                        )
                        continue

                    if current_balance <= 0:
                        send_whatsapp(
                            sender_phone,
                            f"✅ {debtor['name']} hore ayuu u bixiyay deyntiisa."
                        )
                        continue

                    actual_payment = min(payment_amount, current_balance)
                    new_balance = current_balance - actual_payment

                    # Save the transaction.
                    supabase.table("payments").insert({
                        "debtor_id": debtor["id"],
                        "shopkeeper_id": shopkeeper_id,
                        "amount": actual_payment
                    }).execute()

                    if new_balance <= 0:
                        (
                            supabase.table("debtors")
                            .update({"amount": 0, "is_paid": True})
                            .eq("id", debtor["id"])
                            .eq("shopkeeper_id", shopkeeper_id)
                            .execute()
                        )

                        send_whatsapp(
                            sender_phone,
                            f"✅ {debtor['name']} wuu bixiyay deyntii oo dhan. "
                            f"Lacagta la diiwaangeliyay: ${actual_payment:.2f}."
                        )
                    else:
                        (
                            supabase.table("debtors")
                            .update({"amount": new_balance, "is_paid": False})
                            .eq("id", debtor["id"])
                            .eq("shopkeeper_id", shopkeeper_id)
                            .execute()
                        )

                        send_whatsapp(
                            sender_phone,
                            f"✅ {debtor['name']} wuxuu bixiyay "
                            f"${actual_payment:.2f}. "
                            f"Haray: ${new_balance:.2f}"
                        )

            except Exception as e:
                print(f"❌ Payment error: {e}")
                send_whatsapp(
                    sender_phone,
                    "❌ Khalad ayaa dhacay marka lacagta la bixinayay."
                )
                failed_inserts.append({
                    "name": name,
                    "reason": f"Payment error: {str(e)}"
                })
        
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
                            f"✅ Ma jiraan deymo balanteedu tahay {filter_date}."
                        )
                        send_due_list_followup(sender_phone)
                    else:
                        send_whatsapp(
                            sender_phone,
                            "✅ Ma jiraan deyn aan la bixin."
                        )
                    continue

                debt_list = []
                total = 0
                overdue_count = 0
                today = datetime.utcnow().date()

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
                        f"⚠️ {overdue_count} deyn balan dhaafay:\n\n"
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
                    send_whatsapp(sender_phone, f"❌ Lama helin {name}.")
                    failed_inserts.append({
                        "name": name,
                        "reason": "Debtor not found"
                    })
                    continue

                if len(matches) > 1:
                    ask_for_full_name(sender_phone, matches, "EDIT")
                    continue

                debtor = matches[0]

                update_data = {}

                if new_amount is not None:
                    update_data["amount"] = float(new_amount)

                if new_date is not None:
                    update_data["promised_date"] = new_date

                if not update_data:
                    send_whatsapp(
                        sender_phone,
                        "❌ Wax isbeddel ah lama helin.\n"
                        "Tusaale: edit Ali Hassan $50"
                    )
                    failed_inserts.append({
                        "name": name,
                        "reason": "No changes supplied"
                    })
                    continue

                (
                    supabase.table("debtors")
                    .update(update_data)
                    .eq("id", debtor["id"])
                    .eq("shopkeeper_id", shopkeeper_id)
                    .execute()
                )

                changes = []

                if "amount" in update_data:
                    changes.append(
                        f"💵 Lacag: ${debtor['amount']} → ${update_data['amount']}"
                    )

                if "promised_date" in update_data:
                    changes.append(
                        f"📅 Ballan: {debtor['promised_date']} → "
                        f"{update_data['promised_date']}"
                    )

                send_whatsapp(
                    sender_phone,
                    f"✅ {debtor['name']} waa la cusboonaysiiyay:\n"
                    + "\n".join(changes)
                )
                successful_inserts.append(entry)

            except Exception as e:
                print(f"❌ Edit error: {e}")
                send_whatsapp(
                    sender_phone,
                    "❌ Khalad ayaa dhacay marka deynta la beddelayay."
                )
                failed_inserts.append({
                    "name": name,
                    "reason": f"Edit error: {str(e)}"
                })

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
        
        elif action == "HISTORY":
            try:
                # Get all debts (paid + unpaid) for this person
                debts_query = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).ilike("name", f"%{name}%").order("created_at", desc=True).execute()
                
                if not debts_query.data:
                    send_whatsapp(sender_phone, f"❌ No history found for {name}.")
                else:
                    history_list = []
                    for i, debt in enumerate(debts_query.data, 1):
                        status = "✅ PAID" if debt['is_paid'] else "⏳ UNPAID"
                        history_list.append(f"{i}. {debt['name']}: ${debt['amount']} - {debt['promised_date']} [{status}]")
                    
                    message = f"📜 *History for {name}* ({len(debts_query.data)} records):\n\n" + "\n".join(history_list)
                    
                    send_whatsapp(sender_phone, message)
                    
            except Exception as e:
                send_whatsapp(sender_phone, f"❌ Khalad: {str(e)}")
                failed_inserts.append({"name": name, "reason": f"History error: {str(e)}"})
        
        elif action == "REPORT":
            try:
                # Get all debts
                all_debts = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).execute()
                
                if not all_debts.data:
                    send_whatsapp(sender_phone, "✅ No debts found.")
                else:
                    total_added = sum(d['amount'] for d in all_debts.data)
                    paid_debts = [d for d in all_debts.data if d['is_paid']]
                    unpaid_debts = [d for d in all_debts.data if not d['is_paid']]
                    total_paid = sum(d['amount'] for d in paid_debts)
                    total_unpaid = sum(d['amount'] for d in unpaid_debts)
                    
                    if filter_type == "week":
                        title = "📊 *Weekly Report*"
                    elif filter_type == "month":
                        title = "📊 *Monthly Report*"
                    else:
                        title = "📊 *Full Report*"
                    
                    message = f"""{title}

💰 **Total Added:** ${total_added:.2f}
✅ **Total Paid:** ${total_paid:.2f}
⏳ **Total Unpaid:** ${total_unpaid:.2f}

📈 **Collection Rate:** {(total_paid/total_added*100) if total_added > 0 else 0:.1f}%

👥 **Debtors:** {len(all_debts.data)}
   - Paid: {len(paid_debts)}
   - Unpaid: {len(unpaid_debts)}"""
                    
                    send_whatsapp(sender_phone, message)
                    
            except Exception as e:
                send_whatsapp(sender_phone, f"❌ Khalad: {str(e)}")
                failed_inserts.append({"name": "REPORT", "reason": f"Report error: {str(e)}"})
        
        elif action == "EXPORT":
            try:
                # Get all debts
                all_debts = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).order("promised_date", desc=False).execute()
                
                if not all_debts.data:
                    send_whatsapp(sender_phone, "✅ No debts to export.")
                else:
                    # Format as CSV-like text
                    export_text = "NAME,AMOUNT,DUE DATE,PHONE,STATUS\n"
                    for debt in all_debts.data:
                        status = "PAID" if debt['is_paid'] else "UNPAID"
                        phone = debt.get('phone_number') or ""
                        export_text += f"{debt['name']},{debt['amount']},{debt['promised_date']},{phone},{status}\n"
                    
                    # Split into chunks (WhatsApp message limit)
                    chunks = [export_text[i:i+1000] for i in range(0, len(export_text), 1000)]
                    
                    send_whatsapp(sender_phone, f"📥 **EXPORT DATA** ({len(all_debts.data)} debts):\n\n(Copy this to Excel/Sheets)\n\n")
                    for chunk in chunks:
                        send_whatsapp(sender_phone, f"```\n{chunk}\n```")
                    
                    send_whatsapp(sender_phone, f"\n✅ Export complete! Copy the data above and paste into Excel or Google Sheets.")
                    
            except Exception as e:
                send_whatsapp(sender_phone, f"❌ Khalad: {str(e)}")
                failed_inserts.append({"name": "EXPORT", "reason": f"Export error: {str(e)}"})

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


@app.get("/cron/daily-digest")
async def daily_digest():
    print("🔔 DAILY DIGEST STARTED")
    today = (datetime.utcnow() + timedelta(hours=3)).date().isoformat()
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
            if record["promised_date"] <= today:
                print(f"  ✅ Adding to due_today: {record['name']}")
                due_today.append(f"• {record['name']}: ${record['amount']}")
        
        if due_today:
            print(f"📤 Sending message to {sk_phone}")
            msg = "☀️ *Xasuusinta Maalinle ah ee Daynjir* ☀️\n\n*Balamaha maanta & kuwa dhaafay: *\n" + "\n".join(due_today)
            send_whatsapp(sk_phone, msg)
        else:
            print("⚠️ No debts due today")
            
    print("✅ DAILY DIGEST COMPLETED")
    return {"status": "done"}
  
@app.get("/cron/evening-checkin")
async def evening_checkin():
    # East Africa Time is UTC+3.
    now_eat = datetime.utcnow() + timedelta(hours=3)
    today = now_eat.date()

    # Use UTC boundaries for database timestamps.
    start_utc = datetime(today.year, today.month, today.day) - timedelta(hours=3)
    end_utc = start_utc + timedelta(days=1)

    start_iso = start_utc.isoformat() + "+00:00"
    end_iso = end_utc.isoformat() + "+00:00"

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
                lines.append("💵 *Daynta maanta kuusoo xarootay:*")

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
