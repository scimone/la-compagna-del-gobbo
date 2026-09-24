from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("", include("pwa.urls")),
    path("", include("apps.frontend.urls")),
]

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
