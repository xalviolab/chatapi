import sqlite3
import os
from datetime import datetime

# Veritabanı yolu
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat_app.db')

def fix_database_schema():
    print(f"Veritabanı şeması düzeltiliyor: {DB_PATH}")
    
    # Veritabanı bağlantısı oluştur
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Mevcut 'chats' tablosunda 'title' sütununun varlığını kontrol et
        cursor.execute("PRAGMA table_info(chats)")
        columns = cursor.fetchall()
        column_names = [column[1] for column in columns]
        
        # 'title' sütunu yoksa ekle
        if 'title' not in column_names:
            print("'title' sütunu ekleniyor...")
            cursor.execute("ALTER TABLE chats ADD COLUMN title TEXT DEFAULT 'Yeni Sohbet';")
            print("'title' sütunu eklendi.")
        else:
            print("'title' sütunu zaten mevcut.")
        
        # Değişiklikleri kaydet
        conn.commit()
        print("Veritabanı şeması başarıyla düzeltildi.")
        
    except Exception as e:
        print(f"Hata oluştu: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    fix_database_schema()