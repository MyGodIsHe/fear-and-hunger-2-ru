import re
from typing import Iterator
import io
import json
import os

from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload
from settings import *


FMT_REGEX = re.compile(r'\s*(\\.(?:\[[^\]]+\])?)\s*')
REPLACE_REGEX = re.compile(r'\s*\\\s*k\s*\[\s*\d+\s*\]\s*')
NAME_REGEX = re.compile(r'\\>\\i\[(\d+)\]\\\}([^\\]+)\\\{\\<')
ASCII_REGEX = re.compile(r'[A-Za-z]')
MENU_CATEGORY_REGEX = re.compile(r'<Menu Category:([^>]+)>')


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


def split_text(text: str, line_limit: int, count_lines: int) -> list[str]:
    lines = text.split('\n')
    fail = False
    for line in lines:
        if len_visible_chars(line) > line_limit:
            fail = True
            break
    if not fail:
        return lines
    if lines[0].startswith('\\>\\i'):
        text = ' '.join(lines[1:])
        if len_visible_chars(text) <= (count_lines - 1) * line_limit:
            return split_text_by_world(text, line_limit)
    text = ' '.join(lines)
    if len_visible_chars(text) > count_lines * line_limit:
        return split_text_by_char(text, line_limit)
    return split_text_by_world(text, line_limit)


def split_text_by_world(text: str, limit: int) -> list[str]:
    lines = []
    words = []
    cnt = -1
    for w in text.split():
        cnt += 1 + len_visible_chars(w)
        if cnt > limit:
            lines.append(' '.join(words))
            words = []
            cnt = len(w)
        words.append(w)
    if words:
        lines.append(' '.join(words))
    return lines


def split_text_by_char(text: str, limit: int) -> list[str]:
    # TODO: не разбивать спец-символы
    return [
        text[i:i + limit]
        for i in range(0, len(text), limit)
    ]


def except_gab_text(f):
    def wrap(text: str) -> str:
        if text.startswith('GabText '):
            return text[:8] + f(text[8:])
        if text.startswith('choice_text '):
            i = text.find(' ', 12)
            if i != -1:
                i += 1
            return text[:i] + f(text[i:])
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
        f'\\>\\i[{m.group(1)}]\\}}{full_name}\\{{\\<',
    )
    return value


def len_visible_chars(text: str) -> int:
    ln = len(text)
    for m in FMT_REGEX.finditer(text):
        a, b = m.span(1)
        ln -= b - a
    return ln


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
        for pair in get_file(service, file_id).split('\r\n\r\n\r\n'):
            pair = pair.replace('\uFEFF', '')
            yield pair.strip('\r\n').split('\r\n')


def get_file(service, file_id: str) -> str:
    request = service.files().export_media(
        fileId=file_id, mimeType='text/plain')
    file = io.BytesIO()
    downloader = MediaIoBaseDownload(file, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    return file.getvalue().decode('utf-8')


def get_revisions(service, file_id: str):
    request = service.revisions().list(fileId=file_id)
    print(request.execute())


def upload_file(service, file_id: str, body: str):
    m = MediaInMemoryUpload(body.encode('utf-8'), 'text/plain')
    service.files().update(
        fileId=file_id,
        media_body=m,
        media_mime_type='text/plain',
    ).execute()


