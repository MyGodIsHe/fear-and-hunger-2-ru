#!/usr/bin/env python3
import argparse

from common import get_authenticated_service, upload_file
from settings import DOC_IDS


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--file',
        required=True,
    )
    args = parser.parse_args()
    with open(args.file) as f:
        data = f.read()
    offset = int(len(data) / len(DOC_IDS))
    service = get_authenticated_service()
    end = 0
    for n, file_id in enumerate(DOC_IDS, start=1):
        start = end
        end = data.find('\n\n', n * offset)
        if end == -1:
            body = data[start:]
        else:
            end += 2
            body = data[start:end]
        upload_file(service, file_id, body)
