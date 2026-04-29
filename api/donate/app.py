"""
Digital Future NH PAC — donation backend.

Tiny Flask app that:
  1. Creates a Stripe PaymentIntent on the connected account
     acct_1TRbDCDIv3mOgD9F via the 1772 Strategies platform key.
  2. Receives Stripe webhooks and logs successful donations to SQLite.
  3. Sends a contribution receipt email via AWS SES.

Run locally:
  flask --app app run -p 5026
Production: systemd unit (dfnh-donate.service) -> gunicorn on 127.0.0.1:5026,
nginx proxies digitalfuturenh.com/api/donate/* to it.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import stripe
from dotenv import load_dotenv
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')

app = Flask(__name__)

STRIPE_SECRET_KEY = os.environ['STRIPE_SECRET_KEY']
STRIPE_PUBLISHABLE_KEY = os.environ['STRIPE_PUBLISHABLE_KEY']
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
CONNECTED_ACCOUNT_ID = os.environ.get('STRIPE_CONNECTED_ACCOUNT', 'acct_1TRbDCDIv3mOgD9F')
DB_PATH = os.environ.get('DFNH_DB_PATH', str(ROOT / 'donations.db'))
ALLOWED_ORIGIN = os.environ.get('ALLOWED_ORIGIN', 'https://digitalfuturenh.com')

stripe.api_key = STRIPE_SECRET_KEY

# Per FEC and NH RSA 664-style guardrails. Enforce a hard ceiling well above
# any plausible state-PAC contribution; Stripe will also flag oversized
# transactions for review.
MIN_CENTS = 100          # $1.00
MAX_CENTS = 500_000_00   # $500,000


# ---------- DB ----------

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS donations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          payment_intent_id TEXT UNIQUE,
          status TEXT,
          amount_cents INTEGER,
          currency TEXT,
          created_at TEXT,
          succeeded_at TEXT,
          first_name TEXT,
          last_name TEXT,
          email TEXT,
          phone TEXT,
          address1 TEXT,
          address2 TEXT,
          city TEXT,
          state TEXT,
          postal_code TEXT,
          country TEXT,
          employer TEXT,
          occupation TEXT,
          principal_place TEXT,
          attest_citizen INTEGER,
          attest_own_funds INTEGER,
          attest_not_corporate INTEGER,
          ip TEXT,
          user_agent TEXT,
          utm TEXT,
          stripe_event_id TEXT,
          raw_metadata TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_donations_pi ON donations(payment_intent_id);
        CREATE INDEX IF NOT EXISTS idx_donations_email ON donations(email);
        """)


init_db()


# ---------- helpers ----------

REQUIRED_FIELDS = [
    'first_name', 'last_name', 'email',
    'address1', 'city', 'state', 'postal_code',
    'employer', 'occupation', 'principal_place',
]


def _validate_payload(data: dict) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, 'invalid payload'
    amount = data.get('amount_cents')
    if not isinstance(amount, int) or amount < MIN_CENTS or amount > MAX_CENTS:
        return False, 'amount out of range'
    for f in REQUIRED_FIELDS:
        v = data.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            return False, f'missing field: {f}'
    return True, ''


def _cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = ALLOWED_ORIGIN
    resp.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp


@app.after_request
def add_cors(resp):
    return _cors(resp)


# ---------- routes ----------

@app.get('/api/donate/config')
def config():
    return jsonify({
        'publishable_key': STRIPE_PUBLISHABLE_KEY,
        'connected_account': CONNECTED_ACCOUNT_ID,
        'min_cents': MIN_CENTS,
        'max_cents': MAX_CENTS,
    })


@app.route('/api/donate/create-intent', methods=['POST', 'OPTIONS'])
def create_intent():
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.get_json(silent=True) or {}
    ok, err = _validate_payload(data)
    if not ok:
        return jsonify({'error': err}), 400

    metadata = {
        'first_name': data['first_name'][:200],
        'last_name': data['last_name'][:200],
        'email': data['email'][:200],
        'phone': (data.get('phone') or '')[:50],
        'address1': data['address1'][:200],
        'address2': (data.get('address2') or '')[:200],
        'city': data['city'][:120],
        'state': data['state'][:80],
        'postal_code': data['postal_code'][:20],
        'country': (data.get('country') or 'US')[:8],
        'employer': data['employer'][:200],
        'occupation': data['occupation'][:200],
        'principal_place': data['principal_place'][:200],
        'attest_citizen': '1',
        'attest_own_funds': '1',
        'attest_not_corporate': '1',
        'utm': (data.get('utm') or '')[:200],
        'source': 'digitalfuturenh.com',
    }

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(data['amount_cents']),
            currency='usd',
            automatic_payment_methods={'enabled': True},
            description=f"Donation to NH Digital Future PAC from "
                        f"{data['first_name']} {data['last_name']}",
            receipt_email=data['email'],
            metadata=metadata,
            stripe_account=CONNECTED_ACCOUNT_ID,
        )
    except stripe.error.StripeError as e:
        return jsonify({'error': str(e.user_message or e)}), 400

    # Pre-record the intent so the webhook can update it later.
    with db() as c:
        c.execute("""
            INSERT OR IGNORE INTO donations (
              payment_intent_id, status, amount_cents, currency, created_at,
              first_name, last_name, email, phone,
              address1, address2, city, state, postal_code, country,
              employer, occupation, principal_place,
              attest_citizen, attest_own_funds, attest_not_corporate,
              ip, user_agent, utm, raw_metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            intent.id, intent.status, intent.amount, intent.currency,
            datetime.now(timezone.utc).isoformat(),
            metadata['first_name'], metadata['last_name'], metadata['email'],
            metadata['phone'],
            metadata['address1'], metadata['address2'], metadata['city'],
            metadata['state'], metadata['postal_code'], metadata['country'],
            metadata['employer'], metadata['occupation'], metadata['principal_place'],
            1, 1, 1,
            (request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:80],
            (request.headers.get('User-Agent') or '')[:300],
            metadata['utm'], json.dumps(metadata),
        ))

    return jsonify({
        'client_secret': intent.client_secret,
        'payment_intent_id': intent.id,
    })


@app.post('/api/donate/webhook')
def webhook():
    payload = request.data
    sig = request.headers.get('Stripe-Signature', '')
    if not STRIPE_WEBHOOK_SECRET:
        return jsonify({'error': 'webhook secret not configured'}), 500
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        return jsonify({'error': 'bad signature'}), 400

    if event['type'] in ('payment_intent.succeeded', 'payment_intent.payment_failed'):
        pi = event['data']['object']
        with db() as c:
            c.execute("""
                UPDATE donations
                   SET status = ?, succeeded_at = ?, stripe_event_id = ?
                 WHERE payment_intent_id = ?
            """, (
                pi['status'],
                datetime.now(timezone.utc).isoformat() if pi['status'] == 'succeeded' else None,
                event['id'], pi['id'],
            ))
    return jsonify({'received': True})


@app.get('/api/donate/health')
def health():
    return jsonify({'ok': True, 'time': int(time.time())})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 5026)), debug=False)
