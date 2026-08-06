"""Vercel serverless endpoint for the Vapi dental assistant tools."""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from agent.config import settings
from agent.crm_integration import HubSpotClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vercel-vapi-webhook")

app = FastAPI(title="Apex Dental Vapi Webhook API", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


def phone_clean(value: Any) -> Optional[str]:
    if not value:
        return None
    cleaned = "".join(character for character in str(value).strip() if character.isdigit() or character == "+")
    return cleaned or None


def split_name(name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    parts = (name or "").strip().split()
    return (parts[0], " ".join(parts[1:]) or None) if parts else (None, None)


async def sync_to_hubspot(*, email: Optional[str], phone: Optional[str], name: Optional[str], summary: str, outcome: str = "COMPLETED") -> Dict[str, Any]:
    """Upsert a contact and attach a note. Never claim a failed write succeeded."""
    if not settings.HUBSPOT_ACCESS_TOKEN:
        return {"success": False, "code": "crm_not_configured", "message": "HubSpot is not configured on the server."}
    if not email and not phone:
        return {"success": False, "code": "missing_contact_identifier", "message": "Please collect the caller's email address or phone number before saving."}
    first_name, last_name = split_name(name)
    try:
        client = HubSpotClient(api_key=settings.HUBSPOT_ACCESS_TOKEN)
        contact = await client.get_or_create_contact(email=email, phone=phone_clean(phone), first_name=first_name, last_name=last_name)
        note = await client.log_call_activity(contact["id"], summary, outcome=outcome)
        return {"success": True, "contact_id": contact["id"], "note_id": note.get("id"), "message": "Caller details were saved to HubSpot."}
    except Exception as error:
        logger.exception("HubSpot sync failed")
        return {"success": False, "code": "crm_sync_failed", "message": "HubSpot could not save the caller details. Please try again later.", "detail": str(error)}


def clinic_today() -> date:
    try:
        return datetime.now(ZoneInfo(settings.TIMEZONE)).date()
    except Exception:
        return datetime.now().date()


def parse_requested_date(value: Optional[str], base_date: date) -> date:
    text = (value or "").strip().lower()
    if not text or text in {"today", "now"}:
        return base_date
    if text == "tomorrow":
        return base_date + timedelta(days=1)
    if text in {"day after tomorrow", "next day"}:
        return base_date + timedelta(days=2)
    try:
        return date.fromisoformat(text.split("T", 1)[0])
    except ValueError:
        pass
    weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
    for day_name, weekday in weekdays.items():
        if day_name in text:
            days_ahead = (weekday - base_date.weekday()) % 7
            if text.startswith("next ") or days_ahead == 0:
                days_ahead += 7
            return base_date + timedelta(days=days_ahead)
    raise ValueError("Use a weekday, today, tomorrow, or a YYYY-MM-DD date.")


def prototype_slots(date_from: Optional[str], date_to: Optional[str]) -> List[Dict[str, str]]:
    """Return transparent prototype slots until a real calendar is connected."""
    today = clinic_today()
    start = parse_requested_date(date_from, today)
    end = parse_requested_date(date_to, today) if date_to else start + timedelta(days=6)
    if end < start:
        raise ValueError("date_to cannot be earlier than date_from.")
    end = min(end, start + timedelta(days=13))
    slots: List[Dict[str, str]] = []
    current = max(start, today)
    while current <= end:
        if current.weekday() < 5:
            for clock in ("09:00 AM", "10:30 AM", "01:30 PM", "03:00 PM"):
                slots.append({"date": current.isoformat(), "day": current.strftime("%A"), "time": clock, "slot_time": f"{current.isoformat()} {clock}"})
        current += timedelta(days=1)
    return slots


def infer_api_request_tool(payload: Dict[str, Any]) -> Optional[str]:
    """apiRequest tools post their body directly, without the tool name."""
    explicit_name = payload.get("tool_name") or payload.get("toolName")
    if explicit_name:
        return str(explicit_name)
    if "slot_time" in payload:
        return "book_appointment"
    if "service_name" in payload:
        return "get_dental_pricing"
    if any(key in payload for key in ("full_name", "patient_name", "phone_number", "email")):
        return "save_caller_data"
    if "date_from" in payload or "date_to" in payload:
        return "check_availability"
    return None


async def execute_dental_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    patient_name = args.get("patient_name") or args.get("full_name") or args.get("name")
    patient_email = args.get("email")
    patient_phone = phone_clean(args.get("phone_number") or args.get("phone"))
    if name == "check_availability":
        try:
            slots = prototype_slots(args.get("date_from"), args.get("date_to"))
        except ValueError as error:
            return {"success": False, "code": "invalid_date", "message": str(error)}
        return {
            "success": True,
            "source": "prototype_schedule",
            "available": bool(slots),
            "message": "These are prototype office-hour slots. A connected calendar is required for live availability." if slots else "There are no prototype slots in the requested range. Offer a callback.",
            "slots": slots,
        }
    if name == "save_caller_data":
        return await sync_to_hubspot(email=patient_email, phone=patient_phone, name=patient_name, summary="Caller details captured by the AI receptionist.", outcome="CONTACT_CAPTURED")
    if name == "book_appointment":
        if not args.get("slot_time"):
            return {"success": False, "code": "missing_slot", "message": "A requested appointment slot is required."}
        crm_result = await sync_to_hubspot(
            email=patient_email,
            phone=patient_phone,
            name=patient_name,
            summary=f"Appointment request: {args.get('service_type') or 'Dental consultation'} at {args['slot_time']}. This is a prototype request and needs office confirmation.",
            outcome="APPOINTMENT_REQUESTED",
        )
        if not crm_result["success"]:
            return crm_result
        return {**crm_result, "appointment_status": "pending_office_confirmation", "message": "The appointment request was saved to HubSpot for office confirmation."}
    if name == "get_dental_pricing":
        service = str(args.get("service_name") or "").lower()
        prices = {"cleaning": "Standard cleaning is $150 to $220.", "whitening": "Professional in-chair whitening is $350.", "filling": "Composite fillings range from $180 to $350.", "crown": "Porcelain crowns range from $900 to $1,500.", "checkup": "A general checkup and X-ray is $199 for new patients."}
        message = next((value for key, value in prices.items() if key in service), "Checkups start at $199, cleanings at $150, and fillings at $180.")
        return {"success": True, "message": message}
    return {"success": False, "code": "unknown_tool", "message": f"Unsupported tool: {name}"}


@app.get("/api/health")
@app.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "online", "service": "Apex Dental Vapi Webhook Serverless"}


@app.post("/api/vapi/webhook")
async def handle_vapi_webhook(request: Request) -> Dict[str, Any]:
    """Handle Vapi server tool calls and direct apiRequest tool requests."""
    try:
        payload = await request.json()
    except Exception:
        return {"success": False, "code": "invalid_json", "message": "Expected a JSON request body."}
    message = payload.get("message") if isinstance(payload.get("message"), dict) else payload
    tool_calls = message.get("toolCallList") or message.get("toolCalls") or payload.get("toolCalls") or []
    if isinstance(tool_calls, dict):
        tool_calls = [tool_calls]
    if tool_calls:
        results = []
        for item in tool_calls:
            call = item.get("toolCall", item)
            function = call.get("function", call)
            arguments = function.get("arguments", call.get("arguments", {}))
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            name = function.get("name") or call.get("name")
            results.append({"toolCallId": call.get("id") or item.get("id"), "result": await execute_dental_tool(name, arguments or {})})
        return {"results": results}
    if message.get("type") == "end-of-call-report":
        call = message.get("call") or {}
        customer = call.get("customer") or {}
        result = await sync_to_hubspot(email=customer.get("email"), phone=customer.get("number"), name=customer.get("name"), summary=message.get("summary") or "Vapi call completed.", outcome="CALL_COMPLETED")
        return {"status": "synced" if result["success"] else "failed", "crm": result}
    name = infer_api_request_tool(payload)
    if not name:
        return {"success": False, "code": "unknown_request", "message": "Could not determine which Vapi tool made this request."}
    return await execute_dental_tool(name, payload)