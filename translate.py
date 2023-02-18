#!/usr/bin/env python3
"""
pip install translatepy
"""
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
    iterate_over_dict,
    collapse,
    split_text,
    except_gab_text,
    fix_name,
    FMT_REGEX,
    ASCII_REGEX,
    replace_escapes,
)

logging.basicConfig(
    filename='log.txt',
    format='%(message)s',
    level=logging.INFO,
)
TRANSLATE_CACHE_FILENAME = 'translate_cache.json'


class GameTranslator:

    def __init__(self, from_path: str, to_path: str, line_limit: int):
        self.from_path = from_path
        self.to_path = to_path
        self.translate_map = {}
        self.translate_map_counter = defaultdict(int)
        self.translator = YandexTranslate()
        self.line_limit = line_limit
        self.bad_formatting = {}
        self.bad_translate = {}

    def run(self):
        filenames = self.fetch_dir()
        for n, filename in enumerate(filenames, start=1):
            print(f'{n}/{len(filenames)} {filename} .. ')
            self.process_single_file(filename)

    def fetch_dir(self) -> list[str]:
        return [
            filename
            for filename in os.listdir(self.from_path)
            if os.path.splitext(filename)[1].lower() == '.json'
        ]

    def process_single_file(self, filename: str):
        from_path = os.path.join(self.from_path, filename)
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
                parts = split_text(
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
                if 'description' in obj:
                    obj['description'] = '\n'.join(
                        split_text(
                            self.translate(obj['description']),
                            self.line_limit,
                            3,
                        ),
                    )
            case 'System.json':
                if 'gameTitle' in obj:
                    obj['gameTitle'] = self.mark_translate(obj['gameTitle'])
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

        if 'displayName' in obj:
            obj['displayName'] = self.translate(obj['displayName'])

        match obj.get('code'):
            case 102:
                obj['parameters'][0] = [
                    self.translate(parameter)
                    for parameter in obj['parameters'][0]
                ]
            case 356:
                obj['parameters'][0] = except_gab_text(self.translate)(
                    obj['parameters'][0]
                )
            case 401:
                obj['parameters'] = [
                    self.translate(parameter)
                    for parameter in obj['parameters']
                ]
            case 324 | 402:
                obj['parameters'][1] = self.translate(
                    obj['parameters'][1]
                )

    def translate(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return text

        orig_text = text

        self.translate_map_counter[orig_text] += 1

        if orig_text in self.translate_map:
            translated = self.translate_map[orig_text]
        else:
            text = fix_name(text)
            translated = replace_escapes(self.call_translator)(text)

        translated = self.hard_translate(translated)
        self.translate_map[orig_text] = translated

        self.check_bad_translate(orig_text, translated)
        self.check_format_after_translate(orig_text, translated)

        if orig_text != translated:
            logging.info('%s > %s', orig_text, translated)
        return translated

    def mark_translate(self, text) -> str:
        if not text or not isinstance(text, str):
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

    @staticmethod
    def hard_translate(text: str) -> str:
        for world in [
            'All-mer',
            'All-Mer',
            'Alll-mer',
            'Alll-Mer',
            'Аллл-мер',
            'Аллл-Мер',
            'Алль-мер',
            'Алль-Мер',
            'Аллль-мер',
            'Аллль-Мер',
        ]:
            text = text.replace(world, 'Алл-мер')
        for world in ['Prehevil', 'prehevil']:
            text = text.replace(world, 'Прехвил')
        text = text.replace('POCKETCAT', 'Карманный Кот')
        text = text.replace('Pav', 'Пав')
        return text

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

    def create_backup(self):
        if not os.path.exists(self.from_path):
            print('creating backup .. ', end='')
            shutil.copytree(self.to_path, self.from_path)
            print('done')

    def load_translate_cache(self):
        if os.path.exists(TRANSLATE_CACHE_FILENAME):
            print('load translate cache from', TRANSLATE_CACHE_FILENAME)
            with open(TRANSLATE_CACHE_FILENAME, 'r') as f:
                self.translate_map = json.load(f)

    def save_translate_cache(self):
        print('save translate cache to', TRANSLATE_CACHE_FILENAME)
        with open(TRANSLATE_CACHE_FILENAME, 'w') as f:
            json.dump(self.translate_map, f, ensure_ascii=False, indent=2)

    def clean_bad_cache(self):
        for key in set(self.translate_map) - set(self.translate_map_counter):
            del self.translate_map[key]

    def print_bad_format(self):
        if not self.bad_formatting:
            return
        print('Bad formatting strings:')
        for text, translated in self.bad_formatting.items():
            print(
                json.dumps(text, ensure_ascii=False),
                '>',
                json.dumps(translated, ensure_ascii=False),
            )

    def print_bad_translate(self):
        if not self.bad_translate:
            return
        print('Bad translate strings:')
        for text, translated in self.bad_translate.items():
            print(
                json.dumps(text, ensure_ascii=False),
                '>',
                json.dumps(translated, ensure_ascii=False),
            )


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
        '--skip-backup',
        action='store_false',
    )
    args = parser.parse_args()
    try:
        logging.info('start')
        to_path = join(args.game_dir, 'www/data')
        if args.skip_backup:
            from_path = join(args.game_dir, 'www/data-backup')
        else:
            from_path = to_path
        app = GameTranslator(
            from_path,
            to_path,
            args.line_limit,
        )
        if not args.skip_backup:
            app.create_backup()
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
        app.save_translate_cache()
        app.print_bad_format()
        app.print_bad_translate()
