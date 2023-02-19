#!/usr/bin/env python3
import argparse
import os


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--file',
        required=True,
    )
    args = parser.parse_args()
    with open(args.file) as f:
        data = f.read()
    offset = int(len(data) / 2)
    i = data.find('\n\n', offset) + 2
    name, ext = os.path.splitext(args.file)
    with open(f'{name}_part1{ext}', 'w') as f:
        f.write(data[:i])
    with open(f'{name}_part2{ext}', 'w') as f:
        f.write(data[i:])
