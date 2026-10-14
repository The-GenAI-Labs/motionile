variable "enabled" {
  description = "Create the records in Route 53. When false, the environment only outputs them for an external DNS provider."
  type        = bool
  default     = false
}

variable "zone_id" {
  description = "Route 53 hosted zone that owns the domain. Required when enabled."
  type        = string
  default     = null
}

variable "records" {
  description = "Records to create, keyed by a stable label."
  type = map(object({
    name  = string
    type  = string
    value = string
  }))
}

variable "ttl_seconds" {
  description = "TTL of every record."
  type        = number
  default     = 300
}
