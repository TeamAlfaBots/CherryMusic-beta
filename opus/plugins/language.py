# Copyright (c) 2025 OpusMusic
# Licensed under the MIT License.
# This file is part of OpusMusic


from pyrogram import filters, types

from opus import app, db, lang
from opus.helpers import admin_check, buttons, rich


@app.on_message(filters.command(["lang", "language"]) & ~app.bl_users)
@lang.language()
async def _lang(_, m: types.Message):
    current = await db.get_lang(m.chat.id)
    keyboard = buttons.lang_markup(current)
    # Rich Message language menu; classic message is the fallback
    if await rich.send_menu(m.chat.id, None, m.lang["lang_choose"], keyboard):
        return
    await m.reply_text(m.lang["lang_choose"], reply_markup=keyboard)


@app.on_callback_query(filters.regex(r"^lang(?:_change|uage)") & ~app.bl_users)
@lang.language()
@admin_check
async def _lang_cb(_, query: types.CallbackQuery):
    data = query.data.split()
    if data[0] == "language":
        current = await db.get_lang(query.message.chat.id)
        keyboard = buttons.lang_markup(current)
        if await rich.edit_menu(query, keyboard, query.lang["lang_choose"]):
            return
        return await query.edit_message_text(
            query.lang["lang_choose"], reply_markup=keyboard
        )

    _lang = data[1]
    current = await db.get_lang(query.message.chat.id)
    if current == _lang:
        return await query.answer(
            query.lang["lang_same"].format(current), show_alert=True
        )

    await query.answer(query.lang["lang_change"].format(_lang), show_alert=True)
    await db.set_lang(query.message.chat.id, _lang)
    if await rich.edit_menu(query, None, query.lang["lang_changed"].format(_lang)):
        return
    await query.edit_message_text(query.lang["lang_changed"].format(_lang))
    
