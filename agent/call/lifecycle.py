"""
lifecycle.py — Manages the state machine of a phone call.
"""
import uuid
import datetime
import logging
import httpx
from agent.config import settings
from agent.call.models import CallRecord, CallerData, CallOutcome, BookingRecord
from agent.call.summary import generate_call_summary

logger = logging.getLogger("call-lifecycle")

# Shared HTTP client to reduce connection overhead
_http_client = httpx.AsyncClient(timeout=10.0)

class CallLifecycleManager:
    """Tracks the full lifecycle of a voice call."""

    def __init__(self, room_name: str):
        self.record = CallRecord(
            call_id=str(uuid.uuid4()),
            room_name=room_name,
            started_at=datetime.datetime.now(datetime.timezone.utc),
        )
        self._supabase_created = False
        logger.info(f"Call initialized: {self.record.call_id} in room {room_name}")

    async def initialize(self):
        """Create the initial record in Supabase so we don't lose the call if it drops."""
        logger.info(f"Supabase: Creating initial record for {self.record.call_id}...")
        # We pass upsert=True to handle cases where the webhook might have fired before initialize
        await self._save_to_supabase(upsert=True)

    def update_caller_data(self, **kwargs):
        """Incrementally update caller data as it's collected."""
        for key, value in kwargs.items():
            if hasattr(self.record.caller_data, key) and value:
                setattr(self.record.caller_data, key, value)
        logger.info(f"Caller data updated: {kwargs}")

    def record_booking(self, event_id: str, date: str, time: str, appointment_type: str):
        """Record a successful booking."""
        self.record.booking = BookingRecord(
            event_id=event_id,
            appointment_date=date,
            appointment_time=time,
            appointment_type=appointment_type,
        )
        self.record.outcome = CallOutcome.BOOKING
        logger.info(f"Booking recorded: {event_id}")

    async def sync_transcript(self, transcript: list[dict]):
        """Periodically sync the transcript to avoid data loss on abrupt disconnects."""
        self.record.transcript = transcript
        # Auto-update duration for live stats
        self.record.ended_at = datetime.datetime.now(datetime.timezone.utc)
        self.record.duration_seconds = (
            self.record.ended_at - self.record.started_at
        ).total_seconds()
        
        await self._save_to_supabase(upsert=True)

    async def finalize(self, transcript: list[dict]):
        """Called when the call ends. Generates summary and logs everything."""
        self.record.ended_at = datetime.datetime.now(datetime.timezone.utc)
        self.record.duration_seconds = (
            self.record.ended_at - self.record.started_at
        ).total_seconds()
        self.record.transcript = transcript

        # Auto-classify outcome if not already set
        if self.record.outcome == CallOutcome.OTHER:
            self.record.outcome = self._classify_outcome(transcript)

        # Generate AI summary
        try:
            # We only generate summary at the end as it's expensive
            self.record.summary = await generate_call_summary(
                transcript=transcript,
                caller_data=self.record.caller_data
            )
        except Exception as e:
            logger.error(f"Failed to generate call summary: {e}")

        logger.info(f"Call finalized: {self.record.call_id}, Duration: {self.record.duration_seconds}s, Outcome: {self.record.outcome}")
        
        # Async sync to HubSpot CRM
        try:
            from agent.crm_integration import hubspot_client
            email = self.record.caller_data.email
            phone = self.record.caller_data.phone_number
            name = self.record.caller_data.full_name or ""
            fname = name.split()[0] if name else ""
            lname = " ".join(name.split()[1:]) if len(name.split()) > 1 else ""

            if email or phone:
                contact = await hubspot_client.get_or_create_contact(
                    email=email,
                    phone=phone,
                    first_name=fname,
                    last_name=lname
                )
                if contact and "id" in contact:
                    summary_text = self.record.summary or "Call completed."
                    await hubspot_client.log_call_activity(
                        contact_id=contact["id"],
                        summary=summary_text,
                        outcome=str(self.record.outcome)
                    )
                    logger.info(f"HubSpot: Synced call details to contact {contact['id']}")
        except Exception as crm_err:
            logger.error(f"HubSpot sync warning: {crm_err}")

        await self._save_to_supabase(upsert=True)
        return self.record

    def _classify_outcome(self, transcript: list[dict]) -> CallOutcome:
        """Smarter outcome classification."""
        if self.record.booking:
            return CallOutcome.BOOKING

        full_text = " ".join([str(t.get("content", "")) for t in transcript]).lower()
        if any(word in full_text for word in ["booked", "appointment confirmed", "scheduled"]):
            return CallOutcome.BOOKING
        elif any(word in full_text for word in ["call back", "callback", "someone will contact"]):
            return CallOutcome.CALLBACK
        elif any(word in full_text for word in ["question", "wondering", "information"]):
            return CallOutcome.INQUIRY

        return CallOutcome.OTHER

    async def _save_to_supabase(self, upsert: bool = False):
        """Save or update the call record in Supabase."""
        
        if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
            return

        url = f"{settings.SUPABASE_URL}/rest/v1/call_logs"
        # If we are upserting, we need to handle the primary key conflict
        if upsert:
            url += f"?call_id=eq.{self.record.call_id}"
            
        headers = {
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates" if upsert else "return=minimal"
        }
        
        payload = self.record.model_dump(mode='json', exclude={'recording_url', 'recording_status', 'recording_duration_seconds'})
        
        # Cleanup timestamp
        if 'started_at' in payload and isinstance(payload['started_at'], str):
            if not payload['started_at'].endswith('Z') and '+' not in payload['started_at']:
                 payload['started_at'] += 'Z'

        try:
            if upsert:
                # Supabase 'upsert' via POST with Prefer header or just check if we should PATCH
                if self._supabase_created:
                     response = await _http_client.patch(url, json=payload, headers=headers)
                else:
                     # Add on_conflict parameter for POST upsert
                     upsert_url = f"{settings.SUPABASE_URL}/rest/v1/call_logs?on_conflict=call_id"
                     response = await _http_client.post(upsert_url, json=payload, headers=headers)
            else:
                response = await _http_client.post(url, json=payload, headers=headers)
            
            if response.status_code >= 400:
                logger.error(f"Supabase ERROR ({response.status_code}): {response.text}")
            else:
                self._supabase_created = True
                logger.debug(f"Supabase sync successful for {self.record.call_id}")
        except Exception as e:
            logger.error(f"Supabase NETWORK ERROR: {e}")
