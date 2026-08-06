"""
crm_integration.py — Official HubSpot CRM integration client for Dental Voice Agent.
Handles Contacts search, Contact creation/update, and Engagement/Note logging.
"""
import logging
import httpx
from typing import Optional, Dict, Any
from agent.config import settings

logger = logging.getLogger("hubspot-crm")

HUBSPOT_API_BASE = "https://api.hubapi.com"

class HubSpotClient:
    """Client for interacting with HubSpot CRM v3 REST API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "HUBSPOT_ACCESS_TOKEN", "")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def get_or_create_contact(self, email: Optional[str] = None, phone: Optional[str] = None, first_name: Optional[str] = None, last_name: Optional[str] = None) -> Dict[str, Any]:
        """Lookup contact by email or phone; create if non-existent."""
        if not self.api_key:
            logger.warning("HUBSPOT_ACCESS_TOKEN not set. Running in Mock CRM mode.")
            return {"id": "mock_hubspot_123", "status": "mocked", "properties": {"email": email, "firstname": first_name}}

        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Search existing contact by email or phone
            if email or phone:
                search_url = f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts/search"
                filter_prop = "email" if email else "phone"
                filter_val = email or phone
                search_payload = {
                    "filterGroups": [{
                        "filters": [{
                            "propertyName": filter_prop,
                            "operator": "EQ",
                            "value": filter_val
                        }]
                    }]
                }
                res = await client.post(search_url, headers=self.headers, json=search_payload)
                if res.status_code == 200:
                    results = res.json().get("results", [])
                    if results:
                        logger.info(f"HubSpot: Found existing contact {results[0]['id']}")
                        return results[0]

            # 2. Create new contact if not found
            create_url = f"{HUBSPOT_API_BASE}/crm/v3/objects/contacts"
            props = {
                "firstname": first_name or "Patient",
                "lastname": last_name or "Lead",
                "hs_lead_status": "NEW"
            }
            if email:
                props["email"] = email
            if phone:
                props["phone"] = phone

            payload = {"properties": props}
            res = await client.post(create_url, headers=self.headers, json=payload)
            if res.status_code in (200, 201):
                contact = res.json()
                logger.info(f"HubSpot: Created contact {contact['id']}")
                return contact
            else:
                logger.error(f"HubSpot create failed ({res.status_code}): {res.text}")
                return {"id": "fallback_123", "error": res.text}

    async def log_call_activity(self, contact_id: str, summary: str, outcome: str = "COMPLETED") -> bool:
        """Log call notes / engagement to patient's HubSpot record."""
        if not self.api_key or "mock" in contact_id:
            logger.info(f"Mock CRM: Logged call activity for {contact_id}")
            return True

        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{HUBSPOT_API_BASE}/crm/v3/objects/notes"
            payload = {
                "properties": {
                    "hs_note_body": f"🎙️ Dental AI Voice Call Summary:\n{summary}\nOutcome: {outcome}"
                },
                "associations": [
                    {
                        "to": {"id": contact_id},
                        "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}] # Note to Contact
                    }
                ]
            }
            res = await client.post(url, headers=self.headers, json=payload)
            return res.status_code in (200, 201)

hubspot_client = HubSpotClient()
