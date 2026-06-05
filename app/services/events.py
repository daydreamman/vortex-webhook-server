"""In-memory event history and SSE subscriber coordination."""

import logging
from dataclasses import dataclass
from queue import Queue
from typing import Any

from app.state import (
    SUBSCRIBERS,
    add_subscriber,
    get_event_history,
    normalize_token,
    register_token,
    remove_subscriber,
)


@dataclass
class EventSubscription:
    """Represents one active Server-Sent Events subscription."""

    subscriber: dict[str, Any]

    @property
    def queue(self) -> Queue:
        """Return the queue backing this subscription."""
        return self.subscriber["queue"]

    def close(self) -> None:
        """Remove this subscription from the active subscriber list."""
        remove_subscriber(self.subscriber)


def open_subscription(token: str) -> tuple[EventSubscription, Queue]:
    """Create an SSE subscription for a normalized dashboard token."""
    subscriber, client_queue = add_subscriber(token)
    return EventSubscription(subscriber), client_queue


def broadcast_event(token: str, event_data: dict[str, Any]) -> None:
    """Store a new event and broadcast it to matching subscribers."""
    clean_token = register_token(token)
    get_event_history(clean_token).insert(0, event_data)
    publish_to_token(clean_token, "message", event_data)


def broadcast_clear(token: str) -> None:
    """Broadcast a clear command to connected dashboard clients."""
    publish_to_token(normalize_token(token), "clear", {})


def publish_to_token(token: str, event_type: str, data: dict[str, Any]) -> None:
    """Send an SSE queue item to subscribers of one token."""
    for subscriber in list(SUBSCRIBERS):
        try:
            if subscriber["token"] == token:
                subscriber["queue"].put({"type": event_type, "data": data})
        except Exception as err:
            logging.error("Failed to send event to subscriber: %s", err)
            remove_subscriber(subscriber)
