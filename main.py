import os
import re
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException, status
from supabase import create_client, Client
from groq import Groq
import requests
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Connect to services
#  The Fixed Line 16:
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


# FIXED: Correct URL structure for Green-API endpoints
#  The Fixed Line:
INSTANCE_ID = os.getenv("GREEN_API_INSTANCE_ID")
GREEN_API_URL = f"https://green-api.com{INSTANCE_ID}"
GREEN_API_TOKEN = os.getenv("b3a2ccc5aa654185afdf4eaf22bd9c3a2b766efcc9d44ac1a3")


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
'Lacagtiisii xasan waa laga qabtay' -> {"action": "PAY", "customer_name": "Xasan", "amount": null, "days_until_due": null, "customer_phone": null}
"""

def send_whatsapp(to_phone: str, message: str):
    # FIXED: Added correct method appending logic for Green-API
    url = f"{GREEN_API_URL}/sendMessage/{GREEN_API_TOKEN}"
    payload = {"chatId": f"{to_phone}@c.us", "message": message}
    try:
        response = requests.post(url, json=payload, timeout=10)
        print(f"WhatsApp response status: {response.status_code}")
    except Exception as e:
        print(f"Error sending WhatsApp: {e}")

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    
    if data.get("typeWebhook") != "incomingMessageReceived":
        return {"status": "ignored"}
        
    sender_chat_id = data["senderData"]["chatId"]
    sender_phone = sender_chat_id.split("@")[0]
    
    try:
        message_text = data["messageData"]["textMessageData"]["textMessage"]
    except KeyError:
        return {"status": "no_text_payload"}
    
    # Check/Create shopkeeper record
    sk_query = supabase.table("shopkeepers").select("*").eq("phone_number", sender_phone).execute()
    if not sk_query.data:
        sk_insert = supabase.table("shopkeepers").insert({"phone_number": sender_phone}).execute()
        shopkeeper_id = sk_insert.data[0]["id"]
    else:
        shopkeeper_id = sk_query.data[0]["id"]

    # Call Groq AI LLM Engine
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
        send_whatsapp(sender_phone, "❌ Daynjir waa fahmi waayay qoraalkaaga. Fadlan u qor si cad (Tusaale: 'Cali 15$ maanta' ama 'Cali wuu bixiyay').")
        return {"status": "parsing_failed"}

    action = parsed.get("action", "ADD")
    name = parsed.get("customer_name")
    
    if not name:
        send_whatsapp(sender_phone, "❌ Fadlan qor magaca macmiilka si sax ah.")
        return {"status": "incomplete_data"}

    # --- STRATEGY 1: PROCESS DEBT PAYMENTS ---
    if action == "PAY":
        # Look for active unpaid debts for this customer under this shopkeeper
        debt_check = supabase.table("debtors")\
            .select("*")\
            .eq("shopkeeper_id", shopkeeper_id)\
            .ilike("name", f"%{name}%")\
            .eq("is_paid", False)\
            .execute()
            
        if debt_check.data:
            # Mark them paid
            for record in debt_check.data:
                supabase.table("debtors").update({"is_paid": True}).eq("id", record["id"]).execute()
            send_whatsapp(sender_phone, f"✅ Waalala keydiyay! Koontada {name} waxaa loo calaamadeeyay in la bixiyay (Paid).")
            return {"status": "success_paid"}
        else:
            send_whatsapp(sender_phone, f"ℹ️ Wax deyn ah oo u furan {name} lagama helin nidaamka.")
            return {"status": "no_active_debt_found"}

    # --- STRATEGY 2: PROCESS NEW DEBT ENTRIES ---
    amount = parsed.get("amount")
    days = parsed.get("days_until_due")
    debtor_phone = parsed.get("customer_phone")
    
    if not amount:
        send_whatsapp(sender_phone, "❌ Fadlan qor lacagta deynta si sax ah.")
        return {"status": "incomplete_data"}

    if days is None:
        days = 0

    promised_date = (datetime.utcnow() + timedelta(days=int(days))).date().isoformat()

    supabase.table("debtors").insert({
        "shopkeeper_id": shopkeeper_id,
        "name": name,
        "amount": amount,
        "promised_date": promised_date,
        "phone_number": debtor_phone,
        "is_paid": False
    }).execute()

    send_whatsapp(sender_phone, f"✅ Deyntii waa la keydiyay!\n👤 Macmiilka: {name}\n💵 Lacagta: ${amount}\n📅 Ballanta: {promised_date}")
    return {"status": "success_add"}


# --- NEW: DAILY MORNING DIGEST CRON ENGINE ---
@app.get("/cron/daily-digest")
async def daily_digest():
    today = datetime.utcnow().date().isoformat()
    
    # Get all active shopkeepers
    shopkeepers = supabase.table("shopkeepers").select("*").execute()
    
    for sk in shopkeepers.data:
        sk_id = sk["id"]
        sk_phone = sk["phone_number"]
        
        # Pull up all active unpaid rows for this shopkeeper
        debt_records = supabase.table("debtors")\
            .select("*")\
            .eq("shopkeeper_id", sk_id)\
            .eq("is_paid", False)\
            .execute()
            
        if not debt_records.data:
            continue
            
        due_today = []
        overdue = []
        
        for record in debt_records.data:
            p_date = record["promised_date"]
            entry_summary = f"• {record['name']}: ${record['amount']}"
            
            if p_date == today:
                due_today.append(entry_summary)
            elif p_date < today:
                days_past = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(p_date, "%Y-%m-%d")).days
                due_today.append(f"• {record['name']}: ${record['amount']} ({days_past} bari baa dhaaftay)")
        
        # Build out digestible message layout
        digest_msg = "☀️ *Xasuusinta Maalinle ah ee Daynjir* ☀️\n\n"
        
        if due_today:
            digest_msg += "📅 *Kuwa Maanta laga filayo (Due Today):*\n" + "\n".join(due_today) + "\n\n"
        if overdue:
            digest_msg += "🚨 *Kuwa Wakhtigii dhaafay (Overdue):*\n" + "\n".join(overdue) + "\n\n"
            
        if due_today or overdue:
            digest_msg += "💡 _Waxaad u qori kartaa 'Magaca wuu bixiyay' si aad koontada uga masaxdo._"
            send_whatsapp(sk_phone, digest_msg)
            
    return {"status": "digests_sent", "date": today}
