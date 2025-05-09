import os
import json
import PyPDF2
import numpy as np
import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from flask import Blueprint, request, jsonify, render_template, current_app, session, redirect, url_for, flash, g
from flask_socketio import emit
from werkzeug.utils import secure_filename
import sqlite3
from datetime import datetime
import time

# RAG sistemi için Blueprint oluşturma
rag_bp = Blueprint('rag', __name__)

# Vektör veritabanı için dizin
VECTOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vector_db')
os.makedirs(VECTOR_DIR, exist_ok=True)

# PDF yükleme için dizin
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# OpenRouter API anahtarı (Llama 4 Maverick modeli için)
DEEPSEEK_API_KEY = os.getenv('OPENROUTER_API_KEY', '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')

# Veritabanı bağlantısı
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(current_app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db

# 1. PDF İşleme Fonksiyonları
def extract_text_from_pdf(pdf_path):
    """PDF'den metin çıkarma - büyük PDF'ler için optimize edilmiş"""
    text_by_page = {}
    try:
        print(f"PDF işleniyor: {pdf_path}")
        with open(pdf_path, 'rb') as file:
            try:
                reader = PyPDF2.PdfReader(file)
                total_pages = len(reader.pages)
                print(f"Toplam {total_pages} sayfa bulundu")
                
                # Büyük PDF'ler için sayfa sayfa işleme
                for i in range(total_pages):
                    try:
                        if i % 10 == 0:
                            print(f"Sayfa işleniyor: {i+1}/{total_pages}")
                        
                        # Sayfa metnini çıkar ve boşlukları temizle
                        text = reader.pages[i].extract_text() or ""
                        text = text.strip()
                        
                        # Metni kaydet
                        text_by_page[i+1] = text
                    except Exception as page_error:
                        print(f"Sayfa {i+1} işlenirken hata: {str(page_error)}")
                        # Hatalı sayfayı boş metin olarak kaydet ve devam et
                        text_by_page[i+1] = ""
                        continue
                
                print(f"PDF işleme tamamlandı: {len(text_by_page)} sayfa işlendi")
                return text_by_page
            except Exception as reader_error:
                print(f"PDF okuyucu hatası: {str(reader_error)}")
                # PyPDF2 başarısız olursa alternatif bir yöntem denenebilir
                # Şimdilik boş sözlük döndür
                return {}
    except Exception as e:
        import traceback
        print(f"PDF işleme hatası: {str(e)}")
        print(traceback.format_exc())
        return {}

def create_chunks(text_by_page, pdf_name, chunk_size=500, overlap=50, max_chunk_length=10000):
    """Metni anlamlı chunklara bölme - bellek optimizasyonu ve büyük PDF'ler için iyileştirilmiş"""
    chunks = []
    total_pages = len(text_by_page)
    processed_pages = 0
    
    # Çok büyük PDF'ler için sayfa sayfa işleme
    for page_num, text in text_by_page.items():
        processed_pages += 1
        if processed_pages % 10 == 0:
            print(f"PDF işleniyor: {processed_pages}/{total_pages} sayfa tamamlandı")
        
        # Çok uzun metinleri kırp
        if len(text) > max_chunk_length:
            text = text[:max_chunk_length]
            print(f"Sayfa {page_num} çok uzun, {max_chunk_length} karaktere kırpıldı")
        
        # Metni paragraflara ayırma - boş satırları temizle
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        current_chunk = ""
        current_size = 0
        
        for para in paragraphs:
            # Çok uzun paragrafları kırp
            if len(para) > max_chunk_length / 2:
                para = para[:int(max_chunk_length/2)]
                print(f"Sayfa {page_num}'de çok uzun paragraf kırpıldı")
            
            para_tokens = len(para.split())
            if para_tokens == 0:  # Boş paragrafları atla
                continue
            
            # Eğer paragraf tek başına chunk_size'dan büyükse, onu böl
            if para_tokens > chunk_size:
                words = para.split()
                for i in range(0, len(words), chunk_size - overlap):
                    end_idx = min(i + chunk_size, len(words))
                    sub_chunk = " ".join(words[i:end_idx])
                    if len(sub_chunk.strip()) > 0:  # Boş chunk'ları atla
                        # Bölümü tahmin et
                        section = detect_section(sub_chunk)
                        chunks.append({
                            "text": sub_chunk,
                            "source": pdf_name,
                            "page": page_num,
                            "section": section
                        })
            else:
                # Mevcut chunk'a paragrafı ekleyebilir miyiz?
                if current_size + para_tokens <= chunk_size:
                    if current_chunk and not current_chunk.endswith("\n"):
                        current_chunk += "\n\n"
                    current_chunk += para
                    current_size += para_tokens
                else:
                    # Mevcut chunk'ı kaydet ve yeni bir chunk başlat
                    if current_chunk and len(current_chunk.strip()) > 0:
                        section = detect_section(current_chunk)
                        chunks.append({
                            "text": current_chunk,
                            "source": pdf_name,
                            "page": page_num,
                            "section": section
                        })
                    current_chunk = para
                    current_size = para_tokens
        
        # Sayfanın son chunk'ını ekle
        if current_chunk and len(current_chunk.strip()) > 0:
            section = detect_section(current_chunk)
            chunks.append({
                "text": current_chunk,
                "source": pdf_name,
                "page": page_num,
                "section": section
            })
    
    print(f"PDF işleme tamamlandı: {len(chunks)} chunk oluşturuldu")
    return chunks

def detect_section(text):
    """Metin içeriğine göre bölüm tahmini yapma"""
    text_lower = text.lower()
    
    if any(keyword in text_lower for keyword in ["tanı", "teşhis"]):
        return "Tanı"
    elif any(keyword in text_lower for keyword in ["tedavi", "terapi", "ilaç"]):
        return "Tedavi"
    elif any(keyword in text_lower for keyword in ["semptom", "belirti", "şikayet"]):
        return "Semptomlar"
    elif any(keyword in text_lower for keyword in ["önleme", "korunma"]):
        return "Önleme"
    elif any(keyword in text_lower for keyword in ["etiyoloji", "neden", "sebep"]):
        return "Etiyoloji"
    else:
        return "Genel Bilgi"

# 2. Vektör Veritabanı Fonksiyonları
class EmbeddingModel:
    def __init__(self):
        # TF-IDF vektörizasyonu kullanarak embedding oluşturma - sabit boyut kullan
        self.embedding_size = 768  # Sabit vektör boyutu
        # max_features parametresini kaldırıp, sonradan boyutlandırma yapacağız
        self.vectorizer = TfidfVectorizer(analyzer='word', ngram_range=(1, 2))
        self.is_fitted = False
    
    def get_embeddings(self, texts):
        """Metinleri vektörlere dönüştürme"""
        if not self.is_fitted:
            # İlk kullanımda fit_transform kullan
            try:
                embeddings = self.vectorizer.fit_transform(texts).toarray()
                self.is_fitted = True
            except Exception as e:
                print(f"Vektörizasyon hatası: {str(e)}")
                # Hata durumunda boş vektörler oluştur ve işleme devam et
                return np.zeros((len(texts), self.embedding_size))
        else:
            try:
                # Sonraki kullanımlarda transform kullan
                embeddings = self.vectorizer.transform(texts).toarray()
            except Exception as e:
                print(f"Transform hatası: {str(e)}")
                # Hata durumunda boş vektörler oluştur
                return np.zeros((len(texts), self.embedding_size))
        
        # Her zaman sabit boyutlu vektörler oluştur
        fixed_embeddings = np.zeros((len(texts), self.embedding_size))
        
        # Vektör boyutunu kontrol et ve düzelt
        if embeddings.shape[1] != self.embedding_size:
            # Boyutu düzelt - ya kırp ya da genişlet
            min_dim = min(embeddings.shape[1], self.embedding_size)
            for i, emb in enumerate(embeddings):
                fixed_embeddings[i, :min_dim] = emb[:min_dim]
            embeddings = fixed_embeddings
        else:
            # Boyut doğru olsa bile kopyala
            fixed_embeddings = embeddings.copy()
        
        # Vektörleri normalize et
        normalized_embeddings = []
        for emb in embeddings:
            norm = np.linalg.norm(emb)
            if norm > 0:
                normalized_embeddings.append(emb / norm)
            else:
                normalized_embeddings.append(emb)
        
        return np.array(normalized_embeddings)

class VectorDB:
    def __init__(self, index_name="medical_docs"):
        self.index_name = index_name
        self.metadata_path = os.path.join(VECTOR_DIR, f"{index_name}_metadata.json")
        self.vectors_path = os.path.join(VECTOR_DIR, f"{index_name}_vectors.npy")
        self.embedding_model = EmbeddingModel()
        
        # Eğer vektörler ve metadata varsa yükle, yoksa oluştur
        if os.path.exists(self.vectors_path) and os.path.exists(self.metadata_path):
            self.vectors = np.load(self.vectors_path)
            with open(self.metadata_path, 'r', encoding='utf-8') as f:
                self.metadata = json.load(f)
        else:
            self.vectors = np.array([])
            self.metadata = []
    
    def add_documents(self, chunks):
        """Dokümanları vektör veritabanına ekleme"""
        # Bellek yönetimi için büyük chunk listelerini daha küçük parçalara böl
        batch_size = 50  # Bir seferde işlenecek maksimum chunk sayısı
        start_idx = len(self.metadata)
        end_idx = start_idx
        
        # Chunklari batch'ler halinde işle
        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i:i+batch_size]
            try:
                texts = [chunk["text"] for chunk in batch_chunks]
                embeddings = self.embedding_model.get_embeddings(texts)
                
                # Vektör boyutu kontrolü
                expected_dim = self.embedding_model.embedding_size
                if embeddings.shape[1] != expected_dim:
                    print(f"Vektör boyutu uyuşmazlığı: {embeddings.shape[1]} != {expected_dim}")
                    # Boyutu düzelt
                    fixed_embeddings = np.zeros((embeddings.shape[0], expected_dim))
                    min_dim = min(embeddings.shape[1], expected_dim)
                    for j, emb in enumerate(embeddings):
                        fixed_embeddings[j, :min_dim] = emb[:min_dim]
                    embeddings = fixed_embeddings
                
                # Vektörleri ekle
                if self.vectors.size == 0:
                    self.vectors = embeddings
                else:
                    # Boyut kontrolü yap
                    if self.vectors.shape[1] != embeddings.shape[1]:
                        print(f"Mevcut vektörler ile yeni vektörler arasında boyut uyuşmazlığı: {self.vectors.shape[1]} != {embeddings.shape[1]}")
                        # Mevcut vektörleri yeniden boyutlandır
                        resized_vectors = np.zeros((self.vectors.shape[0], expected_dim))
                        min_dim = min(self.vectors.shape[1], expected_dim)
                        for j in range(self.vectors.shape[0]):
                            resized_vectors[j, :min_dim] = self.vectors[j, :min_dim]
                        self.vectors = resized_vectors
                    
                    # Şimdi güvenle birleştir
                    self.vectors = np.vstack((self.vectors, embeddings))
                
                # Metadata'yı güncelle
                for chunk in batch_chunks:
                    self.metadata.append(chunk)
                    end_idx += 1
                
                # Her batch sonrası kaydet
                self._save()
                
            except Exception as e:
                import traceback
                print(f"Batch işleme hatası: {str(e)}")
                print(traceback.format_exc())
                # Hata olsa bile devam et
                continue
        
        return start_idx, end_idx - 1
    
    def search(self, query, k=3):
        """Sorguya en yakın k dokümanı bulma"""
        if len(self.metadata) == 0:
            return []
            
        query_embedding = self.embedding_model.get_embeddings([query])
        
        # Kosinüs benzerliği hesapla
        similarities = cosine_similarity(query_embedding, self.vectors)[0]
        
        # En yüksek benzerliğe sahip k dokümanı bul
        top_indices = np.argsort(similarities)[::-1][:k]
        
        results = []
        for idx in top_indices:
            if idx < len(self.metadata):
                result = self.metadata[idx].copy()
                result["score"] = float(similarities[idx])
                results.append(result)
        
        return results
    
    def _save(self):
        """Vektörler ve metadata'yı diske kaydetme"""
        # Dizinin var olduğundan emin ol
        os.makedirs(os.path.dirname(self.vectors_path), exist_ok=True)
        
        # Vektörleri kaydet
        np.save(self.vectors_path, self.vectors)
        
        # Metadata'yı kaydet
        with open(self.metadata_path, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        
        print(f"Vektör veritabanı kaydedildi: {len(self.metadata)} chunk, {self.vectors.shape if self.vectors.size > 0 else '0'} vektör boyutu")
        return True

# 3. Soru-Cevap Sistemi
def check_if_medical_content(query, context):
    """Sorgu ve bağlamın tıbbi içerik içerip içermediğini kontrol eder"""
    # Tıbbi terimler ve anahtar kelimeler listesi
    medical_keywords = [
        # Hastalıklar ve durumlar
        "hastalık", "sendrom", "enfeksiyon", "virüs", "bakteri", "kanser", "tümör", "diyabet", "hipertansiyon", "tansiyon",
        "kalp", "astım", "alerji", "migren", "depresyon", "anksiyete", "alzheimer", "parkinson", "epilepsi", "felç", "inme",
        "obezite", "artrit", "romatizma", "osteoporoz", "fibromiyalji", "ms", "multipl skleroz", "sedef", "egzama", "ülser",
        
        # Tıbbi terimler
        "teşhis", "tanı", "tedavi", "semptom", "belirti", "ilaç", "reçete", "doz", "yan etki", "aşı", "bağışıklık",
        "ameliyat", "cerrahi", "operasyon", "terapi", "rehabilitasyon", "fizyoterapi", "psikoterapi", "kemoterapi", "radyoterapi",
        "antibiyotik", "antidepresan", "antihistaminik", "antiinflamatuar", "ağrı kesici", "ateş düşürücü",
        
        # Vücut bölümleri ve sistemler
        "beyin", "akciğer", "karaciğer", "böbrek", "mide", "bağırsak", "kemik", "eklem", "kas", "damar", "sinir",
        "hormon", "enzim", "protein", "vitamin", "mineral", "kan", "idrar", "balgam", "dışkı", "ter", "tükürük",
        "sindirim", "solunum", "dolaşım", "boşaltım", "üreme", "bağışıklık sistemi", "sinir sistemi", "endokrin sistem",
        
        # Tıbbi uzmanlıklar ve sağlık çalışanları
        "doktor", "hekim", "uzman", "cerrah", "hemşire", "eczacı", "fizyoterapist", "psikolog", "psikiyatrist", "diyetisyen",
        "kardiyolog", "nörolog", "gastroenterolog", "endokrinolog", "onkolog", "pediatrist", "jinekolog", "ürolog", "ortopedi",
        "dermatoloji", "oftalmoloji", "kulak burun boğaz", "kbb", "radyoloji", "patoloji", "anestezi",
        
        # Tıbbi kurumlar ve hizmetler
        "hastane", "klinik", "poliklinik", "acil servis", "yoğun bakım", "laboratuvar", "eczane", "sağlık ocağı", "aile hekimi",
        "muayene", "konsültasyon", "tahlil", "test", "analiz", "röntgen", "ultrason", "tomografi", "mri", "ekg", "eeg"
    ]
    
    # Sorgu ve bağlamı birleştir ve küçük harfe çevir
    combined_text = (query + " " + context).lower()
    
    # Tıbbi anahtar kelimeleri ara
    for keyword in medical_keywords:
        if keyword.lower() in combined_text:
            return True
    
    return False

def query_deepseek(query, context):
    """Llama 4 Maverick modeli ile soru cevaplama"""
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    # İçeriğin tıbbi olup olmadığını kontrol et
    is_medical_content = check_if_medical_content(query, context)
    
    # Prompt hazırlama - Türkçe yanıt için iyileştirildi
    # Sadece tıbbi içerik varsa uyarı mesajı ekle
    medical_disclaimer = "Uyarı: Bu bilgiler yapay zeka tarafından verilmektedir ve bir uzmanın görüşünün yerini tutmaz. Teşhis koymak için kullanılamaz."
    
    prompt = f"""Aşağıdaki bağlamlara göre soruyu yanıtla. Kapsamlı ve detaylı cevap ver. Bilimsel ve anlaşılır ol.

Yanıtın şu özelliklere sahip olmalı:
1. Tamamen Türkçe olmalı, HİÇBİR ŞEKİLDE başka dilde karakter veya kelime kullanma
2. Kapsamlı ve detaylı olmalı (en az 3-4 paragraf)
3. Bilimsel ve doğru bilgiler içermeli
4. Anlaşılır bir dille yazılmalı
5. Verilen bağlam bilgilerini OLDUĞU GİBİ KOPYALAMA, bu bilgileri kendi cümlelerinle yorumla ve açıkla
{f'6. Yanıtın sonuna şu uyarıyı eklemelisin: "{medical_disclaimer}"' if is_medical_content else ''}

---Bağlam---
{context}

---Soru---
{query}

Önemli: Yanıtını oluştururken bağlam bilgilerini olduğu gibi kopyalama, kendi cümlelerinle yorumla. Yanıtın tamamen Türkçe olmalı, hiçbir şekilde yabancı dilde karakter veya kelime içermemeli."""
    
    payload = {
        'model': 'meta-llama/llama-4-maverick:free',
        'messages': [{'role': 'user', 'content': prompt}],
        'stream': False,
        'temperature': 0.8  # Daha uzun ve detaylı yanıtlar için temperature değeri yükseltildi
    }
    
    # Debug bilgisi ekle
    print(f"OpenRouter API anahtarı: {DEEPSEEK_API_KEY[:5]}...")
    print(f"Kullanılan model: {payload['model']}")
    print(f"İstek gönderiliyor: {headers}")
    print(f"Payload: {json.dumps(payload, ensure_ascii=False)[:200]}...")

    
    try:
        print(f"OpenRouter API'ye istek gönderiliyor: {payload['model']}")
        response = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers=headers,
            json=payload,
            timeout=60  # Zaman aşımı ekle
        )
        
        print(f"API yanıt durumu: {response.status_code}")
        print(f"API yanıt içeriği: {response.text[:500]}")
        
        if response.status_code == 200:
            try:
                result = response.json()
                print(f"API yanıt JSON: {json.dumps(result, ensure_ascii=False)[:500]}")
                
                if 'choices' in result and len(result['choices']) > 0 and 'message' in result['choices'][0]:
                    answer = result['choices'][0]['message']['content']
                    print(f"Alınan cevap: {answer[:100]}...")
                    
                    # Tıbbi içerik kontrolü ve uyarı mesajı ekleme
                    if is_medical_content and medical_disclaimer not in answer:
                        # Eğer tıbbi içerikse ve uyarı mesajı yoksa, uyarı mesajını ekle
                        answer = answer + "\n\n" + medical_disclaimer
                    
                    return answer
                else:
                    print(f"API yanıtı geçerli bir format içermiyor: {result}")
                    return "API yanıtı işlenirken bir hata oluştu. Lütfen daha sonra tekrar deneyin."
            except ValueError as json_err:
                print(f"JSON ayrıştırma hatası: {str(json_err)}. Yanıt: {response.text[:500]}")
                return "API yanıtı JSON formatında değil. Lütfen daha sonra tekrar deneyin."
        else:
            error_msg = f"API Hatası: {response.status_code}"
            try:
                error_detail = response.json()
                print(f"API hata detayı: {json.dumps(error_detail, ensure_ascii=False)}")
                
                # Hata mesajını daha detaylı analiz et
                if 'error' in error_detail:
                    error_obj = error_detail['error']
                    if isinstance(error_obj, dict):
                        error_type = error_obj.get('type', '')
                        error_message = error_obj.get('message', 'Bilinmeyen hata')
                        print(f"Hata tipi: {error_type}, Mesaj: {error_message}")
                        
                        # Model adı hatası kontrolü
                        if 'model' in error_message.lower() or 'not found' in error_message.lower():
                            print("Model adı hatası tespit edildi!")
                            # Model adını düzelt ve tekrar dene
                            payload['model'] = 'meta-llama/llama-4-maverick:free'
                            print(f"Model adı düzeltildi: {payload['model']}")
                            
                            # Tekrar istek gönder
                            print("Düzeltilmiş model adı ile tekrar istek gönderiliyor...")
                            response = requests.post(
                                'https://openrouter.ai/api/v1/chat/completions',
                                headers=headers,
                                json=payload,
                                timeout=60
                            )
                            
                            if response.status_code == 200:
                                try:
                                    result = response.json()
                                    if 'choices' in result and len(result['choices']) > 0 and 'message' in result['choices'][0]:
                                        answer = result['choices'][0]['message']['content']
                                        print(f"Düzeltilmiş model ile alınan cevap: {answer[:100]}...")
                                        return answer
                                except Exception as retry_err:
                                    print(f"Düzeltilmiş model ile tekrar denemede hata: {str(retry_err)}")
                        
                        error_msg += f" - {error_message}"
                    else:
                        error_msg += f" - {error_obj}"
                else:
                    error_msg += f" - {error_detail}"
            except Exception as parse_err:
                print(f"API hata yanıtı ayrıştırma hatası: {str(parse_err)}")
                print(f"API hata yanıtı: {response.text[:500]}")
                error_msg += f" - {response.text[:200]}"
            return error_msg
    
    except requests.exceptions.Timeout:
        print("API isteği zaman aşımına uğradı")
        return "API isteği zaman aşımına uğradı. Lütfen daha sonra tekrar deneyin."
    except requests.exceptions.RequestException as req_err:
        print(f"API istek hatası: {str(req_err)}")
        return f"API bağlantı hatası: {str(req_err)}"
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Beklenmeyen hata: {str(e)}\n{error_details}")
        return f"Beklenmeyen bir hata oluştu: {str(e)}"

# 4. Flask Route'ları
@rag_bp.route('/rag')
def rag_index():
    """RAG ana sayfası"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    # Kullanıcı bilgilerini al
    db = get_db()
    user_id = session.get('user_id')
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    
    # Yüklenen PDF'leri listele
    pdfs = []
    if os.path.exists(UPLOAD_FOLDER):
        for filename in os.listdir(UPLOAD_FOLDER):
            if filename.endswith('.pdf'):
                pdfs.append(filename)
    
    return render_template('rag.html', user=user, pdfs=pdfs)

@rag_bp.route('/get_pdfs')
def get_pdfs():
    """Yüklenen PDF'lerin listesini döndürür"""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'})
    
    pdfs = []
    if os.path.exists(UPLOAD_FOLDER):
        for filename in os.listdir(UPLOAD_FOLDER):
            if filename.endswith('.pdf'):
                pdfs.append(filename)
    
    return jsonify({'success': True, 'pdfs': pdfs})

@rag_bp.route('/delete_pdf', methods=['POST'])
def delete_pdf():
    """PDF dosyasını siler"""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'})
    
    # Admin kontrolü
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Bu işlem için admin yetkisi gerekiyor'})
    
    data = request.get_json()
    filename = data.get('filename')
    
    if not filename:
        return jsonify({'success': False, 'error': 'Dosya adı belirtilmedi'})
    
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'error': 'Dosya bulunamadı'})
    
    try:
        os.remove(file_path)
        return jsonify({'success': True, 'message': f'{filename} başarıyla silindi'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Dosya silinirken hata oluştu: {str(e)}'})

@rag_bp.route('/vector_db_status')
def vector_db_status():
    """Vektör veritabanı durumunu döndürür"""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401
    
    try:
        vector_db = VectorDB()
        chunk_count = len(vector_db.metadata) if hasattr(vector_db, 'metadata') else 0
        
        # Sadece jsonify kullanarak JSON yanıtı döndür
        # Flask otomatik olarak Content-Type'ı application/json olarak ayarlar
        return jsonify({
            'success': True, 
            'chunk_count': chunk_count
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Vektör veritabanı durumu hatası: {str(e)}\n{error_details}")
        # Hata durumunda 500 durum kodu ile yanıt döndür
        return jsonify({
            'success': False, 
            'error': f'Vektör veritabanı durumu alınamadı: {str(e)}'
        }), 500

@rag_bp.route('/upload_pdf', methods=['POST'])
def upload_pdf():
    """PDF yükleme ve işleme"""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'})
    
    if 'pdf_file' not in request.files:
        return jsonify({'success': False, 'error': 'Dosya seçilmedi'})
    
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Dosya seçilmedi'})
    
    if file and file.filename.endswith('.pdf'):
        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)
        
        # PDF'i işle ve vektör veritabanına ekle
        try:
            # PDF'den metin çıkar
            text_by_page = extract_text_from_pdf(file_path)
            
            if not text_by_page:
                return jsonify({'success': False, 'error': 'PDF dosyasından metin çıkarılamadı. Dosya boş veya korumalı olabilir.'})
            
            # Metin chunklara bölünür
            chunks = create_chunks(text_by_page, filename)
            
            if not chunks:
                return jsonify({'success': False, 'error': 'PDF dosyasından chunk oluşturulamadı.'})
            
            # Vektör veritabanı dizininin varlığını kontrol et ve oluştur
            os.makedirs(VECTOR_DIR, exist_ok=True)
            
            # Vektör veritabanına ekle
            vector_db = VectorDB()
            start_idx, end_idx = vector_db.add_documents(chunks)
            
            return jsonify({
                'success': True, 
                'message': f'PDF başarıyla yüklendi ve işlendi. {len(chunks)} chunk oluşturuldu.',
                'chunks': len(chunks)
            })
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"PDF işleme hatası: {str(e)}\n{error_details}")
            return jsonify({'success': False, 'error': f'PDF işleme hatası: {str(e)}'})
    
    return jsonify({'success': False, 'error': 'Geçersiz dosya formatı. Lütfen PDF yükleyin.'})

@rag_bp.route('/ask', methods=['POST'])
def ask_question():
    """Soru sorma ve cevap alma"""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'})
    
    data = request.get_json()
    question = data.get('question')
    
    if not question:
        return jsonify({'success': False, 'error': 'Soru boş olamaz'})
    
    # Kullanıcı token kontrolü
    db = get_db()
    user_id = session.get('user_id')
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    
    if user['tokens_remaining'] <= 0:
        return jsonify({'success': False, 'error': 'Token limitiniz dolmuştur'})
    
    # Socket.io bağlantısı üzerinden bilgi tabanında arama yapıldığını bildir
    socketio = current_app.extensions['socketio']
    socketio.emit('chat_response', {
        'content': '',
        'chat_id': None,
        'is_complete': False,
        'status': 'searching'
    }, room=request.sid)
    
    # Vektör veritabanında arama yap
    try:
        vector_db = VectorDB()
        results = vector_db.search(question, k=3)
        
        if not results:
            # Bilgi bulunamadığında özel bir mesaj ekle
            context = "Bu konu hakkında bilgi tabanımızda yeterli bilgi bulunamadı. Genel bilgilerime dayanarak kapsamlı bir yanıt vereceğim."
            
            # AI'nin düşündüğünü bildir
            socketio.emit('chat_response', {
                'content': '',
                'chat_id': None,
                'is_complete': False,
                'status': 'thinking'
            }, room=request.sid)
            
            # Llama 4 Maverick modeli ile cevap al - bilgi bulunamadığında özel prompt ile
            try:
                answer = query_deepseek(question, context)
                
                # API yanıtında hata mesajı kontrolü
                if answer.startswith("API Hatası") or answer.startswith("Beklenmeyen bir hata"):
                    print(f"API yanıtında hata: {answer}")
                    return jsonify({'success': False, 'error': answer})
                
                # Token kullanımını güncelle (yaklaşık hesaplama)
                tokens_used = len(question.split()) + len(context.split()) + len(answer.split())
                tokens_used = min(tokens_used, 1000)  # Maksimum token kullanımını sınırla
            except Exception as api_err:
                print(f"API yanıtı işlenirken hata: {str(api_err)}")
                return jsonify({'success': False, 'error': f'API yanıtı işlenirken hata: {str(api_err)}'})
            
            new_tokens = user['tokens_remaining'] - tokens_used
            db.execute('UPDATE users SET tokens_remaining = ? WHERE id = ?', (new_tokens, user_id))
            db.commit()
            
            # Soru ve cevabı veritabanına kaydet
            db.execute(
                'INSERT INTO rag_queries (user_id, question, answer, tokens_used, created_at) VALUES (?, ?, ?, ?, ?)',
                (user_id, question, answer, tokens_used, datetime.now().isoformat())
            )
            db.commit()
            
            response = jsonify({
                'success': True,
                'answer': answer,
                'sources': [],  # Bilgi bulunamadığında kaynak yok
                'tokens_used': tokens_used,
                'tokens_remaining': new_tokens,
                'info': 'Bilgi tabanında bu konu hakkında bilgi bulunamadı. Genel bilgilerime dayanarak yanıt verdim.'
            })
            response.headers['Content-Type'] = 'application/json'
            return response
        
        # Bağlam oluştur
        context = "\n\n".join([f"Kaynak: {r['source']}, Sayfa: {r['page']}, Bölüm: {r['section']}\n{r['text']}" for r in results])
        
        # AI'nin düşündüğünü bildir
        socketio.emit('chat_response', {
            'content': '',
            'chat_id': None,
            'is_complete': False,
            'status': 'thinking'
        }, room=request.sid)
        
        # Llama 4 Maverick modeli ile cevap al
        try:
            answer = query_deepseek(question, context)
            
            # API yanıtında hata mesajı kontrolü
            if answer.startswith("API Hatası") or answer.startswith("Beklenmeyen bir hata"):
                print(f"API yanıtında hata: {answer}")
                return jsonify({'success': False, 'error': answer})
            
            # Token kullanımını güncelle (yaklaşık hesaplama)
            tokens_used = len(question.split()) + len(context.split()) + len(answer.split())
            tokens_used = min(tokens_used, 50)  # Minimum token kullanımı
        except Exception as api_err:
            print(f"API yanıtı işlenirken hata: {str(api_err)}")
            return jsonify({'success': False, 'error': f'API yanıtı işlenirken hata: {str(api_err)}'})
        
        new_tokens = user['tokens_remaining'] - tokens_used
        db.execute('UPDATE users SET tokens_remaining = ? WHERE id = ?', (new_tokens, user_id))
        db.commit()
        
        # Soru ve cevabı veritabanına kaydet
        db.execute(
            'INSERT INTO rag_queries (user_id, question, answer, tokens_used, created_at) VALUES (?, ?, ?, ?, ?)',
            (user_id, question, answer, tokens_used, datetime.now().isoformat())
        )
        db.commit()
        
        response = jsonify({
            'success': True,
            'answer': answer,
            'sources': [{'source': r['source'], 'page': r['page'], 'section': r['section']} for r in results],
            'tokens_used': tokens_used,
            'tokens_remaining': new_tokens
        })
        response.headers['Content-Type'] = 'application/json'
        return response
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Sorgulama hatası: {str(e)}\n{error_details}")
        error_response = jsonify({'success': False, 'error': f'Sorgulama hatası: {str(e)}'})
        error_response.headers['Content-Type'] = 'application/json'
        return error_response

# Veritabanı tablosu oluşturma
def init_rag_db():
    db = get_db()
    
    db.execute('''
    CREATE TABLE IF NOT EXISTS rag_queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        tokens_used INTEGER DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')
    
    db.commit()