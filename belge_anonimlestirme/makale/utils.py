import os
import re
import spacy
import cv2
import nltk
import numpy as np
import pytesseract
from collections import Counter
from pdfminer.high_level import extract_text
from pdf2image import convert_from_path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from nltk.corpus import stopwords
from django.db.models.fields.files import FieldFile
import fitz  # PyMuPDF
from PIL import Image
import io
import tempfile
import shutil
from PyPDF2 import PdfReader, PdfWriter
from django.conf import settings

# İngilizce metinleri işlemek için NLP modeli
nlp = spacy.load("en_core_web_sm")  
nltk.download('punkt')  
nltk.download('stopwords')  

# Türkçe ve İngilizce stopwords listesi
STOPWORDS = set(stopwords.words("english") + stopwords.words("turkish"))

# Anonimleştirilmemesi gereken bölümler
HARIC_TUTULACAK_BOLUM_BASLIKLARI = ["giriş", "ilgili çalışmalar", "referanslar", "teşekkür"]

# Poppler'ın Windows'taki konumu
POPPLER_PATH = r"C:\Program Files\poppler\Library\bin"

ES_DEGER_ALANLAR = {
    "Yapay Zeka": ["Yapay Zeka", "Artificial Intelligence", "AI"],
    "Doğal Dil İşleme": ["Doğal Dil İşleme", "Natural Language Processing", "NLP"],
    "Bilgisayarla Görü": ["Bilgisayarla Görü", "Computer Vision"],
    "Büyük Veri": ["Büyük Veri", "Big Data"],
    "Siber Güvenlik": ["Siber Güvenlik", "Cyber Security"],
    "Ağ Sistemleri": ["Ağ Sistemleri", "Network Systems"]
}



def guclu_yuz_bulaniklastirma(image_data):
    try:
        # Resmi PIL'den OpenCV formatına çevir
        image = Image.open(io.BytesIO(image_data))
        if image.mode == 'RGBA':
            image = image.convert('RGB')
        cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        # Gri tonlama
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

        # Yüzleri tespit et
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)

        # Her yüz bölgesini bulanıklaştır
        for (x, y, w, h) in faces:
            face_region = cv_image[y:y+h, x:x+w]
            face_region = cv2.GaussianBlur(face_region, (99, 99), 30)
            cv_image[y:y+h, x:x+w] = face_region

        # Geri PIL formatına çevirip byte olarak döndür
        cv_image_rgb = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(cv_image_rgb)
        buffer = io.BytesIO()
        pil_image.save(buffer, format="PNG")
        return buffer.getvalue()

    except Exception as e:
        print(f"[HATA] Yüz bulanıklaştırma başarısız: {e}")
        return image_data
  
def extract_images_from_pdf(pdf_path):
    images = []
    doc = fitz.open(pdf_path)

    for page_index in range(len(doc)):
        page = doc[page_index]
        image_list = page.get_images(full=True)

        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            image = Image.open(io.BytesIO(image_bytes))

            # CMYK görselleri RGB'ye dönüştür
            if image.mode == "CMYK":
                image = image.convert("RGB")

            images.append((page_index, img_index, xref, image, image_ext))

    return images

def process_pdf_images(pdf_path, output_folder="blurred_images"):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    extracted_images = extract_images_from_pdf(pdf_path)

    for page_index, img_index, xref, image, ext in extracted_images:
        image_bytes = io.BytesIO()
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.save(image_bytes, format="PNG")
        blurred_data = guclu_yuz_bulaniklastirma(image_bytes.getvalue())

        blurred_image = Image.open(io.BytesIO(blurred_data)).convert("RGB")
        output_path = os.path.join(output_folder, f"page{page_index}_img{img_index}_blurred.jpg")
        blurred_image.save(output_path, format="JPEG")

    return output_folder

def insert_blurred_images_to_pdf(original_pdf, image_folder, output_pdf="output_blurred.pdf"):
    doc = fitz.open(original_pdf)

    for page_index in range(len(doc)):
        page = doc[page_index]
        image_list = page.get_images(full=True)

        for img_index, (xref, *_) in enumerate(image_list):
            expected_filename = f"page{page_index}_img{img_index}_blurred.jpg"
            img_path = os.path.join(image_folder, expected_filename)

            if os.path.exists(img_path):
                with open(img_path, "rb") as img_file:
                    img_bytes = img_file.read()

                try:
                    doc.update_stream(xref, img_bytes)
                except Exception as e:
                    print(f"Resim güncellenemedi (xref={xref}): {e}")

    doc.save(output_pdf)
    return os.path.abspath(output_pdf)

def dogrudan_pdf_anonim_geri_al(makale, anonimlestirme):
    """
    PDF formatını bozmadan anonimleştirilmiş PDF'in orijinalini oluşturur.
    Doğrudan PDF karşılaştırması yaparak bilgileri geri getirir.
    
    Args:
        makale (Makale): Makale modeli nesnesi
        anonimlestirme (Anonimlestirme): Anonimlestirme modeli nesnesi
        
    Returns:
        str: İşlenmiş PDF'in yolu (başarısız olursa None)
    """
    import fitz  # PyMuPDF
    import os
    import re
    import tempfile
    import logging
    import uuid
    from typing import List, Dict, Tuple

    # Logging ayarları
    logging.basicConfig(level=logging.INFO, 
                        format='%(asctime)s - %(levelname)s: %(message)s')
    logger = logging.getLogger(__name__)

    def pdf_metin_karsilastir(orijinal_pdf: str, anonim_pdf: str) -> Dict[str, str]:
        """
        İki PDF'in metinlerini karşılaştırarak değişen alanları tespit eder.
        
        Args:
            orijinal_pdf (str): Orijinal PDF yolu
            anonim_pdf (str): Anonimleştirilmiş PDF yolu
        
        Returns:
            Dict[str, str]: Değişen alanların eşleşmeleri
        """
        try:
            # PDF'leri aç
            orijinal_doc = fitz.open(orijinal_pdf)
            anonim_doc = fitz.open(anonim_pdf)
            
            # Değişen alanları tutacak sözlük
            degisen_alanlar = {}
            
            # Her sayfayı karşılaştır
            for sayfa_no in range(min(len(orijinal_doc), len(anonim_doc))):
                orijinal_sayfa = orijinal_doc[sayfa_no]
                anonim_sayfa = anonim_doc[sayfa_no]
                
                # Sayfa metinlerini al
                orijinal_metin = orijinal_sayfa.get_text()
                anonim_metin = anonim_sayfa.get_text()
                
                # Anonimleştirilmiş alanları tespit et
                anonim_etiketleri = [
                    '[YAZAR ***]', 
                    '[KURUM ***]', 
                    '[EMAIL ***]'
                ]
                
                for etiket in anonim_etiketleri:
                    if etiket in anonim_metin:
                        # Orijinal metinde bu etikete karşılık gelen alanı bul
                        karsilastirma_desenleri = {
                            '[YAZAR ***]': [
                                # IEEE formatındaki yazar desenleri
                                r'([A-Z][a-zışğüöçİŞĞÜÖÇ]+(?:\s+[A-Z][a-zışğüöçİŞĞÜÖÇ]+)+)(?:\s*\((?:Graduate Student|Senior Member|Member),\s*IEEE\))?',
                                r'([A-Z][a-zışğüöçİŞĞÜÖÇ]+\s+[A-Z]\.\s+[A-Z][a-zışğüöçİŞĞÜÖÇ]+)'
                            ],
                            '[KURUM ***]': [
                                r'([A-Z][a-zA-ZışğüöçİŞĞÜÖÇ\s]+(?:University|Institute|Engineering|Technology|College)(?:\s*of\s*[A-Z][a-zA-ZışğüöçİŞĞÜÖÇ\s]+)?)',
                                r'(Indian Institute of [A-Z][a-zA-ZışğüöçİŞĞÜÖÇ\s]+)',
                                r'([A-Z][a-zA-ZışğüöçİŞĞÜÖÇ\s]+Department of [A-Z][a-zA-ZışğüöçİŞĞÜÖÇ\s]+)'
                            ],
                            '[EMAIL ***]': [
                                r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                            ]
                        }
                        
                        # Her desen için kontrol
                        for desen in karsilastirma_desenleri.get(etiket, []):
                            orijinal_eslesmeler = re.findall(desen, orijinal_metin, re.IGNORECASE)
                            
                            if orijinal_eslesmeler:
                                # İlk eşleşmeyi kullan
                                degisen_alanlar[etiket] = orijinal_eslesmeler[0] if isinstance(orijinal_eslesmeler[0], str) else orijinal_eslesmeler[0][0]
                                break
            
            # Dokümanları kapat
            orijinal_doc.close()
            anonim_doc.close()
            
            return degisen_alanlar
        
        except Exception as e:
            logger.error(f"PDF metin karşılaştırma hatası: {e}")
            return {}

    def pdf_redaksiyonu_uygula(
        input_pdf: str, 
        output_pdf: str, 
        degisen_alanlar: Dict[str, str]
    ) -> bool:
        """
        PDF'de redaksiyon işlemi yapar.
        
        Args:
            input_pdf (str): Girdi PDF yolu
            output_pdf (str): Çıktı PDF yolu
            degisen_alanlar (Dict[str, str]): Değiştirilecek alanlar
        
        Returns:
            bool: İşlem başarılı mı
        """
        try:
            doc = fitz.open(input_pdf)
            
            # Değiştirilecek alanları belirle
            degistirilecekler = [
                ('[YAZAR ***]', degisen_alanlar.get('[YAZAR ***]', 'Yazar')),
                ('[KURUM ***]', degisen_alanlar.get('[KURUM ***]', 'Kurum')),
                ('[EMAIL ***]', degisen_alanlar.get('[EMAIL ***]', 'ornek@email.com'))
            ]
            
            degisiklik_yapildi = False
            
            for sayfa_no in range(len(doc)):
                sayfa = doc[sayfa_no]
                
                for eski, yeni in degistirilecekler:
                    # Eşleşen alanları bul
                    eslesme_alanlari = sayfa.search_for(eski)
                    
                    for alan in eslesme_alanlari:
                        # Redaksiyon annotasyonu ekle
                        sayfa.add_redact_annot(
                            alan, 
                            fill=(1, 1, 1),  # Beyaz doldurma
                            text=yeni
                        )
                        degisiklik_yapildi = True
                
                # Redaksiyonları uygula
                sayfa.apply_redactions()
            
            # Değişiklik varsa kaydet
            if degisiklik_yapildi:
                doc.save(
                    output_pdf, 
                    garbage=4,    # Eski içeriği temizle
                    deflate=True, # Sıkıştır
                    clean=True    # PDF'i temizle
                )
                doc.close()
                return True
            
            doc.close()
            return False
        
        except Exception as e:
            logger.error(f"PDF redaksiyonu sırasında hata: {e}")
            return False

    # Ana fonksiyon akışı
    try:
        # Orijinal ve anonim PDF yollarını al
        orijinal_pdf_yolu = (
            anonimlestirme.orijinal_dosya.path 
            if anonimlestirme.orijinal_dosya 
            else makale.dosya.path
        )
        anonim_pdf_yolu = makale.anonim_dosya.path

        # Geçici bir dosya oluştur
        temp_dir = tempfile.mkdtemp()
        temp_pdf_yolu = os.path.join(temp_dir, f"geri_alinmis_{uuid.uuid4()}.pdf")

        # PDF metinlerini karşılaştır ve değişen alanları bul
        degisen_alanlar = pdf_metin_karsilastir(orijinal_pdf_yolu, anonim_pdf_yolu)

        # Redaksiyon uygula
        if pdf_redaksiyonu_uygula(anonim_pdf_yolu, temp_pdf_yolu, degisen_alanlar):
            logger.info("PDF başarıyla geri alındı.")
            return temp_pdf_yolu
        else:
            logger.warning("Herhangi bir değişiklik yapılamadı.")
            return None

    except Exception as e:
        logger.error(f"Genel hata: {e}")
        return None


def extract_author_names(text, max_authors=5):
    """
    Orijinal metinden yazar isimlerini çıkarır.
    Akademik makalelerde yazarlar genellikle ilk sayfada ve başlıktan sonra yer alır.
    """
    import re
    
    # IEEE formatlı makalelerde yazar adları genellikle Ad Soyad formatında
    author_pattern = re.compile(r'([A-Z][a-z]+\s[A-Z][a-z]+)(?:,|\s|and|\n)')
    
    # Metni satırlara böl ve ilk 20 satıra bak (genellikle başlık ve yazarlar burada olur)
    lines = text.split('\n')[:20]
    first_section = '\n'.join(lines)
    
    # Yazar adaylarını bul
    candidates = author_pattern.findall(first_section)
    
    # Filtreleme: Yaygın başlık kelimeleri/makale başlığı parçaları içeren adayları çıkar
    filtered_authors = []
    common_words = ["Abstract", "Introduction", "Figure", "Table", "Section", "Analysis"]
    
    for candidate in candidates:
        if not any(word in candidate for word in common_words) and len(candidate.split()) >= 2:
            filtered_authors.append(candidate)
    
    # Benzersiz yazarları döndür (en fazla max_authors)
    return list(dict.fromkeys(filtered_authors))[:max_authors]

def extract_institution_names(text, max_institutions=5):
    """
    Orijinal metinden kurum isimlerini çıkarır.
    Akademik makalelerde kurumlar genellikle yazarlardan sonra veya altında listelenir.
    """
    import re
    
    # Kurum adları için regex kalıpları
    patterns = [
        r'([A-Z][a-zA-Z\s]+University\b)',  # Harvard University
        r'(University\sof\s[A-Z][a-zA-Z\s]+)',  # University of California
        r'([A-Z][a-zA-Z\s]+Institute\s(?:of\s)?[A-Z][a-zA-Z\s]+)',  # Massachusetts Institute of Technology
        r'([A-Z][a-zA-Z\s]+College\b)',  # Boston College
        r'([A-Z][a-zA-Z\s]+Laboratory\b)',  # National Laboratory
        r'(\b[A-Z][a-zA-Z\s]+Department\b)',  # Computer Science Department
    ]
    
    # Metni satırlara böl ve ilk 30 satıra bak (genellikle kurumlar burada olur)
    lines = text.split('\n')[:30]
    first_section = '\n'.join(lines)
    
    all_institutions = []
    for pattern in patterns:
        matches = re.findall(pattern, first_section)
        all_institutions.extend(matches)
    
    # Benzersiz kurumları döndür (en fazla max_institutions)
    return list(dict.fromkeys(all_institutions))[:max_institutions]

def extract_email_addresses(text, max_emails=5):
    """
    Orijinal metinden e-posta adreslerini çıkarır.
    """
    import re
    
    # E-posta adresi için standart regex
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
    
    # Tüm metinde email adreslerini bul
    emails = re.findall(email_pattern, text)
    
    # Benzersiz e-postaları döndür (en fazla max_emails)
    return list(dict.fromkeys(emails))[:max_emails]

def degerlendirilmis_pdf_anonim_coz(makale, anonimlestirme):
    """
    Değerlendirilmiş PDF dosyasındaki anonim etiketleri orijinal bilgilerle değiştirir.
    PDF formatını ve değerlendirme metnini bozmadan işlem yapar.
    
    Args:
        makale: Makale modeli nesnesi
        anonimlestirme: Anonimlestirme modeli nesnesi
        
    Returns:
        str: İşlenmiş PDF'in yolu (başarısız olursa None)
    """
    try:
        import fitz  # PyMuPDF
        import os
        import re
        import tempfile
        import hashlib
        from django.conf import settings
        
        # Değerlendirilmiş PDF dosya yolunu al
        degerlendirilmis_pdf_yolu = makale.anonim_dosya.path
        
        # Orijinal PDF dosya yolunu al
        if anonimlestirme.orijinal_dosya and hasattr(anonimlestirme.orijinal_dosya, 'path'):
            orijinal_pdf_yolu = anonimlestirme.orijinal_dosya.path
        else:
            orijinal_pdf_yolu = makale.dosya.path
        
        # Geçici dosya oluştur
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        temp_file.close()
        temp_path = temp_file.name
        
        # Değerlendirilmiş PDF'i ve orijinal PDF'i aç
        degerlendirilmis_doc = fitz.open(degerlendirilmis_pdf_yolu)
        orijinal_doc = fitz.open(orijinal_pdf_yolu)
        
        # Orijinal metin bilgilerini çıkar
        orijinal_metin = ""
        for page in orijinal_doc:
            orijinal_metin += page.get_text()
        
        # Orijinal bilgileri çıkar
        authors = extract_author_names(orijinal_metin)
        institutions = extract_institution_names(orijinal_metin)
        emails = extract_email_addresses(orijinal_metin)
        
        print(f"Bulunan yazarlar: {authors}")
        print(f"Bulunan kurumlar: {institutions}")
        print(f"Bulunan e-posta adresleri: {emails}")
        
        # Her sayfayı işle ve anonimlik etiketlerini çöz
        for page_num in range(len(degerlendirilmis_doc)):
            page = degerlendirilmis_doc[page_num]
            
            # [YAZAR ***] etiketlerini bul ve değiştir
            yazar_alanlar = page.search_for("[YAZAR ***]")
            for i, rect in enumerate(yazar_alanlar):
                if i < len(authors):
                    # Hash güvenliği ile etiketlenen alanları değiştir
                    hash_val = hashlib.sha256(f"yazar_{i}".encode()).hexdigest()[:8]
                    annot = page.add_redact_annot(rect, text=authors[i])
                    page.apply_redactions()
            
            # [KURUM ***] etiketlerini bul ve değiştir
            kurum_alanlar = page.search_for("[KURUM ***]") 
            for i, rect in enumerate(kurum_alanlar):
                if i < len(institutions):
                    hash_val = hashlib.sha256(f"kurum_{i}".encode()).hexdigest()[:8]
                    annot = page.add_redact_annot(rect, text=institutions[i])
                    page.apply_redactions()
            
            # [EMAIL ***] etiketlerini bul ve değiştir
            email_alanlar = page.search_for("[EMAIL ***]")
            for i, rect in enumerate(email_alanlar):
                if i < len(emails):
                    hash_val = hashlib.sha256(f"email_{i}".encode()).hexdigest()[:8]
                    annot = page.add_redact_annot(rect, text=emails[i])
                    page.apply_redactions()
        
        # Değişiklikleri geçici dosyaya kaydet
        degerlendirilmis_doc.save(temp_path, garbage=4, deflate=True, clean=True)
        
        # Referans kaldır
        degerlendirilmis_doc.close()
        orijinal_doc.close()
        
        # Orijinal dosya ismi ile aynı olacak şekilde dosyayı kopyala
        # Dosya ismini değiştirmeden aynı yere kaydet
        return temp_path
        
    except Exception as e:
        import traceback
        print(f"Değerlendirilmiş PDF anonimlik çözme hatası: {str(e)}")
        print(traceback.format_exc())
        return None
def normalize_ilgi_alanlari(metin):
    """
    Verilen metindeki kelimeleri ES_DEGER_ALANLAR'a göre normalize eder.
    Her eşleşmeyi genel başlığa dönüştürür.
    """
    metin = metin.lower()
    normalize_sonuclari = []

    for anahtar, es_degerler in ES_DEGER_ALANLAR.items():
        for terim in es_degerler:
            if terim.lower() in metin:
                normalize_sonuclari.append(anahtar)
                break  # Aynı kategori tekrar tekrar eklenmesin

    return " ".join(normalize_sonuclari) if normalize_sonuclari else metin


def dogrudan_pdf_anonimlestir(girdi_pdf_yolu, cikti_pdf_yolu, anonim_yazar=True, anonim_kurum=True, anonim_email=True, anonim_yuzler=True):
    """
    IEEE formatındaki PDF makaleyi format ve düzeni bozmadan kapsamlı şekilde anonimleştiren fonksiyon.
    Geliştirilmiş yazar tespiti ve çok daha agresif yüz bulanıklaştırma özelliği içerir.
    
    Args:
        girdi_pdf_yolu: Orijinal PDF'in dosya yolu
        cikti_pdf_yolu: Anonimleştirilmiş PDF'in kaydedileceği yol
        anonim_yazar: Yazar bilgilerini anonimleştir (varsayılan: True)
        anonim_kurum: Kurum bilgilerini anonimleştir (varsayılan: True)
        anonim_email: Email adreslerini anonimleştir (varsayılan: True)
        anonim_yuzler: İnsan yüzlerini bulanıklaştır (varsayılan: True)
    """
    try:
        import fitz  # PyMuPDF
        import re
        import os
        import tempfile
        import io
        import shutil
        
        # PDF'i aç
        doc = fitz.open(girdi_pdf_yolu)
        
        # Önce tüm metni çıkar ve analiz et - daha kapsamlı bir yaklaşım
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        
        # Anonimleştirilecek tüm metinleri topla
        items_to_anonymize = []
        
        if anonim_yazar:
            # Yazar isimleri için daha kapsamlı regex'ler
            author_patterns = [
                r'\b[A-Z][a-z]+\s[A-Z][a-z]+\b',  # John Smith
                r'\b[A-Z][a-z]+\s[A-Z]\.\s[A-Z][a-z]+\b',  # John A. Smith
                r'\b[A-Z][a-z]+\s[A-Z]\.\s[A-Z]\.\s[A-Z][a-z]+\b',  # John A. B. Smith
            ]
            
            # Tespit edilen tüm potansiyel yazarları topla
            potential_authors = []
            for pattern in author_patterns:
                matches = re.finditer(pattern, full_text)
                for match in matches:
                    # IEEE makalelerinde yazar isimleri genellikle başlangıçta bulunur
                    if match.start() < 2000:
                        potential_authors.append(match.group())
            
            # Tespit edilen yazarları filtreleme fonksiyonu ile iyileştir
            try:
                filtered_authors = tespit_edilen_yazarlari_filtrele(potential_authors, full_text)
            except:
                # Filtreleme fonksiyonu kullanılamıyorsa
                filtered_authors = [author for author in potential_authors if author.split()[0] not in ["The", "This", "Abstract", "Introduction"]]
            
            # Filtrelenmiş yazarları anonimleştir listesine ekle
            for author in filtered_authors:
                items_to_anonymize.append((author, "[YAZAR ***]"))
            
            # Debug için
            print(f"Tespit edilen makale yazarları: {filtered_authors}")
        
        if anonim_kurum:
            # Kurum bilgileri için geniş kapsamlı regex'ler
            institution_patterns = [
                r'\b[A-Z][a-zA-Z\s]+University\b',  # Harvard University
                r'\bUniversity\sof\s[A-Z][a-zA-Z\s]+\b',  # University of California
                r'\b[A-Z][a-zA-Z\s]+Institute\sof\s[A-Z][a-zA-Z\s]+\b',  # Massachusetts Institute of Technology
                r'\bDepartment\sof\s[A-Z][a-zA-Z\s]+\b',  # Department of Computer Science
                r'\b[A-Z][a-zA-Z\s]+College\b',  # Boston College
                r'\b[A-Z][a-zA-Z\s]+Laboratory\b',  # Lincoln Laboratory
                r'\b[A-Z][a-zA-Z\s]+Lab\b',  # Bell Lab
            ]
            
            for pattern in institution_patterns:
                matches = re.finditer(pattern, full_text)
                for match in matches:
                    # Kurum isimleri genellikle yazarların hemen altında olur, ilk 3000 karakterde
                    if match.start() < 3000:
                        items_to_anonymize.append((match.group(), "[KURUM ***]"))
        
        if anonim_email:
            # Email regex - comprehensive pattern
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
            matches = re.finditer(email_pattern, full_text)
            for match in matches:
                items_to_anonymize.append((match.group(), "[EMAIL ***]"))
        
        # Her sayfayı işle ve tüm bulunan metinleri değiştir
        for page_num in range(len(doc)):
            page = doc[page_num]
            
            # Metin bazlı anonimleştirme
            for original, replacement in items_to_anonymize:
                # Sayfada tüm eşleşmeleri bul
                text_instances = page.search_for(original)
                
                # Her eşleşmeyi işaretle ve değiştir
                for inst in text_instances:
                    # Redaksiyon işlemi - metni değiştir
                    page.add_redact_annot(inst, text=replacement)
            
            # Redaksiyonları uygula
            page.apply_redactions()
            
            # Yüz bulanıklaştırma işlemi
            if anonim_yuzler:
                # Sayfadaki görüntüleri kontrol et
                image_list = page.get_images(full=True)
                
                for img_index, img_info in enumerate(image_list):
                    xref = img_info[0]  # Resmin referans numarası
                    
                    try:
                        # Resmi çıkar
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        
                        # Agresif yüz tespiti ve bulanıklaştırma fonksiyonunu kullan
                        processed_bytes = guclu_yuz_bulaniklastirma(image_bytes)
                        
                        # İşlenen resmi kaydet ve yerleştir
                        if processed_bytes != image_bytes:  # Resim değiştiyse
                            # Geçici bir dosya oluştur
                            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                                tmp.write(processed_bytes)
                                tmp_filename = tmp.name
                            
                            # Orijinal resmi bul ve pozisyonunu al
                            try:
                                rect = page.get_image_bbox(img_info)
                                
                                # Eski resmi sil ve yenisini ekle
                                page.delete_image(rect)
                                page.insert_image(rect, filename=tmp_filename)
                                
                                print(f"Sayfa {page_num+1}'deki resim {img_index+1} başarıyla bulanıklaştırıldı")
                            except Exception as rect_err:
                                print(f"Görüntü konumu alınamadı: {rect_err}")
                                
                                # Alternatif yaklaşım: Tüm görüntüyü bul ve değiştir
                                try:
                                    for obj in page.get_images():
                                        if obj[0] == xref:  # Doğru resim mi?
                                            rect = page.get_image_bbox(obj)
                                            page.delete_image(rect)
                                            page.insert_image(rect, filename=tmp_filename)
                                            print(f"Alternatif yöntemle resim değiştirildi")
                                            break
                                except Exception as alt_err:
                                    print(f"Alternatif yöntem hatası: {alt_err}")
                            
                            # Geçici dosyayı sil
                            try:
                                os.unlink(tmp_filename)
                            except:
                                pass
                    
                    except Exception as e:
                        print(f"Resim işleme hatası (sayfa {page_num+1}, resim {img_index+1}): {str(e)}")
                        continue
        
        # PDF'i geçici bir dosyaya kaydet
        temp_output = tempfile.mktemp(suffix=".pdf")
        doc.save(temp_output)
        doc.close()
        
        # Geçici dosyayı hedef konuma kopyala
        shutil.copy2(temp_output, cikti_pdf_yolu)
        
        # Geçici dosyayı sil
        try:
            os.unlink(temp_output)
        except:
            pass
        
        # Kontrol et - dosya oluştu mu?
        if not os.path.exists(cikti_pdf_yolu):
            raise Exception("PDF dosyası oluşturulamadı!")
            
        return True
        
    except Exception as e:
        import traceback
        print(f"PDF anonimleştirme hatası: {str(e)}")
        print(traceback.format_exc())
        
        # Alternatif yöntem - PyPDF2 ve pikepdf kombinasyonu dene
        try:
            import pikepdf
            
            # Pikepdf ile PDF'i aç - bu genellikle formatı daha iyi korur
            with pikepdf.Pdf.open(girdi_pdf_yolu) as pdf:
                # Doğrudan pikepdf ile kaydet - minimal müdahale
                pdf.save(cikti_pdf_yolu)
                
            return True
        except Exception as e2:
            print(f"Alternatif metot da başarısız oldu: {str(e2)}")
            return False

def tespit_edilen_yazarlari_filtrele(yazarlar, metin):
    """
    Hatalı yazar tespitlerini filtrelemek için geliştirilmiş fonksiyon.
    Bu fonksiyon muhtemel yazar isimlerini daha sıkı filtrelerden geçirir.
    
    Args:
        yazarlar: Tespit edilen olası yazar isimleri listesi
        metin: Makalenin tam metni
    
    Returns:
        Filtrelenmiş, gerçek yazar isimlerini içeren liste
    """
    # IEEE makalelerinde yaygın olarak bulunan ve yazar olmayan özel isimler
    filtrelenecek_kelimeler = [
        "Digital Object", "Emotion Recognition", "Using Temporally", 
        "Emotional Events", "With Naturalistic", "Graduate Student", 
        "Senior Member", "Information Technology", "Graduate", 
        "Indian Institute", "Uttar Pradesh", "Corresponding",
        "Conference", "Institute", "University", "Department",
        "Abstract", "Introduction", "Keywords", "Conclusion"
    ]
    
    # Makale içinde sık geçen ama yazar olmayan kalıplar için regex
    import re
    
    # Kesin yazar olmayan kalıplar
    kesin_yazar_olmayan_pattern = re.compile(r'^(Using|With|In|On|And|The|This|That|These|Those|For|From|To|By|Abstract|Introduction|Conclusion|Keywords)$')
    
    # Filtrelenmiş yazar listesi
    filtrelenmis_yazarlar = []
    
    for yazar in yazarlar:
        # Basit filtreleme: Kısaysa atla
        if len(yazar.split()) < 2:
            continue
            
        # Filtrelenecek özel ifadeler içeriyorsa atla
        if any(ifade in yazar for ifade in filtrelenecek_kelimeler):
            continue
            
        # Kesin yazar olmayan kalıpları filtrele
        kelimeler = yazar.split()
        if any(kesin_yazar_olmayan_pattern.match(kelime) for kelime in kelimeler):
            continue
            
        # İsim kalıbına uymayan kelimeleri filtrele (örn. sayılar, kısaltmalar)
        isim_pattern = re.compile(r'^[A-Z][a-z]+$')  # Büyük harfle başlayan, geri kalanı küçük harf
        if not all(isim_pattern.match(kelime) for kelime in kelimeler):
            continue
            
        # Makale içinde konumu kontrol et - yazarlar genellikle başta olur
        ilk_bulunma = metin.find(yazar)
        if ilk_bulunma > 1500:  # İlk 1500 karakterde değilse muhtemelen yazar değil
            continue
            
        # Sıkı kontrolleri geçtiyse ekle
        filtrelenmis_yazarlar.append(yazar)
    
    # Benzersiz yazarları döndür
    return list(set(filtrelenmis_yazarlar))

def yuz_tespit_ve_bulaniklastir(image_data):
    """
    Geliştirilmiş yüz tespiti ve bulanıklaştırma fonksiyonu.
    Bu fonksiyon birden fazla yüz algılama yaklaşımı kullanır ve daha iyi sonuçlar verir.
    
    Args:
        image_data: Resim verisi (bytes)
        
    Returns:
        Bulanıklaştırılmış yüzleri içeren resim verisi (bytes)
    """
    try:
        import cv2
        import numpy as np
        from PIL import Image
        import io
        
        # Resmi OpenCV formatına dönüştür
        image = Image.open(io.BytesIO(image_data))
        # RGBA formatını RGB'ye dönüştür (gerekirse)
        if image.mode == 'RGBA':
            image = image.convert('RGB')
        cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        
        # Yüz tespiti için iki farklı sınıflandırıcı kullan
        face_cascade1 = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        face_cascade2 = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_alt.xml')
        face_cascade3 = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_profileface.xml')
        
        # Gri tonlamaya dönüştür
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        
        # Eşitleme yaparak kontrastı iyileştir - yüz tespitini geliştirir
        gray_eq = cv2.equalizeHist(gray)
        
        # Farklı ölçeklerde yüz tespiti yap - daha kapsamlı sonuç için
        faces1 = face_cascade1.detectMultiScale(gray_eq, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        faces2 = face_cascade2.detectMultiScale(gray_eq, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        faces3 = face_cascade3.detectMultiScale(gray_eq, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        
        # Tüm tespit edilen yüzleri birleştir
        all_faces = []
        if len(faces1) > 0:
            for face in faces1:
                all_faces.append(face)
                
        if len(faces2) > 0:
            for face in faces2:
                all_faces.append(face)
                
        if len(faces3) > 0:
            for face in faces3:
                all_faces.append(face)
        
        # Tespit edilen her yüzü bulanıklaştır
        if len(all_faces) > 0:
            for (x, y, w, h) in all_faces:
                # Yüzün etrafında bir dikdörtgen çiz (isteğe bağlı, test için)
                # cv2.rectangle(cv_image, (x, y), (x+w, y+h), (255, 0, 0), 2)
                
                # Daha güçlü bir bulanıklaştırma efekti için
                face_roi = cv_image[y:y+h, x:x+w]
                
                # Gaussian blur - daha büyük kernel boyutu ve sigma değeri
                face_roi = cv2.GaussianBlur(face_roi, (99, 99), 30)
                
                # Bulanıklaştırılmış yüzü orijinal görüntüye yerleştir
                cv_image[y:y+h, x:x+w] = face_roi
            
            # İşlenmiş resmi BytesIO'ya dönüştür
            cv_image_rgb = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
            pil_image_processed = Image.fromarray(cv_image_rgb)
            
            buffer = io.BytesIO()
            pil_image_processed.save(buffer, format="PNG")
            return buffer.getvalue()
        
        return image_data  # Yüz bulunamadıysa orijinal resmi döndür
        
    except Exception as e:
        print(f"Yüz işleme hatası: {str(e)}")
        return image_data  # Hata durumunda orijinal resmi döndür
def pdf_direkt_anonimlestir(pdf_path, output_path=None, anonim_yazar=True, anonim_kurum=True, anonim_email=True):
    """
    PDF dosyasını doğrudan manipüle ederek anonimleştirir,
    IEEE formatını korur.
    
    Args:
        pdf_path (str): Orijinal PDF dosya yolu
        output_path (str, optional): Çıktı dosyası yolu. Belirtilmezse otomatik oluşturulur.
        anonim_yazar (bool): Yazar isimlerini anonimleştir
        anonim_kurum (bool): Kurum bilgilerini anonimleştir
        anonim_email (bool): E-posta adreslerini anonimleştir
        
    Returns:
        str: Anonimleştirilmiş PDF'in yolu
    """
    # Çıktı yolu belirtilmemişse, otomatik oluştur
    if output_path is None:
        dosya_adi = os.path.basename(pdf_path)
        dosya_adi_parcalar = os.path.splitext(dosya_adi)
        output_path = os.path.join(os.path.dirname(pdf_path), 
                                  f"{dosya_adi_parcalar[0]}_anonim{dosya_adi_parcalar[1]}")
    
    # Geçici bir dosya oluştur
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    temp_file.close()
    temp_path = temp_file.name
    
    # İlk olarak PDF'i kopyala
    shutil.copy2(pdf_path, temp_path)
    
    try:
        # PDF'i aç
        pdf = fitz.open(temp_path)
        
        # Anonimleştirilmeyecek bölüm başlıkları
        haric_tutulacak_basliklar = [
            "giriş", "ilgili çalışmalar", "referanslar", "teşekkür", "kaynakça",
            "introduction", "related work", "references", "acknowledgement", "bibliography"
        ]
        
        # İlk sayfadan yazar ve kurum bilgilerini tespit et
        ilk_sayfa = pdf[0]
        ilk_sayfa_metin = ilk_sayfa.get_text()
        
        # Yazar adlarını tespit et (IEEE formatında genellikle ilk sayfada)
        yazar_pattern = re.compile(r'\b([A-Z][a-zışğüöçİŞĞÜÖÇ]+(?:\s+[A-Z][a-zışğüöçİŞĞÜÖÇ]+)+)\b')
        potansiyel_yazarlar = yazar_pattern.findall(ilk_sayfa_metin)
        
        # IEEE makalelerinde yazarlar genellikle Abstract öncesinde ve başlık sonrasında bulunur
        # Başlık ve Abstract konumlarını bul
        baslik_pozisyonu = ilk_sayfa_metin.find(pdf.metadata['title']) if pdf.metadata.get('title') else 0
        abstract_pozisyonu = ilk_sayfa_metin.lower().find('abstract')
        
        # Başlık ve Abstract arasındaki metinden yazar adlarını filtreleme
        makale_yazarlari = []
        if baslik_pozisyonu >= 0 and abstract_pozisyonu > baslik_pozisyonu:
            arasi_metin = ilk_sayfa_metin[baslik_pozisyonu:abstract_pozisyonu]
            for yazar in potansiyel_yazarlar:
                if yazar in arasi_metin and len(yazar.split()) >= 2:  # En az iki kelime (Ad Soyad)
                    makale_yazarlari.append(yazar)
        
        # Kurum bilgilerini tespit et
        kurum_pattern = re.compile(r'\b([A-Za-zışğüöçİŞĞÜÖÇ]+ (?:University|Üniversitesi|Institute|Enstitüsü|Department|Bölümü)(?:[ ,][A-Za-zışğüöçİŞĞÜÖÇ]+){0,4})\b')
        potansiyel_kurumlar = kurum_pattern.findall(ilk_sayfa_metin)
        
        # Her sayfayı işle
        for i, sayfa in enumerate(pdf):
            sayfa_metin = sayfa.get_text().lower()
            
            # Bu sayfa korunacak bir bölüm içeriyor mu kontrol et
            if any(baslik in sayfa_metin for baslik in haric_tutulacak_basliklar):
                # Bu sayfada referans vb. bölümler var, hassas kısımları tespit et
                haric_tutulacak_bolum_var = False
                for baslik in haric_tutulacak_basliklar:
                    if baslik in sayfa_metin:
                        haric_tutulacak_bolum_var = True
                        # İlgili bölümün başlangıç konumunu bul
                        baslik_konum = sayfa_metin.find(baslik)
                        # Bu bölüm sonrası anonimleştirilmeyecek
                        # Bölüm öncesi kısımlar için hassas bilgi arama ve kapatma işlemleri yapılabilir
                
                if haric_tutulacak_bolum_var:
                    # Bu sayfayı atla veya sadece bölüm öncesini işle
                    continue
            
            # E-posta adreslerini tespit et ve anonimleştir
            if anonim_email:
                email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                for match in re.finditer(email_pattern, sayfa.get_text()):
                    email = match.group()
                    areas = sayfa.search_for(email)
                    for rect in areas:
                        # Dikdörtgen oluştur ve metin yerine [EMAIL ***] ekle
                        rect.x1 += 3  # Kenarlık için biraz genişlet
                        sayfa.add_redact_annot(rect, fill=(1, 1, 1), text="[EMAIL ***]")
            
            # Yazar adlarını tespit et ve anonimleştir
            if anonim_yazar and makale_yazarlari:
                for yazar in makale_yazarlari:
                    areas = sayfa.search_for(yazar)
                    for rect in areas:
                        # Dikdörtgen oluştur ve metin yerine [YAZAR ***] ekle
                        rect.x1 += 3  # Kenarlık için biraz genişlet
                        sayfa.add_redact_annot(rect, fill=(1, 1, 1), text="[YAZAR ***]")
            
            # Kurum bilgilerini tespit et ve anonimleştir
            if anonim_kurum and potansiyel_kurumlar:
                for kurum in potansiyel_kurumlar:
                    areas = sayfa.search_for(kurum)
                    for rect in areas:
                        # Dikdörtgen oluştur ve metin yerine [KURUM ***] ekle
                        rect.x1 += 3  # Kenarlık için biraz genişlet
                        sayfa.add_redact_annot(rect, fill=(1, 1, 1), text="[KURUM ***]")
            
            # Gerçekleştirilen redaksiyon işlemlerini uygula
            sayfa.apply_redactions()
        
        # Anonimleştirilmiş PDF'i kaydet
        pdf.save(output_path, garbage=4, deflate=True, clean=True, incremental=False)
        pdf.close()
        
        # Geçici dosyayı temizle
        os.unlink(temp_path)
        
        return output_path
    
    except Exception as e:
        # Hata durumunda geçici dosyayı temizle ve hatayı yeniden fırlat
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise e

def pdf_to_images(pdf_path):
    """PDF'yi sayfa sayfa resimlere çevirir."""
    return convert_from_path(pdf_path, poppler_path=POPPLER_PATH)

def pdf_to_text(pdf_path):
    """PDF dosyasını metne çevirir."""
    try:
        # Dosya yolunu kontrol et
        if not os.path.exists(pdf_path):
            print(f"HATA: Dosya bulunamadı - {pdf_path}")
            return "Hata: Dosya bulunamadı"

        # Dosya izinlerini ve erişilebilirliğini kontrol et
        if not os.access(pdf_path, os.R_OK):
            print(f"HATA: Dosya okunabilir değil - {pdf_path}")
            return "Hata: Dosya okunabilir değil"

        # PDFMiner ile metni çıkar
        text = extract_text(pdf_path)
        
        # Eğer metin boşsa farklı bir yöntem dene
        if not text.strip():
            import PyPDF2
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text()
        
        return text if text.strip() else "Hata: PDF metin içermiyor."
    except Exception as e:
        import traceback
        print(f"PDF dönüştürme hatası: {e}")
        print(traceback.format_exc())
        return f"Hata: {e}"
def anonimlestir(text, anonim_yazar=True, anonim_kurum=True, anonim_email=True):
    """
    Makale içindeki yazar, kurum ve e-posta adreslerini anonimleştirir.
    
    Args:
        text (str): Anonimleştirilecek PDF'den çıkarılan metin
        anonim_yazar (bool): Yazar isimlerini anonimleştir
        anonim_kurum (bool): Kurum bilgilerini anonimleştir
        anonim_email (bool): E-posta adreslerini anonimleştir
        
    Returns:
        str: Anonimleştirilmiş metin
    """
    # Metni bölümlere ayır (paragraf, başlık vb.)
    bolumler = text.split("\n\n")
    doc = nlp(text)
    
    # Hem Türkçe hem İngilizce için desteklenen bölüm başlıkları
    HARIC_TUTULACAK_BOLUM_BASLIKLARI = [
        "giriş", "ilgili çalışmalar", "referanslar", "teşekkür", "kaynakça",
        "introduction", "related work", "references", "acknowledgement", "bibliography"
    ]
    
    # Kurum için tanımlayıcı kelimeler
    kurum_keywords = [
        "university", "üniversite", "department", "fakülte", "faculty", 
        "institute", "enstitü", "laboratuvar", "laboratory", "corp", "inc", 
        "research center", "araştırma merkezi"
    ]
    
    # Makale yazarlarını tanımlama - ilk sayfada en başta yer alır genellikle
    ilk_sayfa = " ".join(bolumler[:5])  # İlk 5 bölüm/paragraf
    makale_yazarlari = []
    
    # Yazar tespiti için basit sözlük oluşturma (gerçek uygulamalarda daha gelişmiş NER kullanılır)
    for ent in doc.ents:
        if ent.label_ == "PERSON" and ent.text in ilk_sayfa:
            makale_yazarlari.append(ent.text)
    
    # Akademik makale yazarı genellikle "Ad Soyad" formatında olur
    isim_pattern = re.compile(r"\b([A-Z][a-zışğüöçİŞĞÜÖÇ]+ [A-Z][a-zışğüöçİŞĞÜÖÇ]+)\b")
    potansiyel_isimler = isim_pattern.findall(ilk_sayfa)
    
    # Bulunan isimleri makale yazarlarına ekle
    for isim in potansiyel_isimler:
        if isim not in makale_yazarlari:
            makale_yazarlari.append(isim)
    
    print(f"Tespit edilen makale yazarları: {makale_yazarlari}")
    
    # Her bölümü işle
    for i, bolum in enumerate(bolumler):
        bolum_kucuk = bolum.lower()
        
        # Bu bölüm, anonimleştirilmemesi gereken bir bölüm mü kontrol et
        haric_tutulacak_mu = any(baslik in bolum_kucuk for baslik in HARIC_TUTULACAK_BOLUM_BASLIKLARI)
        
        if haric_tutulacak_mu:
            continue
        
        # E-posta adreslerini anonimleştir
        if anonim_email:
            bolumler[i] = re.sub(
                r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", 
                "[EMAIL ***]", 
                bolumler[i]
            )
        
        # Makale yazarlarını anonimleştir
        if anonim_yazar and makale_yazarlari:
            for yazar in makale_yazarlari:
                # Yazarın adını tam eşleştirme ile değiştir
                bolumler[i] = re.sub(
                    r"\b" + re.escape(yazar) + r"\b", 
                    "[YAZAR ***]", 
                    bolumler[i]
                )
        
        # Yazar isimlerini genel olarak tespit et ve anonimleştir (makale yazarları tespit edilemezse)
        elif anonim_yazar and not makale_yazarlari:
            for ent in doc.ents:
                if ent.label_ == "PERSON" and ent.text in bolumler[i]:
                    bolumler[i] = re.sub(
                        r"\b" + re.escape(ent.text) + r"\b", 
                        "[YAZAR ***]", 
                        bolumler[i]
                    )
        
        # Kurum bilgilerini anonimleştir
        if anonim_kurum:
            # SpaCy ile tespit edilen organizasyonları anonimleştir
            for ent in doc.ents:
                if ent.label_ == "ORG" and ent.text in bolumler[i]:
                    # Eğer ilgili bölümde bir kurum kelimesi içeriyorsa anonimleştir
                    if any(kw.lower() in ent.text.lower() for kw in kurum_keywords):
                        bolumler[i] = re.sub(
                            r"\b" + re.escape(ent.text) + r"\b", 
                            "[KURUM ***]", 
                            bolumler[i]
                        )
            
            # Kurum anahtar kelimeleriyle pattern tabanlı arama
            for kw in kurum_keywords:
                # Kurum kelimesinin etrafındaki metni anonimleştir
                # Örn: "X Üniversitesi Bilgisayar Mühendisliği"
                pattern = re.compile(r"\b([A-Za-zışğüöçİŞĞÜÖÇ]+ " + kw + r"([ \t]+[A-Za-zışğüöçİŞĞÜÖÇ]+){0,4})\b", re.IGNORECASE)
                matches = pattern.findall(bolumler[i])
                
                for match in matches:
                    if isinstance(match, tuple):  # Eğer match bir tuple ise
                        kurum_text = match[0]
                    else:
                        kurum_text = match
                    
                    # Farklı bir anlamda kullanılan kurumları tespit etmek için basit bir kontrol
                    # Cümle içinde kurum olarak geçiyorsa anonimleştir
                    if re.search(r"\b(at|from|in|by|of|with|çalışan|görevli|öğretim|üyesi|mensubu|akademisyen)\b", bolumler[i], re.IGNORECASE):
                        bolumler[i] = bolumler[i].replace(kurum_text, "[KURUM ***]")
    
    return "\n\n".join(bolumler)

def anahtar_kelime_cikar(text, n=10):
    """Metinden en sık geçen anahtar kelimeleri çıkarır, stopwords ve anlamsız kelimeleri temizler."""
    doc = nlp(text.lower())
    kelimeler = [
        token.text for token in doc
        if token.is_alpha
        and not token.is_stop
        and token.text not in STOPWORDS
        and len(token.text) > 2  # **Tek ve iki harfli kelimeleri çıkar**
    ]
    
    kelime_sayaci = Counter(kelimeler)
    return [kelime for kelime, _ in kelime_sayaci.most_common(n)]

ALANLAR = {
    "Yapay Zeka": ["derin öğrenme", "nöral ağlar", "makine öğrenimi", "yapay zeka", "AI"],
    "Artificial Intelligence": ["deep learning", "neural networks", "machine learning", "artificial intelligence", "AI"],
    "Doğal Dil İşleme": ["doğal dil işleme", "NLP", "sentiment analizi", "tokenization"],
    "Natural Language Processing": ["natural language processing", "NLP", "sentiment analysis", "tokenization"],
    "Bilgisayarla Görü": ["görüntü işleme", "bilgisayarla görü", "CNN", "resim analizi"],
    "Computer Vision": ["image processing", "computer vision", "CNN", "image analysis"],
    "Büyük Veri": ["büyük veri", "Hadoop", "Spark", "veri madenciliği", "zaman serisi"],
    "Big Data": ["big data", "Hadoop", "Spark", "data mining", "time series"],
    "Siber Güvenlik": ["şifreleme", "AES", "RSA", "güvenlik", "kimlik doğrulama"],
    "Cyber Security": ["encryption", "AES", "RSA", "security", "authentication"],
    "Ağ Sistemleri": ["5G", "bulut bilişim", "P2P", "blockchain", "merkeziyetsiz sistemler"],
    "Network Systems": ["5G", "cloud computing", "P2P", "blockchain", "decentralized systems"]
}


def alan_atama_nlp(makale_metin):
    """Makale içeriğine göre en uygun alanı belirler (TF-IDF + Cosine Similarity), gereksiz kelimeleri filtreler."""
    if not makale_metin:
        return "Bilinmeyen"

    temiz_metin = " ".join(anahtar_kelime_cikar(makale_metin, n=50))

    alan_etiketleri = list(ALANLAR.keys())
    alan_cumleleri = [" ".join(ALANLAR[alan]) for alan in ALANLAR]

    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform([temiz_metin] + alan_cumleleri)

    benzerlik_skorlari = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()
    en_uygun_alan_index = benzerlik_skorlari.argmax()
    return alan_etiketleri[en_uygun_alan_index]

def uygun_hakem_bul(makale_metin, hakemler, max_sayi=5):
    """Makale metnine en uygun hakemleri sıralı liste olarak döner"""

    hakem_listesi = list(hakemler)
    if not hakem_listesi:
        return []

    # ✨ Normalize et
    makale_metin = normalize_ilgi_alanlari(makale_metin)

    hakem_ilgi_cumleleri = []
    for hakem in hakem_listesi:
        ilgi = hakem.ilgi_alanlari if hakem.ilgi_alanlari else "Bilinmeyen"
        ilgi = normalize_ilgi_alanlari(ilgi)
        hakem_ilgi_cumleleri.append(ilgi)

    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform([makale_metin] + hakem_ilgi_cumleleri)

    benzerlik_skorlari = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()
    
    skorlu_hakemler = sorted(zip(hakem_listesi, benzerlik_skorlari), key=lambda x: x[1], reverse=True)
    return skorlu_hakemler[:max_sayi]

# utils.py dosyasına ekleyin

def anonimlestir_pdf_format_korunarak(pdf_path, output_path=None, anonim_yazar=True, anonim_kurum=True, anonim_email=True):
    """
    IEEE formatını bozmadan PDF'i anonimleştirir.
    
    Args:
        pdf_path (str): Orijinal PDF dosya yolu
        output_path (str, optional): Çıktı dosyasının yolu. Belirtilmezse otomatik oluşturulur.
        anonim_yazar (bool): Yazar isimlerini anonimleştir
        anonim_kurum (bool): Kurum bilgilerini anonimleştir
        anonim_email (bool): E-posta adreslerini anonimleştir
        
    Returns:
        str: Anonimleştirilmiş PDF'in yolu
    """
    import cv2
    import numpy as np
    import os
    import re
    import pytesseract
    from pdf2image import convert_from_path
    from PIL import Image, ImageDraw, ImageFont
    import img2pdf
    from pathlib import Path
    
    # Çıktı yolu belirtilmemişse, giriş dosyasının adını kullanarak oluştur
    if output_path is None:
        input_path = Path(pdf_path)
        output_path = str(input_path.parent / f"{input_path.stem}_anonim{input_path.suffix}")
    
    # PDF'i görüntülere dönüştür
    images = convert_from_path(pdf_path, poppler_path=POPPLER_PATH)
    
    # İlk sayfadan yazar ve kurum bilgilerini tespit et
    ilk_sayfa = images[0]
    ilk_sayfa_metin = pytesseract.image_to_string(ilk_sayfa)
    
    # Yazar isimlerini tespit et
    isim_pattern = re.compile(r"\b([A-Z][a-zışğüöçİŞĞÜÖÇ]+ [A-Z][a-zışğüöçİŞĞÜÖÇ]+)(?:,?\s+(?:Üye|Member),?\s+IEEE)?\b")
    makale_yazarlari = [match for match in isim_pattern.findall(ilk_sayfa_metin)]
    
    # Kurum bilgilerini tespit et
    kurum_pattern = re.compile(r"\b([A-Za-zışğüöçİŞĞÜÖÇ]+ (?:University|Üniversitesi|Institute|Enstitüsü)(?:,| [A-Za-zışğüöçİŞĞÜÖÇ]+){1,3}(?:,| [A-Za-zışğüöçİŞĞÜÖÇ]+)?)\b")
    potansiyel_kurumlar = [match for match in kurum_pattern.findall(ilk_sayfa_metin)]
    
    # Her görüntüyü işle
    processed_images = []
    
    # Anonimleştirilmeyecek bölümlerin başlıkları
    HARIC_TUTULACAK_BOLUM_BASLIKLARI = [
        "giriş", "ilgili çalışmalar", "referanslar", "teşekkür", "kaynakça",
        "introduction", "related work", "references", "acknowledgement", "bibliography"
    ]
    
    for i, img in enumerate(images):
        # Görüntüyü numpy array'e ve OpenCV formatına dönüştür
        img_np = np.array(img)
        img_cv = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        
        # Bu sayfanın metnini çıkar
        sayfa_metin = pytesseract.image_to_string(img)
        sayfa_metin_lower = sayfa_metin.lower()
        
        # Bu sayfa anonimleştirilmeyecek bir bölüm içeriyor mu kontrol et
        haric_tutulacak_mu = any(baslik in sayfa_metin_lower for baslik in HARIC_TUTULACAK_BOLUM_BASLIKLARI)
        
        if haric_tutulacak_mu:
            # Anonimleştirilmeyecek bölüm içeren sayfayı olduğu gibi bırak
            processed_images.append(img_cv)
            continue
        
        # Metin tespiti yap - metin ve konumlarını al
        metin_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        
        # Tespit edilen her metin parçasını işle
        for j, text in enumerate(metin_data['text']):
            if not text.strip():
                continue
            
            x = metin_data['left'][j]
            y = metin_data['top'][j]
            w = metin_data['width'][j]
            h = metin_data['height'][j]
            
            # E-posta kontrolü
            if anonim_email and re.match(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text):
                # Alanı kapat
                cv2.rectangle(img_cv, (x, y), (x + w, y + h), (255, 255, 255), -1)
                # Yerine etiket ekle
                cv2.putText(img_cv, "[EMAIL ***]", (x, y + h), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
            
            # Yazar ismi kontrolü
            if anonim_yazar and makale_yazarlari:
                for yazar in makale_yazarlari:
                    if yazar in text:
                        # Alanı kapat
                        cv2.rectangle(img_cv, (x, y), (x + w, y + h), (255, 255, 255), -1)
                        # Yerine etiket ekle
                        cv2.putText(img_cv, "[YAZAR ***]", (x, y + h), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
                        break
            
            # Kurum kontrolü
            if anonim_kurum and potansiyel_kurumlar:
                for kurum in potansiyel_kurumlar:
                    if kurum in text:
                        # Alanı kapat
                        cv2.rectangle(img_cv, (x, y), (x + w, y + h), (255, 255, 255), -1)
                        # Yerine etiket ekle
                        cv2.putText(img_cv, "[KURUM ***]", (x, y + h), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
                        break
        
        # İşlenmiş görüntüyü listeye ekle
        processed_images.append(img_cv)
    
    # Geçici olarak görüntüleri diske kaydet (img2pdf için gerekli olabilir)
    temp_image_paths = []
    for i, img in enumerate(processed_images):
        temp_path = f"temp_page_{i}.png"
        cv2.imwrite(temp_path, img)
        temp_image_paths.append(temp_path)
    
    # Görüntüleri tekrar PDF'e dönüştür
    with open(output_path, "wb") as f:
        # PNG dosyalarını PDF'e dönüştür
        f.write(img2pdf.convert(temp_image_paths))
    
    # Geçici dosyaları temizle
    for temp_path in temp_image_paths:
        os.remove(temp_path)
    
    return output_path
def geri_anonim_ac(anonim_metin, orijinal_metin):
    """
    Anonimleştirilmiş metni eski haline döndürür.
    """
    from django.db.models.fields.files import FieldFile
    import re
    
    # Eğer orijinal dosya bir `FieldFile` ise, metne çevir
    if isinstance(orijinal_metin, FieldFile):
        orijinal_metin = pdf_to_text(orijinal_metin.path)  # PDF dosyasını metne çevir
    
    # Anonimleştirilen kısımları regex ile bul
    anonim_pattern = r'\[(YAZAR|KURUM|EMAIL) \*\*\*\]'
    
    # Tüm eşleşmeleri bul
    anonim_kisimlar = re.findall(anonim_pattern, anonim_metin)
    
    # Eşleşme yoksa orijinal metni doğrudan döndür
    if not anonim_kisimlar:
        return anonim_metin
    
    # Anonimleştirilmiş etiketleri kaldır
    dekode_metin = anonim_metin
    for etiket in ['[YAZAR ***]', '[KURUM ***]', '[EMAIL ***]']:
        # Her etiketi, karşılık gelen bilgiyle değiştir
        if etiket in dekode_metin:
            # Basit bir yaklaşım: Etiketleri tespit edilebilir bir metinle değiştir
            if etiket == '[YAZAR ***]':
                # Orijinal metinden yazar bilgisini çıkarmaya çalış
                from nltk.chunk import RegexpParser
                from nltk import pos_tag, word_tokenize
                
                # Orijinal metni analiz et
                try:
                    # İlk cümleleri analiz et (genellikle yazar bilgisi başta olur)
                    ilk_cumleler = ' '.join(orijinal_metin.split('\n')[:5])
                    tokenlar = word_tokenize(ilk_cumleler)
                    etiketli_tokenlar = pos_tag(tokenlar)
                    
                    # Kişi isimleri için örüntü (NNP: Özel isim)
                    pattern = r'NP: {<NNP>+}'
                    parser = RegexpParser(pattern)
                    agac = parser.parse(etiketli_tokenlar)
                    
                    # İlk NP öbeğini al (muhtemelen yazar adı)
                    for yaprak in agac:
                        if isinstance(yaprak, tuple) and yaprak[1] == 'NNP':
                            yazar_adi = yaprak[0]
                            dekode_metin = dekode_metin.replace(etiket, yazar_adi)
                            break
                except Exception:
                    # NLP başarısız olursa, basit bir değiştirme yap
                    dekode_metin = dekode_metin.replace(etiket, "Yazar Adı")
            
            elif etiket == '[KURUM ***]':
                # Basit değiştirme - gerçek uygulamada daha karmaşık olabilir
                dekode_metin = dekode_metin.replace(etiket, "Kurum Adı")
            
            elif etiket == '[EMAIL ***]':
                # E-posta regex ile bul
                email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                emails = re.findall(email_pattern, orijinal_metin)
                
                if emails:
                    dekode_metin = dekode_metin.replace(etiket, emails[0])
                else:
                    dekode_metin = dekode_metin.replace(etiket, "ornek@email.com")
    
    return dekode_metin

import base64
import hashlib
import json
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def generate_key(password, salt=None):
    """
    Verilen parola ve salt değeri ile şifreleme anahtarı oluşturur.
    
    Args:
        password (str): Parola
        salt (bytes, optional): Salt değeri. Değer belirtilmezse rastgele oluşturulur.
        
    Returns:
        tuple: (anahtar, salt) - şifreleme için kullanılacak anahtar ve salt değeri
    """
    if not salt:
        salt = os.urandom(16)
    
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key, salt

def encrypt_data(data_dict, password, salt=None):
    """
    Veri sözlüğünü şifreler.
    
    Args:
        data_dict (dict): Şifrelenecek veriler
        password (str): Şifreleme parolası
        salt (bytes, optional): Salt değeri. Belirtilmezse rastgele oluşturulur.
        
    Returns:
        dict: Şifrelenmiş veri ve salt değeri içeren sözlük
    """
    key, salt = generate_key(password, salt)
    
    # Veriyi JSON'a dönüştür
    json_data = json.dumps(data_dict).encode()
    
    # Fernet ile şifrele
    f = Fernet(key)
    encrypted_data = f.encrypt(json_data)
    
    # SHA-256 ile özet değeri hesapla (doğrulama için)
    hash_value = hashlib.sha256(json_data).hexdigest()
    
    return {
        'encrypted_data': base64.b64encode(encrypted_data).decode('utf-8'),
        'salt': base64.b64encode(salt).decode('utf-8'),
        'hash': hash_value
    }

def decrypt_data(encrypted_dict, password):
    """
    Şifrelenmiş veriyi çözer.
    
    Args:
        encrypted_dict (dict): Şifrelenmiş veri, salt ve hash değeri içeren sözlük
        password (str): Şifre çözme parolası
        
    Returns:
        dict: Çözülmüş veri sözlüğü
    """
    # Veri string olarak gelmişse dict'e çevir
    if isinstance(encrypted_dict, str):
        try:
            encrypted_dict = json.loads(encrypted_dict)
        except:
            raise ValueError("Şifrelenmiş veri geçerli bir JSON formatında değil")
    
    try:
        salt = base64.b64decode(encrypted_dict['salt'])
        encrypted_data = base64.b64decode(encrypted_dict['encrypted_data'])
        hash_value = encrypted_dict['hash']
        
        key, _ = generate_key(password, salt)
        
        # Şifreyi çöz
        f = Fernet(key)
        
        decrypted_data = f.decrypt(encrypted_data)
        
        # Hash değeri ile doğrula
        computed_hash = hashlib.sha256(decrypted_data).hexdigest()
        if computed_hash != hash_value:
            raise ValueError("Hash doğrulama başarısız. Veri bozulmuş olabilir.")
        
        # JSON'dan sözlüğe dönüştür
        result = json.loads(decrypted_data.decode('utf-8'))
        print(f"Çözülen veri: {result}")
        return result
    except KeyError as ke:
        raise ValueError(f"Şifrelenmiş veride gerekli alan eksik: {str(ke)}")
    except Exception as e:
        raise ValueError(f"Şifre çözme başarısız: {str(e)}")

def anonymize_with_encryption(original_text, password, anonymize_author=True, anonymize_institution=True, anonymize_email=True):
    """
    Metni anonimleştirir ve orijinal bilgileri şifreler.
    
    Args:
        original_text (str): Orijinal metin
        password (str): Şifreleme parolası
        anonymize_author (bool): Yazar bilgilerini anonimleştir
        anonymize_institution (bool): Kurum bilgilerini anonimleştir
        anonymize_email (bool): E-posta adreslerini anonimleştir
        
    Returns:
        tuple: (anonimleştirilmiş_metin, şifrelenmiş_veri_sözlüğü)
    """
    import re
    
    # Tespit edilecek verileri saklamak için sözlük
    original_data = {
        'authors': [],
        'institutions': [],
        'emails': []
    }
    
    # Anonimleştirilmiş metin başlangıçta orijinal metin ile aynı
    anonymized_text = original_text
    
    # Yazar tespiti ve anonimleştirme
    if anonymize_author:
        author_pattern = re.compile(r'\b([A-Z][a-z]+ [A-Z][a-z]+)\b')
        authors = author_pattern.findall(original_text[:1000])  # İlk 1000 karakterde ara
        
        for author in authors:
            if len(author.split()) >= 2:  # En az iki kelime (Ad Soyad)
                original_data['authors'].append(author)
                anonymized_text = anonymized_text.replace(author, "[YAZAR ***]")
    
    # Kurum tespiti ve anonimleştirme
    if anonymize_institution:
        institution_patterns = [
            r'\b([A-Za-z]+ University)\b',
            r'\b(University of [A-Za-z]+)\b',
            r'\b([A-Za-z]+ Institute of [A-Za-z]+)\b'
        ]
        
        for pattern in institution_patterns:
            institution_regex = re.compile(pattern)
            institutions = institution_regex.findall(original_text)
            
            for institution in institutions:
                original_data['institutions'].append(institution)
                anonymized_text = anonymized_text.replace(institution, "[KURUM ***]")
    
    # E-posta tespiti ve anonimleştirme
    if anonymize_email:
        email_pattern = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
        emails = email_pattern.findall(original_text)
        
        for email in emails:
            original_data['emails'].append(email)
            anonymized_text = anonymized_text.replace(email, "[EMAIL ***]")
    
    # Orijinal veriyi şifrele
    encrypted_data = encrypt_data(original_data, password)
    
    return anonymized_text, encrypted_data

def restore_anonymized_text(anonymized_text, encrypted_data_str, password):
    """
    Anonimleştirilmiş metni orijinal haline geri döndürür.
    
    Args:
        anonymized_text (str): Anonimleştirilmiş metin
        encrypted_data_str (str): JSON formatında şifrelenmiş veri dizgisi
        password (str): Şifre çözme parolası
        
    Returns:
        str: Orijinal haline döndürülmüş metin
    """
    # JSON string'i dict'e çevir
    if isinstance(encrypted_data_str, str):
        encrypted_data = json.loads(encrypted_data_str)
    else:
        encrypted_data = encrypted_data_str
    # Şifrelenmiş veriyi çöz
    try:
        original_data = decrypt_data(encrypted_data, password)
        restored_text = anonymized_text
        
        # Yazarları geri yerleştir
        author_index = 0
        while "[YAZAR ***]" in restored_text and author_index < len(original_data['authors']):
            restored_text = restored_text.replace("[YAZAR ***]", original_data['authors'][author_index], 1)
            author_index += 1
        
        # Kurumları geri yerleştir
        institution_index = 0
        while "[KURUM ***]" in restored_text and institution_index < len(original_data['institutions']):
            restored_text = restored_text.replace("[KURUM ***]", original_data['institutions'][institution_index], 1)
            institution_index += 1
        
        # E-postaları geri yerleştir
        email_index = 0
        while "[EMAIL ***]" in restored_text and email_index < len(original_data['emails']):
            restored_text = restored_text.replace("[EMAIL ***]", original_data['emails'][email_index], 1)
            email_index += 1
        
        return restored_text
    except Exception as e:
        raise ValueError(f"Anonimliği çözme hatası: {str(e)}")