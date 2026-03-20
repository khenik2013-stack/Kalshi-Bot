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

BASE = os.getenv("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2").rstrip("/")
KEY_ID = os.getenv("KALSHI_API_KEY_ID")
KEY_PEM = os.getenv("KALSHI_PRIVATE_KEY_PEM").replace("\\n", "\n").strip()
SERIES = "KXBTC15M"

COUNT = 1
YES_PRICE = 50
NO_PRICE = 50

PRIVATE_KEY = serialization.load_pem_private_key(
    KEY_PEM.encode(),
    password=None
)

def headers(method, path):
    ts = str(int(time.time()*1000))
    sign_path = urlparse(BASE + path).path
    msg = ts + method + sign_path

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

def get_ticker():
    r = requests.get(f"{BASE}/markets", params={
        "series_ticker": SERIES,
        "status": "open",
        "limit": 10
    }, timeout=5)

    r.raise_for_status()
    m = r.json()["markets"]

    m.sort(key=lambda x: x.get("close_time", "9999"))
    return m[0]["ticker"]

@app.route("/trade", methods=["POST"])
def trade():
    data = request.get_json(force=True)
    action = data.get("action")

    if action not in ["buy_yes", "buy_no"]:
        return jsonify({"error": "bad action"}), 400

    ticker = get_ticker()

    payload = {
        "ticker": ticker,
        "action": "buy",
        "side": "yes" if action=="buy_yes" else "no",
        "count": COUNT,
        "client_order_id": str(uuid.uuid4()),
        "time_in_force": "fill_or_kill"
    }

    if action=="buy_yes":
        payload["yes_price"]=YES_PRICE
    else:
        payload["no_price"]=NO_PRICE

    path = "/portfolio/orders"
    r = requests.post(
        BASE+path,
        json=payload,
        headers=headers("POST", path),
        timeout=5
    )

    return jsonify({
        "ok": r.ok,
        "ticker": ticker,
        "resp": r.json() if r.text else {}
    })

@app.route("/health")
def health():
    return {"ok": True}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",10000)))
