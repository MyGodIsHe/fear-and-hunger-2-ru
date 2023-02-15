#!/usr/bin/env python3
"""
pip install google-auth google-auth-httplib2 google-api-python-client
"""
import io
import json
import os

from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseDownload

SERVICE_ACCOUNT_FILE = 'service.json'

SCOPES = ['https://www.googleapis.com/auth/drive']
API_SERVICE_NAME = 'drive'
API_VERSION = 'v3'
DOC_IDS = [
    '1It-ptFBxDCnCsYWFyqCBY-HlOXVxOjen7lI2WZtdT9k',
    '1hJd5UT-3dom3jHQaDyBo47TnQpWvPAGSvHcJaPuGBLk',
]


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
    for doc_id in DOC_IDS:
        for pair in get_file(service, doc_id).split('\r\n\r\n\r\n'):
            pair = pair.replace('\uFEFF', '')
            yield pair.strip('\r\n').split('\r\n')


def get_file(service, doc_id: str) -> str:
    request = service.files().export_media(fileId=doc_id, mimeType='text/plain')
    file = io.BytesIO()
    downloader = MediaIoBaseDownload(file, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    return file.getvalue().decode('utf-8')


def get_revisions(service, doc_id: str):
    request = service.revisions().list(fileId=doc_id)
    print(request.execute())


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
