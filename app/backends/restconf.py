# ==============================================================================
# Part 3: RESTCONF Backend Adapter
# ทำไมต้องมีไฟล์นี้:
# จัดการสื่อสารกับ Router Cisco IOS XE ผ่าน RESTCONF (HTTP over TLS):
# - อ่านสถานะ (GET): ใช้โมเดลมาตรฐานสากล IETF (ietf-interfaces)
# - คอนฟิกจริง (PUT): ใช้โมเดลเฉพาะของซิสโก้ Cisco Native (Cisco-IOS-XE-native)
# ==============================================================================

from ipaddress import IPv4Interface
import os
import requests
from app.backends import planning


def _get_auth():
    """ดึง Username และ Password สำหรับเข้า Router จาก Environment Variable"""
    return (os.getenv("ROUTER_USER", "cisco"), os.getenv("ROUTER_PASS", "cisco"))


def get_interface_state(
    router,
    interface_name,
    http_get=None,
):
    """
    Return normalized interface status using RESTCONF.
    ทำไมใช้ URL นี้: /restconf/data/ietf-interfaces:interfaces/interface=<name>
    เป็น path มาตรฐาน IETF สำหรับอ่านค่า Interface แบบเป็นกลาง
    """
    url = f"https://{router}/restconf/data/ietf-interfaces:interfaces/interface={interface_name}"
    try:
        # http_get ถูกส่งเข้ามาตอนรัน Unit Test เพื่อจำลอง HTTP response โดยไม่ต้องต่อ Router จริง
        if http_get is not None:
            resp = http_get(url)
        else:
            headers = {"Accept": "application/yang-data+json"}
            resp = requests.get(
                url,
                headers=headers,
                auth=_get_auth(),
                verify=False,
                timeout=10,
            )
    except PermissionError:
        return {"status": "error", "result": "authentication_failed"}
    except ConnectionError:
        return {"status": "error", "result": "connection_failed"}
    except Exception:
        return {"status": "error", "result": "backend_failed"}

    # ทำไม 404 ถึงไม่ใช่ error:
    # HTTP 404 หมายความว่าติดต่อ Router ได้ แต่ยังไม่มี Interface นี้อยู่บนอุปกรณ์
    # จึงคืนผลเป็น ok พร้อม result: not_found และ interface: null เพื่อนำไปใช้กับ plan (create) ต่อไป
    if resp.status_code == 404:
        return {"status": "ok", "result": "not_found", "interface": None}

    # กรณี Authentication/Authorization ไม่ผ่าน (รหัสผ่านผิด)
    if resp.status_code in (401, 403):
        return {"status": "error", "result": "authentication_failed"}

    if resp.status_code != 200:
        return {"status": "error", "result": "backend_failed"}

    # ทำไมต้องแปลงข้อมูล (Normalization):
    # ข้อมูลดิบจาก RESTCONF เป็น IETF YANG structure ซับซ้อน จึงต้องแปลงให้อยู่ในรูปทรงมาตรฐาน
    # ที่ทุก backend ให้ผลลัพธ์เหมือนกัน: {name, ipv4, description, admin_state}
    data = resp.json().get("ietf-interfaces:interface", {})
    name = data.get("name", interface_name)
    description = data.get("description")
    enabled = data.get("enabled", True)
    admin_state = "up" if enabled else "down"

    # แปลง IP และ Netmask ให้อยู่ในรูป CIDR notation เช่น 172.23.123.1/32
    ipv4_addresses = data.get("ietf-ip:ipv4", {}).get("address", [])
    if ipv4_addresses:
        ip = ipv4_addresses[0].get("ip")
        netmask = ipv4_addresses[0].get("netmask")
        ipv4 = str(IPv4Interface(f"{ip}/{netmask}"))
    else:
        ipv4 = None

    return {
        "status": "ok",
        "result": "found",
        "interface": {
            "name": name,
            "ipv4": ipv4,
            "description": description,
            "admin_state": admin_state,
        },
    }


def plan_interface(
    router,
    desired_interface,
    http_get=None,
):
    """
    Return create/update/no_change plan using RESTCONF status.
    ทำไม: ส่งต่อให้ planning.plan_interface จัดการ เพื่อใช้ logic คำนวณ diff กลางร่วมกัน
    """
    return planning.plan_interface(
        router,
        desired_interface,
        lambda r, name: get_interface_state(r, name, http_get=http_get),
    )


def apply_interface(
    router,
    desired_interface,
    http_put=None,
):
    """
    Apply complete desired interface state using RESTCONF.
    ทำไมใช้ Cisco Native Model และคำสั่ง HTTP PUT:
    1. HTTP PUT เป็นการแทนที่ Resource ทั้งหมด (Complete Replacement)
    2. ช่วยลบ IP Address เก่าทิ้งโดยสมบูรณ์ ไม่ให้ค้างเป็น Secondary IP
    3. Loopback key ใน native model ของ Cisco จะใช้เฉพาะตัวเลข (เช่น Loopback123 -> 123)
    """
    number = int(desired_interface["name"][len("Loopback"):])
    url = f"https://{router}/restconf/data/Cisco-IOS-XE-native:native/interface/Loopback={number}"

    iface = IPv4Interface(desired_interface["ipv4"])
    payload = {
        "Cisco-IOS-XE-native:Loopback": {
            "name": number,
            "description": desired_interface["description"],
            "ip": {
                "address": {
                    "primary": {
                        "address": str(iface.ip),
                        "mask": str(iface.network.netmask),
                    }
                }
            },
        }
    }

    # ทำไม admin_state == "down" ต้องใส่ "shutdown": [None]:
    # ในโมเดล YANG ของ Cisco Native แท็ก shutdown เป็น empty container
    # ซึ่งในรูปแบบ JSON จะแทนด้วย [null] (หรือ [None] ใน Python)
    # ถ้าสถานะเป็น "up" ให้ละเว้นฟิลด์นี้ออกไป ซึ่งเทียบเท่ากับคำสั่ง "no shutdown"
    if desired_interface["admin_state"] == "down":
        payload["Cisco-IOS-XE-native:Loopback"]["shutdown"] = [None]

    try:
        if http_put is not None:
            resp = http_put(url, json=payload)
        else:
            headers = {
                "Accept": "application/yang-data+json",
                "Content-Type": "application/yang-data+json",
            }
            resp = requests.put(
                url,
                headers=headers,
                json=payload,
                auth=_get_auth(),
                verify=False,
                timeout=10,
            )
    except PermissionError:
        return {"status": "error", "result": "authentication_failed"}
    except ConnectionError:
        return {"status": "error", "result": "connection_failed"}
    except Exception:
        return {"status": "error", "result": "backend_failed"}

    # HTTP 200 (OK), 201 (Created), 204 (No Content) ล้วนถือว่าคอนฟิกสำเร็จ
    if resp.status_code in (200, 201, 204):
        return {"status": "ok", "result": "applied"}
    if resp.status_code in (401, 403):
        return {"status": "error", "result": "authentication_failed"}
    return {"status": "error", "result": "backend_failed"}
