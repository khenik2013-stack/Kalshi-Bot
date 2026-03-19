import os
import requests
from flask import Flask, request, jsonify
from cryptography.hazmat.primitives import serialization

app = Flask(__name__)

KALSHI_BASE_URL = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2").rstrip("/")
KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID")
KALSHI_PRIVATE_KEY_PEM = os.getenv("KALSHI_PRIVATE_KEY_PEM")
KALSHI_SERIES_PREFIX = os.getenv("KALSHI_SERIES_PREFIX", "KXBTC15M")

def load_private_key():
    if not KALSHI_PRIVATE_KEY_PEM:
        return None, "Missing KALSHI_PRIVATE_KEY_PEM"

    try:
        pem = KALSHI_PRIVATE_KEY_PEM.replace("\\n", "\n").strip()
        key = serialization.load_pem_private_key(
            pem.encode("utf-8"),
            password=None
        )
        return key, None
    except Exception as e:
        return None, f"Private key load failed: {str(e)}"

private_key, private_key_error = load_private_key()

def get_current_btc_15m_ticker():
    url = f"{KALSHI_BASE_URL}/markets"
    params = {
        "status": "open",
        "limit": 200
    }

    resp = requests.get(url, params=params, timeout=8)
    resp.raise_for_status()
    data = resp.json()

    markets = data.get("markets") or data.get("data") or []

    candidates = []
    for m in markets:
        ticker = m.get("ticker", "")
        if not ticker.startswith(KALSHI_SERIES_PREFIX):
            continue

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

    candidates.sort(key=lambda x: x["close_ts"] if x["close_ts"] else 10**18)
    return candidates[0]["ticker"]

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "has_api_key": bool(KALSHI_API_KEY_ID),
        "has_private_key_env": bool(KALSHI_PRIVATE_KEY_PEM),
        "private_key_loaded": private_key is not None,
        "private_key_error": private_key_error,
        "series_prefix": KALSHI_SERIES_PREFIX,
        "base_url": KALSHI_BASE_URL
    })

@app.route("/trade", methods=["POST"])
def trade():
    data = request.get_json(force=True) or {}

    if not KALSHI_API_KEY_ID:
        return jsonify({
            "ok": False,
            "stage": "config",
            "error": "Missing KALSHI_API_KEY_ID"
        }), 500

    if private_key is None:
        return jsonify({
            "ok": False,
            "stage": "config",
            "error": private_key_error or "Private key failed to load"
        }), 500

    try:
        market_ticker = get_current_btc_15m_ticker()
        return jsonify({
            "ok": True,
            "stage": "ticker_lookup",
            "received": data,
            "used_ticker": market_ticker
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "stage": "ticker_lookup",
            "error": str(e)
        }), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
