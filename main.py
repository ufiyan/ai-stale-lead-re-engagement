from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, root_validator
from typing import List, Dict, Optional
import os
from datetime import datetime
from dotenv import load_dotenv
import logging

from airtable_utils import AirtableUtils
from email_generator import GeminiEmailGenerator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# Initialize FastAPI app
app = FastAPI(
    title="AI-Powered Stale Lead Re-Engagement API",
    description="Backend API for AI-powered stale lead re-engagement with Airtable integration",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://ufiyan.github.io",
        "https://ufiyan.github.io/spidr-airfryer-form",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create static directory if it doesn't exist
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

# Mount static files
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Initialize utilities
airtable_utils = AirtableUtils()
email_generator = GeminiEmailGenerator()

# Pydantic models - Corrected to match form and Airtable field intentions
class EmailUpdateRequest(BaseModel):
    # This field maps to the 'Generated Text Message' column in your table
    generated_text_message: str

class FormSubmission(BaseModel):
    # Core required fields
    fullName: str
    emailAddress: str = None  # Make optional for validation
    email: Optional[str] = None  # Accept 'email' as well

    # Optional fields based on your form and Airtable table
    phoneNumber: Optional[str] = None
    potentialInterest: Optional[str] = None
    crmServicesNeeded: Optional[str] = None
    leadSource: Optional[str] = None

    @root_validator(pre=True)
    def map_email_field(cls, values):
        # If 'email' is present but 'emailAddress' is not, map it
        if not values.get('emailAddress') and values.get('email'):
            values['emailAddress'] = values['email']
        return values

# ROOT ENDPOINTS
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "AI-Powered Stale Lead Re-Engagement API is running!",
        "docs": "/docs",
        "redoc": "/redoc",
        "admin": "/admin"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "stale-lead-re-engagement-api"}

# ADMIN DASHBOARD STATIC FILE ENDPOINTS
@app.get("/admin")
async def serve_admin_dashboard():
    """Serve the admin dashboard HTML file"""
    admin_file = os.path.join(static_dir, "admin.html")
    if os.path.exists(admin_file):
        return FileResponse(admin_file)
    else:
        raise HTTPException(
            status_code=404, 
            detail="Admin dashboard not found. Please create static/admin.html file."
        )

@app.get("/admin/")
async def admin_dashboard_redirect():
    """Redirect /admin/ to /admin"""
    return await serve_admin_dashboard()

# ===== CORE AUTOMATION ENDPOINTS =====

@app.get("/stale-leads")
async def get_stale_leads():
    """Fetch stale leads where Last Contacted > 7 days"""
    try:
        leads = await airtable_utils.fetch_stale_leads()
        return {
            "leads": leads,
            "total_count": len(leads)
        }
    except Exception as e:
        logger.error(f"Error fetching stale leads: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching stale leads: {str(e)}")

@app.post("/process-stale-leads")
async def process_stale_leads():
    """
    MAIN AUTOMATION ENDPOINT: Process all stale leads.
    """
    try:
        logger.info("Starting stale lead processing automation...")
        result = await airtable_utils.process_all_stale_leads()
        logger.info(f"Automation completed: {result['message']}")
        return result
        
    except Exception as e:
        logger.error(f"Error in process_stale_leads: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing stale leads: {str(e)}")

@app.get("/dashboard-stats")
async def get_dashboard_stats():
    """Get statistics for the admin dashboard"""
    try:
        stale_leads = await airtable_utils.fetch_stale_leads()
        total_stale = len(stale_leads)
        emails_generated = len([lead for lead in stale_leads if lead.get('generated_text_message')])
        pending_engagement = total_stale - emails_generated
        
        return {
            "total_stale_leads": total_stale,
            "emails_generated": emails_generated,
            "pending_engagement": pending_engagement,
            "stale_leads": stale_leads
        }
        
    except Exception as e:
        logger.error(f"Error fetching dashboard stats: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching dashboard stats: {str(e)}")

# ===== INDIVIDUAL LEAD OPERATIONS =====

@app.get("/leads/{lead_id}")
async def get_lead(lead_id: str):
    """Get a specific lead by ID from Airtable"""
    try:
        lead = await airtable_utils.get_lead_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        return lead
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching lead {lead_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching lead: {str(e)}")

@app.post("/generate-email/{lead_id}")
async def generate_email_for_lead(lead_id: str):
    """Generate email for a specific lead and update Airtable"""
    try:
        lead = await airtable_utils.get_lead_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        if not email_generator.validate_lead_data(lead):
            raise HTTPException(status_code=400, detail="Insufficient lead data for email generation")
        
        generated_email = await email_generator.generate_re_engagement_email(lead)  # <-- FIXED
        success = await airtable_utils.update_lead_with_generated_email(lead_id, generated_email)
        
        if success:
            return {
                "lead_id": lead_id,
                "generated_email": generated_email,
                "message": "Email generated and saved successfully",
                "lead_info": lead
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to update Airtable")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating email for lead {lead_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating email: {str(e)}")

@app.post("/update-email/{lead_id}")
async def update_email(lead_id: str, request: EmailUpdateRequest):
    """Update the Generated Text Message field in Airtable with the generated email"""
    try:
        lead = await airtable_utils.get_lead_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        success = await airtable_utils.update_lead_with_generated_email(lead_id, request.generated_text_message)
        
        if success:
            return {
                "message": "Email updated successfully in Airtable",
                "lead_id": lead_id
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to update email in Airtable")
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating email: {str(e)}")

@app.post("/generate-and-update-email/{lead_id}")
async def generate_and_update_email(lead_id: str):
    """Generate a personalized re-engagement email and update Airtable with the result."""
    try:
        lead = await airtable_utils.get_lead_by_id(lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        if not email_generator.validate_lead_data(lead):
            raise HTTPException(status_code=400, detail="Insufficient lead data for email generation")
        
        generated_email = await email_generator.generate_re_engagement_email(lead)  # <-- FIXED
        update_success = await airtable_utils.update_lead_with_generated_email(lead_id, generated_email)
        
        if update_success:
            return {
                "lead_id": lead_id,
                "generated_email": generated_email,
                "lead_info": lead,
                "message": "Email generated and Airtable updated successfully"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to update Airtable with generated email")
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.error(f"Error in generate-and-update-email: {e}")
        raise HTTPException(status_code=500, detail=f"Error in generate-and-update-email: {str(e)}")

# ===== FORM SUBMISSION =====

@app.post("/submit-form")
async def submit_form(form_data: FormSubmission):
    """Submit a new lead form to Airtable with comprehensive field mapping"""
    try:
        import logging
        logging.info(f"Received form submission: {form_data}")
        
        success = await airtable_utils.create_new_lead(form_data)
        
        if success:
            return {
                "message": "Form submitted successfully",
                "status": "success",
                "data": form_data.dict()
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to submit form to Airtable")
            
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.error(f"Error in submit_form endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Error submitting form: {str(e)}")

# ===== DATA EXPORT =====

@app.get("/export-leads")
async def export_leads():
    """Export all stale leads data for download"""
    try:
        leads = await airtable_utils.fetch_stale_leads()
        
        export_data = []
        for lead in leads:
            export_data.append({
                "ID": lead.get("id", ""),
                "Full Name": lead.get("fullName", ""),
                "Email": lead.get("emailAddress", ""),
                "Phone": lead.get("phoneNumber", ""),
                "Interest": lead.get("potentialInterest", ""),
                "CRM Needs": lead.get("crmServicesNeeded", ""),
                "Source": lead.get("leadSource", ""),
                "Status": lead.get("statusInSalesFunnel", ""),
                "Last Contacted": lead.get("lastContacted", ""),
                "Email Generated": "Yes" if lead.get("generatedTextMessage") else "No",
                "Email Status": lead.get("status", ""),
                "Timestamp": lead.get("timestamp", "")
            })
        
        return {
            "data": export_data,
            "total_records": len(export_data),
            "export_timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error exporting leads: {e}")
        raise HTTPException(status_code=500, detail=f"Error exporting leads: {str(e)}")

# ADMIN API ENDPOINTS FOR DASHBOARD
@app.get("/admin/dashboard")
async def admin_dashboard_api():
    """Admin dashboard API to view leads and automation status"""
    try:
        stale_leads = await airtable_utils.fetch_stale_leads()
        total_leads = len(stale_leads)
        leads_with_generated_emails = len([lead for lead in stale_leads if lead.get('generatedTextMessage')])
        leads_pending_engagement = total_leads - leads_with_generated_emails
        
        return {
            "dashboard_stats": {
                "total_stale_leads": total_leads,
                "leads_with_generated_emails": leads_with_generated_emails,
                "leads_pending_engagement": leads_pending_engagement
            },
            "stale_leads": stale_leads
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching dashboard data: {str(e)}")

@app.post("/admin/generate-batch-emails")
async def generate_batch_emails():
    """Generate emails for all stale leads that don't have generated emails yet"""
    try:
        stale_leads = await airtable_utils.fetch_stale_leads()
        leads_to_process = [lead for lead in stale_leads if not lead.get('generatedTextMessage')]
        
        results = []
        success_count = 0
        
        for lead in leads_to_process:
            try:
                if email_generator.validate_lead_data(lead):
                    generated_email = await email_generator.generate_re_engagement_email(lead)  # <-- FIXED
                    email_success = await airtable_utils.update_lead_with_generated_email(lead['id'], generated_email)
                    
                    if email_success:
                        success_count += 1
                        results.append({
                            "lead_id": lead['id'],
                            "lead_name": lead['fullName'],
                            "status": "success"
                        })
                    else:
                        results.append({
                            "lead_id": lead['id'],
                            "lead_name": lead['fullName'],
                            "status": "failed_to_update_airtable"
                        })
                else:
                    results.append({
                        "lead_id": lead['id'],
                        "lead_name": lead['fullName'],
                        "status": "insufficient_data"
                    })
            except Exception as e:
                results.append({
                    "lead_id": lead['id'],
                    "lead_name": lead.get('fullName', 'Unknown'),
                    "status": f"error: {str(e)}"
                })
        
        return {
            "message": f"Batch email generation completed. {success_count}/{len(leads_to_process)} successful.",
            "total_processed": len(leads_to_process),
            "successful": success_count,
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error in batch email generation: {str(e)}")

# SERVER STARTUP
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True
    )
