#!/usr/bin/env python3
import argparse
import json
import logging
import os
import shutil
from collections import defaultdict
from functools import partial
from multiprocessing.pool import ThreadPool
from os.path import join

from translatepy.translators.yandex import YandexTranslate

from common import (
    Font,
    combine_desc_and_note,
    iterate_over_dict,
    collapse,
    except_gab_text,
    fix_name,
    FMT_REGEX,
    ASCII_REGEX,
    replace_escapes,
    translate_category,
)
from settings import TRANSLATE_CACHE_FILENAME


class GameTranslator:

    def __init__(self, src_game_dir: str, dst_game_dir: str, line_limit: int):
        self.src_game_dir = src_game_dir
        self.dst_game_dir = dst_game_dir
        self.to_path = join(dst_game_dir, 'www/data')
        self.translate_map = {}
        self.translate_map_counter = defaultdict(int)
        self.translator = YandexTranslate()
        self.line_limit = line_limit
        self.bad_formatting = {}
        self.bad_translate = {}
        self.font = Font(
            join(src_game_dir, 'www/fonts/Garamond-Premier-Pro_19595.ttf'))
        self.overspaces = {}

    def run(self):
        filenames = self.fetch_dir()
        filenames = self.sort_files(filenames)
        for n, filename in enumerate(filenames, start=1):
            print(f'{n}/{len(filenames)} {filename} .. ')
            self.process_single_file(filename)

    def fetch_dir(self) -> list[str]:
        return [
            filename
            for filename in os.listdir(self.to_path)
            if os.path.splitext(filename)[1].lower() == '.json'
        ]

    @staticmethod
    def sort_files(filenames: list[str]) -> list[str]:
        up = []
        middle = []
        down = []
        for fn in filenames:
            if fn.startswith('Map'):
                down.append(fn)
            elif fn.startswith('CommonEvents'):
                middle.append(fn)
            else:
                up.append(fn)

        up.sort()
        middle.sort()
        down.sort()
        return up + middle + down

    def process_single_file(self, filename: str):
        from_path = os.path.join(self.to_path, filename)
        data = json.loads(open(from_path).read())
        with ThreadPool(10) as pool:
            pool.map(
                partial(self.task, filename),
                collapse(iterate_over_dict(data)),
            )
        for obj in iterate_over_dict(data):
            self.wrap_lines(obj)
        self.save_single_file(filename, data)

    def wrap_lines(self, obj: dict):
        items = obj.get('list')
        if not items:
            return
        new_items = []
        for item in items:
            if (
                    item.get('code') == 401 and
                    item['parameters'] and
                    item['parameters'][0]
            ):
                parts = self.font.split_text(
                    item['parameters'][0],
                    self.line_limit,
                    4,
                )
                for part in parts:
                    new_item = item.copy()
                    new_item['parameters'] = [part]
                    new_items.append(new_item)
            else:
                new_items.append(item)
        obj['list'] = new_items

    def save_single_file(self, filename: str, data: dict):
        to_path = os.path.join(self.to_path, filename)
        with open(to_path, 'w') as f:
            f.write(json.dumps(data, ensure_ascii=False))

    def task(self, filename: str, obj: dict):
        match filename:
            case (
                'Items.json' |
                'Actors.json' |
                'Weapons.json' |
                'Enemies.json' |
                'Armors.json' |
                'Skills.json'
            ):
                if 'name' in obj:
                    obj['name'] = self.translate(obj['name'])
                if 'description' in obj and obj['description'].strip():
                    combine_desc_and_note(obj)
                    obj['description'] = self.split_and_translate_text(
                        obj['description'],
                        3,
                    )
                translate_category(obj)
            case 'Classes.json':
                if 'name' in obj:
                    obj['name'] = self.translate(obj['name'])
                if 'description' in obj:
                    obj['description'] = self.split_and_translate_text(
                        obj['description'],
                        3,
                    )
                if 'note' in obj:
                    obj['note'] = self.mark_translate(obj['note'])
            case 'System.json':
                if 'gameTitle' in obj:
                    obj['gameTitle'] = self.mark_translate(obj['gameTitle'])
                if 'equipTypes' in obj:
                    obj['equipTypes'] = [self.mark_translate(item) for item in obj['equipTypes']]
                if 'skillTypes' in obj:
                    obj['skillTypes'] = [self.mark_translate(item) for item in obj['skillTypes']]
                if 'terms' in obj:
                    if 'params' in obj['terms']:
                        obj['terms']['params'] = [
                            self.mark_translate(item)
                            for item in obj['terms']['params']
                        ]
                    if 'messages' in obj['terms']:
                        obj['terms']['messages'] = {
                            k: self.mark_translate(v)
                            for k, v in obj['terms']['messages'].items()
                        }
                    if 'basic' in obj['terms']:
                        obj['terms']['basic'] = [
                            self.mark_translate(item)
                            for item in obj['terms']['basic']
                        ]
                    if 'commands' in obj['terms']:
                        obj['terms']['commands'] = [
                            self.mark_translate(item)
                            for item in obj['terms']['commands']
                        ]

        if 'displayName' in obj:
            obj['displayName'] = self.translate(obj['displayName'])

        match obj.get('code'):
            case 102:
                obj['parameters'][0] = [
                    self.translate(parameter)
                    for parameter in obj['parameters'][0]
                ]
            case 356:
                obj['parameters'][0] = except_gab_text(self.split_and_translate_text)(
                    obj['parameters'][0],
                    1,
                )
            case 401:
                assert len(obj['parameters']) == 1
                obj['parameters'] = [
                    self.split_and_translate_text(obj['parameters'][0], 4)
                ]
            case 320:
                assert len(obj['parameters']) == 2
                obj['parameters'][1] = self.translate(obj['parameters'][1])
            case 324 | 402:
                obj['parameters'][1] = self.split_and_translate_text(
                    obj['parameters'][1],
                    1,
                )

    def translate(self, text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            return text

        orig_text = text

        self.translate_map_counter[orig_text] += 1

        if orig_text in self.translate_map:
            translated = self.translate_map[orig_text]
        else:
            text = fix_name(text)
            translated = replace_escapes(self.call_translator)(text)

        self.translate_map[orig_text] = translated

        self.check_bad_translate(orig_text, translated)
        self.check_format_after_translate(orig_text, translated)

        if orig_text != translated:
            logging.info('%s > %s', orig_text, translated)
        return translated

    def mark_translate(self, text) -> str:
        if not isinstance(text, str) or not text.strip():
            return text

        self.translate_map_counter[text] += 1

        if text in self.translate_map:
            return self.translate_map[text]
        self.translate_map[text] = text
        return text

    def call_translator(self, text: str) -> str:
        return self.translator.translate(
            text,
            source_language='en',
            destination_language='ru',
        ).result

    def split_and_translate_text(
            self,
            text: str,
            count_lines: int,
    ) -> str:
        translated = self.translate(text)
        parts = self.font.split_text(translated, self.line_limit, count_lines)
        result = '\n'.join(parts)
        if len(parts) > count_lines:
            self.overspaces[text] = count_lines, len(parts), result
        return result

    def check_format_after_translate(self, text: str, translated: str):
        a = FMT_REGEX.findall(text)
        b = FMT_REGEX.findall(translated)
        if a != b:
            self.bad_formatting[text] = translated

    def check_bad_translate(self, text: str, translated: str):
        orig_translated = translated
        for fmt in reversed(list(FMT_REGEX.finditer(translated))):
            start, stop = fmt.span(1)
            translated = translated[:start] + translated[stop:]
        m = ASCII_REGEX.search(translated)
        if m:
            self.bad_translate[text] = orig_translated

    def copy_to_game_dir(self):
        if self.src_game_dir != self.dst_game_dir:
            shutil.copytree(
                self.src_game_dir, self.dst_game_dir, dirs_exist_ok=True)

    def load_translate_cache(self):
        if os.path.exists(TRANSLATE_CACHE_FILENAME):
            print('load translate cache from', TRANSLATE_CACHE_FILENAME)
            with open(TRANSLATE_CACHE_FILENAME, 'r') as f:
                self.translate_map = json.load(f)

    def resort_translate_cache(self):
        new_map = {}
        for k in self.translate_map_counter.keys():
            new_map[k] = self.translate_map[k]
        self.translate_map = new_map

    def save_translate_cache(self):
        print('save translate cache to', TRANSLATE_CACHE_FILENAME)
        with open(TRANSLATE_CACHE_FILENAME, 'w') as f:
            json.dump(self.translate_map, f, ensure_ascii=False, indent=2)

    def clean_bad_cache(self):
        was_deleted = {}
        for key in set(self.translate_map) - set(self.translate_map_counter):
            was_deleted[key] = self.translate_map[key]
            del self.translate_map[key]
        if was_deleted:
            print('bad cache:')
            for k, v in was_deleted.items():
                print(repr(k), '>', repr(v))

    def print_bad_format(self):
        if not self.bad_formatting:
            return
        print('=== Bad formatting strings:')
        for text, translated in self.bad_formatting.items():
            print(
                json.dumps(text, ensure_ascii=False),
                '>',
                json.dumps(translated, ensure_ascii=False),
            )
        print()
        print()

    def print_overspaces(self):
        if not self.overspaces:
            return
        print()
        print('=== Over space strings ===')
        print()
        for text, (need_ln, ln, translated) in self.overspaces.items():
            print(
                f'[{need_ln}]',
                json.dumps(text, ensure_ascii=False),
            )
            print(
                f'[{ln}]',
                json.dumps(translated, ensure_ascii=False),
            )
            print()
        print()
        print()

    def print_bad_translate(self):
        if not self.bad_translate:
            return
        print('=== Bad translate strings:')
        for text, translated in self.bad_translate.items():
            print(
                json.dumps(text, ensure_ascii=False),
                '>',
                json.dumps(translated, ensure_ascii=False),
            )
        print()
        print()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--game-dir',
        help='location of game directory',
        required=True,
    )
    parser.add_argument(
        '--line-limit',
        help='the number of characters in the line after which'
             ' the sentence will be wrapped to a new line',
        type=int,
        required=True,
    )
    parser.add_argument(
        '--resort-cache',
        action='store_true',
    )
    parser.add_argument(
        '--print-bad-format',
        action='store_true',
    )
    parser.add_argument(
        '--print-overspaces',
        action='store_true',
    )
    parser.add_argument(
        '--print-bad-translate',
        action='store_true',
    )
    parser.add_argument(
        '--log',
        action='store_true',
    )
    args = parser.parse_args()
    try:
        if args.log:
            logging.basicConfig(
                filename='log.txt',
                format='%(message)s',
                level=logging.ERROR,
            )
        logging.info('start')
        app = GameTranslator(
            'src_game',
            args.game_dir,
            args.line_limit,
        )
        app.copy_to_game_dir()
        app.load_translate_cache()
    except KeyboardInterrupt:
        pass
    else:
        try:
            app.run()
        except KeyboardInterrupt:
            pass
        else:
            app.clean_bad_cache()
        if args.resort_cache:
            app.resort_translate_cache()
        app.save_translate_cache()
        if args.print_bad_format:
            app.print_bad_format()
        if args.print_overspaces:
            app.print_overspaces()
        if args.print_bad_translate:
            app.print_bad_translate()
