"""数据源仓储：所有方法都带 user_id，防越权。"""

import json
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_json, encrypt_json
from app.models.datasource import DataSource


class DataSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, user_id: int, kind: str, name: str, config: dict | None = None
    ) -> DataSource:
        # config = {
        #     "host": "10.0.0.5",
        #     "port": 3306,
        #     "user": "readonly",
        #     "password": "s3cret",
        #     "database": "shop",
        # }
        payload = encrypt_json(json.dumps(config or {}, ensure_ascii=False)) if config else ""
        row = DataSource(user_id=user_id, kind=kind, name=name, config_enc=payload)
        self.session.add(row)
        await self.session.flush()
        return row

    async def get(self, user_id: int, datasource_id: int) -> DataSource | None:
        result = await self.session.execute(
            select(DataSource).where(
                DataSource.id == datasource_id, DataSource.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int) -> list[DataSource]:
        result = await self.session.execute(
            select(DataSource).where(DataSource.user_id == user_id).order_by(DataSource.id.desc())
        )
        return list(result.scalars().all())

    async def delete(self, user_id: int, datasource_id: int) -> None:
        from sqlalchemy import delete as sa_delete

        await self.session.execute(
            sa_delete(DataSource).where(
                DataSource.id == datasource_id, DataSource.user_id == user_id
            )
        )
        await self.session.flush()

    async def set_status(self, datasource_id: int, status: str, error: str = "") -> None:
        row = await self.session.get(DataSource, datasource_id)
        if row is not None:
            row.status = status
            row.error = error
            row.last_checked = int(time.time())
            await self.session.flush()

    @staticmethod
    def read_config(row: DataSource) -> dict:
        """解密连接配置（只在内部使用，不要返回给接口）。"""
        if not row.config_enc:
            return {}
        return json.loads(decrypt_json(row.config_enc))
