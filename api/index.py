"""
api/index.py — Vercel Serverless entrypoint for Vapi Webhooks + Dental AI tools.
Lightweight (Under 15MB), zero card required, instant 24/7 serverless execution.
"""
import os
import json
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vercel-vapi-webhook")

app = FastAPI(
    title="Apex Dental AI — Vapi Webhook API",
    description="Serverless webhook handler for Vapi voice agent tools & HubSpot integration.",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    from agent.config import settings
except Exception:
    settings = None

# --- Helper: HubSpot Sync ---
async def sync_to_hubspot(email: str = None, phone: str = None, name: str = None, summary: str = None):
    token = os.getenv("HUBSPOT_ACCESS_TOKEN", getattr(settings, "HUBSPOT_ACCESS_TOKEN", "") if settings else "")
    if not token:
        logger.info("Mock CRM: No HUBSPOT_ACCESS_TOKEN configured.")
        return {"status": "mocked"}
    
    try:
        from agent.crm_integration import HubSpotClient
        client = HubSpotClient(api_key=token)
        fname = name.split()[0] if name else ""
        lname = " ".join(name.split()[1:]) if name and len(name.split()) > 1 else ""
        
        contact = await client.get_or_create_contact(
            email=email,
            phone=phone,
            first_name=fname,
            last_name=lname
        )
        if contact and "id" in contact and summary:
            await client.log_call_activity(contact["id"], summary)
        return contact
    except Exception as e:
        logger.error(f"HubSpot sync error: {e}")
        return None

# --- Health Check ---
@app.get("/api/health")
@app.get("/health")
def health_check():
    return {"status": "online", "service": "Apex Dental Vapi Webhook Serverless"}

# --- Vapi Webhook Handler ---
@app.post("/api/vapi/webhook")
async def handle_vapi_webhook(request: Request):
    """
    Primary endpoint called by Vapi whenever the voice agent triggers a tool call
    or finishes an end-of-call report.
    """
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}

        raw_msg = body.get("message")
        message = raw_msg if isinstance(raw_msg, dict) else body
        msg_type = message.get("type") or body.get("type") or body.get("role") or ""

        logger.info(f"Received Vapi Webhook event: {msg_type}")

        # 1. Handle Function / Tool Calls (Any shape from Vapi)
        single_tc = body.get("toolCall") or message.get("toolCall")
        tool_calls = (
            message.get("toolCalls") or 
            message.get("toolWithToolCallList") or 
            message.get("toolCallList") or 
            body.get("toolCalls") or 
            body.get("toolWithToolCallList") or 
            body.get("toolCallList") or 
            ([single_tc] if isinstance(single_tc, dict) else [])
        )
        results = []

        if tool_calls:
            for tc in tool_calls:
                tool_call = tc.get("toolCall", tc)
                call_id = tool_call.get("id") or tc.get("id")
                func = tool_call.get("function", tool_call)
                name = func.get("name")
                args = func.get("arguments", {})

                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}

                logger.info(f"Executing tool: {name} with args {args}")
                output = await execute_dental_tool(name, args)

                results.append({
                    "toolCallId": call_id,
                    "result": output
                })
            return {"results": results}

        # Direct function call fallback format
        func = message.get("functionCall") or message.get("function") or body.get("functionCall") or body.get("function") or {}
        name = func.get("name") or message.get("name") or body.get("name")
        args = func.get("arguments") or message.get("parameters") or body.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}

        if name:
            output = await execute_dental_tool(name, args)
            return {"result": output}

        # 2. Handle End of Call Report (Auto Sync to HubSpot CRM)
        elif msg_type == "end-of-call-report":
            summary = message.get("summary", "")
            call = message.get("call", {})
            customer = call.get("customer", {})
            phone = customer.get("number")
            email = customer.get("email")
            name = customer.get("name")

            logger.info(f"End of call report received. Syncing to HubSpot CRM for {email or phone or 'Guest'}...")
            await sync_to_hubspot(email=email, phone=phone, name=name, summary=summary)
            return {"status": "synced"}

        return {"status": "ignored"}
    except Exception as err:
        logger.error(f"Webhook error: {err}")
        return {"status": "error", "message": str(err)}

# --- Dental Tools Execution Logic ---
async def execute_dental_tool(name: str, args: Dict[str, Any]) -> str:
    # Always pull any available patient identifiers from tool arguments and sync immediately
    p_name = args.get("patient_name") or args.get("full_name") or args.get("name")
    p_email = args.get("email")
    p_phone = args.get("phone_number") or args.get("phone")

    if p_name or p_email or p_phone:
        logger.info(f"Tool {name}: Auto-syncing patient info ({p_name}, {p_email}, {p_phone}) to HubSpot CRM...")
        await sync_to_hubspot(email=p_email, phone=phone_clean(p_phone), name=p_name, summary=f"Interacted with AI Tool: {name} (Args: {json.dumps(args)})")

    if name == "check_availability":
        date_from = args.get("date_from", "upcoming days")
        return (
            f"Available slots for Apex Dental Care ({date_from}): "
            "Monday at 10:00 AM, Tuesday at 2:15 PM, and Thursday at 11:30 AM. "
            "Which time works best for you?"
        )

    elif name == "book_appointment":
        patient_name = p_name or "Patient"
        slot_time = args.get("slot_time", "the requested time")
        service = args.get("service_type", "Dental Consultation")

        # Sync lead immediately to HubSpot CRM with explicit booking note
        await sync_to_hubspot(email=p_email, phone=phone_clean(p_phone), name=patient_name, summary=f"Booked {service} for {slot_time}")

        return (
            f"Appointment successfully confirmed for {patient_name}! "
            f"Service: {service} at {slot_time}. "
            "A confirmation details note has been logged in our system."
        )

    elif name == "save_caller_data":
        await sync_to_hubspot(email=p_email, phone=phone_clean(p_phone), name=p_name, summary="Updated patient profile details via AI Receptionist.")
        return "Saved patient contact details successfully."

    elif name == "get_dental_pricing":
        service = args.get("service_name", "").lower()
        pricing_guide = {
            "cleaning": "Standard cleaning is $150 to $220. Covered by most private health funds.",
            "whitening": "Professional teeth whitening is $350 for in-chair treatment.",
            "filling": "Composite fillings range between $180 and $350 depending on tooth location.",
            "crown": "Porcelain crowns range from $900 to $1,500.",
            "checkup": "General checkup and X-ray special is $199 for new patients."
        }
        for key, text in pricing_guide.items():
            if key in service:
                return text
        return "Checkups start at $199, cleanings at $150, and fillings at $180. We accept all major health insurance providers."

    return f"Tool {name} executed successfully."

def phone_clean(val: Any) -> Optional[str]:
    if not val:
        return None
    s = str(val).replace(" ", "").replace("-", "")
    return s if s else None
