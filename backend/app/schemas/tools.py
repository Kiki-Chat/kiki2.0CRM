"""Request schemas for the ElevenLabs tool webhooks.

Shapes mirror hk_tools_payload_reference.md. Every tool call carries the same
underscore-prefixed system fields plus its own parameters. No business logic
lives here — these are just the typed contracts for the Phase 2 handlers.
"""

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ToolRequestBase(BaseModel):
    # Tolerate extra/unknown keys ElevenLabs may add; map _-prefixed system fields.
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    tool_name: str | None = Field(default=None, alias="_toolName")
    caller_number: str | None = Field(default=None, alias="_callerNumber")
    conversation_id: str | None = Field(default=None, alias="_conversationId")
    agent_id: str | None = Field(default=None, alias="_agentId")
    call_sid: str | None = Field(default=None, alias="_callSid")


class AdditionalField(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")
    question: str | None = None
    answer: str | None = None


# 1. identifyCustomer
class IdentifyCustomerRequest(ToolRequestBase):
    phone_number: str | None = Field(default=None, alias="phoneNumber")
    customer_number: str | None = Field(default=None, alias="customerNumber")
    address: str | None = None
    last_name: str | None = Field(default=None, alias="lastName")


# 2. updateCustomerData
class UpdateCustomerDataRequest(ToolRequestBase):
    customer_id: str | None = Field(default=None, alias="customerId")
    address: str | None = None
    email: str | None = None
    phone: str | None = None
    name: str | None = None


# 3. createInquiry
class CreateInquiryRequest(ToolRequestBase):
    inquiry_title: str | None = Field(default=None, alias="inquiryTitle")
    message: str | None = None
    name: str | None = None
    phone: str | None = None
    address: str | None = None
    email: str | None = None
    urgent: bool | None = None
    callback_requested: bool | None = Field(default=None, alias="callbackRequested")
    additional_fields: list[AdditionalField] | None = Field(
        default=None, alias="additionalFields"
    )


# 4. getAvailableAppointments
class GetAvailableAppointmentsRequest(ToolRequestBase):
    days: int | None = None
    duration_minutes: int | None = Field(default=None, alias="durationMinutes")
    preferred_date: str | None = Field(default=None, alias="preferredDate")
    preferred_time: str | None = Field(default=None, alias="preferredTime")
    # Routing signal (optional, additive). `category` = the appointment TYPE
    # (drives duration); `topic` = the call's domain/problem (drives WHO is
    # competent). When either is present, slots are offered per-competent-employee
    # and filtered to that person's real availability; absent → org-wide behaviour.
    category: str | None = None
    topic: str | None = None


# 5. bookAppointment
class BookAppointmentRequest(ToolRequestBase):
    date: str | None = None
    time: str | None = None
    name: str | None = None
    phone: str | None = None
    address: str | None = None
    description: str | None = None
    inquiry_title: str | None = Field(default=None, alias="inquiryTitle")
    email: str | None = None
    category: str | None = None
    additional_fields: list[AdditionalField] | None = Field(
        default=None, alias="additionalFields"
    )


# 6. cancelAppointment
class CancelAppointmentRequest(ToolRequestBase):
    phone_number: str | None = Field(default=None, alias="phoneNumber")
    name: str | None = None
    date: str | None = None  # appointment date, used to confirm a name-based match
    reason: str | None = None


# 7. changeAppointment
class ChangeAppointmentRequest(ToolRequestBase):
    phone_number: str | None = Field(default=None, alias="phoneNumber")
    name: str | None = None
    new_date: str | None = Field(default=None, alias="newDate")
    new_time: str | None = Field(default=None, alias="newTime")
    reason: str | None = None
    # Date of the EXISTING appointment the customer wants to move. Used to pick
    # the right one when the customer has several upcoming appointments (the agent
    # asks for it, mirroring the cancel flow). Optional when there's only one.
    appointment_date: str | None = Field(default=None, alias="appointmentDate")
    # TRUE  → customer wants the new time INSTEAD of the old (abandons the old slot).
    # FALSE/None → keep the original as a fallback; never auto-cancel it.
    replace_original: bool | None = Field(default=None, alias="replaceOriginal")


# 8. searchCustomerInquiries
class SearchCustomerInquiriesRequest(ToolRequestBase):
    customer_id: str | None = Field(default=None, alias="customerId")
    status: str | None = None
    date_from: str | None = Field(default=None, alias="dateFrom")
    date_to: str | None = Field(default=None, alias="dateTo")
    sort_order: str | None = Field(default=None, alias="sortOrder")


# 9. queryKnowledgeBase
class QueryKnowledgeBaseRequest(ToolRequestBase):
    question: str | None = None


# 10. transferCall
class TransferCallRequest(ToolRequestBase):
    # The ElevenLabs tool param is `emergency`, but the German prompt has historically
    # said "notfall=true" / "grund". Accept BOTH spellings so the emergency flag can
    # never be silently lost (→ a Notfall misrouted to the staff line). With
    # populate_by_name=True (ToolRequestBase), the field name still works too.
    emergency: bool | None = Field(
        default=None, validation_alias=AliasChoices("emergency", "notfall")
    )
    reason: str | None = Field(
        default=None, validation_alias=AliasChoices("reason", "grund")
    )


# 11. draftCostEstimate
class DraftCostEstimateRequest(ToolRequestBase):
    customer_id: str | None = Field(default=None, alias="customerId")
    inquiry_id: str | None = Field(default=None, alias="inquiryId")
    subject: str | None = None
    positions: list[dict] | None = None
    notes: str | None = None


# 12. sendCostEstimate (hk_sendKVA) — email an EXISTING KVA to the customer.
# Resolution priority: costEstimateId → number → the customer's most recent KVA.
class SendCostEstimateRequest(ToolRequestBase):
    cost_estimate_id: str | None = Field(default=None, alias="costEstimateId")
    number: str | None = None
    customer_id: str | None = Field(default=None, alias="customerId")


# Conversation Initiation Webhook (fires when the call connects, before the agent
# speaks). ElevenLabs sends Twilio-style fields.
class ConversationInitRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    caller_id: str | None = None
    agent_id: str | None = None
    called_number: str | None = None
    call_sid: str | None = None
