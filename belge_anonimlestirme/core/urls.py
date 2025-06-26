from django.contrib import admin
from django.urls import path, include
from makale.views import ana_sayfa  # Ana sayfa görünümünü ekledik
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", ana_sayfa, name="anasayfa"),  # Ana sayfa buraya eklendi
    path("", include("makale.urls")),  # Ana sayfa ve makale yollarını içeriyor
]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)