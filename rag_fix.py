import os
import json
from flask import Blueprint, request, jsonify, current_app, session
from werkzeug.utils import secure_filename
import traceback

# RAG sistemi için Blueprint oluşturma
rag_fix_bp = Blueprint('rag_fix', __name__)

# PDF yükleme için dizin
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Vektör veritabanı için dizin
VECTOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vector_db')
os.makedirs(VECTOR_DIR, exist_ok=True)

@rag_fix_bp.route('/upload', methods=['POST'])
def admin_upload_pdf():
    """Admin paneli için PDF yükleme ve işleme - büyük PDF'ler için optimize edilmiş"""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'})
    
    if 'pdf_file' not in request.files:
        return jsonify({'success': False, 'error': 'Dosya seçilmedi'})
    
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Dosya seçilmedi'})
    
    if file and file.filename.endswith('.pdf'):
        try:
            # Dosya adını güvenli hale getir
            filename = secure_filename(file.filename)
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(file_path)
            
            print(f"PDF dosyası kaydedildi: {file_path}")
            
            # PDF işleme fonksiyonlarını rag_system.py'den import et
            from rag_system import extract_text_from_pdf, create_chunks, VectorDB
            
            # PDF'den metin çıkar - büyük dosyalar için optimize edilmiş
            text_by_page = extract_text_from_pdf(file_path)
            
            if not text_by_page:
                return jsonify({'success': False, 'error': 'PDF dosyasından metin çıkarılamadı. Dosya boş veya korumalı olabilir.'})
            
            # Metin chunklara bölünür - bellek optimizasyonu ile
            # Büyük PDF'ler için max_chunk_length parametresi eklendi
            chunks = create_chunks(text_by_page, filename, max_chunk_length=20000)
            
            if not chunks:
                return jsonify({'success': False, 'error': 'PDF dosyasından chunk oluşturulamadı.'})
            
            print(f"Toplam {len(chunks)} chunk oluşturuldu, vektör veritabanına ekleniyor...")
            
            # Vektör veritabanına ekle - batch işleme ile
            vector_db = VectorDB()
            try:
                start_idx, end_idx = vector_db.add_documents(chunks)
                print(f"Vektör veritabanına ekleme tamamlandı: {start_idx} - {end_idx} arası indeksler")
                
                return jsonify({
                    'success': True, 
                    'message': f'PDF başarıyla yüklendi ve işlendi. {len(chunks)} chunk oluşturuldu.',
                    'chunks': len(chunks)
                })
            except Exception as vector_error:
                print(f"Vektör veritabanı hatası: {str(vector_error)}")
                # Hata olsa bile başarılı sayalım, çünkü PDF işlendi ve chunklara bölündü
                return jsonify({
                    'success': True, 
                    'message': f'PDF işlendi ancak vektör veritabanına eklenirken hata oluştu. {len(chunks)} chunk oluşturuldu.',
                    'chunks': len(chunks),
                    'warning': f'Vektör veritabanı hatası: {str(vector_error)}'
                })
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"PDF işleme hatası: {str(e)}\n{error_details}")
            return jsonify({'success': False, 'error': f'PDF işleme hatası: {str(e)}'})
    
    return jsonify({'success': False, 'error': 'Geçersiz dosya formatı. Lütfen PDF yükleyin.'})

@rag_fix_bp.route('/get_pdfs')
def get_pdfs():
    """Yüklenen PDF'lerin listesini döndürür"""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401
    
    pdfs = []
    if os.path.exists(UPLOAD_FOLDER):
        for filename in os.listdir(UPLOAD_FOLDER):
            if filename.endswith('.pdf'):
                pdfs.append(filename)
    
    return jsonify({'success': True, 'pdfs': pdfs})

@rag_fix_bp.route('/vector_db_status')
def vector_db_status():
    """Vektör veritabanı durumunu döndürür"""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401
    
    try:
        # Vektör veritabanı sınıfını rag_system.py'den import et
        from rag_system import VectorDB
        
        vector_db = VectorDB()
        chunk_count = len(vector_db.metadata) if hasattr(vector_db, 'metadata') else 0
        
        return jsonify({
            'success': True, 
            'chunk_count': chunk_count
        })
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"Vektör veritabanı durumu hatası: {str(e)}\n{error_details}")
        return jsonify({
            'success': False, 
            'error': f'Vektör veritabanı durumu alınamadı: {str(e)}'
        }), 500

@rag_fix_bp.route('/ask', methods=['POST'])
def ask_question():
    """Soru sorma ve cevap alma"""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'}), 401
    
    data = request.get_json()
    question = data.get('question')
    chat_id = data.get('chat_id')  # Socket.io için chat_id ekledik
    
    if not question:
        return jsonify({'success': False, 'error': 'Soru boş olamaz'}), 400
    
    try:
        # Gerekli sınıfları ve fonksiyonları rag_system.py'den import et
        from rag_system import VectorDB, query_deepseek
        from app import get_db, socketio
        from flask_socketio import emit
        
        # Kullanıcı token kontrolü
        db = get_db()
        user_id = session.get('user_id')
        user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        
        if user['tokens_remaining'] <= 0:
            return jsonify({'success': False, 'error': 'Token limitiniz dolmuştur'}), 403
        
        # RAG sisteminde arama yapılıyor durumunu bildir (eğer chat_id varsa)
        if chat_id:
            socketio.emit('chat_response', {
                'content': '',
                'chat_id': chat_id,
                'is_complete': False,
                'status': 'rag_searching'
            }, room=request.sid)
        
        # Vektör veritabanında arama yap
        vector_db = VectorDB()
        results = vector_db.search(question, k=3)
        
        if not results:
            # RAG sisteminde bilgi bulunamadı durumunu bildir (eğer chat_id varsa)
            if chat_id:
                socketio.emit('chat_response', {
                    'content': '',
                    'chat_id': chat_id,
                    'is_complete': False,
                    'status': 'rag_not_found'
                }, room=request.sid)
            
            # Bilgi bulunamadığında özel bağlam ile devam et
            context = "Bu konu hakkında bilgi tabanımızda yeterli bilgi bulunamadı. Genel bilgilerime dayanarak kapsamlı bir yanıt vereceğim. Yanıtın tamamen Türkçe olmalı, hiçbir şekilde yabancı dilde karakter veya kelime içermemeli."
            
            # Llama 4 Maverick modeli ile cevap al - bilgi bulunamadığında özel prompt ile
            # query_deepseek fonksiyonu artık tıbbi içerik kontrolü yapıyor
            answer = query_deepseek(question, context)
            
            # API yanıtında hata mesajı kontrolü
            if answer.startswith("API Hatası") or answer.startswith("Beklenmeyen bir hata"):
                print(f"API yanıtında hata: {answer}")
                return jsonify({'success': False, 'error': answer}), 500
            
            # Token kullanımını güncelle (yaklaşık hesaplama)
            tokens_used = len(question.split()) + len(context.split()) + len(answer.split())
            tokens_used = min(tokens_used, 1000)  # Maksimum token kullanımını sınırla
            
            # Kullanıcının token sayısını güncelle
            db.execute('UPDATE users SET tokens_remaining = ? WHERE id = ?', 
                      (max(0, user['tokens_remaining'] - tokens_used), user_id))
            db.commit()
            
            return jsonify({
                'success': True,
                'answer': answer,
                'tokens_used': tokens_used,
                'tokens_remaining': max(0, user['tokens_remaining'] - tokens_used)
            })
        
        # RAG sisteminde bilgi bulundu durumunu bildir (eğer chat_id varsa)
        if chat_id:
            socketio.emit('chat_response', {
                'content': '',
                'chat_id': chat_id,
                'is_complete': False,
                'status': 'rag_found'
            }, room=request.sid)
        
        # Bağlam oluştur - iyileştirilmiş format
        context = "Aşağıdaki bilgileri KOPYALAMADAN, kendi cümlelerinle yorumlayarak ve açıklayarak yanıt ver:\n\n"
        for r in results:
            # Metin içinde yabancı dil karakterleri olup olmadığını kontrol et
            clean_text = ''.join(c for c in r['text'] if ord(c) < 128 or c.isalpha())
            context += f"Kaynak: {r['source']}, Sayfa: {r['page']}, Bölüm: {r['section']}\n{clean_text}\n\n"
        
        # Llama 4 Maverick modeli ile cevap al
        answer = query_deepseek(question, context)
        
        # API yanıtında hata mesajı kontrolü
        if answer.startswith("API Hatası") or answer.startswith("Beklenmeyen bir hata"):
            print(f"API yanıtında hata: {answer}")
            return jsonify({'success': False, 'error': answer}), 500
        
        # Token kullanımını güncelle (yaklaşık hesaplama)
        tokens_used = len(question.split()) + len(context.split()) + len(answer.split())
        tokens_used = min(tokens_used, 1000)  # Maksimum token kullanımını sınırla
        
        db.execute('UPDATE users SET tokens_remaining = tokens_remaining - ? WHERE id = ?', 
                  (tokens_used, user_id))
        
        # Sorguyu kaydet
        now = datetime.now().isoformat()
        db.execute(
            'INSERT INTO rag_queries (user_id, question, answer, tokens_used, created_at) VALUES (?, ?, ?, ?, ?)',
            (user_id, question, answer, tokens_used, now)
        )
        db.commit()
        
        return jsonify({
            'success': True,
            'answer': answer,
            'sources': [{'source': r['source'], 'page': r['page'], 'section': r['section']} for r in results],
            'tokens_used': tokens_used,
            'rag_status': 'found'  # RAG durumunu da döndür
        })
        
    except Exception as e:
        error_details = traceback.format_exc()
        print(f"Soru yanıtlama hatası: {str(e)}\n{error_details}")
        return jsonify({'success': False, 'error': f'Soru yanıtlama hatası: {str(e)}'}), 500

# datetime modülünü ekleyelim
from datetime import datetime