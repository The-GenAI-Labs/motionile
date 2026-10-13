local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local member = ARGV[1]
local allowed = 1
local used = {}
local resets = {}

for index = 1, #KEYS do
  local key = KEYS[index]
  local limit = tonumber(ARGV[index * 2])
  local window = tonumber(ARGV[index * 2 + 1])
  redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
  local count = redis.call('ZCARD', key)
  local reset = window
  if count > 0 then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    reset = tonumber(oldest[2]) + window - now
  end
  if count >= limit then
    allowed = 0
  end
  used[index] = count
  resets[index] = reset
end

local response = {allowed}
for index = 1, #KEYS do
  local key = KEYS[index]
  local limit = tonumber(ARGV[index * 2])
  local window = tonumber(ARGV[index * 2 + 1])
  local count = used[index]
  local reset = resets[index]
  if allowed == 1 then
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, window)
    count = count + 1
    if count == 1 then
      reset = window
    end
  end
  local remaining = limit - count
  if remaining < 0 then
    remaining = 0
  end
  table.insert(response, remaining)
  table.insert(response, reset)
end

return response
