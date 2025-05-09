from flask import Flask, request, jsonify, render_template, session, redirect, url_for, g, flash
from flask_socketio import SocketIO, emit
from flask_bcrypt import Bcrypt
import os
import requests
import json
import sqlite3
from datetime import datetime
import time
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from rag_fix import rag_fix_bp

# Load environment variables
load_dotenv()
# Add this to your existing socket.io events in app.py


app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')
app.config['DATABASE'] = os.path.join(os.path.dirname(__file__), 'chat_app.db')

# Initialize extensions
bcrypt = Bcrypt(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# API keys
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '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')

# OpenRouter API endpoint
OPENROUTER_API_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

# OpenRouter modelleri
OPENROUTER_MODELS = {
    "llama-4-maverick-openrouter": "meta-llama/llama-4-maverick:free",
    "llama-3-openrouter": "meta-llama/llama-4-scout:free",
    "claude-3-opus-openrouter": "deepseek/deepseek-chat-v3-0324:free"
}

# Qroq API entegrasyonu
from qroq_api import query_qroq, is_medical_query, QROQ_MODELS

# PDF yükleme için dizin
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Vektör veritabanı için dizin
VECTOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vector_db')
os.makedirs(VECTOR_DIR, exist_ok=True)

# Database helper functions
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db

def close_db(e=None):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.teardown_appcontext
def close_connection(exception):
    close_db()

# User session management
def login_user(user_id, username, is_admin):
    session['user_id'] = user_id
    session['username'] = username
    session['is_admin'] = is_admin
    session['logged_in'] = True

def logout_user():
    session.clear()

def is_logged_in():
    return session.get('logged_in', False)

def is_admin():
    return session.get('is_admin', False)

def get_current_user():
    if not is_logged_in():
        return None
    
    user_id = session.get('user_id')
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    return user

# Routes
@app.route('/')
def index():
    if is_logged_in():
        user = get_current_user()
        # Kullanıcının sohbet geçmişini getir
        db = get_db()
        chats = db.execute(
            'SELECT * FROM chats WHERE user_id = ? ORDER BY updated_at DESC', 
            (user['id'],)
        ).fetchall()
        return render_template('chat.html', user=user, chats=chats)
    return render_template('login.html')

@app.route('/chat/<int:chat_id>')
def view_chat(chat_id):
    if not is_logged_in():
        return redirect(url_for('login'))
    
    user = get_current_user()
    db = get_db()
    
    # Sohbetin kullanıcıya ait olup olmadığını kontrol et
    chat = db.execute('SELECT * FROM chats WHERE id = ? AND user_id = ?', (chat_id, user['id'])).fetchone()
    if not chat:
        return redirect(url_for('index'))
    
    # Sohbet mesajlarını getir
    messages = db.execute('SELECT * FROM messages WHERE chat_id = ? ORDER BY created_at', (chat_id,)).fetchall()
    
    # Kullanıcının tüm sohbetlerini getir
    chats = db.execute(
        'SELECT * FROM chats WHERE user_id = ? ORDER BY updated_at DESC', 
        (user['id'],)
    ).fetchall()
    
    return render_template('chat.html', user=user, chats=chats, current_chat=chat, messages=messages)

@app.route('/new_chat', methods=['GET'])
def new_chat():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    try:
        user = get_current_user()
        db = get_db()
        
        # Yeni sohbet oluştur
        now = datetime.now().isoformat()
        db.execute(
            'INSERT INTO chats (user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)',
            (user['id'], 'Yeni Sohbet', now, now)
        )
        db.commit()
        
        return redirect(url_for('index'))
    except Exception as e:
        print(f"Yeni sohbet oluşturma hatası: {str(e)}")
        flash('Sohbet oluşturulurken bir hata oluştu. Lütfen tekrar deneyin.', 'error')
        return redirect(url_for('index'))

@app.route('/update_chat_title', methods=['POST'])
def update_chat_title():
    if not is_logged_in():
        return jsonify({'success': False, 'error': 'Oturum açmanız gerekiyor'})
    
    data = request.get_json()
    chat_id = data.get('chat_id')
    title = data.get('title')
    
    if not chat_id or not title:
        return jsonify({'success': False, 'error': 'Geçersiz istek'})
    
    user = get_current_user()
    db = get_db()
    
    # Sohbetin kullanıcıya ait olup olmadığını kontrol et
    chat = db.execute('SELECT * FROM chats WHERE id = ? AND user_id = ?', (chat_id, user['id'])).fetchone()
    if not chat:
        return jsonify({'success': False, 'error': 'Sohbet bulunamadı'})
    
    # Sohbet başlığını güncelle
    db.execute('UPDATE chats SET title = ? WHERE id = ?', (title, chat_id))
    db.commit()
    
    return jsonify({'success': True})

@app.route('/delete_chat/<int:chat_id>', methods=['POST'])
def delete_chat(chat_id):
    if not is_logged_in():
        return redirect(url_for('login'))
    
    user = get_current_user()
    db = get_db()
    
    # Sohbetin kullanıcıya ait olup olmadığını kontrol et
    chat = db.execute('SELECT * FROM chats WHERE id = ? AND user_id = ?', (chat_id, user['id'])).fetchone()
    if not chat:
        return redirect(url_for('index'))
    
    # Önce sohbete ait mesajları sil
    db.execute('DELETE FROM messages WHERE chat_id = ?', (chat_id,))
    # Sonra sohbeti sil
    db.execute('DELETE FROM chats WHERE id = ?', (chat_id,))
    db.commit()
    
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if is_logged_in():
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        db = get_db()
        # Check if username or email already exists
        user_exists = db.execute('SELECT * FROM users WHERE username = ? OR email = ?', 
                                (username, email)).fetchone()
        if user_exists:
            return render_template('register.html', error='Username or email already exists')
        
        # Create new user
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        db.execute(
            'INSERT INTO users (username, email, password, is_admin, tokens_remaining, plan, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (username, email, hashed_password, 0, 100, 'basic', datetime.now().isoformat())
        )
        db.commit()
        
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if is_logged_in():
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user and bcrypt.check_password_hash(user['password'], password):
            login_user(user['id'], user['username'], bool(user['is_admin']))
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/profile')
def profile():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    return render_template('profile.html', user=get_current_user())

@app.route('/admin')
def admin():
    if not is_logged_in() or not is_admin():
        return redirect(url_for('login'))
    
    db = get_db()
    users = db.execute('SELECT * FROM users').fetchall()
    
    # Yüklenen PDF'leri listele
    pdfs = []
    if os.path.exists(UPLOAD_FOLDER):
        for filename in os.listdir(UPLOAD_FOLDER):
            if filename.endswith('.pdf'):
                pdfs.append(filename)
    
    # Pass the current user information to the template
    return render_template('admin.html', users=users, user=get_current_user(), pdfs=pdfs)

@app.route('/admin/update_user', methods=['POST'])
def update_user():
    if not is_logged_in() or not is_admin():
        return redirect(url_for('login'))
    
    user_id = request.form.get('user_id')
    tokens = request.form.get('tokens')
    plan = request.form.get('plan')
    
    db = get_db()
    db.execute('UPDATE users SET tokens_remaining = ?, plan = ? WHERE id = ?',
              (tokens, plan, user_id))
    db.commit()
    
    return redirect(url_for('admin'))

# Socket.IO events
@socketio.on('connect')
def handle_connect():
    if not is_logged_in():
        return False
    print(f"Client connected: {session.get('username')}")

# OpenRouter API ile soru cevaplama
def query_openrouter(messages, model="llama-4-maverick-openrouter", stream=False, temperature=0.8):
    """OpenRouter API ile soru cevaplama"""
    headers = {
        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
        'Content-Type': 'application/json',
        'HTTP-Referer': 'https://newedu.ai',  # OpenRouter için gerekli
        'X-Title': 'NewEdu AI'  # OpenRouter için gerekli
    }
    
    # Model adını kontrol et ve gerçek model adına dönüştür
    if model in OPENROUTER_MODELS:
        actual_model = OPENROUTER_MODELS[model]
    else:
        # Varsayılan model
        actual_model = OPENROUTER_MODELS["llama-4-maverick-openrouter"]
    
    payload = {
        'model': actual_model,
        'messages': messages,
        'stream': stream,
        'temperature': temperature
    }
    
    try:
        print(f"OpenRouter API'ye istek gönderiliyor: {actual_model}")
        response = requests.post(
            OPENROUTER_API_ENDPOINT,
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

@socketio.on('chat_message')
def handle_chat_message(data):
    if not is_logged_in():
        return
    
    user = get_current_user()
    message = data.get('message')
    model = data.get('model', 'llama-4-maverick-qroq')  # Varsayılan model olarak Qroq'un Llama 4 Maverick modeli ayarlandı
    chat_id = data.get('chat_id')
    
    # RAG sistemini kullanıp kullanmayacağımızı kontrol et - sadece tıbbi sorularda kullan
    use_rag = False
    try:
        # Basit selamlaşma veya teşekkür mesajları için RAG kullanma
        simple_greetings = ['merhaba', 'selam', 'nasılsın', 'teşekkür', 'teşekkürler', 'sağol', 'hoşça kal', 'günaydın', 'iyi günler', 'iyi akşamlar']
        is_simple_message = any(greeting in message.lower() for greeting in simple_greetings) and len(message.split()) < 5
        
        if is_simple_message:
            # Basit mesajlar için RAG kullanma
            pass
        # Sadece tıbbi sorularda RAG sistemini kullan
        elif is_medical_query(message):
            from rag_system import VectorDB
            vector_db = VectorDB()
            
            # RAG sisteminde arama yapılıyor durumunu bildir
            emit('chat_response', {
                'content': '',
                'chat_id': chat_id,
                'is_complete': False,
                'status': 'rag_searching'
            }, room=request.sid)
            
            # RAG sisteminde ara - daha alakalı sonuçlar için k değerini azalttık
            results = vector_db.search(message, k=2)
            
            # Sonuçların alakalı olup olmadığını kontrol et
            relevant_results = []
            if results and len(results) > 0:
                # Basit bir alaka skoru hesapla (mesajdaki anahtar kelimelerin sonuçlarda bulunması)
                keywords = [word.lower() for word in message.split() if len(word) > 3]
                for result in results:
                    relevance_score = 0
                    for keyword in keywords:
                        if keyword in result['text'].lower():
                            relevance_score += 1
                    # En az bir anahtar kelime eşleşiyorsa alakalı kabul et
                    if relevance_score > 0:
                        relevant_results.append(result)
            
            if relevant_results:
                use_rag = True
                # RAG sisteminde bilgi bulundu durumunu bildir
                emit('chat_response', {
                    'content': '',
                    'chat_id': chat_id,
                    'is_complete': False,
                    'status': 'rag_found'
                }, room=request.sid)
            else:
                # RAG sisteminde bilgi bulunamadı durumunu bildir
                emit('chat_response', {
                    'content': '',
                    'chat_id': chat_id,
                    'is_complete': False,
                    'status': 'rag_not_found'
                }, room=request.sid)
    except Exception as e:
        print(f"RAG sistemi kontrolü sırasında hata: {str(e)}")
        # Hata durumunda normal sohbet moduna devam et
    
    db = get_db()
    now = datetime.now().isoformat()
    
    if not chat_id:
        # Create new chat
        cursor = db.execute('INSERT INTO chats (user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?)',
                           (user['id'], 'Yeni Sohbet', now, now))
        chat_id = cursor.lastrowid
        db.commit()
    else:
        # Sohbetin güncellenme zamanını güncelle
        db.execute('UPDATE chats SET updated_at = ? WHERE id = ?', (now, chat_id))
        db.commit()
    
    # Save user message
    db.execute('INSERT INTO messages (chat_id, content, is_user, created_at, tokens_used) VALUES (?, ?, ?, ?, ?)',
              (chat_id, message, 1, now, 0))
    db.commit()
    
    # Check if user has tokens
    if user['tokens_remaining'] <= 0:
        emit('error', {'message': 'No tokens remaining'})
        return
    
    # RAG sonuçlarını ekleyelim - iyileştirilmiş format
    rag_context = ""
    if use_rag and 'vector_db' in locals() and hasattr(vector_db, 'search'):
        # Eğer alakalı sonuçlar varsa, bunları kullan
        if 'relevant_results' in locals() and relevant_results:
            results_to_use = relevant_results
        else:
            results_to_use = vector_db.search(message, k=2)
            
        if results_to_use and len(results_to_use) > 0:
            rag_context = "\n\nAşağıdaki bilgileri KOPYALAMADAN, kendi cümlelerinle yorumlayarak ve açıklayarak yanıt ver. Yanıtın kapsamlı, detaylı ve en az 3-4 paragraf olmalı. Bilgileri olduğu gibi kopyalamak yerine, bilgileri sentezleyerek ve kendi ifadelerinle açıkla:\n"
            for i, result in enumerate(results_to_use):
                # Metin içinde yabancı dil karakterleri olup olmadığını kontrol et
                clean_text = ''.join(c for c in result['text'] if ord(c) < 128 or c.isalpha())
                rag_context += f"Bilgi {i+1}: {clean_text}\n"
        else:
            # Bilgi bulunamadığında özel bir mesaj ekle
            rag_context = "\n\nBu konu hakkında bilgi tabanımızda yeterli bilgi bulunamadı. Genel bilgilerime dayanarak kapsamlı ve detaylı bir yanıt vereceğim. Yanıtın en az 3-4 paragraf olmalı ve konuyu derinlemesine açıklamalı.\n"
    
    # Türkçe yanıt vermesi için geliştirilmiş sistem mesajı
    system_message = """Sen deneyimli bir tıp profesörüsün. Tıp öğrencilerine yönelik uzun, kapsamlı, öğretici ve örneklerle zenginleştirilmiş açıklamalar yap. Tıbbi terimleri parantez içinde sade dille açıkla. 'kapsamlı Tanım, Mekanizma, Detaylı Kullanım Alanı, Riskler, Klinik Vaka, Ek Bilgi, Uyarı' gibi alt başlıklar, emojiler kullan. Samimi, düşündüren ama bilimsel doğruluğu koruyan bir üslupla yaz. Ansiklopedi dili kullan ancak dost gibi öğrenciyi düşündür, kıyasla ve yönlendir'"""
    
    
    # DeepSeek ve NVIDIA modelleri için özel prompt
    if model in ['deepseek/deepseek-chat-v3-0324:free', 'nvidia/llama-3.1-nemotron-ultra-253b-v1:free']:
        system_message += """

6. BİLGİ TABANI KULLANIMI:
   - Bilgi tabanından gelen bilgileri kullanarak yanıt ver
   - Bilgileri olduğu gibi kopyalamak yerine kendi cümlelerinle yorumla ve açıkla
   - Bilgi tabanındaki bilgileri kullanıcının sorusuyla ilişkilendir
   - Bilgi tabanından gelen farklı bilgileri mantıklı bir şekilde birleştir
   - Bilgi tabanında eksik bilgi varsa, kendi bilgilerinle tamamla

7. SOHBET GEÇMİŞİ YÖNETİMİ:
   - Kullanıcının tüm önceki sorularını ve senin yanıtlarını dikkate al
   - Önceki yanıtlarınla tutarlı bilgiler ver
   - Kullanıcının sohbet boyunca belirttiği tercihleri hatırla ve uygula
   - Önceki konuşmalarda verdiğin bilgileri tekrar etme, onlara atıfta bulun
   - Kullanıcının ilgi alanlarını ve endişelerini hatırla ve yanıtlarını buna göre şekillendir"""
    
    # Bilgi bulunamadığında özel prompt
    if rag_context and "bilgi tabanımızda yeterli bilgi bulunamadı" in rag_context:
        system_message += """

6. BİLGİ BULUNAMAMA DURUMU:
   - Kullanıcının sorduğu konu hakkında bilgi tabanında bilgi bulunamadı
   - Kendi bilgilerinle çok kapsamlı ve detaylı bir yanıt ver
   - Yanıtını şu şekilde yapılandır:
     a) Konuya genel bir giriş (1 paragraf)
     b) Konunun ana yönlerini maddeler halinde açıkla (en az 5 madde)
     c) Her maddeyi detaylı olarak açıkla (her madde için 1 paragraf)
     d) Varsa pratik bilgiler ve öneriler sun (1-2 paragraf)
     e) Özet bir sonuç paragrafı ekle
   - Yanıtın tamamen Türkçe olmalı, hiçbir şekilde yabancı dilde karakter veya kelime içermemeli
   - Bilgi eksikliğini telafi etmek için daha fazla detay ve örnek ver"""
    
    # Mesajları hazırla
    messages = [
        {'role': 'system', 'content': system_message}
    ]
    
    # Sohbet geçmişini ekle (son 10 mesaj)
    if chat_id:
        chat_history = db.execute(
            'SELECT content, is_user, created_at FROM messages WHERE chat_id = ? ORDER BY created_at DESC LIMIT 10', 
            (chat_id,)
        ).fetchall()
        
        # Mesajları ters çevir (en eskiden en yeniye)
        chat_history = list(reversed(chat_history))
        
        # Sohbet geçmişini mesajlara ekle
        for msg in chat_history:
            role = 'user' if msg['is_user'] == 1 else 'assistant'
            messages.append({'role': role, 'content': msg['content']})
    
    # Kullanıcı mesajını ekle
    user_content = message
    if rag_context:
        user_content += rag_context
    
    messages.append({'role': 'user', 'content': user_content})
    
    # Start timeout timer
    start_time = time.time()
    timeout = 300  # 5 minutes
    
    try:
        # Modelin hangi API'den olduğunu kontrol et
        if model.endswith('-openrouter'):
            # OpenRouter API'yi kullan
            response = query_openrouter(messages, model=model, stream=True, temperature=0.8)
        else:
            # Qroq API'yi kullan
            response = query_qroq(messages, model=model, stream=True, temperature=0.8)
            
        if response.status_code != 200:
            emit('error', {'message': f'API yanıt hatası: {response.status_code}'})
            return
            
        # AI'nin düşündüğünü bildir
        emit('chat_response', {
            'content': '',
            'chat_id': chat_id,
            'is_complete': False,
            'status': 'thinking'
        }, room=request.sid)
        
        # Initialize variables for the AI response
        full_response = ""
        tokens_used = 0
        
        for line in response.iter_lines():
            # Check timeout
            if time.time() - start_time > timeout:
                emit('error', {'message': 'Sunucu zaman aşımı. Lütfen daha sonra tekrar deneyin.'})
                break
            
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = line[6:]
                    if data == '[DONE]':
                        break
                    
                    try:
                        json_data = json.loads(data)
                        
                        # Farklı API yanıt formatlarını kontrol et
                        content = ""
                        
                        # OpenAI/Qroq formatı
                        if 'choices' in json_data and len(json_data['choices']) > 0:
                            choice = json_data['choices'][0]
                            
                            # Delta formatı (stream için)
                            if 'delta' in choice and 'content' in choice['delta']:
                                content = choice['delta']['content']
                            # Tam mesaj formatı
                            elif 'message' in choice and 'content' in choice['message']:
                                content = choice['message']['content']
                        
                        if content:
                            full_response += content
                            tokens_used += 1  # Yaklaşık token sayısı
                            emit('chat_response', {
                                'content': content,
                                'chat_id': chat_id,
                                'is_complete': False,
                                'status': 'typing'
                            }, room=request.sid)
                    except json.JSONDecodeError as e:
                        print(f"JSON ayrıştırma hatası: {str(e)} - {data[:100]}")
                        continue
        
        # Yanıt tamamlandı, veritabanına kaydet - döngü dışında yapılıyor
        if full_response:
            now = datetime.now().isoformat()
            db.execute('INSERT INTO messages (chat_id, content, is_user, created_at, tokens_used) VALUES (?, ?, ?, ?, ?)',
                      (chat_id, full_response, 0, now, tokens_used))
            
            # Update user's token count
            new_tokens = user['tokens_remaining'] - tokens_used
            db.execute('UPDATE users SET tokens_remaining = ? WHERE id = ?',
                      (new_tokens, user['id']))
            
            # Sohbet başlığını güncelle (eğer hala "Yeni Sohbet" ise)
            chat = db.execute('SELECT title FROM chats WHERE id = ?', (chat_id,)).fetchone()
            if chat and chat['title'] == 'Yeni Sohbet':
                # Kullanıcı mesajını al
                user_msg = db.execute('SELECT content FROM messages WHERE chat_id = ? AND is_user = 1 ORDER BY created_at ASC LIMIT 1', 
                                     (chat_id,)).fetchone()
                
                if user_msg:
                    # Kullanıcı mesajından başlık oluştur
                    title = generate_chat_title(user_msg['content'])
                    db.execute('UPDATE chats SET title = ? WHERE id = ?', (title, chat_id))
            
            db.commit()
            
            # Send completion signal
            emit('chat_response', {
                'content': '',
                'chat_id': chat_id,
                'is_complete': True,
                'tokens_used': tokens_used,
                'tokens_remaining': new_tokens
            }, room=request.sid)
    
    except Exception as e:
        emit('error', {'message': f'Server error: {str(e)}'})

# Sohbet başlığı oluşturma fonksiyonu
def generate_chat_title(message):
    """Kullanıcı mesajından anlamlı bir sohbet başlığı oluşturur"""
    # Mesajı kısalt (çok uzunsa)
    if len(message) > 100:
        message = message[:100]
    
    # Mesajdaki noktalama işaretlerini temizle
    import re
    message = re.sub(r'[^\w\s]', '', message)
    
    # Mesajı kelimelere ayır
    words = message.split()
    
    # Çok kısa mesajlar için
    if len(words) <= 3:
        return message
    
    # Daha uzun mesajlar için ilk 4-6 kelimeyi al
    word_count = min(6, len(words))
    title = ' '.join(words[:word_count])
    
    # Başlığın sonuna ... ekle
    if len(words) > word_count:
        title += '...'
    
    return title

# RAG sistemi blueprint'ini içe aktar
from rag_system import rag_bp, init_rag_db

# RAG blueprint'ini kaydet
app.register_blueprint(rag_bp)

# RAG fix blueprint'ini kaydet
app.register_blueprint(rag_fix_bp, url_prefix='/rag')

# Initialize database
def init_database():
    db = get_db()
    
    # Create tables if they don't exist
    db.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_admin INTEGER DEFAULT 0,
        tokens_remaining INTEGER DEFAULT 100,
        plan TEXT DEFAULT 'basic',
        created_at TEXT
    )
    ''')
    
    db.execute('''
    CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT DEFAULT 'Yeni Sohbet',
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')
    
    db.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        is_user INTEGER DEFAULT 1,
        created_at TEXT,
        tokens_used INTEGER DEFAULT 0,
        FOREIGN KEY (chat_id) REFERENCES chats (id)
    )
    ''')
    
    # RAG sorguları için tablo oluştur
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
    
    # Create admin user if not exists
    admin = db.execute('SELECT * FROM users WHERE username = ?', ('admin',)).fetchone()
    if not admin:
        hashed_password = bcrypt.generate_password_hash('admin123').decode('utf-8')
        db.execute('''
        INSERT INTO users (username, email, password, is_admin, tokens_remaining, plan, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ('admin', 'admin@example.com', hashed_password, 1, 1000, 'enterprise', datetime.now().isoformat()))
        db.commit()
    
    # RAG veritabanını başlat
    init_rag_db()

# Uygulama başlatıldığında veritabanını başlat
with app.app_context():
    init_database()

if __name__ == '__main__':
    socketio.run(app, debug=True)