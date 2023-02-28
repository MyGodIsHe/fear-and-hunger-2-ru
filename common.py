import re
from collections import defaultdict
from typing import Iterator
import io
import json
import os

from fontTools.ttLib import TTFont
from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload
from settings import *


FMT_REGEX = re.compile(r'\s*(\\.(?:\[[^\]]+\])?)\s*')
REPLACE_REGEX = re.compile(r'\s*\\\s*k\s*\[\s*\d+\s*\]\s*')
NAME_REGEX = re.compile(r'\\>\\i\[(\d+)\]\\\}([^\\]+)\\\{\\<')
ASCII_REGEX = re.compile(r'[A-Za-z]')
MENU_CATEGORY_REGEX = re.compile(r'<Menu Category:([^>]+)>')
COMMENT_REGEX = re.compile(r'\[[a-z]+\]')


def iterate_over_dict(data: dict | list) -> Iterator[dict]:
    match data:
        case dict():
            yield data
            for v in data.values():
                yield from iterate_over_dict(v)
        case list():
            for v in data:
                yield from iterate_over_dict(v)
        case _:
            return


def collapse(data: Iterator[dict]) -> Iterator[dict]:
    for obj in data:
        items = obj.get('list')
        if not items:
            yield obj
            continue
        new_items = []
        sentence = []
        first_obj = {}
        for item in items:
            code = item.get('code')
            if first_obj:
                if code == 401:
                    sentence.append(item['parameters'][0])
                else:
                    first_obj['parameters'][0] = '\n'.join(sentence)
                    new_items.append(first_obj)
                    sentence = []
                    first_obj = {}
                    new_items.append(item)
                continue
            if code == 401:
                first_obj = item
                sentence = [item['parameters'][0]]
                continue
            new_items.append(item)
        obj['list'] = new_items
        yield obj


def except_gab_text(f):
    def wrap(text: str, *args, **kwargs) -> str:
        if text.startswith('GabText '):
            return text[:8] + f(text[8:], *args, **kwargs)
        if text.startswith('choice_text '):
            i = text.find(' ', 12)
            if i != -1:
                i += 1
            return text[:i] + f(text[i:], *args, **kwargs)
        return text

    return wrap


def fix_name(text: str) -> str:
    m = NAME_REGEX.search(text)
    if not m:
        return text
    code = int(m.group(1))
    if code == 144:
        code = 80  # P
    elif code == 81:
        code = 83  # S
    elif code == 80:
        code = 82  # R
    else:
        code += 1
    full_name = chr(code) + m.group(2)
    value = text.replace(
        m.group(0),
        f'\\>\\}}{full_name}\\{{\\<',  # \\i[{m.group(1)}] - remove
    )
    return value


def replace_escapes(f):
    """for better formatting in yandex translater"""
    def wrapper(text: str) -> str:
        fmt_groups = list(FMT_REGEX.finditer(text))
        for n, fmt in reversed(list(enumerate(fmt_groups, start=1))):
            start, stop = fmt.span(1)
            text = text[:start] + f'\\k[{n}]' + text[stop:]

        translated = f(text)

        ts_groups = REPLACE_REGEX.finditer(translated)
        for fmt, ts in reversed(list(zip(fmt_groups, ts_groups))):
            translated = replace_last(translated, ts.group(), fmt.group())
        return translated

    return wrapper


def replace_last(source_string, replace_what, replace_with):
    head, _sep, tail = source_string.rpartition(replace_what)
    return head + replace_with + tail


def combine_desc_and_note(obj: dict):
    note = obj.get('note')
    if not note:
        return
    i = note.find('\n\n')
    if i != -1:
        obj['description'] = (
                obj['description'].rstrip() + ' ' + note[:i].lstrip()
        )
        obj['note'] = note[i:]


def translate_category(obj: dict):
    note = obj.get('note')
    if not note:
        return
    m = MENU_CATEGORY_REGEX.search(note)
    if not m:
        return
    value = m.group(1).strip()
    match value:
        case 'Items':
            value = 'Предметы'
        case 'Healing':
            value = 'Исцеление'
        case 'Food':
            value = 'Еда'
        case 'Body bag':
            value = 'Мешок для трупов'
    start, end = m.span(1)
    obj['note'] = note[:start] + ' ' + value + note[end:]


class Font:
    def __init__(self, font_path: str):
        font = TTFont(font_path)
        cmap = font['cmap']
        self.t = cmap.getcmap(3, 1).cmap
        self.s = font.getGlyphSet()
        self.units_per_em = font['head'].unitsPerEm

    def get_width(self, text: str) -> float:
        total = 0
        for c in text:
            if ord(c) in self.t and self.t[ord(c)] in self.s:
                total += self.s[self.t[ord(c)]].width
            else:
                total += self.s['.notdef'].width
        total = total * 10.0 / self.units_per_em
        return total

    def split_text(
            self,
            text: str,
            line_limit: int,
            count_lines: int,
    ) -> list[str]:
        lines = text.split('\n')
        fail = False
        for line in lines:
            if self.len_visible_chars(line) > line_limit:
                fail = True
                break
        if not fail:
            return lines
        if lines[0].startswith('\\>'):
            text = ' '.join(lines[1:])
            if self.len_visible_chars(text) <= (count_lines - 1) * line_limit:
                return self.split_text_by_world(text, line_limit)
        text = ' '.join(lines)
        return self.split_text_by_world(text, line_limit)

    def split_text_by_world(self, text: str, limit: int) -> list[str]:
        lines = []
        words = []
        space_w = self.get_width(' ')
        cnt = -space_w
        for w in text.split():
            len_w = self.len_visible_chars(w)
            cnt += space_w + len_w
            if cnt > limit:
                lines.append(' '.join(words))
                words = []
                cnt = len_w
            words.append(w)
        if words:
            lines.append(' '.join(words))
        return lines

    def len_visible_chars(self, text: str) -> float:
        clean_text = ''
        of = 0
        for m in FMT_REGEX.finditer(text):
            to, next_of = m.span(1)
            clean_text += text[of:to]
            of = next_of
        clean_text += text[of:len(text)]
        return self.get_width(clean_text)


def get_authenticated_service():
    google_service_account = os.environ.get('GOOGLE_SERVICE_ACCOUNT')
    if google_service_account:
        credentials = service_account.Credentials.from_service_account_info(
            json.loads(google_service_account), scopes=SCOPES)
    else:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build(API_SERVICE_NAME, API_VERSION, credentials=credentials)


def get_parts(service):
    for file_id in DOC_IDS:
        blocks = get_file(service, file_id).split('\r\n\r\n\r\n')
        blocks = [
            pair.replace('\uFEFF', '').strip('\r\n')
            for pair in blocks
        ]
        comments = blocks[-1]
        if comments.startswith('[a]'):
            blocks = blocks[:-1]
            comments = [
                COMMENT_REGEX.search(c).group(0)
                for c in comments.split('\r\n')
            ]
            counts = defaultdict(int)
            for block in blocks:
                for c in comments:
                    before = len(block)
                    block = block.replace(c, '')
                    after = len(block)
                    cnt = (before - after) / len(c)
                    if cnt:
                        counts[c] += cnt
            for k, v in counts.items():
                assert v == 1, (k, v)
        for pair in blocks:
            pair = pair.split('\r\n')
            assert len(pair) == 2, pair
            yield pair


def get_file(service, file_id: str) -> str:
    request = service.files().export_media(
        fileId=file_id, mimeType='text/plain')
    file = io.BytesIO()
    downloader = MediaIoBaseDownload(file, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    return file.getvalue().decode('utf-8')


def upload_file(service, file_id: str, body: str):
    m = MediaInMemoryUpload(body.encode('utf-8'), 'text/plain')
    service.files().update(
        fileId=file_id,
        media_body=m,
        media_mime_type='text/plain',
    ).execute()


