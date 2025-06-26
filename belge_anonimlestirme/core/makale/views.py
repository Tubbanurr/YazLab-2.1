import mimetypes
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import path
from django.shortcuts import render, redirect
from .models import Kullanici, Makale, Anonimlestirme, Degerlendirme, LogKaydi,Mesaj
from django.core.files.storage import default_storage
from .forms import MakaleYuklemeForm
import uuid
from django.db import transaction
import re
from django.shortcuts import render, get_object_or_404
from .utils import pdf_to_text, anonimlestir
from .utils import pdf_to_text, anahtar_kelime_cikar, alan_atama_nlp, anonimlestir_pdf_format_korunarak
from .utils import pdf_to_text, anahtar_kelime_cikar
from django.contrib import messages
from .utils import pdf_to_text, alan_atama_nlp
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Makale, Mesaj
from .forms import MakaleYuklemeForm    
from .utils import pdf_to_text, alan_atama_nlp, uygun_hakem_bul
from django.shortcuts import render, get_object_or_404, redirect
from .models import Makale, Anonimlestirme, Kullanici, LogKaydi 
from .utils import pdf_to_text, anonimlestir
from .utils import geri_anonim_ac
from django.core.files.base import ContentFile
from django.http import FileResponse
import PyPDF2
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.core.files.base import ContentFile
from django.conf import settings
from .models import Makale, Degerlendirme, Kullanici
from django.shortcuts import get_object_or_404, render
from django.contrib import messages
from .models import Makale, Kullanici, Anonimlestirme, Degerlendirme, LogKaydi, Mesaj
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import os

def makale_revize_yukle(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)

    if request.method == 'POST' and request.FILES.get('revize_dosya'):
        revize_dosya = request.FILES['revize_dosya']

        dosya_yolu = os.path.join('makaleler', 'revizyon', revize_dosya.name)
        makale.dosya.save(dosya_yolu, revize_dosya, save=True)

        # Makale durumunu güncelle
        makale.durum = 'Revize Edildi'
        makale.save()

        # Önceki değerlendirme ve anonimleştirme kayıtlarını sil
        Degerlendirme.objects.filter(makale=makale).delete()
        Anonimlestirme.objects.filter(makale=makale).delete()

        # Revizyon işlemini log olarak kaydet
        LogKaydi.objects.create(
            makale=makale,
            islem_tipi='Revize Edildi',
            aciklama=f'"{makale.baslik}" başlıklı makale revize edildi ve yeniden değerlendirme süreci başlatıldı.'
        )

        messages.success(request, 'Revize edilmiş makaleniz başarıyla yüklendi. Makaleniz yeniden değerlendirilmek üzere editöre gönderildi.')
    else:
        messages.error(request, 'Lütfen bir dosya seçiniz!')

    makaleler = Makale.objects.filter(yazar=makale.yazar)
    return render(request, 'yazar.html', {
        'makaleler': makaleler,
        'email': makale.yazar.email,
    })

def makale_yazara_gonder(request, makale_id):
    """
    Editörün değerlendirilmiş ve anonimliği çözülmüş makaleyi yazara göndermesi için kullanılır.
    """
    if request.method != "POST":
        return redirect('editor_panel')
    
    makale = get_object_or_404(Makale, id=makale_id)
    
    # Editör kontrolü
    editor_email = request.session.get('email')
    editor = Kullanici.objects.filter(email=editor_email, kullanici_tipi="editor").first()
    if not editor:
        messages.error(request, "Bu işlemi sadece editörler yapabilir!")
        return redirect('editor_panel')
    
    # Makale durumu kontrolü - daha geniş bir durum kontrol mekanizması
    valid_statuses = [
        "Değerlendirildi ve Anonimlik Çözüldü", 
        "Değerlendirildi - Anonimlik Çözüldü",
        "Anonimlik Çözüldü - Değerlendirildi",
        "Anonimlik Kaldırıldı"
    ]
    
    is_valid_status = makale.durum in valid_statuses or (
        "Değerlendirildi" in makale.durum and "Anonimlik" in makale.durum
    )
    
    if not is_valid_status:
        messages.error(request, f"Bu makale henüz yazara gönderilemez! Mevcut durum: {makale.durum}")
        return redirect('editor_panel')
    
    # Anonimleştirme kaydını kontrol et
    anonimlestirme = Anonimlestirme.objects.filter(makale=makale).first()
    if not anonimlestirme:
        messages.error(request, "Bu makale için anonimleştirme kaydı bulunamadı!")
        return redirect('editor_panel')
    
    # Anonim etiketler hala var mı kontrol et
    has_anonymous_tags = (
        "[YAZAR ***]" in anonimlestirme.anonim_bilgiler or 
        "[KURUM ***]" in anonimlestirme.anonim_bilgiler or 
        "[EMAIL ***]" in anonimlestirme.anonim_bilgiler
    )
    
    if has_anonymous_tags:
        messages.error(request, "Bu makale hala anonim! Önce anonimliği çözmeniz gerekiyor.")
        return redirect('makale_goruntule', makale_id=makale.id)
    
    # Yazara mesaj gönder
    try:
        Mesaj.objects.create(
            makale=makale,
            gonderen=editor,
            alici=makale.yazar,
            mesaj=f"Değerli Yazar, makaleniz değerlendirildi ve incelemeniz için hazırlandı. Değerlendirme sonuçlarını görüntüleyebilir ve değerlendirme PDF'ini aşağıdaki butondan indirebilirsiniz."
        )
        
        # Makale durumunu "Yazara Gönderildi" olarak güncelle
        makale.durum = "Yazara Gönderildi"
        makale.save()
    except Exception as e:
        messages.error(request, f"Yazara mesaj gönderirken bir hata oluştu: {str(e)}")
        return redirect('editor_panel')
    
    # Log kaydı oluştur
    LogKaydi.objects.create(
        makale=makale,
        islem_tipi="yazara_gonderildi",
        aciklama=f"{makale.baslik} makalesi yazara gönderildi."
    )
    
    messages.success(request, "Makale başarıyla yazara gönderildi ve bildirim mesajı iletildi.")
    return redirect('editor_panel')

def makale_yayinla(request, makale_id):
    """
    Editörün değerlendirilmiş makaleyi yayınlaması için kullanılan işlev.
    """
    if request.method != "POST":
        return redirect('editor_panel')
    
    makale = get_object_or_404(Makale, id=makale_id)
    
    # Editör kontrolü
    editor_email = request.session.get('email')
    editor = Kullanici.objects.filter(email=editor_email, kullanici_tipi="editor").first()
    if not editor:
        messages.error(request, "Bu işlemi sadece editörler yapabilir!")
        return redirect('editor_panel')
    
    # Makale değerlendirilmiş mi kontrolü
    if makale.durum != "Değerlendirildi":
        messages.error(request, "Yalnızca değerlendirilmiş makaleler yayınlanabilir!")
        return redirect('editor_panel')
    
    # Makaleyi yayınla
    makale.durum = "Yayınlandı"
    makale.save()
    
    # Log kaydı oluştur
    LogKaydi.objects.create(
        makale=makale,
        islem_tipi="yayınlandı",
        aciklama=f"{makale.baslik} makalesi yayınlandı."
    )
    
    messages.success(request, "Makale başarıyla yayınlandı!")
    return redirect('editor_panel')

def makale_gonder(request, makale_id):
    """
    Yazarın değerlendirilmiş makaleyi dergiye göndermesi için kullanılan işlev.
    """
    if request.method != "POST":
        return redirect('ana_sayfa')
    
    makale = get_object_or_404(Makale, id=makale_id)
    
    # Yazar kontrolü
    yazar_email = request.session.get('email')
    yazar = get_object_or_404(Kullanici, email=yazar_email)
    
    if yazar != makale.yazar:
        messages.error(request, "Bu makale size ait değil!")
        return redirect('ana_sayfa')
    
    # Makale değerlendirilmiş mi kontrolü
    if makale.durum != "Değerlendirildi":
        messages.error(request, "Yalnızca değerlendirilmiş makaleler gönderilebilir!")
        return redirect('ana_sayfa')
    
    # Makaleyi dergiye gönder
    # Bu işlem gerçekte dergi API'si kullanılarak yapılabilir
    # Burada sadece durum güncellemesi yapıyoruz
    makale.durum = "Dergiye Gönderildi"
    makale.save()
    
    # Log kaydı oluştur
    LogKaydi.objects.create(
        makale=makale,
        islem_tipi="dergiye_gonderildi",
        aciklama=f"{makale.baslik} makalesi dergiye gönderildi."
    )

    # Yönlendirme: artık özel tasarlanmış başarı sayfasına git
    return render(request, "dergiye_gonderildi.html", {"makale": makale})


def degerlendirme_sayfasi(request, makale_id):
    """
    Hakemin değerlendirme yapabileceği sayfayı gösterir.
    """
    makale = get_object_or_404(Makale, id=makale_id)
    
    # Hakem doğrulaması
    hakem_email = request.session.get('email')
    if not hakem_email:
        messages.error(request, "Oturum bilgisi bulunamadı!")
        return redirect('hakem_paneli')
    
    if not makale.atanan_hakem or makale.atanan_hakem.email != hakem_email:
        messages.error(request, "Bu makale için atanmış hakem değilsiniz!")
        return redirect('hakem_paneli')
    
    # Makale zaten değerlendirilmiş mi kontrol et
    mevcut_degerlendirme = Degerlendirme.objects.filter(makale=makale, hakem__email=hakem_email).first()
    if mevcut_degerlendirme and mevcut_degerlendirme.degerlendirme_icerik:
        messages.warning(request, "Bu makale için zaten değerlendirme yapmışsınız. Tekrar değerlendirme yapamazsınız.")
        return redirect('hakem_paneli')
    
    return render(request, "degerlendirme.html", {"makale": makale})

def degerlendirme_ekle(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)

    # Hakem doğrulaması
    hakem_email = request.session.get('email')
    if not hakem_email:
        messages.error(request, "Oturum bilgisi bulunamadı!")
        return redirect('hakem_paneli')
    if not makale.atanan_hakem or makale.atanan_hakem.email != hakem_email:
        messages.error(request, "Bu makale için atanmış hakem değilsiniz!")
        return redirect('hakem_paneli')
    
    # Makale zaten değerlendirilmiş mi kontrol et - ilk tarihli değerlendirmeyi al
    mevcut_degerlendirmeler = Degerlendirme.objects.filter(makale=makale, hakem__email=hakem_email).order_by('tarih')
    mevcut_degerlendirme = mevcut_degerlendirmeler.first() if mevcut_degerlendirmeler.exists() else None
    
    if mevcut_degerlendirme and mevcut_degerlendirme.degerlendirme_icerik and mevcut_degerlendirme.kilitli:
        messages.warning(request, "Bu makale için zaten değerlendirme yapmışsınız ve kilitlenmiş. Tekrar değerlendirme yapamazsınız.")
        return redirect('hakem_paneli')

    if request.method == "POST":
        degerlendirme_metin = request.POST.get("degerlendirme", "").strip()
        if not degerlendirme_metin:
            messages.error(request, "Değerlendirme metni boş olamaz.")
            return redirect('degerlendirme_sayfasi', makale_id=makale.id)

        if not makale.anonim_dosya:
            messages.error(request, "Anonimleştirilmiş makale bulunamadı.")
            return redirect('hakem_paneli')

        # Hata yakalama için try-except bloğu
        try:
            # Önce değerlendirme kaydını oluşturalım/güncelleyelim
            hakem = get_object_or_404(Kullanici, email=hakem_email)
            
            # 1. VERİTABANI KAYDI
            try:
                print(f"Değerlendirme kaydediliyor: Hakem={hakem_email}, Makale ID={makale.id}")
                
                if mevcut_degerlendirme:
                    # Mevcut değerlendirmeyi güncelle
                    print(f"Mevcut değerlendirme (ID: {mevcut_degerlendirme.id}) güncelleniyor...")
                    
                    # Eğer değerlendirme kilitliyse, yeni bir değerlendirme oluştur
                    if mevcut_degerlendirme.kilitli:
                        print("Değerlendirme kilitli, yeni değerlendirme oluşturuluyor...")
                        mevcut_degerlendirme = Degerlendirme.objects.create(
                            makale=makale,
                            hakem=hakem,
                            degerlendirme_icerik=degerlendirme_metin,
                            kilitli=False  # Önce kilitsiz olarak kaydet
                        )
                    else:
                        # Kilitli değilse güncelle
                        mevcut_degerlendirme.degerlendirme_icerik = degerlendirme_metin
                        mevcut_degerlendirme.save()  # Henüz kilitlemiyoruz
                    
                    print(f"Değerlendirme ID: {mevcut_degerlendirme.id} güncellendi/oluşturuldu")
                else:
                    # Yeni değerlendirme oluştur
                    print("Yeni değerlendirme oluşturuluyor...")
                    mevcut_degerlendirme = Degerlendirme.objects.create(
                        makale=makale,
                        hakem=hakem,
                        degerlendirme_icerik=degerlendirme_metin,
                        kilitli=False  # Önce kilitsiz olarak kaydet
                    )
                    print(f"Yeni değerlendirme oluşturuldu, ID: {mevcut_degerlendirme.id}")
                
                # Değerlendirmenin doğru kaydedildiğini kontrol et
                kontrol_degerlendirme = Degerlendirme.objects.get(id=mevcut_degerlendirme.id)
                if not kontrol_degerlendirme or not kontrol_degerlendirme.degerlendirme_icerik:
                    print("HATA: Değerlendirme içeriği kontrol edildiğinde boş bulundu!")
                    raise ValueError("Değerlendirme içeriği veritabanına kaydedilemedi.")
                
                print(f"Değerlendirme kaydı doğrulandı: {len(kontrol_degerlendirme.degerlendirme_icerik)} karakter")
                
                # Log kaydı oluştur
                LogKaydi.objects.create(
                    makale=makale,
                    islem_tipi="degerlendirme_kaydedildi",
                    aciklama=f"{makale.baslik} makalesi için değerlendirme veritabanına kaydedildi."
                )
            except Exception as e:
                import traceback
                print(f"Değerlendirme kaydı sırasında hata: {str(e)}")
                print(traceback.format_exc())
                messages.error(request, f"Değerlendirme kaydedilirken bir hata oluştu: {str(e)}")
                return redirect('hakem_paneli')

            # 2. PDF OLUŞTURMA İŞLEMİ
            try:
                # ReportLab ile değerlendirme sayfası oluştur
                from reportlab.pdfgen import canvas
                from reportlab.lib.pagesizes import letter
                from io import BytesIO
                
                # Geçici bir PDF oluştur
                buffer = BytesIO()
                c = canvas.Canvas(buffer, pagesize=letter)
                
                # Değerlendirme başlığı
                c.setFont("Helvetica-Bold", 14)
                c.drawString(72, 750, "HAKEM DEĞERLENDİRMESİ")
                
                # Değerlendirme tarihi
                from datetime import datetime
                c.setFont("Helvetica", 10)
                c.drawString(72, 730, f"Tarih: {datetime.now().strftime('%d/%m/%Y')}")
                
                # Değerlendirme metni
                c.setFont("Helvetica", 12)
                y_position = 700
                
                # Metni satırlar halinde bölme
                words = degerlendirme_metin.split()
                lines = []
                current_line = ""
                
                for word in words:
                    if len(current_line + " " + word) < 70:  # Satır genişliği
                        current_line += " " + word if current_line else word
                    else:
                        lines.append(current_line)
                        current_line = word
                
                if current_line:
                    lines.append(current_line)
                
                # Metni sayfaya yerleştir
                for line in lines:
                    y_position -= 15
                    c.drawString(72, y_position, line)
                    
                    if y_position < 72:  # Sayfa sınırına yaklaştık mı?
                        c.showPage()  # Yeni sayfa
                        y_position = 750  # Y koordinatını sıfırla
                
                c.save()
                
                # Değerlendirme PDF'i
                buffer.seek(0)
                degerlendirme_pdf = BytesIO(buffer.getvalue())
                
                # PyPDF2 ile mevcut PDF'e yeni sayfayı ekle
                from PyPDF2 import PdfReader, PdfWriter
                
                # Orijinal anonim dosyayı aç
                anonim_pdf = PdfReader(makale.anonim_dosya.path)
                output_pdf = PdfWriter()
                
                # Tüm orijinal sayfaları kopyala
                for page in anonim_pdf.pages:
                    output_pdf.add_page(page)
                
                # Yeni değerlendirme sayfasını ekle
                degerlendirme_pdf.seek(0)
                degerlendirme_reader = PdfReader(degerlendirme_pdf)
                for page in degerlendirme_reader.pages:
                    output_pdf.add_page(page)
                
                # Dosya yolları belirleme
                media_root = settings.MEDIA_ROOT
                anonim_klasoru = os.path.join(media_root, "makaleler", "anonim")
                os.makedirs(anonim_klasoru, exist_ok=True)
                
                # Makale ID'sine göre dosya adı oluştur
                degerlendirme_dosya_adi = f"makale_{makale.id}_degerlendirilmis.pdf"
                yeni_pdf_yolu = os.path.join(anonim_klasoru, degerlendirme_dosya_adi)
                
                # Yeni PDF'i kaydet
                with open(yeni_pdf_yolu, "wb") as output_file:
                    output_pdf.write(output_file)
                
                # Yeni dosyayı makale modeline kaydet
                with open(yeni_pdf_yolu, "rb") as final_file:
                    makale.anonim_dosya.save(
                        f"makaleler/anonim/{degerlendirme_dosya_adi}",
                        ContentFile(final_file.read()),
                        save=False  # save=False çünkü sonraki .save() ile kaydedceğiz
                    )
                
                # Makale durumunu güncelle
                makale.durum = "Değerlendirildi"
                makale.save()
                
                # ŞİMDİ DEĞERLENDİRMEYİ KİLİTLE - Database.Models.UPDATE_FIELDS kullanarak sadece kilitli alanını değiştir
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE makale_degerlendirme SET kilitli = %s WHERE id = %s", 
                        [True, mevcut_degerlendirme.id]
                    )
                
                # Log kaydı oluştur
                LogKaydi.objects.create(
                    makale=makale,
                    islem_tipi="hakem_degerlendirdi",
                    aciklama=f"{makale.baslik} makalesi değerlendirildi ve editöre gönderildi."
                )
                
                # Tüm editörlere bildirim mesajı gönder
                editorler = Kullanici.objects.filter(kullanici_tipi="editor")
                for editor in editorler:
                    try:
                        Mesaj.objects.create(
                            makale=makale,
                            gonderen=hakem,
                            alici=editor,
                            mesaj=f"Değerlendirmem tamamlandı. Lütfen değerlendirmeyi inceleyip anonimliği çözerek yazara iletiniz."
                        )
                    except Exception as e:
                        print(f"Editöre mesaj gönderme hatası: {str(e)}")
                
                messages.success(request, "Değerlendirme başarıyla kaydedildi, PDF oluşturuldu ve editöre bildirildi.")
                
            except Exception as e:
                import traceback
                print(traceback.format_exc())  # Konsola detaylı hata çıktısı
                messages.error(request, f"PDF düzenlenirken bir hata oluştu: {str(e)}")
                # PDF oluşturmada hata olsa bile değerlendirme veritabanına kaydedildi
                messages.info(request, "Değerlendirme içeriği veritabanına kaydedildi, ancak PDF oluşturulurken hata oluştu.")
            
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            messages.error(request, f"Değerlendirme sırasında beklenmeyen bir hata oluştu: {str(e)}")
        
        return redirect('hakem_paneli')

    return redirect('hakem_paneli')

def makale_goruntule(request, makale_id):
    """
    Editörün makaleyi görüntülemesini sağlar.
    Eğer makale değerlendirilmişse, değerlendirme PDF'ini metin olarak gösterir.
    Hakem değerlendirmesi bölümü değiştirilemez, makale metni değiştirilebilir.
    """
    makale = get_object_or_404(Makale, id=makale_id)
    print(f"Makale yüklendi: {makale.id} - {makale.baslik} - Durum: {makale.durum}")

    # Kullanıcı yetkilendirme kontrolü
    editor_email = request.session.get('email')
    
    # Oturum kontrolü
    if not editor_email:
        messages.error(request, "Lütfen önce giriş yapınız.")
        return redirect('anasayfa')
    
    editor = Kullanici.objects.filter(email=editor_email).first()
    if not editor:
        messages.error(request, "Kullanıcı bilgisi bulunamadı!")
        return redirect('anasayfa')

    # Anonimleştirilmiş hali var mı?
    anonimlestirme = Anonimlestirme.objects.filter(makale=makale).first()
    
    # Değerlendirme yapılmış mı kontrol et - son değerlendirmeyi al
    degerlendirme_listesi = Degerlendirme.objects.filter(makale=makale).order_by('-tarih')
    
    degerlendirme = degerlendirme_listesi.first()
    
    # Makale değerlendirilmiş mi?
    degerlendirilmis = makale.durum == "Değerlendirildi" or (degerlendirme is not None and degerlendirme.degerlendirme_icerik is not None)
    
    # Doğrudan anonimliği kaldırma butonu (değerlendirilmemiş makale için)
    if request.method == "POST" and "remove_anon" in request.POST and anonimlestirme:
        try:
            # Orijinal dosyadan metni al
            if anonimlestirme.orijinal_dosya:
                orijinal_metin = pdf_to_text(anonimlestirme.orijinal_dosya.path)
            else:
                orijinal_metin = pdf_to_text(makale.dosya.path)
            
            # Anonimleştirilmiş metni çöz
            cozulmus_metin = anonimlestirme.anonim_bilgiler
            
            # YAZAR, KURUM ve EMAIL etiketlerini değiştir
            import re
            
            # Yazar adı için orijinal metinden tespit et
            yazar_pattern = re.compile(r'([A-Z][a-z]+ [A-Z][a-z]+)')
            yazar_eslesmeler = yazar_pattern.findall(orijinal_metin[:500])  # İlk 500 karakterde ara
            
            if yazar_eslesmeler:
                yazar_adi = yazar_eslesmeler[0]
                cozulmus_metin = cozulmus_metin.replace('[YAZAR ***]', yazar_adi)
            
            # Kurum adı için basit bir tespit
            kurum_pattern = re.compile(r'(Üniversite[a-zşğıöçü]* [A-Za-zşğıöçü]+ [A-Za-zşğıöçü]+|[A-Za-zşğıöçü]+ Üniversite[a-zşğıöçü]*)')
            kurum_eslesmeler = kurum_pattern.findall(orijinal_metin[:1000])
            
            if kurum_eslesmeler:
                kurum_adi = kurum_eslesmeler[0]
                cozulmus_metin = cozulmus_metin.replace('[KURUM ***]', kurum_adi)
            else:
                cozulmus_metin = cozulmus_metin.replace('[KURUM ***]', "Kurum Adı")
            
            # E-posta adresi için regex
            email_pattern = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
            email_eslesmeler = email_pattern.findall(orijinal_metin)
            
            if email_eslesmeler:
                email_adresi = email_eslesmeler[0]
                cozulmus_metin = cozulmus_metin.replace('[EMAIL ***]', email_adresi)
            
            # Güncellenmiş metni kaydet
            anonimlestirme.anonim_bilgiler = cozulmus_metin
            anonimlestirme.save()
            
            # PDF olarak kaydet
            try:
                # Gerekli importlar
                from reportlab.pdfgen import canvas
                from reportlab.lib.pagesizes import letter
                from io import BytesIO
                from django.core.files.base import ContentFile
                
                
                # PDF dosyasını oluştur
                buffer = BytesIO()
                c = canvas.Canvas(buffer, pagesize=letter)
                
                # Başlık ekle
                c.setFont("Helvetica-Bold", 16)
                c.drawString(72, 750, f"Anonimliği Kaldırılmış Makale - {makale.baslik}")
                
                # Çözülmüş metni ekle
                c.setFont("Helvetica", 12)
                y_position = 720
                
                # Metni satırlar halinde böl
                lines = []
                for paragraph in cozulmus_metin.split('\n'):
                    words = paragraph.split()
                    current_line = ""
                    
                    for word in words:
                        if len(current_line + " " + word) < 70:  # Satır genişliği
                            current_line += " " + word if current_line else word
                        else:
                            lines.append(current_line)
                            current_line = word
                    
                    if current_line:
                        lines.append(current_line)
                    lines.append("")  # Paragraf arası boş satır
                
                # Metni sayfaya yerleştir
                for line in lines:
                    if y_position < 72:  # Sayfa sınırına yaklaştık mı?
                        c.showPage()  # Yeni sayfa
                        y_position = 750  # Y koordinatını sıfırla
                    
                    c.drawString(72, y_position, line)
                    y_position -= 15
                
                c.save()
                
                # Dosya yolları belirleme
                media_root = settings.MEDIA_ROOT
                anonim_klasoru = os.path.join(media_root, "makaleler", "anonim")
                os.makedirs(anonim_klasoru, exist_ok=True)
                
                # PDF adı
                cozulmus_pdf_adi = f"makale_{makale.id}_anonimlik_kaldirilmis.pdf"
                pdf_yolu = os.path.join(anonim_klasoru, cozulmus_pdf_adi)
                
                # Yeni PDF'i kaydet
                buffer.seek(0)
                with open(pdf_yolu, "wb") as f:
                    f.write(buffer.getvalue())
                
                # Makale nesnesine PDF'i kaydet
                with open(pdf_yolu, "rb") as f:
                    makale.anonim_dosya.save(
                        f"makaleler/anonim/{cozulmus_pdf_adi}",
                        ContentFile(f.read()),
                        save=True
                    )
                
                # Makale durumunu güncelle
                if not degerlendirilmis:
                    makale.durum = "Anonimlik Kaldırıldı"
                    makale.save()
                    anonim_etiketler_var = False
                
                # Log kaydı oluştur
                LogKaydi.objects.create(
                    makale=makale,
                    islem_tipi="anonim_kaldirildi",
                    aciklama=f"{makale.baslik} makalesinin anonimliği editör tarafından kaldırıldı."
                )
                
                messages.success(request, "Anonimlik başarıyla kaldırıldı ve PDF oluşturuldu.")
                
                # Güncellenmiş metni göstermek için değerleri güncelle
                goruntulenecek_metin = cozulmus_metin
                metin_tipi = "Anonimliği Kaldırılmış Metin"
                anonim_etiketler_var = False
                
            except Exception as e:
                import traceback
                print(traceback.format_exc())
                messages.error(request, f"PDF oluşturulurken bir hata oluştu: {str(e)}")
            
        except Exception as e:
            messages.error(request, f"Anonimlik kaldırılırken bir hata oluştu: {str(e)}")
    

    # Düzenlenmiş içeriği kaydetme işlemi
    elif request.method == "POST" and "saveEditedContent" in request.POST:
        try:
            # Form içeriğini al
            form_data = request.POST
            
            # Form alanlarını kontrol et
            for key, value in form_data.items():
                print(f"Form verisi: {key} = {value[:30] if key == 'editedContent' and value else value}")
            
            edited_content = request.POST.get("editedContent", "")
            makale_id = request.POST.get("makale_id", makale.id)
            
            # İçerik boş mu kontrol et - duzenlenebilir_metin ve goruntulenecek_metin değişkenlerini kullanmadan
            if not edited_content or edited_content.strip() == "":
                messages.error(request, "Düzenlenecek içerik boş olamaz. Lütfen metin kutusunu doldurun.")
                return redirect('makale_goruntule', makale_id=makale_id)
            
            print(f"Düzenleme kaydediliyor: makale_id={makale_id}, içerik uzunluğu={len(edited_content) if edited_content else 0}")
            
            # Anonimlestirme kaydını kontrol et ve gerekirse oluştur
            anonimlestirme = Anonimlestirme.objects.filter(makale=makale).first()
            if not anonimlestirme:
                # Anonimlestirme kaydı yoksa, yeni bir kayıt oluştur
                editor = Kullanici.objects.filter(email=editor_email, kullanici_tipi="editor").first()
                if not editor:
                    messages.error(request, "Editör bilgisi bulunamadı!")
                    return redirect('makale_goruntule', makale_id=makale_id)
                
                print(f"Anonimlestirme kaydı bulunamadı, yeni kayıt oluşturuluyor...")
                anonimlestirme = Anonimlestirme(
                    makale=makale,
                    anonim_bilgiler=edited_content,
                    editor=editor
                )
                if makale.dosya:
                    anonimlestirme.orijinal_dosya = makale.dosya
                anonimlestirme.save()
                print(f"Yeni anonimlestirme kaydı oluşturuldu, ID: {anonimlestirme.id}")
            
            # Mevcut değerlendirme ve orijinal metin
            original_content = anonimlestirme.anonim_bilgiler
            print(f"Orijinal içerik uzunluğu: {len(original_content) if original_content else 0}")
            
            # Değerlendirme metnini bul ve koru
            hakem_degerlendirme_metni = None
            final_content = edited_content
            
            if degerlendirme and degerlendirme.degerlendirme_icerik:
                print(f"Değerlendirme bulundu, ID: {degerlendirme.id}, içerik uzunluğu: {len(degerlendirme.degerlendirme_icerik)}")
                
                # Orijinal metinde değerlendirme bölümünü ara
                degerlendirme_basligi = "HAKEM DEĞERLENDİRMESİ"
                
                # Değerlendirme metnini oluştur (eğer bulunamazsa)
                standart_degerlendirme_metni = "HAKEM DEĞERLENDİRMESİ\n\n"
                standart_degerlendirme_metni += f"Tarih: {degerlendirme.tarih.strftime('%d/%m/%Y')}\n\n"
                standart_degerlendirme_metni += degerlendirme.degerlendirme_icerik
                
                if degerlendirme_basligi in original_content:
                    # Değerlendirme metnini ve sonrasını al
                    degerlendirme_baslangic = original_content.find(degerlendirme_basligi)
                    hakem_degerlendirme_metni = original_content[degerlendirme_baslangic:]
                    
                    print(f"Değerlendirme metni orijinal içerikte bulundu, pozisyon: {degerlendirme_baslangic}")
                    
                    # Değerlendirme sonrasında başka içerik var mı?
                    if "\n\n" in hakem_degerlendirme_metni[20:]:  # İlk 20 karakterden sonra çift satır
                        iki_bos_satir_index = hakem_degerlendirme_metni[20:].find("\n\n") + 20
                        hakem_degerlendirme_metni = hakem_degerlendirme_metni[:iki_bos_satir_index]
                else:
                    print(f"Değerlendirme metni orijinal içerikte bulunamadı, standart metni kullanılıyor")
                    hakem_degerlendirme_metni = standart_degerlendirme_metni
                
                print(f"Hakem değerlendirme metni uzunluğu: {len(hakem_degerlendirme_metni)}")
                
                # ÖNEMLİ: Önce düzenlenebilir içerik, sonra hakem değerlendirmesi
                final_content = edited_content + "\n\n" + hakem_degerlendirme_metni
            
            print(f"Final içerik uzunluğu: {len(final_content)}")
            
            # Metni güncelle
            anonimlestirme.anonim_bilgiler = final_content
            anonimlestirme.save()
            print(f"Anonimlestirme kaydı güncellendi, ID: {anonimlestirme.id}")
            
            # PDF olarak güncelle
            try:
                from reportlab.pdfgen import canvas
                from reportlab.lib.pagesizes import letter
                from io import BytesIO
                from django.core.files.base import ContentFile
                
                buffer = BytesIO()
                c = canvas.Canvas(buffer, pagesize=letter)
                
                # Başlık ekle
                c.setFont("Helvetica-Bold", 16)
                c.drawString(72, 750, f"{makale.baslik}")
                
                # İçeriği ekle
                c.setFont("Helvetica", 12)
                y_position = 720
                
                # Metni satırlar halinde böl
                lines = []
                for paragraph in final_content.split('\n'):
                    words = paragraph.split()
                    current_line = ""
                    
                    for word in words:
                        if len(current_line + " " + word) < 70:  # Satır genişliği
                            current_line += " " + word if current_line else word
                        else:
                            lines.append(current_line)
                            current_line = word
                    
                    if current_line:
                        lines.append(current_line)
                    lines.append("")  # Paragraf arası boş satır
                
                # Metni sayfaya yerleştir
                for line in lines:
                    if y_position < 72:  # Sayfa sınırına yaklaştık mı?
                        c.showPage()  # Yeni sayfa
                        y_position = 750  # Y koordinatını sıfırla
                    
                    c.drawString(72, y_position, line)
                    y_position -= 15
                
                c.save()
                print(f"PDF oluşturuldu, buffer uzunluğu: {buffer.getbuffer().nbytes}")
                
                # Dosya yolları belirleme
                media_root = settings.MEDIA_ROOT
                anonim_klasoru = os.path.join(media_root, "makaleler", "anonim")
                os.makedirs(anonim_klasoru, exist_ok=True)
                
                # Eski PDF'in yolunu sakla (gerekirse yedek almak için)
                eski_pdf_yolu = None
                if makale.anonim_dosya:
                    eski_pdf_yolu = makale.anonim_dosya.path
                    print(f"Eski PDF yolu: {eski_pdf_yolu}")
                
                # PDF adı - aynı ismi koruyalım ki yazar indirdiğinde aynı PDF'i görsün
                if makale.anonim_dosya:
                    pdf_adi = os.path.basename(makale.anonim_dosya.name)
                else:
                    pdf_adi = f"makale_{makale.id}_degerlendirilmis.pdf"
                
                pdf_yolu = os.path.join(anonim_klasoru, pdf_adi)
                print(f"Yeni PDF yolu: {pdf_yolu}")
                
                # Yeni PDF'i kaydet
                buffer.seek(0)
                with open(pdf_yolu, "wb") as f:
                    f.write(buffer.getvalue())
                
                print(f"PDF dosyaya kaydedildi")
                
                # Makale nesnesine PDF'i kaydet - mevcut dosyayı değiştir
                with open(pdf_yolu, "rb") as f:
                    # Eski dosya varsa sil
                    if makale.anonim_dosya:
                        makale.anonim_dosya.delete(save=False)
                    
                    # Aynı yola yeni PDF'i kaydet
                    makale.anonim_dosya.save(
                        f"makaleler/anonim/{pdf_adi}",
                        ContentFile(f.read()),
                        save=True
                    )
                
                print(f"PDF makale nesnesine kaydedildi")
                
                # Log kaydı oluştur
                log = LogKaydi.objects.create(
                    makale=makale,
                    islem_tipi="metin_guncellendi",
                    aciklama=f"{makale.baslik} makalesinin metni editör tarafından güncellendi, hakem değerlendirmesi korunarak PDF oluşturuldu."
                )
                print(f"Log kaydı oluşturuldu, ID: {log.id}")
                
                messages.success(request, "PDF'deki değişiklikler başarıyla kaydedildi. Hakem değerlendirmesi korundu.")
                
            except Exception as e:
                import traceback
                print(f"PDF oluşturma hatası: {str(e)}")
                print(traceback.format_exc())
                messages.error(request, f"PDF güncellenirken bir hata oluştu: {str(e)}")
        
        except Exception as e:
            import traceback
            print(f"Genel hata: {str(e)}")
            print(traceback.format_exc())
            messages.error(request, f"İçerik güncellenirken bir hata oluştu: {str(e)}")
    
    if (makale.durum == "Değerlendirildi" or makale.durum== 'Değerlendirildi - Anonimlik Çözüldü' or makale.durum== 'Anonimlik Çözüldü - Değerlendirildi' or makale.durum== 'Anonimlik Kaldırıldı')and makale.anonim_dosya :
        try:
            # PDF dosyasını text'e çevirme
            pdf_text = pdf_to_text(makale.anonim_dosya.path)
            goruntulenecek_metin = pdf_text
            metin_tipi = "Değerlendirilmiş PDF İçeriği"
            
            # Hakem değerlendirmesini tespit et
            hakem_degerlendirme_bolumu = None
            duzenlenebilir_metin = goruntulenecek_metin
            
            if degerlendirme and degerlendirme.degerlendirme_icerik:
                # Değerlendirme metni formatı (views.py'daki degerlendirme_ekle fonksiyonundan)
                degerlendirme_basligi = "HAKEM DEĞERLENDİRMESİ"
                
                # Değerlendirme metnini içerikte bul
                if degerlendirme_basligi in goruntulenecek_metin:
                    # Değerlendirme metnini ve sonrasını al
                    degerlendirme_baslangic = goruntulenecek_metin.find(degerlendirme_basligi)
                    hakem_degerlendirme_bolumu = goruntulenecek_metin[degerlendirme_baslangic:]
                    
                    # PDF'in içinde değerlendirme öncesi içeriği duzenlenebilir_metin'e ata
                    duzenlenebilir_metin = goruntulenecek_metin[:degerlendirme_baslangic].strip()
                    
                    print(f"Değerlendirme bölümü bulundu, başlangıç pozisyonu: {degerlendirme_baslangic}")
                    print(f"Düzenlenebilir metin uzunluğu: {len(duzenlenebilir_metin)}")
                    print(f"Hakem değerlendirme bölümü uzunluğu: {len(hakem_degerlendirme_bolumu)}")
                else:
                    # Değerlendirme metni formatını bulamazsak, ayrı bir değerlendirme içeriği olarak göster
                    hakem_degerlendirme_bolumu = degerlendirme.degerlendirme_icerik
                    print("Değerlendirme bölümü PDF'te bulunamadı, veritabanından alındı")
            
        except Exception as e:
            print(f"PDF dönüştürme hatası: {str(e)}")
            goruntulenecek_metin = f"PDF içeriği okunamadı: {str(e)}"
            metin_tipi = "Hata"
            hakem_degerlendirme_bolumu = None
            duzenlenebilir_metin = ""
    # Değerlendirme yoksa, anonim veya orijinal metni göster
    elif degerlendirilmis and degerlendirme and degerlendirme.degerlendirme_icerik:
        goruntulenecek_metin = degerlendirme.degerlendirme_icerik
        metin_tipi = "Hakem Değerlendirmesi"
        hakem_degerlendirme_bolumu = degerlendirme.degerlendirme_icerik
        duzenlenebilir_metin = ""
    elif anonimlestirme:
        goruntulenecek_metin = anonimlestirme.anonim_bilgiler
        metin_tipi = "Anonimleştirilmiş Metin"
        hakem_degerlendirme_bolumu = None
        duzenlenebilir_metin = goruntulenecek_metin
    else:
        try:
            goruntulenecek_metin = pdf_to_text(makale.dosya.path)
            metin_tipi = "Orijinal Metin"
            hakem_degerlendirme_bolumu = None
            duzenlenebilir_metin = goruntulenecek_metin
        except Exception as e:
            goruntulenecek_metin = f"Metin okunamadı: {str(e)}"
            metin_tipi = "Hata"
            hakem_degerlendirme_bolumu = None
            duzenlenebilir_metin = ""
    
    # Anonim etiketler var mı kontrolü
    anonim_etiketler_var = anonimlestirme and ('[YAZAR ***]' in anonimlestirme.anonim_bilgiler or 
                                           '[KURUM ***]' in anonimlestirme.anonim_bilgiler or 
                                           '[EMAIL ***]' in anonimlestirme.anonim_bilgiler)
    
    
    if 'deanonymize' in request.POST and anonimlestirme:
        try:
            from django.core.files.base import ContentFile
            import traceback
            
            # Dosya yolları belirleme
            media_root = settings.MEDIA_ROOT
            anonim_klasoru = os.path.join(media_root, "makaleler", "anonim")
            os.makedirs(anonim_klasoru, exist_ok=True)
            
            # Format korumalı anonimlik çözme fonksiyonunu çağır
            from .utils import dogrudan_pdf_anonim_geri_al
            
            # PDF üzerinde doğrudan işlem yap - orijinal formatı koru
            print(f"Anonimleştirmeyi çözme işlemi başlatılıyor: Makale ID={makale.id}")
            cozulmus_pdf_yolu = dogrudan_pdf_anonim_geri_al(makale, anonimlestirme)
            
            if cozulmus_pdf_yolu and os.path.exists(cozulmus_pdf_yolu):
                # PDF başarıyla oluşturuldu
                print(f"Anonimleştirme çözme başarılı: {cozulmus_pdf_yolu}")
                
                # Değerlendirme PDF adını koru - sadece sonuna "cozulmus" ekle
                dosya_adi_parcalar = os.path.splitext(os.path.basename(makale.anonim_dosya.name))
                cozulmus_pdf_adi = f"{dosya_adi_parcalar[0]}_cozulmus{dosya_adi_parcalar[1]}"
                pdf_hedef_yolu = os.path.join(anonim_klasoru, cozulmus_pdf_adi)
                
                # Geçici dosyayı hedef konuma kopyala
                import shutil
                shutil.copy2(cozulmus_pdf_yolu, pdf_hedef_yolu)
                print(f"PDF dosyası kopyalandı: {pdf_hedef_yolu}")
                
                # Makale nesnesine PDF'i kaydet
                with open(pdf_hedef_yolu, "rb") as f:
                    makale.anonim_dosya.save(
                        f"makaleler/anonim/{cozulmus_pdf_adi}",
                        ContentFile(f.read()),
                        save=True
                    )
                print(f"Yeni PDF makale nesnesine kaydedildi: {makale.anonim_dosya.path}")
                
                # Anonimlestirme veritabanı kaydını da güncelle - anonimlik çözüldü işaretleme
                anonimlestirme.anonim_bilgiler = anonimlestirme.anonim_bilgiler.replace("[YAZAR ***]", "Yazar Adı Soyadı")
                anonimlestirme.anonim_bilgiler = anonimlestirme.anonim_bilgiler.replace("[KURUM ***]", "Kurum Adı")
                anonimlestirme.anonim_bilgiler = anonimlestirme.anonim_bilgiler.replace("[EMAIL ***]", "ornek@email.com")
                anonimlestirme.save()
                
                # Makale durumunu "Değerlendirildi ve Anonimlik Çözüldü" olarak güncelle
                makale.durum = "Değerlendirildi ve Anonimlik Çözüldü"
                makale.save()
                
                # Log kaydı oluştur
                LogKaydi.objects.create(
                    makale=makale,
                    islem_tipi="anonim_cozuldu",
                    aciklama=f"{makale.baslik} makalesinin anonimliği PDF formatı korunarak çözüldü."
                )
                
                # Değerlendirmeyi de içeren PDF'i göstermek için değerleri güncelle
                goruntulenecek_metin = pdf_to_text(pdf_hedef_yolu)
                metin_tipi = "Anonimliği Çözülmüş ve Değerlendirmeyi İçeren PDF"
                anonim_etiketler_var = False
                
                messages.success(request, "Anonimlik başarıyla çözüldü ve PDF formatı korunarak dosya oluşturuldu.")
                
                # Geçici dosyayı temizle
                try:
                    os.unlink(cozulmus_pdf_yolu)
                    print(f"Geçici dosya silindi: {cozulmus_pdf_yolu}")
                except Exception as e:
                    print(f"Geçici dosya silinirken hata: {str(e)}")
            else:
                # PDF oluşturma başarısız oldu
                messages.error(request, "PDF oluşturulurken bir hata oluştu. Lütfen loglara bakınız.")
                print("Anonimleştirme çözme başarısız oldu")
        
        except Exception as e:
            import traceback
            print(f"Anonimlik çözme hatası: {str(e)}")
            print(traceback.format_exc())
            messages.error(request, f"Anonimlik çözülürken bir hata oluştu: {str(e)}")
    
    # Yazara gönder butonuna tıklandıysa
    # Yazara gönder butonuna tıklandıysa
    if 'send_to_author' in request.POST:
        try:
            # Yazara mesaj gönder
            Mesaj.objects.create(
                makale=makale,
                gonderen=editor,
                alici=makale.yazar,
                mesaj=f"Değerli Yazar, makaleniz için hakem değerlendirmesi tamamlanmıştır. Makalenizin değerlendirme sonucunu panelinizdeki 'Değerlendirme' bölümünden inceleyebilirsiniz."
            )
            
            # Makale durumunu güncelle - "Yazara Gönderildi" olarak işaretle
            makale.durum = "Yazara Gönderildi"
            makale.save()
            
            # Log kaydı
            LogKaydi.objects.create(
                makale=makale,
                islem_tipi="yazara_gonderildi",
                aciklama=f"{makale.baslik} makalesi değerlendirme sonuçlarıyla birlikte yazara gönderildi."
            )
            
            messages.success(request, "Değerlendirme sonuçları başarıyla yazara gönderildi.")
            return redirect('editor_panel')
            
        except Exception as e:
            messages.error(request, f"Yazara gönderim sırasında bir hata oluştu: {str(e)}")

   # POST işleme kodu buraya devam eder...
    
    return render(request, "makale_goruntule.html", {
        "makale": makale,
        "goruntulenecek_metin": goruntulenecek_metin,
        "metin_tipi": metin_tipi,
        "degerlendirilmis": degerlendirilmis,
        "anonim_etiketler_var": anonim_etiketler_var,
        "hakem_degerlendirme_bolumu": hakem_degerlendirme_bolumu,
        "duzenlenebilir_metin": duzenlenebilir_metin
    })

def anonimlestirme_duzenle(request, anonim_id):
    """
    Editör anonimleştirilmiş metni düzenleyebilir ve eski haline getirebilir.
    """
    anonimlestirme = get_object_or_404(Anonimlestirme, id=anonim_id)
    makale = anonimlestirme.makale

    if request.method == "POST":
        islem = request.POST.get("islem")

        if islem == "geri_al":
            # Orijinal dosyayı metne çevir ve anonimleştirilmiş metni geri al
            orijinal_metin = pdf_to_text(anonimlestirme.orijinal_dosya.path) if anonimlestirme.orijinal_dosya else ""
            anonimlestirme.anonim_bilgiler = geri_anonim_ac(anonimlestirme.anonim_bilgiler, orijinal_metin)
            anonimlestirme.save()
            return redirect('anonimlestirme_duzenle', anonim_id=anonimlestirme.id)

        elif islem == "kaydet":
            yeni_metin = request.POST.get("duzenlenmis_metin")
            anonimlestirme.anonim_bilgiler = yeni_metin
            anonimlestirme.save()
            
            # Düzenlenen metinden PDF oluştur
            try:
                from reportlab.pdfgen import canvas
                from reportlab.lib.pagesizes import letter
                from io import BytesIO
                
                buffer = BytesIO()
                c = canvas.Canvas(buffer, pagesize=letter)
                
                # Başlık ekle
                c.setFont("Helvetica-Bold", 16)
                c.drawString(72, 750, f"Anonimleştirilmiş Makale - {makale.baslik}")
                
                # Metin ekle
                c.setFont("Helvetica", 12)
                y_position = 720
                
                # Metni satırlar halinde böl
                lines = []
                for paragraph in yeni_metin.split('\n'):
                    words = paragraph.split()
                    current_line = ""
                    
                    for word in words:
                        if len(current_line + " " + word) < 70:  # Satır genişliği
                            current_line += " " + word if current_line else word
                        else:
                            lines.append(current_line)
                            current_line = word
                    
                    if current_line:
                        lines.append(current_line)
                    lines.append("")  # Paragraf arası boş satır
                
                # Metni sayfaya yerleştir
                for line in lines:
                    if y_position < 72:  # Sayfa sınırına yaklaştık mı?
                        c.showPage()  # Yeni sayfa
                        y_position = 750  # Y koordinatını sıfırla
                    
                    c.drawString(72, y_position, line)
                    y_position -= 15
                
                c.save()
                
                # Dosya yolları belirleme - Makale ID'sine göre isimlendirme
                media_root = settings.MEDIA_ROOT
                anonim_klasoru = os.path.join(media_root, "makaleler", "anonim")
                os.makedirs(anonim_klasoru, exist_ok=True)
                
                # Makale ID'sine göre dosya adı oluştur
                anonim_dosya_adi = f"anonim_makale_{makale.id}.pdf"
                anonim_pdf_yolu = os.path.join(anonim_klasoru, anonim_dosya_adi)
                
                # PDF'i kaydet
                buffer.seek(0)
                with open(anonim_pdf_yolu, "wb") as f:
                    f.write(buffer.getvalue())
                
                # Makale nesnesini güncelle
                with open(anonim_pdf_yolu, "rb") as f:
                    makale.anonim_dosya.save(
                        f"makaleler/anonim/{anonim_dosya_adi}",
                        ContentFile(f.read()),
                        save=True
                    )
                
                # Log kaydı oluştur
                LogKaydi.objects.create(
                    makale=makale,
                    islem_tipi="anonimlestirildi",
                    aciklama=f"{makale.baslik} anonimleştirmesi düzenlendi."
                )
                
                messages.success(request, "Anonimleştirme başarıyla güncellendi.")
                
            except Exception as e:
                import traceback
                print(traceback.format_exc())
                messages.error(request, f"PDF oluşturulurken bir hata oluştu: {str(e)}")
            
            return redirect('editor_panel')

    return render(request, "anonimlestirme_duzenle.html", {"anonimlestirme": anonimlestirme})

from .utils import restore_anonymized_text

def anonimlestirmeyi_geri_al(request, makale_id):
    """
    PDF kaydetme sorununu çözmek için tamamen yeniden yazılmış fonksiyon.
    Orijinal PDF'e değerlendirme sayfasını ekler ve kaydeder.
    """
    import tempfile
    import shutil
    from django.core.files.base import ContentFile
    
    try:
        # Makaleyi getir
        makale = get_object_or_404(Makale, id=makale_id)
        
        # Anonimleştirme kaydını kontrol et
        anonimlestirme = Anonimlestirme.objects.filter(makale=makale).first()
        if not anonimlestirme:
            messages.error(request, "Bu makale için anonimleştirme kaydı bulunamadı!")
            return redirect('editor_panel')
        
        if request.method == "POST":
            # Orijinal PDF'i al
            if anonimlestirme.orijinal_dosya:
                orijinal_pdf_yolu = anonimlestirme.orijinal_dosya.path
                print(f"Orijinal PDF bulundu: {orijinal_pdf_yolu}")
            elif makale.dosya:
                orijinal_pdf_yolu = makale.dosya.path
                print(f"Makale dosyası kullanılıyor: {orijinal_pdf_yolu}")
            else:
                messages.error(request, "Orijinal PDF dosyası bulunamadı!")
                return redirect('makale_goruntule', makale_id=makale.id)
            
            # Değerlendirme bilgisini al
            degerlendirme = Degerlendirme.objects.filter(makale=makale).order_by('-tarih').first()
            degerlendirme_metni = degerlendirme.degerlendirme_icerik if degerlendirme else "Değerlendirme bulunmamaktadır."
            
            # 1. İlk aşama: Geçici dosyalar için klasör oluştur
            try:
                temp_dir = tempfile.mkdtemp()
                print(f"Geçici klasör oluşturuldu: {temp_dir}")
            except Exception as e:
                print(f"Geçici klasör oluşturma hatası: {str(e)}")
                messages.error(request, f"Geçici klasör oluşturulamadı: {str(e)}")
                return redirect('makale_goruntule', makale_id=makale.id)
            
            # 2. Değerlendirme PDF'i oluştur
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            from io import BytesIO
            
            degerlendirme_pdf_yolu = os.path.join(temp_dir, "degerlendirme.pdf")
            try:
                c = canvas.Canvas(degerlendirme_pdf_yolu, pagesize=letter)
                c.setFont("Helvetica-Bold", 16)
                c.drawString(72, 750, "HAKEM DEĞERLENDİRMESİ")
                c.setFont("Helvetica", 12)
                
                y_position = 720
                for i, line in enumerate(degerlendirme_metni.split('\n')):
                    if y_position < 50:
                        c.showPage()
                        y_position = 750
                    c.drawString(72, y_position, line)
                    y_position -= 15
                
                c.save()
                print(f"Değerlendirme PDF'i kaydedildi: {degerlendirme_pdf_yolu}")
            except Exception as e:
                print(f"Değerlendirme PDF'i oluşturma hatası: {str(e)}")
                shutil.rmtree(temp_dir, ignore_errors=True)
                messages.error(request, f"Değerlendirme PDF'i oluşturulamadı: {str(e)}")
                return redirect('makale_goruntule', makale_id=makale.id)
            
            # 3. PDF'leri birleştir
            cikti_pdf_yolu = os.path.join(temp_dir, f"makale_{makale.id}_cozulmus.pdf")
            try:
                from PyPDF2 import PdfMerger
                
                merger = PdfMerger()
                merger.append(orijinal_pdf_yolu)  # Orijinal PDF ekle
                merger.append(degerlendirme_pdf_yolu)  # Değerlendirme PDF ekle
                merger.write(cikti_pdf_yolu)
                merger.close()
                
                print(f"Birleştirilmiş PDF kaydedildi: {cikti_pdf_yolu}")
                
                # PDF dosyasının varlığını ve boyutunu kontrol et
                if not os.path.exists(cikti_pdf_yolu):
                    raise FileNotFoundError(f"PDF dosyası oluşturuldu ancak bulunamadı: {cikti_pdf_yolu}")
                
                pdf_boyut = os.path.getsize(cikti_pdf_yolu)
                print(f"PDF dosya boyutu: {pdf_boyut} byte")
                
                if pdf_boyut == 0:
                    raise ValueError("PDF dosyası oluşturuldu ancak boyutu 0 byte!")
            except Exception as e:
                print(f"PDF birleştirme hatası: {str(e)}")
                shutil.rmtree(temp_dir, ignore_errors=True)
                messages.error(request, f"PDF'ler birleştirilemedi: {str(e)}")
                return redirect('makale_goruntule', makale_id=makale.id)
            
            # 4. PDF'i Django modelinde kaydet
            try:
                # Hedef klasör varlığını kontrol et ve oluştur
                media_root = settings.MEDIA_ROOT
                hedef_klasor = os.path.join(media_root, "makaleler", "anonim")
                os.makedirs(hedef_klasor, exist_ok=True)
                
                # Kalıcı dosya yolunu belirle
                kalici_dosya_adi = f"makale_{makale.id}_COZULMUS_DEGERLENDIRILMIS.pdf"
                kalici_dosya_yolu = os.path.join(hedef_klasor, kalici_dosya_adi)
                
                # Geçici dosyayı kalıcı konuma kopyala
                shutil.copy2(cikti_pdf_yolu, kalici_dosya_yolu)
                print(f"PDF kalıcı konuma kopyalandı: {kalici_dosya_yolu}")
                
                # Dosya varlığını ve boyutunu kontrol et
                if not os.path.exists(kalici_dosya_yolu):
                    raise FileNotFoundError(f"Kalıcı PDF dosyası oluşturuldu ancak bulunamadı: {kalici_dosya_yolu}")
                
                kalici_pdf_boyut = os.path.getsize(kalici_dosya_yolu)
                print(f"Kalıcı PDF dosya boyutu: {kalici_pdf_boyut} byte")
                
                # Şimdi model üzerinde kaydet - önce eski dosyayı sil
                if makale.anonim_dosya:
                    try:
                        eski_dosya_yolu = makale.anonim_dosya.path
                        makale.anonim_dosya.delete(save=False)
                        print(f"Eski PDF silindi: {eski_dosya_yolu}")
                    except Exception as e:
                        print(f"Eski PDF silinirken hata (devam ediliyor): {str(e)}")
                
                # Yeni dosyayı modelimize kaydet
                with open(kalici_dosya_yolu, 'rb') as f:
                    dosya_icerik = f.read()
                    makale.anonim_dosya.save(
                        f"makaleler/anonim/{kalici_dosya_adi}", 
                        ContentFile(dosya_icerik), 
                        save=False
                    )
                
                # Makale durumunu güncelle
                makale.durum = "Değerlendirildi - Anonimlik Çözüldü"
                makale.save()
                print(f"Makale durumu güncellendi: {makale.durum}")
                print(f"Makale PDF yolu: {makale.anonim_dosya.path}")
                
                # Log oluştur
                LogKaydi.objects.create(
                    makale=makale,
                    islem_tipi="anonim_cozuldu",
                    aciklama=f"{makale.baslik} makalesinin anonimliği çözüldü ve değerlendirme sayfası eklendi. PDF başarıyla kaydedildi."
                )
                
                messages.success(request, f"Anonimlik çözüldü ve değerlendirme eklendi. PDF başarıyla kaydedildi (Boyut: {kalici_pdf_boyut/1024:.1f} KB)")
                
            except Exception as e:
                print(f"Model kaydetme hatası: {str(e)}")
                import traceback
                print(traceback.format_exc())
                messages.error(request, f"PDF oluşturuldu ancak model güncellenirken hata: {str(e)}")
            finally:
                # Geçici dosyaları temizle
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    print(f"Geçici klasör temizlendi: {temp_dir}")
                except Exception as e:
                    print(f"Geçici dosyaları temizlerken hata (önemsiz): {str(e)}")
    
    except Exception as e:
        import traceback
        print(f"Genel hata: {str(e)}")
        print(traceback.format_exc())
        messages.error(request, f"İşlem sırasında beklenmeyen hata: {str(e)}")
    
    return redirect('makale_goruntule', makale_id=makale.id)


def orijinal_metin_goster(request, makale_id):
    """
    Anonimleştirmeyi geri aldıktan sonra orijinal metni gösteren sayfa.
    """
    makale = get_object_or_404(Makale, id=makale_id)
    orijinal_metin = pdf_to_text(makale.dosya.path)  # Orijinal PDF içeriğini çıkar

    return render(request, "orijinal_metin_goster.html", {
        "makale": makale,
        "orijinal_metin": orijinal_metin
    })

def mesaj_paneli(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)
    mesajlar = Mesaj.objects.filter(makale=makale).order_by('tarih')

    # **Yalnızca yazar ve editörler listelenir**
    yazarlar = Kullanici.objects.filter(kullanici_tipi="yazar")
    editorler = Kullanici.objects.filter(kullanici_tipi="editor").first()

    return render(request, 'mesaj_paneli.html', {
        'makale': makale,
        'mesajlar': mesajlar,
        'yazarlar': yazarlar,
        'editor': editorler
    })


@csrf_exempt
def mesaj_gonder(request, makale_id):
    if request.method == "POST":
        makale = get_object_or_404(Makale, id=makale_id)
        mesaj_icerik = request.POST.get("mesaj", "").strip()
        alici_id = request.POST.get("alici_id")
        
        # Gönderici bilgisini oturumdan al
        gonderen_email = request.session.get('email')
        if not gonderen_email:
            return JsonResponse({"status": "error", "message": "Oturum bilgisi bulunamadı!"}, status=400)
            
        gonderen = get_object_or_404(Kullanici, email=gonderen_email)

        if not mesaj_icerik or not alici_id:
            return JsonResponse({"status": "error", "message": "Mesaj veya alıcı eksik!"}, status=400)

        alici = get_object_or_404(Kullanici, id=alici_id)

        # Mesaj yetkilendirmesi kontrolü
        if gonderen.kullanici_tipi == "yazar" and alici.kullanici_tipi != "editor":
            return JsonResponse({"status": "error", "message": "Yazar sadece editöre mesaj gönderebilir!"}, status=403)
        elif gonderen.kullanici_tipi == "editor" and alici.kullanici_tipi != "yazar":
            return JsonResponse({"status": "error", "message": "Editör sadece yazarlara mesaj gönderebilir!"}, status=403)

        # Mesajı kaydet
        yeni_mesaj = Mesaj.objects.create(
            makale=makale,
            gonderen=gonderen,
            alici=alici,
            mesaj=mesaj_icerik
        )

        return JsonResponse({
            "status": "success",
            "mesaj": yeni_mesaj.mesaj,
            "gonderen": gonderen.email,
            "alici": alici.email,
            "tarih": yeni_mesaj.tarih.strftime("%Y-%m-%d %H:%M")
        })

    return JsonResponse({"status": "error", "message": "Geçersiz istek!"}, status=400)

from .utils import anonymize_with_encryption
def anonimlestirme_yap(request, makale_id):
    """
    IEEE makalelerini doğrudan PDF üzerinde anonimleştiren fonksiyon.
    Kullanıcı arayüzünden seçilen alanları anonimleştirir ve insan yüzlerini bulanıklaştırabilir.
    Orijinal verileri SHA-256 ile şifreleyerek saklar.
    """
    from django.conf import settings
    import os, json, traceback
    from django.core.files import File
    from .utils import dogrudan_pdf_anonimlestir, process_pdf_images, insert_blurred_images_to_pdf

    makale = get_object_or_404(Makale, id=makale_id)

    if request.method == "POST":
        pdf_path = makale.dosya.path

        # Arayüzden seçilen anonimleştirme seçeneklerini al
        anonim_yazar = 'anonim_yazar' in request.POST
        anonim_kurum = 'anonim_kurum' in request.POST
        anonim_email = 'anonim_email' in request.POST
        anonim_yuzler = 'anonim_yuzler' in request.POST or 'anonim_yuz' in request.POST

        try:
            # Editor bilgisini al
            editor_email = request.session.get('email')
            editor = Kullanici.objects.filter(email=editor_email).first()

            if not editor:
                messages.error(request, "Anonimleştirme işlemi için giriş yapmalısınız.")
                return redirect('anasayfa')

            # Önce metin olarak anonimleştirme yap
            metin = pdf_to_text(pdf_path)

            # Her makale için benzersiz bir şifreleme anahtarı oluştur
            encryption_password = f"makale_{makale.id}_{makale.makale_takip_no}"
            anonim_metin, encrypted_data = anonymize_with_encryption(
                metin,
                encryption_password,
                anonymize_author=anonim_yazar,
                anonymize_institution=anonim_kurum,
                anonymize_email=anonim_email
            )

            encrypted_data_json = json.dumps(encrypted_data)

            anonimlestirme = Anonimlestirme.objects.filter(makale=makale).first()
            if anonimlestirme:
                anonimlestirme.anonim_bilgiler = anonim_metin
                anonimlestirme.orijinal_dosya = makale.dosya
                anonimlestirme.editor = editor
                anonimlestirme.sifreli_veriler = encrypted_data_json
                anonimlestirme.save()
            else:
                anonimlestirme = Anonimlestirme.objects.create(
                    makale=makale,
                    anonim_bilgiler=anonim_metin,
                    orijinal_dosya=makale.dosya,
                    editor=editor,
                    sifreli_veriler=encrypted_data_json
                )

            anonim_klasoru = os.path.join(settings.MEDIA_ROOT, "makaleler", "anonim")
            os.makedirs(anonim_klasoru, exist_ok=True)

            anonim_dosya_adi = f"anonim_makale_{makale.id}.pdf"
            anonim_pdf_yolu = os.path.join(anonim_klasoru, anonim_dosya_adi)

            # PDF'ten kişisel bilgileri sil
            dogrudan_pdf_anonimlestir(
                pdf_path,
                anonim_pdf_yolu,
                anonim_yazar,
                anonim_kurum,
                anonim_email,
                False  # yüzler burada değil, aşağıda yapılacak
            )

            # 📌 Yüz bulanıklaştırmayı burada yap (eğer istenmişse)
            if anonim_yuzler:
                blur_dir = process_pdf_images(anonim_pdf_yolu)
                yeni_yol = insert_blurred_images_to_pdf(anonim_pdf_yolu, blur_dir)
                if os.path.exists(yeni_yol):
                    anonim_pdf_yolu = yeni_yol

            # PDF'i makale nesnesine kaydet
            with open(anonim_pdf_yolu, 'rb') as f:
                makale.anonim_dosya.save(f"makaleler/anonim/{anonim_dosya_adi}", File(f), save=False)

            makale.durum = "Anonimleştirildi"
            makale.save()

            anonim_alanlar = []
            if anonim_yazar: anonim_alanlar.append("Yazar bilgileri")
            if anonim_kurum: anonim_alanlar.append("Kurum bilgileri")
            if anonim_email: anonim_alanlar.append("Email adresleri")
            if anonim_yuzler: anonim_alanlar.append("İnsan yüzleri bulanıklaştırıldı")
            anonim_aciklama = ", ".join(anonim_alanlar) if anonim_alanlar else "Hiçbir alan"

            LogKaydi.objects.create(
                makale=makale,
                islem_tipi="anonimlestirildi",
                aciklama=f"{makale.baslik} IEEE formatı korunarak PDF üzerinde doğrudan anonimleştirildi. Anonimleştirilen alanlar: {anonim_aciklama}. SHA-256 ile şifrelendi."
            )

            messages.success(request, f"Makale başarıyla anonimleştirildi, IEEE formatı korundu ve veriler SHA-256 ile şifrelendi. Anonimleştirilen alanlar: {anonim_aciklama}.")

            return render(request, "anonimlestirme_sonuc.html", {
                "anonimlestirme": anonimlestirme,
                "anonim_metin": anonimlestirme.anonim_bilgiler,
                "anonim_yazar": anonim_yazar,
                "anonim_kurum": anonim_kurum,
                "anonim_email": anonim_email,
                "anonim_yuzler": anonim_yuzler,
                "sifreli": True
            })

        except Exception as e:
            print(traceback.format_exc())
            return render(request, "anonimlestirme_hata.html", {"hata": str(e)})

    return render(request, "anonimlestirme.html", {"makale": makale})
def ana_sayfa(request):
    if request.method == "POST":
        email = request.POST.get("email")
        
        # E-posta format kontrolü
        email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        
        if not re.match(email_regex, email):
            return render(request, "anasayfa.html", {"hata": "E-posta uygun formatta değil!"})
        
        try:
            kullanici = Kullanici.objects.get(email=email)
            # Oturum bilgilerini kaydet
            request.session['email'] = email
            request.session['kullanici_tipi'] = kullanici.kullanici_tipi
            
            if kullanici.kullanici_tipi == "yazar":
                makaleler = Makale.objects.filter(yazar=kullanici)
                return render(request, "yazar.html", {"makaleler": makaleler, "email": email})
            elif kullanici.kullanici_tipi == "editor":
                return redirect('editor_panel')
            elif kullanici.kullanici_tipi == "hakem":
                # Ana sayfada yönlendirmeyi yap, verileri hakem_paneli'nde al
                return redirect('hakem_paneli')
            else:
                return render(request, "anasayfa.html", {"hata": "Geçersiz kullanıcı tipi!"})
        
        except Kullanici.DoesNotExist:
            return render(request, "anasayfa.html", {"hata": "Kullanıcı bulunamadı!"})
    
    return render(request, "anasayfa.html")

def hakem_paneli(request):
    hakem_email = request.session.get('email')
    if not hakem_email:
        messages.error(request, "Oturum açmalısınız!")
        return redirect('anasayfa')

    hakem = get_object_or_404(Kullanici, email=hakem_email)
    
    # Hakemin atandığı tüm makaleleri al (atanan_hakem_id ile eşleşenler)
    atanan_makaleler = Makale.objects.filter(atanan_hakem=hakem)
    
    # DEBUG: Kontrol yazdırması
    print(f"Hakem: {hakem_email}, Atanan makale sayısı: {atanan_makaleler.count()}")
    for makale in atanan_makaleler:
        print(f"Makale ID: {makale.id}, Başlık: {makale.baslik}, Durum: {makale.durum}")
    
    return render(request, 'hakem.html', {"makaleler": atanan_makaleler})


def makale_indir(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)
    file_path = makale.dosya.path
    if os.path.exists(file_path):
        file_ext = os.path.splitext(file_path)[1]
        dosya_adi = f"{makale.baslik}{file_ext}"
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = "application/octet-stream"
        
        with open(file_path, 'rb') as dosya:
            response = HttpResponse(dosya.read(), content_type=mime_type)
            response['Content-Disposition'] = f'attachment; filename="{dosya_adi}"'
            return response
    else:
        raise Http404("Dosya bulunamadı.")


def makale_yukle(request):
    if request.method == "POST":
        form = MakaleYuklemeForm(request.POST, request.FILES)
        if form.is_valid():
            email = form.cleaned_data["email"]
            with transaction.atomic():
                kullanici = Kullanici.objects.filter(email=email).first()
                if not kullanici:
                    kullanici = Kullanici.objects.create(email=email, kullanici_tipi="yazar")
                makale = form.save(commit=False)
                makale.yazar = kullanici
                makale.makale_takip_no = uuid.uuid4()

                # 📌 Dosya gerçekten var mı kontrol et
                if 'dosya' in request.FILES:
                    makale.dosya = request.FILES['dosya']
                else:
                    return render(request, "makale_yukle.html", {"form": form, "hata": "Dosya yüklenmedi!"})

                makale.save()

                # ✅ Dosyanın gerçekten kaydedildiğini kontrol et
                if not default_storage.exists(makale.dosya.path):
                    return render(request, "makale_yukle.html", {"form": form, "hata": "Dosya kaydedilemedi!"})

            return render(request, "makale_yuklendi.html", {"makale": makale, "email": email})
        else:
            return render(request, "makale_yukle.html", {"form": form, "hata": form.errors})
    else:
        form = MakaleYuklemeForm()
    return render(request, "makale_yukle.html", {"form": form})

def editor_panel(request):
    makaleler = Makale.objects.all()  # Veritabanındaki tüm makaleleri çekiyoruz
    return render(request, 'editor_panel.html', {'makaleler': makaleler})

from django.shortcuts import render, get_object_or_404
from .models import Makale, Anonimlestirme, Kullanici, LogKaydi
from .utils import pdf_to_text, anonimlestir

def makale_detay(request, makale_id):
    """Editörün makale detayını görmesini ve anonimleştirme işlemini yapmasını sağlar."""
    makale = get_object_or_404(Makale, id=makale_id)

    if request.method == "POST":
        anonim_yazar = "anonim_yazar" in request.POST
        anonim_kurum = "anonim_kurum" in request.POST
        anonim_email = "anonim_email" in request.POST

        pdf_path = makale.dosya.path
        metin = pdf_to_text(pdf_path)

        if metin.startswith("Hata:"):
            return render(request, "anonimlestirme_hata.html", {"hata": metin})

        anonim_metin = anonimlestir(metin, anonim_yazar, anonim_kurum, anonim_email)

        editor = Kullanici.objects.filter(kullanici_tipi="editor").first()

        anonim_kayit = Anonimlestirme.objects.create(
            makale=makale,
            anonim_bilgiler=anonim_metin,
            editor=editor
        )

        makale.durum = "Anonimleştirildi"
        makale.save()

        LogKaydi.objects.create(
            makale=makale,
            islem_tipi="anonimlestirildi",
            aciklama=f"{makale.baslik} anonimleştirildi."
        )

        return render(request, "anonimlestirme_sonuc.html", {"anonim_metin": anonim_kayit.anonim_bilgiler})

    return render(request, "makale_detay.html", {"makale": makale})



def hakem_atama(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)
    hakemler = Kullanici.objects.filter(kullanici_tipi='hakem')

    skorlu_hakemler = uygun_hakem_bul(pdf_to_text(makale.dosya.path), hakemler, max_sayi=5)

    if request.method == "POST":
        hakem_email = request.POST.get("hakem_email")
        hakem = get_object_or_404(Kullanici, email=hakem_email)

        Degerlendirme.objects.create(makale=makale, hakem=hakem)

        makale.durum = "Değerlendirilmeye Gönderildi"
        makale.atanan_hakem = hakem
        makale.save()

        messages.success(request, "Hakem ataması başarıyla gerçekleştirildi.")
        return redirect('editor_panel')

    return render(request, "hakem_atama.html", {
        "makale": makale,
        "hakemler": [h[0] for h in skorlu_hakemler],
        "skorlar": {h[0].email: round(h[1]*100, 2) for h in skorlu_hakemler}  # Skorları yüzde olarak verir
    })


def log_kaydi_goruntule(request):
    """Editörün sistemde yapılan tüm işlemleri görmesini sağlar."""
    loglar = LogKaydi.objects.all().order_by('-tarih')
    return render(request, "log_kaydi.html", {"loglar": loglar})

def makale_takip(request):
    """
    Makalenin takibini sağlayan ve editörle mesajlaşma özelliği sunan fonksiyon.
    Kullanıcı makale takip numarası ile makalesi hakkında durum kontrolü yapabilir
    ve editörle mesajlaşabilir.
    """
    takip_no = request.GET.get("takip_no", None)
    makale = None
    mesajlar = []
    loglar = []

    if takip_no:
        try:
            makale = Makale.objects.filter(makale_takip_no=takip_no).first()
            
            if makale:
                # Oturum bilgisini geçici olarak kaydet
                request.session['email'] = makale.yazar.email
                request.session['kullanici_tipi'] = 'yazar'
                
                # Makaleyle ilgili mesajları al
                mesajlar = Mesaj.objects.filter(makale=makale).order_by('tarih')
                
                # Makaleyle ilgili log kayıtlarını al
                loglar = LogKaydi.objects.filter(makale=makale).order_by('-tarih')
        except:
            # Hatalı takip numarası durumunda
            makale = None
            mesajlar = []
            loglar = []

    return render(request, "makale_takip.html", {
        "makale": makale,
        "mesajlar": mesajlar,
        "loglar": loglar
    })


def takip_mesaj_gonder(request):
    """
    Makale takip sayfasından editöre mesaj göndermeyi sağlayan fonksiyon.
    """
    if request.method != "POST":
        return redirect('makale_takip')
    
    makale_id = request.POST.get("makale_id")
    mesaj_icerik = request.POST.get("mesaj", "").strip()
    takip_no = request.POST.get("takip_no", "")
    
    if not makale_id or not mesaj_icerik:
        messages.error(request, "Mesaj veya makale bilgisi eksik!")
        return redirect('makale_takip')
    
    try:
        makale = Makale.objects.get(id=makale_id)
        
        # Yazar bilgisini al
        yazar = makale.yazar
        
        # Editörü bul (ilk editörü alıyoruz)
        editor = Kullanici.objects.filter(kullanici_tipi="editor").first()
        
        if not editor:
            messages.error(request, "Sistem editörü bulunamadı!")
            return redirect('makale_takip')
        
        # Mesajı oluştur
        Mesaj.objects.create(
            makale=makale,
            gonderen=yazar,
            alici=editor,
            mesaj=mesaj_icerik
        )
        
        messages.success(request, "Mesajınız editöre başarıyla gönderildi.")
    except Makale.DoesNotExist:
        messages.error(request, "Makale bulunamadı!")
    except Exception as e:
        messages.error(request, f"Mesaj gönderilirken bir hata oluştu: {str(e)}")
    
    # Takip numarası ile makale takip sayfasına yönlendir
    return redirect(f'/makale/takip/?takip_no={takip_no}')

def alan_atama_goruntule(request, makale_id):
    makale = get_object_or_404(Makale, id=makale_id)

    if not makale.dosya or not makale.dosya.name:
        return render(request, "alan_atama_hata.html", {"hata": "Makale dosyası eksik!"})

    pdf_path = makale.dosya.path

    if not os.path.exists(pdf_path):
        return render(request, "alan_atama_hata.html", {"hata": f"Dosya bulunamadı: {pdf_path}"})

    makale_metin = pdf_to_text(pdf_path)

    if not makale_metin.strip():
        return render(request, "alan_atama_hata.html", {"hata": "Makale metni boş!"})

    tahmini_alan = alan_atama_nlp(makale_metin)

    makale.alan = tahmini_alan
    makale.save()

    return render(request, "alan_atama_sonuc.html", {
        "makale": makale,
        "alan": tahmini_alan,
        "anahtar_kelimeler": anahtar_kelime_cikar(makale_metin, n=10)
    })