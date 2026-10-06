import os
import re
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from supabase import create_client, Client
from groq import Groq
import requests
from dotenv import load_dotenv

load_dotenv()

# Uvicorn looks for this exact variable to run the application
app = FastAPI()
# Connect to your services using Render variables (DO NOT PASTE RAW URLS HERE)
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# FIXED: Standardized, official Green-API base URL path format using environment variables
INSTANCE_ID = os.getenv("GREEN_API_INSTANCE_ID")
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN")
GREEN_API_URL = f"https://green-api.com{INSTANCE_ID}"


SYSTEM_PROMPT = """You are Daynjir, a Somali debt management assistant for small shopkeepers. 
Extract transaction intent from chaotic, unstructured Somali text into raw JSON. 
Do not include any conversational filler, markdown syntax, or backticks.

Determine if the shopkeeper wants to ADD a new debt or mark an existing debt as PAID.

Response format: 
{"action": "ADD" or "PAY", "customer_name": "string or null", "amount": number or null, "days_until_due": number or null, "customer_phone": "string or null"}

Examples:
'Cali 20$ oo bari ah lambarkisu waa 252634444444' -> {"action": "ADD", "customer_name": "Cali", "amount": 20, "days_until_due": 1, "customer_phone": "252634444444"}
'Xasan baa 15 doolar qaatay maanta' -> {"action": "ADD", "customer_name": "Xasan", "amount": 15, "days_until_due": 0, "customer_phone": null}
'Cali wuu bixiyay hantidii' -> {"action": "PAY", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null}
"""

def send_whatsapp(to_phone: str, message: str):
    url = f"{GREEN_API_URL}/sendMessage/{GREEN_API_TOKEN}"
    payload = {"chatId": f"{to_phone}@c.us", "message": message}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Error dispatching WhatsApp outbound request: {e}")

@app.get("/")
def home():
    # Adding a clean root route so visiting the base domain doesn't throw a 404
    return {"status": "Daynjir Bot Engine is running live."}

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    
    print(f"📥 RAW GREEN-API PAYHOOK PAYLOAD: {json.dumps(data)}")
    
    #  FIXED: Allow both incoming messages AND messages you type on your own instance phone
    allowed_types = ["incomingMessageReceived", "outgoingMessageReceived"]
    if data.get("typeWebhook") not in allowed_types:
        return {"status": "ignored"}
        
    sender_data = data.get("senderData", {})
    sender_chat_id = sender_data.get("chatId")
    if not sender_chat_id:
        return {"status": "no_chat_id"}
        
    #  FIXED: Correctly get the clean phone number string from the text instead of a list object
    #  THE FIX: Add [0] at the end to get the clean text string "252633732215"
sender_phone = sender_chat_id.split("@")[0]
    
    # Extract message text safely whether it's a standard text or extended link text
    message_data = data.get("messageData", {})
    type_message = message_data.get("typeMessage")
    
    message_text = ""
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
    
    # Check/Create shopkeeper safely with string layout parameters
    try:
        sk_query = supabase.table("shopkeepers").select("*").eq("phone_number", sender_phone).execute()
        if not sk_query.data:
            sk_insert = supabase.table("shopkeepers").insert({"phone_number": sender_phone}).execute()
            shopkeeper_id = sk_insert.data[0]["id"]
        else:
            shopkeeper_id = sk_query.data[0]["id"]
    except Exception as db_err:
        print(f"❌ DATABASE ERROR (Shopkeepers Lookup): {db_err}")
        return {"status": "shopkeeper_db_error"}

    # Process unstructured text via Groq AI Cloud
       # Pass today's absolute calendar date context to help the LLM process deadline offsets
    today_str = datetime.utcnow().date().isoformat()
    dynamic_system_prompt = f"{SYSTEM_PROMPT}\nToday's date is strictly: {today_str}. Use this to calculate calendar targets or relative days offsets like 'berri'."

       # Pass today's absolute calendar date context to help the LLM process deadline offsets
    today_str = datetime.utcnow().date().isoformat()
    dynamic_system_prompt = f"{SYSTEM_PROMPT}\nToday's date is strictly: {today_str}. Use this to calculate calendar targets or relative days offsets like 'berri'."

    chat_completion = groq_client.chat.completions.create(
        messages=[{"role": "system", "content": dynamic_system_prompt}, {"role": "user", "content": message_text}],
        model="openai/gpt-oss-20b",
        temperature=0.0
    )
    
    #  FIXED: Robust handling to read content whether Groq returns an object or a list
    try:
        if isinstance(chat_completion, list):
            ai_response = chat_completion[0].get("message", {}).get("content", "").strip()
        else:
            ai_response = chat_completion.choices[0].message.content.strip()
    except Exception as parse_err:
        # Fallback tracking if structure shifts drastically
        print(f"⚠️ Direct extraction failed, casting raw string: {parse_err}")
        ai_response = str(chat_completion).strip()
        
    print(f"🤖 Groq AI Processed Output: {ai_response}")

    try:
        clean_json = re.search(r'\{.*\}', ai_response, re.DOTALL).group()
        parsed = json.loads(clean_json)
    except Exception:
        send_whatsapp(sender_phone, "❌ Daynjir waa fahmi waayay qoraalkaaga. Fadlan u qor si cad.")
        return {"status": "parsing_failed"}

    action = parsed.get("action", "ADD")
    name = parsed.get("customer_name")
    
    if not name:
        send_whatsapp(sender_phone, "❌ Magaca macmiilka si sax ah looma helin.")
        return {"status": "incomplete_data"}

    if action == "PAY":
        try:
            supabase.table("debtors").update({"is_paid": True}).eq("shopkeeper_id", shopkeeper_id).ilike("name", f"%{name}%").execute()
            send_whatsapp(sender_phone, f"✅ Koontada {name} waxaa loo calaamadeeyay in la bixiyay!")
            return {"status": "success_paid"}
        except Exception as pay_err:
            print(f"❌ DATABASE ERROR (Update Pay Status): {pay_err}")
            return {"status": "pay_db_error"}

    amount = parsed.get("amount")
    days = parsed.get("days_until_due", 0)
    debtor_phone = parsed.get("customer_phone")

    if not amount:
        send_whatsapp(sender_phone, "❌ Fadlan qor lacagta deynta si sax ah.")
        return {"status": "incomplete_amount"}

    promised_date = (datetime.utcnow() + timedelta(days=int(days if days is not None else 0))).date().isoformat()

    try:
        insert_payload = {
            "shopkeeper_id": int(shopkeeper_id),
            "name": str(name),
            "amount": float(amount),
            "promised_date": promised_date,
            "phone_number": str(debtor_phone) if debtor_phone else None,
            "is_paid": False
        }
        print(f"⚙️ Attempting Supabase Insert Payload: {insert_payload}")
        
        db_res = supabase.table("debtors").insert(insert_payload).execute()
        print(f"✅ Supabase Database Response Data: {db_res.data}")
        
        send_whatsapp(sender_phone, f"✅ Deyntii waa la keydiyay!\n👤 Macmiilka: {name}\n💵 Lacagta: ${amount}\n📅 Ballanta: {promised_date}")
        return {"status": "success_add"}
    except Exception as insert_err:
        print(f"❌ DATABASE ERROR (Debtors Insertion Failure): {insert_err}")
        return {"status": "debtor_insert_db_error"}

    sender_chat_id = data["senderData"]["chatId"]
    # FIXED: Cleans string layout immediately to avoid array mismatches in Supabase filters
    sender_phone = sender_chat_id.split("@")[0]
    
    try:
        message_text = data["messageData"]["textMessageData"]["textMessage"]
    except KeyError:
        return {"status": "no_text_payload"}
    
    # Safe database lookups for registered shopkeepers
    try:
        sk_query = supabase.table("shopkeepers").select("*").eq("phone_number", sender_phone).execute()
        if not sk_query.data:
            sk_insert = supabase.table("shopkeepers").insert({"phone_number": sender_phone}).execute()
            shopkeeper_id = sk_insert.data[0]["id"]
        else:
            shopkeeper_id = sk_query.data[0]["id"]
    except Exception as db_err:
        print(f"❌ DATABASE ERROR (Shopkeeper configuration lookup): {db_err}")
        return {"status": "shopkeeper_lookup_failed"}

    # Process unstructured message using Groq AI
    chat_completion = groq_client.chat.completions.create(
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": message_text}],
        model="llama3-8b-8192",
        temperature=0.0
    )
    
    ai_response = chat_completion.choices.message.content.strip()
    
    try:
        clean_json = re.search(r'\{.*\}', ai_response, re.DOTALL).group()
        parsed = json.loads(clean_json)
    except Exception:
        send_whatsapp(sender_phone, "❌ Daynjir fariintaada si sax ah uma fahmi waayay. Fadlan u qor si cad (Tusaale: 'Cali $15 maanta').")
        return {"status": "parsing_failed"}

    action = parsed.get("action", "ADD")
    name = parsed.get("customer_name")
    
    if not name:
        send_whatsapp(sender_phone, "❌ Magaca macmiilka si cad looma helin fariintaada.")
        return {"status": "missing_customer_name"}

    # Strategy 1: Clear existing active balances
    if action == "PAY":
        try:
            # Query for active rows matching criteria matching name string variables
            check_debts = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).ilike("name", f"%{name}%").eq("is_paid", False).execute()
            if check_debts.data:
                supabase.table("debtors").update({"is_paid": True}).eq("shopkeeper_id", shopkeeper_id).ilike("name", f"%{name}%").execute()
                send_whatsapp(sender_phone, f"✅ Koontada {name} waxaa loo calaamadeeyay in la bixiyay (Paid)!")
                return {"status": "success_paid"}
            else:
                send_whatsapp(sender_phone, f"ℹ️ Wax deyn oo u furan {name} lagama helin diiwaanka.")
                return {"status": "no_open_debt"}
        except Exception as pay_err:
            print(f"❌ DATABASE ERROR (Processing payment update): {pay_err}")
            return {"status": "payment_update_failed"}

    # Strategy 2: Record new entries securely into debtors ledger
    amount = parsed.get("amount")
    days = parsed.get("days_until_due", 0)
    debtor_phone = parsed.get("customer_phone")

    if not amount:
        send_whatsapp(sender_phone, "❌ Fadlan qor lacagta deynta cadadkeeda si sax ah.")
        return {"status": "missing_amount"}

    promised_date = (datetime.utcnow() + timedelta(days=int(days if days is not None else 0))).date().isoformat()

    try:
        insert_payload = {
            "shopkeeper_id": int(shopkeeper_id),
            "name": str(name),
            "amount": float(amount),
            "promised_date": promised_date,
            "phone_number": str(debtor_phone) if debtor_phone else None,
            "is_paid": False
        }
        
        db_res = supabase.table("debtors").insert(insert_payload).execute()
        print(f"✅ Supabase Response Data: {db_res.data}")
        
        send_whatsapp(sender_phone, f"✅ Deyntii waa la keydiyay!\n👤 Macmiilka: {name}\n💵 Lacagta: ${amount}\n📅 Ballanta: {promised_date}")
        return {"status": "success_add"}
    except Exception as insert_err:
        print(f"❌ DATABASE ERROR (Failed adding row record): {insert_err}")
        return {"status": "ledger_insertion_failed"}

@app.get("/cron/daily-digest")
async def daily_digest():
    today = datetime.utcnow().date().isoformat()
    try:
        shopkeepers = supabase.table("shopkeepers").select("*").execute()
        
        for sk in shopkeepers.data:
            sk_id = sk["id"]
            sk_phone = sk["phone_number"]
            
            debt_records = supabase.table("debtors").select("*").eq("shopkeeper_id", sk_id).eq("is_paid", False).execute()
            if not debt_records.data:
                continue
                
            due_today = []
            for record in debt_records.data:
                if record["promised_date"] <= today:
                    due_today.append(f"• {record['name']}: ${record['amount']}")
            
            if due_today:
                msg = "☀️ *Xasuusinta Maalinle ah ee Daynjir* ☀️\n\n*Kuwa maanta laga filayo ama dhaafay:*\n" + "\n".join(due_today)
                send_whatsapp(sk_phone, msg)
                
        return {"status": "all_digests_processed"}
    except Exception as cron_err:
        print(f"❌ CRON RUNTIME ERROR: {cron_err}")
        return {"status": "cron_failed"}
