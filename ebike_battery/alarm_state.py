"""Restart semantics for the persistent alarm; no I/O or MQTT dependencies."""


def restore_state(payload):
    # A pending alarm lost its timer on restart. Trigger conservatively rather
    # than silently disarming or granting a fresh entry period.
    if payload == "pending":
        return "triggered"
    if payload in ("disarmed", "armed_away", "armed_home", "armed_night", "triggered"):
        return payload
    return None
