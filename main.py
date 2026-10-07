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
groq_client = Groq(api_key=os.getenv("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"))

INSTANCE_ID = "710722758620"
GREEN_API_TOKEN = "feb8f9b99fa047a3b8b3442b303b6cbb8564a60129604f149c"
GREEN_API_BASE = "https://7107.api.greenapi.com"

SYSTEM_PROMPT = """You are Daynjir, a Somali debt management assistant for small shopkeepers. 
Extract transaction intent from chaotic, unstructured Somali text into raw JSON. 
Do not include any conversational filler, markdown syntax, or backticks.

Extract ALL debt entries from the message.
For each entry, extract: customer_name, amount, promised_date (YYYY-MM-DD)

ALWAYS return a JSON array, even for single entries.

Response format (JSON array):
[
  {"action": "ADD" or "PAY" or "LIST", "customer_name": "string or null", "amount": number or null, "days_until_due": number or null, "customer_phone": "string or null", "promised_date": "YYYY-MM-DD or null", "filter_date": "YYYY-MM-DD or null", "filter_type": "today" or "tomorrow" or "date" or null}
]

Examples:
'Cali 20$ oo bari ah' -> [{"action": "ADD", "customer_name": "Cali", "amount": 20, "days_until_due": 1, "customer_phone": null, "promised_date": "2026-10-08", "filter_date": null, "filter_type": null}]
'Cali $34 oct 8, Axmed $50 oct 9' -> [{"action": "ADD", "customer_name": "Cali", "amount": 34, "days_until_due": 1, "customer_phone": null, "promised_date": "2026-10-08", "filter_date": null, "filter_type": null}, {"action": "ADD", "customer_name": "Axmed", "amount": 50, "days_until_due": 2, "customer_phone": null, "promised_date": "2026-10-09", "filter_date": null, "filter_type": null}]
'Xasan baa 15 doolar qaatay maanta' -> [{"action": "ADD", "customer_name": "Xasan", "amount": 15, "days_until_due": 0, "customer_phone": null, "promised_date": "2026-10-07", "filter_date": null, "filter_type": null}]
'Cali wuu bixiyay' -> [{"action": "PAY", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null}]
'Cali wuu bixiyay hantidii' -> [{"action": "PAY", "customer_name": "Cali", "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null}]
'Gaawe wuxuu bixiyay $5' -> [{"action": "PAY", "customer_name": "Gaawe", "amount": 5, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null}]
'Cali wuu bixiyay 10 doolar' -> [{"action": "PAY", "customer_name": "Cali", "amount": 10, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null}]
'List my debts' -> [{"action": "LIST", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null}]
'My debts' -> [{"action": "LIST", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null}]
'Liiska deynta' -> [{"action": "LIST", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": null, "filter_type": null}]
'Balamaha maanta' -> [{"action": "LIST", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": "2026-10-07", "filter_type": "today"}]
'Balamaha berri' -> [{"action": "LIST", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": "2026-10-08", "filter_type": "tomorrow"}]
'Balamaha Oct 15' -> [{"action": "LIST", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": "2026-10-15", "filter_type": "date"}]
'Balamaha 2026-10-15' -> [{"action": "LIST", "customer_name": null, "amount": null, "days_until_due": null, "customer_phone": null, "promised_date": null, "filter_date": "2026-10-15", "filter_type": "date"}]
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


@app.get("/")
def home():
    return {"status": "Daynjir Bot Engine is running live."}


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
    
    # Get or create shopkeeper
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
        ai_response = chat_completion.choices[0].message.content.strip()
    except Exception as parse_err:
        print(f"⚠️ Direct extraction failed, casting raw string: {parse_err}")
        ai_response = str(chat_completion).strip()
        
    print(f"🤖 Groq AI Processed Output: {ai_response}")
    
    # Parse JSON response
    try:
        json_match = re.search(r'[\[{].*[\]}]', ai_response, re.DOTALL)
        if not json_match:
            raise Exception("No JSON found")
        
        clean_json = json_match.group()
        parsed = json.loads(clean_json)
        
        # Ensure it's always a list
        if isinstance(parsed, dict):
            entries = [parsed]
        else:
            entries = parsed
        
        if not entries:
            raise Exception("Empty entries")
            
    except Exception as e:
        send_whatsapp(sender_phone, "❌ ma fahmin qoraalkaaga. Fadlan u qor si cad.")
        return {"status": "parsing_failed"}

       # Process each entry
    successful_inserts = []
    failed_inserts = []

    for entry in entries:
        action = entry.get("action", "ADD")
        name = entry.get("customer_name")
        amount = entry.get("amount")
        promised_date = entry.get("promised_date")
        days_until_due = entry.get("days_until_due")
        
        # Validate name
        if not name and action != "LIST":
            failed_inserts.append({"name": "Unknown", "reason": "No name"})
            continue
        
        if action == "ADD":
            try:
                # Calculate promised_date if not provided
                if not promised_date and days_until_due is not None:
                    promised_date = (datetime.utcnow() + timedelta(days=int(days_until_due))).date().isoformat()
                elif not promised_date:
                    # Default to today if no date provided
                    promised_date = datetime.utcnow().date().isoformat()
                
                debtor_data = {
                    'shopkeeper_id': shopkeeper_id,
                    'name': name,
                    'amount': float(amount) if amount else 0,
                    'promised_date': promised_date,
                    'phone_number': None,
                    'is_paid': False
                }
                
                result = supabase.table("debtors").insert(debtor_data).execute()
                successful_inserts.append(entry)
                
            except Exception as e:
                failed_inserts.append({"name": name, "reason": str(e)})
        
        elif action == "PAY":
            try:
                payment_amount = entry.get("amount")
                
                debtor_query = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).ilike("name", f"%{name}%").eq("is_paid", False).order("promised_date", desc=False).limit(1).execute()
                
                if not debtor_query.data:
                    send_whatsapp(sender_phone, f"❌ Lama helin deynta {name}.")
                    failed_inserts.append({"name": name, "reason": "Debtor not found"})
                    continue
                
                debtor = debtor_query.data[0]
                current_balance = float(debtor["amount"])
                
                if payment_amount is None:
                    updated = supabase.table("debtors").update({"is_paid": True}).eq("shopkeeper_id", shopkeeper_id).eq("name", debtor["name"]).eq("amount", debtor["amount"]).execute()
                    send_whatsapp(sender_phone, f"✅ {name} wuu bixiyay deyntii (${current_balance}).")
                else:
                    new_balance = current_balance - float(payment_amount)
                    if new_balance <= 0:
                        updated = supabase.table("debtors").update({"is_paid": True, "amount": 0}).eq("shopkeeper_id", shopkeeper_id).eq("name", debtor["name"]).eq("amount", debtor["amount"]).execute()
                        send_whatsapp(sender_phone, f"✅ {name} wuu bixiyay deyntii oo dhan.")
                    else:
                        updated = supabase.table("debtors").update({"amount": new_balance}).eq("shopkeeper_id", shopkeeper_id).eq("name", debtor["name"]).eq("amount", debtor["amount"]).execute()
                        send_whatsapp(sender_phone, f"✅ {name} wuu bixiyay ${payment_amount}. Haray: ${new_balance}")
                    
            except Exception as e:
                send_whatsapp(sender_phone, f"❌ Khalad: {str(e)}")
                failed_inserts.append({"name": name, "reason": f"Payment error: {str(e)}"})
        
        elif action == "LIST":
            try:
                filter_date = entry.get("filter_date")
                filter_type = entry.get("filter_type")
                
                # Build query
                query = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).eq("is_paid", False)
                
                # Apply date filter if exists
                if filter_date:
                    query = query.eq("promised_date", filter_date)
                    if filter_type == "today":
                        message_title = "📋 *Balamaha Maanta*"
                    elif filter_type == "tomorrow":
                        message_title = "📋 *Balamaha Berri*"
                    else:
                        message_title = f"📋 *Balamaha {filter_date}*"
                else:
                    query = query.order("promised_date", desc=False)
                    # Check if user asked for due dates
                    show_due_dates = any(keyword in message_text.lower() for keyword in ['balamaha', 'balamaha', 'balanta', 'ballanta', 'due'])
                    if show_due_dates:
                        message_title = "📋 *Liiska Deynta iyo Balamaha*"
                    else:
                        message_title = "📋 *Liiska Deynta*"
                
                debts_query = query.execute()
                
                if not debts_query.data:
                    if filter_date:
                        send_whatsapp(sender_phone, f"✅ Ma jiraan deynta balamaheedu yahay {filter_date}.")
                    else:
                        send_whatsapp(sender_phone, "✅ Ma hayo Deyn aan la bixin. All debts are paid!")
                else:
                    # Check if user asked for due dates
                    show_due_dates = filter_date or any(keyword in message_text.lower() for keyword in ['balamaha', 'balamaha', 'balanta', 'ballanta', 'due'])
                    
                    debt_list = []
                    total = 0
                    for i, debt in enumerate(debts_query.data, 1):
                        if show_due_dates:
                            debt_list.append(f"{i}. {debt['name']}: ${debt['amount']} - {debt['promised_date']}")
                        else:
                            debt_list.append(f"{i}. {debt['name']}: ${debt['amount']}")
                        total += debt['amount']
                    
                    message = f"{message_title} ({len(debts_query.data)} debtor(s)):\n\n" + "\n".join(debt_list)
                    message += f"\n\n💰 **Total: ${total:.2f}**"
                    
                    send_whatsapp(sender_phone, message)
                    
            except Exception as e:
                send_whatsapp(sender_phone, f"❌ Khalad: {str(e)}")
                failed_inserts.append({"name": "LIST", "reason": f"List error: {str(e)}"})

    # Send confirmation for ADD actions
    if successful_inserts:
        if len(successful_inserts) == 1:
            entry = successful_inserts[0]
            success_message = f"""✅ Deyntan waa la keydiyay!

👤 Macmiilka: {entry['customer_name']}
💵 Lacagta: ${entry['amount']}
📅 Ballanta: {entry['promised_date']}"""
        else:
            success_message = f"""✅ Deymahan waa la keydiyay!

"""
            for entry in successful_inserts:
                success_message += f"""👤 {entry['customer_name']}: ${entry['amount']} - {entry['promised_date']}
"""
        
        send_whatsapp(sender_phone, success_message)

    if failed_inserts:
        error_message = f"❌ {len(failed_inserts)} deyntii ma keydsamin:\n"
        for fail in failed_inserts:
            error_message += f"- {fail['name']}: {fail['reason']}\n"
        send_whatsapp(sender_phone, error_message)
    
    return {"status": "success"}
        
        elif action == "LIST":
    # Process each entry
    successful_inserts = []
    failed_inserts = []

    for entry in entries:
        action = entry.get("action", "ADD")
        name = entry.get("customer_name")
        amount = entry.get("amount")
        promised_date = entry.get("promised_date")
        days_until_due = entry.get("days_until_due")
        
        # Validate name
        if not name and action != "LIST":
            failed_inserts.append({"name": "Unknown", "reason": "No name"})
            continue
        
        if action == "ADD":
            try:
                # Calculate promised_date if not provided
                if not promised_date and days_until_due is not None:
                    promised_date = (datetime.utcnow() + timedelta(days=int(days_until_due))).date().isoformat()
                
                debtor_data = {
                    'shopkeeper_id': shopkeeper_id,
                    'name': name,
                    'amount': float(amount) if amount else 0,
                    'promised_date': promised_date,
                    'phone_number': None,
                    'is_paid': False
                }
                
                result = supabase.table("debtors").insert(debtor_data).execute()
                successful_inserts.append(entry)
                
            except Exception as e:
                failed_inserts.append({"name": name, "reason": str(e)})
        
               elif action == "PAY":
            try:
                payment_amount = entry.get("amount")
                
                debtor_query = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).ilike("name", f"%{name}%").eq("is_paid", False).order("promised_date", desc=False).limit(1).execute()
                
                if not debtor_query.data:
                    send_whatsapp(sender_phone, f"❌ Lama helin deynta {name}.")
                    failed_inserts.append({"name": name, "reason": "Debtor not found"})
                    continue
                
                debtor = debtor_query.data[0]
                current_balance = float(debtor["amount"])
                
                if payment_amount is None:
                    updated = supabase.table("debtors").update({"is_paid": True}).eq("shopkeeper_id", shopkeeper_id).eq("name", debtor["name"]).eq("amount", debtor["amount"]).execute()
                    send_whatsapp(sender_phone, f"✅ {name} wuu bixiyay deyntii (${current_balance}).")
                else:
                    new_balance = current_balance - float(payment_amount)
                    if new_balance <= 0:
                        updated = supabase.table("debtors").update({"is_paid": True, "amount": 0}).eq("shopkeeper_id", shopkeeper_id).eq("name", debtor["name"]).eq("amount", debtor["amount"]).execute()
                        send_whatsapp(sender_phone, f"✅ {name} wuu bixiyay deyntii oo dhan.")
                    else:
                        updated = supabase.table("debtors").update({"amount": new_balance}).eq("shopkeeper_id", shopkeeper_id).eq("name", debtor["name"]).eq("amount", debtor["amount"]).execute()
                        send_whatsapp(sender_phone, f"✅ {name} wuu bixiyay ${payment_amount}. Haray: ${new_balance}")
                    
            except Exception as e:
                send_whatsapp(sender_phone, f"❌ Khalad: {str(e)}")
                failed_inserts.append({"name": name, "reason": f"Payment error: {str(e)}"})
        
        elif action == "LIST":
            try:
                filter_date = entry.get("filter_date")
                filter_type = entry.get("filter_type")
                
                # Build query
                query = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).eq("is_paid", False)
                
                # Apply date filter if exists
                if filter_date:
                    query = query.eq("promised_date", filter_date)
                    if filter_type == "today":
                        message_title = "📋 *Balamaha Maanta*"
                    elif filter_type == "tomorrow":
                        message_title = "📋 *Balamaha Berri*"
                    else:
                        message_title = f"📋 *Balamaha {filter_date}*"
                else:
                    query = query.order("promised_date", desc=False)
                    # Check if user asked for due dates
                    show_due_dates = any(keyword in message_text.lower() for keyword in ['balamaha', 'balamaha', 'balanta', 'ballanta', 'due'])
                    if show_due_dates:
                        message_title = "📋 *Liiska Deynta iyo Balamaha*"
                    else:
                        message_title = "📋 *Liiska Deynta*"
                
                debts_query = query.execute()
                
                if not debts_query.data:
                    if filter_date:
                        send_whatsapp(sender_phone, f"✅ Ma jiraan deynta balamaheedu yahay {filter_date}.")
                    else:
                        send_whatsapp(sender_phone, "✅ Ma hayo Deyn aan la bixin. All debts are paid!")
                else:
                    # Check if user asked for due dates
                    show_due_dates = filter_date or any(keyword in message_text.lower() for keyword in ['balamaha', 'balamaha', 'balanta', 'ballanta', 'due'])
                    
                    debt_list = []
                    total = 0
                    for i, debt in enumerate(debts_query.data, 1):
                        if show_due_dates:
                            debt_list.append(f"{i}. {debt['name']}: ${debt['amount']} - {debt['promised_date']}")
                        else:
                            debt_list.append(f"{i}. {debt['name']}: ${debt['amount']}")
                        total += debt['amount']
                    
                    message = f"{message_title} ({len(debts_query.data)} debtor(s)):\n\n" + "\n".join(debt_list)
                    message += f"\n\n💰 **Total: ${total:.2f}**"
                    
                    send_whatsapp(sender_phone, message)
                    
            except Exception as e:
                send_whatsapp(sender_phone, f"❌ Khalad: {str(e)}")
                failed_inserts.append({"name": "LIST", "reason": f"List error: {str(e)}"})

    # Send confirmation for ADD actions
    if successful_inserts:
        if len(successful_inserts) == 1:
            entry = successful_inserts[0]
            success_message = f"""✅ Deyntan waa la keydiyay!

👤 Macmiilka: {entry['customer_name']}
💵 Lacagta: ${entry['amount']}
📅 Ballanta: {entry['promised_date']}"""
        else:
            success_message = f"""✅ Deymahan waa la keydiyay!

"""
            for entry in successful_inserts:
                success_message += f"""👤 {entry['customer_name']}: ${entry['amount']} - {entry['promised_date']}
"""
        
        send_whatsapp(sender_phone, success_message)

    if failed_inserts:
        error_message = f"❌ {len(failed_inserts)} deyntii ma keydsamin:\n"
        for fail in failed_inserts:
            error_message += f"- {fail['name']}: {fail['reason']}\n"
        send_whatsapp(sender_phone, error_message)
    
    return {"status": "success"}
  
    # Send confirmation for ADD actions
    if successful_inserts:
        if len(successful_inserts) == 1:
            entry = successful_inserts[0]
            success_message = f"""✅ Deyntan waa la keydiyay!

👤 Macmiilka: {entry['customer_name']}
💵 Lacagta: ${entry['amount']}
📅 Ballanta: {entry['promised_date']}"""
        else:
            success_message = f"""✅ Deymahan waa la keydiyay!

"""
            for entry in successful_inserts:
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
            msg = "☀️ *Xasuusinta Maalinle ah ee Daynjir* ☀️\n\n*Balamaha maanta & kuwa dhaafay:*\n" + "\n".join(due_today)
            send_whatsapp(sk_phone, msg)
            
    return {"status": "done"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
