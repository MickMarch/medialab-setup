from medialab_setup.answers import Answers
from medialab_setup.bindings import BINDINGS, GENERATED_FIELDS, KEY_PAIRS, owner_of


def test_every_binding_names_a_real_answers_field() -> None:
    fields = set(Answers.model_fields)
    for binding in BINDINGS:
        assert binding.field in fields, binding


def test_every_secrets_md_pair_is_bound_to_one_field() -> None:
    by_target_key = {(b.target, b.key): b.field for b in BINDINGS}
    for caller, callee in KEY_PAIRS:
        assert by_target_key[caller] == by_target_key[callee], (caller, callee)


def test_generated_fields_each_have_an_owner() -> None:
    for field in GENERATED_FIELDS:
        assert owner_of(field) is not None, field


def test_no_target_key_is_bound_twice() -> None:
    seen = [(b.target, b.key) for b in BINDINGS]
    assert len(seen) == len(set(seen))
