# ACM certificate for the ALB's HTTPS listener.
#
# DNS-validated. Cloudflare hosts the zone, so the operator manually adds
# the validation CNAME — the ACM record outputs are emitted for that purpose.
#
# Domain per env (matches manifest.json APP_DOMAIN):
#   - production: app.madeithomeapp.com
#   - staging:    staging-app.madeithomeapp.com

locals {
  app_domain = var.environment_name == "production" ? "app.madeithomeapp.com" : "staging-app.madeithomeapp.com"
}

resource "aws_acm_certificate" "app" {
  domain_name       = local.app_domain
  validation_method = "DNS"

  # Subject Alternative Names (e.g., apex `madeithomeapp.com`) can be
  # added here. Out of scope today — current deploy is subdomain-only.

  lifecycle {
    # Cert rotation: the new cert must be issued + validated + attached
    # to the ALB BEFORE the old cert is deleted, or HTTPS breaks during
    # the swap. create_before_destroy enforces that ordering.
    create_before_destroy = true
  }

  tags = {
    Name = "${local.name_prefix}-cert-${local.env}"
  }
}

# The ALB listener CANNOT reference an unvalidated cert — ELBv2 rejects
# `CreateListener` with UnsupportedCertificate while the cert is still
# in PENDING_VALIDATION. So apply must block until the operator adds
# the validation CNAME to Cloudflare.
#
# This is fine for the staging/production bootstrap (one-time, operator
# is at the console); it would NOT be appropriate in unattended CI, but
# this stack isn't applied by CI. CD deploys app code, never TF.
#
# Validation polls with a 45-min timeout — enough for Cloudflare DNS
# propagation and ACM's polling cycle.
resource "aws_acm_certificate_validation" "app" {
  certificate_arn = aws_acm_certificate.app.arn

  timeouts {
    create = "45m"
  }
}
