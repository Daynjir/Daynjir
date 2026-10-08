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
    
    # ✅ CHECK IF USER IS ALREADY APPROVED
    try:
        approved_check = supabase.table("approved_users").select("*").eq("phone_number", sender_phone).execute()
        
        if not approved_check.data:
            # User is NOT approved - check if this is the owner
            OWNER_PHONE = "252904039457"  # ← REPLACE WITH YOUR PHONE NUMBER
            
            if sender_phone == OWNER_PHONE:
                # Owner - allow but don't add to approved_users
                pass
            else:
                # New user - notify owner and reject
                try:
                    supabase.table("pending_users").insert({"phone_number": sender_phone}).execute()
                except:
                    pass
                
                send_whatsapp(OWNER_PHONE, f"🔔 NEW USER REQUEST:\n\nPhone: {sender_phone}\n\nAdd this number to approved_users table to allow access.")
                send_whatsapp(sender_phone, "⏳ Your request is pending approval. Contact the owner.")
                return {"status": "pending"}
                
    except Exception as auth_err:
        print(f"❌ Authorization check failed: {auth_err}")
    
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
        customer_phone = entry.get("customer_phone")
        new_amount = entry.get("new_amount")
        new_date = entry.get("new_date")
        new_phone = entry.get("new_phone")
        filter_date = entry.get("filter_date")
        filter_type = entry.get("filter_type")
        
        # Validate name for actions that need it
        if not name and action not in ["LIST", "REPORT", "EXPORT"]:
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
                
                # Handle phone number save
                if new_phone and not amount:
                    # Just saving phone number
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
        
        elif action == "SEARCH":
            try:
                # Search for debtor by name
                debts_query = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).ilike("name", f"%{name}%").eq("is_paid", False).execute()
                
                if not debts_query.data:
                    send_whatsapp(sender_phone, f"❌ Lama helin {name}.")
                else:
                    debt_list = []
                    total = 0
                    for i, debt in enumerate(debts_query.data, 1):
                        debt_list.append(f"{i}. {debt['name']}: ${debt['amount']} - Due: {debt['promised_date']}")
                        if debt.get('phone_number'):
                            debt_list[-1] += f" 📞 {debt['phone_number']}"
                        total += debt['amount']
                    
                    message = f"🔍 *Search Results for {name}* ({len(debts_query.data)} found):\n\n" + "\n".join(debt_list)
                    message += f"\n\n💰 **Total: ${total:.2f}**"
                    
                    send_whatsapp(sender_phone, message)
                    
            except Exception as e:
                send_whatsapp(sender_phone, f"❌ Khalad: {str(e)}")
                failed_inserts.append({"name": name, "reason": f"Search error: {str(e)}"})
        
        elif action == "EDIT":
            try:
                # Find debtor
                debtor_query = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).ilike("name", f"%{name}%").eq("is_paid", False).limit(1).execute()
                
                if not debtor_query.data:
                    send_whatsapp(sender_phone, f"❌ Lama helin {name}.")
                    failed_inserts.append({"name": name, "reason": "Debtor not found"})
                    continue
                
                debtor = debtor_query.data[0]
                
                # Build update data
                update_data = {}
                if new_amount is not None:
                    update_data['amount'] = float(new_amount)
                if new_date is not None:
                    update_data['promised_date'] = new_date
                
                if not update_data:
                    send_whatsapp(sender_phone, "❌ No changes specified. Use: edit [Name] $[Amount] [Date]")
                    failed_inserts.append({"name": name, "reason": "No changes"})
                    continue
                
                # Update
                updated = supabase.table("debtors").update(update_data).eq("shopkeeper_id", shopkeeper_id).eq("name", debtor["name"]).eq("amount", debtor["amount"]).execute()
                
                changes = []
                if 'amount' in update_data:
                    changes.append(f"Amount: ${debtor['amount']} → ${update_data['amount']}")
                if 'promised_date' in update_data:
                    changes.append(f"Date: {debtor['promised_date']} → {update_data['promised_date']}")
                
                send_whatsapp(sender_phone, f"✅ {name} updated:\n" + "\n".join(changes))
                successful_inserts.append(entry)
                    
            except Exception as e:
                send_whatsapp(sender_phone, f"❌ Khalad: {str(e)}")
                failed_inserts.append({"name": name, "reason": f"Edit error: {str(e)}"})
        
        elif action == "DELETE":
            try:
                # Find debtor
                debtor_query = supabase.table("debtors").select("*").eq("shopkeeper_id", shopkeeper_id).ilike("name", f"%{name}%").eq("is_paid", False).limit(1).execute()
                
                if not debtor_query.data:
                    send_whatsapp(sender_phone, f"❌ Lama helin {name}.")
                    failed_inserts.append({"name": name, "reason": "Debtor not found"})
                    continue
                
                debtor = debtor_query.data[0]
                
                # Delete
                deleted = supabase.table("debtors").delete().eq("shopkeeper_id", shopkeeper_id).eq("name", debtor["name"]).eq("amount", debtor["amount"]).execute()
                
                send_whatsapp(sender_phone, f"✅ {name} (${debtor['amount']}) has been deleted.")
                successful_inserts.append(entry)
                    
            except Exception as e:
                send_whatsapp(sender_phone, f"❌ Khalad: {str(e)}")
                failed_inserts.append({"name": name, "reason": f"Delete error: {str(e)}"})
        
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
            msg = "☀️ *Xasuusinta Maalinle ah ee Daynjir* ☀️\n\n*Balamaha maanta & kuwa dhaafay:*\n" + "\n".join(due_today)
            send_whatsapp(sk_phone, msg)
        else:
            print("⚠️ No debts due today")
            
    print("✅ DAILY DIGEST COMPLETED")
    return {"status": "done"}
@app.post("/webhook")  # ← CORRECT: No indentation
async def whatsapp_webhook(request: Request):  # ← CORRECT: No indentation
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
    
    # ✅ CHECK IF THIS IS YOUR PHONE NUMBER (OWNER)
    OWNER_PHONE = "252904039457"  # Replace with YOUR phone number
    
    # ✅ CHECK IF USER IS ALREADY APPROVED
    try:
        approved_check = supabase.table("approved_users").select("*").eq("phone_number", sender_phone).execute()
        
        if approved_check.data:
            # User is approved, continue normally
            pass
        else:
            # User is NOT approved
            if sender_phone == OWNER_PHONE:
                # This is YOU (owner) - check if approving someone
                if message_text.upper() == "ACCEPT":
                    # Get the last pending user and approve them
                    pending = supabase.table("pending_users").select("*").eq("status", "pending").order("created_at", desc=True).limit(1).execute()
                    if pending.data:
                        pending_user = pending.data[0]["phone_number"]
                        # Add to approved
                        supabase.table("approved_users").insert({"phone_number": pending_user}).execute()
                        # Update pending status
                        supabase.table("pending_users").update({"status": "approved"}).eq("phone_number", pending_user).execute()
                        send_whatsapp(pending_user, "✅ You have been approved to use Daynjir bot!")
                        send_whatsapp(sender_phone, f"✅ User {pending_user} approved!")
                    else:
                        send_whatsapp(sender_phone, "❌ No pending users to approve.")
                    return {"status": "success"}
                    
                elif message_text.upper() == "REJECT":
                    # Get the last pending user and reject them
                    pending = supabase.table("pending_users").select("*").eq("status", "pending").order("created_at", desc=True).limit(1).execute()
                    if pending.data:
                        pending_user = pending.data[0]["phone_number"]
                        # Update pending status
                        supabase.table("pending_users").update({"status": "rejected"}).eq("phone_number", pending_user).execute()
                        send_whatsapp(pending_user, "❌ Your request to use Daynjir bot has been rejected.")
                        send_whatsapp(sender_phone, f"✅ User {pending_user} rejected!")
                    else:
                        send_whatsapp(sender_phone, "❌ No pending users to reject.")
                    return {"status": "success"}
                else:
                    # You sending normal message - continue
                    pass
            else:
                # This is a NEW user - add to pending and notify owner
                try:
                    supabase.table("pending_users").insert({"phone_number": sender_phone}).execute()
                except:
                    pass  # Already pending
                
                # Notify YOU (owner)
                send_whatsapp(OWNER_PHONE, f"🔔 NEW USER REQUEST:\n\nPhone: {sender_phone}\n\nReply ACCEPT or REJECT")
                
                # Tell user to wait
                send_whatsapp(sender_phone, "⏳ Your request is pending approval. Please wait for the owner to approve you.")
                return {"status": "pending"}
                
    except Exception as auth_err:
        print(f"❌ Authorization check failed: {auth_err}")
        send_whatsapp(sender_phone, "❌ Authorization error. Please try again later.")
        return {"status": "auth_error"}

    # ... rest of your existing code continues ...
        
        if due_today:
            msg = "☀️ *Xasuusinta Maalinle ah ee Daynjir* ☀️\n\n*Balamaha maanta & kuwa dhaafay:*\n" + "\n".join(due_today)
            send_whatsapp(sk_phone, msg)
            
    return {"status": "done"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
