import os
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/trade", methods=["POST"])
def trade():
    data = request.get_json(force=True)

    action = data.get("action")
    amount = data.get("amount", 10)

    print(f"Received trade: {action} for ${amount}")

    # TEMP (we will connect Kalshi next)
    return jsonify({
        "status": "received",
        "action": action,
        "amount": amount
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
