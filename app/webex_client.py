# ==============================================================================
# Part 4: Webex REST API Client
# ทำไมต้องมีไฟล์นี้:
# ห่อหุ้มการเรียกใช้งาน Webex REST API (https://webexapis.com/v1)
# จัดการ Bearer Token Authentication, การตั้งค่า Header และการเชื่อมต่อ HTTP
# ==============================================================================

import os
import requests

WEBEX_API_BASE = 'https://webexapis.com/v1'


class WebexClient:
    def __init__(self, token=None, session=None):
        # ทำไมต้องดึงจาก WEBEX_BOT_TOKEN: เพื่อไม่ให้มีการ Hardcode Token ลงในซอร์สโค้ด
        self.token = token or os.getenv("WEBEX_BOT_TOKEN")
        if not self.token:
            raise PermissionError("Webex bot token is required")
        # ใช้ requests.Session() เพื่อ reuse TCP connection ช่วยเพิ่มความเร็ว
        self.session = session or requests.Session()

    @property
    def headers(self):
        """Header สำหรับยืนยันตัวตนด้วย Bearer Token กับ Webex API"""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def get_message(self, message_id):
        """
        ดึงรายละเอียดของข้อความจาก Webex (roomId, mentionedPeople, files)
        ทำไมต้องมี timeout=10: ป้องกันโปรแกรมค้างหาก Webex API ตอบสนองช้า
        """
        url = f"{WEBEX_API_BASE}/messages/{message_id}"
        resp = self.session.get(url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def download_file(self, file_url):
        """
        ดาวน์โหลดไฟล์แนบ (YAML) จาก Webex Storage โดยใช้ Bot Token
        """
        headers = {"Authorization": f"Bearer {self.token}"}
        resp = self.session.get(file_url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.content

    def send_message(self, room_id, text):
        """
        ส่งข้อความตอบกลับไปยังห้อง Webex (roomId เดียวกับที่ได้รับคำขอ)
        ทำไม: บอตต้องตอบผลลัพธ์ JSON กลับไปให้ผู้ใช้ในห้องเดิม
        """
        url = f"{WEBEX_API_BASE}/messages"
        payload = {
            "roomId": room_id,
            "text": text,
        }
        resp = self.session.post(url, headers=self.headers, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
