#!/usr/bin/env python3
import argparse
import json
import re

LETTERS_REGEX = re.compile(r'[А-я]')


def main(original: str, target: str) -> None:
    with open(original) as f:
        original_data = dict(sorted(json.loads(f.read()).items()))
    with open(target) as f:
        target_data = dict(sorted(json.loads(f.read()).items()))

    for k in set(original_data) - set(target_data):
        del original_data[k]
    for k in set(target_data) - set(original_data):
        del target_data[k]

    assert original_data.keys() == target_data.keys()

    different_lines = 0
    for o, t in zip(original_data.values(), target_data.values()):
        o = only_letters(o)
        t = only_letters(t)
        if o != t:
            different_lines += 1

    print('Отредактировано {:0.2f}% строк машинного перевода'.format(100 * different_lines / len(original_data)))


def only_letters(text: str) -> str:
    return ''.join(LETTERS_REGEX.findall(text))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--original',
        required=True,
    )
    parser.add_argument(
        '--target',
        required=True,
    )
    args = parser.parse_args()
    main(args.original, args.target)
