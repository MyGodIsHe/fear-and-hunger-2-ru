#!/usr/bin/env python3
import json

from common import NAME_REGEX, fix_name


def main():
    with open('translate_cache.json') as f:
        data = json.load(f)
    names = {}
    for k, v in data.items():
        mk = NAME_REGEX.search(fix_name(k))
        if not mk:
            continue
        mv = NAME_REGEX.search(v)
        names[mk.group(2)] = mv.group(2)
    for k, v in names.items():
        print(k, '>', v)


if __name__ == '__main__':
    main()
