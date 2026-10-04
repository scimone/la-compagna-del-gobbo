import pytest
from django.urls import reverse

from apps.frontend.entries_render import render_entries
from apps.rules.models import Class, OptionalFeature


@pytest.fixture
def options(db):
    Class.objects.create(id="warlock", name="Warlock", page=1, hit_die="d8")
    Class.objects.create(id="sorcerer", name="Sorcerer", page=1, hit_die="d6")
    OptionalFeature.objects.create(
        id="agonizing-blast", name="Agonizing Blast", page=1, feature_type="Eldritch Invocation"
    )
    OptionalFeature.objects.create(
        id="careful-spell", name="Careful Spell", page=1, feature_type="Metamagic"
    )


def _names(response):
    return [item["name"] for item in response.context["items"]]


def test_features_list_has_an_options_type_with_its_own_filters(client, options):
    url = reverse("world-feats")
    assert set(_names(client.get(url, {"type": "option"}))) == {"Agonizing Blast", "Careful Spell"}

    by_type = client.get(url, {"type": "option", "option_type": "Metamagic"})
    assert _names(by_type) == ["Careful Spell"]

    by_class = client.get(url, {"type": "option", "class": "warlock"})
    assert _names(by_class) == ["Agonizing Blast"]

    row = by_class.context["items"][0]
    assert row["kind"] == "option"
    assert row["url"] == reverse("world-option-detail", args=["agonizing-blast"])


def test_option_references_render_as_links_to_their_page(options):
    html = render_entries(
        [
            "Options appear in alphabetical order.",
            {
                "type": "options",
                "count": 1,
                "entries": [
                    {"type": "refOptionalfeature", "optionalfeature": "Agonizing Blast|XPHB"},
                    {"type": "refOptionalfeature", "optionalfeature": "Unknown Thing|XPHB"},
                ],
            },
        ]
    )
    assert '<a href="/world/feats/option/agonizing-blast/">Agonizing Blast</a>' in html
    assert "<li>Unknown Thing</li>" in html


def test_a_class_with_options_has_an_options_tab_replacing_the_listing_feature(client, options):
    from apps.rules.models import ClassLevel, Feature

    level = ClassLevel.objects.create(klass_id="warlock", level=1)
    listing = Feature.objects.create(class_level=level, name="Eldritch Invocation Options")
    Feature.objects.create(class_level=level, name="Eldritch Invocations")
    url = reverse("world-class-detail", args=["warlock"])

    about = client.get(url)
    assert [key for key, _label in about.context["tabs"]][-1] == "options"
    assert about.context["tabs"][-1][1] == "Eldritch Invocation Options"
    assert "Eldritch Invocations" in client.get(url, {"tab": "levels"}).content.decode()
    assert (
        f"/world/feats/feature/{listing.pk}/"
        not in client.get(url, {"tab": "levels"}).content.decode()
    )

    tab = client.get(url, {"tab": "options"}).content.decode()
    assert '<a href="/world/feats/option/agonizing-blast/">Agonizing Blast</a>' in tab
    assert "Careful Spell" not in tab  # Metamagic belongs to the Sorcerer


def test_option_filter_tags_link_to_the_class_options_tab(options):
    html = render_entries(
        ['See "{@filter Metamagic Options|optionalfeatures|feature type=MM|source=XPHB}".']
    )
    assert '<a href="/world/classes/sorcerer/?tab=options">Metamagic Options</a>' in html
