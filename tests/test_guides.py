from medialab_setup.answers import Answers
from medialab_setup.bindings import ASKED_FIELDS, GENERATED_FIELDS
from medialab_setup.guides import GUIDES, guide_for
from medialab_setup.prompts import render_guide


def test_every_asked_field_has_a_guide_and_nothing_else_does() -> None:
    assert {guide.field for guide in GUIDES} == set(ASKED_FIELDS)


def test_asked_and_generated_fields_are_real_and_disjoint() -> None:
    fields = set(Answers.model_fields)
    assert set(ASKED_FIELDS) <= fields
    assert set(GENERATED_FIELDS) <= fields
    assert not set(ASKED_FIELDS) & set(GENERATED_FIELDS)


def test_credential_guides_carry_a_url_and_steps() -> None:
    for name in ("tmdb_api_key", "jellyfin_api_key", "discord_token", "wireguard_private_key"):
        guide = guide_for(name)
        assert guide.url and guide.url.startswith("http")
        assert guide.steps
        assert guide.secret


def test_render_guide_lists_steps_and_url() -> None:
    text = render_guide(guide_for("tmdb_api_key"))
    assert "1." in text
    assert "themoviedb.org" in text
    assert "Looks like" in text
