"""Phone number utilities using phonenumbers library"""

import hashlib

import phonenumbers


def phone_tag(phone: str) -> str:
    """Short opaque tag for log/metric correlation that doesn't leak
    the phone number itself.

    `security.md`: phones are PII; only `user.id` goes to Bugsnag.
    Use this tag in `extra={"phone_tag": phone_tag(p)}` on
    `logger.exception/error/critical` calls so events from the same
    number stay groupable without exposing the number in error tracking.

    8 hex chars is plenty for within-incident disambiguation;
    enforced by `tests/test_no_phone_in_log_extras.py`.
    """
    return hashlib.sha256(phone.encode("utf-8")).hexdigest()[:8]


def format_to_e164(phone_number: str, default_country: str = "US") -> str | None:
    """
    Format a phone number to E164 format

    Args:
        phone_number: The phone number to format
        default_country: Default country code if not provided (default: US)

    Returns:
        E164 formatted phone number or None if invalid
    """
    try:
        # If the number doesn't start with +, parse with default country
        if not phone_number.startswith("+"):
            parsed = phonenumbers.parse(phone_number, default_country)
        else:
            parsed = phonenumbers.parse(phone_number, None)

        # Validate the number
        if not phonenumbers.is_valid_number(parsed):
            return None

        # Format to E164
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        # benign: invalid input — callers treat None as "not a phone number"
        return None


def format_for_display(phone_number: str, default_country: str = "US") -> str:
    """
    Format a phone number for display in a user-friendly way

    Args:
        phone_number: The phone number to format (E164 or national format)
        default_country: Default country code if not provided (default: US)

    Returns:
        Formatted phone number for display (e.g., "(510) 284-9127" for US numbers)
    """
    try:
        # Parse the phone number
        if not phone_number.startswith("+"):
            parsed = phonenumbers.parse(phone_number, default_country)
        else:
            parsed = phonenumbers.parse(phone_number, None)

        # Format as national for US numbers, international for others
        if parsed.country_code == 1:  # US/Canada
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.NATIONAL
            )
        else:
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
            )
    except phonenumbers.NumberParseException:
        # benign: if parsing fails, show the original string
        return phone_number
