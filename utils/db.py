from __future__ import annotations
import asyncpg
import json


class MaybeAcquire:
    def __init__(self, connection, *, pool):
        self.connection = connection
        self.pool = pool
        self._cleanup = False

    async def __aenter__(self):
        if self.connection is None:
            self._cleanup = True
            self._connection = c = await self.pool.acquire()
            return c
        return self.connection

    async def __aexit__(self, *args):
        if self._cleanup:
            await self.pool.release(self._connection)


class Column:
    __slots__ = ("value",)

    def __init__(self, value: str):
        self.value = value

    def __repr__(self) -> str:
        return f"<Column {self.value}>"

    def __str__(self) -> str:
        return self.value


class TableMeta(type):
    def __new__(cls, name, parents, dct, **kwargs):
        columns = []
        try:
            table_name = kwargs["table_name"]
        except KeyError:
            table_name = name.lower()

        dct["__tablename__"] = table_name
        for elem, value in dct.items():
            if isinstance(value, Column):
                columns.append(value)
        dct["columns"] = columns
        return super().__new__(cls, name, parents, dct)

    def __init__(self, name, parents, dct, **kwargs):
        super().__init__(name, parents, dct)


class Table(metaclass=TableMeta):  # type: ignore
    _pool: asyncpg.Pool
    __tablename__: str
    columns: list[Column]

    @classmethod
    async def create_pool(cls, uri, **kwargs) -> asyncpg.Pool:
        def _encode_jsonb(value: str):
            return json.dumps(value)

        def _decord_jsonb(value: str):
            return json.loads(value)

        old_init = kwargs.pop('init', None)

        kwargs.update({
            'command_timeout': 60,
            'max_size': 15,
            'min_size': 15,
        })

        async def init(con):
            await con.set_type_codec(
                "jsonb", schema="pg_catalog", encoder=_encode_jsonb, decoder=_decord_jsonb, format="text"
            )
            if old_init is not None:
                await old_init(con)

        cls._pool = pool = await asyncpg.create_pool(uri, init=init, **kwargs)
        return pool

    @classmethod
    def create_table(cls, *, exists_ok=True) -> str:
        statements = []
        builder = ["CREATE TABLE"]

        if exists_ok:
            builder.append("IF NOT EXISTS")

        builder.append(cls.__tablename__)
        column_creations = []
        for col in cls.columns:
            column_creations.append(col.value)
        builder.append('(%s)' % ', '.join(column_creations))
        statements.append(' '.join(builder) + ";")

        return '\n'.join(statements)

    @classmethod
    async def create(cls, *, connection=None):
        async with MaybeAcquire(connection, pool=cls._pool) as conn:
            await conn.execute(cls.create_table())

    @classmethod
    def all_tables(cls):
        return cls.__subclasses__()
