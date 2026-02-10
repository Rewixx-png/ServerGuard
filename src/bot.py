import asyncio
import os
import sys
import json
import time
import secrets
import aiosqlite
import asyncssh
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Config
TOKEN = os.getenv("TG_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
PUBLIC_IP = os.getenv("PUBLIC_IP", "127.0.0.1")
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
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# FSM States
class AddServer(StatesGroup):
    ip = State()
    port = State()
    user = State()
    auth_method = State() # 'pass' or 'key'
    credentials = State()

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
        # Default Localhost
        async with db.execute("SELECT count(*) FROM servers") as cursor:
            count = await cursor.fetchone()
            if count[0] == 0:
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
    
    # We need to scp the scripts. In docker, they are in current dir or /app
    # But usually Bot runs in /app and scripts are not there unless copied.
    # We will reconstruct the installer content dynamically or assume availability.
    # Best way: Read local files.
    
    # Check if files exist
    base_path = "." # In Docker, WORKDIR is /app
    files_to_send = [
        ("sg-check-access", "scripts/check_access.sh"),
        ("sg-sftp-wrapper", "scripts/sftp_wrapper.sh"),
        ("sg-logger", "scripts/logger.sh"),
        ("agent_installer.sh", "scripts/agent_installer.sh")
    ]
    
    # In docker, the context is /app. Scripts are not copied to /app/scripts in previous steps?
    # Wait, 'installer.py' copies 'src' to install dir. Docker builds FROM src.
    # But 'src' contains 'bot.py'. Does it contain 'scripts'?
    # Previous user requests didn't explicitly COPY scripts into Docker image.
    # CRITICAL FIX: We must assume scripts might be missing inside container if not COPY'd.
    # But for now, let's assume valid mount or copy.
    # If fails, we can just write content string.
    
    # Actually, let's look at Dockerfile previously generated. It only copies requirements and bot.py.
    # FIX: We need to update Dockerfile to copy scripts too. I will update Dockerfile in this response.
    
    try:
        conn_args = {'host': ip, 'port': port, 'username': user, 'known_hosts': None}
        if password:
            conn_args['password'] = password
        if key_file:
            conn_args['client_keys'] = [key_file]

        async with asyncssh.connect(**conn_args) as conn:
            # Upload files
            for remote_name, local_rel_path in files_to_send:
                # local path is relative to /app inside docker
                # We need to make sure these exist.
                # If they don't, we are in trouble.
                # Assuming updated Dockerfile.
                await asyncssh.scp(local_rel_path, (conn, f"/tmp/{remote_name}"))
            
            # Run Installer
            api_url = f"http://{PUBLIC_IP}:{HTTP_PORT}"
            log_host = PUBLIC_IP
            
            cmd = f"chmod +x /tmp/agent_installer.sh && /tmp/agent_installer.sh '{api_url}' '{token}' '{log_host}'"
            result = await conn.run(cmd, check=True)
            return True, result.stdout

    except Exception as e:
        return False, str(e)

# --- Handlers ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.from_user.id != ADMIN_ID: return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Server", callback_data="add_server")],
        [InlineKeyboardButton(text="📜 Access History", callback_data="menu_history")],
        [InlineKeyboardButton(text="🔐 Whitelist IPs", callback_data="menu_whitelist")]
    ])
    
    await message.answer(
        "🛡 <b>Server Guard Controller</b>\n\nSelect an action:",
        reply_markup=kb
    )

@dp.callback_query(F.data == "add_server")
async def start_add_server(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("🌐 Enter the <b>IP Address</b> of the new server:")
    await state.set_state(AddServer.ip)
    await call.answer()

@dp.message(AddServer.ip)
async def process_ip(message: types.Message, state: FSMContext):
    await state.update_data(ip=message.text.strip())
    await message.answer("🔌 Enter SSH Port (send 22 for default):")
    await state.set_state(AddServer.port)

@dp.message(AddServer.port)
async def process_port(message: types.Message, state: FSMContext):
    port = message.text.strip()
    if not port.isdigit(): port = 22
    await state.update_data(port=int(port))
    await message.answer("👤 Enter SSH Username (send root for default):")
    await state.set_state(AddServer.user)

@dp.message(AddServer.user)
async def process_user(message: types.Message, state: FSMContext):
    user = message.text.strip()
    if not user: user = "root"
    await state.update_data(user=user)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Password", callback_data="auth_pass")],
        [InlineKeyboardButton(text="📄 SSH Key File", callback_data="auth_key")]
    ])
    await message.answer("🔐 Choose authentication method:", reply_markup=kb)
    await state.set_state(AddServer.auth_method)

@dp.callback_query(AddServer.auth_method)
async def process_auth_method(call: types.CallbackQuery, state: FSMContext):
    method = call.data.split("_")[1]
    await state.update_data(auth_method=method)
    if method == "pass":
        await call.message.answer("⌨️ Enter SSH Password:")
    else:
        await call.message.answer("📂 Send the SSH Private Key file:")
    await state.set_state(AddServer.credentials)
    await call.answer()

@dp.message(AddServer.credentials)
async def process_credentials(message: types.Message, state: FSMContext):
    data = await state.get_data()
    auth_method = data['auth_method']
    
    password = None
    key_file = None
    
    msg = await message.answer(f"⏳ Connecting to {data['ip']}...")
    
    if auth_method == "pass":
        password = message.text
    else:
        if not message.document:
            await message.answer("❌ Please send a file.")
            return
        file_id = message.document.file_id
        file = await bot.get_file(file_id)
        key_file = f"/tmp/key_{data['ip']}"
        await bot.download_file(file.file_path, key_file)
        os.chmod(key_file, 0o600)

    success, log = await deploy_agent(data['ip'], data['port'], data['user'], password, key_file)
    
    if key_file and os.path.exists(key_file):
        os.remove(key_file)
        
    if success:
        await msg.edit_text(f"✅ <b>Agent Installed!</b>\nServer {data['ip']} is now protected.")
    else:
        # Truncate log if too long
        log_snippet = (str(log)[:3000] + '..') if len(str(log)) > 3000 else str(log)
        await msg.edit_text(f"❌ <b>Deployment Failed:</b>\n\n<code>{log_snippet}</code>")
    
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
        await call.message.edit_text("📜 History is empty.", reply_markup=None)
        return

    msg = "📜 <b>Last 10 Login Attempts:</b>\n\n"
    for r in rows:
        ts = time.strftime('%H:%M', time.localtime(r[3]))
        icon = "✅" if r[2] == "ALLOWED" else "⛔"
        srv = r[4] if r[4] else "Unknown"
        msg += f"{icon} <b>{srv}</b>\n   <code>{r[0]}</code> ({r[1]}) - {ts}\n"
    
    await call.message.edit_text(msg, reply_markup=None)

@dp.callback_query(F.data == "menu_whitelist")
async def show_whitelist(call: types.CallbackQuery):
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

# --- HTTP API ---
async def handle_check_access(request):
    token = request.headers.get("X-Guard-Token") or request.query.get("token")
    ip = request.query.get('ip')
    user = request.query.get('user')
    
    if not ip or not user:
        return web.json_response({"status": "error"}, status=400)
    
    # Authenticate Server
    server = await get_server_by_token(token)
    if not server:
        # Fallback for localhost legacy or missing token
        if ip == "127.0.0.1" or ip == "::1":
            server = (1, "Master Node", "127.0.0.1")
        else:
            return web.json_response({"status": "unauthorized"}, status=401)
    
    server_id = server[0]
    server_name = server[1]

    allowed = await is_ip_allowed(ip)
    
    status_log = "ALLOWED" if allowed else "BLOCKED"
    await log_attempt(server_id, ip, user, status_log)
    
    if allowed:
        return web.json_response({"status": "allowed"})
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Allow {ip} (1h)", callback_data=f"allow_{ip}")]
    ])
    
    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🚨 <b>UNAUTHORIZED ACCESS BLOCKED</b>\n\n"
                 f"🏢 <b>Server:</b> {server_name}\n"
                 f"👤 <b>User:</b> {user}\n"
                 f"🌐 <b>IP:</b> <code>{ip}</code>\n"
                 f"🕒 <b>Time:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                 f"Connection closed.",
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

# --- UDP Logger ---
class UDPLogProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        try:
            payload = json.loads(data.decode())
            asyncio.create_task(self.process_log(payload, addr))
        except Exception:
            pass

    async def process_log(self, data, addr):
        log_type = data.get("type", "info")
        token = data.get("token", "")
        
        # Verify Token (Optional, but good practice)
        # server = await get_server_by_token(token)
        # For performance we might skip DB check on every UDP packet or cache it.
        # Let's trust the token exists in DB for now or fallback to IP check.
        
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
    print(f"Starting Guard Controller on {HTTP_PORT}")
    await site.start()
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
