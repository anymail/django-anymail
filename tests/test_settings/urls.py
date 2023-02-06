from django.urls import include, re_path

urlpatterns = [
    re_path(r"^anymail/", include("anymail.urls")),
]
