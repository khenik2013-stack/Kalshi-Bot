import os
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

@app.route("/trade", methods=["POST"])
def trade():
    data = request.get_json(force=True) or {}

    print("Received request:", data)

    return jsonify({
        "ok": True,
        "received": data
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
