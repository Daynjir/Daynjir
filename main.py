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

app = FastAPI()

# Connect to your services
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

GREEN_API_URL = f"https://green-api.com{os.getenv('GREEN_API_INSTANCE_ID')}"
GREEN_API_TOKEN = os.getenv("GREEN_API_TOKEN")

SYSTEM_PROMPT = """You are a Somali debt assistant. Extract debt info from messy text into strict JSON. No markdown, no conversational text.
Response format: {"customer_name": "string or null", "amount": number or null, "days_until_due": number or null, "customer_phone": "string or null"}
Examples:
'Cali 20$ oo bari ah lambarkisu waa 252634444444' -> {"customer_name": "Cali", "amount": 20, "days_until_due": 1, "customer_phone": "252634444444"}
'Xasan baa 15 doolar qaatay maanta' -> {"customer_name": "Xasan", "amount": 15, "days_until_due": 0, "customer_phone": null}"""

def send_whatsapp(to_phone: str, message: str):
    url = f"{GREEN_API_URL}/sendMessage/{GREEN_API_TOKEN}"
    payload = {"chatId": f"{to_phone}@c.us", "message": message}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending WhatsApp: {e}")

@app.post("/webhook")
async def whatsapp_webhook(request: Request):
    data = await request.json()
    
    # 1. Ignore anything that isn't a text message sent to you
    if data.get("typeWebhook") != "incomingMessageReceived":
        return {"status": "ignored"}
        
    sender_chat_id = data["senderData"]["chatId"]
    sender_phone = sender_chat_id.split("@")[0] # Cleans the number
    
    try:
        message_text = data["messageData"]["textMessageData"]["textMessage"]
    except KeyError:
        return {"status": "no_text_payload"}
    
    # 2. Check if shopkeeper exists, if not create them
    sk_query = supabase.table("shopkeepers").select("*").eq("phone_number", sender_phone).execute()
    if not sk_query.data:
        sk_insert = supabase.table("shopkeepers").insert({"phone_number": sender_phone}).execute()
        shopkeeper_id = sk_insert.data[0]["id"]
    else:
        shopkeeper_id = sk_query.data[0]["id"]

    # 3. Ask Groq AI to understand the messy Somali text
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
        send_whatsapp(sender_phone, "❌ Ma fariisan waayay qoraalkaaga. Fadlan u qor si cad (Tusaale: 'Cali 15$ maanta').")
        return {"status": "parsing_failed"}

    name = parsed.get("customer_name")
    amount = parsed.get("amount")
    days = parsed.get("days_until_due")
    debtor_phone = parsed.get("customer_phone")
    if days is None:
        days = 0

    if not name or not amount:
        send_whatsapp(sender_phone, "❌ Fadlan qor magaca iyo lacagta deynta si sax ah.")
        return {"status": "incomplete_data"}

    promised_date = (datetime.utcnow() + timedelta(days=int(days))).date().isoformat()

    # 4. Save directly into Debtors table
    supabase.table("debtors").insert({
        "shopkeeper_id": shopkeeper_id,
        "name": name,
        "amount": amount,
        "promised_date": promised_date,
        "phone_number": debtor_phone,
        "is_paid": False
    }).execute()

    # 5. Send confirmation back to the shopkeeper
    send_whatsapp(sender_phone, f"✅ Deyntii waa la keydiyay!\nMacmiilka: {name}\nLacagta: ${amount}\nBallanta: {promised_date}")
    return {"status": "success"}
