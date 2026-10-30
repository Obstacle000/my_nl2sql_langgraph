import json
import time

import httpx

BASE = "http://127.0.0.1:8000"


def ask(c, h, ds, q):
    frames = []
    with c.stream("POST", "/api/query", headers=h, json={"dataset_id": ds, "question": q}) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                frames.append(json.loads(line[6:]))
    res = [f for f in frames if f.get("type") == "result"]
    if not res:
        print("  无结果帧，帧数:", len(frames), frames[-1:] if frames else "")
        return None
    r0 = res[0]
    print(f"  hit={r0.get('hit_cache')} kind={r0.get('cache_kind')} frames={len(frames)}")
    print("  SQL:", r0.get("sql"))
    return r0


def main() -> None:
    u = f"sem{int(time.time()) % 100000}"
    c = httpx.Client(base_url=BASE, timeout=180)
    c.post("/api/auth/register", json={"username": u, "password": "123456"})
    tok = c.post("/api/auth/login", json={"username": u, "password": "123456"}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    ds = c.post("/api/datasets", json={"name": "语义缓存测试"}, headers=h).json()["dataset_id"]
    with open("smoke_orders.csv", "rb") as f:
        c.post(f"/api/datasets/{ds}/tables", headers=h, files={"file": ("o.csv", f, "text/csv")}, data={"name": "订单"})

    print("① 首次（应为 miss）")
    ask(c, h, ds, "华北地区的订单总额是多少")
    print("② 原样再问（应为 exact）")
    ask(c, h, ds, "华北地区的订单总额是多少")
    print("③ 换种说法（应为 semantic，若向量足够近）")
    ask(c, h, ds, "华北地区订单总金额是多少")


if __name__ == "__main__":
    main()
