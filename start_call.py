import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
PUBLIC_HOST = os.getenv("PUBLIC_HOST")  # e.g. abc123.ngrok-free.app (no protocol)

if not PUBLIC_HOST:
    raise SystemExit("Set PUBLIC_HOST in .env to your ngrok domain first.")

call = client.calls.create(
    from_=os.getenv("TWILIO_PHONE_NUMBER"),
    to=os.getenv("MY_PHONE_NUMBER"),
    url=f"https://{PUBLIC_HOST}/twiml",
)

print(f"Call placed: {call.sid}")
print("Answer your phone, then open the dashboard to watch the live transcript.")
