import asyncio
import os
import sys
import json
import time
import secrets
import logging
import aiosqlite
import asyncssh
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ServerGuard")

# --- Configuration ---
TOKEN = os.getenv("TG_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
PUBLIC_IP = os.getenv("PUBLIC_IP", "127.0.0.1")
DB_PATH = "/data/guard.db"
UDP_PORT = 9999
HTTP_PORT = 8080

if not TOKEN or not ADMIN_ID:
    logger.fatal("TG_TOKEN or ADMIN_ID is missing in environment variables.")
    sys.exit(1)

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    logger.fatal("ADMIN_ID must be an integer.")
    sys.exit(1)

# --- Bot Initialization ---
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- FSM States ---
class AddServer(StatesGroup):
    ip = State()
    port = State()
    user = State()
    auth_method = State()
    credentials = State()

# --- Database Functions ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                ip TEXT UNIQUE,
                token TEXT,
                added_at INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS approved_ips (
                ip TEXT PRIMARY KEY,
                expiry INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER,
                ip TEXT,
                user TEXT,
                status TEXT,
                timestamp INTEGER
            )
        """)
        
        async with db.execute("SELECT count(*) FROM servers") as cursor:
            count = await cursor.fetchone()
            if count[0] == 0:
                logger.info("Initializing DB with Master Node...")
                await db.execute(
                    "INSERT INTO servers (name, ip, token, added_at) VALUES (?, ?, ?, ?)",
                    ("Master Node", "127.0.0.1", "local-token", int(time.time()))
                )
        await db.commit()

async def get_server_by_token(token):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name, ip FROM servers WHERE token = ?", (token,)) as cursor:
            return await cursor.fetchone()

async def add_server_db(name, ip):
    token = secrets.token_hex(16)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("REPLACE INTO servers (name, ip, token, added_at) VALUES (?, ?, ?, ?)", 
                         (name, ip, token, int(time.time())))
        await db.commit()
    return token

async def log_attempt(server_id, ip, user, status):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO history (server_id, ip, user, status, timestamp) VALUES (?, ?, ?, ?, ?)",
            (server_id, ip, user, status, int(time.time()))
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

# --- SSH Deployment Logic ---
async def deploy_agent(ip, port, user, password=None, key_file=None):
    token = await add_server_db(f"Agent {ip}", ip)
    
    files_to_send = [
        ("scripts/check_access.sh", "sg-check-access"),
        ("scripts/sftp_wrapper.sh", "sg-sftp-wrapper"),
        ("scripts/logger.sh", "sg-logger"),
        ("scripts/agent_installer.sh", "agent_installer.sh")
    ]
    
    try:
        conn_args = {'host': ip, 'port': port, 'username': user, 'known_hosts': None}
        if password:
            conn_args['password'] = password
        if key_file:
            conn_args['client_keys'] = [key_file]

        async with asyncssh.connect(**conn_args) as conn:
            for local_rel, remote_name in files_to_send:
                local_path = os.path.abspath(local_rel)
                if not os.path.exists(local_path):
                    return False, f"Missing local file: {local_path}"
                await asyncssh.scp(local_path, (conn, f"/tmp/{remote_name}"))
            
            # FIX: Append /check-access to the API URL
            api_url = f"http://{PUBLIC_IP}:{HTTP_PORT}/check-access"
            log_host = PUBLIC_IP
            
            cmd = f"chmod +x /tmp/agent_installer.sh && /tmp/agent_installer.sh '{api_url}' '{token}' '{log_host}'"
            result = await conn.run(cmd, check=True)
            return True, result.stdout

    except Exception as e:
        logger.error(f"Deploy Error: {e}")
        return False, str(e)

# --- Telegram Handlers ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Server", callback_data="add_server")],
        [InlineKeyboardButton(text="📜 History", callback_data="menu_history")],
        [InlineKeyboardButton(text="🔐 Whitelist", callback_data="menu_whitelist")]
    ])
    await message.answer(
        f"🛡 <b>Server Guard Controller</b>\nIP: <code>{PUBLIC_IP}</code>\n\nSystem Online.",
        reply_markup=kb
    )

@dp.callback_query(F.data == "add_server")
async def start_add_server(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("🌐 Enter <b>IP Address</b> of new server:")
    await state.set_state(AddServer.ip)
    await call.answer()

@dp.message(AddServer.ip)
async def process_ip(message: types.Message, state: FSMContext):
    await state.update_data(ip=message.text.strip())
    await message.answer("🔌 Enter SSH Port (default 22):")
    await state.set_state(AddServer.port)

@dp.message(AddServer.port)
async def process_port(message: types.Message, state: FSMContext):
    txt = message.text.strip()
    port = int(txt) if txt.isdigit() else 22
    await state.update_data(port=port)
    await message.answer("👤 Enter SSH Username (default root):")
    await state.set_state(AddServer.user)

@dp.message(AddServer.user)
async def process_user(message: types.Message, state: FSMContext):
    user = message.text.strip() or "root"
    await state.update_data(user=user)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Password", callback_data="auth_pass")],
        [InlineKeyboardButton(text="📄 SSH Key", callback_data="auth_key")]
    ])
    await message.answer("🔐 Auth Method:", reply_markup=kb)
    await state.set_state(AddServer.auth_method)

@dp.callback_query(AddServer.auth_method)
async def process_auth_method(call: types.CallbackQuery, state: FSMContext):
    method = call.data.split("_")[1]
    await state.update_data(auth_method=method)
    if method == "pass":
        await call.message.answer("⌨️ Enter Password:")
    else:
        await call.message.answer("📂 Send Private Key File:")
    await state.set_state(AddServer.credentials)
    await call.answer()

@dp.message(AddServer.credentials)
async def process_credentials(message: types.Message, state: FSMContext):
    data = await state.get_data()
    auth_method = data['auth_method']
    password = None
    key_file = None
    status_msg = await message.answer(f"⏳ Connecting to {data['ip']}...")
    
    if auth_method == "pass":
        password = message.text
    else:
        if not message.document:
            await message.answer("❌ File expected.")
            return
        file_id = message.document.file_id
        file = await bot.get_file(file_id)
        key_file = f"/tmp/key_{data['ip']}_{int(time.time())}"
        await bot.download_file(file.file_path, key_file)
        os.chmod(key_file, 0o600)

    success, log = await deploy_agent(data['ip'], data['port'], data['user'], password, key_file)
    if key_file and os.path.exists(key_file):
        os.remove(key_file)
        
    if success:
        await status_msg.edit_text(f"✅ <b>Success!</b>\nServer {data['ip']} attached.")
    else:
        clean_log = str(log).replace("<", "&lt;")[:3000]
        await status_msg.edit_text(f"❌ <b>Failed:</b>\n<pre>{clean_log}</pre>")
    await state.clear()

@dp.callback_query(F.data == "menu_history")
async def show_history(call: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT h.ip, h.user, h.status, h.timestamp, s.name 
            FROM history h 
            LEFT JOIN servers s ON h.server_id = s.id 
            ORDER BY h.id DESC LIMIT 10
        """) as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await call.message.edit_text("📜 History empty.", reply_markup=None)
        return
    msg = "📜 <b>Last Access Attempts:</b>\n"
    for r in rows:
        ts = time.strftime('%H:%M', time.localtime(r[3]))
        icon = "✅" if r[2] == "ALLOWED" else "⛔"
        srv = r[4] if r[4] else "?"
        msg += f"{icon} <b>{srv}</b> | {r[1]}@{r[0]} ({ts})\n"
    await call.message.edit_text(msg, reply_markup=None)

@dp.callback_query(F.data == "menu_whitelist")
async def show_whitelist(call: types.CallbackQuery):
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT ip, expiry FROM approved_ips WHERE expiry > ?", (now,)) as cursor:
            rows = await cursor.fetchall()
    msg = "🔐 <b>Whitelisted IPs:</b>\n"
    if not rows: msg += "None."
    for r in rows:
        left = int((r[1] - now) / 60)
        msg += f"🌐 <code>{r[0]}</code> ({left}m)\n"
    await call.message.edit_text(msg, reply_markup=None)

# --- HTTP API Handlers ---

async def handle_check_access(request):
    token = request.headers.get("X-Guard-Token") or request.query.get("token")
    ip = request.query.get('ip')
    user = request.query.get('user')
    
    if not ip or not user:
        return web.json_response({"status": "error", "msg": "missing_params"}, status=400)
    
    if token == "None" or token is None:
        token = "local-token"
    
    server = await get_server_by_token(token)
    
    if not server:
        if token == "local-token":
             server = (1, "Master Node", "127.0.0.1")
        else:
            logger.warning(f"Unauthorized API call from {ip}. Token received: '{token}'")
            return web.json_response({"status": "unauthorized"}, status=401)
            
    server_id = server[0]
    server_name = server[1]

    allowed = await is_ip_allowed(ip)
    status_log = "ALLOWED" if allowed else "BLOCKED"
    await log_attempt(server_id, ip, user, status_log)
    
    if allowed:
        return web.json_response({"status": "allowed"})
    
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"✅ Allow {ip} (1h)", callback_data=f"allow_{ip}")]])
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🚨 <b>BLOCKED</b>\n\n🏢 <b>{server_name}</b>\n👤 {user}\n🌐 <code>{ip}</code>",
            reply_markup=kb
        )
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")

    return web.json_response({"status": "forbidden"}, status=403)

@dp.callback_query(F.data.startswith("allow_"))
async def process_callback_allow(call: types.CallbackQuery):
    ip = call.data.split("_")[1]
    await approve_ip(ip)
    try:
        await call.message.edit_text(f"✅ <b>Access Granted</b>\n🌐 {ip} (1h)")
    except: pass

class UDPLogProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        try:
            payload = json.loads(data.decode())
            if payload.get("token") == "local-token" or payload.get("token"):
                 asyncio.create_task(self.process_log(payload))
        except Exception:
            pass

    async def process_log(self, data):
        log_type = data.get("type", "info")
        user = data.get("user", "?")
        ip = data.get("ip", "?")
        cmd = data.get("cmd", "")
        if log_type == "cmd" and cmd:
            msg = f"💻 <b>CMD</b>: <code>{cmd}</code>\n👤 {user} | 🌐 {ip}"
            try:
                await bot.send_message(chat_id=ADMIN_ID, text=msg)
            except: pass

async def start_background_tasks(app):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: UDPLogProtocol(),
        local_addr=("0.0.0.0", UDP_PORT)
    )
    app['udp_transport'] = transport
    try:
        await bot.send_message(ADMIN_ID, f"🟢 <b>System Online</b>\nRunning on Port {HTTP_PORT}")
    except Exception as e:
        logger.error(f"Startup Msg Failed: {e}")
    asyncio.create_task(dp.start_polling(bot))

async def cleanup_background_tasks(app):
    if 'udp_transport' in app:
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
    print(f"ServerGuard Controller running on 0.0.0.0:{HTTP_PORT} (TCP) & {UDP_PORT} (UDP)")
    await site.start()
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
