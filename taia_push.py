#!/usr/bin/env python3
"""
TAIA LINE Push - GitHub Actions Version
"""

import os
import sys
import json
import re
import email
import logging
import imaplib
from datetime import datetime, timedelta, timezone
from email.header import decode_header

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Missing dependencies")
    sys.exit(1)

GMAIL_USER = os.environ.get("GMAIL_USER", "nilouis.r@gmail.com")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS", "")
WORKER_URL = os.environ.get("WORKER_URL", "https://line-push-bot.farmer-line-bot.workers.dev")
EMAIL_SUBJECT_PREFIX = "[TAIA-REPORT]"
THAI_TZ = timezone(timedelta(hours=7))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("taia_push")


def get_today_str():
    return datetime.now(THAI_TZ).strftime("%Y-%m-%d")


def connect_gmail():
    logger.info(f"Connecting to Gmail IMAP as {GMAIL_USER}...")
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(GMAIL_USER, GMAIL_APP_PASS)
    logger.info("Gmail login OK")
    return mail


def find_today_report(mail):
    today = get_today_str()
    search_subject = f'{EMAIL_SUBJECT_PREFIX} {today}'
    logger.info(f'Searching for email: subject="{search_subject}"')
    mail.select('INBOX', readonly=True)
    date_str = datetime.now(THAI_TZ).strftime("%d-%b-%Y")
    status, data = mail.search(None, f'(SUBJECT "{search_subject}" SINCE {date_str})')
    if status != 'OK' or not data[0]:
        status, data = mail.search(None, f'SUBJECT "{search_subject}"')
    if status != 'OK' or not data[0]:
        logger.info("No report email found")
        return None, None
    email_ids = data[0].split()
    latest_id = email_ids[-1]
    logger.info(f"Found report email (ID: {latest_id.decode()})")
    status, msg_data = mail.fetch(latest_id, '(RFC822)')
    if status != 'OK':
        return None, None
    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email)
    body = ''
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype in ('text/plain', 'text/html'):
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    body = payload.decode(charset, errors='replace')
                    if ctype == 'text/plain':
                        break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or 'utf-8'
            body = payload.decode(charset, errors='replace')
    url = None
    for pattern in [r'(https://www\.coze\.cn/s/[A-Za-z0-9_-]+/?\S*)', r'(https://www\.coze\.cn/[^\s<>"\']+)']:
        match = re.search(pattern, body)
        if match:
            url = match.group(1).rstrip('.\'" \n\r')
            break
    summary = None
    summary_match = re.search(r'\[TAIA-SUMMARY\]\s*\n(.*?)(?:\n\[TAIA-URL\]|\n---|\nhttp)', body, re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()
    logger.info(f"URL found: {url is not None}")
    logger.info(f"Summary found: {summary is not None}")
    return url, summary


def push_to_line(text):
    if not text:
        return False
    try:
        MAX_LEN = 4900
        chunks = []
        remaining = text
        while remaining:
            if len(remaining) <= MAX_LEN:
                chunks.append(remaining)
                break
            idx = remaining.rfind('\n', 0, MAX_LEN)
            if idx < MAX_LEN * 0.5:
                idx = MAX_LEN
            chunks.append(remaining[:idx])
            remaining = remaining[idx:]
        for i, chunk in enumerate(chunks):
            resp = requests.post(WORKER_URL, headers={"Content-Type": "application/json"}, json={"message": chunk}, timeout=30)
            if resp.status_code == 200:
                logger.info(f"LINE push chunk {i+1}/{len(chunks)} OK")
            else:
                logger.error(f"Worker chunk {i+1} returned {resp.status_code}: {resp.text}")
                return False
        return
