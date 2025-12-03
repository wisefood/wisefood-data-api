import os
import redis

from exceptions import (
    BadGatewayError,
)
import logging
import json


class RedisClient:
    _pools = {}

    @classmethod
    def _initialize_redis(cls, db: int):
        host = os.getenv("REDIS_HOST", "redis")
        port = int(os.getenv("REDIS_PORT", 6379))
        pool = redis.ConnectionPool(
            host=host,
            port=port,
            db=db,
            decode_responses=True,
            max_connections=10,
        )
        cls._pools[db] = pool
        logging.info("Initialized Redis connection pool for db %s", db)
        return pool

    def _get_pool(self, db: int):
        pool = self._pools.get(db)
        if pool is None:
            pool = self._initialize_redis(db)
        return pool

    def set(self, key, value, db: int | None = None):
        """Set a value in Redis using a connection from the pool."""
        try:
            db_to_use = db if db is not None else int(os.getenv("REDIS_DB", 1))
            conn = redis.Redis(connection_pool=self._get_pool(db_to_use))
            if isinstance(value, dict):
                conn.set(key, json.dumps(value))  # Serialize dict to JSON string
            else:
                conn.set(key, value)
        except Exception as e:
            raise BadGatewayError(e)

    def get(self, key, db: int | None = None):
        """Get a value from Redis using a connection from the pool."""
        try:
            db_to_use = db if db is not None else int(os.getenv("REDIS_DB", 1))
            conn = redis.Redis(connection_pool=self._get_pool(db_to_use))
            value = conn.get(key)
            try:
                return json.loads(value)  # Attempt to deserialize JSON string
            except (TypeError, json.JSONDecodeError):
                return value  # Return as-is if not JSON
        except Exception as e:
            raise BadGatewayError(e)

    def delete(self, key, db: int | None = None):
        """Delete a value from Redis using a connection from the pool."""
        try:
            db_to_use = db if db is not None else int(os.getenv("REDIS_DB", 1))
            conn = redis.Redis(connection_pool=self._get_pool(db_to_use))
            conn.delete(key)
        except Exception as e:
            raise BadGatewayError(e)

    def lpush(self, key, value, db: int | None = None):
        """Push a value to the left of a Redis list."""
        try:
            db_to_use = db if db is not None else int(os.getenv("REDIS_DB", 1))
            conn = redis.Redis(connection_pool=self._get_pool(db_to_use))
            if isinstance(value, dict):
                value = json.dumps(value)
            conn.lpush(key, value)
        except Exception as e:
            raise BadGatewayError(e)

    def brpop(self, key, timeout=0, db: int | None = None):
        """Blocking pop from the right of a Redis list."""
        try:
            db_to_use = db if db is not None else int(os.getenv("REDIS_DB", 1))
            conn = redis.Redis(connection_pool=self._get_pool(db_to_use))
            return conn.brpop(key, timeout=timeout)
        except Exception as e:
            raise BadGatewayError(e)

    def expire(self, key, ttl_seconds: int, db: int | None = None):
        """Set an expiration on a key."""
        try:
            db_to_use = db if db is not None else int(os.getenv("REDIS_DB", 1))
            conn = redis.Redis(connection_pool=self._get_pool(db_to_use))
            conn.expire(key, ttl_seconds)
        except Exception as e:
            raise BadGatewayError(e)


# Create a singleton instance of RedisClient
REDIS = RedisClient()
