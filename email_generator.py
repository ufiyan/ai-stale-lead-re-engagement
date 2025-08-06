import json
import logging
import httpx
import os
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# Set up logging for better error visibility
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GeminiEmailGenerator:
    """
    A class to generate personalized re-engagement emails using the Gemini API.
    """
    def __init__(self, api_key: str = ""):
        """
        Initializes the email generator with the Gemini API key.
        The API key is handled by the canvas environment.
        """
        if not api_key:
            api_key = os.getenv("GEMINI_API_KEY", "")
        self.api_key = api_key
        self.api_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent"
        
    def _create_personalized_prompt(self, lead: Dict) -> str:
        """
        Creates a personalized prompt for the Gemini model based on the lead's data.
        
        Args:
            lead (Dict): A dictionary containing lead information.
        
        Returns:
            str: The formatted prompt string.
        """
        # It's important to match the key names from the Airtable fetch function.
        # The AirtableUtils class normalizes field names to camelCase, so we use those here.
        full_name = lead.get("fullName", "Valued Customer")
        email_address = lead.get("emailAddress", "")
        potential_interest = lead.get("potentialInterest", "our services")
        crm_services_needed = lead.get("crmServicesNeeded", "their CRM needs")
        lead_source = lead.get("leadSource", "a previous conversation")
        last_contacted = lead.get("lastContacted", "more than a week ago")
        
        prompt = f"""
You are a professional sales representative writing a personalized re-engagement email to a lead who has gone stale.

LEAD INFORMATION:
- Name: {full_name}
- Email: {email_address}
- Potential Interest: {potential_interest}
- CRM Services Needed: {crm_services_needed}
- Lead Source: {lead_source}
- Last Contacted: {last_contacted}
- Status: Lead has been inactive for more than 7 days

TASK: Write a compelling, personalized re-engagement email that:
1. Acknowledges the time gap since last contact.
2. References their specific interests and needs.
3. Provides value or insight related to their CRM needs.
4. Includes a clear, soft call-to-action.
5. Maintains a professional but friendly tone.
6. Keep it concise (under 200 words).

FORMAT YOUR RESPONSE AS:
Subject: [Compelling subject line]

[Email body]

Best regards,
[Your Name]

IMPORTANT: Make it personal and relevant to their specific situation. Avoid generic sales language.
"""
        return prompt.strip()

    async def generate_re_engagement_email(self, lead: Dict) -> str:
        """
        Generates a personalized re-engagement email for a stale lead using the Gemini API.

        Args:
            lead (Dict): A dictionary containing lead information.

        Returns:
            str: The generated email content or an error message.
        """
        if not self.validate_lead_data(lead):
            return "Error: Missing required lead data (fullName or emailAddress)."

        try:
            prompt = self._create_personalized_prompt(lead)
            
            payload = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}]
            }

            # Make the API call with exponential backoff
            response = await self._make_api_call(payload)
            
            if response and "candidates" in response and response["candidates"][0]["content"]["parts"][0]["text"]:
                generated_email = response["candidates"][0]["content"]["parts"][0]["text"]
                logging.info(f"Generated email for lead: {lead.get('fullName', 'Unknown')}")
                return generated_email
            else:
                logging.error(f"Gemini API response is empty or malformed: {response}")
                return "Error: Gemini API returned an empty or invalid response."
        except Exception as e:
            logging.error(f"Error generating email for lead {lead.get('fullName', 'Unknown')}: {e}")
            return f"Error generating email: {str(e)}"

    async def _make_api_call(self, payload: Dict, retries: int = 5, delay: int = 1):
        """
        Makes a fetch call to the Gemini API with exponential backoff using httpx.
        The previous code used `js.fetch`, which is not valid Python.
        """
        api_url = f"{self.api_url}?key={self.api_key}"
        for i in range(retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        api_url,
                        headers={'Content-Type': 'application/json'},
                        json=payload,
                        timeout=30
                    )
                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as e:
                # Handle rate limiting specifically
                if e.response.status_code == 429 and i < retries - 1:
                    logging.warning(f"Rate limit exceeded. Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    logging.error(f"HTTP error during API call: {e}")
                    raise
            except httpx.RequestError as e:
                logging.warning(f"API call failed (retry {i+1}/{retries}): {e}")
                if i < retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                else:
                    raise
        return None

    def validate_lead_data(self, lead: Dict) -> bool:
        """
        Validate that required lead data is present for email generation.
        We've updated the field names to match the camelCase keys from AirtableUtils.
        """
        required_fields = ["fullName", "emailAddress"]
        for field in required_fields:
            if not lead.get(field):
                logging.warning(f"Missing required field '{field}' for lead {lead.get('id', 'Unknown')}")
                return False
        return True

