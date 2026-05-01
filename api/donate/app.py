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
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
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
# Platform fee routed to the 1772 Strategies parent account (in percent).
# 0.5 == 0.5% of the charge total. Set to 0 to disable.
PLATFORM_FEE_PERCENT = float(os.environ.get('PLATFORM_FEE_PERCENT', '0') or '0')

# NOWPayments (crypto) — direct payment API, not invoice/hosted page.
NOWPAYMENTS_API_KEY = os.environ.get('NOWPAYMENTS_API_KEY', '')
NOWPAYMENTS_IPN_SECRET = os.environ.get('NOWPAYMENTS_IPN_SECRET', '')

# Email config (AWS SES). digitalfuturenh.com isn't yet a verified SES domain,
# so we send from 1772strategies.com (parent platform) with reply-to set to
# info@digitalfuturenh.com.
SES_FROM = os.environ.get('SES_FROM', 'forms@1772strategies.com')
ENDORSEMENT_TO = os.environ.get('ENDORSEMENT_TO', 'info@digitalfuturenh.com')
BRIEFING_TO = os.environ.get('BRIEFING_TO', 'info@digitalfuturenh.com')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')

_ses = boto3.client('ses', region_name=AWS_REGION) if os.environ.get('AWS_ACCESS_KEY_ID') else None

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

        CREATE TABLE IF NOT EXISTS endorsement_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT,
          name TEXT,
          email TEXT,
          office TEXT,
          party TEXT,
          message TEXT,
          ip TEXT,
          user_agent TEXT
        );
        CREATE TABLE IF NOT EXISTS briefing_signups (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT,
          email TEXT UNIQUE,
          ip TEXT,
          user_agent TEXT,
          source TEXT
        );

        CREATE TABLE IF NOT EXISTS survey_invites (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          token TEXT UNIQUE NOT NULL,
          created_at TEXT,
          name TEXT,
          email TEXT,
          office TEXT,
          party TEXT,
          message TEXT,
          email_sent_at TEXT,
          opened_at TEXT,
          completed_at TEXT,
          ip TEXT,
          user_agent TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_survey_token ON survey_invites(token);

        CREATE TABLE IF NOT EXISTS survey_responses (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          invite_id INTEGER NOT NULL,
          submitted_at TEXT,
          answers TEXT,
          ip TEXT,
          user_agent TEXT,
          FOREIGN KEY (invite_id) REFERENCES survey_invites(id)
        );

        CREATE TABLE IF NOT EXISTS crypto_donations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          payment_id TEXT UNIQUE,
          order_id TEXT UNIQUE,
          status TEXT,
          price_amount_usd_cents INTEGER,
          pay_currency TEXT,
          pay_amount TEXT,
          pay_address TEXT,
          actually_paid TEXT,
          created_at TEXT,
          confirmed_at TEXT,
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
          ip TEXT,
          user_agent TEXT,
          raw_create TEXT,
          raw_callback TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_crypto_payment_id ON crypto_donations(payment_id);
        CREATE INDEX IF NOT EXISTS idx_crypto_order_id ON crypto_donations(order_id);
        """)


init_db()


# ---------- helpers ----------

def _validate_amount(data: dict) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, 'invalid payload'
    amount = data.get('amount_cents')
    if not isinstance(amount, int) or amount < MIN_CENTS or amount > MAX_CENTS:
        return False, 'amount out of range'
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
    """Create the PaymentIntent up-front with just an amount.

    Donor info is collected later via /update-metadata so that the
    Stripe Payment Element can mount as soon as the donor picks an
    amount — UX-wise this matters more than carrying donor metadata
    on the initial intent."""
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.get_json(silent=True) or {}
    ok, err = _validate_amount(data)
    if not ok:
        return jsonify({'error': err}), 400

    amount_cents = int(data['amount_cents'])
    intent_kwargs = dict(
        amount=amount_cents,
        currency='usd',
        automatic_payment_methods={'enabled': True},
        description="Donation to NH Digital Future PAC",
        metadata={'source': 'digitalfuturenh.com',
                  'utm': (data.get('utm') or '')[:200]},
        stripe_account=CONNECTED_ACCOUNT_ID,
    )
    platform_fee_cents = int(round(amount_cents * (PLATFORM_FEE_PERCENT / 100.0)))
    if platform_fee_cents > 0:
        intent_kwargs['application_fee_amount'] = platform_fee_cents
    try:
        intent = stripe.PaymentIntent.create(**intent_kwargs)
    except stripe.error.StripeError as e:
        return jsonify({'error': str(e.user_message or e)}), 400

    with db() as c:
        c.execute("""
            INSERT OR IGNORE INTO donations (
              payment_intent_id, status, amount_cents, currency, created_at,
              ip, user_agent, utm)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            intent.id, intent.status, intent.amount, intent.currency,
            datetime.now(timezone.utc).isoformat(),
            (request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:80],
            (request.headers.get('User-Agent') or '')[:300],
            (data.get('utm') or '')[:200],
        ))

    return jsonify({
        'client_secret': intent.client_secret,
        'payment_intent_id': intent.id,
    })


REQUIRED_DONOR_FIELDS = [
    'first_name', 'last_name', 'email',
    'address1', 'city', 'state', 'postal_code',
    'employer', 'occupation', 'principal_place',
]


@app.route('/api/donate/update-metadata', methods=['POST', 'OPTIONS'])
def update_metadata():
    """Attach donor info to a previously-created PaymentIntent and
    record it locally. Called right before stripe.confirmPayment()."""
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.get_json(silent=True) or {}
    pi_id = (data.get('payment_intent_id') or '').strip()
    if not pi_id.startswith('pi_'):
        return jsonify({'error': 'missing payment_intent_id'}), 400
    for f in REQUIRED_DONOR_FIELDS:
        v = data.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            return jsonify({'error': f'missing field: {f}'}), 400

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
        'utm': (data.get('utm') or '')[:200],
        'source': 'digitalfuturenh.com',
    }

    try:
        stripe.PaymentIntent.modify(
            pi_id,
            metadata=metadata,
            receipt_email=data['email'],
            description=f"Donation to NH Digital Future PAC from "
                        f"{data['first_name']} {data['last_name']}",
            stripe_account=CONNECTED_ACCOUNT_ID,
        )
    except stripe.error.StripeError as e:
        return jsonify({'error': str(e.user_message or e)}), 400

    with db() as c:
        c.execute("""
            UPDATE donations SET
              first_name = ?, last_name = ?, email = ?, phone = ?,
              address1 = ?, address2 = ?, city = ?, state = ?,
              postal_code = ?, country = ?,
              employer = ?, occupation = ?, principal_place = ?,
              raw_metadata = ?
            WHERE payment_intent_id = ?
        """, (
            metadata['first_name'], metadata['last_name'], metadata['email'],
            metadata['phone'],
            metadata['address1'], metadata['address2'], metadata['city'],
            metadata['state'], metadata['postal_code'], metadata['country'],
            metadata['employer'], metadata['occupation'], metadata['principal_place'],
            json.dumps(metadata),
            pi_id,
        ))

    return jsonify({'ok': True})


@app.route('/api/donate/update-amount', methods=['POST', 'OPTIONS'])
def update_amount():
    """Modify the amount on an existing PaymentIntent.

    Used when the donor changes the preset/custom amount or toggles
    the cover-fees checkbox after the Element has already mounted."""
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.get_json(silent=True) or {}
    pi_id = (data.get('payment_intent_id') or '').strip()
    if not pi_id.startswith('pi_'):
        return jsonify({'error': 'missing payment_intent_id'}), 400
    ok, err = _validate_amount(data)
    if not ok:
        return jsonify({'error': err}), 400
    amount_cents = int(data['amount_cents'])
    modify_kwargs = dict(amount=amount_cents, stripe_account=CONNECTED_ACCOUNT_ID)
    platform_fee_cents = int(round(amount_cents * (PLATFORM_FEE_PERCENT / 100.0)))
    if platform_fee_cents > 0:
        modify_kwargs['application_fee_amount'] = platform_fee_cents
    try:
        intent = stripe.PaymentIntent.modify(pi_id, **modify_kwargs)
    except stripe.error.StripeError as e:
        return jsonify({'error': str(e.user_message or e)}), 400
    with db() as c:
        c.execute("UPDATE donations SET amount_cents = ? WHERE payment_intent_id = ?",
                  (intent.amount, pi_id))
    return jsonify({'ok': True, 'amount_cents': intent.amount})


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

    # This is a Connect-level webhook on the 1772 Strategies platform —
    # we receive events from ALL connected accounts. Ignore anything that
    # isn't for the DFNH PAC connected account.
    if event.get('account') and event['account'] != CONNECTED_ACCOUNT_ID:
        return jsonify({'received': True, 'ignored': 'wrong account'})

    etype = event['type']
    obj = event['data']['object']

    if etype in ('payment_intent.succeeded', 'payment_intent.payment_failed'):
        pi = obj
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
        if etype == 'payment_intent.succeeded':
            md = pi.get('metadata') or {}
            charges = (pi.get('charges') or {}).get('data') or []
            last4 = (charges[0].get('payment_method_details', {}).get('card', {}).get('last4')
                     if charges else '')
            brand = (charges[0].get('payment_method_details', {}).get('card', {}).get('brand')
                     if charges else '')
            donor = (md.get('first_name', '') + ' ' + md.get('last_name', '')).strip() \
                    or pi.get('receipt_email') or '(unknown donor)'
            body = (
                f"New donation received via digitalfuturenh.com\n\n"
                f"Amount:        ${pi['amount']/100:.2f}\n"
                f"Donor:         {donor}\n"
                f"Email:         {pi.get('receipt_email','')}\n"
                f"Card:          {brand} ****{last4}\n"
                f"Address:       {md.get('address1','')} {md.get('address2','')}, "
                f"{md.get('city','')}, {md.get('state','')} {md.get('postal_code','')} {md.get('country','')}\n"
                f"Employer:      {md.get('employer','')}\n"
                f"Occupation:    {md.get('occupation','')}\n"
                f"Place of work: {md.get('principal_place','')}\n"
                f"PaymentIntent: {pi['id']}\n"
                f"Stripe link:   https://dashboard.stripe.com/connect/accounts/{CONNECTED_ACCOUNT_ID}/payments/{pi['id']}\n"
            )
            _send_email(ENDORSEMENT_TO,
                        f"💸 New donation: ${pi['amount']/100:.2f} from {donor}",
                        body, reply_to=pi.get('receipt_email') or None)

    elif etype == 'charge.refunded':
        ch = obj
        body = (f"Refund issued on digitalfuturenh.com donation\n\n"
                f"Charge:   {ch['id']}\n"
                f"Amount:   ${ch['amount_refunded']/100:.2f} of ${ch['amount']/100:.2f}\n"
                f"PI:       {ch.get('payment_intent','')}\n")
        _send_email(ENDORSEMENT_TO, f"Refund: ${ch['amount_refunded']/100:.2f}", body)

    return jsonify({'received': True})


def _send_email(to, subject, body_text, reply_to=None):
    if not _ses:
        return False, 'SES not configured'
    try:
        kwargs = {
            'Source': SES_FROM,
            'Destination': {'ToAddresses': [to]},
            'Message': {
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {'Text': {'Data': body_text, 'Charset': 'UTF-8'}},
            },
        }
        if reply_to:
            kwargs['ReplyToAddresses'] = [reply_to]
        _ses.send_email(**kwargs)
        return True, None
    except Exception as e:
        return False, str(e)


SURVEY_BASE_URL = os.environ.get('SURVEY_BASE_URL', 'https://digitalfuturenh.com/survey/')


@app.route('/api/donate/endorsement-request', methods=['POST', 'OPTIONS'])
def endorsement_request():
    """Candidate requests the issues survey. We:
       (1) record the request,
       (2) generate a unique token for them,
       (3) email them a personalized survey link,
       (4) notify the PAC team."""
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    office = (data.get('office') or '').strip()
    party = (data.get('party') or '').strip()
    message = (data.get('message') or '').strip()
    if not name or not email:
        return jsonify({'error': 'Name and email are required.'}), 400
    if '@' not in email or '.' not in email:
        return jsonify({'error': 'Please enter a valid email address.'}), 400

    token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc).isoformat()
    ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:80]
    ua = (request.headers.get('User-Agent') or '')[:300]

    with db() as c:
        c.execute("""
            INSERT INTO survey_invites
              (token, created_at, name, email, office, party, message, ip, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (token, now, name[:200], email[:200], office[:200], party[:50],
              message[:5000], ip, ua))
        # Also keep a row in the legacy endorsement_requests table for back-compat.
        c.execute("""
            INSERT INTO endorsement_requests
              (created_at, name, email, office, party, message, ip, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (now, name[:200], email[:200], office[:200], party[:50],
              message[:5000], ip, ua))

    survey_link = f"{SURVEY_BASE_URL}?t={token}"

    candidate_body = (
        f"Hi {name.split()[0] if name else 'there'},\n\n"
        f"Thanks for asking about a Digital Future NH PAC endorsement.\n\n"
        f"To be considered, please complete the issues survey below. It "
        f"covers six policy pillars (self-custody, zero state taxation of "
        f"digital-asset gains, opposition to CBDCs, the right to mine and "
        f"run nodes, encryption and digital privacy, and smart-contract "
        f"recognition). Most candidates finish it in under 15 minutes.\n\n"
        f"Your survey link (unique to you — please don't share it):\n"
        f"{survey_link}\n\n"
        f"Endorsements are party-blind and graded against the public framework "
        f"on https://digitalfuturenh.com/issues/. Once you submit, we'll "
        f"compare your answers against your public record and follow up.\n\n"
        f"Questions: just reply to this email.\n\n"
        f"— NH Digital Future PAC\n"
        f"  info@digitalfuturenh.com  ·  digitalfuturenh.com\n\n"
        f"--\n"
        f"Paid for by NH Digital Future PAC, 248 Carley Road, Peterborough, "
        f"NH 03458. Chris Maidment, Chair. Not authorized by any candidate or "
        f"candidate's committee.\n"
    )
    _send_email(email, "Your NH Digital Future PAC issues survey",
                candidate_body, reply_to=ENDORSEMENT_TO)

    team_body = (
        f"New survey request from digitalfuturenh.com\n\n"
        f"Name:    {name}\n"
        f"Email:   {email}\n"
        f"Office:  {office or '(not specified)'}\n"
        f"Party:   {party or '(not specified)'}\n\n"
        f"Why they'd like an endorsement:\n{message or '(not specified)'}\n\n"
        f"Survey link sent to candidate:\n{survey_link}\n"
    )
    _send_email(ENDORSEMENT_TO, f"Survey request — {name}",
                team_body, reply_to=email)

    with db() as c:
        c.execute("UPDATE survey_invites SET email_sent_at = ? WHERE token = ?",
                  (now, token))

    return jsonify({'ok': True})


@app.get('/api/donate/survey/info')
def survey_info():
    """Public lookup of survey metadata by token (used by /survey/ page)."""
    t = (request.args.get('t') or '').strip()
    if not t:
        return jsonify({'error': 'missing token'}), 400
    with db() as c:
        row = c.execute("""
            SELECT id, name, email, office, party, completed_at
              FROM survey_invites WHERE token = ?
        """, (t,)).fetchone()
        if not row:
            return jsonify({'error': 'survey link not found'}), 404
        c.execute("UPDATE survey_invites SET opened_at = COALESCE(opened_at, ?) WHERE token = ?",
                  (datetime.now(timezone.utc).isoformat(), t))
    return jsonify({
        'name': row['name'],
        'email': row['email'],
        'office': row['office'],
        'party': row['party'],
        'completed': bool(row['completed_at']),
    })


@app.route('/api/donate/survey/submit', methods=['POST', 'OPTIONS'])
def survey_submit():
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.get_json(silent=True) or {}
    t = (data.get('token') or '').strip()
    answers = data.get('answers')
    if not t:
        return jsonify({'error': 'missing token'}), 400
    if not isinstance(answers, dict):
        return jsonify({'error': 'answers must be an object'}), 400

    now = datetime.now(timezone.utc).isoformat()
    ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:80]
    ua = (request.headers.get('User-Agent') or '')[:300]

    with db() as c:
        inv = c.execute("""
            SELECT id, name, email, office, party FROM survey_invites WHERE token = ?
        """, (t,)).fetchone()
        if not inv:
            return jsonify({'error': 'survey link not found'}), 404
        c.execute("""
            INSERT INTO survey_responses (invite_id, submitted_at, answers, ip, user_agent)
            VALUES (?, ?, ?, ?, ?)
        """, (inv['id'], now, json.dumps(answers)[:200000], ip, ua))
        c.execute("UPDATE survey_invites SET completed_at = ? WHERE id = ?",
                  (now, inv['id']))

    summary = "\n".join(f"{k}: {v}" for k, v in answers.items() if v)
    body = (
        f"Survey response received from digitalfuturenh.com\n\n"
        f"Candidate: {inv['name']}\n"
        f"Email:     {inv['email']}\n"
        f"Office:    {inv['office']}\n"
        f"Party:     {inv['party']}\n\n"
        f"Submitted at: {now}\n\n"
        f"Answers:\n{summary}\n"
    )
    _send_email(ENDORSEMENT_TO, f"Survey submitted — {inv['name']}",
                body, reply_to=inv['email'])
    return jsonify({'ok': True})


@app.route('/api/donate/briefing-signup', methods=['POST', 'OPTIONS'])
def briefing_signup():
    if request.method == 'OPTIONS':
        return ('', 204)
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if '@' not in email or '.' not in email:
        return jsonify({'error': 'Please enter a valid email address.'}), 400
    with db() as c:
        c.execute("""
            INSERT OR IGNORE INTO briefing_signups
              (created_at, email, ip, user_agent, source)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            email[:200],
            (request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:80],
            (request.headers.get('User-Agent') or '')[:300],
            (data.get('source') or 'involved-page')[:50],
        ))
    _send_email(BRIEFING_TO,
                f"New briefing list signup — {email}",
                f"New signup on digitalfuturenh.com\n\nEmail: {email}\n",
                reply_to=email)
    return jsonify({'ok': True})


SUPPORTED_CRYPTO = {
    'btc':  'Bitcoin',
    'eth':  'Ethereum',
    'sol':  'Solana',
    'usdc': 'USDC (Ethereum)',
    'usdcsol': 'USDC (Solana)',
    'usdtsol': 'USDT (Solana)',
}


@app.route('/api/donate/crypto/create-payment', methods=['POST', 'OPTIONS'])
def crypto_create_payment():
    """Create a direct NOWPayments crypto payment, return the deposit
    address + crypto amount to display to the donor. We do NOT use the
    NOWPayments invoice/hosted page — donor sees the address on our
    site, then sends from their own wallet."""
    if request.method == 'OPTIONS':
        return ('', 204)
    if not NOWPAYMENTS_API_KEY:
        return jsonify({'error': 'crypto donations not configured'}), 500
    data = request.get_json(silent=True) or {}

    # validate amount
    amount_cents = data.get('amount_cents')
    if not isinstance(amount_cents, int) or amount_cents < MIN_CENTS or amount_cents > MAX_CENTS:
        return jsonify({'error': 'amount out of range'}), 400

    # validate crypto choice
    pay_currency = (data.get('pay_currency') or '').lower().strip()
    if pay_currency not in SUPPORTED_CRYPTO:
        return jsonify({'error': 'unsupported cryptocurrency'}), 400

    # validate full RSA 664 donor info
    for f in REQUIRED_DONOR_FIELDS:
        v = data.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            return jsonify({'error': f'missing field: {f}'}), 400

    order_id = f"DFNH-{secrets.token_urlsafe(12)}"
    price_amount_usd = round(amount_cents / 100, 2)

    import urllib.request, urllib.error
    payload = {
        'price_amount': price_amount_usd,
        'price_currency': 'usd',
        'pay_currency': pay_currency,
        'order_id': order_id,
        'order_description': f"Donation to NH Digital Future PAC from "
                             f"{data['first_name']} {data['last_name']}",
        'ipn_callback_url': 'https://digitalfuturenh.com/api/donate/nowpayments-webhook',
    }
    req = urllib.request.Request(
        'https://api.nowpayments.io/v1/payment',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'x-api-key': NOWPAYMENTS_API_KEY,
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'DigitalFutureNH-PAC/1.0 (digitalfuturenh.com)',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            np = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try: msg = json.loads(body).get('message', body)
        except Exception: msg = body
        return jsonify({'error': f'NOWPayments error: {msg}'}), 502
    except Exception as e:
        return jsonify({'error': f'NOWPayments unreachable: {e}'}), 502

    md = data
    with db() as c:
        c.execute("""
            INSERT INTO crypto_donations (
              payment_id, order_id, status, price_amount_usd_cents,
              pay_currency, pay_amount, pay_address, created_at,
              first_name, last_name, email, phone,
              address1, address2, city, state, postal_code, country,
              employer, occupation, principal_place,
              ip, user_agent, raw_create
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(np.get('payment_id') or ''),
            order_id,
            np.get('payment_status') or 'waiting',
            amount_cents, pay_currency,
            str(np.get('pay_amount') or ''),
            str(np.get('pay_address') or ''),
            datetime.now(timezone.utc).isoformat(),
            md['first_name'][:200], md['last_name'][:200], md['email'][:200],
            (md.get('phone') or '')[:50],
            md['address1'][:200], (md.get('address2') or '')[:200],
            md['city'][:120], md['state'][:80], md['postal_code'][:20],
            (md.get('country') or 'US')[:8],
            md['employer'][:200], md['occupation'][:200], md['principal_place'][:200],
            (request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:80],
            (request.headers.get('User-Agent') or '')[:300],
            json.dumps(np)[:50000],
        ))

    # Notify donor right away (lets them re-find the address by email)
    body_text = (
        f"Hi {md['first_name']},\n\n"
        f"Thanks for your contribution to NH Digital Future PAC.\n\n"
        f"To complete your donation of ${price_amount_usd:.2f} USD, send "
        f"{np.get('pay_amount')} {pay_currency.upper()} to:\n\n"
        f"  {np.get('pay_address')}\n\n"
        f"You can do this from any wallet (Phantom, Coinbase, Ledger, etc.). "
        f"Once the network confirms your transaction we will send a final "
        f"receipt and report the contribution to the New Hampshire Secretary "
        f"of State per RSA 664.\n\n"
        f"This deposit address is unique to your donation; do not share it.\n\n"
        f"— NH Digital Future PAC\n"
        f"  info@digitalfuturenh.com  ·  digitalfuturenh.com\n"
    )
    _send_email(md['email'], "Complete your crypto donation — NH Digital Future PAC",
                body_text, reply_to=ENDORSEMENT_TO)

    return jsonify({
        'payment_id': np.get('payment_id'),
        'order_id': order_id,
        'pay_address': np.get('pay_address'),
        'pay_amount': np.get('pay_amount'),
        'pay_currency': pay_currency,
        'price_amount': price_amount_usd,
        'expiration_estimate_date': np.get('expiration_estimate_date'),
        'network': np.get('network'),
    })


@app.post('/api/donate/nowpayments-webhook')
def nowpayments_webhook():
    """NOWPayments IPN callback. Verify HMAC-SHA512 over the sorted JSON
    body using the IPN secret, then update DB + notify."""
    import hmac, hashlib
    raw = request.data
    if not NOWPAYMENTS_IPN_SECRET:
        return jsonify({'error': 'ipn secret not configured'}), 500
    sig_hdr = request.headers.get('x-nowpayments-sig', '')
    try:
        body = json.loads(raw.decode('utf-8'))
    except Exception:
        return jsonify({'error': 'invalid body'}), 400
    canonical = json.dumps(body, separators=(',', ':'), sort_keys=True).encode('utf-8')
    expected = hmac.new(NOWPAYMENTS_IPN_SECRET.encode('utf-8'),
                        canonical, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, sig_hdr):
        return jsonify({'error': 'bad signature'}), 400

    payment_id = str(body.get('payment_id') or '')
    order_id = body.get('order_id') or ''
    status = (body.get('payment_status') or '').lower()
    actually_paid = body.get('actually_paid') or body.get('pay_amount')

    with db() as c:
        row = c.execute("SELECT * FROM crypto_donations WHERE payment_id = ? OR order_id = ?",
                        (payment_id, order_id)).fetchone()
        if row:
            c.execute("""UPDATE crypto_donations
                            SET status = ?, actually_paid = ?, raw_callback = ?,
                                confirmed_at = CASE WHEN ? IN ('finished','confirmed') THEN ? ELSE confirmed_at END
                          WHERE id = ?""",
                      (status, str(actually_paid or ''), json.dumps(body)[:50000],
                       status, datetime.now(timezone.utc).isoformat(), row['id']))

    if status in ('finished', 'confirmed'):
        donor = ''
        if row:
            donor = f"{row['first_name']} {row['last_name']}".strip() or row['email']
            email_body = (
                f"Crypto donation confirmed via digitalfuturenh.com\n\n"
                f"Amount:        ${row['price_amount_usd_cents']/100:.2f} USD "
                f"(paid {actually_paid} {row['pay_currency'].upper()})\n"
                f"Donor:         {donor}\n"
                f"Email:         {row['email']}\n"
                f"Address:       {row['address1']} {row['address2'] or ''}, "
                f"{row['city']}, {row['state']} {row['postal_code']} {row['country']}\n"
                f"Employer:      {row['employer']}\n"
                f"Occupation:    {row['occupation']}\n"
                f"Place of work: {row['principal_place']}\n"
                f"NOWPayments ID: {payment_id}\n"
                f"Order ID:      {order_id}\n"
            )
            _send_email(ENDORSEMENT_TO,
                        f"Crypto donation: ${row['price_amount_usd_cents']/100:.2f} from {donor}",
                        email_body, reply_to=row['email'])
            # Final receipt to donor
            receipt = (
                f"Thanks {row['first_name']} — your crypto donation is confirmed.\n\n"
                f"Amount:  ${row['price_amount_usd_cents']/100:.2f} USD ({actually_paid} {row['pay_currency'].upper()})\n"
                f"Network confirmation received {datetime.now(timezone.utc).date().isoformat()}\n\n"
                f"This contribution will be reported to the New Hampshire "
                f"Secretary of State per RSA 664.\n\n"
                f"— NH Digital Future PAC\n"
            )
            _send_email(row['email'], "Crypto donation confirmed — NH Digital Future PAC",
                        receipt, reply_to=ENDORSEMENT_TO)
    return jsonify({'received': True})


@app.get('/api/donate/health')
def health():
    return jsonify({'ok': True, 'time': int(time.time())})


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', 5026)), debug=False)
