import sqlite3
import random
from datetime import datetime, timedelta
from faker import Faker
from hashlib import sha256
import getpass

# Constants
DB = "expense_tracker.db"
CATEGORIES = ["Food", "Transport", "Utilities", "Entertainment", "Miscellaneous"]
MONTHS = 18
ENTRIES_PER_MONTH = 1398
fake = Faker()

def get_user_id(username, password):
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    hashed = sha256(password.encode()).hexdigest()
    cursor.execute("SELECT id FROM users WHERE username = ? AND password_hash = ?", (username, hashed))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def insert_synthetic_expenses(user_id):
    conn = sqlite3.connect(DB)
    cursor = conn.cursor()
    base_date = datetime.now() - timedelta(days=30 * MONTHS)

    for month in range(MONTHS):
        for _ in range(ENTRIES_PER_MONTH):
            amount = round(random.uniform(10, 500), 2)
            category = random.choice(CATEGORIES)
            date = base_date + timedelta(days=random.randint(0, 29))
            is_necessary = random.choice([0, 1])
            description = fake.sentence(nb_words=6)
            cursor.execute("""
                INSERT INTO expenses (user_id, amount, category, date, is_necessary, description)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, amount, category, date.strftime("%Y-%m-%d"), is_necessary, description))
        base_date += timedelta(days=30)

    conn.commit()
    conn.close()
    print(f"✅ Inserted {MONTHS * ENTRIES_PER_MONTH} entries for user_id {user_id}")

if __name__ == "__main__":
    print("🔐 Login to inject synthetic data")
    username = input("Username: ")
    password = getpass.getpass("Password: ")

    user_id = get_user_id(username, password)
    if user_id:
        insert_synthetic_expenses(user_id)
    else:
        print("❌ Invalid username or password.")
