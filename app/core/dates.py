from datetime import date as date_type, datetime, timezone

from fastapi import HTTPException


def resolve_today(client_date: date_type | None) -> date_type:
    """The user's "today": the device-local date the client sends.

    Food logs are stored under the device-local date, but insights used the
    server's date (UTC on Render), so for anyone away from UTC the 7-day window,
    the "today so far" numbers and the daily cache were off by a day for part
    of every day. Accept the client's date only within a day of the server's
    UTC date, which covers every real timezone (UTC-12 to UTC+14) and rules
    out arbitrary dates. Older clients send nothing and get the UTC date.
    """
    server_today = datetime.now(timezone.utc).date()
    if client_date is None:
        return server_today
    if abs((client_date - server_today).days) > 1:
        raise HTTPException(status_code=422, detail="date must be the device's current date")
    return client_date
