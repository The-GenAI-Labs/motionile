local count = redis.call("ZCARD", KEYS[1])
-- explain the count
return count
