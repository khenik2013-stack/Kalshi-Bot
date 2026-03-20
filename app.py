import os
import time
import uuid
import base64
import math
import requests
from urllib.parse import urlparse
from flask import Flask, request, jsonify
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

app = Flask(__name__)

BASE = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2").rstrip("/")
KEY_ID = os.getenv("KALSHI_API_KEY_ID")
KEY_PEM_RAW = os.getenv("KALSHI_PRIVATE_KEY_PEM", "")
SERIES = os.getenv("KALSHI_SERIES_PREFIX", "KXBTC15M")

BUY_MAX_COST_CENTS = 1000

KEY_PEM = KEY_PEM_RAW.replace("\\n", "\n").strip()
PRIVATE_KEY = serialization.load_pem_private_key(KEY_PEM.encode(), password=None)

STATE = {
    "bucket": None,
    "traded": False,
    "side": None,
}

def headers(method: str, path: str):
    ts = str(int(time.time() * 1000))
    sign_path = urlparse(BASE + path).path
    msg = ts + method.upper() + sign_path

    sig = PRIVATE_KEY.sign(
        msg.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )

    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode()
    }

def current_15m_bucket():
    return int(time.time() // 900)

def get_current_ticker():
    r = requests.get(
        f"{BASE}/markets",
        params={"series_ticker": SERIES, "status": "open", "limit": 20},
        timeout=5
    )
    r.raise_for_status()
    data = r.json()
    markets = data.get("markets", [])
    if not markets:
        raise RuntimeError("No open BTC 15m markets found")

    markets.sort(key=lambda x: x.get("close_time", "9999"))
    return markets[0]["ticker"]

def get_implied_ask_cents(ticker: str, side: str):
    r = requests.get(f"{BASE}/markets/{ticker}/orderbook", timeout=5)
    r.raise_for_status()
    data = r.json()
    ob = data.get("orderbook_fp", {})
    yes_bids = ob.get("yes_dollars", [])
    no_bids = ob.get("no_dollars", [])

    if side == "yes":
        if not no_bids:
            raise RuntimeError("No NO bids available")
        best_no_bid = float(no_bids[-1][0])
        ask_cents = int(round((1.0 - best_no_bid) * 100))
    else:
        if not yes_bids:
            raise RuntimeError("No YES bids available")
        best_yes_bid = float(yes_bids[-1][0])
        ask_cents = int(round((1.0 - best_yes_bid) * 100))

    return max(1, min(99, ask_cents))

def calculate_count_for_budget(ask_cents: int):
    return max(1, math.floor(BUY_MAX_COST_CENTS / ask_cents))

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "state": STATE})

@app.route("/trade", methods=["POST"])
def trade():
    try:
        data = request.get_json(force=True) or {}
        action = data.get("action")

        if action not in {"buy_yes", "buy_no"}:
            return jsonify({"ok": False, "error": "bad action"}), 400

        side = "yes" if action == "buy_yes" else "no"
        bucket = current_15m_bucket()

        if STATE["bucket"] != bucket:
            STATE["bucket"] = bucket
            STATE["traded"] = False
            STATE["side"] = None

        if STATE["traded"]:
            return jsonify({
                "ok": True,
                "blocked": True,
                "reason": "already traded this 15m bucket",
                "bucket": bucket,
                "locked_side": STATE["side"],
                "requested_side": side
            }), 200

        ticker = get_current_ticker()
        ask_cents = get_implied_ask_cents(ticker, side)
        count = calculate_count_for_budget(ask_cents)

        payload = {
            "ticker": ticker,
            "action": "buy",
            "side": side,
            "count": count,
            "client_order_id": str(uuid.uuid4()),
            "time_in_force": "fill_or_kill",
            "buy_max_cost": BUY_MAX_COST_CENTS
        }

        if side == "yes":
            payload["yes_price"] = ask_cents
        else:
            payload["no_price"] = ask_cents

        path = "/portfolio/orders"
        r = requests.post(
            BASE + path,
            json=payload,
            headers=headers("POST", path),
            timeout=5
        )

        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text}

        if not r.ok:
            return jsonify({
                "ok": False,
                "stage": "kalshi",
                "status_code": r.status_code,
                "ticker": ticker,
                "payload": payload,
                "body": body
            }), 200

        STATE["traded"] = True
        STATE["side"] = side

        return jsonify({
            "ok": True,
            "blocked": False,
            "bucket": bucket,
            "ticker": ticker,
            "side": side,
            "ask_cents": ask_cents,
            "count": count,
            "payload": payload,
            "body": body
        }), 200

    except Exception as e:
        return jsonify({
            "ok": False,
            "stage": "python",
            "error": str(e)
        }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
