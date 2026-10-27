// Deployment settings live in config.js (loaded before this file).
const APP_CONFIG = window.APP_CONFIG || {};
const API_BASE_URL = APP_CONFIG.API_BASE_URL || "http://127.0.0.1:8000/api/v1";

console.log("Admin dashboard app.js loaded successfully v400");
let selectedUnansweredQuestionIdForFAQ = null;
function getToken() {
    return localStorage.getItem("access_token");
}

function getHospitalId() {
    const hospitalId = localStorage.getItem("hospital_id");

    if (!hospitalId || hospitalId === "undefined" || hospitalId === "null") {
        return 1;
    }

    return Number(hospitalId);
}

function authHeaders() {
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + getToken()
    };
}

function authFileHeaders() {
    return {
        "Authorization": "Bearer " + getToken()
    };
}

function escapeHTML(text) {
    if (text === null || text === undefined) {
        return "";
    }

    return String(text)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function setText(id, value) {
    const element = document.getElementById(id);

    if (element) {
        element.innerText = value;
    }
}

function setHTML(id, value) {
    const element = document.getElementById(id);

    if (element) {
        element.innerHTML = value;
    }
}

function getValue(id) {
    const element = document.getElementById(id);

    if (!element) {
        return "";
    }

    return element.value.trim();
}

async function login() {
    const email = getValue("email");
    const password = getValue("password");
    const message = document.getElementById("login-message");

    if (!email || !password) {
        message.innerText = "Please enter email and password.";
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/auth/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                email: email,
                password: password
            })
        });

        const data = await response.json();

        if (!response.ok) {
            message.innerText = data.detail || "Login failed";
            return;
        }

        localStorage.setItem("access_token", data.access_token);
        localStorage.setItem("hospital_id", data.hospital_id || 1);

        message.innerText = "Login successful";

        await showDashboard();
    } catch (error) {
        message.innerText = "Backend server is not running";
    }
}

function logout() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("hospital_id");

    document.getElementById("dashboard-section").classList.add("hidden");
    document.getElementById("login-section").classList.remove("hidden");
}

async function showDashboard() {
    document.getElementById("login-section").classList.add("hidden");
    document.getElementById("dashboard-section").classList.remove("hidden");

    await loadCurrentUser();

    await loadChatLogs();
    await loadChatFeedbacks();

    await loadFAQs();
    await loadPatientLeads();
    await loadUnansweredQuestions();

    await loadDepartments();
    await loadHospitalServices();
    await loadLabTests();
    await loadEmergencyContacts();

    await loadDocuments();
    await loadDoctors();
    await loadSchedules();
    await loadAppointments();
    await loadPatients();
}

async function loadCurrentUser() {
    try {
        const response = await fetch(`${API_BASE_URL}/auth/me`, {
            method: "GET",
            headers: authHeaders()
        });

        const data = await response.json();

        if (!response.ok) {
            setText("user-info", "Unable to load user");
            return;
        }

        localStorage.setItem("hospital_id", data.hospital_id || 1);

        setText("user-info", `${data.full_name} | ${data.email} | Role: ${data.role}`);
    } catch (error) {
        setText("user-info", "Unable to load user");
    }
}

/* =========================
   CHAT LOGS + ANALYTICS
========================= */

function updateChatAnalytics(logs) {
    const totalMessages = logs.length;
    const doctorQuestions = logs.filter(log => log.intent === "doctor_info").length;
    const appointmentRequests = logs.filter(log => log.intent === "appointment_booking").length;
    const medicalSafetyQuestions = logs.filter(log => log.intent === "medical_safety").length;
    const documentQuestions = logs.filter(log => log.intent === "document_rag").length;

    setText("total-chat-messages", totalMessages);
    setText("doctor-chat-count", doctorQuestions);
    setText("appointment-chat-count", appointmentRequests);
    setText("medical-safety-count", medicalSafetyQuestions);
    setText("document-rag-count", documentQuestions);
}

async function loadChatLogs() {
    const hospitalId = getHospitalId();

    try {
        const response = await fetch(`${API_BASE_URL}/chat/logs?hospital_id=${hospitalId}`, {
            method: "GET",
            headers: authHeaders()
        });

        const logs = await response.json();

        if (!response.ok) {
            setHTML("chat-logs-list", `<p>${escapeHTML(logs.detail || "Unable to load chat logs")}</p>`);
            updateChatAnalytics([]);
            return;
        }

        updateChatAnalytics(logs);

        if (logs.length === 0) {
            setHTML("chat-logs-list", "<p>No chat logs found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Chat</th>
                    <th>Intent</th>
                    <th>Time</th>
                </tr>
        `;

        logs.forEach(log => {
            html += `
                <tr>
                    <td>${log.id}</td>
                    <td>
                        <div class="chat-log-message">Patient: ${escapeHTML(log.message)}</div>
                        <div class="chat-log-answer">AI: ${escapeHTML(log.answer)}</div>
                    </td>
                    <td><span class="intent-badge">${escapeHTML(log.intent)}</span></td>
                    <td>${escapeHTML(log.created_at)}</td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("chat-logs-list", html);
    } catch (error) {
        setHTML("chat-logs-list", "<p>Unable to load chat logs.</p>");
        updateChatAnalytics([]);
    }
}

/* =========================
   CHAT FEEDBACK ANALYTICS
========================= */

function updateFeedbackAnalytics(feedbacks) {
    const activeFeedbacks = feedbacks.filter(feedback => feedback.is_active !== false);

    const totalFeedback = activeFeedbacks.length;
    const helpfulFeedback = activeFeedbacks.filter(feedback => feedback.helpful === true).length;
    const notHelpfulFeedback = activeFeedbacks.filter(feedback => feedback.helpful === false).length;

    const ratedFeedbacks = activeFeedbacks.filter(
        feedback => feedback.rating !== null && feedback.rating !== undefined
    );

    let averageRating = 0;

    if (ratedFeedbacks.length > 0) {
        const totalRating = ratedFeedbacks.reduce(
            (sum, feedback) => sum + Number(feedback.rating),
            0
        );

        averageRating = (totalRating / ratedFeedbacks.length).toFixed(1);
    }

    setText("total-feedback-count", totalFeedback);
    setText("helpful-feedback-count", helpfulFeedback);
    setText("not-helpful-feedback-count", notHelpfulFeedback);
    setText("average-feedback-rating", averageRating);
}

async function loadChatFeedbacks() {
    try {
        const response = await fetch(`${API_BASE_URL}/feedback/?hospital_id=${getHospitalId()}`, {
            method: "GET",
            headers: authHeaders()
        });

        const feedbacks = await response.json();

        if (!response.ok) {
            setHTML("chat-feedback-list", `<p>${escapeHTML(feedbacks.detail || "Unable to load feedback")}</p>`);
            updateFeedbackAnalytics([]);
            return;
        }

        updateFeedbackAnalytics(feedbacks);

        if (feedbacks.length === 0) {
            setHTML("chat-feedback-list", "<p>No feedback found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Question</th>
                    <th>Answer</th>
                    <th>Intent</th>
                    <th>Helpful</th>
                    <th>Rating</th>
                    <th>Comment</th>
                    <th>Status</th>
                    <th>Time</th>
                    <th>Action</th>
                </tr>
        `;

        feedbacks.forEach(feedback => {
            let helpfulText = "-";

            if (feedback.helpful === true) {
                helpfulText = "Helpful";
            }

            if (feedback.helpful === false) {
                helpfulText = "Not Helpful";
            }

            html += `
                <tr>
                    <td>${feedback.id}</td>
                    <td>${escapeHTML(feedback.message || "-")}</td>
                    <td>${escapeHTML(feedback.answer || "-")}</td>
                    <td>${escapeHTML(feedback.intent || "-")}</td>
                    <td>${helpfulText}</td>
                    <td>${feedback.rating !== null && feedback.rating !== undefined ? feedback.rating : "-"}</td>
                    <td>${escapeHTML(feedback.comment || "-")}</td>
                    <td>${feedback.is_active ? "Active" : "Inactive"}</td>
                    <td>${escapeHTML(feedback.created_at)}</td>
                    <td>
                        ${
                            feedback.is_active
                                ? `<button class="delete-btn" onclick="deleteChatFeedback(${feedback.id})">Deactivate</button>`
                                : `<span>Already Inactive</span>`
                        }
                    </td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("chat-feedback-list", html);
    } catch (error) {
        setHTML("chat-feedback-list", "<p>Unable to load feedback.</p>");
        updateFeedbackAnalytics([]);
    }
}

async function deleteChatFeedback(feedbackId) {
    if (!confirm("Are you sure you want to deactivate this feedback?")) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/feedback/${feedbackId}`, {
            method: "DELETE",
            headers: authHeaders()
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Failed to deactivate feedback");
            return;
        }

        alert("Feedback deactivated successfully");
        await loadChatFeedbacks();
    } catch (error) {
        alert("Backend server is not running.");
    }
}

/* =========================
   FAQ MANAGEMENT
========================= */
async function createFAQ() {
    const question = getValue("faq-question");
    const answer = getValue("faq-answer");
    const category = getValue("faq-category");

    if (!question) {
        setText("faq-message", "FAQ question is required.");
        return;
    }

    if (!answer) {
        setText("faq-message", "FAQ answer is required.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/faqs/`, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({
                hospital_id: getHospitalId(),
                question: question,
                answer: answer,
                category: category || null
            })
        });

        const data = await response.json();

        if (!response.ok) {
            setText("faq-message", data.detail || "FAQ creation failed");
            return;
        }

        if (selectedUnansweredQuestionIdForFAQ) {
            await updateUnansweredQuestionStatus(
                selectedUnansweredQuestionIdForFAQ,
                "faq_created",
                false
            );

            selectedUnansweredQuestionIdForFAQ = null;

            setText("faq-message", "FAQ created successfully and unanswered question marked as FAQ Created.");
        } else {
            setText("faq-message", "FAQ created successfully.");
        }

        document.getElementById("faq-question").value = "";
        document.getElementById("faq-answer").value = "";
        document.getElementById("faq-category").value = "";

        await loadFAQs();
        await loadUnansweredQuestions();
    } catch (error) {
        setText("faq-message", "Backend server is not running.");
    }
}
async function loadFAQs() {
    try {
        const response = await fetch(`${API_BASE_URL}/faqs/?hospital_id=${getHospitalId()}`, {
            method: "GET",
            headers: authHeaders()
        });

        const faqs = await response.json();

        if (!response.ok) {
            setHTML("faqs-list", `<p>${escapeHTML(faqs.detail || "Unable to load FAQs")}</p>`);
            return;
        }

        if (faqs.length === 0) {
            setHTML("faqs-list", "<p>No FAQs found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Question</th>
                    <th>Answer</th>
                    <th>Category</th>
                    <th>Status</th>
                    <th>Time</th>
                    <th>Action</th>
                </tr>
        `;

        faqs.forEach(faq => {
            html += `
                <tr>
                    <td>${faq.id}</td>
                    <td>${escapeHTML(faq.question)}</td>
                    <td>${escapeHTML(faq.answer)}</td>
                    <td>${escapeHTML(faq.category || "-")}</td>
                    <td>${faq.is_active ? "Active" : "Inactive"}</td>
                    <td>${escapeHTML(faq.created_at)}</td>
                    <td>
                        ${
                            faq.is_active
                                ? `<button class="delete-btn" onclick="deleteFAQ(${faq.id})">Deactivate</button>`
                                : `<span>Already Inactive</span>`
                        }
                    </td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("faqs-list", html);
    } catch (error) {
        setHTML("faqs-list", "<p>Unable to load FAQs.</p>");
    }
}

async function deleteFAQ(faqId) {
    if (!confirm("Are you sure you want to deactivate this FAQ?")) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/faqs/${faqId}`, {
            method: "DELETE",
            headers: authHeaders()
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Failed to deactivate FAQ");
            return;
        }

        alert("FAQ deactivated successfully");
        await loadFAQs();
    } catch (error) {
        alert("Backend server is not running.");
    }
}

/* =========================
   PATIENT LEADS
========================= */
async function loadPatientLeads() {
    try {
        const response = await fetch(`${API_BASE_URL}/patient-leads/?hospital_id=${getHospitalId()}`, {
            method: "GET",
            headers: authHeaders()
        });

        const leads = await response.json();

        if (!response.ok) {
            setHTML("patient-leads-list", `<p>${escapeHTML(leads.detail || "Unable to load patient leads")}</p>`);
            return;
        }

        if (leads.length === 0) {
            setHTML("patient-leads-list", "<p>No patient leads found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>Phone</th>
                    <th>Question</th>
                    <th>Interested Service</th>
                    <th>Status</th>
                    <th>Source</th>
                    <th>Time</th>
                    <th>Action</th>
                </tr>
        `;

        leads.forEach(lead => {
            let actionHtml = "";

            if (!lead.is_active) {
                actionHtml = `<span>Deactivated</span>`;
            } else if (lead.status === "contacted") {
                actionHtml = `<span>Contacted</span>`;
            } else {
                actionHtml = `
                    <button onclick="updatePatientLeadStatus(${lead.id}, 'contacted')">Mark Contacted</button>
                    <button class="delete-btn" onclick="deletePatientLead(${lead.id})">Deactivate</button>
                `;
            }

            html += `
                <tr>
                    <td>${lead.id}</td>
                    <td>${escapeHTML(lead.name)}</td>
                    <td>${escapeHTML(lead.phone)}</td>
                    <td>${escapeHTML(lead.question || "-")}</td>
                    <td>${escapeHTML(lead.interested_service || "-")}</td>
                    <td>${escapeHTML(lead.status)}</td>
                    <td>${escapeHTML(lead.source)}</td>
                    <td>${escapeHTML(lead.created_at)}</td>
                    <td>${actionHtml}</td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("patient-leads-list", html);
    } catch (error) {
        setHTML("patient-leads-list", "<p>Unable to load patient leads.</p>");
    }
}
async function updatePatientLeadStatus(leadId, statusValue) {
    try {
        const response = await fetch(`${API_BASE_URL}/patient-leads/${leadId}`, {
            method: "PUT",
            headers: authHeaders(),
            body: JSON.stringify({
                status: statusValue
            })
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Failed to update patient lead");
            return;
        }

        alert("Patient lead updated successfully");
        await loadPatientLeads();
    } catch (error) {
        alert("Backend server is not running.");
    }
}

async function deletePatientLead(leadId) {
    if (!confirm("Are you sure you want to deactivate this patient lead?")) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/patient-leads/${leadId}`, {
            method: "DELETE",
            headers: authHeaders()
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Failed to deactivate patient lead");
            return;
        }

        alert("Patient lead deactivated successfully");
        await loadPatientLeads();
    } catch (error) {
        alert("Backend server is not running.");
    }
}

/* =========================
   UNANSWERED QUESTIONS
========================= */
async function loadUnansweredQuestions() {
    try {
        const response = await fetch(`${API_BASE_URL}/unanswered-questions/?hospital_id=${getHospitalId()}`, {
            method: "GET",
            headers: authHeaders()
        });

        const questions = await response.json();

        if (!response.ok) {
            setHTML("unanswered-questions-list", `<p>${escapeHTML(questions.detail || "Unable to load unanswered questions")}</p>`);
            return;
        }

        if (questions.length === 0) {
            setHTML("unanswered-questions-list", "<p>No unanswered questions found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Question</th>
                    <th>Suggested Action</th>
                    <th>Status</th>
                    <th>Time</th>
                    <th>Action</th>
                </tr>
        `;

        questions.forEach(question => {
            let actionHtml = "";

            if (!question.is_active) {
                actionHtml = `<span>Deactivated</span>`;
            } else if (question.status === "reviewed") {
                actionHtml = `<span>Reviewed</span>`;
            } else if (question.status === "faq_created") {
                actionHtml = `<span>FAQ Created</span>`;
            } else {
                actionHtml = `
                    <button onclick="fillFAQFromUnanswered(${question.id}, '${encodeURIComponent(question.question).replace(/'/g, '%27')}')">Create FAQ</button>
                    <button onclick="updateUnansweredQuestionStatus(${question.id}, 'reviewed')">Mark Reviewed</button>
                    <button class="delete-btn" onclick="deleteUnansweredQuestion(${question.id})">Deactivate</button>
                `;
            }

            html += `
                <tr>
                    <td>${question.id}</td>
                    <td>${escapeHTML(question.question)}</td>
                    <td>${escapeHTML(question.suggested_action || "-")}</td>
                    <td>${escapeHTML(question.status)}</td>
                    <td>${escapeHTML(question.created_at)}</td>
                    <td>${actionHtml}</td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("unanswered-questions-list", html);
    } catch (error) {
        setHTML("unanswered-questions-list", "<p>Unable to load unanswered questions.</p>");
    }
}
function fillFAQFromUnanswered(questionId, encodedQuestion) {
    const questionText = decodeURIComponent(encodedQuestion);

    selectedUnansweredQuestionIdForFAQ = questionId;

    document.getElementById("faq-question").value = questionText;
    document.getElementById("faq-answer").value = "";
    document.getElementById("faq-category").value = "Unanswered Question";

    document.getElementById("faqs").scrollIntoView({
        behavior: "smooth"
    });

    setText("faq-message", "Question copied. Now write the answer and click Create FAQ.");
}
async function updateUnansweredQuestionStatus(questionId, statusValue, showAlert = true) {
    try {
        const response = await fetch(`${API_BASE_URL}/unanswered-questions/${questionId}`, {
            method: "PUT",
            headers: authHeaders(),
            body: JSON.stringify({
                status: statusValue
            })
        });

        const data = await response.json();

        if (!response.ok) {
            if (showAlert) {
                alert(data.detail || "Failed to update unanswered question");
            }

            return;
        }

        if (showAlert) {
            alert("Unanswered question updated successfully");
        }

        await loadUnansweredQuestions();
    } catch (error) {
        if (showAlert) {
            alert("Backend server is not running.");
        }
    }
}
async function deleteUnansweredQuestion(questionId) {
    if (!confirm("Are you sure you want to deactivate this unanswered question?")) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/unanswered-questions/${questionId}`, {
            method: "DELETE",
            headers: authHeaders()
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Failed to deactivate unanswered question");
            return;
        }

        alert("Unanswered question deactivated successfully");
        await loadUnansweredQuestions();
    } catch (error) {
        alert("Backend server is not running.");
    }
}

/* =========================
   DEPARTMENTS
========================= */

async function createDepartment() {
    const name = getValue("department-name");
    const description = getValue("department-description");

    if (!name) {
        setText("department-message", "Department name is required.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/departments/`, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({
                hospital_id: getHospitalId(),
                name: name,
                description: description || null
            })
        });

        const data = await response.json();

        if (!response.ok) {
            setText("department-message", data.detail || "Department creation failed");
            return;
        }

        setText("department-message", "Department created successfully");

        document.getElementById("department-name").value = "";
        document.getElementById("department-description").value = "";

        await loadDepartments();
    } catch (error) {
        setText("department-message", "Backend server is not running.");
    }
}

async function loadDepartments() {
    try {
        const response = await fetch(`${API_BASE_URL}/departments/?hospital_id=${getHospitalId()}`, {
            method: "GET",
            headers: authHeaders()
        });

        const departments = await response.json();

        if (!response.ok) {
            setHTML("departments-list", `<p>${escapeHTML(departments.detail || "Unable to load departments")}</p>`);
            return;
        }

        if (departments.length === 0) {
            setHTML("departments-list", "<p>No departments found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>Description</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
        `;

        departments.forEach(department => {
            html += `
                <tr>
                    <td>${department.id}</td>
                    <td>${escapeHTML(department.name)}</td>
                    <td>${escapeHTML(department.description || "-")}</td>
                    <td>${department.is_active ? "Active" : "Inactive"}</td>
                    <td>
                        ${
                            department.is_active
                                ? `<button class="delete-btn" onclick="deleteDepartment(${department.id})">Deactivate</button>`
                                : `<span>Already Inactive</span>`
                        }
                    </td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("departments-list", html);
    } catch (error) {
        setHTML("departments-list", "<p>Unable to load departments.</p>");
    }
}

async function deleteDepartment(departmentId) {
    if (!confirm("Are you sure you want to deactivate this department?")) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/departments/${departmentId}`, {
            method: "DELETE",
            headers: authHeaders()
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Failed to deactivate department");
            return;
        }

        alert("Department deactivated successfully");
        await loadDepartments();
    } catch (error) {
        alert("Backend server is not running.");
    }
}

/* =========================
   SERVICES
========================= */

async function createHospitalService() {
    const departmentIdValue = getValue("service-department-id");
    const name = getValue("service-name");
    const description = getValue("service-description");

    if (!name) {
        setText("service-message", "Service name is required.");
        return;
    }

    const departmentId = departmentIdValue ? Number(departmentIdValue) : null;

    try {
        const response = await fetch(`${API_BASE_URL}/services/`, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({
                hospital_id: getHospitalId(),
                department_id: departmentId,
                name: name,
                description: description || null
            })
        });

        const data = await response.json();

        if (!response.ok) {
            setText("service-message", data.detail || "Service creation failed");
            return;
        }

        setText("service-message", "Service created successfully");

        document.getElementById("service-department-id").value = "";
        document.getElementById("service-name").value = "";
        document.getElementById("service-description").value = "";

        await loadHospitalServices();
    } catch (error) {
        setText("service-message", "Backend server is not running.");
    }
}

async function loadHospitalServices() {
    try {
        const response = await fetch(`${API_BASE_URL}/services/?hospital_id=${getHospitalId()}`, {
            method: "GET",
            headers: authHeaders()
        });

        const services = await response.json();

        if (!response.ok) {
            setHTML("services-list", `<p>${escapeHTML(services.detail || "Unable to load services")}</p>`);
            return;
        }

        if (services.length === 0) {
            setHTML("services-list", "<p>No services found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Department ID</th>
                    <th>Name</th>
                    <th>Description</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
        `;

        services.forEach(service => {
            html += `
                <tr>
                    <td>${service.id}</td>
                    <td>${service.department_id || "-"}</td>
                    <td>${escapeHTML(service.name)}</td>
                    <td>${escapeHTML(service.description || "-")}</td>
                    <td>${service.is_active ? "Active" : "Inactive"}</td>
                    <td>
                        ${
                            service.is_active
                                ? `<button class="delete-btn" onclick="deleteHospitalService(${service.id})">Deactivate</button>`
                                : `<span>Already Inactive</span>`
                        }
                    </td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("services-list", html);
    } catch (error) {
        setHTML("services-list", "<p>Unable to load services.</p>");
    }
}

async function deleteHospitalService(serviceId) {
    if (!confirm("Are you sure you want to deactivate this service?")) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/services/${serviceId}`, {
            method: "DELETE",
            headers: authHeaders()
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Failed to deactivate service");
            return;
        }

        alert("Service deactivated successfully");
        await loadHospitalServices();
    } catch (error) {
        alert("Backend server is not running.");
    }
}

/* =========================
   LAB TESTS
========================= */

async function createLabTest() {
    const departmentIdValue = getValue("lab-test-department-id");
    const name = getValue("lab-test-name");
    const priceValue = getValue("lab-test-price");
    const sampleType = getValue("lab-test-sample-type");
    const reportTime = getValue("lab-test-report-time");
    const description = getValue("lab-test-description");

    if (!name) {
        setText("lab-test-message", "Lab test name is required.");
        return;
    }

    const departmentId = departmentIdValue ? Number(departmentIdValue) : null;
    const price = priceValue ? Number(priceValue) : null;

    try {
        const response = await fetch(`${API_BASE_URL}/lab-tests/`, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({
                hospital_id: getHospitalId(),
                department_id: departmentId,
                name: name,
                description: description || null,
                price: price,
                sample_type: sampleType || null,
                report_time: reportTime || null
            })
        });

        const data = await response.json();

        if (!response.ok) {
            setText("lab-test-message", data.detail || "Lab test creation failed");
            return;
        }

        setText("lab-test-message", "Lab test created successfully");

        document.getElementById("lab-test-department-id").value = "";
        document.getElementById("lab-test-name").value = "";
        document.getElementById("lab-test-price").value = "";
        document.getElementById("lab-test-sample-type").value = "";
        document.getElementById("lab-test-report-time").value = "";
        document.getElementById("lab-test-description").value = "";

        await loadLabTests();
    } catch (error) {
        setText("lab-test-message", "Backend server is not running.");
    }
}

async function loadLabTests() {
    try {
        const response = await fetch(`${API_BASE_URL}/lab-tests/?hospital_id=${getHospitalId()}`, {
            method: "GET",
            headers: authHeaders()
        });

        const labTests = await response.json();

        if (!response.ok) {
            setHTML("lab-tests-list", `<p>${escapeHTML(labTests.detail || "Unable to load lab tests")}</p>`);
            return;
        }

        if (labTests.length === 0) {
            setHTML("lab-tests-list", "<p>No lab tests found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Department ID</th>
                    <th>Name</th>
                    <th>Price</th>
                    <th>Sample</th>
                    <th>Report Time</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
        `;

        labTests.forEach(test => {
            html += `
                <tr>
                    <td>${test.id}</td>
                    <td>${test.department_id || "-"}</td>
                    <td>${escapeHTML(test.name)}</td>
                    <td>${test.price !== null && test.price !== undefined ? "Rs. " + test.price : "-"}</td>
                    <td>${escapeHTML(test.sample_type || "-")}</td>
                    <td>${escapeHTML(test.report_time || "-")}</td>
                    <td>${test.is_active ? "Active" : "Inactive"}</td>
                    <td>
                        ${
                            test.is_active
                                ? `<button class="delete-btn" onclick="deleteLabTest(${test.id})">Deactivate</button>`
                                : `<span>Already Inactive</span>`
                        }
                    </td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("lab-tests-list", html);
    } catch (error) {
        setHTML("lab-tests-list", "<p>Unable to load lab tests.</p>");
    }
}

async function deleteLabTest(labTestId) {
    if (!confirm("Are you sure you want to deactivate this lab test?")) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/lab-tests/${labTestId}`, {
            method: "DELETE",
            headers: authHeaders()
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Failed to deactivate lab test");
            return;
        }

        alert("Lab test deactivated successfully");
        await loadLabTests();
    } catch (error) {
        alert("Backend server is not running.");
    }
}

/* =========================
   EMERGENCY CONTACTS
========================= */

async function createEmergencyContact() {
    const title = getValue("emergency-title");
    const phoneNumber = getValue("emergency-phone");
    const contactType = getValue("emergency-type");
    const description = getValue("emergency-description");

    if (!title) {
        setText("emergency-message", "Contact title is required.");
        return;
    }

    if (!phoneNumber) {
        setText("emergency-message", "Phone number is required.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/emergency-contacts/`, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({
                hospital_id: getHospitalId(),
                title: title,
                phone_number: phoneNumber,
                contact_type: contactType || null,
                description: description || null
            })
        });

        const data = await response.json();

        if (!response.ok) {
            setText("emergency-message", data.detail || "Emergency contact creation failed");
            return;
        }

        setText("emergency-message", "Emergency contact created successfully");

        document.getElementById("emergency-title").value = "";
        document.getElementById("emergency-phone").value = "";
        document.getElementById("emergency-type").value = "";
        document.getElementById("emergency-description").value = "";

        await loadEmergencyContacts();
    } catch (error) {
        setText("emergency-message", "Backend server is not running.");
    }
}

async function loadEmergencyContacts() {
    try {
        const response = await fetch(`${API_BASE_URL}/emergency-contacts/?hospital_id=${getHospitalId()}`, {
            method: "GET",
            headers: authHeaders()
        });

        const contacts = await response.json();

        if (!response.ok) {
            setHTML("emergency-contacts-list", `<p>${escapeHTML(contacts.detail || "Unable to load emergency contacts")}</p>`);
            return;
        }

        if (contacts.length === 0) {
            setHTML("emergency-contacts-list", "<p>No emergency contacts found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Title</th>
                    <th>Phone</th>
                    <th>Type</th>
                    <th>Description</th>
                    <th>Status</th>
                    <th>Action</th>
                </tr>
        `;

        contacts.forEach(contact => {
            html += `
                <tr>
                    <td>${contact.id}</td>
                    <td>${escapeHTML(contact.title)}</td>
                    <td>${escapeHTML(contact.phone_number)}</td>
                    <td>${escapeHTML(contact.contact_type || "-")}</td>
                    <td>${escapeHTML(contact.description || "-")}</td>
                    <td>${contact.is_active ? "Active" : "Inactive"}</td>
                    <td>
                        ${
                            contact.is_active
                                ? `<button class="delete-btn" onclick="deleteEmergencyContact(${contact.id})">Deactivate</button>`
                                : `<span>Already Inactive</span>`
                        }
                    </td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("emergency-contacts-list", html);
    } catch (error) {
        setHTML("emergency-contacts-list", "<p>Unable to load emergency contacts.</p>");
    }
}

async function deleteEmergencyContact(contactId) {
    if (!confirm("Are you sure you want to deactivate this emergency contact?")) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/emergency-contacts/${contactId}`, {
            method: "DELETE",
            headers: authHeaders()
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Failed to deactivate emergency contact");
            return;
        }

        alert("Emergency contact deactivated successfully");
        await loadEmergencyContacts();
    } catch (error) {
        alert("Backend server is not running.");
    }
}

/* =========================
   RAG + DOCUMENTS
========================= */

async function askRagQuestion() {
    const question = getValue("rag-question");

    if (!question) {
        setHTML("rag-answer", "<p>Please enter a question.</p>");
        return;
    }

    setHTML("rag-answer", "<p>Searching uploaded documents...</p>");

    try {
        const response = await fetch(`${API_BASE_URL}/rag/ask`, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({
                hospital_id: getHospitalId(),
                question: question
            })
        });

        const data = await response.json();

        if (!response.ok) {
            setHTML("rag-answer", `<p>${escapeHTML(data.detail || "Unable to get answer")}</p>`);
            return;
        }

        let html = `
            <h4>Answer</h4>
            <p>${escapeHTML(data.answer)}</p>
        `;

        if (data.sources && data.sources.length > 0) {
            html += "<h4>Sources</h4>";

            data.sources.forEach(source => {
                html += `
                    <div class="rag-source">
                        <strong>Document ID:</strong> ${source.document_id}<br>
                        <strong>Chunk ID:</strong> ${source.chunk_id}<br>
                        <strong>Score:</strong> ${source.score}<br>
                        <p>${escapeHTML(source.content)}</p>
                    </div>
                `;
            });
        }

        setHTML("rag-answer", html);
    } catch (error) {
        setHTML("rag-answer", "<p>Backend server is not running.</p>");
    }
}

async function uploadDocument() {
    const documentType = getValue("document-type");
    const fileInput = document.getElementById("document-file");

    if (!fileInput.files || fileInput.files.length === 0) {
        setText("document-message", "Please select a file");
        return;
    }

    const formData = new FormData();
    formData.append("hospital_id", getHospitalId());
    formData.append("document_type", documentType);
    formData.append("file", fileInput.files[0]);

    try {
        const response = await fetch(`${API_BASE_URL}/documents/upload`, {
            method: "POST",
            headers: authFileHeaders(),
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            setText("document-message", data.detail || "Document upload failed");
            return;
        }

        setText("document-message", "Document uploaded successfully");

        document.getElementById("document-type").value = "";
        document.getElementById("document-file").value = "";

        await loadDocuments();
    } catch (error) {
        setText("document-message", "Backend server is not running.");
    }
}

async function loadDocuments() {
    try {
        const response = await fetch(`${API_BASE_URL}/documents/`, {
            method: "GET",
            headers: authHeaders()
        });

        const documents = await response.json();

        if (!response.ok) {
            setHTML("documents-list", `<p>${escapeHTML(documents.detail || "Unable to load documents")}</p>`);
            return;
        }

        if (documents.length === 0) {
            setHTML("documents-list", "<p>No documents uploaded.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>File Name</th>
                    <th>Type</th>
                    <th>Stored File</th>
                    <th>Uploaded At</th>
                    <th>Action</th>
                </tr>
        `;

        documents.forEach(documentItem => {
            html += `
                <tr>
                    <td>${documentItem.id}</td>
                    <td>${escapeHTML(documentItem.file_name)}</td>
                    <td>${escapeHTML(documentItem.document_type || "-")}</td>
                    <td>${escapeHTML(documentItem.stored_file_name)}</td>
                    <td>${escapeHTML(documentItem.created_at)}</td>
                    <td>
                        <button class="delete-btn" onclick="deleteDocument(${documentItem.id})">
                            Delete
                        </button>
                    </td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("documents-list", html);
    } catch (error) {
        setHTML("documents-list", "<p>Unable to load documents.</p>");
    }
}

async function deleteDocument(documentId) {
    if (!confirm("Are you sure you want to delete this document?")) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/documents/${documentId}`, {
            method: "DELETE",
            headers: authHeaders()
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Failed to delete document");
            return;
        }

        alert("Document deleted successfully");
        await loadDocuments();
    } catch (error) {
        alert("Backend server is not running.");
    }
}

/* =========================
   DOCTORS
========================= */

async function createDoctor() {
    const name = getValue("doctor-name");
    const specialization = getValue("doctor-specialization");
    const feeValue = getValue("doctor-fee");
    const phone = getValue("doctor-phone");

    if (!name || !specialization) {
        setText("doctor-message", "Doctor name and specialization are required.");
        return;
    }

    const fee = feeValue ? Number(feeValue) : null;

    try {
        const response = await fetch(`${API_BASE_URL}/doctors/`, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({
                hospital_id: getHospitalId(),
                name: name,
                specialization: specialization,
                consultation_fee: fee,
                phone: phone || null
            })
        });

        const data = await response.json();

        if (!response.ok) {
            setText("doctor-message", data.detail || "Doctor creation failed");
            return;
        }

        setText("doctor-message", "Doctor created successfully");

        document.getElementById("doctor-name").value = "";
        document.getElementById("doctor-specialization").value = "";
        document.getElementById("doctor-fee").value = "";
        document.getElementById("doctor-phone").value = "";

        await loadDoctors();
    } catch (error) {
        setText("doctor-message", "Backend server is not running.");
    }
}

async function loadDoctors() {
    try {
        const response = await fetch(`${API_BASE_URL}/doctors/`, {
            method: "GET",
            headers: authHeaders()
        });

        const doctors = await response.json();

        if (!response.ok) {
            setHTML("doctors-list", `<p>${escapeHTML(doctors.detail || "Unable to load doctors")}</p>`);
            setText("total-doctors", "0");
            return;
        }

        setText("total-doctors", doctors.length);

        if (doctors.length === 0) {
            setHTML("doctors-list", "<p>No doctors found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>Specialization</th>
                    <th>Fee</th>
                    <th>Phone</th>
                </tr>
        `;

        doctors.forEach(doctor => {
            html += `
                <tr>
                    <td>${doctor.id}</td>
                    <td>${escapeHTML(doctor.name)}</td>
                    <td>${escapeHTML(doctor.specialization)}</td>
                    <td>${doctor.consultation_fee !== null && doctor.consultation_fee !== undefined ? doctor.consultation_fee : "-"}</td>
                    <td>${escapeHTML(doctor.phone || "-")}</td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("doctors-list", html);
    } catch (error) {
        setHTML("doctors-list", "<p>Unable to load doctors.</p>");
        setText("total-doctors", "0");
    }
}

/* =========================
   SCHEDULES
========================= */

async function createSchedule() {
    const doctorId = Number(getValue("schedule-doctor-id"));
    const day = getValue("schedule-day");
    const startTime = getValue("schedule-start-time");
    const endTime = getValue("schedule-end-time");
    const duration = Number(getValue("schedule-duration"));

    if (!doctorId || !day || !startTime || !endTime || !duration) {
        setText("schedule-message", "All schedule fields are required.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/schedules/`, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({
                hospital_id: getHospitalId(),
                doctor_id: doctorId,
                day_of_week: day,
                start_time: startTime + ":00",
                end_time: endTime + ":00",
                slot_duration_minutes: duration
            })
        });

        const data = await response.json();

        if (!response.ok) {
            setText("schedule-message", data.detail || "Schedule creation failed");
            return;
        }

        setText("schedule-message", "Schedule created successfully");

        document.getElementById("schedule-doctor-id").value = "";
        document.getElementById("schedule-day").value = "";
        document.getElementById("schedule-start-time").value = "";
        document.getElementById("schedule-end-time").value = "";
        document.getElementById("schedule-duration").value = "30";

        await loadSchedules();
    } catch (error) {
        setText("schedule-message", "Backend server is not running.");
    }
}

async function loadSchedules() {
    try {
        const response = await fetch(`${API_BASE_URL}/schedules/`, {
            method: "GET",
            headers: authHeaders()
        });

        const schedules = await response.json();

        if (!response.ok) {
            setHTML("schedules-list", `<p>${escapeHTML(schedules.detail || "Unable to load schedules")}</p>`);
            return;
        }

        if (schedules.length === 0) {
            setHTML("schedules-list", "<p>No schedules found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Doctor ID</th>
                    <th>Day</th>
                    <th>Start</th>
                    <th>End</th>
                    <th>Slot</th>
                </tr>
        `;

        schedules.forEach(schedule => {
            html += `
                <tr>
                    <td>${schedule.id}</td>
                    <td>${schedule.doctor_id}</td>
                    <td>${escapeHTML(schedule.day_of_week)}</td>
                    <td>${escapeHTML(schedule.start_time)}</td>
                    <td>${escapeHTML(schedule.end_time)}</td>
                    <td>${schedule.slot_duration_minutes} min</td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("schedules-list", html);
    } catch (error) {
        setHTML("schedules-list", "<p>Unable to load schedules.</p>");
    }
}

/* =========================
   APPOINTMENTS
========================= */

async function checkAvailableSlots() {
    const doctorId = Number(getValue("slot-doctor-id"));
    const date = getValue("slot-date");

    if (!doctorId || !date) {
        setHTML("slots-list", "<p>Please enter doctor ID and date.</p>");
        return;
    }

    try {
        const response = await fetch(
            `${API_BASE_URL}/appointments/available-slots?hospital_id=${getHospitalId()}&doctor_id=${doctorId}&appointment_date=${date}`,
            {
                method: "GET",
                headers: authHeaders()
            }
        );

        const data = await response.json();

        if (!response.ok) {
            setHTML("slots-list", `<p>${escapeHTML(data.detail || "Unable to load slots")}</p>`);
            return;
        }

        if (!data.available_slots || data.available_slots.length === 0) {
            setHTML("slots-list", "<p>No available slots found.</p>");
            return;
        }

        let html = `<h4>Available Slots for ${escapeHTML(data.doctor_name)}</h4>`;

        data.available_slots.forEach(slot => {
            html += `
                <button onclick="selectSlot('${slot}', ${doctorId}, '${date}')">${slot}</button>
            `;
        });

        setHTML("slots-list", html);
    } catch (error) {
        setHTML("slots-list", "<p>Backend server is not running.</p>");
    }
}

function selectSlot(slot, doctorId, date) {
    document.getElementById("appointment-doctor-id").value = doctorId;
    document.getElementById("appointment-date").value = date;
    document.getElementById("appointment-time").value = slot.substring(0, 5);
}

async function createAppointment() {
    const doctorId = Number(getValue("appointment-doctor-id"));
    const patientId = Number(getValue("appointment-patient-id"));
    const date = getValue("appointment-date");
    const time = getValue("appointment-time");
    const reason = getValue("appointment-reason");

    if (!doctorId || !patientId || !date || !time) {
        setText("appointment-message", "Doctor ID, Patient ID, date and time are required.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/appointments/`, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({
                hospital_id: getHospitalId(),
                doctor_id: doctorId,
                patient_id: patientId,
                appointment_date: date,
                appointment_time: time + ":00",
                reason: reason || null
            })
        });

        const data = await response.json();

        if (!response.ok) {
            setText("appointment-message", data.detail || "Appointment booking failed");
            return;
        }

        setText("appointment-message", "Appointment booked successfully");

        document.getElementById("appointment-doctor-id").value = "";
        document.getElementById("appointment-patient-id").value = "";
        document.getElementById("appointment-date").value = "";
        document.getElementById("appointment-time").value = "";
        document.getElementById("appointment-reason").value = "";

        await loadAppointments();
    } catch (error) {
        setText("appointment-message", "Backend server is not running.");
    }
}

async function loadAppointments() {
    try {
        const response = await fetch(`${API_BASE_URL}/appointments/`, {
            method: "GET",
            headers: authHeaders()
        });

        const appointments = await response.json();

        if (!response.ok) {
            setHTML("appointments-list", `<p>${escapeHTML(appointments.detail || "Unable to load appointments")}</p>`);
            setText("total-appointments", "0");
            setText("booked-appointments", "0");
            return;
        }

        setText("total-appointments", appointments.length);

        const bookedAppointments = appointments.filter(
            appointment => appointment.status === "booked" || appointment.status === "confirmed"
        );

        setText("booked-appointments", bookedAppointments.length);

        if (appointments.length === 0) {
            setHTML("appointments-list", "<p>No appointments found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Doctor ID</th>
                    <th>Patient ID</th>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Status</th>
                    <th>Reason</th>
                    <th>Action</th>
                </tr>
        `;

        appointments.forEach(appointment => {
            let actionButton = "-";

            if (appointment.status !== "cancelled") {
                actionButton = `
                    <button class="cancel-btn" onclick="cancelAppointment(${appointment.id})">
                        Cancel
                    </button>
                `;
            }

            html += `
                <tr>
                    <td>${appointment.id}</td>
                    <td>${appointment.doctor_id}</td>
                    <td>${appointment.patient_id}</td>
                    <td>${escapeHTML(appointment.appointment_date)}</td>
                    <td>${escapeHTML(appointment.appointment_time)}</td>
                    <td>${escapeHTML(appointment.status)}</td>
                    <td>${escapeHTML(appointment.reason || "-")}</td>
                    <td>${actionButton}</td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("appointments-list", html);
    } catch (error) {
        setHTML("appointments-list", "<p>Unable to load appointments.</p>");
        setText("total-appointments", "0");
        setText("booked-appointments", "0");
    }
}

async function cancelAppointment(appointmentId) {
    if (!confirm("Are you sure you want to cancel this appointment?")) {
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/appointments/${appointmentId}`, {
            method: "DELETE",
            headers: authHeaders()
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Failed to cancel appointment");
            return;
        }

        alert("Appointment cancelled successfully");
        await loadAppointments();
    } catch (error) {
        alert("Backend server is not running.");
    }
}

/* =========================
   PATIENTS
========================= */

async function createPatient() {
    const name = getValue("patient-name");
    const phone = getValue("patient-phone");
    const email = getValue("patient-email");

    if (!name || !phone) {
        setText("patient-message", "Patient name and phone are required.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/patients/`, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({
                hospital_id: getHospitalId(),
                name: name,
                phone: phone,
                email: email || null
            })
        });

        const data = await response.json();

        if (!response.ok) {
            setText("patient-message", data.detail || "Patient creation failed");
            return;
        }

        setText("patient-message", "Patient created successfully");

        document.getElementById("patient-name").value = "";
        document.getElementById("patient-phone").value = "";
        document.getElementById("patient-email").value = "";

        await loadPatients();
    } catch (error) {
        setText("patient-message", "Backend server is not running.");
    }
}

async function loadPatients() {
    try {
        const response = await fetch(`${API_BASE_URL}/patients/`, {
            method: "GET",
            headers: authHeaders()
        });

        const patients = await response.json();

        if (!response.ok) {
            setHTML("patients-list", `<p>${escapeHTML(patients.detail || "Unable to load patients")}</p>`);
            setText("total-patients", "0");
            return;
        }

        setText("total-patients", patients.length);

        if (patients.length === 0) {
            setHTML("patients-list", "<p>No patients found.</p>");
            return;
        }

        let html = `
            <table>
                <tr>
                    <th>ID</th>
                    <th>Name</th>
                    <th>Phone</th>
                    <th>Email</th>
                </tr>
        `;

        patients.forEach(patient => {
            html += `
                <tr>
                    <td>${patient.id}</td>
                    <td>${escapeHTML(patient.name)}</td>
                    <td>${escapeHTML(patient.phone)}</td>
                    <td>${escapeHTML(patient.email || "-")}</td>
                </tr>
            `;
        });

        html += "</table>";

        setHTML("patients-list", html);
    } catch (error) {
        setHTML("patients-list", "<p>Unable to load patients.</p>");
        setText("total-patients", "0");
    }
}

/* =========================
   WINDOW FUNCTIONS
========================= */

window.login = login;
window.logout = logout;
window.showDashboard = showDashboard;

window.loadChatLogs = loadChatLogs;

window.loadChatFeedbacks = loadChatFeedbacks;
window.deleteChatFeedback = deleteChatFeedback;

window.createFAQ = createFAQ;
window.loadFAQs = loadFAQs;
window.deleteFAQ = deleteFAQ;

window.loadPatientLeads = loadPatientLeads;
window.updatePatientLeadStatus = updatePatientLeadStatus;
window.deletePatientLead = deletePatientLead;

window.loadUnansweredQuestions = loadUnansweredQuestions;
window.fillFAQFromUnanswered = fillFAQFromUnanswered;
window.updateUnansweredQuestionStatus = updateUnansweredQuestionStatus;
window.deleteUnansweredQuestion = deleteUnansweredQuestion;

window.createDepartment = createDepartment;
window.loadDepartments = loadDepartments;
window.deleteDepartment = deleteDepartment;

window.createHospitalService = createHospitalService;
window.loadHospitalServices = loadHospitalServices;
window.deleteHospitalService = deleteHospitalService;

window.createLabTest = createLabTest;
window.loadLabTests = loadLabTests;
window.deleteLabTest = deleteLabTest;

window.createEmergencyContact = createEmergencyContact;
window.loadEmergencyContacts = loadEmergencyContacts;
window.deleteEmergencyContact = deleteEmergencyContact;

window.askRagQuestion = askRagQuestion;

window.uploadDocument = uploadDocument;
window.loadDocuments = loadDocuments;
window.deleteDocument = deleteDocument;

window.createDoctor = createDoctor;
window.loadDoctors = loadDoctors;

window.createSchedule = createSchedule;
window.loadSchedules = loadSchedules;

window.checkAvailableSlots = checkAvailableSlots;
window.selectSlot = selectSlot;

window.createAppointment = createAppointment;
window.loadAppointments = loadAppointments;
window.cancelAppointment = cancelAppointment;

window.createPatient = createPatient;
window.loadPatients = loadPatients;

window.onload = async function () {
    if (getToken()) {
        await showDashboard();
    }
};