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
'Balamaha Oct 15' -> [{"action":
