import asyncio
import os
import sys
import json
import time
import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

TOKEN = os.getenv("TG_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
DB_PATH = "/data/guard.db"
UDP_IP = "0.0.0.0"
UDP_PORT = 9999
HTTP_PORT = 8080

if not TOKEN or not ADMIN_ID:
    sys.exit("Fatal: TG_TOKEN or ADMIN_ID missing.")

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    sys.exit("Fatal: ADMIN_ID must be an integer.")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS approved_ips (
                ip TEXT PRIMARY KEY,
                expiry INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT,
                user TEXT,
                status TEXT,
                timestamp INTEGER
            )
        """)
        await db.commit()

async def log_attempt(ip, user, status):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO history (ip, user, status, timestamp) VALUES (?, ?, ?, ?)",
            (ip, user, status, int(time.time()))
        )
        await db.commit()

async def is_ip_allowed(ip: str) -> bool:
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT expiry FROM approved_ips WHERE ip = ?", (ip,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] > now:
                return True
            if row: 
                await db.execute("DELETE FROM approved_ips WHERE ip = ?", (ip,))
                await db.commit()
    return False

async def approve_ip(ip: str, duration_hours: int = 1):
    expiry = int(time.time()) + (duration_hours * 3600)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("REPLACE INTO approved_ips (ip, expiry) VALUES (?, ?)", (ip, expiry))
        await db.commit()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Active Sessions", callback_data="menu_sessions")],
        [InlineKeyboardButton(text="📜 Access History", callback_data="menu_history")],
        [InlineKeyboardButton(text="🔐 Whitelist IPs", callback_data="menu_whitelist")]
    ])
    
    await message.answer(
        "🛡 <b>Server Guard Panel</b>\n\nSelect an action:",
        reply_markup=kb
    )

@dp.callback_query(F.data == "menu_history")
async def show_history(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT ip, user, status, timestamp FROM history ORDER BY id DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
            
    if not rows:
        await call.message.edit_text("📜 History is empty.", reply_markup=None)
        return

    msg = "📜 <b>Last 10 Login Attempts:</b>\n\n"
    for r in rows:
        ts = time.strftime('%H:%M %d/%m', time.localtime(r[3]))
        icon = "✅" if r[2] == "ALLOWED" else "⛔"
        msg += f"{icon} <code>{r[0]}</code> ({r[1]}) - {ts}\n"
    
    await call.message.edit_text(msg, reply_markup=None)

@dp.callback_query(F.data == "menu_whitelist")
async def show_whitelist(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT ip, expiry FROM approved_ips WHERE expiry > ?", (now,)) as cursor:
            rows = await cursor.fetchall()
            
    msg = "🔐 <b>Active Whitelisted IPs:</b>\n\n"
    if not rows:
        msg += "No active IPs."
    
    for r in rows:
        left = int((r[1] - now) / 60)
        msg += f"🌐 <code>{r[0]}</code> ({left} min left)\n"
        
    await call.message.edit_text(msg, reply_markup=None)

async def handle_check_access(request):
    ip = request.query.get('ip')
    user = request.query.get('user')
    
    if not ip or not user:
        return web.json_response({"status": "error"}, status=400)

    allowed = await is_ip_allowed(ip)
    
    status_log = "ALLOWED" if allowed else "BLOCKED"
    await log_attempt(ip, user, status_log)
    
    if allowed:
        return web.json_response({"status": "allowed"})
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Allow {ip} (1h)", callback_data=f"allow_{ip}")]
    ])
    
    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🚨 <b>UNAUTHORIZED ACCESS BLOCKED</b>\n\n"
                 f"👤 <b>User:</b> {user}\n"
                 f"🌐 <b>IP:</b> <code>{ip}</code>\n"
                 f"🕒 <b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                 f"Connection closed. Tap below to authorize.",
            reply_markup=keyboard
        )
    except Exception as e:
        print(f"Failed to send alert: {e}")

    return web.json_response({"status": "forbidden"}, status=403)

@dp.callback_query(F.data.startswith("allow_"))
async def process_callback_allow(callback_query: types.CallbackQuery):
    ip = callback_query.data.split("_")[1]
    await approve_ip(ip)
    await bot.answer_callback_query(callback_query.id, text=f"IP {ip} allowed")
    await bot.edit_message_text(
        text=f"✅ <b>ACCESS GRANTED</b>\n\n🌐 <b>IP:</b> <code>{ip}</code>\n🔓 Authorized for 1 hour.",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id
    )

class UDPLogProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        try:
            payload = json.loads(data.decode())
            asyncio.create_task(self.process_log(payload))
        except Exception:
            pass

    async def process_log(self, data):
        log_type = data.get("type", "info")
        user = data.get("user", "unknown")
        ip = data.get("ip", "unknown")
        cmd = data.get("cmd", "")

        if log_type == "cmd":
            msg = (
                f"💻 <b>CMD</b>: <code>{cmd}</code>\n"
                f"👤 {user} | 🌐 {ip}"
            )
            try:
                await bot.send_message(chat_id=ADMIN_ID, text=msg)
            except Exception:
                pass

async def start_background_tasks(app):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: UDPLogProtocol(),
        local_addr=(UDP_IP, UDP_PORT)
    )
    app['udp_transport'] = transport
    asyncio.create_task(dp.start_polling(bot))

async def cleanup_background_tasks(app):
    app['udp_transport'].close()
    await bot.session.close()

async def main():
    await init_db()
    
    app = web.Application()
    app.router.add_get('/check-access', handle_check_access)
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HTTP_PORT)
    print(f"Starting Guard on {HTTP_PORT}/{UDP_PORT}")
    await site.start()
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
