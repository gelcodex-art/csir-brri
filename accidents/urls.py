from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("accidents/", views.accident_list, name="accident_list"),
    path("accidents/new/", views.accident_edit, name="accident_new"),
    path("accidents/<int:pk>/", views.accident_detail, name="accident_detail"),
    path("accidents/<int:pk>/edit/", views.accident_edit, name="accident_edit"),
    path("accidents/<int:pk>/review/", views.accident_review, name="accident_review"),
    path("export/<str:fmt>/", views.export, name="export"),
    path("api/locations.json", views.locations_api, name="locations_api"),
    path("api/pins.json", views.pins_api, name="pins_api"),
    # Removes the offline service worker from browsers that installed it earlier.
    path("sw.js", views.service_worker_removal, name="service_worker_removal"),
]
