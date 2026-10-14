locals {
  url      = "https://example.com/#anchor"
  pattern  = "a // b /* c */"
  nested   = "${var.mode == "x#y" ? "a//b" : "c"}"
  policy   = <<-EOT
    # not a comment inside a heredoc
    // still data
  EOT
  after    = { key = "value" }
}
