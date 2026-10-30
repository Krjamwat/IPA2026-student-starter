# ==============================================================================
# Part 4: Webhook Server & Event Handler
# ทำไมต้องมีไฟล์นี้:
# ไฟล์นี้คือ Main Server ที่เปิดรับ Webhook จาก Webex:
# 1. ให้บริการ GET /health สำหรับตรวจสอบสถานะของ Container (Health Check)
# 2. ให้บริการ POST /webhook สำหรับรับ Event จาก Webex โดยจะตอบ HTTP 200 ทันที
#    แล้วนำงานไปเข้าคิวประมวลผลเบื้องหลัง เพื่อไม่ให้ Webex ตัดการเชื่อมต่อ (Timeout)
# 3. จัดการคิวงานแบบ Sequential (max_workers=1) เพื่อไม่ให้คำสั่งที่ยิงไป Router ชนกัน
# ==============================================================================

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from app.integration import process_request
from app.webex_client import WEBEX_API_BASE, WebexClient


class WebexEventHandler:
    def __init__(self, client, bot_person_id, processor=None):
        self.client = client
        self.bot_person_id = bot_person_id
        self.processor = processor or process_request

    def handle_event(self, event):
        """
        ประมวลผล Event ที่ส่งมาจาก Webex Webhook
        """
        # 1. กรองเฉพาะ Event ที่เกี่ยวกับข้อความใหม่เท่านั้น
        if not isinstance(event, dict):
            return None
        if event.get("resource") != "messages" or event.get("event") != "created":
            return None

        data = event.get("data", {})
        if not isinstance(data, dict):
            return None

        message_id = data.get("id")
        if not message_id:
            return None

        # ทำไมต้องเช็ก personId ตรงนี้ (Early Filter):
        # ถ้าข้อความนี้ถูกส่งโดยตัวบอตเอง ให้หยุดทันทีเพื่อป้องกัน Infinite Loop
        # (บอตส่งผลลัพธ์ -> Webex แจ้ง event -> บอตประมวลผลตัวเอง -> บอตส่งซ้ำไม่รู้จบ)
        if data.get("personId") == self.bot_person_id:
            return None

        # ดึงรายละเอียดข้อความจริงจาก Webex API
        message = self.client.get_message(message_id)

        # ตรวจสอบซ้ำอีกครั้งว่าผู้ส่งไม่ใช่ตัวบอตเอง
        if message.get("personId") == self.bot_person_id:
            return None

        room_id = message.get("roomId")
        mentioned_people = message.get("mentionedPeople", [])
        files = message.get("files", [])

        # 2. ตรวจสอบไฟล์แนบ:
        # ทำไม: spec กำหนดว่าต้องแนบไฟล์ YAML เพียง "1 ไฟล์เท่านั้น"
        # หากแนบมากกว่า 1 ไฟล์ ต้องปฏิเสธทันทีก่อนดาวน์โหลด
        if len(files) > 1:
            result = {"status": "error", "result": "multiple_attachments"}
        elif len(files) == 1:
            # ดาวน์โหลดไฟล์แล้วบันทึกลง Temporary Directory ชั่วคราว
            # ทำไมต้องมี try/finally: เพื่อรับประกันว่าไฟล์ temp จะถูกลบทิ้งเสมอ แม้เกิด exception
            file_bytes = self.client.download_file(files[0])
            with TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir) / "request.yaml"
                tmp_path.write_bytes(file_bytes)
                try:
                    result = self.processor(mentioned_people, tmp_path, self.bot_person_id)
                finally:
                    if tmp_path.exists():
                        tmp_path.unlink()
        else:
            # กรณีไม่มีไฟล์แนบ ส่ง None ไปให้ processor แจ้ง error "no_yaml"
            result = self.processor(mentioned_people, None, self.bot_person_id)

        # 3. ตอบกลับข้อความผลลัพธ์ (JSON) ไปยังห้องเดิม (room_id)
        # ทำไม: บอตต้องตอบห้องเดียวกับที่ได้รับข้อความ ไม่ฮาร์ดโค้ดห้องใดห้องหนึ่ง
        if room_id and result is not None:
            self.client.send_message(room_id, json.dumps(result))

        return result


def make_http_handler(submit_event):
    """
    สร้าง HTTP Request Handler สำหรับรับ GET /health และ POST /webhook
    """
    class RequestHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Endpoint สำหรับ Health Check ของ Docker และ CI
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "result": "healthy"}).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            # Endpoint รับ Webhook จาก Webex
            if self.path == "/webhook":
                length = int(self.headers.get("Content-Length", 0))
                # spec กำหนดขนาด payload ระหว่าง 1 ถึง 1,000,000 bytes
                if length < 1 or length > 1_000_000:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "result": "invalid_event"}).encode())
                    return

                raw_body = self.rfile.read(length)
                try:
                    event_data = json.loads(raw_body.decode("utf-8"))
                    if not isinstance(event_data, dict):
                        raise ValueError()
                except Exception:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "error", "result": "invalid_event"}).encode())
                    return

                # ทำไมต้องตอบ HTTP 200 ทันที:
                # Webex กำหนดว่า Webhook Server ต้องตอบกลับ HTTP 200 ภายในไม่กี่วินาที
                # มิฉะนั้น Webex จะมองว่าระบบล่ม (Timeout) และส่งคำขอซ้ำ
                # การคุยกับ Router ใช้เวลานาน เราจึงตอบ 200 'accepted' ก่อน แล้วนำ event เข้าคิวเบื้องหลัง
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "result": "accepted"}).encode())

                # ส่ง Event เข้าคิวเบื้องหลัง (Background Worker)
                submit_event(event_data)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            # ปิด Default logging เพื่อไม่ให้มีข้อความขยะรกในหน้าจอ terminal
            pass

    return RequestHandler


def main():
    # โหลดค่าจากไฟล์ .env อัตโนมัติ (หากมี) เพื่อให้อ่าน Token เมื่อรัน python ใน terminal ได้ทันที
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))

    token = os.getenv("WEBEX_BOT_TOKEN")
    client = WebexClient(token=token)

    # ดึง personId ของตัวบอตเองผ่าน /people/me เพื่อใช้ระบุตัวตนในการเช็ก Mention
    resp = client.session.get(f"{WEBEX_API_BASE}/people/me", headers=client.headers, timeout=10)
    resp.raise_for_status()
    bot_person_id = resp.json().get("id")

    handler = WebexEventHandler(client, bot_person_id)

    # ทำไมต้องใช้ max_workers=1:
    # Router ในแล็บไม่รองรับการคอนฟิกพร้อม ๆ กันหลายคำสั่ง (Concurrent Changes)
    # การตั้ง max_workers=1 จะทำให้คำขอทั้งหมดถูกประมวลผลเรียงตามลำดับ (Sequential) คำสั่งจะไม่ตีกัน
    executor = ThreadPoolExecutor(max_workers=1)

    host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.getenv("WEBHOOK_PORT", 8000))

    server = ThreadingHTTPServer((host, port), make_http_handler(lambda ev: executor.submit(handler.handle_event, ev)))
    print(f"Webhook server started at http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        executor.shutdown(wait=True)


if __name__ == "__main__":
    main()
