from pydantic import BaseModel, ConfigDict, ValidationError

# extra="allow" is deliberate: unknown fields pass through untouched, so
# validation can only ever REJECT clearly-broken calls, never break a
# working one. Declared fields get type coercion (e.g. "300" -> 300).

class EscalateArgs(BaseModel):
    model_config = ConfigDict(extra="allow")
    ticket_id: str

class UpdateTicketArgs(BaseModel):
    model_config = ConfigDict(extra="allow")
    ticket_id: str
    field: str | None = None
    value: str | None = None

class FollowupTaskArgs(BaseModel):
    model_config = ConfigDict(extra="allow")
    ticket_id: str
    description: str

class ProposeCreditArgs(BaseModel):
    model_config = ConfigDict(extra="allow")
    order_id: str
    amount_inr: int | None = None

_MODELS = {
    "escalate_ticket": EscalateArgs,
    "update_ticket": UpdateTicketArgs,
    "create_followup_task": FollowupTaskArgs,
    "propose_credit": ProposeCreditArgs,
}

def validate_args(name, args):
    """Returns (args, error). error is None on success or when the tool is
    not validated (read-only tools)."""
    model = _MODELS.get(name)
    if model is None:
        return args, None
    try:
        validated = model.model_validate(args)
    except ValidationError as e:
        return None, str(e.errors()[:2])
    if name == "update_ticket" and validated.field is not None \
            and validated.field not in ("status", "assigned_to"):
        return None, f"field must be 'status' or 'assigned_to', got {validated.field!r}"
    return validated.model_dump(), None
