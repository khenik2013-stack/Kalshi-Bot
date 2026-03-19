import os
import time
import uuid
import base64
import requests
from urllib.parse import urlparse
from flask import Flask, request, jsonify
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

app = Flask(__name__)

KALSHI_BASE_URL = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID")
KALSHI_PRIVATE_KEY_PEM = os.getenv("KALSHI_PRIVATE_KEY_PEM")

# Series prefix for BTC 15-minute markets
KALSHI_SERIES_PREFIX = os.getenv("KALSHI_SERIES_PREFIX", "KXBTC15M")

KALSHI_COUNT = int(os.getenv("KALSHI_COUNT", "1"))
KALSHI_YES_PRICE = int(os.getenv("KALSHI_YES_PRICE", "50"))
KALSHI_NO_PRICE = int(os.getenv("KALSHI_NO_PRICE", "50"))
KALSHI_TIME_IN_FORCE = os.getenv("KALSHI_TIME_IN_FORCE", "fill_or_kill")

private_key = None
if KALSHI_PRIVATE_KEY_PEM:
    private_key = serialization.load_pem_private_key(
        KALSHI_PRIVATE_KEY_PEM.encode("utf-8"),
        password=None
    )

def kalshi_headers(method: str, endpoint_path: str):
    timestamp_ms = str(int(time.time() * 1000))
    sign_path = urlparse(KALSHI_BASE_URL + endpoint_path).path
    message = timestamp_ms + method.upper() + sign_path

    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )

    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
    }

def get_current_btc_15m_ticker():
    # Public market lookup; production market data can be queried without auth
    url = f"{KALSHI_BASE_URL}/markets"
    params = {
        "status": "open",
        "limit": 200
    }

    resp = requests.get(url, params=params, timeout=8)
    resp.raise_for_status()
    data = resp.json()

    # Kalshi list endpoints are paginated and return arrays of markets.
    # Different responses may use "markets" or "data", so support both.
    markets = data.get("markets") or data.get("data") or []

    candidates = []
    for m in markets:
        ticker = m.get("ticker", "")
        if not ticker.startswith(KALSHI_SERIES_PREFIX):
            continue

        # Prefer a real close timestamp if present
        close_ts = (
            m.get("close_time")
            or m.get("expiration_time")
            or m.get("settlement_time")
            or m.get("latest_expiration_time")
            or 0
        )
        candidates.append({
            "ticker": ticker,
            "close_ts": close_ts
        })

    if not candidates:
        raise RuntimeError(f"No open markets found for series prefix {KALSHI_SERIES_PREFIX}")

    # Choose the soonest-closing currently open BTC 15m market
    candidates.sort(key=lambda x: x["close_ts"] if x["close_ts"] else 10**18)
    return candidates[0]["ticker"]

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/trade", methods=["POST"])
def trade():
    if not all([KALSHI_API_KEY_ID, private_key]):
        return jsonify({
            "ok": False,
            "error": "Missing KALSHI_API_KEY_ID or KALSHI_PRIVATE_KEY_PEM"
        }), 500

    data = request.get_json(force=True) or {}
    action = data.get("action")

    if action not in {"buy_yes", "buy_no"}:
        return jsonify({"ok": False, "error": "Invalid action"}), 400

    try:
        market_ticker = get_current_btc_15m_ticker()
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not find live ticker: {str(e)}"}), 500

    endpoint_path = "/portfolio/orders"
    url = KALSHI_BASE_URL + endpoint_path

    payload = {
        "ticker": market_ticker,
        "action": "buy",
        "side": "yes" if action == "buy_yes" else "no",
        "count": KALSHI_COUNT,
        "client_order_id": str(uuid.uuid4()),
        "time_in_force": KALSHI_TIME_IN_FORCE
    }

    if action == "buy_yes":
        payload["yes_price"] = KALSHI_YES_PRICE
    else:
        payload["no_price"] = KALSHI_NO_PRICE

    headers = kalshi_headers("POST", endpoint_path)
    resp = requests.post(url, json=payload, headers=headers, timeout=8)

    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}

    return jsonify({
        "ok": resp.ok,
        "status_code": resp.status_code,
        "used_ticker": market_ticker,
        "sent_payload": payload,
        "kalshi_response": body
    }), (200 if resp.ok else 500)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
