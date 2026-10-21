"""Expo Push Notifications Service.

Sends push notifications through Expo's push API (the project uses
Expo SDK instead of FCM directly).

The send_notification call returns a structured result that includes
`dead_tokens` — tokens Expo says are no longer registered to a device.
Callers should pass these to `clear_dead_push_tokens` so they get
nulled out on the User row; otherwise every future push burns Expo
quota and floods logs trying to deliver to dead devices.
"""

import logging
from typing import Any

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

logger = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
EXPO_RECEIPTS_URL = "https://exp.host/--/api/v2/push/getReceipts"

# Per-ticket error codes Expo returns. Only `DeviceNotRegistered`
# means the token itself is dead — the other codes are transient
# (rate limit), our bug (oversized message), or Expo-side auth
# (their FCM/APNs credentials) and shouldn't trigger token deletion.
_DEAD_TOKEN_ERROR = "DeviceNotRegistered"


class ExpoPushNotificationService:
    """Service for sending push notifications via Expo."""

    @staticmethod
    async def send_notification(
        push_tokens: list[str],
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        priority: str = "default",
        sound: str = "default",
        badge: int | None = None,
        category_id: str | None = None,
    ) -> dict[str, Any]:
        """Send push notification to one or more Expo push tokens.

        Returns a dict with:
          - status: "success" | "error"
          - data: the raw Expo response (for "success")
          - message: error description (for "error")
          - dead_tokens: list[str] — tokens Expo says are
            DeviceNotRegistered. Callers should clear these from the
            User table via `clear_dead_push_tokens`.
        """

        # Validate tokens
        valid_tokens = [
            token
            for token in push_tokens
            if token and token.startswith("ExponentPushToken[")
        ]

        if not valid_tokens:
            logger.warning("No valid Expo push tokens provided")
            return {
                "status": "error",
                "message": "No valid tokens",
                "ok_tokens": [],
                "dead_tokens": [],
                "ticket_ids": {},
            }

        # Build notification payload
        messages = []
        for token in valid_tokens:
            message = {
                "to": token,
                "title": title,
                "body": body,
                "priority": priority,
                "sound": sound,
            }

            if data:
                message["data"] = data

            if badge is not None:
                message["badge"] = badge

            # Notification category (action buttons) — the mobile app
            # registers matching categories via setNotificationCategoryAsync
            # (e.g. session_expiring → "Extend 30 min").
            if category_id is not None:
                message["categoryId"] = category_id

            messages.append(message)

        # Send to Expo
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    EXPO_PUSH_URL,
                    json=messages,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    timeout=10.0,
                )

                response.raise_for_status()
                result = response.json()

                ok_tokens, dead_tokens, ticket_ids = _map_tickets(valid_tokens, result)
                if dead_tokens:
                    logger.info(
                        "expo_push_dead_tokens_detected",
                        extra={"count": len(dead_tokens)},
                    )

                logger.info("Sent %d notifications via Expo", len(messages))
                return {
                    "status": "success",
                    "data": result,
                    "ok_tokens": ok_tokens,
                    "dead_tokens": dead_tokens,
                    "ticket_ids": ticket_ids,
                }

        except httpx.HTTPError as e:
            logger.exception("Failed to send Expo push notification")
            return {
                "status": "error",
                "message": str(e),
                "ok_tokens": [],
                "dead_tokens": [],
                "ticket_ids": {},
            }
        except Exception as e:
            logger.exception("Unexpected error sending notification")
            return {
                "status": "error",
                "message": str(e),
                "ok_tokens": [],
                "dead_tokens": [],
                "ticket_ids": {},
            }

    @staticmethod
    async def get_receipts(ticket_ids: list[str]) -> dict[str, Any]:
        """Fetch delivery RECEIPTS for Expo ticket ids — the real APNs/FCM
        handoff outcome, available a short while after the ticket. Returns
        ``{"status": "success"|"error", "receipts": {ticket_id: {"ok": bool,
        "dead": bool, "error": str|None}}}``. A missing ticket id in the result
        means "no receipt yet" (caller keeps waiting)."""
        if not ticket_ids:
            return {"status": "success", "receipts": {}}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    EXPO_RECEIPTS_URL,
                    json={"ids": ticket_ids},
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json().get("data", {})
        except httpx.HTTPError as e:
            logger.error("Failed to fetch Expo receipts: %s", e)
            return {"status": "error", "receipts": {}}
        except Exception as e:
            logger.error("Unexpected error fetching Expo receipts: %s", e)
            return {"status": "error", "receipts": {}}

        receipts: dict[str, dict[str, Any]] = {}
        if isinstance(data, dict):
            for ticket_id, receipt in data.items():
                if not isinstance(receipt, dict):
                    continue
                status = receipt.get("status")
                if status == "ok":
                    receipts[ticket_id] = {"ok": True, "dead": False, "error": None}
                elif status == "error":
                    details = receipt.get("details") or {}
                    err = details.get("error")
                    receipts[ticket_id] = {
                        "ok": False,
                        "dead": err == _DEAD_TOKEN_ERROR,
                        "error": err or receipt.get("message"),
                    }
        return {"status": "success", "receipts": receipts}


def _map_tickets(
    sent_tokens: list[str], response: dict[str, Any]
) -> tuple[list[str], list[str], dict[str, str]]:
    """Map each ticket back to the token it was sent for.

    Returns `(ok_tokens, dead_tokens, ticket_ids)`:
      - ok_tokens:   tokens whose ticket `status == "ok"` — the ONLY ones Expo
                     actually accepted. A push "delivered" claim must be gated on
                     this, never on "the HTTP call returned" (a ticket can be an
                     error while the batch HTTP call is 200).
      - dead_tokens: tokens whose ticket errored with DeviceNotRegistered.
      - ticket_ids:  token -> Expo ticket id, for the accepted tickets — needed to
                     later fetch delivery RECEIPTS (the real APNs/FCM outcome).

    Expo guarantees order: `response.data[i]` is the ticket for `sent_tokens[i]`.
    If the shape doesn't match (defensive guard for a future Expo API change),
    return empties rather than guessing.
    """
    tickets = response.get("data")
    if not isinstance(tickets, list) or len(tickets) != len(sent_tokens):
        return [], [], {}
    ok: list[str] = []
    dead: list[str] = []
    ids: dict[str, str] = {}
    # strict=True belts-and-suspenders the explicit length check above.
    for token, ticket in zip(sent_tokens, tickets, strict=True):
        if not isinstance(ticket, dict):
            continue
        status = ticket.get("status")
        if status == "ok":
            ok.append(token)
            ticket_id = ticket.get("id")
            if isinstance(ticket_id, str):
                ids[token] = ticket_id
        elif status == "error":
            details = ticket.get("details") or {}
            if details.get("error") == _DEAD_TOKEN_ERROR:
                dead.append(token)
    return ok, dead, ids


def _extract_dead_tokens(sent_tokens: list[str], response: dict[str, Any]) -> list[str]:
    """Back-compat thin wrapper over `_map_tickets`."""
    return _map_tickets(sent_tokens, response)[1]


async def clear_dead_push_tokens(db: AsyncSession, dead_tokens: list[str]) -> int:
    """Null out `expo_push_token` for every User row whose token Expo
    flagged as DeviceNotRegistered. Returns the number of rows updated.

    Safe to call with an empty list — short-circuits without a DB
    round-trip.

    Does NOT commit. Callers control transaction lifetime — if you call
    this mid-loop alongside other DB mutations (e.g. session_tasks
    dispatching alerts), an internal commit here would persist partial
    loop state and break atomicity. The cascade fan-out and the alert
    dispatch both commit when their unit of work completes.
    """
    if not dead_tokens:
        return 0
    stmt = (
        update(User)
        .where(User.expo_push_token.in_(dead_tokens))
        .values(expo_push_token=None)
    )
    result = await db.execute(stmt)
    cleared = result.rowcount or 0
    if cleared:
        logger.info(
            "expo_push_tokens_cleared",
            extra={"count": cleared},
        )
    return cleared


# Create singleton instance
expo_push_service = ExpoPushNotificationService()
