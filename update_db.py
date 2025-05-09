import sqlite3
import os

# Veritabanı dosya yolu
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat_app.db')

def update_database_schema():
    print(f"Veritabanı güncelleniyor: {DB_PATH}")
    
    # Veritabanı bağlantısı oluştur
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Mevcut 'chats' tablosunda 'updated_at' sütununun varlığını kontrol et
        cursor.execute("PRAGMA table_info(chats)")
        columns = cursor.fetchall()
        column_names = [column[1] for column in columns]
        
        # 'updated_at' sütunu yoksa ekle
        if 'updated_at' not in column_names:
            print("'updated_at' sütunu ekleniyor...")
            cursor.execute("ALTER TABLE chats ADD COLUMN updated_at TEXT;")
            
            # Mevcut kayıtlar için 'updated_at' değerini 'created_at' ile aynı yap
            cursor.execute("UPDATE chats SET updated_at = created_at WHERE updated_at IS NULL;")
            print("Mevcut kayıtlar güncellendi.")
        else:
            print("'updated_at' sütunu zaten mevcut.")
        
        # Değişiklikleri kaydet
        conn.commit()
        print("Veritabanı şeması başarıyla güncellendi.")
        
    except Exception as e:
        print(f"Hata oluştu: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    update_database_schema()