import pytest

from spacy import registry
from spacy.tokens import Doc, Span
from spacy.language import Language
from spacy.lang.en import English
from spacy.pipeline import EntityRuler, EntityRecognizer, merge_entities
from spacy.pipeline.ner import DEFAULT_NER_MODEL
from spacy.errors import MatchPatternError
from spacy.tests.util import make_tempdir

from thinc.api import NumpyOps, get_current_ops


@pytest.fixture
def nlp():
    return Language()


@pytest.fixture
@registry.misc("entity_ruler_patterns")
def patterns():
    return [
        {"label": "HELLO", "pattern": "hello world"},
        {"label": "BYE", "pattern": [{"LOWER": "bye"}, {"LOWER": "bye"}]},
        {"label": "HELLO", "pattern": [{"ORTH": "HELLO"}]},
        {"label": "COMPLEX", "pattern": [{"ORTH": "foo", "OP": "*"}]},
        {"label": "TECH_ORG", "pattern": "Apple", "id": "a1"},
        {"label": "TECH_ORG", "pattern": "Microsoft", "id": "a2"},
    ]


@Language.component("add_ent")
def add_ent_component(doc):
    doc.ents = [Span(doc, 0, 3, label="ORG")]
    return doc


@pytest.mark.issue(3345)
def test_issue3345():
    """Test case where preset entity crosses sentence boundary."""
    nlp = English()
    doc = Doc(nlp.vocab, words=["I", "live", "in", "New", "York"])
    doc[4].is_sent_start = True
    ruler = EntityRuler(nlp, patterns=[{"label": "GPE", "pattern": "New York"}])
    cfg = {"model": DEFAULT_NER_MODEL}
    model = registry.resolve(cfg, validate=True)["model"]
    ner = EntityRecognizer(doc.vocab, model)
    # Add the OUT action. I wouldn't have thought this would be necessary...
    ner.moves.add_action(5, "")
    ner.add_label("GPE")
    doc = ruler(doc)
    # Get into the state just before "New"
    state = ner.moves.init_batch([doc])[0]
    ner.moves.apply_transition(state, "O")
    ner.moves.apply_transition(state, "O")
    ner.moves.apply_transition(state, "O")
    # Check that B-GPE is valid.
    assert ner.moves.is_valid(state, "B-GPE")


@pytest.mark.issue(4849)
def test_issue4849():
    nlp = English()
    patterns = [
        {"label": "PERSON", "pattern": "joe biden", "id": "joe-biden"},
        {"label": "PERSON", "pattern": "bernie sanders", "id": "bernie-sanders"},
    ]
    ruler = nlp.add_pipe("entity_ruler", config={"phrase_matcher_attr": "LOWER"})
    ruler.add_patterns(patterns)
    text = """
    The left is starting to take aim at Democratic front-runner Joe Biden.
    Sen. Bernie Sanders joined in her criticism: "There is no 'middle ground' when it comes to climate policy."
    """
    # USING 1 PROCESS
    count_ents = 0
    for doc in nlp.pipe([text], n_process=1):
        count_ents += len([ent for ent in doc.ents if ent.ent_id > 0])
    assert count_ents == 2
    # USING 2 PROCESSES
    if isinstance(get_current_ops, NumpyOps):
        count_ents = 0
        for doc in nlp.pipe([text], n_process=2):
            count_ents += len([ent for ent in doc.ents if ent.ent_id > 0])
        assert count_ents == 2


@pytest.mark.issue(5918)
def test_issue5918():
    # Test edge case when merging entities.
    nlp = English()
    ruler = nlp.add_pipe("entity_ruler")
    patterns = [
        {"label": "ORG", "pattern": "Digicon Inc"},
        {"label": "ORG", "pattern": "Rotan Mosle Inc's"},
        {"label": "ORG", "pattern": "Rotan Mosle Technology Partners Ltd"},
    ]
    ruler.add_patterns(patterns)

    text = """
        Digicon Inc said it has completed the previously-announced disposition
        of its computer systems division to an investment group led by
        Rotan Mosle Inc's Rotan Mosle Technology Partners Ltd affiliate.
        """
    doc = nlp(text)
    assert len(doc.ents) == 3
    # make it so that the third span's head is within the entity (ent_iob=I)
    # bug #5918 would wrongly transfer that I to the full entity, resulting in 2 instead of 3 final ents.
    # TODO: test for logging here
    # with pytest.warns(UserWarning):
    #     doc[29].head = doc[33]
    doc = merge_entities(doc)
    assert len(doc.ents) == 3


@pytest.mark.issue(8168)
def test_issue8168():
    nlp = English()
    ruler = nlp.add_pipe("entity_ruler")
    patterns = [
        {"label": "ORG", "pattern": "Apple"},
        {
            "label": "GPE",
            "pattern": [{"LOWER": "san"}, {"LOWER": "francisco"}],
            "id": "san-francisco",
        },
        {
            "label": "GPE",
            "pattern": [{"LOWER": "san"}, {"LOWER": "fran"}],
            "id": "san-francisco",
        },
    ]
    ruler.add_patterns(patterns)

    assert ruler._ent_ids == {8043148519967183733: ("GPE", "san-francisco")}


@pytest.mark.issue(8216)
def test_entity_ruler_fix8216(nlp, patterns):
    """Test that patterns don't get added excessively."""
    ruler = nlp.add_pipe("entity_ruler", config={"validate": True})
    ruler.add_patterns(patterns)
    pattern_count = sum(len(mm) for mm in ruler.matcher._patterns.values())
    assert pattern_count > 0
    ruler.add_patterns([])
    after_count = sum(len(mm) for mm in ruler.matcher._patterns.values())
    assert after_count == pattern_count


def test_entity_ruler_init(nlp, patterns):
    ruler = EntityRuler(nlp, patterns=patterns)
    assert len(ruler) == len(patterns)
    assert len(ruler.labels) == 4
    assert "HELLO" in ruler
    assert "BYE" in ruler
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns(patterns)
    doc = nlp("hello world bye bye")
    assert len(doc.ents) == 2
    assert doc.ents[0].label_ == "HELLO"
    assert doc.ents[1].label_ == "BYE"


def test_entity_ruler_no_patterns_warns(nlp):
    ruler = EntityRuler(nlp)
    assert len(ruler) == 0
    assert len(ruler.labels) == 0
    nlp.add_pipe("entity_ruler")
    assert nlp.pipe_names == ["entity_ruler"]
    with pytest.warns(UserWarning):
        doc = nlp("hello world bye bye")
    assert len(doc.ents) == 0


def test_entity_ruler_init_patterns(nlp, patterns):
    # initialize with patterns
    ruler = nlp.add_pipe("entity_ruler")
    assert len(ruler.labels) == 0
    ruler.initialize(lambda: [], patterns=patterns)
    assert len(ruler.labels) == 4
    doc = nlp("hello world bye bye")
    assert doc.ents[0].label_ == "HELLO"
    assert doc.ents[1].label_ == "BYE"
    nlp.remove_pipe("entity_ruler")
    # initialize with patterns from misc registry
    nlp.config["initialize"]["components"]["entity_ruler"] = {
        "patterns": {"@misc": "entity_ruler_patterns"}
    }
    ruler = nlp.add_pipe("entity_ruler")
    assert len(ruler.labels) == 0
    nlp.initialize()
    assert len(ruler.labels) == 4
    doc = nlp("hello world bye bye")
    assert doc.ents[0].label_ == "HELLO"
    assert doc.ents[1].label_ == "BYE"


def test_entity_ruler_init_clear(nlp, patterns):
    """Test that initialization clears patterns."""
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns(patterns)
    assert len(ruler.labels) == 4
    ruler.initialize(lambda: [])
    assert len(ruler.labels) == 0


def test_entity_ruler_clear(nlp, patterns):
    """Test that initialization clears patterns."""
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns(patterns)
    assert len(ruler.labels) == 4
    doc = nlp("hello world")
    assert len(doc.ents) == 1
    ruler.clear()
    assert len(ruler.labels) == 0
    with pytest.warns(UserWarning):
        doc = nlp("hello world")
    assert len(doc.ents) == 0


def test_entity_ruler_existing(nlp, patterns):
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns(patterns)
    nlp.add_pipe("add_ent", before="entity_ruler")
    doc = nlp("OH HELLO WORLD bye bye")
    assert len(doc.ents) == 2
    assert doc.ents[0].label_ == "ORG"
    assert doc.ents[1].label_ == "BYE"


def test_entity_ruler_existing_overwrite(nlp, patterns):
    ruler = nlp.add_pipe("entity_ruler", config={"overwrite_ents": True})
    ruler.add_patterns(patterns)
    nlp.add_pipe("add_ent", before="entity_ruler")
    doc = nlp("OH HELLO WORLD bye bye")
    assert len(doc.ents) == 2
    assert doc.ents[0].label_ == "HELLO"
    assert doc.ents[0].text == "HELLO"
    assert doc.ents[1].label_ == "BYE"


def test_entity_ruler_existing_complex(nlp, patterns):
    ruler = nlp.add_pipe("entity_ruler", config={"overwrite_ents": True})
    ruler.add_patterns(patterns)
    nlp.add_pipe("add_ent", before="entity_ruler")
    doc = nlp("foo foo bye bye")
    assert len(doc.ents) == 2
    assert doc.ents[0].label_ == "COMPLEX"
    assert doc.ents[1].label_ == "BYE"
    assert len(doc.ents[0]) == 2
    assert len(doc.ents[1]) == 2


def test_entity_ruler_entity_id(nlp, patterns):
    ruler = nlp.add_pipe("entity_ruler", config={"overwrite_ents": True})
    ruler.add_patterns(patterns)
    doc = nlp("Apple is a technology company")
    assert len(doc.ents) == 1
    assert doc.ents[0].label_ == "TECH_ORG"
    assert doc.ents[0].ent_id_ == "a1"


def test_entity_ruler_cfg_ent_id_sep(nlp, patterns):
    config = {"overwrite_ents": True, "ent_id_sep": "**"}
    ruler = nlp.add_pipe("entity_ruler", config=config)
    ruler.add_patterns(patterns)
    assert "TECH_ORG**a1" in ruler.phrase_patterns
    doc = nlp("Apple is a technology company")
    assert len(doc.ents) == 1
    assert doc.ents[0].label_ == "TECH_ORG"
    assert doc.ents[0].ent_id_ == "a1"


def test_entity_ruler_serialize_bytes(nlp, patterns):
    ruler = EntityRuler(nlp, patterns=patterns)
    assert len(ruler) == len(patterns)
    assert len(ruler.labels) == 4
    ruler_bytes = ruler.to_bytes()
    new_ruler = EntityRuler(nlp)
    assert len(new_ruler) == 0
    assert len(new_ruler.labels) == 0
    new_ruler = new_ruler.from_bytes(ruler_bytes)
    assert len(new_ruler) == len(patterns)
    assert len(new_ruler.labels) == 4
    assert len(new_ruler.patterns) == len(ruler.patterns)
    for pattern in ruler.patterns:
        assert pattern in new_ruler.patterns
    assert sorted(new_ruler.labels) == sorted(ruler.labels)


def test_entity_ruler_serialize_phrase_matcher_attr_bytes(nlp, patterns):
    ruler = EntityRuler(nlp, phrase_matcher_attr="LOWER", patterns=patterns)
    assert len(ruler) == len(patterns)
    assert len(ruler.labels) == 4
    ruler_bytes = ruler.to_bytes()
    new_ruler = EntityRuler(nlp)
    assert len(new_ruler) == 0
    assert len(new_ruler.labels) == 0
    assert new_ruler.phrase_matcher_attr is None
    new_ruler = new_ruler.from_bytes(ruler_bytes)
    assert len(new_ruler) == len(patterns)
    assert len(new_ruler.labels) == 4
    assert new_ruler.phrase_matcher_attr == "LOWER"


def test_entity_ruler_validate(nlp):
    ruler = EntityRuler(nlp)
    validated_ruler = EntityRuler(nlp, validate=True)

    valid_pattern = {"label": "HELLO", "pattern": [{"LOWER": "HELLO"}]}
    invalid_pattern = {"label": "HELLO", "pattern": [{"ASDF": "HELLO"}]}

    # invalid pattern raises error without validate
    with pytest.raises(ValueError):
        ruler.add_patterns([invalid_pattern])

    # valid pattern is added without errors with validate
    validated_ruler.add_patterns([valid_pattern])

    # invalid pattern raises error with validate
    with pytest.raises(MatchPatternError):
        validated_ruler.add_patterns([invalid_pattern])


def test_entity_ruler_properties(nlp, patterns):
    ruler = EntityRuler(nlp, patterns=patterns, overwrite_ents=True)
    assert sorted(ruler.labels) == sorted(["HELLO", "BYE", "COMPLEX", "TECH_ORG"])
    assert sorted(ruler.ent_ids) == ["a1", "a2"]


def test_entity_ruler_overlapping_spans(nlp):
    ruler = EntityRuler(nlp)
    patterns = [
        {"label": "FOOBAR", "pattern": "foo bar"},
        {"label": "BARBAZ", "pattern": "bar baz"},
    ]
    ruler.add_patterns(patterns)
    doc = ruler(nlp.make_doc("foo bar baz"))
    assert len(doc.ents) == 1
    assert doc.ents[0].label_ == "FOOBAR"


@pytest.mark.parametrize("n_process", [1, 2])
def test_entity_ruler_multiprocessing(nlp, n_process):
    if isinstance(get_current_ops, NumpyOps) or n_process < 2:
        texts = ["I enjoy eating Pizza Hut pizza."]

        patterns = [{"label": "FASTFOOD", "pattern": "Pizza Hut", "id": "1234"}]

        ruler = nlp.add_pipe("entity_ruler")
        ruler.add_patterns(patterns)

        for doc in nlp.pipe(texts, n_process=2):
            for ent in doc.ents:
                assert ent.ent_id_ == "1234"


def test_entity_ruler_serialize_jsonl(nlp, patterns):
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns(patterns)
    with make_tempdir() as d:
        ruler.to_disk(d / "test_ruler.jsonl")
        ruler.from_disk(d / "test_ruler.jsonl")  # read from an existing jsonl file
        with pytest.raises(ValueError):
            ruler.from_disk(d / "non_existing.jsonl")  # read from a bad jsonl file


def test_entity_ruler_serialize_dir(nlp, patterns):
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns(patterns)
    with make_tempdir() as d:
        ruler.to_disk(d / "test_ruler")
        ruler.from_disk(d / "test_ruler")  # read from an existing directory
        with pytest.raises(ValueError):
            ruler.from_disk(d / "non_existing_dir")  # read from a bad directory
