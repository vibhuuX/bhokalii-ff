import logging
import re
import os
import asyncio
import sys
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message
from supabase import create_client
from dotenv import load_dotenv

# ---------- PYTHON 3.14+ FIX ----------
if sys.version_info >= (3, 14):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv()
logging.basicConfig(level=logging.INFO)

# ---------- CONFIGURATION ----------
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
STREAM_DOMAIN = os.getenv("STREAM_DOMAIN")

# ---------- Supabase Client ----------
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Pyrogram Client ----------
app = Client("vibhu_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# In-memory sessions
user_sessions = {}

# ---------- Helper Functions ----------
def is_admin(user_id: int) -> bool:
    try:
        resp = supabase.table("admins").select("user_id").eq("user_id", user_id).execute()
        return len(resp.data) > 0
    except:
        return False

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

async def authorize(user_id: int) -> bool:
    if is_owner(user_id) or is_admin(user_id):
        return True
    return False

def extract_topic_from_caption(caption: str) -> str:
    if not caption:
        return None
    match = re.search(r'Title:\s*(.+?)\s+\d+x\d+', caption, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match2 = re.search(r'Title:\s*(.+?)(?:\n|$)', caption, re.IGNORECASE)
    if match2:
        return match2.group(1).strip()
    return None

def save_lecture(app_name, batch_name, subject_name, topic, stream_url, file_type):
    data = {
        "app_name": app_name,
        "batch_name": batch_name,
        "subject_name": subject_name,
        "topic": topic[:200],
        "stream_url": stream_url,
        "file_type": file_type
    }
    try:
        supabase.table("lectures").insert(data).execute()
        logging.info(f"Saved: {topic}")
        return True
    except Exception as e:
        logging.error(f"Supabase insert error: {e}")
        return False

# ---------- Streaming Server ----------
async def stream_file(request):
    file_id = request.match_info['file_id']
    try:
        file_path = await app.download_media(file_id, in_memory=True)
        if not file_path:
            return web.Response(text="File not found", status=404)
        
        mime = "video/mp4"
        response = web.StreamResponse()
        response.headers['Content-Type'] = mime
        response.headers['Content-Disposition'] = 'inline'
        await response.prepare(request)
        
        chunk_size = 1024 * 1024
        while True:
            chunk = file_path.read(chunk_size)
            if not chunk:
                break
            await response.write(chunk)
        return response
    except Exception as e:
        logging.error(f"Stream error: {e}")
        return web.Response(text="Streaming error", status=500)

# ---------- Health Check for Render ----------
async def health(request):
    return web.Response(text="OK", status=200)

# ---------- Bot Commands ----------
@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client: Client, message: Message):
    if not await authorize(message.from_user.id):
        await message.reply("⛔ Access Denied.")
        return
    await message.reply(
        "⚔️ *Vɪʙʜᴜᴜ 𓃵 X* ⚔️\n"
        "Defence Study Hub Bot Active\n\n"
        "📌 *Commands:*\n"
        "/setapp <App> - e.g., /setapp CDS JOURNEY\n"
        "/setbatch <Batch> - e.g., /setbatch Alpha OTA\n"
        "/setsubject <Subject> - e.g., /setsubject English\n"
        "Then forward any video/PDF.\n"
        "/done - Clear current session\n\n"
        "*Admin only:*\n/addadmin /removeadmin /listadmins",
        parse_mode="Markdown"
    )

@app.on_message(filters.command("ping") & filters.private)
async def ping_cmd(client: Client, message: Message):
    if not await authorize(message.from_user.id):
        return
    await message.reply("pong")

@app.on_message(filters.command("setapp") & filters.private)
async def setapp_cmd(client: Client, message: Message):
    if not await authorize(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Usage: /setapp CDS JOURNEY")
        return
    uid = message.from_user.id
    user_sessions[uid] = {"app": parts[1]}
    await message.reply("✅ App set. Now /setbatch <Batch>")

@app.on_message(filters.command("setbatch") & filters.private)
async def setbatch_cmd(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in user_sessions:
        await message.reply("First /setapp")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Usage: /setbatch Alpha OTA")
        return
    user_sessions[uid]["batch"] = parts[1]
    await message.reply("✅ Batch set. Now /setsubject <Subject>")

@app.on_message(filters.command("setsubject") & filters.private)
async def setsubject_cmd(client: Client, message: Message):
    uid = message.from_user.id
    if uid not in user_sessions or "batch" not in user_sessions[uid]:
        await message.reply("First /setapp and /setbatch")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Usage: /setsubject English")
        return
    user_sessions[uid]["subject"] = parts[1]
    await message.reply("✅ Subject set. Now forward any video/PDF. Use /done to finish.")

@app.on_message(filters.command("done") & filters.private)
async def done_cmd(client: Client, message: Message):
    uid = message.from_user.id
    user_sessions.pop(uid, None)
    await message.reply("Session cleared.")

@app.on_message(filters.video | filters.document)
async def handle_file(client: Client, message: Message):
    if message.chat.type != "private":
        return
    if not await authorize(message.from_user.id):
        return
    uid = message.from_user.id
    if uid not in user_sessions or "subject" not in user_sessions[uid]:
        await message.reply("Please set app/batch/subject first.")
        return
    
    ctx = user_sessions[uid]
    file_obj = message.video or message.document
    if not file_obj:
        await message.reply("Only video or PDF files are supported.")
        return
    
    file_type = "video" if message.video else "pdf"
    file_name = file_obj.file_name or "unknown"
    caption = message.caption or ""
    
    topic = extract_topic_from_caption(caption)
    if not topic:
        topic = os.path.splitext(file_name)[0]
    if not topic:
        topic = "Unknown Topic"
    
    file_id = file_obj.file_id
    stream_url = f"{STREAM_DOMAIN}/stream/{file_id}"
    
    success = save_lecture(
        ctx["app"], ctx["batch"], ctx["subject"],
        topic, stream_url, file_type
    )
    if success:
        await message.reply(f"✅ Saved: {topic[:60]}")
    else:
        await message.reply("❌ Failed to save to database.")

# Admin commands
@app.on_message(filters.command("addadmin") & filters.private)
async def add_admin_cmd(client: Client, message: Message):
    if not is_owner(message.from_user.id):
        await message.reply("Only owner can add admins.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Usage: /addadmin <user_id>")
        return
    new_id = int(parts[1])
    try:
        supabase.table("admins").insert({"user_id": new_id, "added_by": OWNER_ID}).execute()
        await message.reply(f"✅ Admin {new_id} added.")
    except Exception as e:
        await message.reply(f"Failed: {e}")

@app.on_message(filters.command("removeadmin") & filters.private)
async def remove_admin_cmd(client: Client, message: Message):
    if not is_owner(message.from_user.id):
        await message.reply("Only owner can remove admins.")
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Usage: /removeadmin <user_id>")
        return
    admin_id = int(parts[1])
    if admin_id == OWNER_ID:
        await message.reply("Cannot remove owner.")
        return
    try:
        supabase.table("admins").delete().eq("user_id", admin_id).execute()
        await message.reply(f"✅ Admin {admin_id} removed.")
    except Exception as e:
        await message.reply(f"Failed: {e}")

@app.on_message(filters.command("listadmins") & filters.private)
async def list_admins_cmd(client: Client, message: Message):
    if not await authorize(message.from_user.id):
        return
    resp = supabase.table("admins").select("user_id").execute()
    admins = [str(row["user_id"]) for row in resp.data]
    if not admins:
        await message.reply("No admins found.")
    else:
        await message.reply("Admins:\n" + "\n".join(admins))

# ---------- Run Both Bot and Stream Server ----------
async def main():
    # Create a fresh event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    web_app = web.Application()
    web_app.router.add_get('/stream/{file_id}', stream_file)
    web_app.router.add_get('/health', health)   # <-- Health check endpoint
    
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Health check & stream server running on port {port}")
    
    await app.start()
    logging.info("Bot started")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())





