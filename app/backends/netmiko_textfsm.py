# ==============================================================================
# Part 3: Netmiko + TextFSM Backend Adapter
# ทำไมต้องมีไฟล์นี้:
# จัดการสื่อสารกับ Router ผ่าน SSH CLI แบบดั้งเดิม:
# - อ่านสถานะ: รันคำสั่ง show แล้วใช้ TextFSM แปลงข้อความดิบเป็นตารางข้อมูล
# - ลบ Interface: Netmiko เป็น Backend เดียวที่ได้รับมอบหมายให้ทำหน้าที่ delete
#   เพราะคำสั่ง "no interface Loopback..." ใน CLI มีความแน่นอนและเสถียรที่สุด
# ==============================================================================

import os
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException


def _get_device(router):
    """สร้าง device connection config สำหรับเชื่อมต่อไปยัง Cisco Router"""
    return {
        "device_type": "cisco_ios",
        "host": router,
        "username": os.getenv("ROUTER_USER", "cisco"),
        "password": os.getenv("ROUTER_PASS", "cisco"),
        "conn_timeout": 10,
        "read_timeout_override": 10,
    }


def get_interface_state(
    router,
    interface_name,
    netmiko_get=None,
):
    """
    Return normalized interface status using Netmiko + TextFSM.
    ทำไมต้องรัน 2 คำสั่ง:
    1. 'show ip interface': บอก IP, Subnet Prefix และสถานะ Link (Up/Admin Down)
    2. 'show interfaces description': บอกข้อความ Description ที่ตั้งไว้
    """
    try:
        # netmiko_get ถูกจำลองในการทดสอบเพื่อคืน tuple (ip_info, descriptions)
        if netmiko_get is not None:
            ip_info, descriptions = netmiko_get(router, interface_name)
        else:
            with ConnectHandler(**_get_device(router)) as conn:
                ip_info = conn.send_command(f"show ip interface {interface_name}", use_textfsm=True)
                descriptions = conn.send_command("show interfaces description", use_textfsm=True)
                if isinstance(ip_info, str):
                    ip_info = []
                if isinstance(descriptions, str):
                    descriptions = []
    except (PermissionError, NetmikoAuthenticationException):
        return {"status": "error", "result": "authentication_failed"}
    except (ConnectionError, NetmikoTimeoutException, TimeoutError):
        return {"status": "error", "result": "connection_failed"}
    except Exception:
        return {"status": "error", "result": "backend_failed"}

    # ถ้า ip_info ว่าง แปลว่า Router ไม่มี interface นี้ -> not_found
    if not ip_info:
        return {"status": "ok", "result": "not_found", "interface": None}

    ip_record = ip_info[0]
    link_status = ip_record.get("link_status", "").lower()
    # ทำไม: ถ้าผลลัพธ์มีคำว่า "administratively down" แสดงว่าถูก shutdown -> admin_state: down
    admin_state = "down" if "admin" in link_status else "up"

    ip_addr = ip_record["ip_address"][0]
    prefix = ip_record["prefix_length"][0]
    ipv4 = f"{ip_addr}/{prefix}"

    # ทำไมต้องแปลงชื่อย่อ Loopback123 เป็น Lo123:
    # คำสั่ง 'show interfaces description' ของ Cisco มักย่อชื่อพอร์ต เช่น Loopback123 -> Lo123
    # โค้ดนี้จึงต้องรองรับทั้งชื่อเต็มและชื่อย่อ เพื่อให้จับคู่ Description ได้ถูกต้องเสมอ
    short_name = "Lo" + interface_name[len("Loopback"):] if interface_name.startswith("Loopback") else interface_name
    desc_val = None
    for desc_entry in descriptions:
        port = desc_entry.get("port", "")
        if port in (interface_name, short_name):
            desc_val = desc_entry.get("description")
            break

    return {
        "status": "ok",
        "result": "found",
        "interface": {
            "name": interface_name,
            "ipv4": ipv4,
            "description": desc_val,
            "admin_state": admin_state,
        },
    }


def delete_interface(
    router,
    interface_name,
    netmiko_delete=None,
):
    """
    Delete an interface using Netmiko.
    ทำไมต้องมีเงื่อนไข not_found:
    เพื่อให้การลบมีคุณสมบัติ Idempotency (ถ้า interface ถูกลบไปแล้ว สั่งลบซ้ำอีกครั้ง
    จะต้องไม่พัง และตอบกลับว่า not_found พร้อม interface: null เพื่อยืนยันว่าไม่มีอยู่แล้วจริง)
    """
    # กรณี Unit Test (มี mock netmiko_delete ส่งเข้ามา)
    if netmiko_delete is not None:
        try:
            res = netmiko_delete(router, interface_name)
        except PermissionError:
            return {"status": "error", "result": "authentication_failed"}
        except ConnectionError:
            return {"status": "error", "result": "connection_failed"}
        except Exception:
            return {"status": "error", "result": "backend_failed"}

        if res == "not_found":
            return {"status": "ok", "result": "not_found", "interface": None}
        if res == "deleted":
            return {"status": "ok", "result": "deleted"}
        return {"status": "error", "result": "backend_failed"}

    # กรณียิง Router จริง (Live Mode) ตาม Spec 324-329:
    # 1. ตรวจก่อนว่า interface มีอยู่ไหม
    status_resp = get_interface_state(router, interface_name)
    if status_resp.get("status") == "error":
        return status_resp
    if status_resp.get("result") == "not_found":
        return {"status": "ok", "result": "not_found", "interface": None}

    # 2. ถ้ามีอยู่ ให้ส่งคำสั่ง no interface <name> เข้า Router จริง
    try:
        with ConnectHandler(**_get_device(router)) as conn:
            conn.send_config_set([f"no interface {interface_name}"])
    except (PermissionError, NetmikoAuthenticationException):
        return {"status": "error", "result": "authentication_failed"}
    except (ConnectionError, NetmikoTimeoutException, TimeoutError):
        return {"status": "error", "result": "connection_failed"}
    except Exception:
        return {"status": "error", "result": "backend_failed"}

    # 3. ตรวจสอบยืนยันอีกครั้งว่าถูกลบไปแล้วจริง
    verify_resp = get_interface_state(router, interface_name)
    if verify_resp.get("result") == "not_found":
        return {"status": "ok", "result": "deleted"}

    return {"status": "error", "result": "backend_failed"}