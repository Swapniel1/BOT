import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import sqlite3
import datetime
import random
import config

bot = telebot.TeleBot(config.BOT_TOKEN)

# ================= DATABASE SETUP ================= #
def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    # Users Table (Added banned status)
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        first_name TEXT,
                        balance REAL DEFAULT 0.0,
                        total_referrals INTEGER DEFAULT 0,
                        invited_by INTEGER,
                        last_bonus TEXT DEFAULT '2000-01-01',
                        banned INTEGER DEFAULT 0
                    )''')
                    
    # Safely try to add the 'banned' column in case the database already exists from an older version
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        # If the column already exists, ignore the error and continue
        pass

    # Withdrawals Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        method TEXT,
                        number TEXT,
                        amount REAL,
                        status TEXT DEFAULT 'Pending'
                    )''')
                    
    # Promo Codes Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS promo_codes (
                        code TEXT PRIMARY KEY,
                        reward REAL,
                        max_uses INTEGER,
                        uses INTEGER DEFAULT 0
                    )''')
                    
    # Used Promo Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS used_promo (
                        user_id INTEGER,
                        code TEXT
                    )''')
    conn.commit()
    conn.close()

init_db()

# ================= HELPER FUNCTIONS ================= #
def check_join(user_id):
    if not config.FORCE_JOIN_CHANNEL:
        return True
    try:
        status = bot.get_chat_member(config.FORCE_JOIN_CHANNEL, user_id).status
        return status in['member', 'administrator', 'creator']
    except:
        return False

def is_banned(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT banned FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user and user[0] == 1

def get_db_connection():
    return sqlite3.connect("bot_database.db", check_same_thread=False)

# ================= KEYBOARDS ================= #
def main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("💰 My Account"), KeyboardButton("🔗 Referral Link"),
        KeyboardButton("🎁 Daily Bonus"), KeyboardButton("💸 Withdraw"),
        KeyboardButton("🎟 Promo Code"), KeyboardButton("🎲 Coin Flip"),
        KeyboardButton("🏆 Leaderboard"), KeyboardButton("📊 Bot Info")
    )
    return markup

def force_join_markup():
    markup = InlineKeyboardMarkup()
    channel_url = f"https://t.me/{config.FORCE_JOIN_CHANNEL.replace('@', '')}"
    markup.add(InlineKeyboardButton("📢 Join Our Channel", url=channel_url))
    markup.add(InlineKeyboardButton("✅ I have Joined", callback_data="check_join"))
    return markup

# ================= USER COMMANDS ================= #
@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    text = message.text.split()
    referrer_id = None

    if is_banned(user_id):
        bot.send_message(user_id, "🚫 You are banned from using this bot.")
        return

    if len(text) > 1 and text[1].isdigit():
        referrer_id = int(text[1])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cursor.fetchone()

    if not user:
        if referrer_id == user_id:
            referrer_id = None
            
        cursor.execute("INSERT INTO users (user_id, first_name, invited_by) VALUES (?, ?, ?)", (user_id, first_name, referrer_id))
        conn.commit()

        if referrer_id:
            cursor.execute("UPDATE users SET balance = balance + ?, total_referrals = total_referrals + 1 WHERE user_id = ?", (config.REF_REWARD, referrer_id))
            conn.commit()
            try:
                bot.send_message(referrer_id, f"🎉 **New Referral!**\n{first_name} joined using your link. You got {config.REF_REWARD}{config.CURRENCY}!", parse_mode="Markdown")
            except:
                pass

    conn.close()

    if not check_join(user_id):
        bot.send_message(user_id, f"👋 Hello {first_name}!\n\n⚠️ To use this bot, you must join our official channel.", reply_markup=force_join_markup())
        return

    welcome_msg = f"👋 Welcome to the Professional Earning Bot, {first_name}!\n\nEarn money by inviting friends, playing games, and claiming bonuses."
    bot.send_message(user_id, welcome_msg, reply_markup=main_menu())

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    if check_join(call.from_user.id):
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "✅ Thank you for joining! You can now use the bot.", reply_markup=main_menu())
    else:
        bot.answer_callback_query(call.id, "❌ You haven't joined the channel yet!", show_alert=True)

@bot.message_handler(commands=['transfer'])
def transfer_balance(message):
    user_id = message.from_user.id
    if is_banned(user_id): return
    
    try:
        args = message.text.split()
        target_id = int(args[1])
        amount = float(args[2])
        
        if amount <= 0:
            bot.send_message(user_id, "❌ Invalid amount.")
            return

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check sender balance
        cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        sender_balance = cursor.fetchone()[0]
        
        if sender_balance < amount:
            bot.send_message(user_id, "❌ Insufficient balance for transfer.")
            conn.close()
            return
            
        # Check if receiver exists
        cursor.execute("SELECT user_id FROM users WHERE user_id=?", (target_id,))
        receiver = cursor.fetchone()
        
        if not receiver:
            bot.send_message(user_id, "❌ User not found in database.")
            conn.close()
            return
            
        # Deduct and Add
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
        conn.commit()
        conn.close()
        
        bot.send_message(user_id, f"✅ Successfully transferred {amount}{config.CURRENCY} to `{target_id}`.", parse_mode="Markdown")
        try:
            bot.send_message(target_id, f"💸 **Balance Received!**\nYou received {amount}{config.CURRENCY} from ID: `{user_id}`", parse_mode="Markdown")
        except:
            pass
    except:
        bot.send_message(user_id, "❌ Usage: `/transfer [UserID][Amount]`", parse_mode="Markdown")

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    user_id = message.from_user.id
    text = message.text

    if is_banned(user_id):
        bot.send_message(user_id, "🚫 You are banned from using this bot.")
        return

    if not check_join(user_id):
        bot.send_message(user_id, "⚠️ Please join our channel first!", reply_markup=force_join_markup())
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    if text == "💰 My Account":
        cursor.execute("SELECT balance, total_referrals, banned FROM users WHERE user_id=?", (user_id,))
        user = cursor.fetchone()
        if user:
            status = "Active ✅" if user[2] == 0 else "Banned 🚫"
            msg = f"👤 **Account Details**\n\n🆔 ID: `{user_id}`\n💵 Balance: **{user[0]}{config.CURRENCY}**\n👥 Total Referrals: **{user[1]}**\n📈 Status: {status}"
            bot.send_message(user_id, msg, parse_mode="Markdown")

    elif text == "🔗 Referral Link":
        bot_info = bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
        msg = f"🔗 **Your Unique Referral Link**\n\n`{ref_link}`\n\n🎁 Earn {config.REF_REWARD}{config.CURRENCY} for every valid invite!"
        bot.send_message(user_id, msg, parse_mode="Markdown")

    elif text == "🎁 Daily Bonus":
        cursor.execute("SELECT last_bonus FROM users WHERE user_id=?", (user_id,))
        last_bonus_str = cursor.fetchone()[0]
        last_bonus_date = datetime.datetime.strptime(last_bonus_str, '%Y-%m-%d').date()
        today = datetime.date.today()

        if last_bonus_date < today:
            cursor.execute("UPDATE users SET balance = balance + ?, last_bonus = ? WHERE user_id = ?", (config.DAILY_BONUS, str(today), user_id))
            conn.commit()
            bot.send_message(user_id, f"🎉 Congratulations! You received your daily bonus of {config.DAILY_BONUS}{config.CURRENCY}.")
        else:
            bot.send_message(user_id, "❌ You have already claimed your bonus today. Come back tomorrow!")

    elif text == "🎟 Promo Code":
        msg = bot.send_message(user_id, "🎟 Please send the Promo Code:")
        bot.register_next_step_handler(msg, process_promo_code)

    elif text == "🎲 Coin Flip":
        msg = bot.send_message(user_id, "🎲 **Coin Flip Game**\nEnter the amount you want to bet:")
        bot.register_next_step_handler(msg, process_coin_flip_amount)

    elif text == "🏆 Leaderboard":
        cursor.execute("SELECT first_name, total_referrals FROM users ORDER BY total_referrals DESC LIMIT 5")
        top_users = cursor.fetchall()
        if not top_users:
            bot.send_message(user_id, "🏆 No users have referred anyone yet.")
        else:
            msg = "🏆 **Top 5 Referrers** 🏆\n\n"
            for i, u in enumerate(top_users):
                msg += f"{i+1}. {u[0]} - {u[1]} Invites\n"
            bot.send_message(user_id, msg, parse_mode="Markdown")

    elif text == "📊 Bot Info":
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        bot_info = bot.get_me()
        msg = f"🤖 **Bot Information**\n\n📛 Name: {bot_info.first_name}\n👤 Total Users: {total_users}\n👨‍💻 Developer: Your Admin\n🔄 Transfers Enabled"
        bot.send_message(user_id, msg, parse_mode="Markdown")

    elif text == "💸 Withdraw":
        cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        balance = cursor.fetchone()[0]

        if balance < config.MIN_WITHDRAW:
            bot.send_message(user_id, f"❌ You need at least {config.MIN_WITHDRAW}{config.CURRENCY} to withdraw.\nYour balance: {balance}{config.CURRENCY}")
        else:
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("Bkash", callback_data="wd_Bkash"), InlineKeyboardButton("Nagad", callback_data="wd_Nagad"))
            bot.send_message(user_id, "💳 Choose your payment method:", reply_markup=markup)

    conn.close()

# ================= PROMO CODE LOGIC ================= #
def process_promo_code(message):
    code = message.text.strip()
    user_id = message.from_user.id
    
    if message.text.startswith('/'): return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM used_promo WHERE user_id=? AND code=?", (user_id, code))
    if cursor.fetchone():
        bot.send_message(user_id, "❌ You have already used this promo code.")
        conn.close()
        return
        
    cursor.execute("SELECT reward, max_uses, uses FROM promo_codes WHERE code=?", (code,))
    promo = cursor.fetchone()
    
    if not promo:
        bot.send_message(user_id, "❌ Invalid Promo Code.")
    elif promo[2] >= promo[1]:
        bot.send_message(user_id, "❌ This Promo Code has reached its maximum limit.")
    else:
        reward = promo[0]
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (reward, user_id))
        cursor.execute("UPDATE promo_codes SET uses = uses + 1 WHERE code=?", (code,))
        cursor.execute("INSERT INTO used_promo (user_id, code) VALUES (?, ?)", (user_id, code))
        conn.commit()
        bot.send_message(user_id, f"✅ Successfully redeemed! You got {reward}{config.CURRENCY}.")
        
    conn.close()

# ================= COIN FLIP GAME ================= #
def process_coin_flip_amount(message):
    try:
        amount = float(message.text)
        user_id = message.from_user.id
        
        if amount <= 0:
            bot.send_message(user_id, "❌ Invalid amount.")
            return
            
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        balance = cursor.fetchone()[0]
        conn.close()
        
        if balance < amount:
            bot.send_message(user_id, "❌ Insufficient balance to play.")
            return
            
        markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(KeyboardButton("Heads"), KeyboardButton("Tails"))
        msg = bot.send_message(user_id, f"You are betting {amount}{config.CURRENCY}.\nChoose Heads or Tails:", reply_markup=markup)
        bot.register_next_step_handler(msg, play_coin_flip, amount)
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Please enter a valid number.", reply_markup=main_menu())

def play_coin_flip(message, amount):
    user_choice = message.text.lower()
    user_id = message.from_user.id
    
    if user_choice not in ["heads", "tails"]:
        bot.send_message(user_id, "❌ Invalid choice. Game cancelled.", reply_markup=main_menu())
        return
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    balance = cursor.fetchone()[0]
    
    if balance < amount:
        bot.send_message(user_id, "❌ Insufficient balance.", reply_markup=main_menu())
        conn.close()
        return

    result = random.choice(["heads", "tails"])
    
    if user_choice == result:
        win_amount = amount * 0.8 # 80% profit
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (win_amount, user_id))
        msg = f"🎉 **You Won!**\nThe coin landed on **{result.capitalize()}**.\nYou won {win_amount}{config.CURRENCY}!"
    else:
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
        msg = f"😢 **You Lost!**\nThe coin landed on **{result.capitalize()}**.\nYou lost {amount}{config.CURRENCY}."
        
    conn.commit()
    conn.close()
    bot.send_message(user_id, msg, parse_mode="Markdown", reply_markup=main_menu())

# ================= WITHDRAW SYSTEM ================= #
@bot.callback_query_handler(func=lambda call: call.data.startswith("wd_"))
def process_withdraw(call):
    method = call.data.split("_")[1]
    bot.delete_message(call.message.chat.id, call.message.message_id)
    msg = bot.send_message(call.message.chat.id, f"📱 You selected {method}. Please send your account number:")
    bot.register_next_step_handler(msg, save_withdraw_request, method)

def save_withdraw_request(message, method):
    if message.text.startswith('/'):
        bot.send_message(message.chat.id, "❌ Withdrawal cancelled. Please start over.")
        return

    number = message.text
    user_id = message.from_user.id

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    balance = cursor.fetchone()[0]

    if balance >= config.MIN_WITHDRAW:
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (balance, user_id))
        cursor.execute("INSERT INTO withdrawals (user_id, method, number, amount) VALUES (?, ?, ?, ?)", (user_id, method, number, balance))
        conn.commit()
        
        cursor.execute("SELECT last_insert_rowid()")
        wd_id = cursor.fetchone()[0]

        bot.send_message(user_id, f"✅ Withdraw request submitted successfully!\n\n💳 Amount: {balance}{config.CURRENCY}\n🏦 Method: {method}\n📱 Number: {number}\n⏳ Status: Pending Admin Approval.")
        bot.send_message(config.ADMIN_ID, f"🔔 **New Withdraw Request!**\n\n🆔 WD ID: `{wd_id}`\n👤 User ID: `{user_id}`\n💰 Amount: {balance}{config.CURRENCY}\n🏦 Method: {method}\n📱 Number: `{number}`\n\nApprove: /approve {wd_id}\nReject: /reject {wd_id}", parse_mode="Markdown")
    else:
        bot.send_message(user_id, "❌ Not enough balance.")
    conn.close()

# ================= ADMIN PANEL ================= #
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != config.ADMIN_ID: return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM withdrawals WHERE status='Pending'")
    pending_wd = cursor.fetchone()[0]
    conn.close()

    msg = f"""👨‍💻 **Admin Dashboard**

👥 Total Users: {total_users}
⏳ Pending Withdrawals: {pending_wd}

**User Control:**
`/addbalance [id][amount]` - Add money manually
`/ban [id]` - Ban user
`/unban [id]` - Unban user

**Withdrawals:**
`/pending` - View pending withdrawals
`/approve [WD_ID]` - Approve payment
`/reject [WD_ID]` - Reject & Refund payment

**Tools:**
`/createpromo [code][reward] [max_users]` - Create Promo
`/broadcast` - Send message to all users"""

    bot.send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(commands=['ban'])
def ban_user(message):
    if message.from_user.id != config.ADMIN_ID: return
    try:
        target_id = int(message.text.split()[1])
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET banned = 1 WHERE user_id = ?", (target_id,))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, f"✅ User `{target_id}` banned successfully.", parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ Usage: `/ban [user_id]`", parse_mode="Markdown")

@bot.message_handler(commands=['unban'])
def unban_user(message):
    if message.from_user.id != config.ADMIN_ID: return
    try:
        target_id = int(message.text.split()[1])
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET banned = 0 WHERE user_id = ?", (target_id,))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, f"✅ User `{target_id}` unbanned successfully.", parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ Usage: `/unban [user_id]`", parse_mode="Markdown")

@bot.message_handler(commands=['createpromo'])
def create_promo(message):
    if message.from_user.id != config.ADMIN_ID: return
    try:
        args = message.text.split()
        code = args[1]
        reward = float(args[2])
        max_uses = int(args[3])
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO promo_codes (code, reward, max_uses, uses) VALUES (?, ?, ?, 0)", (code, reward, max_uses))
        conn.commit()
        conn.close()
        bot.send_message(message.chat.id, f"✅ **Promo Code Created!**\n\n🎟 Code: `{code}`\n💰 Reward: {reward}{config.CURRENCY}\n👥 Max Users: {max_uses}", parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ Usage: `/createpromo [code] [amount] [max_uses]`", parse_mode="Markdown")

@bot.message_handler(commands=['broadcast'])
def broadcast(message):
    if message.from_user.id != config.ADMIN_ID: return
    msg = bot.send_message(message.chat.id, "📝 Send the message you want to broadcast:")
    bot.register_next_step_handler(msg, send_broadcast)

def send_broadcast(message):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()

    success = 0
    for user in users:
        try:
            bot.send_message(user[0], f"📢 **Announcement**\n\n{message.text}", parse_mode="Markdown")
            success += 1
        except:
            pass
    bot.send_message(config.ADMIN_ID, f"✅ Broadcast sent to {success} users.")

@bot.message_handler(commands=['addbalance'])
def add_balance(message):
    if message.from_user.id != config.ADMIN_ID: return
    try:
        args = message.text.split()
        target_id = int(args[1])
        amount = float(args[2])
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
        conn.commit()
        conn.close()
        
        bot.send_message(message.chat.id, f"✅ Added {amount}{config.CURRENCY} to user `{target_id}`.", parse_mode="Markdown")
        bot.send_message(target_id, f"💰 **Admin added {amount}{config.CURRENCY} to your account!**", parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, "❌ Invalid format. Use: `/addbalance [user_id] [amount]`", parse_mode="Markdown")

@bot.message_handler(commands=['pending'])
def pending_withdrawals(message):
    if message.from_user.id != config.ADMIN_ID: return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, method, number, amount FROM withdrawals WHERE status='Pending'")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        bot.send_message(message.chat.id, "✅ No pending withdrawals.")
        return
        
    for row in rows:
        msg = f"🆔 WD ID: `{row[0]}`\n👤 User ID: `{row[1]}`\n💳 Method: {row[2]}\n📱 Number: `{row[3]}`\n💰 Amount: {row[4]}{config.CURRENCY}\n\nApprove: /approve {row[0]}\nReject: /reject {row[0]}"
        bot.send_message(message.chat.id, msg, parse_mode="Markdown")

@bot.message_handler(commands=['approve'])
def approve_wd(message):
    if message.from_user.id != config.ADMIN_ID: return
    try:
        wd_id = int(message.text.split()[1])
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount FROM withdrawals WHERE id=? AND status='Pending'", (wd_id,))
        wd = cursor.fetchone()
        
        if wd:
            cursor.execute("UPDATE withdrawals SET status='Approved' WHERE id=?", (wd_id,))
            conn.commit()
            bot.send_message(message.chat.id, f"✅ Withdrawal `{wd_id}` Approved successfully.", parse_mode="Markdown")
            bot.send_message(wd[0], f"✅ **Payment Approved!**\nYour withdrawal request for {wd[1]}{config.CURRENCY} has been successfully paid.", parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "❌ Invalid ID or already processed.")
        conn.close()
    except:
        bot.send_message(message.chat.id, "❌ Usage: `/approve [ID]`", parse_mode="Markdown")

@bot.message_handler(commands=['reject'])
def reject_wd(message):
    if message.from_user.id != config.ADMIN_ID: return
    try:
        wd_id = int(message.text.split()[1])
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, amount FROM withdrawals WHERE id=? AND status='Pending'", (wd_id,))
        wd = cursor.fetchone()
        
        if wd:
            cursor.execute("UPDATE withdrawals SET status='Rejected' WHERE id=?", (wd_id,))
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (wd[1], wd[0])) 
            conn.commit()
            bot.send_message(message.chat.id, f"❌ Withdrawal `{wd_id}` Rejected & Amount Refunded.", parse_mode="Markdown")
            bot.send_message(wd[0], f"❌ **Payment Rejected!**\nYour withdrawal request for {wd[1]}{config.CURRENCY} was rejected and the balance has been refunded to your account.", parse_mode="Markdown")
        else:
            bot.send_message(message.chat.id, "❌ Invalid ID or already processed.")
        conn.close()
    except:
        bot.send_message(message.chat.id, "❌ Usage: `/reject [ID]`", parse_mode="Markdown")

# Bot Polling
print("Bot is running with new features...")
bot.infinity_polling()