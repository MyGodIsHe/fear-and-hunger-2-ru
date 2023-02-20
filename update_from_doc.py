#!/usr/bin/env python3
from common import get_authenticated_service, get_parts


if __name__ == '__main__':
    service = get_authenticated_service()
    itr = get_parts(service)
    print('{')
    text, translated = next(itr)
    print(f'  "{text}": "{translated}"', end='')
    for text, translated in itr:
        print(',')
        print(f'  "{text}": "{translated}"', end='')
    print()
    print('}', end='')
