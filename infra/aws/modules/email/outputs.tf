output "identity_arn" {
  description = "ARN of the SES domain identity."
  value       = aws_sesv2_email_identity.domain.arn
}

output "configuration_set_name" {
  description = "Name of the configuration set the application sends with."
  value       = aws_sesv2_configuration_set.this.configuration_set_name
}

output "configuration_set_arn" {
  description = "ARN of the configuration set."
  value       = aws_sesv2_configuration_set.this.arn
}

output "feedback_topic_arn" {
  description = "SNS topic that receives bounces and complaints."
  value       = aws_sns_topic.feedback.arn
}

output "dns_records" {
  description = "DKIM, MAIL FROM and DMARC records for the sending domain, keyed by a stable label."
  value = merge(
    {
      for index in range(3) : "ses-dkim-${index + 1}" => {
        name  = "${aws_sesv2_email_identity.domain.dkim_signing_attributes[0].tokens[index]}._domainkey.${var.domain}"
        type  = "CNAME"
        value = "${aws_sesv2_email_identity.domain.dkim_signing_attributes[0].tokens[index]}.dkim.amazonses.com"
      }
    },
    {
      ses-mail-from-mx = {
        name  = local.mail_from_domain
        type  = "MX"
        value = "10 feedback-smtp.${data.aws_region.current.region}.amazonses.com"
      }
      ses-mail-from-spf = {
        name  = local.mail_from_domain
        type  = "TXT"
        value = "v=spf1 include:amazonses.com -all"
      }
      dmarc = {
        name  = "_dmarc.${var.domain}"
        type  = "TXT"
        value = "v=DMARC1; p=quarantine; adkim=s; aspf=s"
      }
    },
  )
}
