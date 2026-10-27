from fastapi import APIRouter

from app.api.v1.endpoints import (
    appointments,
    auth,
    chat,
    chat_feedback,
    departments,
    doctors,
    documents,
    emergency_contacts,
    faqs,
    hospital_services,
    hospitals,
    lab_tests,
    patient_leads,
    patients,
    public_booking,
    rag,
    schedules,
    unanswered_questions,
    otp,
    observability
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(hospitals.router, prefix="/hospitals", tags=["Hospitals"])
api_router.include_router(doctors.router, prefix="/doctors", tags=["Doctors"])
api_router.include_router(patients.router, prefix="/patients", tags=["Patients"])
api_router.include_router(appointments.router, prefix="/appointments", tags=["Appointments"])
api_router.include_router(schedules.router, prefix="/schedules", tags=["Schedules"])
api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])
api_router.include_router(rag.router, prefix="/rag", tags=["RAG"])
api_router.include_router(chat.router, prefix="/chat", tags=["Patient Chat"])
api_router.include_router(chat_feedback.router, prefix="/feedback", tags=["Chat Feedback"])
api_router.include_router(public_booking.router, prefix="/public", tags=["Public Booking"])
api_router.include_router(departments.router, prefix="/departments", tags=["Departments"])
api_router.include_router(hospital_services.router, prefix="/services", tags=["Hospital Services"])
api_router.include_router(lab_tests.router, prefix="/lab-tests", tags=["Lab Tests"])
api_router.include_router(emergency_contacts.router, prefix="/emergency-contacts", tags=["Emergency Contacts"])
api_router.include_router(patient_leads.router, prefix="/patient-leads", tags=["Patient Leads"])
api_router.include_router(faqs.router, prefix="/faqs", tags=["FAQs"])
api_router.include_router(unanswered_questions.router, prefix="/unanswered-questions", tags=["Unanswered Questions"])
api_router.include_router(otp.router, prefix="/otp", tags=["OTP Verification"])
api_router.include_router(observability.router, prefix="/observability", tags=["Observability"])
