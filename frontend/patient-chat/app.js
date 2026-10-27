console.log("LLM-FIRST APP LOADED - VERSION 20260913-2");
// Deployment settings live in config.js (loaded before this file).
const APP_CONFIG = window.APP_CONFIG || {};
const API_BASE_URL = APP_CONFIG.API_BASE_URL || "http://127.0.0.1:8000/api/v1";
const HOSPITAL_ID = Number(APP_CONFIG.HOSPITAL_ID) || 1;

const CHAT_SESSION_KEY = "hospital_ai_chat_session_id";

function createChatSessionId() {
    return "web_" + Date.now() + "_" + Math.random().toString(36).substring(2, 12);
}

function getChatSessionId() {
    let sessionId = localStorage.getItem(CHAT_SESSION_KEY);

    if (!sessionId) {
        sessionId = createChatSessionId();
        localStorage.setItem(CHAT_SESSION_KEY, sessionId);
    }

    return sessionId;
}

function startNewChat() {
    const newSessionId = createChatSessionId();
    localStorage.setItem(CHAT_SESSION_KEY, newSessionId);

    const chatBox = document.getElementById("chat-box");

    if (chatBox) {
        chatBox.innerHTML = "";
    }

    const input = document.getElementById("message-input");

    if (input) {
        input.value = "";
        input.focus();
    }
}

window.startNewChat = startNewChat;

console.log("Patient chat app.js loaded - LLM first routing");

const feedbackStore = {};

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

function getTodayDateString() {
    const today = new Date();

    const year = today.getFullYear();
    const month = String(today.getMonth() + 1).padStart(2, "0");
    const day = String(today.getDate()).padStart(2, "0");

    return `${year}-${month}-${day}`;
}

function isPastDate(selectedDate) {
    return selectedDate < getTodayDateString();
}

function setupDateSafety() {
    const bookingDateInput = document.getElementById("booking-date");
    const rescheduleDateInput = document.getElementById("reschedule-date");

    const today = getTodayDateString();

    if (bookingDateInput) {
        bookingDateInput.min = today;

        if (
            !bookingDateInput.value ||
            bookingDateInput.value < today
        ) {
            bookingDateInput.value = today;
        }
    }

    if (rescheduleDateInput) {
        rescheduleDateInput.min = today;

        if (
            !rescheduleDateInput.value ||
            rescheduleDateInput.value < today
        ) {
            rescheduleDateInput.value = today;
        }
    }
}

function setupBookingFormEvents() {
    const bookingDateInput =
        document.getElementById("booking-date");

    const doctorSelect =
        document.getElementById("booking-doctor");

    if (!bookingDateInput || !doctorSelect) {
        return;
    }

    bookingDateInput.onchange = function () {
        const slots =
            document.getElementById("available-slots");

        const selectedSlot =
            document.getElementById("selected-slot");

        const confirmation =
            document.getElementById("appointment-confirmation");

        const bookingMessage =
            document.getElementById("booking-message");

        if (slots) {
            slots.innerHTML = "";
        }

        if (selectedSlot) {
            selectedSlot.value = "";
        }

        if (confirmation) {
            confirmation.innerHTML = "";
        }

        if (bookingMessage) {
            bookingMessage.innerText = "";
            bookingMessage.className = "";
        }

        if (isPastDate(bookingDateInput.value)) {
            if (bookingMessage) {
                bookingMessage.innerText =
                    "You cannot select a past date.";

                bookingMessage.className =
                    "error-text";
            }

            setupDateSafety();
        }
    };

    doctorSelect.onchange = function () {
        const slots =
            document.getElementById("available-slots");

        const selectedSlot =
            document.getElementById("selected-slot");

        const confirmation =
            document.getElementById("appointment-confirmation");

        const bookingMessage =
            document.getElementById("booking-message");

        if (slots) {
            slots.innerHTML = "";
        }

        if (selectedSlot) {
            selectedSlot.value = "";
        }

        if (confirmation) {
            confirmation.innerHTML = "";
        }

        if (bookingMessage) {
            bookingMessage.innerText = "";
            bookingMessage.className = "";
        }
    };
}

function setupRescheduleFormEvents() {
    const rescheduleDateInput =
        document.getElementById("reschedule-date");

    const doctorSelect =
        document.getElementById("reschedule-doctor");

    if (!rescheduleDateInput || !doctorSelect) {
        return;
    }

    rescheduleDateInput.onchange = function () {
        const slots =
            document.getElementById(
                "reschedule-available-slots"
            );

        const selectedSlot =
            document.getElementById(
                "reschedule-selected-slot"
            );

        const confirmation =
            document.getElementById(
                "reschedule-confirmation"
            );

        const message =
            document.getElementById(
                "reschedule-message"
            );

        if (slots) {
            slots.innerHTML = "";
        }

        if (selectedSlot) {
            selectedSlot.value = "";
        }

        if (confirmation) {
            confirmation.innerHTML = "";
        }

        if (message) {
            message.innerText = "";
            message.className = "";
        }

        if (isPastDate(rescheduleDateInput.value)) {
            if (message) {
                message.innerText =
                    "You cannot select a past date.";

                message.className =
                    "error-text";
            }

            setupDateSafety();
        }
    };

    doctorSelect.onchange = function () {
        const slots =
            document.getElementById(
                "reschedule-available-slots"
            );

        const selectedSlot =
            document.getElementById(
                "reschedule-selected-slot"
            );

        const confirmation =
            document.getElementById(
                "reschedule-confirmation"
            );

        const message =
            document.getElementById(
                "reschedule-message"
            );

        if (slots) {
            slots.innerHTML = "";
        }

        if (selectedSlot) {
            selectedSlot.value = "";
        }

        if (confirmation) {
            confirmation.innerHTML = "";
        }

        if (message) {
            message.innerText = "";
            message.className = "";
        }
    };
}

function addMessage(type, text) {
    const chatBox =
        document.getElementById("chat-box");

    if (!chatBox) {
        return;
    }

    const messageDiv =
        document.createElement("div");

    messageDiv.classList.add("message");

    if (type === "user") {
        messageDiv.classList.add(
            "user-message"
        );
    } else {
        messageDiv.classList.add(
            "bot-message"
        );
    }

    messageDiv.innerText =
        text || "";

    chatBox.appendChild(messageDiv);

    chatBox.scrollTop =
        chatBox.scrollHeight;
}

function addBotMessageWithFeedback(
    userMessage,
    answer,
    intent
) {
    const chatBox =
        document.getElementById("chat-box");

    if (!chatBox) {
        return;
    }

    const messageDiv =
        document.createElement("div");

    messageDiv.classList.add(
        "message",
        "bot-message"
    );

    const textDiv =
        document.createElement("div");

    textDiv.innerText =
        answer || "";

    const feedbackId =
        `feedback_${Date.now()}_${Math.random()
            .toString(36)
            .substring(2, 10)}`;

    feedbackStore[feedbackId] = {
        message: userMessage,
        answer: answer,
        intent: intent
    };

    const feedbackDiv =
        document.createElement("div");

    feedbackDiv.style.marginTop =
        "10px";

    feedbackDiv.style.display =
        "flex";

    feedbackDiv.style.gap =
        "8px";

    feedbackDiv.style.flexWrap =
        "wrap";

    const helpfulButton =
        document.createElement("button");

    helpfulButton.innerText =
        "Helpful 👍";

    helpfulButton.onclick =
        function () {
            submitChatFeedback(
                feedbackId,
                true,
                5,
                feedbackDiv
            );
        };

    const notHelpfulButton =
        document.createElement("button");

    notHelpfulButton.innerText =
        "Not Helpful 👎";

    notHelpfulButton.onclick =
        function () {
            submitChatFeedback(
                feedbackId,
                false,
                1,
                feedbackDiv
            );
        };

    feedbackDiv.appendChild(
        helpfulButton
    );

    feedbackDiv.appendChild(
        notHelpfulButton
    );

    messageDiv.appendChild(
        textDiv
    );

    messageDiv.appendChild(
        feedbackDiv
    );

    chatBox.appendChild(
        messageDiv
    );

    chatBox.scrollTop =
        chatBox.scrollHeight;
}

async function submitChatFeedback(
    feedbackId,
    helpful,
    rating,
    feedbackDiv
) {
    const feedbackData =
        feedbackStore[feedbackId];

    if (!feedbackData) {
        feedbackDiv.innerHTML =
            "<span>Feedback data not found.</span>";

        return;
    }

    feedbackDiv.innerHTML =
        "<span>Saving feedback...</span>";

    try {
        const response =
            await fetch(
                `${API_BASE_URL}/feedback/`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            hospital_id:
                                HOSPITAL_ID,

                            message:
                                feedbackData.message,

                            answer:
                                feedbackData.answer,

                            intent:
                                feedbackData.intent,

                            rating:
                                rating,

                            helpful:
                                helpful,

                            comment:
                                helpful
                                    ? "Helpful answer"
                                    : "Not helpful answer"
                        })
                }
            );

        const data =
            await response.json();

        if (!response.ok) {
            feedbackDiv.innerHTML =
                `<span>${
                    escapeHTML(
                        data.detail ||
                        "Feedback failed."
                    )
                }</span>`;

            return;
        }

        feedbackDiv.innerHTML =
            "<span>Thanks for your feedback.</span>";
    } catch (error) {
        console.error(
            "Feedback request failed:",
            error
        );

        feedbackDiv.innerHTML =
            "<span>Unable to save feedback right now.</span>";
    }
}

function handleEnter(event) {
    if (
        event.key === "Enter" &&
        !event.shiftKey
    ) {
        event.preventDefault();

        sendMessage();
    }
}

function sendQuickMessage(message) {
    const input =
        document.getElementById(
            "message-input"
        );

    if (!input) {
        return;
    }

    input.value =
        message;

    sendMessage();
}

async function sendMessage() {
    const input = document.getElementById("message-input");

    if (!input) {
        return;
    }

    const message = input.value.trim();

    if (!message) {
        return;
    }

    /*
        IMPORTANT:
        Frontend does ZERO intent detection.

        Booking
        Cancellation
        Rescheduling
        Appointment status
        Hospital questions
        Doctor questions
        Normal conversation

        ALL go to the LLM brain.
    */

    addMessage("user", message);

    input.value = "";
    input.disabled = true;

    try {
        console.log(
            "Sending message to LLM backend:",
            message
        );

        const response = await fetch(
            `${API_BASE_URL}/chat/message`,
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({
                    hospital_id: HOSPITAL_ID,
                    message: message,
                    session_id: getChatSessionId()
                })
            }
        );

        const data = await response.json();

        console.log(
            "LLM backend response:",
            data
        );

        if (!response.ok) {
            addMessage(
                "bot",
                data.detail ||
                data.message ||
                "Something went wrong."
            );

            return;
        }

        if (!data.answer) {
            addMessage(
                "bot",
                "I couldn't generate a response. Please try again."
            );

            return;
        }

        addBotMessageWithFeedback(
            message,
            data.answer,
            data.intent || "conversation"
        );

    } catch (error) {
        console.error(
            "LLM backend request failed:",
            error
        );

        addMessage(
            "bot",
            "I'm having trouble connecting to the hospital assistant. Please try again."
        );

    } finally {
        input.disabled = false;
        input.focus();
    }
}

async function loadDoctorsIntoSelect(
    selectId
) {
    const doctorSelect =
        document.getElementById(
            selectId
        );

    if (!doctorSelect) {
        return;
    }

    doctorSelect.innerHTML =
        `<option value="">
            Loading doctors...
        </option>`;

    try {
        const response =
            await fetch(
                `${API_BASE_URL}/public/doctors?hospital_id=${HOSPITAL_ID}`
            );

        const doctors =
            await response.json();

        if (!response.ok) {
            doctorSelect.innerHTML =
                `<option value="">
                    Unable to load doctors
                </option>`;

            return;
        }

        if (
            !Array.isArray(doctors) ||
            doctors.length === 0
        ) {
            doctorSelect.innerHTML =
                `<option value="">
                    No doctors available
                </option>`;

            return;
        }

        let html =
            `<option value="">
                Select doctor
            </option>`;

        doctors.forEach(
            doctor => {
                let feeText = "";

                if (
                    doctor.consultation_fee !== null &&
                    doctor.consultation_fee !== undefined
                ) {
                    feeText =
                        ` - Rs. ${doctor.consultation_fee}`;
                }

                html += `
                    <option value="${doctor.id}">
                        ${
                            escapeHTML(
                                doctor.name
                            )
                        } - ${
                            escapeHTML(
                                doctor.specialization ||
                                ""
                            )
                        }${feeText}
                    </option>
                `;
            }
        );

        doctorSelect.innerHTML =
            html;

    } catch (error) {
        console.error(
            "Doctor loading failed:",
            error
        );

        doctorSelect.innerHTML =
            `<option value="">
                Unable to connect to server
            </option>`;
    }
}

function loadDoctors() {
    loadDoctorsIntoSelect(
        "booking-doctor"
    );

    loadDoctorsIntoSelect(
        "reschedule-doctor"
    );
}

function hideAllPanels() {
    const panelIds = [
        "appointment-panel",
        "appointment-status-panel",
        "cancel-appointment-panel",
        "reschedule-appointment-panel",
        "support-panel"
    ];

    panelIds.forEach(
        panelId => {
            const panel =
                document.getElementById(
                    panelId
                );

            if (panel) {
                panel.classList.add(
                    "hidden"
                );
            }
        }
    );
}

/*
    These functions are for manual UI forms.

    They do NOT classify chat messages
    and they do NOT generate chatbot replies.

    Normal chat always goes to the LLM.
*/

function openAppointmentForm() {
    hideAllPanels();

    const panel =
        document.getElementById(
            "appointment-panel"
        );

    if (!panel) {
        return;
    }

    panel.classList.remove(
        "hidden"
    );

    setupDateSafety();

    setupBookingFormEvents();

    loadDoctorsIntoSelect(
        "booking-doctor"
    );
}

function openAppointmentStatusForm() {
    hideAllPanels();

    const panel =
        document.getElementById(
            "appointment-status-panel"
        );

    if (!panel) {
        return;
    }

    panel.classList.remove(
        "hidden"
    );

    const message =
        document.getElementById(
            "status-message"
        );

    const confirmation =
        document.getElementById(
            "status-confirmation"
        );

    if (message) {
        message.innerText = "";
        message.className = "";
    }

    if (confirmation) {
        confirmation.innerHTML = "";
    }
}

function openCancelAppointmentForm() {
    hideAllPanels();

    const panel =
        document.getElementById(
            "cancel-appointment-panel"
        );

    if (!panel) {
        return;
    }

    panel.classList.remove(
        "hidden"
    );

    const message =
        document.getElementById(
            "cancel-message"
        );

    const confirmation =
        document.getElementById(
            "cancel-confirmation"
        );

    if (message) {
        message.innerText = "";
        message.className = "";
    }

    if (confirmation) {
        confirmation.innerHTML = "";
    }
}

function openRescheduleAppointmentForm() {
    hideAllPanels();

    const panel =
        document.getElementById(
            "reschedule-appointment-panel"
        );

    if (!panel) {
        return;
    }

    panel.classList.remove(
        "hidden"
    );

    setupDateSafety();

    setupRescheduleFormEvents();

    loadDoctorsIntoSelect(
        "reschedule-doctor"
    );

    const message =
        document.getElementById(
            "reschedule-message"
        );

    const confirmation =
        document.getElementById(
            "reschedule-confirmation"
        );

    const slots =
        document.getElementById(
            "reschedule-available-slots"
        );

    const selectedSlot =
        document.getElementById(
            "reschedule-selected-slot"
        );

    if (message) {
        message.innerText = "";
        message.className = "";
    }

    if (confirmation) {
        confirmation.innerHTML = "";
    }

    if (slots) {
        slots.innerHTML = "";
    }

    if (selectedSlot) {
        selectedSlot.value = "";
    }
}

function openSupportForm(
    questionText = ""
) {
    hideAllPanels();

    const panel =
        document.getElementById(
            "support-panel"
        );

    if (!panel) {
        return;
    }

    panel.classList.remove(
        "hidden"
    );

    const message =
        document.getElementById(
            "lead-message"
        );

    const confirmation =
        document.getElementById(
            "lead-confirmation"
        );

    const question =
        document.getElementById(
            "lead-question"
        );

    if (message) {
        message.innerText = "";
        message.className = "";
    }

    if (confirmation) {
        confirmation.innerHTML = "";
    }

    if (
        questionText &&
        question
    ) {
        question.value =
            questionText;
    }
}

async function checkPublicAppointmentStatus() {
    const appointmentId =
        document.getElementById(
            "status-appointment-id"
        )?.value;

    const patientPhone =
        document.getElementById(
            "status-patient-phone"
        )?.value.trim();

    const statusMessage =
        document.getElementById(
            "status-message"
        );

    const confirmationBox =
        document.getElementById(
            "status-confirmation"
        );

    if (statusMessage) {
        statusMessage.innerText = "";
        statusMessage.className = "";
    }

    if (confirmationBox) {
        confirmationBox.innerHTML = "";
    }

    if (!appointmentId) {
        if (statusMessage) {
            statusMessage.innerText =
                "Please enter appointment ID.";

            statusMessage.className =
                "error-text";
        }

        return;
    }

    if (!patientPhone) {
        if (statusMessage) {
            statusMessage.innerText =
                "Please enter phone number.";

            statusMessage.className =
                "error-text";
        }

        return;
    }

    try {
        const response =
            await fetch(
                `${API_BASE_URL}/public/appointment-status`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            hospital_id:
                                HOSPITAL_ID,

                            appointment_id:
                                Number(
                                    appointmentId
                                ),

                            patient_phone:
                                patientPhone
                        })
                }
            );

        const data =
            await response.json();

        if (!response.ok) {
            if (statusMessage) {
                statusMessage.innerText =
                    data.detail ||
                    "Unable to check appointment status.";

                statusMessage.className =
                    "error-text";
            }

            return;
        }

        if (statusMessage) {
            statusMessage.innerText =
                "Appointment found.";

            statusMessage.className =
                "success-text";
        }

        if (confirmationBox) {
            confirmationBox.innerHTML = `
                <div class="confirmation-card">
                    <h4>Appointment Status</h4>

                    <p>
                        <strong>Appointment ID:</strong>
                        ${escapeHTML(data.appointment_id)}
                    </p>

                    <p>
                        <strong>Patient:</strong>
                        ${escapeHTML(data.patient_name)}
                    </p>

                    <p>
                        <strong>Doctor:</strong>
                        ${escapeHTML(data.doctor_name)}
                    </p>

                    <p>
                        <strong>Date:</strong>
                        ${escapeHTML(data.appointment_date)}
                    </p>

                    <p>
                        <strong>Time:</strong>
                        ${escapeHTML(data.appointment_time)}
                    </p>

                    <p>
                        <strong>Status:</strong>
                        ${escapeHTML(data.status)}
                    </p>

                    <p>
                        <strong>Reason:</strong>
                        ${escapeHTML(
                            data.reason || "-"
                        )}
                    </p>
                </div>
            `;
        }

    } catch (error) {
        console.error(
            "Appointment status request failed:",
            error
        );

        if (statusMessage) {
            statusMessage.innerText =
                "Unable to connect to server.";

            statusMessage.className =
                "error-text";
        }
    }
}

async function submitPatientLead() {
    const name =
        document.getElementById(
            "lead-name"
        )?.value.trim();

    const phone =
        document.getElementById(
            "lead-phone"
        )?.value.trim();

    const question =
        document.getElementById(
            "lead-question"
        )?.value.trim();

    const interestedService =
        document.getElementById(
            "lead-service"
        )?.value.trim();

    const message =
        document.getElementById(
            "lead-message"
        );

    const confirmationBox =
        document.getElementById(
            "lead-confirmation"
        );

    if (message) {
        message.innerText = "";
        message.className = "";
    }

    if (confirmationBox) {
        confirmationBox.innerHTML = "";
    }

    if (!name) {
        if (message) {
            message.innerText =
                "Please enter your name.";

            message.className =
                "error-text";
        }

        return;
    }

    if (!phone) {
        if (message) {
            message.innerText =
                "Please enter your phone number.";

            message.className =
                "error-text";
        }

        return;
    }

    try {
        const response =
            await fetch(
                `${API_BASE_URL}/patient-leads/`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            hospital_id:
                                HOSPITAL_ID,

                            name:
                                name,

                            phone:
                                phone,

                            question:
                                question || null,

                            interested_service:
                                interestedService ||
                                null
                        })
                }
            );

        const data =
            await response.json();

        if (!response.ok) {
            if (message) {
                message.innerText =
                    data.detail ||
                    "Unable to submit support request.";

                message.className =
                    "error-text";
            }

            return;
        }

        if (message) {
            message.innerText =
                "Support request submitted successfully.";

            message.className =
                "success-text";
        }

        if (confirmationBox) {
            confirmationBox.innerHTML = `
                <div class="confirmation-card">
                    <h4>Request Submitted</h4>

                    <p>
                        <strong>Lead ID:</strong>
                        ${escapeHTML(data.id)}
                    </p>

                    <p>
                        <strong>Name:</strong>
                        ${escapeHTML(data.name)}
                    </p>

                    <p>
                        <strong>Phone:</strong>
                        ${escapeHTML(data.phone)}
                    </p>

                    <p>
                        <strong>Status:</strong>
                        ${escapeHTML(data.status)}
                    </p>
                </div>
            `;
        }

        const nameInput =
            document.getElementById(
                "lead-name"
            );

        const phoneInput =
            document.getElementById(
                "lead-phone"
            );

        const questionInput =
            document.getElementById(
                "lead-question"
            );

        const serviceInput =
            document.getElementById(
                "lead-service"
            );

        if (nameInput) {
            nameInput.value = "";
        }

        if (phoneInput) {
            phoneInput.value = "";
        }

        if (questionInput) {
            questionInput.value = "";
        }

        if (serviceInput) {
            serviceInput.value = "";
        }

    } catch (error) {
        console.error(
            "Support request failed:",
            error
        );

        if (message) {
            message.innerText =
                "Unable to connect to server.";

            message.className =
                "error-text";
        }
    }
}

async function loadAvailableSlots() {
    const doctorId =
        document.getElementById(
            "booking-doctor"
        )?.value;

    const appointmentDate =
        document.getElementById(
            "booking-date"
        )?.value;

    const slotsBox =
        document.getElementById(
            "available-slots"
        );

    const bookingMessage =
        document.getElementById(
            "booking-message"
        );

    const selectedSlot =
        document.getElementById(
            "selected-slot"
        );

    const confirmation =
        document.getElementById(
            "appointment-confirmation"
        );

    if (bookingMessage) {
        bookingMessage.innerText = "";
        bookingMessage.className = "";
    }

    if (selectedSlot) {
        selectedSlot.value = "";
    }

    if (confirmation) {
        confirmation.innerHTML = "";
    }

    if (!doctorId) {
        if (slotsBox) {
            slotsBox.innerHTML =
                `<p class="error-text">
                    Please select a doctor.
                </p>`;
        }

        return;
    }

    if (!appointmentDate) {
        if (slotsBox) {
            slotsBox.innerHTML =
                `<p class="error-text">
                    Please select appointment date.
                </p>`;
        }

        return;
    }

    if (isPastDate(appointmentDate)) {
        if (slotsBox) {
            slotsBox.innerHTML =
                `<p class="error-text">
                    You cannot select a past date.
                </p>`;
        }

        setupDateSafety();

        return;
    }

    if (slotsBox) {
        slotsBox.innerHTML =
            "<p>Checking doctor availability...</p>";
    }

    try {
        const response =
            await fetch(
                `${API_BASE_URL}/public/available-slots?hospital_id=${HOSPITAL_ID}&doctor_id=${doctorId}&appointment_date=${appointmentDate}`
            );

        const data =
            await response.json();

        if (!response.ok) {
            const errorText =
                data.detail ||
                "Doctor is not available on this date. Please select another date.";

            if (slotsBox) {
                slotsBox.innerHTML =
                    `<p class="error-text">${
                        escapeHTML(
                            errorText
                        )
                    }</p>`;
            }

            return;
        }

        if (
            !data.available_slots ||
            data.available_slots.length === 0
        ) {
            if (slotsBox) {
                slotsBox.innerHTML =
                    `<p class="error-text">
                        No available slots found for this date.
                        Please select another date.
                    </p>`;
            }

            return;
        }

        let html =
            "<h4>Available Slots</h4>";

        data.available_slots.forEach(
            slot => {
                html += `
                    <button
                        class="slot-btn"
                        onclick="selectSlot('${slot}', this)"
                    >
                        ${escapeHTML(slot)}
                    </button>
                `;
            }
        );

        if (slotsBox) {
            slotsBox.innerHTML =
                html;
        }

    } catch (error) {
        console.error(
            "Slot loading failed:",
            error
        );

        if (slotsBox) {
            slotsBox.innerHTML =
                `<p class="error-text">
                    Unable to connect to server.
                </p>`;
        }
    }
}

function selectSlot(
    slot,
    buttonElement
) {
    const selectedSlot =
        document.getElementById(
            "selected-slot"
        );

    const confirmation =
        document.getElementById(
            "appointment-confirmation"
        );

    const buttons =
        document.querySelectorAll(
            "#available-slots .slot-btn"
        );

    if (selectedSlot) {
        selectedSlot.value =
            slot;
    }

    if (confirmation) {
        confirmation.innerHTML = "";
    }

    buttons.forEach(
        button => {
            button.classList.remove(
                "selected"
            );
        }
    );

    if (buttonElement) {
        buttonElement.classList.add(
            "selected"
        );
    }
}

async function loadRescheduleAvailableSlots() {
    const appointmentId =
        document.getElementById(
            "reschedule-appointment-id"
        )?.value;

    const patientPhone =
        document.getElementById(
            "reschedule-patient-phone"
        )?.value.trim();

    const doctorId =
        document.getElementById(
            "reschedule-doctor"
        )?.value;

    const appointmentDate =
        document.getElementById(
            "reschedule-date"
        )?.value;

    const slotsBox =
        document.getElementById(
            "reschedule-available-slots"
        );

    const message =
        document.getElementById(
            "reschedule-message"
        );

    const selectedSlot =
        document.getElementById(
            "reschedule-selected-slot"
        );

    const confirmation =
        document.getElementById(
            "reschedule-confirmation"
        );

    if (message) {
        message.innerText = "";
        message.className = "";
    }

    if (selectedSlot) {
        selectedSlot.value = "";
    }

    if (confirmation) {
        confirmation.innerHTML = "";
    }

    if (!appointmentId) {
        if (message) {
            message.innerText =
                "Please enter appointment ID.";

            message.className =
                "error-text";
        }

        return;
    }

    if (!patientPhone) {
        if (message) {
            message.innerText =
                "Please enter phone number.";

            message.className =
                "error-text";
        }

        return;
    }

    if (!doctorId) {
        if (message) {
            message.innerText =
                "Please select a doctor.";

            message.className =
                "error-text";
        }

        return;
    }

    if (!appointmentDate) {
        if (message) {
            message.innerText =
                "Please select new appointment date.";

            message.className =
                "error-text";
        }

        return;
    }

    if (isPastDate(appointmentDate)) {
        if (message) {
            message.innerText =
                "You cannot select a past date.";

            message.className =
                "error-text";
        }

        setupDateSafety();

        return;
    }

    if (slotsBox) {
        slotsBox.innerHTML =
            "<p>Checking availability...</p>";
    }

    try {
        const response =
            await fetch(
                `${API_BASE_URL}/public/available-slots?hospital_id=${HOSPITAL_ID}&doctor_id=${doctorId}&appointment_date=${appointmentDate}`
            );

        const data =
            await response.json();

        if (!response.ok) {
            const errorText =
                data.detail ||
                "Doctor is not available on this date.";

            if (slotsBox) {
                slotsBox.innerHTML =
                    `<p class="error-text">${
                        escapeHTML(
                            errorText
                        )
                    }</p>`;
            }

            return;
        }

        if (
            !data.available_slots ||
            data.available_slots.length === 0
        ) {
            if (slotsBox) {
                slotsBox.innerHTML =
                    `<p class="error-text">
                        No available slots found.
                    </p>`;
            }

            return;
        }

        let html =
            "<h4>New Available Slots</h4>";

        data.available_slots.forEach(
            slot => {
                html += `
                    <button
                        class="slot-btn"
                        onclick="selectRescheduleSlot('${slot}', this)"
                    >
                        ${escapeHTML(slot)}
                    </button>
                `;
            }
        );

        if (slotsBox) {
            slotsBox.innerHTML =
                html;
        }

    } catch (error) {
        console.error(
            "Reschedule slot loading failed:",
            error
        );

        if (slotsBox) {
            slotsBox.innerHTML =
                `<p class="error-text">
                    Unable to connect to server.
                </p>`;
        }
    }
}

function selectRescheduleSlot(
    slot,
    buttonElement
) {
    const selectedSlot =
        document.getElementById(
            "reschedule-selected-slot"
        );

    const confirmation =
        document.getElementById(
            "reschedule-confirmation"
        );

    const buttons =
        document.querySelectorAll(
            "#reschedule-available-slots .slot-btn"
        );

    if (selectedSlot) {
        selectedSlot.value =
            slot;
    }

    if (confirmation) {
        confirmation.innerHTML =
            "";
    }

    buttons.forEach(
        button => {
            button.classList.remove(
                "selected"
            );
        }
    );

    if (buttonElement) {
        buttonElement.classList.add(
            "selected"
        );
    }
}

async function bookAppointment() {
    const doctorId =
        document.getElementById(
            "booking-doctor"
        )?.value;

    const appointmentDate =
        document.getElementById(
            "booking-date"
        )?.value;

    const selectedSlot =
        document.getElementById(
            "selected-slot"
        )?.value;

    const patientName =
        document.getElementById(
            "patient-name"
        )?.value.trim();

    const patientPhone =
        document.getElementById(
            "patient-phone"
        )?.value.trim();

    const patientEmail =
        document.getElementById(
            "patient-email"
        )?.value.trim();

    const reason =
        document.getElementById(
            "appointment-reason"
        )?.value.trim();

    const bookingMessage =
        document.getElementById(
            "booking-message"
        );

    const confirmationBox =
        document.getElementById(
            "appointment-confirmation"
        );

    if (bookingMessage) {
        bookingMessage.innerText = "";
        bookingMessage.className = "";
    }

    if (confirmationBox) {
        confirmationBox.innerHTML = "";
    }

    if (!doctorId) {
        if (bookingMessage) {
            bookingMessage.innerText =
                "Please select a doctor.";

            bookingMessage.className =
                "error-text";
        }

        return;
    }

    if (!appointmentDate) {
        if (bookingMessage) {
            bookingMessage.innerText =
                "Please select appointment date.";

            bookingMessage.className =
                "error-text";
        }

        return;
    }

    if (isPastDate(appointmentDate)) {
        if (bookingMessage) {
            bookingMessage.innerText =
                "You cannot book an appointment for a past date.";

            bookingMessage.className =
                "error-text";
        }

        setupDateSafety();

        return;
    }

    if (!selectedSlot) {
        if (bookingMessage) {
            bookingMessage.innerText =
                "Please select an available slot first.";

            bookingMessage.className =
                "error-text";
        }

        return;
    }

    if (!patientName) {
        if (bookingMessage) {
            bookingMessage.innerText =
                "Please enter patient name.";

            bookingMessage.className =
                "error-text";
        }

        return;
    }

    if (!patientPhone) {
        if (bookingMessage) {
            bookingMessage.innerText =
                "Please enter phone number.";

            bookingMessage.className =
                "error-text";
        }

        return;
    }

    try {
        const response =
            await fetch(
                `${API_BASE_URL}/public/book-appointment`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            hospital_id:
                                HOSPITAL_ID,

                            doctor_id:
                                Number(
                                    doctorId
                                ),

                            patient_name:
                                patientName,

                            patient_phone:
                                patientPhone,

                            patient_email:
                                patientEmail ||
                                null,

                            appointment_date:
                                appointmentDate,

                            appointment_time:
                                selectedSlot,

                            reason:
                                reason || null
                        })
                }
            );

        const data =
            await response.json();

        if (!response.ok) {
            if (bookingMessage) {
                bookingMessage.innerText =
                    data.detail ||
                    "Appointment booking failed.";

                bookingMessage.className =
                    "error-text";
            }

            return;
        }

        if (bookingMessage) {
            bookingMessage.innerText =
                "Appointment booked successfully.";

            bookingMessage.className =
                "success-text";
        }

        if (confirmationBox) {
            confirmationBox.innerHTML = `
                <div class="confirmation-card">
                    <h4>Appointment Confirmed</h4>

                    <p>
                        <strong>Appointment ID:</strong>
                        ${escapeHTML(data.appointment_id)}
                    </p>

                    <p>
                        <strong>Patient ID:</strong>
                        ${escapeHTML(data.patient_id)}
                    </p>

                    <p>
                        <strong>Doctor:</strong>
                        ${escapeHTML(data.doctor_name)}
                    </p>

                    <p>
                        <strong>Date:</strong>
                        ${escapeHTML(data.appointment_date)}
                    </p>

                    <p>
                        <strong>Time:</strong>
                        ${escapeHTML(data.appointment_time)}
                    </p>

                    <p>
                        <strong>Status:</strong>
                        ${escapeHTML(data.status)}
                    </p>
                </div>
            `;
        }

        const patientNameInput =
            document.getElementById(
                "patient-name"
            );

        const patientPhoneInput =
            document.getElementById(
                "patient-phone"
            );

        const patientEmailInput =
            document.getElementById(
                "patient-email"
            );

        const reasonInput =
            document.getElementById(
                "appointment-reason"
            );

        const selectedSlotInput =
            document.getElementById(
                "selected-slot"
            );

        const slots =
            document.getElementById(
                "available-slots"
            );

        if (patientNameInput) {
            patientNameInput.value = "";
        }

        if (patientPhoneInput) {
            patientPhoneInput.value = "";
        }

        if (patientEmailInput) {
            patientEmailInput.value = "";
        }

        if (reasonInput) {
            reasonInput.value = "";
        }

        if (selectedSlotInput) {
            selectedSlotInput.value = "";
        }

        if (slots) {
            slots.innerHTML = "";
        }

        setupDateSafety();

    } catch (error) {
        console.error(
            "Appointment booking failed:",
            error
        );

        if (bookingMessage) {
            bookingMessage.innerText =
                "Unable to connect to server.";

            bookingMessage.className =
                "error-text";
        }
    }
}

async function cancelPublicAppointment() {
    const appointmentId =
        document.getElementById(
            "cancel-appointment-id"
        )?.value;

    const patientPhone =
        document.getElementById(
            "cancel-patient-phone"
        )?.value.trim();

    const cancelMessage =
        document.getElementById(
            "cancel-message"
        );

    const confirmationBox =
        document.getElementById(
            "cancel-confirmation"
        );

    if (cancelMessage) {
        cancelMessage.innerText = "";
        cancelMessage.className = "";
    }

    if (confirmationBox) {
        confirmationBox.innerHTML = "";
    }

    if (!appointmentId) {
        if (cancelMessage) {
            cancelMessage.innerText =
                "Please enter appointment ID.";

            cancelMessage.className =
                "error-text";
        }

        return;
    }

    if (!patientPhone) {
        if (cancelMessage) {
            cancelMessage.innerText =
                "Please enter phone number.";

            cancelMessage.className =
                "error-text";
        }

        return;
    }

    try {
        const response =
            await fetch(
                `${API_BASE_URL}/public/cancel-appointment`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            hospital_id:
                                HOSPITAL_ID,

                            appointment_id:
                                Number(
                                    appointmentId
                                ),

                            patient_phone:
                                patientPhone
                        })
                }
            );

        const data =
            await response.json();

        if (!response.ok) {
            if (cancelMessage) {
                cancelMessage.innerText =
                    data.detail ||
                    "Appointment cancellation failed.";

                cancelMessage.className =
                    "error-text";
            }

            return;
        }

        if (cancelMessage) {
            cancelMessage.innerText =
                "Appointment cancelled successfully.";

            cancelMessage.className =
                "success-text";
        }

        if (confirmationBox) {
            confirmationBox.innerHTML = `
                <div class="confirmation-card">
                    <h4>Appointment Cancelled</h4>

                    <p>
                        <strong>Appointment ID:</strong>
                        ${escapeHTML(data.appointment_id)}
                    </p>

                    <p>
                        <strong>Doctor ID:</strong>
                        ${escapeHTML(data.doctor_id)}
                    </p>

                    <p>
                        <strong>Date:</strong>
                        ${escapeHTML(data.appointment_date)}
                    </p>

                    <p>
                        <strong>Time:</strong>
                        ${escapeHTML(data.appointment_time)}
                    </p>

                    <p>
                        <strong>Status:</strong>
                        ${escapeHTML(data.status)}
                    </p>
                </div>
            `;
        }

        const appointmentInput =
            document.getElementById(
                "cancel-appointment-id"
            );

        const phoneInput =
            document.getElementById(
                "cancel-patient-phone"
            );

        if (appointmentInput) {
            appointmentInput.value = "";
        }

        if (phoneInput) {
            phoneInput.value = "";
        }

    } catch (error) {
        console.error(
            "Cancellation failed:",
            error
        );

        if (cancelMessage) {
            cancelMessage.innerText =
                "Unable to connect to server.";

            cancelMessage.className =
                "error-text";
        }
    }
}

async function reschedulePublicAppointment() {
    const appointmentId =
        document.getElementById(
            "reschedule-appointment-id"
        )?.value;

    const patientPhone =
        document.getElementById(
            "reschedule-patient-phone"
        )?.value.trim();

    const doctorId =
        document.getElementById(
            "reschedule-doctor"
        )?.value;

    const appointmentDate =
        document.getElementById(
            "reschedule-date"
        )?.value;

    const selectedSlot =
        document.getElementById(
            "reschedule-selected-slot"
        )?.value;

    const message =
        document.getElementById(
            "reschedule-message"
        );

    const confirmationBox =
        document.getElementById(
            "reschedule-confirmation"
        );

    if (message) {
        message.innerText = "";
        message.className = "";
    }

    if (confirmationBox) {
        confirmationBox.innerHTML = "";
    }

    if (!appointmentId) {
        if (message) {
            message.innerText =
                "Please enter appointment ID.";

            message.className =
                "error-text";
        }

        return;
    }

    if (!patientPhone) {
        if (message) {
            message.innerText =
                "Please enter phone number.";

            message.className =
                "error-text";
        }

        return;
    }

    if (!doctorId) {
        if (message) {
            message.innerText =
                "Please select a doctor.";

            message.className =
                "error-text";
        }

        return;
    }

    if (!appointmentDate) {
        if (message) {
            message.innerText =
                "Please select new appointment date.";

            message.className =
                "error-text";
        }

        return;
    }

    if (isPastDate(appointmentDate)) {
        if (message) {
            message.innerText =
                "You cannot reschedule to a past date.";

            message.className =
                "error-text";
        }

        setupDateSafety();

        return;
    }

    if (!selectedSlot) {
        if (message) {
            message.innerText =
                "Please select a new available slot first.";

            message.className =
                "error-text";
        }

        return;
    }

    try {
        const response =
            await fetch(
                `${API_BASE_URL}/public/reschedule-appointment`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            hospital_id:
                                HOSPITAL_ID,

                            appointment_id:
                                Number(
                                    appointmentId
                                ),

                            patient_phone:
                                patientPhone,

                            doctor_id:
                                Number(
                                    doctorId
                                ),

                            appointment_date:
                                appointmentDate,

                            appointment_time:
                                selectedSlot
                        })
                }
            );

        const data =
            await response.json();

        if (!response.ok) {
            if (message) {
                message.innerText =
                    data.detail ||
                    "Appointment reschedule failed.";

                message.className =
                    "error-text";
            }

            return;
        }

        if (message) {
            message.innerText =
                "Appointment rescheduled successfully.";

            message.className =
                "success-text";
        }

        if (confirmationBox) {
            confirmationBox.innerHTML = `
                <div class="confirmation-card">
                    <h4>Appointment Rescheduled</h4>

                    <p>
                        <strong>Appointment ID:</strong>
                        ${escapeHTML(data.appointment_id)}
                    </p>

                    <p>
                        <strong>Doctor:</strong>
                        ${escapeHTML(data.doctor_name)}
                    </p>

                    <p>
                        <strong>New Date:</strong>
                        ${escapeHTML(data.appointment_date)}
                    </p>

                    <p>
                        <strong>New Time:</strong>
                        ${escapeHTML(data.appointment_time)}
                    </p>

                    <p>
                        <strong>Status:</strong>
                        ${escapeHTML(data.status)}
                    </p>
                </div>
            `;
        }

        const appointmentInput =
            document.getElementById(
                "reschedule-appointment-id"
            );

        const phoneInput =
            document.getElementById(
                "reschedule-patient-phone"
            );

        const doctorInput =
            document.getElementById(
                "reschedule-doctor"
            );

        const selectedSlotInput =
            document.getElementById(
                "reschedule-selected-slot"
            );

        const slots =
            document.getElementById(
                "reschedule-available-slots"
            );

        if (appointmentInput) {
            appointmentInput.value = "";
        }

        if (phoneInput) {
            phoneInput.value = "";
        }

        if (doctorInput) {
            doctorInput.value = "";
        }

        if (selectedSlotInput) {
            selectedSlotInput.value = "";
        }

        if (slots) {
            slots.innerHTML = "";
        }

        setupDateSafety();

    } catch (error) {
        console.error(
            "Rescheduling failed:",
            error
        );

        if (message) {
            message.innerText =
                "Unable to connect to server.";

            message.className =
                "error-text";
        }
    }
}

/*
    Expose functions for buttons
    that may be called from HTML.
*/

window.sendMessage =
    sendMessage;

window.handleEnter =
    handleEnter;

window.sendQuickMessage =
    sendQuickMessage;

window.openAppointmentForm =
    openAppointmentForm;

window.openAppointmentStatusForm =
    openAppointmentStatusForm;

window.openCancelAppointmentForm =
    openCancelAppointmentForm;

window.openRescheduleAppointmentForm =
    openRescheduleAppointmentForm;

window.openSupportForm =
    openSupportForm;

window.checkPublicAppointmentStatus =
    checkPublicAppointmentStatus;

window.submitPatientLead =
    submitPatientLead;

window.loadAvailableSlots =
    loadAvailableSlots;

window.selectSlot =
    selectSlot;

window.loadRescheduleAvailableSlots =
    loadRescheduleAvailableSlots;

window.selectRescheduleSlot =
    selectRescheduleSlot;

window.bookAppointment =
    bookAppointment;

window.cancelPublicAppointment =
    cancelPublicAppointment;

window.reschedulePublicAppointment =
    reschedulePublicAppointment;


/*
    Application startup
*/

window.addEventListener(
    "load",
    function () {
        getChatSessionId();

        setupDateSafety();

        setupBookingFormEvents();

        setupRescheduleFormEvents();

        loadDoctors();

        const input =
            document.getElementById(
                "message-input"
            );

        if (input) {
            input.focus();
        }
    }
);