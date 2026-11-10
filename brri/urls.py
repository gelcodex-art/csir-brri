from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.site_header = "CSIR-BRRI"
admin.site.site_title = "CSIR-BRRI admin"
admin.site.index_title = "Administration"

urlpatterns = [
    # One log-in page for the whole system (the admin area has no separate one).
    path("admin/login/", RedirectView.as_view(url="/login/?next=/admin/")),
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("accidents.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
