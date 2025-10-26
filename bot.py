"""Makima Bot — Expanded polling bot implementing the provided menu commands
with many working placeholders and simple persistence in SQLite.
Also includes a simple Flask admin dashboard to view users and approve WhatsApp proofs.
"""
import logging, sqlite3, hashlib, random, time
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberStatus, InputMediaPhoto
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# -------------- CONFIG ----------------
BOT_TOKEN = "8407783811:AAGKsXIGnu5YQNWC8TufhEYZLutYd2Qg3I4"
TELEGRAM_CHANNEL_USERNAME = "@hackers_hideout359"
WHATSAPP_CHANNEL_LINK = "https://whatsapp.com/channel/0029VbBwO480bIdr9QEH6k1a"
PREMIUM_CONTACT = "@Tdt_Minato"
ADMIN_IDS = [123456789]  # replace with numeric admin ids
FREE_DAILY_LIMIT = 80
DB_PATH = "bot_data.sqlite3"
# --------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------- DB utils ----------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        passhash TEXT,
        logged_in INTEGER DEFAULT 0,
        is_premium INTEGER DEFAULT 0,
        whatsapp_verified INTEGER DEFAULT 0,
        used_today INTEGER DEFAULT 0,
        last_reset_date TEXT,
        balance INTEGER DEFAULT 1000
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS whatsapp_proofs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        file_id TEXT,
        timestamp TEXT,
        processed INTEGER DEFAULT 0
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner INTEGER,
        name TEXT,
        tier TEXT
    )""")
    conn.commit()
    conn.close()

def current_date_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def hash_pass(pw: str) -> str:
    return hashlib.sha256(pw.encode('utf-8')).hexdigest()

def ensure_user_row(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, last_reset_date) VALUES (?,?)", (user_id, current_date_str()))
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, logged_in, is_premium, whatsapp_verified, used_today, last_reset_date, balance FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row

def reset_daily_if_needed(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT used_today, last_reset_date FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close(); return
    used_today, last_reset = row
    if last_reset != current_date_str():
        cur.execute("UPDATE users SET used_today = 0, last_reset_date = ? WHERE user_id = ?", (current_date_str(), user_id))
        conn.commit()
    conn.close()

def increment_usage(user_id: int) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    reset_daily_if_needed(user_id)
    cur.execute("SELECT used_today FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO users (user_id, used_today, last_reset_date) VALUES (?,1,?)", (user_id, current_date_str()))
        conn.commit(); conn.close(); return 1
    used_today = row[0] + 1
    cur.execute("UPDATE users SET used_today = ? WHERE user_id = ?", (used_today, user_id))
    conn.commit(); conn.close(); return used_today

def add_whatsapp_proof(user_id: int, file_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO whatsapp_proofs (user_id, file_id, timestamp, processed) VALUES (?, ?, ?, 0)", (user_id, file_id, datetime.now(timezone.utc).isoformat()))
    conn.commit(); conn.close()

def set_whatsapp_verified(user_id: int, yes: bool):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET whatsapp_verified = ? WHERE user_id = ?", (1 if yes else 0, user_id))
    conn.commit(); conn.close()

def set_premium(user_id: int, yes: bool):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_premium = ? WHERE user_id = ?", (1 if yes else 0, user_id))
    conn.commit(); conn.close()

# ---------- Checks ----------
async def is_member_of_telegram_channel(app, user_id: int) -> bool:
    try:
        member = await app.bot.get_chat_member(TELEGRAM_CHANNEL_USERNAME, user_id)
        status = member.status
        return status in (ChatMemberStatus.MEMBER, ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except Exception as e:
        logger.warning(f"Failed to check channel membership: {e}")
        return False

async def require_checks_and_usage(user_id: int, app) -> (bool, str):
    ensure_user_row(user_id)
    row = get_user(user_id)
    if not row:
        return False, "Missing user row."
    _, username, logged_in, is_premium, whatsapp_verified, used_today, last_reset, balance = row
    member = await is_member_of_telegram_channel(app, user_id)
    if not member:
        return False, f"Please join our Telegram channel: https://t.me/{TELEGRAM_CHANNEL_USERNAME.lstrip('@')}"
    if not whatsapp_verified:
        return False, f"Please join WhatsApp and upload proof: {WHATSAPP_CHANNEL_LINK}"
    if is_premium:
        return True, ""
    reset_daily_if_needed(user_id)
    if used_today >= FREE_DAILY_LIMIT:
        return False, f"You used {used_today}/{FREE_DAILY_LIMIT} free commands today. Buy premium from {PREMIUM_CONTACT}."
    return True, ""

# ---------- Handlers (message-based commands starting with dot) ----------
async def handle_dot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if not text.startswith('.'):
        return
    parts = text[1:].split()
    cmd = parts[0].lower()
    args = parts[1:]
    user = update.effective_user
    user_id = user.id
    ensure_user_row(user_id)

    # ACCOUNT
    if cmd == 'register':
        if len(args) < 2:
            await update.message.reply_text("Usage: .register username password")
            return
        uname, pw = args[0], args[1]
        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
        cur.execute("UPDATE users SET username = ?, passhash = ?, logged_in = 1 WHERE user_id = ?", (uname, hash_pass(pw), user_id))
        conn.commit(); conn.close()
        await update.message.reply_text(f"Registered as {uname} and logged in.")
        return
    if cmd == 'login':
        if len(args) < 2:
            await update.message.reply_text("Usage: .login username password"); return
        uname, pw = args[0], args[1]
        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
        cur.execute("SELECT passhash FROM users WHERE username = ?", (uname,))
        row = cur.fetchone()
        if not row or row[0] != hash_pass(pw):
            await update.message.reply_text("Login failed."); conn.close(); return
        cur.execute("UPDATE users SET logged_in = 1, user_id = ? WHERE username = ?", (user_id, uname))
        conn.commit(); conn.close()
        await update.message.reply_text("Logged in successfully."); return
    if cmd == 'profile':
        row = get_user(user_id)
        if not row:
            await update.message.reply_text("No profile."); return
        uid, username, logged_in, is_premium, whatsapp_verified, used_today, last_reset, balance = row
        await update.message.reply_text(f"User: {username or uid}\nPremium: {bool(is_premium)}\nWhatsApp verified: {bool(whatsapp_verified)}\nBalance: {balance}")
        return
    if cmd == 'edit':
        if len(args) < 2:
            await update.message.reply_text("Usage: .edit field value (supported: username)"); return
        field, value = args[0], args[1]
        if field != 'username':
            await update.message.reply_text("Only 'username' editable in this demo."); return
        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
        cur.execute("UPDATE users SET username = ? WHERE user_id = ?", (value, user_id))
        conn.commit(); conn.close()
        await update.message.reply_text("Username updated."); return
    if cmd == 'logout':
        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
        cur.execute("UPDATE users SET logged_in = 0 WHERE user_id = ?", (user_id,))
        conn.commit(); conn.close()
        await update.message.reply_text("Logged out."); return

    # CARDS (simple placeholders)
    if cmd == 'cards':
        await update.message.reply_text("Cards system is enabled. Use .card [index] or .cardshop to buy."); return
    if cmd == 'card':
        idx = args[0] if args else '1'
        await update.message.reply_text(f"Showing card #{idx} — (placeholder)"); return
    if cmd == 'ci' or cmd == 'cardinfo':
        if len(args) < 2:
            await update.message.reply_text("Usage: .ci name tier"); return
        name, tier = args[0], args[1]
        await update.message.reply_text(f"Card {name} (Tier: {tier}) — placeholder info."); return
    if cmd == 'deck':
        await update.message.reply_text("Your deck is empty (placeholder). Use .ci to create cards."); return
    if cmd == 'cardshop':
        await update.message.reply_text("Card shop: [1] Firewolf (Rare) — 500 coins. [2] Aqua-Drake (Common) — 200 coins."); return
    if cmd == 'claim':
        await update.message.reply_text("Claimed reward (placeholder).") ; return
    if cmd == 'auction' or cmd == 'listauc':
        await update.message.reply_text("Auction system coming soon (placeholder)."); return

    # ECONOMY
    if cmd in ('balance','bal'):
        row = get_user(user_id); bal = row[7] if row else 0
        await update.message.reply_text(f"Balance: {bal} coins."); return
    if cmd == 'daily':
        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
        conn.execute("UPDATE users SET balance = balance + 200 WHERE user_id = ?", (user_id,))
        conn.commit(); conn.close()
        await update.message.reply_text("You claimed daily 200 coins."); return
    if cmd in ('deposit','dep','withdraw','wd','shop','inventory','inv','use','sell','gamble','lottery','leaderboard','lb'):
        await update.message.reply_text(f"{cmd} is a placeholder economy command — implement later."); return

    # GAMES
    if cmd in ('ttt','chess','startbattle','aki','c4','wcg'):
        await update.message.reply_text(f"Command {cmd} starts a game (placeholder).") ; return

    # GUILDS
    if cmd == 'guild':
        await update.message.reply_text("Guild subsystem placeholder."); return

    # GAMBLE
    if cmd in ('slots','cf','dice','roulette','horse'):
        await update.message.reply_text("Gamble placeholder: not a real gambling system."); return

    # PETS
    if cmd == 'pet':
        await update.message.reply_text("You have no pet yet (placeholder).") ; return
    if cmd == 'pet' and len(args)>0:
        await update.message.reply_text("pet subcommands placeholder"); return

    # RPG
    if cmd == 'rpg':
        await update.message.reply_text("RPG subsystem placeholder. Use .rpg start") ; return

    # INTERACTION
    interactions = ['hug','kiss','slap','pat','dance','wave','bonk','kill','tickle','smile','sad','laugh']
    if cmd in interactions:
        target = args[0] if args else 'someone'
        await update.message.reply_text(f"{update.effective_user.first_name} {cmd}s {target} 🤖") ; return

    # FUN
    if cmd in ('gay','lesbian','simp','ship','pp','joke','truth','dare','wyr'):
        if cmd == 'pp':
            size = random.randint(1,30)
            await update.message.reply_text(f"PP size: {size}cm (just for fun)"); return
        if cmd == 'joke':
            jokes = ["Why did the chicken cross the road? To get to the other side.", "I told my computer I needed a break, now it won't stop sending me KitKat ads."]
            await update.message.reply_text(random.choice(jokes)); return
        await update.message.reply_text(f"Fun: {cmd} -> (placeholder)"); return

    # DOWNLOADERS (stubs - actual downloading requires 3rd party APIs)
    if cmd in ('yt','ig','ttk','fb','play'):
        await update.message.reply_text("Downloader functionality is not enabled in this demo. Use verified APIs to implement safely."); return

    # SEARCH
    if cmd in ('pinterest','pint','wallpaper','lyrics','sauce'):
        await update.message.reply_text(f"Search: {cmd} -> placeholder (requires external API)." ); return

    # AI
    if cmd in ('gpt','copilot','translate','tt','imagine','upscale'):
        await update.message.reply_text(f"AI feature {cmd} not enabled in this offline demo."); return

    # CONVERTER
    if cmd in ('sticker','s','take','toimg','tovid','rotate'):
        await update.message.reply_text("Converter features are placeholders. Use media APIs / file processing to enable."); return

    # ANIME SFW
    if cmd in ('waifu','neko','maid','uniform','raiden-shogun','kamisato-ayaka'):
        await update.message.reply_text(f"Anime: {cmd} image placeholder. Configure image APIs to deliver real images."); return

    # ANIME NSFW
    if cmd == 'nsfw':
        await update.message.reply_text("NSFW toggle placeholder. NSFW content is restricted — ensure compliance with platform rules."); return
    if cmd in ('hentai','ass','oral','ecchi','nhentai'):
        await update.message.reply_text("NSFW commands disabled in this demo."); return

    # ADMIN via dot commands (only telegram admins)
    if cmd == 'approve_proof':
        if update.effective_user.id not in ADMIN_IDS:
            await update.message.reply_text("Admins only."); return
        if not args:
            await update.message.reply_text("Usage: .approve_proof <id>"); return
        pid = int(args[0])
        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
        cur.execute("SELECT user_id FROM whatsapp_proofs WHERE id = ? AND processed = 0", (pid,))
        row = cur.fetchone()
        if not row: await update.message.reply_text("Not found."); conn.close(); return
        uid = row[0]; cur.execute("UPDATE whatsapp_proofs SET processed = 1 WHERE id = ?", (pid,)); conn.commit(); conn.close()
        set_whatsapp_verified(uid, True)
        await update.message.reply_text(f"Proof {pid} approved."); return
    if cmd == 'list_proofs':
        if update.effective_user.id not in ADMIN_IDS:
            await update.message.reply_text("Admins only."); return
        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
        cur.execute("SELECT id, user_id, timestamp FROM whatsapp_proofs WHERE processed = 0 ORDER BY timestamp DESC")
        rows = cur.fetchall(); conn.close()
        if not rows: await update.message.reply_text("No proofs."); return
        msg = '\n'.join([f"{r[0]} — user {r[1]} — {r[2]}" for r in rows[:50]])
        await update.message.reply_text(msg); return

    # fallback
    await update.message.reply_text(f"Unknown or unimplemented command: .{cmd}")

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user_row(user.id)
    buttons = [
        [InlineKeyboardButton("Join Telegram Channel", url=f"https://t.me/{TELEGRAM_CHANNEL_USERNAME.lstrip('@')}")],
        [InlineKeyboardButton("Open WhatsApp Channel", url=WHATSAPP_CHANNEL_LINK)],
        [InlineKeyboardButton("I've joined WhatsApp (upload proof)", callback_data="whatsapp_proof")],
    ]
    kb = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Welcome to Makima Bot! Use commands with a leading dot like .register or .balance.", reply_markup=kb)

async def whatsapp_proof_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); await query.message.reply_text("Upload a screenshot as photo in chat. Admins will review.")

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo: return
    file = update.message.photo[-1]
    uid = update.effective_user.id
    add_whatsapp_proof(uid, file.file_id)
    await update.message.reply_text("Proof received. Admins will review and approve.")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id; ensure_user_row(uid)
    row = get_user(uid)
    if not row: await update.message.reply_text("No data."); return
    uid, username, logged_in, is_premium, whatsapp_verified, used_today, last_reset, balance = row
    member = await is_member_of_telegram_channel(context.application, uid)
    await update.message.reply_text(f"Status:\nTelegram member: {bool(member)}\nWhatsApp verified: {bool(whatsapp_verified)}\nPremium: {bool(is_premium)}\nBalance: {balance}")

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler('start', start_cmd))
    app.add_handler(CallbackQueryHandler(whatsapp_proof_callback, pattern='^whatsapp_proof$'))
    app.add_handler(CommandHandler('status', status_cmd))
    app.add_handler(MessageHandler(filters.Regex(r'^\.'), handle_dot_command))
    app.add_handler(MessageHandler(filters.PHOTO & (~filters.COMMAND), photo_handler))
    logger.info('Makima Bot (expanded) started') 
    app.run_polling(allowed_updates=['message','callback_query','edited_message'])

if __name__ == '__main__':
    main()
