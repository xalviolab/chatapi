from flask import Flask, request, jsonify, render_template, session, redirect, url_for, g
from flask_socketio import SocketIO, emit
from flask_bcrypt import Bcrypt
import os
import requests
import json
import sqlite3
from datetime import datetime
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
# Add this to your existing socket.io events in app.py


app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key')
app.config['DATABASE'] = os.path.join(os.path.dirname(__file__), 'chat_app.db')

# Initialize extensions
bcrypt = Bcrypt(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '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')

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
        return render_template('chat.html', user=user)
    return render_template('login.html')

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
    # Pass the current user information to the template
    return render_template('admin.html', users=users, user=get_current_user())

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

@socketio.on('chat_message')
def handle_chat_message(data):
    if not is_logged_in():
        return
    
    user = get_current_user()
    message = data.get('message')
    model = data.get('model', 'microsoft/phi-4-reasoning-plus:free')
    chat_id = data.get('chat_id')
    
    db = get_db()
    if not chat_id:
        # Create new chat
        cursor = db.execute('INSERT INTO chats (user_id, created_at) VALUES (?, ?)',
                           (user['id'], datetime.now().isoformat()))
        chat_id = cursor.lastrowid
        db.commit()
        
        # Save user message
        db.execute('INSERT INTO messages (chat_id, content, is_user, created_at, tokens_used) VALUES (?, ?, ?, ?, ?)',
                  (chat_id, message, 1, datetime.now().isoformat(), 0))
        db.commit()
    
    # Check if user has tokens
    if user['tokens_remaining'] <= 0:
        emit('error', {'message': 'No tokens remaining'})
        return
    
    # Call OpenRouter API with streaming
    headers = {
        'Authorization': f'Bearer {OPENROUTER_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'model': model,
        'messages': [{'role': 'user', 'content': message}],
        'stream': True
    }
    
    # Start timeout timer
    start_time = time.time()
    timeout = 300  # 5 minutes
    
    try:
        with requests.post('https://openrouter.ai/api/v1/chat/completions', 
                          headers=headers, 
                          json=payload, 
                          stream=True) as response:
            
            if response.status_code != 200:
                emit('error', {'message': 'Error from OpenRouter API'})
                return
            
            # Initialize variables for the AI response
            full_response = ""
            tokens_used = 0
            
            for line in response.iter_lines():
                # Check timeout
                if time.time() - start_time > timeout:
                    emit('error', {'message': 'Server timeout. Please try again later.'})
                    break
                
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            break
                        
                        try:
                            json_data = json.loads(data)
                            delta = json_data.get('choices', [{}])[0].get('delta', {})
                            content = delta.get('content', '')
                            
                            if content:
                                full_response += content
                                tokens_used += 1  # Approximate token count
                                emit('chat_response', {
                                    'content': content,
                                    'chat_id': chat_id,
                                    'is_complete': False
                                })
                        except json.JSONDecodeError:
                            continue
            
            # Save AI message to database
            if full_response:
                db.execute('INSERT INTO messages (chat_id, content, is_user, created_at, tokens_used) VALUES (?, ?, ?, ?, ?)',
                          (chat_id, full_response, 0, datetime.now().isoformat(), tokens_used))
                
                # Update user's token count
                new_tokens = user['tokens_remaining'] - tokens_used
                db.execute('UPDATE users SET tokens_remaining = ? WHERE id = ?',
                          (new_tokens, user['id']))
                db.commit()
                
                # Send completion signal
                emit('chat_response', {
                    'content': '',
                    'chat_id': chat_id,
                    'is_complete': True,
                    'tokens_used': tokens_used,
                    'tokens_remaining': new_tokens
                })
    
    except Exception as e:
        emit('error', {'message': f'Server error: {str(e)}'})

# Initialize database
@app.before_first_request
def before_first_request():
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
        created_at TEXT,
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
    
    # Create admin user if not exists
    admin = db.execute('SELECT * FROM users WHERE username = ?', ('admin',)).fetchone()
    if not admin:
        hashed_password = bcrypt.generate_password_hash('admin123').decode('utf-8')
        db.execute('''
        INSERT INTO users (username, email, password, is_admin, tokens_remaining, plan, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', ('admin', 'admin@example.com', hashed_password, 1, 1000, 'enterprise', datetime.now().isoformat()))
        db.commit()

if __name__ == '__main__':
    socketio.run(app, debug=True)