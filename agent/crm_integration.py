"""HubSpot CRM integration for the Dental Voice Agent."""

import logging
import time
from typing import Any, Dict, Optional

import httpx

from agent.config import settings

logger = logging.getLogger("hubspot-crm")
HUBSPOT_API_BASE = "https://api.hubapi.com"


class HubSpotClient:
    """Client for HubSpot contacts and contact notes."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.HUBSPOT_ACCESS_TOKEN or ""
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _find_contact(self, client: httpx.AsyncClient, property_name: str, value: str) -> Optional[Dict[str, Any]]:
        response = await client.post(
            f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts/search",
            headers=self.headers,
            json={"filterGroups": [{"filters": [{"propertyName": property_name, "operator": "EQ", "value": value}]}], "limit": 1},
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        return results[0] if results else None

    async def get_or_create_contact(self, email: Optional[str] = None, phone: Optional[str] = None, first_name: Optional[str] = None, last_name: Optional[str] = None) -> Dict[str, Any]:
        """Find a contact, update supplied details, or create one."""
        if not self.api_key:
            raise RuntimeError("HUBSPOT_ACCESS_TOKEN is not configured")
        if not email and not phone:
            raise ValueError("An email address or phone number is required to save a contact")

        properties: Dict[str, str] = {}
        if email:
            properties["email"] = email.strip().lower()
        if phone:
            properties["phone"] = phone
        if first_name:
            properties["firstname"] = first_name.strip()
        if last_name:
            properties["lastname"] = last_name.strip()

        async with httpx.AsyncClient(timeout=10.0) as client:
            contact = await self._find_contact(client, "email", properties["email"]) if email else None
            if contact is None and phone:
                contact = await self._find_contact(client, "phone", phone)
            if contact:
                response = await client.patch(
                    f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts/{contact['id']}",
                    headers=self.headers,
                    json={"properties": properties},
                )
                response.raise_for_status()
                logger.info("HubSpot: updated contact %s", contact["id"])
                return response.json()

            properties["hs_lead_status"] = "NEW"
            response = await client.post(
                f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts",
                headers=self.headers,
                json={"properties": properties},
            )
            response.raise_for_status()
            contact = response.json()
            logger.info("HubSpot: created contact %s", contact["id"])
            return contact

    async def log_call_activity(self, contact_id: str, summary: str, outcome: str = "COMPLETED") -> Dict[str, Any]:
        """Create a note associated with a contact and return HubSpot's response."""
        if not self.api_key:
            raise RuntimeError("HUBSPOT_ACCESS_TOKEN is not configured")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{HUBSPOT_API_BASE}/crm/v3/objects/notes",
                headers=self.headers,
                json={
                    "properties": {
                        "hs_note_body": f"Dental AI Voice Agent\n\n{summary}\n\nOutcome: {outcome}",
                        "hs_timestamp": str(int(time.time() * 1000)),
                    },
                    "associations": [{"to": {"id": contact_id}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]}],
                },
            )
            response.raise_for_status()
            note = response.json()
            logger.info("HubSpot: created note %s for contact %s", note.get("id"), contact_id)
            return note


hubspot_client = HubSpotClient()