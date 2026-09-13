from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from ninja import NinjaAPI

from apps.builder.api.router import router as builder_router
from apps.characters.api.router import router as characters_router
from apps.rules.api.router import router as rules_router

api = NinjaAPI(title="La Compagna del Gobbo API", version="1.0.0")
api.add_router("/rules", rules_router)
api.add_router("/characters", characters_router)
api.add_router("/characters", builder_router)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("", include("pwa.urls")),
    path("", include("apps.frontend.urls")),
]

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
