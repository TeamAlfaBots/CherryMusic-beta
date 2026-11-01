# Copyright (c) 2025 OpusMusic
# Licensed under the MIT License.
# This file is part of OpusMusic
#
# Now-playing player + start menu built with Telegram Rich Messages
# (Bot API 10.1+). If the installed Pyrogram fork has no rich-message
# support (RICH_OK is False) or a rich call fails, every public function
# returns None/False so the caller falls back to the classic inline player.

import html as _html
import logging
import os
import random
import re
import time

from pyrogram import enums, errors, types

from opus import app

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

# seconds between rich player refreshes (each refresh re-uploads the thumbnail
# and re-rolls the button colors). RICH_TIMER_GAP env var overrides.
TIMER_GAP = int(os.getenv("RICH_TIMER_GAP", "12"))
# set RICH_START=0 to keep the classic /start message
START_ENABLED = os.getenv("RICH_START", "1") != "0"
# set RICH_HELP=0 to keep the classic /help menu
HELP_ENABLED = os.getenv("RICH_HELP", "1") != "0"
# set RICH_QUEUE=0 to keep the classic "Added to queue" message
QUEUE_ENABLED = os.getenv("RICH_QUEUE", "1") != "0"

_FORBIDDEN = (errors.ChatSendPhotosForbidden, errors.ChatSendMediaForbidden)
_KEEP = object()  # "leave the stored value as it is"
_TAG_RE = re.compile(r"<(/?)(b|a|code)(?:\s+href=([^>]+))?>", re.IGNORECASE)
_BQ_RE = re.compile(r"</?blockquote[^>]*>", re.IGNORECASE)

S = enums.ButtonStyle
_COLORS = (S.PRIMARY, S.SUCCESS, S.DANGER)

_np: dict[int, dict] = {}  # chat_id -> live now-playing state
_menus: dict[tuple, dict] = {}  # (chat_id, message_id) -> rich menu state


# HTML caption -> rich text
_OTHER_TAG_RE = re.compile(r"</?(?!b\b|a\b|code\b)[a-z][^>]*>", re.IGNORECASE)

def _inline(segment: str):
    segment = _OTHER_TAG_RE.sub("", segment)  # <i>, <u>, <pre>... -> dropped
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

_BQ_BLOCK_RE = re.compile(r"<blockquote\b([^>]*)>(.*?)</blockquote>", re.IGNORECASE | re.DOTALL)
_QUOTE_ERRORS = (errors.BadRequest, TypeError, ValueError, AttributeError)
# footer line under the player ("Made By <link>")
CREDIT_TEXT = "AlfaBots"
CREDIT_URL = "https://t.me/Uffsexyboi"
_QUOTE = {"ok": os.getenv("RICH_QUOTE", "1") != "0"}  # RICH_QUOTE=0 -> no quote boxes

def _lines(html_text: str) -> list:
    return [ln.strip() for ln in (html_text or "").split("\n") if ln.strip()]

def _plain_blocks(html_text: str) -> list:
    html_text = _BQ_RE.sub("", html_text or "")
    return [types.InputRichBlockParagraph(text=_inline(ln)) for ln in _lines(html_text)]

def _quote_blocks(inner: str, expandable: bool) -> list:
    """<blockquote> -> quote block, <blockquote expandable> -> collapsible block."""
    lines = _lines(inner)
    if not lines:
        return []
    try:
        if expandable and hasattr(types, "InputRichBlockExpandableBlockQuotation"):
            parts = []
            for i, ln in enumerate(lines):
                if i:
                    parts.append("\n")
                x = _inline(ln)
                parts += x if isinstance(x, list) else [x]
            return [types.InputRichBlockExpandableBlockQuotation(text=parts)]
        return [
            types.InputRichBlockBlockQuotation(
                blocks=[types.InputRichBlockParagraph(text=_inline(ln)) for ln in lines]
            )
        ]
    except Exception as e:  # field names differ in this fork -> plain text
        _QUOTE["ok"] = False
        logger.warning("[Rich] quote blocks unsupported (%r) - using plain text", e)
        return _plain_blocks(inner)

def _paragraphs(html_text: str) -> list:
    html_text = html_text or ""
    if not (_QUOTE["ok"] and hasattr(types, "InputRichBlockBlockQuotation")):
        return _plain_blocks(html_text)
    blocks, pos = [], 0
    for m in _BQ_BLOCK_RE.finditer(html_text):
        blocks += _plain_blocks(html_text[pos:m.start()])
        blocks += _quote_blocks(m.group(2), "expandable" in m.group(1).lower())
        pos = m.end()
    return blocks + _plain_blocks(html_text[pos:])

def _player_text_blocks(html_text: str) -> list:
    """1st <blockquote> -> heading, the other ones -> one collapsible block."""
    html_text = html_text or ""
    parts = _BQ_BLOCK_RE.findall(html_text)
    if (len(parts) < 2 or not _QUOTE["ok"]
            or not hasattr(types, "InputRichBlockExpandableBlockQuotation")):
        return _paragraphs(html_text)
    title = _html.unescape(re.sub(r"<[^>]+>", "", parts[0][1])).strip()
    blocks = [_heading(title)] + _quote_blocks("\n".join(p[1] for p in parts[1:]), True)
    return blocks + _plain_blocks(_BQ_BLOCK_RE.sub("", html_text))

def _has_quote(blocks) -> bool:
    kinds = tuple(
        c for c in (getattr(types, "InputRichBlockBlockQuotation", None),
                    getattr(types, "InputRichBlockExpandableBlockQuotation", None)) if c
    )
    return bool(kinds) and any(isinstance(b, kinds) for b in blocks)

def _unquote(blocks) -> list:
    bq = getattr(types, "InputRichBlockBlockQuotation", None)
    out = []
    for b in blocks:
        if bq is not None and isinstance(b, bq):
            out += list(b.blocks)
        elif _has_quote([b]):
            out.append(types.InputRichBlockParagraph(text=b.text))
        else:
            out.append(b)
    return out


# Progress bar + random colors
def _fmt(sec) -> str:
    sec = int(max(sec or 0, 0))
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def progress_bar(played, duration, width: int = 12) -> str:
    """01:18  ●●○○○○○○○○○○  06:43"""
    ratio = min(max(played / duration, 0), 1) if duration else 0
    done = min(max(round(ratio * width), 0), width)
    return f"{_fmt(played)}  {'●' * done}{'○' * (width - done)}  {_fmt(duration)}"

def _rand_styles(n: int) -> list:
    for _ in range(10):
        styles = [random.choice(_COLORS) for _ in range(n)]
        if len(set(styles)) > 1:
            break
    return styles

def _btn(text, style, data=None, url=None):
    kw = {"text": text, "style": style}
    if url:
        kw["url"] = url
    else:
        kw["callback_data"] = data
    return types.RichMessageButton(**kw)


# Player blocks
async def _blocks(chat_id, st, *, status=None, remove=False):
    from opus.plugins.autoplay import is_autoplay

    blocks = []
    if st.get("photo"):
        blocks.append(types.InputRichBlockPhoto(photo=types.InputMediaPhoto(st["photo"])))
    blocks += _player_text_blocks(st["caption"])
    if st.get("note"):
        blocks += _paragraphs(st["note"])

    c = _rand_styles(8)
    duration = st.get("duration") or 0
    top = status or (progress_bar(st.get("played", 0), duration) if duration else None)
    if top:  # row 1: progress bar
        blocks.append(
            types.InputRichBlockButtons(
                buttons=[_btn(top, c[0], f"controls status {chat_id}")]
            )
        )
    foot = [types.InputRichBlockParagraph(
        text=["Made By ", types.RichTextUrl(text=CREDIT_TEXT, url=CREDIT_URL)])]
    if remove:
        return blocks + foot

    ap_on = await is_autoplay(chat_id)
    ap_text = "ᴀᴜᴛᴏᴘʟᴀʏ: ᴏɴ ✅" if ap_on else "ᴀᴜᴛᴏᴘʟᴀʏ: ᴏꜰꜰ ❌"
    row2 = (("▷", "resume"), ("II", "pause"), ("⥁", "replay"), ("‣‣I", "skip"), ("▢", "stop"))
    blocks += [
        types.InputRichBlockButtons(
            buttons=[
                _btn(label, c[1 + i], f"controls {act} {chat_id}")
                for i, (label, act) in enumerate(row2)
            ]
        ),
        types.InputRichBlockButtons(
            buttons=[_btn(ap_text, c[6], f"controls autoplay {chat_id}")]
        ),
        types.InputRichBlockButtons(
            buttons=[_btn("ᴅᴇʟᴇᴛᴇ 🗑", c[7], f"controls delete {chat_id}")]
        ),
    ]
    return blocks + foot

async def _with_quote_retry(call, *args):
    """Run an edit/send; if quote blocks are rejected, retry once as plain text."""
    blocks = args[-1]
    try:
        return await call(*args)
    except _QUOTE_ERRORS as e:
        if isinstance(e, errors.MessageNotModified) or not _has_quote(blocks):
            raise
        res = await call(*args[:-1], _unquote(blocks))  # still failing -> not the quotes
        _QUOTE["ok"] = False
        logger.warning("[Rich] quote blocks rejected (%r) - switched to plain text", e)
        return res

async def _edit(message, blocks):
    return await _with_quote_retry(_edit_core, message, blocks)

async def _send(chat_id, blocks):
    return await _with_quote_retry(_send_core, chat_id, blocks)

def _strip_photo(blocks):
    return [b for b in blocks if not isinstance(b, types.InputRichBlockPhoto)]


# Send / edit
async def _edit_core(message, blocks):
    try:
        return await message.edit_text(rich_message=types.InputRichMessage(blocks=blocks))
    except _FORBIDDEN:
        plain = _strip_photo(blocks)
        if len(plain) == len(blocks):
            raise
        return await message.edit_text(rich_message=types.InputRichMessage(blocks=plain))

async def _send_core(chat_id, blocks):
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

async def send_player(chat_id, message, photo, caption_html, lang, duration=0):
    """Turn `message` (placeholder) into the rich player. Returns the Message
    that now holds the player, or None if rich is unavailable / failed."""
    if not RICH_OK:
        return None
    st = {"photo": photo, "caption": caption_html, "note": None, "msg": message,
          "lang": lang, "last": 0.0, "played": 0, "duration": duration}
    try:
        blocks = await _blocks(chat_id, st)
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
                 played=None, duration=None, remove=False, min_gap=0):
    """Re-render the rich player (new progress, new random colors).
    True = handled, False = caller should use the old inline-keyboard path."""
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
    if played is not None:
        st["played"] = played
    if duration:
        st["duration"] = duration
    try:
        await _edit(msg, await _blocks(chat_id, st, status=status, remove=remove))
    except errors.MessageNotModified:
        pass
    except Exception as e:
        logger.warning("[Rich] update failed in %s: %r", chat_id, e)
        return False
    st["last"] = time.monotonic()
    return True

def clear(chat_id):
    _np.pop(chat_id, None)


# Rich menus (/start + its sub-menus), converted from InlineKeyboardMarkup
def _markup_blocks(markup, group: bool = False) -> list:
    rows = []
    for row in getattr(markup, "inline_keyboard", None) or []:
        btns = []
        for b in row:
            style = getattr(b, "style", None) or random.choice(_COLORS)
            if getattr(b, "url", None):
                btns.append(_btn(b.text, style, url=b.url))
            elif getattr(b, "callback_data", None):
                data = b.callback_data
                data = data.decode() if isinstance(data, bytes) else data
                uname = getattr(app, "username", None)
                if data == "help" and uname:
                    btns.append(_btn(b.text, style, url=f"https://t.me/{uname}?start=help"))
                else:
                    btns.append(_btn(b.text, style, data=data))
        if btns:
            rows.append(types.InputRichBlockButtons(buttons=btns))
    return rows

def _menu_blocks(st, markup) -> list:
    blocks = []
    if st.get("video") and hasattr(types, "InputRichBlockVideo"):
        blocks.append(types.InputRichBlockVideo(video=types.InputMediaVideo(st["video"])))
    elif st.get("photo"):
        blocks.append(types.InputRichBlockPhoto(photo=types.InputMediaPhoto(st["photo"])))
    blocks += _paragraphs(st["caption"])
    return blocks + _markup_blocks(markup, st.get("group", False))

async def send_menu(chat_id, photo, caption_html, markup, video=None, flag=None):
    """Send a rich menu (video/photo + text + buttons). None -> use classic."""
    if not (RICH_OK and (START_ENABLED if flag is None else flag)):
        return None
    st = {"photo": photo, "video": video, "caption": caption_html,
          "group": chat_id < 0}
    sent = None
    for use_video in ((True, False) if video else (False,)):
        if not use_video:
            st["video"] = None
        try:
            sent = await _send(chat_id, _menu_blocks(st, markup))
            break
        except Exception as e:
            logger.warning("[Rich] send_menu (%s) failed in %s: %r",
                           "video" if use_video else "photo", chat_id, e)
    if sent is None:
        return None
    if len(_menus) > 500:
        _menus.pop(next(iter(_menus)))
    st["msg"] = sent
    _menus[(chat_id, sent.id)] = st
    return sent

def _heading(text: str, size: int = 2):
    """Big title line (<h2>-style). Falls back to a bold paragraph."""
    cls = getattr(types, "InputRichBlockSectionHeading", None)
    if cls is not None:
        return cls(text=text, size=size)
    return types.InputRichBlockParagraph(text=types.RichTextBold(text=text))

def _as_list(x):
    return x if isinstance(x, list) else [x]

def _short(text, n=42) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"

def _queue_list_blocks(items) -> list:
    """"In queue: N" line + collapsible "Up next" list (items[0] is playing)."""
    waiting = list(items or [])[1:]
    if not waiting:
        return []
    shown = waiting[:15]
    lines = ["<b>Up next</b>"] + [
        f"{i}. {_html.escape(_short(it.title))} · {_html.escape(str(it.duration))}"
        for i, it in enumerate(shown, start=1)
    ]
    if len(waiting) > len(shown):
        lines.append(f"+{len(waiting) - len(shown)} more")
    head = types.InputRichBlockParagraph(
        text=["• In queue: ", types.RichTextBold(text=f"{len(waiting)} track"
                                                  + ("s" if len(waiting) != 1 else ""))]
    )
    return [head] + _paragraphs("<blockquote expandable>" + "\n".join(lines) + "</blockquote>")

async def send_queued(message, chat_id, position, file, user_html, lang, items=None):
    """Rich "Added to Queue" message. None -> caller sends the classic one."""
    if not (RICH_OK and QUEUE_ENABLED):
        return None
    try:
        bold = types.RichTextBold
        title = types.RichTextUrl(text=file.title, url=file.url) if file.url else file.title
        blocks = [
            _heading("Added to Queue"),
            types.InputRichBlockParagraph(text=["• Track: ", title]),
            types.InputRichBlockParagraph(
                text=["• Position: ", bold(text=str(position)),
                      "  |  Duration: ", bold(text=str(file.duration))]
            ),
            types.InputRichBlockParagraph(
                text=["• Requested by: "] + _as_list(_inline(user_html))
            ),
            *_queue_list_blocks(items),
            types.InputRichBlockButtons(
                buttons=[
                    _btn(lang.get("play_now", "Play Now"), S.SUCCESS,
                         f"controls force {chat_id} {file.id}"),
                    _btn(lang.get("close", "Close"), S.DANGER,
                         f"controls close {chat_id}"),
                ]
            ),
        ]
        try:
            return await _edit(message, blocks) or message
        except errors.MessageNotModified:
            return message
        except Exception:
            try:
                await message.delete()
            except Exception:
                pass
            return await _send(chat_id, blocks)
    except Exception as e:
        logger.warning("[Rich] send_queued failed in %s: %r - falling back", chat_id, e,
                       exc_info=True)
        return None

async def finish_menu(chat_id, message_id, caption_html) -> bool:
    """Replace a rich menu with plain text (no photo, no buttons).
    False = not a rich menu, use the normal edit."""
    st = _menus.get((chat_id, message_id))
    if not st:
        return False
    st.update(caption=caption_html, photo=None, video=None)
    try:
        await _edit(st["msg"], _menu_blocks(st, None))
    except errors.MessageNotModified:
        pass
    except Exception as e:
        logger.warning("[Rich] finish_menu failed: %r", e)
        return False
    return True

async def edit_menu(query, markup, caption_html=None) -> bool:
    """Swap buttons (and optionally the text) of a rich menu from a callback.
    False = this message isn't a rich menu, use the normal edit."""
    key = (query.message.chat.id, query.message.id)
    st = _menus.get(key)
    if not st:
        return False
    if caption_html is not None:
        st["caption"] = caption_html
    try:
        await _edit(query.message, _menu_blocks(st, markup))
    except errors.MessageNotModified:
        pass
    except Exception as e:
        logger.warning("[Rich] edit_menu failed: %r", e)
        return False
    return True
