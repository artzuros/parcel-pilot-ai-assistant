from app.agent.args_models import validate_args

def test_unknown_tool_passthrough():
    args, err = validate_args("get_tickets", {"ticket_id": "TKT-501"})
    assert err is None and args == {"ticket_id": "TKT-501"}

def test_coerces_and_preserves_extras():
    args, err = validate_args("propose_credit",
                              {"order_id": "ORD-2002", "amount_inr": "300",
                               "reason": "missed window", "issued_by": "aisha"})
    assert err is None
    assert args["amount_inr"] == 300          # coerced to int
    assert args["issued_by"] == "aisha"       # extra preserved

def test_missing_required_field_rejected():
    args, err = validate_args("escalate_ticket", {"reason": "upset"})
    assert err is not None and args is None

def test_update_field_whitelist():
    _, err = validate_args("update_ticket",
                           {"ticket_id": "TKT-504", "field": "owner", "value": "x"})
    assert err is not None
