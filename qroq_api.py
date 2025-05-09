import os
import json
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Qroq API key
QROQ_API_KEY = os.getenv('QROQ_API_KEY', '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')

# Qroq API endpoint
QROQ_API_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

# Available models
QROQ_MODELS = {
    "llama-4-maverick-qroq": "meta-llama/llama-4-maverick-17b-128e-instruct",
    "llama3-qroq": "meta-llama/llama-4-scout-17b-16e-instruct",
    "mixtral-qroq": "compound-beta-mini"
}

def query_qroq(messages, model="llama-4-maverick-premium", stream=False, temperature=0.8):
    """Qroq API ile soru cevaplama"""
    headers = {
        'Authorization': f'Bearer {QROQ_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    # Model adını kontrol et ve gerçek model adına dönüştür
    if model in QROQ_MODELS:
        actual_model = QROQ_MODELS[model]
    else:
        # Varsayılan model
        actual_model = QROQ_MODELS["llama-4-maverick-premium"]
    
    payload = {
        'model': actual_model,
        'messages': messages,
        'stream': stream,
        'temperature': temperature
    }
    
    try:
        print(f"Qroq API'ye istek gönderiliyor: {actual_model}")
        response = requests.post(
            QROQ_API_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=60  # Zaman aşımı ekle
        )
        
        print(f"API yanıt durumu: {response.status_code}")
        
        if response.status_code == 200:
            if stream:
                return response  # Stream modunda ham yanıtı döndür
            else:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0 and 'message' in result['choices'][0]:
                    return result['choices'][0]['message']['content']
                else:
                    return "API yanıtı işlenirken bir hata oluştu. Lütfen daha sonra tekrar deneyin."
        else:
            error_msg = f"API Hatası: {response.status_code}"
            try:
                error_detail = response.json()
                if 'error' in error_detail:
                    error_msg += f" - {error_detail['error'].get('message', 'Bilinmeyen hata')}"
                else:
                    error_msg += f" - {error_detail}"
            except:
                error_msg += f" - {response.text[:200]}"
            return error_msg
    
    except requests.exceptions.Timeout:
        return "API isteği zaman aşımına uğradı. Lütfen daha sonra tekrar deneyin."
    except requests.exceptions.RequestException as req_err:
        return f"API bağlantı hatası: {str(req_err)}"
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Beklenmeyen hata: {str(e)}\n{error_details}")
        return f"Beklenmeyen bir hata oluştu: {str(e)}"

def is_medical_query(query):
    """Sorgunun tıbbi içerik içerip içermediğini kontrol eder"""
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
    
    # Sorguyu küçük harfe çevir
    query_lower = query.lower()
    
    # Tıbbi anahtar kelimeleri ara
    for keyword in medical_keywords:
        if keyword.lower() in query_lower:
            return True
    
    return False