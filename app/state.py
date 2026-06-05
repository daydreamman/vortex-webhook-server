import queue


DEFAULT_RUNTIME_TOKEN = ""
KNOWN_VORTEX_TOKENS = set()
EVENT_HISTORY_BY_TOKEN = {}
SUBSCRIBERS = []
VORTEXAI_SESSIONS = {}


def normalize_token(token):
    return str(token or "").strip()


def register_token(token):
    clean_token = normalize_token(token)
    if clean_token:
        KNOWN_VORTEX_TOKENS.add(clean_token)
    return clean_token


def get_event_history(token):
    clean_token = register_token(token)
    return EVENT_HISTORY_BY_TOKEN.setdefault(clean_token, [])


def get_vortexai_session(session_id):
    return VORTEXAI_SESSIONS.get(str(session_id or "").strip())


def get_vortexai_auth_context(session_id):
    session = get_vortexai_session(session_id)
    if not session:
        return None
    return {
        "base_url": session["base_url"],
        "headers": {
            "Authorization": f"Bearer {session['jwt']}",
            "Content-Type": "application/json",
        },
    }


def add_subscriber(token):
    client_queue = queue.Queue()
    subscriber = {"queue": client_queue, "token": token}
    SUBSCRIBERS.append(subscriber)
    return subscriber, client_queue


def remove_subscriber(subscriber):
    if subscriber in SUBSCRIBERS:
        SUBSCRIBERS.remove(subscriber)
