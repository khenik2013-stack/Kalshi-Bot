import os
from flask import Flask, request, jsonify
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import base64
import time
import uuid

app = Flask(__name__)

KALSHI_BASE_URL = os.getenv("KALSHI_BASE_URL", "https://demo-api.kalshi.co/trade-api/v2")
KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID")
KALSHI_MARKET_TICKER = os.getenv("KALSHI_MARKET_TICKER")

# Optional: set fixed prices and contract count
KALSHI_COUNT = int(os.getenv("KALSHI_COUNT", "1"))
KALSHI_YES_PRICE = int(os.getenv("KALSHI_YES_PRICE", "50"))
KALSHI_NO_PRICE = int(os.getenv("KALSHI_NO_PRICE", "50"))
KALSHI_TIME_IN_FORCE = os.getenv("KALSHI_TIME_IN_FORCE", "fill_or_kill")

private_key_pem = os.getenv("KALSHI_PRIVATE_KEY_PEM")
private_key = None
if private_key_pem:
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=None
    )

def kalshi_headers(method: str, path: str):
    timestamp_ms = str(int(time.time() * 1000))
    message = timestamp_ms + method.upper() + path
    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    signature_b64 = base64.b64encode(signature).decode("utf-8")
    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY_ID,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": signature_b64,
    }

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/trade", methods=["POST"])
def trade():
    if not all([KALSHI_API_KEY_ID, private_key, KALSHI_MARKET_TICKER]):
        return jsonify({
            "ok": False,
            "error": "Missing KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY_PEM, or KALSHI_MARKET_TICKER"
        }), 500

    data = request.get_json(force=True) or {}
    action = data.get("action")

    if action not in {"buy_yes", "buy_no"}:
        return jsonify({"ok": False, "error": "Invalid action"}), 400

    path = "/portfolio/orders"
    url = KALSHI_BASE_URL + path
    
    payload = {
        "ticker": KALSHI_MARKET_TICKER,
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

    headers = kalshi_headers("POST", path)
    resp = requests.post(url, json=payload, headers=headers, timeout=20)

    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}

    return jsonify({
        "ok": resp.ok,
        "status_code": resp.status_code,
        "sent_payload": payload,
        "kalshi_response": body
    }), (200 if resp.ok else 500)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
