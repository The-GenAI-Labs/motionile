local count = redis.call("ZCARD", KEYS[1])
local label = "--not-a-comment"
return {count, label}
