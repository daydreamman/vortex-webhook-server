from flask import Flask, request, jsonify, render_template
import os
import logging
import queue
import json

app = Flask(__name__)

# 設定日誌格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

# 讀取認證 Token，若未設定環境變數則使用預設值（建議在 GCP Cloud Run 中透過環境變數設定此金鑰）
VORTEX_VERIFICATION_TOKEN = os.getenv("VORTEX_TOKEN", "vortex_default_secure_token")

# 全域變數：儲存最近 50 筆 Webhook 事件（新事件在最前面）
EVENT_HISTORY = []
# 全域變數：所有連接中前端用戶的訊息 Queue 列表
SUBSCRIBERS = []

def broadcast_event(event_data):
    """將新事件存入歷史並廣播給所有連線中的前端"""
    # 存入歷史（最多保留 50 筆）
    EVENT_HISTORY.insert(0, event_data)
    if len(EVENT_HISTORY) > 50:
        EVENT_HISTORY.pop()
        
    # 廣播給所有 active 的 SSE 連線
    for sub_queue in list(SUBSCRIBERS):
        try:
            sub_queue.put(event_data)
        except Exception as e:
            logging.error(f"無法發送事件給訂閱者: {e}")
            if sub_queue in SUBSCRIBERS:
                SUBSCRIBERS.remove(sub_queue)

@app.route('/webhook', methods=['POST'])
def handle_vortex_webhook():
    import time
    from datetime import datetime, timezone

    # 1. 取得原始 Request 資訊（用於偵錯）
    raw_body_str = request.get_data(as_text=True)
    client_token = request.headers.get('X-Vortex-Token')
    
    # 驗證 Token 是否合法
    token_valid = (client_token == VORTEX_VERIFICATION_TOKEN)
    
    # 2. 嘗試解析 JSON
    is_json = True
    payload = {}
    try:
        if request.is_json:
            payload = request.get_json(force=True, silent=True) or {}
        else:
            # 嘗試強行解析 body
            payload = json.loads(raw_body_str)
    except Exception:
        is_json = False
        payload = {}

    # 3. 讀取 VIVOTEK Vortex 警報事件參數 (依自訂 Payload 欄位解析，包含 UTC 與本地 ISO 等多種時間格式)
    utc_time_str = ""
    
    # 優先權 1: UtcISOTime (e.g., "2026-05-29T09:50:00Z")
    utc_iso_val = payload.get("utcISOTime") or payload.get("utc_iso_time")
    if utc_iso_val:
        utc_time_str = utc_iso_val
        
    # 優先權 2: UtcTime (Unix timestamp in seconds/milliseconds)
    if not utc_time_str:
        utc_time_val = payload.get("utcTime") or payload.get("utc_time_val")
        if utc_time_val:
            try:
                ts = float(utc_time_val)
                if ts > 1e11:
                    ts = ts / 1000.0
                utc_time_str = datetime.fromtimestamp(ts, timezone.utc).isoformat()
            except Exception:
                pass
                
    # 優先權 3: LocalISOTime
    if not utc_time_str:
        local_iso_val = payload.get("localISOTime") or payload.get("local_iso_time")
        if local_iso_val:
            utc_time_str = local_iso_val

    # 優先權 4: LocalTime (Unix timestamp)
    local_time_val = payload.get("localTime") or payload.get("local_time")
    if not utc_time_str and local_time_val:
        try:
            ts = float(local_time_val)
            if ts > 1e11:
                ts = ts / 1000.0
            utc_time_str = datetime.fromtimestamp(ts, timezone.utc).isoformat()
        except Exception:
            pass

    # 優先權 5: 當前伺服器時間 Fallback
    if not utc_time_str:
        utc_time_str = datetime.now(timezone.utc).isoformat()

    event_id = payload.get("eventId") or payload.get("event_id") or f"debug_{int(time.time())}"
    event_name = payload.get("eventName") or payload.get("event_name") or ("Raw HTTP Post" if not is_json else "Empty Event")
    device_name = payload.get("deviceName") or payload.get("device_name") or "N/A"
    mac = payload.get("mac") or payload.get("macAddress") or "Unknown MAC"

    event_data = {
        "event_id": event_id,
        "org_name": payload.get("organizationName") or payload.get("organization_name") or payload.get("org_name") or "N/A",
        "org_id": payload.get("organizationId") or payload.get("org_id") or "",
        "event_type": payload.get("eventType") or payload.get("event_type") or "",
        "event_name": event_name,
        "device_name": device_name,
        "device_id": payload.get("deviceId") or payload.get("device_id") or "",
        "mac": mac,
        "device_group_name": payload.get("deviceGroupName") or payload.get("device_group_name") or "",
        "device_group_id": payload.get("deviceGroupId") or payload.get("device_group_id") or payload.get("deviceGroupID") or "",
        "local_time": local_time_val,
        "local_iso_time": payload.get("localISOTime") or payload.get("local_iso_time") or "",
        "utc_time_val": payload.get("utcTime") or payload.get("utc_time_val") or "",
        "utc_iso_time": payload.get("utcISOTime") or payload.get("utc_iso_time") or "",
        "timezone": payload.get("timezone") or "",
        "alarm_id": payload.get("alarmId") or payload.get("alarm_id") or "",
        "profile_name": payload.get("profileName") or payload.get("profile_name") or "",
        "image_face": payload.get("imageFace") or payload.get("image_face") or "",
        "image_person": payload.get("imagePerson") or payload.get("image_person") or "",
        "thumbnail": payload.get("thumbnail") or payload.get("Thumbnail") or "",
        "utc_time": utc_time_str,
        # 偵錯用欄位
        "debug_raw_headers": {k: v for k, v in request.headers.items() if k.lower() != "authorization"},
        "debug_raw_body": raw_body_str,
        "debug_token_valid": token_valid,
        "debug_is_json": is_json,
        "debug_received_token": client_token or "None"
    }

    # 4. 輸出事件日誌
    logging.info("=" * 50)
    logging.info(f"🔔 Webhook 進入 (Token驗證: {token_valid}, 是否JSON: {is_json})")
    logging.info(f"來源 IP: {request.remote_addr}")
    logging.info(f"網頁顯示名稱 (Device): {device_name} (MAC: {mac})")
    logging.info(f"事件內容 (Event): {event_name}")
    logging.info("=" * 50)

    # 5. 廣播給連接的網頁端 (即使驗證失敗或不是 JSON，我們也廣播，讓前端顯示偵錯狀態)
    broadcast_event(event_data)

    # 6. 回應發送端
    if not token_valid:
        return jsonify({
            "status": "warning",
            "message": "Webhook received but verification token failed. Please check X-Vortex-Token header.",
            "expected_token": VORTEX_VERIFICATION_TOKEN,
            "received_token": client_token or "None"
        }), 200

    return jsonify({"status": "success", "message": "Vortex Webhook processed"}), 200

@app.route('/events')
def stream_events():
    """Server-Sent Events (SSE) 串流端點，提供即時推播給網頁"""
    def event_generator():
        # 為當前連接的前端建立一個專屬 Queue
        client_queue = queue.Queue()
        SUBSCRIBERS.append(client_queue)
        
        # 連接建立時，先將當前已有的歷史事件發送給前端
        yield f"event: history\ndata: {json.dumps(EVENT_HISTORY)}\n\n"
        
        try:
            while True:
                try:
                    # 從 Queue 中獲取最新事件，阻塞 15 秒以實現長輪詢
                    event_data = client_queue.get(timeout=15)
                    yield f"event: message\ndata: {json.dumps(event_data)}\n\n"
                except queue.Empty:
                    # 發送 Keep-Alive 註釋，避免 Cloud Run / nginx 逾時斷開
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            # 瀏覽器分頁關閉或斷開連線
            pass
        finally:
            if client_queue in SUBSCRIBERS:
                SUBSCRIBERS.remove(client_queue)
                
    return app.response_class(event_generator(), mimetype='text/event-stream')

@app.route('/thumbnail/<event_id>')
def serve_thumbnail(event_id):
    """將事件中的 Base64 縮圖解碼後，以真實 JPEG 圖片格式回傳"""
    import base64
    from flask import Response

    for evt in EVENT_HISTORY:
        if evt.get("event_id") == event_id and evt.get("thumbnail"):
            try:
                raw_b64 = evt["thumbnail"].strip()
                # 移除 data:image 前綴 (如果有)
                if raw_b64.startswith("data:"):
                    raw_b64 = raw_b64.split(",", 1)[1]
                # 清除空白換行
                raw_b64 = raw_b64.replace("\n", "").replace("\r", "").replace(" ", "")
                img_bytes = base64.b64decode(raw_b64)
                return Response(img_bytes, mimetype='image/jpeg',
                                headers={'Cache-Control': 'public, max-age=3600'})
            except Exception as e:
                logging.error(f"縮圖解碼失敗 event_id={event_id}: {e}")
                return Response("Decode error", status=500)

    return Response("Not found", status=404)

@app.route('/', methods=['GET'])
def index():
    # 渲染儀表板網頁
    return render_template('index.html')

if __name__ == '__main__':
    # 本地測試時執行
    app.run(host='0.0.0.0', port=8080, debug=True)


