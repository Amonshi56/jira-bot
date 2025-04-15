import aiosqlite
import datetime

DB_PATH = ""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                chat_id TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                task_key TEXT,
                summary TEXT,
                state TEXT,
                created_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS block (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE,
                reason TEXT DEFAULT '',
                username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS auth_attempts (
                chat_id INTEGER PRIMARY KEY,
                attempts INTEGER DEFAULT 0,
                username TEXT,
                last_try TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await db.execute("PRAGMA journal_mode = WAL;")
        await db.execute("PRAGMA cache_size = 10000;")
        await db.commit()

async def in_block(chat_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM block WHERE chat_id = ?", (chat_id,)) as cursor:
            row = await cursor.fetchone()
        return row is not None

async def get_blocked_user_by_username(username: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM block WHERE username = ?", (username,)) as cursor:
            row = await cursor.fetchone()
        return row is not None

async def in_active(chat_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM users WHERE chat_id = ?", (chat_id,)) as cursor:
            row = await cursor.fetchone()
        return row is not None


async def block_user(chat_id: int, block_reason: str, username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO block (chat_id, reason, username) VALUES (?, ?, ?)",
            (chat_id, block_reason, username)
        )
        await db.commit()

async def remove_from_blocked(username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM block WHERE username = (?)",
            (username,)
        )
        await db.commit()

async def clear_auth_attempts(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM auth_attempts WHERE chat_id = ?", (chat_id,))
        await db.commit()

async def clear_auth_attempts_username(username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM auth_attempts WHERE username = ?", (username,))
        await db.commit()

async def get_auth_attempts(chat_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT attempts FROM auth_attempts WHERE chat_id = ?", (chat_id,)) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0


async def increment_auth_attempts(chat_id: int, username: str):
    if await get_auth_attempts(chat_id) == 0:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO auth_attempts (chat_id, attempts, username) VALUES (?, 1, ?)", (chat_id, username))
            await db.commit()
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE auth_attempts SET attempts = attempts + 1, last_try = CURRENT_TIMESTAMP WHERE chat_id = ?",
                (chat_id,)
            )
            await db.commit()

async def add_user(message):
    user_id = message.from_user.id
    username = message.from_user.username
    chat_id = message.chat.id
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users (id, username, chat_id) VALUES (?, ?, ?)
        """, (user_id, username, chat_id))
        await db.commit()

async def save_task(user_id: int, task_key: str, summary: str, state: str):
    created_at = datetime.datetime.now().strftime("%d %B %Y, %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO tasks (user_id, task_key, summary, state, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, task_key, summary, state, created_at))
        await db.commit()

async def get_tasks_for_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT task_key, summary, state, created_at
            FROM tasks
            WHERE user_id = ?
        """, (user_id,))
        rows = await cursor.fetchall()
        return rows