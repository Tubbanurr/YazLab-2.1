from django.urls import path
from .views import (
    ana_sayfa, 
    makale_yukle, 
    makale_takip, 
    makale_indir,
    anonimlestirme_yap, 
    editor_panel, 
    makale_detay, 
    hakem_atama, 
    log_kaydi_goruntule,
    alan_atama_goruntule,
    mesaj_paneli,
    mesaj_gonder,
    anonimlestirme_duzenle,
    anonimlestirmeyi_geri_al,
    orijinal_metin_goster,
    makale_goruntule,
    degerlendirme_ekle,
    degerlendirme_sayfasi,
    hakem_paneli,
    makale_yayinla,
    makale_gonder,
    makale_yazara_gonder,
    makale_revize_yukle,
    takip_mesaj_gonder
)

urlpatterns = [
    path("", ana_sayfa, name="anasayfa"),  # Ana sayfa
    path('takip/mesaj-gonder/', takip_mesaj_gonder, name='takip_mesaj_gonder'),
    path("makale/yukle/", makale_yukle, name="makale_yukle"),  # Makale yükleme
    path("makale/takip/", makale_takip, name="makale_takip"),  # Makale takip
    path('mesaj-paneli/<int:makale_id>/', mesaj_paneli, name='mesaj_paneli'),
    path('mesaj-gonder/<int:makale_id>/', mesaj_gonder, name='mesaj_gonder'),
    path('makale/<int:makale_id>/degerlendirme/', degerlendirme_sayfasi, name='degerlendirme_sayfasi'),
    path('makale/<int:makale_id>/degerlendirme-ekle/', degerlendirme_ekle, name="hakem_degerlendirme_ekle"),
    path("makale/<int:makale_id>/", makale_detay, name="makale_detay"),  # Makale detay
    path("makale/<int:makale_id>/anonimlestir/", anonimlestirme_yap, name="anonimlestirme_yap"),  # Makale anonimleştirme
    path("makale/<int:makale_id>/hakem-atama/", hakem_atama, name="hakem_atama"),  # Hakem atama
    path("makale-indir/<int:makale_id>/", makale_indir, name="makale_indir"),  # Makale indirme
    path("editor/", editor_panel, name="editor_panel"),  # Editör paneli
    path("hakem/panel/", hakem_paneli, name="hakem_paneli"),
    path("loglar/", log_kaydi_goruntule, name="log_kaydi_goruntule"),  # Log kayıtlarını görüntüleme
    path('editor/alan-atama/<int:makale_id>/', alan_atama_goruntule, name='alan_atama_goruntule'),
    path('editor/hakem-atama/<int:makale_id>/', hakem_atama, name='hakem_atama'),
    path('anonimlestirme/<int:anonim_id>/duzenle/', anonimlestirme_duzenle, name="anonimlestirme_duzenle"),
    path('anonimlestirme/<int:makale_id>/geri_al/', anonimlestirmeyi_geri_al, name="anonimlestirmeyi_geri_al"),
    path('orijinal-metin/<int:makale_id>/', orijinal_metin_goster, name="orijinal_metin_goster"),
    path('makale/<int:makale_id>/goruntule/', makale_goruntule, name="makale_goruntule"),
    # Yeni eklenen URL'ler
    path('makale/<int:makale_id>/yayinla/', makale_yayinla, name="makale_yayinla"),
    path('makale/<int:makale_id>/gonder/', makale_gonder, name="makale_gonder"),
    path('makale/<int:makale_id>/yazara-gonder/', makale_yazara_gonder, name="makale_yazara_gonder"),
    path('makale/<int:makale_id>/revize-yukle/', makale_revize_yukle, name='makale_revize_yukle'),

]