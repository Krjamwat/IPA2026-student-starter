# ==============================================================================
# Part 3: Ansible Backend Adapter
# ทำไมต้องมีไฟล์นี้:
# จัดเตรียมตัวแปร (Variables Dictionary) เพื่อส่งให้ Ansible Playbook
# ในการคอนฟิก Cisco IOS Loopback Interface โดย Ansible จะรองรับเฉพาะ action: apply
# ==============================================================================

from ipaddress import IPv4Interface
import json
import os
import subprocess


def apply_interface(
    router,
    desired_interface,
    run_playbook=None,
):
    """
    Apply complete desired interface state using Ansible.
    ทำไมต้องแตกตัวแปร IPv4 และ Netmask:
    คำสั่ง IOS CLI 'ip address <ip> <netmask>' ต้องการ IP และ Subnet Mask แบบแยกกัน (Dotted-Decimal)
    จึงต้องใช้ IPv4Interface แปลง CIDR เช่น 172.23.123.1/32 เป็น IP: 172.23.123.1 และ Mask: 255.255.255.255
    """
    iface = IPv4Interface(desired_interface["ipv4"])
    variables = {
        "router": router,
        "interface_name": desired_interface["name"],
        "description": desired_interface["description"],
        "ipv4_address": str(iface.ip),
        "netmask": str(iface.network.netmask),
        # แปลง admin_state: down ให้เป็นตัวแปร boolean shutdown: True
        "shutdown": desired_interface["admin_state"] == "down",
    }
    # กรณี Unit Test (มี mock runner)
    if run_playbook is not None:
    # run_playbook ถูก inject เข้ามาในการทดสอบเพื่อตรวจสอบความถูกต้องของตัวแปร
        try:
            run_playbook(variables)
        except PermissionError:
            return {"status": "error", "result": "authentication_failed"}
        except ConnectionError:
            return {"status": "error", "result": "connection_failed"}
        except Exception:
            return {"status": "error", "result": "backend_failed"}
        return {"status": "ok", "result": "applied"}

    # กรณียิง Router จริง (Live Mode)
    cmd = [
        "ansible-playbook",
        "-i", "ansible/inventory.ini",
        "ansible/apply_interface.yml",
        "-e", json.dumps(variables),
    ]
    env = os.environ.copy()
    env["ANSIBLE_HOST_KEY_CHECKING"] = "False"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
    except subprocess.TimeoutExpired:
        return {"status": "error", "result": "connection_failed"}
    except Exception:
        return {"status": "error", "result": "backend_failed"}
    if proc.returncode != 0:
        out = (proc.stdout + proc.stderr).lower()
        if "authentication failed" in out or "permission denied" in out:
            return {"status": "error", "result": "authentication_failed"}
        if "unreachable" in out or "timed out" in out or "connection refused" in out:
            return {"status": "error", "result": "connection_failed"}
        return {"status": "error", "result": "backend_failed"}
    return {"status": "ok", "result": "applied"}