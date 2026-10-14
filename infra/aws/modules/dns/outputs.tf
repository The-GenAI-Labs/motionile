output "managed_record_fqdns" {
  description = "Fully qualified names of the records Route 53 manages."
  value       = [for record in aws_route53_record.this : record.fqdn]
}
