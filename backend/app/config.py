from datetime import datetime

# dataset snapshot is the ONLY valid "now" for time based questions

REFERENCE_NOW = datetime(2026, 8, 16, 11, 0)

# mock accounts

USERS = {
    "aisha":{"password": "parcelpilot", "role":"support_agent", "name": "Aisha"},
    "rohan":{"password": "parcelpilot", "role":"maanger", "name":"Rohan"},
    "neha": {"password": "parcelpilot", "role":"admin", "name": "Neha"},
}
ROLES = ("support_agent", "manager", "admin")