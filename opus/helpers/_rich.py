# Copyright (c) 2025 OpusMusic
# Licensed under the MIT License.
# This file is part of OpusMusic
#
# Now-playing player built with Telegram Rich Messages (Bot API 10.1+).
# If the installed Pyrogram fork has no rich-message support (RICH_OK is
# False) or a rich call fails, every public function returns None/False so
# the caller falls back to the old inline-keyboard player.

import html as _html
import logging
import re
import time

from pyrogram import enums, errors, types

from opus import app, db

logger = logging.getLogger(__name__)

_NEEDED = (
    "InputRichMessage",
    "InputRichBlockPhoto",
    "InputRichBlockParagraph",
    "InputRichBlockButtons",
    "RichMessageButton",
    "RichTextBold",
    "RichTextUrl",
    "RichTextCode",
)
_MISSING = [n for n in _NEEDED if not hasattr(types, n)]
if not hasattr(app, "send_rich_message"):
    _MISSING.append("Client.send_rich_message")
RICH_OK = not _MISSING
if RICH_OK:
    logger.info("[Rich] Rich Message player ENABLED")
else:
    logger.warning(
        "[Rich] Rich Message player DISABLED - installed Pyrogram fork is "
        "missing: %s. Using the old inline-keyboard player.", ", ".join(_MISSING)
    )

_FORBIDDEN = (errors.ChatSendPhotosForbidden, errors.ChatSendMediaForbidden)
_KEEP = object()  # "leave the stored value as it is"
_TAG_RE = re.compile(r"<(/?)(b|a|code)(?:\s+href=([^>]+))?>", re.IGNORECASE)
_BQ_RE = re.compile(r"</?blockquote[^>]*>", re.IGNORECASE)

# chat_id -> state of the live now-playing message
_np: dict[int, dict] = {}

_DEFAULT_LABELS = {
    "rich_replay": "⥁",
    "rich_pause": "II",
    "rich_resume": "▷",
    "rich_skip": "‣‣I",
    "rich_end": "▢",
}

S = enums.ButtonStyle


# --------------------------------------------------------------------------
# HTML caption -> rich text
# --------------------------------------------------------------------------
def _inline(segment: str):
    parts, stack, pos = [], [], 0
    for m in _TAG_RE.finditer(segment):
        if m.start() > pos:
            parts.append(_html.unescape(segment[pos:m.start()]))
        pos = m.end()
        closing, tag, href = m.group(1), m.group(2).lower(), m.group(3)
        if not closing:
            stack.append((tag, href.strip("\"'") if href else None, len(parts)))
        elif stack and stack[-1][0] == tag:
            open_tag, url, start = stack.pop()
            inner = parts[start:]
            del parts[start:]
            inner = inner[0] if len(inner) == 1 else (inner or "")
            if open_tag == "code":
                parts.append(types.RichTextCode(text=inner))
            elif open_tag == "a" and url and not url.startswith("tg://"):
                parts.append(types.RichTextUrl(text=inner, url=url))
            else:  # bold, or a user mention -> plain bold text
                parts.append(types.RichTextBold(text=inner))
    if pos < len(segment):
        parts.append(_html.unescape(segment[pos:]))
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else parts


def _paragraphs(html_text: str) -> list:
    html_text = _BQ_RE.sub("", html_text or "")
    return [
        types.InputRichBlockParagraph(text=_inline(line))
        for line in (ln.strip() for ln in html_text.split("\n"))
        if line
    ]


# --------------------------------------------------------------------------
# Blocks
# --------------------------------------------------------------------------
def _btn(text, data, style):
    return types.RichMessageButton(text=text, style=style, callback_data=data)


async def _blocks(chat_id, lang, st, *, timer=None, status=None, remove=False):
    from opus.plugins.autoplay import is_autoplay

    blocks = []
    if st.get("photo"):
        blocks.append(types.InputRichBlockPhoto(photo=types.InputMediaPhoto(st["photo"])))
    blocks += _paragraphs(st["caption"])
    if st.get("note"):
        blocks += _paragraphs(st["note"])

    top = status or timer
    if top:
        blocks.append(
            types.InputRichBlockButtons(
                buttons=[_btn(top, f"controls status {chat_id}", S.PRIMARY)]
            )
        )
    if remove:
        return blocks

    def t(key):
        return lang.get(key, _DEFAULT_LABELS[key])

    playing = await db.playing(chat_id)
    toggle = (
        _btn(t("rich_pause"), f"controls pause {chat_id}", S.PRIMARY)
        if playing
        else _btn(t("rich_resume"), f"controls resume {chat_id}", S.SUCCESS)
    )
    ap_on = await is_autoplay(chat_id)
    ap_text = "ᴀᴜᴛᴏᴘʟᴀʏ: ᴏɴ ✅" if ap_on else "ᴀᴜᴛᴏᴘʟᴀʏ: ᴏꜰꜰ ❌"
    blocks += [
        types.InputRichBlockButtons(
            buttons=[
                _btn(t("rich_replay"), f"controls replay {chat_id}", S.PRIMARY),
                toggle,
                _btn(t("rich_skip"), f"controls skip {chat_id}", S.PRIMARY),
            ]
        ),
        types.InputRichBlockButtons(
            buttons=[
                _btn(t("rich_end"), f"controls stop {chat_id}", S.DANGER),
                _btn(ap_text, f"controls autoplay {chat_id}",
                     S.SUCCESS if ap_on else S.DANGER),
            ]
        ),
    ]
    return blocks


def _strip_photo(blocks):
    return [b for b in blocks if not isinstance(b, types.InputRichBlockPhoto)]


# --------------------------------------------------------------------------
# Send / edit
# --------------------------------------------------------------------------
async def _edit(message, blocks):
    try:
        return await message.edit_text(rich_message=types.InputRichMessage(blocks=blocks))
    except _FORBIDDEN:
        plain = _strip_photo(blocks)
        if len(plain) == len(blocks):
            raise
        return await message.edit_text(rich_message=types.InputRichMessage(blocks=plain))


async def _send(chat_id, blocks):
    try:
        return await app.send_rich_message(
            chat_id, rich_message=types.InputRichMessage(blocks=blocks)
        )
    except _FORBIDDEN:
        plain = _strip_photo(blocks)
        if len(plain) == len(blocks):
            raise
        return await app.send_rich_message(
            chat_id, rich_message=types.InputRichMessage(blocks=plain)
        )


async def send_player(chat_id, message, photo, caption_html, lang):
    """Turn `message` (placeholder) into the rich player. Returns the Message
    that now holds the player, or None if rich is unavailable / failed."""
    if not RICH_OK:
        return None
    st = {"photo": photo, "caption": caption_html, "note": None,
          "msg": message, "lang": lang, "last": 0.0}
    try:
        blocks = await _blocks(chat_id, lang, st)
        try:
            sent = await _edit(message, blocks) or message
        except errors.MessageNotModified:
            sent = message
        except Exception:
            try:
                await message.delete()
            except Exception:
                pass
            sent = await _send(chat_id, blocks)
    except Exception as e:
        logger.warning("[Rich] send_player failed in %s: %r - falling back", chat_id, e,
                       exc_info=True)
        return None
    st["msg"] = sent
    st["last"] = time.monotonic()
    _np[chat_id] = st
    return sent


async def update(chat_id, *, message_id=None, note=_KEEP, status=None,
                 timer=None, remove=False, min_gap=0):
    """Re-render the rich player. True = handled, False = caller should
    use the old inline-keyboard path."""
    st = _np.get(chat_id)
    if not RICH_OK or not st:
        return False
    msg = st["msg"]
    if message_id is not None and message_id != msg.id:
        return False
    if min_gap and not remove and time.monotonic() - st["last"] < min_gap:
        return True  # handled: just skipped this tick
    if note is not _KEEP:
        st["note"] = note
    try:
        blocks = await _blocks(chat_id, st["lang"], st, timer=timer,
                               status=status, remove=remove)
        await _edit(msg, blocks)
    except errors.MessageNotModified:
        pass
    except Exception as e:
        logger.warning("[Rich] update failed in %s: %r", chat_id, e)
        return False
    st["last"] = time.monotonic()
    return True


def clear(chat_id):
    _np.pop(chat_id, None)
    
