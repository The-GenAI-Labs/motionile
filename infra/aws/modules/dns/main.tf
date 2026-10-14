resource "aws_route53_record" "this" {
  for_each = var.enabled ? var.records : {}

  zone_id         = var.zone_id
  name            = each.value.name
  type            = each.value.type
  ttl             = var.ttl_seconds
  records         = [each.value.value]
  allow_overwrite = false

  lifecycle {
    precondition {
      condition     = var.zone_id != null
      error_message = "Set route53_zone_id when manage_dns is true."
    }
  }
}
