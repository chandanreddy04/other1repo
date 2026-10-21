"""Every coded short-link slug is the first letter of its lander's
resource segment (app/web/short_links.py) — the rule that keeps a new
slug from being picked at random as the registry grows. The codeless
`/sub` entry is the one documented exception (it's the full frozen SMS
path segment, not a one-letter code prefix)."""

from app.web.short_links import SHORT_LINKS, ShortLink


def _first_letter_rule_ok(link: ShortLink) -> bool:
    """True if a coded slug is the first letter of its lander's resource
    segment (e.g. "r" for "/referrals", "g" for "/groups")."""
    resource = link.lander.strip("/").split("/")[0]
    return bool(resource) and link.slug == resource[0]


class TestFirstLetterRule:
    def test_every_coded_slug_matches_its_lander(self):
        offenders = [
            sl for sl in SHORT_LINKS if sl.has_code and not _first_letter_rule_ok(sl)
        ]
        assert not offenders, (
            "coded slug isn't the first letter of its lander's resource "
            f"segment: {[(sl.slug, sl.lander) for sl in offenders]}"
        )

    def test_sub_is_the_only_codeless_exception(self):
        codeless = [sl for sl in SHORT_LINKS if not sl.has_code]
        assert [(sl.slug, sl.lander) for sl in codeless] == [("sub", "/plans")], (
            "the only codeless short link is the frozen lapse-SMS /sub "
            "(sub_lapse_notifications.py) — a new one needs an owner decision"
        )
