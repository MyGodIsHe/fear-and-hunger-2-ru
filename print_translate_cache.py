#!/usr/bin/env python3
import json
import os

from translate import TRANSLATE_CACHE_FILENAME

if __name__ == '__main__':
    if os.path.exists(TRANSLATE_CACHE_FILENAME):
        with open(TRANSLATE_CACHE_FILENAME, 'r') as f:
            translate_map = json.load(f)
        for k, v in translate_map.items():
            print(json.dumps(k, ensure_ascii=False)[1:-1])
            print(json.dumps(v, ensure_ascii=False)[1:-1])
            print()
