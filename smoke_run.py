"""端到端冒烟：注册 → 登录 → 建数据集 → 上传 CSV → 问数（SSE）。

用法（项目根目录）：
    .venv\\Scripts\\python.exe -B ..\\..\\smoke_run.py   # 或直接放项目根下运行
"""

import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
USERNAME = f"smoke{int(time.time()) % 100000}"
PASSWORD = "123456"


def show(label: str, resp: httpx.Response) -> dict:
    print(f"\n=== {label} === {resp.status_code}")
    try:
        data = resp.json()
        print(json.dumps(data, ensure_ascii=False)[:400])
        return data
    except Exception:
        print(resp.text[:400])
        return {}


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=120) as client:
        show("注册", client.post("/api/auth/register", json={"username": USERNAME, "password": PASSWORD}))
        token = show("登录", client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})).get("access_token", "")
        if not token:
            print("登录失败，退出")
            sys.exit(1)
        headers = {"Authorization": f"Bearer {token}"}

        ds = show("建数据集", client.post("/api/datasets", json={"name": "冒烟数据", "description": "5 行订单"}, headers=headers))
        dataset_id = ds.get("dataset_id")
        if not dataset_id:
            sys.exit(1)

        with open("smoke_orders.csv", "rb") as f:
            files = {"file": ("orders.csv", f, "text/csv")}
            data = {"name": "订单"}
            show("上传 CSV", client.post(f"/api/datasets/{dataset_id}/tables", headers=headers, files=files, data=data))

        print("\n=== 问数（SSE）===")
        with client.stream(
            "POST",
            "/api/query",
            headers={**headers, "Accept": "text/event-stream"},
            json={"dataset_id": dataset_id, "question": "华北地区的订单总额是多少"},
        ) as resp:
            for line in resp.iter_lines():
                if line:
                    print("  ", line[:200])


if __name__ == "__main__":
    main()
