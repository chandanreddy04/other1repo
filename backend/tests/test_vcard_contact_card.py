"""Regression guard: the /made-it-home.vcf contact card must carry a structured
N (name) property.

iOS populates a contact's First/Last fields from N, not FN — the card shipped
with only FN, so iOS saved it with a blank name. N is also required by the
vCard 3.0 spec and read identically by Android, so this stays portable.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_vcard_has_structured_name(client: AsyncClient):
    resp = await client.get("/made-it-home.vcf")
    assert resp.status_code == 200
    # Family=Alerts, Given="Made It Home" → First "Made It Home", Last "Alerts".
    assert "N:Alerts;Made It Home;;;" in resp.text
    # Display name preserved.
    assert "FN:Made It Home Alerts" in resp.text
    # Stable UID so re-download can update in place rather than duplicate.
    assert "UID:made-it-home-alerts" in resp.text
