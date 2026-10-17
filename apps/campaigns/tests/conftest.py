import pytest
from django.contrib.auth import get_user_model

pytestmark = pytest.mark.no_default_campaign


@pytest.fixture
def make_user(db):
    def make(name: str, email: str = ""):
        return get_user_model().objects.create_user(
            username=name, email=email or f"{name}@example.com"
        )

    return make
