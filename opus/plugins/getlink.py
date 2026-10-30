# ╔══════════════════════════════════════════════╗
# ║             OpusMusic Bot                  ║
# ║      Advanced Telegram Music System         ║
# ╚══════════════════════════════════════════════╝
#
#  Feature: /getlink
#  Owner/Sudo only — all group invite links
#
#  Powered by OpusMusic
#

from pyrogram import filters, types

from opus import app, db


@app.on_message(
    filters.command(["getlink", "getlinks"])
    & app.sudoers
    & ~app.bl_users,
)
async def getlink_cmd(_, m: types.Message):

    sent = await m.reply_text("⏳ ꜰᴇᴛᴄʜɪɴɢ ɢʀᴏᴜᴘ ʟɪɴᴋꜱ...")
    chats = await db.get_chats()

    if not chats:
        return await sent.edit_text("ʙᴏᴛ ᴋɪꜱɪ ɢʀᴏᴜᴘ ᴍᴇɪɴ ɴᴀʜɪɴ ʜᴀɪ.")

    results = []
    failed = []
    count = 0

    for chat_id in chats:
        try:
            chat = await app.get_chat(chat_id)
            chat_name = chat.title or "Unknown"
            try:
                link = chat.invite_link
                if not link:
                    link = await app.export_chat_invite_link(chat_id)
            except Exception:
                link = "ɴᴏ ᴘᴇʀᴍɪꜱꜱɪᴏɴ"

            count += 1
            results.append(
                f"<b>{count}.</b>\n"
                f"📛 <b>ɴᴀᴍᴇ ➥</b> {chat_name}\n"
                f"🆔 <b>ɪᴅ ➥</b> <code>{chat_id}</code>\n"
                f"🔗 <b>ʟɪɴᴋ ➥</b> {link}\n"
            )
        except Exception:
            failed.append(str(chat_id))
            continue

    if not results:
        return await sent.edit_text("❌ ᴋᴏɪ ʟɪɴᴋ ꜰᴇᴛᴄʜ ɴᴀʜɪɴ ʜᴏ ᴘᴀʏᴀ.")

    full_text = (
        f"<b>🔗 ʙᴏᴛ ɢʀᴏᴜᴘ ʟɪɴᴋꜱ — {count} ɢʀᴏᴜᴘꜱ</b>\n"
        f"▰▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▱▰\n\n"
    ) + "\n".join(results)

    if failed:
        full_text += f"\n\n⚠️ <b>{len(failed)} ɢʀᴏᴜᴘꜱ ꜰᴇᴛᴄʜ ɴᴀʜɪɴ ʜᴜᴇ</b>"

    chunks = [full_text[i:i+4096] for i in range(0, len(full_text), 4096)]
    await sent.edit_text(chunks[0], disable_web_page_preview=True)
    for chunk in chunks[1:]:
        await m.reply_text(chunk, disable_web_page_preview=True)
