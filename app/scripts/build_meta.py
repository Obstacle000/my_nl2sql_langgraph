"""离线建库入口（占位：后续接 dataset 全量重建索引）。"""

import argparse
import asyncio


async def main(config_path: str) -> None:
    print(f"TODO: 按 {config_path} 重建元数据索引")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--conf", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.conf))
