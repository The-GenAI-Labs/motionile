resource "aws_acm_certificate" "cdn" {
  provider = aws.us_east_1

  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "cdn" {
  count    = var.enabled ? 1 : 0
  provider = aws.us_east_1

  certificate_arn = aws_acm_certificate.cdn.arn
}

resource "aws_cloudfront_public_key" "signing" {
  for_each = var.public_keys

  name        = "${var.name}-signing-${each.key}"
  comment     = "Verifies Motionile signed cookies and URLs (${each.key})"
  encoded_key = trimspace(each.value)
}

resource "aws_cloudfront_key_group" "signing" {
  name    = "${var.name}-signing"
  comment = "Keys trusted for /media and /share"
  items   = [for label in sort(keys(var.public_keys)) : aws_cloudfront_public_key.signing[label].id]

  lifecycle {
    precondition {
      condition     = contains(keys(var.public_keys), var.active_public_key)
      error_message = "active_public_key must be one of the labels in public_keys."
    }
  }
}

resource "aws_cloudfront_origin_access_control" "media" {
  name                              = "${var.name}-media"
  description                       = "Signed requests from CloudFront to the media bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_cache_policy" "path_only" {
  name        = "${var.name}-path-only"
  comment     = "Cache key is the path only"
  default_ttl = var.default_ttl_seconds
  min_ttl     = 0
  max_ttl     = 31536000

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_brotli = false
    enable_accept_encoding_gzip   = false

    cookies_config {
      cookie_behavior = "none"
    }

    headers_config {
      header_behavior = "none"
    }

    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

resource "aws_cloudfront_response_headers_policy" "media" {
  name    = "${var.name}-media"
  comment = "CORS for the web origin plus nosniff and HSTS"

  cors_config {
    access_control_allow_credentials = true
    access_control_max_age_sec       = 3000
    origin_override                  = true

    access_control_allow_headers {
      items = ["Range", "Content-Type"]
    }

    access_control_allow_methods {
      items = ["GET", "HEAD", "OPTIONS"]
    }

    access_control_allow_origins {
      items = [var.web_origin]
    }

    access_control_expose_headers {
      items = ["Accept-Ranges", "Content-Length", "Content-Range", "ETag"]
    }
  }

  security_headers_config {
    content_type_options {
      override = true
    }

    strict_transport_security {
      access_control_max_age_sec = 63072000
      include_subdomains         = true
      preload                    = true
      override                   = true
    }
  }
}

resource "aws_cloudfront_function" "deny" {
  name    = "${var.name}-deny"
  runtime = "cloudfront-js-2.0"
  comment = "Rejects every path outside /media and /share"
  publish = true
  code    = <<-EOT
    function handler(event) {
      return { statusCode: 403, statusDescription: "Forbidden" };
    }
  EOT
}

resource "aws_cloudfront_distribution" "this" {
  count = var.enabled ? 1 : 0

  enabled         = true
  is_ipv6_enabled = true
  comment         = "${var.name} media"
  aliases         = [var.domain_name]
  http_version    = "http2and3"
  price_class     = var.price_class
  web_acl_id      = var.web_acl_arn

  origin {
    origin_id                = "media"
    domain_name              = var.media_bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.media.id
  }

  default_cache_behavior {
    target_origin_id           = "media"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.path_only.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.media.id
    compress                   = false

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.deny.arn
    }
  }

  ordered_cache_behavior {
    path_pattern               = "/media/*"
    target_origin_id           = "media"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.path_only.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.media.id
    trusted_key_groups         = [aws_cloudfront_key_group.signing.id]
    compress                   = false
  }

  ordered_cache_behavior {
    path_pattern               = "/share/*"
    target_origin_id           = "media"
    viewer_protocol_policy     = "https-only"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.path_only.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.media.id
    trusted_key_groups         = [aws_cloudfront_key_group.signing.id]
    compress                   = false
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.cdn[0].certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

resource "aws_cloudwatch_log_delivery_source" "access_logs" {
  count    = var.enabled ? 1 : 0
  provider = aws.us_east_1

  name         = "${var.name}-cdn-access"
  log_type     = "ACCESS_LOGS"
  resource_arn = aws_cloudfront_distribution.this[0].arn
}

resource "aws_cloudwatch_log_delivery_destination" "access_logs" {
  count    = var.enabled ? 1 : 0
  provider = aws.us_east_1

  name          = "${var.name}-cdn-access-s3"
  output_format = "json"

  delivery_destination_configuration {
    destination_resource_arn = "${var.log_bucket_arn}/cloudfront"
  }
}

resource "aws_cloudwatch_log_delivery" "access_logs" {
  count    = var.enabled ? 1 : 0
  provider = aws.us_east_1

  delivery_source_name     = aws_cloudwatch_log_delivery_source.access_logs[0].name
  delivery_destination_arn = aws_cloudwatch_log_delivery_destination.access_logs[0].arn

  s3_delivery_configuration {
    suffix_path = "/{yyyy}/{MM}/{dd}"
  }
}
