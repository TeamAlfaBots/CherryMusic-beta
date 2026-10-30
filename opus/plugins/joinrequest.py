# ╔══════════════════════════════════════════════╗
# ║             OpusMusic Bot                  ║
# ║      Advanced Telegram Music System         ║
# ╚══════════════════════════════════════════════╝

from pyrogram import filters, types

from opus import app, config
from opus.plugins.start import get_start_img
#&&
_pending: dict[str, dict] = {}


def _key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}:{user_id}"


def _request_buttons(chat_id: int, user_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup([
        [
            types.InlineKeyboardButton(
                text="✅ ᴀᴄᴄᴇᴘᴛ", callback_data=f"jreq accept {chat_id} {user_id}"
            ),
            types.InlineKeyboardButton(
                text="❌ ʀᴇᴊᴇᴄᴛ", callback_data=f"jreq reject {chat_id} {user_id}"
            ),
        ],
    ])


def _joinrequest_buttons() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup([
        [
            types.InlineKeyboardButton(text="ꜱᴜᴘᴘᴏʀᴛ", url=config.SUPPORT_CHAT),
            types.InlineKeyboardButton(text="ᴜᴘᴅᴀᴛᴇ", url=config.SUPPORT_CHANNEL),
        ],
    ])


# -- Naya join request aane par -> sabhi owners ko DM -------------------------

@app.on_chat_join_request()
async def joinrequest_notify_owner(_, request: types.ChatJoinRequest):
    try:
        user = request.from_user
        if not user or user.is_bot:
            return

        chat = request.chat
        chat_title = chat.title or "ɢʀᴏᴜᴘ"
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username = f"@{user.username}" if user.username else "ɴᴏɴᴇ"

        text = (
            f"📥 <b>ɴᴇᴡ ᴊᴏɪɴ ʀᴇǫᴜᴇsᴛ</b>\n\n"
            f"👤 ɴᴀᴍᴇ: {full_name}\n"
            f"🆔 ᴜsᴇʀ ɪᴅ: <code>{user.id}</code>\n"
            f"🔗 ᴜsᴇʀɴᴀᴍᴇ: {username}\n"
            f"💬 ᴄʜᴀᴛ: {chat_title} (<code>{chat.id}</code>)\n\n"
            f"ᴀᴄᴄᴇᴘᴛ ᴏʀ ʀᴇᴊᴇᴄᴛ ᴛʜɪs ʀᴇǫᴜᴇsᴛ?"
        )

        key = _key(chat.id, user.id)
        _pending[key] = {
            "messages": {},  # owner_id -> message_id
            "chat_title": chat_title,
            "full_name": full_name,
            "handled": False,
        }

        for owner_id in config.OWNER_ID:
            try:
                sent = await app.send_message(
                    chat_id=owner_id,
                    text=text,
                    reply_markup=_request_buttons(chat.id, user.id),
                )
                _pending[key]["messages"][owner_id] = sent.id
            except Exception:
                # Owner ne bot ko start nahi kiya ya DM band hai - skip.
                continue

    except Exception:
        pass


# -- Owner ke Approve/Reject dabane par ---------------------------------------

@app.on_callback_query(filters.regex("^jreq ") & ~app.bl_users)
async def joinrequest_decision(_, query: types.CallbackQuery):
    try:
        _, action, chat_id, user_id = query.data.split()
        chat_id, user_id = int(chat_id), int(user_id)
    except Exception:
        return await query.answer()

    if query.from_user.id not in config.OWNER_ID:
        return await query.answer("ʏᴇ ʙᴜᴛᴛᴏɴ ꜱɪʀꜰ ᴏᴡɴᴇʀ ᴋᴇ ʟɪʏᴇ ʜᴀɪ.", show_alert=True)

    key = _key(chat_id, user_id)
    entry = _pending.get(key)

    if not entry or entry["handled"]:
        try:
            await query.edit_message_text("⚠️ ʏᴇ ʀᴇǫᴜᴇsᴛ ᴘᴀʜᴀʟᴇ ʜɪ ᴋɪꜱɪ ᴀᴜʀ ᴏᴡɴᴇʀ ɴᴇ ʜᴀɴᴅʟᴇ ᴋᴀʀ ᴅɪ ʜᴀɪ.")
        except Exception:
            pass
        return await query.answer()

    entry["handled"] = True
    decided_by = query.from_user.mention

    if action == "accept":
        try:
            await app.approve_chat_join_request(chat_id, user_id)
        except Exception:
            for owner_id, msg_id in entry["messages"].items():
                try:
                    await app.edit_message_text(
                        owner_id, msg_id,
                        "❌ ʀᴇǫᴜᴇsᴛ ᴀᴄᴄᴇᴘᴛ ɴᴀʜɪ ʜᴏ ᴘᴀᴀʏɪ (ʙᴏᴛ ᴋᴇ ᴘᴀᴀꜱ ᴘᴇʀᴍɪꜱꜱɪᴏɴ ɴᴀʜɪ ʜᴀɪ)."
                    )
                except Exception:
                    pass
            _pending.pop(key, None)
            return await query.answer()

        result_text = f"✅ ʀᴇǫᴜᴇsᴛ ᴀᴄᴄᴇᴘᴛ ᴋᴀʀ ᴅɪ ɢᴀʏɪ ʙʏ {decided_by}"
        try:
            welcome_text = (
                f"💐 ʜᴇʏ {entry['full_name']} 👋\n"
                f"💮 ᴀᴀᴘᴋɪ ᴊᴏɪɴ ʀᴇǫᴜᴇsᴛ {entry['chat_title']} ᴍᴇ ᴀᴄᴄᴇᴘᴛ ᴋᴀʀ ᴅɪ ɢᴀʏɪ ʜᴀɪ 🎉\n\n"
                f"ɪ'ᴍ {app.name} - ᴀ ʜɪɢʜ ǫᴜᴀʟɪᴛʏ ᴍᴜsɪᴄ sᴛʀᴇᴀᴍɪɴɢ ʙᴏᴛ ꜰᴏʀ ᴛᴇʟᴇɢʀᴀᴍ ɢʀᴏᴜᴘs & ᴄʜᴀɴɴᴇʟs 🚀\n\n"
                f"📋 ᴊᴜsᴛ sᴇɴᴅ /start ᴛᴏ sᴇᴇ ʙᴏᴛ ᴍᴇɴᴜ ᴀɴᴅ ᴄᴏᴍᴍᴀɴᴅs 📋"
            )
            start_img = get_start_img()
            if start_img:
                await app.send_photo(
                    chat_id=user_id,
                    photo=start_img,
                    caption=welcome_text,
                    reply_markup=_joinrequest_buttons(),
                )
            else:
                await app.send_message(
                    chat_id=user_id,
                    text=welcome_text,
                    reply_markup=_joinrequest_buttons(),
                )
        except Exception:
            # User ne bot ko /start nahi kiya hoga - request phir bhi accept ho chuki hai.
            pass

    else:
        try:
            await app.decline_chat_join_request(chat_id, user_id)
        except Exception:
            pass
        result_text = f"❌ ʀᴇǫᴜᴇsᴛ ʀᴇᴊᴇᴄᴛ ᴋᴀʀ ᴅɪ ɢᴀʏɪ ʙʏ {decided_by}"

    for owner_id, msg_id in entry["messages"].items():
        try:
            await app.edit_message_text(owner_id, msg_id, result_text)
        except Exception:
            pass

    _pending.pop(key, None)
    await query.answer()
    
