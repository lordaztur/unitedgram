import html
import re

from config import settings

__all__ = ["format_telegram_message", "build_bbcode_payload"]

_RE_NEW = re.compile(
    r'\[quote=@?(?P<to>[^\]]+)\](?P<quoted>.*?)\[/quote\](?:\s*(?P<reply>.*))?',
    re.DOTALL | re.IGNORECASE,
)
_RE_BB_QUOTE = re.compile(
    r'\[b\]\[url=[^\]]+\](?P<to>[^\[]+)\[/url\]\s*:\s*\[/b\]\[color=[^\]]+\]\s*'
    r'["“”]?\[i\](?P<quoted>.*?)\[/i\]["“”]?\s*\[/color\](?:\s*(?P<reply>.*))?',
    re.DOTALL | re.IGNORECASE,
)
_RE_RAW = re.compile(
    r'^[“" ]*(?:Quoting|Citando)\s*@?(?P<to>[^:]+):\s*(.*)',
    re.DOTALL | re.IGNORECASE,
)
_RE_OLD = re.compile(
    r'^\s*@?(?P<to>[A-Za-z0-9_.-]+)\s*:\s*[“"](?P<quoted>.*?)[”"]\s*\n+(?P<reply>.*)$',
    re.DOTALL,
)
_RE_BLANKLINE = re.compile(r'\n{2,}')


def format_telegram_message(bridge, msg_data: dict) -> str:
    from bridge import clean_html

    user = msg_data.get("user") or {}
    username = user.get("username") or user.get("name") or "Desconhecido"

    username_clean = username.lower().lstrip("@")
    is_me = username_clean in bridge.aliases

    display_name = html.escape("Você" if is_me else username)

    raw_text = clean_html(msg_data.get("message") or "")

    if not raw_text.strip(): return f"💬 <b>{display_name}</b> enviou:"

    to_user = None
    quoted = ""
    reply_txt = ""

    m_new = _RE_NEW.search(raw_text)
    m_bb_quote = _RE_BB_QUOTE.search(raw_text)

    if m_new:
        to_user = m_new.group("to")
        quoted = m_new.group("quoted")
        reply_txt = m_new.group("reply")
    elif m_bb_quote:
        to_user = m_bb_quote.group("to")
        quoted = m_bb_quote.group("quoted")
        reply_txt = m_bb_quote.group("reply")
    else:
        m_raw = _RE_RAW.match(raw_text)
        if m_raw:
            to_user = m_raw.group("to")
            rest = m_raw.group(2).strip()

            if '\n\n' in rest:
                parts = _RE_BLANKLINE.split(rest, maxsplit=1)
                quoted = parts[0]
                reply_txt = parts[1]
            else:
                quoted = rest
                reply_txt = ""
        else:
            m_old = _RE_OLD.match(raw_text)
            if m_old:
                to_user = m_old.group("to")
                quoted = m_old.group("quoted")
                reply_txt = m_old.group("reply")

    def tag_aliases(text):
        if not text or not bridge.aliases or not settings.telegram_user or not settings.tag_aliases:
            return text
        escaped_aliases = [re.escape(a) for a in bridge.aliases]
        pattern = r'(?<!\w)@?(' + '|'.join(escaped_aliases) + r')(?!\w)'
        return re.sub(pattern, rf"\g<0> [@{settings.telegram_user}]", text, flags=re.IGNORECASE)

    if to_user is not None:
        to_user = to_user.strip()
        clean_to_user = to_user.lstrip("@")

        if clean_to_user.lower() in bridge.aliases and settings.tag_aliases and settings.telegram_user:
            to_user_disp = f"@{settings.telegram_user}"
        else:
            to_user_disp = html.escape(to_user)

        quoted_format = html.escape(tag_aliases(quoted or "").strip())
        reply_format = html.escape(tag_aliases(reply_txt or "").strip())

        if reply_format:
            return f"💬 <b>{display_name}</b> respondeu a <b>{to_user_disp}</b>:\n<blockquote>{quoted_format}</blockquote>\n{reply_format}"
        else:
            return f"💬 <b>{display_name}</b> citou <b>{to_user_disp}</b>:\n<blockquote>{quoted_format}</blockquote>"

    return f"💬 <b>{display_name}</b>: {html.escape(tag_aliases(raw_text))}"


def build_bbcode_payload(original_data: dict, reply_text: str) -> str:
    to_user = original_data.get("handle", "").lstrip("@")
    quoted_text = original_data.get("text", "")
    if len(quoted_text) > 240: quoted_text = quoted_text[:240].rstrip() + "..."

    for c, r in [("[", "［"), ("]", "］")]:
        to_user = to_user.replace(c, r)
        quoted_text = quoted_text.replace(c, r)

    return f'[quote={to_user}]{quoted_text}[/quote]\n{reply_text}'
