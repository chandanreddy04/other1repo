# Security groups for the web service plane.
#
# Three SGs:
#   - alb: 443 in from internet
#   - web_task: 8000 in from alb only (public IPs but no internet ingress)
#   - rds (declared in rds.tf): 5432 in from web_task — added below via a
#     separate aws_security_group_rule resource so the two SGs don't have
#     a circular reference.

# --- ALB security group --------------------------------------------------
resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-alb-${local.env}"
  description = "Public ALB - HTTPS from internet"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-alb-${local.env}"
  }
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from internet"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

# Port 80 ingress used only to redirect to 443 — no app traffic.
resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from internet (redirected to 443)"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

# Egress: open. ALB needs to reach the task SG; restricting egress here
# adds complexity without much security benefit.
resource "aws_vpc_security_group_egress_rule" "alb_all" {
  security_group_id = aws_security_group.alb.id
  description       = "All egress (ALB to tasks + internet for ACM/health)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# --- Web task security group ---------------------------------------------
resource "aws_security_group" "web_task" {
  name        = "${local.name_prefix}-web-task-${local.env}"
  description = "Web Fargate tasks - 8000 from ALB only"
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${local.name_prefix}-web-task-${local.env}"
  }
}

# Only the ALB can reach the task port. Tasks may have public IPs (for
# outbound to Stripe/Twilio without NAT) but the SG rejects everything
# else inbound.
resource "aws_vpc_security_group_ingress_rule" "web_task_from_alb" {
  security_group_id            = aws_security_group.web_task.id
  description                  = "Container port from ALB"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_egress_rule" "web_task_all" {
  security_group_id = aws_security_group.web_task.id
  # Open egress is the ECS de facto default. The app needs to reach
  # Stripe + Twilio + AWS APIs on 443, plus RDS on 5432.
  # Tightening to specific destinations adds friction every time a new
  # third-party integration lands; we accept the trade-off here and
  # rely on outbound traffic being from trusted code in a private app.
  description = "All egress (RDS + Stripe + Twilio + AWS APIs + general)"
  ip_protocol = "-1"
  cidr_ipv4   = "0.0.0.0/0"
}

# --- RDS ingress from web task ------------------------------------------
# Declared here (not in rds.tf) so adding new task SGs in PR 11 stays a
# single-file edit without touching the data layer.
resource "aws_vpc_security_group_ingress_rule" "rds_from_web_task" {
  security_group_id            = aws_security_group.rds.id
  description                  = "Postgres from web tasks"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.web_task.id
}
