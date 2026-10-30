# ╔══════════════════════════════════════════════╗
# ║             OpusMusic Bot                  ║
# ║      Advanced Telegram Music System         ║
# ╚══════════════════════════════════════════════╝
#
#  Feature: Auto Welcome
#  Group join hone pe welcome message with group photo
#
#  Powered by OpusMusic
#

from pyrogram import enums, filters, types

from opus import app, config, db, lang
from opus.helpers import can_manage_vc


# ── MongoDB helpers ──────────────────────────────────────────────────────────

_welcome_cache: dict[int, bool] = {}


async def is_welcome(chat_id: int) -> bool:
    if chat_id in _welcome_cache:
        return _welcome_cache[chat_id]
    doc = await db.db.welcome.find_one({"_id": chat_id})
    state = bool(doc.get("enabled", True)) if doc else True
    _welcome_cache[chat_id] = state
    return state


async def set_welcome(chat_id: int, enabled: bool) -> None:
    _welcome_cache[chat_id] = enabled
    await db.db.welcome.update_one(
        {"_id": chat_id}, {"$set": {"enabled": enabled}}, upsert=True,
    )


# ── Welcome buttons ───────────────────────────────────────────────────────────

def _welcome_buttons(chat_id: int, is_on: bool) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup([
        [
            types.InlineKeyboardButton(
                text="✅ ᴡᴇʟᴄᴏᴍᴇ ᴏɴ" if is_on else "❌ ᴡᴇʟᴄᴏᴍᴇ ᴏꜰꜰ",
                callback_data=f"welcome_toggle {chat_id}",
                style=enums.ButtonStyle.SUCCESS if is_on else enums.ButtonStyle.DANGER,
            ),
        ],
        [
            types.InlineKeyboardButton(
                text="⛩️ OpusMusic",
                url=config.SUPPORT_CHAT,
            ),
        ],
    ])


# ── New member handler ────────────────────────────────────────────────────────

@app.on_message(
    filters.new_chat_members & filters.group,
    group=8,
)
async def welcome_new_member(_, m: types.Message):
    try:
        chat_id = m.chat.id
        if not await is_welcome(chat_id):
            return

        for user in m.new_chat_members:
            if user.is_bot:
                continue

            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            user_id = user.id
            username = f"@{user.username}" if user.username else "ɴᴏɴᴇ"
            mention = f"<a href='tg://user?id={user_id}'>{full_name}</a>"
            group_name = m.chat.title or "ɢʀᴏᴜᴘ"

            text = (
                f"ㅤㅤㅤ◦•●◉✿ ᴡᴇʟᴄᴏᴍᴇ ʙᴀʙʏ ✿◉●•◦\n"
                f"▰▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▰\n\n"
                f"● ɢʀᴏᴜᴘ ➥ {group_name}\n"
                f"● ɴᴀᴍᴇ ➥ {mention}\n"
                f"● ᴜsᴇʀ ɪᴅ ➥ <code>{user_id}</code>\n"
                f"● ᴜsᴇʀɴᴀᴍᴇ ➥ {username}\n\n"
                f"❖ ᴘᴏᴡᴇʀᴇᴅ ʙʏ ➥ <a href='{config.SUPPORT_CHAT}'>OpusMusic</a>\n"
                f"▰▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▰"
            )

            buttons = _welcome_buttons(chat_id, True)

            WELCOME_IMG = "https://files.catbox.moe/kdeoz4.jpg"
            await m.reply_photo(photo=WELCOME_IMG, caption=text, reply_markup=buttons, quote=False)

    except Exception:
        pass


# ── /welcome command ──────────────────────────────────────────────────────────

@app.on_message(
    filters.command(["welcome", "setwelcome"])
    & filters.group
    & ~app.bl_users,
    group=9,
)
@can_manage_vc
async def welcome_cmd(_, m: types.Message):
    chat_id = m.chat.id

    if len(m.command) < 2:
        state = await is_welcome(chat_id)
        status = "✅ ᴏɴ" if state else "❌ ᴏꜰꜰ"
        return await m.reply_text(
            f"<b>ᴡᴇʟᴄᴏᴍᴇ ꜱᴛᴀᴛᴜꜱ:</b> {status}",
            reply_markup=_welcome_buttons(chat_id, state),
        )

    sub = m.command[1].lower()
    if sub in ("on", "enable", "1"):
        await set_welcome(chat_id, True)
        return await m.reply_text("✅ ᴡᴇʟᴄᴏᴍᴇ <b>ᴇɴᴀʙʟᴇᴅ</b>.", reply_markup=_welcome_buttons(chat_id, True))
    if sub in ("off", "disable", "0"):
        await set_welcome(chat_id, False)
        return await m.reply_text("❌ ᴡᴇʟᴄᴏᴍᴇ <b>ᴅɪꜱᴀʙʟᴇᴅ</b>.", reply_markup=_welcome_buttons(chat_id, False))

    return await m.reply_text("<b>ᴜꜱᴀɢᴇ:</b> <code>/welcome on</code> | <code>/welcome off</code>")


# ── Callback toggle ───────────────────────────────────────────────────────────

@app.on_callback_query(
    filters.regex(r"^welcome_toggle (\-?\d+)$") & ~app.bl_users,
)
async def welcome_toggle_callback(_, query: types.CallbackQuery):
    try:
        chat_id = int(query.matches[0].group(1))
        member = await app.get_chat_member(chat_id, query.from_user.id)
        if member.status not in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
            return await query.answer("⚠️ Sirf admins toggle kar sakte hain!", show_alert=True)

        current = await is_welcome(chat_id)
        new_state = not current
        await set_welcome(chat_id, new_state)
        status_text = "✅ ᴇɴᴀʙʟᴇᴅ" if new_state else "❌ ᴅɪꜱᴀʙʟᴇᴅ"
        await query.answer(f"ᴡᴇʟᴄᴏᴍᴇ {status_text}", show_alert=True)
        await query.edit_message_reply_markup(reply_markup=_welcome_buttons(chat_id, new_state))
    except Exception:
        await query.answer("ᴇʀʀᴏʀ!", show_alert=True)
