from django.db import models
import uuid
from django.utils.timezone import now



class Kullanici(models.Model):
    KULLANICI_TIPLERI = [
        ('yazar', 'Yazar'),
        ('editor', 'Editör'),
        ('hakem', 'Hakem'),
    ]

    email = models.EmailField(unique=True)  # Kullanıcı giriş yapmayacak ama e-posta doğrulama için kullanılacak
    kullanici_tipi = models.CharField(max_length=50, choices=KULLANICI_TIPLERI)
    ilgi_alanlari = models.TextField(blank=True, null=True)  # Hakemlerin uzmanlık alanlarını saklamak için

    def __str__(self):
        return f"{self.email} ({self.kullanici_tipi})"


class Makale(models.Model):
    DURUM_SECENEKLERI = [
        ('Yüklendi', 'Yüklendi'),
        ('Anonimleştirildi', 'Anonimleştirildi'),
        ('Değerlendirmeye Gönderildi', 'Değerlendirmeye Gönderildi'),
        ('Değerlendirildi', 'Değerlendirildi'),
        ('Değerlendirildi ve Anonimlik Çözüldü', 'Değerlendirildi ve Anonimlik Çözüldü'),
        ('Değerlendirildi - Anonimlik Çözüldü', 'Değerlendirildi - Anonimlik Çözüldü'),
        ('Anonimlik Çözüldü - Değerlendirildi', 'Anonimlik Çözüldü - Değerlendirildi'),
        ('Anonimlik Kaldırıldı', 'Anonimlik Kaldırıldı'),
        ('Yazara Gönderildi', 'Yazara Gönderildi'),
        ('Revize Edildi', 'Revize Edildi'),
        ('Yayınlandı', 'Yayınlandı'),
    ]

    makale_takip_no = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)  # Takip numarası UUID ile oluşturulacak
    baslik = models.CharField(max_length=255)
    dosya = models.FileField(upload_to='makaleler/orijinal/')  # Orijinal makale dosyası buraya yüklenecek
    anonim_dosya = models.FileField(upload_to='makaleler/anonim/', blank=True, null=True)  # Anonimleştirilmiş versiyon
    durum = models.CharField(max_length=50, choices=DURUM_SECENEKLERI, default='Yüklendi')
    yazar = models.ForeignKey(Kullanici, on_delete=models.CASCADE, related_name='makaleler')
    alan = models.CharField(max_length=100, blank=True, null=True)
    atanan_hakem = models.ForeignKey(Kullanici, on_delete=models.SET_NULL, null=True, blank=True, related_name="hakem_atanan_makaleler")
    yuklenme_tarihi = models.DateTimeField(default=now)  # Makalenin yüklenme tarihi
    ozet = models.TextField(blank=True, null=True)  # Makale özeti

    def __str__(self):
        return f"Makale {self.baslik} - {self.durum}"


class Anonimlestirme(models.Model):
    makale = models.ForeignKey(Makale, on_delete=models.CASCADE)
    anonim_bilgiler = models.TextField()  # Anonimleştirilen metin veya bilgileri tutar
    editor = models.ForeignKey(Kullanici, on_delete=models.CASCADE, related_name='anonimlestirmeler')
    orijinal_dosya = models.FileField(upload_to='makaleler/orijinal_kopya/', blank=True, null=True)  # Editör isterse geri alabilsin
    tarih = models.DateTimeField(auto_now_add=True)
    # Şifrelenmiş veri alanı ekleniyor - JSON formatında şifrelenmiş veri
    sifreli_veriler = models.TextField(blank=True, null=True)  # SHA-256 ile şifrelenmiş orijinal veriler

    def __str__(self):
        return f"Anonimleştirme {self.id} - Makale {self.makale.baslik}"


class Degerlendirme(models.Model):
    makale = models.ForeignKey(Makale, on_delete=models.CASCADE)
    hakem = models.ForeignKey(Kullanici, on_delete=models.CASCADE, related_name='degerlendirmeler')
    degerlendirme_icerik = models.TextField(null=True, blank=True)
    kilitli = models.BooleanField(default=False)  # Editör değiştiremesin
    tarih = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        """Değerlendirme kaydedildikten sonra editör tarafından değiştirilemez."""
        if self.kilitli:
            raise ValueError("Bu değerlendirme değiştirilemez.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Değerlendirme {self.id} - Makale {self.makale.baslik}"


class LogKaydi(models.Model):
    ISLEM_TIPLERI = [
        ('yuklendi', 'Yüklendi'),
        ('anonimlestirildi', 'Anonimleştirildi'),
        ('hakeme_gonderildi', 'Hakeme Gönderildi'),
        ('hakem_degerlendirdi', 'Hakem Değerlendirdi'),
        ('anonim_cozuldu', 'Anonimlik Çözüldü'),
        ('yazara_gonderildi', 'Yazara Gönderildi'),
        ('editor_geri_yukledi', 'Editör Geri Yükledi'),
        ('yayınlandı', 'Yayınlandı'),
    ]

    makale = models.ForeignKey(Makale, on_delete=models.CASCADE)
    islem_tipi = models.CharField(max_length=50, choices=ISLEM_TIPLERI)
    aciklama = models.TextField(null=True, blank=True)
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Log {self.id} - {self.islem_tipi} - Makale {self.makale.baslik}"


class Mesaj(models.Model):
    makale = models.ForeignKey(Makale, on_delete=models.CASCADE, related_name='mesajlar')
    gonderen = models.ForeignKey(Kullanici, on_delete=models.CASCADE, related_name='gonderilen_mesajlar')
    alici = models.ForeignKey(Kullanici, on_delete=models.CASCADE, related_name='alinan_mesajlar')
    mesaj = models.TextField()
    tarih = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Mesaj {self.id} - {self.gonderen.email} -> {self.alici.email}"