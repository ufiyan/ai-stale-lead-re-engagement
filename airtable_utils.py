import httpx
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dotenv import load_dotenv
import logging
from email_generator import GeminiEmailGenerator

# Load environment variables from .env file
load_dotenv()

class AirtableUtils:
    def __init__(self):
        """Initializes the Airtable client with API keys and table info."""
        self.api_key = os.getenv("AIRTABLE_API_KEY")
        self.base_id = os.getenv("AIRTABLE_BASE_ID")
        self.table_name = os.getenv("AIRTABLE_TABLE_NAME")
        
        if not all([self.api_key, self.base_id, self.table_name]):
            raise ValueError("Missing Airtable configuration. Please set AIRTABLE_API_KEY, AIRTABLE_BASE_ID, and AIRTABLE_TABLE_NAME")
    
    # ... (all other methods are unchanged, as they were already correctly implemented)
    
    async def fetch_stale_leads(self) -> List[Dict]:
        """
        Fetches all leads from Airtable and filters for "stale" leads.
        A lead is considered stale if 'Last Contacted' is more than 7 days ago.
        """
        try:
            async with httpx.AsyncClient() as client:
                url = f"https://api.airtable.com/v0/{self.base_id}/{self.table_name}"
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                all_records = []
                params = {}
                while True:
                    response = await client.get(url, headers=headers, params=params)
                    response.raise_for_status()
                    data = response.json()
                    all_records.extend(data.get("records", []))
                    offset = data.get("offset")
                    if not offset:
                        break
                    params["offset"] = offset
                
                stale_leads = []
                today = datetime.now().date()
                stale_threshold = timedelta(days=7)

                for record in all_records:
                    fields = record.get("fields", {})
                    last_contacted_str = fields.get("Last Contacted")

                    # Normalize field names for internal use (camelCase keys)
                    lead = {
                        "id": record["id"],
                        "full_name": fields.get("Full Name", ""),
                        "email": fields.get("Email Address", ""),
                        "phone_number": fields.get("Phone Number", ""),
                        "potential_interest": fields.get("Potential Interest", ""),
                        "crm_services_needed": fields.get("CRM Services Needed", ""),
                        "lead_source": fields.get("Lead Source", ""),
                        "status_in_sales_funnel": fields.get("Status in Sales Funnel", ""),
                        "last_contacted": fields.get("Last Contacted", ""),
                        "generated_email_message": fields.get("Generated Text Message", ""),
                        "timestamp": fields.get("Timestamp", ""),
                        "status": fields.get("Status", "")
                    }

                    # Only include leads that have not been contacted in >7 days AND have no generated email
                    if not lead.get("generated_email_message"):
                        if not last_contacted_str:
                            stale_leads.append(lead)
                            continue
                        try:
                            if "/" in last_contacted_str:
                                # Airtable is giving you DD/MM/YYYY
                                last_contacted_date = datetime.strptime(last_contacted_str, "%d/%m/%Y").date()
                            else:
                                # Fallback to ISO YYYY-MM-DD
                                last_contacted_date = datetime.strptime(last_contacted_str, "%Y-%m-%d").date()
                            if today - last_contacted_date > stale_threshold:
                                stale_leads.append(lead)
                        except ValueError:
                            logging.warning(f"Could not parse date '{last_contacted_str}' for record ID {record['id']}. Assuming stale.")
                            stale_leads.append(lead)
                
                logging.info(f"Found {len(stale_leads)} stale leads")
                return stale_leads
                
        except Exception as e:
            logging.error(f"Error fetching stale leads: {e}")
            return []

    async def get_lead_by_id(self, lead_id: str) -> Optional[Dict]:
        """Get a specific lead by ID from Airtable"""
        try:
            async with httpx.AsyncClient() as client:
                url = f"https://api.airtable.com/v0/{self.base_id}/{self.table_name}/{lead_id}"
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                
                record = response.json()
                fields = record.get("fields", {})
                
                # Normalize field names for internal use
                lead = {
                    "id": record["id"],
                    "full_name": fields.get("Full Name", ""),
                    "email": fields.get("Email Address", ""),
                    "phone_number": fields.get("Phone Number", ""),
                    "potential_interest": fields.get("Potential Interest", ""),
                    "crm_services_needed": fields.get("CRM Services Needed", ""),
                    "lead_source": fields.get("Lead Source", ""),
                    "status_in_sales_funnel": fields.get("Status in Sales Funnel", ""),
                    "last_contacted": fields.get("Last Contacted", ""),
                    "generated_email_message": fields.get("Generated Text Message", ""),
                    "timestamp": fields.get("Timestamp", ""),
                    "status": fields.get("Status", "")
                }
                
                return lead
                
        except Exception as e:
            logging.error(f"Error fetching lead {lead_id}: {e}")
            return None

    async def update_lead_with_generated_email(self, lead_id: str, generated_email: str) -> bool:
        """Update lead with generated text message, timestamp, and status"""
        try:
            async with httpx.AsyncClient() as client:
                url = f"https://api.airtable.com/v0/{self.base_id}/{self.table_name}/{lead_id}"
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                data = {
                    "fields": {
                        "Generated Text Message": generated_email,
                        "Timestamp": datetime.now().isoformat(),
                        "Status": "Email Generated"
                    }
                }
                
                response = await client.patch(url, headers=headers, json=data)
                response.raise_for_status()
                
                logging.info(f"Successfully updated lead {lead_id} with generated email and status")
                return True
                
        except Exception as e:
            logging.error(f"Error updating lead {lead_id}: {e}")
            return False

    async def process_all_stale_leads(self) -> Dict:
        """Main automation function: Process all stale leads and generate emails"""
        
        try:
            stale_leads = await self.fetch_stale_leads()
            
            if not stale_leads:
                return {
                    "success": True,
                    "message": "No stale leads found",
                    "processed": 0,
                    "results": []
                }
            
            # Correctly instantiate the GeminiEmailGenerator class
            email_generator = GeminiEmailGenerator()
            
            results = []
            success_count = 0
            
            for lead in stale_leads:
                try:
                    # Check if email is already generated for this lead
                    if lead.get('generatedTextMessage'):
                        results.append({
                            "lead_id": lead['id'],
                            "name": lead['fullName'],
                            "status": "already_processed",
                            "message": "Email already generated"
                        })
                        continue
                    
                    if not lead.get('fullName') or not lead.get('emailAddress'):
                        results.append({
                            "lead_id": lead['id'],
                            "name": lead.get('fullName', 'Unknown'),
                            "status": "insufficient_data",
                            "message": "Missing name or email"
                        })
                        continue
                    
                    # Correctly use `await` because generate_re_engagement_email is an async function
                    generated_email = await email_generator.generate_re_engagement_email(lead)
                    
                    update_success = await self.update_lead_with_generated_email(
                        lead['id'], 
                        generated_email
                    )
                    
                    if update_success:
                        success_count += 1
                        results.append({
                            "lead_id": lead['id'],
                            "name": lead['fullName'],
                            "status": "success",
                            "message": "Email generated and saved"
                        })
                    else:
                        results.append({
                            "lead_id": lead['id'],
                            "name": lead['fullName'],
                            "status": "update_failed",
                            "message": "Failed to update Airtable"
                        })
                        
                except Exception as e:
                    results.append({
                        "lead_id": lead['id'],
                        "name": lead.get('fullName', 'Unknown'),
                        "status": "error",
                        "message": f"Processing error: {str(e)}"
                    })
            
            return {
                "success": True,
                "message": f"Processed {len(stale_leads)} stale leads. {success_count} successful.",
                "total_leads": len(stale_leads),
                "successful": success_count,
                "results": results
            }
            
        except Exception as e:
            logging.error(f"Error in process_all_stale_leads: {e}")
            return {
                "success": False,
                "message": f"Error processing stale leads: {str(e)}",
                "processed": 0,
                "results": []
            }

    async def create_new_lead(self, form_data) -> bool:
        """Create a new lead record in Airtable from form submission"""
        try:
            async with httpx.AsyncClient() as client:
                url = f"https://api.airtable.com/v0/{self.base_id}/{self.table_name}"
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                # Map form fields to corrected Airtable fields
                fields = {
                    "Full Name": form_data.fullName,
                    "Email Address": form_data.emailAddress,
                    "Status in Sales Funnel": "New",
                    "Last Contacted": datetime.now().strftime("%Y-%m-%d"),
                }
                
                # Add optional fields if they exist in the form data
                if form_data.phoneNumber:
                    fields["Phone Number"] = form_data.phoneNumber
                
                if form_data.potentialInterest:
                    fields["Potential Interest"] = form_data.potentialInterest
                
                if form_data.crmServicesNeeded:
                    fields["CRM Services Needed"] = form_data.crmServicesNeeded
                
                if form_data.leadSource:
                    fields["Lead Source"] = form_data.leadSource

                data = {
                    "records": [
                        {
                            "fields": fields
                        }
                    ]
                }
                
                logging.info(f"Creating new lead with data: {fields}")
                
                response = await client.post(url, headers=headers, json=data)
                response.raise_for_status()
                
                logging.info("Successfully created lead in Airtable")
                return True
                
        except Exception as e:
            logging.error(f"Error creating new lead: {e}")
            return False

# --- Example Usage (for demonstration) ---
async def main():
    # Sample lead data
    sample_lead = {
        "fullName": "Jane Doe",
        "emailAddress": "jane.doe@example.com",
        "potentialInterest": "CRM integration with marketing automation",
        "crmServicesNeeded": "a seamless data sync solution",
        "leadSource": "a past webinar on sales efficiency",
        "lastContacted": "2023-01-01"
    }
    
    # Example for GeminiEmailGenerator
    email_generator = GeminiEmailGenerator()
    generated_email = await email_generator.generate_re_engagement_email(sample_lead)

    if "Error" not in generated_email:
        print("Generated Email:")
        print("------------------")
        print(generated_email)
    else:
        print(generated_email)
    
    # Example for AirtableUtils
    airtable_utils = AirtableUtils()
    processed_leads_result = await airtable_utils.process_all_stale_leads()
    print("\nProcessed Stale Leads:")
    print("-------------------------")
    print(processed_leads_result)

# To run this code, you would use an event loop.
# Example: asyncio.run(main())