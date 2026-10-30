"""数据源注册表：按 kind 造实例，池子做 LRU 上限，避免连接数爆炸。"""

from collections import OrderedDict

from app.core.errors import NotFoundError
from app.datasources.base import DataSource
from app.datasources.csv_source import CSVDataSource
from app.datasources.mysql_source import MySQLDataSource
from app.repositories.mysql.dataset_repo import DatasetRepository
from app.repositories.mysql.datasource_repo import DataSourceRepository

MAX_CACHED_SOURCES = 20


class DataSourceRegistry:
    """注意：持有 manager 而不是 session_factory——后者要等 lifespan 里 init() 才有值。"""

    def __init__(self, mysql_manager) -> None:
        self.mysql_manager = mysql_manager
        self._cache: OrderedDict[tuple[int, int], DataSource] = OrderedDict()

    async def get(self, user_id: int, dataset_id: int) -> DataSource:
        """按“数据集”取数据源：数据集决定查哪个源、哪些表。"""
        factory = self.mysql_manager.session_factory
        if factory is None:
            raise RuntimeError("MySQL 尚未初始化")

        async with factory() as session:
            dataset = await DatasetRepository(session).get(user_id, dataset_id)
            if dataset is None:
                raise NotFoundError("数据集不存在")
            datasource_id = dataset.datasource_id or 0
            row = await DataSourceRepository(session).get(user_id, datasource_id)
            if row is None:
                raise NotFoundError("数据源不存在")
            kind = row.kind
            config = DataSourceRepository.read_config(row)

        key = (user_id, datasource_id)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        source: DataSource
        if kind == "csv":
            source = CSVDataSource(factory, user_id, datasource_id, dataset_id)
        elif kind == "mysql":
            source = MySQLDataSource(datasource_id, config)
        else:
            raise ValueError(f"不支持的数据源类型：{kind}")

        self._cache[key] = source
        if len(self._cache) > MAX_CACHED_SOURCES:
            _, evicted = self._cache.popitem(last=False)
            engine = getattr(evicted, "engine", None)
            if engine is not None:
                await engine.dispose()
        return source
