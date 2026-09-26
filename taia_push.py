import os
import sys
import logging
import imaplib
import email
import time
from datetime import datetime, timezone, timedelta
import requests

GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASS")
WORKER_URL = os.environ.get("WORKER_URL")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "12"))
RETRY_DELAY = int(os.environ.get("RETRY_DELAY", "300"))
BKK_TZ = timezone(timedelta(hours=7))

def create_logger():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    return logging.getLogger("TAIA")

def connect_imap():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_APP_PASS)
    return mail

def find_today_report(mail):
    mail.select("inbox")
    tz = BKK_TZ
    now = datetime.now(tz)
    search_date = (now - timedelta(hours=26)).strftime('%d-%b-%Y')
    status, data = mail.search(None, f'(SINCE "{search_date}" SUBJECT "[TAIA-REPORT]")')
    if status == "OK" and data[0]:
        msg_ids = data[0].split()
        return msg_ids[-1]
    return None

def fetch_email_html(mail, msg_id):
    status, data = mail.fetch(msg_id, "(RFC822)")
    if status != "OK":
        return ""
    raw = data[0][1]
    msg = email.message_from_bytes(raw)
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode("utf-8", errors="replace")
    return ""

def send_alert():
    now = datetime.now(BKK_TZ)
    thai_date = now.strftime('%d %b %Y').replace('Jan','ม.ค.').replace('Feb','ก.พ.').replace('Mar','มี.ค.').replace('Apr','เม.ย.').replace('May','พ.ค.').replace('Jun','มิ.ย.').replace('Jul','ก.ค.').replace('Aug','ส.ค.').replace('Sep','ก.ย.').replace('Oct','ต.ค.').replace('Nov','พ.ย.').replace('Dec','ธ.ค.')
    payload = {
        "messages": [{
            "type": "text",
            "text": f"⚠️ TAIA Alert: ไม่พบรายงานวันที่ {now.strftime('%Y-%m-%d')} ({thai_date})\nเวลาตรวจสอบ: {now.strftime('%H:%M น.')}\nอีเมลอาจยังไม่ถึงหรือมีปัญหา กรุณาตรวจสอบ Gmail"
        }]
    }
    headers = {"Content-Type": "application/json"}
    r = requests.post(WORKER_URL, json=payload, headers=headers, timeout=10)
    return r.status_code

def main():
    logger = create_logger()
    logger.info("TAIA Push Started")

    if not WORKER_URL:
        logger.error("WORKER_URL not configured")
        sys.exit(1)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            mail = connect_imap()
            msg_id = find_today_report(mail)
            if msg_id:
                logger.info(f"Found report: {msg_id}")
                html = fetch_email_html(mail, msg_id)
                mail.logout()
                if html:
                    payload = {"messages": [{"type": "text", "text": html, "format": "html"}]}
                    headers = {"Content-Type": "application/json"}
                    r = requests.post(WORKER_URL, json=payload, headers=headers, timeout=10)
                    logger.info(f"Sent to LINE: {r.status_code}")
                    sys.exit(0)
        except Exception as e:
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed: {e}")
        if attempt < MAX_RETRIES:
            logger.info(f"Retry in {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)

    logger.error("Report not found after all retries")
    send_alert()
    logger.info("Alert sent to LINE")
    sys.exit(0)

if __name__ == "__main__":
    main()
