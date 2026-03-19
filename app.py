import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

KALSHI_BASE_URL = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")
KALSHI_SERIES_PREFIX = os.getenv("KALSHI_SERIES_PREFIX", "KXBTC15M")

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
    return jsonify({"ok": True})

@app.route("/trade", methods=["POST"])
def trade():
    data = request.get_json(force=True) or {}

    try:
        market_ticker = get_current_btc_15m_ticker()
        return jsonify({
            "ok": True,
            "received": data,
            "used_ticker": market_ticker
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": f"Could not find live ticker: {str(e)}"
        }), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
