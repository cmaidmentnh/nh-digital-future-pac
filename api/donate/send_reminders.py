#!/usr/bin/env python3
"""
Send reminder emails to crypto donors who haven't completed their
deposit yet. Designed to be run hourly from cron.

Sends three reminders:
  - 24h after creation (for donations still in 'waiting' state)
  - 48h after creation
  -  6d after creation (final, before NOWPayments expires the address)

Each row is updated with the timestamp of the reminder so we don't
double-send.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')

DB_PATH = os.environ.get('DFNH_DB_PATH', str(ROOT / 'donations.db'))
SES_FROM = os.environ.get('SES_FROM', 'forms@digitalfuturenh.com')
ENDORSEMENT_TO = os.environ.get('ENDORSEMENT_TO', 'info@digitalfuturenh.com')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

ses = boto3.client('ses', region_name=AWS_REGION) if os.environ.get('AWS_ACCESS_KEY_ID') else None


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def send(to, subject, body):
    if not ses:
        print(f"[reminders] SES not configured, would send to {to}: {subject}", file=sys.stderr)
        return
    ses.send_email(
        Source=SES_FROM,
        Destination={'ToAddresses': [to]},
        Message={
            'Subject': {'Data': subject, 'Charset': 'UTF-8'},
            'Body': {'Text': {'Data': body, 'Charset': 'UTF-8'}},
        },
        ReplyToAddresses=[ENDORSEMENT_TO],
    )


def reminder_body(row, label):
    pay_amount = row['pay_amount']
    pay_currency = (row['pay_currency'] or '').upper()
    address = row['pay_address']
    usd = (row['price_amount_usd_cents'] or 0) / 100
    return (
        f"Hi {row['first_name']},\n\n"
        f"{label}\n\n"
        f"To complete your donation of ${usd:.2f} USD to NH Digital Future "
        f"PAC, send {pay_amount} {pay_currency} to:\n\n"
        f"  {address}\n\n"
        f"You can do this from any wallet (Phantom, Coinbase, Ledger, etc.). "
        f"This deposit address remains valid for 7 days from when you "
        f"submitted the form. If you've already sent the payment and just "
        f"haven't seen confirmation yet, you can ignore this — networks "
        f"sometimes take a few minutes to a few hours to confirm.\n\n"
        f"Questions: just reply to this email.\n\n"
        f"— NH Digital Future PAC\n"
        f"  info@digitalfuturenh.com  ·  digitalfuturenh.com\n\n"
        f"--\n"
        f"Paid for by NH Digital Future PAC, 248 Carley Road, Peterborough, "
        f"NH 03458. Chris Maidment, Chair. Not authorized by any candidate "
        f"or candidate's committee.\n"
    )


def main():
    now = datetime.now(timezone.utc)
    iso_now = now.isoformat()

    with db() as c:
        rows = c.execute("""
            SELECT * FROM crypto_donations
             WHERE status IN ('waiting', 'partially_paid', 'confirming')
               AND created_at IS NOT NULL
        """).fetchall()
        sent_count = 0
        for r in rows:
            try:
                created = datetime.fromisoformat(r['created_at'])
            except Exception:
                continue
            age = now - created
            email = r['email']
            if not email:
                continue

            # 24h reminder
            if age >= timedelta(hours=24) and age < timedelta(hours=48) and not r['reminder_24h_sent_at']:
                send(email,
                     "Reminder: complete your NH Digital Future PAC donation",
                     reminder_body(r, "Just a quick reminder — your crypto donation is still pending."))
                c.execute("UPDATE crypto_donations SET reminder_24h_sent_at = ? WHERE id = ?",
                          (iso_now, r['id']))
                sent_count += 1

            # 48h reminder
            elif age >= timedelta(hours=48) and age < timedelta(days=6) and not r['reminder_48h_sent_at']:
                send(email,
                     "Still waiting on your contribution — NH Digital Future PAC",
                     reminder_body(r, "We haven't yet seen your contribution land on-chain."))
                c.execute("UPDATE crypto_donations SET reminder_48h_sent_at = ? WHERE id = ?",
                          (iso_now, r['id']))
                sent_count += 1

            # 6-day final reminder (one day before 7d expiration)
            elif age >= timedelta(days=6) and age < timedelta(days=7) and not r['reminder_6d_sent_at']:
                send(email,
                     "Last chance: your deposit address expires in 24 hours",
                     reminder_body(r, "This is your final reminder — the deposit address for your "
                                       "donation expires in about 24 hours. After that, sending crypto "
                                       "to it may result in lost funds."))
                c.execute("UPDATE crypto_donations SET reminder_6d_sent_at = ? WHERE id = ?",
                          (iso_now, r['id']))
                sent_count += 1

    print(f"[reminders] checked {len(rows)} pending, sent {sent_count} reminders")


if __name__ == '__main__':
    main()
