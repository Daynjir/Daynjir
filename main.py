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

Determine if the shopkeeper wants to ADD a new debt, mark an existing debt as PAID, or LIST their debts.
Carefully calculate 'days_until_due' by finding the difference between today's date and the requested promise target deadline date mentioned in the message text.

Response format: 
{"action": "ADD" or "PAY" or "LIST", "customer_name": "string or null", "amount": number or null, "days_until_due": number or null, "customer_phone": "string or null"}

Examples:
'Cali 20$ oo bari ah' -> {"action": "ADD", "customer_name": "Cali", "amount": 20, "days_until_due": 1, "customer_phone": null}
'Xasan baa 15 doolar qaatay maanta' -> {"action": "ADD", "customer_name": "Xasan", "amount": 15, "days_until_due": 0, "customer_phone": null}
'Cali wuu bixiyay hantidii' -> {"action": "PAY", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null}
'Gaawe wuxuu bixiyay $5' -> {"action": "PAY", "customer_name": "Gaawe", "amount": 5, "days_until_due": null, "customer_phone": null}
'List my debts' -> {"action": "LIST", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null}
'My debts' -> {"action": "LIST", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null}
'Liiska deynta' -> {"action": "LIST", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null}
"""

def send_whatsapp(to_phone: str, message: str):
    clean_phone = str(to_phone).lstrip("+").split("@")[0].strip()
    url = "https://7107.api.greenapi.com/waInstance710722757201/sendMessage/b3a2ccc5aa654185afdf4eaf22bd9c3a2b766efcc9d44ac1a3"
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

@app.get("/")
def home():
    return {"status": "Daynjir Bot Engine is running live."}

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    print(f"📥 RAW GREEN-API PAYHOOK PAYLOAD: {json.dumps(data)}")
    
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

    today_str = datetime.utcnow().date().isoformat()
    dynamic_system_prompt = f"{SYSTEM_PROMPT}\nToday's date is strictly: {today_str}. Use this to calculate calendar targets or relative days offsets like 'berri'."

    chat_completion = groq_client.chat.completions.create(
        messages=[{"role": "system", "content": dynamic_system_prompt}, {"role": "user", "content": message_text}],
        model="openai/gpt-oss-20b",
        temperature=0.0
    )
    
    try:
        if isinstance(chat_completion, list):
            ai_response = chat_completion.get("message", {}).get("content", "").strip()
        else:
            ai_response = chat_completion.choices[0].message.content.strip()
    except Exception as parse_err:
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
    
    if not name and action != "LIST":
        send_whatsapp(sender_phone, "❌ Magaca macmiilka si sax ah looma helin.")
        return {"status": "incomplete_data"}

    if action == "PAY":
        try:
            payment_amount = parsed.get("amount")
            
            debtor_query = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).ilike("name", f"%{name}%").eq("is_paid", False).order("id", desc=False).limit(1).execute()
            
            if not debtor_query.data:
                send_whatsapp(sender_phone, f"❌ Lama helin deynta {name}.")
                return {"status": "debtor_not_found"}
            
            debtor = debtor_query.data[0]
            current_balance = float(debtor["amount"])
            
            if payment_amount is None:
                supabase.table("debtors").update({"amount": 0, "is_paid": True}).eq("id", debtor["id"]).execute()
                send_whatsapp(sender_phone, f"✅ Deynta {name} oo dhan waa la bixiyay.")
                return {"status": "success_paid_full"}
            
            payment_amount = float(payment_amount)
            
            if payment_amount <= 0:
                send_whatsapp(sender_phone, "❌ Lacagta bixinta waa inay ka weynaataa eber.")
                return {"status": "invalid_payment_amount"}
            
            remaining_balance = current_balance - payment_amount
            
            if remaining_balance <= 0:
                supabase.table("debtors").update({"amount": 0, "is_paid": True}).eq("id", debtor["id"]).execute()
                send_whatsapp(sender_phone, f"✅ {name} wuxuu bixiyay ${payment_amount:.2f}. Deyntii oo dhan waa la bixiyay.")
            else:
                supabase.table("debtors").update({"amount": round(remaining_balance, 2)}).eq("id", debtor["id"]).execute()
                send_whatsapp(sender_phone, f"✅ {name} wuxuu bixiyay ${payment_amount:.2f}. Haraaga: ${remaining_balance:.2f}")
            
            return {"status": "success_partial_payment"}
        except Exception as pay_err:
            print(f"❌ DATABASE ERROR (Update Pay Status): {pay_err}")
            return {"status": "pay_db_error"}

    if action == "LIST":
        try:
            debts_query = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).eq("is_paid", False).order("promised_date", desc=False).execute()
            
            if not debts_query.data:
                send_whatsapp(sender_phone, "✅ Deyn la bixin lama hayo. All debts are paid!")
                return {"status": "success_list_empty"}
            
            debt_list = []
            total = 0
            for i, debt in enumerate(debts_query.data, 1):
                debt_list.append(f"{i}. {debt['name']}: ${debt['amount']} (Due: {debt['promised_date']})")
                total += debt['amount']
            
            message = f"📋 *Liiska Deynta* ({len(debts_query.data)} debtor(s)):\n\n" + "\n".join(debt_list)
            message += f"\n\n💰 **Total: ${total:.2f}**"
            
            send_whatsapp(sender_phone, message)
            return {"status": "success_list"}
        except Exception as list_err:
            print(f"❌ DATABASE ERROR (List Debts): {list_err}")
            return {"status": "list_db_error"}

    amount = parsed.get("amount")
    days = parsed.get("days_until_due")
    debtor_phone = parsed.get("customer_phone")

    if not amount:
        send_whatsapp(sender_phone, "❌ Fadlan qor lacagta deynta si sax ah.")
        return {"status": "incomplete_amount"}

    try:
        if days is None or str(days).strip() == "" or str(days).lower() == "null":
            days_offset = 0
        else:
            days_offset = int(days)
    except Exception:
        days_offset = 0

    promised_date = (datetime.utcnow() + timedelta(days=days_offset)).date().isoformat()

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
        
        send_whatsapp(sender_phone, f"✅ *Deyntii waa la keydiyay!*\n\n👤 Macmiilka: {name}\n💵 Lacagta: ${amount}\n📅 Ballanta: {promised_date}")
        return {"status": "success_add"}
    except Exception as insert_err:
        print(f"❌ DATABASE ERROR (Debtors Insertion Failure): {insert_err}")
        return {"status": "debtor_insert_db_error"}

@app.get("/cron/daily-digest")
async def daily_digest():
    today = datetime.utcnow().date().isoformat()
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
            
    return {"status": "done"}
