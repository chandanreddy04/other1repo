"""Backend side of the push notification `type` contract.

The mobile app routes notification taps by the `type` value in the push data
payload. Historically the mobile handlers checked type names the backend
never emitted, so routing and escalation were silently dead. The contract
now lives in mobile/constants/notificationTypes.json:

- this test asserts the types the backend actually emits (scanned from the
  dispatch modules) EXACTLY match the contract's `backend` list;
- mobile's services/notificationRouting.test.ts asserts every contract type
  has a routing entry.

Adding a new notification: add the type to the JSON first, then wire both
sides — either side missing becomes a test failure, not a dead handler.

Related: app/services/notification_helpers.py, app/services/session_tasks.py.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_FILE = REPO_ROOT / "mobile" / "constants" / "notificationTypes.json"

# Only the modules that build push data payloads. (Other services use
# "type" keys for unrelated things, e.g. Stripe metadata.)
DISPATCH_MODULES = [
    REPO_ROOT / "backend" / "app" / "services" / "notification_helpers.py",
    REPO_ROOT / "backend" / "app" / "services" / "session_tasks.py",
    REPO_ROOT / "backend" / "app" / "services" / "alert_acknowledgement.py",
    REPO_ROOT / "backend" / "app" / "services" / "group_plan_service.py",
    REPO_ROOT / "backend" / "app" / "services" / "notification_outbox.py",
    REPO_ROOT / "backend" / "app" / "services" / "sub_lapse_notifications.py",
]

_TYPE_PATTERN = re.compile(r'["\']type["\']\s*:\s*["\'](\w+)["\']')


def _emitted_types() -> set[str]:
    found: set[str] = set()
    for module in DISPATCH_MODULES:
        found.update(_TYPE_PATTERN.findall(module.read_text()))
    return found


def test_contract_file_exists_and_parses():
    contract = json.loads(CONTRACT_FILE.read_text())
    assert isinstance(contract["backend"], list) and contract["backend"]
    assert isinstance(contract["local"], list)


def test_emitted_types_exactly_match_contract():
    contract = json.loads(CONTRACT_FILE.read_text())
    contracted = set(contract["backend"])
    emitted = _emitted_types()

    missing_from_contract = emitted - contracted
    stale_in_contract = contracted - emitted

    assert not missing_from_contract, (
        f"Backend emits push types not in the contract: {missing_from_contract}. "
        "Add them to mobile/constants/notificationTypes.json AND a routing "
        "entry in mobile/services/notificationRouting.ts."
    )
    assert not stale_in_contract, (
        f"Contract lists push types the backend no longer emits: {stale_in_contract}. "
        "Remove them from mobile/constants/notificationTypes.json and the "
        "mobile routing map."
    )
