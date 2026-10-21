# Application Load Balancer for the web service.
#
# Internet-facing, multi-AZ across the two public subnets, HTTPS listener
# only (port 80 redirects to 443). Idle connection timeout follows the
# default 60s.

resource "aws_lb" "web" {
  name               = "${local.name_prefix}-alb-${local.env}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  # 60s idle timeout. Fine for normal request/response; if a future
  # endpoint streams or holds connections > 60s (long-polling, SSE,
  # large uploads bottlenecked on backend processing), bump this so
  # the client doesn't see spurious 502s.
  idle_timeout = 60

  # Deletion protection in production; staging stays nimble.
  enable_deletion_protection = var.environment_name == "production"

  tags = {
    Name = "${local.name_prefix}-alb-${local.env}"
  }
}

# --- Target group --------------------------------------------------------
# Targets are ECS Fargate tasks (IP-mode required for Fargate).
resource "aws_lb_target_group" "web" {
  name        = "${local.name_prefix}-web-${local.env}"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  # 60s deregistration: enough for the slower handlers (Stripe checkout
  # redirect, photo uploads) to complete during a rolling deploy.
  deregistration_delay = 60

  tags = {
    Name = "${local.name_prefix}-web-${local.env}"
  }
}

# --- HTTPS listener ------------------------------------------------------
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.web.arn
  port              = 443
  protocol          = "HTTPS"
  # Modern TLS only — TLS 1.2+ with strong ciphers.
  ssl_policy = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  # Reference the validation result rather than the cert directly, so
  # CreateListener doesn't race ACM's PENDING_VALIDATION → ISSUED
  # transition. ELBv2 rejects an unvalidated cert with
  # UnsupportedCertificate.
  certificate_arn = aws_acm_certificate_validation.app.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

# --- HTTP → HTTPS redirect ----------------------------------------------
resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.web.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
