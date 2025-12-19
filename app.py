# visits_api.py
from flask import Flask, request, jsonify
import aiohttp
import asyncio
import json
from byte import encrypt_api, Encrypt_ID
from visit_count_pb2 import Info  # your generated protobuf class
import time

app = Flask(__name__)

def load_tokens(server_name):
    try:
        if server_name == "IND":
            path = "token_ind.json"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            path = "token_sac.json"
        else:
            path = "token_bd.json"

        with open(path, "r") as f:
            data = json.load(f)

        tokens = [item["token"] for item in data if "token" in item and item["token"] not in ["", "N/A"]]
        return tokens
    except Exception as e:
        app.logger.error(f"❌ Token load error for {server_name}: {e}")
        return []

def get_url(server_name):
    if server_name == "IND":
        return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif server_name in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    else:
        return "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"

def parse_protobuf_response(response_data):
    try:
        info = Info()
        info.ParseFromString(response_data)
        
        player_data = {
            "uid": info.AccountInfo.UID if info.AccountInfo.UID else 0,
            "nickname": info.AccountInfo.PlayerNickname if info.AccountInfo.PlayerNickname else "",
            "likes": info.AccountInfo.Likes if info.AccountInfo.Likes else 0,
            "region": info.AccountInfo.PlayerRegion if info.AccountInfo.PlayerRegion else "",
            "level": info.AccountInfo.Levels if info.AccountInfo.Levels else 0
        }
        return player_data
    except Exception as e:
        app.logger.error(f"❌ Protobuf parsing error: {e}")
        return None

async def do_post(session, url, token, data):
    headers = {
        "ReleaseVersion": "OB51",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": url.replace("https://", "").split("/")[0]
    }
    try:
        # small per-request timeout
        async with session.post(url, headers=headers, data=data, ssl=False, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                response_data = await resp.read()
                return True, response_data
            else:
                return False, None
    except Exception as e:
        # log less verbosely for speed; Flask logger is sync so use app.logger
        app.logger.debug(f"visit error: {e}")
        return False, None

async def worker(session, url, tokens, uid, data, target_success, counters, lock, first_success_holder):
    """
    Continuously send requests until target_success reached.
    counters: dict with 'success' and 'sent' ints (shared)
    first_success_holder: dict to hold {'response': bytes or None}
    """
    ntokens = len(tokens)
    if ntokens == 0:
        return

    while True:
        # quick stop check
        async with lock:
            if counters['success'] >= target_success:
                return

            # compute token index and increment sent
            token_index = counters['sent'] % ntokens
            counters['sent'] += 1

        token = tokens[token_index]

        ok, resp = await do_post(session, url, token, data)

        if ok:
            async with lock:
                counters['success'] += 1
                # store first successful response if not already set
                if first_success_holder['response'] is None and resp is not None:
                    first_success_holder['response'] = resp

        # optional: tiny sleep to yield (tweak based on load)
        # await asyncio.sleep(0)

async def run_visits(tokens, uid, server_name, target_success, concurrency):
    url = get_url(server_name)
    connector = aiohttp.TCPConnector(limit=0)  # unlimited concurrent connections (bounded by OS)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=10)
    counters = {'success': 0, 'sent': 0}
    lock = asyncio.Lock()
    first_success_holder = {'response': None}

    # precompute encrypted payload once
    encrypted = encrypt_api("08" + Encrypt_ID(str(uid)) + "1801")
    data = bytes.fromhex(encrypted)

    # create session once
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # spawn worker tasks
        workers = []
        # limit concurrency to target_success (no need to spawn more workers than required)
        nworkers = min(max(1, int(concurrency)), max(1, target_success))
        for _ in range(nworkers):
            workers.append(asyncio.create_task(worker(session, url, tokens, uid, data, target_success, counters, lock, first_success_holder)))

        # wait for all workers to finish (they exit once counters['success'] >= target_success)
        start = time.time()
        await asyncio.gather(*workers)
        elapsed = time.time() - start

    return counters['success'], counters['sent'], first_success_holder['response'], elapsed

@app.route('/visits', methods=['GET'])
def visits_endpoint():
    # Query parameters
    try:
        uid = int(request.args.get('uid', '0'))
        server = request.args.get('server_name', 'IND').upper()
        target_success = int(request.args.get('visit', '1000'))
        concurrency = int(request.args.get('concurrency', '500'))  # default 500
    except Exception as e:
        return jsonify({"error": "Invalid parameters", "detail": str(e)}), 400

    if uid <= 0 or target_success <= 0:
        return jsonify({"error": "uid and visit must be positive integers"}), 400

    tokens = load_tokens(server)
    if not tokens:
        return jsonify({"error": "❌ No valid tokens found"}), 500

    # safety cap: don't allow absurdly large concurrency by default
    if concurrency > 5000:
        concurrency = 5000

    app.logger.info(f"🚀 Sending {target_success} visits to UID {uid} on server {server} using {len(tokens)} tokens (concurrency={concurrency})")

    # run async workload
    total_success, total_sent, first_resp, elapsed = asyncio.run(run_visits(tokens, uid, server, target_success, concurrency))

    if first_resp:
        player_info = parse_protobuf_response(first_resp)
        player_info_response = {
            "fail": max(0, target_success - total_success),
            "level": player_info.get("level", 0),
            "likes": player_info.get("likes", 0),
            "nickname": player_info.get("nickname", ""),
            "region": player_info.get("region", ""),
            "success": total_success,
            "uid": player_info.get("uid", 0),
            "total_sent_attempts": total_sent,
            "elapsed_seconds": round(elapsed, 2)
        }
        return jsonify(player_info_response), 200
    else:
        return jsonify({
            "error": "Could not decode player information",
            "success": total_success,
            "total_sent_attempts": total_sent,
            "elapsed_seconds": round(elapsed, 2)
        }), 500

if __name__ == "__main__":
    # For production, run under gunicorn/uvicorn+ASGI or use a reverse proxy.
    app.run(host="0.0.0.0", port=9000, threaded=True)
