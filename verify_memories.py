from services.storage import storage
import sqlite3

def verify_db():
    print(f"DB Path: {storage.db_path}")
    conn = storage.get_connection()
    cursor = conn.cursor()
    
    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    print("Tables:", [t[0] for t in tables])
    
    if 'memories' in [t[0] for t in tables]:
        print("PASS: 'memories' table exists.")
    else:
        print("FAIL: 'memories' table missing.")
        
    conn.close()

if __name__ == "__main__":
    verify_db()
